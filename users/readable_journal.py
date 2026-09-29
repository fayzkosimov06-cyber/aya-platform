from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.urls import resolve, Resolver404
from django.utils import timezone
from datetime import date, timedelta
from .models import JournalEntry, User
from .permissions import allowed
from .journal import PRIVATE

ROUTES={'public_profile':'Профиль','my_profile':'Свой профиль','profile_edit':'Редактирование профиля','event_detail':'Мероприятие','event_edit':'Редактор мероприятия','school_detail':'Школа','school_edit':'Редактор школы','direction_detail':'Направление','direction_edit':'Редактор направления','club_detail':'Клуб','club_edit':'Редактор клуба','home':'Главная','volunteer_list':'Волонтёры','event_list':'Мероприятия','unit_catalog':'Направления','school_catalog':'Школы','club_catalog':'Клубы','volunteer_rating':'Рейтинг','user_management':'Управление людьми','moderator_dashboard':'Кандидаты и визиты','training_progress':'Обучение','training_help':'Помощь','login':'Вход','logout':'Выход','staff_signup':'Регистрация сотрудника','staff_applications':'Заявки сотрудников','points_quick':'Начисление баллов','points_work':'Работа и баллы','rights_manage':'Полномочия'}
MODELS={'events.EventVideo':'Видео мероприятия','users.AboutPage':'Страница О нас','users.User':'Профиль','users.Direction':'Направление','users.School':'Школа','users.Club':'Клуб','users.SchoolLesson':'Занятие','users.ClubMeeting':'Встреча клуба','users.SchoolTeacher':'Учитель','users.ContributionWork':'Работа','users.ContributionAward':'Начисление баллов','users.PermissionOverride':'Полномочия','users.StaffApplication':'Заявка сотрудника','users.TourProgress':'Обучение','events.Event':'Мероприятие','events.EventAttendance':'Присутствие','users.VolunteerVisit':'Вступительный визит'}
FIELDS={'memberships':'Состав','status':'Статус','method':'Запрос','action':'Действие','path':'Страница','filters':'Условия поиска','results':'Найдено','error':'Ошибка','pk':'Запись','id':'Запись','username':'Логин','first_name':'Имя','last_name':'Фамилия','role':'Роль','is_approved':'Полный доступ','candidate_approved':'Кандидат принят','date_joined':'На сайте с','is_active':'Аккаунт активен','points':'Баллы','revoked':'Начисление отменено','created_at':'Дата создания','updated_at':'Дата изменения','query':'Поиск','q':'Поиск','title':'Название','name':'Название','member':'Участник','user':'Пользователь','organizer':'Организатор','created_by':'Автор','marked_by':'Отметил','confirmed_by':'Подтвердил','reviewer':'Рассмотрел','before':'Было','after':'Стало','description':'Описание','comment':'Комментарий','note':'Комментарий','enabled':'Разрешено','scope':'Область доступа','code':'Разрешение','cancelled':'Отменено','is_completed':'Завершено','is_public_for_guests':'Доступно гостям','volunteer_access':'Доступ волонтёра','new_volunteer_until':'Статус нового до','school':'Школа','direction':'Направление','club':'Клуб','event':'Мероприятие','work':'Работа','topic':'Тема','starts_at':'Начало','ends_at':'Окончание','visit_date':'Дата визита'}
FIELDS.update({'result':'Результат','target_name':'К кому / к чему относится','target_type':'Раздел','network':'Контакт','birth_date':'Дата рождения','event_key':'Уведомление','is_read':'Прочитано','selected':'Выбранные','tab':'Вкладка','subject':'Объект','label':'Название'})
ROUTES.update({'event_join':'Запись на мероприятие','event_finish':'Завершение мероприятия','event_report_edit':'Отчёт мероприятия','event_export':'Выгрузка участников','event_delete':'Удаление мероприятия','event_photo_delete':'Удаление фотографии','proposal_list':'Заявки на баллы','proposal_review':'Рассмотрение заявки','points_correct':'Корректировка баллов','points_kinds':'Правила баллов','points_works':'Работы и начисления','user_delete':'Удаление аккаунта','work_delete':'Удаление работы','mark_candidate_visit':'Отметка визита','delete_candidate_visit':'Удаление визита','grant_volunteer_access':'Открытие доступа волонтёру','approve_user':'Одобрение кандидата','reject_user':'Отклонение кандидата','mark_notification_as_read':'Чтение уведомления','mark_all_notifications_as_read':'Чтение всех уведомлений','admin_password_change':'Смена пароля','activity_period_edit':'Период активности','activity_periods_manage':'Периоды активности','activity_period_delete':'Удаление периода активности','update_user_role':'Изменение роли','toggle_active_volunteer':'Звание активного волонтёра','home_manage':'Редактор главной','about_manage':'Редактор сведений об AYA','open_contact':'Контакты профиля','reveal_phone':'Контакты профиля','birthday_calendar':'Дни рождения','staff_login':'Вход сотрудника','signup':'Регистрация','notifications':'Уведомления','teacher_edit':'Карточка учителя','teacher_create':'Назначение учителя','lesson_create':'Новое занятие','lesson_edit':'Редактор занятия','club_meeting_create':'Встреча клуба','club_meeting_edit':'Встреча клуба'})
ROUTES.update({'about_page':'О нас','admin_about_manage':'Редактор сведений об AYA','about_page_edit':'Редактор сведений об AYA','rating_history':'История начислений','open_profile_photo':'Фотография профиля','reveal_birthday':'Дата рождения','audit_log':'Журнал действий','journal_private':'Закрытый журнал','journal_activity':'Просмотры и поиск'})
ROUTES['journal_cleanup']='Очистка журнала'
FIELDS.update({'deleted_count':'Удалено записей','filters':'Условия очистки'})
USER_KEYS={'user','member','actor','organizer','created_by','marked_by','confirmed_by','reviewer','author','volunteer_access_granted_by','volunteer','evaluator'}


