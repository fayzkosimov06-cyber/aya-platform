from django.db import migrations
import re

def copy_logs(apps,schema_editor):
    Audit=apps.get_model('users','AuditLog');Entry=apps.get_model('users','JournalEntry');User=apps.get_model('users','User')
    roots=set(User.objects.filter(is_superuser=True).values_list('pk',flat=True))
    for row in Audit.objects.all().iterator():
        action=re.sub(r'(?i)(password|token|secret|api[_-]?key)\s*[:=]\s*\S+',r'\1=[скрыто]',row.action)
        entry=Entry.objects.create(actor_id=row.actor_id,private=row.actor_id in roots or row.target_user_id in roots,category='action',section='Ранее записанные действия',action=action[:200],after={'description':action,'target':row.target_user_id})
        Entry.objects.filter(pk=entry.pk).update(created_at=row.created_at)

class Migration(migrations.Migration):
    dependencies=[('users','0040_permissions_and_private_journal')]
    operations=[migrations.RunPython(copy_logs,migrations.RunPython.noop)]
