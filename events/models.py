from django.db import models
from users.models import User

class Event(models.Model):
    title = models.CharField(max_length=200, verbose_name="Название мероприятия")
    description = models.TextField(verbose_name="Описание анонса")
    cover_image = models.ImageField(upload_to='event_covers/', blank=True, null=True, verbose_name="Обложка (для списка)")
    
    start_time = models.DateTimeField(verbose_name="Время начала")
    end_time = models.DateTimeField(verbose_name="Время окончания")
    location = models.CharField(max_length=255, blank=True, verbose_name="Место проведения")
    
    organizer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="organized_events", verbose_name="Организатор")
    
    # Статусы
    is_approved = models.BooleanField(default=False, verbose_name="Одобрено")
    is_completed = models.BooleanField(default=False, verbose_name="Завершено")
    
    max_participants = models.PositiveIntegerField(null=True, blank=True, verbose_name="Макс. участников")
    participants = models.ManyToManyField(User, related_name="attending_events", blank=True, verbose_name="Участники")

    # Отчет
    report_text = models.TextField(blank=True, verbose_name="Текст отчета")
    is_report_published = models.BooleanField(default=False, verbose_name="Опубликовать отчет")

    class Meta:
        ordering = ['-start_time']

    def __str__(self):
        return self.title

class EventPhoto(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='event_gallery/', verbose_name="Фото")
    caption = models.CharField(max_length=200, blank=True, verbose_name="Подпись")

class EventVideo(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='videos')
    video_url = models.URLField(verbose_name="Ссылка на видео")

class EventHero(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='heroes')
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Волонтер")
    role_name = models.CharField(max_length=100, verbose_name="Роль")