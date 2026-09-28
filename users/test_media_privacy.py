import tempfile
from datetime import date, timedelta
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from users.models import User, AboutPage, JournalEntry
from users.about_views import MainForm
from events.models import Event, EventVideo
from events.forms import EventVideoForm


def clip(name='clip.mp4',content=None):
    return SimpleUploadedFile(name,content or b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom',content_type='video/mp4')

class MediaPrivacyTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.settings=override_settings(MEDIA_ROOT=self.tmp.name);self.settings.enable()
        self.addCleanup(self.tmp.cleanup);self.addCleanup(self.settings.disable)
        self.head=User.objects.create(username='media-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.person=User.objects.create(username='media-person',is_approved=True,birth_date=date(2000,4,3),qr_code='unused.png')
        self.client.force_login(self.head)
        self.event=Event.objects.create(title='Отчёт',description='Событие',organizer=self.head,start_time=timezone.now()-timedelta(days=2),end_time=timezone.now()-timedelta(days=1),is_completed=True,is_approved=True,is_report_published=True)

    def test_date_reveal_no_initial_html_and_private_log(self):
        page=self.client.get(reverse('public_profile',args=[self.person.pk]))
        self.assertContains(page,'Показать дату');self.assertNotContains(page,'03.04.2000')
        url=reverse('reveal_birthday',args=[self.person.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        response=self.client.post(url)
        self.assertEqual(response.json()['date'],'03.04.2000')
        self.assertIn('no-store',response['Cache-Control'])
        row=JournalEntry.objects.get(category='contact')
        self.assertTrue(row.private);self.assertNotIn('2000',str(row.after))
        self.person.is_approved=False;self.person.save()
        self.client.force_login(User.objects.create(username='ordinary',is_approved=True,qr_code='unused.png'))
        self.assertEqual(self.client.post(url).status_code,404)

    def test_video_form_rejects_empty_both_invalid_header_and_size(self):
        self.assertFalse(EventVideoForm({}).is_valid())
        self.assertFalse(EventVideoForm({'video_url':'https://example.com/video'},{'video_file':clip()}).is_valid())
        self.assertFalse(EventVideoForm({}, {'video_file':clip(content=b'<html>not a video</html>')}).is_valid())
        self.assertFalse(EventVideoForm({}, {'video_file':clip(name='script.html')}).is_valid())
        self.assertFalse(EventVideoForm({'video_url':'javascript:alert(1)'}).is_valid())
        with override_settings(AYA_MAX_VIDEO_MB=0):
            self.assertFalse(EventVideoForm({}, {'video_file':clip()}).is_valid())

    def test_uploaded_event_video_and_link_render(self):
        url=reverse('event_report_edit',args=[self.event.pk])
        self.assertEqual(self.client.post(url,{'action':'add_video','title':'Наша команда','video_file':clip()}).status_code,302)
        video=EventVideo.objects.get(event=self.event)
        self.assertTrue(video.video_file.name.startswith('videos/'))
        page=self.client.get(reverse('event_detail',args=[self.event.pk]))
        self.assertContains(page,'<video controls');self.assertContains(page,'Наша команда')
        self.assertEqual(self.client.post(url,{'action':'add_video','title':'Внешний ролик','video_url':'https://youtu.be/dQw4w9WgXcQ'}).status_code,302)
        self.assertContains(self.client.get(reverse('event_detail',args=[self.event.pk])),'youtube-nocookie.com/embed/dQw4w9WgXcQ')
        self.event.is_report_published=False;self.event.save()
        self.assertNotContains(self.client.get(reverse('event_detail',args=[self.event.pk])),'<video controls')

    def test_video_requires_completed_event_and_correct_scope(self):
        url=reverse('event_report_edit',args=[self.event.pk])
        self.event.is_completed=False;self.event.save()
        self.assertEqual(self.client.post(url,{'action':'add_video','video_file':clip()}).status_code,403)
        self.event.is_completed=True;self.event.save()
        other=Event.objects.create(title='Другой',start_time=timezone.now(),end_time=timezone.now(),organizer=self.head)
        video=EventVideo.objects.create(event=other,video_url='https://example.com/video')
        self.assertEqual(self.client.post(url,{'action':'delete_video','video_id':video.pk}).status_code,404)
        self.client.force_login(self.person)
        self.assertEqual(self.client.post(url,{'action':'add_video','video_file':clip()}).status_code,403)
        self.assertEqual(EventVideo.objects.count(),1)

    def test_invalid_upload_displays_bound_form_errors(self):
        response=self.client.post(reverse('event_report_edit',args=[self.event.pk]),{'action':'add_video','title':'Сохранённое название','video_file':clip(content=b'bad')})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Сохранённое название')
        self.assertContains(response,'Содержимое не соответствует')
        self.assertFalse(EventVideo.objects.exists())

    def test_about_upload_and_remove_preserves_text(self):
        data={'kind':'main','action':'save','title':'Наша AYA','description':'История команды','mission_title':'Миссия','mission_text':'Помогаем','video_file':clip()}
        self.assertEqual(self.client.post(reverse('about_manage'),data).status_code,302)
        page=AboutPage.objects.get(pk=1)
        self.assertTrue(page.video_file)
        self.assertContains(self.client.get(reverse('about_page')),'<video controls')
        data.pop('video_file');data['video_file-clear']='on'
        self.assertEqual(self.client.post(reverse('about_manage'),data).status_code,302)
        page.refresh_from_db();self.assertFalse(page.video_file);self.assertEqual(page.description,'История команды')
