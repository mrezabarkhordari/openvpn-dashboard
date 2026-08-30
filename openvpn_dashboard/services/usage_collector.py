"""
OpenVPN Usage Collector Service

This module collects usage metrics from OpenVPN status log every 2 seconds.
It tracks each connection session and accumulates usage data.

Live Usage Updates:
- Usage is committed to Account totals periodically (default: every 10 seconds)
- This provides real-time visibility into usage even for long-running connections
- When a client disconnects, any remaining uncommitted usage is added to the account's total

Environment Variables:
- USAGE_COLLECTOR_INTERVAL: How often to poll the status log (default: 2.0 seconds)
- USAGE_COMMIT_INTERVAL: How often to commit usage to account totals (default: 10.0 seconds)

Uses the openvpn-status library: https://github.com/tonyseek/openvpn-status
"""

import os
import time
import signal
import logging
import threading
from datetime import datetime
from typing import Dict, Set, Optional
from dataclasses import dataclass, field

import django
from django.utils import timezone
from django.db import transaction, close_old_connections

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('usage_collector')


@dataclass
class ClientSnapshot:
    """Snapshot of a connected client's state."""
    common_name: str
    real_address: str
    bytes_sent: int
    bytes_received: int
    connected_since: datetime
    virtual_address: Optional[str] = None


@dataclass
class CollectorState:
    """Maintains the collector's state between iterations."""
    # Track which clients were seen in the last iteration
    last_seen_clients: Set[str] = field(default_factory=set)
    # Map of common_name -> session_id for active sessions
    active_sessions: Dict[str, int] = field(default_factory=dict)
    # Last update timestamp
    last_update: Optional[datetime] = None
    # Last time usage was committed to account totals
    last_commit_time: Optional[datetime] = None
    # Running flag
    running: bool = True


