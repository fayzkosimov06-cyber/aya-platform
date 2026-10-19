"""Card photographs and approval assets must never be served by public /media/."""
import uuid
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile


class PrivateCardStorage(FileSystemStorage):
    def url(self, name):
        raise ValueError('Файлы карт доступны только через проверку прав.')


def card_storage():
    return PrivateCardStorage(location=settings.CARD_PRIVATE_ROOT,
                              file_permissions_mode=0o600, directory_permissions_mode=0o700)


def card_asset_path(instance, filename):
    return f'assets/{uuid.uuid4().hex}.png'


def normalized_image(upload, *, transparent=False):
    if not upload:
        return upload
    if upload.size > 8 * 1024 * 1024:
        raise ValidationError('Выберите изображение размером до 8 МБ.')
    if Path(upload.name).suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'}:
        raise ValidationError('Используйте PNG, JPEG или WebP.')
    try:
        upload.seek(0)
        with Image.open(upload) as source:
            if source.format not in {'PNG', 'JPEG', 'WEBP'} or source.width * source.height > 20_000_000:
                raise ValidationError('Изображение слишком большое или имеет неподдерживаемый формат.')
            source.load()
            image = ImageOps.exif_transpose(source).convert('RGBA' if transparent else 'RGB')
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            stream = BytesIO()
            image.save(stream, format='PNG', optimize=True)
        return SimpleUploadedFile('asset.png', stream.getvalue(), content_type='image/png')
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
        raise ValidationError('Изображение не удалось прочитать. Загрузите другой файл.') from error
