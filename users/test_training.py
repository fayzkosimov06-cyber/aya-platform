"""Training state, admission integration and read-only tour routes."""
import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import User, TourProgress, Notification, VolunteerVisit, Direction, School
from .services import grant_access
from events.models import Event


class TrainingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user(username='tour-member', is_approved=True, qr_code='unused.png')
        cls.other = User.objects.create_user(username='tour-other', is_approved=True, qr_code='unused.png')
        cls.candidate = User.objects.create_user(username='tour-candidate', candidate_approved=True, qr_code='unused.png')
        cls.staff = User.objects.create_user(username='tour-staff', role='worker', is_approved=True, qr_code='unused.png')

    def setUp(self):
        self.client.force_login(self.member)
        self.url = reverse('training_progress')

    def command(self, action, topic='main', **extra):
        row = TourProgress.objects.filter(user=self.member, topic=topic).first()
        return self.client.post(self.url, json.dumps({'action': action, 'topic': topic, 'version': 1,
            'revision': row.updated_at.isoformat() if row else None, **extra}), content_type='application/json')

    def test_existing_member_read_is_not_enrolled(self):
        data = self.client.get(self.url).json()
        self.assertEqual(data['states'], {})
        self.assertEqual(TourProgress.objects.count(), 0)
        self.assertEqual(len(data['topics']), 8)

    def test_candidate_has_profile_only_and_cannot_forge_full_tour(self):
        self.client.force_login(self.candidate)
        self.assertEqual(set(self.client.get(self.url).json()['topics']), {'profile'})
        self.assertEqual(self.command('start').status_code, 400)
        self.assertEqual(self.command('start', 'profile').status_code, 200)
        self.candidate.refresh_from_db()
        self.assertFalse(self.candidate.volunteer_access)
        self.assertFalse(self.candidate.is_approved)

    def test_manual_access_invites_once(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('grant_volunteer_access', args=[self.candidate.pk]), {'is_old_volunteer': 'on'})
        row = TourProgress.objects.get(user=self.candidate, topic='main')
        self.assertEqual(row.status, 'not_started')
        row.status = 'completed'; row.save()
        self.candidate.refresh_from_db()
        self.assertFalse(grant_access(self.candidate, self.staff))
        row.refresh_from_db(); self.assertEqual(row.status, 'completed')

    def test_third_visit_invites_but_first_two_do_not(self):
        self.client.force_login(self.staff)
        day = timezone.localdate()
        for n in range(3):
            with patch('users.views.timezone.localdate', return_value=day + timedelta(days=n)):
                self.client.post(reverse('mark_candidate_visit', args=[self.candidate.pk]))
                self.client.post(reverse('mark_candidate_visit', args=[self.candidate.pk]))
            self.assertEqual(VolunteerVisit.objects.filter(user=self.candidate).count(), n+1)
            self.assertEqual(TourProgress.objects.filter(user=self.candidate).exists(), n == 2)

    def test_pause_resume_complete_repeat_and_new_session(self):
        self.assertEqual(self.command('start').json()['state']['step'], 0)
        self.assertEqual(self.command('next').json()['state']['step'], 1)
        self.assertEqual(self.command('defer').json()['state']['status'], 'deferred')
        self.client.logout(); self.client.force_login(self.member)
        self.assertEqual(self.client.get(self.url).json()['states']['main']['step'], 1)
        self.command('resume'); self.command('back')
        count = len(self.client.get(self.url).json()['topics']['main']['steps'])
        for _ in range(count):
            self.assertEqual(self.command('next').status_code, 200)
        self.assertEqual(self.command('next').status_code, 400)
        self.assertEqual(self.client.get(self.url).json()['states']['main']['status'], 'completed')
        self.assertEqual(self.command('start').json()['state']['step'], 0)

    def test_post_owns_only_current_account(self):
        self.command('start', user_id=self.other.pk, step=999, status='completed')
        self.assertFalse(TourProgress.objects.filter(user=self.other).exists())
        row = TourProgress.objects.get(user=self.member)
        self.assertEqual((row.status, row.step), ('in_progress', 0))

    def test_invalid_payloads_and_methods(self):
        for body in ['[]', 'null', '{', '{"topic": []}', '{"topic":"main","action":"start","version":true}']:
            self.assertEqual(self.client.post(self.url, body, content_type='application/json').status_code, 400)
        for args in [{'topic':'unknown'}, {'version':2}, {'action':'delete'}]:
            payload = {'topic':'main','action':'start','version':1, **args}
            self.assertEqual(self.client.post(self.url,json.dumps(payload),content_type='application/json').status_code,400)
        self.assertEqual(self.client.put(self.url).status_code,405)
        self.assertEqual(TourProgress.objects.count(),0)

    def test_stale_tab_cannot_overwrite(self):
        revision = self.command('start').json()['state']['revision']
        self.command('next')
        self.assertEqual(self.command('defer', revision=revision).status_code,409)
        self.assertEqual(TourProgress.objects.get(user=self.member).step,1)

    def test_csrf_and_authentication(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code,302)
        client=Client(enforce_csrf_checks=True);client.force_login(self.member)
        self.assertEqual(client.post(self.url,'{}',content_type='application/json').status_code,403)
        client.get(reverse('training_help'))
        token=client.cookies['csrftoken'].value
        self.assertEqual(client.post(self.url,json.dumps({'topic':'main','action':'start','version':1}),content_type='application/json',HTTP_X_CSRFTOKEN=token).status_code,200)

    def test_empty_catalog_routes_render_and_notifications_stay_unread(self):
        note=Notification.objects.create(recipient=self.member,message='Test notice')
        data=self.client.get(self.url).json()
        for url in {s['url'] for t in data['topics'].values() for s in t['steps']}:
            self.assertEqual(self.client.get(url).status_code,200,url)
        note.refresh_from_db();self.assertFalse(note.is_read)
        self.assertEqual(TourProgress.objects.count(),0)

    def test_real_targets_do_not_register_user(self):
        event=Event.objects.create(title='Tour event',description='Demo',organizer=self.staff,
            start_time=timezone.now()+timedelta(days=1),end_time=timezone.now()+timedelta(days=2),is_approved=True)
        Direction.objects.create(name='Tour direction');School.objects.create(name='Tour school')
        data=self.client.get(self.url).json()
        for name in ['events', 'profile', 'volunteers', 'rating', 'main']:
            for item in data['topics'][name]['steps']:
                if item['target'] == 'help-topics':
                    continue
                response = self.client.get(item['url'])
                self.assertContains(response, 'data-tour="' + item['target'] + '"')
        for url in {s['url'] for t in data['topics'].values() for s in t['steps']}:
            self.assertEqual(self.client.get(url).status_code,200,url)
        self.assertFalse(event.participants.exists())
        for s in data['topics']['events']['steps'][1:]:
            self.assertEqual(s['url'],reverse('event_detail',args=[event.pk]))
        self.client.force_login(self.candidate)
        self.client.post(reverse('event_join',args=[event.pk]),{'action':'join'})
        self.assertFalse(event.participants.exists())

    def test_revoked_access_hides_saved_full_topics(self):
        self.command('start')
        User.objects.filter(pk=self.member.pk).update(is_approved=False,volunteer_access=False,candidate_approved=True)
        data=self.client.get(self.url).json()
        self.assertNotIn('main',data['topics']);self.assertNotIn('main',data['states'])
        self.assertEqual(self.command('resume').status_code,400)
