import uuid
from datetime import date
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from .card_storage import card_storage, card_asset_path


def current_card_year():
    today = timezone.localdate()
    return today.year if today.month >= 9 else today.year - 1


class CardEdition(models.Model):
    start_year = models.PositiveSmallIntegerField('Начало учебного года', unique=True,
        default=current_card_year, validators=[MinValueValidator(2020), MaxValueValidator(2200)])
    name_order = models.CharField('Порядок ФИО', max_length=16, default='family_first', choices=[
        ('given_first', 'Имя → фамилия → отчество'), ('family_first', 'Фамилия → имя → отчество')])
    aya_logo = models.ImageField('Логотип AYA этого года', storage=card_storage, upload_to=card_asset_path, blank=True)
    university_logo = models.ImageField('Логотип университета', storage=card_storage, upload_to=card_asset_path, blank=True)
    stamp = models.ImageField('Печать', storage=card_storage, upload_to=card_asset_path, blank=True)
    signature = models.ImageField('Подпись руководителя', storage=card_storage, upload_to=card_asset_path, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_year']
        verbose_name = 'Учебный год карт'
        verbose_name_plural = 'Учебные годы карт'

    @property
    def academic_year(self):
        return f'{self.start_year} / {self.start_year + 1}'

    @property
    def valid_from(self):
        return date(self.start_year, 9, 1)

    @property
    def valid_until(self):
        return date(self.start_year + 1, 8, 31)

    @property
    def approval_ready(self):
        return bool(self.stamp and self.signature)

    def __str__(self):
        return self.academic_year


class VolunteerCard(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey('users.User', on_delete=models.CASCADE, related_name='volunteer_cards', verbose_name='Волонтёр')
    edition = models.ForeignKey(CardEdition, on_delete=models.PROTECT, related_name='cards', verbose_name='Учебный год')
    number = models.CharField('Номер карты', max_length=40, unique=True)
    first_name = models.CharField('Имя', max_length=150, blank=True)
    last_name = models.CharField('Фамилия', max_length=150, blank=True)
    patronymic = models.CharField('Отчество', max_length=150, blank=True)
    course = models.PositiveSmallIntegerField('Курс', null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(8)])
    photo = models.ImageField('Фото для карты', storage=card_storage, upload_to=card_asset_path, blank=True)
    status = models.CharField('Состояние', max_length=12, default='draft', choices=[
        ('draft', 'Черновик'), ('issued', 'Выдана'), ('revoked', 'Отозвана')])
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey('users.User', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='issued_volunteer_cards', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-edition__start_year', 'number']
        constraints = [models.UniqueConstraint(fields=['edition', 'user'], name='one_card_per_user_and_year')]
        verbose_name = 'Волонтёрская карта'
        verbose_name_plural = 'Волонтёрские карты'

    @property
    def name_lines(self):
        parts = [self.first_name, self.last_name, self.patronymic]
        if self.edition.name_order == 'family_first':
            parts[0], parts[1] = parts[1], parts[0]
        return [' '.join(value.split()) for value in parts if value and value.strip()]

    @property
    def full_name(self):
        return ' '.join(self.name_lines)

    @property
    def is_current(self):
        from .card_access import eligible_person
        return (self.status == 'issued' and eligible_person(self.user)
                and self.edition.valid_from <= timezone.localdate() <= self.edition.valid_until)

    def clean(self):
        super().clean()
        self.number = ' '.join(self.number.split()).upper()
        if not self.number or any(not (c.isalnum() or c in ' -./') for c in self.number):
            raise ValidationError({'number': 'Используйте буквы, цифры, пробел, точку, дефис или косую черту.'})
        if not any(value.strip() for value in [self.first_name, self.last_name, self.patronymic]):
            raise ValidationError('Укажите хотя бы одну часть имени.')

    def __str__(self):
        return f'{self.number} · {self.full_name}'
