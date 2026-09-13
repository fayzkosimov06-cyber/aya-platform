from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from users.models import JournalEntry
class Command(BaseCommand):
    help='Удалить просмотры и поисковые запросы старше 90 дней; изменения сохраняются.'
    def handle(self,*args,**options):
        n,_=JournalEntry.objects.filter(category__in=['view','search'],created_at__lt=timezone.now()-timedelta(days=90)).delete()
        self.stdout.write(f'Удалено записей активности: {n}')
