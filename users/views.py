from .profile_choices import filter_profiles, filter_choices
# users/views.py

import json
from collections import defaultdict
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.urls import reverse
from django.db import models, transaction
from datetime import timedelta
from django.http import HttpResponseForbidden
from django.utils.http import url_has_allowed_host_and_scheme
from .services import grant_access
from django.db.models import Q
from django.utils import timezone

from .forms import UserRegisterForm, UserUpdateForm, AdminUpdateForm, AboutPageForm, ActivityPeriodForm
from .models import User, Direction, School, ActivityPeriod, Notification, AboutPage, AuditLog
from .access import (
    can_register_for_events,
    can_record_visits,
    can_manage_members,
    can_see_event_catalog,
    has_full_volunteer_access,
    is_candidate_user,
    is_privileged_user,
    is_public_volunteer,
    is_worker_account,
)
try:
    from .models import VolunteerVisit
except Exception:
    VolunteerVisit = None

from events.models import Event, EventEvaluation
from .permissions import allowed


# --- HELPER: ЗАПИСЬ В ЖУРНАЛ (С РЕЖИМОМ ПРИЗРАКА) ---
def log_action(user, action, target=None):
    AuditLog.objects.create(actor=user, action=action, target_user=target)


def can_manage_candidates(user):
    return can_record_visits(user)


def can_grant_candidate_access(user):
    from .permissions import allowed
    return allowed(user,'admissions')


def _back_redirect(request, fallback_name='moderator_dashboard', **kwargs):
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect(fallback_name, **kwargs)


def _candidate_visits_qs(user_obj):
    if VolunteerVisit is None:
        return []
    return list(
        VolunteerVisit.objects.filter(user=user_obj)
        .select_related('marked_by')
        .order_by('-visit_date', '-created_at')
    )

# --- HELPER: ПРОВЕРКА ПРАВ НА ПРОСМОТР (НОВОЕ) ---
def is_privileged_viewer(user):
    from .permissions import allowed
    return allowed(user,'contacts')


def can_view_field(viewer, target_user, privacy_setting):
    """
    Решает, можно ли показать поле.
    """
    # 1. Если это сам владелец профиля -> Видит всё
    if viewer == target_user:
        return True
    
    # 2. Если это "Начальство" -> Видит всё
    if is_privileged_viewer(viewer):
        return True
    
    # 3. Если поле Публичное -> Видят все (даже гости)
    if privacy_setting == 'public':
        return True
    
    # 4. Если "Только волонтеры" -> Видят только авторизованные и одобренные
    if privacy_setting == 'volunteers':
        return viewer.is_authenticated and viewer.is_approved
    
    # 5. Если "Приватно" -> Никто больше не видит
    if privacy_setting == 'private':
        return False
    
    return False


# --- Проверка прав доступа к админ-функциям ---
def is_moderator_or_higher(user):
    from .permissions import legacy
    return legacy(user, 'visits')


def is_admin_or_higher(user):
    from .permissions import legacy
    return legacy(user, 'people')


def can_edit_activity_periods(user):
    from .permissions import allowed
    return allowed(user, 'activity')


def get_user_power_level(user):
    from .permissions import rank
    return rank(user)


def build_evaluation_stats(volunteer: User):
    """Сводка оценок волонтёра по всем мероприятиям."""
    from .rating import eligible_evaluations, rounded_score
    qs = eligible_evaluations().filter(volunteer=volunteer)
    agg = qs.aggregate(
        avg=models.Avg('total_score'),
        count=models.Count('id'),
        event_count=models.Count('event', distinct=True),
    )
    count = agg.get('count') or 0
    avg = float(agg.get('avg') or 0)

    def badge_class(val, has_any):
        if not has_any:
            return "bg-secondary"
        if val >= 4.5:
            return "bg-success"
        if val >= 3.5:
            return "bg-primary"
        if val >= 2.5:
            return "bg-warning text-dark"
        return "bg-danger"

    # Статистика по критериям
    crit_scores = defaultdict(list)
    for ev in qs.only('criteria', 'total_score'):
        for item in (ev.criteria or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '').strip()
            if not name:
                continue
            try:
                score = float(item.get('score'))
            except (TypeError, ValueError):
                continue
            crit_scores[name].append(score)

    criteria_stats = []
    for name, scores in crit_scores.items():
        criteria_stats.append({
            'name': name,
            'avg': round(sum(scores) / len(scores), 2),
            'count': len(scores),
        })
    criteria_stats.sort(key=lambda x: (x['avg'], x['count']), reverse=True)

    latest = list(
        qs.select_related('event', 'evaluator')
          .order_by('-updated_at')[:8]
          .values('event__title', 'total_score', 'updated_at', 'evaluator__first_name', 'evaluator__last_name')
    )

    return {
        'count': count,
        'event_count': agg.get('event_count') or 0,
        'avg': rounded_score(avg) if count else None,
        'badge_class': badge_class(avg, count > 0),
        'top_criteria': criteria_stats[:3],
        'all_criteria': criteria_stats,
        'latest': latest,
    }



