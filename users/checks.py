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
