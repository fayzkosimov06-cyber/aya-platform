# users/admin.py
from django.contrib import admin
from .models import User, Direction, School, ActivityPeriod, Notification, AboutPage

# Регистрируем все модели, чтобы Суперадмин мог управлять ими
admin.site.register(User)
admin.site.register(Direction)
admin.site.register(School)
admin.site.register(ActivityPeriod)
admin.site.register(Notification)
admin.site.register(AboutPage)