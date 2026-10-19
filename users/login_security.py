"""Presentation and trusted proxy integration for django-axes, not authentication."""
from ipaddress import ip_address
from math import ceil
from unicodedata import normalize

from django.conf import settings
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme


def normalized_username(request, credentials=None):
    data = credentials if credentials is not None else request.POST
    # Match Django's UsernameField normalization. Real authentication stays case sensitive.
    return normalize("NFKC", str(data.get("username") or "")).strip()[:255]


def client_ip(request):
    """Only the local AYA Nginx may supply X-Real-IP; it overwrites that header."""
    try:
        peer = ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return None
    if str(peer) in {"127.0.0.1", "::1"}:
        try:
            return str(ip_address(request.META.get("HTTP_X_REAL_IP", "")))
        except ValueError:
            pass
    # Never take the leftmost, client-controlled X-Forwarded-For value.
    return str(peer)


def retry_seconds(request, credentials=None):
    """Time until enough current failure buckets expire to allow another attempt."""
    from axes.models import AccessAttempt

    now = timezone.now()
    cooloff = settings.AXES_COOLOFF_TIME
    attempts = list(AccessAttempt.objects.filter(
        username=normalized_username(request, credentials),
        attempt_time__gte=now - cooloff,
    ).order_by("attempt_time").values_list("attempt_time", "failures_since_start"))
    remaining = sum(count for _, count in attempts)
    for when, count in attempts:
        remaining -= count
        if remaining < settings.AXES_FAILURE_LIMIT:
            return max(1, ceil((when + cooloff - now).total_seconds()))
    return max(1, ceil(cooloff.total_seconds()))


def lockout_response(request, original_response=None, credentials=None):
    # Reuse the actual login view's context, including its safe next URL and admin context.
    context = dict(getattr(original_response, "context_data", None) or {})
    form = context.get("form")
    if form is not None:
        context["form"] = type(form)(
            request=request, initial={"username": normalized_username(request, credentials)},
        )
    else:
        from django.contrib.auth.forms import AuthenticationForm
        context["form"] = AuthenticationForm(request=request)
    seconds = retry_seconds(request, credentials)
    context["login_pause"] = {"seconds": seconds, "display": f"{seconds // 60}:{seconds % 60:02d}"}
    context["login_again_url"] = request.path
    # Preserve the route's own safe redirect, never arbitrary POST next data.
    destination = context.get("next", "")
    if destination and not url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        context["next"] = ""
    name = getattr(getattr(request, "resolver_match", None), "url_name", "")
    template = getattr(original_response, "template_name", None) or (
        "admin/aya_login.html" if request.path.startswith(reverse("admin:index"))
        else "users/staff_login.html" if name == "staff_login"
        else "users/login.html"
    )
    response = render(request, template, context, status=429)
    response["Retry-After"] = str(seconds)
    response["Cache-Control"] = "no-store, private"
    return response
