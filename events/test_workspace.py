from datetime import timedelta
from io import BytesIO
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from users.models import User,Direction,School,SchoolTeacher,PointProposal,ContributionAward,ContributionWork,VolunteerVisit
from users.access import can_manage_event,can_create_event
from .models import Event,EventAttendance

class WorkspaceTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create(username='president',role='president',is_approved=True,qr_code='unused.png')
        self.leader=User.objects.create(username='leader',is_approved=True,qr_code='unused.png')
        self.teacher=User.objects.create(username='teacher',is_approved=True,qr_code='unused.png')
        self.person=User.objects.create(username='member',last_name='=Фамилия',first_name='Имя',patronymic='Отчество',faculty='Medicine',course=2,group='17',is_approved=True,qr_code='unused.png')
        self.candidate=User.objects.create(username='candidate',candidate_approved=True,qr_code='unused.png')
        self.direction=Direction.objects.create(name='Direction');self.direction.leaders.add(self.leader)
        self.school=School.objects.create(name='School',direction=self.direction);SchoolTeacher.objects.create(school=self.school,member=self.teacher,name='Teacher')
        self.start=timezone.now()+timedelta(days=1)
        self.event=Event.objects.create(title='Event',description='Description',organizer=self.admin,start_time=self.start,end_time=self.start+timedelta(hours=2),is_approved=True)
        self.event.aya_schools.add(self.school)
    def post(self,name,data=None,actor=None,pk=None,tab=''):
        self.client.force_login(actor or self.admin)
        return self.client.post(reverse(name,args=[pk or self.event.pk] if name!='event_create' else [])+('?tab='+tab if tab else ''),data or {})
    def payload(self,**kw):
        return {'title':'New','description':'Short','location':'University','start_time':self.start.isoformat(),'max_participants':1,**kw}
    def test_short_creation_draft_publish_and_scopes(self):
        response=self.post('event_create',self.payload(schools=[self.school.pk],action='submit'),self.teacher)
        self.assertEqual(response.status_code,302)
        event=Event.objects.get(title='New');self.assertFalse(event.is_approved);self.assertTrue(event.submitted_for_review)
        self.assertEqual(event.end_time,event.start_time+timedelta(hours=2));self.assertIn(self.school,event.aya_schools.all())
        self.assertEqual(self.post('event_edit',{'action':'publish'},self.teacher,event.pk,'status').status_code,403)
        self.assertEqual(self.post('event_edit',{'action':'publish'},pk=event.pk,tab='status').status_code,302)
        event.refresh_from_db();self.assertTrue(event.is_approved)
        self.assertFalse(can_create_event(self.person))
        alien=Direction.objects.create(name='Alien')
        self.assertEqual(self.post('event_create',self.payload(directions=[alien.pk]),self.teacher).status_code,403)
        self.assertEqual(Event.objects.count(),2)
    def test_joint_creation_only_global_and_unrelated_editor_denied(self):
        data=self.payload(directions=[self.direction.pk],schools=[self.school.pk])
        self.assertEqual(self.post('event_create',data,self.leader).status_code,200)
        self.assertEqual(Event.objects.count(),1)
        self.assertEqual(self.post('event_create',data).status_code,302)
        self.assertFalse(can_manage_event(self.person,self.event));self.assertTrue(can_manage_event(self.teacher,self.event));self.assertTrue(can_manage_event(self.leader,self.event))
    def test_over_capacity_and_cancel_notification(self):
        self.event.max_participants=1;self.event.save();self.event.participants.add(self.teacher)
        response=self.post('event_join',actor=self.person)
        self.assertEqual(response.status_code,302);self.assertTrue(self.event.participants.filter(pk=self.person.pk).exists())
        self.assertEqual(self.post('event_edit',{'action':'cancel','reason':'Weather'},tab='status',actor=self.teacher).status_code,403)
        self.post('event_edit',{'action':'cancel','reason':'Weather'},tab='status')
        self.event.refresh_from_db();self.assertTrue(self.event.cancelled)
        self.assertTrue(self.person.notifications.filter(message__contains='Weather').exists())
        self.event.participants.remove(self.person);self.post('event_join',actor=self.person)
        self.assertFalse(self.event.participants.filter(pk=self.person.pk).exists())
    def test_bulk_attendance_no_candidate_visits_and_candidate_rejected(self):
        self.post('event_edit',{'action':'add','selected':[self.person.pk,self.teacher.pk]},actor=self.teacher,tab='participants')
        self.assertEqual(self.event.participants.count(),2)
        for _ in range(2):self.post('event_edit',{'action':'present','selected':[self.person.pk,self.teacher.pk]},actor=self.teacher,tab='participants')
        self.assertEqual(EventAttendance.objects.count(),2);self.assertEqual(VolunteerVisit.objects.count(),0)
        self.post('event_edit',{'action':'add','selected':[self.candidate.pk]},actor=self.teacher,tab='participants')
        self.assertFalse(self.event.participants.filter(pk=self.candidate.pk).exists())
    def test_excel_scope_contents_and_literal_strings(self):
        self.event.participants.add(self.person)
        self.client.force_login(self.teacher);response=self.client.get(reverse('event_export',args=[self.event.pk]))
        self.assertEqual(response.status_code,200)
        with ZipFile(BytesIO(response.content)) as z:
            self.assertIsNone(z.testzip());sheet=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            values=[e.text for e in sheet.findall('.//s:t',ns)]
            self.assertIn('=Фамилия Имя Отчество',values);self.assertIn('Medicine',values);self.assertIn('17',values)
            self.assertFalse(sheet.findall('.//s:f',ns))
        self.client.force_login(self.person);self.assertEqual(self.client.get(reverse('event_export',args=[self.event.pk])).status_code,403)
    def test_points_approval_and_delete_preserves_awards(self):
        self.event.participants.add(self.person)
        data={'title':'Help','date':timezone.localdate(),'description':'Assistance','volunteers':[self.person.pk]}
        self.assertEqual(self.post('event_edit',data,self.teacher,tab='points').status_code,302)
        proposal=PointProposal.objects.get();self.assertEqual(proposal.event,self.event)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(reverse('proposal_review',args=[proposal.pk]),{'decision':'approved','points':5}).status_code,302)
        self.assertEqual(ContributionAward.objects.get().work.event,self.event)
        self.assertEqual(self.post('event_delete',actor=self.teacher).status_code,403)
        self.assertEqual(self.post('event_delete').status_code,302)
        self.assertEqual(ContributionAward.objects.get().points,5);self.assertIsNone(ContributionWork.objects.get().event)
    def test_creator_can_delete_own_and_get_never_deletes(self):
        self.event.organizer=self.teacher;self.event.save();self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse('event_delete',args=[self.event.pk])).status_code,200)
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.assertEqual(self.post('event_delete',actor=self.teacher).status_code,302)
    def test_templates_and_edit_does_not_erase_participants(self):
        self.event.participants.add(self.person);self.client.force_login(self.admin)
        for tab in ['about','participants','report','points','status']:
            self.assertEqual(self.client.get(reverse('event_edit',args=[self.event.pk])+'?tab='+tab).status_code,200)
        for route in ['event_list','admin_dashboard','user_management','moderator_dashboard']:
            self.assertEqual(self.client.get(reverse(route)).status_code,200)
        self.assertEqual(self.post('event_edit',self.payload(title='Updated'),self.teacher).status_code,302)
        self.assertTrue(self.event.participants.filter(pk=self.person.pk).exists());self.assertTrue(self.event.aya_schools.filter(pk=self.school.pk).exists())
    def test_multiple_event_proposals_share_work_without_collision(self):
        self.event.participants.add(self.person)
        for i in range(2):
            self.post('event_edit',{'title':f'Help {i}','date':timezone.localdate(),'volunteers':[self.person.pk]},self.teacher,tab='points')
        self.client.force_login(self.admin)
        for proposal in PointProposal.objects.all():
            self.assertEqual(self.client.post(reverse('proposal_review',args=[proposal.pk]),{'decision':'approved','points':5}).status_code,302)
        self.assertEqual(ContributionWork.objects.filter(event=self.event).count(),1)
        self.assertEqual(ContributionAward.objects.count(),2)
    def test_direct_points_form_saves_once(self):
        import uuid
        self.event.participants.add(self.person)
        data={'title':'Help','date':timezone.localdate(),'volunteers':[self.person.pk],'points':7,'token':uuid.uuid4()}
        for _ in range(2):self.assertEqual(self.post('event_edit',data,tab='points').status_code,302)
        self.assertEqual(ContributionAward.objects.count(),1);self.assertEqual(ContributionAward.objects.get().points,7)
