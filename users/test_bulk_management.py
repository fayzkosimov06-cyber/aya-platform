from django.test import TestCase
from django.urls import reverse
from .models import User,Direction,School,SchoolTeacher
from .access import can_manage_event
from events.models import Event
from django.utils import timezone

class BulkTests(TestCase):
    def setUp(self):
        self.root=User.objects.create(username='root',is_superuser=True,is_approved=True,qr_code='unused.png')
        self.admin=User.objects.create(username='admin',role='president',is_approved=True,qr_code='unused.png')
        self.mod=User.objects.create(username='mod',role='moderator',is_approved=True,qr_code='unused.png')
        self.people=[User.objects.create(username=f'user{i}',is_approved=True,qr_code='unused.png') for i in range(2)]
        self.direction=Direction.objects.create(name='Direction');self.school=School.objects.create(name='School',direction=self.direction)
    def post(self,action,actor=None,**extra):
        self.client.force_login(actor or self.admin)
        return self.client.post(reverse('user_management'),{'action':action,'selected':[m.pk for m in self.people],**extra})
    def test_bulk_titles_and_assignments(self):
        for action,extra in [('active',{}),('leader_add',{'direction':self.direction.pk}),('teacher_add',{'school':self.school.pk})]:
            self.assertEqual(self.post(action,**extra).status_code,302)
        self.assertEqual(self.direction.leaders.count(),2);self.assertEqual(self.school.teachers.count(),2)
        self.assertEqual(self.school.members.count(),2)
        self.assertEqual(User.objects.filter(is_active_volunteer_title=True).count(),2)
        self.assertEqual(self.post('teacher_remove',school=self.school.pk).status_code,302)
        self.assertEqual(self.school.teachers.count(),0);self.assertEqual(self.school.members.count(),2)
    def test_role_escalation_and_mixed_selection_atomic(self):
        response=self.post('role',role='worker');self.assertEqual(response.status_code,200)
        self.assertFalse(User.objects.filter(username__startswith='user',role='worker').exists())
        self.assertEqual(self.post('active',actor=self.mod).status_code,403)
        response=self.post('active',selected=[self.people[0].pk,self.root.pk]);self.assertEqual(response.status_code,200)
        self.people[0].refresh_from_db();self.assertFalse(self.people[0].is_active_volunteer_title)
        self.assertEqual(self.post('role',actor=self.root,role='moderator').status_code,302)
        self.assertEqual(User.objects.filter(username__startswith='user',role='moderator').count(),2)
    def test_candidates_and_access(self):
        User.objects.filter(pk__in=[p.pk for p in self.people]).update(is_approved=False)
        self.assertEqual(self.post('candidate').status_code,302)
        self.assertEqual(User.objects.filter(candidate_approved=True,is_approved=False).count(),2)
        self.assertEqual(self.post('grant',old='on').status_code,302)
        self.assertEqual(User.objects.filter(is_old_volunteer=True,is_approved=True).count(),2)
    def test_linking_foreign_event_cannot_grant_own_access(self):
        self.direction.leaders.add(self.people[0])
        event=Event.objects.create(title='Private',description='Private',organizer=self.admin,start_time=timezone.now(),end_time=timezone.now(),is_approved=True)
        self.client.force_login(self.people[0])
        response=self.client.post(reverse('direction_edit',args=[self.direction.pk])+'?tab=events',{'events':[event.pk]})
        self.assertEqual(response.status_code,403);self.assertFalse(self.direction.events.exists())
        self.assertFalse(can_manage_event(self.people[0],event))
