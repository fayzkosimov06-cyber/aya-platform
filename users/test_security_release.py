from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from events.models import Event, EventHero
from .models import User, StaffApplication


class EditorIdentifierTests(TestCase):
    def setUp(self):
        self.head=User.objects.create(username='release-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.worker=User.objects.create(username='release-worker',role='worker',is_approved=True,qr_code='unused.png')
        self.member=User.objects.create(username='release-member',is_approved=True,qr_code='unused.png')
        self.applicant=User.objects.create(username='release-applicant',qr_code='unused.png')
        self.application=StaffApplication.objects.create(user=self.applicant,requested_role='worker')
        self.event=Event.objects.create(title='Release event',organizer=self.worker,start_time=timezone.now()-timedelta(days=2),end_time=timezone.now()-timedelta(days=1),is_approved=True,is_completed=True)
        self.event.participants.add(self.member)
        self.hero=EventHero.objects.create(event=self.event,user=self.member,role_name='Synthetic role')

    def test_malformed_editor_ids_return_404_without_changing_data(self):
        self.client.force_login(self.head)
        for value in ['', 'not-a-number','-1','0','9'*80,'9223372036854775808','١٢']:
            for path,data in [
                (reverse('event_edit',args=[self.event.pk])+'?tab=report',{'action':'delete_role','hero_id':value}),
                (reverse('event_edit',args=[self.event.pk])+'?tab=report',{'action':'delete_video','video_id':value}),
                (reverse('staff_applications'),{'action':'approve','application':value})]:
                with self.subTest(value=value,path=path):self.assertEqual(self.client.post(path,data).status_code,404)
        self.assertTrue(EventHero.objects.filter(pk=self.hero.pk).exists())
        self.application.refresh_from_db();self.assertEqual(self.application.status,'pending')

    def test_valid_role_delete_still_works_and_cannot_delete_other_events_role(self):
        self.client.force_login(self.worker)
        other=Event.objects.create(title='Other',organizer=self.head,start_time=timezone.now(),end_time=timezone.now())
        foreign=EventHero.objects.create(event=other,user=self.member,role_name='Other')
        url=reverse('event_edit',args=[self.event.pk])+'?tab=report'
        self.assertEqual(self.client.post(url,{'action':'delete_role','hero_id':foreign.pk}).status_code,404)
        self.assertTrue(EventHero.objects.filter(pk=foreign.pk).exists())
        self.assertEqual(self.client.post(url,{'action':'delete_role','hero_id':self.hero.pk}).status_code,302)
        self.assertFalse(EventHero.objects.filter(pk=self.hero.pk).exists())

    def test_staff_application_still_requires_authority(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(reverse('staff_applications'),{'action':'approve','application':self.application.pk}).status_code,403)
        self.client.force_login(self.head)
        self.assertEqual(self.client.post(reverse('staff_applications'),{'action':'approve','application':self.application.pk}).status_code,302)
        self.application.refresh_from_db();self.assertEqual(self.application.status,'approved')
