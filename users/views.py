# users/views.py

import json
from collections import defaultdict
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.urls import reverse
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .forms import UserRegisterForm, UserUpdateForm, AdminUpdateForm, AboutPageForm, ActivityPeriodForm
from .models import User, Direction, School, ActivityPeriod, Notification, AboutPage, AuditLog
from events.models import Event, EventEvaluation


# --- HELPER: ЗАПИСЬ В ЖУРНАЛ (С РЕЖИМОМ ПРИЗРАКА) ---
def log_action(user, action, target=None):
    if user.is_superuser:
        return
    try:
        AuditLog.objects.create(actor=user, action=action, target_user=target)
    except Exception:
        pass


# --- HELPER: ПРОВЕРКА ПРАВ НА ПРОСМОТР (НОВОЕ) ---
def is_privileged_viewer(user):
    """
    Возвращает True, если пользователь - "Начальство" 
    (Супер-админ, Руководитель направления, Руководитель отдела, Работник, Президент, Модератор).
    Они видят всё, игнорируя настройки приватности.
    """
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.role in ['leader', 'head_admin', 'worker', 'president', 'moderator']


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
    return user.is_authenticated and (
        user.role in ['leader', 'moderator', 'president', 'worker', 'head_admin'] or user.is_superuser
    )

def is_admin_or_higher(user):
    return user.is_authenticated and (
        user.role in ['leader', 'president', 'worker', 'head_admin'] or user.is_superuser
    )

def can_edit_activity_periods(user):
    """Кто может заполнять/редактировать историю активности волонтёров."""
    return user.is_authenticated and (user.is_superuser or user.role in ['leader', 'worker', 'head_admin'])



