"""QR regression checks: decode real PNGs and enforce existing profile visibility."""
from io import BytesIO, StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
import zxingcpp
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command, CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import JournalEntry, User
from .profile_qr import profile_url, png_for_profile


@override_settings(PUBLIC_SITE_URL='https://aya.test')
class ProfileQRTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        self.files = override_settings(MEDIA_ROOT=self.media.name)
        self.files.enable()
        self.addCleanup(self.files.disable)
        self.person = User.objects.create(username='qr-member', is_approved=True, qr_code='qr_codes/legacy.png')
        self.pending = User.objects.create(username='qr-pending', qr_code='qr_codes/pending.png')
        self.worker = User.objects.create(username='qr-worker', role='worker', is_approved=True, qr_code='qr_codes/worker.png')
        self.owner = User.objects.create(username='qr-owner', is_superuser=True, is_staff=True, qr_code='qr_codes/owner.png')

    def decode(self, content):
        with Image.open(BytesIO(content)) as image:
            result = zxingcpp.read_barcode(image.convert('RGB'))
        self.assertIsNotNone(result)
        self.assertEqual(result.format, zxingcpp.BarcodeFormat.QRCode)
        return result.text

    def test_png_decodes_to_canonical_profile_without_private_fields(self):
        self.person.phone='+992000000000';self.person.email='private-address@example.test'
        content = png_for_profile(self.person)
        self.assertEqual(self.decode(content), 'https://aya.test' + reverse('public_profile', args=[self.person.pk]))
        with Image.open(BytesIO(content)) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertGreaterEqual(image.width, 500)
            self.assertEqual(image.width, image.height)
            self.assertEqual(image.convert('RGB').getpixel((0,0)), (255,255,255))

    def test_small_print_and_rotated_code_are_readable(self):
        with Image.open(BytesIO(png_for_profile(self.person))) as image:
            for transformed in [image.resize((180,180), Image.Resampling.LANCZOS), image.rotate(90, expand=True)]:
                with self.subTest(size=transformed.size):
                    output=BytesIO();transformed.save(output,format='PNG')
                    self.assertEqual(self.decode(output.getvalue()), profile_url(self.person))

    def test_each_person_has_their_own_link_and_host_header_cannot_change_it(self):
        response=self.client.get(reverse('profile_qr',args=[self.person.pk]),HTTP_HOST='localhost')
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.decode(response.content),profile_url(self.person))
        other=self.client.get(reverse('profile_qr',args=[self.worker.pk]))
        self.assertNotEqual(self.decode(other.content),self.decode(response.content))

    def test_configured_origin_change_updates_download_without_stale_cache(self):
        before=self.decode(png_for_profile(self.person))
        with override_settings(PUBLIC_SITE_URL='https://new-aya.test/'):
            after=self.decode(png_for_profile(self.person))
        self.assertNotEqual(before,after)
        self.assertTrue(after.startswith('https://new-aya.test/profile/'))

    def test_bad_canonical_origins_are_rejected(self):
        for value in ['', 'http://aya.test', 'javascript:alert(1)', 'https://name:password@aya.test', 'https://aya.test/?next=evil', 'https://aya.test/path', 'https://aya.test/#part', 'https://aya.test:wrong']:
            with self.subTest(value=value), override_settings(PUBLIC_SITE_URL=value):
                with self.assertRaises(ImproperlyConfigured):png_for_profile(self.person)

    def test_view_and_download_do_not_modify_accounts_and_log_once(self):
        before=list(User.objects.values().order_by('pk'))
        url=reverse('profile_qr',args=[self.person.pk])
        for query,category in [({},'view'),({'download':'1'},'action')]:
            response=self.client.get(url,query)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Content-Type'],'image/png')
            self.assertEqual(response['Content-Disposition'].startswith('attachment'),bool(query))
            self.assertIn('no-store',response['Cache-Control'])
            self.assertEqual(self.decode(response.content),profile_url(self.person))
            entry=JournalEntry.objects.filter(section='profile_qr',category=category).get()
            self.assertTrue(entry.private)
            self.assertEqual(entry.subject_key,'users.User:'+str(self.person.pk))
        self.assertEqual(JournalEntry.objects.filter(section='profile_qr').count(),2)
        self.assertEqual(list(User.objects.values().order_by('pk')),before)

    def test_pending_and_hidden_profiles_cannot_be_exposed_through_qr(self):
        url=reverse('profile_qr',args=[self.pending.pk])
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.person)
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.pending)
        self.assertEqual(self.client.get(url).status_code,200)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(url).status_code,200)
        hidden=reverse('profile_qr',args=[self.owner.pk])
        for client in [Client(),self.client]:self.assertEqual(client.get(hidden).status_code,404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(hidden).status_code,404)

    def test_post_does_not_change_profile_or_award_any_access(self):
        before=User.objects.values().get(pk=self.person.pk)
        response=self.client.post(reverse('profile_qr',args=[self.person.pk]),{'role':'head_admin','is_superuser':'on','volunteer_access':'on'})
        self.assertEqual(response.status_code,405)
        self.assertEqual(User.objects.values().get(pk=self.person.pk),before)

    def test_profile_templates_offer_qr_and_download_for_volunteers_and_staff(self):
        for person in [self.person,self.worker]:
            response=self.client.get(reverse('public_profile',args=[person.pk]))
            self.assertContains(response,reverse('profile_qr',args=[person.pk])+'?download=1')
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('my_profile')),'class="profile-qr"')

    def test_new_registration_stores_readable_correct_qr_without_username_filename(self):
        person=User.objects.create(username='new-qr-account',is_approved=True)
        self.assertTrue(person.qr_code.name.endswith('profile-'+str(person.pk)+'.png'))
        self.assertNotIn(person.username,person.qr_code.name)
        with person.qr_code.open('rb') as file:self.assertEqual(self.decode(file.read()),profile_url(person))

    def write_legacy_files(self):
        root=Path(self.media.name)/'qr_codes';root.mkdir()
        for person in [self.person,self.pending,self.worker,self.owner]:
            (Path(self.media.name)/person.qr_code.name).write_bytes(b'old-qr-image')
        return root

    def refresh(self,apply=False):
        output=StringIO();call_command('refresh_profile_qr',**{'apply':apply,'stdout':output})
        return json.loads(output.getvalue())

    def test_bulk_refresh_dry_run_then_in_place_update_keeps_database_and_names(self):
        self.write_legacy_files();before=list(User.objects.values().order_by('pk'))
        preview=self.refresh()
        self.assertEqual(preview['refresh'],3)
        self.assertEqual((Path(self.media.name)/self.person.qr_code.name).read_bytes(),b'old-qr-image')
        self.assertEqual(self.refresh(True)['refresh'],3)
        self.assertEqual(self.refresh(True)['refresh'],0)
        for person in [self.person,self.pending,self.worker]:
            self.assertEqual(self.decode((Path(self.media.name)/person.qr_code.name).read_bytes()),profile_url(person))
        self.assertEqual((Path(self.media.name)/self.owner.qr_code.name).read_bytes(),b'old-qr-image')
        self.assertEqual(list(User.objects.values().order_by('pk')),before)

    def test_bulk_refresh_recreates_missing_file_without_touching_other_media(self):
        root=self.write_legacy_files();(root/'legacy.png').unlink()
        marker=Path(self.media.name)/'portrait.png';marker.write_bytes(b'portrait-unchanged')
        self.refresh(True)
        self.assertEqual(self.decode((root/'legacy.png').read_bytes()),profile_url(self.person))
        self.assertEqual(marker.read_bytes(),b'portrait-unchanged')

    def test_bulk_refresh_refuses_shared_or_outside_paths_before_any_write(self):
        root=self.write_legacy_files()
        for value in ['../outside.png','portrait.png','qr_codes/../portrait.png',self.person.qr_code.name]:
            with self.subTest(value=value):
                User.objects.filter(pk=self.worker.pk).update(qr_code=value)
                with self.assertRaises(CommandError):self.refresh(True)
                self.assertEqual((root/'legacy.png').read_bytes(),b'old-qr-image')

    def test_failed_bulk_write_restores_already_written_images(self):
        root=self.write_legacy_files()
        from .management.commands.refresh_profile_qr import replace_png
        count=0
        def fail_second(path,content,folder):
            nonlocal count
            count+=1
            if count==2:raise OSError('Synthetic write failure')
            return replace_png(path,content,folder)
        with patch('users.management.commands.refresh_profile_qr.replace_png',side_effect=fail_second):
            with self.assertRaises(CommandError):self.refresh(True)
        for path in root.iterdir():self.assertEqual(path.read_bytes(),b'old-qr-image')
