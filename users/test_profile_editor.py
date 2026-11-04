"""Profile editor regressions use only disposable accounts and image files."""
from pathlib import Path
from tempfile import TemporaryDirectory
from django.test import TestCase, override_settings
from django.urls import reverse
from .forms import UserUpdateForm
from .models import User
from .test_profile_photos import picture


class ProfileEditorTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        setting = override_settings(MEDIA_ROOT=root/'media', CARD_PRIVATE_ROOT=root/'private/cards')
        setting.enable(); self.addCleanup(setting.disable)
        self.member = User.objects.create(username='editor-member',is_approved=True,qr_code='unused.png',photo=picture())
        self.staff = User.objects.create(username='editor-staff',role='worker',is_approved=True,qr_code='unused.png')
        self.manager = User.objects.create(username='editor-manager',is_superuser=True,is_staff=True,qr_code='unused.png')

    def data(self):
        form = UserUpdateForm(instance=self.member)
        return {name:form[name].value() for name in form.fields if name!='photo' and form[name].value() is not None}

    def test_all_editable_fields_are_available_in_each_editor(self):
        for actor,target,route in [(self.member,self.member,'profile_edit'),(self.staff,self.staff,'profile_edit'),(self.manager,self.member,'admin_edit_user'),(self.manager,self.staff,'admin_edit_user')]:
            with self.subTest(actor=actor.username,route=route):
                self.client.force_login(actor)
                response = self.client.get(reverse(route,args=[target.pk] if route=='admin_edit_user' else []))
                self.assertEqual(response.status_code,200)
                for name in response.context['form'].fields:
                    self.assertContains(response,'name="'+name+'"')
                if target.role=='worker': self.assertNotContains(response,'name="faculty"')

    def test_upload_widget_keeps_native_clear_control_without_raw_file_link(self):
        html = str(UserUpdateForm(instance=self.member)['photo'])
        self.assertIn('name="photo"',html)
        self.assertIn('name="photo-clear"',html)
        self.assertIn('accept="image/jpeg,image/png,image/webp"',html)
        self.assertNotIn(self.member.photo.name,html)
        self.assertNotIn('href=',html)

    def test_invalid_form_keeps_clear_selection_without_deleting_photo(self):
        self.client.force_login(self.member)
        previous = self.member.photo.name
        response = self.client.post(reverse('profile_edit'),{**self.data(),'photo-clear':'on','birth_date':'2999-01-01'})
        self.assertEqual(response.status_code,200)
        self.assertIn('birth_date',response.context['form'].errors)
        self.assertIn('checked',str(response.context['form']['photo']))
        self.member.refresh_from_db()
        self.assertEqual(self.member.photo.name,previous)
        self.assertTrue(Path(self.member.photo.path).is_file())

    def test_simultaneous_upload_and_clear_is_visible_and_does_not_lose_photo(self):
        self.client.force_login(self.member)
        previous = self.member.photo.name
        response = self.client.post(reverse('profile_edit'),{**self.data(),'photo-clear':'on','photo':picture('replacement.png',color='blue')})
        self.assertEqual(response.status_code,200)
        self.assertIn('photo',response.context['form'].errors)
        self.assertContains(response,'href="#id_photo"')
        self.member.refresh_from_db(); self.assertEqual(self.member.photo.name,previous)
