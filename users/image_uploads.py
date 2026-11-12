"""Bound public image uploads before decoding or storing them.

Profile portraits and private card assets have their own stricter policies.
These limits cover covers, logos, report galleries and editorial images.
"""
import warnings

from django import forms
from PIL import Image

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_BATCH_FILES = 20
MAX_BATCH_BYTES = 32 * 1024 * 1024


class BoundedImageField(forms.ImageField):
    def to_python(self, data):
        if data not in self.empty_values and data is not False and getattr(data, 'size', 0) > MAX_IMAGE_BYTES:
            raise forms.ValidationError('Изображение должно быть не больше 8 МБ.', code='image_size')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            image = super().to_python(data)
        if image is not None and image is not False:
            width, height = image.image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise forms.ValidationError('Изображение должно содержать не больше 20 миллионов пикселей.', code='image_pixels')
        return image


def clean_image_batch(files, field=None):
    """Validate the complete batch before any caller writes its first file."""
    if len(files) > MAX_BATCH_FILES:
        raise forms.ValidationError('За один раз можно добавить не больше 20 фотографий.', code='image_count')
    if sum(file.size for file in files) > MAX_BATCH_BYTES:
        raise forms.ValidationError('Общий размер фотографий должен быть не больше 32 МБ.', code='image_batch_size')
    field = field or BoundedImageField()
    return [field.clean(file) for file in files]
