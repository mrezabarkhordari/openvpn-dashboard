# openvpn_dashboard/models.py

from django.db import models
from django.db.models import Sum, Q
from django.utils import timezone
from datetime import timedelta


class Setting(models.Model):
    """
    Key-value store for application settings.
    Used to store configurable values like server URL.
    """
    key = models.CharField(max_length=100, unique=True)
    value = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ui_ovpn_setting'
        ordering = ['key']

    def __str__(self):
        return f"{self.key}: {self.value}"
    
    @classmethod
    def get_value(cls, key: str, default: str = '') -> str:
        """Get a setting value by key, returns default if not found."""
        try:
            setting = cls.objects.get(key=key)
            return setting.value
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def set_value(cls, key: str, value: str) -> 'Setting':
        """Set a setting value, creates if doesn't exist."""
        setting, created = cls.objects.update_or_create(
            key=key,
            defaults={'value': value}
        )
        return setting


class User(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    info = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'ui_ovpn_user'

    def __str__(self):
        return self.name


class Account(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('disabled', 'Disabled'),
        ('revoked', 'Revoked'),
        ('deleted', 'Deleted'),
        ('expired', 'Expired'),
    ]
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')    
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    account_number = models.CharField(max_length=100, unique=True)
    expiration_date = models.DateField()
    remaining_days = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Usage tracking fields - cumulative totals
    total_bytes_sent = models.BigIntegerField(default=0, help_text="Total bytes sent (upload) - cumulative")
    total_bytes_received = models.BigIntegerField(default=0, help_text="Total bytes received (download) - cumulative")
    usage_last_updated = models.DateTimeField(null=True, blank=True, help_text="Last time usage was updated")
    usage_reset_at = models.DateTimeField(null=True, blank=True, help_text="Last time usage was reset")

    class Meta:
        db_table = 'ui_ovpn_account'

    def save(self, *args, **kwargs):
        today = timezone.now().date()
        
        if not self.pk:  # If the instance is being created (not updated)   
            # Calculate remaining days based on expiration date and today's date
            self.remaining_days = (self.expiration_date - today).days
        else:
            # Update remaining days if expiration date is changed
            old_instance = Account.objects.get(pk=self.pk)
            if self.expiration_date != old_instance.expiration_date:
                self.remaining_days = (self.expiration_date - today).days
                
                # If account was expired and expiration date is now in the future, 
                # automatically change status to 'active'
                if old_instance.status == 'expired' and self.expiration_date > today:
                    self.status = 'active'
        
        super().save(*args, **kwargs)

    @property
    def days_until_expiration(self):
        """Live days remaining from expiration_date. Negative if already expired."""
        if not self.expiration_date:
            return None
        return (self.expiration_date - timezone.now().date()).days

    def reset_usage(self):
        """Reset usage counters to zero.
        
        Also resets committed_bytes in any active sessions to prevent
        double-counting when the session closes.
        """
        self.total_bytes_sent = 0
        self.total_bytes_received = 0
        self.usage_reset_at = timezone.now()
        self.save(update_fields=['total_bytes_sent', 'total_bytes_received', 'usage_reset_at'])
        
        # Reset committed bytes in active sessions to match current session usage
        # This ensures that when the session closes, only new usage since reset is counted
        active_sessions = self.sessions.filter(is_active=True)
        for session in active_sessions:
            session.committed_bytes_sent = session.bytes_sent
            session.committed_bytes_received = session.bytes_received
            session.save(update_fields=['committed_bytes_sent', 'committed_bytes_received'])
    
    def add_usage(self, bytes_sent: int, bytes_received: int):
        """Add usage to cumulative totals."""
        self.total_bytes_sent += bytes_sent
        self.total_bytes_received += bytes_received
        self.usage_last_updated = timezone.now()
        self.save(update_fields=['total_bytes_sent', 'total_bytes_received', 'usage_last_updated'])
    
    @property
    def total_bytes_sent_human(self) -> str:
        """Human-readable bytes sent."""
        return self._format_bytes(self.total_bytes_sent)
    
    @property
    def total_bytes_received_human(self) -> str:
        """Human-readable bytes received."""
        return self._format_bytes(self.total_bytes_received)
    
    @property
    def total_usage(self) -> int:
        """Total usage (sent + received)."""
        return self.total_bytes_sent + self.total_bytes_received
    
    @property
    def total_usage_human(self) -> str:
        """Human-readable total usage."""
        return self._format_bytes(self.total_usage)
    
    def get_last_24h_usage(self):
        """
        Calculate download and upload usage for the current calendar day (00:00 to 23:59).
        
        Returns:
            tuple: (bytes_sent, bytes_received) for today
        """
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Get sessions that have activity today:
        # 1. Sessions that connected today
        # 2. Active sessions (regardless of when they started, count their current usage)
        # 3. Sessions that disconnected today (but started earlier)
        
        # For sessions that started today, count all their usage
        recent_sessions = self.sessions.filter(
            Q(connected_at__gte=today_start) |  # Started today
            Q(is_active=True) |  # Still active
            Q(disconnected_at__gte=today_start)  # Disconnected today
        )
        
        # Aggregate usage
        result = recent_sessions.aggregate(
            total_sent=Sum('bytes_sent'),
            total_received=Sum('bytes_received')
        )
        
        bytes_sent = result['total_sent'] or 0
        bytes_received = result['total_received'] or 0
        
        return (bytes_sent, bytes_received)
    
    @property
    def last_24h_bytes_sent(self) -> int:
        """Bytes sent in the last 24 hours."""
        return self.get_last_24h_usage()[0]
    
    @property
    def last_24h_bytes_received(self) -> int:
        """Bytes received in the last 24 hours."""
        return self.get_last_24h_usage()[1]
    
    @property
    def last_24h_bytes_sent_human(self) -> str:
        """Human-readable bytes sent in last 24 hours."""
        return self._format_bytes(self.last_24h_bytes_sent)
    
    @property
    def last_24h_bytes_received_human(self) -> str:
        """Human-readable bytes received in last 24 hours."""
        return self._format_bytes(self.last_24h_bytes_received)
    
    @property
    def last_24h_total_usage(self) -> int:
        """Total usage (sent + received) in last 24 hours."""
        return self.last_24h_bytes_sent + self.last_24h_bytes_received
    
    @property
    def last_24h_total_usage_human(self) -> str:
        """Human-readable total usage in last 24 hours."""
        return self._format_bytes(self.last_24h_total_usage)
    
    @staticmethod
    def _format_bytes(size: int) -> str:
        """Format bytes to human readable string."""
        if size == 0:
            return "0 B"
        for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
            if abs(size) < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

    def __str__(self):
        return f"Account for {self.user.name} - {self.account_number}"


class ConnectionSession(models.Model):
    """
    Tracks individual connection sessions for detailed logging.
    Each time a client connects, a new session is created.
    When they disconnect, the session is closed and usage is added to Account totals.
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='sessions')
    
    # Connection info
    real_address = models.CharField(max_length=50, help_text="Client's real IP:port")
    virtual_address = models.CharField(max_length=50, null=True, blank=True, help_text="Assigned VPN IP")
    
    # Timestamps
    connected_at = models.DateTimeField(help_text="When the client connected")
    disconnected_at = models.DateTimeField(null=True, blank=True, help_text="When the client disconnected")
    
    # Usage for this session
    bytes_sent = models.BigIntegerField(default=0)
    bytes_received = models.BigIntegerField(default=0)
    
    # Last known values (for calculating delta)
    last_bytes_sent = models.BigIntegerField(default=0)
    last_bytes_received = models.BigIntegerField(default=0)
    last_updated = models.DateTimeField(auto_now=True)
    
    # Track how much usage has been committed to the Account totals (for live updates)
    committed_bytes_sent = models.BigIntegerField(default=0, help_text="Bytes sent already committed to account totals")
    committed_bytes_received = models.BigIntegerField(default=0, help_text="Bytes received already committed to account totals")
    
    # Session state
    is_active = models.BooleanField(default=True)
    usage_committed = models.BooleanField(default=False, help_text="Whether final usage has been added to account totals")
    
    class Meta:
        db_table = 'ui_ovpn_connectionsession'
        ordering = ['-connected_at']
        indexes = [
            models.Index(fields=['account', 'is_active']),
            models.Index(fields=['is_active', 'usage_committed']),
        ]
    
    def close_session(self, final_bytes_sent: int = None, final_bytes_received: int = None):
        """
        Close this session and ensure final usage is committed to account totals.
        Since we now commit usage incrementally, we just need to commit any remaining delta.
        """
        if final_bytes_sent is not None:
            self.bytes_sent = final_bytes_sent
        if final_bytes_received is not None:
            self.bytes_received = final_bytes_received
        
        self.disconnected_at = timezone.now()
        self.is_active = False
        
        # Commit any remaining usage delta that hasn't been committed yet
        if not self.usage_committed:
            # Calculate uncommitted usage (total session usage minus what was already committed)
            uncommitted_sent = self.bytes_sent - self.committed_bytes_sent
            uncommitted_received = self.bytes_received - self.committed_bytes_received
            
            if uncommitted_sent > 0 or uncommitted_received > 0:
                self.account.add_usage(uncommitted_sent, uncommitted_received)
            
            self.committed_bytes_sent = self.bytes_sent
            self.committed_bytes_received = self.bytes_received
            self.usage_committed = True
        
        self.save()
    
    def update_usage(self, current_bytes_sent: int, current_bytes_received: int, commit_to_account: bool = False):
        """
        Update session usage with current values from OpenVPN status.
        The values from OpenVPN are cumulative for the session.
        
        Args:
            current_bytes_sent: Current cumulative bytes sent for this session.
            current_bytes_received: Current cumulative bytes received for this session.
            commit_to_account: If True, commit the delta to the Account totals (for live updates).
        """
        self.bytes_sent = current_bytes_sent
        self.bytes_received = current_bytes_received
        self.last_bytes_sent = current_bytes_sent
        self.last_bytes_received = current_bytes_received
        
        update_fields = ['bytes_sent', 'bytes_received', 'last_bytes_sent', 'last_bytes_received', 'last_updated']
        
        if commit_to_account:
            # Calculate the delta since last commit
            delta_sent = current_bytes_sent - self.committed_bytes_sent
            delta_received = current_bytes_received - self.committed_bytes_received
            
            if delta_sent > 0 or delta_received > 0:
                self.account.add_usage(delta_sent, delta_received)
                self.committed_bytes_sent = current_bytes_sent
                self.committed_bytes_received = current_bytes_received
                update_fields.extend(['committed_bytes_sent', 'committed_bytes_received'])
        
        self.save(update_fields=update_fields)
    
    @property
    def duration(self):
        """Get session duration."""
        end_time = self.disconnected_at or timezone.now()
        return end_time - self.connected_at
    
    @property
    def duration_human(self) -> str:
        """Human-readable duration."""
        duration = self.duration
        total_seconds = int(duration.total_seconds())
        
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        
        return " ".join(parts)
    
    @staticmethod
    def format_duration(duration):
        """Format a timedelta to human-readable string."""
        if not duration:
            return "-"
        total_seconds = int(duration.total_seconds())
        
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if seconds or not parts:
            parts.append(f"{seconds}s")
        
        return " ".join(parts)
    
    def __str__(self):
        status = "Active" if self.is_active else "Closed"
        return f"{self.account.account_number} - {self.real_address} ({status})"


class DailyUsageStats(models.Model):
    """
    Daily aggregated usage statistics for monitoring and historical tracking.
    Stores one record per account per day.
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='daily_stats')
    date = models.DateField(help_text="The calendar date for these statistics")
    
    # Usage metrics
    bytes_sent = models.BigIntegerField(default=0, help_text="Total bytes sent (upload) for this day")
    bytes_received = models.BigIntegerField(default=0, help_text="Total bytes received (download) for this day")
    
    # Session metrics
    session_count = models.IntegerField(default=0, help_text="Number of sessions on this day")
    total_session_duration = models.DurationField(default=timedelta(0), help_text="Total duration of all sessions")
    avg_session_duration = models.DurationField(null=True, blank=True, help_text="Average session duration")
    
    # Connection metrics
    first_connection_time = models.DateTimeField(null=True, blank=True, help_text="Time of first connection")
    last_connection_time = models.DateTimeField(null=True, blank=True, help_text="Time of last disconnection")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ui_ovpn_dailyusagestats'
        unique_together = [['account', 'date']]
        ordering = ['-date', 'account']
        indexes = [
            models.Index(fields=['date', 'account']),
            models.Index(fields=['account', 'date']),
            models.Index(fields=['-date']),  # For recent stats queries
        ]
    
    @property
    def total_bytes(self):
        """Total bytes (sent + received)."""
        return self.bytes_sent + self.bytes_received
    
    @property
    def bytes_sent_human(self):
        """Human-readable bytes sent."""
        return Account._format_bytes(self.bytes_sent)
    
    @property
    def bytes_received_human(self):
        """Human-readable bytes received."""
        return Account._format_bytes(self.bytes_received)
    
    @property
    def total_bytes_human(self):
        """Human-readable total bytes."""
        return Account._format_bytes(self.total_bytes)
    
    @property
    def total_session_duration_human(self):
        """Human-readable total session duration."""
        return ConnectionSession.format_duration(self.total_session_duration)
    
    @property
    def avg_session_duration_human(self):
        """Human-readable average session duration."""
        return ConnectionSession.format_duration(self.avg_session_duration)
    
    def __str__(self):
        return f"{self.account.account_number} - {self.date} ({self.total_bytes_human})"


