# aya_platform/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
import os # <-- ИСПРАВЛЕНИЕ: ДОБАВЛЕНА ЭТА СТРОКА

urlpatterns = [
    path('superadmin/', admin.site.urls), 
    path('events/', include('events.urls')),
    path('', include('users.urls')),
]

# Этот блок кода КРИТИЧЕСКИ ВАЖЕН для отображения картинок и стилей в режиме разработки
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Используем os.path.join для корректного пути к статике
    urlpatterns += static(settings.STATIC_URL, document_root=os.path.join(settings.BASE_DIR, 'static'))