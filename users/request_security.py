"""Safe CSRF recovery and structured rejection diagnostics. Never replay a POST."""
from urllib.parse import urlsplit

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import requires_csrf_token


def rejection_details(reason):
    # Raw Django reasons can contain an untrusted Origin/Referer. Store fixed labels only.
    if reason == 'CSRF cookie not set.':
        code = 'browser_cookie_missing'
        message = 'Браузер не передал защитные cookie. Откройте форму заново; если ошибка повторяется, разрешите cookie для сайта или откройте его в обычном браузере.'
    elif reason == 'CSRF token missing.':
        code = 'form_check_missing'
        message = 'В запросе отсутствовал код проверки формы. Откройте форму заново и повторите действие.'
    elif reason.startswith('CSRF cookie has'):
        code = 'browser_cookie_invalid'
        message = 'Защитные cookie браузера повреждены. Откройте форму заново, чтобы получить новый код проверки.'
    elif reason.startswith('Origin checking failed'):
        code = 'origin_mismatch'
        message = 'Адрес отправки формы не совпал с адресом сайта. Откройте форму на этом сайте заново.'
    elif reason.startswith('Referer checking failed'):
        code = 'referrer_missing' if 'no Referer' in reason else 'referrer_mismatch'
        message = 'Браузер не подтвердил адрес страницы с формой. Откройте сайт в обычном браузере и повторите действие.'
    elif 'incorrect' in reason or 'invalid characters' in reason:
        code = 'form_check_mismatch'
        message = 'Код проверки формы устарел или не совпал с кодом браузера. Это возможно после входа в другой вкладке или возврата к старой странице.'
    else:
        code = 'form_check_failed'
        message = 'Запрос не прошёл проверку безопасности формы. Откройте форму заново и повторите действие.'
    return {'failure_kind': 'csrf', 'failure_code': code, 'reason': message}


def recovery_url(request):
    """Local GET navigation only; never accept an arbitrary external return address."""
    match = getattr(request, 'resolver_match', None)
    name = getattr(match, 'url_name', '')
    if name in {'reveal_phone', 'reveal_birthday', 'open_profile_photo'}:
        return reverse('public_profile', args=[match.kwargs['pk']])
    if name == 'training_progress':
        return reverse('training_help')
    if name == 'logout':
        return reverse('home')
    if name not in {'record_search', 'birthday_seen'} and match:
        return request.path
    referrer = request.META.get('HTTP_REFERER', '')
    if url_has_allowed_host_and_scheme(referrer, {request.get_host()}, require_https=request.is_secure()):
        path = urlsplit(referrer).path
        try:
            resolve(path)
            if path.startswith('/') and not path.startswith('//'):
                return path
        except Resolver404:
            pass
    return reverse('home')


@never_cache
@requires_csrf_token
def csrf_failure(request, reason=''):
    request.aya_rejection = rejection_details(reason)
    context = {'recovery_url': recovery_url(request), 'explanation': request.aya_rejection['reason']}
    wants_json = 'application/json' in request.headers.get('Accept', '') or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if wants_json:
        response = JsonResponse({'error': 'csrf', 'message': context['explanation'], 'recovery_url': context['recovery_url']}, status=403)
    else:
        response = render(request, 'users/csrf_failure.html', context, status=403)
    response['X-AYA-Error'] = 'csrf'
    return response
