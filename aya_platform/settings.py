# aya_platform/settings.py
from pathlib import Path
import os

# Определяем базовую папку проекта
BASE_DIR = Path(__file__).resolve().parent.parent

# ВАЖНО: В продакшене этот ключ должен быть секретным.
# Для бесплатного хостинга пока оставляем как есть.
SECRET_KEY = 'django-insecure-ваша-секретная-фраза-здесь'

# DEBUG = True оставляем включенным для первого запуска, 
# чтобы видеть ошибки, если они возникнут. Потом выключим.
DEBUG = True

# Разрешаем доступ с любого адреса (нужно для PythonAnywhere)
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Наши приложения
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
        'DIRS': [BASE_DIR / 'templates'], # Указываем папку с шаблонами
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'users.context_processors.notifications_processor', # Наш процессор уведомлений
            ],
        },
    },
]

WSGI_APPLICATION = 'aya_platform.wsgi.application'

# База данных (SQLite)
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3', 
        'NAME': BASE_DIR / 'db.sqlite3'
    }
}

# Локализация
LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Asia/Dushanbe'
USE_I18N = True
USE_TZ = True

# --- НАСТРОЙКИ СТАТИЧЕСКИХ ФАЙЛОВ И МЕДИА ---

# URL, по которому доступны статические файлы (CSS, JS, картинки оформления)
STATIC_URL = '/static/'

# Папки, где Django ищет статику во время разработки
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# Папка, куда Django СОБЕРЕТ всю статику при деплое (команда collectstatic)
# Это критически важно для хостинга!
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# URL для пользовательских медиа-файлов (аватарки, фото отчетов)
MEDIA_URL = '/media/'

# Папка на диске для медиа-файлов
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# --- КОНЕЦ НАСТРОЕК ФАЙЛОВ ---

# Настройки входа/выхода
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'home'

# Наша кастомная модель пользователя
AUTH_USER_MODEL = 'users.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'