from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q, Sum
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from .models import Direction, School, User, SchoolTeacher, SchoolLesson, AuditLog, ContributionAward
from .access import has_full_volunteer_access
from .points import can_award, members as eligible_members
from events.models import Event


def global_manager(user):
    from .permissions import allowed,setting,request_context
    if allowed(user,'people'):return True
    req=request_context.get();code=getattr(req,'aya_capability',None)
    rule=setting(user,code) if code in {'directions','schools'} and user.is_authenticated else None
    return bool(rule and rule.enabled and allowed(user,code,getattr(req,'aya_object',None)))


def can_edit_unit(user,obj):
    from .permissions import allowed,request_context
    req=request_context.get();code=getattr(req,'aya_capability',None)
    return allowed(user, code if code in {'points_propose','directions','schools'} else ('schools' if isinstance(obj,School) else 'directions'),obj)


def get_unit(kind,pk): return get_object_or_404(School if kind=='school' else Direction,pk=pk)

def log(user,text): AuditLog.objects.create(actor=user,action=text)


def catalog(request,kind='direction'):
    school=kind=='school';query=request.GET.get('q','').strip();inactive=request.GET.get('state')=='inactive'
    objects=School.objects.select_related('direction').filter(active=not inactive) if school else Direction.objects.all()
    if school and request.GET.get('direction','').isdigit():objects=objects.filter(direction_id=request.GET['direction'])
    if query:objects=objects.filter(name__icontains=query)
    page=Paginator(objects.order_by('name'),18).get_page(request.GET.get('page'))
    request.aya_result_count=page.paginator.count
    for obj in page:obj.manage_allowed=can_edit_unit(request.user,obj)
    return render(request,'users/unit_catalog.html',{'objects':page,'kind':kind,'is_school':school,'global_manager':global_manager(request.user),'q':query,'inactive':inactive,'directions':Direction.objects.all(),'filter_direction':request.GET.get('direction','')})


def detail(request,pk,kind='direction'):
    obj=get_unit(kind,pk);school=kind=='school';can_edit=can_edit_unit(request.user,obj)
    people=eligible_members().filter(aya_schools=obj) if school else eligible_members().filter(directions=obj)
    count=people.count()
    if not school and obj.featured_only:people=people.filter(featured_in_directions=obj)
    events=obj.events.filter(is_approved=True)
    if not has_full_volunteer_access(request.user):events=events.filter(is_public_for_guests=True)
    upcoming=events.filter(is_completed=False,cancelled=False,end_time__gte=timezone.now()).order_by('start_time')
    from datetime import date
    today=timezone.localdate();year=today.year-(today.month<9)
    awards=ContributionAward.objects.filter(revoked=False,work__date__gte=date(year,9,1),work__date__lt=date(year+1,9,1))
    awards=awards.filter(work__school=obj) if school else awards.filter(Q(work__direction=obj)|Q(work__school__direction=obj))
    lessons=obj.lessons.filter(ends_at__gte=timezone.now()).prefetch_related('teachers') if school and obj.active else SchoolLesson.objects.none()
    return render(request,'users/unit_detail.html',{'unit':obj,'is_school':school,'kind':kind,'unit_can_manage':can_edit,'can_edit_unit':can_edit,'global_manager':global_manager(request.user),'can_award_points':can_award(request.user),'unit_leaders':obj.leaders.filter(is_approved=True,is_superuser=False) if not school else [],'member_count':count,'member_page':Paginator(people.order_by('last_name','first_name','pk'),24).get_page(request.GET.get('page')),'upcoming':upcoming[:8],'schools':obj.schools.filter(active=True) if not school else [],'teachers':obj.teachers.exclude(member__is_superuser=True).select_related('member') if school else [],'lessons':Paginator(lessons,20).get_page(request.GET.get('lessons_page')),'unit_points':awards.aggregate(n=Sum('points'))['n'] if has_full_volunteer_access(request.user) else None})


