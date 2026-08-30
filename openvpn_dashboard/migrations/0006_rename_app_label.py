# DB-safe app rename: ui_ovpn -> openvpn_ui.
# Does not rename or drop application tables (they stay ui_ovpn_*).

from django.db import migrations


def forwards(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentType.objects.filter(app_label='ui_ovpn').update(app_label='openvpn_ui')
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE django_migrations SET app = %s WHERE app = %s",
            ['openvpn_ui', 'ui_ovpn'],
        )


def backwards(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentType.objects.filter(app_label='openvpn_ui').update(app_label='ui_ovpn')
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE django_migrations SET app = %s WHERE app = %s AND name != %s",
            ['ui_ovpn', 'openvpn_ui', '0006_rename_app_label'],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('openvpn_dashboard', '0005_add_server_daily_stats'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
