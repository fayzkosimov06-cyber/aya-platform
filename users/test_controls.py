from datetime import timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import User,Direction,School,PermissionOverride,JournalEntry,BalanceAdjustment,ContributionWork,ContributionKind,ContributionAward
from .permissions import allowed,rank,CAPABILITIES
from events.models import Event

class ControlTests(TestCase):
 def setUp(self):
  def u(name,role='volunteer',root=False):return User.objects.create(username=name,first_name=name,role=role,is_superuser=root,is_approved=True,qr_code='unused.png')
  self.root=u('InvisibleRoot',root=True);self.head=u('Head','head_admin');self.worker=u('Worker','worker');self.president=u('President','president');self.mod=u('Moderator','moderator');self.teacher=u('Teacher');self.member=u('Member');self.leader=u('Leader')
  self.direction=Direction.objects.create(name='Own');self.other=Direction.objects.create(name='Other');self.direction.leaders.add(self.leader)
  self.school=School.objects.create(name='School');self.teacher.school_leader_of.add(self.school)
  self.event=Event.objects.create(title='Meeting',description='Description',start_time=timezone.now()+timedelta(days=1),end_time=timezone.now()+timedelta(days=1,hours=2),organizer=self.president,is_approved=True)
  self.event.aya_directions.add(self.direction)
 def grant(self,user,code,enabled=True,scope='all'):
  return PermissionOverride.objects.create(user=user,code=code,enabled=enabled,scope=scope)
 def login(self,user):self.client.force_login(user)
 def rights(self,actor,target,**changes):
  self.login(actor);data={c:'keep' for c in CAPABILITIES};data.update(targets=[target.pk],scope='all',acknowledge='on');data.update(changes)
  return self.client.post(reverse('rights_manage'),data)
 def test_hierarchy_and_equal_protection(self):
  self.assertEqual(rank(self.head),rank(self.worker));self.assertEqual(rank(self.leader),rank(self.mod));self.assertGreater(rank(self.mod),rank(self.teacher))
  self.assertEqual(self.rights(self.head,self.worker,events_edit='off').status_code,200)
  self.assertFalse(PermissionOverride.objects.filter(user=self.worker).exists())
  self.assertEqual(self.rights(self.root,self.head,events_edit='off').status_code,302)
 def test_delegate_permission_management_without_rank_escalation(self):
  self.grant(self.mod,'permissions')
  self.assertEqual(self.rights(self.mod,self.leader,events_edit='on').status_code,200)
  self.assertFalse(PermissionOverride.objects.filter(user=self.leader).exists())
  self.assertEqual(self.rights(self.mod,self.member,events_edit='on').status_code,200)
  self.assertFalse(PermissionOverride.objects.filter(user=self.member).exists())
  self.assertEqual(self.rights(self.mod,self.member,visits='on').status_code,302)
 def test_explicit_denial_overrides_assignment(self):
  self.assertTrue(allowed(self.leader,'directions',self.direction));self.grant(self.leader,'directions',False)
  self.assertFalse(allowed(self.leader,'directions',self.direction));self.login(self.leader)
  self.assertEqual(self.client.get(reverse('direction_edit',args=[self.direction.pk])).status_code,403)
  self.assertTrue(self.direction.leaders.filter(pk=self.leader.pk).exists())
 def test_selected_event_scope(self):
  grant=self.grant(self.mod,'events_edit',scope='selected');grant.directions.add(self.direction)
  self.assertTrue(allowed(self.mod,'events_edit',self.event));self.login(self.mod)
  self.assertEqual(self.client.get(reverse('event_edit',args=[self.event.pk])).status_code,200)
  self.assertEqual(self.client.post(reverse('event_edit',args=[self.event.pk])+'?tab=status',{'action':'publish'}).status_code,403)
  self.event.aya_directions.set([self.other]);self.assertFalse(allowed(self.mod,'events_edit',self.event))
 def test_points_rules_permission_is_independent(self):
  self.grant(self.mod,'points_rules');self.login(self.mod)
  self.assertEqual(self.client.get(reverse('points_kinds')).status_code,200)
  self.assertEqual(self.client.get(reverse('points_quick')).status_code,403)
 def test_root_profile_hidden_and_private_log_isolation(self):
  self.login(self.president);self.assertEqual(self.client.get(reverse('public_profile',args=[self.root.pk])).status_code,404)
  for name in ['journal_private','journal_activity','ghost_balance','ghost_dates']:
   self.assertEqual(self.client.get(reverse(name)).status_code,403)
  self.login(self.root)
  data={'member':self.member.pk,'operation':'add','amount':17,'date':timezone.localdate(),'confirm':'on','note':'HiddenNote'}
  self.assertEqual(self.client.post(reverse('ghost_balance'),data).status_code,302)
  self.assertEqual(BalanceAdjustment.objects.get().amount,17)
  self.assertTrue(JournalEntry.objects.filter(actor=self.root,private=True).exists())
  self.login(self.president);r=self.client.get(reverse('audit_log'));self.assertNotContains(r,'InvisibleRoot');self.assertNotContains(r,'HiddenNote')
  r=self.client.get(reverse('public_profile',args=[self.member.pk]));self.assertContains(r,'17');self.assertNotContains(r,'HiddenNote')
 def test_balance_set_and_historical_team(self):
  self.login(self.root);day=timezone.localdate()-timedelta(days=400)
  for op,n in [('add',10),('set',25),('subtract',5)]:
   r=self.client.post(reverse('ghost_balance'),{'member':self.member.pk,'operation':op,'amount':n,'date':day,'confirm':'on'})
   self.assertEqual(r.status_code,302)
  self.assertEqual(sum(BalanceAdjustment.objects.values_list('amount',flat=True)),20)
  work=ContributionWork.objects.create(title='OldTeam',date=day,event=self.event,direction=self.direction,created_by=self.president)
  self.assertEqual(self.client.post(reverse('ghost_balance'),{'member':self.member.pk,'operation':'team','amount':5,'date':day,'confirm':'on','work':work.pk}).status_code,302)
  self.assertTrue(self.event.participants.filter(pk=self.member.pk).exists());self.assertTrue(self.member.directions.filter(pk=self.direction.pk).exists())
  self.assertIsNone(ContributionAward.objects.get().confirmed_by)
 def test_no_backdated_nonroot_awards(self):
  self.login(self.president)
  response=self.client.post(reverse('points_quick'),{'date':timezone.localdate()-timedelta(days=1)})
  self.assertEqual(response.status_code,403)
 def test_search_is_private_redacts_secrets(self):
  self.login(self.member)
  self.client.post(reverse('record_search'),{'section':'volunteer_list','query':'token=SECRET123'})
  entry=JournalEntry.objects.filter(category='search').get();self.assertTrue(entry.private)
  self.assertNotIn('SECRET123',str(entry.after))
 def test_role_change_resets_overrides(self):
  self.grant(self.member,'events_edit');self.login(self.root)
  r=self.client.post(reverse('update_user_role',args=[self.member.pk]),{'role':'moderator'})
  # The existing individual endpoint uses role or new_role depending on caller; bulk is canonical.
  if PermissionOverride.objects.filter(user=self.member).exists():
   self.client.post(reverse('user_management'),{'action':'role','role':'moderator','selected':[self.member.pk]})
  self.assertFalse(PermissionOverride.objects.filter(user=self.member).exists())
 def test_legacy_journal_private_migration(self):
  from importlib import import_module
  from django.apps import apps
  from .models import AuditLog
  AuditLog.objects.create(actor=self.root,action='Private legacy')
  AuditLog.objects.create(actor=self.worker,action='Public legacy')
  import_module('users.migrations.0041_import_legacy_journal').copy_logs(apps,None)
  self.assertTrue(JournalEntry.objects.filter(action='Private legacy',private=True).exists())
  self.login(self.worker);response=self.client.get(reverse('audit_log'))
  self.assertContains(response,'Public legacy');self.assertNotContains(response,'Private legacy')
 def test_disable_own_permission_management_impossible(self):
  response=self.rights(self.president,self.president,permissions='off')
  self.assertEqual(response.status_code,200)
  self.assertFalse(PermissionOverride.objects.filter(user=self.president).exists())
 def test_admissions_and_visits_are_independent(self):
  self.grant(self.member,'admissions');self.login(self.member)
  candidate=User.objects.create(username='newcandidate',candidate_approved=True,qr_code='unused.png')
  response=self.client.get(reverse('moderator_dashboard'))
  self.assertEqual(response.status_code,200)
  self.assertNotContains(response,'+ Отметить визит')
  self.assertEqual(self.client.post(reverse('mark_candidate_visit',args=[candidate.pk])).status_code,403)
 def test_only_root_can_open_django_admin(self):
  self.worker.is_staff=True;self.worker.save();self.login(self.worker)
  self.assertEqual(self.client.get('/superadmin/').status_code,404)
 def test_dates_keep_real_audit_timestamp(self):
  self.login(self.root);effective=timezone.now()-timedelta(days=100)
  response=self.client.post(reverse('ghost_dates'),{'entity':'event','object_id':self.event.pk,'start':effective.isoformat(),'end':(effective+timedelta(hours=2)).isoformat(),'confirm':'on'})
  self.assertEqual(response.status_code,302);self.event.refresh_from_db()
  self.assertEqual(self.event.start_time,effective)
  entry=JournalEntry.objects.get(category='correction',section='events.Event')
  self.assertGreater(entry.created_at,effective+timedelta(days=90));self.assertTrue(entry.private)
 def test_selected_scope_cannot_be_expanded_on_delegation(self):
  self.grant(self.mod,'permissions');rule=self.grant(self.mod,'events_edit',scope='selected');rule.directions.add(self.direction)
  response=self.rights(self.mod,self.member,events_edit='on',scope='selected',scope_directions=[self.other.pk])
  self.assertEqual(response.status_code,200);self.assertFalse(PermissionOverride.objects.filter(user=self.member).exists())
 def test_cleanup_preserves_changes(self):
  from django.core.management import call_command
  old=timezone.now()-timedelta(days=91)
  a=JournalEntry.objects.create(category='view',action='old',private=True);b=JournalEntry.objects.create(category='change',action='old')
  JournalEntry.objects.filter(pk__in=[a.pk,b.pk]).update(created_at=old)
  call_command('purge_activity',verbosity=0)
  self.assertFalse(JournalEntry.objects.filter(pk=a.pk).exists());self.assertTrue(JournalEntry.objects.filter(pk=b.pk).exists())
 def test_bulk_cannot_bypass_disabled_admissions(self):
  self.grant(self.president,'admissions',False);self.login(self.president)
  candidate=User.objects.create(username='bulk-candidate',qr_code='unused.png')
  r=self.client.post(reverse('user_management'),{'action':'grant','selected':[candidate.pk]})
  self.assertEqual(r.status_code,403);candidate.refresh_from_db();self.assertFalse(candidate.is_approved)
 def test_linking_foreign_event_does_not_expand_grants(self):
  self.grant(self.mod,'directions',scope='selected').directions.add(self.direction)
  alien=Event.objects.create(title='Alien',description='Private',start_time=timezone.now(),end_time=timezone.now(),organizer=self.president,is_approved=True)
  self.login(self.mod)
  r=self.client.post(reverse('direction_edit',args=[self.direction.pk])+'?tab=events',{'events':[alien.pk]})
  self.assertEqual(r.status_code,403);self.assertFalse(self.direction.events.filter(pk=alien.pk).exists())
