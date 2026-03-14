from django import forms
from .models import Event, EventVideo, EventHero
from users.models import User

# Виджет для множественной загрузки
class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True

class MultipleFileField(forms.FileField):
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
            self.fields['user'].queryset = User.objects.filter(is_approved=True).exclude(is_superuser=True).order_by('last_name', 'first_name')
