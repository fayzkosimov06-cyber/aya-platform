"""Private, verified SQLite snapshots. Never restores or changes the source DB."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from uuid import uuid4

FORMAT = 'aya-backup-v1'
SNAPSHOT_NAME = re.compile(r'aya-\d{8}T\d{6}Z-[0-9a-f]{8}\Z')


class MetadataTimeout(RuntimeError):
    pass


def git_metadata(root, operation):
    commands={'status':['status','--porcelain'], 'files':['ls-files','-z'],
              'revision':['rev-parse','HEAD']}
    arguments=commands[operation]
    for attempt in range(2):
        try:
            return subprocess.check_output(['git',*arguments],cwd=root,timeout=180).decode('utf-8')
        except subprocess.TimeoutExpired as error:
            if attempt:
                raise MetadataTimeout('AYA backup metadata timed out: '+operation+'. Previous copies retained.') from error
            time.sleep(1)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def plain_path(path):
    """Reject symlinks in the entire path, including destination ancestors."""
    path = Path(os.path.abspath(path))
    if path.resolve() != path or path.is_symlink():
        raise ValueError('Backup paths must not contain symlinks')
    return path


def archive_files(path, entries):
    with tarfile.open(path, 'w:gz', compresslevel=1, dereference=False) as archive:
        for name, source in entries:
            source = plain_path(source)
            if not source.is_file():
                raise ValueError('Only regular files can be archived')
            before = source.stat()
            archive.add(source, arcname=name, recursive=False)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise RuntimeError('A source file changed during backup; retry later')
    path.chmod(0o600)


def tree_files(root, prefix):
    root = plain_path(root)
    if root.exists():
        for path in sorted(root.rglob('*')):
            path = plain_path(path)
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError('Unsupported file in backup source')
            yield prefix + '/' + path.relative_to(root).as_posix(), path


def verify_snapshot(folder):
    folder = plain_path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != FORMAT or not manifest.get('files'):
        raise ValueError('Unsupported or incomplete backup')
    required = {'database.sqlite3', 'code.tar.gz', 'media.tar.gz', 'private.tar.gz', 'config.tar.gz', 'runtime.json'}
    if set(manifest['files']) != required:
        raise ValueError('Incomplete backup file set')
    for name, metadata in manifest['files'].items():
        path = plain_path(folder / name)
        if path.parent != folder or not path.is_file() or path.stat().st_size != metadata['bytes'] or digest(path) != metadata['sha256']:
            raise ValueError('Backup checksum mismatch')
    # Verify a separate restored database, never the source or the only backup.
    with tempfile.TemporaryDirectory(prefix='.restore-check-', dir=folder) as restored:
        restored = Path(restored)
        database = restored / 'database.sqlite3'
        shutil.copyfile(folder / 'database.sqlite3', database)
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
            if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('Restored database integrity failed')
        # Extract and read every archived file in a private temporary directory.
        for name in sorted(required - {'database.sqlite3', 'runtime.json'}):
            target = restored / name.removesuffix('.tar.gz')
            target.mkdir()
            with tarfile.open(folder / name, 'r:gz') as archive:
                seen = set()
                for member in archive:
                    relative = PurePosixPath(member.name)
                    if (not member.isfile() or relative.is_absolute() or '..' in relative.parts
                            or '\\' in member.name or ':' in member.name or member.name in seen):
                        raise ValueError('Unsafe archive entry')
                    seen.add(member.name)
                    output = target.joinpath(*relative.parts)
                    if not output.resolve().is_relative_to(target):
                        raise ValueError('Unsafe archive path')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as stream, output.open('xb') as file:
                        shutil.copyfileobj(stream, file)
                    if output.stat().st_size != member.size:
                        raise ValueError('Restored archive is incomplete')
    return manifest


def prune_snapshots(destination, keep, current):
    """Prune only verified, managed snapshots after a new successful backup."""
    destination = plain_path(destination)
    current = plain_path(current)
    if keep < 2 or current.parent != destination:
        raise ValueError('Invalid retention policy')
    verify_snapshot(current)
    snapshots = []
    for path in destination.iterdir():
        if not SNAPSHOT_NAME.fullmatch(path.name) or path.is_symlink() or not path.is_dir():
            continue
        try:
            manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if manifest.get('format') == FORMAT and manifest.get('verified') is True:
            snapshots.append(path)
    older = sorted((p for p in snapshots if p != current), key=lambda p: p.name, reverse=True)
    for path in older[keep - 1:]:
        # Recheck absolute boundary immediately before deletion. Never follow links.
        path = plain_path(path)
        if path.parent != destination or any(p.is_symlink() for p in path.rglob('*')):
            raise ValueError('Unsafe retention target')
        shutil.rmtree(path)


def create_snapshot(*, root, database, media, private, destination, code_files, config_files, revision, runtime, keep=14):
    root, database, media, private, destination = map(plain_path, (root, database, media, private, destination))
    if not root.is_dir() or not database.is_file() or not database.is_relative_to(root):
        raise ValueError('Invalid project database')
    if not media.is_relative_to(root) or not private.is_relative_to(root) or destination.is_relative_to(root):
        raise ValueError('Backups must be outside the project and its media')
    if not 2 <= keep <= 90:
        raise ValueError('Keep between 2 and 90 verified snapshots')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.chmod(0o700)
    # Allow room for both the archive and its restore check; stop before disk fills.
    entries = list(tree_files(media, 'media')) + list(tree_files(private, 'private'))
    code_entries = []
    for relative in code_files:
        path = plain_path(root / relative)
        if not path.is_relative_to(root):
            raise ValueError('Code path escapes project')
        code_entries.append((path.relative_to(root).as_posix(), path))
    configs = [(name, plain_path(path)) for name, path in config_files]
    required_bytes = 3 * (database.stat().st_size + sum(p.stat().st_size for _, p in entries + code_entries + configs))
    if shutil.disk_usage(destination).free < required_bytes + 512 * 1024 * 1024:
        raise OSError('Insufficient free space for a verified backup')
    name = 'aya-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
    folder = destination / ('.partial-' + name)
    folder.mkdir(mode=0o700)
    # An incomplete copy remains private and is never counted/pruned as a valid one.
    deadline = time.monotonic() + 300
    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            raise TimeoutError('Database snapshot timed out')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(folder / 'database.sqlite3')) as target:
            source.backup(target, pages=256, progress=progress, sleep=0.1)
    archive_files(folder / 'code.tar.gz', code_entries)
    archive_files(folder / 'media.tar.gz', ((n,p) for n,p in entries if n.startswith('media/')))
    archive_files(folder / 'private.tar.gz', ((n,p) for n,p in entries if n.startswith('private/')))
    archive_files(folder / 'config.tar.gz', configs)
    (folder / 'runtime.json').write_text(json.dumps(runtime, indent=2), encoding='utf-8')
    manifest = {'format':FORMAT, 'created_at':datetime.now(timezone.utc).isoformat(), 'commit':revision,
                'verified':False, 'database_source':str(database), 'files':{}}
    for path in folder.iterdir():
        path.chmod(0o600)
        manifest['files'][path.name] = {'bytes':path.stat().st_size, 'sha256':digest(path)}
    manifest_file = folder / 'manifest.json'
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    manifest_file.chmod(0o600)
    verify_snapshot(folder)
    manifest['verified'] = True
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    complete = destination / name
    folder.rename(complete)
    prune_snapshots(destination, keep, complete)
    return complete
