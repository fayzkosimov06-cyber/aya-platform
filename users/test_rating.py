from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from events.models import Event, EventEvaluation
from .models import User
from .rating import rating_rows
from .views import build_evaluation_stats

class RatingTests(TestCase):
    def setUp(self):
        self.staff = self.member('staff', role='worker')
        self.volunteer = self.member('volunteer')
        self.event = Event.objects.create(title='Completed', organizer=self.staff, start_time=timezone.now(), end_time=timezone.now(), is_completed=True, is_approved=True)

    def member(self, name, **kwargs):
        return User.objects.create(username=name, qr_code='unused.png', **{'is_approved':True, **kwargs})

    def evaluate(self, member=None, score=5, event=None, evaluator=None):
        member = member or self.volunteer
        event = event or self.event
        event.participants.add(member)
        return EventEvaluation.objects.create(event=event, volunteer=member, evaluator=evaluator or self.staff, criteria=[{'name':'Teamwork','score':score}])

    def test_average_counts_and_profile_agree(self):
        self.evaluate(score=5)
        self.evaluate(score=3, evaluator=self.member('second', role='worker'))
        row = rating_rows()[0]
        self.assertEqual((row['score'], row['events'], row['evaluations']), (Decimal('4.00'),1,2))
        self.assertEqual(build_evaluation_stats(self.volunteer)['avg'], row['score'])

    def test_only_completed_approved_registered_valid_scores(self):
        evaluation = self.evaluate()
        for field in ('is_completed','is_approved'):
            setattr(self.event,field,False); self.event.save()
            self.assertEqual(rating_rows(),[])
            setattr(self.event,field,True); self.event.save()
        self.event.participants.remove(self.volunteer)
        self.assertEqual(rating_rows(),[])
        self.event.participants.add(self.volunteer)
        EventEvaluation.objects.filter(pk=evaluation.pk).update(total_score=0)
        self.assertEqual(rating_rows(),[])

    def test_roles_and_unrated_excluded(self):
        for role in ('worker','leader','head_admin'):
            self.evaluate(self.member(role,role=role))
        self.evaluate(self.member('super',is_superuser=True))
        self.evaluate(self.member('candidate',is_approved=False))
        president=self.member('president',role='president')
        self.evaluate(president)
        self.assertEqual([r['member'].pk for r in rating_rows()],[president.pk])

    def test_ties_and_global_places(self):
        self.evaluate(score=5)
        self.evaluate(self.member('equal'),score=5)
        self.evaluate(self.member('third'),score=4)
        self.assertEqual([r['place'] for r in rating_rows()],[1,1,3])

    def test_privacy_and_profile_links(self):
        self.evaluate()
        url=reverse('volunteer_rating')
        self.assertNotContains(self.client.get(url),reverse('public_profile',args=[self.volunteer.pk]))
        self.client.force_login(self.member('pending',is_approved=False))
        self.assertTrue(self.client.get(url).context['locked'])
        self.client.force_login(self.volunteer)
        response=self.client.get(url)
        self.assertFalse(response.context.get('locked',False))
        self.assertNotContains(response,reverse('public_profile',args=[self.volunteer.pk]))  # Old scores are not points.

    def test_updates_and_deletion(self):
        evaluation=self.evaluate()
        evaluation.criteria=[{'name':'Teamwork','score':2}];evaluation.save()
        self.assertEqual(rating_rows()[0]['score'],Decimal('2.00'))
        evaluation.delete()
        self.assertEqual(rating_rows(),[])

    def test_pagination_keeps_places(self):
        for i in range(31):
            self.evaluate(self.member('v%02d'%i),score=5-i/100)
        self.client.force_login(self.volunteer)
        response=self.client.get(reverse('volunteer_rating'),{'page':2})
        self.assertEqual(len(response.context['rows']),0)
        self.assertEqual(response.context['leaders'],[])

    def test_empty_page(self):
        self.client.force_login(self.volunteer)
        self.assertContains(self.client.get(reverse('volunteer_rating')),'За выбранный период начислений пока нет.')