class Display:
    def __init__(self,user):self.user=user;self.cache={}
    def label(self,model,pk):
        key=(model,str(pk))
        if key not in self.cache:
            try:
                cls=apps.get_model(model);obj=cls.objects.filter(pk=pk).first() if str(pk).isdigit() else None
                if isinstance(obj,User):value='Скрытый аккаунт' if obj.is_superuser and not self.user.is_superuser else str(obj)
                else:value=str(obj) if obj else 'Удалённая запись'
            except (LookupError,ValueError,TypeError):value='Запись'
            self.cache[key]=value
        return self.cache[key]
    def value(self,key,value):
        key=key.removesuffix('_id')
        if value is None or value=='':return '—'
        if not allowed(self.user,'contacts') and key in PRIVATE:return 'Значение скрыто'
        if isinstance(value,dict):return '; '.join(f'{FIELDS.get(k.removesuffix("_id"),k.removesuffix("_id"))}: {self.value(k,v)}' for k,v in value.items() if not k.startswith('_') and k!='id')
        if isinstance(value,list):return '\n'.join(self.value(key,v) for v in value) or 'Нет'
        if key in USER_KEYS:return self.label('users.User',value) if str(value).isdigit() else str(value)
        if key in {'school','direction','club','event','work'} and str(value).isdigit():return self.label({'school':'users.School','direction':'users.Direction','club':'users.Club','event':'events.Event','work':'users.ContributionWork'}[key],value)
        if key=='network':return {'telegram':'Telegram','instagram':'Instagram','linkedin':'LinkedIn','phone':'Телефон','birthday':'Дата рождения','photo':'Фотография'}.get(value,value)
        if key=='target_type':return MODELS.get(value,value)
        if key=='status' and str(value).isdigit():return {'200':'Успешно','302':'Переход выполнен','403':'Недостаточно прав','404':'Не найдено / недоступно','500':'Ошибка сервера'}.get(str(value),str(value))
        if key=='role':return dict(User.ROLE_CHOICES).get(value,value)
        if key=='scope':return {'all':'Все команды','own':'Свои команды','selected':'Выбранные команды'}.get(value,value)
        if key=='code':
            from .permissions import CAPABILITIES
            return CAPABILITIES.get(value,value)
        if value is True or value=='True':return 'Да'
        if value is False or value=='False':return 'Нет'
        return str(value)
    def entry(self,entry):
        section=entry.section;target='';model=None
        if section in MODELS:
            model=section
            if entry.object_id:target=self.label(section,entry.object_id)
            if target=='Удалённая запись':target=entry.before.get('title') or entry.before.get('name') or 'Удалённая запись'
        elif entry.after.get('path'):
            try:
                match=resolve(entry.after['path']);section=match.url_name
                model=('events.Event' if section.startswith('event_') else 'users.School' if section.startswith('school_') else 'users.Direction' if section.startswith('direction_') else 'users.Club' if section.startswith('club_') else 'users.User' if section=='public_profile' else None)
                if model and match.kwargs.get('pk'):target=self.label(model,match.kwargs['pk'])
            except Resolver404:pass
        target=entry.after.get('target_name') or target
        if entry.section=='public_profile' and entry.object_id and not target:target=self.label('users.User',entry.object_id)
        section_label=MODELS.get(section,ROUTES.get(section,'Действие на сайте'))
        verb={'view':'Открыл','search':'Выполнил поиск','failure':'Ошибка или отказ','action':'Выполнил действие','deletion':'Удалил'}.get(entry.category,entry.action)
        if entry.category=='contact':verb=entry.action;section_label=self.value('network',entry.after.get('network'))
        if entry.category=='action' and entry.action not in {'Выполнено действие','Действие'}:verb=entry.action
        if verb.startswith('Изменён состав:'):
            relation=verb.split(':',1)[1].strip()
            description='ответственные' if relation=='club_leaders' else 'учителя' if relation=='user_school_leader_of' else 'руководители' if relation=='direction_leaders' else 'активная команда' if 'featured' in relation else 'мероприятия' if 'events' in relation else 'участники'
            verb='Изменены '+description
        entry.readable_title=f'{verb} · {section_label}'+(f' «{target}»' if target else '')
        entry.actor_name=str(entry.actor) if entry.actor else (entry.after.get('_actor_name') or ('Гость' if entry.category in {'view','search','contact'} else 'Система / аккаунт удалён'))
        fields={}
        if model:
            try:fields={f.name:str(f.verbose_name) for f in apps.get_model(model)._meta.fields}
            except LookupError:pass
        entry.differences=[]
        for key in sorted(set(entry.before)|set(entry.after)):
            if key in {'id','path','method','target_name','target_type'} or key.startswith('_'):continue
            a=entry.before.get(key);b=entry.after.get(key)
            if key=='memberships' and isinstance(a,list) and isinstance(b,list):
                removed=[row for row in a if row not in b];added=[row for row in b if row not in a]
                if removed:entry.differences.append(('Убраны',self.value(key,removed),'—'))
                if added:entry.differences.append(('Добавлены','—',self.value(key,added)))
                continue
            if a!=b:entry.differences.append((FIELDS.get(key,fields.get(key,key)),self.value(key,a),self.value(key,b)))
        entry.change_preview='; '.join(f'{field}: {before} → {after}' for field,before,after in entry.differences[:3]) if entry.category=='change' else ''
        entry.is_observation=entry.category in {'view','search','contact','failure','action'}
        entry.readable_details=[(field,after) for field,before,after in entry.differences if after!='—']
        return entry


