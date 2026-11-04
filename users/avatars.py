"""Bounded profile images and reversible retirement of unreferenced originals."""
from contextlib import contextmanager
from datetime import timedelta
from io import BytesIO
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
from uuid import uuid4
import warnings

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)
UPLOAD_SECTION = 'profile_photo_upload'
MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 20_000_000
HELP = 'JPEG, PNG или WebP, до 5 МБ и 20 миллионов пикселей. Фото сохраняется без геометок, до 1600 × 1600.'


def roots():
    public = Path(settings.MEDIA_ROOT).absolute() / 'profile_photos'
    private = Path(getattr(settings, 'PROFILE_PHOTO_ARCHIVE_ROOT',
                   Path(settings.CARD_PRIVATE_ROOT).parent / 'avatar_history')).absolute()
    for path in (public, private):
        if path.resolve() != path or path.is_symlink():
            raise ValidationError('Хранилище фотографий временно недоступно.')
    if private == public or private.is_relative_to(Path(settings.MEDIA_ROOT).resolve()):
        raise ValidationError('Архив фотографий должен быть закрытым.')
    return public, private


def file_bytes(root):
    if not root.exists():
        return 0
    total = 0
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValidationError('Хранилище фотографий требует проверки.')
        if path.is_file():
            total += path.stat().st_size
    return total


def check_allowance(person, size):
    from .models import JournalEntry
    now = timezone.now()
    if person.pk:
        changes = JournalEntry.objects.filter(section=UPLOAD_SECTION, object_id=str(person.pk))
        if (changes.filter(created_at__gte=now-timedelta(hours=1)).count() >= getattr(settings,'PROFILE_PHOTO_HOURLY_LIMIT',10)
                or changes.filter(created_at__gte=now-timedelta(days=1)).count() >= getattr(settings,'PROFILE_PHOTO_DAILY_LIMIT',30)):
            raise ValidationError('Вы слишком часто меняете фото. Попробуйте позже.')
    public, private = roots()
    owned = file_bytes(private / str(person.pk)) if person.pk else 0
    names = {path for path in public.glob(f'avatar-{person.pk}-*.jpg')} if person.pk else set()
    if person.photo and getattr(person.photo, '_committed', True):
        try:
            path = Path(person.photo.path)
            if path.is_file() and path.resolve().is_relative_to(public): names.add(path)
        except (OSError, ValueError, NotImplementedError): pass
    elif person.pk:
        previous = person.__class__.objects.filter(pk=person.pk).values_list('photo',flat=True).first()
        if previous:
            path = Path(settings.MEDIA_ROOT).absolute() / previous
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(public): names.add(path)
    owned += sum(path.stat().st_size for path in names if path.is_file() and not path.is_symlink())
    if owned + size > getattr(settings,'PROFILE_PHOTO_ACCOUNT_BYTES',64*1024*1024):
        raise ValidationError('Достигнут лимит хранения фотографий профиля. Обратитесь к сотруднику AYA.')
    if file_bytes(public) + file_bytes(private) + size > getattr(settings,'PROFILE_PHOTO_TOTAL_BYTES',2*1024**3):
        raise ValidationError('Хранилище фотографий заполнено. Обратитесь к сотруднику AYA.')
    existing = public if public.exists() else Path(settings.MEDIA_ROOT)
    while not existing.exists(): existing = existing.parent
    if shutil.disk_usage(existing).free < getattr(settings,'PROFILE_PHOTO_FREE_BYTES',1024**3) + size:
        raise ValidationError('Недостаточно свободного места для фотографии. Попробуйте позже.')


