from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.paginator import Paginator
from django.http import HttpResponseForbidden
from django.shortcuts import render,redirect,get_object_or_404
from django.utils import timezone
from .models import PointProposal,ContributionWork,ContributionKind,ContributionAward,ContributionChange
from .units import get_unit,can_edit_unit,global_manager,people_field,log
from .points import snapshot
from .permissions import allowed

class ProposalForm(forms.ModelForm):
    volunteers=people_field('Кому предложить баллы (можно выбрать помощников вне команды)')
    class Meta:
        model=PointProposal;fields=['title','date','description','volunteers'];widgets={'date':forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'})}
    def clean_volunteers(self):
        people=self.cleaned_data['volunteers']
        if not people:raise forms.ValidationError('Выберите хотя бы одного волонтёра.')
        return people
    def clean_date(self):
        d=self.cleaned_data['date']
        if d>timezone.localdate():raise forms.ValidationError('Помощь должна быть уже выполнена.')
        return d

class ReviewForm(forms.Form):
    decision=forms.ChoiceField(label='Решение',choices=[('approved','Подтвердить'),('rejected','Отклонить')])
    points=forms.IntegerField(label='Баллы каждому участнику',min_value=1,max_value=1000000,required=False)
    note=forms.CharField(label='Комментарий / причина',required=False,widget=forms.Textarea)
    def clean(self):
        data=super().clean()
        if data.get('decision')=='approved' and not data.get('points'):self.add_error('points','Укажите количество баллов.')
        if data.get('decision')=='rejected' and not data.get('note'):self.add_error('note','Объясните причину отклонения.')
        return data

@login_required
@transaction.atomic
def suggest(request,pk,kind='direction'):
    obj=get_unit(kind,pk)
    if not can_edit_unit(request.user,obj):return HttpResponseForbidden('Нет доступа к разделу.')
    form=ProposalForm(request.POST if request.method=='POST' else None,initial={'date':timezone.localdate()})
    if request.method=='POST' and form.is_valid():
        proposal=form.save(commit=False);proposal.author=request.user
        if kind=='school':proposal.school=obj;proposal.direction=obj.direction
        else:proposal.direction=obj
        proposal.save();form.save_m2m();log(request.user,f'Заявка на баллы #{proposal.pk}: {proposal.title}')
        messages.success(request,'Заявка отправлена президенту и сотрудникам отдела.')
        return redirect('proposal_list')
    return render(request,'users/proposal_form.html',{'form':form,'unit':obj})

@login_required
def listing(request):
    proposals=PointProposal.objects.select_related('author','school','direction').order_by('-created_at')
    gm=allowed(request.user,'points_review')
    if not gm:proposals=proposals.filter(author=request.user)
    status=request.GET.get('status','pending')
    if status in {'pending','approved','rejected'}:proposals=proposals.filter(status=status)
    else:status='all'
    return render(request,'users/proposal_list.html',{'proposals':Paginator(proposals,25).get_page(request.GET.get('page')),'status':status,'global_manager':gm})

@login_required
@transaction.atomic
def review(request,pk):
    if not allowed(request.user,'points_review'):return HttpResponseForbidden('Баллы подтверждает президент или сотрудник отдела.')
    proposal=get_object_or_404(PointProposal.objects.select_for_update(),pk=pk)
    form=ReviewForm(request.POST if request.method=='POST' else None)
    valid=request.method=='POST' and proposal.status=='pending' and form.is_valid()
    if valid and form.cleaned_data['decision']=='approved' and proposal.event_id and proposal.volunteers.exclude(attending_events=proposal.event).exists():
        form.add_error(None,'Состав мероприятия изменился: некоторые люди из заявки больше не записаны. Проверьте участников перед начислением.');valid=False
    if valid:
        data=form.cleaned_data
        if data['decision']=='approved':
            if proposal.event_id:
                work,_=ContributionWork.objects.get_or_create(event=proposal.event,defaults={'title':proposal.title,'date':proposal.date,'description':proposal.description,'direction':proposal.direction,'school':proposal.school,'created_by':request.user})
            else:
                work=ContributionWork.objects.create(title=proposal.title,date=proposal.date,description=proposal.description,direction=proposal.direction,school=proposal.school,created_by=request.user)
            kind,_=ContributionKind.objects.get_or_create(name=f'Заявка на участие #{proposal.pk}' if proposal.event_id else 'Подтверждённая помощь по заявке',defaults={'points':1,'active':False})
            for member in proposal.volunteers.all():
                award=ContributionAward.objects.create(work=work,member=member,kind=kind,points=data['points'],comment=proposal.description,confirmed_by=request.user)
                ContributionChange.objects.create(award=award,actor=request.user,after=snapshot(award),reason=f'Подтверждение заявки #{proposal.pk}')
            proposal.work=work
        proposal.status=data['decision'];proposal.reviewer=request.user;proposal.reviewed_at=timezone.now();proposal.review_note=data['note'];proposal.save()
        log(request.user,f'Заявка #{proposal.pk}: {proposal.get_status_display()}')
        messages.success(request,'Решение сохранено.');return redirect('proposal_list')
    return render(request,'users/proposal_review.html',{'proposal':proposal,'form':form})
