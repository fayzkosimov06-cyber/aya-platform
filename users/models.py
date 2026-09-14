from .profile_choices import CITY_CHOICES, FACULTY_CHOICES, COURSE_CHOICES
# users/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from io import BytesIO
from django.core.files import File
from django.utils import timezone
import qrcode

class Direction(models.Model):
    intro = models.CharField('Коротко о направлении', max_length=240, blank=True)
    description = models.TextField('О направлении', blank=True)
    cover = models.ImageField('Обложка', upload_to='directions/', blank=True)
    featured_only = models.BooleanField('Показывать активную команду', default=False)
    featured_members = models.ManyToManyField('User', blank=True, related_name='featured_in_directions')
    events = models.ManyToManyField('events.Event', blank=True, related_name='aya_directions')

    name = models.CharField(max_length=100, unique=True, verbose_name="Название направления")
    leaders = models.ManyToManyField(
        'User',
        blank=True,
        related_name='directions_led',
        verbose_name="Руководители"
    )
    def __str__(self): return self.name

class School(models.Model):
    active = models.BooleanField('Занятия проводятся', default=True)
    direction = models.ForeignKey(Direction, null=True, blank=True, on_delete=models.SET_NULL, related_name='schools', verbose_name='Направление')
    intro = models.CharField('Коротко о школе', max_length=240, blank=True)
    description = models.TextField('О школе', blank=True)
    cover = models.ImageField('Обложка', upload_to='schools/', blank=True)
    members = models.ManyToManyField('User', blank=True, related_name='aya_schools', verbose_name='Участники школы')
    events = models.ManyToManyField('events.Event', blank=True, related_name='aya_schools')

    name = models.CharField(max_length=100, unique=True, verbose_name="Название школы")
    def __str__(self): return self.name

class User(AbstractUser):
    ROLE_CHOICES = (
        ('volunteer', 'Волонтер'),
        ('moderator', 'Модератор'),
        ('president', 'Президент Ассоциации'),
        ('worker', 'Работник (Админ)'),
        ('head_admin', 'Начальник отдела'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='volunteer', verbose_name="Роль в системе")
    is_approved = models.BooleanField(default=False, verbose_name="Профиль одобрен")
    candidate_approved = models.BooleanField(
        default=False,
        verbose_name="Кандидат одобрен (договор подписан)",
        help_text="Одобрен как кандидат: может заходить на сайт, но без волонтёрских прав.",
    )
    volunteer_access = models.BooleanField(
        default=False,
        verbose_name="Доступ волонтёра открыт (3 визита)",
        help_text="Полный доступ волонтёра (открывается автоматически на 3-й отметке или вручную).",
    )
    is_active_volunteer_title = models.BooleanField(default=False, verbose_name="Имеет звание 'Активный волонтер'")
    school_leader_of = models.ManyToManyField(School, blank=True, related_name="leaders", verbose_name="Руководит школами")
    
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True, verbose_name="Фотография")
    
    patronymic = models.CharField(max_length=100, blank=True, verbose_name="Отчество")
    birth_date = models.DateField(null=True, blank=True, verbose_name="Дата рождения")
    gender = models.CharField(max_length=1, choices=[('M', 'Мужской'), ('F', 'Женский')], blank=True, verbose_name="Пол")
    city = models.CharField(max_length=100, blank=True, choices=CITY_CHOICES, verbose_name="Город")
    
    # --- НОВЫЕ ПОЛЯ ---
    about_me = models.TextField(blank=True, verbose_name="О себе (Bio)")
    instagram = models.CharField(max_length=100, blank=True, verbose_name="Instagram")
    linkedin = models.CharField(max_length=100, blank=True, verbose_name="LinkedIn")
    
    job_title = models.CharField(max_length=200, blank=True, verbose_name="Должность (для сотрудников)")
    office_location = models.CharField(max_length=100, blank=True, verbose_name="Кабинет/Местоположение")
    is_old_volunteer = models.BooleanField(default=False, verbose_name="Старый волонтёр")
    
    new_volunteer_until = models.DateTimeField(blank=True, null=True, verbose_name="До какого времени показывать статус 'Новый волонтёр'")
    volunteer_access_granted_at = models.DateTimeField(blank=True, null=True, verbose_name='Когда выдан полный доступ')
    volunteer_access_granted_by = models.ForeignKey('self', blank=True, null=True, on_delete=models.SET_NULL, related_name='granted_volunteer_access_to', verbose_name='Кто выдал полный доступ')

    @property
    def is_new_volunteer(self):
        return bool(self.is_approved and not self.is_old_volunteer and self.new_volunteer_until and self.new_volunteer_until > timezone.now())

    faculty = models.CharField(max_length=200, blank=True, choices=FACULTY_CHOICES, verbose_name="Факультет")
    course = models.PositiveSmallIntegerField(null=True, blank=True, choices=COURSE_CHOICES, verbose_name="Курс")
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
    def get_role_display_custom(self):
        if self.is_superuser: return 'Суперадминистратор'
        if self.role in {'volunteer','leader'} and self.pk:
            if self.directions_led.exists(): return 'Руководитель направления'
            if self.school_leader_of.exists(): return 'Учитель школы'
        return dict(self.ROLE_CHOICES).get(self.role,self.role.capitalize())
    
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
    end_date = models.DateField(null=True, blank=True, verbose_name="Дата окончания периода")
    description = models.CharField(max_length=255, blank=True, verbose_name="Описание")
    class Meta: ordering = ['-start_date']
    def __str__(self):
        end = self.end_date if self.end_date else 'по н.в.'
        return f"{self.user}: {self.start_date} - {end}"

