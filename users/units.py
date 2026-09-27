from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.urls import reverse
from .permissions import allowed
from .models import Direction, School, User, SchoolTeacher, SchoolLesson, AuditLog, ContributionAward
from .access import has_full_volunteer_access
from .points import can_award, members as eligible_members
from events.models import Event


def global_manager(user, code=None):
    from .permissions import allowed, setting, request_context
    req = request_context.get()
    code = code or getattr(req, 'aya_capability', None)
    if code not in {'directions', 'schools'}:
        return allowed(user, 'people')
    obj = getattr(req, 'aya_object', None)
    if not allowed(user, code, obj):
        return False
    if user.is_superuser:
        return True
    rule = setting(user, code)
    scope = rule.scope if rule else ('all' if user.role in {'president','worker','head_admin'} else 'own')
    # Creation requires all teams; explicit scoped administration only works on an existing team.
    return scope == 'all' or bool(obj and rule and rule.enabled)


def can_edit_unit(user,obj):
    from .permissions import allowed,request_context
    req=request_context.get();code=getattr(req,'aya_capability',None)
    return allowed(user, code if code in {'points_propose','directions','schools'} else ('schools' if isinstance(obj,School) else 'directions'),obj)


def get_unit(kind,pk): return get_object_or_404(School if kind=='school' else Direction,pk=pk)

def log(user,text): AuditLog.objects.create(actor=user,action=text)


def schedule_page(request, school, *, editor=False):
    """Retain history and inactive-school lessons; never silently hide a saved schedule."""
    now = timezone.now()
    lessons = school.lessons.prefetch_related('teachers__member')
    counts = lessons.aggregate(all=Count('pk'),
        upcoming=Count('pk', filter=Q(ends_at__gte=now, cancelled=False)),
        past=Count('pk', filter=Q(ends_at__lt=now, cancelled=False)),
        cancelled=Count('pk', filter=Q(cancelled=True)))
    selected = request.GET.get('schedule', 'upcoming' if counts['upcoming'] else 'all')
    if selected not in counts:
        selected = 'all'
    if selected == 'upcoming': lessons = lessons.filter(ends_at__gte=now, cancelled=False)
    elif selected == 'past': lessons = lessons.filter(ends_at__lt=now, cancelled=False)
    elif selected == 'cancelled': lessons = lessons.filter(cancelled=True)
    query = request.GET.get('lesson_q', '').strip()[:200]
    if query: lessons = lessons.filter(Q(topic__icontains=query) | Q(location__icontains=query))
    lessons = lessons.order_by('-starts_at', '-pk') if selected == 'past' else lessons.order_by('starts_at', 'pk')
    page = Paginator(lessons, 15 if editor else 8).get_page(request.GET.get('lessons_page'))
    for lesson in page:
        lesson.finished = lesson.ends_at < now
        lesson.happening = lesson.starts_at <= now <= lesson.ends_at
    return {'lessons': page, 'schedule_filter': selected, 'schedule_counts': counts,
            'lesson_q': query, 'schedule_timezone': str(timezone.get_current_timezone()),
            'schedule_tabs': [('upcoming', 'Ближайшие', counts['upcoming']),
                              ('all', 'Все занятия', counts['all']),
                              ('past', 'Прошедшие', counts['past']),
                              ('cancelled', 'Отменённые', counts['cancelled'])]}


def unit_actions(user, obj):
    return {'can_create_unit_event': allowed(user, 'events_edit', obj),
            'can_propose_unit_points': allowed(user, 'points_propose', obj),
            'can_award_points': can_award(user)}


