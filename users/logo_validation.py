from pathlib import Path
from django.core.exceptions import ValidationError

def validate_logo(value):
    if value.size > 8*1024*1024:
        raise ValidationError('Логотип должен быть не больше 8 МБ.')
    if Path(value.name).suffix.lower() not in {'.png','.jpg','.jpeg','.webp'}:
        raise ValidationError('Используйте PNG, JPEG или WebP. Для прозрачного фона подойдёт PNG.')