# --- VIEWS (Представления) ---

def home_view(request):
    from .models import HomePage
    from .access import STAFF_ONLY_ROLES
    about = AboutPage.objects.filter(pk=1).first()
    home_page = HomePage.objects.filter(pk=1).first()
    directions = list(Direction.objects.all())
    icons = [('эко', 'leaf'), ('мед', 'briefcase-medical'), ('здоров', 'heart'), ('спорт', 'running'), ('наук', 'microscope'), ('образ', 'graduation-cap'), ('культур', 'palette'), ('междун', 'globe'), ('it', 'laptop-code')]
    for direction in directions:
        direction.home_icon = next((icon for word, icon in icons if word in direction.name.lower()), 'users')
    events = Event.objects.filter(is_approved=True, is_completed=False, cancelled=False, end_time__gte=timezone.now()).order_by('start_time')
    if not request.user.is_authenticated:
        events = events.filter(is_public_for_guests=True)
    from .about_content import public_stats, public_contacts
    stats = public_stats(about)
    contacts = public_contacts(about, request.user)
    return render(request, 'users/home.html', {
        'directions': directions, 'upcoming_events': events[:3], 'home_stats': stats,
        'home_page': home_page, 'about_content': about,
        'home_slides': list(home_page.slides.filter(is_active=True)) if home_page else [],
        'home_quotes': list(home_page.quotes.filter(is_active=True).select_related('member').exclude(member__is_superuser=True).exclude(member__is_approved=False)) if home_page else [],
        'home_contacts': contacts, 'can_edit_home': allowed(request.user,'home'),
        'home_full_access': has_full_volunteer_access(request.user),
        'home_catalog_access': can_see_event_catalog(request.user),
    })


def about_view(request):
    from .models import HomeSlide
    from .about_content import public_stats, public_contacts, video_embed_url
    from urllib.parse import urlsplit
    about = AboutPage.objects.filter(pk=1).first()
    return render(request, 'users/about.html', {
        'about_content': about,
        'about_photo': HomeSlide.objects.filter(page_id=1, is_active=True).first(),
        'value_blocks': about.value_blocks.filter(is_active=True).order_by('order', 'id') if about else [],
        'extra_blocks': about.extra_blocks.filter(is_active=True).order_by('order', 'id') if about else [],
        'stat_items': public_stats(about),
        'contact_links': public_contacts(about, request.user),
        'can_edit_about': allowed(request.user,'about'),
        'about_video_embed': video_embed_url(about.video_url) if about else '',
        'about_video_url': about.video_url if about and urlsplit(about.video_url).scheme in ['http','https'] else '',
    })


