from io import BytesIO
from tempfile import TemporaryDirectory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from .models import HomePage, HomeSlide, HomeQuote, User


class HomeMediaTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.tmp.name);self.override.enable();self.addCleanup(self.override.disable)
        self.editor=User.objects.create(username='editor',role='worker',is_approved=True,qr_code='unused.png')
        self.member=User.objects.create(username='person',first_name='Author',is_approved=True,qr_code='unused.png')
        self.page=HomePage.objects.create(pk=1)
        self.client.force_login(self.editor)

    def post(self,**data):return self.client.post(reverse('home_manage'),data)

    def image(self,name):
        data=BytesIO();Image.new('RGB',(16,16),'blue').save(data,format='PNG')
        return SimpleUploadedFile(name,data.getvalue(),content_type='image/png')

    def test_upload_reorder_hide_replace_delete(self):
        self.post(action='upload',images=[self.image('a.png'),self.image('b.png')])
        first,second=list(self.page.slides.all());self.assertEqual(self.page.slides.count(),2)
        self.post(action='up',kind='slide',id=second.pk)
        self.assertEqual(list(self.page.slides.values_list('pk',flat=True)),[second.pk,first.pk])
        self.post(action='save_slide',id=first.pk,image=self.image('replaced.png'),caption='New photo')
        first.refresh_from_db();self.assertEqual(first.caption,'New photo')
        self.post(action='toggle',kind='slide',id=second.pk)
        response=self.client.get(reverse('home'));self.assertEqual(len(response.context['home_slides']),1)
        self.assertNotContains(response,second.image.url)
        self.post(action='delete',kind='slide',id=first.pk)
        self.assertFalse(HomeSlide.objects.filter(pk=first.pk).exists())
        self.assertContains(self.client.get(reverse('home')),'img/collage_2.jpg')

    def test_invalid_bulk_upload_does_not_save_partial_batch(self):
        response=self.post(action='upload',images=[self.image('valid.png'),SimpleUploadedFile('bad.png',b'not an image',content_type='image/png')])
        self.assertEqual(response.status_code,200);self.assertEqual(HomeSlide.objects.count(),0)

    def test_linked_and_external_quotes_modes_and_visibility(self):
        self.post(action='save_quote',author_type='member',member=self.member.pk,text='Our team matters')
        quote=HomeQuote.objects.get();self.assertEqual(quote.member,self.member)
        self.assertEqual(quote.author_url,reverse('public_profile',args=[self.member.pk]))
        self.post(action='save_quote',author_type='external',author_name='Scientist',text='A sourced quotation',source_url='https://example.org/source')
        self.post(action='settings',quotes_per_view=2)
        self.client.logout();response=self.client.get(reverse('home'))
        self.assertContains(response,'Our team matters');self.assertContains(response,'A sourced quotation')
        self.assertContains(response,'https://example.org/source')
        self.assertContains(response,'data-count="2"')
        self.client.force_login(self.editor)
        self.post(action='toggle',kind='quote',id=quote.pk)
        self.assertNotContains(self.client.get(reverse('home')),'Our team matters')
        self.post(action='delete',kind='quote',id=quote.pk)
        self.assertFalse(HomeQuote.objects.filter(pk=quote.pk).exists())

    def test_permissions_and_profile_validation(self):
        self.member.role='moderator';self.member.save();self.client.force_login(self.member)
        self.assertEqual(self.post(action='upload',images=[self.image('denied.png')]).status_code,403)
        self.assertEqual(HomeSlide.objects.count(),0)
        self.client.force_login(self.editor)
        pending=User.objects.create(username='pending_quote',qr_code='unused.png')
        response=self.post(action='save_quote',author_type='member',member=pending.pk,text='Invalid')
        self.assertEqual(response.status_code,200);self.assertEqual(HomeQuote.objects.count(),0)
        response=self.post(action='save_quote',author_type='external',author_name='External',text='X',source_url='javascript:alert(1)')
        self.assertEqual(response.status_code,200);self.assertEqual(HomeQuote.objects.count(),0)

    def test_editor_get_and_csrf(self):
        self.assertContains(self.client.get(reverse('home_manage')),'multiple')
        from django.test import Client
        client=Client(enforce_csrf_checks=True);client.force_login(self.editor)
        self.assertEqual(client.post(reverse('home_manage'),{'action':'settings','quotes_per_view':3}).status_code,403)
