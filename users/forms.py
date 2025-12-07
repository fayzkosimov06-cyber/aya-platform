# users/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, AboutPage

class UserRegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=True, label="Имя", widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ваше имя'}))
    last_name = forms.CharField(max_length=150, required=True, label="Фамилия", widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ваша фамилия'}))
    email = forms.EmailField(required=True, label="Электронная почта", widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}))

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Придумайте логин'}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data.get('first_name')
        user.last_name = self.cleaned_data.get('last_name')
        user.email = self.cleaned_data.get('email')
        if commit:
            user.save()
        return user

class UserUpdateForm(forms.ModelForm):
    """
    Форма для ВОЛОНТЕРА (редактирование своего профиля).
    Включает настройки приватности.
    """
    class Meta:
        model = User
        fields = [
            'photo', 
            'first_name', 'last_name', 'patronymic', 
            'birth_date', 'gender', 'city', 
            'about_me', 'about_me_privacy', # Новое
            'faculty', 'course', 'group',
            'phone', 'phone_privacy', 
            'telegram', 'telegram_privacy',
            'instagram', 'instagram_privacy', # Новое
            'linkedin', 'linkedin_privacy',   # Новое
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'patronymic': forms.TextInput(attrs={'class': 'form-control'}),
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'about_me': forms.Textarea(attrs={'rows': 4, 'class': 'form-control', 'placeholder': 'Расскажите о себе...'}),
            'faculty': forms.TextInput(attrs={'class': 'form-control'}),
            'course': forms.NumberInput(attrs={'class': 'form-control'}),
            'group': forms.TextInput(attrs={'class': 'form-control'}),
            
            # Контакты
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+992 XX XXX XX XX'}),
            'telegram': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@username'}),
            'instagram': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@username или ссылка'}),
            'linkedin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ссылка на профиль'}),
            
            # Приватность (стилизуем как небольшие селекты)
            'phone_privacy': forms.Select(attrs={'class': 'form-select form-select-sm border-info'}),
            'telegram_privacy': forms.Select(attrs={'class': 'form-select form-select-sm border-info'}),
            'instagram_privacy': forms.Select(attrs={'class': 'form-select form-select-sm border-info'}),
            'linkedin_privacy': forms.Select(attrs={'class': 'form-select form-select-sm border-info'}),
            'about_me_privacy': forms.Select(attrs={'class': 'form-select form-select-sm border-info'}),
            
            'photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

class AdminUpdateForm(forms.ModelForm):
    """
    Форма для АДМИНА/МОДЕРАТОРА.
    Видит всё, но НЕ трогает настройки приватности пользователя.
    """
    class Meta:
        model = User
        fields = [
            'photo', 'username', 'email', 'role', # Админ может менять роль и email
            'first_name', 'last_name', 'patronymic', 
            'birth_date', 'gender', 'city', 'about_me',
            'faculty', 'course', 'group',
            'job_title', 'office_location',
            'phone', 'telegram', 'instagram', 'linkedin',
            'is_active_volunteer_title'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'patronymic': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'about_me': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control'}),
            'office_location': forms.TextInput(attrs={'class': 'form-control'}),
            'faculty': forms.TextInput(attrs={'class': 'form-control'}),
            'course': forms.NumberInput(attrs={'class': 'form-control'}),
            'group': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'telegram': forms.TextInput(attrs={'class': 'form-control'}),
            'instagram': forms.TextInput(attrs={'class': 'form-control'}),
            'linkedin': forms.TextInput(attrs={'class': 'form-control'}),
            'photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

class AboutPageForm(forms.ModelForm):
    class Meta:
        model = AboutPage
        fields = '__all__'
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'video_url': forms.URLInput(attrs={'class': 'form-control'}),
            'mission_title': forms.TextInput(attrs={'class': 'form-control'}),
            'mission_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'stat_1_num': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_1_text': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_2_num': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_2_text': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_3_num': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_3_text': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'instagram': forms.TextInput(attrs={'class': 'form-control'}),
            'telegram': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }