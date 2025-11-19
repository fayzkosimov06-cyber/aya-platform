from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
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
    return user.role in ['leader', 'president', 'worker', 'head_admin'] or user.is_superuser

# events/views.py

def event_list_view(request):
    upcoming_events = Event.objects.filter(is_approved=True, is_completed=False).order_by('start_time')
    
    # ИСПРАВЛЕНИЕ: Показываем ВСЕ завершенные мероприятия, даже если отчет не опубликован
    # (фильтрацию "кто что видит" сделаем в шаблоне)
    past_events = Event.objects.filter(is_completed=True).order_by('-end_time')
    
    return render(request, 'events/event_list.html', {
        'upcoming_events': upcoming_events,
        'past_events': past_events
    })
@login_required
def event_detail_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    is_participant = request.user in event.participants.all()
    can_manage = can_manage_event(request.user, event)
    return render(request, 'events/event_detail.html', {'event': event, 'is_participant': is_participant, 'can_manage': can_manage})

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
    if not can_manage_event(request.user, event): return redirect('event_detail', pk=pk)

    if request.method == 'POST':
        report_form = EventReportForm(request.POST, instance=event)
        video_form = EventVideoForm(request.POST)
        hero_form = EventHeroForm(request.POST)
        
        log_details = []

        if report_form.is_valid():
            report_form.save()
            photos = request.FILES.getlist('photos')
            if photos:
                for photo in photos:
                    EventPhoto.objects.create(event=event, image=photo)
                log_details.append(f"добавил {len(photos)} фото")
            
            if video_form.is_valid() and video_form.cleaned_data['video_url']:
                v = video_form.save(commit=False)
                v.event = event
                v.save()
                log_details.append("добавил видео")
                
            if hero_form.is_valid() and hero_form.cleaned_data['user']:
                h = hero_form.save(commit=False)
                h.event = event
                h.save()
                log_details.append(f"отметил героя {h.user.get_full_name()}")

            if log_details:
                log_event_action(request.user, f"Обновил отчет '{event.title}': {', '.join(log_details)}")

            messages.success(request, "Отчет сохранен.")
            return redirect('event_report_edit', pk=pk)
    else:
        report_form = EventReportForm(instance=event)
        video_form = EventVideoForm()
        hero_form = EventHeroForm()
        
    return render(request, 'events/event_report_edit.html', {
        'event': event, 'report_form': report_form, 
        'video_form': video_form, 'hero_form': hero_form
    })

@login_required
def event_join_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not event.is_completed:
        if request.user in event.participants.all():
            event.participants.remove(request.user)
            messages.info(request, "Вы отменили запись.")
        else:
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