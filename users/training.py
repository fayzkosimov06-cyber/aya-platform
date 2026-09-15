"""Small, versioned tours. URLs and eligibility stay on the server."""
import json
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .access import has_full_volunteer_access, is_candidate_user
from .models import TourProgress, User, Direction, School

VERSION = 1


def full_access(user):
    return has_full_volunteer_access(user) and not is_candidate_user(user)


def step(route, target, title, text, *, pk=None, fallback=''):
    return {'url': reverse(route, args=[pk] if pk else None), 'target': target,
            'title': title, 'text': text, 'fallback': fallback}


def topics_for(user):
    profile = [
        step('profile_edit', 'profile-info', 'Расскажите о себе', 'Добавьте фотографию и проверьте ФИО: так участникам будет проще вас узнать.'),
        step('profile_edit', 'profile-study', 'Учебные сведения', 'Выберите факультет и курс от 1 до 6, укажите группу. Поддерживайте эти сведения актуальными.'),
        step('profile_edit', 'profile-privacy', 'Видимость контактов', 'Рядом с каждым контактом выберите, кому он доступен. У телефона, социальных сетей и сведений о себе отдельные настройки.'),
        step('profile_edit', 'profile-save', 'Сохраните после обучения', 'Закончив обучение, внесите изменения и нажмите «Сохранить». Сейчас форма не отправляется.'),
    ]
    topics = {'profile': {'title': 'Профиль и приватность', 'description': 'Фотография, учёба и видимость контактов.', 'steps': profile}}
    if not full_access(user):
        return topics
    main = [
        step('home', 'nav-home', 'Добро пожаловать в AYA', 'Основные разделы находятся в меню сверху. На телефоне меню раскрывается кнопкой с тремя полосками.'),
        step('home', 'account', 'Ваш аккаунт', 'Нажмите на своё имя, чтобы открыть профиль, редактирование и помощь. Подробные темы можно пройти отдельно.'),
        step('home', 'nav-events', 'Участвуйте в мероприятиях', 'Здесь можно найти событие, проверить время и место и открыть его карточку для записи.'),
        step('home', 'nav-volunteers', 'Знакомьтесь с командой', 'Ищите волонтёров по имени и учебным сведениям. Из списка можно открыть профиль участника.'),
        step('home', 'nav-directions', 'Направления и школы', 'Найдите интересное направление или школу. У них есть отдельные страницы с командой и занятиями.'),
        step('home', 'nav-rating', 'Ваш вклад виден', 'Рейтинг показывает подтверждённые баллы за выбранный период. Помощь учитывается и вне мероприятий.'),
        step('home', 'nav-notifications', 'Уведомления', 'Колокольчик показывает новые сообщения. Просмотреть их можно после обучения.'),
        step('training_help', 'help-topics', 'Продолжайте в удобном темпе', 'Здесь можно продолжить отложенную тему или повторить знакомство. Помощь всегда доступна в меню аккаунта.'),
    ]
    from events.models import Event
    from django.utils import timezone
    event = Event.objects.filter(is_approved=True, is_completed=False, cancelled=False,
                                 end_time__gte=timezone.now()).order_by('start_time', 'pk').first()
    events = [step('event_list', 'event-search', 'Найдите мероприятие', 'Поиск помогает найти событие по названию или месту. В списке есть предстоящие и прошедшие мероприятия.')]
    route, pk = ('event_detail', event.pk) if event else ('event_list', None)
    events += [
        step(route, 'event-info', 'Сначала проверьте подробности', 'В карточке указаны время, место и описание. Убедитесь, что сможете прийти.', pk=pk,
             fallback='Сейчас нет подходящего предстоящего мероприятия. Когда оно появится, откройте карточку и проверьте время, место и описание.'),
        step(route, 'event-join', 'Запись и отмена', '«Присоединиться» записывает вас на событие. После записи здесь появляется «Отменить запись». Если планы изменились, отмените участие заранее. Во время обучения запись не выполняется.', pk=pk,
             fallback='Кнопки записи сейчас нет. Она появляется в карточке, когда участие доступно вашему аккаунту. Обучение никого не записывает.'),
        step(route, 'event-info', 'Если план участников превышен', 'При превышении планового числа участников сайт предупреждает об этом. Внимательно прочитайте сообщение при самостоятельной записи.', pk=pk,
             fallback='При записи на будущее мероприятие обращайте внимание на предупреждение о превышении планового числа участников.'),
    ]
    topics = {'main': {'title': 'Знакомство с AYA', 'description': 'Короткий обзор основных разделов.', 'steps': main}, **topics,
              'events': {'title': 'Мероприятия и запись', 'description': 'Как найти событие и управлять своей записью.', 'steps': events},
              'volunteers': {'title': 'Волонтёры', 'description': 'Поиск людей и знакомство с командой.', 'steps': [
                  step('volunteer_list', 'volunteer-search', 'Поиск и фильтры', 'Используйте имя, факультет, курс и другие доступные фильтры. Если результатов нет, попробуйте убрать часть условий.'),
                  step('volunteer_list', 'volunteer-card', 'Профиль участника', 'Откройте карточку человека, чтобы узнать о нём больше. Видимость контактов зависит от его настроек приватности.', fallback='В списке пока нет участников. Когда они появятся, можно будет открыть их профили.') ]},
              'rating': {'title': 'Рейтинг и результаты', 'description': 'Периоды, учебный год и история вклада.', 'steps': [
                  step('volunteer_rating', 'rating-period', 'Выберите период', 'Сравните результаты за неделю, месяц, учебный год или всё время. Учебный год начинается 1 сентября.'),
                  step('volunteer_rating', 'rating-results', 'Прошлые результаты сохраняются', 'Переключение периода не удаляет баллы. Выберите прошлый учебный год, чтобы посмотреть историю. Если начислений за период нет, список будет пустым.') ]},
              'notifications': {'title': 'Уведомления', 'description': 'Где искать сообщения сайта.', 'steps': [
                  step('home', 'nav-notifications', 'Следите за сообщениями', 'Число рядом с колокольчиком — непрочитанные уведомления. Откройте их самостоятельно после обучения: переход по сообщению может отметить его прочитанным.') ]}}
    for key, model, catalog, detail, title, explanation in [
        ('directions', Direction, 'unit_catalog', 'direction_detail', 'Направления', 'В направлении можно узнать о его работе, руководителях, составе команды и связанных школах.'),
        ('schools', School, 'school_catalog', 'school_detail', 'Школы', 'Школа может относиться к направлению или быть самостоятельной. В каталоге есть фильтр активности.')]:
        obj = (model.objects.filter(active=True) if key == 'schools' else model.objects.all()).order_by('name', 'pk').first()
        r, ident = (detail, obj.pk) if obj else (catalog, None)
        steps = [step(catalog, 'unit-search', title, explanation),
                 step(r, 'unit-overview', 'Страница команды', 'Здесь находятся описание и сведения о команде. Состав, учителя и руководители появляются по мере заполнения страницы.', pk=ident, fallback='В каталоге пока нет подходящей команды. Вернитесь к теме, когда появится направление или школа.')]
        if key == 'schools':
            steps.append(step(r, 'school-schedule', 'Расписание занятий', 'Проверьте дату, время, место и учителя ближайшего занятия. Обратите внимание на отметку отмены.', pk=ident, fallback='Ближайших занятий пока нет или школа неактивна. Расписание появится после добавления занятий.'))
        else:
            steps.append(step(r, 'direction-schools', 'Связанные школы', 'Отсюда можно перейти к школам направления и выбрать интересные занятия.', pk=ident, fallback='У этого направления пока нет активных связанных школ. Самостоятельные школы можно найти в общем каталоге.'))
        topics[key] = {'title': title, 'description': explanation, 'steps': steps}
    return topics


