"""Security regression cases use synthetic people and an isolated database only."""
from datetime import timedelta
from uuid import uuid4
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from users.models import User, Direction, School, Club, PermissionOverride, ContributionWork, SchoolTeacher
from .models import Event


class PublicationBoundaryTests(TestCase):
    def setUp(self):
        self.head=User.objects.create(username='boundary-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.person=User.objects.create(username='boundary-person',is_approved=True,qr_code='unused.png')
        self.a=Direction.objects.create(name='Allowed team');self.b=Direction.objects.create(name='Other team')
        self.start=timezone.now()+timedelta(days=1)
        self.event=Event.objects.create(title='Original',organizer=self.head,start_time=self.start,end_time=self.start+timedelta(hours=2))
        self.event.aya_directions.add(self.a)
        self.client.force_login(self.person)

    def grant(self,code,scope='all',enabled=True):
        rule=PermissionOverride.objects.create(user=self.person,code=code,scope=scope,enabled=enabled)
        if scope=='selected':rule.directions.add(self.a)
        return rule

    def data(self,**extra):
        return {'title':'Edited title','description':'Test description','location':'Test room','max_participants':10,
            'start_time':timezone.localtime(self.start).strftime('%Y-%m-%dT%H:%M'),
            'end_time':timezone.localtime(self.start+timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'action':'publish',**extra}

    def test_publication_permission_does_not_allow_content_edit(self):
        self.grant('events_publish');self.grant('events_edit',enabled=False)
        self.assertEqual(self.client.post(reverse('event_edit',args=[self.event.pk]),self.data()).status_code,403)
        self.event.refresh_from_db();self.assertEqual(self.event.title,'Original');self.assertFalse(self.event.is_approved)

    def test_publisher_can_still_use_status_tab_without_edit_permission(self):
        self.grant('events_publish');self.grant('events_edit',enabled=False)
        self.assertRedirects(self.client.get(reverse('event_edit',args=[self.event.pk])),reverse('event_edit',args=[self.event.pk])+'?tab=status')
        response=self.client.post(reverse('event_edit',args=[self.event.pk])+'?tab=status',self.data())
        self.assertEqual(response.status_code,302)
        self.event.refresh_from_db();self.assertTrue(self.event.is_approved);self.assertEqual(self.event.title,'Original')

    def test_publish_action_cannot_replace_proposal_permission(self):
        self.grant('events_publish');self.grant('points_propose',enabled=False)
        self.assertEqual(self.client.post(reverse('event_edit',args=[self.event.pk])+'?tab=points',{'action':'publish'}).status_code,403)

    def test_publish_action_cannot_bypass_backdated_points_restriction(self):
        self.client.force_login(self.head)
        response=self.client.post(reverse('event_edit',args=[self.event.pk])+'?tab=points',{
            'action':'publish','title':'Old work','date':timezone.localdate()-timedelta(days=1),
            'volunteers':[self.person.pk],'points':'10','token':uuid4()})
        self.assertEqual(response.status_code,403);self.assertFalse(ContributionWork.objects.exists())

    def test_new_event_cannot_publish_outside_selected_scope(self):
        self.grant('events_edit');self.grant('events_publish','selected')
        response=self.client.post(reverse('event_create'),self.data(directions=[self.b.pk]))
        self.assertEqual(response.status_code,403);self.assertEqual(Event.objects.count(),1)

    def test_unlinked_event_cannot_publish_with_selected_scope(self):
        self.grant('events_edit');self.grant('events_publish','selected')
        response=self.client.post(reverse('event_create'),self.data())
        self.assertEqual(response.status_code,403);self.assertEqual(Event.objects.count(),1)

    def test_team_change_cannot_move_published_event_outside_scope(self):
        self.grant('events_edit');self.grant('events_publish','selected')
        response=self.client.post(reverse('event_edit',args=[self.event.pk]),self.data(directions=[self.b.pk]))
        self.assertEqual(response.status_code,403)
        self.event.refresh_from_db();self.assertEqual(self.event.title,'Original');self.assertFalse(self.event.is_approved)
        self.assertEqual(list(self.event.aya_directions.all()),[self.a])

    def test_create_and_publish_within_selected_scope_still_works(self):
        self.grant('events_edit');self.grant('events_publish','selected')
        response=self.client.post(reverse('event_create'),self.data(directions=[self.a.pk]))
        self.assertEqual(response.status_code,302)
        created=Event.objects.exclude(pk=self.event.pk).get();self.assertTrue(created.is_approved)

    def test_joint_event_preserves_any_matching_team_scope(self):
        self.grant('events_edit');self.grant('events_publish','selected')
        response=self.client.post(reverse('event_create'),self.data(directions=[self.a.pk,self.b.pk]))
        self.assertEqual(response.status_code,302)
        created=Event.objects.exclude(pk=self.event.pk).get();self.assertTrue(created.is_approved)

    def test_publication_scope_inherits_school_and_club_direction(self):
        self.grant('events_edit');self.grant('events_publish','selected')
        school=School.objects.create(name='Scoped school',direction=self.a)
        club=Club.objects.create(name='Scoped club',school=school,direction=self.a)
        for field,obj in [('schools',school),('clubs',club)]:
            response=self.client.post(reverse('event_create'),self.data(**{field:[obj.pk]}))
            self.assertEqual(response.status_code,302)


class RequestBoundaryTests(TestCase):
    def setUp(self):
        self.head=User.objects.create(username='request-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.root=User.objects.create(username='request-root',is_superuser=True,is_approved=True,qr_code='unused.png')
        self.direction=Direction.objects.create(name='Request team')
        self.school=School.objects.create(name='Request school')

    def test_numeric_lookalikes_and_huge_query_values_cannot_raise_server_errors(self):
        for person,route,keys in [(None,'volunteer_list',['direction']),(None,'school_catalog',['direction']),
            (None,'club_catalog',['school','direction']),(self.head,'card_create',['user','year']),
            (self.head,'card_list',['year','course','direction','school','club']),
            (self.head,'points_quick',['member','work','direction','school','club']),
            (self.root,'journal_private',['actor','until'])]:
            client=Client()
            if person:client.force_login(person)
            for key in keys:
                for value in ('²','١٢','9'*5000):
                    with self.subTest(route=route,key=key,value=value[:8]):
                        self.assertEqual(client.get(reverse(route),{key:value}).status_code,404)

    def test_oversized_path_integer_rejected_before_url_conversion(self):
        for digits in ('9'*5000,'9'*20):
            self.assertEqual(self.client.get('/profile/'+digits+'/').status_code,404)

    def test_numeric_post_identifiers_rejected_before_permission_queries(self):
        self.client.force_login(self.head)
        for route,pk,tab,field in [('direction_edit',self.direction.pk,'leaders','leaders'),('school_edit',self.school.pk,'schedule','lessons'),('teacher_create',self.school.pk,'','member')]:
            for value in ('²','9'*5000):
                response=self.client.post(reverse(route,args=[pk])+('?tab='+tab if tab else ''),{field:[value],'action':'cancel_lessons'})
                self.assertEqual(response.status_code,404)
        self.assertFalse(SchoolTeacher.objects.exists())

    def test_valid_filters_and_empty_journal_snapshot_remain_available(self):
        self.assertEqual(self.client.get(reverse('school_catalog'),{'direction':'standalone'}).status_code,200)
        self.assertEqual(self.client.get(reverse('club_catalog'),{'direction':self.direction.pk}).status_code,200)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(reverse('journal_private'),{'until':'0','actor':'none'}).status_code,200)

    def test_authenticated_pages_are_not_stored_in_http_caches(self):
        self.client.force_login(self.head)
        for route in ('my_profile','audit_log','user_management','birthday_calendar'):
            response=self.client.get(reverse(route));self.assertEqual(response.status_code,200)
            self.assertIn('no-store',response['Cache-Control']);self.assertIn('private',response['Cache-Control'])
            self.assertIn('Cookie',response['Vary'])

    def test_baseline_csp_covers_public_pages_and_rejections(self):
        for path in ('/','/login/','/no-such-security-page/'):
            response=self.client.get(path)
            for directive in ("base-uri 'self'","object-src 'none'","form-action 'self'","frame-ancestors 'none'"):
                self.assertIn(directive,response['Content-Security-Policy'])
            if path=='/':self.assertNotIn('no-store',response.get('Cache-Control',''))

    def test_hsts_is_sent_over_https_without_subdomain_or_preload_scope(self):
        from aya_platform.settings import SECURE_HSTS_SECONDS
        with self.settings(SECURE_HSTS_SECONDS=SECURE_HSTS_SECONDS):
            response=self.client.get('/',secure=True)
            self.assertEqual(response['Strict-Transport-Security'],'max-age=3600')
            self.assertNotIn('Strict-Transport-Security',self.client.get('/'))


class LinkedProfilePrivacyTests(TestCase):
    def setUp(self):
        self.member=User.objects.create(username='visible-member',first_name='VisibleMember',is_approved=True,qr_code='unused.png')
        self.hidden=User.objects.create(username='hidden-member',first_name='HiddenCandidateMarker',candidate_approved=True,qr_code='unused.png')
        self.head=User.objects.create(username='privacy-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.root=User.objects.create(username='privacy-root',is_superuser=True,is_approved=True,qr_code='unused.png')
        self.school=School.objects.create(name='Privacy school')
        self.teacher=SchoolTeacher.objects.create(school=self.school,member=self.hidden,name='HiddenCandidateMarker',bio='HiddenTeacherBiography')
        SchoolTeacher.objects.create(school=self.school,name='LegacyTeacherMarker')
        self.event=Event.objects.create(title='Privacy event',organizer=self.head,is_approved=True,start_time=timezone.now(),end_time=timezone.now()+timedelta(hours=2))
        self.event.participants.add(self.hidden,self.member)
        from .models import EventHero
        EventHero.objects.create(event=self.event,user=self.hidden,role_name='HiddenRoleMarker')
        EventHero.objects.create(event=self.event,user=self.root,role_name='HiddenRootRoleMarker')

    def test_school_cannot_expose_hidden_candidate_through_teacher_card(self):
        response=self.client.get(reverse('school_detail',args=[self.school.pk]))
        self.assertNotContains(response,'HiddenCandidateMarker');self.assertNotContains(response,'HiddenTeacherBiography')
        self.assertContains(response,'LegacyTeacherMarker')

    def test_schedule_does_not_expose_hidden_candidate_teacher(self):
        from users.models import SchoolLesson
        lesson=SchoolLesson.objects.create(school=self.school,topic='Test lesson',starts_at=timezone.now(),ends_at=timezone.now()+timedelta(hours=1));lesson.teachers.add(self.teacher)
        response=self.client.get(reverse('school_detail',args=[self.school.pk]))
        self.assertNotContains(response,'HiddenCandidateMarker')
        self.assertEqual(list(response.context['lessons'])[0].teachers.count(),0)

    def test_ordinary_member_cannot_see_hidden_event_people_or_roles(self):
        self.client.force_login(self.member)
        response=self.client.get(reverse('event_detail',args=[self.event.pk]))
        self.assertNotContains(response,'HiddenCandidateMarker');self.assertNotContains(response,'HiddenRoleMarker')
        self.assertNotContains(response,'HiddenRootRoleMarker');self.assertContains(response,'VisibleMember')

    def test_authorized_manager_retains_visibility_of_candidate_assignments(self):
        self.client.force_login(self.head)
        self.assertContains(self.client.get(reverse('school_detail',args=[self.school.pk])),'HiddenCandidateMarker')
        response=self.client.get(reverse('event_detail',args=[self.event.pk]))
        self.assertContains(response,'HiddenCandidateMarker');self.assertNotContains(response,'HiddenRootRoleMarker')

    def test_linked_visibility_matches_profile_policy(self):
        from django.contrib.auth.models import AnonymousUser
        from users.access import visible_profiles,can_view_profile
        from users.models import StaffApplication
        applicant=User.objects.create(username='privacy-applicant',qr_code='unused.png');StaffApplication.objects.create(user=applicant,requested_role='worker')
        moderator=User.objects.create(username='privacy-moderator',role='moderator',is_approved=True,qr_code='unused.png')
        for viewer in (AnonymousUser(),self.member,self.hidden,self.head,self.root,moderator):
            expected={person.pk for person in User.objects.all() if can_view_profile(viewer,person)}
            actual=set(visible_profiles(viewer,User.objects.all()).values_list('pk',flat=True))
            self.assertEqual(actual,expected)
