from datetime import date
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import User, Direction, School, SchoolTeacher, Club
from .permissions import allowed
from .templatetags.aya_people import presentation


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AssignmentFeedbackTests(TestCase):
    def setUp(self):
        self.head=User.objects.create_user(username='head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.person=User.objects.create_user(username='student',first_name='Алина',is_approved=True,qr_code='unused.png',birth_date=date(2001,2,3))
        self.other=User.objects.create_user(username='other',is_approved=True,qr_code='unused.png')
        self.direction=Direction.objects.create(name='Наука')
        self.school=School.objects.create(name='Исследования',direction=self.direction)
        self.card=SchoolTeacher.objects.create(school=self.school,member=self.person,name='Алина')
        self.client.force_login(self.head)

    def test_school_member_removal_clears_teacher_and_permissions(self):
        self.assertTrue(allowed(self.person,'schools',self.school))
        response=self.client.post(reverse('school_edit',args=[self.school.pk])+'?tab=members',{'members':[]})
        self.assertEqual(response.status_code,302)
        self.assertFalse(self.school.members.exists());self.assertFalse(self.school.leaders.exists())
        self.assertFalse(self.school.teachers.exists());self.assertFalse(allowed(self.person,'schools',self.school))
        self.assertEqual(presentation(self.person)['frame'],'volunteer')

    def test_teacher_unassign_leaves_roster_and_clears_profile(self):
        response=self.client.post(reverse('teacher_edit',args=[self.school.pk,self.card.pk]),{'action':'delete'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(self.school.members.filter(pk=self.person.pk).exists())
        self.assertFalse(self.school.leaders.exists());self.assertFalse(self.school.teachers.exists())
        self.assertNotContains(self.client.get(reverse('public_profile',args=[self.person.pk])),'Учитель школы')

    def test_direct_teacher_change_and_legacy_unassignment(self):
        self.card.member=self.other;self.card.save()
        self.assertFalse(self.school.leaders.filter(pk=self.person.pk).exists())
        self.assertTrue(self.school.leaders.filter(pk=self.other.pk).exists())
        self.other.school_leader_of.clear()
        self.assertFalse(self.school.teachers.exists())

    def test_direct_membership_removal_clears_appointments(self):
        self.school.featured_members.add(self.person)
        self.person.aya_schools.remove(self.school)
        self.assertFalse(self.school.teachers.exists());self.assertFalse(self.school.leaders.exists())
        self.assertFalse(self.school.featured_members.exists())
        self.direction.user_set.add(self.person);self.direction.leaders.add(self.person)
        self.person.directions.clear()
        self.assertFalse(self.direction.leaders.exists())

    def test_removing_direction_does_not_reappear_on_school_save(self):
        self.school.members.add(self.other);self.direction.user_set.add(self.other)
        self.client.post(reverse('direction_edit',args=[self.direction.pk])+'?tab=members',{'members':[]})
        for url,data in [
            (reverse('school_edit',args=[self.school.pk])+'?tab=members',{'members':[self.person.pk,self.other.pk]}),
            (reverse('direction_edit',args=[self.direction.pk])+'?tab=schools',{'schools':[self.school.pk]}),
        ]:
            self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertFalse(self.other.directions.filter(pk=self.direction.pk).exists())

    def test_club_roster_removal_unassigns_responsible(self):
        club=Club.objects.create(name='Клуб',school=self.school);club.members.add(self.other);club.leaders.add(self.other)
        response=self.client.post(reverse('club_edit',args=[club.pk])+'?tab=members',{'members':[]})
        self.assertEqual(response.status_code,302);self.assertFalse(club.leaders.exists())
        self.assertFalse(allowed(self.other,'clubs',club))

    def test_responsible_cannot_unassign_self_through_roster(self):
        club=Club.objects.create(name='Клуб');club.members.add(self.other);club.leaders.add(self.other)
        self.client.force_login(self.other)
        response=self.client.post(reverse('club_edit',args=[club.pk])+'?tab=members',{'members':[]})
        self.assertEqual(response.status_code,200);self.assertTrue(club.leaders.filter(pk=self.other.pk).exists())

    def test_all_frame_combinations_and_active_priority(self):
        self.direction.leaders.add(self.person)
        club=Club.objects.create(name='Клуб');club.leaders.add(self.person)
        self.person.is_active_volunteer_title=True
        self.assertEqual(presentation(self.person)['frame'],'leader-teacher-club')
        self.school.leaders.remove(self.person)
        self.assertEqual(presentation(self.person)['frame'],'leader-club')
        self.direction.leaders.remove(self.person)
        self.assertEqual(presentation(self.person)['frame'],'club')
        club.leaders.remove(self.person)
        self.assertEqual(presentation(self.person)['frame'],'active')
        self.person.role='president';club.leaders.add(self.person)
        self.assertEqual(presentation(self.person)['frame'],'president')

    def test_birthday_visible_in_student_and_staff_profiles(self):
        self.assertNotContains(self.client.get(reverse('public_profile',args=[self.person.pk])),'03.02.2001')
        self.assertEqual(self.client.post(reverse('reveal_birthday',args=[self.person.pk])).json()['date'],'03.02.2001')
        self.person.role='worker';self.person.save()
        self.assertNotContains(self.client.get(reverse('public_profile',args=[self.person.pk])),'03.02.2001')
        self.assertEqual(self.client.post(reverse('reveal_birthday',args=[self.person.pk])).json()['date'],'03.02.2001')
        response=self.client.get(reverse('admin_edit_user',args=[self.person.pk]))
        self.assertNotContains(response,'name="faculty"');self.assertContains(response,'2001-02-03')

    def test_school_parent_change_updates_club_even_without_request(self):
        club=Club.objects.create(name='Клуб',school=self.school)
        self.school.direction=None;self.school.save(update_fields=['direction'])
        club.refresh_from_db();self.assertIsNone(club.direction_id)

    def test_club_delete_requires_global_right_and_post_confirmation(self):
        club=Club.objects.create(name='Клуб');club.leaders.add(self.other)
        self.client.force_login(self.other)
        url=reverse('club_delete',args=[club.pk])
        self.assertEqual(self.client.post(url,{'confirm':'yes'}).status_code,403)
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(url).status_code,200)
        self.client.post(url,{})
        self.assertTrue(Club.objects.filter(pk=club.pk).exists())
        self.assertEqual(self.client.post(url,{'confirm':'yes'}).status_code,302)
        self.assertFalse(Club.objects.filter(pk=club.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())

    def test_profile_links_reject_script_urls_in_existing_data(self):
        from .social_links import social_url
        self.assertEqual(social_url('javascript:alert(1)'),'')
        self.assertEqual(social_url('data:text/html,test'),'')
        self.assertEqual(social_url('@aya_test','instagram'),'https://www.instagram.com/aya_test/')
        self.person.instagram='javascript:alert(1)';self.person.save()
        response=self.client.get(reverse('public_profile',args=[self.person.pk]))
        self.assertNotContains(response,'href="javascript:')

    def test_quick_award_keeps_club_and_parent_relationship(self):
        from .models import ContributionWork
        import uuid
        from django.utils import timezone
        club=Club.objects.create(name='Клуб',school=self.school)
        response=self.client.post(reverse('points_quick'),{'club':club.pk,'title':'Помощь клубу','date':timezone.localdate(),'points':5,'volunteers':[self.person.pk],'token':uuid.uuid4()})
        self.assertEqual(response.status_code,302)
        work=ContributionWork.objects.get();self.assertEqual(work.club,club)
        self.assertEqual(work.school,self.school);self.assertEqual(work.direction,self.direction)

    def test_role_training_opens_accessible_tabs_without_mutating_team(self):
        from .training import topics_for
        topics=topics_for(self.person)
        self.assertNotIn('rights',topics)
        self.assertEqual(topics['schools_editor']['group'],'work')
        self.client.force_login(self.person)
        before=list(self.school.members.values_list('pk',flat=True))
        for item in topics['schools_editor']['steps']:
            response=self.client.get(item['url'])
            self.assertEqual(response.status_code,200,item['url'])
            self.assertContains(response,'data-tour="'+item['target']+'"')
        self.assertEqual(list(self.school.members.values_list('pk',flat=True)),before)

    def test_staff_training_does_not_explain_student_enrollment(self):
        from .training import topics_for
        topics=topics_for(self.head)
        self.assertNotIn('event-join',[s['target'] for s in topics['events']['steps']])
        self.assertIn('Рабочий профиль',topics['profile']['title'])
        self.assertIn('staff_applications',topics)
