from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree.ElementTree import Element,SubElement,tostring
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q,Count
from django.core.paginator import Paginator
from django.http import Http404,HttpResponse,HttpResponseForbidden
from django.shortcuts import render,redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from users.access import can_manage_event,can_create_event,has_full_volunteer_access,can_register_for_events,can_see_event_catalog
from users.units import global_manager,people_field
from users.points import members,can_award
from users.models import AuditLog,Notification,ContributionWork,PointProposal
from users.permissions import allowed
from .models import Event,EventAttendance,EventPhoto,EventVideo,EventHero
from .forms import EventWorkspaceForm,EventReportForm,EventVideoForm,EventHeroForm


def log(user,text):AuditLog.objects.create(actor=user,action=text)
def manage_q(user):
    return Q(organizer=user)|Q(aya_directions__leaders=user)|Q(aya_schools__teachers__member=user)|Q(aya_schools__direction__leaders=user)
def can_delete(user,event):return allowed(user,'events_delete',event)
def attach_state(event):
    event.state_label='Отменено' if event.cancelled else 'Завершено' if event.is_completed else 'Опубликовано' if event.is_approved else 'На рассмотрении' if event.submitted_for_review else 'Черновик'
    return event

def listing(request):
    locked=request.user.is_authenticated and not can_see_event_catalog(request.user)
    state=request.GET.get('state','upcoming');q=request.GET.get('q','').strip();gm=global_manager(request.user)
    events=Event.objects.select_related('organizer').prefetch_related('aya_schools','aya_directions').annotate(people_count=Count('participants',distinct=True))
    if locked:events=events.none()
    elif state=='manage':
        if not any(allowed(request.user,c) for c in ['events_edit','events_publish','events_delete']):events=events.none()
        else:events=events.filter(pk__in=[e.pk for e in events if any(allowed(request.user,c,e) for c in ['events_edit','events_publish','events_delete'])])
    else:
        events=events.filter(is_approved=True)
        if not request.user.is_authenticated:events=events.filter(is_public_for_guests=True)
        if state=='past':events=events.filter(Q(is_completed=True)|Q(end_time__lt=timezone.now()),cancelled=False)
        elif state=='cancelled':events=events.filter(cancelled=True)
        else:state='upcoming';events=events.filter(is_completed=False,cancelled=False,end_time__gte=timezone.now())
    if q:events=events.filter(Q(title__icontains=q)|Q(location__icontains=q))
    events=events.distinct().order_by('start_time' if state=='upcoming' else '-start_time')
    page=Paginator(events,12).get_page(request.GET.get('page'))
    request.aya_result_count=page.paginator.count
    for event in page:attach_state(event);event.manage_allowed=any(allowed(request.user,c,event) for c in ['events_edit','events_publish','events_delete'])
    return render(request,'events/hub.html',{'events':page,'q':q,'state':state,'catalog_locked':locked,'can_create_event':can_create_event(request.user),'global_manager':gm,'can_manage_events':any(allowed(request.user,c) for c in ['events_edit','events_publish','events_delete'])})

def detail(request,pk):
    event=attach_state(get_object_or_404(Event,pk=pk));manage=can_manage_event(request.user,event)
    if not manage and (not event.is_approved or (not request.user.is_authenticated and not event.is_public_for_guests)):raise Http404
    full=has_full_volunteer_access(request.user)
    people=event.participants.exclude(is_superuser=True).order_by('last_name','first_name','pk') if full else members().none()
    return render(request,'events/page.html',{'event':event,'can_manage':manage,'can_delete_event':can_delete(request.user,event),'can_register':can_register_for_events(request.user),'can_view_participants':full,'is_participant':request.user.is_authenticated and event.participants.filter(pk=request.user.pk).exists(),'people_count':event.participants.count(),'people':Paginator(people,24).get_page(request.GET.get('page')),'registration_open':event.is_approved and not event.cancelled and not event.is_completed and event.end_time>timezone.now()})

