"""Explicit grants/denials; assignments determine rank, never the grants themselves."""
from contextvars import ContextVar
from django.db.models import Q
request_context=ContextVar('aya_request',default=None)
CAPABILITIES={
 'permissions':'Настраивать полномочия','people':'Профили, роли и составы',
 'visits':'Отмечать визиты','admissions':'Принимать кандидатов и открывать доступ',
 'events_edit':'Мероприятия: создание, редактор, участники и Excel',
 'events_publish':'Мероприятия: публикация и отмена','events_delete':'Мероприятия: удаление',
 'directions':'Управлять направлениями','schools':'Управлять школами',
 'points_propose':'Подавать заявки на баллы','points_award':'Начислять баллы',
 'points_review':'Рассматривать заявки на баллы','points_correct':'Исправлять и отменять начисления',
 'points_rules':'Редактировать правила баллов','activity':'Периоды деятельности',
 'home':'Редактировать главную','about':'Редактировать «О нас»','audit':'Общий журнал',
 'contacts':'Просматривать закрытые контакты'}
SCOPED={'events_edit','events_publish','events_delete','directions','schools','points_propose'}

def rank(user):
 if not getattr(user,'is_authenticated',False):return 0
 if user.is_superuser:return 1000
 base={'head_admin':80,'worker':80,'president':60,'moderator':50,'volunteer':10}.get(user.role,10)
 if getattr(user,'pk',None) and hasattr(user,'directions_led'):
  if user.directions_led.exists():base=max(base,50)
  if user.school_leader_of.exists() or user.schoolteacher_set.exists():base=max(base,40)
 return base

def defaults(user,code):
 if user.role in {'president','head_admin','worker'}:return True
 if code=='visits' and user.role=='moderator':return True
 if code not in {'events_edit','points_propose','directions','schools'}:return False
 if not getattr(user,'pk',None):return False
 leader=user.directions_led.exists();teacher=user.school_leader_of.exists() or user.schoolteacher_set.exists()
 return (code in {'events_edit','points_propose'} and (leader or teacher)) or (code=='directions' and leader) or (code=='schools' and (leader or teacher))

def setting(user,code):
 from .models import PermissionOverride
 req=request_context.get()
 if req and req.method=='GET':
  if not hasattr(user,'_permission_read_cache'):user._permission_read_cache={r.code:r for r in PermissionOverride.objects.filter(user=user).prefetch_related('directions','schools')}
  return user._permission_read_cache.get(code)
 return PermissionOverride.objects.filter(user=user,code=code).first()

def allowed(user,code,obj=None):
 if not getattr(user,'is_authenticated',False):return False
 if user.is_superuser:return True
 if not (user.is_approved or user.volunteer_access or user.role in {'president','worker','head_admin'}):return False
 rule=setting(user,code)
 enabled=rule.enabled if rule else (defaults(user,code) or (code in {'events_edit','events_delete'} and obj is not None and getattr(obj,'organizer_id',None)==user.pk and user.role!='moderator'))
 if not enabled:return False
 if code not in SCOPED:return True
 scope=rule.scope if rule else ('all' if user.role in {'president','worker','head_admin'} else 'own')
 if obj is None:return True
 if scope=='all':return True
 if not rule and code in {'events_edit','events_delete'} and getattr(obj,'organizer_id',None)==user.pk and user.role!='moderator':return True
 from .models import Direction,School
 dirs=set(rule.directions.values_list('pk',flat=True)) if rule and scope=='selected' else set(user.directions_led.values_list('pk',flat=True))
 schools=set(rule.schools.values_list('pk',flat=True)) if rule and scope=='selected' else set(user.school_leader_of.values_list('pk',flat=True))|set(user.schoolteacher_set.values_list('school_id',flat=True))
 if isinstance(obj,Direction):return obj.pk in dirs
 if isinstance(obj,School):return obj.pk in schools or obj.direction_id in dirs
 if hasattr(obj,'aya_directions'):
  return obj.aya_directions.filter(pk__in=dirs).exists() or obj.aya_schools.filter(Q(pk__in=schools)|Q(direction_id__in=dirs)).exists()
 return False

def can_change(actor,target):
 return actor.is_superuser or (actor.pk!=target.pk and not target.is_superuser and rank(actor)>rank(target) and allowed(actor,'permissions'))

def legacy(user,default):
 request=request_context.get()
 code=getattr(request,'aya_capability',None) if request and request.user.pk==user.pk else None
 return allowed(user,code or default,getattr(request,'aya_object',None) if code else None)