def volunteer_list_view(request):
    queryset = User.objects.filter(is_approved=True).exclude(is_superuser=True).exclude(
        role__in=['worker', 'head_admin']
    ).order_by('last_name', 'first_name')

    choices = filter_choices()
    faculties, courses, cities = choices['faculties'], choices['courses'], choices['cities']
    directions = Direction.objects.all().order_by('name')

    query = request.GET.get('query')
    if query:
        queryset = queryset.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(patronymic__icontains=query))

    queryset = filter_profiles(queryset, request.GET)
    if request.GET.get('gender'):
        queryset = queryset.filter(gender=request.GET.get('gender'))
    if request.GET.get('direction'):
        queryset = queryset.filter(directions__id=request.GET['direction']) if request.GET['direction'].isdigit() else queryset.none()

    status = request.GET.get('status')
    if status == 'active':
        queryset = queryset.filter(is_active_volunteer_title=True)
    elif status == 'school_leader':
        queryset = queryset.filter(school_leader_of__isnull=False).distinct()
    elif status == 'leader':
        queryset = queryset.filter(directions_led__isnull=False).distinct()
    elif status == 'president':
        queryset = queryset.filter(role='president')

    request.aya_result_count=queryset.distinct().count()
    context = {
        'volunteers': queryset.distinct().prefetch_related('directions_led', 'school_leader_of'),
        'volunteers_count': queryset.distinct().count(),
        'faculties': faculties, 'courses': courses, 'cities': cities, 'directions': directions,
        'form_values': request.GET,
    }
    return render(request, 'users/volunteer_list.html', context)


def administration_page_view(request):
    head_admin = User.objects.filter(role='head_admin', is_approved=True).exclude(is_superuser=True).first()
    workers = User.objects.filter(role__in=['worker'], is_approved=True).exclude(is_superuser=True).order_by('last_name', 'first_name')
    return render(request, 'users/administration_page.html', {'head_admin': head_admin, 'workers': workers})


# --- Аутентификация ---
def signup_view(request):
    if request.user.is_authenticated: return redirect('home')
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_approved = False
            user.save()
            
            # Уведомления
            staff = User.objects.filter(Q(role__in=['moderator', 'worker', 'head_admin', 'president']) | Q(is_superuser=True)).distinct()
            for s in staff:
                Notification.objects.create(
                    recipient=s, 
                    message=f'Новый волонтер "{user.get_full_name()}" зарегистрировался.',
                    link=reverse('public_profile', kwargs={'pk': user.pk})
                )
            messages.success(request, 'Ваш аккаунт создан и отправлен на модерацию!')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'users/signup.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, "Вы успешно вышли из системы.")
    return redirect('home')


# --- ПРОФИЛЬ (Личный) ---
@login_required
def my_profile_view(request):
    # В своем профиле человек видит всё, поэтому show={} не нужен, или можно передать всё True
    # Но проще использовать тот же шаблон и просто не скрывать ничего
    # Для этого в profile.html мы используем {% if user == profile_user %}
    
    activity_periods = request.user.activity_periods.all()
    
    # Для своего профиля все поля "открыты" для показа самому себе
    show_fields = {
        'phone': True, 'telegram': True, 'instagram': True, 'linkedin': True, 'about_me': True
    }
    
    context = {
        'profile_user': request.user,
        'is_candidate_profile': is_candidate_user(request.user),
        'needs_initial_approval': not request.user.is_approved and not request.user.candidate_approved,
        'candidate_visits': _candidate_visits_qs(request.user),
        'candidate_visit_count': request.user.volunteer_visits.count(), 
        'activity_periods': activity_periods,
        'can_admin_edit': False,
        'can_edit_activity': can_edit_activity_periods(request.user),
        'show_evaluations': True,
        'evaluation': None,
        'show': show_fields # Показываем всё хозяину
    }
    if context['show_evaluations']:
        from .points import point_profile
        context.update(point_profile(request, context['profile_user']))
    return render(request, 'users/profile.html', context)


# --- РЕДАКТИРОВАНИЕ ПРОФИЛЯ ---
@login_required
def profile_edit_view(request):
    if request.method == 'POST':
        form = UserUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Ваш профиль успешно обновлен.')
            return redirect('my_profile')
    else:
        form = UserUpdateForm(instance=request.user)
    return render(request, 'users/profile_edit.html', {'form': form, 'user_to_edit': request.user})


