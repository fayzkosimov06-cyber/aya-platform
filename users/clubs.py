from datetime import timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from .models import Club, ClubMeeting, Direction, School, PointProposal
from .permissions import allowed, rank, setting
from .units import people_field
from .points import members
from .proposals import ProposalForm


def all_clubs(user):
    rule = setting(user,'clubs') if user.is_authenticated else None
    return allowed(user,'clubs') and (user.is_superuser or (rule.scope == 'all' if rule else user.role in {'president','worker','head_admin'}))


class ClubForm(forms.ModelForm):
    class Meta:
        model=Club
        fields=['name','intro','description','cover','logo','active','school','direction']

    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk and not all_clubs(user):
            self.fields.pop('school'); self.fields.pop('direction')
        else:
            self.fields['school'].queryset=School.objects.filter(pk__in=[o.pk for o in School.objects.all() if allowed(user,'schools',o)])
            self.fields['direction'].queryset=Direction.objects.filter(pk__in=[o.pk for o in Direction.objects.all() if allowed(user,'directions',o)])
            self.fields['school'].help_text='При выборе школы направление наследуется от неё.'

    def clean(self):
        data=super().clean()
        if data.get('school'):data['direction']=data['school'].direction
        return data


class TeamForm(forms.Form):
    members=people_field('Участники')
    featured_members=people_field('Активная команда')
    def __init__(self,*args,user,club,**kwargs):
        self.user=user;self.club=club
        super().__init__(*args,**kwargs)
        self.fields['members'].help_text='Снятие участника также снимает его назначение ответственным. Аккаунт и баллы сохраняются.'
    def clean(self):
        data=super().clean()
        if 'members' in data and 'featured_members' in data and not set(data['featured_members']).issubset(set(data['members'])):
            self.add_error('featured_members','Активная команда должна входить в состав участников.')
        if 'members' in data:
            removed=self.club.leaders.exclude(pk__in=data['members'])
            if removed.exists() and (not allowed(self.user,'club_appointments',self.club) or (not self.user.is_superuser and any(p.pk==self.user.pk or rank(p)>=rank(self.user) for p in removed))):
                self.add_error('members','Снять ответственного может пользователь с правом назначения и более высоким уровнем. Остальных участников можно изменять отдельно.')
        return data


class LeadersForm(forms.Form):
    leaders=people_field('Ответственные')
    def __init__(self,*args,user,club,**kwargs):
        self.user=user;self.club=club
        super().__init__(*args,**kwargs)
    def clean_leaders(self):
        selected=self.cleaned_data['leaders']
        changed=set(selected.values_list('pk',flat=True)) ^ set(self.club.leaders.values_list('pk',flat=True))
        if not self.user.is_superuser and (rank(self.user)<=30 or any(p.pk==self.user.pk or rank(p)>=rank(self.user) for p in members().filter(pk__in=changed))):
            raise forms.ValidationError('Нельзя менять назначение себя, равного или вышестоящего пользователя.')
        return selected


class MeetingForm(forms.ModelForm):
    repeat_until=forms.DateField(label='Повторять еженедельно до',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    class Meta:
        model=ClubMeeting
        fields=['topic','starts_at','ends_at','location','description','cancelled']
        widgets={key:forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}) for key in ['starts_at','ends_at']}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.pk:self.fields.pop('repeat_until')
    def clean(self):
        data=super().clean();start=data.get('starts_at');end=data.get('ends_at');until=data.get('repeat_until')
        if start and end and end<=start:self.add_error('ends_at','Окончание должно быть позже начала.')
        if start and until and not start.date()<=until<=start.date()+timedelta(days=366):self.add_error('repeat_until','Повторы доступны на срок до года.')
        return data


def catalog(request):
    qs=Club.objects.select_related('school','direction').prefetch_related('leaders','meetings').order_by('name');q=request.GET.get('q','').strip()[:200]
    if q:qs=qs.filter(Q(name__icontains=q)|Q(intro__icontains=q))
    for field in ['school','direction']:
        if request.GET.get(field,'').isdigit():qs=qs.filter(**{field+'_id':request.GET[field]})
    page=Paginator(qs,12).get_page(request.GET.get('page'))
    for item in page:
        item.public_leaders=[p for p in item.leaders.all() if p.is_approved and not p.is_superuser]
        item.next_meeting=next((m for m in sorted(item.meetings.all(),key=lambda m:m.starts_at) if not m.cancelled and m.ends_at>=timezone.now()),None)
    return render(request,'users/club_catalog.html',{'clubs':page,'q':q,'can_create':all_clubs(request.user)})


