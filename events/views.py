from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import Event, EventPhoto, EventVideo, EventHero, EventEvaluation
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
    if user.role in ['leader', 'head_admin', 'worker', 'moderator', 'president']: return True
    return False


def can_evaluate_volunteers(user):
    """Кто может оценивать волонтёров после мероприятия."""
    if user.is_superuser:
        return True
    return user.role in ['worker', 'head_admin', 'leader', 'president']

def can_create_instantly(user):
    return user.role in ['leader', 'president', 'worker', 'head_admin', 'moderator'] or user.is_superuser

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
            or request.user.role in ['leader', 'head_admin', 'worker']
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
            hero_form = EventHeroForm(request.POST)
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
        if action == 'save_evaluation':
            if not can_evaluate:
                messages.error(request, "У вас нет прав оценивать волонтёров.")
                return redirect('event_report_edit', pk=event.pk)

            evaluation_id = (request.POST.get('evaluation_id') or '').strip()
            volunteer_id = (request.POST.get('volunteer_id') or '').strip()

            if not volunteer_id:
                messages.error(request, "Выберите волонтёра для оценки.")
                return redirect('event_report_edit', pk=event.pk)

            volunteer = get_object_or_404(User, pk=volunteer_id)
            if volunteer not in event.participants.all():
                messages.error(request, "Этот пользователь не является участником данного мероприятия.")
                return redirect('event_report_edit', pk=event.pk)

            role_name = (request.POST.get('eval_role_name') or '').strip()
            if role_name == '__custom__':
                role_name = (request.POST.get('eval_role_custom') or '').strip()

            # Сбор критериев (можно выбирать/вводить вручную)
            names = request.POST.getlist('criteria_name')
            scores = request.POST.getlist('criteria_score')
            criteria = []
            for n, s in zip(names, scores):
                n = (n or '').strip()
                if not n:
                    continue
                try:
                    score_int = int(s)
                except (TypeError, ValueError):
                    continue
                # ограничим диапазон
                score_int = max(1, min(5, score_int))
                criteria.append({'name': n, 'score': score_int})

            comment = (request.POST.get('eval_comment') or '').strip()

            # Редактирование существующей оценки
            if evaluation_id:
                evaluation = get_object_or_404(EventEvaluation, pk=evaluation_id, event=event)
                can_edit = (
                    request.user.is_superuser
                    or request.user.role in ['leader', 'head_admin', 'worker']
                    or evaluation.evaluator_id == request.user.id
                )
                if not can_edit:
                    messages.error(request, "У вас нет прав редактировать эту оценку.")
                    return redirect('event_report_edit', pk=event.pk)

                evaluation.volunteer = volunteer
                evaluation.role_name = role_name
                evaluation.criteria = criteria
                evaluation.comment = comment
                evaluation.save()
                log_event_action(request.user, f"Обновил оценку {volunteer} в '{event.title}'")
                messages.success(request, "Оценка обновлена.")
            else:
                evaluation, _created = EventEvaluation.objects.get_or_create(
                    event=event,
                    volunteer=volunteer,
                    evaluator=request.user,
                    defaults={'role_name': role_name},
                )
                evaluation.role_name = role_name
                evaluation.criteria = criteria
                evaluation.comment = comment
                evaluation.save()
                log_event_action(request.user, f"Поставил оценку {volunteer} в '{event.title}'")
                messages.success(request, "Оценка сохранена.")

            url = reverse('event_report_edit', kwargs={'pk': event.pk})
            return redirect(f"{url}?eval={evaluation.id}#evaluation")

        if action == 'delete_evaluation':
            evaluation_id = (request.POST.get('evaluation_id') or '').strip()
            evaluation = get_object_or_404(EventEvaluation, pk=evaluation_id, event=event)

            can_delete = (
                request.user.is_superuser
                or request.user.role in ['leader', 'head_admin', 'worker']
                or evaluation.evaluator_id == request.user.id
            )
            if not can_delete:
                messages.error(request, "У вас нет прав удалить эту оценку.")
                return redirect('event_report_edit', pk=event.pk)

            evaluation.delete()
            log_event_action(request.user, f"Удалил оценку {evaluation.volunteer} в '{event.title}'")
            messages.success(request, "Оценка удалена.")
            return redirect('event_report_edit', pk=event.pk)

        # Если action неизвестен
        messages.error(request, "Неизвестное действие.")
        return redirect('event_report_edit', pk=event.pk)

    # GET
    report_form = EventReportForm(instance=event)
    video_form = EventVideoForm()
    hero_form = EventHeroForm()

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
        'participants': event.participants.all(),
        'roles': heroes,
        'heroes': heroes,
        'can_evaluate': can_evaluate,
        'evaluations': evaluations,
        'editing_evaluation': editing_evaluation,
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