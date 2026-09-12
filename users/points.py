from datetime import date, timedelta
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Sum, Count
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from .access import has_full_volunteer_access, STAFF_ONLY_ROLES
from .models import User, ContributionKind, ContributionWork, ContributionAward, ContributionChange, Direction, School


def can_award(user):
    return has_full_volunteer_access(user) and (user.is_superuser or user.role in {'worker','head_admin','president'})


def members():
    return User.objects.filter(is_approved=True,is_superuser=False).exclude(role__in=STAFF_ONLY_ROLES)


def period(query, today=None):
    today=today or timezone.localdate()
    year=today.year if today.month >= 9 else today.year-1
    selected=query.get('period','year')
    if selected not in {'year','month','week','all'}: selected='year'
    try: chosen=int(query.get('year',year))
    except (ValueError,TypeError): chosen=year
    if not 1900 <= chosen <= year: chosen=year
    if selected=='all': start=None; end=None
    elif selected=='week': start=today-timedelta(days=today.weekday());end=start+timedelta(days=7)
    elif selected=='month':
        start=today.replace(day=1);end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
    else: start=date(chosen,9,1);end=date(chosen+1,9,1)
    years=set(ContributionWork.objects.values_list('date',flat=True))
    years={d.year if d.month>=9 else d.year-1 for d in years}|{year}
    return {'period':selected,'selected_year':chosen,'years':[(y,f'{y}/{y+1}') for y in sorted(years,reverse=True)],'start':start,'end':end}


def selected_awards(query, member=None):
    info=period(query)
    qs=ContributionAward.objects.filter(revoked=False)
    if member is not None: qs=qs.filter(member=member)
    if info['start']: qs=qs.filter(work__date__gte=info['start'],work__date__lt=info['end'])
    return qs,info


def point_profile(request, member):
    qs,info=selected_awards(request.GET,member)
    current,_=selected_awards({},member)
    return {**info,'point_page':Paginator(qs.select_related('work','kind','confirmed_by').order_by('-work__date','-pk'),10).get_page(request.GET.get('points_page')),
            'year_points':current.aggregate(n=Sum('points'))['n'] or 0,
            'all_points':ContributionAward.objects.filter(member=member,revoked=False).aggregate(n=Sum('points'))['n'] or 0,'can_award_points':can_award(request.user)}


def points_rating(request):
    if not has_full_volunteer_access(request.user): return render(request,'users/points_rating.html',{'locked':True})
    qs,info=selected_awards(request.GET)
    totals=dict(qs.values('member_id').annotate(total=Sum('points')).values_list('member_id','total'))
    rows=[{'member':m,'points':totals[m.pk]} for m in members().filter(pk__in=totals)]
    rows.sort(key=lambda r:(-r['points'],r['member'].last_name,r['member'].first_name,r['member'].pk))
    last=None;place=0
    for i,row in enumerate(rows,1):
        if row['points']!=last: place=i
        row['place']=place;last=row['points']
    work_counts=dict(qs.values('member_id').annotate(n=Count('work_id',distinct=True)).values_list('member_id','n'))
    for row in rows: row['works']=work_counts.get(row['member'].pk,0)
    page=Paginator(rows,30).get_page(request.GET.get('page'))
    return render(request,'users/points_rating.html',{**info,'ranked_count':len(rows),'awarded_points':sum(r['points'] for r in rows),'my_rank':next((r for r in rows if r['member'].pk==request.user.pk),None),'rows':page,'leaders':[r for r in rows if r['place']<=3] if page.number==1 else [],'can_award_points':can_award(request.user)})


class KindForm(forms.ModelForm):
    class Meta:
        model=ContributionKind
        fields=['name','points','active']
    def clean_points(self):
        n=self.cleaned_data['points']
        if not 1<=n<=1000000: raise forms.ValidationError('Введите от 1 до 1 000 000 баллов.')
        return n


