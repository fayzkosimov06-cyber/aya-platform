# aya_platform/settings.py
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-ваша-секретная-фраза-здесь' # ЗАМЕНИТЕ НА СВОЮ
DEBUG = True
ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'users.apps.UsersConfig',
    'events.apps.EventsConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'aya_platform.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'users.context_processors.notifications_processor',
            ],
        },
    },
]

WSGI_APPLICATION = 'aya_platform.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Asia/Dushanbe'
USE_I18N = True
USE_TZ = True

# --- НАСТРОЙКИ ДЛЯ СТАТИЧЕСКИХ ФАЙЛОВ И ИЗОБРАЖЕНИЙ ---
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# --- ИЗМЕНЕНИЕ: ДОБАВЛЕНА ЭТА СТРОКА ---
# Эта папка будет создана автоматически для сбора всех статических файлов.
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles') 

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
# --- КОНЕЦ НАСТРОЕК ДЛЯ ФАЙЛОВ ---

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'
AUTH_USER_MODEL = 'users.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'