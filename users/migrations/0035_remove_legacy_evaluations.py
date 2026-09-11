from django.db import migrations


def remove_legacy(apps, schema_editor):
    apps.get_model('events', 'EventEvaluation').objects.using(schema_editor.connection.alias).all().delete()


class Migration(migrations.Migration):
    dependencies = [('users', '0034_contributionwork_submission')]
    operations = [migrations.RunPython(remove_legacy)]
