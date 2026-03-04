from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from .models import Event, EventPhoto, EventVideo, EventHero
from .forms import EventCreateForm, EventReportForm, EventVideoForm, EventHeroForm
from users.models import AuditLog

# --- Логирование ("Призрак") ---
def log_event_action(user, action_text):
    if not user.is_superuser:
        AuditLog.objects.create(actor=user, action=action_text)

# --- Права ---
def can_manage_event(user, event):
    if user.is_superuser: return True
    if user == event.organizer: return True
    if user.role in ['moderator', 'president', 'worker', 'head_admin']: return True
    return False

def can_create_instantly(user):
    return user.role in ['leader', 'president', 'worker', 'head_admin', 'moderator'] or user.is_superuser

# events/views.py

def event_list_view(request):
    q = (request.GET.get('q') or '').strip()

    # База: показываем только одобренные
    upcoming_events = Event.objects.filter(is_approved=True, is_completed=False)
    past_events = Event.objects.filter(is_approved=True, is_completed=True)

    # Гости видят только публичные для гостей
    if not request.user.is_authenticated:
        upcoming_events = upcoming_events.filter(is_public_for_guests=True)
        past_events = past_events.filter(is_public_for_guests=True)

    # Поиск (название, описание, локация)
    if q:
        upcoming_events = upcoming_events.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q)
        )
        past_events = past_events.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q)
        )

    upcoming_events = upcoming_events.order_by('start_time')
    past_events = past_events.order_by('-end_time')

    return render(request, 'events/event_list.html', {
        'upcoming_events': upcoming_events,
        'past_events': past_events
    })
def event_detail_view(request, pk):
    event = get_object_or_404(Event, pk=pk)

    # 1) Неодобренное мероприятие: показываем только тем, кто может управлять
    if not event.is_approved:
        if not (request.user.is_authenticated and can_manage_event(request.user, event)):
            messages.error(request, "Мероприятие еще не опубликовано.")
            return redirect('event_list')

    # 2) Гости могут видеть только публичные для гостей
    if not request.user.is_authenticated and not event.is_public_for_guests:
        messages.info(request, "Войдите, чтобы просмотреть это мероприятие.")
        return redirect('login')

    is_participant = False
    can_manage = False
    if request.user.is_authenticated:
        is_participant = event.participants.filter(pk=request.user.pk).exists()
        can_manage = can_manage_event(request.user, event)

    return render(request, 'events/event_detail.html', {
        'event': event,
        'is_participant': is_participant,
        'can_manage': can_manage
    })

@login_required
def event_create_view(request):
    if request.method == 'POST':
        form = EventCreateForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.organizer = request.user
            if can_create_instantly(request.user):
                event.is_approved = True
                msg = "Мероприятие опубликовано!"
            else:
                event.is_approved = False
                msg = "Отправлено на модерацию."
            event.save()
            log_event_action(request.user, f"Создал мероприятие '{event.title}'")
            messages.success(request, msg)
            return redirect('event_detail', pk=event.pk)
    else:
        form = EventCreateForm()
    return render(request, 'events/event_create.html', {'form': form})

@login_required
def event_edit_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not can_manage_event(request.user, event): return redirect('event_detail', pk=pk)
    
    if request.method == 'POST':
        form = EventCreateForm(request.POST, request.FILES, instance=event)
        if form.is_valid():
            form.save()
            log_event_action(request.user, f"Отредактировал мероприятие '{event.title}'")
            messages.success(request, "Обновлено.")
            return redirect('event_detail', pk=pk)
    else:
        form = EventCreateForm(instance=event)
    return render(request, 'events/event_edit.html', {'form': form, 'event': event})

@login_required
def event_finish_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not can_manage_event(request.user, event): return redirect('event_detail', pk=pk)
    
    if request.method == 'POST':
        event.is_completed = True
        event.save()
        log_event_action(request.user, f"Завершил мероприятие '{event.title}'")
        messages.success(request, "Завершено! Заполните отчет.")
        return redirect('event_report_edit', pk=pk)
    return redirect('event_detail', pk=pk)

@login_required
def event_report_edit_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not can_manage_event(request.user, event):
        return redirect('event_detail', pk=pk)

    # Формы по умолчанию (GET)
    report_form = EventReportForm(instance=event)
    video_form = EventVideoForm()
    hero_form = EventHeroForm()

    if request.method == 'POST':
        action = (request.POST.get('action') or '').strip()

        # 1) Сохранить основной отчёт + фото + публикация
        if action == 'save_report':
            report_form = EventReportForm(request.POST, instance=event)
            if report_form.is_valid():
                report_form.save()

                photos = request.FILES.getlist('photos')
                if photos:
                    for photo in photos:
                        EventPhoto.objects.create(event=event, image=photo)
                    log_event_action(request.user, f"Добавил {len(photos)} фото в отчет '{event.title}'")

                log_event_action(request.user, f"Обновил основной контент отчета '{event.title}'")
                messages.success(request, "Отчет сохранен.")
                return redirect('event_report_edit', pk=pk)

        # 2) Добавить видео
        elif action == 'add_video':
            video_form = EventVideoForm(request.POST)
            if video_form.is_valid() and video_form.cleaned_data.get('video_url'):
                v = video_form.save(commit=False)
                v.event = event
                v.save()
                log_event_action(request.user, f"Добавил видео в отчет '{event.title}'")
                messages.success(request, "Видео добавлено.")
                return redirect('event_report_edit', pk=pk)

        # 3) Добавить героя (если уже был — обновим роль)
        elif action == 'add_hero':
            hero_form = EventHeroForm(request.POST)
            if hero_form.is_valid() and hero_form.cleaned_data.get('user'):
                user = hero_form.cleaned_data['user']
                role_name = (hero_form.cleaned_data.get('role_name') or '').strip()

                hero_obj, created = EventHero.objects.update_or_create(
                    event=event,
                    user=user,
                    defaults={'role_name': role_name}
                )

                if created:
                    log_event_action(request.user, f"Отметил героя {user.get_full_name()} в '{event.title}'")
                    messages.success(request, "Герой отмечен.")
                else:
                    log_event_action(request.user, f"Обновил роль героя {user.get_full_name()} в '{event.title}'")
                    messages.success(request, "Роль героя обновлена.")
                return redirect('event_report_edit', pk=pk)

        # 4) Редактировать роль героя
        elif action == 'update_hero':
            hero_id = request.POST.get('hero_id')
            role_name = (request.POST.get('role_name') or '').strip()

            hero_obj = get_object_or_404(EventHero, pk=hero_id, event=event)
            hero_obj.role_name = role_name
            hero_obj.save(update_fields=['role_name'])

            log_event_action(request.user, f"Изменил роль героя {hero_obj.user.get_full_name()} в '{event.title}'")
            messages.success(request, "Роль обновлена.")
            return redirect('event_report_edit', pk=pk)

        # 5) Удалить героя
        elif action == 'delete_hero':
            hero_id = request.POST.get('hero_id')
            hero_obj = get_object_or_404(EventHero, pk=hero_id, event=event)

            full_name = hero_obj.user.get_full_name()
            hero_obj.delete()

            log_event_action(request.user, f"Удалил отметку героя {full_name} в '{event.title}'")
            messages.success(request, "Отметка героя удалена.")
            return redirect('event_report_edit', pk=pk)

        else:
            messages.error(request, "Неизвестное действие формы.")

    return render(request, 'events/event_report_edit.html', {
        'event': event,
        'report_form': report_form,
        'video_form': video_form,
        'hero_form': hero_form
    })

@login_required
def event_join_view(request, pk):
    event = get_object_or_404(Event, pk=pk)

    if not request.user.is_approved:
        messages.error(request, "Ваш профиль еще не одобрен. Запись на мероприятия будет доступна после одобрения.")
        return redirect('event_detail', pk=pk)

    if not event.is_approved:
        messages.error(request, "Это мероприятие еще не опубликовано.")
        return redirect('event_detail', pk=pk)

    if event.is_completed:
        messages.info(request, "Мероприятие уже завершено.")
        return redirect('event_detail', pk=pk)

    if event.participants.filter(pk=request.user.pk).exists():
        event.participants.remove(request.user)
        messages.info(request, "Вы отменили запись.")
        return redirect('event_detail', pk=pk)

    # Проверка лимита участников
    if event.max_participants is not None:
        current_count = event.participants.count()
        if current_count >= event.max_participants:
            messages.error(request, "Достигнут лимит участников для этого мероприятия.")
            return redirect('event_detail', pk=pk)

    event.participants.add(request.user)
    messages.success(request, "Вы записаны!")
    return redirect('event_detail', pk=pk)

# --- УДАЛЕНИЕ ФОТО ---
@login_required
def event_photo_delete_view(request, pk):
    photo = get_object_or_404(EventPhoto, pk=pk)
    event = photo.event
    
    # Проверка прав (используем ту же логику, что и для ивента)
    if not can_manage_event(request.user, event):
        messages.error(request, "У вас нет прав удалять фото в этом событии.")
        return redirect('event_detail', pk=event.pk)

    if request.method == 'POST':
        # Лог (призрак)
        log_event_action(request.user, f"Удалил фотографию из отчета '{event.title}'")
        
        photo.delete()
        messages.success(request, "Фотография удалена.")
        
    return redirect('event_report_edit', pk=event.pk)

# --- УДАЛЕНИЕ МЕРОПРИЯТИЯ ---
@login_required
def event_delete_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    
    # Проверка прав (используем нашу функцию)
    if not can_manage_event(request.user, event):
        messages.error(request, "У вас нет прав удалять это мероприятие.")
        return redirect('event_detail', pk=pk)
    
    if request.method == 'POST':
        title = event.title # Сохраняем название для лога
        event.delete()
        
        # Лог (Призрак: супер-админ не пишется)
        log_event_action(request.user, f"Удалил мероприятие '{title}'")
        
        messages.warning(request, f"Мероприятие '{title}' было удалено.")
        return redirect('event_list')
        
    return redirect('event_detail', pk=pk)