# --- ПРОФИЛЬ (Публичный) - ЗДЕСЬ ГЛАВНАЯ МАГИЯ ---
def public_profile_view(request, pk):
    profile_user = get_object_or_404(User.objects.all() if request.user.is_superuser else User.objects.filter(is_superuser=False), pk=pk)

    is_candidate_profile = bool(getattr(profile_user, 'candidate_approved', False) and not getattr(profile_user, 'is_approved', False))
    needs_initial_approval = bool(not getattr(profile_user, 'is_approved', False) and not getattr(profile_user, 'candidate_approved', False))

    # Неодобренный профиль могут смотреть только сам пользователь и начальство.
    if needs_initial_approval and request.user != profile_user and not is_privileged_viewer(request.user):
        messages.error(request, "Этот профиль недоступен или находится на проверке.")
        return redirect('home')

    activity_periods = profile_user.activity_periods.all()

    # Право на админское редактирование
    can_admin_edit = False
    if can_manage_members(request.user) and request.user != profile_user:
        if get_user_power_level(request.user) > get_user_power_level(profile_user):
            can_admin_edit = True

    # --- ПРОВЕРКА ПРИВАТНОСТИ ПОЛЕЙ ---
    show_fields = {
        'phone': can_view_field(request.user, profile_user, profile_user.phone_privacy),
        'telegram': can_view_field(request.user, profile_user, profile_user.telegram_privacy),
        'instagram': can_view_field(request.user, profile_user, profile_user.instagram_privacy),
        'linkedin': can_view_field(request.user, profile_user, profile_user.linkedin_privacy),
        'about_me': can_view_field(request.user, profile_user, profile_user.about_me_privacy),
    }

    # --- ОЦЕНКИ ВОЛОНТЁРА (сводка) ---
    show_evaluations = False
    if request.user == profile_user:
        show_evaluations = True
    elif is_privileged_viewer(request.user):
        show_evaluations = True
    elif request.user.is_authenticated and getattr(request.user, 'is_approved', False):
        show_evaluations = True

    evaluation_stats = None

    candidate_visits = _candidate_visits_qs(profile_user)
    candidate_visit_count = len(candidate_visits)
    can_review_candidate = bool(request.user.is_authenticated and request.user != profile_user and allowed(request.user,'admissions'))
    can_mark_candidate_visit = bool(request.user.is_authenticated and request.user != profile_user and can_manage_candidates(request.user))
    can_manual_grant_access = bool(request.user.is_authenticated and request.user != profile_user and can_grant_candidate_access(request.user))

    # --- ИСТОРИЯ АКТИВНОСТИ: кто может заполнять ---
    can_edit_activity = can_edit_activity_periods(request.user)
    context = {
        'profile_user': profile_user,
        'activity_periods': activity_periods,
        'can_admin_edit': can_admin_edit,
        'can_edit_activity': can_edit_activity,
        'show_evaluations': show_evaluations,
        'evaluation': evaluation_stats,
        'show': show_fields,
        'is_candidate_profile': is_candidate_profile,
        'needs_initial_approval': needs_initial_approval,
        'candidate_visits': candidate_visits,
        'candidate_visit_count': candidate_visit_count,
        'can_review_candidate': can_review_candidate,
        'can_mark_candidate_visit': can_mark_candidate_visit,
        'can_manual_grant_access': can_manual_grant_access,
    }
    if context['show_evaluations']:
        from .points import point_profile
        context.update(point_profile(request, context['profile_user']))
    return render(request, 'users/profile.html', context)




@login_required
def activity_periods_manage_view(request, pk):
    """Управление периодами активности волонтёра (только Руководитель направления и Работники/Руководитель отдела)."""
    target = get_object_or_404(User, pk=pk)
    if not can_edit_activity_periods(request.user):
        messages.error(request, "Недостаточно прав для редактирования истории активности.")
        return redirect('public_profile', pk=pk)

    if request.method == 'POST':
        form = ActivityPeriodForm(request.POST)
        if form.is_valid():
            period = form.save(commit=False)
            period.user = target
            period.save()
            log_action(request.user, f"Добавил период активности для {target}", target=target)
            messages.success(request, "Период активности добавлен.")
            return redirect('activity_periods_manage', pk=pk)
    else:
        form = ActivityPeriodForm()

    periods = target.activity_periods.all()
    return render(request, 'users/activity_periods_manage.html', {
        'target_user': target,
        'periods': periods,
        'form': form,
    })