class UsageCollector:
    """
    Collects OpenVPN usage metrics and stores them in the database.
    
    Features:
    - Polls OpenVPN status log every N seconds (default: 2)
    - Tracks individual connection sessions
    - Accumulates usage when clients disconnect
    - Thread-safe operation
    """
    
    def __init__(
        self,
        status_log_path: str = None,
        poll_interval: float = None,
        commit_interval: float = None,
        use_openvpn_status_lib: bool = True
    ):
        # Use environment variables if not provided
        if status_log_path is None:
            status_log_path = os.environ.get('OPENVPN_STATUS_LOG', '/var/log/openvpn/status.log')
        if poll_interval is None:
            try:
                poll_interval = float(os.environ.get('USAGE_COLLECTOR_INTERVAL', '2.0'))
            except (ValueError, TypeError):
                poll_interval = 2.0
        if commit_interval is None:
            try:
                # Default: commit usage to account every 10 seconds for live updates
                commit_interval = float(os.environ.get('USAGE_COMMIT_INTERVAL', '10.0'))
            except (ValueError, TypeError):
                commit_interval = 10.0
        """
        Initialize the usage collector.
        
        Args:
            status_log_path: Path to OpenVPN status log file.
            poll_interval: How often to poll the status log (seconds).
            commit_interval: How often to commit usage to account totals (seconds).
            use_openvpn_status_lib: Whether to use openvpn-status library.
        """
        self.status_log_path = status_log_path
        self.poll_interval = poll_interval
        self.commit_interval = commit_interval
        self.use_openvpn_status_lib = use_openvpn_status_lib
        self.state = CollectorState()
        self._lock = threading.Lock()
        
        # Try to import openvpn-status library
        if use_openvpn_status_lib:
            try:
                from openvpn_status import parse_status
                self._parse_status = parse_status
                logger.info("Using openvpn-status library for parsing")
            except ImportError:
                logger.warning("openvpn-status library not found, using fallback parser")
                self._parse_status = None
        else:
            self._parse_status = None
    
    def get_connected_clients(self) -> Dict[str, ClientSnapshot]:
        """
        Get currently connected clients from OpenVPN status log.
        
        Uses the shared parser: openvpn-status for version 1, then a
        fallback that reads version 2 CLIENT_LIST lines and legacy v1.
        
        Returns:
            Dictionary mapping common_name to ClientSnapshot.
        """
        if not os.path.exists(self.status_log_path):
            logger.debug(f"Status log not found: {self.status_log_path}")
            return {}
        
        try:
            from .status_log import parse_status_log_file
            return self._snapshots_from_parsed(parse_status_log_file(self.status_log_path))
        except Exception as e:
            logger.error(f"Failed to parse status log: {e}")
            return {}
    
    def _snapshots_from_parsed(self, parsed) -> Dict[str, ClientSnapshot]:
        """Convert shared parser dicts into ClientSnapshot objects."""
        clients = {}
        for item in parsed:
            cn = item.get('common_name') or item.get('name') or ''
            if not cn:
                continue
            if cn.startswith('server_') or cn.startswith('cn_'):
                continue

            connected_since = item.get('connected_since') or timezone.now()
            if isinstance(connected_since, datetime) and timezone.is_naive(connected_since):
                connected_since = timezone.make_aware(
                    connected_since,
                    timezone.get_current_timezone()
                )

            clients[cn] = ClientSnapshot(
                common_name=cn,
                real_address=item.get('real_address') or '',
                bytes_sent=int(item.get('bytes_sent') or 0),
                bytes_received=int(item.get('bytes_received') or 0),
                connected_since=connected_since,
                virtual_address=item.get('virtual_address'),
            )
        return clients

    def _parse_with_library(self, content: str) -> Dict[str, ClientSnapshot]:
        """Parse status log using the shared helper (library, then v1/v2 fallback)."""
        from .status_log import parse_status_log
        return self._snapshots_from_parsed(parse_status_log(content))
    
    def _parse_fallback(self, content: str) -> Dict[str, ClientSnapshot]:
        """Fallback parser for status-version 2 CLIENT_LIST and legacy v1."""
        from .status_log import parse_status_log_manual
        return self._snapshots_from_parsed(parse_status_log_manual(content))
    
    def process_clients(self, current_clients: Dict[str, ClientSnapshot]) -> None:
        """
        Process current clients and update database.
        
        Args:
            current_clients: Dictionary of currently connected clients.
        """
        from openvpn_dashboard.models import Account, ConnectionSession
        
        current_names = set(current_clients.keys())
        now = timezone.now()
        
        with self._lock:
            # Find newly connected clients
            new_clients = current_names - self.state.last_seen_clients
            
            # Find disconnected clients
            disconnected_clients = self.state.last_seen_clients - current_names
            
            # Process new connections
            for cn in new_clients:
                self._handle_new_connection(cn, current_clients[cn])
            
            # Process disconnections
            for cn in disconnected_clients:
                self._handle_disconnection(cn)
            
            # Determine if we should commit usage to account totals (live update)
            should_commit = False
            if self.state.last_commit_time is None:
                should_commit = True
            else:
                time_since_commit = (now - self.state.last_commit_time).total_seconds()
                should_commit = time_since_commit >= self.commit_interval
            
            # Update active sessions with current usage
            for cn, client in current_clients.items():
                self._update_session_usage(cn, client, commit_to_account=should_commit)
            
            # Update state
            self.state.last_seen_clients = current_names
            self.state.last_update = now
            if should_commit:
                self.state.last_commit_time = now
    
    def _handle_new_connection(self, common_name: str, client: ClientSnapshot) -> None:
        """Handle a new client connection."""
        from openvpn_dashboard.models import Account, ConnectionSession
        
        try:
            # Find the account
            account = Account.objects.filter(account_number=common_name).first()
            if not account:
                logger.warning(f"No account found for client: {common_name}")
                return
            
            # Check if there's already an active session (shouldn't happen, but handle it)
            existing_session = ConnectionSession.objects.filter(
                account=account,
                is_active=True
            ).first()
            
            if existing_session:
                logger.warning(f"Found existing active session for {common_name}, closing it")
                existing_session.close_session()
            
            # Create new session
            session = ConnectionSession.objects.create(
                account=account,
                real_address=client.real_address,
                virtual_address=client.virtual_address,
                connected_at=client.connected_since,
                bytes_sent=client.bytes_sent,
                bytes_received=client.bytes_received,
                last_bytes_sent=client.bytes_sent,
                last_bytes_received=client.bytes_received,
                is_active=True
            )
            
            self.state.active_sessions[common_name] = session.id
            logger.info(f"New connection: {common_name} from {client.real_address}")
            
        except Exception as e:
            logger.error(f"Failed to handle new connection for {common_name}: {e}")
    
    def _handle_disconnection(self, common_name: str) -> None:
        """Handle a client disconnection."""
        from openvpn_dashboard.models import ConnectionSession
        
        try:
            session_id = self.state.active_sessions.pop(common_name, None)
            
            if session_id:
                session = ConnectionSession.objects.filter(id=session_id).first()
                if session:
                    session.close_session()
                    logger.info(
                        f"Disconnected: {common_name} - "
                        f"Sent: {session.bytes_sent}, Received: {session.bytes_received}"
                    )
            else:
                # Try to find and close any active session for this client
                sessions = ConnectionSession.objects.filter(
                    account__account_number=common_name,
                    is_active=True
                )
                for session in sessions:
                    session.close_session()
                    logger.info(f"Closed orphaned session for {common_name}")
                    
        except Exception as e:
            logger.error(f"Failed to handle disconnection for {common_name}: {e}")
    
    def _update_session_usage(self, common_name: str, client: ClientSnapshot, commit_to_account: bool = False) -> None:
        """
        Update usage for an active session.
        
        Args:
            common_name: The client's common name (account number).
            client: Current client snapshot with usage data.
            commit_to_account: If True, commit usage delta to account totals (for live updates).
        """
        from openvpn_dashboard.models import ConnectionSession
        
        try:
            session_id = self.state.active_sessions.get(common_name)
            
            if session_id:
                session = ConnectionSession.objects.filter(id=session_id).first()
                if session:
                    session.update_usage(client.bytes_sent, client.bytes_received, commit_to_account=commit_to_account)
            else:
                # Session not tracked, try to find it
                session = ConnectionSession.objects.filter(
                    account__account_number=common_name,
                    is_active=True
                ).first()
                
                if session:
                    self.state.active_sessions[common_name] = session.id
                    session.update_usage(client.bytes_sent, client.bytes_received, commit_to_account=commit_to_account)
                    
        except Exception as e:
            logger.error(f"Failed to update session usage for {common_name}: {e}")
    
    def collect_once(self) -> int:
        """
        Perform a single collection cycle.
        
        Returns:
            Number of connected clients found.
        """
        close_old_connections()  # Ensure fresh DB connections
        
        clients = self.get_connected_clients()
        
        with transaction.atomic():
            self.process_clients(clients)
        
        return len(clients)
    
    def run(self) -> None:
        """
        Run the collector loop.
        
        This method blocks and runs until stop() is called or a signal is received.
        """
        logger.info(f"Starting usage collector (poll interval: {self.poll_interval}s, commit interval: {self.commit_interval}s)")
        logger.info(f"Status log: {self.status_log_path}")
        logger.info("Live usage updates enabled - account totals will be updated periodically")
        
        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, stopping...")
            self.stop()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.state.running = True
        iteration = 0
        
        while self.state.running:
            try:
                start_time = time.time()
                
                client_count = self.collect_once()
                
                elapsed = time.time() - start_time
                iteration += 1
                
                if iteration % 30 == 0:  # Log every minute (30 * 2s)
                    logger.info(f"Collector running - {client_count} clients connected")
                
                # Sleep for remaining time
                sleep_time = max(0, self.poll_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    
            except Exception as e:
                logger.error(f"Error in collection cycle: {e}")
                time.sleep(self.poll_interval)
        
        # Clean up - close all active sessions
        self._cleanup()
        logger.info("Usage collector stopped")
    
    def stop(self) -> None:
        """Stop the collector loop."""
        self.state.running = False
    
    def _cleanup(self) -> None:
        """Clean up on shutdown - mark active sessions as potentially incomplete."""
        from openvpn_dashboard.models import ConnectionSession
        
        try:
            # Get current clients one last time
            clients = self.get_connected_clients()
            
            # Update final usage for active sessions
            for cn, client in clients.items():
                session_id = self.state.active_sessions.get(cn)
                if session_id:
                    session = ConnectionSession.objects.filter(id=session_id).first()
                    if session:
                        session.update_usage(client.bytes_sent, client.bytes_received)
            
            logger.info("Cleanup completed - active sessions updated with final usage")
            
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
    
    def recover_sessions(self) -> None:
        """
        Recover session state from database on startup.
        
        This should be called before run() to restore state after a restart.
        """
        from openvpn_dashboard.models import ConnectionSession
        
        try:
            # Get currently connected clients
            current_clients = self.get_connected_clients()
            current_names = set(current_clients.keys())
            
            # Find active sessions in database
            active_sessions = ConnectionSession.objects.filter(is_active=True)
            
            for session in active_sessions:
                cn = session.account.account_number
                
                if cn in current_names:
                    # Client is still connected, resume tracking
                    self.state.active_sessions[cn] = session.id
                    self.state.last_seen_clients.add(cn)
                    logger.info(f"Recovered session for {cn}")
                else:
                    # Client is no longer connected, close the session
                    session.close_session()
                    logger.info(f"Closed stale session for {cn}")
            
            logger.info(f"Session recovery complete - {len(self.state.active_sessions)} active sessions")
            
        except Exception as e:
            logger.error(f"Session recovery failed: {e}")


def reset_account_usage(account_number: str) -> bool:
    """
    Reset usage counters for a specific account.
    
    Args:
        account_number: The account to reset.
    
    Returns:
        True if successful, False otherwise.
    """
    from openvpn_dashboard.models import Account
    
    try:
        account = Account.objects.get(account_number=account_number)
        account.reset_usage()
        logger.info(f"Reset usage for account: {account_number}")
        return True
    except Account.DoesNotExist:
        logger.error(f"Account not found: {account_number}")
        return False
    except Exception as e:
        logger.error(f"Failed to reset usage for {account_number}: {e}")
        return False


def reset_all_usage() -> int:
    """
    Reset usage counters for all accounts.
    
    Returns:
        Number of accounts reset.
    """
    from openvpn_dashboard.models import Account
    
    try:
        count = Account.objects.update(
            total_bytes_sent=0,
            total_bytes_received=0,
            usage_reset_at=timezone.now()
        )
        logger.info(f"Reset usage for {count} accounts")
        return count
    except Exception as e:
        logger.error(f"Failed to reset all usage: {e}")
        return 0


def get_usage_stats() -> Dict:
    """
    Get overall usage statistics.
    
    Returns:
        Dictionary with usage statistics.
    """
    default_stats = {
        'total_bytes_sent': 0,
        'total_bytes_received': 0,
        'total_accounts': 0,
        'active_sessions': 0,
        'today_sessions': 0,
    }
    
    try:
        from openvpn_dashboard.models import Account, ConnectionSession
        from django.db.models import Sum, Count
        
        # Aggregate account usage
        account_stats = Account.objects.aggregate(
            total_sent=Sum('total_bytes_sent'),
            total_received=Sum('total_bytes_received'),
            account_count=Count('id')
        )
        
        # Active sessions
        active_sessions = ConnectionSession.objects.filter(is_active=True).count()
        
        # Today's sessions
        today = timezone.now().date()
        today_sessions = ConnectionSession.objects.filter(
            connected_at__date=today
        ).count()
        
        return {
            'total_bytes_sent': account_stats['total_sent'] or 0,
            'total_bytes_received': account_stats['total_received'] or 0,
            'total_accounts': account_stats['account_count'] or 0,
            'active_sessions': active_sessions,
            'today_sessions': today_sessions,
        }
    except Exception as e:
        logger.error(f"Failed to get usage stats: {e}")
        return default_stats


# For running as a standalone script
if __name__ == '__main__':
    import sys
    
    # Setup Django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    django.setup()
    
    # Get intervals from environment variables (with defaults)
    try:
        poll_interval = float(os.environ.get('USAGE_COLLECTOR_INTERVAL', '2.0'))
    except (ValueError, TypeError):
        poll_interval = 2.0
    
    try:
        commit_interval = float(os.environ.get('USAGE_COMMIT_INTERVAL', '10.0'))
    except (ValueError, TypeError):
        commit_interval = 10.0
    
    # Allow command line override for poll_interval
    if len(sys.argv) > 1:
        try:
            poll_interval = float(sys.argv[1])
        except ValueError:
            pass
    
    status_log = os.environ.get('OPENVPN_STATUS_LOG', '/var/log/openvpn/status.log')
    
    logger.info(f"Configuration: poll_interval={poll_interval}s, commit_interval={commit_interval}s")
    
    # Create and run collector with both intervals
    collector = UsageCollector(
        status_log_path=status_log,
        poll_interval=poll_interval,
        commit_interval=commit_interval
    )
    
    # Recover any existing sessions
    collector.recover_sessions()
    
    # Run the collector
    collector.run()

