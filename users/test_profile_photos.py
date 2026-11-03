from collections import namedtuple
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from events.models import Event, EventPhoto
from .models import User, JournalEntry
from .forms import UserUpdateForm, AdminUpdateForm
from .avatars import roots, UPLOAD_SECTION


def picture(name='source.png', size=(24,16), color='red', exif=None):
    stream=BytesIO();image=Image.new('RGB',size,color)
    image.save(stream,format='JPEG' if exif else 'PNG',**({'exif':exif} if exif else {}))
    return SimpleUploadedFile(name,stream.getvalue(),content_type='image/jpeg' if exif else 'image/png')


class ProfilePhotoTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.override=override_settings(MEDIA_ROOT=root/'media',CARD_PRIVATE_ROOT=root/'private/cards')
        self.override.enable();self.addCleanup(self.override.disable)
        self.person=User.objects.create(username='photo-member',is_approved=True,qr_code='unused.png')
        self.staff=User.objects.create(username='photo-staff',role='worker',is_approved=True,qr_code='unused.png')

    def data(self,person=None):
        form=UserUpdateForm(instance=person or self.person)
        return {key:form[key].value() for key in form.fields if key!='photo' and form[key].value() is not None}

    def upload(self,photo=None):
        form=UserUpdateForm(self.data(),{'photo':photo or picture()},instance=self.person)
        self.assertTrue(form.is_valid(),form.errors)
        with self.captureOnCommitCallbacks(execute=True):form.save()
        self.person.refresh_from_db()
        return Path(self.person.photo.path)

    def test_new_photo_is_bounded_jpeg_and_strips_metadata(self):
        exif=Image.Exif();exif[274]=6;exif[315]='private-synthetic-marker'
        path=self.upload(picture('private-name.jpg',exif=exif))
        self.assertNotIn('private-name',path.name)
        with Image.open(path) as image:
            self.assertEqual(image.format,'JPEG');self.assertEqual(image.size,(16,24))
            self.assertFalse(image.getexif());self.assertLessEqual(max(image.size),1600)
        self.assertLessEqual(path.stat().st_size,1024*1024)
        self.assertEqual(JournalEntry.objects.filter(section=UPLOAD_SECTION,object_id=str(self.person.pk)).count(),1)

    def test_file_size_format_and_dimension_limits(self):
        large=picture();large.file.seek(0,2);large.file.write(b'\0'*(6*1024*1024));large.size=large.file.tell();large.seek(0)
        for upload in [large,picture('animated.gif'),picture(size=(5001,4000))]:
            with self.subTest(name=upload.name,size=upload.size):
                form=UserUpdateForm(self.data(),{'photo':upload},instance=self.person)
                self.assertFalse(form.is_valid());self.assertIn('photo',form.errors)
        self.assertFalse(self.person.photo and self.person.photo._committed)

    def test_model_save_cannot_bypass_validation(self):
        self.person.photo=SimpleUploadedFile('bad.jpg',b'not an image')
        with self.assertRaises(ValidationError):self.person.save()
        self.person.refresh_from_db();self.assertFalse(self.person.photo)

    def test_admin_form_uses_the_same_limits(self):
        form=AdminUpdateForm({'username':self.person.username,'role':'volunteer'},
            {'photo':picture('bad.gif')},instance=self.person,actor=self.staff)
        self.assertFalse(form.is_valid());self.assertIn('photo',form.errors)

    def test_replacing_photo_archives_bytes_and_can_restore(self):
        old=self.upload();original=old.read_bytes()
        new=self.upload(picture(color='blue'))
        self.assertTrue(new.exists());self.assertFalse(old.exists())
        public,private=roots();record=next((private/str(self.person.pk)).glob('*.json'))
        metadata=json.loads(record.read_text());self.assertEqual((record.parent/metadata['file']).read_bytes(),original)
        call_command('archive_profile_photos',restore=record.stem,apply=True,stdout=StringIO())
        self.assertEqual(old.read_bytes(),original);self.assertTrue(new.exists())

    def test_other_model_reference_retains_old_file(self):
        old=self.upload()
        event=Event.objects.create(title='Photo reference',start_time=timezone.now(),end_time=timezone.now())
        EventPhoto.objects.create(event=event,image=self.person.photo.name)
        self.upload(picture(color='green'))
        self.assertTrue(old.exists())

    def test_rollback_does_not_archive_still_current_photo(self):
        old=self.upload()
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.person.photo=picture(color='yellow');self.person.save()
                raise RuntimeError('synthetic rollback')
        self.person.refresh_from_db()
        self.assertEqual(Path(self.person.photo.path),old);self.assertTrue(old.exists())

    def test_hourly_and_daily_limits_do_not_change_current_photo(self):
        old=self.upload()
        for limits in [{'PROFILE_PHOTO_HOURLY_LIMIT':1},{'PROFILE_PHOTO_DAILY_LIMIT':1}]:
            with self.subTest(limits=limits),override_settings(**limits):
                form=UserUpdateForm(self.data(),{'photo':picture(color='blue')},instance=self.person)
                self.assertFalse(form.is_valid());self.assertIn('photo',form.errors)
        self.person.refresh_from_db();self.assertEqual(Path(self.person.photo.path),old)

    def test_quota_and_low_space_return_field_errors(self):
        for limits in [{'PROFILE_PHOTO_ACCOUNT_BYTES':1},{'PROFILE_PHOTO_TOTAL_BYTES':1}]:
            with self.subTest(limits=limits),override_settings(**limits):
                form=UserUpdateForm(self.data(),{'photo':picture()},instance=self.person)
                self.assertFalse(form.is_valid());self.assertIn('photo',form.errors)
        usage=namedtuple('usage','total used free')
        with patch('users.avatars.shutil.disk_usage',return_value=usage(100,99,1)):
            form=UserUpdateForm(self.data(),{'photo':picture()},instance=self.person)
            self.assertFalse(form.is_valid());self.assertIn('photo',form.errors)

    def test_clear_photo_archives_after_successful_save(self):
        old=self.upload()
        form=UserUpdateForm({**self.data(),'photo-clear':'on'},instance=self.person)
        self.assertTrue(form.is_valid(),form.errors)
        with self.captureOnCommitCallbacks(execute=True):form.save()
        self.person.refresh_from_db();self.assertFalse(self.person.photo);self.assertFalse(old.exists())

    def test_legacy_current_photo_counts_towards_account_quota(self):
        public=Path(self.tmp.name)/'media/profile_photos';public.mkdir(parents=True)
        legacy=public/'old-name.png';legacy.write_bytes(b'x'*4096)
        User.objects.filter(pk=self.person.pk).update(photo='profile_photos/old-name.png')
        self.person.refresh_from_db()
        with override_settings(PROFILE_PHOTO_ACCOUNT_BYTES=4096):
            form=UserUpdateForm(self.data(),{'photo':picture()},instance=self.person)
            self.assertFalse(form.is_valid());self.assertIn('photo',form.errors)
        self.assertTrue(legacy.exists())

    def test_old_photo_is_not_rewritten_when_editing_birth_date(self):
        old=self.upload();before=old.read_bytes()
        form=UserUpdateForm({**self.data(),'birth_date':'2001-02-03'},instance=self.person)
        self.assertTrue(form.is_valid(),form.errors);form.save()
        self.person.refresh_from_db();self.assertEqual(old.read_bytes(),before)
        self.assertEqual(self.person.birth_date.isoformat(),'2001-02-03')

    def test_cleanup_dry_run_and_apply_preserve_referenced_files(self):
        current=self.upload();unused=current.parent/'legacy-unused.png';unused.write_bytes(b'original bytes retained')
        output=StringIO();call_command('archive_profile_photos',stdout=output)
        self.assertEqual(json.loads(output.getvalue())['unreferenced_files'],1);self.assertTrue(unused.exists())
        output=StringIO();call_command('archive_profile_photos',apply=True,stdout=output)
        self.assertEqual(json.loads(output.getvalue())['archived'],1)
        self.assertTrue(current.exists());self.assertFalse(unused.exists())

    def test_symlink_or_public_archive_is_rejected(self):
        self.upload();public,private=roots()
        with override_settings(PROFILE_PHOTO_ARCHIVE_ROOT=public/'unsafe'):
            with self.assertRaises(ValidationError):roots()
        outside=Path(self.tmp.name)/'external';outside.write_bytes(b'keep')
        link=public/'escape'
        try:link.symlink_to(outside)
        except OSError:self.skipTest('Creating links requires platform privileges')
        with self.assertRaises(Exception):call_command('archive_profile_photos',apply=True,stdout=StringIO())
        self.assertEqual(outside.read_bytes(),b'keep')

    def test_restore_rejects_bad_id_and_tampered_content(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):call_command('archive_profile_photos',restore='../bad',apply=True,stdout=StringIO())
        self.upload();self.upload(picture(color='blue'))
        record=next((roots()[1]/str(self.person.pk)).glob('*.json'));data=json.loads(record.read_text())
        (record.parent/data['file']).write_bytes(b'changed')
        with self.assertRaises(CommandError):call_command('archive_profile_photos',restore=record.stem,apply=True,stdout=StringIO())

    def test_profile_save_validation_race_shows_error_instead_of_500(self):
        self.client.force_login(self.person)
        with patch.object(UserUpdateForm,'save',side_effect=ValidationError({'photo':'Synthetic storage limit'})):
            response=self.client.post(reverse('profile_edit'),self.data())
        self.assertContains(response,'Synthetic storage limit')
