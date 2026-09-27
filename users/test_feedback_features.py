from datetime import timedelta
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import User, Club, ClubMeeting, Direction, School, SchoolTeacher, StaffApplication, PermissionOverride, ContributionWork, ContributionAward, ContributionKind, ContributionChange, JournalEntry
from .permissions import allowed,rank
from .templatetags.aya_people import presentation
from .training import topics_for
from events.models import Event


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class FeedbackFeaturesTests(TestCase):
    def setUp(self):
        def person(name,role='volunteer',**kwargs):return User.objects.create_user(username=name,first_name=name,role=role,is_approved=True,qr_code='unused.png',**kwargs)
        self.root=person('Root',is_superuser=True)
        self.head=person('Head','head_admin');self.worker=person('Worker','worker');self.president=person('President','president')
        self.member=person('Member');self.other=person('Other');self.teacher=person('Teacher');self.leader=person('Leader')
        self.direction=Direction.objects.create(name='Science');self.direction.leaders.add(self.leader)
        self.school=School.objects.create(name='School',direction=self.direction)
        SchoolTeacher.objects.create(school=self.school,member=self.teacher,name='Teacher')
        self.club=Club.objects.create(name='Reading',school=self.school);self.club.leaders.add(self.member)
        self.club.members.add(self.member,self.other)
        self.event=Event.objects.create(title='Meeting',organizer=self.member,description='Description',start_time=timezone.now()+timedelta(days=1),end_time=timezone.now()+timedelta(days=2),is_approved=True)
        self.event.aya_clubs.add(self.club)
    def login(self,user):self.client.force_login(user)
    def test_rank_and_inherited_club_scope(self):
        self.assertGreater(rank(self.head),rank(self.worker));self.assertGreater(rank(self.worker),rank(self.president))
        for user in [self.member,self.teacher,self.leader]:
            self.assertTrue(allowed(user,'clubs',self.club));self.assertTrue(allowed(user,'events_edit',self.event))
        self.assertFalse(allowed(self.other,'clubs',self.club));self.assertFalse(allowed(self.member,'club_appointments',self.club))
    def test_explicit_club_denial_and_selected_scope(self):
        PermissionOverride.objects.create(user=self.teacher,code='clubs',enabled=False)
        self.assertFalse(allowed(self.teacher,'clubs',self.club))
        rule=PermissionOverride.objects.create(user=self.other,code='clubs',enabled=True,scope='selected');rule.clubs.add(self.club)
        self.assertTrue(allowed(self.other,'clubs',self.club));self.assertFalse(allowed(self.other,'clubs',Club.objects.create(name='Foreign')))
    def test_editor_tabs_and_public_pages(self):
        self.login(self.president)
        for route,args in [('club_catalog',[]),('club_detail',[self.club.pk]),('club_create',[]),('club_meeting_create',[self.club.pk]),('staff_signup',[]),('staff_login',[])]:
            self.assertEqual(self.client.get(reverse(route,args=args)).status_code,200,route)
        for tab in ['about','members','leaders','schedule']:
            self.assertEqual(self.client.get(reverse('club_edit',args=[self.club.pk])+'?tab='+tab).status_code,200)
        self.login(self.member)
        self.assertEqual(self.client.get(reverse('club_edit',args=[self.club.pk])+'?tab=leaders').status_code,403)
    def test_club_leaders_cannot_elevate_peers(self):
        self.login(self.president)
        response=self.client.post(reverse('club_edit',args=[self.club.pk])+'?tab=leaders',{'leaders':[self.other.pk]})
        self.assertEqual(response.status_code,302);self.assertTrue(self.club.leaders.filter(pk=self.other.pk).exists())
        rule=PermissionOverride.objects.create(user=self.other,code='club_appointments',enabled=True,scope='own')
        self.login(self.other)
        response=self.client.post(reverse('club_edit',args=[self.club.pk])+'?tab=leaders',{'leaders':[self.other.pk,self.member.pk]})
        self.assertEqual(response.status_code,200);self.assertFalse(self.club.leaders.filter(pk=self.member.pk).exists())
    def test_club_meetings_repeat_and_foreign_id(self):
        self.login(self.member);start=timezone.localtime()+timedelta(days=1)
        response=self.client.post(reverse('club_meeting_create',args=[self.club.pk]),{'topic':'Weekly','starts_at':start.strftime('%Y-%m-%dT%H:%M'),'ends_at':(start+timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'),'repeat_until':(start+timedelta(days=14)).date().isoformat()})
        self.assertEqual(response.status_code,302);self.assertEqual(self.club.meetings.count(),3)
        foreign=Club.objects.create(name='Foreign');meeting=ClubMeeting.objects.create(club=foreign,topic='Private',starts_at=start,ends_at=start+timedelta(hours=1))
        self.assertEqual(self.client.post(reverse('club_meeting_edit',args=[self.club.pk,meeting.pk]),{'action':'delete'}).status_code,404)
    def test_staff_signup_cannot_select_effective_role(self):
        with override_settings(MEDIA_ROOT=str(__import__('tempfile').gettempdir())):
            response=self.client.post(reverse('staff_signup'),{'username':'applicant','first_name':'New','last_name':'Staff','email':'staff@example.test','password1':'Example-long-pass-943!','password2':'Example-long-pass-943!','requested_role':'worker','role':'head_admin','is_superuser':'on'})
        self.assertEqual(response.status_code,200)
        user=User.objects.get(username='applicant');self.assertFalse(user.is_active);self.assertFalse(user.is_superuser);self.assertEqual(user.role,'volunteer')
        application=user.staff_application
        self.login(self.president);self.assertEqual(self.client.post(reverse('staff_applications'),{'application':application.pk,'action':'approve'}).status_code,403)
        self.login(self.head);self.assertEqual(self.client.post(reverse('staff_applications'),{'application':application.pk,'action':'approve'}).status_code,302)
        user.refresh_from_db();self.assertTrue(user.is_active);self.assertEqual(user.role,'worker')
    def test_head_application_only_root_and_no_second_head(self):
        target=User.objects.create(username='Waiting',is_active=False,qr_code='unused.png')
        application=StaffApplication.objects.create(user=target,requested_role='head_admin')
        self.login(self.head);self.assertEqual(self.client.post(reverse('staff_applications'),{'application':application.pk,'action':'approve'}).status_code,404)
        self.login(self.root);self.client.post(reverse('staff_applications'),{'application':application.pk,'action':'approve'})
        target.refresh_from_db();self.assertFalse(target.is_active)
    def make_work(self):
        work=ContributionWork.objects.create(title='Help',date=timezone.localdate(),created_by=self.member,event=self.event)
        kind=ContributionKind.objects.create(name='Kind',points=10)
        for member in [self.member,self.other]:
            award=ContributionAward.objects.create(work=work,member=member,kind=kind,points=10)
            ContributionChange.objects.create(award=award,reason='Initial')
        return work
    def test_delete_work_removes_every_award_keeps_event(self):
        work=self.make_work();self.login(self.president)
        response=self.client.post(reverse('work_delete',args=[work.pk]),{'confirm':'yes'})
        self.assertEqual(response.status_code,302);self.assertFalse(ContributionWork.objects.exists());self.assertFalse(ContributionAward.objects.exists());self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.assertTrue(JournalEntry.objects.filter(category='deletion',private=True).exists())
    def test_delete_account_preserves_shared_work_and_other_points(self):
        work=self.make_work();self.login(self.president)
        response=self.client.post(reverse('user_delete',args=[self.member.pk]),{'username':self.member.username,'confirm':'on'})
        self.assertEqual(response.status_code,302);self.assertFalse(User.objects.filter(pk=self.member.pk).exists())
        self.event.refresh_from_db();self.assertIsNone(self.event.organizer)
        self.assertEqual(ContributionAward.objects.get().member,self.other)
        self.assertTrue(ContributionWork.objects.filter(pk=work.pk).exists())
        self.assertEqual(self.client.get(reverse('event_detail',args=[self.event.pk])).status_code,200)
    def test_delete_role_boundaries_and_no_get_mutation(self):
        self.login(self.president)
        for target in [self.president,self.worker,self.head,self.root]:self.assertEqual(self.client.post(reverse('user_delete',args=[target.pk]),{'username':target.username,'confirm':'on'}).status_code,403)
        self.assertEqual(self.client.get(reverse('user_delete',args=[self.member.pk])).status_code,200)
        self.assertTrue(User.objects.filter(pk=self.member.pk).exists())
    def test_staff_profile_has_no_student_sections(self):
        self.login(self.worker)
        response=self.client.get(reverse('my_profile'));self.assertContains(response,'Профиль сотрудника');self.assertNotContains(response,'Факультет');self.assertNotContains(response,'Вклад в AYA')
        response=self.client.get(reverse('profile_edit'));self.assertNotContains(response,'name="faculty"');self.assertContains(response,'name="job_title"')
    def test_frames_and_leadership_only(self):
        self.member.is_active_volunteer_title=True
        self.assertEqual(presentation(self.member)['frame'],'club')
        self.president.clubs_led.add(self.club)
        self.assertEqual(presentation(self.president)['frame'],'president')
        self.login(self.other);self.other.aya_schools.add(self.school)
        response=self.client.get(reverse('my_profile'));self.assertNotContains(response,'Учитель школы')
    def test_journal_names_grouping_and_private_boundary(self):
        JournalEntry.objects.create(actor=self.member,private=True,category='view',section='public_profile',after={'path':reverse('public_profile',args=[self.other.pk])})
        self.login(self.root)
        response=self.client.get(reverse('journal_activity'));self.assertContains(response,'Member')
        response=self.client.get(reverse('journal_activity')+'?actor='+str(self.member.pk));self.assertContains(response,'Other');self.assertContains(response,'Открыл')
        self.login(self.president);self.assertEqual(self.client.get(reverse('journal_activity')).status_code,403)
    def test_training_topics_follow_roles(self):
        self.assertIn('clubs_editor',topics_for(self.member));self.assertNotIn('rights',topics_for(self.member))
        self.assertIn('rights',topics_for(self.president));self.assertIn('clubs',topics_for(self.other))
    def test_cookie_joke_has_no_side_effects(self):
        before=User.objects.count();response=self.client.get(reverse('cookie_vault'))
        self.assertContains(response,'Отдел печенья взломан');self.assertEqual(User.objects.count(),before)
