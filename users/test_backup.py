"""Backup/restore checks against temporary files, never the deployed database."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tarfile
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from users.backup import create_snapshot, verify_snapshot, prune_snapshots, digest
from users.backup import git_metadata, MetadataTimeout


class BackupMetadataTests(TestCase):
    def test_temporary_metadata_timeout_is_retried_before_backup(self):
        import subprocess
        error=subprocess.TimeoutExpired(['git','status'],180)
        with patch('users.backup.subprocess.check_output',side_effect=[error,b'']) as git, patch('users.backup.time.sleep'):
            self.assertEqual(git_metadata(Path('/synthetic-aya'),'status'),'')
            self.assertEqual(git.call_count,2)

    def test_repeated_timeout_is_bounded_and_names_safe_operation(self):
        import subprocess
        error=subprocess.TimeoutExpired(['git','ls-files'],180)
        with patch('users.backup.subprocess.check_output',side_effect=error) as git, patch('users.backup.time.sleep'):
            with self.assertRaisesRegex(MetadataTimeout,'files.*Previous copies retained'):
                git_metadata(Path('/synthetic-aya'),'files')
            self.assertEqual(git.call_count,2)


class BackupTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base/'aya';self.root.mkdir()
        self.media = self.root/'media';self.media.mkdir()
        self.private = self.root/'private';self.private.mkdir()
        (self.media/'portrait.png').write_bytes(b'synthetic portrait')
        (self.private/'stamp.png').write_bytes(b'synthetic private stamp')
        (self.root/'manage.py').write_text('# synthetic code',encoding='utf-8')
        self.config=self.base/'aya.env';self.config.write_text('SYNTHETIC=fixture',encoding='utf-8')
        self.database=self.root/'db.sqlite3'
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('CREATE TABLE synthetic (id INTEGER PRIMARY KEY, value TEXT)')
            db.execute('INSERT INTO synthetic(value) VALUES (?)',('retained-value',))
            db.commit()
        self.destination=self.base/'backups'

    def backup(self, **kwargs):
        params=dict(root=self.root,database=self.database,media=self.media,private=self.private,
            destination=self.destination,code_files=['manage.py'],config_files=[('aya.env',self.config)],
            revision='synthetic-commit',runtime={'python':'synthetic'},keep=2)
        params.update(kwargs)
        return create_snapshot(**params)

    def test_restore_contains_exact_database_media_private_config_and_code(self):
        before=digest(self.database)
        folder=self.backup()
        self.assertEqual(digest(self.database),before)
        manifest=verify_snapshot(folder)
        self.assertTrue(manifest['verified'])
        with closing(sqlite3.connect(folder/'database.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT value FROM synthetic').fetchall(),[('retained-value',)])
        for archive,name,value in [('media.tar.gz','media/portrait.png',b'synthetic portrait'),
                                   ('private.tar.gz','private/stamp.png',b'synthetic private stamp'),
                                   ('config.tar.gz','aya.env',b'SYNTHETIC=fixture'),
                                   ('code.tar.gz','manage.py',b'# synthetic code')]:
            with tarfile.open(folder/archive) as file:
                self.assertEqual(file.extractfile(name).read(),value)
        self.assertFalse(list(folder.glob('.restore-check-*')))

    def test_live_wal_database_includes_committed_rows(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('INSERT INTO synthetic(value) VALUES (?)',('wal-value',));db.commit()
            folder=self.backup()
        with closing(sqlite3.connect(folder/'database.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM synthetic').fetchone()[0],2)

    def test_checksum_corruption_detected_and_existing_snapshots_retained(self):
        first=self.backup()
        (first/'media.tar.gz').write_bytes(b'corrupted')
        with self.assertRaises(ValueError):verify_snapshot(first)
        with self.assertRaises(ValueError):prune_snapshots(self.destination,2,first)
        self.assertTrue(first.exists())

    def test_retention_never_deletes_manual_or_partial_or_unmarked_folders(self):
        first=self.backup()
        # Stable age order independent of random suffix and test execution speed.
        old=self.destination/'aya-20200101T000000Z-12345678';first.rename(old)
        for name in ['before-manual','not-aya','.partial-aya-fixture','aya-20200102T000000Z-12345678']:
            path=self.destination/name;path.mkdir();(path/'retain').write_text('keep')
        second=self.backup();third=self.backup()
        self.assertFalse(old.exists())
        self.assertTrue(second.exists());self.assertTrue(third.exists())
        self.assertTrue((self.destination/'before-manual/retain').exists())
        self.assertTrue((self.destination/'aya-20200102T000000Z-12345678/retain').exists())

    def test_failed_verification_does_not_publish_or_prune(self):
        first=self.backup()
        with patch('users.backup.verify_snapshot',side_effect=ValueError('synthetic corruption')):
            with self.assertRaises(ValueError):self.backup()
        self.assertTrue(verify_snapshot(first)['verified'])
        self.assertEqual(len(list(self.destination.glob('aya-*'))),1)
        self.assertEqual(len(list(self.destination.glob('.partial-*'))),1)

    def test_database_outside_project_and_code_traversal_rejected(self):
        for params in [{'database':self.base/'outside.sqlite3'},
                       {'code_files':['../aya.env']},
                       {'destination':self.media/'backups'}, {'keep':0}]:
            with self.subTest(params=params),self.assertRaises(ValueError):self.backup(**params)

    def test_missing_private_directory_is_valid_and_not_created(self):
        (self.private/'stamp.png').unlink();self.private.rmdir()
        folder=self.backup()
        with tarfile.open(folder/'private.tar.gz') as file:self.assertEqual(file.getmembers(),[])
        self.assertFalse(self.private.exists())

    def test_symlink_escape_rejected(self):
        link=self.media/'external'
        try:link.symlink_to(self.config)
        except OSError:self.skipTest('Creating symlinks requires privileges on this platform')
        with self.assertRaises(ValueError):self.backup()
        self.assertEqual(self.config.read_text(),'SYNTHETIC=fixture')

    def test_archive_traversal_rejected_even_with_matching_checksum(self):
        import io
        folder=self.backup()
        archive=folder/'media.tar.gz'
        with tarfile.open(archive,'w:gz') as file:
            item=tarfile.TarInfo('../../outside');item.size=4
            file.addfile(item,io.BytesIO(b'evil'))
        manifest_file=folder/'manifest.json'
        manifest=json.loads(manifest_file.read_text())
        manifest['files'][archive.name]={'bytes':archive.stat().st_size,'sha256':digest(archive)}
        manifest_file.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):verify_snapshot(folder)
        self.assertFalse((self.destination/'outside').exists())

    def test_low_space_preserves_verified_copy_and_does_not_start_new_one(self):
        from collections import namedtuple
        first=self.backup()
        usage=namedtuple('usage','total used free')
        with patch('users.backup.shutil.disk_usage',return_value=usage(100,99,1)):
            with self.assertRaises(OSError):self.backup()
        self.assertTrue(verify_snapshot(first)['verified'])
        self.assertFalse(list(self.destination.glob('.partial-*')))
