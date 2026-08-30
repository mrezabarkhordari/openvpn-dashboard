"""
Django management command to display usage statistics.

Usage:
    python manage.py usage_stats
    python manage.py usage_stats --top 10
    python manage.py usage_stats --json
"""

import json
from django.core.management.base import BaseCommand
from django.db.models import Sum, F
from openvpn_dashboard.models import Account, ConnectionSession
from openvpn_dashboard.services.usage_collector import get_usage_stats


class Command(BaseCommand):
    help = 'Display OpenVPN usage statistics'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--top',
            type=int,
            default=10,
            help='Number of top users to show (default: 10)'
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='Output in JSON format'
        )
    
    def handle(self, *args, **options):
        top_n = options['top']
        as_json = options['json']
        
        # Get overall stats
        stats = get_usage_stats()
        
        # Get top users by total usage
        top_users = Account.objects.annotate(
            total_usage=F('total_bytes_sent') + F('total_bytes_received')
        ).order_by('-total_usage')[:top_n]
        
        # Get active sessions
        active_sessions = ConnectionSession.objects.filter(
            is_active=True
        ).select_related('account')
        
        if as_json:
            output = {
                'summary': {
                    'total_bytes_sent': stats.get('total_bytes_sent', 0),
                    'total_bytes_received': stats.get('total_bytes_received', 0),
                    'total_accounts': stats.get('total_accounts', 0),
                    'active_sessions': stats.get('active_sessions', 0),
                    'today_sessions': stats.get('today_sessions', 0),
                },
                'top_users': [
                    {
                        'account': u.account_number,
                        'user': u.user.name,
                        'bytes_sent': u.total_bytes_sent,
                        'bytes_received': u.total_bytes_received,
                        'total': u.total_usage,
                    }
                    for u in top_users
                ],
                'active_sessions': [
                    {
                        'account': s.account.account_number,
                        'real_address': s.real_address,
                        'connected_at': s.connected_at.isoformat(),
                        'bytes_sent': s.bytes_sent,
                        'bytes_received': s.bytes_received,
                    }
                    for s in active_sessions
                ]
            }
            self.stdout.write(json.dumps(output, indent=2))
        else:
            # Pretty print
            self.stdout.write(self.style.SUCCESS('=' * 60))
            self.stdout.write(self.style.SUCCESS('OpenVPN Usage Statistics'))
            self.stdout.write(self.style.SUCCESS('=' * 60))
            
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING('Summary:'))
            self.stdout.write(f"  Total Accounts: {stats.get('total_accounts', 0)}")
            self.stdout.write(f"  Active Sessions: {stats.get('active_sessions', 0)}")
            self.stdout.write(f"  Today's Sessions: {stats.get('today_sessions', 0)}")
            self.stdout.write(
                f"  Total Sent: {self._format_bytes(stats.get('total_bytes_sent', 0))}"
            )
            self.stdout.write(
                f"  Total Received: {self._format_bytes(stats.get('total_bytes_received', 0))}"
            )
            
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING(f'Top {top_n} Users by Usage:'))
            self.stdout.write('-' * 60)
            self.stdout.write(
                f"{'Account':<20} {'User':<15} {'Sent':<12} {'Received':<12}"
            )
            self.stdout.write('-' * 60)
            
            for account in top_users:
                self.stdout.write(
                    f"{account.account_number:<20} "
                    f"{account.user.name[:14]:<15} "
                    f"{account.total_bytes_sent_human:<12} "
                    f"{account.total_bytes_received_human:<12}"
                )
            
            if active_sessions:
                self.stdout.write('')
                self.stdout.write(self.style.MIGRATE_HEADING('Active Sessions:'))
                self.stdout.write('-' * 60)
                
                for session in active_sessions:
                    self.stdout.write(
                        f"  {session.account.account_number} "
                        f"({session.real_address}) - "
                        f"Duration: {session.duration_human}"
                    )
            
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('=' * 60))
    
    @staticmethod
    def _format_bytes(size: int) -> str:
        """Format bytes to human readable string."""
        if size == 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if abs(size) < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