def get_user_power_level(user):
    """Числовой уровень прав/иерархии (для сравнения доступа).

    ВАЖНО: Руководитель направления (leader) выше всех; работники/админы выше президента.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return 0
    if getattr(user, 'is_superuser', False):
        return 1000

    levels = {
        'leader': 90,
        'head_admin': 80,
        'worker': 70,
        'president': 60,
        'moderator': 50,
        'volunteer': 10,
    }
    base_level = levels.get(getattr(user, 'role', None), 0)

    # Небольшой бонус для 'Активного волонтёра', но только если он обычный volunteer.
    if getattr(user, 'is_active_volunteer_title', False) and getattr(user, 'role', None) == 'volunteer':
        base_level += 15

    return base_level

def build_evaluation_stats(volunteer: User):
    """Сводка оценок волонтёра по всем мероприятиям."""
    qs = EventEvaluation.objects.filter(volunteer=volunteer)
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
        'avg': round(avg, 2) if count else None,
        'badge_class': badge_class(avg, count > 0),
        'top_criteria': criteria_stats[:3],
        'all_criteria': criteria_stats,
        'latest': latest,
    }



# --- VIEWS (Представления) ---

def home_view(request):
    # 1. Получаем Президента (для цитат)
    president = User.objects.filter(role='president', is_approved=True).first()
    
    # 2. Получаем Направления (для блока иконок)
    directions = Direction.objects.all() 
    
    # 3. Получаем Мероприятия (для афиши)
    # Гости видят только публичные, свои видят все
    if request.user.is_authenticated:
        upcoming_events = Event.objects.filter(is_approved=True, is_completed=False).order_by('start_time')[:3]
    else:
        upcoming_events = Event.objects.filter(is_approved=True, is_completed=False, is_public_for_guests=True).order_by('start_time')[:3]
        
    context = {
        'president': president, 
        'upcoming_events': upcoming_events,
        'directions': directions  # <-- Важно: передаем направления в шаблон
    }
    return render(request, 'users/home.html', context)


def about_view(request):
    return render(request, 'users/about.html', {'about_content': AboutPage.objects.first()})


def volunteer_list_view(request):
    # Показываем одобренных, НО ИСКЛЮЧАЕМ (exclude) работников, админов и президента
    queryset = User.objects.filter(is_approved=True).exclude(
        role__in=['worker', 'head_admin']
    ).order_by('last_name')
    
    # Списки для фильтров
    faculties = User.objects.filter(is_approved=True).exclude(faculty='').values_list('faculty', flat=True).distinct().order_by('faculty')
    courses = User.objects.filter(is_approved=True).exclude(course__isnull=True).values_list('course', flat=True).distinct().order_by('course')
    cities = User.objects.filter(is_approved=True).exclude(city='').values_list('city', flat=True).distinct().order_by('city')
    directions = Direction.objects.all().order_by('name')

    # Фильтрация
    query = request.GET.get('query')
    if query: queryset = queryset.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(patronymic__icontains=query))
    
    if request.GET.get('faculty'): queryset = queryset.filter(faculty=request.GET.get('faculty'))
    if request.GET.get('course'): queryset = queryset.filter(course=request.GET.get('course'))
    if request.GET.get('city'): queryset = queryset.filter(city=request.GET.get('city'))
    if request.GET.get('gender'): queryset = queryset.filter(gender=request.GET.get('gender'))
    if request.GET.get('direction'): queryset = queryset.filter(directions__id=request.GET.get('direction'))
    
    status = request.GET.get('status')
    if status == 'active': queryset = queryset.filter(is_active_volunteer_title=True)
    elif status == 'leader': queryset = queryset.filter(role='leader')
    elif status == 'school_leader': queryset = queryset.filter(school_leader_of__isnull=False).distinct()
    elif status == 'president': queryset = queryset.filter(role='president')

    volunteers_count = queryset.count()

    context = {
        'volunteers': queryset,
        'volunteers_count': volunteers_count,
        'faculties': faculties, 'courses': courses, 'cities': cities, 'directions': directions,
        'form_values': request.GET,
    }
    return render(request, 'users/volunteer_list.html', context)


def administration_page_view(request):
    head_admin = User.objects.filter(role='head_admin', is_approved=True).exclude(is_superuser=True).first()
    workers = User.objects.filter(role='worker', is_approved=True).exclude(is_superuser=True)
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
            staff = User.objects.filter(Q(role__in=['leader','moderator', 'worker', 'head_admin', 'president']) | Q(is_superuser=True)).distinct()
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
        'activity_periods': activity_periods,
        'can_admin_edit': False,
        'can_edit_activity': can_edit_activity_periods(request.user),
        'show_evaluations': True,
        'evaluation': build_evaluation_stats(request.user),
        'show': show_fields # Показываем всё хозяину
    }
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
    profile_user = get_object_or_404(User, pk=pk)

    # Проверка одобрения
    if not profile_user.is_approved:
        if not is_privileged_viewer(request.user):
            messages.error(request, "Этот профиль недоступен или находится на проверке.")
            return redirect('home')

    activity_periods = profile_user.activity_periods.all()

    # Право на админское редактирование
    can_admin_edit = False
    if request.user.is_authenticated and request.user != profile_user:
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

    evaluation_stats = build_evaluation_stats(profile_user) if show_evaluations else None

    # --- ИСТОРИЯ АКТИВНОСТИ: кто может заполнять ---
    can_edit_activity = can_edit_activity_periods(request.user)
    context = {
        'profile_user': profile_user, 
        'activity_periods': activity_periods,
        'can_admin_edit': can_admin_edit,
        'can_edit_activity': can_edit_activity,
        'show_evaluations': show_evaluations,
        'evaluation': evaluation_stats,
        'show': show_fields, # Передаем результаты проверки
    }
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
    if not is_moderator_or_higher(request.user): return redirect('home')
    pending_users = User.objects.filter(is_approved=False)
    return render(request, 'users/moderator_dashboard.html', {'pending_users': pending_users})

@login_required
def approve_user_view(request, pk):
    if not is_moderator_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        user_to_approve = get_object_or_404(User, pk=pk)
        user_to_approve.is_approved = True
        user_to_approve.save()
        log_action(request.user, f"Одобрил пользователя: {user_to_approve.get_full_name()}", target=user_to_approve)
        Notification.objects.create(recipient=user_to_approve, message="Поздравляем! Ваш профиль был одобрен.", link=reverse('my_profile'))
        messages.success(request, f'Профиль {user_to_approve.get_full_name()} одобрен.')
    return redirect('moderator_dashboard')

@login_required
def reject_user_view(request, pk):
    if not is_moderator_or_higher(request.user): return redirect('home')
    user_to_reject = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        reason = request.POST.get('reason', 'Причина не указана.')
        Notification.objects.create(recipient=user_to_reject, message=f'Ваша регистрация отклонена: {reason}')
        log_action(request.user, f"Отклонил (удален) пользователя: {user_to_reject.get_full_name()}", target=user_to_reject)
        user_to_reject.delete()
        messages.warning(request, 'Пользователь отклонен и удален.')
    return redirect('moderator_dashboard')

@login_required
def admin_dashboard_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    context = {
        'total_users': User.objects.count(),
        'active_count': User.objects.filter(is_active_volunteer_title=True).count(),
        'leaders_count': User.objects.filter(role='leader').count(),
        'school_leaders_count': User.objects.filter(school_leader_of__isnull=False).distinct().count(),
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
    return render(request, 'users/direction_management.html', {
        'directions': Direction.objects.all(), 'volunteers': User.objects.filter(is_approved=True)
    })

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
            u.role = 'leader'; u.save()
            messages.success(request, f"{u} назначен.")
    return redirect('direction_management')

@login_required
def school_management_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    return render(request, 'users/school_management.html', {
        'schools': School.objects.all(), 'volunteers': User.objects.filter(is_approved=True).exclude(is_superuser=True)
    })

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
            messages.info(request, f"{u} снят.")
        else:
            u.school_leader_of.add(s)
            messages.success(request, f"{u} назначен.")
    return redirect('school_management')

@login_required
def about_page_edit_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    obj, _ = AboutPage.objects.get_or_create(pk=1)
    if request.method == 'POST':
        form = AboutPageForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Сохранено.")
            return redirect('about_page_edit')
    else:
        form = AboutPageForm(instance=obj)
    return render(request, 'users/about_page_edit.html', {'form': form})

# --- Уведомления ---
@login_required
def notification_list_view(request):
    return render(request, 'users/notifications.html', {'notifications': request.user.notifications.all()})

@login_required
def mark_notification_as_read_view(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    n.is_read = True; n.save()
    return redirect(n.link if n.link else 'notification_list')

@login_required
def admin_edit_user_view(request, pk):
    target = get_object_or_404(User, pk=pk)
    if get_user_power_level(request.user) <= get_user_power_level(target):
        messages.error(request, "Недостаточно прав.")
        return redirect('public_profile', pk=pk)
        
    if request.method == 'POST':
        form = AdminUpdateForm(request.POST, request.FILES, instance=target)
        if form.is_valid():
            form.save()
            log_action(request.user, f"Отредактировал профиль {target}", target=target)
            if request.user != target:
                Notification.objects.create(recipient=target, message=f"Модератор {request.user} изменил ваш профиль.")
            messages.success(request, "Профиль обновлен.")
            return redirect('public_profile', pk=pk)
    else:
        form = AdminUpdateForm(instance=target)
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
