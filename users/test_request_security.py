"""Enforced CSRF and readable diagnostics, using synthetic accounts only."""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from axes.models import AccessAttempt
from .forms import UserUpdateForm
from .models import JournalEntry, User
from .readable_journal import Display
from .request_security import csrf_failure


class RequestSecurityTests(TestCase):
    password = 'Synthetic-Password-For-CSRF-Tests!'

    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user(username='request-member', password=cls.password, is_approved=True, qr_code='unused.png', phone='+992000000000', phone_privacy='public')
        cls.root = User.objects.create_user(username='request-root', password=cls.password, is_superuser=True, is_staff=True, qr_code='unused.png')

    def setUp(self):
        self.browser = Client(enforce_csrf_checks=True)

    def profile_data(self):
        form = UserUpdateForm(instance=self.member)
        return {name: form[name].value() for name in form.fields if name != 'photo' and form[name].value() is not None}

    def current(self):
        return self.browser.cookies[settings.CSRF_COOKIE_NAME].value

    def test_missing_cookie_shows_safe_branded_recovery_and_one_private_record(self):
        response = self.browser.post(reverse('login'), {'username': self.member.username, 'password': 'private-password-marker'})
        self.assertContains(response, 'Обновите форму', status_code=403)
        self.assertContains(response, 'Браузер не передал защитные cookie', status_code=403)
        self.assertNotContains(response, 'DEBUG=True', status_code=403)
        self.assertNotContains(response, 'private-password-marker', status_code=403)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotIn('_auth_user_id', self.browser.session)
        row = JournalEntry.objects.get(category='failure')
        self.assertTrue(row.private)
        self.assertEqual(row.after['failure_code'], 'browser_cookie_missing')
        self.assertEqual(row.after['failure_kind'], 'csrf')
        self.assertNotIn('private-password-marker', json.dumps(row.after))
        self.assertFalse(AccessAttempt.objects.exists())

    def test_login_rotates_cookie_old_profile_form_rejected_current_cookie_succeeds(self):
        self.browser.get(reverse('login'))
        old = self.current()
        response = self.browser.post(reverse('login'), {'username': self.member.username, 'password': self.password, 'csrfmiddlewaretoken': old})
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(old, self.current())
        data = {**self.profile_data(), 'first_name': 'Updated in synthetic test'}
        denied = self.browser.post(reverse('profile_edit'), {**data, 'csrfmiddlewaretoken': old})
        self.assertEqual(denied.status_code, 403)
        self.member.refresh_from_db()
        self.assertEqual(self.member.first_name, '')
        row = JournalEntry.objects.filter(section='profile_edit', category='failure').get()
        self.assertEqual(row.after['failure_code'], 'form_check_mismatch')
        accepted = self.browser.post(reverse('profile_edit'), {**data, 'csrfmiddlewaretoken': self.current()})
        self.assertEqual(accepted.status_code, 302)
        self.member.refresh_from_db()
        self.assertEqual(self.member.first_name, data['first_name'])
        self.assertNotIn(old, json.dumps(row.after))

    def test_ajax_current_cookie_works_and_missing_token_is_explained(self):
        self.browser.force_login(self.member)
        page = self.browser.get(reverse('my_profile'))
        self.assertContains(page, 'js/csrf.js')
        url = reverse('reveal_phone', args=[self.member.pk])
        denied = self.browser.post(url, HTTP_ACCEPT='application/json')
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()['error'], 'csrf')
        self.assertEqual(denied.json()['recovery_url'], reverse('public_profile', args=[self.member.pk]))
        self.assertNotIn('phone', denied.json())
        accepted = self.browser.post(url, HTTP_ACCEPT='application/json', HTTP_X_CSRFTOKEN=self.current())
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()['phone'], self.member.phone)
        self.assertEqual(JournalEntry.objects.filter(category='contact', after__network='phone').count(), 1)

    def test_foreign_origin_still_denied_with_current_cookie_and_not_reflected(self):
        self.browser.get(reverse('login'))
        marker = 'https://untrusted.invalid/private-origin-marker'
        response = self.browser.post(reverse('login'), {'username': self.member.username, 'password': self.password, 'csrfmiddlewaretoken': self.current()}, secure=True, HTTP_ORIGIN=marker)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', self.browser.session)
        row = JournalEntry.objects.get(category='failure')
        self.assertEqual(row.after['failure_code'], 'origin_mismatch')
        self.assertNotIn(marker, json.dumps(row.after))
        self.assertNotContains(response, marker, status_code=403)

    def test_https_missing_and_foreign_referrers_still_denied(self):
        for referrer, code in [('', 'referrer_missing'), ('https://untrusted.invalid/', 'referrer_mismatch')]:
            with self.subTest(referrer=referrer):
                self.browser.get(reverse('login'), secure=True)
                response = self.browser.post(reverse('login'), {'username': self.member.username, 'password': self.password, 'csrfmiddlewaretoken': self.current()}, secure=True, **({'HTTP_REFERER': referrer} if referrer else {}))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(JournalEntry.objects.filter(category='failure').first().after['failure_code'], code)
        self.assertNotIn('_auth_user_id', self.browser.session)

    def test_https_same_origin_with_valid_token_works(self):
        self.browser.get(reverse('login'), secure=True)
        response = self.browser.post(reverse('login'), {'username': self.member.username, 'password': self.password, 'csrfmiddlewaretoken': self.current()}, secure=True, HTTP_ORIGIN='https://testserver')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(int(self.browser.session['_auth_user_id']), self.member.pk)

    def test_recovery_does_not_redirect_to_external_referrer(self):
        request = RequestFactory().post('/activity/search/', HTTP_REFERER='https://untrusted.invalid/')
        request.user = AnonymousUser()
        response = csrf_failure(request, 'CSRF token missing.')
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('untrusted.invalid', response.content.decode())
        self.assertIn('href="/"', response.content.decode())

    def test_legacy_favicon_failure_is_explained_without_rewriting_history(self):
        row = JournalEntry.objects.create(actor=self.member, actor_key='user:'+str(self.member.pk), category='failure', private=True, section='', action='Отказ или ошибка', after={'path':'/favicon.ico','method':'GET','status':404})
        before = JournalEntry.objects.values().get(pk=row.pk)
        Display(self.root).entry(row)
        self.assertIn('значок вкладки', row.readable_title)
        self.assertIn('служебный запрос', row.failure_summary)
        self.assertIn(('Адрес запроса','/favicon.ico'), row.readable_details)
        self.assertEqual(JournalEntry.objects.values().get(pk=row.pk), before)

    def test_old_403_is_not_falsely_called_permission_denial_or_csrf(self):
        row = JournalEntry(category='failure', section='login', action='Отказ или ошибка', before={}, after={'path':'/login/','status':403})
        Display(self.root).entry(row)
        self.assertIn('Запрос отклонён (403)', row.readable_title)
        self.assertIn('Точная причина', row.failure_summary)
        self.assertNotIn('Недостаточно прав', row.readable_title)
        self.assertNotIn('устарел', row.failure_summary)

    def test_reason_visible_in_group_and_entry_summary_private_only(self):
        row = JournalEntry.objects.create(actor=self.member, actor_key='user:'+str(self.member.pk), subject_key='section:login', category='failure', private=True, section='login', action='Защита формы', after={'path':'/login/','method':'POST','status':403,'failure_kind':'csrf','failure_code':'form_check_mismatch','reason':'Синтетическая причина отказа'})
        self.client.force_login(self.root)
        params = {'actor': self.member.pk}
        grouped = self.client.get(reverse('journal_private'), params)
        self.assertContains(grouped, row.after['reason'])
        group = list(grouped.context['bundles'])[0]
        entries = self.client.get(reverse('journal_private'), {**params, 'bundle':group['token']})
        self.assertContains(entries, 'journal-failure-summary')
        self.assertContains(entries, row.after['reason'])
        self.assertContains(entries, 'Способ запроса')
        public = self.client.get(reverse('audit_log'), {**params, 'bundle':group['token']})
        self.assertNotContains(public, row.after['reason'])

    def test_missing_page_label_escapes_html(self):
        JournalEntry.objects.create(actor=self.member, actor_key='user:'+str(self.member.pk), category='failure', private=True, section='', action='Отказ', after={'path':'/<script>alert(1)</script>/','status':404})
        self.client.force_login(self.root)
        response = self.client.get(reverse('journal_private'), {'actor':self.member.pk})
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')

    def test_icon_is_available_and_never_logged_as_failure(self):
        for method in [self.browser.get, self.browser.head]:
            response = method('/favicon.ico')
            self.assertEqual(response.status_code, 301)
            self.assertEqual(response['Location'], '/static/img/aya-logo-2026.png')
        self.assertFalse(JournalEntry.objects.filter(category='failure').exists())
        self.assertTrue((Path(settings.BASE_DIR) / 'static/img/aya-logo-2026.png').is_file())

    def test_admin_pages_share_the_same_fresh_token_handling(self):
        self.client.force_login(self.root)
        response = self.client.get(reverse('admin:index'))
        self.assertContains(response, 'js/csrf.js', count=1)
