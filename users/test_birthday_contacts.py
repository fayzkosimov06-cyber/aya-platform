from datetime import date, timedelta
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import User, Notification, BirthdayGreeting, JournalEntry
from .birthdays import upcoming, notify, occurrence

class BirthdayContactTests(TestCase):
    def setUp(self):
        self.person=User.objects.create(username='birthday-test',first_name='Алина',is_approved=True,birth_date=date(2000,9,27),phone='+992123456789',telegram='alina_test',instagram='@alina',qr_code='unused.png')
        self.viewer=User.objects.create(username='viewer',is_approved=True,qr_code='unused.png')
        self.head=User.objects.create(username='head',role='head_admin',qr_code='unused.png')
        self.root=User.objects.create(username='root',is_superuser=True,qr_code='unused.png')

    def test_phone_not_embedded_and_reveal_authorized(self):
        self.client.force_login(self.viewer)
        page=self.client.get(reverse('public_profile',args=[self.person.pk]))
        self.assertNotContains(page,self.person.phone)
        self.assertContains(page,'Показать номер')
        url=reverse('reveal_phone',args=[self.person.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        response=self.client.post(url)
        self.assertEqual(response.json()['phone'],self.person.phone)
        self.assertIn('no-store',response['Cache-Control'])
        entry=JournalEntry.objects.get(category='contact')
        self.assertEqual(entry.actor,self.viewer)
        self.assertEqual(entry.after['target_name'],'Алина')
        self.assertNotIn(self.person.phone,str(entry.after))
        self.person.phone_privacy='private';self.person.save()
        self.assertEqual(self.client.post(url).status_code,404)
        self.assertEqual(JournalEntry.objects.filter(category='contact').count(),1)

    def test_public_guest_phone_and_csrf(self):
        self.person.phone_privacy='public';self.person.save()
        response=self.client.post(reverse('reveal_phone',args=[self.person.pk]))
        self.assertEqual(response.status_code,200)
        self.assertIsNone(JournalEntry.objects.get(category='contact').actor)
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('reveal_phone',args=[self.person.pk])).status_code,403)

    def test_social_redirect_privacy_and_target(self):
        self.client.force_login(self.viewer)
        response=self.client.get(reverse('open_contact',args=[self.person.pk,'telegram']))
        self.assertRedirects(response,'https://t.me/alina_test',fetch_redirect_response=False)
        self.assertEqual(JournalEntry.objects.get(category='contact').after['network'],'telegram')
        self.person.telegram_privacy='private';self.person.save()
        self.assertEqual(self.client.get(reverse('open_contact',args=[self.person.pk,'telegram'])).status_code,404)
        self.person.instagram='javascript:alert(1)';self.person.save()
        self.assertEqual(self.client.get(reverse('open_contact',args=[self.person.pk,'instagram'])).status_code,404)

    def test_calendar_is_management_only_and_no_birth_year(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('birthday_calendar')).status_code,403)
        self.client.force_login(self.head)
        response=self.client.get(reverse('birthday_calendar'))
        self.assertContains(response,'Алина')
        self.assertNotContains(response,'2000')

    def test_notifications_once_and_tomorrow_today(self):
        self.assertEqual(notify(self.head,date(2026,9,26)),1)
        self.assertEqual(notify(self.head,date(2026,9,26)),0)
        self.assertEqual(notify(self.head,date(2026,9,27)),1)
        self.assertEqual(notify(self.viewer,date(2026,9,27)),0)
        self.assertEqual(Notification.objects.count(),2)
        self.assertTrue(Notification.objects.filter(message__startswith='Завтра').exists())
        self.assertTrue(Notification.objects.filter(message__startswith='Сегодня').exists())

    def test_leap_day_and_year_rollover(self):
        self.assertEqual(occurrence(date(2000,2,29),2027),date(2027,2,28))
        self.assertEqual(occurrence(date(2000,2,29),2028),date(2028,2,29))
        self.person.birth_date=date(2000,1,1);self.person.save()
        self.assertEqual(upcoming(date(2026,12,31))[0].birthday_days,1)

    @patch('users.birthdays.timezone.localdate',return_value=date(2026,9,27))
    def test_greeting_once_on_birthday_and_repeat_available(self, clock):
        self.client.force_login(self.person)
        response=self.client.get(reverse('my_profile'))
        self.assertContains(response,'data-auto="yes"')
        self.assertEqual(self.client.post(reverse('birthday_seen')).status_code,200)
        self.assertEqual(self.client.post(reverse('birthday_seen')).status_code,200)
        self.assertEqual(BirthdayGreeting.objects.count(),1)
        self.assertContains(self.client.get(reverse('my_profile')),'data-auto="no"')
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('birthday_seen')).status_code,403)

    def test_private_journal_unifies_actions_with_names(self):
        self.client.force_login(self.viewer)
        self.client.get(reverse('public_profile',args=[self.person.pk]))
        self.client.post(reverse('reveal_phone',args=[self.person.pk]))
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse('journal_private')).status_code,403)
        self.client.force_login(self.root)
        response=self.client.get(reverse('journal_private'),{'actor':self.viewer.pk,'view':'timeline'})
        self.assertContains(response,'Алина')
        self.assertContains(response,'Раскрыл номер телефона')
        self.assertContains(response,'Открыл')
        self.assertNotContains(response,self.person.phone)

    def test_missing_birthday_explicit_in_both_profiles(self):
        for person in [self.viewer,self.head]:
            self.client.force_login(person)
            self.assertContains(self.client.get(reverse('my_profile')),'Дата не указана')
