from django.test import TestCase
from django.urls import reverse
from .models import AboutPage, AboutContactLink, Direction, HomePage, User


class HomepageTests(TestCase):
    def test_all_directions_menu_and_single_statistics(self):
        for i in range(17): Direction.objects.create(name=f'Direction {i}')
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['directions']),17)
        html=response.content.decode()
        self.assertLess(html.index('id="directions"'),html.index('id="events-title"'))
        for name in ['volunteer_list','administration_page','about_page','notifications'][:3]:
            self.assertContains(response,reverse(name))
        self.assertNotContains(response,'1000+')
        self.assertNotContains(response,'hp-stats')
        self.assertNotContains(response,'Новости')
        self.assertContains(response,'id="contacts"')

    def test_telegram_not_in_guest_or_candidate_html(self):
        about=AboutPage.objects.create(pk=1)
        AboutContactLink.objects.create(about=about,platform='telegram',label='TG',url='https://t.me/private_aya_example')
        AboutContactLink.objects.create(about=about,platform='instagram',label='Instagram',url='https://instagram.com/aya_example',requires_volunteer_access=True)
        response=self.client.get(reverse('home'))
        self.assertNotContains(response,'private_aya_example')
        self.assertContains(response,'instagram.com/aya_example')
        user=User.objects.create(username='candidate_home',candidate_approved=True,qr_code='unused.png')
        self.client.force_login(user)
        self.assertNotContains(self.client.get(reverse('home')),'private_aya_example')
        user.is_approved=True;user.volunteer_access=True;user.save()
        self.assertContains(self.client.get(reverse('home')),'private_aya_example')

    def test_editor_permissions_and_content(self):
        moderator=User.objects.create(username='home_mod',role='moderator',is_approved=True,qr_code='unused.png')
        self.client.force_login(moderator)
        self.assertEqual(self.client.post(reverse('home_manage'),{'quote_text':'No'}).status_code,403)
        moderator.role='worker';moderator.save()
        response=self.client.post(reverse('home_manage'),{'action':'save_quote','author_type':'external','text':'A real submitted quote','author_name':'Test author','author_role':'Volunteer'})
        self.assertEqual(response.status_code,302)
        self.assertContains(self.client.get(reverse('home')),'A real submitted quote')
        self.assertContains(self.client.get(reverse('home')),'Test author')

    def test_no_invented_quote_and_requires_attribution(self):
        self.assertNotContains(self.client.get(reverse('home')),'aya-quote-mark')
        from .home_views import HomeQuoteForm
        form=HomeQuoteForm({'author_type':'external','text':'Without author'})
        self.assertFalse(form.is_valid())
        self.assertIn('author_name',form.errors)
        self.assertContains(self.client.get(reverse('home')),'Здесь скоро появятся истории участников AYA')