def filtered_journal(request,mode):
    qs=JournalEntry.objects.select_related('actor')
    if mode=='activity':qs=qs.filter(category__in=['view','search','contact'])
    elif mode=='public':qs=qs.filter(private=False).exclude(actor__is_superuser=True).exclude(category__in=['view','search','contact'])
    q=request.GET.get('q','').strip()[:200]
    if q:
        search=Q(action__icontains=q)|Q(actor__first_name__icontains=q)|Q(actor__last_name__icontains=q)|Q(actor__username__icontains=q)|Q(after__target_name__icontains=q)
        if allowed(request.user,'contacts'):search|=Q(before__icontains=q)|Q(after__icontains=q)
        qs=qs.filter(search)
    if request.GET.get('section'):qs=qs.filter(section=request.GET['section'][:200])
    category=request.GET.get('category','')
    if category in {'change','action','failure','view','search','deletion','contact'}:qs=qs.filter(category=category)
    for key,lookup in [('start','created_at__date__gte'),('end','created_at__date__lte')]:
        try:d=date.fromisoformat(request.GET.get(key,''))
        except ValueError:continue
        qs=qs.filter(**{lookup:d})
    actor=request.GET.get('actor','')
    if actor=='none':qs=qs.filter(actor__isnull=True)
    elif actor.isdigit():qs=qs.filter(actor_id=actor)
    return qs


def grouped_queryset(qs):
    from django.db.models import Value, CharField
    from django.db.models.functions import Coalesce,NullIf,Concat,Cast,TruncDate
    return qs.annotate(subject=Coalesce(NullIf('subject_key',Value('')),Concat(Value('entry:'),Cast('pk',CharField()))),who=Coalesce(NullIf('actor_key',Value('')),Concat(Value('legacy:'),Cast('pk',CharField()))),day=TruncDate('created_at'))