@login_required
@transaction.atomic
def edit(request,pk=None):
    event=get_object_or_404(Event,pk=pk) if pk else None
    if (event and not can_manage_event(request.user,event)) or (not event and not can_create_event(request.user)):
        messages.error(request,'Нет доступа к этому действию.');return redirect('event_list')
    gm=global_manager(request.user);tab=request.GET.get('tab','about') if event else 'about'
    if tab not in {'about','participants','report','points','status'}:raise Http404
    form=None
    if tab=='about':
        form=EventWorkspaceForm(request.POST if request.method=='POST' else None,request.FILES or None,instance=event,user=request.user,initial={key:[request.GET[key]] for key in ['directions','schools'] if request.GET.get(key,'').isdigit()})
        if request.method=='POST' and form.is_valid():
            obj=form.save(commit=False)
            if not event:obj.organizer=request.user
            action=request.POST.get('action','save')
            if action=='publish':
                if not allowed(request.user,'events_publish',event):return HttpResponseForbidden('Публикация недоступна.')
                obj.is_approved=True;obj.submitted_for_review=False
            elif action=='submit' and not obj.is_approved:obj.submitted_for_review=True
            obj.save();form.save_links(obj)
            log(request.user,f'Сохранено мероприятие #{obj.pk}: {obj.title}')
            messages.success(request,'Мероприятие сохранено.' if obj.is_approved else 'Сохранено. Опубликовать сможет президент или сотрудник отдела.')
            return redirect('event_edit',pk=obj.pk)
    elif tab=='participants':return participants(request,event)
    elif tab=='report':return report(request,event)
    elif tab=='points':return event_points(request,event)
    elif tab=='status' and request.method=='POST':
        action=request.POST.get('action')
        if action in {'publish','unpublish'}:
            if not allowed(request.user,'events_publish',event):return HttpResponseForbidden('Публикация недоступна.')
            event.is_approved=action=='publish';event.submitted_for_review=False
        elif action=='finish':event.is_completed=True
        elif action=='reopen':event.is_completed=False
        elif action=='cancel':
            reason=request.POST.get('reason','').strip()
            if not reason:messages.error(request,'Напишите причину отмены.');return redirect(reverse('event_edit',args=[event.pk])+'?tab=status')
            event.cancelled=True;event.cancellation_reason=reason
            Notification.objects.bulk_create([Notification(recipient=m,message=f'Мероприятие «{event.title}» отменено: {reason}',link=reverse('event_detail',args=[event.pk])) for m in event.participants.all()])
        elif action=='restore':event.cancelled=False;event.cancellation_reason=''
        else:return HttpResponseForbidden('Неизвестное действие.')
        event.save();log(request.user,f'Статус мероприятия #{event.pk}: {action}');messages.success(request,'Статус обновлён.')
        return redirect(reverse('event_edit',args=[event.pk])+'?tab=status')
    return render_editor(request,event,tab,form=form)

def render_editor(request,event,tab,**context):
    return render(request,'events/editor.html',{'event':attach_state(event) if event else None,'tab':tab,'global_manager':allowed(request.user,'events_publish',event),'can_delete_event':event and can_delete(request.user,event),**context})

class PeopleAction(forms.Form):
    selected=people_field('Выберите участников')
    action=forms.ChoiceField(label='Действие',choices=[('add','Добавить в мероприятие'),('remove','Убрать из участников'),('present','Отметить присутствие'),('unmark','Снять отметку присутствия'),('role','Назначить роль в мероприятии')])
    role_name=forms.CharField(label='Роль в мероприятии',required=False,max_length=100)
    def clean_selected(self):
        if not self.cleaned_data['selected']:raise forms.ValidationError('Выберите хотя бы одного человека.')
        return self.cleaned_data['selected']
    def clean(self):
        data=super().clean()
        if data.get('action')=='role' and not data.get('role_name'):self.add_error('role_name','Напишите роль: например, фотограф или ведущий.')
        return data

