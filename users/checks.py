from django.core.checks import Error,register
from django.conf import settings
@register()
def control_middleware_check(app_configs,**kwargs):
    mw=list(settings.MIDDLEWARE)
    name='users.control_middleware.ControlMiddleware'
    auth='django.contrib.auth.middleware.AuthenticationMiddleware'
    if name not in mw or auth not in mw or mw.index(name)<mw.index(auth):
        return [Error('Добавьте users.control_middleware.ControlMiddleware после AuthenticationMiddleware. Запустите python configure_controls.py.',id='aya.E015')]
    return []


@register()
def profile_qr_url_check(app_configs, **kwargs):
    from django.core.exceptions import ImproperlyConfigured
    from .profile_qr import public_site_url
    try:
        public_site_url()
    except ImproperlyConfigured as error:
        return [Error(str(error), id='aya.E016')]
    return []


@register()
def private_card_storage_check(app_configs, **kwargs):
    from pathlib import Path
    private = Path(settings.CARD_PRIVATE_ROOT).resolve()
    roots = [Path(settings.MEDIA_ROOT).resolve(), Path(settings.STATIC_ROOT).resolve()]
    roots += [Path(p).resolve() for p in settings.STATICFILES_DIRS]
    if any(private == root or private.is_relative_to(root) or root.is_relative_to(private) for root in roots):
        return [Error('CARD_PRIVATE_ROOT должен находиться вне публичных media и static.', id='aya.E017')]
    return []
