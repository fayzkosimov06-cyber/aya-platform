# users/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from .forms import UserRegisterForm, UserUpdateForm
from .models import User, Direction, School, ActivityPeriod, Notification, AboutPage
from events.models import Event
import json
import datetime # <-- Добавлен импорт
from django.urls import reverse
from django.db.models import Q
from django.utils import timezone

# --- ДЕКОРАТОРЫ ПРОВЕРКИ ПРАВ ---
def is_moderator_or_higher(user):
    return user.is_authenticated and (user.role in ['moderator', 'president', 'worker', 'head_admin'] or user.is_superuser)

def is_admin_or_higher(user):
    return user.is_authenticated and (user.role in ['president', 'worker', 'head_admin'] or user.is_superuser)

# --- ОБЩИЕ VIEW ---
def home_view(request):
    president = User.objects.filter(role='president', is_approved=True).first()
    key_figures_qs = User.objects.filter(
        Q(role='leader') | Q(school_leader_of__isnull=False),
        is_approved=True
    ).distinct()
    if president:
        key_figures_qs = key_figures_qs.exclude(pk=president.pk)
    
    # upcoming_events = Event.objects.filter(is_approved=True, start_time__gte=timezone.now()).order_by('start_time')[:3]
    
    context = {
        'president': president,
        'board_of_honor': key_figures_qs,
        # 'upcoming_events': upcoming_events,
    }
    return render(request, 'users/home.html', context)

def about_view(request):
    about_content = AboutPage.objects.first()
    return render(request, 'users/about.html', {'about_content': about_content})

def volunteer_list_view(request):
    queryset = User.objects.filter(is_approved=True).order_by('last_name')
    faculties = User.objects.filter(is_approved=True, faculty__isnull=False).exclude(faculty='').values_list('faculty', flat=True).distinct().order_by('faculty')
    courses = User.objects.filter(is_approved=True, course__isnull=False).values_list('course', flat=True).distinct().order_by('course')
    cities = User.objects.filter(is_approved=True, city__isnull=False).exclude(city='').values_list('city', flat=True).distinct().order_by('city')
    directions = Direction.objects.all().order_by('name')

    query = request.GET.get('query')
    faculty = request.GET.get('faculty')
    course = request.GET.get('course')
    city = request.GET.get('city')
    gender = request.GET.get('gender')
    direction = request.GET.get('direction')
    status = request.GET.get('status')

    if query:
        queryset = queryset.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(patronymic__icontains=query))
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
        if status == 'active': queryset = queryset.filter(is_active_volunteer_title=True)
        if status == 'leader': queryset = queryset.filter(role='leader')
        if status == 'school_leader': queryset = queryset.filter(school_leader_of__isnull=False).distinct()
        if status == 'president': queryset = queryset.filter(role='president')

    context = {
        'volunteers': queryset, 'faculties': faculties, 'courses': courses,
        'cities': cities, 'directions': directions, 'form_values': request.GET
    }
    return render(request, 'users/volunteer_list.html', context)

# --- АУТЕНТИФИКАЦИЯ ---
def signup_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_approved = False 
            user.save()
            moderators = User.objects.filter(role__in=['moderator', 'worker', 'head_admin', 'president'])
            for moderator in moderators:
                Notification.objects.create(recipient=moderator, message=f'Новый волонтер "{user.get_full_name()}" зарегистрировался.', link=reverse('moderator_dashboard'))
            messages.success(request, 'Ваш аккаунт создан и отправлен на модерацию!')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'users/signup.html', {'form': form})

def logout_view(request):
    logout(request)
    messages.info(request, "Вы успешно вышли из системы.")
    return redirect('home')

# --- ПРОФИЛИ ---
@login_required
def my_profile_view(request):
    activity_periods = request.user.activity_periods.all()
    context = {'profile_user': request.user, 'activity_periods': activity_periods}
    return render(request, 'users/profile.html', context)

# === КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (1/3) ===
@login_required
def profile_edit_view(request):
    user = request.user
    
    if request.method == 'POST':
        # Собираем СТАРЫЕ данные для сравнения
        initial_data = {}
        for field_name in UserUpdateForm.Meta.fields:
             if field_name != 'photo':
                initial_data[field_name] = getattr(user, field_name)

        # Передаем 'initial' в конструктор, но НЕ instance
        form = UserUpdateForm(request.POST, request.FILES, initial=initial_data)

        if form.is_valid():
            changes = {}
            
            # Теперь .changed_data работает ПРАВИЛЬНО
            for field in form.changed_data:
                if field == 'photo':
                    continue 
                
                data = form.cleaned_data[field]
                
                # Конвертируем типы, которые JSON не понимает
                if isinstance(data, (datetime.date, datetime.datetime)):
                    changes[field] = data.isoformat() # Сохраняем как строку 'YYYY-MM-DD'
                elif data is None:
                    changes[field] = None # Сохраняем None
                else:
                    changes[field] = data # Сохраняем str, int, bool

            # Получаем ЧИСТУЮ копию пользователя из БД
            fresh_user = User.objects.get(pk=user.pk)

            # Обрабатываем фото (оно сохраняется сразу)
            if 'photo' in request.FILES:
                fresh_user.photo = request.FILES['photo']
                if not changes: # Если изменили ТОЛЬКО фото
                    fresh_user.save()
                    messages.success(request, 'Фотография профиля обновлена.')
                    return redirect('my_profile')
            
            if changes:
                fresh_user.pending_changes = changes # Сохраняем dict в JSONField
                fresh_user.moderation_comment = "" 
                fresh_user.save() # Сохраняем ТОЛЬКО photo и pending_changes
                
                moderators = User.objects.filter(role__in=['moderator', 'worker', 'head_admin', 'president'])
                for moderator in moderators:
                    Notification.objects.create(
                        recipient=moderator,
                        message=f'Волонтер "{user.get_full_name()}" предложил изменения.',
                        link=reverse('pending_changes')
                    )
                messages.info(request, 'Ваши изменения отправлены на модерацию. Они не появятся в профиле до одобрения.')
            
            return redirect('my_profile')
        else:
            return render(request, 'users/profile_edit.html', {'form': form})
            
    else:
        # GET-запрос: показываем форму, заполненную текущими данными
        form = UserUpdateForm(instance=user)
        if user.moderation_comment:
            user.moderation_comment = ""
            user.save()
            
    return render(request, 'users/profile_edit.html', {'form': form})
# === КОНЕЦ КРИТИЧЕСКОГО ИСПРАВЛЕНИЯ (1/3) ===


def public_profile_view(request, pk):
    profile_user = get_object_or_404(User, pk=pk)
    if not profile_user.is_approved and not (request.user.is_authenticated and is_moderator_or_higher(request.user)):
        messages.error(request, "Этот профиль еще не прошел модерацию.")
        return redirect('home')
    activity_periods = profile_user.activity_periods.all()
    context = {'profile_user': profile_user, 'activity_periods': activity_periods}
    return render(request, 'users/profile.html', context)

# --- ПАНЕЛЬ МОДЕРАТОРА ---
@login_required
def moderator_dashboard_view(request):
    if not is_moderator_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    pending_users = User.objects.filter(is_approved=False)
    pending_changes = User.objects.filter(pending_changes__isnull=False).exclude(pending_changes={})
    context = {'pending_users': pending_users, 'pending_changes': pending_changes}
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
def reject_user_view(request, pk):
    if not is_moderator_or_higher(request.user): return redirect('home')
    user_to_reject = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        reason = request.POST.get('reason', 'Причина не указана.')
        Notification.objects.create(recipient=user_to_reject, message=f'Ваша регистрация была отклонена. Причина: "{reason}"')
        user_to_reject.delete() 
        messages.warning(request, f'Профиль {user_to_reject.get_full_name()} отклонен и удален.')
    return redirect('moderator_dashboard')

# === КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (2/3) ===
@login_required
def pending_changes_view(request):
    if not is_moderator_or_higher(request.user): return redirect('home')
    
    users_with_changes = User.objects.filter(pending_changes__isnull=False).exclude(pending_changes={})
    
    field_names = {
        'first_name': 'Имя', 'last_name': 'Фамилия', 'patronymic': 'Отчество',
        'birth_date': 'Дата рождения', 'gender': 'Пол', 'city': 'Город',
        'about_me': 'О себе', 'faculty': 'Факультет', 'course': 'Курс',
        'group': 'Группа', 'phone': 'Телефон', 'telegram': 'Telegram',
        'phone_privacy': 'Приватность телефона', 'telegram_privacy': 'Приватность Telegram'
    }

    for user in users_with_changes:
        changes_list = []
        decoded_changes = user.pending_changes
        
        if isinstance(decoded_changes, str):
            try: decoded_changes = json.loads(decoded_changes)
            except (json.JSONDecodeError, TypeError): decoded_changes = {}

        if isinstance(decoded_changes, dict):
            for field, new_value in decoded_changes.items():
                old_value = getattr(user, field, '') 
                
                # Форматируем для красоты
                if field == 'gender':
                    old_value_display = user.get_gender_display()
                    new_value_display = 'Мужской' if new_value == 'M' else ('Женский' if new_value == 'F' else '(не указано)')
                elif field in ['phone_privacy', 'telegram_privacy']:
                    old_value_display = dict(User.PRIVACY_CHOICES).get(old_value, old_value)
                    new_value_display = dict(User.PRIVACY_CHOICES).get(new_value, new_value)
                elif field == 'course':
                    old_value_display = old_value if old_value else "(не указано)"
                    new_value_display = new_value if new_value else "(не указано)"
                elif field == 'birth_date':
                    try: old_value_display = old_value.strftime('%Y-%m-%d')
                    except: old_value_display = old_value if old_value else "(не указано)"
                    new_value_display = new_value if new_value else "(не указано)"
                else:
                    old_value_display = old_value if (old_value is not None and old_value != '') else "(не указано)"
                    new_value_display = new_value if (new_value is not None and new_value != '') else "(не указано)"
                
                changes_list.append({
                    'field_name': field_names.get(field, field),
                    'old': old_value_display,
                    'new': new_value_display
                })
        
        user.changes_list = changes_list
            
    return render(request, 'users/pending_changes.html', {'users_with_changes': users_with_changes})