def catalog(request, kind='direction'):
    school = kind == 'school'
    query = request.GET.get('q', '').strip()[:200]
    state = request.GET.get('state', 'active')
    if state not in {'active', 'inactive', 'all'}: state = 'active'
    objects = School.objects.select_related('direction') if school else Direction.objects.all()
    if school and state != 'all': objects = objects.filter(active=state == 'active')
    direction = request.GET.get('direction', '')
    if school and direction == 'standalone': objects = objects.filter(direction__isnull=True)
    elif school and direction.isdigit(): objects = objects.filter(direction_id=direction)
    if query: objects = objects.filter(Q(name__icontains=query) | Q(intro__icontains=query))
    member_relation = 'members' if school else 'user'
    public_members = Q(**{member_relation + '__is_approved': True, member_relation + '__is_superuser': False}) & ~Q(**{member_relation + '__role__in': ['worker', 'head_admin']})
    objects = objects.annotate(people_count=Count(member_relation, filter=public_members, distinct=True))
    objects = objects.annotate(extra_count=Count('lessons' if school else 'schools', distinct=True))
    page = Paginator(objects.order_by('name', 'pk'), 12).get_page(request.GET.get('page'))
    request.aya_result_count = page.paginator.count
    for obj in page: obj.manage_allowed = can_edit_unit(request.user, obj)
    return render(request, 'users/unit_catalog.html', {
        'objects': page, 'kind': kind, 'is_school': school,
        'global_manager': global_manager(request.user, 'schools' if school else 'directions'),
        'q': query, 'state': state, 'inactive': state == 'inactive',
        'directions': Direction.objects.order_by('name'), 'filter_direction': direction})


def detail(request, pk, kind='direction'):
    obj = get_unit(kind, pk)
    school = kind == 'school'
    can_edit = can_edit_unit(request.user, obj)
    people = eligible_members().filter(aya_schools=obj) if school else eligible_members().filter(directions=obj)
    count = people.count()
    featured=obj.featured_members.filter(pk__in=people.values('pk'))
    if featured.exists() and request.GET.get('team')!='all':people=people.filter(pk__in=featured.values('pk'))
    query = request.GET.get('people_q', '').strip()[:200]
    if query: people = people.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(username__icontains=query))
    events = obj.events.filter(is_approved=True)
    if not has_full_volunteer_access(request.user): events = events.filter(is_public_for_guests=True)
    event_filter = request.GET.get('events', 'upcoming')
    if event_filter == 'past': events = events.filter(Q(is_completed=True) | Q(end_time__lt=timezone.now())).order_by('-start_time')
    else:
        event_filter = 'upcoming'
        events = events.filter(is_completed=False, cancelled=False, end_time__gte=timezone.now()).order_by('start_time')
    from datetime import date
    today = timezone.localdate(); year = today.year - (today.month < 9)
    awards = ContributionAward.objects.filter(revoked=False, work__date__gte=date(year, 9, 1), work__date__lt=date(year+1, 9, 1))
    awards = awards.filter(work__school=obj) if school else awards.filter(Q(work__direction=obj) | Q(work__school__direction=obj))
    context = {
        'unit': obj, 'is_school': school, 'kind': kind, 'unit_can_manage': can_edit,
        'can_edit_unit': can_edit, 'global_manager': global_manager(request.user),
        'unit_leaders': obj.leaders.filter(is_approved=True, is_superuser=False).exclude(role__in=['worker','head_admin']) if not school else [],
        'member_count': count, 'people_q': query, 'has_featured':featured.exists(), 'show_all_team':request.GET.get('team')=='all', 'clubs':obj.clubs.all(),
        'member_page': Paginator(people.order_by('last_name', 'first_name', 'pk'), 18).get_page(request.GET.get('page')),
        'upcoming': Paginator(events, 6).get_page(request.GET.get('events_page')),
        'event_filter': event_filter,
        'schools': obj.schools.order_by('-active', 'name') if not school else [],
        'teachers': obj.teachers.exclude(member__is_superuser=True).select_related('member') if school else [],
        'unit_points': awards.aggregate(n=Sum('points'))['n'] or 0 if has_full_volunteer_access(request.user) else None,
        'academic_year': f'{year}/{year+1}', **unit_actions(request.user, obj),
    }
    if school: context.update(schedule_page(request, obj))
    return render(request, 'users/unit_detail.html', context)


class PeopleField(forms.ModelMultipleChoiceField):
    def label_from_instance(self,obj):
        study = ' · '.join(str(v) for v in [obj.faculty, f'{obj.course} курс' if obj.course else '', obj.group] if v)
        return f'{obj.get_full_name() or obj.username} · @{obj.username}' + (f' · {study}' if study else '')


