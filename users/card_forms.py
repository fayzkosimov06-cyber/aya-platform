from django import forms
from django.core.exceptions import ValidationError
from .models import User, CardEdition, VolunteerCard
from .card_access import eligible_people
from .card_storage import normalized_image


class CardEditionForm(forms.ModelForm):
    class Meta:
        model = CardEdition
        fields = ['start_year', 'name_order', 'aya_logo', 'university_logo', 'stamp', 'signature']
        widgets = {key: forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'})
                   for key in ['aya_logo', 'university_logo', 'stamp', 'signature']}
        help_texts = {
            'start_year': 'Например, 2026 означает учебный год с 01.09.2026 до 31.08.2027.',
            'aya_logo': 'Если файл не выбран, используется текущий логотип AYA из сайта.',
            'university_logo': 'Если файл не выбран, используется логотип университета из сайта.',
            'stamp': 'PNG с прозрачным фоном подходит лучше всего. Файл хранится в закрытом хранилище.',
            'signature': 'Загрузите настоящую подпись. Для выдачи карты нужны и печать, и подпись.'}

    def clean(self):
        data = super().clean()
        for key in ['aya_logo', 'university_logo', 'stamp', 'signature']:
            if key in self.files and key in data:
                try:
                    data[key] = normalized_image(data[key], transparent=True)
                except ValidationError as error:
                    self.add_error(key, error)
        return data

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['start_year'].disabled = True


class CardForm(forms.ModelForm):
    photo_source = forms.ChoiceField(label='Фотография', choices=[
        ('profile', 'Взять фотографию из профиля'), ('upload', 'Загрузить отдельную фотографию'),
        ('keep', 'Оставить фотографию карты')])

    class Meta:
        model = VolunteerCard
        fields = ['user', 'edition', 'number', 'last_name', 'first_name', 'patronymic', 'course', 'photo_source', 'photo']
        widgets = {
            'photo': forms.FileInput(attrs={'accept': 'image/png,image/jpeg,image/webp', 'data-photo-ratio': '0.836237'}),
            'user': forms.Select(attrs={'class': 'use-select2'}),
        }
        help_texts = {
            'first_name': 'Каждая часть ФИО печатается отдельной строкой.',
            'last_name': 'Если фамилии нет, оставьте поле пустым.',
            'patronymic': 'Если отчества нет, оставьте поле пустым.',
            'number': 'Номер можно изменить. Один номер не может принадлежать разным картам.',
            'photo': 'Отдельное фото используется только в карте и не меняет фотографию профиля.'}

    def __init__(self, *args, person=None, edition=None, **kwargs):
        super().__init__(*args, **kwargs)
        editing = bool(self.instance.pk and not self.instance._state.adding)
        self.fields['user'].queryset = eligible_people().order_by('last_name', 'first_name', 'pk')
        if editing:
            self.fields['user'].queryset = User.objects.filter(pk=self.instance.user_id, is_superuser=False)
            self.fields['user'].disabled = True
            self.fields['edition'].disabled = True
            self.fields['photo_source'].initial = 'keep' if self.instance.photo else 'profile'
        else:
            self.fields['photo_source'].choices = self.fields['photo_source'].choices[:2]
            self.fields['photo_source'].initial = 'profile'
            if person:
                self.initial.update({name: getattr(person, name) for name in ['last_name', 'first_name', 'patronymic', 'course']})
                self.initial['user'] = person.pk
                if edition:
                    self.initial['edition'] = edition.pk
                    self.initial['number'] = f'AYA-{edition.start_year % 100:02d}-{person.pk:04d}'

    def clean(self):
        data = super().clean()
        if 'photo' in self.files:
            data['photo_source'] = 'upload'
        source = data.get('photo_source')
        if source == 'upload' and 'photo' not in self.files:
            self.add_error('photo', 'Выберите фотографию для загрузки.')
        if 'photo' in self.files and 'photo' in data:
            try:
                data['photo'] = normalized_image(data['photo'])
            except ValidationError as error:
                self.add_error('photo', error)
        if source == 'profile' and data.get('user') and not data['user'].photo:
            self.add_error('photo_source', 'В профиле нет фотографии. Загрузите отдельное фото.')
        if source == 'keep' and not self.instance.photo:
            self.add_error('photo_source', 'В карте пока нет фотографии.')
        return data

    def save(self, commit=True):
        card = super().save(commit=False)
        if self.cleaned_data['photo_source'] == 'profile':
            try:
                with card.user.photo.open('rb') as file:
                    copied = normalized_image(file)
                card.photo = copied
            except (OSError, ValueError, ValidationError) as error:
                raise ValidationError('Фотографию из профиля не удалось открыть. Загрузите отдельную.') from error
        card.status = 'draft'
        card.issued_at = None
        card.issued_by = None
        if commit:
            card.save()
        return card


class CardExportForm(forms.Form):
    cards = forms.ModelMultipleChoiceField(queryset=VolunteerCard.objects.none(), widget=forms.MultipleHiddenInput)
    format = forms.ChoiceField(label='Формат', choices=[
        ('press', 'PDF для типографии: отдельные стороны, вылеты 3 мм'),
        ('a4-long', 'PDF на А4: двусторонняя печать, переворот по длинной стороне'),
        ('a4-short', 'PDF на А4: двусторонняя печать, переворот по короткой стороне'),
        ('zip', 'ZIP: отдельный PDF для каждой карты и список')])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cards'].queryset = VolunteerCard.objects.select_related('user', 'edition').filter(
            status='issued', user__is_active=True, user__is_approved=True, user__is_superuser=False
        ).exclude(user__role__in=['worker', 'head_admin'])

    def clean_cards(self):
        cards = self.cleaned_data['cards']
        if cards.count() > 100:
            raise ValidationError('Выберите до 100 карт для одной выгрузки.')
        from .card_print import preflight
        for card in cards:
            errors = preflight(card)
            if errors:
                raise ValidationError(f'Карта {card.number}: ' + ' '.join(errors))
        return cards.order_by('number', 'pk')