@login_required
def journal(request,mode='public'):
    from django.core import signing
    from django.http import Http404
    from django.db.models import Min
    if mode!='public' and not request.user.is_superuser:return HttpResponseForbidden('Недоступно.')
    if mode=='public' and not allowed(request.user,'audit'):return HttpResponseForbidden('Нет доступа к журналу.')
    qs=filtered_journal(request,mode)
    until=request.GET.get('until','')
    until=int(until) if until.isdigit() else (qs.aggregate(n=Max('pk'))['n'] or 0)
    qs=qs.filter(pk__lte=until);display=Display(request.user)
    context={'sections':[(value,MODELS.get(value,ROUTES.get(value,'Другие действия'))) for value in JournalEntry.objects.order_by('section').values_list('section',flat=True).distinct()], 'mode':mode,'q':request.GET.get('q',''),'filters':request.GET,'total':qs.count(),'until':until}
    if request.GET.get('bundle'):
        try:
            who,subject,day=signing.loads(request.GET['bundle'],salt='journal-group')
            day=date.fromisoformat(day)
        except (signing.BadSignature,ValueError,TypeError):raise Http404
        items=grouped_queryset(qs).filter(who=who,subject=subject,day=day).order_by('-created_at','-pk')
        entries=Paginator(items,40).get_page(request.GET.get('detail_page'))
        for entry in entries:display.entry(entry)
        return render(request,'users/journal_bundle_items.html',{**context,'entries':entries,'bundle':request.GET['bundle']})
    actor=request.GET.get('actor','')
    view=request.GET.get('view','people' if not actor else 'groups')
    if view not in {'people','groups','timeline'}:view='groups'
    if actor and view=='people':view='groups'
    context['view']=view;context['grouped']=view=='people'
    if actor.isdigit():context['actor_person']=User.objects.filter(pk=actor).first()
    if view=='people':
        groups=qs.order_by().values('actor_id','actor__first_name','actor__last_name','actor__username').annotate(count=Count('pk'),last=Max('created_at')).order_by('-last','actor_id')
        context['groups']=Paginator(groups,24).get_page(request.GET.get('page'))
    elif view=='timeline':
        entries=Paginator(qs.order_by('-created_at','-pk'),30).get_page(request.GET.get('page'))
        for entry in entries:display.entry(entry)
        context['entries']=entries
    else:
        base=grouped_queryset(qs)
        groups=base.order_by().values('who','subject','day').annotate(count=Count('pk'),first=Min('created_at'),last=Max('created_at'),last_id=Max('pk')).order_by('-last','-last_id')
        page=Paginator(groups,20).get_page(request.GET.get('page'))
        latest={e.pk:e for e in qs.filter(pk__in=[g['last_id'] for g in page])}
        for group in page:
            entry=latest[group['last_id']];display.entry(entry)
            group['actor_name']=entry.actor_name
            group['token']=signing.dumps([group['who'],group['subject'],group['day'].isoformat()],salt='journal-group')
            key=group['subject'];model,sep,pk=key.rpartition(':')
            group['title']=entry.readable_title;group['url']=''
            if model in MODELS and pk.isdigit():
                label=display.label(model,pk)
                if label=='Удалённая запись':label=entry.after.get('target_name') or entry.before.get('name') or entry.before.get('title') or label
                group['title']=MODELS[model]+' · '+label
                routes={'users.User':'public_profile','events.Event':'event_detail','users.School':'school_detail','users.Direction':'direction_detail','users.Club':'club_detail'}
                if model in routes and label not in {'Удалённая запись','Скрытый аккаунт'}:
                    from django.urls import reverse
                    group['url']=reverse(routes[model],args=[pk])
            elif key.startswith('section:'):group['title']=ROUTES.get(key.split(':')[1],entry.readable_title)
            subset=base.filter(who=group['who'],subject=key,day=group['day'])
            counters=subset.order_by().values('category','after__network').annotate(n=Count('pk'))
            names={'view':'Просмотры','contact':'Контакты','search':'Поиск','change':'Изменения','deletion':'Удаления','failure':'Ошибки','action':'Действия'}
            group['counts']=[{'label':display.value('network',c['after__network']) if c['category']=='contact' and c['after__network'] else names.get(c['category'],'Действия'),'count':c['n'],'important':c['category'] in {'deletion','change','failure'}} for c in counters]
            group['important']=subset.filter(Q(category='deletion')|Q(action__icontains='Удал')|Q(section__in=['users.ContributionAward','users.PermissionOverride'])|Q(after__role__isnull=False)).exists()
        context['bundles']=page
    template='users/journal_page_items.html' if request.GET.get('partial')=='1' else 'users/journal_readable.html'
    return render(request,template,context)
