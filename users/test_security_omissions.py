"""Regressions for inconsistent read/write policies and bounded image uploads."""
from datetime import timedelta
from functools import lru_cache
from io import BytesIO
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from events.forms import EventCreateForm, EventReportForm, EventVideoForm
from events.models import Event, EventPhoto
from .about_views import MainForm
from .clubs import ClubForm
from .forms import AboutPageForm
from .home_views import HomeSlideForm, HomeQuoteForm
from .image_uploads import BoundedImageField, clean_image_batch
from .models import User, Direction, School, PermissionOverride, HomeSlide, AboutPage
from .units import AboutDirection, AboutSchool, TeacherForm, EventForm


@lru_cache(maxsize=2)
def png(size=(20,20)):
    stream=BytesIO();Image.new('RGB',size,'navy').save(stream,format='PNG')
    return stream.getvalue()


def upload(*,size=(20,20),padding=0):
    return SimpleUploadedFile('synthetic.png',png(size)+b'0'*padding,content_type='image/png')


class HomeVisibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.head=User.objects.create(username='omission-head',role='head_admin',is_approved=True,qr_code='unused.png')
        cls.pending=User.objects.create(username='omission-pending',qr_code='unused.png')
        cls.candidate=User.objects.create(username='omission-candidate',candidate_approved=True,qr_code='unused.png')
        cls.member=User.objects.create(username='omission-member',is_approved=True,qr_code='unused.png')
        start=timezone.now()+timedelta(days=1)
        cls.private=Event.objects.create(title='PRIVATE-HOME-EVENT',organizer=cls.head,start_time=start,end_time=start+timedelta(hours=2),is_approved=True)
        cls.public=Event.objects.create(title='PUBLIC-HOME-EVENT',organizer=cls.head,start_time=start,end_time=start+timedelta(hours=2),is_approved=True,is_public_for_guests=True)

    def check_home(self,person,private_visible):
        if person:self.client.force_login(person)
        response=self.client.get(reverse('home'))
        self.assertContains(response,self.public.title)
        if private_visible:self.assertContains(response,self.private.title)
        else:
            self.assertNotContains(response,self.private.title)
            self.assertNotIn(self.private,list(response.context['upcoming_events']))

    def test_guest_sees_only_public_announcements(self):self.check_home(None,False)
    def test_pending_account_sees_only_public_announcements(self):self.check_home(self.pending,False)
    def test_candidate_sees_only_public_announcements(self):self.check_home(self.candidate,False)
    def test_approved_volunteer_keeps_private_announcements(self):self.check_home(self.member,True)
    def test_department_staff_keeps_private_announcements(self):self.check_home(self.head,True)