def prepare(person):
    photo = person.photo
    if not photo or getattr(photo, '_committed', True): return
    upload = photo.file
    if not getattr(upload, '_aya_normalized_avatar', False):
        if upload.size > MAX_BYTES:
            raise ValidationError('Фотография слишком большая. Максимум 5 МБ.')
        if Path(upload.name).suffix.lower() not in {'.jpg','.jpeg','.png','.webp'}:
            raise ValidationError('Выберите фотографию JPEG, PNG или WebP.')
        try:
            upload.seek(0)
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(upload) as source:
                    if source.format not in {'JPEG','PNG','WEBP'} or source.width*source.height > MAX_PIXELS or max(source.size)>10000:
                        raise ValidationError('Фотография слишком большая: максимум 20 миллионов пикселей и 10000 пикселей по стороне.')
                    source.load()
                    image = ImageOps.exif_transpose(source).convert('RGBA')
                    image.thumbnail((1600,1600), Image.Resampling.LANCZOS)
                    background = Image.new('RGB',image.size,'white');background.paste(image,mask=image.getchannel('A'))
                    for quality in (88,80,70):
                        stream=BytesIO();background.save(stream,format='JPEG',quality=quality,optimize=True)
                        if stream.tell() <= 1024*1024: break
            if stream.tell()>1024*1024: raise ValidationError('Не удалось уменьшить фотографию. Выберите другой файл.')
        except (OSError,ValueError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning) as error:
            raise ValidationError('Изображение не удалось прочитать. Выберите другой файл.') from error
        normalized=ContentFile(stream.getvalue(),name=f'avatar-{person.pk or "new"}-{uuid4().hex}.jpg')
        normalized._aya_normalized_avatar=True
        person.photo=normalized
    check_allowance(person,person.photo.size)


def is_referenced(name, path):
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if not isinstance(field,models.FileField): continue
            try:
                if Path(field.storage.path(name)).resolve()!=path: continue
            except NotImplementedError:
                return True  # Unknown storage: retain the file rather than guess.
            if model._default_manager.filter(**{field.name:name}).exists(): return True
    return False


def archive_unused(name, owner='legacy'):
    """Move bytes intact outside public media; retain a private restoration manifest."""
    public, private=roots()
    if str(owner)!='legacy' and not str(owner).isdigit(): raise ValueError('Invalid archive owner')
    source=Path(settings.MEDIA_ROOT).absolute()/name
    if (source.resolve()!=source or source.is_symlink() or not source.is_relative_to(public)
            or not source.is_file()): return False
    with transaction.atomic():
        if is_referenced(name,source): return False
        folder=private/str(owner);folder.mkdir(mode=0o750,parents=True,exist_ok=True)
        if folder.resolve()!=folder: raise ValueError('Invalid archive path')
        identity=uuid4().hex
        target=folder/(identity+source.suffix.lower())
        with source.open('rb') as stream: checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        metadata={'original':name,'file':target.name,'sha256':checksum,'bytes':source.stat().st_size,
                  'archived_at':timezone.now().isoformat()}
        record=folder/(identity+'.json')
        with record.open('x',encoding='utf-8') as stream:
            json.dump(metadata,stream);stream.flush();os.fsync(stream.fileno())
        record.chmod(0o640)
        os.replace(source,target)
        target.chmod(0o640)
        return True


def retire_safely(name, owner):
    try: archive_unused(name,owner)
    except Exception:
        # Profile changes have already committed; never turn successful saving into a 500.
        # A later dry-run/apply command can retry. Bytes are never deliberately destroyed.
        logger.warning('Deferred avatar archival requires an AYA storage check.')


@contextmanager
def updating(person, update_fields=None):
    if update_fields is not None and 'photo' not in update_fields:
        yield;return
    previous = person.__class__.objects.filter(pk=person.pk).values_list('photo',flat=True).first() if person.pk else ''
    pending=bool(person.photo and not getattr(person.photo,'_committed',True))
    if not pending and (previous or '')==(person.photo.name or ''):
        yield;return
    with transaction.atomic():
        if person.pk:
            previous=person.__class__.objects.select_for_update().filter(pk=person.pk).values_list('photo',flat=True).first()
        if pending:
            try: prepare(person)
            except ValidationError as error: raise ValidationError({'photo':error.messages}) from error
        yield
        if pending:
            from .journal import emit
            emit('action',UPLOAD_SECTION,'Обновлена фотография профиля',object_id=person.pk,
                 after={'target_name':str(person),'target_type':'users.User','bytes':person.photo.size},private=True)
        if previous and previous!=person.photo.name:
            transaction.on_commit(lambda name=previous,owner=person.pk:retire_safely(name,owner))
