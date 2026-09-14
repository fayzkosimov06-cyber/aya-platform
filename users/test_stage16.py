from django import forms
from django.test import TestCase
from django.urls import reverse
from .models import User, AuditLog, PermissionOverride, Direction
from .control_views import RightsForm
from .forms import UserUpdateForm, AdminUpdateForm
from .profile_choices import filter_profiles, CITY_CHOICES


class ManagementRepairTests(TestCase):
    def setUp(self):
        self.root = User.objects.create(username='hidden-root', is_superuser=True, is_approved=True, qr_code='unused.png')
        self.president = User.objects.create(username='president', role='president', is_approved=True, qr_code='unused.png')
        self.member = User.objects.create(username='member', is_approved=True, qr_code='unused.png')

    def test_dashboard_with_deleted_author(self):
        AuditLog.objects.create(actor=None, action='Historical system action')
        self.client.force_login(self.president)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(response, 'Historical system action')
        self.assertContains(response, 'Система')
        self.assertNotContains(response, 'hidden-root')

    def test_partial_rights_submission_preserves_other_rights(self):
        PermissionOverride.objects.create(user=self.member, code='events_edit', enabled=True, scope='all')
        self.client.force_login(self.root)
        response = self.client.post(reverse('rights_manage'), {'targets':[self.member.pk], 'visits':'on'}, follow=True)
        self.assertContains(response, 'Права сохранены')
        self.assertTrue(PermissionOverride.objects.get(user=self.member, code='events_edit').enabled)
        self.assertTrue(PermissionOverride.objects.get(user=self.member, code='visits').enabled)
        self.assertEqual(PermissionOverride.objects.filter(user=self.member).count(), 2)

    def test_empty_scope_does_not_save(self):
        form = RightsForm({'targets':[self.member.pk], 'events_edit':'on', 'scope':'selected'}, actor=self.root)
        self.assertFalse(form.is_valid())
        self.assertIn('Выберите хотя бы одно направление', str(form.errors))

    def test_noop_does_not_report_success(self):
        form = RightsForm({'targets':[self.member.pk]}, actor=self.root)
        self.assertFalse(form.is_valid())

    def test_profile_choices_reject_forged_values(self):
        for cls in (UserUpdateForm, AdminUpdateForm):
            form = cls(instance=self.member)
            for name, bad, good in [('course','7','6'), ('city','Москва','Душанбе'), ('faculty','Другой','Лечебный')]:
                self.assertIsInstance(form.fields[name].widget, forms.Select)
                with self.assertRaises(forms.ValidationError):
                    form.fields[name].clean(bad)
                self.assertTrue(form.fields[name].clean(good))
        self.assertEqual(len(CITY_CHOICES), 18)

    def test_legacy_values_require_deliberate_replacement(self):
        self.member.city = 'Старое неизвестное значение'
        self.member.save()
        form = UserUpdateForm({'city':''}, instance=self.member)
        self.assertFalse(form.is_valid())
        self.assertIn('city', form.errors)
        self.member.refresh_from_db()
        self.assertEqual(self.member.city, 'Старое неизвестное значение')

    def test_invalid_filter_does_not_crash(self):
        self.assertEqual(filter_profiles(User.objects.all(), {'course':'abc'}).count(), 0)
        self.assertEqual(self.client.get(reverse('volunteer_list'), {'course':'abc', 'direction':'bad'}).status_code, 200)

    def test_independent_unit_permission_displays_create_action(self):
        PermissionOverride.objects.create(user=self.member, code='directions', enabled=True, scope='all')
        self.client.force_login(self.member)
        response = self.client.get(reverse('unit_catalog'))
        self.assertContains(response, reverse('direction_create_page'))
        self.assertEqual(self.client.get(reverse('direction_create_page')).status_code, 200)

    def test_hidden_inaccessible_management_links(self):
        PermissionOverride.objects.create(user=self.member, code='audit', enabled=True, scope='all')
        self.client.force_login(self.member)
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="' + reverse('home_manage') + '"')
        self.assertNotContains(response, 'href="' + reverse('user_management') + '"')
