"""
Django management command to aggregate daily usage statistics from sessions.

Usage:
    python manage.py aggregate_daily_stats                    # Aggregate yesterday
    python manage.py aggregate_daily_stats --date 2024-01-15  # Aggregate specific date
    python manage.py aggregate_daily_stats --all              # Aggregate all missing dates
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta, datetime
from openvpn_dashboard.models import Account, ConnectionSession, DailyUsageStats, ServerDailyStats
import re


class Command(BaseCommand):
    help = 'Aggregate daily usage statistics from sessions'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--date',
            type=str,
            help='Date to aggregate (YYYY-MM-DD). Defaults to yesterday.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Aggregate all dates that have sessions but no stats',
        )
    
    def handle(self, *args, **options):
        if options['all']:
            # Find all dates with sessions but no account stats
            self.stdout.write('Finding dates with sessions but no account stats...')
            
            # Get all unique dates from sessions
            dates_with_sessions = set(
                ConnectionSession.objects.values_list(
                    'connected_at__date', flat=True
                ).distinct()
            )
            
            # Get all dates that already have account stats
            dates_with_account_stats = set(
                DailyUsageStats.objects.values_list('date', flat=True).distinct()
            )
            
            # Get all dates that already have server stats
            dates_with_server_stats = set(
                ServerDailyStats.objects.values_list('date', flat=True).distinct()
            )
            
            # Find missing account stats
            dates_to_aggregate = dates_with_sessions - dates_with_account_stats
            
            # Find dates with account stats but no server stats
            dates_needing_server_stats = dates_with_account_stats - dates_with_server_stats
            
            if dates_to_aggregate:
                self.stdout.write(f'Found {len(dates_to_aggregate)} dates to aggregate account stats.')
                for date in sorted(dates_to_aggregate):
                    self.aggregate_date(date)
            
            if dates_needing_server_stats:
                self.stdout.write(f'Found {len(dates_needing_server_stats)} dates needing server stats.')
                for date in sorted(dates_needing_server_stats):
                    self.aggregate_server_stats(date)
            
            if not dates_to_aggregate and not dates_needing_server_stats:
                self.stdout.write(self.style.SUCCESS('All dates already have stats.'))
                return
        else:
            # Aggregate specific date or yesterday
            if options['date']:
                try:
                    target_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
                except ValueError:
                    self.stdout.write(
                        self.style.ERROR(f'Invalid date format: {options["date"]}. Use YYYY-MM-DD')
                    )
                    return
            else:
                target_date = (timezone.now() - timedelta(days=1)).date()
            
            self.aggregate_date(target_date)
    
    def aggregate_date(self, date):
        """Aggregate statistics for a specific date."""
        date_start = timezone.make_aware(
            datetime.combine(date, datetime.min.time())
        )
        date_end = date_start + timedelta(days=1)
        
        self.stdout.write(f'Aggregating stats for {date}...')
        
        # Get all accounts that had sessions on this date
        accounts = Account.objects.filter(
            sessions__connected_at__date=date
        ).distinct()
        
        stats_created = 0
        stats_updated = 0
        
        for account in accounts:
            # Get all sessions for this account on this date
            # Sessions that started today, or started before but ended today
            sessions = ConnectionSession.objects.filter(
                account=account
            ).filter(
                Q(connected_at__date=date) |  # Started today
                Q(disconnected_at__date=date)  # Ended today
            )
            
            if not sessions.exists():
                continue
            
            # Calculate usage metrics
            total_sent = 0
            total_received = 0
            session_count = 0
            total_duration = timedelta(0)
            first_connection = None
            last_disconnection = None
            
            for session in sessions:
                # Only count usage for sessions that were active during this day
                # For sessions that started before today but ended today, count all usage
                # For sessions that started today, count all usage
                # For sessions that started today and are still active, count all usage
                
                if session.connected_at.date() == date:
                    # Session started today - count all its usage
                    total_sent += session.bytes_sent
                    total_received += session.bytes_received
                    session_count += 1
                    
                    if not first_connection or session.connected_at < first_connection:
                        first_connection = session.connected_at
                    
                    if session.disconnected_at:
                        duration = session.disconnected_at - session.connected_at
                        total_duration += duration
                        if not last_disconnection or session.disconnected_at > last_disconnection:
                            last_disconnection = session.disconnected_at
                    else:
                        # Still active - use current time for duration calculation
                        duration = timezone.now() - session.connected_at
                        total_duration += duration
                        if not last_disconnection:
                            last_disconnection = timezone.now()
                elif session.disconnected_at and session.disconnected_at.date() == date:
                    # Session started before today but ended today
                    # Count all usage (approximation - we don't track per-day usage within a session)
                    total_sent += session.bytes_sent
                    total_received += session.bytes_received
                    session_count += 1
                    
                    duration = session.disconnected_at - session.connected_at
                    total_duration += duration
                    if not last_disconnection or session.disconnected_at > last_disconnection:
                        last_disconnection = session.disconnected_at
            
            if session_count == 0:
                continue
            
            avg_duration = total_duration / session_count if session_count > 0 else None
            
            # Create or update daily stats
            stats, created = DailyUsageStats.objects.update_or_create(
                account=account,
                date=date,
                defaults={
                    'bytes_sent': total_sent,
                    'bytes_received': total_received,
                    'session_count': session_count,
                    'total_session_duration': total_duration,
                    'avg_session_duration': avg_duration,
                    'first_connection_time': first_connection,
                    'last_connection_time': last_disconnection,
                }
            )
            
            if created:
                stats_created += 1
            else:
                stats_updated += 1
        
        # Now aggregate server-wide stats for this date
        self.aggregate_server_stats(date)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Successfully aggregated stats for {date}: '
                f'{stats_created} created, {stats_updated} updated'
            )
        )
    
    def aggregate_server_stats(self, date):
        """Aggregate server-wide statistics for a specific date."""
        # Get all account stats for this date
        account_stats = DailyUsageStats.objects.filter(date=date)
        
        if not account_stats.exists():
            # No account stats, so no server stats
            return
        
        # Use aggregation to avoid DurationField deserialization issues
        # Aggregate simple fields using values() 
        from django.db.models import Sum, Min, Max
        from django.db import connection
        
        # Get aggregated values without loading DurationField
        aggregates = account_stats.aggregate(
            total_sent=Sum('bytes_sent'),
            total_received=Sum('bytes_received'),
            total_sessions=Sum('session_count'),
            first_conn=Min('first_connection_time'),
            last_conn=Max('last_connection_time'),
        )
        
        total_bytes_sent = aggregates['total_sent'] or 0
        total_bytes_received = aggregates['total_received'] or 0
        total_sessions = aggregates['total_sessions'] or 0
        first_connection = aggregates['first_conn']
        last_disconnection = aggregates['last_conn']
        
        # Calculate total duration using raw SQL to avoid DurationField deserialization
        total_duration = timedelta(0)
        cursor = connection.cursor()
        cursor.execute("""
            SELECT total_session_duration
            FROM ui_ovpn_dailyusagestats
            WHERE date = ? AND total_session_duration IS NOT NULL
        """, [date])
        
        for (duration_str,) in cursor.fetchall():
            if duration_str:
                try:
                    # Parse Django's duration format from SQLite TEXT
                    # Format: "days HH:MM:SS.microseconds" or "HH:MM:SS.microseconds"
                    parsed = self._parse_duration(duration_str)
                    if parsed:
                        total_duration += parsed
                except (ValueError, AttributeError, TypeError) as e:
                    # Skip invalid duration values
                    self.stdout.write(
                        self.style.WARNING(f'Skipping invalid duration value: {duration_str}')
                    )
                    continue
        
        avg_duration = total_duration / total_sessions if total_sessions > 0 else None
        
        # Count active accounts
        active_accounts = account_stats.count()
        
        # Get total number of accounts (all accounts that existed on this date)
        # For simplicity, we'll use current total accounts
        total_accounts = Account.objects.count()
        
        # Create or update server stats
        ServerDailyStats.objects.update_or_create(
            date=date,
            defaults={
                'total_bytes_sent': total_bytes_sent,
                'total_bytes_received': total_bytes_received,
                'active_accounts': active_accounts,
                'total_accounts': total_accounts,
                'total_sessions': total_sessions,
                'total_session_duration': total_duration,
                'avg_session_duration': avg_duration,
                'first_connection_time': first_connection,
                'last_connection_time': last_disconnection,
            }
        )
    
    def _parse_duration(self, duration_str):
        """
        Parse a duration string from SQLite TEXT format to timedelta.
        Handles formats like: "1 02:30:45.123456", "02:30:45", "0:00:00"
        """
        if not duration_str:
            return None
        
        try:
            # Handle Django's duration format: "days HH:MM:SS.microseconds"
            if ' ' in duration_str:
                days_str, time_part = duration_str.split(' ', 1)
                days = int(days_str)
            else:
                days = 0
                time_part = duration_str
            
            # Parse time part: HH:MM:SS or HH:MM:SS.microseconds
            time_parts = time_part.split(':')
            if len(time_parts) >= 3:
                hours = int(time_parts[0])
                minutes = int(time_parts[1])
                sec_parts = time_parts[2].split('.')
                seconds = int(sec_parts[0])
                microseconds = int(sec_parts[1]) if len(sec_parts) > 1 else 0
                return timedelta(days=days, hours=hours, minutes=minutes, 
                               seconds=seconds, microseconds=microseconds)
        except (ValueError, AttributeError, TypeError, IndexError):
            # Try alternative format or return None
            pass
        
        return None

