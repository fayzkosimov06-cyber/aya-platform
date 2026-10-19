"""Read-only profile validation evidence, with no submitted values in output."""
from collections import Counter
from copy import copy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .forms import UserUpdateForm, AdminUpdateForm
from .models import User, JournalEntry, PermissionOverride


def validation_result(person, form_type):
    # ModelForm.is_valid() mutates its in-memory instance: give it a detached copy.
    detached=copy(person)
    initial=form_type(instance=detached)
    data={name:initial[name].value() for name in initial.fields if name!='photo' and initial[name].value() is not None}
    form=form_type(data=data,instance=detached)
    form.is_valid()
    return {'valid':not bool(form.errors), 'legacy_social_fields':sorted(form.legacy_social_fields), 'codes':{name:[error.code or 'invalid' for error in errors] for name,errors in form.errors.as_data().items()}}


def diagnose_profile(username, day='2026-09-29', start='13:26', end='13:39'):
    person=User.objects.get(username=username)
    zone=ZoneInfo('Asia/Dushanbe')
    since=datetime.fromisoformat(day+'T'+start).replace(tzinfo=zone)
    until=datetime.fromisoformat(day+'T'+end).replace(tzinfo=zone)+timedelta(minutes=1)
    if until<=since:raise ValueError('End must be after start')
    from django.conf import settings
    from django.db import connection
    events=JournalEntry.objects.filter(created_at__gte=since,created_at__lt=until).filter(actor=person).order_by('created_at','pk')
    categories=Counter();routes=Counter();timeline=[]
    for entry in events.iterator(chunk_size=200):
        categories[entry.category]+=1;routes[entry.section]+=1
        # No raw paths, queries, IPs, error messages, snapshots or submitted values.
        timeline.append({'time':entry.created_at.astimezone(zone).isoformat(),'category':entry.category,'section':entry.section,'http_status':entry.after.get('status'),'method':entry.after.get('method'),'validation_fields':list(entry.after.get('validation_codes',{}))})
    protected={'role','is_superuser','is_staff','is_active','is_approved','volunteer_access','candidate_approved','enabled','scope','code','memberships'}
    changes=JournalEntry.objects.filter(created_at__lt=until).filter(section='users.User',object_id=str(person.pk)).order_by('-created_at','-pk')
    role_history=[]
    for entry in changes[:100]:
        modified=[field for field in protected if field in entry.before or field in entry.after if entry.before.get(field)!=entry.after.get(field)]
        if modified:role_history.append({'time':entry.created_at.astimezone(zone).isoformat(),'changed_fields':sorted(modified),'within_window':entry.created_at>=since})
    choices={}
    for name in ('city','faculty','course'):
        value=getattr(person,name)
        choices[name]={'present':value not in (None,''),'listed':value in (None,'') or str(value) in {str(v) for v,label in User._meta.get_field(name).choices}}
    return {'read_only':True,'production_identity_not_assumed':True,'database_vendor':connection.vendor,'debug':settings.DEBUG,'window':{'timezone':'Asia/Dushanbe','start':since.isoformat(),'end_exclusive':until.isoformat()},'current_status':{name:getattr(person,name) for name in ('role','is_active','is_superuser','is_staff','is_approved','candidate_approved','volunteer_access')},'current_choice_checks':choices,'current_self_form':validation_result(person,UserUpdateForm),'current_admin_form':validation_result(person,AdminUpdateForm),'permission_overrides':list(PermissionOverride.objects.filter(user=person).values('code','enabled','scope')),'actor_window':{'count':sum(categories.values()),'categories':dict(categories),'sections':dict(routes),'timeline':timeline},'recent_security_field_history':role_history,'limits':['Current values may differ from the incident after Django Admin edits.','A historical action entry alone does not prove a successful save.','This does not include rotated Nginx or systemd logs.','No inference of malicious intent is made.']}
