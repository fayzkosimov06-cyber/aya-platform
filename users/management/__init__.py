from types import SimpleNamespace
from ..profile_choices import filter_profiles, filter_choices
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q,Count
from django.http import HttpResponseForbidden
from django.shortcuts import render,redirect
from django.urls import reverse
from ..models import User,Direction,School,SchoolTeacher,AuditLog,Notification,PointProposal
from ..units import global_manager,people_field
from ..access import STAFF_ONLY_ROLES
from ..services import grant_access

ACTIONS=[('active','Присвоить звание «Активный волонтёр»'),('inactive','Снять звание «Активный волонтёр»'),('direction_add','Добавить в направление'),('direction_remove','Убрать из направления'),('leader_add','Назначить руководителями направления'),('leader_remove','Снять руководство направлением'),('school_add','Добавить в школу'),('school_remove','Убрать из школы'),('teacher_add','Назначить учителями школы'),('teacher_remove','Снять назначение учителя'),('role','Изменить системную роль'),('candidate','Принять в кандидаты'),('grant','Открыть полный доступ')]
class BulkForm(forms.Form):
    selected=people_field('Люди',User.objects.exclude(is_superuser=True))
    action=forms.ChoiceField(label='Действие',choices=ACTIONS)
    direction=forms.ModelChoiceField(label='Направление',queryset=Direction.objects.all(),required=False)
    school=forms.ModelChoiceField(label='Школа',queryset=School.objects.all(),required=False)
    role=forms.ChoiceField(label='Новая системная роль',choices=User.ROLE_CHOICES,required=False)
    old=forms.BooleanField(label='Это старые волонтёры (для открытия доступа)',required=False)
    def __init__(self,*args,actor,**kwargs):
        from ..views import get_user_power_level
        super().__init__(*args,**kwargs);self.actor=actor
        from ..permissions import allowed
        def available(key):
            cap='admissions' if key in {'candidate','grant'} else 'directions' if key.startswith(('direction_','leader_')) else 'schools' if key.startswith(('school_','teacher_')) else 'people'
            return allowed(actor,cap)
        self.fields['action'].choices=[(k,v) for k,v in ACTIONS if available(k)]
        self.fields['role'].choices=[(key,label) for key,label in User.ROLE_CHOICES if actor.is_superuser or get_user_power_level(SimpleNamespace(is_authenticated=True,is_superuser=False,role=key))<get_user_power_level(actor)]
    def clean(self):
        from ..views import get_user_power_level
        data=super().clean();chosen=data.get('selected');action=data.get('action','')
        if not chosen:self.add_error('selected','Выберите людей в списке.');return data
        if any(m.pk==self.actor.pk or get_user_power_level(m)>=get_user_power_level(self.actor) for m in chosen):self.add_error('selected','Нельзя изменять себя или пользователей равного/более высокого уровня. Снимите их выбор.')
        if action.startswith(('direction_','leader_')) and not data.get('direction'):self.add_error('direction','Выберите направление.')
        if action.startswith(('school_','teacher_')) and not data.get('school'):self.add_error('school','Выберите школу.')
        if action not in {'role','candidate','grant'} and (chosen.filter(is_approved=False).exists() or chosen.filter(role__in=STAFF_ONLY_ROLES).exists()):self.add_error('selected','Для этого действия выберите допущенных студентов.')
        if action in {'leader_add','teacher_add'} and not self.actor.is_superuser and get_user_power_level(self.actor)<=(50 if action=='leader_add' else 40):self.add_error('action','Нельзя назначить человека на равный или более высокий уровень.')
        if action=='role':
            if not data.get('role'):self.add_error('role','Выберите роль.')
            if chosen.filter(is_approved=False).exists():self.add_error('selected','Сначала откройте полный доступ выбранным пользователям.')
            if data.get('role')=='head_admin' and (chosen.count()!=1 or User.objects.filter(role='head_admin').exclude(pk__in=chosen).exists()):self.add_error('role','Начальник отдела должен быть один. Сначала измените роль прежнего начальника.')
        if action in {'candidate','grant'} and chosen.exclude(role='volunteer').exists():self.add_error('selected','Выберите заявки или кандидатов с ролью волонтёра.')
        return data

