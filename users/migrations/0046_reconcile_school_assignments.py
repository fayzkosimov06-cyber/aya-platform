from django.db import migrations


def reconcile(apps, schema_editor):
    School = apps.get_model('users', 'School')
    Teacher = apps.get_model('users', 'SchoolTeacher')
    Club = apps.get_model('users', 'Club')
    for school in School.objects.all().iterator():
        for person in school.leaders.all():
            if not Teacher.objects.filter(school=school, member=person).exists():
                Teacher.objects.create(school=school, member=person,
                    name=('%s %s' % (person.first_name, person.last_name)).strip() or person.username)
        for teacher in Teacher.objects.filter(school=school, member__isnull=False):
            school.leaders.add(teacher.member_id)
            school.members.add(teacher.member_id)
        Club.objects.filter(school=school).update(direction_id=school.direction_id)


class Migration(migrations.Migration):
    dependencies = [('users', '0045_preserve_deleted_authors')]
    operations = [migrations.RunPython(reconcile, migrations.RunPython.noop)]
