# users/admin.py
from django.contrib import admin
from .models import User, Direction, School, ActivityPeriod, Notification, AboutPage, AuditLog

admin.site.login_template = 'admin/aya_login.html'

@admin.register(User)
class AccountAdmin(admin.ModelAdmin):
    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'is_superuser':
            kwargs['label'] = 'Полный доступ'
        return super().formfield_for_dbfield(db_field, request, **kwargs)

admin.site.register(Direction)
admin.site.register(School)
admin.site.register(ActivityPeriod)
admin.site.register(Notification)
admin.site.register(AboutPage)
admin.site.register(AuditLog)
