from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.db import models, transaction
from django.http import Http404
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Event, EventPhoto, EventVideo, EventHero, EventEvaluation
from .forms import EventCreateForm, EventReportForm, EventVideoForm, EventHeroForm
from users.models import AuditLog
from users.access import can_manage_event, can_create_event, can_manage_members, can_register_for_events, can_see_event_catalog, has_full_volunteer_access, is_candidate_user

# --- Логирование ("Призрак") ---
def log_event_action(user, action_text):
    if not user.is_superuser:
        AuditLog.objects.create(actor=user, action=action_text)

# --- Права ---
def can_evaluate_volunteers(user):
    """Кто может оценивать волонтёров после мероприятия."""
    return can_manage_members(user)

def can_create_instantly(user):
    return can_manage_members(user)

# events/views.py

def event_list_view(request):
    q = (request.GET.get('q') or '').strip()

    if request.user.is_authenticated and not can_see_event_catalog(request.user):
        return render(request, 'events/event_list.html', {
            'upcoming_events': Event.objects.none(),
            'past_events': Event.objects.none(),
            'catalog_locked': True,
        })

    upcoming_events = Event.objects.filter(is_approved=True, is_completed=False).order_by('start_time')
    past_events = Event.objects.filter(is_completed=True, is_approved=True).order_by('-end_time')

    if not request.user.is_authenticated:
        upcoming_events = upcoming_events.filter(is_public_for_guests=True)
        past_events = past_events.filter(is_public_for_guests=True)

    if q:
        upcoming_events = upcoming_events.filter(models.Q(title__icontains=q) | models.Q(location__icontains=q))
        past_events = past_events.filter(models.Q(title__icontains=q) | models.Q(location__icontains=q))

    return render(request, 'events/event_list.html', {
        'upcoming_events': upcoming_events,
        'past_events': past_events,
        'catalog_locked': False,
        'can_create_event': can_create_event(request.user),
    })

def event_detail_view(request, pk):
    event = get_object_or_404(Event, pk=pk)
    is_participant = request.user.is_authenticated and event.participants.filter(pk=request.user.pk).exists()
    can_manage = can_manage_event(request.user, event)
    if not can_manage and (not event.is_approved or (not request.user.is_authenticated and not event.is_public_for_guests)):
        raise Http404
    can_register = can_register_for_events(request.user)
    can_view_participants = has_full_volunteer_access(request.user) or can_manage
    return render(request, 'events/event_detail.html', {
        'event': event,
        'is_participant': is_participant,
        'can_manage': can_manage,
        'can_register': can_register,
        'can_view_participants': can_view_participants,
        'catalog_locked': request.user.is_authenticated and is_candidate_user(request.user),
    })

