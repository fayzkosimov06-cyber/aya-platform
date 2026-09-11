from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('events', '0009_merge_20260309_1503')]

    # Two merged branches added the same named constraint. Remove it ONCE:
    # Django removes both state entries and SQLite rebuilds the table preserving
    # rows and unique_together. Then restore one named constraint.
    operations = [
        migrations.RemoveConstraint(model_name='eventhero', name='unique_event_hero_per_user'),
        migrations.AddConstraint(model_name='eventhero', constraint=models.UniqueConstraint(fields=('event', 'user'), name='unique_event_hero_per_user')),
    ]
