"""Query budgets and security boundaries for page performance improvements."""
from datetime import date
from unittest.mock import patch
from django.db import connection
from django.db.models import prefetch_related_objects
from django.test import TestCase, RequestFactory
from django.test.utils import CaptureQueriesContext
from .models import User, Club
from .permissions import request_context, assignment_flags, allowed, rank
from .birthdays import upcoming, context, notify


class PagePerformanceTests(TestCase):
    def setUp(self):
        self.person=User.objects.create(username='speed-person',is_approved=True,qr_code='unused.png')

    def request(self,method='get'):
        request=getattr(RequestFactory(),method)('/');request.user=self.person
        return request

    def test_assignment_reads_reused_only_within_get(self):
        club=Club.objects.create(name='Temporary team');club.leaders.add(self.person)
        token=request_context.set(self.request())
        try:
            self.assertEqual(assignment_flags(self.person),(False,False,True))
            with self.assertNumQueries(0):
                self.assertEqual(assignment_flags(self.person),(False,False,True))
        finally:request_context.reset(token)
        club.leaders.remove(self.person)
        token=request_context.set(self.request())
        try:self.assertEqual(assignment_flags(self.person),(False,False,False))
        finally:request_context.reset(token)

    def test_post_permissions_ignore_get_and_prefetch_caches(self):
        club=Club.objects.create(name='Removed responsibility');club.leaders.add(self.person)
        prefetch_related_objects([self.person],'directions_led','school_leader_of','schoolteacher_set','clubs_led')
        token=request_context.set(self.request())
        try:self.assertTrue(allowed(self.person,'clubs'))
        finally:request_context.reset(token)
        club.leaders.remove(self.person)
        token=request_context.set(self.request('post'))
        try:
            self.assertFalse(allowed(self.person,'clubs'))
            self.assertEqual(rank(self.person),10)
        finally:request_context.reset(token)

    def test_higher_ranks_do_not_query_lower_appointments(self):
        for role,value in [('president',60),('worker',80),('head_admin',90),('moderator',50)]:
            self.person.role=role
            with self.assertNumQueries(0):self.assertEqual(rank(self.person),value)

    def test_volunteer_catalog_query_count_does_not_grow_per_person(self):
        self.client.force_login(self.person)
        with CaptureQueriesContext(connection) as first:
            self.assertEqual(self.client.get('/volunteers/').status_code,200)
        User.objects.bulk_create([User(username='speed-extra-'+str(i),is_approved=True,qr_code='unused.png') for i in range(30)])
        with CaptureQueriesContext(connection) as many:
            response=self.client.get('/volunteers/')
        self.assertContains(response,'speed-extra-29')
        self.assertLessEqual(len(many),len(first)+2)
        self.assertLessEqual(len(many),20)

    def test_birthday_context_skips_queries_outside_actual_birthday(self):
        self.person.birth_date=date(2000,1,2)
        with patch('users.birthdays.timezone.localdate',return_value=date(2026,1,1)):
            with self.assertNumQueries(0):self.assertFalse(context(self.request())['birthday_today'])

    def test_birthday_window_handles_year_boundary_and_leap_days(self):
        self.person.birth_date=date(2000,1,1);self.person.save()
        leap=User.objects.create(username='leap-speed',is_approved=True,birth_date=date(2000,2,29),qr_code='unused.png')
        self.assertEqual([p.pk for p in upcoming(date(2026,12,31),window_days=1)],[self.person.pk])
        self.assertEqual([(p.pk,p.birthday_days) for p in upcoming(date(2025,2,27),window_days=1)],[(leap.pk,1)])
        self.assertEqual([(p.pk,p.birthday_days) for p in upcoming(date(2024,2,28),window_days=1)],[(leap.pk,1)])

    def test_notification_window_does_not_load_unrelated_volunteer_profiles(self):
        head=User.objects.create(username='speed-head',role='head_admin',qr_code='unused.png')
        self.person.birth_date=date(2000,1,1);self.person.save()
        User.objects.bulk_create([User(username='unrelated-'+str(i),is_approved=True,birth_date=date(2000,6,7),qr_code='unused.png') for i in range(30)])
        with CaptureQueriesContext(connection) as captured:self.assertEqual(notify(head,date(2026,12,31)),1)
        reads=[q['sql'] for q in captured if 'FROM "users_user"' in q['sql']]
        self.assertEqual(len(reads),1)
        self.assertIn('django_date_extract',reads[0])
        self.assertNotIn('"photo"',reads[0])

    def test_common_template_assets_are_same_origin(self):
        response=self.client.get('/')
        self.assertNotContains(response,'cdn.jsdelivr.net')
        self.assertNotContains(response,'cdnjs.cloudflare.com')
        self.assertNotContains(response,'code.jquery.com')
        self.assertContains(response,'/static/vendor/bootstrap/5.3.3/bootstrap.min.css')

    def test_profile_uses_complete_name_in_canonical_order_and_prioritizes_photo(self):
        for surname,given,patronymic,expected in [
            ('Каримов','Искандар','Саидович','Каримов Искандар Саидович'),
            ('Каримов','Искандар','','Каримов Искандар'),
            ('','Искандар','Саидович','Искандар Саидович'),
            ('','','','speed-person'),
        ]:
            self.person.last_name=surname;self.person.first_name=given;self.person.patronymic=patronymic;self.person.save()
            response=self.client.get('/profile/'+str(self.person.pk)+'/')
            self.assertContains(response,'<h1>'+expected+'</h1>',html=True)
            self.assertContains(response,'loading="eager" fetchpriority="high"')