def serialize(row):
    return {'status': row.status, 'step': row.step, 'version': row.version, 'revision': row.updated_at.isoformat()}


@login_required
@never_cache
def help_view(request):
    return render(request, 'users/training_help.html', {'training_full_access': full_access(request.user)})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def progress_view(request):
    topics = topics_for(request.user)
    if request.method == 'GET':
        states = {p.topic: serialize(p) for p in TourProgress.objects.filter(user=request.user, topic__in=topics)}
        return JsonResponse({'topics': topics, 'states': states, 'version': VERSION})
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        topic, action = data.get('topic'), data.get('action')
        if not isinstance(topic, str) or topic not in topics or action not in ['start', 'resume', 'next', 'back', 'defer'] or type(data.get('version')) is not int or data['version'] != VERSION:
            raise ValueError
    except (ValueError, TypeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Некорректная тема или действие.'}, status=400)
    with transaction.atomic():
        # Serialize updates including creation and simultaneous requests from two tabs.
        User.objects.select_for_update().get(pk=request.user.pk)
        row = TourProgress.objects.filter(user=request.user, topic=topic).first()
        revision = row.updated_at.isoformat() if row else None
        if data.get('revision') != revision:
            return JsonResponse({'error': 'Прогресс изменился в другой вкладке. Откройте тему заново.'}, status=409)
        if row is None:
            if action not in ['start', 'defer']:
                return JsonResponse({'error': 'Сначала начните тему.'}, status=400)
            row = TourProgress(user=request.user, topic=topic)
        count = len(topics[topic]['steps'])
        row.step = min(row.step, count - 1)
        if action == 'start':
            row.status, row.step, row.version = 'in_progress', 0, VERSION
        elif action == 'resume':
            if row.status not in ['in_progress', 'deferred'] or row.version != VERSION:
                return JsonResponse({'error': 'Начните тему заново.'}, status=400)
            row.status = 'in_progress'
        elif action == 'defer':
            if row.status != 'completed':
                row.status = 'deferred'
        else:
            if row.status != 'in_progress' or row.version != VERSION:
                return JsonResponse({'error': 'Сначала продолжите тему.'}, status=400)
            if action == 'back':
                row.step = max(0, row.step - 1)
            elif row.step + 1 == count:
                row.status = 'completed'
            else:
                row.step += 1
        row.save()
    return JsonResponse({'state': serialize(row), 'topic': topics[topic]})