@login_required
@transaction.atomic
def people(request):
    if not global_manager(request.user):return HttpResponseForbidden('Нет доступа к управлению людьми.')
    form=BulkForm(request.POST if request.method=='POST' else None,actor=request.user)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data;selected=list(d['selected'].select_for_update());action=d['action'];direction=d.get('direction');school=d.get('school')
        for person in selected:
            if action in {'active','inactive'}:person.is_active_volunteer_title=action=='active';person.save(update_fields=['is_active_volunteer_title'])
            elif action=='direction_add':person.directions.add(direction)
            elif action=='direction_remove':person.directions.remove(direction);direction.featured_members.remove(person)
            elif action=='leader_add':direction.leaders.add(person);person.directions.add(direction)
            elif action=='leader_remove':direction.leaders.remove(person)
            elif action=='school_add':
                school.members.add(person)
                if school.direction_id:person.directions.add(school.direction)
            elif action=='school_remove':school.members.remove(person)
            elif action=='teacher_add':
                SchoolTeacher.objects.get_or_create(school=school,member=person,defaults={'name':person.get_full_name() or person.username})
                school.leaders.add(person);school.members.add(person)
                if school.direction_id:person.directions.add(school.direction)
            elif action=='teacher_remove':school.teachers.filter(member=person).delete();school.leaders.remove(person)
            elif action=='role':person.role=d['role'];person.save(update_fields=['role'])
            elif action=='candidate' and not person.is_approved and not person.candidate_approved:
                person.candidate_approved=True;person.save(update_fields=['candidate_approved'])
                Notification.objects.create(recipient=person,message='Ваша заявка принята. После трёх визитов откроется полный доступ.',link=reverse('my_profile'))
            elif action=='grant' and not person.is_approved:
                grant_access(person,request.user,old=d['old']);Notification.objects.create(recipient=person,message='Вам открыт полный доступ волонтёра.',link=reverse('my_profile'))
            AuditLog.objects.create(actor=request.user,target_user=person,action=f'Массовое действие: {dict(ACTIONS)[action]}; направление={direction}; школа={school}; роль={d.get("role") if action=="role" else ""}')
        messages.success(request,f'Готово. Обработано людей: {len(selected)}.');return redirect(request.get_full_path())
    q=request.GET.get('q','').strip();state=request.GET.get('state','');people=User.objects.exclude(is_superuser=True).prefetch_related('directions','directions_led','aya_schools','school_leader_of').order_by('last_name','first_name','pk')
    if q:people=people.filter(Q(first_name__icontains=q)|Q(last_name__icontains=q)|Q(username__icontains=q)|Q(group__icontains=q)|Q(faculty__icontains=q))
    if state=='candidate':people=people.filter(candidate_approved=True,is_approved=False)
    elif state=='pending':people=people.filter(candidate_approved=False,is_approved=False)
    elif state=='active':people=people.filter(is_active_volunteer_title=True)
    elif state=='approved':people=people.filter(is_approved=True)
    if request.GET.get('direction','').isdigit():people=people.filter(directions=request.GET['direction'])
    if request.GET.get('school','').isdigit():people=people.filter(aya_schools=request.GET['school'])
    from ..views import get_user_power_level
    people=list(filter_profiles(people, request.GET))
    for person in people:person.bulk_allowed=person.pk!=request.user.pk and get_user_power_level(person)<get_user_power_level(request.user)
    return render(request,'users/people_hub.html',{**filter_choices(),'filters':request.GET,'form':form,'people':people,'selected':request.POST.getlist('selected'),'q':q,'state':state,'directions':Direction.objects.all(),'schools':School.objects.all(),'filter_direction':request.GET.get('direction',''),'filter_school':request.GET.get('school','')})

@login_required
def dashboard(request):
    from ..permissions import CAPABILITIES, allowed
    if not any(allowed(request.user,c) for c in CAPABILITIES if c!='contacts'):return HttpResponseForbidden('Нет доступа.')
    from events.models import Event
    from ..points import members
    roster=members()
    return render(request,'users/admin_hub.html',{'people_count':roster.count(),'active_count':roster.filter(is_active_volunteer_title=True).count(),'candidate_count':User.objects.filter(candidate_approved=True,is_approved=False,is_superuser=False).count(),'pending_count':User.objects.filter(candidate_approved=False,is_approved=False,is_superuser=False).count(),'proposal_count':PointProposal.objects.filter(status='pending').count(),'event_count':Event.objects.filter(is_approved=False,submitted_for_review=True).count(),'recent_actions':AuditLog.objects.none() if not allowed(request.user,'audit') else AuditLog.objects.exclude(actor__is_superuser=True).exclude(target_user__is_superuser=True).select_related('actor').order_by('-pk')[:6]})
