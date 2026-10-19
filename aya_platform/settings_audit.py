"""Isolated test settings: no production imports, credentials, database or email."""
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
import tempfile
AUDIT_RUNTIME = Path(tempfile.mkdtemp(prefix="aya-audit-"))
SECRET_KEY = "isolated-audit-tests-no-production-secret"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
INSTALLED_APPS = ["django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles", "users.apps.UsersConfig", "events.apps.EventsConfig"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "users.control_middleware.ControlMiddleware", "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware"]
ROOT_URLCONF = "aya_platform.urls"
TEMPLATES = [{"BACKEND":"django.template.backends.django.DjangoTemplates", "DIRS":[BASE_DIR / "templates"], "APP_DIRS":True, "OPTIONS":{"context_processors":["django.template.context_processors.debug", "django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages", "users.context_processors.notifications_processor"]}}]
DATABASES = {"default":{"ENGINE":"django.db.backends.sqlite3", "NAME":":memory:"}}
AUTH_USER_MODEL = "users.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Asia/Dushanbe"
USE_TZ = True
USE_I18N = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = AUDIT_RUNTIME / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = AUDIT_RUNTIME / "test-media"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
AUTH_PASSWORD_VALIDATORS = [{"NAME":"django.contrib.auth.password_validation.UserAttributeSimilarityValidator"}, {"NAME":"django.contrib.auth.password_validation.MinimumLengthValidator"}, {"NAME":"django.contrib.auth.password_validation.CommonPasswordValidator"}, {"NAME":"django.contrib.auth.password_validation.NumericPasswordValidator"}]
