from datetime import date,timedelta
from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q,Sum
from django.http import HttpResponseForbidden,JsonResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from .models import User,PermissionOverride,Direction,School,JournalEntry,BalanceAdjustment,ContributionWork,ContributionAward,ContributionKind,ActivityPeriod,VolunteerVisit
from .permissions import CAPABILITIES,SCOPED,allowed,defaults,setting,rank,can_change
from .journal import emit,PRIVATE,safe_value

class RightsForm(forms.Form):
 targets=forms.ModelMultipleChoiceField(queryset=User.objects.exclude(is_superuser=True),widget=forms.CheckboxSelectMultiple,label='Пользователи')
 acknowledge=forms.BooleanField(required=False,label='Понимаю, что отключаю важные права руководителя или учителя')
 def __init__(self,*args,actor,**kwargs):
  super().__init__(*args,**kwargs);self.actor=actor
  people=list(User.objects.exclude(is_superuser=True).prefetch_related('directions_led','school_leader_of','schoolteacher_set'))
  self.fields['targets'].queryset=User.objects.filter(pk__in=[p.pk for p in people if can_change(actor,p)]).order_by('last_name','first_name','pk').prefetch_related('directions_led','school_leader_of','schoolteacher_set','permission_overrides__directions','permission_overrides__schools')
  for code,label in CAPABILITIES.items():
   self.fields[code]=forms.ChoiceField(required=False,label=label,choices=[('keep','Не менять'),('inherit','Стандарт должности'),('on','Разрешить'),('off','Запретить')],initial='keep')
  self.fields['scope']=forms.ChoiceField(required=False,initial='own',label='Область изменяемых прав команд',choices=[('own','Свои команды'),('selected','Выбранные команды'),('all','Все команды')])
  self.fields['scope_directions']=forms.ModelMultipleChoiceField(queryset=Direction.objects.all(),required=False,widget=forms.CheckboxSelectMultiple,label='Направления')
  self.fields['scope_schools']=forms.ModelMultipleChoiceField(queryset=School.objects.all(),required=False,widget=forms.CheckboxSelectMultiple,label='Школы')
 def clean(self):
  d=super().clean();people=d.get('targets',[])
  for code in CAPABILITIES:d[code]=d.get(code) or 'keep'
  d['scope']=d.get('scope') or 'own'
  if not any(d[c]!='keep' for c in CAPABILITIES):
   raise forms.ValidationError('Выберите хотя бы одно изменение прав.')
  if d['scope']=='selected' and any(d[c]=='on' for c in SCOPED) and not (d.get('scope_directions') or d.get('scope_schools')):
   raise forms.ValidationError('Выберите хотя бы одно направление или школу для ограниченного доступа.')
  for person in people:
   if not can_change(self.actor,person):raise forms.ValidationError('Недоступный пользователь.')
   for code in CAPABILITIES:
    mode=d.get(code,'keep')
    if mode=='keep':continue
    new=mode=='on' or (mode=='inherit' and defaults(person,code))
    if new and not allowed(self.actor,code):raise forms.ValidationError('Нельзя передать право, которого у вас нет: '+CAPABILITIES[code])
    if new and code in SCOPED and not self.actor.is_superuser:
     own=setting(self.actor,code);scope=own.scope if own else ('all' if self.actor.role in {'president','worker','head_admin'} else 'own')
     desired=d.get('scope') if mode=='on' else ('all' if person.role in {'president','worker','head_admin'} else 'own')
     if scope!='all':
      if desired!='selected':raise forms.ValidationError('При ограниченных правах выберите конкретные доступные команды.')
      if any(not allowed(self.actor,code,obj) for obj in list(d.get('scope_directions',[]))+list(d.get('scope_schools',[]))):raise forms.ValidationError('Нельзя передать недоступную команду.')
    if mode=='off' and code in {'events_edit','directions','schools'} and rank(person) in {40,50} and not d.get('acknowledge'):
     raise forms.ValidationError('Среди выбранных есть руководитель, учитель или модератор. Подтвердите отключение важных прав. Имя, должность и рамка сохранятся.')
  return d

