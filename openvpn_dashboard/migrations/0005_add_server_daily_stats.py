# Generated migration for ServerDailyStats and DailyUsageStats

import datetime
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('openvpn_dashboard', '0004_add_committed_bytes_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyUsageStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(help_text='The calendar date for these statistics')),
                ('bytes_sent', models.BigIntegerField(default=0, help_text='Total bytes sent (upload) for this day')),
                ('bytes_received', models.BigIntegerField(default=0, help_text='Total bytes received (download) for this day')),
                ('session_count', models.IntegerField(default=0, help_text='Number of sessions on this day')),
                ('total_session_duration', models.DurationField(default=datetime.timedelta(0), help_text='Total duration of all sessions')),
                ('avg_session_duration', models.DurationField(blank=True, help_text='Average session duration', null=True)),
                ('first_connection_time', models.DateTimeField(blank=True, help_text='Time of first connection', null=True)),
                ('last_connection_time', models.DateTimeField(blank=True, help_text='Time of last disconnection', null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_stats', to='openvpn_dashboard.account')),
            ],
            options={
                'db_table': 'ui_ovpn_dailyusagestats',
                'ordering': ['-date', 'account'],
                'indexes': [
                    models.Index(fields=['date', 'account'], name='ui_ovpn_dai_date_34de36_idx'),
                    models.Index(fields=['account', 'date'], name='ui_ovpn_dai_account_d0ba3e_idx'),
                    models.Index(fields=['-date'], name='ui_ovpn_dai_date_d2f893_idx'),
                ],
                'unique_together': {('account', 'date')},
            },
        ),
        migrations.CreateModel(
            name='ServerDailyStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(help_text='The calendar date for these statistics', unique=True)),
                ('total_bytes_sent', models.BigIntegerField(default=0, help_text='Total bytes sent (upload) across all accounts')),
                ('total_bytes_received', models.BigIntegerField(default=0, help_text='Total bytes received (download) across all accounts')),
                ('active_accounts', models.IntegerField(default=0, help_text='Number of accounts with activity on this day')),
                ('total_accounts', models.IntegerField(default=0, help_text='Total number of accounts on this day')),
                ('total_sessions', models.IntegerField(default=0, help_text='Total number of sessions across all accounts')),
                ('total_session_duration', models.DurationField(default=datetime.timedelta(0), help_text='Total duration of all sessions')),
                ('avg_session_duration', models.DurationField(blank=True, help_text='Average session duration', null=True)),
                ('first_connection_time', models.DateTimeField(blank=True, help_text='Time of first connection on server', null=True)),
                ('last_connection_time', models.DateTimeField(blank=True, help_text='Time of last disconnection on server', null=True)),
                ('peak_concurrent_sessions', models.IntegerField(default=0, help_text='Maximum concurrent sessions at any point')),
                ('peak_bytes_per_second', models.BigIntegerField(default=0, help_text='Peak transfer rate (bytes/sec)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'ui_ovpn_serverdailystats',
                'ordering': ['-date'],
                'indexes': [
                    models.Index(fields=['-date'], name='ui_ovpn_ser_date_e517b3_idx'),
                    models.Index(fields=['date'], name='ui_ovpn_ser_date_5cee70_idx'),
                ],
            },
        ),
    ]

