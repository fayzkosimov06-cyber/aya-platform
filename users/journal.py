import re
from datetime import timedelta
from django.db.models.signals import pre_save,post_save,pre_delete,m2m_changed
from django.dispatch import receiver
from django.utils import timezone
from .permissions import request_context
SECRET=re.compile(r'password|passwd|secret|token|cookie|session|authorization|csrf|api.?key|reset|credential',re.I)
PRIVATE={'phone','telegram','instagram','linkedin','about_me','birth_date','email'}

def safe_value(key,value):
 if SECRET.search(str(key)):return '[скрыто]'
 text=str(value) if value is not None else None
 if text:
  text=re.sub(r'(?i)(password|token|secret|api[_-]?key|authorization)\s*[:=]\s*\S+',r'\1=[скрыто]',text)
  text=re.sub(r'(?i)bearer\s+\S+','Bearer [скрыто]',text)
 return text[:4000] if text else text

def snapshot(obj):
 return {f.name:safe_value(f.name,getattr(obj,f.attname,None)) for f in obj._meta.concrete_fields if not SECRET.search(f.name)}

def clean_payload(data):
 if isinstance(data,dict):return {str(k):('[скрыто]' if SECRET.search(str(k)) else clean_payload(v)) for k,v in data.items()}
 if isinstance(data,(list,tuple)):return [clean_payload(v) for v in data]
 if isinstance(data,str):return safe_value('',data)
 return data

def emit(category,section,action,before=None,after=None,object_id='',actor=None,private=None):
 from .models import JournalEntry
 req=request_context.get()
 actor=actor or (req.user if req and req.user.is_authenticated else None)
 JournalEntry.objects.create(actor=actor,private=bool(actor and actor.is_superuser) if private is None else private,category=category,section=section,action=action,before=clean_payload(before or {}),after=clean_payload(after or {}),object_id=str(object_id))

def tracked(sender):
 return sender._meta.app_label in {'users','events'} and sender.__name__ not in {'JournalEntry','AuditLog','Notification'} and not sender._meta.auto_created

@receiver(pre_save)
def before_save(sender,instance,**kwargs):
 if not tracked(sender) or not request_context.get():return
 old=sender.objects.filter(pk=instance.pk).first() if instance.pk else None
 instance._journal_before=snapshot(old) if old else {}
 req=request_context.get()
 if req and req.user.is_authenticated and req.user.is_superuser:
  for field in sender._meta.concrete_fields:
   if field.is_relation and field.null and field.name in {'confirmed_by','created_by','marked_by','reviewer','volunteer_access_granted_by'} and getattr(instance,field.attname,None)==req.user.pk:setattr(instance,field.attname,None)
 if old and sender.__name__=='User' and old.password!=instance.password:emit('change','users.User','Изменён пароль (значение не записывается)',object_id=instance.pk)
 if sender.__name__=='User' and old and old.role!=instance.role:
  instance._reset_rights=True

@receiver(post_save)
def after_save(sender,instance,created,**kwargs):
 if not tracked(sender) or not request_context.get():return
 before=getattr(instance,'_journal_before',{});after=snapshot(instance)
 if before!=after:emit('change',sender._meta.label,'Создано' if created else 'Изменено',before,after,instance.pk,private=True if getattr(instance,'is_superuser',False) else None)
 if getattr(instance,'_reset_rights',False):
  instance.permission_overrides.all().delete();instance._reset_rights=False

@receiver(pre_delete)
def deleted(sender,instance,**kwargs):
 if tracked(sender) and request_context.get():emit('change',sender._meta.label,'Удалено',snapshot(instance),{},instance.pk)

@receiver(m2m_changed)
def memberships(sender,instance,action,reverse,model,pk_set,**kwargs):
 if not request_context.get() or instance._meta.app_label not in {'users','events'}:return
 links=[f for f in sender._meta.fields if f.is_relation and f.related_model==type(instance)]
 if not links:return
 link=links[-1] if reverse and len(links)>1 else links[0]
 rows=lambda:list(sender.objects.filter(**{link.attname:instance.pk}).values())
 key='_journal_'+sender._meta.label.replace('.','_')
 if action.startswith('pre_'):setattr(instance,key,rows())
 elif action in {'post_add','post_remove','post_clear'}:
  before=getattr(instance,key,[]);after=rows()
  if before!=after:emit('change',instance._meta.label,'Изменён состав: '+sender._meta.model_name,{'memberships':before},{'memberships':after},instance.pk)