def participants(request,event):
    form=PeopleAction(request.POST if request.method=='POST' else None)
    if request.method=='POST' and form.is_valid():
        chosen=form.cleaned_data['selected'];action=form.cleaned_data['action']
        if action!='add' and chosen.exclude(attending_events=event).exists():form.add_error('selected','Для этого действия выберите только записанных участников.')
        elif action=='remove' and (event.attendance.filter(member__in=chosen).exists() or event.heroes.filter(user__in=chosen).exists()):form.add_error('selected','Сначала снимите отметки присутствия и роли. История баллов сохранится.')
        else:
            if action=='add':event.participants.add(*chosen)
            elif action=='remove':event.participants.remove(*chosen)
            elif action=='present':
                for person in chosen:EventAttendance.objects.get_or_create(event=event,member=person,defaults={'marked_by':request.user})
            elif action=='unmark':event.attendance.filter(member__in=chosen).delete()
            elif action=='role':
                for person in chosen:EventHero.objects.update_or_create(event=event,user=person,defaults={'role_name':form.cleaned_data['role_name']})
            log(request.user,f'Мероприятие #{event.pk}: {action}, участники {list(chosen.values_list("pk",flat=True))}')
            messages.success(request,f'Готово. Обработано участников: {chosen.count()}.')
            return redirect(reverse('event_edit',args=[event.pk])+'?tab=participants')
    people=list(members().order_by('last_name','first_name'));registered=set(event.participants.values_list('pk',flat=True));present=set(event.attendance.values_list('member_id',flat=True))
    roles=dict(event.heroes.values_list('user_id','role_name'))
    for person in people:person.registered=person.pk in registered;person.present=person.pk in present;person.event_role=roles.get(person.pk,'')
    people.sort(key=lambda m:not m.registered)
    return render_editor(request,event,'participants',form=form,people=people,selected=request.POST.getlist('selected'),registered_count=len(registered),present_count=len(present))

def report(request,event):
    action=request.POST.get('action','save_report');form=EventReportForm(request.POST if request.method=='POST' and action=='save_report' else None,request.FILES or None,instance=event)
    video=EventVideoForm(request.POST if request.method=='POST' and action=='add_video' else None)
    if request.method=='POST':
        success=False
        if action=='save_report' and form.is_valid():
            form.save()
            for photo in request.FILES.getlist('photos'):EventPhoto.objects.create(event=event,image=photo)
            success=True
        elif action=='add_video' and video.is_valid():obj=video.save(commit=False);obj.event=event;obj.save();success=True
        elif action=='delete_video':get_object_or_404(EventVideo,pk=request.POST.get('video_id'),event=event).delete();success=True
        elif action=='set_role':
            hero=EventHeroForm(request.POST,event=event)
            if hero.is_valid():EventHero.objects.update_or_create(event=event,user=hero.cleaned_data['user'],defaults={'role_name':hero.cleaned_data['role_name']});success=True
            else:messages.error(request,'Выберите записанного участника и укажите роль.')
        elif action=='delete_role':get_object_or_404(EventHero,pk=request.POST.get('hero_id'),event=event).delete();success=True
        if success:
            log(request.user,f'Отчёт мероприятия #{event.pk}: {action}');messages.success(request,'Сохранено.')
            return redirect(reverse('event_edit',args=[event.pk])+'?tab=report')
    return render_editor(request,event,'report',form=form,video_form=video)

def event_scope(event):
    schools=list(event.aya_schools.all());directions=list(event.aya_directions.all())
    school=schools[0] if len(schools)==1 else None
    direction=school.direction if school else directions[0] if len(directions)==1 else None
    return direction,school

