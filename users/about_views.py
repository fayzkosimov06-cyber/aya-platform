from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseForbidden, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from urllib.parse import urlsplit
from .access import can_manage_members
from .models import AboutContactLink, AboutExtraBlock, AboutPage, AboutStatItem, AboutValueBlock
ICON_CHOICES = [
    ('fa-solid fa-star', 'Звезда'),
    ('fa-solid fa-heart', 'Сердце'),
    ('fa-solid fa-bullseye', 'Цель'),
    ('fa-solid fa-lightbulb', 'Идея'),
    ('fa-solid fa-users', 'Команда'),
    ('fa-solid fa-user-group', 'Люди'),
    ('fa-solid fa-hand-holding-heart', 'Помощь'),
    ('fa-solid fa-graduation-cap', 'Обучение'),
    ('fa-solid fa-briefcase-medical', 'Медицина'),
    ('fa-solid fa-leaf', 'Экология'),
    ('fa-solid fa-chart-line', 'Рост'),
    ('fa-solid fa-chart-column', 'Статистика'),
    ('fa-solid fa-calendar-check', 'Мероприятия'),
    ('fa-solid fa-location-dot', 'Адрес'),
    ('fa-solid fa-envelope', 'Email'),
    ('fa-solid fa-phone', 'Телефон'),
]


def can_edit_about(user):return can_manage_members(user)


class AboutForm(forms.ModelForm):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for name,field in self.fields.items():
            field.widget.attrs['class']='form-check-input' if isinstance(field,forms.BooleanField) else 'form-control'
        if 'icon' in self.fields:
            choices=list(ICON_CHOICES)
            current=getattr(self.instance,'icon','')
            if current and current not in dict(choices):choices.append((current,'Текущая иконка'))
            self.fields['icon']=forms.ChoiceField(choices=choices,label='Иконка',initial=current or choices[0][0],widget=forms.RadioSelect)


class MainForm(AboutForm):
    class Meta:
        model=AboutPage
        fields=['title','description','mission_title','mission_text','video_url','email','address']
        labels={'title':'Заголовок страницы','description':'Об ассоциации','mission_title':'Заголовок миссии','mission_text':'Текст миссии','video_url':'Ссылка на видео','email':'Электронная почта','address':'Адрес'}
        widgets={'description':forms.Textarea(attrs={'rows':4}),'mission_text':forms.Textarea(attrs={'rows':5})}
    def clean_video_url(self):
        value=self.cleaned_data['video_url']
        if value and urlsplit(value).scheme not in ['https','http']:raise forms.ValidationError('Укажите ссылку http:// или https://.')
        return value


class ValueForm(AboutForm):
    class Meta:
        model=AboutValueBlock
        fields=['title','text','icon']
        labels={'title':'Название блока','text':'Текст'}
        widgets={'text':forms.Textarea(attrs={'rows':5})}


class ExtraForm(ValueForm):
    class Meta(ValueForm.Meta):model=AboutExtraBlock


class StatForm(AboutForm):
    number=forms.CharField(max_length=30,required=False,label='Значение вручную',help_text='Например: 125 или 100+. При автоматическом подсчёте это поле не используется.')
    class Meta:
        model=AboutStatItem
        fields=['source','number','label','icon']
        labels={'label':'Подпись под числом'}
    def clean(self):
        data=super().clean()
        if data.get('source')=='manual' and not data.get('number'):self.add_error('number','Введите значение.')
        if data.get('source')!='manual':data['number']=data.get('number') or '0'
        return data


class ContactForm(AboutForm):
    class Meta:
        model=AboutContactLink
        fields=['platform','label','url','requires_volunteer_access']
        labels={'label':'Название','url':'Ссылка или контакт','requires_volunteer_access':'Только после полного доступа'}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['label'].required=False
        self.fields['url'].help_text='Ссылка, @имя, email или телефон. Иконка выбирается автоматически.'
    def clean(self):
        data=super().clean();platform=data.get('platform','custom');raw=(data.get('url') or '').strip()
        if not data.get('label'):data['label']=dict(AboutContactLink.PLATFORM_CHOICES).get(platform,'Контакт')
        if raw and ':' in raw and not raw.lower().startswith(('http://','https://','mailto:','tel:')):
            self.add_error('url','Укажите обычную ссылку, email, @имя или телефон.')
        data['requires_volunteer_access']=True if platform=='telegram' else False if platform in ['instagram','facebook'] else data.get('requires_volunteer_access',False)
        return data
    def save(self,commit=True):
        item=super().save(commit=False)
        item.icon=AboutContactLink.PLATFORM_ICONS.get(item.platform,'fa-solid fa-link')
        if commit:item.save()
        return item


SECTIONS={
    'value':(AboutValueBlock,ValueForm,'Ценности и деятельность','Добавить блок'),
    'stat':(AboutStatItem,StatForm,'AYA в цифрах','Добавить число'),
    'contact':(AboutContactLink,ContactForm,'Контакты и соцсети','Добавить контакт'),
    'extra':(AboutExtraBlock,ExtraForm,'Пространство для новых идей','Добавить блок'),
}


@login_required
@transaction.atomic
def about_manage_view(request):
    if not can_edit_about(request.user):return HttpResponseForbidden('Недостаточно прав.')
    about,_=AboutPage.objects.get_or_create(pk=1)
    kind=request.POST.get('kind') or request.GET.get('kind') or 'main'
    if kind!='main' and kind not in SECTIONS:return HttpResponseBadRequest('Неизвестный раздел.')
    model,formclass=(AboutPage,MainForm) if kind=='main' else SECTIONS[kind][:2]
    item_id=request.POST.get('id') if request.method=='POST' else request.GET.get('id')
    obj=about if kind=='main' else get_object_or_404(model,about=about,pk=item_id) if item_id else None
    form=formclass(request.POST if request.method=='POST' else None,instance=obj)
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='save':
            if form.is_valid():
                item=form.save(commit=False)
                if kind!='main':
                    item.about=about
                    if not item.pk:item.order=(model.objects.filter(about=about).aggregate(n=Max('order'))['n'] or 0)+1
                item.save();messages.success(request,'Изменения сохранены.')
                return redirect(reverse('about_manage')+'#'+kind)
        elif kind!='main' and obj and action in ['toggle','delete','up','down']:
            if action=='delete':obj.delete()
            elif action=='toggle':obj.is_active=not obj.is_active;obj.save(update_fields=['is_active'])
            else:
                records=list(model.objects.filter(about=about).select_for_update().order_by('order','id'))
                index=next(i for i,x in enumerate(records) if x.pk==obj.pk);other=index+(-1 if action=='up' else 1)
                if 0<=other<len(records):records[index],records[other]=records[other],records[index]
                for i,x in enumerate(records):x.order=i
                model.objects.bulk_update(records,['order'])
            return redirect(reverse('about_manage')+'#'+kind)
        else:return HttpResponseBadRequest('Неизвестное действие.')
    sections=[]
    for key,(model,_,title,add_label) in SECTIONS.items():
        items=list(model.objects.filter(about=about).order_by('order','id'))
        for item in items:
            item.editor_title=getattr(item,'title','') or getattr(item,'label','')
            item.editor_summary=getattr(item,'text','') or (item.number if key=='stat' and item.source=='manual' else item.get_source_display() if key=='stat' else getattr(item,'url',''))
        sections.append({'key':key,'title':title,'add_label':add_label,'items':items})
    return render(request,'users/about_manage.html',{'about':about,'sections':sections,'form':form,'kind':kind,'item':obj,'form_title':'Основная информация' if kind=='main' else SECTIONS[kind][2], 'is_editing':bool(obj)})
