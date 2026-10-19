"""Real Django authentication flow with synthetic accounts and isolated storage."""
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone

from axes.models import AccessAttempt, AccessLog
from .login_security import client_ip
from .models import JournalEntry, PermissionOverride, User

# Test-only access to the real admin login view, without changing production's hidden URL policy.
from aya_platform.urls import urlpatterns as production_urls
urlpatterns = [path('test-admin-login/', admin.site.login)] + production_urls


class LoginSecurityTests(TestCase):
    password = 'Synthetic-Long-Password-For-Tests-Only!'

    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user(
            username='security-member', password=cls.password,
            is_approved=True, qr_code='unused.png',
        )
        cls.other = User.objects.create_user(
            username='security-other', password=cls.password,
            is_approved=True, qr_code='unused.png',
        )
        cls.worker = User.objects.create_user(
            username='security-worker', password=cls.password,
            role='worker', is_approved=True, qr_code='unused.png',
        )
        cls.root = User.objects.create_user(
            username='security-root', password=cls.password,
            is_superuser=True, is_staff=True, qr_code='unused.png',
        )

    def post(self, person=None, password='wrong', url=None, client=None, **extra):
        return (client or self.client).post(url or reverse('login'), {
            'username': (person or self.member).username, 'password': password,
        }, **extra)

    def lock(self, person=None, url=None):
        for index in range(5):
            response = self.post(person, url=url)
            self.assertEqual(response.status_code, 429 if index == 4 else 200)
        return response

    def test_five_failures_pause_even_correct_password_without_changing_account(self):
        before = User.objects.values().get(pk=self.member.pk)
        self.lock()
        self.assertEqual(self.post(password=self.password).status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(User.objects.values().get(pk=self.member.pk), before)
        self.assertFalse(PermissionOverride.objects.exists())

    def test_cooldown_expires_automatically(self):
        start = timezone.now()
        with patch('django.utils.timezone.now', return_value=start), patch('axes.handlers.proxy.now', return_value=start):
            self.lock()
        later = start + timedelta(minutes=10, seconds=1)
        with patch('django.utils.timezone.now', return_value=later), patch('axes.handlers.proxy.now', return_value=later):
            self.assertEqual(self.post(password=self.password).status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.member.pk)

    def test_blocked_retries_never_extend_pause(self):
        start = timezone.now()
        with patch('django.utils.timezone.now', return_value=start), patch('axes.handlers.proxy.now', return_value=start):
            self.lock()
        stored = list(AccessAttempt.objects.values())
        later = start + timedelta(seconds=90)
        with patch('django.utils.timezone.now', return_value=later), patch('axes.handlers.proxy.now', return_value=later):
            response = self.post(password=self.password)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(int(response['Retry-After']), 510)
        self.assertEqual(list(AccessAttempt.objects.values()), stored)

    def test_other_account_on_same_wifi_can_log_in(self):
        self.lock()
        fresh = Client()
        self.assertEqual(self.post(self.other, self.password, client=fresh).status_code, 302)
        self.assertEqual(int(fresh.session['_auth_user_id']), self.other.pk)
        self.assertEqual(self.post(password=self.password).status_code, 429)

    def test_new_cookie_ip_user_agent_and_forwarded_headers_do_not_bypass(self):
        self.lock()
        response = self.post(password=self.password, client=Client(),
            REMOTE_ADDR='198.51.100.15', HTTP_USER_AGENT='Another browser',
            HTTP_X_REAL_IP='192.0.2.99', HTTP_X_FORWARDED_FOR='192.0.2.11')
        self.assertEqual(response.status_code, 429)

    def test_login_pages_share_counters_and_staff_rules(self):
        for i in range(5):
            url = reverse('staff_login' if i % 2 else 'login')
            response = self.post(self.worker, url=url)
            self.assertEqual(response.status_code, 429 if i == 4 else 200)
        response = self.post(self.worker, self.password, url=reverse('staff_login'))
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, 'Вход для сотрудников', status_code=429)
        self.assertContains(response, 'login-security.js', status_code=429)

    def test_successful_login_resets_previous_failures(self):
        for _ in range(4): self.post()
        self.assertEqual(self.post(password=self.password).status_code, 302)
        self.assertFalse(AccessAttempt.objects.exists())
        self.assertFalse(AccessLog.objects.exists())
        self.client.logout()
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(AccessAttempt.objects.get().failures_since_start, 1)

    def test_existing_sessions_survive_someone_else_failing_to_log_in(self):
        self.client.force_login(self.member, backend='django.contrib.auth.backends.ModelBackend')
        attacker = Client()
        for _ in range(5): self.post(client=attacker)
        self.assertEqual(self.client.get(reverse('my_profile')).status_code, 200)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.member.pk)

    def test_unknown_login_has_same_pause_policy(self):
        for i in range(5):
            response = self.client.post(reverse('login'), {'username':'nonexistent-security-user','password':'wrong'})
            self.assertEqual(response.status_code, 429 if i == 4 else 200)
        self.assertContains(response, 'Небольшая пауза', status_code=429)
        self.assertNotContains(response, 'не существует', status_code=429)

    def test_normalization_cannot_split_the_same_login_counter(self):
        for i in range(5):
            username = '  security-member  ' if i % 2 else 'ｓｅｃｕｒｉｔｙ－ｍｅｍｂｅｒ'
            response = self.client.post(reverse('login'), {'username':username,'password':'wrong'})
            self.assertEqual(response.status_code, 429 if i == 4 else 200)
        self.assertEqual(self.post(password=self.password).status_code, 429)

    def test_server_side_enforcement_also_covers_direct_authentication(self):
        rf = RequestFactory()
        for _ in range(5):
            request = rf.post('/login/')
            self.assertIsNone(authenticate(request=request, username=self.member.username, password='wrong'))
        request = rf.post('/login/')
        self.assertIsNone(authenticate(request=request, username=self.member.username, password=self.password))
        request = rf.post('/login/')
        self.assertEqual(authenticate(request=request, username=self.other.username, password=self.password), self.other)

    @override_settings(ROOT_URLCONF='users.test_login_security')
    def test_actual_django_admin_login_has_same_backend_protection_and_ui(self):
        self.lock(self.root, url='/test-admin-login/')
        response = self.post(self.root, self.password, url='/test-admin-login/')
        self.assertEqual(response.status_code, 429)
        self.assertTemplateUsed(response, 'admin/aya_login.html')
        self.assertContains(response, 'login-pause', status_code=429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_csrf_failure_does_not_authenticate_or_increment_password_attempts(self):
        client = Client(enforce_csrf_checks=True)
        for url in (reverse('login'), reverse('staff_login')):
            self.assertEqual(self.post(password=self.password, url=url, client=client).status_code, 403)
        self.assertFalse(AccessAttempt.objects.exists())

    def test_pause_has_retry_header_clear_password_and_no_cache(self):
        response = self.lock()
        self.assertGreater(int(response['Retry-After']), 0)
        self.assertLessEqual(int(response['Retry-After']), 600)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertContains(response, 'data-pause-countdown', status_code=429)
        self.assertNotContains(response, 'value="wrong"', status_code=429)

    def test_passwords_and_credentials_not_in_persistent_attempts_or_journal(self):
        secret = 'Synthetic-secret-value-should-not-be-stored'
        self.client.post(reverse('login')+'?token='+secret, {
            'username':self.member.username, 'password':secret,
            'csrfmiddlewaretoken':secret,'token':secret,'secret_key':secret,'next':secret,
        })
        self.assertNotIn(secret, repr(list(AccessAttempt.objects.values())))
        self.assertNotIn(secret, repr(list(JournalEntry.objects.values())))
        entry = JournalEntry.objects.get(section='login')
        self.assertEqual(entry.category, 'failure')
        self.assertTrue(entry.private)
        self.assertIsNone(entry.actor_id)

    def test_lockout_is_one_private_failure_record_per_request(self):
        self.lock()
        entries = JournalEntry.objects.filter(section='login')
        self.assertEqual(entries.count(), 5)
        self.assertFalse(entries.exclude(category='failure', private=True).exists())
        self.assertEqual(entries.filter(after__status=429).count(), 1)

    def test_staff_login_does_not_grant_worker_role_to_volunteer(self):
        self.assertEqual(self.post(password=self.password, url=reverse('staff_login')).status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, 'volunteer')

    def test_safe_next_survives_pause_and_external_next_is_rejected(self):
        self.lock()
        response = self.client.post(reverse('login'), {
            'username':self.member.username,'password':'wrong','next':'https://attacker.invalid/',
        })
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.context['next'], '')
        AccessAttempt.objects.all().delete()
        response = self.client.post(reverse('login'), {
            'username':self.member.username,'password':self.password,'next':reverse('my_profile'),
        })
        self.assertRedirects(response, reverse('my_profile'), fetch_redirect_response=False)

    def test_proxy_headers_only_trusted_from_local_aya_nginx(self):
        rf = RequestFactory()
        request = rf.get('/', REMOTE_ADDR='198.51.100.2', HTTP_X_REAL_IP='192.0.2.2', HTTP_X_FORWARDED_FOR='192.0.2.3')
        self.assertEqual(client_ip(request), '198.51.100.2')
        request = rf.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='198.51.100.2', HTTP_X_FORWARDED_FOR='192.0.2.3')
        self.assertEqual(client_ip(request), '198.51.100.2')
        request = rf.get('/', REMOTE_ADDR='127.0.0.1', HTTP_X_REAL_IP='malformed,192.0.2.2')
        self.assertEqual(client_ip(request), '127.0.0.1')

    def test_policy_uses_database_and_preserves_old_session_backend(self):
        self.assertEqual(settings.AXES_HANDLER, 'axes.handlers.database.AxesDatabaseHandler')
        self.assertIn('username', settings.AXES_LOCKOUT_PARAMETERS)
        self.assertIn(['username', 'ip_address'], settings.AXES_LOCKOUT_PARAMETERS)
        self.assertNotIn('ip_address', settings.AXES_LOCKOUT_PARAMETERS)
        self.assertEqual(settings.AUTHENTICATION_BACKENDS[-1], 'django.contrib.auth.backends.ModelBackend')
        self.assertFalse(settings.AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT)
