from datetime import date
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import User, ActivityPeriod
from .forms import ActivityPeriodForm
from events.models import Event, EventEvaluation

class ProfileHistoryTests(TestCase):
    def setUp(self):
        self.member=User.objects.create(username='member',is_approved=True,qr_code='unused.png')
        self.worker=User.objects.create(username='worker',role='worker',is_approved=True,qr_code='unused.png')
        self.events=[]
        for i in range(12):
            event=Event.objects.create(title='Event '+str(i),organizer=self.worker,start_time=timezone.now(),end_time=timezone.now(),is_completed=True,is_approved=True)
            event.participants.add(self.member)
            EventEvaluation.objects.create(event=event,volunteer=self.member,evaluator=self.worker,criteria=[{'name':'Teamwork','score':4}],comment='Private comment '+str(i))
            self.events.append(event)
        self.url=reverse('public_profile',args=[self.member.pk])

    def test_legacy_history_removed_from_profile(self):
        self.client.force_login(self.member)
        response=self.client.get(self.url)
        self.assertNotIn('history_page',response.context)
        self.assertNotContains(response,'Private comment')
        self.assertContains(response,'Мой вклад в AYA')

    def test_guest_and_candidate_no_history(self):
        self.assertNotContains(self.client.get(self.url),'Private comment')
        candidate=User.objects.create(username='candidate',candidate_approved=True,qr_code='unused.png')
        self.client.force_login(candidate)
        response=self.client.get(self.url)
        self.assertNotContains(response,'Private comment')
        self.assertNotIn('history_page',response.context)

    def test_invalid_filters_safe(self):
        self.client.force_login(self.member)
        response=self.client.get(self.url,{'period':'invalid','points_page':'bad'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['period'],'year')

    def test_activity_dates_and_gaps(self):
        period=ActivityPeriod.objects.create(user=self.member,start_date=date(2024,1,1),end_date=date(2024,3,1))
        form=ActivityPeriodForm(instance=period)
        self.assertIn('2024-01-01',str(form['start_date']))
        self.assertFalse(ActivityPeriodForm(data={'start_date':'2025-01-01','end_date':'2024-01-01'}).is_valid())
        self.client.force_login(self.worker)
        response=self.client.post(reverse('activity_periods_manage',args=[self.member.pk]),{'start_date':'2025-01-01','end_date':'','description':'Returned'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.member.activity_periods.count(),2)
        self.assertContains(self.client.get(self.url),'Returned')

    def test_activity_permissions_and_scoping(self):
        url=reverse('activity_periods_manage',args=[self.member.pk])
        for role in ('volunteer','moderator','leader'):
            actor=User.objects.create(username=role,role=role,is_approved=True,qr_code='unused.png')
            self.client.force_login(actor)
            self.client.post(url,{'start_date':'2025-01-01'})
        self.assertEqual(self.member.activity_periods.count(),0)
        period=ActivityPeriod.objects.create(user=self.worker,start_date=date(2024,1,1))
        self.client.force_login(self.worker)
        self.assertEqual(self.client.post(reverse('activity_period_delete',args=[self.member.pk,period.pk])).status_code,404)
        self.client.get(reverse('activity_period_delete',args=[self.worker.pk,period.pk]))
        self.assertTrue(ActivityPeriod.objects.filter(pk=period.pk).exists())
