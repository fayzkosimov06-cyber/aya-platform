"""Regression checks for admission, permissions, reports and event registration."""
from datetime import timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.models import AnonymousUser
from users.models import User, VolunteerVisit
from users.access import can_manage_event, can_register_for_events
from users.forms import AdminUpdateForm
from events.models import Event, EventHero, EventEvaluation
from events.forms import EventHeroForm


class AdmissionAndEventTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.media = TemporaryDirectory()
        cls.settings_override = override_settings(MEDIA_ROOT=cls.media.name, PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        cls.settings_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.settings_override.disable()
        cls.media.cleanup()

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(username='staff', role='worker', is_approved=True)
        cls.moderator = User.objects.create_user(username='moderator', role='moderator', is_approved=True)
        cls.member = User.objects.create_user(username='member', is_approved=True, volunteer_access=True)
        cls.pending = User.objects.create_user(username='pending')
        cls.candidate = User.objects.create_user(username='candidate', candidate_approved=True)
        cls.event = Event.objects.create(title='Test event', description='Test', organizer=cls.staff, start_time=timezone.now()+timedelta(days=1), end_time=timezone.now()+timedelta(days=2), is_approved=True, is_public_for_guests=True, max_participants=1)

    def post(self, name, obj, data=None, actor=None):
        self.client.force_login(actor or self.staff)
        return self.client.post(reverse(name, args=[obj.pk]), data or {})

    def test_approval_is_candidate_not_full_access(self):
        self.post('approve_user', self.pending)
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.candidate_approved)
        self.assertFalse(self.pending.is_approved)
        self.assertFalse(self.pending.volunteer_access)

    def test_three_visits_and_duplicate_request(self):
        day = timezone.localdate()
        for offset in range(3):
            with patch('users.views.timezone.localdate', return_value=day+timedelta(days=offset)):
                self.post('mark_candidate_visit', self.candidate, {'comment':'Came in'}, self.moderator)
                self.post('mark_candidate_visit', self.candidate, actor=self.moderator)
            self.assertEqual(self.candidate.volunteer_visits.count(), offset+1)
        self.candidate.refresh_from_db()
        self.assertTrue(self.candidate.is_approved)
        self.assertTrue(self.candidate.is_new_volunteer)
        self.assertEqual(self.candidate.volunteer_access_granted_by, self.moderator)
        self.assertEqual(self.candidate.new_volunteer_until-self.candidate.volunteer_access_granted_at, timedelta(days=14))
        self.assertTrue(self.candidate.volunteer_visits.filter(comment='Came in').exists())
        response=self.client.get(reverse('moderator_dashboard'))
        self.assertNotIn(self.candidate, response.context['candidates'])
        self.assertIn(self.candidate, response.context['recently_approved'])

    def test_manual_old_and_new_access_and_idempotence(self):
        self.post('grant_volunteer_access', self.candidate, {'is_old_volunteer':'on'})
        self.candidate.refresh_from_db()
        stamp=self.candidate.volunteer_access_granted_at
        self.assertTrue(self.candidate.is_old_volunteer)
        self.assertIsNone(self.candidate.new_volunteer_until)
        self.post('grant_volunteer_access', self.candidate)
        self.candidate.refresh_from_db()
        self.assertEqual(stamp,self.candidate.volunteer_access_granted_at)
        self.assertTrue(self.candidate.is_old_volunteer)
        self.post('grant_volunteer_access', self.pending)
        self.pending.refresh_from_db()
        self.assertTrue(self.pending.is_new_volunteer)
        self.pending.new_volunteer_until=timezone.now()-timedelta(seconds=1)
        self.assertFalse(self.pending.is_new_volunteer)

    def test_superadmin_attribution(self):
        actor=User.objects.create_superuser(username='root', email='root@example.test', password='test')
        self.post('grant_volunteer_access',self.candidate,actor=actor)
        self.candidate.refresh_from_db()
        self.assertIsNone(self.candidate.volunteer_access_granted_by)

    def test_moderator_cannot_approve_reject_grant_or_edit(self):
        for action in ['approve_user','reject_user','grant_volunteer_access','admin_edit_user']:
            self.post(action,self.pending,actor=self.moderator)
            self.pending.refresh_from_db()
            self.assertFalse(self.pending.is_approved)
            self.assertFalse(self.pending.candidate_approved)
        self.client.force_login(self.moderator)
        response=self.client.get(reverse('public_profile',args=[self.member.pk]))
        self.assertFalse(response.context['can_admin_edit'])

    def test_moderator_cannot_manage_even_own_event(self):
        self.event.organizer=self.moderator;self.event.save()
        self.assertFalse(can_manage_event(self.moderator,self.event))
        for action in ['event_delete','event_finish','event_report_edit','event_edit']:
            self.post(action,self.event, {'action':'save_report','report_text':'Changed'},self.moderator)
        self.event.refresh_from_db()
        self.assertFalse(self.event.is_completed)
        self.assertEqual(self.event.report_text,'')
        self.client.force_login(self.moderator)
        response=self.client.get(reverse('event_create'))
        self.assertEqual(response.status_code,403)

    def test_role_escalation_rejected(self):
        response=self.post('update_user_role',self.member,{'role':'leader'})
        self.assertEqual(response.status_code,403)
        self.member.refresh_from_db();self.assertEqual(self.member.role,'volunteer')
        choices=dict(AdminUpdateForm(instance=self.member,actor=self.staff).fields['role'].choices)
        self.assertNotIn('leader',choices);self.assertNotIn('worker',choices)

    def test_join_is_post_only_and_idempotent(self):
        self.client.force_login(self.member)
        response=self.client.get(reverse('event_join',args=[self.event.pk]))
        self.assertEqual(response.status_code,405)
        self.assertEqual(self.event.participants.count(),0)
        for _ in range(2):self.post('event_join',self.event,{'action':'join'},self.member)
        self.assertEqual(self.event.participants.count(),1)
        self.post('event_join',self.event,{'action':'leave'},self.member)
        self.assertEqual(self.event.participants.count(),0)

    def test_capacity_and_closed_events(self):
        self.event.participants.add(self.moderator)
        self.post('event_join',self.event,actor=self.member)
        self.assertTrue(self.event.participants.filter(pk=self.member.pk).exists())
        self.event.participants.clear()
        for field in ['is_completed','is_approved']:
            setattr(self.event,field,field=='is_completed');self.event.save()
            self.post('event_join',self.event,actor=self.member)
            self.assertEqual(self.event.participants.count(),0)
            setattr(self.event,field,field!='is_completed')

    def test_registration_permissions(self):
        for role in ['volunteer','president','worker','leader','head_admin']:
            user=User.objects.create_user(username='role_'+role,role=role,is_approved=True)
            self.assertEqual(can_register_for_events(user),role in ['volunteer','president','leader'])
        for user in [self.pending,self.candidate,self.staff]:
            self.post('event_join',self.event,actor=user)
        self.assertEqual(self.event.participants.count(),0)
        self.assertFalse(can_register_for_events(AnonymousUser()))

    def test_candidate_privacy_and_own_progress(self):
        self.event.participants.add(self.member)
        self.client.force_login(self.candidate)
        response=self.client.get(reverse('event_detail',args=[self.event.pk]))
        self.assertFalse(response.context['can_view_participants'])
        self.assertFalse(response.context['can_register'])
        response=self.client.get(reverse('my_profile'))
        self.assertContains(response,'Кандидат: 0/3')
        response=self.client.get(reverse('public_profile',args=[self.member.pk]))
        self.assertFalse(response.context['show']['phone'])
        self.assertTrue(self.client.get(reverse('event_list')).context['catalog_locked'])

    def test_public_detail_and_unpublished_protection(self):
        self.assertEqual(self.client.get(reverse('event_detail',args=[self.event.pk])).status_code,200)
        self.event.is_public_for_guests=False;self.event.save()
        self.assertEqual(self.client.get(reverse('event_detail',args=[self.event.pk])).status_code,404)
        self.client.force_login(self.member)
        self.event.is_approved=False;self.event.save()
        self.assertEqual(self.client.get(reverse('event_detail',args=[self.event.pk])).status_code,404)

    def test_heroes_and_evaluations_only_participants(self):
        self.event.is_completed=True;self.event.save()
        self.event.participants.add(self.member)
        self.assertFalse(EventHeroForm({'user':self.candidate.pk,'role_name':'Host'},event=self.event).is_valid())
        for user in [self.candidate,self.member]:
            self.post('event_report_edit',self.event, {'action':'set_role','user':user.pk,'role_name':'Host'})
            self.post('event_report_edit',self.event, {'action':'save_evaluation','volunteer_id':user.pk,'criteria_name':['Teamwork'],'criteria_score':['5']})
        self.assertEqual(list(EventHero.objects.values_list('user_id',flat=True)),[self.member.pk])
        self.assertFalse(EventEvaluation.objects.exists())  # Legacy scoring is now read-only.

    def test_history_and_new_badge_after_admission(self):
        VolunteerVisit.objects.create(user=self.candidate,marked_by=self.moderator,comment='History')
        self.post('grant_volunteer_access',self.candidate)
        self.client.force_login(self.candidate)
        self.assertContains(self.client.get(reverse('my_profile')),'History')
        self.client.logout()
        self.assertContains(self.client.get(reverse('public_profile',args=[self.candidate.pk])),'Новый волонтёр')

    def test_external_back_redirect_is_rejected(self):
        response=self.post('approve_user',self.pending,{'next':'https://example.org/'})
        self.assertFalse(response.url.startswith('https://example.org'))
