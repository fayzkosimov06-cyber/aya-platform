import csv
import json
from datetime import date
from django.views.decorators.cache import never_cache
from copy import copy
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseBadRequest, QueryDict
from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from .readable_journal import filtered_journal, Display, MODELS, ROUTES
from .journal import emit

FIELDS=('actor','start','end','category','q','section','cleanup_mode')

def selection(request, data):
    scoped=copy(request);scoped.GET=QueryDict('',mutable=True)
    scoped.GET.update(data)
    return filtered_journal(scoped, data.get('cleanup_mode') if data.get('cleanup_mode') in {'public','activity'} else 'private').exclude(section='journal_cleanup', category='deletion')

@login_required
@never_cache
def cleanup(request):
    if not request.user.is_superuser:return HttpResponseForbidden('Очистка доступна только суперадминистратору.')
    error=''
    if request.method=='POST':
        try:payload=signing.loads(request.POST.get('token',''),salt='journal-cleanup',max_age=900)
        except signing.BadSignature:return HttpResponseBadRequest('Подтверждение устарело. Откройте очистку заново.')
        if payload.get('actor')!=request.user.pk:return HttpResponseForbidden('Недействительное подтверждение.')
        data=payload['filters'];until=payload['until']
        if request.POST.get('confirm')!='yes':error='Подтвердите удаление выбранных записей.'
        else:
            with transaction.atomic():
                rows=selection(request,data).filter(pk__lte=until)
                count=rows.count()
                if count!=payload['count']:return HttpResponseBadRequest('Состав записей изменился. Откройте предварительный просмотр заново.')
                rows.delete()
                emit('deletion','journal_cleanup','Очищен журнал',after={'deleted_count':count,'filters':data},actor=request.user,private=True)
            messages.success(request,f'Удалено записей: {count}. Факт очистки сохранён.')
            return redirect('journal_private')
    else:
        data={k:request.GET.get(k,'')[:200] for k in FIELDS if request.GET.get(k)}
        try:
            for field in ('start','end'):
                if data.get(field):date.fromisoformat(data[field])
            if data.get('actor') and data['actor']!='none' and not data['actor'].isdigit():raise ValueError
            if data.get('category') and data['category'] not in {'change','action','failure','view','search','deletion','contact'}:raise ValueError
        except ValueError:return HttpResponseBadRequest('Некорректные условия. Вернитесь к фильтрам журнала.')
        until=selection(request,data).aggregate(n=Max('pk'))['n'] or 0
    rows=selection(request,data).filter(pk__lte=until)
    if request.method=='GET' and request.GET.get('export')=='csv':
        response=HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition']='attachment; filename="aya-journal.csv"'
        response['Cache-Control']='no-store, private'
        response.write('\ufeff');writer=csv.writer(response);writer.writerow(['Время','Кто','Действие','До','После'])
        display=Display(request.user)
        def safe(value):
            value=str(value)
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        for row in rows.select_related('actor').order_by('-created_at').iterator(chunk_size=500):
            display.entry(row)
            writer.writerow([safe(v) for v in [row.created_at.isoformat(),row.actor_name,row.readable_title,json.dumps(row.before,ensure_ascii=False),json.dumps(row.after,ensure_ascii=False)]])
        return response
    count=rows.count()
    token=signing.dumps({'actor':request.user.pk,'filters':data,'until':until,'count':count},salt='journal-cleanup')
    names={'actor':'Человек (ID)','start':'С даты','end':'По дату','category':'Тип','q':'Поиск','section':'Раздел','cleanup_mode':'Журнал'}
    readable=[(names[k],{'private':'Полная история','public':'Общие действия','activity':'Просмотры и поиск'}.get(v,v) if k=='cleanup_mode' else v) for k,v in data.items()]
    labels={**MODELS,**ROUTES,'view':'Просмотры','search':'Поиск','change':'Изменения','action':'Действия','failure':'Ошибки и отказы','deletion':'Удаления','contact':'Контакты','none':'Гость'}
    readable=[(k,labels.get(v,v)) for k,v in readable]
    if set(data)=={'cleanup_mode'}:readable.append(('Область','Все записи этого журнала'))
    if data.get('actor','').isdigit():
        name=Display(request.user).label('users.User',data['actor'])
        readable=[('Человек',name) if k=='Человек (ID)' else (k,v) for k,v in readable]
    return render(request,'users/journal_cleanup.html',{'count':count,'token':token,'selection':readable,'error':error})
