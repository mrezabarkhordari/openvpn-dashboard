"""
Django management command to reset usage counters.

Usage:
    python manage.py reset_usage                    # Reset all accounts
    python manage.py reset_usage --account user123  # Reset specific account
    python manage.py reset_usage --confirm          # Skip confirmation prompt
"""

from django.core.management.base import BaseCommand, CommandError
from openvpn_dashboard.services.usage_collector import reset_account_usage, reset_all_usage
from openvpn_dashboard.models import Account


class Command(BaseCommand):
    help = 'Reset usage counters for OpenVPN accounts'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--account',
            type=str,
            help='Specific account number to reset (resets all if not provided)'
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Skip confirmation prompt'
        )
    
    def handle(self, *args, **options):
        account_number = options.get('account')
        confirmed = options.get('confirm', False)
        
        if account_number:
            # Reset specific account
            try:
                account = Account.objects.get(account_number=account_number)
            except Account.DoesNotExist:
                raise CommandError(f'Account "{account_number}" not found.')
            
            if not confirmed:
                self.stdout.write(
                    f'This will reset usage for account: {account_number}'
                )
                self.stdout.write(
                    f'  Current sent: {account.total_bytes_sent_human}'
                )
                self.stdout.write(
                    f'  Current received: {account.total_bytes_received_human}'
                )
                confirm = input('Are you sure? [y/N]: ')
                if confirm.lower() != 'y':
                    self.stdout.write(self.style.WARNING('Aborted.'))
                    return
            
            if reset_account_usage(account_number):
                self.stdout.write(
                    self.style.SUCCESS(f'Reset usage for account: {account_number}')
                )
            else:
                raise CommandError(f'Failed to reset usage for {account_number}')
        
        else:
            # Reset all accounts
            total_accounts = Account.objects.count()
            
            if total_accounts == 0:
                self.stdout.write(self.style.WARNING('No accounts found.'))
                return
            
            if not confirmed:
                self.stdout.write(
                    self.style.WARNING(
                        f'This will reset usage for ALL {total_accounts} accounts!'
                    )
                )
                confirm = input('Are you sure? [y/N]: ')
                if confirm.lower() != 'y':
                    self.stdout.write(self.style.WARNING('Aborted.'))
                    return
            
            count = reset_all_usage()
            self.stdout.write(
                self.style.SUCCESS(f'Reset usage for {count} accounts.')
            )

