from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import StaffApplication, User


class StaffSignupForm(UserCreationForm):
    requested_role = forms.ChoiceField(label='Должность', choices=StaffApplication._meta.get_field('requested_role').choices)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username','first_name','last_name','email','job_title','office_location')
        labels = {'job_title':'Рабочая должность','office_location':'Кабинет'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('first_name','last_name','email'):
            self.fields[name].required = True


class StaffAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not (user.is_superuser or user.role in {'worker','head_admin'}):
            raise forms.ValidationError('Этот вход предназначен для сотрудников. Волонтёры входят через основной вход.', code='staff_only')


class StaffLoginView(LoginView):
    template_name = 'users/staff_login.html'
    authentication_form = StaffAuthenticationForm


@transaction.atomic
def signup(request):
    form = StaffSignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save(commit=False)
        # Requested status is never an effective role before explicit review.
        user.role = 'volunteer'
        user.is_active = False
        user.is_approved = False
        user.save()
        StaffApplication.objects.create(user=user, requested_role=form.cleaned_data['requested_role'])
        return render(request, 'users/staff_signup.html', {'submitted':True})
    return render(request, 'users/staff_signup.html', {'form':form})


@login_required
@transaction.atomic
def applications(request):
    if not (request.user.is_superuser or request.user.role == 'head_admin'):
        return HttpResponseForbidden('Заявки сотрудников рассматривает начальник отдела или суперадминистратор.')
    qs = StaffApplication.objects.select_related('user').filter(status='pending')
    if not request.user.is_superuser:
        qs = qs.filter(requested_role='worker')
    if request.method == 'POST':
        item = get_object_or_404(qs.select_for_update(), pk=request.POST.get('application'))
        person = User.objects.select_for_update().get(pk=item.user_id)
        if person.pk == request.user.pk or person.is_superuser:
            return HttpResponseForbidden('Недоступная заявка.')
        action = request.POST.get('action')
        if action not in {'approve','reject'}:
            return HttpResponseForbidden('Неизвестное действие.')
        if action == 'approve':
            if item.requested_role == 'head_admin' and User.objects.filter(role='head_admin').exclude(pk=person.pk).exists():
                messages.error(request, 'Начальник уже назначен. Сначала измените роль прежнего начальника.')
                return redirect('staff_applications')
            person.role = item.requested_role
            person.is_active = True
            person.is_approved = True
            person.candidate_approved = False
            person.save()
        item.status = 'approved' if action == 'approve' else 'rejected'
        item.note = request.POST.get('note','').strip()[:2000]
        item.reviewed_by = request.user
        item.reviewed_at = timezone.now()
        item.save()
        messages.success(request, 'Решение сохранено.')
        return redirect('staff_applications')
    return render(request, 'users/staff_applications.html', {'applications':qs.order_by('created_at')})
