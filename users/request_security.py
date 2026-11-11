"""Safe CSRF recovery and structured rejection diagnostics. Never replay a POST."""
from urllib.parse import urlsplit

from django.http import JsonResponse
from django.shortcuts import render
from django.urls import Resolver404, resolve, reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import requires_csrf_token


QUERY_IDENTIFIERS = {
    'volunteer_list': ('direction',), 'school_catalog': ('direction',),
    'club_catalog': ('school','direction'), 'user_management': ('school','direction'),
    'card_list': ('year','course','school','direction','club'), 'card_create': ('user','year'), 'card_edit': ('user','year'),
    'points_quick': ('member','work','school','direction','club'),
    'points_works': ('school','direction','club'), 'volunteer_rating': ('school','direction','club'),
    'audit_log': ('actor','until'), 'journal_private': ('actor','until'), 'journal_activity': ('actor','until'),
    'event_create': ('directions','schools','clubs'),
    'my_profile': ('direction','school','club'), 'public_profile': ('direction','school','club'),
    'rating_history': ('direction','school','club'),
}


def oversized_record_path(path):
    # Run before URL resolution: Django's integer converter can raise on huge integers.
    return any(len(part)>19 and part.isascii() and part.isdecimal() for part in path.split('/'))


def validate_identifiers(request, route, kwargs):
    def check(value):
        text=str(value)
        # Other malformed form choices remain form errors. Guard numeric lookalikes
        # and oversized values that would otherwise reach int() or a DB driver.
        if text.isdigit():
            if text.isascii() and len(text)<=19 and not text.strip('0'):return
            positive_pk(text)
    for value in kwargs.values():
        if isinstance(value,int):check(value)
    for key in QUERY_IDENTIFIERS.get(route,()):
        for value in request.GET.getlist(key):check(value)
    if request.method=='POST':
        # These fields are inspected by permissions before ModelForm validation.
        for key in ('direction','school','member','leaders','events','directions','schools','clubs','lessons','actor'):
            for value in request.POST.getlist(key):check(value)


def protect_response(request, response):
    # Partial CSP: preserve existing inline scripts and permitted video providers.
    # A stricter script-src policy needs a separate migration to nonces.
    response.setdefault('Content-Security-Policy', "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'")
    if request.user.is_authenticated and not request.path.startswith(('/static/','/media/')):
        from django.utils.cache import patch_cache_control, patch_vary_headers
        patch_cache_control(response,private=True,no_store=True)
        patch_vary_headers(response,['Cookie'])


def positive_pk(value):
    """Reject malformed and oversized IDs before passing them to database drivers."""
    from django.http import Http404
    text = str(value)
    if not text.isascii() or not text.isdecimal() or len(text) > 19:
        raise Http404('Некорректный номер записи.')
    number = int(text)
    if not 1 <= number <= 9223372036854775807:
        raise Http404('Некорректный номер записи.')
    return number


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
