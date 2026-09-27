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
MODELS={'users.User':'Профиль','users.Direction':'Направление','users.School':'Школа','users.Club':'Клуб','users.SchoolLesson':'Занятие','users.ClubMeeting':'Встреча клуба','users.SchoolTeacher':'Учитель','users.ContributionWork':'Работа','users.ContributionAward':'Начисление баллов','users.PermissionOverride':'Полномочия','users.StaffApplication':'Заявка сотрудника','users.TourProgress':'Обучение','events.Event':'Мероприятие','events.EventAttendance':'Присутствие','users.VolunteerVisit':'Вступительный визит'}
FIELDS={'memberships':'Состав','status':'Статус','method':'Запрос','action':'Действие','path':'Страница','filters':'Условия поиска','results':'Найдено','error':'Ошибка','pk':'Запись','id':'Запись','username':'Логин','first_name':'Имя','last_name':'Фамилия','role':'Роль','is_approved':'Полный доступ','candidate_approved':'Кандидат принят','date_joined':'На сайте с','is_active':'Аккаунт активен','points':'Баллы','revoked':'Начисление отменено','created_at':'Дата создания','updated_at':'Дата изменения','query':'Поиск','q':'Поиск','title':'Название','name':'Название','member':'Участник','user':'Пользователь','organizer':'Организатор','created_by':'Автор','marked_by':'Отметил','confirmed_by':'Подтвердил','reviewer':'Рассмотрел','before':'Было','after':'Стало','description':'Описание','comment':'Комментарий','note':'Комментарий','enabled':'Разрешено','scope':'Область доступа','code':'Разрешение','cancelled':'Отменено','is_completed':'Завершено','is_public_for_guests':'Доступно гостям','volunteer_access':'Доступ волонтёра','new_volunteer_until':'Статус нового до','school':'Школа','direction':'Направление','club':'Клуб','event':'Мероприятие','work':'Работа','topic':'Тема','starts_at':'Начало','ends_at':'Окончание','visit_date':'Дата визита'}
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
        section_label=MODELS.get(section,ROUTES.get(section,'Действие на сайте'))
        verb={'view':'Открыл','search':'Выполнил поиск','failure':'Ошибка или отказ','action':'Выполнил действие','deletion':'Удалил'}.get(entry.category,entry.action)
        if verb.startswith('Изменён состав:'):
            relation=verb.split(':',1)[1].strip()
            description='ответственные' if relation=='club_leaders' else 'учителя' if relation=='user_school_leader_of' else 'руководители' if relation=='direction_leaders' else 'активная команда' if 'featured' in relation else 'мероприятия' if 'events' in relation else 'участники'
            verb='Изменены '+description
        entry.readable_title=f'{verb} · {section_label}'+(f' «{target}»' if target else '')
        entry.actor_name=str(entry.actor) if entry.actor else ('Гость' if entry.category in {'view','search'} else 'Система / аккаунт удалён')
        fields={}
        if model:
            try:fields={f.name:str(f.verbose_name) for f in apps.get_model(model)._meta.fields}
            except LookupError:pass
        entry.differences=[]
        for key in sorted(set(entry.before)|set(entry.after)):
            if key in {'id','path','method'} or key.startswith('_'):continue
            a=entry.before.get(key);b=entry.after.get(key)
            if a!=b:entry.differences.append((FIELDS.get(key,fields.get(key,key)),self.value(key,a),self.value(key,b)))
        return entry


@login_required
def journal(request,mode='public'):
    if mode!='public' and not request.user.is_superuser:return HttpResponseForbidden('Недоступно.')
    if mode=='public' and not allowed(request.user,'audit'):return HttpResponseForbidden('Нет доступа к журналу.')
    qs=JournalEntry.objects.select_related('actor')
    if mode=='activity':qs=qs.filter(category__in=['view','search'],created_at__gte=timezone.now()-timedelta(days=90))
    elif mode=='private':qs=qs.filter(private=True).exclude(category__in=['view','search'])
    else:qs=qs.filter(private=False).exclude(actor__is_superuser=True).exclude(category__in=['view','search'])
    q=request.GET.get('q','').strip()[:200]
    if q:
        search=Q(action__icontains=q)|Q(actor__first_name__icontains=q)|Q(actor__last_name__icontains=q)|Q(actor__username__icontains=q)
        if allowed(request.user,'contacts'):
            search |= Q(before__icontains=q)|Q(after__icontains=q)
        qs=qs.filter(search)
    category=request.GET.get('category','')
    if category in {'change','action','failure','view','search','deletion'}:qs=qs.filter(category=category)
    for key,lookup in [('start','created_at__date__gte'),('end','created_at__date__lte')]:
        try:d=date.fromisoformat(request.GET.get(key,''))
        except ValueError:continue
        qs=qs.filter(**{lookup:d})
    actor=request.GET.get('actor','');grouped=request.GET.get('view','people')=='people' and not actor
    context={'mode':mode,'q':q,'filters':request.GET,'grouped':grouped,'total':qs.count()}
    if grouped:
        groups=qs.order_by().values('actor_id','actor__first_name','actor__last_name','actor__username').annotate(count=Count('pk'),last=Max('created_at')).order_by('-last')
        context['groups']=Paginator(groups,24).get_page(request.GET.get('page'))
    else:
        if actor=='none':qs=qs.filter(actor__isnull=True)
        elif actor.isdigit():qs=qs.filter(actor_id=actor)
        entries=Paginator(qs,30).get_page(request.GET.get('page'));display=Display(request.user)
        for entry in entries:display.entry(entry)
        context['entries']=entries
    return render(request,'users/journal_readable.html',context)