class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    link = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-created_at']



class VolunteerVisit(models.Model):
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='volunteer_visits', verbose_name='Пользователь')
    marked_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='marked_visits', verbose_name='Кто отметил')
    visit_date = models.DateField(default=timezone.localdate, verbose_name='Дата визита')
    comment = models.TextField(blank=True, default='', verbose_name='Комментарий модератора')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-visit_date', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'visit_date'], name='unique_user_visit_per_day')
        ]

    def __str__(self):
        return f"{self.user} — {self.visit_date}"


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


class AboutValueBlock(models.Model):
    about = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name='value_blocks')
    title = models.CharField(max_length=120)
    text = models.TextField(blank=True)
    icon = models.CharField(max_length=120, blank=True, default='fa-solid fa-star')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    def __str__(self):
        return self.title

class AboutStatItem(models.Model):
    SOURCE_CHOICES = [('manual', 'Ввести вручную'), ('volunteers', 'Волонтёры'), ('active', 'Активные волонтёры'), ('workers', 'Работники'), ('leaders', 'Руководители направлений'), ('school_leaders', 'Руководители школ'), ('schools', 'Школы'), ('directions', 'Направления'), ('events', 'Мероприятия')]
    source = models.CharField(max_length=24, choices=SOURCE_CHOICES, default='manual', verbose_name='Откуда брать число')
    about = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name='stat_items')
    number = models.CharField(max_length=30)
    label = models.CharField(max_length=120)
    icon = models.CharField(max_length=120, blank=True, default='fa-solid fa-chart-line')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    def __str__(self):
        return f"{self.number} {self.label}"

class AboutContactLink(models.Model):
    PLATFORM_CHOICES = [
        ('instagram', 'Instagram'),
        ('facebook', 'Facebook'),
        ('telegram', 'Telegram'),
        ('youtube', 'YouTube'),
        ('tiktok', 'TikTok'),
        ('whatsapp', 'WhatsApp'),
        ('website', 'Сайт'),
        ('email', 'Email'),
        ('phone', 'Телефон'),
        ('custom', 'Другое'),
    ]
    PLATFORM_ICONS = {
        'instagram': 'fa-brands fa-instagram',
        'facebook': 'fa-brands fa-facebook-f',
        'telegram': 'fa-brands fa-telegram',
        'youtube': 'fa-brands fa-youtube',
        'tiktok': 'fa-brands fa-tiktok',
        'whatsapp': 'fa-brands fa-whatsapp',
        'website': 'fa-solid fa-globe',
        'email': 'fa-solid fa-envelope',
        'phone': 'fa-solid fa-phone',
        'custom': 'fa-solid fa-link',
    }

    about = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name='contact_links')
    platform = models.CharField(max_length=32, choices=PLATFORM_CHOICES, default='custom', verbose_name='Платформа')
    label = models.CharField(max_length=120)
    url = models.CharField(max_length=255)
    icon = models.CharField(max_length=120, blank=True, default='')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    requires_volunteer_access = models.BooleanField(default=False, verbose_name='Только для волонтёров')

    def __str__(self):
        return self.label

    class Meta:
        ordering = ['order', 'id']

    @property
    def platform_label(self):
        return dict(self.PLATFORM_CHOICES).get(self.platform, 'Другое')

    @property
    def resolved_icon(self):
        raw = (self.icon or '').strip()
        if raw:
            return raw
        return self.PLATFORM_ICONS.get(self.platform, 'fa-solid fa-link')

    @property
    def get_icon(self):
        return self.resolved_icon

    @property
    def resolved_url(self):
        raw = (self.url or '').strip()
        if not raw:
            return '#'
        lower = raw.lower()
        if raw.startswith('@'):
            nick = raw[1:]
            if self.platform == 'telegram':
                return f'https://t.me/{nick}'
            if self.platform == 'instagram':
                return f'https://instagram.com/{nick}'
            if self.platform == 'facebook':
                return f'https://facebook.com/{nick}'
        if lower.startswith(('http://', 'https://', 'mailto:', 'tel:')):
            return raw
        if self.platform == 'email' or ('@' in raw and ' ' not in raw and '.' in raw):
            return f'mailto:{raw}'
        normalized_digits = raw.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        if self.platform == 'phone' or raw.startswith('+') or normalized_digits.isdigit():
            return f'tel:{raw}'
        return f'https://{raw}'

