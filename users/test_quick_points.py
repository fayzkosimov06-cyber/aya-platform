import uuid
from datetime import date
from django.test import TestCase
from django.urls import reverse
from .models import User, ContributionAward, ContributionWork

class QuickPointsTests(TestCase):
    def setUp(self):
        self.staff=User.objects.create(username='worker',role='worker',is_approved=True,qr_code='unused.png')
        self.member=User.objects.create(username='member',is_approved=True,qr_code='unused.png')
        self.client.force_login(self.staff)
        self.data={'title':'Помощь библиотеке','date':'2026-01-02','points':'10','volunteers':[self.member.pk],'token':str(uuid.uuid4())}
        self.url=reverse('points_quick')

    def test_save_without_rules_and_repeated_post(self):
        response=self.client.post(self.url,self.data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(ContributionAward.objects.get().points,10)
        self.client.post(self.url,self.data)
        self.assertEqual(ContributionAward.objects.count(),1)
        self.assertEqual(ContributionWork.objects.count(),1)
        self.assertContains(self.client.get(response.url),'Помощь библиотеке')

    def test_errors_retain_selection(self):
        self.data['points']='0'
        response=self.client.post(self.url,self.data)
        self.assertContains(response,'Начисление не сохранено')
        self.assertContains(response,'Помощь библиотеке')
        self.assertIn(str(self.member.pk),response.context['selected'])
        self.assertFalse(ContributionAward.objects.exists())

    def test_preselect_and_pages(self):
        response=self.client.get(self.url,{'member':self.member.pk})
        self.assertIn(str(self.member.pk),response.context['selected'])
        self.assertContains(response,'people-search')
        for name in ['points_works','points_kinds','volunteer_rating']:
            self.assertEqual(self.client.get(reverse(name)).status_code,200)
        profile=self.client.get(reverse('public_profile',args=[self.member.pk]))
        self.assertContains(profile,'Отметить помощь')
        self.assertNotContains(profile,'Архив старых оценок')

    def test_existing_work_and_duplicate(self):
        work=ContributionWork.objects.create(title='Shared',date=date(2026,1,1),created_by=self.staff)
        self.data['work']=work.pk;self.data['title']=''
        self.client.post(self.url,self.data)
        self.data['token']=str(uuid.uuid4());self.client.post(self.url,self.data)
        self.assertEqual(ContributionAward.objects.count(),1)
        self.assertEqual(ContributionAward.objects.get().work.date,date(2026,1,1))

    def test_permission_and_empty_selection(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(self.url,self.data).status_code,403)
        self.client.force_login(self.staff);self.data['volunteers']=[]
        response=self.client.post(self.url,self.data)
        self.assertEqual(response.status_code,200)
        self.assertFalse(ContributionWork.objects.exists())
