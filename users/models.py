# users/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from io import BytesIO
from django.core.files import File
import qrcode

class Direction(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название направления")
    leaders = models.ManyToManyField(
        'User',
        blank=True,
        related_name='directions_led',
        verbose_name="Руководители"
    )
    def __str__(self): return self.name

class School(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название школы")
    def __str__(self): return self.name

class User(AbstractUser):
    ROLE_CHOICES = (
        ('volunteer', 'Волонтер'),
        ('leader', 'Руководитель направления'),
        ('moderator', 'Модератор'),
        ('president', 'Президент Ассоциации'),
        ('worker', 'Работник (Админ)'),
        ('head_admin', 'Руководитель отдела'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='volunteer', verbose_name="Роль в системе")
    is_approved = models.BooleanField(default=False, verbose_name="Профиль одобрен")
    is_active_volunteer_title = models.BooleanField(default=False, verbose_name="Имеет звание 'Активный волонтер'")
    school_leader_of = models.ManyToManyField(School, blank=True, related_name="leaders", verbose_name="Руководит школами")
    
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True, verbose_name="Фотография")
    
    patronymic = models.CharField(max_length=100, blank=True, verbose_name="Отчество")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    gender = models.CharField(max_length=1, choices=[('M', 'Мужской'), ('F', 'Женский')], blank=True, verbose_name="Пол")
    city = models.CharField(max_length=100, blank=True, verbose_name="Город")
    
    # --- НОВЫЕ ПОЛЯ ---
    about_me = models.TextField(blank=True, verbose_name="О себе (Bio)")
    instagram = models.CharField(max_length=100, blank=True, verbose_name="Instagram")
    linkedin = models.CharField(max_length=100, blank=True, verbose_name="LinkedIn")
    
    job_title = models.CharField(max_length=200, blank=True, verbose_name="Должность (для сотрудников)")
    office_location = models.CharField(max_length=100, blank=True, verbose_name="Кабинет/Местоположение")
    
    faculty = models.CharField(max_length=200, blank=True, verbose_name="Факультет")
    course = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Курс")
    group = models.CharField(max_length=50, blank=True, verbose_name="Группа")
    directions = models.ManyToManyField(Direction, blank=True, verbose_name="Участвует в направлениях")
    
    phone = models.CharField(max_length=20, blank=True, verbose_name="Номер телефона")
    telegram = models.CharField(max_length=100, blank=True, verbose_name="Telegram")
    
    # --- НАСТРОЙКИ ПРИВАТНОСТИ ---
    # private = Только я и Администрация (Модераторы+)
    # volunteers = Все зарегистрированные волонтеры
    # public = Весь интернет (Гости)
    
    PRIVACY_CHOICES = (
        ('private', '🔒 Только я и Админы'),
        ('volunteers', '👥 Все волонтеры'),
        ('public', '🌐 Все (Публично)'),
    )
    
    # По умолчанию ставим 'volunteers' (видно своим), как вы и просили
    phone_privacy = models.CharField(max_length=15, choices=PRIVACY_CHOICES, default='volunteers', verbose_name="Кто видит телефон?")
    telegram_privacy = models.CharField(max_length=15, choices=PRIVACY_CHOICES, default='volunteers', verbose_name="Кто видит Telegram?")
    instagram_privacy = models.CharField(max_length=15, choices=PRIVACY_CHOICES, default='volunteers', verbose_name="Кто видит Instagram?")
    linkedin_privacy = models.CharField(max_length=15, choices=PRIVACY_CHOICES, default='volunteers', verbose_name="Кто видит LinkedIn?")
    about_me_privacy = models.CharField(max_length=15, choices=PRIVACY_CHOICES, default='volunteers', verbose_name="Кто видит Био?")

    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, verbose_name="QR-код")

    def get_full_name(self): return f"{self.last_name} {self.first_name} {self.patronymic}".strip()
    def get_role_display_custom(self): return dict(self.ROLE_CHOICES).get(self.role, self.role.capitalize())
    
    def save(self, *args, **kwargs):
        from django.urls import reverse
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.qr_code:
            try:
                public_profile_url = reverse('public_profile', kwargs={'pk': self.pk})
                # Замените домен на реальный при деплое
                domain = "http://aya1.pythonanywhere.com" 
                full_url = f"{domain}{public_profile_url}"
                qr_image = qrcode.make(full_url)
                qr_offset = BytesIO()
                qr_image.save(qr_offset, format='PNG')
                file_name = f'qr_code_{self.username}.png'
                self.qr_code.save(file_name, File(qr_offset), save=True)
            except Exception: pass

    def __str__(self): return self.get_full_name() or self.username

class ActivityPeriod(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activity_periods')
    start_date = models.DateField(verbose_name="Дата начала периода")
    end_date = models.DateField(verbose_name="Дата окончания периода")
    description = models.CharField(max_length=255, blank=True, verbose_name="Описание")
    class Meta: ordering = ['-start_date']
    def __str__(self): return f"{self.user}: {self.start_date} - {self.end_date}"

class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    link = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-created_at']

class AboutPage(models.Model):
    title = models.CharField(max_length=255, default="О нас")
    description = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    mission_title = models.CharField(max_length=100, default="Наша Миссия")
    mission_text = models.TextField(blank=True)
    stat_1_num = models.CharField(max_length=20, default="500+")
    stat_1_text = models.CharField(max_length=100, default="Волонтеров")
    stat_2_num = models.CharField(max_length=20, default="50+")
    stat_2_text = models.CharField(max_length=100, default="Мероприятий")
    stat_3_num = models.CharField(max_length=20, default="5")
    stat_3_text = models.CharField(max_length=100, default="Лет работы")
    email = models.EmailField(blank=True)
    instagram = models.CharField(max_length=100, blank=True)
    telegram = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    def __str__(self): return self.title

class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='actor_logs')
    action = models.TextField()
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='target_logs')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-created_at']