@login_required
def event_create_view(request):
    if not can_create_event(request.user):
        messages.error(request, "Доступ вам закрыт. Сначала получите полный доступ волонтёра.")
        return redirect('event_list')

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
@transaction.atomic
def event_report_edit_view(request, pk):
    event = get_object_or_404(Event, pk=pk)

    if not can_manage_event(request.user, event):
        messages.error(request, "У вас нет прав редактировать отчёт этого мероприятия.")
        return redirect('event_detail', pk=event.pk)

    User = get_user_model()
    can_evaluate = can_evaluate_volunteers(request.user)

    # Если открыли страницу через ссылку "Редактировать" конкретную оценку
    editing_evaluation = None
    eval_id = request.GET.get('eval')
    if eval_id:
        editing_evaluation = get_object_or_404(EventEvaluation, pk=eval_id, event=event)
        # Редактировать можно: автор оценки, супер-админ, или "рабочие" админы
        if not (
            request.user.is_superuser
            or request.user.role in ['president', 'head_admin', 'worker']
            or editing_evaluation.evaluator_id == request.user.id
        ):
            messages.error(request, "У вас нет прав редактировать эту оценку.")
            editing_evaluation = None

    if request.method == 'POST':
        action = request.POST.get('action', '').strip()

        # --- 1) Сохранить отчёт ---
        if action == 'save_report':
            report_form = EventReportForm(request.POST, request.FILES, instance=event)
            if report_form.is_valid():
                report_form.save()
                # Новые фото (хранение в MEDIA; если место ограничено — лучше перейти на внешнее хранилище)
                for file in request.FILES.getlist('photos'):
                    EventPhoto.objects.create(event=event, image=file)

                log_event_action(request.user, f"Обновил отчёт мероприятия '{event.title}'")
                messages.success(request, "Отчёт сохранён.")
            else:
                messages.error(request, "Ошибка сохранения отчёта. Проверьте поля.")
            return redirect('event_report_edit', pk=event.pk)

        # --- 2) Добавить видео (ссылка) ---
        if action == 'add_video':
            video_form = EventVideoForm(request.POST)
            if video_form.is_valid():
                EventVideo.objects.create(event=event, video_url=video_form.cleaned_data['video_url'])
                log_event_action(request.user, f"Добавил видео в отчёт '{event.title}'")
                messages.success(request, "Видео добавлено.")
            else:
                messages.error(request, "Введите корректную ссылку на видео.")
            return redirect('event_report_edit', pk=event.pk)

        # --- 3) Назначить роль участнику (бывш. 'герой') ---
        if action == 'set_role':
            hero_form = EventHeroForm(request.POST, event=event)
            if hero_form.is_valid():
                u = hero_form.cleaned_data['user']
                role_name = (hero_form.cleaned_data['role_name'] or '').strip()
                if role_name:
                    # Чтобы можно было исправлять — обновляем роль для этого пользователя (а не создаём дубликаты)
                    EventHero.objects.update_or_create(
                        event=event,
                        user=u,
                        defaults={'role_name': role_name},
                    )
                    log_event_action(request.user, f"Назначил роль '{role_name}' для {u} в '{event.title}'")
                    messages.success(request, "Роль сохранена (можно изменять сколько угодно).")
                else:
                    messages.error(request, "Роль не должна быть пустой.")
            else:
                messages.error(request, "Ошибка: выберите участника и укажите роль.")
            return redirect('event_report_edit', pk=event.pk)

        if action == 'delete_role':
            hero_id = request.POST.get('hero_id')
            hero = get_object_or_404(EventHero, pk=hero_id, event=event)
            hero.delete()
            log_event_action(request.user, f"Удалил роль '{hero.role_name}' у {hero.user} в '{event.title}'")
            messages.success(request, "Роль удалена.")
            return redirect('event_report_edit', pk=event.pk)

        # --- 4) Оценка волонтёров ---
        if action in {'save_evaluation', 'delete_evaluation'}:
            messages.error(request, 'Оценки 1–5 перенесены в архив. Используйте раздел баллов.')
            return redirect('event_report_edit', pk=event.pk)

        # Если action неизвестен
        messages.error(request, "Неизвестное действие.")
        return redirect('event_report_edit', pk=event.pk)

    # GET
    report_form = EventReportForm(instance=event)
    video_form = EventVideoForm()
    hero_form = EventHeroForm(event=event)

    heroes = EventHero.objects.filter(event=event).select_related('user')
    evaluations = EventEvaluation.objects.filter(event=event).select_related('volunteer', 'evaluator')

    # compute points for display (sum of criteria and max possible)
    for ev in evaluations:
        crit = ev.criteria or []
        points_total = 0
        for c in crit:
            try:
                points_total += int(c.get('score', 0))
            except Exception:
                pass
        ev.points_total = points_total
        ev.points_max = 5 * len(crit)


    return render(request, 'events/event_report_edit.html', {
        'event': event,
        'report_form': report_form,
        'video_form': video_form,
        'hero_form': hero_form,
        'participants': event.participants.exclude(is_superuser=True).order_by('last_name', 'first_name'),
        'roles': heroes,
        'heroes': heroes,
        'can_evaluate': can_evaluate,
        'evaluations': evaluations,
        'editing_evaluation': editing_evaluation,
    })



@login_required
@require_POST
@transaction.atomic
def event_join_view(request, pk):
    event = get_object_or_404(Event.objects.select_for_update(), pk=pk)
    if not can_register_for_events(request.user):
        messages.error(request, "Участие откроется после полного допуска волонтёра.")
        return redirect('event_detail', pk=pk)
    if not event.is_approved or event.is_completed or event.end_time <= timezone.now():
        messages.error(request, "Запись на это мероприятие закрыта.")
        return redirect('event_detail', pk=pk)

    action = request.POST.get('action', 'join')
    if action == 'leave':
        # Preserve participants who already have a report role or evaluation.
        if event.heroes.filter(user=request.user).exists() or event.evaluations.filter(volunteer=request.user).exists():
            messages.error(request, "Отмена недоступна: ваше участие уже отмечено в отчёте. Обратитесь к организатору.")
        else:
            event.participants.remove(request.user)
            messages.info(request, "Вы отменили запись.")
    elif action == 'join':
        if event.participants.filter(pk=request.user.pk).exists():
            messages.info(request, "Вы уже записаны.")
        elif event.max_participants is not None and event.participants.count() >= event.max_participants:
            messages.error(request, "Свободных мест больше нет.")
        else:
            event.participants.add(request.user)
            messages.success(request, "Вы записаны!")
    else:
        messages.error(request, "Неизвестное действие.")
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