@login_required
@transaction.atomic
def rights(request):
 if not allowed(request.user,'permissions'):return HttpResponseForbidden('Настройка полномочий недоступна.')
 form=RightsForm(request.POST if request.method=='POST' else None,actor=request.user)
 if request.method=='POST' and form.is_valid():
  d=form.cleaned_data
  # Lock target accounts so simultaneous role changes cannot invalidate hierarchy checks.
  for person in d['targets'].select_for_update():
   if not can_change(request.user,person):return HttpResponseForbidden('Полномочия пользователя изменились. Обновите страницу.')
   for code in CAPABILITIES:
    mode=d[code]
    if mode=='keep':continue
    if mode=='inherit':PermissionOverride.objects.filter(user=person,code=code).delete();continue
    obj,_=PermissionOverride.objects.update_or_create(user=person,code=code,defaults={'enabled':mode=='on','scope':d['scope'] if code in SCOPED else 'all'})
    obj.directions.set(d['scope_directions']);obj.schools.set(d['scope_schools'])
  messages.success(request, f'Права сохранены. Пользователей: {len(d["targets"])}. Остальные разрешения сохранены.')
  return redirect('rights_manage')
 users=form.fields['targets'].queryset
 groups = [
  ('Люди и доступ', ['people','admissions','visits','contacts','permissions']),
  ('Мероприятия', ['events_edit','events_publish','events_delete']),
  ('Направления и школы', ['directions','schools']),
  ('Баллы и деятельность', ['points_propose','points_award','points_review','points_correct','points_rules','activity']),
  ('Страницы и журнал', ['home','about','audit']),
 ]
 people_data=[]
 for person in users:
  rules={r.code:r for r in person.permission_overrides.all()}
  states={}
  for code in CAPABILITIES:
   rule=rules.get(code)
   enabled=bool(person.is_approved or person.volunteer_access or person.role in {'president','worker','head_admin'}) and (rule.enabled if rule else defaults(person,code))
   states[code]={'enabled':enabled, 'source':'Личная настройка' if rule else 'По должности',
    'scope':dict(PermissionOverride.SCOPE_CHOICES).get(rule.scope,rule.scope) if rule and hasattr(PermissionOverride,'SCOPE_CHOICES') else (rule.scope if rule else ('all' if person.role in {'president','worker','head_admin'} else 'own'))}
  people_data.append({'id':str(person.pk),'name':person.get_full_name() or person.username,'role':('Руководитель направления' if person.directions_led.exists() else 'Учитель школы' if person.school_leader_of.exists() or person.schoolteacher_set.exists() else person.get_role_display()),'states':states})
 return render(request,'users/rights.html',{'form':form,'permission_groups':[(title,[form[c] for c in codes]) for title,codes in groups], 'people_data':people_data, 'scoped_codes':sorted(SCOPED)})

@login_required
def journal(request,mode='public'):
 if mode!='public' and not request.user.is_superuser:return HttpResponseForbidden('Недоступно.')
 if mode=='public' and not allowed(request.user,'audit'):return HttpResponseForbidden('Нет доступа к журналу.')
 qs=JournalEntry.objects.select_related('actor')
 if mode=='activity':
  cutoff=timezone.now()-timedelta(days=90)
  qs=qs.filter(category__in=['view','search'],created_at__gte=cutoff)
 elif mode=='private':qs=qs.filter(private=True).exclude(category__in=['view','search'])
 else:qs=qs.filter(private=False).exclude(actor__is_superuser=True).exclude(category__in=['view','search'])
 q=request.GET.get('q','').strip();section=request.GET.get('section','');category=request.GET.get('category','');actor=request.GET.get('actor','')
 if q:qs=qs.filter(Q(action__icontains=q)|Q(object_id=q)|Q(section__icontains=q))
 if section:qs=qs.filter(section=section)
 if category:qs=qs.filter(category=category)
 if actor.isdigit():qs=qs.filter(actor_id=actor)
 for key,lookup in [('start','created_at__date__gte'),('end','created_at__date__lte')]:
  try:d=date.fromisoformat(request.GET.get(key,''))
  except ValueError:continue
  qs=qs.filter(**{lookup:d})
 page=Paginator(qs,40).get_page(request.GET.get('page'))
 for entry in page:
  keys=set(entry.before)|set(entry.after);entry.differences=[]
  for key in sorted(keys):
   a=entry.before.get(key);b=entry.after.get(key)
   if a==b:continue
   if not allowed(request.user,'contacts') and key in PRIVATE:a=b='Значение скрыто'
   if not request.user.is_superuser and key in {'actor','organizer','confirmed_by','created_by','marked_by','reviewer','volunteer_access_granted_by'}:
    roots={str(x) for x in User.objects.filter(is_superuser=True).values_list('pk',flat=True)}
    if str(a) in roots:a='—'
    if str(b) in roots:b='—'
   entry.differences.append((key,a,b))
 params=request.GET.copy();params.pop('page',None)
 return render(request,'users/journal.html',{'entries':page,'mode':mode,'q':q,'query':params.urlencode(),'sections':JournalEntry.objects.filter(private=False).values_list('section',flat=True).distinct(),'actors':User.objects.exclude(is_superuser=True).order_by('last_name'),'filters':request.GET})

