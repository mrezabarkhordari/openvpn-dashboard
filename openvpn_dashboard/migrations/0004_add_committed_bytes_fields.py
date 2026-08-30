# Generated migration for live usage tracking
# Adds committed_bytes_sent and committed_bytes_received to ConnectionSession
# These fields track how much usage has been committed to Account totals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('openvpn_dashboard', '0003_setting'),
    ]

    operations = [
        migrations.AddField(
            model_name='connectionsession',
            name='committed_bytes_sent',
            field=models.BigIntegerField(default=0, help_text='Bytes sent already committed to account totals'),
        ),
        migrations.AddField(
            model_name='connectionsession',
            name='committed_bytes_received',
            field=models.BigIntegerField(default=0, help_text='Bytes received already committed to account totals'),
        ),
        migrations.AlterField(
            model_name='connectionsession',
            name='usage_committed',
            field=models.BooleanField(default=False, help_text='Whether final usage has been added to account totals'),
        ),
    ]




