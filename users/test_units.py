from datetime import timedelta
import uuid
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import User, Direction, School, SchoolTeacher, SchoolLesson, ContributionAward
from .units import can_edit_unit
from events.models import Event

class UnitTests(TestCase):
    def setUp(self):
        self.leader=User.objects.create(username='leader',role='leader',is_approved=True,qr_code='unused.png')
        self.other=User.objects.create(username='other',role='leader',is_approved=True,qr_code='unused.png')
        self.member=User.objects.create(username='member',is_approved=True,qr_code='unused.png')
        self.school_leader=User.objects.create(username='teacher',is_approved=True,qr_code='unused.png')
        self.direction=Direction.objects.create(name='Science')
        self.direction.leaders.add(self.leader)
        self.member.directions.add(self.direction)
        self.school=School.objects.create(name='Biology',direction=self.direction)
        self.school.leaders.add(self.school_leader);self.school.members.add(self.member)
        SchoolTeacher.objects.create(school=self.school,member=self.school_leader,name='Teacher')

    def test_scoped_edit_permissions(self):
        self.assertTrue(can_edit_unit(self.leader,self.direction))
        self.assertFalse(can_edit_unit(self.other,self.direction))
        self.assertTrue(can_edit_unit(self.leader,self.school))
        self.assertTrue(can_edit_unit(self.school_leader,self.school))
        self.assertFalse(can_edit_unit(self.school_leader,self.direction))
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('direction_edit',args=[self.direction.pk]),{'intro':'bad'}).status_code,403)
        self.direction.refresh_from_db();self.assertEqual(self.direction.intro,'')

    def test_pages_featured_and_links(self):
        self.assertContains(self.client.get(reverse('school_catalog')),'Biology')
        url=reverse('direction_detail',args=[self.direction.pk])
        self.assertContains(self.client.get(url),reverse('public_profile',args=[self.member.pk]))
        self.direction.featured_only=True;self.direction.save()
        self.assertNotContains(self.client.get(url),reverse('public_profile',args=[self.member.pk]))
        self.direction.featured_members.add(self.member)
        self.assertContains(self.client.get(url),'Активная команда направления')
        self.assertContains(self.client.get(reverse('school_detail',args=[self.school.pk])),reverse('public_profile',args=[self.member.pk]))
        self.assertContains(self.client.get(reverse('home')),url)

    def test_teacher_lesson_and_cross_school_validation(self):
        self.client.force_login(self.school_leader)
        teacher=self.school.teachers.get(member=self.school_leader)
        other=School.objects.create(name='Other');alien=SchoolTeacher.objects.create(school=other,name='Alien')
        now=timezone.now()+timedelta(days=1)
        data={'topic':'Cells','starts_at':now.isoformat(),'ends_at':(now+timedelta(hours=1)).isoformat(),'teachers':[alien.pk]}
        url=reverse('lesson_create',args=[self.school.pk])
        self.client.post(url,data);self.assertFalse(SchoolLesson.objects.exists())
        data['teachers']=[teacher.pk];self.client.post(url,data)
        self.assertEqual(SchoolLesson.objects.count(),1)
        response=self.client.get(reverse('school_detail',args=[self.school.pk]))
        self.assertContains(response,'Cells');self.assertContains(response,'Teacher')
        self.assertEqual(self.client.post(reverse('teacher_edit',args=[self.school.pk,alien.pk]),{'action':'delete'}).status_code,404)
        data['ends_at']=now.isoformat();self.client.post(url,data)
        self.assertEqual(SchoolLesson.objects.count(),1)

    def test_event_visibility(self):
        event=Event.objects.create(title='Private event',organizer=self.leader,is_approved=True,start_time=timezone.now(),end_time=timezone.now()+timedelta(days=1))
        self.direction.events.add(event)
        url=reverse('direction_detail',args=[self.direction.pk])
        self.assertNotContains(self.client.get(url),'Private event')
        self.client.force_login(self.member);self.assertContains(self.client.get(url),'Private event')

    def test_edit_forms_and_scope_points(self):
        self.client.force_login(self.leader)
        for route,obj in [('direction_edit',self.direction),('school_edit',self.school)]:
            self.assertEqual(self.client.get(reverse(route,args=[obj.pk])).status_code,200)
        president=User.objects.create(username='president',role='president',is_approved=True,qr_code='unused.png')
        self.client.force_login(president)
        response=self.client.post(reverse('points_quick'),{'title':'Lesson assistance','date':timezone.localdate().isoformat(),'points':10,'volunteers':[self.member.pk],'school':self.school.pk,'token':str(uuid.uuid4())})
        self.assertEqual(response.status_code,302)
        award=ContributionAward.objects.get();self.assertEqual(award.work.direction,self.direction)
        self.assertEqual(self.client.get(reverse('direction_detail',args=[self.direction.pk])).context['unit_points'],10)
        self.assertEqual(self.client.get(reverse('school_detail',args=[self.school.pk])).context['unit_points'],10)
        self.client.logout();self.assertIsNone(self.client.get(reverse('school_detail',args=[self.school.pk])).context['unit_points'])

    def test_school_leader_cannot_move_school(self):
        self.client.force_login(self.school_leader)
        other=Direction.objects.create(name='Other direction')
        self.client.post(reverse('school_edit',args=[self.school.pk]),{'intro':'Updated','direction':other.pk,'members':[self.member.pk]})
        self.school.refresh_from_db();self.assertEqual(self.school.direction,self.direction)
        self.assertEqual(self.school.intro,'Updated')