def people_field(label,queryset=None):
    return PeopleField(queryset=queryset if queryset is not None else eligible_members(),required=False,label=label,widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))


class AboutDirection(forms.ModelForm):
    class Meta:
        model=Direction;fields=['name','intro','description','cover']

class AboutSchool(forms.ModelForm):
    class Meta:
        model=School;fields=['name','direction','active','intro','description','cover']
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['direction'].empty_label='Самостоятельная школа'
        if not global_manager(user):
            self.fields.pop('direction');self.fields.pop('name')


class MemberForm(forms.Form):
    def __init__(self,*args,obj,user=None,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj;self.user=user
        self.fields['members']=people_field('Участники')
        self.initial['members']=(obj.members if isinstance(obj,School) else obj.user_set).values_list('pk',flat=True)
    def clean_members(self):
        from .permissions import rank
        selected=self.cleaned_data['members']
        existing=self.obj.members if isinstance(self.obj,School) else self.obj.user_set
        removed=self.obj.leaders.filter(pk__in=existing.values('pk')).exclude(pk__in=selected)
        if removed.exists() and (not self.user or not global_manager(self.user) or any(p.pk==self.user.pk or rank(p)>=rank(self.user) for p in removed)):
            raise forms.ValidationError('Сначала снимите руководящее назначение. Вы не можете убрать действующего руководителя или учителя с вашим уровнем доступа.')
        return selected
    def save(self):
        selected=self.cleaned_data['members']
        existing=self.obj.members if isinstance(self.obj,School) else self.obj.user_set
        removed=self.obj.leaders.filter(pk__in=existing.values('pk')).exclude(pk__in=selected)
        self.obj.leaders.remove(*removed)
        if isinstance(self.obj,School):
            added=list(selected.exclude(pk__in=self.obj.members.values('pk')))
            self.obj.members.set(selected)
            self.obj.featured_members.remove(*self.obj.featured_members.exclude(pk__in=selected))
            if self.obj.direction_id:self.obj.direction.user_set.add(*added)
        else:
            self.obj.user_set.set(selected)
            self.obj.featured_members.remove(*self.obj.featured_members.exclude(pk__in=selected.values('pk')))

class LeaderForm(forms.Form):
    def __init__(self,*args,obj,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj
        self.fields['leaders']=people_field('Руководители направления')
        self.initial['leaders']=obj.leaders.values_list('pk',flat=True)
    def save(self):
        self.obj.leaders.set(self.cleaned_data['leaders']);self.obj.user_set.add(*self.cleaned_data['leaders'])

class FeatureForm(forms.Form):
    featured_only=forms.BooleanField(label='Показывать только активную команду',required=False)
    def __init__(self,*args,obj,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj
        self.fields['featured_members']=people_field('Активная команда',eligible_members().filter(aya_schools=obj) if isinstance(obj,School) else eligible_members().filter(directions=obj))
        self.initial.update(featured_only=getattr(obj,'featured_only',False),featured_members=obj.featured_members.values_list('pk',flat=True))
        if isinstance(obj,School):self.fields.pop('featured_only')
    def save(self):
        if not isinstance(self.obj,School):self.obj.featured_only=self.cleaned_data['featured_only'];self.obj.save(update_fields=['featured_only'])
        self.obj.featured_members.set(self.cleaned_data['featured_members'])

class EventForm(forms.Form):
    events=forms.ModelMultipleChoiceField(queryset=Event.objects.filter(is_approved=True),required=False,label='Мероприятия',widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    def __init__(self,*args,obj,user=None,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj;self.initial['events']=obj.events.values_list('pk',flat=True)
        if user:
            ids = [e.pk for e in Event.objects.filter(is_approved=True) if allowed(user, 'events_edit', e)]
            self.fields['events'].queryset=Event.objects.filter(Q(pk__in=ids) | Q(pk__in=obj.events.values('pk'))).filter(is_approved=True)
    def save(self): self.obj.events.set(self.cleaned_data['events'])

class SchoolLinkForm(forms.Form):
    schools=forms.ModelMultipleChoiceField(queryset=School.objects.all(),required=False,label='Школы этого направления',widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    def __init__(self,*args,obj,user,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj;self.user=user;self.initial['schools']=obj.schools.values_list('pk',flat=True)
        candidates = School.objects.select_related('direction')
        ids = [school.pk for school in candidates if school.direction_id == obj.pk or
               (allowed(user, 'schools', school) and (not school.direction_id or allowed(user, 'directions', school.direction)))]
        self.fields['schools'].queryset=School.objects.filter(pk__in=ids)
        self.fields['schools'].help_text='Выбранные школы будут связаны с направлением. Снятые с выбора станут самостоятельными. Участники привязанных школ добавятся в состав направления.'
    def clean_schools(self):
        selected=self.cleaned_data['schools']
        changed=set(selected.values_list('pk',flat=True)) ^ set(self.obj.schools.values_list('pk',flat=True))
        for school in School.objects.filter(pk__in=changed).select_related('direction'):
            if not allowed(self.user,'schools',school) or (school.direction_id and not allowed(self.user,'directions',school.direction)):
                raise forms.ValidationError('Нет прав на изменение связи одной из школ.')
        return selected
    def save(self):
        selected=self.cleaned_data['schools']
        added=list(selected.exclude(direction=self.obj))
        for school in self.obj.schools.exclude(pk__in=selected):school.direction=None;school.save(update_fields=['direction'])
        for school in selected:school.direction=self.obj;school.save(update_fields=['direction'])
        for school in added:self.obj.user_set.add(*school.members.all())


@login_required
@transaction.atomic
def edit(request,pk,kind='direction'):
    obj=get_unit(kind,pk)
    if not can_edit_unit(request.user,obj):return HttpResponseForbidden('Нет доступа к управлению этим разделом.')
    school=kind=='school';gm=global_manager(request.user)
    tabs=[('about','О странице'),('members','Участники')]
    if school:tabs += [('teachers','Учителя'),('schedule','Расписание'),('featured','Активная команда')]
    else:
        tabs += [('featured','Активная команда')]
        if gm:tabs += [('leaders','Руководители'),('schools','Школы')]
    tabs += [('events','Мероприятия'),('points','Баллы')]
    tab=request.GET.get('tab','about')
    if tab not in dict(tabs):return HttpResponseForbidden('Этот раздел управления недоступен.')
    data=request.POST if request.method=='POST' else None;form=None
    if tab=='about':
        form=AboutSchool(data,request.FILES or None,instance=obj,user=request.user) if school else AboutDirection(data,request.FILES or None,instance=obj)
    elif tab=='events':form=EventForm(data,obj=obj,user=request.user)
    elif tab=='schools':form=SchoolLinkForm(data,obj=obj,user=request.user)
    elif tab=='members':form=MemberForm(data,obj=obj,user=request.user)
    elif tab in {'featured','leaders'}:form={'featured':FeatureForm,'leaders':LeaderForm}[tab](data,obj=obj)
    if request.method=='POST' and tab=='schedule':
        action=request.POST.get('action')
        ids=request.POST.getlist('lessons')
        if action not in {'cancel_lessons','restore_lessons'} or not ids or len(ids)>200 or any(not x.isdigit() for x in ids):
            messages.error(request,'Выберите занятия и действие.')
        else:
            selected=obj.lessons.filter(pk__in=ids)
            if selected.count()!=len(set(ids)):return HttpResponseForbidden('В списке есть занятия другой школы.')
            for lesson in selected:
                lesson.cancelled=action=='cancel_lessons';lesson.save(update_fields=['cancelled'])
            messages.success(request,'Статус выбранных занятий обновлён.')
            return redirect(request.path+'?tab=schedule&schedule=all')
    if request.method=='POST' and form and form.is_valid():
        form.save()
        log(request.user,f'Изменён раздел «{dict(tabs)[tab]}»: {obj.name}')
        messages.success(request,'Изменения сохранены.')
        if request.POST.get('save_action')=='view':
            return redirect('school_detail' if school else 'direction_detail',pk=obj.pk)
        return redirect(request.path+'?tab='+tab)
    context={'form':form,'unit':obj,'kind':kind,'is_school':school,'global_manager':gm,'tabs':tabs,'tab':tab,'teachers':obj.teachers.exclude(member__is_superuser=True).select_related('member') if school else [],'member_count':(obj.members if school else obj.user_set).count(),**unit_actions(request.user,obj)}
    if school:context.update(schedule_page(request,obj,editor=True))
    return render(request,'users/unit_edit.html',context)


class TeacherForm(forms.ModelForm):
    class Meta:
        model=SchoolTeacher;fields=['member','subject','bio','photo']
    def __init__(self,*args,school,user,**kwargs):
        super().__init__(*args,**kwargs);self.school=school
        self.fields['bio'].label='Об учителе'
        self.fields['member'].required=True
        self.fields['member'].queryset=eligible_members().exclude(pk__in=school.teachers.filter(member__isnull=False).exclude(pk=self.instance.pk).values('member_id'))
        self.fields['member'].label='Учитель — аккаунт на сайте'
        self.fields['member'].widget=forms.RadioSelect(attrs={'class':'member-picker'})
        self.fields['member'].empty_label=None
        self.fields['member'].label_from_instance=lambda p:f'{p.get_full_name() or p.username} · @{p.username}'
        self.fields['member'].widget.choices=self.fields['member'].choices
        self.fields['member'].help_text='Выберите один аккаунт. Для нескольких учителей создайте отдельную карточку каждому.'
        if not self.fields['member'].queryset.exists():
            self.fields['member'].help_text='Все доступные участники уже назначены учителями. Их карточки можно изменить на вкладке «Учителя».'
        if not global_manager(user):self.fields.pop('member')
    def clean_member(self):
        member=self.cleaned_data['member']
        if self.school.teachers.filter(member=member).exclude(pk=self.instance.pk).exists():raise forms.ValidationError('Этот учитель уже назначен.')
        return member

class LessonForm(forms.ModelForm):
    repeat_until=forms.DateField(label='Повторять еженедельно до',required=False,help_text='Оставьте пустым для одного занятия. Можно создать расписание на срок до года; каждую встречу затем можно изменить отдельно.',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    class Meta:
        model=SchoolLesson;fields=['topic','starts_at','ends_at','location','description','teachers','cancelled']
        widgets={'starts_at':forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}),'ends_at':forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}),'teachers':forms.CheckboxSelectMultiple(attrs={'class':'member-picker'})}
    def __init__(self,*args,school,**kwargs):
        super().__init__(*args,**kwargs);self.fields['teachers'].queryset=school.teachers.exclude(member__is_superuser=True);self.fields['teachers'].label='Учителя'
        if not self.is_bound and not self.instance.pk:
            start=(timezone.localtime()+timedelta(hours=1)).replace(minute=0,second=0,microsecond=0)
            self.initial.update(starts_at=start,ends_at=start+timedelta(hours=1))
        if self.instance.pk:self.fields.pop('repeat_until')
    def clean(self):
        data=super().clean();start=data.get('starts_at');end=data.get('ends_at');until=data.get('repeat_until')
        if start and end and end<=start:self.add_error('ends_at','Окончание должно быть позже начала.')
        if start and until and not start.date()<=until<=start.date()+timedelta(days=366):self.add_error('repeat_until','Выберите дату от первого занятия до одного года вперёд.')
        return data


@login_required
@transaction.atomic
def school_item(request,pk,item_type,item_id=None):
    school=get_object_or_404(School,pk=pk)
    if not can_edit_unit(request.user,school):return HttpResponseForbidden('Нет доступа к школе.')
    model=SchoolTeacher if item_type=='teacher' else SchoolLesson
    item=get_object_or_404(model,pk=item_id,school=school) if item_id else None
    gm=global_manager(request.user)
    if item_type=='teacher' and not gm and (not item or item.member_id!=request.user.pk or request.POST.get('action')=='delete'):return HttpResponseForbidden('Учителей назначает президент или сотрудник отдела.')
    kwargs={'instance':item,'school':school}
    if item_type=='teacher':kwargs['user']=request.user
    form=(TeacherForm if item_type=='teacher' else LessonForm)(request.POST if request.method=='POST' else None,request.FILES or None,**kwargs)
    if request.method=='POST':
        if item_type=='lesson' and item and request.POST.get('action') in {'cancel','restore'}:
            item.cancelled=request.POST['action']=='cancel';item.save(update_fields=['cancelled'])
            messages.success(request,'Занятие отменено.' if item.cancelled else 'Занятие восстановлено.')
            return redirect(reverse('school_edit',args=[pk])+'?tab=schedule&schedule=all')
        if request.POST.get('action')=='delete' and item:
            if item_type=='teacher' and item.member_id:school.leaders.remove(item.member)
            log(request.user,f'Удалено из школы {school.name}: {item}');item.delete()
            return redirect(reverse('school_edit',args=[pk])+'?tab='+('teachers' if item_type=='teacher' else 'schedule'))
        if form.is_valid():
            old_member=item.member_id if item_type=='teacher' and item else None
            item=form.save(commit=False);item.school=school
            if item_type=='teacher':item.name=item.member.get_full_name() or item.member.username
            item.save();form.save_m2m()
            if item_type=='teacher':
                if old_member and old_member!=item.member_id:school.leaders.remove(old_member)
                school.leaders.add(item.member);school.members.add(item.member)
                if school.direction_id:school.direction.user_set.add(item.member)
            elif form.cleaned_data.get('repeat_until'):
                until=form.cleaned_data['repeat_until'];start=item.starts_at+timedelta(days=7);end=item.ends_at+timedelta(days=7)
                while start.date()<=until:
                    copy=SchoolLesson.objects.create(school=school,topic=item.topic,starts_at=start,ends_at=end,location=item.location,description=item.description,cancelled=item.cancelled)
                    copy.teachers.set(item.teachers.all());start+=timedelta(days=7);end+=timedelta(days=7)
            log(request.user,f'Обновлена школа {school.name}: {item}')
            messages.success(request,'Учитель сохранён.' if item_type=='teacher' else 'Занятия сохранены и доступны на странице школы. Каждую встречу можно переносить и отменять отдельно.')
            if request.POST.get('save_action')=='view':
                return redirect(reverse('school_detail',args=[pk])+('?schedule=all#schedule' if item_type=='lesson' else '#teachers'))
            return redirect(reverse('school_edit',args=[pk])+'?tab='+('teachers' if item_type=='teacher' else 'schedule')+'&schedule=all')
    return render(request,'users/unit_item.html',{'form':form,'unit':school,'is_school':True,'item':item,'item_type':item_type,'can_delete':item_type!='teacher' or gm,'schedule_timezone':str(timezone.get_current_timezone())})


@login_required
@transaction.atomic
def create(request,kind='direction'):
    if not global_manager(request.user):return HttpResponseForbidden('Создание доступно президенту и сотрудникам отдела.')
    school=kind=='school'
    Form=AboutSchool if school else AboutDirection
    kwargs={'user':request.user} if school else {}
    form=Form(request.POST if request.method=='POST' else None,request.FILES or None,**kwargs)
    if request.method=='POST' and form.is_valid():
        obj=form.save();log(request.user,f'Создан раздел: {obj.name}')
        return redirect('school_edit' if school else 'direction_edit',pk=obj.pk)
    return render(request,'users/unit_create.html',{'form':form,'is_school':school})


@login_required
@transaction.atomic
def delete(request,pk,kind='direction'):
    if not global_manager(request.user):return HttpResponseForbidden('Удаление доступно президенту и сотрудникам отдела.')
    obj=get_unit(kind,pk)
    if request.method=='POST':
        log(request.user,f'Удалён раздел: {obj.name}');obj.delete()
        return redirect('school_catalog' if kind=='school' else 'unit_catalog')
    return render(request,'users/unit_delete.html',{'unit':obj,'kind':kind,'is_school':kind=='school'})
