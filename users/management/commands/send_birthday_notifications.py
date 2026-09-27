from django.core.management.base import BaseCommand
from django.db.models import Q
from users.models import User
from users.birthdays import notify

class Command(BaseCommand):
    help='Создать уведомления о днях рождения сегодня и завтра; повторный запуск безопасен.'
    def handle(self, *args, **options):
        count=sum(notify(person) for person in User.objects.filter(is_active=True).filter(Q(is_superuser=True)|Q(role__in=['president','worker','head_admin'])))
        self.stdout.write(f'Создано уведомлений: {count}')
