from datetime import timedelta
from importlib import import_module
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import User, JournalEntry, ContributionKind, ContributionWork, ContributionAward, Direction, School, Club
from .journal import emit
from .journal_keys import subject_key

class PhotoJournalRatingTests(TestCase):
    def setUp(self):
        self.viewer=User.objects.create(username='reader',first_name='Читатель',is_approved=True,qr_code='unused.png')
        self.person=User.objects.create(username='person',first_name='Алина',is_approved=True,photo='photos/portrait.png',qr_code='unused.png')
        self.root=User.objects.create(username='root',is_superuser=True,qr_code='unused.png')

    def test_photo_access_and_exactly_one_private_record_per_click(self):
        self.client.force_login(self.viewer)
        url=reverse('open_profile_photo',args=[self.person.pk])
        self.assertEqual(self.client.get(url).status_code,405)
        for _ in range(2):
            response=self.client.post(url)
            self.assertEqual(response.json()['url'],self.person.photo.url)
            self.assertIn('no-store',response['Cache-Control'])
        rows=JournalEntry.objects.filter(category='contact',after__network='photo')
        self.assertEqual(rows.count(),2)
        self.assertTrue(all(r.private and r.actor_id==self.viewer.pk and r.subject_key==f'users.User:{self.person.pk}' for r in rows))
        self.assertContains(self.client.get(reverse('public_profile',args=[self.person.pk])),'data-photo-endpoint')
        self.person.photo='';self.person.save()
        self.assertEqual(self.client.post(url).status_code,404)
        self.assertNotContains(self.client.get(reverse('public_profile',args=[self.person.pk])),'data-photo-endpoint')

    def test_photo_guest_csrf_and_hidden_accounts(self):
        url=reverse('open_profile_photo',args=[self.person.pk])
        self.assertEqual(Client(enforce_csrf_checks=True).post(url).status_code,403)
        for client in (self.client,Client()):self.assertEqual(client.post(url).status_code,200)
        keys=list(JournalEntry.objects.filter(category='contact').values_list('actor_key',flat=True))
        self.assertEqual(len(set(keys)),2)
        self.assertTrue(all(k.startswith('guest:') for k in keys))
        self.person.is_approved=False;self.person.save()
        self.assertEqual(self.client.post(url).status_code,404)
        self.root.photo='photos/root.png';self.root.save()
        self.assertEqual(self.client.post(reverse('open_profile_photo',args=[self.root.pk])).status_code,404)

    def test_group_keeps_visits_contacts_and_exact_times(self):
        for category,network in [('view',None),('view',None),('contact','photo'),('contact','telegram'),('contact','phone')]:
            emit(category,'public_profile','Открыл',object_id=self.person.pk,actor=self.viewer,after={'target_name':str(self.person),**({'network':network} if network else {})},private=True)
        self.client.force_login(self.root)
        response=self.client.get(reverse('journal_private'),{'actor':self.viewer.pk})
        bundle=list(response.context['bundles'])[0]
        self.assertEqual(len(response.context['bundles']),1)
        self.assertEqual(bundle['count'],5)
        self.assertEqual({c['label']:c['count'] for c in bundle['counts']},{'Просмотры':2,'Фотография':1,'Telegram':1,'Телефон':1})
        details=self.client.get(reverse('journal_private'),{'actor':self.viewer.pk,'bundle':bundle['token'],'until':response.context['until']})
        self.assertEqual(len(details.context['entries']),5)
        for row in details.context['entries']:self.assertContains(details,timezone.localtime(row.created_at).strftime('%H:%M:%S'))
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('journal_private'),{'bundle':bundle['token']}).status_code,403)

    def test_group_days_targets_and_snapshot_pagination(self):
        for _ in range(43):emit('view','public_profile','Открыл',object_id=self.person.pk,actor=self.viewer,private=True)
        first=JournalEntry.objects.order_by('pk').first()
        JournalEntry.objects.filter(pk=first.pk).update(created_at=timezone.now()-timedelta(days=1))
        emit('view','public_profile','Открыл',object_id=self.viewer.pk,actor=self.viewer,private=True)
        self.client.force_login(self.root)
        response=self.client.get(reverse('journal_private'),{'actor':self.viewer.pk})
        self.assertEqual(len(response.context['bundles']),3)
        group=next(g for g in response.context['bundles'] if g['count']==42)
        params={'actor':self.viewer.pk,'bundle':group['token'],'until':response.context['until']}
        first=self.client.get(reverse('journal_private'),params)
        emit('view','public_profile','Открыл',object_id=self.person.pk,actor=self.viewer,private=True)
        second=self.client.get(reverse('journal_private'),{**params,'detail_page':2})
        self.assertEqual(len(first.context['entries']),40)
        self.assertEqual(len(second.context['entries']),2)
        self.assertFalse(set(e.pk for e in first.context['entries']) & set(e.pk for e in second.context['entries']))
        self.assertEqual(self.client.get(reverse('journal_private'),{'bundle':'forged'}).status_code,404)

    def test_public_journal_does_not_leak_private_bundle(self):
        emit('contact','public_profile','Открыл',object_id=self.person.pk,actor=self.viewer,after={'network':'photo'},private=True)
        emit('change','users.User','Изменено',object_id=self.person.pk,actor=self.viewer,after={'first_name':'Алина'},private=False)
        self.client.force_login(self.root)
        private=self.client.get(reverse('journal_private'),{'actor':self.viewer.pk})
        token=list(private.context['bundles'])[0]['token']
        public=self.client.get(reverse('audit_log'),{'actor':self.viewer.pk,'bundle':token})
        self.assertEqual(len(public.context['entries']),1)
        self.assertEqual(list(public.context['entries'])[0].category,'change')

    def test_migration_keys_match_runtime_for_old_records(self):
        frozen=import_module('users.migrations.0049_journalentry_actor_key_journalentry_subject_key').subject_key
        for args in [('public_profile','12',{}, {},2),('my_profile','',{}, {},2),('anything','',{}, {'path':'/profile/12/'},2),('users.ContributionAward','4',{}, {'work':'9'},2)]:
            self.assertEqual(frozen(*args),subject_key(*args))
        self.assertEqual(subject_key('anything','',{}, {'path':'/profile/12/'},2),'users.User:12')

    def seed_points(self):
        kind=ContributionKind.objects.create(name='Помощь',points=100)
        work=ContributionWork.objects.create(title='Общая работа',date=timezone.localdate())
        people=[]
        for i,n in enumerate([100,100,100,100,90,80,0]):
            person=User.objects.create(username=f'rank{i}',last_name=f'Участник {i}',is_approved=True,qr_code='unused.png')
            if n:ContributionAward.objects.create(work=work,member=person,kind=kind,points=n)
            people.append(person)
        self.client.force_login(people[0])
        return kind,work,people

    def test_dense_podium_ties_search_and_own_result(self):
        kind,work,people=self.seed_points()
        response=self.client.get(reverse('volunteer_rating'),{'period':'all'})
        self.assertEqual([r['place'] for r in response.context['rows']],[1,1,1,1,2,3])
        podium=response.context['podium'];gold=next(g for g in podium if g['place']==1)
        self.assertEqual((gold['count'],len(gold['rows']),len(gold['extra'])),(4,3,1))
        self.assertEqual(response.context['my_rank']['shared'],3)
        result=self.client.get(reverse('volunteer_rating'),{'q':'rank5','period':'all'})
        self.assertEqual(list(result.context['rows'])[0]['place'],3)
        self.assertEqual(result.context['my_rank']['place'],1)
        self.assertContains(result,reverse('rating_history',args=[people[5].pk]))

    def test_team_scope_counts_work_and_history_not_membership(self):
        kind,work,people=self.seed_points()
        direction=Direction.objects.create(name='Экология')
        school=School.objects.create(name='Школа',direction=direction)
        club=Club.objects.create(name='Клуб',school=school,direction=direction)
        work.club=club;work.save()
        other=ContributionWork.objects.create(title='Другая работа',date=timezone.localdate())
        ContributionAward.objects.create(work=other,member=people[0],kind=kind,points=1000)
        for field,team in [('direction',direction),('school',school),('club',club)]:
            params={field:team.pk,'period':'all'}
            page=self.client.get(reverse('volunteer_rating'),params)
            self.assertEqual(page.context['my_rank']['points'],100)
            history=self.client.get(reverse('rating_history',args=[people[0].pk]),params)
            self.assertEqual(history.context['total'],100)
            self.assertNotContains(history,'Другая работа')
        ContributionAward.objects.filter(member=people[0],work=work).update(revoked=True)
        self.assertIsNone(self.client.get(reverse('volunteer_rating'),{'club':club.pk}).context['my_rank'])
        self.client.logout()
        self.assertEqual(self.client.get(reverse('rating_history',args=[people[0].pk])).status_code,302)