def detail(request,pk):
    club=get_object_or_404(Club.objects.select_related('school','direction'),pk=pk)
    people=members().filter(aya_clubs=club).exclude(pk__in=club.leaders.values('pk'))
    featured=club.featured_members.filter(pk__in=people.values('pk'))
    if featured.exists() and request.GET.get('team')!='all':people=featured
    meetings=club.meetings.all();schedule=request.GET.get('schedule','upcoming')
    if schedule=='past':meetings=meetings.filter(ends_at__lt=timezone.now(),cancelled=False).order_by('-starts_at')
    elif schedule=='cancelled':meetings=meetings.filter(cancelled=True)
    elif schedule!='all':
        schedule='upcoming';meetings=meetings.filter(ends_at__gte=timezone.now(),cancelled=False)
    events=club.events.filter(is_approved=True)
    from .access import has_full_volunteer_access
    if not has_full_volunteer_access(request.user):events=events.filter(is_public_for_guests=True)
    return render(request,'users/club_detail.html',{'club':club,'people':Paginator(people.order_by('last_name','pk'),18).get_page(request.GET.get('people_page')),'featured':featured.exists(),'show_all':request.GET.get('team')=='all','leaders':club.leaders.filter(is_approved=True,is_superuser=False),'meetings':Paginator(meetings,10).get_page(request.GET.get('page')),'schedule':schedule,'events':events.order_by('-start_time')[:8],'can_manage':allowed(request.user,'clubs',club),'can_event':allowed(request.user,'events_edit',club),'can_propose':allowed(request.user,'points_propose',club)})


@login_required
@transaction.atomic
def edit(request,pk=None):
    club=get_object_or_404(Club.objects.select_for_update(),pk=pk) if pk else None
    if not (allowed(request.user,'clubs',club) if club else all_clubs(request.user)):return HttpResponseForbidden('Нет доступа к клубу.')
    tab=request.GET.get('tab','about') if club else 'about'
    if tab not in {'about','members','leaders','schedule'}:return HttpResponseForbidden('Неизвестный раздел.')
    appoint=club and allowed(request.user,'club_appointments',club)
    if tab=='leaders' and not appoint:return HttpResponseForbidden('Назначение ответственных недоступно.')
    data=request.POST if request.method=='POST' else None;form=None
    if tab=='about':form=ClubForm(data,request.FILES or None,instance=club,user=request.user)
    elif tab=='members':form=TeamForm(data,user=request.user,club=club,initial={'members':club.members.all(),'featured_members':club.featured_members.all()})
    elif tab=='leaders':form=LeadersForm(data,user=request.user,club=club,initial={'leaders':club.leaders.all()})
    if request.method=='POST' and form and form.is_valid():
        if tab=='about':club=form.save()
        elif tab=='members':
            club.leaders.remove(*club.leaders.exclude(pk__in=form.cleaned_data['members']))
            club.members.set(form.cleaned_data['members']);club.featured_members.set(form.cleaned_data['featured_members'])
        else:
            club.leaders.set(form.cleaned_data['leaders']);club.members.add(*form.cleaned_data['leaders'])
        messages.success(request,'Изменения сохранены.')
        return redirect(reverse('club_edit',args=[club.pk])+'?tab='+tab)
    return render(request,'users/club_edit.html',{'club':club,'form':form,'tab':tab,'can_appoint':appoint,'can_delete':all_clubs(request.user),'meetings':Paginator(club.meetings.all(),15).get_page(request.GET.get('page')) if club else None})


@login_required
@transaction.atomic
def delete(request,pk):
    club=get_object_or_404(Club.objects.select_for_update(),pk=pk)
    if not all_clubs(request.user):return HttpResponseForbidden('Удаление клуба требует права управления всеми клубами.')
    if request.method=='POST' and request.POST.get('confirm')=='yes':
        club.delete();messages.success(request,'Клуб удалён. Аккаунты, мероприятия и начисленные баллы сохранены.')
        return redirect('club_catalog')
    return render(request,'users/club_delete.html',{'club':club})


@login_required
@transaction.atomic
def meeting(request,pk,item_id=None):
    club=get_object_or_404(Club,pk=pk)
    if not allowed(request.user,'clubs',club):return HttpResponseForbidden('Нет доступа к клубу.')
    item=get_object_or_404(ClubMeeting,pk=item_id,club=club) if item_id else None
    form=MeetingForm(request.POST if request.method=='POST' else None,instance=item)
    if request.method=='POST':
        action=request.POST.get('action','save')
        if item and action in {'cancel','restore','delete'}:
            if action=='delete':item.delete()
            else:item.cancelled=action=='cancel';item.save(update_fields=['cancelled'])
            return redirect(reverse('club_edit',args=[pk])+'?tab=schedule')
        if form.is_valid():
            obj=form.save(commit=False);obj.club=club;obj.save()
            until=form.cleaned_data.get('repeat_until')
            if until:
                start=obj.starts_at+timedelta(days=7);end=obj.ends_at+timedelta(days=7)
                while start.date()<=until:
                    ClubMeeting.objects.create(club=club,topic=obj.topic,starts_at=start,ends_at=end,location=obj.location,description=obj.description,cancelled=obj.cancelled)
                    start+=timedelta(days=7);end+=timedelta(days=7)
            return redirect(reverse('club_edit',args=[pk])+'?tab=schedule')
    return render(request,'users/club_meeting.html',{'club':club,'item':item,'form':form})


@login_required
def suggest(request,pk):
    club=get_object_or_404(Club,pk=pk)
    if not allowed(request.user,'points_propose',club):return HttpResponseForbidden('Заявки недоступны.')
    form=ProposalForm(request.POST if request.method=='POST' else None,initial={'date':timezone.localdate()})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            item=form.save(commit=False);item.author=request.user;item.club=club;item.school=club.school;item.direction=club.direction;item.save();form.save_m2m()
        return redirect('proposal_list')
    return render(request,'users/club_meeting.html',{'club':club,'form':form,'proposal':True})
