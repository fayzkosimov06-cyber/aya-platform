from django.db import migrations


BLOCKED_ROLES = {'leader', 'worker', 'head_admin'}


def cleanup_event_participants_and_roles(apps, schema_editor):
    User = apps.get_model('users', 'User')
    Event = apps.get_model('events', 'Event')
    EventHero = apps.get_model('events', 'EventHero')
    EventEvaluation = apps.get_model('events', 'EventEvaluation')

    blocked_users = list(User.objects.filter(is_superuser=True))
    blocked_users += list(User.objects.filter(role__in=list(BLOCKED_ROLES)))
    blocked_ids = {u.id for u in blocked_users}

    through = Event.participants.through
    if blocked_ids:
        through.objects.filter(user_id__in=blocked_ids).delete()

    participant_pairs = set(through.objects.values_list('event_id', 'user_id'))

    # Удаляем героев и оценки, если пользователь не был зарегистрирован на мероприятие.
    for hero in EventHero.objects.all().order_by('id'):
        if (hero.event_id, hero.user_id) not in participant_pairs:
            hero.delete()

    for evaluation in EventEvaluation.objects.all().order_by('id'):
        if (evaluation.event_id, evaluation.volunteer_id) not in participant_pairs:
            evaluation.delete()

    # Удаляем дубли героев, оставляя последнюю запись.
    seen = set()
    for hero in EventHero.objects.order_by('event_id', 'user_id', '-id'):
        key = (hero.event_id, hero.user_id)
        if key in seen:
            hero.delete()
        else:
            seen.add(key)


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0006_eventevaluation'),
    ]

    operations = [
        migrations.RunPython(cleanup_event_participants_and_roles, migrations.RunPython.noop),
        migrations.AlterUniqueTogether(
            name='eventhero',
            unique_together={('event', 'user')},
        ),
    ]
