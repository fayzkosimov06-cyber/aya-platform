from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from .models import User, ContributionWork, ContributionAward, ContributionChange, PointProposal, BalanceAdjustment, HomeQuote
from .permissions import allowed, rank
from .journal import emit


def can_delete_user(actor,target):
    return allowed(actor,'users_delete') and actor.pk!=target.pk and not target.is_superuser and rank(actor)>rank(target)


def erase_work(work):
    ContributionChange.objects.filter(award__work=work).delete()
    work.awards.all().delete()
    PointProposal.objects.filter(work=work).delete()
    work.delete()


class UserDeleteForm(forms.Form):
    events=forms.ModelMultipleChoiceField(queryset=None,required=False,label='Также удалить выбранные мероприятия (включая отчёты и галереи)',widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    works=forms.ModelMultipleChoiceField(queryset=None,required=False,label='Также удалить выбранные работы и их баллы у всех участников',widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    quotes=forms.ModelMultipleChoiceField(queryset=None,required=False,label='Также удалить выбранные цитаты',widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    username=forms.CharField(label='Для подтверждения введите логин удаляемого аккаунта')
    confirm=forms.BooleanField(label='Понимаю, что удаление аккаунта необратимо. Невыбранные материалы сохранятся.')
    def __init__(self,*args,target,actor,**kwargs):
        from events.models import Event
        super().__init__(*args,**kwargs);self.target=target
        self.fields['events'].queryset=Event.objects.filter(organizer=target,pk__in=[e.pk for e in Event.objects.filter(organizer=target) if allowed(actor,'events_delete',e)])
        self.fields['works'].queryset=ContributionWork.objects.filter(created_by=target) if allowed(actor,'works_delete') else ContributionWork.objects.none()
        self.fields['quotes'].queryset=HomeQuote.objects.filter(member=target) if allowed(actor,'home') else HomeQuote.objects.none()
    def clean_username(self):
        value=self.cleaned_data['username']
        if value!=self.target.username:raise forms.ValidationError('Логин не совпадает.')
        return value


@login_required
@transaction.atomic
def user_delete(request,pk):
    target=get_object_or_404(User.objects.select_for_update(),pk=pk)
    if not can_delete_user(request.user,target):return HttpResponseForbidden('Нельзя удалить себя, равного, вышестоящего или недоступного пользователя.')
    form=UserDeleteForm(request.POST if request.method=='POST' else None,target=target,actor=request.user)
    if request.method=='POST' and form.is_valid():
        request.aya_private_deletion=True
        selected=form.cleaned_data
        emit('deletion','users.User','Удалён аккаунт',before={'name':str(target),'username':target.username},after={'events':list(selected['events'].values_list('title',flat=True)),'works':list(selected['works'].values_list('title',flat=True))},object_id=target.pk,private=True)
        for work in selected['works'].select_for_update():erase_work(work)
        selected['events'].delete();selected['quotes'].delete()
        # Personal balances disappear, but other people's awards and shared works remain.
        ContributionChange.objects.filter(award__member=target).delete()
        ContributionAward.objects.filter(member=target).delete()
        BalanceAdjustment.objects.filter(member=target).delete()
        HomeQuote.objects.filter(member=target).update(author_name='Аккаунт удалён',author_role='')
        target.schoolteacher_set.update(name='Аккаунт удалён')
        target.delete()
        messages.success(request,'Аккаунт удалён. Невыбранные материалы и баллы других участников сохранены.')
        return redirect('home')
    works=ContributionWork.objects.filter(created_by=target)
    return render(request,'users/delete_account.html',{'target':target,'form':form,'works':works,'personal_points':target.point_awards.filter(revoked=False).aggregate(total=Sum('points'))['total'] or 0})


@login_required
@transaction.atomic
def work_delete(request,pk):
    if not allowed(request.user,'works_delete'):return HttpResponseForbidden('Удаление работ недоступно.')
    work=get_object_or_404(ContributionWork.objects.select_for_update(),pk=pk)
    awards=work.awards.select_related('member')
    if request.method=='POST' and request.POST.get('confirm')=='yes':
        request.aya_private_deletion=True
        emit('deletion','users.ContributionWork','Удалена работа и её начисления',before={'title':work.title,'awards':[{'member':str(a.member),'points':a.points,'revoked':a.revoked} for a in awards]},object_id=work.pk,private=True)
        erase_work(work)
        messages.success(request,'Работа удалена. Её баллы исключены у всех участников.')
        return redirect('volunteer_rating')
    return render(request,'users/delete_work.html',{'work':work,'awards':awards,'total':awards.filter(revoked=False).aggregate(n=Sum('points'))['n'] or 0})