@login_required
def activity_period_edit_view(request, pk, period_id):
    target = get_object_or_404(User, pk=pk)
    period = get_object_or_404(ActivityPeriod, pk=period_id, user=target)
    if not can_edit_activity_periods(request.user):
        messages.error(request, "Недостаточно прав для редактирования истории активности.")
        return redirect('public_profile', pk=pk)

    if request.method == 'POST':
        form = ActivityPeriodForm(request.POST, instance=period)
        if form.is_valid():
            form.save()
            log_action(request.user, f"Изменил период активности для {target}", target=target)
            messages.success(request, "Период активности обновлён.")
            return redirect('activity_periods_manage', pk=pk)
    else:
        form = ActivityPeriodForm(instance=period)

    return render(request, 'users/activity_period_edit.html', {
        'target_user': target,
        'period': period,
        'form': form,
    })


@login_required
def activity_period_delete_view(request, pk, period_id):
    target = get_object_or_404(User, pk=pk)
    period = get_object_or_404(ActivityPeriod, pk=period_id, user=target)
    if not can_edit_activity_periods(request.user):
        messages.error(request, "Недостаточно прав.")
        return redirect('public_profile', pk=pk)

    if request.method == 'POST':
        period.delete()
        log_action(request.user, f"Удалил период активности для {target}", target=target)
        messages.success(request, "Период активности удалён.")
        return redirect('activity_periods_manage', pk=pk)

    return render(request, 'users/activity_period_delete_confirm.html', {
        'target_user': target,
        'period': period,
    })



# --- АДМИН ПАНЕЛИ (Модератор, Админ) ---

@login_required
def moderator_dashboard_view(request):
    if not is_moderator_or_higher(request.user):
        return redirect('home')

    pending_users = User.objects.filter(
        is_approved=False,
        candidate_approved=False,
    ).exclude(is_superuser=True).order_by('-date_joined')

    candidates_qs = User.objects.filter(
        candidate_approved=True,
        is_approved=False,
    ).exclude(is_superuser=True).order_by('-date_joined')

    if not allowed(request.user,'admissions'):
        pending_users = User.objects.none()

    candidate_cards = []
    for candidate in candidates_qs:
        visits = _candidate_visits_qs(candidate)
        candidate_cards.append({
            'user': candidate,
            'visit_count': len(visits),
            'last_visit': visits[0] if visits else None,
            'visits': visits,
        })

    return render(request, 'users/moderator_dashboard.html', {
        'pending_users': pending_users,
        'candidate_cards': candidate_cards,
        'candidates': candidates_qs,
        'can_manual_grant_access': can_grant_candidate_access(request.user),
        'can_review_candidates': allowed(request.user,'admissions'),
        'recently_approved': User.objects.filter(is_approved=True, is_superuser=False, volunteer_access_granted_at__gte=timezone.now() - timedelta(days=14)).exclude(role__in=['worker', 'head_admin']).select_related('volunteer_access_granted_by').order_by('-volunteer_access_granted_at'),
    })

@login_required
@transaction.atomic
def approve_user_view(request, pk):
    if not allowed(request.user,'admissions'):
        return HttpResponseForbidden('Недостаточно прав.')
    user_to_approve = get_object_or_404(User.objects.select_for_update(), pk=pk, is_superuser=False, role='volunteer')

    if request.method == 'POST':
        if getattr(user_to_approve, 'is_approved', False):
            messages.info(request, 'У пользователя уже открыт полный доступ волонтёра.')
            return _back_redirect(request, 'public_profile', pk=pk)

        if getattr(user_to_approve, 'candidate_approved', False):
            messages.info(request, 'Заявка уже принята. Теперь нужно отмечать посещения.')
            return _back_redirect(request, 'public_profile', pk=pk)

        user_to_approve.candidate_approved = True
        user_to_approve.volunteer_access = False
        user_to_approve.is_approved = False
        user_to_approve.save(update_fields=['candidate_approved', 'volunteer_access', 'is_approved'])

        log_action(request.user, f"Одобрил пользователя как кандидата: {user_to_approve.get_full_name()}", target=user_to_approve)
        Notification.objects.create(
            recipient=user_to_approve,
            message="Ваша заявка принята. Вы стали кандидатом — после 3 визитов откроется полный доступ волонтёра.",
            link=reverse('my_profile'),
        )
        messages.success(request, f'Профиль {user_to_approve.get_full_name()} переведён в кандидаты. Теперь доступны посещения.')
    return _back_redirect(request, 'moderator_dashboard')

