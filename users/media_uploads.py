from pathlib import Path
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import ValidationError


def video_upload_path(instance, filename):
    return 'videos/'+uuid4().hex+Path(filename).suffix.lower()


def validate_video(file):
    limit=getattr(settings,'AYA_MAX_VIDEO_MB',100)*1024*1024
    if file.size>limit: raise ValidationError(f'Видео слишком большое. Максимум {limit//1024//1024} МБ.')
    suffix=Path(file.name).suffix.lower()
    if suffix not in {'.mp4','.webm'}: raise ValidationError('Загрузите видео MP4 или WebM.')
    position=file.tell()
    try:
        file.seek(0);header=file.read(64)
    finally:file.seek(position)
    valid=(suffix=='.mp4' and len(header)>=12 and header[4:8]==b'ftyp') or (suffix=='.webm' and header[:4]==b'\x1aE\xdf\xa3' and b'webm' in header.lower())
    if not valid: raise ValidationError('Содержимое не соответствует формату MP4/WebM. Экспортируйте видео заново.')
