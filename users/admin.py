# users/admin.py
from django.contrib import admin
from django.db import models
from .models import User, Direction, School, ActivityPeriod, Notification, AboutPage, AuditLog
from .image_uploads import BoundedImageField

admin.site.login_template = 'admin/aya_login.html'

@admin.register(User)
class AccountAdmin(admin.ModelAdmin):
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'is_superuser':
            kwargs['label'] = 'Полный доступ'
        return super().formfield_for_dbfield(db_field, request, **kwargs)

class PublicImageAdmin(admin.ModelAdmin):
    formfield_overrides = {models.ImageField: {'form_class': BoundedImageField}}


admin.site.register(Direction, PublicImageAdmin)
admin.site.register(School, PublicImageAdmin)
admin.site.register(ActivityPeriod)
admin.site.register(Notification)
admin.site.register(AboutPage, PublicImageAdmin)
admin.site.register(AuditLog)
