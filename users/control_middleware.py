from django.http import HttpResponseForbidden,Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from .permissions import request_context,allowed,rank,setting

ROUTES={
 'user_management':'people','admin_edit_user':'people','update_user_role':'people','toggle_active_volunteer':'people',
 'moderator_dashboard':'visits','mark_candidate_visit':'visits','delete_candidate_visit':'admissions',
 'approve_user':'admissions','reject_user':'admissions','grant_volunteer_access':'admissions',
 'activity_periods_manage':'activity','activity_period_edit':'activity','activity_period_delete':'activity',
 'home_manage':'home','about_manage':'about','about_page_edit':'about',
 'points_quick':'points_award','points_work':'points_award','points_works':'points_award','points_correct':'points_correct','points_kinds':'points_rules',
 'proposal_review':'points_review','direction_suggest':'points_propose','school_suggest':'points_propose',
 'event_create':'events_edit','event_edit':'events_edit','event_export':'events_edit','event_finish':'events_publish',
 'event_report_edit':'events_edit','event_photo_delete':'events_edit','event_delete':'events_delete',
 'direction_edit':'directions','direction_create_page':'directions','direction_delete_page':'directions',
 'school_edit':'schools','school_create_page':'schools','school_delete_page':'schools','teacher_create':'schools','teacher_edit':'schools','lesson_create':'schools','lesson_edit':'schools',
 'direction_management':'directions','direction_create':'directions','direction_delete':'directions','assign_direction_leader':'directions',
 'school_management':'schools','school_create':'schools','school_delete':'schools','assign_school_leader':'schools','audit_log':'audit',
}
class ControlMiddleware:
 def __init__(self,get_response):self.get_response=get_response
 def __call__(self,request):
  from django.core.cache import cache
  if cache.add('aya_activity_cleanup',True,3600):
   from datetime import timedelta
   from .models import JournalEntry
   JournalEntry.objects.filter(category__in=['view','search'],created_at__lt=timezone.now()-timedelta(days=90)).delete()
  token=request_context.set(request)
  try:
   response=self.get_response(request)
   if not request.path.startswith(('/static/','/media/')):
    from .journal import emit,safe_value
    name=getattr(getattr(request,'resolver_match',None),'url_name','') or ''
    if name=='record_search':return response
    if response.status_code>=400:emit('failure',name,'Отказ или ошибка',after={'status':response.status_code,'method':request.method})
    elif request.method not in {'GET','HEAD','OPTIONS'}:
     import re,html
     body=response.content.decode('utf-8',errors='replace') if not response.streaming and response.get('Content-Type','').startswith('text/html') else ''
     errors=re.findall(r'<ul[^>]*class=[\"\'][^\"\']*errorlist[^\"\']*[\"\'][^>]*>(.*?)</ul>',body,re.S)
     error='; '.join(html.unescape(re.sub('<[^>]+>',' ',x)).strip() for x in errors)
     emit('failure' if errors else 'action',name,'Не сохранено: ошибка формы' if errors else 'Выполнено действие',after={'status':response.status_code,'action':safe_value('action',request.POST.get('action','сохранение')),'error':safe_value('error',error)})
    elif response.status_code==200 and name not in {'journal_private','journal_activity','audit_log','record_search'}:
     # Query text is retained only for known site search fields, never arbitrary URL credentials.
     query={k:safe_value(k,request.GET[k]) for k in ['q','query','status','state','direction','school','faculty','course','gender','city'] if k in request.GET}
     emit('search' if query else 'view',name,'Поиск' if query else 'Просмотр',after={'path':request.path,'filters':query,'results':getattr(request,'aya_result_count',None)},private=True)
   return response
  finally:request_context.reset(token)
 def process_view(self,request,view,args,kwargs):
  name=request.resolver_match.url_name
  if request.path.startswith('/superadmin/') and not request.user.is_superuser:raise Http404
  from .models import User,Direction,School,ContributionWork,ContributionAward,PointProposal
  if name in {'public_profile','admin_edit_user','activity_periods_manage','activity_period_edit','activity_period_delete','admin_password_change'} and 'pk' in kwargs:
   target=User.objects.filter(pk=kwargs['pk']).first()
   if target and target.is_superuser and not request.user.is_superuser:raise Http404
   if name not in {'public_profile','admin_password_change'} and target and request.user.is_authenticated and not request.user.is_superuser and (target.pk==request.user.pk or rank(target)>=rank(request.user)):
    return HttpResponseForbidden('Нельзя изменять равного или вышестоящего пользователя.')
  code=ROUTES.get(name)
  if request.user.is_authenticated and request.method=='GET':
   if name in {'points_work','points_works'} and not allowed(request.user,'points_award'):
    code=next((c for c in ['points_correct','points_review','points_rules'] if allowed(request.user,c)),code)
   if name=='moderator_dashboard' and not allowed(request.user,'visits') and allowed(request.user,'admissions'):code='admissions'
  if not code:return
  if not request.user.is_authenticated:return
  obj=None
  pk=kwargs.get('pk')
  if name=='event_edit':
   tab=request.GET.get('tab','about');action=request.POST.get('action','')
   if tab=='status' or action=='publish':code='events_publish'
   elif tab=='points':code='points_award' if allowed(request.user,'points_award') else 'points_propose'
  if pk and name.startswith('event_'):
   from events.models import Event,EventPhoto
   if name=='event_photo_delete':photo=EventPhoto.objects.filter(pk=pk).first();obj=photo.event if photo else None
   else:obj=Event.objects.filter(pk=pk).first()
  elif pk and name.startswith('direction_'):obj=Direction.objects.filter(pk=pk).first()
  elif pk and name.startswith(('school_','teacher_','lesson_')):obj=School.objects.filter(pk=pk).first()
  request.aya_capability=code;request.aya_object=obj
  if name=='event_edit' and request.method=='GET' and request.GET.get('tab','about')=='about' and not allowed(request.user,'events_edit',obj):
   if allowed(request.user,'events_publish',obj):return redirect(reverse('event_edit',args=[pk])+'?tab=status')
   if allowed(request.user,'events_delete',obj):return redirect('event_delete',pk=pk)
  if not allowed(request.user,code,obj):return HttpResponseForbidden('Это действие отключено или находится вне доступных команд.')
  if name in {'direction_create_page','direction_create','school_create_page','school_create'} and not request.user.is_superuser:
   rule=setting(request.user,code)
   scope=rule.scope if rule else ('all' if request.user.role in {'president','worker','head_admin'} else 'own')
   if scope!='all':return HttpResponseForbidden('Создание команды требует права на все команды.')
  if request.method=='POST' and not request.user.is_superuser:
   if name=='user_management':
    action=request.POST.get('action','')
    extra='admissions' if action in {'candidate','grant'} else 'directions' if action.startswith(('direction_','leader_')) else 'schools' if action.startswith(('school_','teacher_')) else None
    target=None
    if extra in {'directions','schools'}:
     value=request.POST.get('direction' if extra=='directions' else 'school','')
     target=(Direction if extra=='directions' else School).objects.filter(pk=value).first() if value.isdigit() else None
    if extra and not allowed(request.user,extra,target):return HttpResponseForbidden('Это массовое действие отключено.')
   if name in {'direction_edit','school_edit'} and request.GET.get('tab')=='events' and obj:
    from events.models import Event
    existing=set(obj.events.values_list('pk',flat=True));ids={int(x) for x in request.POST.getlist('events') if x.isdigit()}
    if any(not allowed(request.user,'events_edit',e) for e in Event.objects.filter(pk__in=ids-existing)):return HttpResponseForbidden('Нельзя привязать чужое недоступное мероприятие.')
   if name in {'school_edit','school_create_page'} and request.POST.get('direction','').isdigit():
    parent=Direction.objects.filter(pk=request.POST['direction']).first()
    if parent and (not obj or obj.direction_id!=parent.pk) and not allowed(request.user,'directions',parent):return HttpResponseForbidden('Недоступное родительское направление.')
   # Appointments cannot be used to elevate self, equals, or higher-ranked people.
   if name in {'direction_edit','teacher_create','teacher_edit','assign_direction_leader','assign_school_leader'}:
    ids=request.POST.getlist('leaders') if request.GET.get('tab')=='leaders' else request.POST.getlist('member') if name.startswith('teacher_') else []
    previous=set(obj.leaders.values_list('pk',flat=True)) if obj and name=='direction_edit' and request.GET.get('tab')=='leaders' else set()
    if name=='teacher_edit':
     from .models import SchoolTeacher
     current=SchoolTeacher.objects.filter(pk=kwargs.get('item_id'),school=obj).first()
     previous={current.member_id} if current and current.member_id else set()
    desired=previous if name=='teacher_edit' and 'member' not in request.POST and request.POST.get('action')!='delete' else {int(x) for x in ids if str(x).isdigit()}
    for target in User.objects.filter(pk__in=desired.symmetric_difference(previous)):
     if target.pk==request.user.pk or rank(target)>=rank(request.user) or (50 if name.startswith('direction') else 40)>=rank(request.user):return HttpResponseForbidden('Назначение равного или вышестоящего недоступно.')
   # No backdated awards, including additions to old work without a date field.
   if code in {'points_award','points_review'}:
    work=ContributionWork.objects.filter(pk=pk if name=='points_work' else request.POST.get('work') or 0).first()
    d=work.date.isoformat() if work else request.POST.get('date')
    if name=='proposal_review':
     proposal=PointProposal.objects.filter(pk=pk).first()
     if proposal:d=proposal.date.isoformat()
    if name=='event_edit' and obj:
     old_work=ContributionWork.objects.filter(event=obj).first()
     if old_work:d=old_work.date.isoformat()
    if d and d!=timezone.localdate().isoformat():return HttpResponseForbidden('Задним числом начисляет только суперадминистратор.')
   if code in {'events_edit','directions','schools','points_propose'}:
    for key,model in [('directions',Direction),('schools',School)]:
     ids=request.POST.getlist(key)
     if any(not v.isdigit() for v in ids):return HttpResponseForbidden('Некорректный состав команд.')
     if any(not allowed(request.user,code,x) for x in model.objects.filter(pk__in=ids)):
      return HttpResponseForbidden('Нельзя привязать недоступную команду.')
  return None
