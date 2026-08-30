"""
Django management command to generate sample usage data for existing accounts.

This command creates sample ConnectionSession records with usage data for existing accounts,
then aggregates them into daily statistics.

Usage:
    python manage.py generate_sample_usage
    python manage.py generate_sample_usage --days 30
    python manage.py generate_sample_usage --days 30 --accounts 5
"""

import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, datetime
from openvpn_dashboard.models import Account, ConnectionSession, DailyUsageStats


class Command(BaseCommand):
    help = 'Generate sample usage data for existing accounts'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to generate data for (default: 30)',
        )
        parser.add_argument(
            '--accounts',
            type=int,
            default=0,
            help='Number of accounts to use (0 = all accounts, default: 0)',
        )
        parser.add_argument(
            '--sessions-per-day',
            type=int,
            default=3,
            help='Average number of sessions per day per account (default: 3)',
        )
        parser.add_argument(
            '--clear-existing',
            action='store_true',
            help='Clear existing sample sessions before generating new ones',
        )
    
    def handle(self, *args, **options):
        days = options['days']
        num_accounts = options['accounts']
        sessions_per_day = options['sessions_per_day']
        clear_existing = options['clear_existing']
        
        # Get accounts
        accounts = Account.objects.all()
        if num_accounts > 0:
            accounts = accounts[:num_accounts]
        
        if not accounts.exists():
            self.stdout.write(self.style.ERROR('No accounts found. Please create accounts first.'))
            return
        
        self.stdout.write(f'Generating sample usage for {accounts.count()} account(s) over {days} days...')
        
        # Clear existing sample sessions if requested
        if clear_existing:
            deleted = ConnectionSession.objects.all().delete()[0]
            self.stdout.write(f'Deleted {deleted} existing sessions.')
        
        # Calculate date range
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days-1)
        
        total_sessions = 0
        
        # Generate sessions for each account
        for account in accounts:
            account_sessions = 0
            
            # Generate sessions for each day
            for day_offset in range(days):
                date = start_date + timedelta(days=day_offset)
                
                # Random number of sessions for this day (0 to 2x average)
                num_sessions = random.randint(0, sessions_per_day * 2)
                
                for session_num in range(num_sessions):
                    # Random connection time during the day
                    hour = random.randint(6, 22)  # Between 6 AM and 10 PM
                    minute = random.randint(0, 59)
                    connection_time = timezone.make_aware(
                        datetime.combine(date, datetime.min.time().replace(hour=hour, minute=minute))
                    )
                    
                    # Random session duration (5 minutes to 8 hours)
                    duration_minutes = random.randint(5, 480)
                    duration = timedelta(minutes=duration_minutes)
                    disconnection_time = connection_time + duration
                    
                    # Only create if disconnection is before end of day or in the past
                    if disconnection_time.date() <= end_date and disconnection_time <= timezone.now():
                        # Generate random usage based on session duration
                        # Average: ~1 MB per minute of connection
                        base_bytes = duration_minutes * 1024 * 1024  # 1 MB per minute
                        
                        # Add randomness (±50%)
                        bytes_sent = int(base_bytes * random.uniform(0.3, 0.7))  # Upload (30-70% of total)
                        bytes_received = int(base_bytes * random.uniform(0.5, 1.2))  # Download (50-120% of total)
                        
                        # Create session
                        session = ConnectionSession.objects.create(
                            account=account,
                            real_address=f"{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}:{random.randint(10000, 65535)}",
                            virtual_address=f"10.8.0.{random.randint(1, 254)}",
                            connected_at=connection_time,
                            disconnected_at=disconnection_time,
                            bytes_sent=bytes_sent,
                            bytes_received=bytes_received,
                            is_active=False,
                            usage_committed=True,
                        )
                        
                        # Commit usage to account totals
                        account.add_usage(bytes_sent, bytes_received)
                        
                        account_sessions += 1
                        total_sessions += 1
            
            self.stdout.write(f'  {account.account_number}: {account_sessions} sessions created')
        
        self.stdout.write(self.style.SUCCESS(f'\nCreated {total_sessions} total sessions.'))
        
        # Now aggregate daily stats
        self.stdout.write('\nAggregating daily statistics...')
        from django.core.management import call_command
        
        # Aggregate all dates
        call_command('aggregate_daily_stats', '--all')
        
        self.stdout.write(self.style.SUCCESS('\nSample usage data generation complete!'))