@login_required
def reject_user_view(request, pk):
    if not allowed(request.user,'admissions'): return HttpResponseForbidden('Недостаточно прав.')
    user_to_reject = get_object_or_404(User, pk=pk, is_approved=False, candidate_approved=False, is_superuser=False, role='volunteer')
    if request.method == 'POST':
        reason = request.POST.get('reason', 'Причина не указана.')
        Notification.objects.create(recipient=user_to_reject, message=f'Ваша регистрация отклонена: {reason}')
        log_action(request.user, f"Отклонил (удален) пользователя: {user_to_reject.get_full_name()}", target=user_to_reject)
        user_to_reject.delete()
        messages.warning(request, 'Пользователь отклонен и удален.')
    return redirect('moderator_dashboard')

@login_required
def admin_dashboard_view(request):
    if not is_admin_or_higher(request.user):
        return redirect('home')

    volunteers_qs = User.objects.filter(is_approved=True).exclude(is_superuser=True).exclude(role__in=['worker', 'head_admin'])
    workers_qs = User.objects.filter(is_approved=True, role__in=['worker', 'head_admin']).exclude(is_superuser=True)

    context = {
        'total_users': volunteers_qs.count(),
        'active_count': volunteers_qs.filter(is_active_volunteer_title=True).count(),
        'leaders_count': User.objects.filter(directions_led__isnull=False, is_approved=True).distinct().exclude(is_superuser=True).count(),
        'school_leaders_count': User.objects.filter(school_leader_of__isnull=False, is_approved=True).exclude(is_superuser=True).distinct().count(),
        'workers_count': workers_qs.count(),
    }
    return render(request, 'users/admin_dashboard.html', context)

@login_required
def user_management_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    users_list = User.objects.exclude(is_superuser=True).order_by('last_name')
    
    search_query = request.GET.get('search')
    if search_query:
        users_list = users_list.filter(Q(first_name__icontains=search_query) | Q(last_name__icontains=search_query) | Q(username__icontains=search_query))
        
    role_filter = request.GET.get('role_filter')
    if role_filter:
        users_list = users_list.filter(role=role_filter)
        
    return render(request, 'users/user_management.html', {
        'users_list': users_list, 'role_choices': User.ROLE_CHOICES,
        'search_query': search_query, 'role_filter': role_filter
    })

@login_required
def update_user_role_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        user_to_update = get_object_or_404(User, pk=pk)
        if get_user_power_level(request.user) <= get_user_power_level(user_to_update):
            messages.error(request, "Недостаточно прав.")
            return redirect('user_management')
            
        new_role = request.POST.get('role')
        from types import SimpleNamespace
        if new_role not in dict(User.ROLE_CHOICES) or (not request.user.is_superuser and get_user_power_level(SimpleNamespace(is_authenticated=True, is_superuser=False, role=new_role)) >= get_user_power_level(request.user)):
            return HttpResponseForbidden('Недостаточно прав для назначения этой роли.')
        if new_role == 'head_admin':
             # Логика снятия старого админа
             old = User.objects.filter(role='head_admin').first()
             if old: 
                 old.role = 'worker'; old.save()
        
        user_to_update.role = new_role
        user_to_update.save()
        log_action(request.user, f"Изменил роль {user_to_update} на {new_role}", target=user_to_update)
        messages.success(request, "Роль обновлена.")
    return redirect('user_management')

@login_required
def toggle_active_volunteer_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        u = get_object_or_404(User, pk=pk)
        u.is_active_volunteer_title = not u.is_active_volunteer_title
        u.save()
        log_action(request.user, f"Изменил статус 'Активный' для {u}", target=u)
        messages.success(request, "Статус обновлен.")
    return redirect('user_management')

# --- Направления и Школы ---
@login_required
def direction_management_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    return redirect('unit_catalog')

@login_required
def direction_create_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        Direction.objects.create(name=request.POST.get('name'))
        messages.success(request, "Направление создано.")
    return redirect('direction_management')

@login_required
def direction_delete_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        Direction.objects.get(pk=pk).delete()
        messages.warning(request, "Направление удалено.")
    return redirect('direction_management')

