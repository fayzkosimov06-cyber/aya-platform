from django.db import migrations, models


def _column_names(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        return {col.name for col in schema_editor.connection.introspection.get_table_description(cursor, table_name)}


def ensure_compatibility_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor

    user_table = 'users_user'
    contact_table = 'users_aboutcontactlink'

    user_columns = _column_names(schema_editor, user_table)
    if 'is_old_volunteer' not in user_columns:
        if vendor == 'postgresql':
            schema_editor.execute(f"ALTER TABLE {schema_editor.quote_name(user_table)} ADD COLUMN is_old_volunteer boolean NOT NULL DEFAULT FALSE")
        else:
            schema_editor.execute(f"ALTER TABLE {schema_editor.quote_name(user_table)} ADD COLUMN is_old_volunteer bool NOT NULL DEFAULT 0")

    contact_columns = _column_names(schema_editor, contact_table)
    if 'platform' not in contact_columns:
        if vendor == 'postgresql':
            schema_editor.execute(f"ALTER TABLE {schema_editor.quote_name(contact_table)} ADD COLUMN platform varchar(32) NOT NULL DEFAULT 'custom'")
        else:
            schema_editor.execute(f"ALTER TABLE {schema_editor.quote_name(contact_table)} ADD COLUMN platform varchar(32) NOT NULL DEFAULT 'custom'")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0025_alter_user_candidate_approved_aboutcontactlink_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(ensure_compatibility_columns, noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name='user',
                    name='is_old_volunteer',
                    field=models.BooleanField(default=False, verbose_name='Старый волонтёр'),
                ),
                migrations.AddField(
                    model_name='aboutcontactlink',
                    name='platform',
                    field=models.CharField(
                        choices=[
                            ('instagram', 'Instagram'),
                            ('facebook', 'Facebook'),
                            ('telegram', 'Telegram'),
                            ('youtube', 'YouTube'),
                            ('tiktok', 'TikTok'),
                            ('whatsapp', 'WhatsApp'),
                            ('website', 'Сайт'),
                            ('email', 'Email'),
                            ('phone', 'Телефон'),
                            ('custom', 'Другое'),
                        ],
                        default='custom',
                        max_length=32,
                        verbose_name='Платформа',
                    ),
                ),
                migrations.AlterField(
                    model_name='aboutcontactlink',
                    name='icon',
                    field=models.CharField(blank=True, default='', max_length=120),
                ),
            ],
        ),
    ]
