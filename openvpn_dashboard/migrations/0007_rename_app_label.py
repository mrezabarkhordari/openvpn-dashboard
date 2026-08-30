# DB-safe app rename: openvpn_ui -> openvpn_dashboard.
# Does not rename or drop application tables (they stay ui_ovpn_*).

from django.db import migrations


def forwards(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentType.objects.filter(app_label='openvpn_ui').update(app_label='openvpn_dashboard')
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE django_migrations SET app = %s WHERE app = %s",
            ['openvpn_dashboard', 'openvpn_ui'],
        )


def backwards(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentType.objects.filter(app_label='openvpn_dashboard').update(app_label='openvpn_ui')
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE django_migrations SET app = %s WHERE app = %s AND name != %s",
            ['openvpn_ui', 'openvpn_dashboard', '0007_rename_app_label'],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('openvpn_dashboard', '0006_rename_app_label'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
