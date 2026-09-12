from django.db import migrations


def migrate_assignments(apps,schema_editor):
    User=apps.get_model('users','User');School=apps.get_model('users','School');Teacher=apps.get_model('users','SchoolTeacher')
    # The owner confirmed every legacy leader account is a student.
    User.objects.filter(role='leader').update(role='volunteer')
    for direction in apps.get_model('users','Direction').objects.all():
        direction.user_set.add(*direction.leaders.all())
    for school in School.objects.all():
        for person in school.leaders.all():
            if not Teacher.objects.filter(school=school,member=person).exists():
                Teacher.objects.create(school=school,member=person,name=f'{person.last_name} {person.first_name}'.strip() or person.username)
            school.members.add(person)
        for teacher in Teacher.objects.filter(school=school,member__isnull=False):
            school.leaders.add(teacher.member);school.members.add(teacher.member)
        if school.direction_id:school.direction.user_set.add(*school.members.all())

class Migration(migrations.Migration):
    dependencies=[('users','0037_school_active_alter_user_role_pointproposal')]
    operations=[migrations.RunPython(migrate_assignments,migrations.RunPython.noop)]
