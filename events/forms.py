from django import forms
from .models import Event, EventVideo, EventHero
from users.models import User

# Виджет для множественной загрузки
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleFileField(forms.ImageField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_file_clean(d, initial) for d in data]
        else:
            result = single_file_clean(data, initial)
        return result

class EventCreateForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['title', 'cover_image', 'description', 'start_time', 'end_time', 'location', 'max_participants']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Напр.: Навруз, Экосубботник, Лекция'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'start_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_time': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Напр.: ТГМУ, корпус 1, аудитория 203 / Душанбе'}),
            'max_participants': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Напр.: 50'}),
            'cover_image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

class EventReportForm(forms.ModelForm):
    photos = MultipleFileField(
        label="Добавить фото (можно несколько)",
        required=False,
        widget=MultipleFileInput(attrs={'class': 'form-control', 'multiple': True})
    )
    class Meta:
        model = Event
        fields = ['report_text', 'is_report_published']
        widgets = {
            'report_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 6}),
            'is_report_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class EventVideoForm(forms.ModelForm):
    class Meta:
        model = EventVideo
        fields = ['video_url']
        widgets = {
            'video_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'YouTube/Instagram'}),
        }

class EventHeroForm(forms.ModelForm):
    user = forms.ModelChoiceField(queryset=User.objects.none(), widget=forms.Select(attrs={'class': 'form-select use-select2'}))

    class Meta:
        model = EventHero
        fields = ['user', 'role_name']
        widgets = {
            'role_name': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, event=None, **kwargs):
        super().__init__(*args, **kwargs)
        if event is not None:
            self.fields['user'].queryset = event.participants.exclude(is_superuser=True).order_by('last_name', 'first_name')
        else:
            self.fields['user'].queryset = User.objects.none()


class EventWorkspaceForm(EventCreateForm):
    directions = forms.ModelMultipleChoiceField(queryset=None, required=False, label='Направления', widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    schools = forms.ModelMultipleChoiceField(queryset=None, required=False, label='Школы', widget=forms.CheckboxSelectMultiple(attrs={'class':'member-picker'}))
    is_public_for_guests = forms.BooleanField(required=False, label='Показывать анонс гостям')
    def __init__(self,*args,user,**kwargs):
        from users.units import global_manager
        from users.permissions import allowed,setting
        from users.models import Direction,School
        from django.db.models import Q
        super().__init__(*args,**kwargs);self.user=user;self.global_access=user.is_superuser or (allowed(user,'events_edit') and ((setting(user,'events_edit').scope=='all') if setting(user,'events_edit') else user.role in {'president','worker','head_admin'}))
        self.fields['directions'].queryset=Direction.objects.filter(pk__in=[o.pk for o in Direction.objects.all() if allowed(user,'events_edit',o)])
        self.fields['schools'].queryset=School.objects.filter(pk__in=[o.pk for o in School.objects.all() if allowed(user,'events_edit',o)])
        for key in ['start_time','end_time']:self.fields[key].widget.format='%Y-%m-%dT%H:%M'
        self.fields['max_participants'].min_value=1
        self.fields['max_participants'].label='Сколько людей нужно'
        self.fields['max_participants'].help_text='Запись останется открытой сверх этого количества — с предупреждением.'
        self.fields['end_time'].required=False
        self.fields['end_time'].help_text='Если не указать, окончание будет через 2 часа после начала.'
        if self.instance.pk:
            self.initial.update(directions=self.instance.aya_directions.values_list('pk',flat=True),schools=self.instance.aya_schools.values_list('pk',flat=True),is_public_for_guests=self.instance.is_public_for_guests)
            if not self.global_access:
                self.fields.pop('directions');self.fields.pop('schools')
    def clean(self):
        from datetime import timedelta
        data=super().clean();start=data.get('start_time');end=data.get('end_time')
        if start and not end:data['end_time']=start+timedelta(hours=2)
        if start and end and end<=start:self.add_error('end_time','Окончание должно быть позже начала.')
        if not self.global_access and not self.instance.pk:
            if len(data.get('directions') or [])+len(data.get('schools') or [])!=1:raise forms.ValidationError('Выберите одно своё направление или одну школу. Совместные мероприятия создаёт президент или сотрудник.')
        if data.get('max_participants') is not None and data['max_participants']<1:self.add_error('max_participants','Укажите положительное количество.')
        return data
    def save(self,commit=True):
        event=super().save(commit=False);event.is_public_for_guests=self.cleaned_data['is_public_for_guests']
        if commit:event.save();self.save_links(event)
        return event
    def save_links(self,event):
        if 'directions' in self.fields:event.aya_directions.set(self.cleaned_data['directions'])
        if 'schools' in self.fields:event.aya_schools.set(self.cleaned_data['schools'])