def event_points(request,event):
    from users.proposals import ProposalForm
    from users.points import QuickAwardForm
    import uuid
    direct=can_award(request.user)
    form=ProposalForm(request.POST if request.method=='POST' else None,initial={'title':event.title,'date':min(timezone.localdate(),timezone.localtime(event.start_time).date())})
    form.fields['volunteers'].queryset=members().filter(attending_events=event)
    if direct:
        form.fields['points']=forms.IntegerField(min_value=1,max_value=1000000,label='Баллы каждому')
        form.fields['token']=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    if request.method=='POST' and form.is_valid():
        direction,school=event_scope(event)
        if direct:
            from users.models import ContributionKind,ContributionAward,ContributionChange
            from users.points import snapshot
            work,_=ContributionWork.objects.get_or_create(event=event,defaults={'title':form.cleaned_data['title'],'date':form.cleaned_data['date'],'description':form.cleaned_data['description'],'created_by':request.user,'direction':direction,'school':school})
            kind,_=ContributionKind.objects.get_or_create(name='Участие в мероприятии',defaults={'points':1,'active':False})
            for person in form.cleaned_data['volunteers']:
                award,new=ContributionAward.objects.get_or_create(work=work,member=person,kind=kind,defaults={'points':form.cleaned_data['points'],'comment':form.cleaned_data['description'],'confirmed_by':request.user})
                if new:ContributionChange.objects.create(award=award,actor=request.user,after=snapshot(award),reason='Начисление из мероприятия')
            messages.success(request,'Баллы сохранены. Повторные начисления за то же участие пропущены.')
            return redirect('points_work',pk=work.pk)
        obj=form.save(commit=False);obj.author=request.user;obj.event=event;obj.direction=direction;obj.school=school;obj.save();form.save_m2m()
        log(request.user,f'Заявка на баллы за мероприятие #{event.pk}');messages.success(request,'Заявка отправлена.');return redirect('proposal_list')
    return render_editor(request,event,'points',form=form,direct_points=direct)

@login_required
@transaction.atomic
def delete(request,pk):
    event=get_object_or_404(Event,pk=pk)
    if not can_delete(request.user,event):return HttpResponseForbidden('Удалить может автор, президент или сотрудник отдела.')
    if request.method=='POST':
        log(request.user,f'Удалено мероприятие #{event.pk}: {event.title}');event.delete();messages.success(request,'Мероприятие удалено. Начисленные баллы сохранены.');return redirect('event_list')
    return render(request,'events/delete.html',{'event':event})

@login_required
def export(request,pk):
    event=get_object_or_404(Event,pk=pk)
    if not can_manage_event(request.user,event):return HttpResponseForbidden('Выгрузка доступна организаторам.')
    people=event.participants.exclude(is_superuser=True).order_by('last_name','first_name','pk')
    if request.GET.get('present')=='1':people=people.filter(event_attendance__event=event)
    # Inline strings prevent names beginning with '=' from being interpreted as formulas.
    ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet=Element('worksheet',xmlns=ns);views=SubElement(sheet,'sheetViews');view=SubElement(views,'sheetView',workbookViewId='0');SubElement(view,'pane',ySplit='1',topLeftCell='A2',activePane='bottomLeft',state='frozen')
    cols=SubElement(sheet,'cols')
    for i,width in enumerate([7,42,40,10,18],1):SubElement(cols,'col',min=str(i),max=str(i),width=str(width),customWidth='1')
    data=SubElement(sheet,'sheetData');rows=[['№','ФИО','Факультет','Курс','Группа']]+[[i,m.get_full_name() or m.username,m.faculty,m.course or '',m.group] for i,m in enumerate(people,1)]
    for i,values in enumerate(rows,1):
        row=SubElement(data,'row',r=str(i))
        for j,value in enumerate(values):
            c=SubElement(row,'c',r=f'{chr(65+j)}{i}',t='inlineStr');text=SubElement(SubElement(c,'is'),'t');text.text=''.join(ch for ch in str(value) if ord(ch)>=32 or ch in '\n\t\r')
    SubElement(sheet,'autoFilter',ref=f'A1:E{len(rows)}')
    out=BytesIO()
    with ZipFile(out,'w',ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Участники" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',tostring(sheet,encoding='utf-8',xml_declaration=True))
    log(request.user,f'Выгрузка участников мероприятия #{event.pk}')
    response=HttpResponse(out.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');response['Content-Disposition']=f'attachment; filename="event-{event.pk}-participants.xlsx"';return response

@login_required
@transaction.atomic
def report_route(request,pk):
    event=get_object_or_404(Event,pk=pk)
    if not can_manage_event(request.user,event):return redirect('event_detail',pk=pk)
    return report(request,event)
