"""Regression cases from the November audit; synthetic users and isolated DB only."""
from datetime import date, timedelta
from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from events.models import Event
from .models import (User, Notification, PermissionOverride, StaffApplication,
                     ContributionWork, ContributionAward, JournalEntry)


class AccessAuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        def person(name, **kw):
            return User.objects.create(username=name, qr_code='unused.png', **kw)
        cls.member = person('audit-member', is_approved=True)
        cls.candidate = person('audit-candidate', candidate_approved=True,
            first_name='PrivateCandidateMarker', phone='+992000000000', phone_privacy='public',
            photo='photos/synthetic.png', birth_date=date(2001, 1, 2),
            telegram='synthetic_person', telegram_privacy='public',
            instagram='https://instagram.com/synthetic_person', instagram_privacy='public')
        cls.moderator = person('audit-moderator', role='moderator', is_approved=True)
        cls.worker = person('audit-worker', role='worker', is_approved=True)
        cls.staff_pending = person('audit-staff-pending')
        StaffApplication.objects.create(user=cls.staff_pending, requested_role='worker')
        cls.event = Event.objects.create(title='Private event', description='PrivateEventMarker',
            organizer=cls.worker, start_time=timezone.now(), end_time=timezone.now()+timedelta(days=1),
            is_approved=True, is_public_for_guests=False)

    def check_profile_endpoints(self, visible):
        target = self.candidate.pk
        response = self.client.get(reverse('public_profile', args=[target]))
        if visible:
            self.assertContains(response, 'PrivateCandidateMarker')
        else:
            self.assertEqual(response.status_code, 302)
            self.assertNotIn(b'PrivateCandidateMarker', response.content)
        for name, method, args, success in [
            ('profile_qr','get',[target],200),
            ('open_profile_photo','post',[target],200),
            ('reveal_phone','post',[target],200),
            ('reveal_birthday','post',[target],200),
            ('open_contact','get',[target,'telegram'],302),
            ('open_contact','get',[target,'instagram'],302),
        ]:
            with self.subTest(endpoint=name, args=args, visible=visible):
                result = getattr(self.client, method)(reverse(name, args=args))
                self.assertEqual(result.status_code, success if visible else 404)

    def test_candidate_hidden_from_guest_and_member_on_all_profile_endpoints(self):
        self.check_profile_endpoints(False)
        self.client.force_login(self.member)
        self.check_profile_endpoints(False)
        self.assertFalse(JournalEntry.objects.filter(category='contact').exists())

    def test_candidate_self_and_admission_staff_retain_access(self):
        for viewer in [self.candidate, self.moderator, self.worker]:
            self.client.force_login(viewer)
            self.check_profile_endpoints(True)

    def test_explicit_visit_denial_and_grant_respected(self):
        PermissionOverride.objects.create(user=self.moderator, code='visits', enabled=False)
        self.client.force_login(self.moderator)
        self.check_profile_endpoints(False)
        PermissionOverride.objects.create(user=self.member, code='admissions', enabled=True)
        self.client.force_login(self.member)
        self.check_profile_endpoints(True)

    def test_visit_permission_does_not_expose_staff_application(self):
        self.client.force_login(self.moderator)
        self.assertEqual(self.client.get(reverse('public_profile', args=[self.staff_pending.pk])).status_code,302)
        self.assertEqual(self.client.get(reverse('profile_qr', args=[self.staff_pending.pk])).status_code,404)

    def test_private_events_require_full_access_even_with_direct_link(self):
        url = reverse('event_detail', args=[self.event.pk])
        self.assertEqual(self.client.get(url).status_code,404)
        for viewer in [self.candidate, self.staff_pending]:
            self.client.force_login(viewer)
            response = self.client.get(url)
            self.assertEqual(response.status_code,404)
            self.assertNotIn(b'PrivateEventMarker', response.content)
        for viewer in [self.member, self.worker]:
            self.client.force_login(viewer)
            self.assertContains(self.client.get(url),'PrivateEventMarker')

    def test_public_event_and_draft_manager_access_preserved(self):
        url = reverse('event_detail', args=[self.event.pk])
        self.event.is_public_for_guests=True; self.event.save()
        self.assertEqual(self.client.get(url).status_code,200)
        self.client.force_login(self.candidate)
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.context['can_register'])
        self.assertFalse(response.context['can_view_participants'])
        self.client.logout()
        self.event.is_approved=False; self.event.save()
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(url).status_code,404)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(url).status_code,200)

    def test_malformed_points_ids_never_mutate_or_raise_server_error(self):
        self.client.force_login(self.worker)
        before=(ContributionWork.objects.count(),ContributionAward.objects.count())
        for value in ['not-a-number','-1','0','1.5','9'*80,'9223372036854775808','١٢']:
            with self.subTest(value=value):
                self.assertEqual(self.client.post(reverse('points_quick'),{'work':value}).status_code,400)
                self.assertEqual(self.client.get(reverse('points_works'),{'event':value}).status_code,404)
                self.assertEqual(self.client.get(reverse('points_kinds'),{'edit':value}).status_code,404)
        self.assertEqual((ContributionWork.objects.count(),ContributionAward.objects.count()),before)


