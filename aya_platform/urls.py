# aya_platform/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.templatetags.static import static as static_url
from django.views.generic import RedirectView
import os # <-- ИСПРАВЛЕНИЕ: ДОБАВЛЕНА ЭТА СТРОКА

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url=static_url('img/aya-logo-2026.png'), permanent=True), name='site_icon'),
    path('superadmin/', admin.site.urls), 
    path('events/', include('events.urls')),
    path('', include('users.urls')),
]

# Этот блок кода КРИТИЧЕСКИ ВАЖЕН для отображения картинок и стилей в режиме разработки
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Используем os.path.join для корректного пути к статике
    urlpatterns += static(settings.STATIC_URL, document_root=os.path.join(settings.BASE_DIR, 'static'))
