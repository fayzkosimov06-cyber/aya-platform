# users/views.py

import json
import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.urls import reverse
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .forms import UserRegisterForm, UserUpdateForm, AdminUpdateForm, AboutPageForm
from .models import User, Direction, School, ActivityPeriod, Notification, AboutPage, AuditLog
from events.models import Event


# --- HELPER: ЗАПИСЬ В ЖУРНАЛ (С РЕЖИМОМ ПРИЗРАКА) ---
def log_action(user, action, target=None):
    """
    Записывает действие в журнал, ТОЛЬКО если пользователь НЕ супер-админ.
    """
    # Если пользователь - супер-админ, ничего не пишем (Призрак)
    if user.is_superuser:
        return
        
    # Иначе создаем запись
    try:
        AuditLog.objects.create(actor=user, action=action, target_user=target)
    except Exception:
        pass # Чтобы ошибка логирования не ломала сайт


# --- Проверка прав ---
def is_moderator_or_higher(user):
    return user.is_authenticated and (
        user.role in ['moderator', 'president', 'worker', 'head_admin'] or user.is_superuser
    )


def is_admin_or_higher(user):
    return user.is_authenticated and (
        user.role in ['president', 'worker', 'head_admin'] or user.is_superuser
    )

# --- НОВАЯ ФУНКЦИЯ ИЕРАРХИИ ---
def get_user_power_level(user):
    """
    Возвращает уровень власти.
    Супер-админ(100) > Руководитель(90) > Работник(80) > Президент(70) > Модератор(50) > Лидер(30) > Активный(20) > Волонтер(0)
    """
    if user.is_superuser: return 100
    
    levels = {
        'head_admin': 90, # Руководитель отдела
        'worker': 80,     # Работник
        'president': 70,  # Президент
        'moderator': 50,  # Модератор
        'leader': 30,     # Руководитель направления
        'volunteer': 0,
    }
    # Бонус за "Активного волонтера", если это обычный волонтер
    base_level = levels.get(user.role, 0)
    if user.is_active_volunteer_title and user.role == 'volunteer':
        base_level = 20 
        
    return base_level


# --- Главные view ---
# users/views.py

def home_view(request):
    # 1. Получаем Президента (для блока на главной)
    president = User.objects.filter(role='president', is_approved=True).first()
    
    # 2. Получаем 3 ближайших мероприятия
    # (Одобренные И Не завершенные, сортируем по дате начала)
    upcoming_events = Event.objects.filter(is_approved=True, is_completed=False).order_by('start_time')[:3]
    
    context = {
        'president': president,
        'upcoming_events': upcoming_events, # <-- Вот это переменная, которую ждет шаблон
    }
    return render(request, 'users/home.html', context)


def about_view(request):
    about_content = AboutPage.objects.first()
    return render(request, 'users/about.html', {'about_content': about_content})


def volunteer_list_view(request):
    queryset = User.objects.filter(is_approved=True).order_by('last_name')
    faculties = (
        User.objects.filter(is_approved=True, faculty__isnull=False)
        .exclude(faculty='')
        .values_list('faculty', flat=True)
        .distinct()
        .order_by('faculty')
    )
    courses = (
        User.objects.filter(is_approved=True, course__isnull=False)
        .values_list('course', flat=True)
        .distinct()
        .order_by('course')
    )
    cities = (
        User.objects.filter(is_approved=True, city__isnull=False)
        .exclude(city='')
        .values_list('city', flat=True)
        .distinct()
        .order_by('city')
    )
    directions = Direction.objects.all().order_by('name')

    query = request.GET.get('query')
    faculty = request.GET.get('faculty')
    course = request.GET.get('course')
    city = request.GET.get('city')
    gender = request.GET.get('gender')
    direction = request.GET.get('direction')
    status = request.GET.get('status')

    if query:
        queryset = queryset.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(patronymic__icontains=query)
        )
    if faculty:
        queryset = queryset.filter(faculty=faculty)
    if course:
        queryset = queryset.filter(course=course)
    if city:
        queryset = queryset.filter(city=city)
    if gender:
        queryset = queryset.filter(gender=gender)
    if direction:
        queryset = queryset.filter(directions__id=direction)
    if status:
        if status == 'active':
            queryset = queryset.filter(is_active_volunteer_title=True)
        if status == 'leader':
            queryset = queryset.filter(role='leader')
        if status == 'school_leader':
            queryset = queryset.filter(school_leader_of__isnull=False).distinct()
        if status == 'president':
            queryset = queryset.filter(role='president')

    context = {
        'volunteers': queryset,
        'faculties': faculties,
        'courses': courses,
        'cities': cities,
        'directions': directions,
        'form_values': request.GET,
    }
    return render(request, 'users/volunteer_list.html', context)