@login_required
def assign_direction_leader_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        d = get_object_or_404(Direction, pk=pk)
        u = get_object_or_404(User, pk=request.POST.get('leader'))
        if u in d.leaders.all():
            d.leaders.remove(u)
            messages.info(request, f"{u} снят.")
        else:
            d.leaders.add(u)
            u.directions.add(d)
            messages.success(request, f"{u} назначен.")
    return redirect('direction_management')

@login_required
def school_management_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    return redirect('school_catalog')

@login_required
def school_create_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        School.objects.create(name=request.POST.get('name'))
        messages.success(request, "Школа создана.")
    return redirect('school_management')

@login_required
def school_delete_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        School.objects.get(pk=pk).delete()
        messages.warning(request, "Школа удалена.")
    return redirect('school_management')

@login_required
def assign_school_leader_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        s = get_object_or_404(School, pk=pk)
        u = get_object_or_404(User, pk=request.POST.get('leader_id'))
        if u in s.leaders.all():
            u.school_leader_of.remove(s)
            s.teachers.filter(member=u).delete()
            messages.info(request, f"{u} снят.")
        else:
            u.school_leader_of.add(s)
            s.teachers.get_or_create(member=u,defaults={'name':u.get_full_name() or u.username})
            s.members.add(u)
            if s.direction_id:s.direction.user_set.add(u)
            messages.success(request, f"{u} назначен.")
    return redirect('school_management')

@login_required
def about_page_edit_view(request):
    return redirect('about_manage')

@login_required
def notification_list_view(request):
    return render(request, 'users/notifications.html', {'notifications': request.user.notifications.all()})

