import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from users.backup import create_snapshot, plain_path, verify_snapshot


class Command(BaseCommand):
    help = 'Create and verify a private AYA backup; never restores production data.'

    def add_arguments(self, parser):
        parser.add_argument('--destination', default='/home/deploy/aya-backups/daily')
        parser.add_argument('--keep', type=int, default=14)
        parser.add_argument('--verify', help='Verify an existing backup only')

    def handle(self, *args, **options):
        os.umask(0o077)
        if options['verify']:
            try:
                manifest = verify_snapshot(options['verify'])
            except Exception as error:
                raise CommandError('Backup verification failed: ' + type(error).__name__) from error
            self.stdout.write(json.dumps({'verified':True, 'commit':manifest['commit']}))
            return
        # Deliberately limited to this project/VPS. No database discovery or shared services.
        root = Path('/srv/aya')
        if Path(settings.BASE_DIR).resolve() != root or settings.DATABASES['default']['ENGINE'] != 'django.db.backends.sqlite3':
            raise CommandError('This backup command requires the AYA production SQLite project.')
        destination = plain_path(options['destination'])
        parent = Path('/home/deploy/aya-backups')
        if destination != parent / 'daily':
            raise CommandError('Scheduled backups must use the dedicated AYA daily directory.')
        private = plain_path(settings.CARD_PRIVATE_ROOT)
        if not private.is_relative_to(root / 'private'):
            raise CommandError('Unexpected private asset location; review the backup configuration.')
        import fcntl
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (destination / '.backup.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise CommandError('An AYA backup is already running.') from error
            try:
                def git(*arguments):
                    return subprocess.check_output(['git',*arguments],cwd=root,timeout=60).decode('utf-8')
                if git('status','--porcelain').strip():
                    raise ValueError('Commit project changes before backing up')
                files = [name for name in git('ls-files','-z').split('\0') if name]
                configs = [('aya.env', Path('/etc/aya.env')),
                           ('aya.service', Path('/etc/systemd/system/aya.service')),
                           ('settings_production.py', root / 'aya_platform/settings_production.py')]
                for name in ['aya-backup.service','aya-backup.timer']:
                    path = Path('/etc/systemd/system') / name
                    if path.exists():configs.append((name,path))
                runtime = {'python':platform.python_version(), 'packages':{
                    d.metadata['Name']:d.version for d in importlib.metadata.distributions()}}
                folder = create_snapshot(root=root, database=settings.DATABASES['default']['NAME'],
                    media=settings.MEDIA_ROOT, private=root/'private', destination=destination,
                    code_files=files, config_files=configs, revision=git('rev-parse','HEAD').strip(),
                    runtime=runtime, keep=options['keep'])
            except Exception as error:
                # Keep secrets and personal data out of systemd logs.
                raise CommandError('AYA backup failed ('+type(error).__name__+'). Previous verified copies were retained.') from error
        self.stdout.write(json.dumps({'verified':True,'path':str(folder),'keep':options['keep']}))
