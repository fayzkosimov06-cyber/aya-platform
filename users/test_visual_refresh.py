import tempfile
from io import BytesIO
from datetime import timedelta
from PIL import Image
from django.test import TestCase, override_settings, Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from .models import User, Direction, School, SchoolTeacher, Club, JournalEntry
from .units import AboutDirection
from .journal import emit

class VisualRefreshTests(TestCase):
    def setUp(self):
        self.root=User.objects.create(username='root-refresh',is_superuser=True,qr_code='unused.png')
        self.head=User.objects.create(username='head-refresh',role='head_admin',is_approved=True,qr_code='unused.png')
        self.lead=User.objects.create(username='lead-refresh',is_approved=True,qr_code='unused.png')
        self.member=User.objects.create(username='member-refresh',is_approved=True,qr_code='unused.png')

    def test_leaders_are_not_repeated_and_membership_is_preserved(self):
        direction=Direction.objects.create(name='Направление')
        direction.user_set.add(self.lead,self.member);direction.leaders.add(self.lead)
        school=School.objects.create(name='Школа',direction=direction)
        school.members.add(self.lead,self.member)
        SchoolTeacher.objects.create(school=school,member=self.lead,name='Учитель')
        club=Club.objects.create(name='Клуб');club.members.add(self.lead,self.member);club.leaders.add(self.lead)
        for url,obj in [('direction_detail',direction),('school_detail',school),('club_detail',club)]:
            response=self.client.get(reverse(url,args=[obj.pk]))
            page=response.context['people' if url=='club_detail' else 'member_page']
            self.assertEqual([p.pk for p in page],[self.member.pk])
        self.assertTrue(direction.user_set.filter(pk=self.lead.pk).exists())
        self.assertTrue(school.members.filter(pk=self.lead.pk).exists())
        self.assertTrue(club.members.filter(pk=self.lead.pk).exists())

    def test_logo_upload_clear_and_format_validation(self):
        directory=self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=directory))
        stream=BytesIO();Image.new('RGBA',(120,60),(0,120,200,0)).save(stream,format='PNG')
        data={'name':'С логотипом','intro':'Команда','description':''}
        form=AboutDirection(data,{'logo':SimpleUploadedFile('logo.png',stream.getvalue(),content_type='image/png')})
        self.assertTrue(form.is_valid(),form.errors)
        obj=form.save();self.assertTrue(obj.logo)
        self.assertContains(self.client.get(reverse('direction_detail',args=[obj.pk])),obj.logo.url)
        bad=AboutDirection({**data,'name':'Плохой формат'},{'logo':SimpleUploadedFile('logo.html',stream.getvalue(),content_type='image/png')})
        self.assertFalse(bad.is_valid())
        clear=AboutDirection({**data,'logo-clear':'on'},instance=obj)
        self.assertTrue(clear.is_valid(),clear.errors);clear.save();obj.refresh_from_db();self.assertFalse(obj.logo)

    def test_cleanup_root_only_preview_csrf_and_confirmation(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get(reverse('journal_cleanup')).status_code,403)
        self.assertEqual(self.client.post(reverse('journal_cleanup')).status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.root)
        self.assertEqual(secure.post(reverse('journal_cleanup')).status_code,403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(reverse('journal_cleanup'),{'token':'forged','confirm':'yes'}).status_code,400)
        self.assertEqual(self.client.get(reverse('journal_cleanup'),{'start':'wrong'}).status_code,400)

    def test_cleanup_filtered_snapshot_retains_new_and_receipt(self):
        emit('view','public_profile','Просмотр',actor=self.member,private=True)
        emit('contact','public_profile','Фото',actor=self.lead,private=True)
        self.client.force_login(self.root)
        url=reverse('journal_cleanup')
        preview=self.client.get(url,{'actor':self.member.pk,'category':'view'})
        self.assertEqual(preview.context['count'],1)
        token=preview.context['token']
        emit('view','public_profile','Новый просмотр',actor=self.member,private=True)
        missing=self.client.post(url,{'token':token});self.assertEqual(missing.status_code,200)
        self.assertEqual(JournalEntry.objects.filter(actor=self.member,category='view').count(),2)
        response=self.client.post(url,{'token':token,'confirm':'yes'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(JournalEntry.objects.filter(actor=self.member,category='view').count(),1)
        self.assertTrue(JournalEntry.objects.filter(actor=self.lead,category='contact').exists())
        receipt=JournalEntry.objects.get(section='journal_cleanup')
        preview=self.client.get(url)
        self.client.post(url,{'token':preview.context['token'],'confirm':'yes'})
        self.assertTrue(JournalEntry.objects.filter(pk=receipt.pk).exists())

    def test_public_cleanup_cannot_remove_private_and_export_is_safe(self):
        emit('change','users.User','Общее',actor=self.member,private=False)
        emit('contact','public_profile','=private',actor=self.member,private=True)
        self.client.force_login(self.root)
        params={'actor':self.member.pk,'cleanup_mode':'public'}
        preview=self.client.get(reverse('journal_cleanup'),params)
        self.assertEqual(preview.context['count'],1)
        exported=self.client.get(reverse('journal_cleanup'),{**params,'export':'csv'})
        self.assertNotContains(exported,'=private')
        self.client.post(reverse('journal_cleanup'),{'token':preview.context['token'],'confirm':'yes'})
        self.assertTrue(JournalEntry.objects.filter(actor=self.member,private=True).exists())

    def test_administration_shows_only_staff(self):
        self.lead.role='president';self.lead.save()
        response=self.client.get(reverse('administration_page'))
        self.assertContains(response,self.head.username)
        self.assertNotContains(response,self.lead.username)
