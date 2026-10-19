"""Canonical profile links and plain, print-ready QR codes (also reusable for cards)."""
from io import BytesIO
from functools import lru_cache
from urllib.parse import urlsplit

import qrcode
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


def public_site_url():
    value = str(getattr(settings, 'PUBLIC_SITE_URL', '')).strip().rstrip('/')
    try:
        parsed = urlsplit(value)
        parsed.port  # Validate malformed ports too.
        URLValidator(schemes=['https'])(value)
    except (ValueError, ValidationError) as error:
        raise ImproperlyConfigured('Укажите корректный PUBLIC_SITE_URL для QR-кодов.') from error
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ImproperlyConfigured('PUBLIC_SITE_URL должен быть HTTPS-адресом сайта без пути, параметров и учётных данных.')
    return value


def profile_url(person):
    if not person.pk:
        raise ValueError('Профиль должен быть сохранён перед созданием QR-кода.')
    return public_site_url() + reverse('public_profile', kwargs={'pk': person.pk})


def png_for_profile(person):
    return _png_for_url(profile_url(person))


@lru_cache(maxsize=256)
def _png_for_url(url):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_Q, box_size=16, border=4)
    code.add_data(url)
    code.make(fit=True)
    image = code.make_image(fill_color='black', back_color='white')
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


@never_cache
@require_GET
def profile_qr(request, pk):
    from .models import User
    from .views import is_privileged_viewer
    from .journal import emit
    person = get_object_or_404(User, pk=pk)
    if person.is_superuser:
        raise Http404
    if not (person.is_approved or person.candidate_approved) and request.user != person and not is_privileged_viewer(request.user):
        raise Http404
    download = request.GET.get('download') == '1'
    response = HttpResponse(png_for_profile(person), content_type='image/png')
    response['Content-Disposition'] = ('attachment' if download else 'inline') + f'; filename="aya-profile-{person.pk}.png"'
    response['X-Content-Type-Options'] = 'nosniff'
    emit('action' if download else 'view', 'profile_qr', 'Скачал QR-код профиля' if download else 'Открыл QR-код профиля',
         object_id=person.pk, after={'target_name': str(person), 'target_type': 'users.User', 'path': request.path}, private=True)
    return response