class WorkForm(forms.ModelForm):
    class Meta:
        model=ContributionWork
        fields=['title','date','description']
        widgets={'date':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'})}
    def clean_date(self):
        d=self.cleaned_data['date']
        if d>timezone.localdate(): raise forms.ValidationError('Нельзя начислять за ещё не выполненную работу.')
        return d


class AwardForm(forms.Form):
    kind=forms.ModelChoiceField(queryset=ContributionKind.objects.filter(active=True),label='Вид вклада')
    volunteers=forms.ModelMultipleChoiceField(queryset=User.objects.none(),label='Волонтёры',widget=forms.CheckboxSelectMultiple)
    comment=forms.CharField(label='Комментарий',required=False,widget=forms.Textarea)
    def __init__(self,*args,work,**kwargs):
        super().__init__(*args,**kwargs)
        qs=members()
        if work.event_id: qs=qs.filter(attending_events=work.event)
        self.fields['volunteers'].queryset=qs.order_by('last_name','first_name','pk')


def snapshot(award):
    return {'points':award.points,'comment':award.comment,'revoked':award.revoked}


@login_required
@transaction.atomic
def work_list(request):
    if not can_award(request.user): return HttpResponseForbidden('Нет доступа к начислениям.')
    event=None
    if request.GET.get('event'):
        from events.models import Event
        event=get_object_or_404(Event,pk=request.GET['event'],is_approved=True)
        existing=ContributionWork.objects.filter(event=event).first()
        if existing:return redirect('points_work',pk=existing.pk)
    form=WorkForm(request.POST or None,initial={'title':event.title if event else '', 'date':timezone.localdate(event.end_time) if event else timezone.localdate()})
    if request.method=='POST' and form.is_valid():
        work=form.save(commit=False);work.created_by=request.user;work.event=event
        if event:
            if event.aya_schools.count()==1:
                work.school=event.aya_schools.first();work.direction=work.school.direction
            elif event.aya_directions.count()==1: work.direction=event.aya_directions.first()
        work.save()
        return redirect('points_work',pk=work.pk)
    works=ContributionWork.objects.all()
    q=request.GET.get('q','').strip()
    if q:works=works.filter(title__icontains=q)
    return render(request,'users/points_work_list.html',{'form':form,'works':Paginator(works,25).get_page(request.GET.get('page')),'q':q,'event':event})


@login_required
@transaction.atomic
def work_detail(request,pk):
    if not can_award(request.user): return HttpResponseForbidden('Нет доступа к начислениям.')
    work=get_object_or_404(ContributionWork,pk=pk)
    form=AwardForm(request.POST or None,work=work)
    if request.method=='POST' and form.is_valid():
        kind=form.cleaned_data['kind'];created=0
        for member in form.cleaned_data['volunteers']:
            award,new=ContributionAward.objects.get_or_create(work=work,member=member,kind=kind,defaults={'points':kind.points,'comment':form.cleaned_data['comment'],'confirmed_by':request.user})
            if new:
                ContributionChange.objects.create(award=award,actor=request.user,after=snapshot(award),reason='Начисление');created+=1
        messages.success(request,f'Начислено участникам: {created}. Существующие начисления не изменены; отменённые можно восстановить через исправление.')
        return redirect('points_work',pk=pk)
    return render(request,'users/points_work.html',{'work':work,'form':form,'awards':work.awards.select_related('member','kind','confirmed_by').prefetch_related('changes__actor')})


class CorrectionForm(forms.Form):
    points=forms.IntegerField(label='Баллы',min_value=1,max_value=1000000)
    comment=forms.CharField(label='Комментарий',required=False,widget=forms.Textarea)
    revoked=forms.BooleanField(label='Отменить начисление',required=False)
    reason=forms.CharField(label='Причина исправления',widget=forms.Textarea)


@login_required
@transaction.atomic
def correct_award(request,pk):
    if not can_award(request.user):return HttpResponseForbidden('Нет доступа к начислениям.')
    award=get_object_or_404(ContributionAward.objects.select_for_update(),pk=pk)
    form=CorrectionForm(request.POST or None,initial=snapshot(award))
    if request.method=='POST' and form.is_valid():
        before=snapshot(award)
        for field in ['points','comment','revoked']:setattr(award,field,form.cleaned_data[field])
        award.save()
        ContributionChange.objects.create(award=award,actor=request.user,before=before,after=snapshot(award),reason=form.cleaned_data['reason'])
        return redirect('points_work',pk=award.work_id)
    return render(request,'users/points_form.html',{'form':form,'heading':'Исправление начисления','back':award.work_id})


@login_required
@transaction.atomic
def kinds(request):
    if not can_award(request.user):return HttpResponseForbidden('Нет доступа к правилам.')
    instance=get_object_or_404(ContributionKind,pk=request.GET['edit']) if request.GET.get('edit') else None
    form=KindForm(request.POST or None,instance=instance)
    if request.method=='POST' and form.is_valid():
        from .models import AuditLog
        obj=form.save()
        AuditLog.objects.create(actor=request.user,action=f'Правило баллов: {obj.name}, {obj.points}, активно: {obj.active}')
        return redirect('points_kinds')
    return render(request,'users/points_kinds.html',{'form':form,'kinds':ContributionKind.objects.all()})


class QuickAwardForm(forms.Form):
    direction=forms.ModelChoiceField(queryset=Direction.objects.all(),required=False,label='Направление')
    school=forms.ModelChoiceField(queryset=School.objects.all(),required=False,label='Школа')
    work=forms.ModelChoiceField(queryset=ContributionWork.objects.all(),required=False,label='Продолжить существующую работу')
    title=forms.CharField(max_length=200,required=False,label='За что начисляем')
    date=forms.DateField(label='Дата помощи',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    kind=forms.ModelChoiceField(queryset=ContributionKind.objects.filter(active=True),required=False,label='Готовое правило (необязательно)')
    points=forms.IntegerField(label='Баллы каждому',min_value=1,max_value=1000000)
    volunteers=forms.ModelMultipleChoiceField(queryset=members(),label='Кому начислить',widget=forms.CheckboxSelectMultiple)
    comment=forms.CharField(required=False,label='Комментарий',widget=forms.Textarea(attrs={'rows':3}))
    token=forms.UUIDField(widget=forms.HiddenInput)

    def clean(self):
        data=super().clean()
        if not data.get('work') and not data.get('title'):self.add_error('title','Напишите, за какую помощь начисляются баллы.')
        if data.get('date') and data['date']>timezone.localdate():self.add_error('date','Выберите сегодняшнюю или прошедшую дату.')
        work=data.get('work')
        direction=data.get('direction');school=data.get('school')
        if not work:
            if school and direction and school.direction_id!=direction.pk:self.add_error('school','Школа должна относиться к выбранному направлению.')
            if school and not direction:data['direction']=school.direction
        if work and work.event_id and data.get('volunteers'):
            allowed=set(work.event.participants.values_list('pk',flat=True))
            if any(m.pk not in allowed for m in data['volunteers']):self.add_error('volunteers','Для этой работы выберите только зарегистрированных участников мероприятия.')
        return data


@login_required
@transaction.atomic
def quick_award(request):
    import uuid
    if not can_award(request.user):return HttpResponseForbidden('Нет доступа к начислениям.')
    initial={'date':timezone.localdate(),'token':uuid.uuid4()}
    for key,model in [('direction',Direction),('school',School)]:
        if request.GET.get(key,'').isdigit():initial[key]=get_object_or_404(model,pk=request.GET[key]).pk
    if request.GET.get('member','').isdigit():initial['volunteers']=[int(request.GET['member'])]
    if request.GET.get('work','').isdigit():
        work=get_object_or_404(ContributionWork,pk=request.GET['work'])
        initial.update(work=work,date=work.date)
    form=QuickAwardForm(request.POST if request.method=='POST' else None,initial=initial)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        work=data.get('work')
        if work is None:
            work,_=ContributionWork.objects.get_or_create(submission=data['token'],defaults={'title':data['title'],'date':data['date'],'description':data['comment'],'created_by':request.user,'direction':data.get('direction'),'school':data.get('school')})
        kind=data.get('kind')
        if kind is None:
            kind,_=ContributionKind.objects.get_or_create(name='Помощь — прямое начисление',defaults={'points':1,'active':False})
        created=0
        for member in data['volunteers']:
            award,new=ContributionAward.objects.get_or_create(work=work,member=member,kind=kind,defaults={'points':data['points'],'comment':data['comment'],'confirmed_by':request.user})
            if new:
                ContributionChange.objects.create(award=award,actor=request.user,after=snapshot(award),reason='Начисление');created+=1
        if created:messages.success(request,f'Сохранено: {created} участникам начислено по {data["points"]} баллов.')
        else:messages.info(request,'Эти начисления уже существуют. Баллы не продублированы. Для изменения откройте запись ниже.')
        return redirect('points_work',pk=work.pk)
    selected={str(v) for v in (request.POST.getlist('volunteers') if request.method=='POST' else initial.get('volunteers',[]))}
    people=members()
    scope=request.POST if request.method=='POST' else initial
    team_ids=[]
    if str(scope.get('school','')).isdigit(): team_ids=list(people.filter(aya_schools=scope['school']).values_list('pk',flat=True))
    elif str(scope.get('direction','')).isdigit(): team_ids=list(people.filter(directions=scope['direction']).values_list('pk',flat=True))
    people=list(people.order_by('last_name','first_name'))
    people.sort(key=lambda person: person.pk not in team_ids)
    return render(request,'users/points_quick.html',{'form':form,'people':people,'team_ids':team_ids,'selected':selected,'rules':list(ContributionKind.objects.filter(active=True).values('id','points'))})
