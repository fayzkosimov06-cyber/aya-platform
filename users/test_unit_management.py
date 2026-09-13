from datetime import timedelta
import importlib, uuid
from django.apps import apps
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import User, Direction, School, SchoolTeacher, SchoolLesson, PointProposal, ContributionAward
from .units import can_edit_unit
from .points import can_award
from .access import can_manage_members, can_register_for_events

class ManagementTests(TestCase):
    def setUp(self):
        self.student=User.objects.create(username='student',is_approved=True,qr_code='unused.png')
        self.teacher=User.objects.create(username='teacher',is_approved=True,qr_code='unused.png')
        self.outsider=User.objects.create(username='outsider',is_approved=True,qr_code='unused.png')
        self.president=User.objects.create(username='president',role='president',is_approved=True,qr_code='unused.png')
        self.root=User.objects.create(username='root',is_superuser=True,qr_code='unused.png')
        self.direction=Direction.objects.create(name='Science')
        self.direction.leaders.add(self.student)
        self.school=School.objects.create(name='School',direction=self.direction)
        self.st=SchoolTeacher.objects.create(school=self.school,member=self.teacher,name='Teacher')
        self.other=School.objects.create(name='Independent')
    def post(self,name,obj=None,data=None,tab='',actor=None):
        self.client.force_login(actor or self.president)
        url=reverse(name,args=[obj.pk] if obj else [])
        return self.client.post(url+('?tab='+tab if tab else ''),data or {})
    def test_global_and_scoped_controls(self):
        for actor in [self.root,self.president]:
            self.client.force_login(actor)
            for name in ['school_detail','school_edit']:
                self.assertEqual(self.client.get(reverse(name,args=[self.school.pk])).status_code,200)
            self.assertContains(self.client.get(reverse('school_detail',args=[self.school.pk])),'Управлять')
        self.assertTrue(can_edit_unit(self.student,self.school))
        self.assertFalse(can_edit_unit(self.student,self.other))
        self.assertTrue(can_edit_unit(self.teacher,self.school))
        self.assertFalse(can_edit_unit(self.teacher,self.direction))
        self.assertFalse(can_award(self.student));self.assertFalse(can_manage_members(self.student))
        self.assertTrue(can_register_for_events(self.student))
        self.assertEqual(self.post('direction_edit',self.direction,{'leaders':[self.outsider.pk]},'leaders',self.student).status_code,403)
    def test_separate_forms_members_and_history(self):
        self.school.description='Keep';self.school.save()
        response=self.post('school_edit',self.school,{'members':[self.outsider.pk]},'members',self.teacher)
        self.assertEqual(response.status_code,302)
        self.assertTrue(self.outsider.directions.filter(pk=self.direction.pk).exists())
        self.school.refresh_from_db();self.assertEqual(self.school.description,'Keep')
        self.assertEqual(self.post('points_quick',data={'title':'Help','date':timezone.localdate(),'points':5,'volunteers':[self.outsider.pk],'school':self.school.pk,'token':uuid.uuid4()}).status_code,302)
        self.post('school_edit',self.school,{},'members',self.teacher)
        self.assertFalse(self.school.members.exists());self.assertEqual(ContributionAward.objects.get().points,5)
    def test_teachers_appointment_and_account(self):
        self.assertEqual(self.post('teacher_create',self.school,{'member':self.outsider.pk},actor=self.student).status_code,403)
        self.assertEqual(self.post('teacher_create',self.school,{'member':''}).status_code,200)
        self.assertEqual(SchoolTeacher.objects.count(),1)
        self.assertEqual(self.post('teacher_create',self.school,{'member':self.outsider.pk,'subject':'Lab'}).status_code,302)
        self.assertTrue(can_edit_unit(self.outsider,self.school))
        self.assertTrue(self.school.members.filter(pk=self.outsider.pk).exists())
        self.client.force_login(self.teacher)
        url=reverse('teacher_edit',args=[self.school.pk,self.st.pk])
        self.assertEqual(self.client.post(url,{'member':self.outsider.pk,'subject':'Updated'}).status_code,403)
        self.assertEqual(self.client.post(url,{'subject':'Updated'}).status_code,302)
        self.st.refresh_from_db();self.assertEqual(self.st.member,self.teacher)
        self.assertEqual(self.client.post(url,{'action':'delete'}).status_code,403)
    def test_school_links_and_inactive_catalog(self):
        self.other.members.add(self.outsider)
        self.assertEqual(self.post('direction_edit',self.direction,{'schools':[self.other.pk]},'schools').status_code,302)
        self.school.refresh_from_db();self.other.refresh_from_db()
        self.assertIsNone(self.school.direction);self.assertEqual(self.other.direction,self.direction)
        self.assertTrue(self.outsider.directions.filter(pk=self.direction.pk).exists())
        self.other.active=False;self.other.save()
        self.assertNotContains(self.client.get(reverse('school_catalog')),'Independent')
        self.assertContains(self.client.get(reverse('school_catalog')+'?state=inactive'),'Independent')
    def test_weekly_lessons_edit_single_occurrence(self):
        start=timezone.now()+timedelta(days=2)
        data={'topic':'Lab','starts_at':start.isoformat(),'ends_at':(start+timedelta(hours=1)).isoformat(),'repeat_until':(start+timedelta(days=14)).date(),'teachers':[self.st.pk]}
        self.assertEqual(self.post('lesson_create',self.school,data,actor=self.teacher).status_code,302)
        self.assertEqual(self.school.lessons.count(),3)
        lesson=self.school.lessons.first();data.pop('repeat_until');data['cancelled']='on';data['topic']='Moved'
        response=self.client.post(reverse('lesson_edit',args=[self.school.pk,lesson.pk]),data)
        self.assertEqual(response.status_code,302);self.assertEqual(self.school.lessons.filter(cancelled=True).count(),1)
        self.assertEqual(self.school.lessons.filter(topic='Lab').count(),2)
    def test_proposals_approve_once_and_outsider_points(self):
        response=self.post('school_suggest',self.school,{'title':'Assistance','date':timezone.localdate(),'description':'Helped with equipment','volunteers':[self.outsider.pk]},actor=self.student)
        self.assertEqual(response.status_code,302);proposal=PointProposal.objects.get()
        self.assertEqual(self.post('proposal_review',proposal,{'decision':'approved','points':10},actor=self.student).status_code,403)
        self.assertEqual(self.post('proposal_review',proposal,{'decision':'approved','points':10}).status_code,302)
        self.post('proposal_review',proposal,{'decision':'approved','points':10})
        self.assertEqual(ContributionAward.objects.count(),1)
        self.assertFalse(self.outsider.aya_schools.exists())
        self.assertFalse(self.outsider.directions.exists())
        for name,obj in [('direction_detail',self.direction),('school_detail',self.school)]:
            self.assertEqual(self.client.get(reverse(name,args=[obj.pk])).context['unit_points'],10)
    def test_proposal_rejection_validation_and_visibility(self):
        self.post('school_suggest',self.school,{'title':'Help','date':timezone.localdate(),'volunteers':[self.outsider.pk]},actor=self.teacher)
        proposal=PointProposal.objects.get()
        self.assertEqual(self.post('proposal_review',proposal,{'decision':'rejected'}).status_code,200)
        self.assertEqual(self.post('proposal_review',proposal,{'decision':'rejected','note':'Уточните работу'}).status_code,302)
        self.assertFalse(ContributionAward.objects.exists())
        self.client.force_login(self.outsider)
        self.assertNotContains(self.client.get(reverse('proposal_list')+'?status=all'),'Уточните работу')
    def test_migration_preserves_assignments_and_is_idempotent(self):
        User.objects.filter(pk=self.student.pk).update(role='leader')
        self.school.leaders.add(self.outsider)
        migration=importlib.import_module('users.migrations.0038_student_leadership_and_school_members')
        migration.migrate_assignments(apps,None);migration.migrate_assignments(apps,None)
        self.student.refresh_from_db();self.assertEqual(self.student.role,'volunteer')
        self.assertTrue(self.direction.leaders.filter(pk=self.student.pk).exists())
        self.assertEqual(self.school.teachers.filter(member=self.outsider).count(),1)
        self.assertTrue(self.school.members.filter(pk=self.outsider.pk).exists())
    def test_all_editor_tabs_render_and_unit_deletion_keeps_points(self):
        self.client.force_login(self.root)
        for name,obj,tabs in [('direction_edit',self.direction,['about','members','leaders','featured','schools','events','points']),('school_edit',self.school,['about','members','teachers','schedule','events','points'])]:
            for tab in tabs:self.assertEqual(self.client.get(reverse(name,args=[obj.pk])+'?tab='+tab).status_code,200)
        for name in ['school_create_page','direction_create_page','proposal_list']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200)
        self.post('points_quick',data={'title':'Outside help','date':timezone.localdate(),'points':5,'volunteers':[self.outsider.pk],'school':self.school.pk,'token':uuid.uuid4()})
        self.assertEqual(self.post('school_delete_page',self.school).status_code,302)
        self.assertEqual(ContributionAward.objects.count(),1)
