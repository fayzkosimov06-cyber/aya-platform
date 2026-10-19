"""Shared authentication policy for production, development and isolated tests."""
from datetime import timedelta

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_HANDLER = "axes.handlers.database.AxesDatabaseHandler"
# Count across login pages, browsers and source addresses, but never lock a shared IP.
# Keep a per-source rule and an aggregate identity rule. The latter prevents IP rotation;
# neither rule is an IP-only lockout that could block other students on shared Wi-Fi.
AXES_LOCKOUT_PARAMETERS = ["username", ["username", "ip_address"]]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=10)
AXES_RESET_ON_SUCCESS = True
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
AXES_USERNAME_CALLABLE = "users.login_security.normalized_username"
AXES_CLIENT_IP_CALLABLE = "users.login_security.client_ip"
AXES_LOCKOUT_CALLABLE = "users.login_security.lockout_response"
AXES_HTTP_RESPONSE_CODE = 429
# AYA already records successful authentication in its private journal.
AXES_DISABLE_ACCESS_LOG = True
AXES_ENABLE_ACCESS_FAILURE_LOG = False
AXES_SENSITIVE_PARAMETERS = [
    "username", "ip_address", "password", "password1", "password2",
    "csrfmiddlewaretoken", "next", "token", "secret", "secret_key", "authorization",
]