class BalanceForm(forms.Form):
 member=forms.ModelChoiceField(queryset=User.objects.filter(is_approved=True,is_superuser=False).exclude(role__in=['worker','head_admin']),label='Волонтёр')
 operation=forms.ChoiceField(choices=[('add','Прибавить'),('subtract','Уменьшить'),('set','Установить итог за учебный год'),('team','Добавить к прежней командной работе')],label='Действие')
 amount=forms.IntegerField(min_value=0,max_value=10000000,label='Количество баллов')
 date=forms.DateField(label='Дата зачёта',widget=forms.DateInput(attrs={'type':'date'}))
 work=forms.ModelChoiceField(queryset=ContributionWork.objects.all(),required=False,label='Командная работа')
 note=forms.CharField(required=False,label='Закрытая заметка',widget=forms.Textarea)
 confirm=forms.BooleanField(label='Подтверждаю изменение баланса')

@login_required
@transaction.atomic
def balance(request):
 if not request.user.is_superuser:return HttpResponseForbidden('Недоступно.')
 form=BalanceForm(request.POST if request.method=='POST' else None,initial={'date':timezone.localdate()})
 result=None
 if request.method=='POST' and form.is_valid():
  from .points import adjustment_total
  d=form.cleaned_data;m=User.objects.select_for_update().get(pk=d['member'].pk);when=d['date'];year=when.year-(when.month<9)
  old=(ContributionAward.objects.filter(member=m,revoked=False,work__date__gte=date(year,9,1),work__date__lt=date(year+1,9,1)).aggregate(n=Sum('points'))['n'] or 0)+(BalanceAdjustment.objects.filter(member=m,date__gte=date(year,9,1),date__lt=date(year+1,9,1)).aggregate(n=Sum('amount'))['n'] or 0)
  delta=d['amount'] if d['operation']=='add' else -d['amount'] if d['operation']=='subtract' else d['amount']-old
  if d['operation']=='team':
   work=d['work']
   if not work:form.add_error('work','Выберите работу.')
   elif d['amount']<1:form.add_error('amount','Для работы укажите положительную сумму.')
   elif work.awards.filter(member=m).exists():form.add_error('member','Участник уже получил начисление за эту работу.')
   else:
    sample=work.awards.first();kind=sample.kind if sample else ContributionKind.objects.get_or_create(name='Участие в команде',defaults={'points':1,'active':False})[0]
    award=ContributionAward.objects.create(work=work,member=m,kind=kind,points=d['amount'],confirmed_by=None)
    ContributionAward.objects.filter(pk=award.pk).update(confirmed_at=sample.confirmed_at if sample else work.created_at)
    if work.event:work.event.participants.add(m)
    if work.school:work.school.members.add(m)
    if work.direction:m.directions.add(work.direction)
    emit('correction','balance','Добавлен в прежнюю команду',after={'member':m.pk,'work':work.pk,'points':d['amount'],'effective_date':str(work.date),'note':d['note']})
    return redirect('ghost_balance')
  else:
   BalanceAdjustment.objects.create(member=m,date=when,amount=delta,note=d['note'],actor=request.user)
   emit('correction','balance','Корректировка баланса',before={'year_total':old},after={'member':m.pk,'year_total':old+delta,'amount':delta,'date':str(when),'note':d['note']})
   return redirect('ghost_balance')
 return render(request,'users/control_form.html',{'form':form,'heading':'Закрытая корректировка баллов','help':'Изменяется итог рейтинга. Работа и уведомление не создаются. Для командной работы используется её исходная дата.'})

