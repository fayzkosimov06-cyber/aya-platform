from datetime import date
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import User, ContributionKind, ContributionWork, ContributionAward, ContributionChange
from .points import period, selected_awards
from events.models import Event

class PointTests(TestCase):
    def setUp(self):
        self.staff=User.objects.create(username='worker',role='worker',is_approved=True,qr_code='unused.png')
        self.member=User.objects.create(username='member',is_approved=True,qr_code='unused.png')
        self.kind=ContributionKind.objects.create(name='Help',points=5)
        self.work=ContributionWork.objects.create(title='Work',date=date(2025,8,31),created_by=self.staff)
        self.client.force_login(self.staff)

    def award(self):
        return self.client.post(reverse('points_work',args=[self.work.pk]),{'kind':self.kind.pk,'volunteers':[self.member.pk],'comment':'Helped'})

    def test_boundaries(self):
        self.assertEqual(period({},date(2026,8,31))['start'],date(2025,9,1))
        self.assertEqual(period({},date(2026,9,1))['start'],date(2026,9,1))
        self.assertEqual(period({'period':'week'},date(2026,9,13))['start'],date(2026,9,7))
        self.assertEqual(period({'period':'month'},date(2026,12,15))['end'],date(2027,1,1))
        self.award()
        self.assertEqual(selected_awards({'period':'year','year':'2024'})[0].count(),1)
        self.assertEqual(selected_awards({'period':'year','year':'2025'})[0].count(),0)
        self.assertEqual(selected_awards({'period':'all'})[0].count(),1)

    def test_duplicate_and_rule_snapshot(self):
        self.award();self.award()
        self.assertEqual(ContributionAward.objects.count(),1)
        self.assertEqual(ContributionChange.objects.count(),1)
        self.kind.points=20;self.kind.save()
        self.assertEqual(ContributionAward.objects.get().points,5)

    def test_correction_revoke_restore_audit(self):
        self.award();award=ContributionAward.objects.get()
        url=reverse('points_correct',args=[award.pk])
        self.client.post(url,{'points':10,'reason':'Mistake','comment':'Fixed','revoked':'on'})
        self.assertEqual(selected_awards({'period':'all'})[0].count(),0)
        self.client.post(url,{'points':10,'reason':'Restored','comment':'Fixed'})
        self.assertEqual(selected_awards({'period':'all'})[0].get().points,10)
        self.assertEqual(ContributionChange.objects.count(),3)
        response=self.client.get(reverse('points_work',args=[self.work.pk]))
        self.assertContains(response,'Mistake')

    def test_roles_and_invalid_members(self):
        for role in ['moderator','volunteer']:
            actor=User.objects.create(username=role,role=role,is_approved=True,qr_code='unused.png')
            self.client.force_login(actor)
            self.assertEqual(self.award().status_code,403)
        self.client.force_login(self.staff)
        self.client.post(reverse('points_work',args=[self.work.pk]),{'kind':self.kind.pk,'volunteers':[self.staff.pk]})
        self.assertEqual(ContributionAward.objects.count(),0)

    def test_event_participants_only_and_reuse(self):
        event=Event.objects.create(title='Event',start_time=timezone.now(),end_time=timezone.now(),organizer=self.staff,is_approved=True)
        self.work.event=event;self.work.save()
        self.award();self.assertFalse(ContributionAward.objects.exists())
        event.participants.add(self.member);self.award()
        self.assertEqual(ContributionAward.objects.count(),1)
        response=self.client.get(reverse('points_works'),{'event':event.pk})
        self.assertRedirects(response,reverse('points_work',args=[self.work.pk]))

    def test_rating_profile_privacy_and_rendering(self):
        self.award()
        response=self.client.get(reverse('volunteer_rating'),{'period':'all'})
        self.assertEqual(response.context['rows'][0]['points'],5)
        response=self.client.get(reverse('public_profile',args=[self.member.pk]),{'period':'all'})
        self.assertContains(response,'Helped')
        self.assertEqual(response.context['all_points'],5)
        for name in ['points_works','points_kinds']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('public_profile',args=[self.member.pk])),'Helped')
        self.assertTrue(self.client.get(reverse('volunteer_rating')).context['locked'])

    def test_future_work_and_empty_rules(self):
        response=self.client.post(reverse('points_works'),{'title':'Future','date':'2099-01-01'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(ContributionWork.objects.count(),1)
        self.kind.active=False;self.kind.save();self.award()
        self.assertFalse(ContributionAward.objects.exists())

    def test_bulk_and_ties(self):
        second=User.objects.create(username='second',is_approved=True,qr_code='unused.png')
        self.client.post(reverse('points_work',args=[self.work.pk]),{'kind':self.kind.pk,'volunteers':[self.member.pk,second.pk]})
        response=self.client.get(reverse('volunteer_rating'),{'period':'all'})
        self.assertEqual([r['place'] for r in response.context['rows']],[1,1])
