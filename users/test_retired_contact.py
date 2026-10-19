"""Retiring a contact must remove its surface without destroying existing records."""
from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .contact_activity import destination
from .forms import AdminUpdateForm, UserUpdateForm
from .journal import PRIVATE, snapshot
from .models import JournalEntry, User
from .readable_journal import Display


class RetiredContactTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member=User.objects.create(username='retired-contact-member',is_approved=True,
            linkedin='https://www.linkedin.com/in/synthetic-retired-contact/',linkedin_privacy='public',
            telegram='synthetic_member',instagram='@synthetic_member',qr_code='unused.png')
        cls.worker=User.objects.create(username='retired-contact-worker',role='worker',is_approved=True,
            linkedin='https://www.linkedin.com/in/synthetic-retired-worker/',qr_code='unused.png')
        cls.root=User.objects.create(username='retired-contact-root',is_superuser=True,is_staff=True,
            is_approved=True,qr_code='unused.png')

    def data(self,person,administrative=False):
        form=AdminUpdateForm(instance=person,actor=self.root) if administrative else UserUpdateForm(instance=person)
        return {name:form[name].value() for name in form.fields if name!='photo' and form[name].value() is not None}

    def test_retired_fields_absent_from_self_admin_staff_and_django_admin_forms(self):
        request=RequestFactory().get('/superadmin/');request.user=self.root
        for person in [self.member,self.worker]:
            forms=[UserUpdateForm(instance=person),AdminUpdateForm(instance=person,actor=self.root),
                admin.site._registry[User].get_form(request,obj=person)(instance=person)]
            for form in forms:
                self.assertNotIn('linkedin',form.fields)
                self.assertNotIn('linkedin_privacy',form.fields)

    def test_all_profile_and_editor_templates_omit_retired_contact(self):
        for person in [self.member,self.worker]:
            self.client.logout()
            for viewer in [None,self.member,self.root]:
                if viewer:self.client.force_login(viewer)
                response=self.client.get(reverse('public_profile',args=[person.pk]))
                self.assertEqual(response.status_code,200)
                self.assertNotIn('linkedin',response.content.decode().lower())
            self.client.force_login(person)
            for name in ['my_profile','profile_edit']:
                response=self.client.get(reverse(name))
                self.assertNotIn('linkedin',response.content.decode().lower())
            self.client.force_login(self.root)
            response=self.client.get(reverse('admin_edit_user',args=[person.pk]))
            self.assertNotIn('linkedin',response.content.decode().lower())

    def test_forged_post_cannot_change_retired_contact_or_its_privacy(self):
        before=(self.member.linkedin,self.member.linkedin_privacy)
        for administrative,actor in [(False,self.member),(True,self.root)]:
            self.client.force_login(actor)
            url=reverse('admin_edit_user',args=[self.member.pk]) if administrative else reverse('profile_edit')
            response=self.client.post(url,{**self.data(self.member,administrative),
                'first_name':'Updated','linkedin':'https://attacker.invalid/','linkedin_privacy':'private'})
            self.assertEqual(response.status_code,302)
            self.member.refresh_from_db()
            self.assertEqual((self.member.linkedin,self.member.linkedin_privacy),before)
            self.assertEqual(self.member.first_name,'Updated')

    def test_malformed_legacy_contact_never_blocks_profile_save(self):
        self.member.linkedin='legacy-not-a-valid-url';self.member.save()
        for administrative in [False,True]:
            form=AdminUpdateForm(self.data(self.member,True),instance=self.member,actor=self.root) if administrative else UserUpdateForm(self.data(self.member),instance=self.member)
            self.assertTrue(form.is_valid(),form.errors)
            self.assertNotIn('linkedin',form.legacy_social_fields)
            form.save()
        self.member.refresh_from_db();self.assertEqual(self.member.linkedin,'legacy-not-a-valid-url')

    def test_old_contact_endpoint_and_destination_are_disabled_for_every_viewer(self):
        self.assertEqual(destination(self.member,'linkedin'),'')
        for viewer in [None,self.member,self.root]:
            if viewer:self.client.force_login(viewer)
            response=self.client.get(reverse('open_contact',args=[self.member.pk,'linkedin']))
            self.assertEqual(response.status_code,404)
            self.assertNotIn('Location',response)
        self.assertFalse(JournalEntry.objects.filter(category='contact').exists())

    def test_telegram_and_instagram_keep_their_working_contact_routes(self):
        self.client.force_login(self.member)
        for network,url in [('telegram','https://t.me/synthetic_member'),('instagram','https://www.instagram.com/synthetic_member/')]:
            response=self.client.get(reverse('open_contact',args=[self.member.pk,network]))
            self.assertRedirects(response,url,fetch_redirect_response=False)

    def test_old_audit_labels_stay_private_but_new_snapshots_omit_retired_fields(self):
        state=snapshot(self.member)
        self.assertNotIn('linkedin',state)
        self.assertNotIn('linkedin_privacy',state)
        self.assertIn('linkedin',PRIVATE)
        self.assertEqual(Display(self.root).value('network','linkedin'),'LinkedIn')