@login_required
def mark_notification_as_read_view(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    n.is_read = True; n.save()
    return redirect(n.link if n.link else 'notifications')

@login_required
def admin_edit_user_view(request, pk):
    target = get_object_or_404(User, pk=pk)
    if not can_manage_members(request.user) or get_user_power_level(request.user) <= get_user_power_level(target):
        messages.error(request, "Недостаточно прав.")
        return redirect('public_profile', pk=pk)
        
    if request.method == 'POST':
        form = AdminUpdateForm(request.POST, request.FILES, instance=target, actor=request.user)
        if form.is_valid():
            form.save()
            log_action(request.user, f"Отредактировал профиль {target}", target=target)
            if request.user != target:
                Notification.objects.create(recipient=target, message=f"Модератор {request.user} изменил ваш профиль.")
            messages.success(request, "Профиль обновлен.")
            return redirect('public_profile', pk=pk)
    else:
        form = AdminUpdateForm(instance=target, actor=request.user)
    return render(request, 'users/profile_edit.html', {'form': form, 'user_to_edit': target})

@login_required
def audit_log_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    return render(request, 'users/audit_log.html', {'audit_logs': AuditLog.objects.all()})

# ... (existing imports)

@login_required
def mark_all_notifications_as_read_view(request):
    """Marks all unread notifications for the current user as read."""
    unread_notifications = Notification.objects.filter(recipient=request.user, is_read=False)
    unread_count = unread_notifications.count()
    
    if unread_count > 0:
        unread_notifications.update(is_read=True)
        messages.success(request, f"Все уведомления ({unread_count}) отмечены как прочитанные.")
    else:
        messages.info(request, "У вас нет непрочитанных уведомлений.")
        
    return redirect('notifications')

from django.contrib.auth.forms import SetPasswordForm

@login_required
def admin_password_change_view(request, pk):
    # Проверка: только супер-админ может менять пароли другим
    if not request.user.is_superuser:
        messages.error(request, "У вас нет прав для этого.")
        return redirect('home')

    target_user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = SetPasswordForm(target_user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Пароль для {target_user.get_full_name()} успешно изменен!")
            # Важно: не даем админу "войти" под этим паролем, просто возвращаем в профиль
            return redirect('public_profile', pk=pk)
    else:
        form = SetPasswordForm(target_user)

    return render(request, 'users/admin_password_change.html', {
        'form': form,
        'target_user': target_user
    })

@login_required
@transaction.atomic
def mark_candidate_visit_view(request, pk):
    """Отметить 'пришёл' кандидату. Не больше 1 раза в день. После 3 отметок -> волонтёр."""
    if not can_manage_candidates(request.user):
        return redirect('home')

    candidate = get_object_or_404(User.objects.select_for_update(), pk=pk, is_superuser=False, role__in=['volunteer', 'president', 'moderator'])

    if request.method != 'POST':
        return _back_redirect(request, 'public_profile', pk=pk)

    if getattr(candidate, 'is_approved', False):
        messages.info(request, "Пользователь уже имеет доступ волонтёра.")
        return _back_redirect(request, 'public_profile', pk=pk)

    if not getattr(candidate, 'candidate_approved', False):
        messages.error(request, "Сначала примите заявку — после этого появятся посещения.")
        return _back_redirect(request, 'public_profile', pk=pk)

    if VolunteerVisit is None:
        messages.error(request, "Модель визитов не подключена. Проверьте migrations/models.py.")
        return _back_redirect(request, 'public_profile', pk=pk)

    today = timezone.localdate()
    if VolunteerVisit.objects.filter(user=candidate, visit_date=today).exists():
        messages.warning(request, "Сегодня посещение уже отмечено (1 визит в день).")
        return _back_redirect(request, 'public_profile', pk=pk)

    VolunteerVisit.objects.create(user=candidate, marked_by=request.user, visit_date=today, comment=(request.POST.get('comment') or '').strip())
    log_action(request.user, f"Отметил визит кандидата: {candidate.get_full_name()} ({today})", target=candidate)

    cnt = VolunteerVisit.objects.filter(user=candidate).count()
    if cnt >= 3:
        grant_access(candidate, request.user)
        Notification.objects.create(
            recipient=candidate,
            message="Поздравляем! Вы стали волонтёром. Вам открыт полный доступ и ссылка на Telegram-группу.",
            link=reverse('my_profile'),
        )
        messages.success(request, "3/3 — доступ открыт! Пользователь теперь волонтёр.")
    else:
        messages.success(request, f"Посещение сохранено. Прогресс: {cnt}/3.")

    return _back_redirect(request, 'public_profile', pk=pk)


@login_required
@transaction.atomic
def grant_volunteer_access_view(request, pk):
    """Выдать полный доступ сразу (для волонтёров, которые давно с вами)."""
    if not can_grant_candidate_access(request.user):
        messages.error(request, 'Модератор может только отмечать посещения. Полный доступ выдают роли выше модератора.')
        return redirect('home')

    target = get_object_or_404(User.objects.select_for_update(), pk=pk, is_superuser=False, role__in=['volunteer', 'president', 'moderator'])

    if request.method != 'POST':
        return _back_redirect(request, 'public_profile', pk=pk)

    if getattr(target, 'is_approved', False):
        messages.info(request, "У пользователя уже есть доступ волонтёра.")
        return _back_redirect(request, 'public_profile', pk=pk)

    grant_access(target, request.user, old=request.POST.get('is_old_volunteer') in ['on', '1', 'true'])

    log_action(request.user, f"Выдал доступ волонтёра сразу: {target.get_full_name()}", target=target)
    Notification.objects.create(
        recipient=target,
        message="Вам выдали полный доступ волонтёра (без ожидания 3 визитов). Добро пожаловать!",
        link=reverse('my_profile'),
    )
    messages.success(request, "Доступ выдан. Пользователь теперь волонтёр.")
    return _back_redirect(request, 'public_profile', pk=pk)


@login_required
@transaction.atomic
def delete_candidate_visit_view(request, visit_id):
    """Удалить ошибочную отметку визита."""
    if not allowed(request.user,'admissions'):
        return redirect('home')

    if VolunteerVisit is None:
        return redirect('home')

    visit = get_object_or_404(VolunteerVisit, pk=visit_id)
    user_pk = visit.user.pk
    if visit.user.is_approved:
        messages.error(request, 'История визитов после выдачи доступа сохранена. Удалять можно отметки действующего кандидата.')
        return _back_redirect(request, 'public_profile', pk=user_pk)

    if request.method == 'POST':
        log_action(request.user, f"Удалил отметку визита {visit.visit_date} у {visit.user}", target=visit.user)
        visit.delete()
        messages.warning(request, "Отметка удалена.")
    return _back_redirect(request, 'public_profile', pk=user_pk)