def administration_page_view(request):
    # 1. Руководитель отдела (только один, исключая супер-админа если вдруг)
    head_admin = User.objects.filter(role='head_admin', is_approved=True).exclude(is_superuser=True).first()
    
    # 2. Работники
    workers = User.objects.filter(role='worker', is_approved=True).exclude(is_superuser=True)

    context = {
        'head_admin': head_admin,
        'workers': workers
    }
    return render(request, 'users/administration_page.html', context)


# --- Аутентификация ---
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_approved = False
            user.save()

            # --- УВЕДОМЛЕНИЕ ДЛЯ МОДЕРАТОРОВ ---
            moderators = User.objects.filter(role__in=['moderator', 'worker', 'head_admin', 'president'])
            superusers = User.objects.filter(is_superuser=True)
            all_staff = moderators | superusers

            for staff_member in all_staff.distinct():
                Notification.objects.create(
                    recipient=staff_member,
                    message=f'Новый волонтер "{user.get_full_name()}" зарегистрировался.',
                    # ИСПРАВЛЕНИЕ: Ссылка ведет на профиль для просмотра
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


# --- Профиль ---
@login_required
def my_profile_view(request):
    activity_periods = request.user.activity_periods.all()
    context = {
        'profile_user': request.user, 
        'activity_periods': activity_periods,
        'can_admin_edit': False # Вы не можете администрировать сами себя
    }
    return render(request, 'users/profile.html', context)


# --- Редактирование профиля (через модерацию) ---
@login_required
def profile_edit_view(request):
    """
    ИЗМЕНЕНО: Теперь это ПРОСТАЯ функция для пользователя,
    редактирующего СВОЙ профиль.
    """
    if request.method == 'POST':
        # Используем UserUpdateForm, которая включает поля приватности
        form = UserUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save() # Мгновенное сохранение
            messages.success(request, 'Ваш профиль успешно обновлен.')
            return redirect('my_profile')
    else:
        form = UserUpdateForm(instance=request.user)

    return render(request, 'users/profile_edit.html', {
        'form': form,
        'user_to_edit': request.user # user_to_edit нужен для шаблона
    })


def public_profile_view(request, pk):
    profile_user = get_object_or_404(User, pk=pk)

    if not profile_user.is_approved and not (request.user.is_authenticated and is_moderator_or_higher(request.user)):
        messages.error(request, "Этот профиль еще не прошел модерацию.")
        return redirect('home')

    activity_periods = profile_user.activity_periods.all()

    # --- НОВАЯ ЛОГИКА ДЛЯ КНОПКИ ---
    can_admin_edit = False
    if request.user.is_authenticated and request.user != profile_user:
        viewer_level = get_user_power_level(request.user)
        target_level = get_user_power_level(profile_user)
        if viewer_level > target_level:
            can_admin_edit = True
    # --- КОНЕЦ НОВОЙ ЛОГИКИ ---

    context = {
        'profile_user': profile_user, 
        'activity_periods': activity_periods,
        'can_admin_edit': can_admin_edit # <-- Передаем право в шаблон
    }
    return render(request, 'users/profile.html', context)


# --- Панель модератора ---
@login_required
def moderator_dashboard_view(request):
    if not is_moderator_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    pending_users = User.objects.filter(is_approved=False)

    context = {'pending_users': pending_users}
    return render(request, 'users/moderator_dashboard.html', context)


@login_required
def approve_user_view(request, pk):
    if not is_moderator_or_higher(request.user):
        return redirect('home')
    if request.method == 'POST':
        user_to_approve = get_object_or_404(User, pk=pk)
        user_to_approve.is_approved = True
        user_to_approve.save()
        AuditLog.objects.create(actor=request.user, action=f"Одобрил пользователя: {user_to_approve.get_full_name()}", target_user=user_to_approve)
        Notification.objects.create(
            recipient=user_to_approve,
            message="Поздравляем! Ваш профиль был одобрен.",
            link=reverse('my_profile'),
        )
        messages.success(request, f'Профиль {user_to_approve.get_full_name()} одобрен.')
    return redirect('moderator_dashboard')


@login_required
def reject_user_view(request, pk):
    if not is_moderator_or_higher(request.user):
        return redirect('home')
    user_to_reject = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        reason = request.POST.get('reason', 'Причина не указана.')
        Notification.objects.create(
            recipient=user_to_reject,
            message=f'Ваша регистрация была отклонена. Причина: "{reason}"',
        )
        user_to_reject.delete()
        AuditLog.objects.create(actor=request.user, action=f"Отклонил (удалил) пользователя: {user_to_reject.get_full_name()}", target_user=user_to_reject)
        messages.warning(
            request, f'Профиль {user_to_reject.get_full_name()} отклонен и удален.'
        )
    return redirect('moderator_dashboard')


# --- Панель администратора ---
@login_required
def admin_dashboard_view(request):
    if not is_admin_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    context = {'total_users': User.objects.count()}
    return render(request, 'users/admin_dashboard.html', context)


# --- ПАНЕЛИ УПРАВЛЕНИЯ ---
# ... (весь остальной код для панелей модератора и администратора остается без изменений)
@login_required
def moderator_dashboard_view(request):
    if not is_moderator_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    pending_users = User.objects.filter(is_approved=False)
    context = {'pending_users': pending_users}
    return render(request, 'users/moderator_dashboard.html', context)

@login_required
def approve_user_view(request, pk):
    if not is_moderator_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        user_to_approve = get_object_or_404(User, pk=pk)
        user_to_approve.is_approved = True
        user_to_approve.save()
        Notification.objects.create(recipient=user_to_approve, message="Поздравляем! Ваш профиль был одобрен.", link=reverse('my_profile'))
        messages.success(request, f'Профиль {user_to_approve.get_full_name()} одобрен.')
    return redirect('moderator_dashboard')

@login_required
def pending_changes_view(request):
    if not is_moderator_or_higher(request.user): return redirect('home')
    users_with_changes = User.objects.filter(pending_changes__isnull=False).exclude(pending_changes={})
    for user in users_with_changes:
        if user.pending_changes:
            try:
                user.decoded_changes = json.loads(user.pending_changes)
            except (json.JSONDecodeError, TypeError):
                user.decoded_changes = {}
    return render(request, 'users/pending_changes.html', {'users_with_changes': users_with_changes})

@login_required
def approve_changes_view(request, pk):
    if not is_moderator_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        user_to_update = get_object_or_404(User, pk=pk)
        if user_to_update.pending_changes:
            try:
                changes = json.loads(user_to_update.pending_changes)
                for field, value in changes.items():
                    setattr(user_to_update, field, value)
            except (json.JSONDecodeError, TypeError):
                pass
            user_to_update.pending_changes = None
            user_to_update.moderation_comment = ""
            user_to_update.save()
            Notification.objects.create(recipient=user_to_update, message="Ваши изменения в профиле были одобрены модератором.", link=reverse('my_profile'))
            messages.success(request, f'Изменения для {user_to_update.get_full_name()} одобрены.')
    return redirect('pending_changes')

@login_required
def reject_changes_view(request, pk):
    if not is_moderator_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        user_to_update = get_object_or_404(User, pk=pk)
        reason = request.POST.get('reason', 'Причина не указана.')
        user_to_update.pending_changes = None
        user_to_update.moderation_comment = reason
        user_to_update.save()
        Notification.objects.create(recipient=user_to_update, message=f'Ваши изменения отклонены. Причина: "{reason}"', link=reverse('my_profile'))
        messages.warning(request, f'Изменения для {user_to_update.get_full_name()} были отклонены.')
    return redirect('pending_changes')

@login_required
def admin_dashboard_view(request):
    if not is_admin_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    context = {'total_users': User.objects.count()}
    return render(request, 'users/admin_dashboard.html', context)

@login_required
def user_management_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    users_list = User.objects.all().order_by('last_name')
    role_choices = User.ROLE_CHOICES
    context = {'users_list': users_list, 'role_choices': role_choices}
    return render(request, 'users/user_management.html', context)

@login_required
def update_user_role_view(request, pk):
    # Доступ: Президент и выше (но внутри проверим строже)
    if not is_admin_or_higher(request.user): 
        return redirect('home')

    if request.method == 'POST':
        user_to_update = get_object_or_404(User, pk=pk)
        
        # ИЕРАРХИЯ: Проверяем, может ли текущий юзер менять роль этому человеку
        my_level = get_user_power_level(request.user)
        target_level = get_user_power_level(user_to_update)
        
        if my_level <= target_level:
             messages.error(request, "Вы не можете менять роль пользователю равного или более высокого ранга.")
             return redirect('user_management')

        new_role = request.POST.get('role')
        
        # ИЕРАРХИЯ 2: Нельзя назначить роль выше своей
        # (Для упрощения пока пропустим сложную проверку назначения, 
        # главное - нельзя трогать тех, кто выше).

        if new_role in [role[0] for role in User.ROLE_CHOICES]:
            # Спец. логика: Если назначаем Руководителя отдела
            if new_role == 'head_admin':
                # Если это делает не Супер-админ - запрет (или можно разрешить старому Руководителю)
                if not request.user.is_superuser and request.user.role != 'head_admin':
                     messages.error(request, "Назначать Руководителя отдела может только Супер-админ или текущий Руководитель.")
                     return redirect('user_management')
                
                # Снимаем старого руководителя (если есть)
                old_head = User.objects.filter(role='head_admin').first()
                if old_head:
                    old_head.role = 'worker' # Становится работником
                    old_head.save()
                    log_action(request.user, f"Автоматически разжаловал {old_head.get_full_name()} до Работника (смена власти)", target=old_head)

            user_to_update.role = new_role
            user_to_update.save()
            
            role_name = dict(User.ROLE_CHOICES).get(new_role)
            log_action(request.user, f"Изменил роль для {user_to_update.get_full_name()} на '{role_name}'", target=user_to_update)
            
            messages.success(request, f'Роль обновлена.')
    return redirect('user_management')

@login_required
def toggle_active_volunteer_view(request, pk):
    if not is_admin_or_higher(request.user):
        messages.error(request, "У вас нет прав для выполнения этого действия.")
        return redirect('home')
    if request.method == 'POST':
        user_to_update = get_object_or_404(User, pk=pk)
        user_to_update.is_active_volunteer_title = not user_to_update.is_active_volunteer_title
        user_to_update.save()
        action_text = "присвоил" if user_to_update.is_active_volunteer_title else "снял"
        AuditLog.objects.create(actor=request.user, action=f"{action_text} статус 'Активный волонтер' для {user_to_update.get_full_name()}", target_user=user_to_update)
        if user_to_update.is_active_volunteer_title:
            messages.success(request, f'Волонтеру {user_to_update.get_full_name()} присвоено звание "Активный волонтер".')
        else:
            messages.warning(request, f'С волонтера {user_to_update.get_full_name()} снято звание "Активный волонтер".')
    return redirect('user_management')

@login_required
def direction_management_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    directions = Direction.objects.all().prefetch_related('leader')
    volunteers = User.objects.filter(is_approved=True)
    return render(request, 'users/direction_management.html', {'directions': directions, 'volunteers': volunteers})

@login_required
def direction_create_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        name = request.POST.get('name')
        if name and not Direction.objects.filter(name=name).exists():
            Direction.objects.create(name=name)
            AuditLog.objects.create(actor=request.user, action=f"Создал направление: {name}")
            messages.success(request, f'Направление "{name}" создано.')
        else: messages.error(request, 'Направление с таким именем уже существует или имя не указано.')
    return redirect('direction_management')

@login_required
def direction_delete_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    direction = get_object_or_404(Direction, pk=pk)
    if request.method == 'POST':
        direction.delete()
        AuditLog.objects.create(actor=request.user, action=f"Удалил направление: {direction.name}")
        messages.warning(request, f'Направление "{direction.name}" удалено.')
    return redirect('direction_management')

@login_required
def assign_direction_leader_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        direction = get_object_or_404(Direction, pk=pk)
        leader_id = request.POST.get('leader')
        if direction.leader:
            old_leader = direction.leader
            if not Direction.objects.filter(leader=old_leader).exclude(pk=pk).exists():
                old_leader.role = 'volunteer'; old_leader.save()
        if leader_id:
            new_leader = get_object_or_404(User, pk=leader_id)
            direction.leader = new_leader; direction.save()
            new_leader.role = 'leader'; new_leader.save()
            AuditLog.objects.create(actor=request.user, action=f"Назначил {new_leader.get_full_name()} руководителем направления '{direction.name}'", target_user=new_leader)
            messages.success(request, f'{new_leader.get_full_name()} назначен руководителем направления "{direction.name}".')
        else:
            if direction.leader:
                old_leader = direction.leader
                old_leader.role = 'volunteer'
                old_leader.save()
            direction.leader = None; direction.save()
            AuditLog.objects.create(actor=request.user, action=f"Снял руководителя с направления '{direction.name}'")
            messages.info(request, f'С направления "{direction.name}" снят руководитель.')
    return redirect('direction_management')

@login_required
def school_management_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    schools = School.objects.all().prefetch_related('leaders')
    volunteers = User.objects.filter(is_approved=True)
    return render(request, 'users/school_management.html', {'schools': schools, 'volunteers': volunteers})

@login_required
def school_create_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        name = request.POST.get('name')
        if name and not School.objects.filter(name=name).exists():
            School.objects.create(name=name)
            AuditLog.objects.create(actor=request.user, action=f"Создал школу: {name}")
            messages.success(request, f'Школа "{name}" создана.')
        else: messages.error(request, 'Школа с таким именем уже существует или имя не указано.')
    return redirect('school_management')

@login_required
def school_delete_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    school = get_object_or_404(School, pk=pk)
    if request.method == 'POST':
        school.delete()
        AuditLog.objects.create(actor=request.user, action=f"Удалил школу: {school.name}")
        messages.warning(request, f'Школа "{school.name}" удалена.')
    return redirect('school_management')

@login_required
def assign_school_leader_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        school = get_object_or_404(School, pk=pk)
        leader_id = request.POST.get('leader_id')
        leader_to_assign = get_object_or_404(User, pk=leader_id)
        if leader_to_assign in school.leaders.all():
            leader_to_assign.school_leader_of.remove(school)
            AuditLog.objects.create(actor=request.user, action=f"Снял {leader_to_assign.get_full_name()} с руководства школой '{school.name}'", target_user=leader_to_assign)
            messages.info(request, f'{leader_to_assign.get_full_name()} больше не руководит школой "{school.name}".')
        else:
            leader_to_assign.school_leader_of.add(school)
            AuditLog.objects.create(actor=request.user, action=f"Назначил {leader_to_assign.get_full_name()} руководителем школы '{school.name}'", target_user=leader_to_assign)
            messages.success(request, f'{leader_to_assign.get_full_name()} назначен руководителем школы "{school.name}".')
    return redirect('school_management')

@login_required
def about_page_edit_view(request):
    if not is_admin_or_higher(request.user): return redirect('home')
    
    about_page, created = AboutPage.objects.get_or_create(pk=1)
    
    if request.method == 'POST':
        form = AboutPageForm(request.POST, instance=about_page)
        if form.is_valid():
            form.save()
            log_action(request.user, "Отредактировал страницу 'О нас'")
            messages.success(request, 'Страница обновлена полностью.')
            return redirect('about_page_edit')
    else:
        form = AboutPageForm(instance=about_page)
        
    return render(request, 'users/about_page_edit.html', {'form': form})

# --- УВЕДОМЛЕНИЯ ---
@login_required
def notification_list_view(request):
    notifications = Notification.objects.filter(recipient=request.user)
    return render(request, 'users/notifications.html', {'notifications': notifications})

@login_required
def mark_notification_as_read_view(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not notification.is_read:
        notification.is_read = True
        notification.save()
    if notification.link: return redirect(notification.link)
    else: return redirect('notification_list')

    # --- НОВАЯ VIEW: ДЛЯ РЕДАКТИРОВАНИЯ МОДЕРАТОРОМ ---
@login_required
def admin_edit_user_view(request, pk):
    """
    Позволяет Модератору (и выше) редактировать профиль
    любого пользователя.
    """
    # --- НОВЫЙ КОД ---
    user_to_edit = get_object_or_404(User, pk=pk) # Сначала получаем цель

    # Проверяем иерархию
    viewer_level = get_user_power_level(request.user)
    target_level = get_user_power_level(user_to_edit)

    if viewer_level <= target_level:
        messages.error(request, "У вас недостаточно прав для редактирования этого профиля.")
        return redirect('public_profile', pk=pk)
    # --- КОНЕЦ НОВОГО КОДА ---

    if request.method == 'POST':
        # Используем AdminUpdateForm, в которой НЕТ полей приватности
        form = AdminUpdateForm(request.POST, request.FILES, instance=user_to_edit)
        if form.is_valid():
            form.save() # Мгновенное сохранение
            AuditLog.objects.create(actor=request.user, action=f"Отредактировал профиль: {user_to_edit.get_full_name()}", target_user=user_to_edit)

            # Отправляем уведомление волонтеру, если его редактирует кто-то другой
            if request.user != user_to_edit:
                Notification.objects.create(
                    recipient=user_to_edit,
                    message=f'Модератор {request.user.get_full_name()} внес изменения в ваш профиль.',
                    link=reverse('my_profile')
                )

            messages.success(request, f'Профиль {user_to_edit.get_full_name()} был успешно обновлен.')
            return redirect('public_profile', pk=pk)
    else:
        form = AdminUpdateForm(instance=user_to_edit)

    # Мы используем тот же шаблон, что и для обычного редактирования
    return render(request, 'users/profile_edit.html', { 
        'form': form, 
        'user_to_edit': user_to_edit
    })

# --- НОВАЯ VIEW ДЛЯ ЖУРНАЛА ДЕЙСТВИЙ ---
@login_required
def audit_log_view(request):
    # Проверяем, что это АДМИН или ВЫШЕ (но не модератор)
    if not is_admin_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')

    # Получаем все логи
    audit_logs = AuditLog.objects.all()

    context = {
        'audit_logs': audit_logs
    }
    return render(request, 'users/audit_log.html', context)

# users/forms.py (Добавьте это в конец)

from .models import AboutPage # Убедитесь, что AboutPage импортирован
