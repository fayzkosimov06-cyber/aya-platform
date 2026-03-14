from django.db import migrations, models


def _column_names(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        return {col.name for col in schema_editor.connection.introspection.get_table_description(cursor, table_name)}


def ensure_volunteervisit_comment(apps, schema_editor):
    table_name = 'users_volunteervisit'
    vendor = schema_editor.connection.vendor
    columns = _column_names(schema_editor, table_name)

    if 'comment' not in columns:
        if vendor == 'postgresql':
            schema_editor.execute(
                f"ALTER TABLE {schema_editor.quote_name(table_name)} ADD COLUMN comment text NOT NULL DEFAULT ''"
            )
        else:
            schema_editor.execute(
                f"ALTER TABLE {schema_editor.quote_name(table_name)} ADD COLUMN comment text NOT NULL DEFAULT ''"
            )
    else:
        # Make existing DBs with a manual column safe for empty comments.
        if vendor == 'postgresql':
            schema_editor.execute(
                f"ALTER TABLE {schema_editor.quote_name(table_name)} ALTER COLUMN comment SET DEFAULT ''"
            )
            schema_editor.execute(
                f"UPDATE {schema_editor.quote_name(table_name)} SET comment = '' WHERE comment IS NULL"
            )
            schema_editor.execute(
                f"ALTER TABLE {schema_editor.quote_name(table_name)} ALTER COLUMN comment SET NOT NULL"
            )
        else:
            schema_editor.execute(
                f"UPDATE {schema_editor.quote_name(table_name)} SET comment = '' WHERE comment IS NULL"
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0026_user_is_old_volunteer_and_contact_platform'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(ensure_volunteervisit_comment, noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='volunteervisit',
                    name='comment',
                    field=models.TextField(blank=True, default='', verbose_name='Комментарий модератора'),
                ),
            ],
        ),
    ]