class EventLinkPolicyTests(TestCase):
    def setUp(self):
        self.head=User.objects.create(username='link-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.person=User.objects.create(username='link-operator',is_approved=True,qr_code='unused.png')
        self.direction=Direction.objects.create(name='Link team')
        self.school=School.objects.create(name='Link school')
        start=timezone.now()+timedelta(days=1)
        self.event=Event.objects.create(title='Linked event',organizer=self.head,start_time=start,end_time=start+timedelta(hours=1),is_approved=True)
        self.event.aya_directions.add(self.direction);self.event.aya_schools.add(self.school)
        for code,relation,obj in [('directions','directions',self.direction),('schools','schools',self.school)]:
            rule=PermissionOverride.objects.create(user=self.person,code=code,enabled=True,scope='selected')
            getattr(rule,relation).add(obj)
        self.edit_rule=PermissionOverride.objects.create(user=self.person,code='events_edit',enabled=False)
        self.client.force_login(self.person)

    def path(self,kind):return reverse(kind+'_edit',args=[getattr(self,kind).pk])+'?tab=events'

    def test_denied_editor_cannot_unlink_direction_event(self):
        self.assertEqual(self.client.post(self.path('direction'),{'events':[]}).status_code,403)
        self.assertTrue(self.event.aya_directions.filter(pk=self.direction.pk).exists())

    def test_denied_editor_cannot_unlink_school_event(self):
        self.assertEqual(self.client.post(self.path('school'),{'events':[]}).status_code,403)
        self.assertTrue(self.event.aya_schools.filter(pk=self.school.pk).exists())

    def test_out_of_scope_editor_cannot_unlink_event(self):
        self.edit_rule.enabled=True;self.edit_rule.scope='selected';self.edit_rule.save()
        foreign=Direction.objects.create(name='Other allowed team');self.edit_rule.directions.add(foreign)
        self.assertEqual(self.client.post(self.path('direction'),{'events':[]}).status_code,403)
        self.assertTrue(self.event.aya_directions.filter(pk=self.direction.pk).exists())

    def test_unchanged_links_can_be_saved_without_event_edit(self):
        self.assertEqual(self.client.post(self.path('direction'),{'events':[self.event.pk]}).status_code,302)
        self.assertTrue(self.event.aya_directions.filter(pk=self.direction.pk).exists())

    def test_authorized_editor_can_unlink_without_deleting_event(self):
        self.edit_rule.enabled=True;self.edit_rule.scope='all';self.edit_rule.save()
        self.assertEqual(self.client.post(self.path('direction'),{'events':[]}).status_code,302)
        self.assertFalse(self.event.aya_directions.exists());self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.assertTrue(self.event.aya_schools.filter(pk=self.school.pk).exists())

    def test_form_rejects_unlink_even_without_middleware(self):
        form=EventForm({'events':[]},obj=self.direction,user=self.person)
        self.assertFalse(form.is_valid());self.assertIn('events',form.errors)

    def test_denied_editor_cannot_add_an_event_either(self):
        other=Direction.objects.create(name='Additional team')
        rule=PermissionOverride.objects.get(user=self.person,code='directions');rule.directions.add(other)
        self.assertEqual(self.client.post(reverse('direction_edit',args=[other.pk])+'?tab=events',{'events':[self.event.pk]}).status_code,403)
        self.assertFalse(self.event.aya_directions.filter(pk=other.pk).exists())


class PublicImageBoundaryTests(TestCase):
    def setUp(self):
        self.head=User.objects.create(username='image-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.school=School.objects.create(name='Image school')

    def test_all_editor_image_fields_share_bounded_validation(self):
        forms=[(EventCreateForm(),('cover_image',)),(EventVideoForm(),('poster',)),
            (MainForm(),('video_poster',)),(AboutPageForm(),('video_poster',)),
            (HomeSlideForm(),('image',)),(HomeQuoteForm(),('photo',)),
            (AboutDirection(),('cover','logo')),(AboutSchool(user=self.head),('cover','logo')),
            (TeacherForm(school=self.school,user=self.head),('photo',)),
            (ClubForm(user=self.head),('cover','logo'))]
        for form,names in forms:
            for name in names:
                with self.subTest(form=type(form).__name__,field=name):
                    self.assertIsInstance(form.fields[name],BoundedImageField)
                    with self.assertRaisesMessage(ValidationError,'8 МБ'):form.fields[name].clean(upload(padding=9*1024*1024))

    def test_size_limit_rejects_before_image_decoder(self):
        with patch('PIL.Image.open') as decoder:
            with self.assertRaisesMessage(ValidationError,'8 МБ'):BoundedImageField().clean(upload(padding=9*1024*1024))
            decoder.assert_not_called()

    def test_small_compressed_file_with_excessive_pixels_is_rejected(self):
        file=upload(size=(6000,4000));self.assertLess(file.size,100000)
        with self.assertRaisesMessage(ValidationError,'20 миллионов'):BoundedImageField().clean(file)

    def test_valid_images_and_optional_clear_keep_working(self):
        field=BoundedImageField(required=False)
        self.assertEqual(field.clean(upload()).image.size,(20,20))
        self.assertIsNone(field.clean(None));self.assertIs(field.clean(False),False)

    def test_misleading_extension_and_invalid_content_still_rejected(self):
        for file in [SimpleUploadedFile('bad.png',b'not an image'),SimpleUploadedFile('payload.html',png())]:
            with self.assertRaises(ValidationError):BoundedImageField().clean(file)

    def test_batch_file_count_rejected_before_processing_files(self):
        with self.assertRaisesMessage(ValidationError,'20 фотографий'):clean_image_batch([upload() for _ in range(21)])

    def test_batch_total_bytes_are_limited(self):
        with self.assertRaisesMessage(ValidationError,'32 МБ'):clean_image_batch([upload(padding=7*1024*1024) for _ in range(5)])

    def test_multiple_report_upload_validates_every_file(self):
        event=self.event()
        form=EventReportForm({'report_text':'Unchanged'}, {'photos':[upload(),SimpleUploadedFile('bad.png',b'not image')]},instance=event)
        self.assertFalse(form.is_valid());self.assertIn('photos',form.errors)

    def event(self):
        start=timezone.now()
        return Event.objects.create(title='Image event',organizer=self.head,start_time=start,end_time=start+timedelta(hours=1),report_text='Original')

    def test_invalid_report_batch_leaves_report_and_storage_unchanged(self):
        event=self.event();self.client.force_login(self.head)
        with patch('django.core.files.storage.FileSystemStorage._save') as save:
            response=self.client.post(reverse('event_edit',args=[event.pk])+'?tab=report',{'action':'save_report','report_text':'Modified','photos':[upload() for _ in range(21)]})
            self.assertEqual(response.status_code,200);save.assert_not_called()
        event.refresh_from_db();self.assertEqual(event.report_text,'Original');self.assertFalse(EventPhoto.objects.exists())

    def test_valid_report_batch_is_saved(self):
        event=self.event();self.client.force_login(self.head)
        response=self.client.post(reverse('event_edit',args=[event.pk])+'?tab=report',{'action':'save_report','report_text':'New report','photos':[upload(),upload()]})
        self.assertEqual(response.status_code,302);self.assertEqual(event.photos.count(),2)
        event.refresh_from_db();self.assertEqual(event.report_text,'New report')

    def test_home_batch_rejection_is_atomic(self):
        self.client.force_login(self.head)
        with patch('django.core.files.storage.FileSystemStorage._save') as save:
            response=self.client.post(reverse('home_manage'),{'action':'upload','images':[upload(),SimpleUploadedFile('bad.png',b'bad')]})
            self.assertEqual(response.status_code,200);save.assert_not_called()
        self.assertFalse(HomeSlide.objects.exists())

    def test_valid_home_batch_is_saved(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.post(reverse('home_manage'),{'action':'upload','images':[upload(),upload()]}).status_code,302)
        self.assertEqual(HomeSlide.objects.count(),2)

    def test_standard_admin_uses_the_same_image_limits(self):
        request=RequestFactory().get('/superadmin/');request.user=self.head
        for model,name in [(Direction,'cover'),(School,'logo'),(AboutPage,'video_poster')]:
            form=admin.site._registry[model].get_form(request)
            self.assertIsInstance(form.base_fields[name],BoundedImageField)


class EditorMalformedIdentifierTests(TestCase):
    def setUp(self):
        self.head=User.objects.create(username='editor-id-head',role='head_admin',is_approved=True,qr_code='unused.png')
        self.direction=Direction.objects.create(name='ID team');self.school=School.objects.create(name='ID school')
        self.client.force_login(self.head)

    def test_invalid_get_identifiers_return_404(self):
        for value in ['bad','-1','0','²','١٢','9'*100]:
            for path,data in [(reverse('home_manage'),{'slide':value}),(reverse('home_manage'),{'quote':value}),
                (reverse('about_manage'),{'kind':'value','id':value}),(reverse('admin_about_manage'),{'kind':'contact','id':value})]:
                with self.subTest(path=path,data=data):self.assertEqual(self.client.get(path,data).status_code,404)

    def test_invalid_post_identifiers_cannot_mutate_editor_objects(self):
        for value in ['bad','-1','0','²','١٢','9'*100]:
            for route,data in [('home_manage',{'action':'delete','kind':'slide','id':value}),
                ('home_manage',{'action':'save_quote','id':value}),('about_manage',{'action':'delete','kind':'value','id':value})]:
                with self.subTest(route=route,data=data):self.assertEqual(self.client.post(reverse(route),data).status_code,404)

    def test_invalid_legacy_assignment_ids_return_404(self):
        for route,obj,key in [('assign_direction_leader',self.direction,'leader'),('assign_school_leader',self.school,'leader_id')]:
            for value in ['bad','²','9'*100]:
                self.assertEqual(self.client.post(reverse(route,args=[obj.pk]),{key:value}).status_code,404)
        self.assertFalse(self.direction.leaders.exists());self.assertFalse(self.school.leaders.exists())
