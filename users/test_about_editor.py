from django.test import TestCase
from django.urls import reverse
from .models import User,AboutPage,AboutValueBlock,AboutStatItem,AboutContactLink,AboutExtraBlock,School
from .about_content import actual_counts


class AboutEditorTests(TestCase):
    def setUp(self):
        self.page=AboutPage.objects.create(pk=1)
        self.editor=User.objects.create(username='about_worker',role='worker',is_approved=True,qr_code='unused.png')
        self.client.force_login(self.editor)

    def post(self,kind='main',**data):return self.client.post(reverse('about_manage'),{'kind':kind,**data})

    def test_main_validation_and_single_editor(self):
        response=self.post(action='save',title='About AYA',description='Our association',mission_title='Mission',mission_text='A'*5000,email='bad',video_url='',address='')
        self.assertEqual(response.status_code,200);self.page.refresh_from_db();self.assertNotEqual(self.page.title,'About AYA')
        response=self.post(action='save',title='About AYA',description='Our association',mission_title='Mission',mission_text='A'*5000,email='aya@example.org',video_url='',address='City')
        self.assertEqual(response.status_code,302)
        self.assertContains(self.client.get(reverse('about_page')),'Our association')
        self.assertEqual(self.client.get(reverse('about_page_edit')).url,reverse('about_manage'))

    def test_blocks_crud_and_order(self):
        for kind,model in [('value',AboutValueBlock),('extra',AboutExtraBlock)]:
            for name in ['First','Second']:
                self.post(kind,action='save',title=name,text='Description',icon='fa-solid fa-heart')
            first,second=list(model.objects.order_by('order','id'))
            self.post(kind,action='up',id=second.pk)
            self.assertEqual(model.objects.order_by('order','id').first().pk,second.pk)
            self.post(kind,action='toggle',id=first.pk)
            first.refresh_from_db();self.assertFalse(first.is_active)
            self.post(kind,action='save',id=second.pk,title='Changed',text='New text',icon='fa-solid fa-leaf')
            second.refresh_from_db();self.assertEqual(second.title,'Changed')
            self.post(kind,action='delete',id=first.pk)
            self.assertFalse(model.objects.filter(pk=first.pk).exists())

    def test_manual_and_auto_counts_shared_by_both_pages(self):
        User.objects.create(username='vol',is_approved=True,is_active_volunteer_title=True,qr_code='unused.png')
        self.post('stat',action='save',source='manual',number='123+',label='Custom',icon='fa-solid fa-users')
        self.post('stat',action='save',source='workers',label='Staff count',icon='fa-solid fa-users')
        self.assertEqual(AboutStatItem.objects.count(),2)
        home=self.client.get(reverse('home'));about=self.client.get(reverse('about_page'))
        self.assertEqual(home.context['home_stats'],about.context['stat_items'])
        self.assertEqual(home.context['home_stats'][0]['number'],'123+')
        self.assertEqual(home.context['home_stats'][1]['number'],1)
        for item in AboutStatItem.objects.all():self.post('stat',action='toggle',id=item.pk)
        self.assertEqual(self.client.get(reverse('home')).context['home_stats'],[])

    def test_counts_exclude_candidate_and_superuser_and_distinct_school_heads(self):
        User.objects.create(username='cand',candidate_approved=True,qr_code='unused.png')
        User.objects.create(username='root',is_superuser=True,is_approved=True,qr_code='unused.png')
        leader=User.objects.create(username='leader',role='leader',is_approved=True,qr_code='unused.png')
        leader.school_leader_of.add(School.objects.create(name='School A'),School.objects.create(name='School B'))
        counts=actual_counts();self.assertEqual(counts['volunteers'],0);self.assertEqual(counts['workers'],1);self.assertEqual(counts['leaders'],1);self.assertEqual(counts['school_leaders'],1)

    def test_contact_policy_shared_and_hidden(self):
        self.post('contact',action='save',platform='telegram',url='@aya_private_test',label='Telegram')
        self.post('contact',action='save',platform='instagram',url='@aya_public_test',requires_volunteer_access='on',label='Instagram')
        tg=AboutContactLink.objects.get(platform='telegram');ig=AboutContactLink.objects.get(platform='instagram')
        self.assertTrue(tg.requires_volunteer_access);self.assertFalse(ig.requires_volunteer_access)
        self.client.logout()
        for route in ['home','about_page']:
            response=self.client.get(reverse(route));self.assertNotContains(response,'aya_private_test');self.assertContains(response,'aya_public_test')
        self.client.force_login(self.editor);self.post('contact',action='toggle',id=ig.pk)
        for route in ['home','about_page']:self.assertNotContains(self.client.get(reverse(route)),'aya_public_test')

    def test_permissions(self):
        moderator=User.objects.create(username='about_mod',role='moderator',qr_code='unused.png')
        self.client.force_login(moderator)
        self.assertEqual(self.post('stat',action='save',source='manual',number='2',label='No').status_code,403)
        self.assertEqual(AboutStatItem.objects.count(),0)

    def test_contact_validation_and_icon_picker(self):
        self.post('contact',action='save',platform='custom',label='Invalid',url='javascript:alert(1)')
        self.assertEqual(AboutContactLink.objects.count(),0)
        response=self.client.get(reverse('about_manage')+'?kind=value')
        self.assertContains(response,'about-icon-picker')
        self.assertContains(response,'type="radio"')