class AboutExtraBlock(models.Model):
    about = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name='extra_blocks')
    title = models.CharField(max_length=120)
    text = models.TextField(blank=True)
    icon = models.CharField(max_length=120, blank=True, default='fa-solid fa-lightbulb')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    def __str__(self):
        return self.title


class AuditLog(models.Model):
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='actor_logs')
    action = models.TextField()
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='target_logs')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta: ordering = ['-created_at']

class HomePage(models.Model):
    quotes_per_view = models.PositiveSmallIntegerField(default=1, choices=[(1, 'По одной'), (2, 'По две'), (3, 'По три')], verbose_name='Показ цитат')
    hero_image = models.ImageField(upload_to='homepage/', blank=True, verbose_name='Фотография в верхнем блоке')
    quote_text = models.TextField(blank=True, verbose_name='Цитата')
    quote_author = models.CharField(max_length=160, blank=True, verbose_name='Автор цитаты')
    quote_role = models.CharField(max_length=160, blank=True, verbose_name='Подпись автора')
    quote_photo = models.ImageField(upload_to='homepage/', blank=True, verbose_name='Фотография автора')

    class Meta:
        verbose_name = 'Главная страница'
        verbose_name_plural = 'Главная страница'

    def __str__(self):
        return 'Главная страница AYA'


class HomeSlide(models.Model):
    page = models.ForeignKey(HomePage, on_delete=models.CASCADE, related_name='slides')
    image = models.ImageField(upload_to='homepage/slides/', verbose_name='Фотография')
    caption = models.CharField(max_length=200, blank=True, verbose_name='Описание фотографии')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']


class HomeQuote(models.Model):
    page = models.ForeignKey(HomePage, on_delete=models.CASCADE, related_name='quotes')
    text = models.TextField(verbose_name='Цитата')
    member = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL, related_name='homepage_quotes', verbose_name='Участник сайта')
    author_name = models.CharField(max_length=160, blank=True, verbose_name='Имя автора')
    author_role = models.CharField(max_length=160, blank=True, verbose_name='Подпись автора')
    photo = models.ImageField(upload_to='homepage/quotes/', blank=True, verbose_name='Фотография автора')
    source_url = models.URLField(blank=True, verbose_name='Ссылка на источник')
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['order', 'id']

    @property
    def display_name(self):
        return (self.member.get_full_name() or self.member.username) if self.member else self.author_name

    @property
    def display_role(self):
        return self.author_role or (self.member.get_role_display() if self.member else '')

    @property
    def display_photo(self):
        return self.photo or (self.member.photo if self.member else None)

    @property
    def author_url(self):
        from django.urls import reverse
        return reverse('public_profile', args=[self.member_id]) if self.member_id else self.source_url


class ContributionKind(models.Model):
    name = models.CharField('Вид помощи', max_length=160, unique=True)
    points = models.PositiveIntegerField('Баллы')
    active = models.BooleanField('Доступен для начислений', default=True)

    def __str__(self):
        return f'{self.name} — {self.points} баллов'