class PeopleField(forms.ModelMultipleChoiceField):
    def label_from_instance(self,obj):return f'{obj.get_full_name() or obj.username} · @{obj.username}'


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
    def __init__(self,*args,obj,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj
        self.fields['members']=people_field('Участники')
        self.initial['members']=(obj.members if isinstance(obj,School) else obj.user_set).values_list('pk',flat=True)
    def save(self):
        selected=self.cleaned_data['members']
        if isinstance(self.obj,School):
            self.obj.members.set(selected)
            if self.obj.direction_id:self.obj.direction.user_set.add(*selected)
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
        self.fields['featured_members']=people_field('Активная команда',eligible_members().filter(directions=obj))
        self.initial.update(featured_only=obj.featured_only,featured_members=obj.featured_members.values_list('pk',flat=True))
    def save(self):
        self.obj.featured_only=self.cleaned_data['featured_only'];self.obj.save(update_fields=['featured_only'])
        self.obj.featured_members.set(self.cleaned_data['featured_members'])

class EventForm(forms.Form):
    events=forms.ModelMultipleChoiceField(queryset=Event.objects.filter(is_approved=True),required=False,label='Мероприятия',widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    def __init__(self,*args,obj,user=None,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj;self.initial['events']=obj.events.values_list('pk',flat=True)
        if user and not global_manager(user):self.fields['events'].queryset=obj.events.filter(is_approved=True)
    def save(self): self.obj.events.set(self.cleaned_data['events'])

class SchoolLinkForm(forms.Form):
    schools=forms.ModelMultipleChoiceField(queryset=School.objects.all(),required=False,label='Школы этого направления',widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    def __init__(self,*args,obj,**kwargs):
        super().__init__(*args,**kwargs);self.obj=obj;self.initial['schools']=obj.schools.values_list('pk',flat=True)
    def save(self):
        selected=self.cleaned_data['schools']
        for school in self.obj.schools.exclude(pk__in=selected):school.direction=None;school.save(update_fields=['direction'])
        for school in selected:school.direction=self.obj;school.save(update_fields=['direction'])
        for school in selected:self.obj.user_set.add(*school.members.all())


@login_required
@transaction.atomic
def edit(request,pk,kind='direction'):
    obj=get_unit(kind,pk)
    if not can_edit_unit(request.user,obj):return HttpResponseForbidden('Нет доступа к управлению этим разделом.')
    school=kind=='school';gm=global_manager(request.user)
    tabs=[('about','О странице'),('members','Участники')]
    if school:tabs += [('teachers','Учителя'),('schedule','Расписание')]
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
    elif tab in {'members','featured','leaders','schools'}:form={'members':MemberForm,'featured':FeatureForm,'leaders':LeaderForm,'events':EventForm,'schools':SchoolLinkForm}[tab](data,obj=obj)
    if request.method=='POST' and form and form.is_valid():
        form.save()
        if school and obj.direction_id:obj.direction.user_set.add(*obj.members.all())
        log(request.user,f'Изменён раздел «{dict(tabs)[tab]}»: {obj.name}')
        messages.success(request,'Изменения сохранены.')
        return redirect(request.path+'?tab='+tab)
    return render(request,'users/unit_edit.html',{'form':form,'unit':obj,'kind':kind,'is_school':school,'global_manager':gm,'tabs':tabs,'tab':tab,'teachers':obj.teachers.exclude(member__is_superuser=True).select_related('member') if school else [],'lessons':obj.lessons.prefetch_related('teachers') if school else [],'can_award_points':can_award(request.user)})


class TeacherForm(forms.ModelForm):
    class Meta:
        model=SchoolTeacher;fields=['member','subject','bio','photo']
    def __init__(self,*args,school,user,**kwargs):
        super().__init__(*args,**kwargs);self.school=school
        self.fields['bio'].label='Об учителе'
        self.fields['member'].required=True;self.fields['member'].queryset=eligible_members();self.fields['member'].label='Учитель — аккаунт на сайте'
        if not global_manager(user):self.fields.pop('member')
    def clean_member(self):
        member=self.cleaned_data['member']
        if self.school.teachers.filter(member=member).exclude(pk=self.instance.pk).exists():raise forms.ValidationError('Этот учитель уже назначен.')
        return member

class LessonForm(forms.ModelForm):
    repeat_until=forms.DateField(label='Повторять еженедельно до (необязательно)',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    class Meta:
        model=SchoolLesson;fields=['topic','starts_at','ends_at','location','description','teachers','cancelled']
        widgets={'starts_at':forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}),'ends_at':forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}),'teachers':forms.CheckboxSelectMultiple(attrs={'class':'member-picker'})}
    def __init__(self,*args,school,**kwargs):
        super().__init__(*args,**kwargs);self.fields['teachers'].queryset=school.teachers.filter(member__isnull=False,member__is_superuser=False);self.fields['teachers'].label='Учителя'
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
        if request.POST.get('action')=='delete' and item:
            if item_type=='teacher' and item.member_id:school.leaders.remove(item.member)
            log(request.user,f'Удалено из школы {school.name}: {item}');item.delete()
            return redirect('school_edit',pk=pk)
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
            messages.success(request,'Сохранено. Каждое занятие можно переносить и отменять отдельно.')
            return redirect('school_edit',pk=pk)
    return render(request,'users/unit_item.html',{'form':form,'unit':school,'item':item,'item_type':item_type,'can_delete':item_type!='teacher' or gm})


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
