from django.test import TestCase
from django.urls import reverse
from django.template.loader import render_to_string
from .models import User, Direction, School


class DesignIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create(username='ordinary', first_name='Обычный', is_approved=True, qr_code='unused.png')
        cls.leader = User.objects.create(username='teamlead', first_name='Руководитель', is_approved=True, qr_code='unused.png')
        cls.head = User.objects.create(username='department', first_name='Начальник', role='head_admin', is_approved=True, qr_code='unused.png')
        cls.worker = User.objects.create(username='employee', first_name='Работник', role='worker', is_approved=True, qr_code='unused.png')
        cls.president = User.objects.create(username='president', first_name='Президент', role='president', is_approved=True, qr_code='unused.png')
        cls.direction = Direction.objects.create(name='Экология')
        cls.direction.leaders.add(cls.leader)
        cls.school = School.objects.create(name='Экошкола', direction=cls.direction)
        cls.leader.school_leader_of.add(cls.school)

    def test_volunteer_label_is_not_duplicated(self):
        content = render_to_string('users/partials/volunteer_card.html', {'volunteer': self.member})
        self.assertEqual(content.count('Волонтёр'), 1)
        self.assertIn('frame-volunteer', content)

    def test_combined_assignment_frame_and_unique_badges(self):
        content = render_to_string('users/partials/volunteer_card.html', {'volunteer': self.leader})
        self.assertIn('frame-combined', content)
        self.assertEqual(content.count('>Руководитель направления<'), 1)
        self.assertEqual(content.count('>Учитель школы<'), 1)
        self.assertNotIn('>Волонтёр<', content)

    def test_direction_filter_uses_membership_not_legacy_role(self):
        response = self.client.get(reverse('volunteer_list'), {'status': 'leader'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['volunteers']), [self.leader])

    def test_public_administration_is_employees_only(self):
        response = self.client.get(reverse('administration_page'))
        self.assertContains(response, reverse('public_profile', args=[self.head.pk]))
        self.assertContains(response, reverse('public_profile', args=[self.worker.pk]))
        for person in [self.member, self.leader, self.president]:
            self.assertNotContains(response, reverse('public_profile', args=[person.pk]))

    def test_render_changed_pages_for_manager_and_moderator(self):
        self.client.force_login(self.head)
        urls = [reverse(name) for name in ['admin_dashboard', 'user_management', 'moderator_dashboard', 'about_page', 'points_quick', 'volunteer_rating', 'unit_catalog', 'school_catalog', 'event_list', 'event_create']]
        urls += [reverse('direction_detail', args=[self.direction.pk]), reverse('school_detail', args=[self.school.pk]), reverse('direction_edit', args=[self.direction.pk]), reverse('public_profile', args=[self.leader.pk])]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        moderator = User.objects.create(username='moddesign', role='moderator', is_approved=True, qr_code='unused.png')
        self.client.force_login(moderator)
        response = self.client.get(reverse('moderator_dashboard'))
        self.assertContains(response, 'Кандидаты и визиты')
        self.assertNotContains(response, 'Открыть полный доступ')
        self.assertNotContains(response, '>Люди и назначения</a>')