class ContributionWork(models.Model):
    direction = models.ForeignKey(Direction, null=True, blank=True, on_delete=models.SET_NULL, related_name='point_works', verbose_name='Направление')
    school = models.ForeignKey(School, null=True, blank=True, on_delete=models.SET_NULL, related_name='point_works', verbose_name='Школа')

    submission = models.UUIDField(null=True, blank=True, unique=True)
    title = models.CharField('Название работы', max_length=200)
    date = models.DateField('Дата выполненной работы')
    description = models.TextField('Описание', blank=True)
    event = models.OneToOneField('events.Event', null=True, blank=True, on_delete=models.SET_NULL)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-pk']

    def __str__(self):
        return f'{self.title} ({self.date:%d.%m.%Y})'


class ContributionAward(models.Model):
    work = models.ForeignKey(ContributionWork, on_delete=models.PROTECT, related_name='awards')
    member = models.ForeignKey(User, on_delete=models.PROTECT, related_name='point_awards')
    kind = models.ForeignKey(ContributionKind, on_delete=models.PROTECT)
    points = models.PositiveIntegerField()
    comment = models.TextField(blank=True)
    confirmed_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='confirmed_awards')
    confirmed_at = models.DateTimeField(auto_now_add=True)
    revoked = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['work', 'member', 'kind'], name='unique_work_member_kind')]


class ContributionChange(models.Model):
    award = models.ForeignKey(ContributionAward, on_delete=models.PROTECT, related_name='changes')
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    at = models.DateTimeField(auto_now_add=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    reason = models.TextField()


class SchoolTeacher(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='teachers')
    member = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, verbose_name='Профиль на сайте')
    name = models.CharField('Имя преподавателя', max_length=200)
    subject = models.CharField('Предмет / специализация', max_length=200, blank=True)
    bio = models.TextField('О преподавателе', blank=True)
    photo = models.ImageField('Фотография', upload_to='teachers/', blank=True)

    def __str__(self): return self.name


class SchoolLesson(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='lessons')
    topic = models.CharField('Тема занятия', max_length=240)
    starts_at = models.DateTimeField('Начало занятия')
    ends_at = models.DateTimeField('Окончание занятия')
    location = models.CharField('Место / кабинет', max_length=240, blank=True)
    description = models.TextField('Описание', blank=True)
    teachers = models.ManyToManyField(SchoolTeacher, blank=True, related_name='lessons', verbose_name='Преподаватели')
    cancelled = models.BooleanField('Занятие отменено', default=False)

    class Meta:
        ordering = ['starts_at', 'pk']

    def __str__(self): return self.topic


class PointProposal(models.Model):
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.SET_NULL)
    direction = models.ForeignKey(Direction, null=True, blank=True, on_delete=models.SET_NULL)
    school = models.ForeignKey(School, null=True, blank=True, on_delete=models.SET_NULL)
    author = models.ForeignKey(User, on_delete=models.PROTECT, related_name='point_proposals')
    title = models.CharField('За какую помощь', max_length=200)
    date = models.DateField('Дата помощи')
    description = models.TextField('Описание помощи', blank=True)
    volunteers = models.ManyToManyField(User, related_name='proposed_awards')
    status = models.CharField(max_length=12, default='pending', choices=[('pending','На рассмотрении'),('approved','Подтверждено'),('rejected','Отклонено')])
    reviewer = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_proposals')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    work = models.ForeignKey(ContributionWork, null=True, blank=True, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class PermissionOverride(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='permission_overrides')
    code = models.CharField(max_length=40)
    enabled = models.BooleanField(default=False)
    scope = models.CharField(max_length=12, default='own', choices=[('own','Свои команды'),('selected','Выбранные команды'),('all','Все команды')])
    directions = models.ManyToManyField(Direction, blank=True)
    schools = models.ManyToManyField(School, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user','code'], name='unique_person_capability')]


class JournalEntry(models.Model):
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    private = models.BooleanField(default=False, db_index=True)
    category = models.CharField(max_length=30, db_index=True)
    section = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    action = models.CharField(max_length=200)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta: ordering = ['-created_at','-pk']


class BalanceAdjustment(models.Model):
    member = models.ForeignKey(User, on_delete=models.PROTECT, related_name='balance_adjustments')
    date = models.DateField()
    amount = models.IntegerField()
    note = models.TextField(blank=True)
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