class ServerDailyStats(models.Model):
    """
    Server-wide daily aggregated usage statistics.
    Stores one record per day with totals across all accounts.
    """
    date = models.DateField(unique=True, help_text="The calendar date for these statistics")
    
    # Usage metrics - totals across all accounts
    total_bytes_sent = models.BigIntegerField(default=0, help_text="Total bytes sent (upload) across all accounts")
    total_bytes_received = models.BigIntegerField(default=0, help_text="Total bytes received (download) across all accounts")
    
    # Account metrics
    active_accounts = models.IntegerField(default=0, help_text="Number of accounts with activity on this day")
    total_accounts = models.IntegerField(default=0, help_text="Total number of accounts on this day")
    
    # Session metrics
    total_sessions = models.IntegerField(default=0, help_text="Total number of sessions across all accounts")
    total_session_duration = models.DurationField(default=timedelta(0), help_text="Total duration of all sessions")
    avg_session_duration = models.DurationField(null=True, blank=True, help_text="Average session duration")
    
    # Connection metrics
    first_connection_time = models.DateTimeField(null=True, blank=True, help_text="Time of first connection on server")
    last_connection_time = models.DateTimeField(null=True, blank=True, help_text="Time of last disconnection on server")
    
    # Peak metrics
    peak_concurrent_sessions = models.IntegerField(default=0, help_text="Maximum concurrent sessions at any point")
    peak_bytes_per_second = models.BigIntegerField(default=0, help_text="Peak transfer rate (bytes/sec)")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ui_ovpn_serverdailystats'
        ordering = ['-date']
        indexes = [
            models.Index(fields=['-date']),
            models.Index(fields=['date']),
        ]
    
    @property
    def total_bytes(self):
        """Total bytes (sent + received)."""
        return self.total_bytes_sent + self.total_bytes_received
    
    @property
    def total_bytes_sent_human(self):
        """Human-readable bytes sent."""
        return Account._format_bytes(self.total_bytes_sent)
    
    @property
    def total_bytes_received_human(self):
        """Human-readable bytes received."""
        return Account._format_bytes(self.total_bytes_received)
    
    @property
    def total_bytes_human(self):
        """Human-readable total bytes."""
        return Account._format_bytes(self.total_bytes)
    
    @property
    def total_session_duration_human(self):
        """Human-readable total session duration."""
        return ConnectionSession.format_duration(self.total_session_duration)
    
    @property
    def avg_session_duration_human(self):
        """Human-readable average session duration."""
        return ConnectionSession.format_duration(self.avg_session_duration)
    
    def __str__(self):
        return f"Server Stats - {self.date} ({self.total_bytes_human})"
