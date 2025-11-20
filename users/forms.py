# users/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import User, AboutPage

class UserRegisterForm(UserCreationForm):
    # Добавляем нужные нам поля, которые не входят в стандартную UserCreationForm,
    # и настраиваем для них виджеты и классы Bootstrap
    first_name = forms.CharField(
        max_length=150, 
        required=True, 
        label="Имя", 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ваше имя'})
    )
    last_name = forms.CharField(
        max_length=150, 
        required=True, 
        label="Фамилия", 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ваша фамилия'})
    )
    email = forms.EmailField(
        required=True, 
        label="Электронная почта", 
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'})
    )

    class Meta(UserCreationForm.Meta):
        model = User
        # Указываем все поля, которые должны быть в форме, включая стандартные
        # username, password, password2, а также наши first_name, last_name, email.
        # UserCreationForm автоматически добавит password и password2.
        fields = ("username", "first_name", "last_name", "email") # password и password2 будут добавлены неявно.
        
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Придумайте логин'}),
            # Виджеты для password и password2 будут автоматически добавлены UserCreationForm
            # и будут иметь базовый form-control, так как мы не переопределяем их здесь явно.
            # Если нужны другие атрибуты, их можно добавить так же, как для username.
        }

    # Метод save UserCreationForm уже умеет сохранять username, password, password2.
    # Нам нужно только убедиться, что first_name, last_name, email также сохраняются.
    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data.get('first_name')
        user.last_name = self.cleaned_data.get('last_name')
        user.email = self.cleaned_data.get('email')
        if commit:
            user.save()
        return user


class UserUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = [
            'photo', 'first_name', 'last_name', 'patronymic', 
            'birth_date', 'gender', 'city', 'about_me', 
            'faculty', 'course', 'group',
            'job_title', 'office_location',
            'phone', 'telegram', 'phone_privacy', 'telegram_privacy'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
             'last_name': forms.TextInput(attrs={'class': 'form-control'}),
             'patronymic': forms.TextInput(attrs={'class': 'form-control'}),
             'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
             'gender': forms.Select(attrs={'class': 'form-select'}),
             'city': forms.TextInput(attrs={'class': 'form-control'}),
             'about_me': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
             'job_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: Специалист отдела'}),
             'office_location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: 3 этаж, 305 кабинет'}),
             'faculty': forms.TextInput(attrs={'class': 'form-control'}),
             'course': forms.NumberInput(attrs={'class': 'form-control'}),
             'group': forms.TextInput(attrs={'class': 'form-control'}),
             'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+992 XX XXX XX XX'}),
             'telegram': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@username'}),
             'phone_privacy': forms.Select(attrs={'class': 'form-select'}),
             'telegram_privacy': forms.Select(attrs={'class': 'form-select'}),
             'photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

        # --- НОВАЯ ФОРМА ДЛЯ АДМИНОВ ---
class AdminUpdateForm(forms.ModelForm):
    """
    Форма для МОДЕРАТОРА/АДМИНА, который редактирует ЧУЖОЙ профиль.
    НЕ включает настройки приватности.
    """
    class Meta:
        model = User
        fields = [
            'photo', 'first_name', 'last_name', 'patronymic', 'username', 'email',
            'birth_date', 'gender', 'city', 'about_me', 
            'faculty', 'course', 'group',
            'job_title', 'office_location',
            'phone', 'telegram'
            # Поля 'phone_privacy' и 'telegram_privacy' намеренно исключены
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'patronymic': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'gender': forms.Select(attrs={'class': 'form-select'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'about_me': forms.Textarea(attrs={'rows': 4, 'class': 'form-control'}),
            'job_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: Специалист отдела'}),
            'office_location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Например: 3 этаж, 305 кабинет'}),
            'faculty': forms.TextInput(attrs={'class': 'form-control'}),
            'course': forms.NumberInput(attrs={'class': 'form-control'}),
            'group': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+992 XX XXX XX XX'}),
            'telegram': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@username'}),
            'photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    # users/forms.py (Добавьте это в конец файла)

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
            
            # Статистика
            'stat_1_num': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_1_text': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_2_num': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_2_text': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_3_num': forms.TextInput(attrs={'class': 'form-control'}),
            'stat_3_text': forms.TextInput(attrs={'class': 'form-control'}),
            
            # Контакты
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'instagram': forms.TextInput(attrs={'class': 'form-control'}),
            'telegram': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
        }