# === КОНЕЦ КРИТИЧЕСКОГО ИСПРАВЛЕНИЯ (2/3) ===


# === КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ (3/3) ===
@login_required
def approve_changes_view(request, pk):
    if not is_moderator_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        user_to_update = get_object_or_404(User, pk=pk)
        
        if user_to_update.pending_changes:
            changes = user_to_update.pending_changes
            if isinstance(changes, str):
                try: changes = json.loads(changes)
                except (json.JSONDecodeError, TypeError): changes = {}

            if isinstance(changes, dict):
                for field, value in changes.items():
                    # === ГЛАВНОЕ ИСПРАВЛЕНИЕ ЗДЕСЬ ===
                    # Мы должны конвертировать данные ОБРАТНО в нужный тип
                    
                    # Если 'course' (int) или 'birth_date' (date) пустые
                    if (field == 'course' or field == 'birth_date') and (value is None or value == ''):
                        setattr(user_to_update, field, None)
                    # Если 'birth_date' не пустая, конвертируем из строки в дату
                    elif field == 'birth_date':
                        try:
                            setattr(user_to_update, field, datetime.date.fromisoformat(value))
                        except (ValueError, TypeError):
                            pass # Пропускаем, если формат даты сломан
                    # Если 'course' не пустой, конвертируем из строки в число
                    elif field == 'course':
                        try:
                            setattr(user_to_update, field, int(value))
                        except (ValueError, TypeError):
                            pass # Пропускаем, если не число
                    # Все остальные поля (str, bool)
                    else:
                        setattr(user_to_update, field, value)
            
            user_to_update.pending_changes = None # Очищаем поле
            user_to_update.moderation_comment = ""
            user_to_update.save() # СОХРАНЯЕМ ИЗМЕНЕНИЯ
            
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
# === КОНЕЦ КРИТИЧЕСКОГО ИСПРАВЛЕНИЯ (3/3) ===

# --- ПАНЕЛЬ АДМИНИСТРАТОРА (остальной код) ---
@login_required
def admin_dashboard_view(request):
    if not is_admin_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    context = {'total_users': User.objects.count()}
    return render(request, 'users/admin_dashboard.html', context)
# ...
# --- ПАНЕЛИ УПРАВЛЕНИЯ ---
# ... (весь остальной код для панелей модератора и администратора остается без изменений)
@login_required
def moderator_dashboard_view(request):
    if not is_moderator_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    pending_users = User.objects.filter(is_approved=False)
    pending_changes = User.objects.filter(pending_changes__isnull=False).exclude(pending_changes={})
    context = {'pending_users': pending_users, 'pending_changes': pending_changes}
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
    if not is_admin_or_higher(request.user): return redirect('home')
    if request.method == 'POST':
        user_to_update = get_object_or_404(User, pk=pk)
        new_role = request.POST.get('role')
        if new_role in [role[0] for role in User.ROLE_CHOICES]:
            user_to_update.role = new_role
            user_to_update.save()
            messages.success(request, f'Роль для {user_to_update.get_full_name()} обновлена.')
        else: messages.error(request, "Выбрана некорректная роль.")
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
            messages.success(request, f'Направление "{name}" создано.')
        else: messages.error(request, 'Направление с таким именем уже существует или имя не указано.')
    return redirect('direction_management')

@login_required
def direction_delete_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    direction = get_object_or_404(Direction, pk=pk)
    if request.method == 'POST':
        direction.delete()
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
            messages.success(request, f'{new_leader.get_full_name()} назначен руководителем направления "{direction.name}".')
        else:
            if direction.leader:
                old_leader = direction.leader
                old_leader.role = 'volunteer'
                old_leader.save()
            direction.leader = None; direction.save()
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
            messages.success(request, f'Школа "{name}" создана.')
        else: messages.error(request, 'Школа с таким именем уже существует или имя не указано.')
    return redirect('school_management')

@login_required
def school_delete_view(request, pk):
    if not is_admin_or_higher(request.user): return redirect('home')
    school = get_object_or_404(School, pk=pk)
    if request.method == 'POST':
        school.delete()
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
            messages.info(request, f'{leader_to_assign.get_full_name()} больше не руководит школой "{school.name}".')
        else:
            leader_to_assign.school_leader_of.add(school)
            messages.success(request, f'{leader_to_assign.get_full_name()} назначен руководителем школы "{school.name}".')
    return redirect('school_management')

@login_required
def about_page_edit_view(request):
    if not is_admin_or_higher(request.user):
        messages.error(request, "У вас нет доступа к этой странице.")
        return redirect('home')
    about_page, created = AboutPage.objects.get_or_create(pk=1)
    if request.method == 'POST':
        about_page.title = request.POST.get('title', '')
        about_page.content = request.POST.get('content', '')
        about_page.video_url = request.POST.get('video_url', '')
        about_page.save()
        messages.success(request, 'Страница "О нас" успешно обновлена.')
        return redirect('about_page_edit')
    return render(request, 'users/about_page_edit.html', {'about_page': about_page})

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