class DatesForm(forms.Form):
 entity=forms.ChoiceField(choices=[('event','Мероприятие'),('attendance','Посещение мероприятия'),('visit','Вступительный визит'),('access','Дата допуска'),('activity','Период деятельности'),('work','Дата работы')],label='Запись')
 object_id=forms.IntegerField(min_value=1,label='Номер записи / ID пользователя для допуска')
 start=forms.DateTimeField(label='Дата и время начала / зачёта',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
 end=forms.DateTimeField(required=False,label='Окончание',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
 confirm=forms.BooleanField(label='Подтверждаю исправление даты')
 def clean(self):
  d=super().clean()
  if d.get('end') and d.get('start') and d['end']<d['start']:raise forms.ValidationError('Окончание не может быть раньше начала.')
  return d

@login_required
@transaction.atomic
def dates(request):
 if not request.user.is_superuser:return HttpResponseForbidden('Недоступно.')
 from events.models import Event,EventAttendance
 mapping={'event':(Event,'start_time','end_time'),'attendance':(EventAttendance,'marked_at',None),'visit':(VolunteerVisit,'visit_date',None),'access':(User,'volunteer_access_granted_at',None),'activity':(ActivityPeriod,'start_date','end_date'),'work':(ContributionWork,'date',None)}
 form=DatesForm(request.POST if request.method=='POST' else None)
 if request.method=='POST' and form.is_valid():
  d=form.cleaned_data;model,start,end=mapping[d['entity']];obj=model.objects.select_for_update().filter(pk=d['object_id']).first()
  if not obj:form.add_error('object_id','Запись не найдена.')
  else:
   from .journal import snapshot
   before=snapshot(obj);value=d['start'].date() if start in {'date','visit_date','start_date'} else d['start'];changes={start:value}
   if end and d['end']:changes[end]=d['end'].date() if end=='end_date' else d['end']
   for key,value in changes.items():setattr(obj,key,value)
   try:
    if end and getattr(obj,end) and getattr(obj,end)<getattr(obj,start):raise forms.ValidationError('Окончание не может быть раньше начала.')
    obj.full_clean(exclude=['password'])
   except forms.ValidationError as exc:
    form.add_error(None,str(exc))
    return render(request,'users/control_form.html',{'form':form,'heading':'Закрытое исправление дат'})
   model.objects.filter(pk=obj.pk).update(**changes);obj.refresh_from_db()
   emit('correction',model._meta.label,'Исправлены даты',before,snapshot(obj),obj.pk)
   return redirect('ghost_dates')
 return render(request,'users/control_form.html',{'form':form,'heading':'Закрытое исправление дат','help':'Настоящее время исправления сохраняется в закрытом журнале. ID записи указан в журнале изменений.'})

@login_required
def search_event(request):
 if request.method!='POST':return HttpResponseForbidden('Требуется POST.')
 from .control_middleware import ROUTES
 section=request.POST.get('section','')
 if section not in {'volunteer_list','unit_catalog','school_catalog','event_list','user_management','moderator_dashboard','points_quick','rights_manage'}:return HttpResponseForbidden('Неизвестный раздел.')
 code='permissions' if section=='rights_manage' else ROUTES.get(section)
 if code and not allowed(request.user,code):return HttpResponseForbidden('Нет доступа.')
 text=request.POST.get('query','').strip()[:300]
 if text:emit('search',section,'Поиск в списке',after={'query':safe_value('query',text),'results':request.POST.get('results','')[:10]},private=True)
 return JsonResponse({'ok':True})
