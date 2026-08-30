"""
Django management command to check for expired accounts and disable them.

Usage:
    python manage.py check_expired_accounts
    python manage.py check_expired_accounts --dry-run
    python manage.py check_expired_accounts --daemon --interval 3600

This command checks all active accounts and disables those whose expiration
date has passed. It can be run as a one-time check or as a daemon that
periodically checks for expired accounts.

Environment Variables:
    EXPIRATION_CHECK_INTERVAL: Check interval in seconds for daemon mode (default: 3600)
"""

import os
import time
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from openvpn_dashboard.models import Account
from openvpn_dashboard.services.utils import disable_openvpn_user

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check for expired accounts and disable them'
    
    def add_arguments(self, parser):
        default_interval = int(os.environ.get('EXPIRATION_CHECK_INTERVAL', '3600'))
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )
        parser.add_argument(
            '--daemon',
            action='store_true',
            help='Run continuously as a daemon'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=default_interval,
            help=f'Check interval in seconds for daemon mode (default: {default_interval})'
        )
    
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        daemon_mode = options['daemon']
        interval = options['interval']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made'))
        
        if daemon_mode:
            self.stdout.write(
                self.style.SUCCESS(f'Starting expiration checker daemon (interval: {interval}s)...')
            )
            self.stdout.write('Press Ctrl+C to stop.')
            
            try:
                while True:
                    self._check_expired_accounts(dry_run)
                    time.sleep(interval)
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING('\nStopping daemon...'))
        else:
            self._check_expired_accounts(dry_run)
    
    def _check_expired_accounts(self, dry_run: bool = False):
        """Check for expired accounts and disable them."""
        today = timezone.now().date()
        
        # Find active accounts that have expired
        expired_accounts = Account.objects.filter(
            status='active',
            expiration_date__lt=today
        )
        
        count = expired_accounts.count()
        
        if count == 0:
            self.stdout.write(f'[{timezone.now()}] No expired accounts found.')
            return
        
        self.stdout.write(
            self.style.WARNING(f'[{timezone.now()}] Found {count} expired account(s)')
        )
        
        for account in expired_accounts:
            days_expired = (today - account.expiration_date).days
            
            self.stdout.write(
                f'  - {account.account_number} (User: {account.user.name}) '
                f'expired {days_expired} day(s) ago'
            )
            
            if not dry_run:
                try:
                    # Update account status to expired
                    account.status = 'expired'
                    account.save()
                    
                    # Disable the OpenVPN user
                    result = disable_openvpn_user(account.account_number)
                    
                    self.stdout.write(
                        self.style.SUCCESS(f'    ✓ Disabled: {result.get("message", "OK")}')
                    )
                    logger.info(
                        f'Disabled expired account {account.account_number} '
                        f'(expired {days_expired} days ago)'
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f'    ✗ Failed to disable: {e}')
                    )
                    logger.error(
                        f'Failed to disable expired account {account.account_number}: {e}'
                    )
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Would have disabled {count} account(s)')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f'Disabled {count} expired account(s)')
            )

