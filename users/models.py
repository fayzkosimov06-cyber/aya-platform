# users/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from io import BytesIO
from django.core.files import File
import qrcode

class Direction(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название направления")
    leader = models.OneToOneField(
        'User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='led_direction',
        verbose_name="Руководитель"
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
    
    # ИЗМЕНЕНИЕ: Убрана заглушка default.png, теперь поле может быть пустым
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True, verbose_name="Фотография")
    
    patronymic = models.CharField(max_length=100, blank=True, verbose_name="Отчество")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    gender = models.CharField(max_length=1, choices=[('M', 'Мужской'), ('F', 'Женский')], blank=True, verbose_name="Пол")
    city = models.CharField(max_length=100, blank=True, verbose_name="Город")
    about_me = models.TextField(blank=True, verbose_name="О себе")
    # ... внутри class User ...
    # Поля для сотрудников отдела
    job_title = models.CharField(max_length=200, blank=True, verbose_name="Должность (для сотрудников)")
    office_location = models.CharField(max_length=100, blank=True, verbose_name="Кабинет/Местоположение")
    faculty = models.CharField(max_length=200, blank=True, verbose_name="Факультет")
    course = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Курс")
    group = models.CharField(max_length=50, blank=True, verbose_name="Группа")
    directions = models.ManyToManyField(Direction, blank=True, verbose_name="Участвует в направлениях")
    phone = models.CharField(max_length=20, blank=True, verbose_name="Номер телефона")
    telegram = models.CharField(max_length=100, blank=True, verbose_name="Telegram")
    PRIVACY_CHOICES = ( ('private', 'Только модераторам'), ('volunteers', 'Только волонтерам'), ('public', 'Всем'), )
    phone_privacy = models.CharField(max_length=15, choices=PRIVACY_CHOICES, default='private')
    telegram_privacy = models.CharField(max_length=15, choices=PRIVACY_CHOICES, default='private')
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
                full_url = f"http://127.0.0.1:8000{public_profile_url}"
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
    description = models.CharField(max_length=255, blank=True, verbose_name="Описание (необязательно)")
    class Meta:
        ordering = ['-start_date']; verbose_name = "Период активности"; verbose_name_plural = "Периоды активности"
    def __str__(self): return f"{self.user.username}: {self.start_date.year} - {self.end_date.year}"

class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField(verbose_name="Сообщение")
    link = models.CharField(max_length=255, verbose_name="Ссылка для перехода", blank=True, null=True)
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']; verbose_name = "Уведомление"; verbose_name_plural = "Уведомления"
    def __str__(self): return f"Уведомление для {self.recipient.username}"

class AboutPage(models.Model):
    title = models.CharField(max_length=255, default="О нас")
    content = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    def __str__(self): return self.title

    # --- НОВАЯ МОДЕЛЬ ДЛЯ ЖУРНАЛА ДЕЙСТВИЙ ---
class AuditLog(models.Model):
    actor = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='actor_logs',
        verbose_name="Действующее лицо"
    )
    action = models.TextField(verbose_name="Действие")
    target_user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='target_logs',
        verbose_name="Целевой пользователь (если применимо)"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Время")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Запись в журнале"
        verbose_name_plural = "Журнал действий"

    def __str__(self):
        return f"{self.actor} - {self.action[:50]}..."
    
    # --- Добавить в конец users/models.py ---

class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='actor_logs', verbose_name="Действующее лицо")
    action = models.TextField(verbose_name="Действие")
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='target_logs', verbose_name="Цель")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Время")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Запись в журнале"
        verbose_name_plural = "Журнал действий"

    def __str__(self):
        return f"{self.actor} - {self.action[:50]}..."