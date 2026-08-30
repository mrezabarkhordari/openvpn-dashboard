"""
Django management command to run the OpenVPN usage collector.

Usage:
    python manage.py collect_usage
    python manage.py collect_usage --interval 2
    python manage.py collect_usage --commit-interval 10
    python manage.py collect_usage --status-log /var/log/openvpn/status.log

Environment Variables:
    USAGE_COLLECTOR_INTERVAL: Poll interval in seconds (default: 2.0)
    USAGE_COMMIT_INTERVAL: Commit interval in seconds (default: 10.0)
    OPENVPN_STATUS_LOG: Path to status log file
"""

import os
from django.core.management.base import BaseCommand, CommandError
from openvpn_dashboard.services.usage_collector import UsageCollector


class Command(BaseCommand):
    help = 'Run the OpenVPN usage collector daemon'
    
    def add_arguments(self, parser):
        # Get defaults from environment variables
        default_interval = float(os.environ.get('USAGE_COLLECTOR_INTERVAL', '2.0'))
        default_commit_interval = float(os.environ.get('USAGE_COMMIT_INTERVAL', '10.0'))
        default_status_log = os.environ.get('OPENVPN_STATUS_LOG', '/var/log/openvpn/status.log')
        
        parser.add_argument(
            '--interval',
            type=float,
            default=default_interval,
            help=f'Poll interval in seconds (default: {default_interval}, env: USAGE_COLLECTOR_INTERVAL)'
        )
        parser.add_argument(
            '--commit-interval',
            type=float,
            default=default_commit_interval,
            help=f'Commit interval in seconds (default: {default_commit_interval}, env: USAGE_COMMIT_INTERVAL)'
        )
        parser.add_argument(
            '--status-log',
            type=str,
            default=default_status_log,
            help=f'Path to OpenVPN status log file (default: {default_status_log})'
        )
        parser.add_argument(
            '--no-recover',
            action='store_true',
            help='Skip session recovery on startup'
        )
    
    def handle(self, *args, **options):
        interval = options['interval']
        commit_interval = options['commit_interval']
        status_log = options['status_log']
        skip_recover = options['no_recover']
        
        self.stdout.write(
            self.style.SUCCESS(f'Starting usage collector...')
        )
        self.stdout.write(f'  Status log: {status_log}')
        self.stdout.write(f'  Poll interval: {interval}s')
        self.stdout.write(f'  Commit interval: {commit_interval}s')
        
        if not os.path.exists(status_log):
            self.stdout.write(
                self.style.WARNING(
                    f'Status log not found at {status_log}. '
                    'Collector will wait for it to appear.'
                )
            )
        
        # Create collector with both intervals
        collector = UsageCollector(
            status_log_path=status_log,
            poll_interval=interval,
            commit_interval=commit_interval
        )
        
        # Recover sessions unless skipped
        if not skip_recover:
            self.stdout.write('Recovering existing sessions...')
            collector.recover_sessions()
        
        self.stdout.write(
            self.style.SUCCESS('Collector running. Press Ctrl+C to stop.')
        )
        
        try:
            collector.run()
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\nStopping collector...'))
        
        self.stdout.write(self.style.SUCCESS('Collector stopped.'))

