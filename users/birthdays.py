from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import User, Notification, BirthdayGreeting


def manager(user):
    return user.is_authenticated and user.is_active and (user.is_superuser or user.role in {'president', 'worker', 'head_admin'})


def volunteers():
    return User.objects.filter(is_active=True, is_superuser=False, role__in=['volunteer', 'moderator', 'president']).filter(Q(is_approved=True) | Q(volunteer_access=True) | Q(role='president'))


def occurrence(born, year):
    try: return born.replace(year=year)
    except ValueError: return date(year, 2, 28)


def upcoming(today=None):
    today = today or timezone.localdate()
    result=[]
    for person in volunteers().exclude(birth_date=None):
        day=occurrence(person.birth_date, today.year)
        if day<today: day=occurrence(person.birth_date, today.year+1)
        person.birthday_day=day
        person.birthday_days=(day-today).days
        result.append(person)
    return sorted(result, key=lambda p:(p.birthday_days, p.get_full_name(), p.pk))


def notify(recipient, today=None):
    if not manager(recipient): return 0
    today=today or timezone.localdate()
    count=0
    for person in upcoming(today):
        if person.birthday_days>1: break
        when='Сегодня' if person.birthday_days==0 else 'Завтра'
        _, created=Notification.objects.get_or_create(event_key=f'birthday:{today}:{recipient.pk}:{person.pk}', defaults={
            'recipient':recipient, 'message':f'{when} день рождения у {person.get_full_name() or person.username}. Поздравьте человека от команды AYA!',
            'link':reverse('birthday_calendar')})
        count+=created
    return count


def context(request):
    if not request.user.is_authenticated: return {}
    today=timezone.localdate()
    person=request.user
    eligible=volunteers().filter(pk=person.pk).exists()
    birthday=bool(eligible and person.birth_date and occurrence(person.birth_date,today.year)==today)
    return {'birthday_today':birthday, 'birthday_auto':birthday and not BirthdayGreeting.objects.filter(user=person,year=today.year).exists(), 'can_view_birthdays':manager(person)}


@login_required
def calendar(request):
    if not manager(request.user): return HttpResponseForbidden('Календарь доступен президенту и сотрудникам.')
    people=upcoming()
    query=request.GET.get('q','').strip()[:100]
    if query: people=[p for p in people if query.casefold() in (p.get_full_name()+' '+p.username).casefold()]
    return render(request,'users/birthdays.html',{'people':people,'q':query})


@login_required
@require_POST
def seen(request):
    if not context(request).get('birthday_today'): return HttpResponseForbidden('Сегодня поздравление недоступно.')
    BirthdayGreeting.objects.get_or_create(user=request.user,year=timezone.localdate().year)
    return JsonResponse({'ok':True})