class SafeActionTests(TestCase):
    def setUp(self):
        self.person=User.objects.create(username='safe-member',is_approved=True,qr_code='unused.png')
        self.other=User.objects.create(username='other-member',is_approved=True,qr_code='unused.png')
        self.note=Notification.objects.create(recipient=self.person,message='Synthetic notice',link='/notifications/')
        self.foreign=Notification.objects.create(recipient=self.other,message='Foreign notice')
        self.browser=Client(enforce_csrf_checks=True)
        self.browser.force_login(self.person)

    def token(self):
        self.browser.get(reverse('notifications'))
        return self.browser.cookies[settings.CSRF_COOKIE_NAME].value

    def test_get_never_logs_out_or_marks_notifications_read(self):
        for name,args in [('logout',[]),('mark_notification_as_read',[self.note.pk]),('mark_all_notifications_as_read',[])]:
            self.assertEqual(self.browser.get(reverse(name,args=args)).status_code,405)
        self.note.refresh_from_db()
        self.assertFalse(self.note.is_read)
        self.assertIn('_auth_user_id',self.browser.session)

    def test_mutations_require_csrf_and_only_touch_owned_notifications(self):
        for name,args in [('logout',[]),('mark_notification_as_read',[self.note.pk]),('mark_all_notifications_as_read',[])]:
            self.assertEqual(self.browser.post(reverse(name,args=args)).status_code,403)
        self.note.refresh_from_db(); self.assertFalse(self.note.is_read)
        token=self.token()
        self.assertEqual(self.browser.post(reverse('mark_notification_as_read',args=[self.foreign.pk]),{'csrfmiddlewaretoken':token}).status_code,404)
        result=self.browser.post(reverse('mark_notification_as_read',args=[self.note.pk]),{'csrfmiddlewaretoken':token})
        self.assertEqual(result.status_code,302)
        self.note.refresh_from_db(); self.assertTrue(self.note.is_read)
        self.browser.post(reverse('mark_all_notifications_as_read'),{'csrfmiddlewaretoken':token})
        self.foreign.refresh_from_db(); self.assertFalse(self.foreign.is_read)
        self.assertEqual(self.browser.post(reverse('logout'),{'csrfmiddlewaretoken':token}).status_code,302)
        self.assertNotIn('_auth_user_id',self.browser.session)

    def test_notification_cannot_redirect_to_foreign_host(self):
        self.note.link='https://untrusted.invalid/';self.note.save()
        response=self.browser.post(reverse('mark_notification_as_read',args=[self.note.pk]),{'csrfmiddlewaretoken':self.token()})
        self.assertRedirects(response,reverse('notifications'))


class TechnicalJournalTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create(username='audit-owner',is_superuser=True,qr_code='unused.png')
        self.member=User.objects.create(username='journal-member',is_approved=True,qr_code='unused.png')
        self.client.force_login(self.owner)
        JournalEntry.objects.all().delete()  # Only synthetic setup/login records in this test DB.
        def row(**kw):
            values=dict(category='failure',private=True,section='',actor_key='guest:synthetic',action='Request failed',after={'path':'/unknown-synthetic','status':404})
            values.update(kw)
            return JournalEntry.objects.create(**values)
        self.technical=[row(actor_key='guest:'+str(i),after={'path':'/unknown-synthetic-'+str(i),'status':404}) for i in range(3)]
        self.real=[row(actor=self.member,actor_key='user:'+str(self.member.pk)),
                   row(after={'path':'/unknown-error','status':500}),
                   row(section='public_profile'),
                   row(section='login',after={'path':'/login/','status':403,'failure_kind':'csrf'}),
                   row(actor_key='user:999'),
                   row(actor_key='',after={'status':404,'_actor_name':'Deleted synthetic account'})]

    def test_default_keeps_user_and_server_errors_without_deleting_history(self):
        before=list(JournalEntry.objects.values().order_by('pk'))
        response=self.client.get(reverse('journal_private'),{'view':'timeline'})
        self.assertEqual({r.pk for r in response.context['entries']},{r.pk for r in self.real})
        self.assertContains(response,'traffic=actions')
        self.assertEqual(list(JournalEntry.objects.values().order_by('pk')),before)

    def test_unknown_addresses_group_by_day_and_keep_each_exact_request(self):
        response=self.client.get(reverse('journal_private'),{'traffic':'technical'})
        self.assertEqual(len(response.context['bundles']),1)
        bundle=list(response.context['bundles'])[0]
        self.assertEqual(bundle['count'],3)
        self.assertEqual(bundle['title'],'Запросы к неизвестным адресам')
        details=self.client.get(reverse('journal_private'),{'traffic':'technical','bundle':bundle['token']})
        self.assertEqual({r.pk for r in details.context['entries']},{r.pk for r in self.technical})
        for row in self.technical:
            self.assertContains(details,row.after['path'])
            self.assertContains(details,timezone.localtime(row.created_at).strftime('%H:%M:%S'))
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('journal_private'),{'traffic':'technical','bundle':bundle['token']}).status_code,403)

    def test_export_and_cleanup_preview_follow_selected_filter(self):
        for traffic,expected in [('technical',3),('actions',6),('all',9)]:
            params={'cleanup_mode':'private','traffic':traffic}
            response=self.client.get(reverse('journal_cleanup'),params)
            self.assertEqual(response.context['count'],expected)
            response=self.client.get(reverse('journal_cleanup'),{**params,'export':'csv'})
            import csv,io
            self.assertEqual(len(list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')))))-1,expected)
        self.assertEqual(JournalEntry.objects.count(),9)
