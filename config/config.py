"""
Configuration module for OpenVPN Dashboard application.

This module centralizes all configuration settings and provides
environment variable support for containerized deployments.

Environment Variables:
    OPENVPN_DIR: Base OpenVPN directory (default: /etc/openvpn)
    OPENVPN_EASY_RSA_DIR: EasyRSA directory (default: /etc/openvpn/easy-rsa)
    OPENVPN_CCD_DIR: Client Config Directory (default: /etc/openvpn/ccd)
    OPENVPN_LOG_DIR: OpenVPN log directory (default: /var/log/openvpn)
    OPENVPN_STATUS_LOG: Status log path (default: /var/log/openvpn/status.log)
    OPENVPN_CLIENT_CONFIG_DIR: Where to store .ovpn files (default: /root)
    OPENVPN_SERVER_ADDRESS: Server address for client configs (required)
    OPENVPN_SERVER_PORT: Server port (default: 443)
    OPENVPN_PROTOCOL: Protocol udp/tcp (default: udp)
    OPENVPN_CERT_EXPIRE: Server/client cert lifetime in days (default: 825, ~2 years)
    
    DATABASE_PATH: SQLite database path (default: /app/data/db.sqlite3)
    SECRET_KEY: Django secret key (required in production)
    DEBUG: Enable debug mode (default: False)
    ALLOWED_HOSTS: Comma-separated list of allowed hosts
    
    USAGE_COLLECTOR_INTERVAL: Poll interval in seconds (default: 2.0)
    USAGE_COMMIT_INTERVAL: How often to commit live usage to account totals (default: 10.0)
    
    SERVER_URL: Default server URL for client config downloads (can be set in UI)
    SERVER_PORT: Default server port for client config downloads (can be set in UI)
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


def get_env(key: str, default: str = None, required: bool = False) -> Optional[str]:
    """Get environment variable with optional default and required check."""
    value = os.environ.get(key, default)
    if required and not value:
        raise ValueError(f"Required environment variable '{key}' is not set")
    return value


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean environment variable."""
    value = os.environ.get(key, '').lower()
    if value in ('true', '1', 'yes', 'on'):
        return True
    if value in ('false', '0', 'no', 'off'):
        return False
    return default


def get_env_int(key: str, default: int = 0) -> int:
    """Get integer environment variable."""
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def get_env_float(key: str, default: float = 0.0) -> float:
    """Get float environment variable."""
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def get_env_list(key: str, default: List[str] = None, separator: str = ',') -> List[str]:
    """Get list environment variable (comma-separated by default)."""
    value = os.environ.get(key, '')
    if not value:
        return default or []
    return [item.strip() for item in value.split(separator) if item.strip()]


@dataclass
class OpenVPNSettings:
    """OpenVPN-related configuration settings."""
    
    # Base directories
    openvpn_dir: str = field(default_factory=lambda: get_env('OPENVPN_DIR', '/etc/openvpn'))
    easy_rsa_dir: str = field(default_factory=lambda: get_env('OPENVPN_EASY_RSA_DIR', '/etc/openvpn/easy-rsa'))
    ccd_dir: str = field(default_factory=lambda: get_env('OPENVPN_CCD_DIR', '/etc/openvpn/ccd'))
    log_dir: str = field(default_factory=lambda: get_env('OPENVPN_LOG_DIR', '/var/log/openvpn'))
    
    # Status and config paths
    status_log: str = field(default_factory=lambda: get_env('OPENVPN_STATUS_LOG', '/var/log/openvpn/status.log'))
    client_config_dir: str = field(default_factory=lambda: get_env('OPENVPN_CLIENT_CONFIG_DIR', '/app/configs'))
    
    # Server settings
    server_address: str = field(default_factory=lambda: get_env('OPENVPN_SERVER_ADDRESS', 'vpn.example.com'))
    server_port: str = field(default_factory=lambda: get_env('OPENVPN_SERVER_PORT', '443'))
    protocol: str = field(default_factory=lambda: get_env('OPENVPN_PROTOCOL', 'udp'))
    cert_expire_days: int = field(default_factory=lambda: get_env_int('OPENVPN_CERT_EXPIRE', 825))
    
    # Certificate settings (usually auto-detected from server.conf)
    hmac_alg: str = field(default_factory=lambda: get_env('OPENVPN_HMAC_ALG', 'SHA256'))
    cipher: str = field(default_factory=lambda: get_env('OPENVPN_CIPHER', 'AES-128-GCM'))
    cc_cipher: str = field(default_factory=lambda: get_env('OPENVPN_CC_CIPHER', 'TLS-ECDHE-ECDSA-WITH-AES-128-GCM-SHA256'))
    
    @property
    def pki_dir(self) -> str:
        return os.path.join(self.easy_rsa_dir, "pki")
    
    @property
    def index_file(self) -> str:
        return os.path.join(self.pki_dir, "index.txt")
    
    @property
    def ca_cert(self) -> str:
        return os.path.join(self.pki_dir, "ca.crt")
    
    @property
    def tls_crypt_key(self) -> str:
        return os.path.join(self.openvpn_dir, "tls-crypt.key")
    
    @property
    def tls_auth_key(self) -> str:
        return os.path.join(self.openvpn_dir, "tls-auth.key")
    
    @property
    def server_conf(self) -> str:
        return os.path.join(self.openvpn_dir, "server.conf")
    
    @property
    def client_template(self) -> str:
        return os.path.join(self.openvpn_dir, "client-template.txt")
    
    def to_dict(self) -> dict:
        """Convert settings to dictionary for Django settings."""
        return {
            'openvpn_dir': self.openvpn_dir,
            'easy_rsa_dir': self.easy_rsa_dir,
            'ccd_path': self.ccd_dir,
            'log_dir': self.log_dir,
            'status_log': self.status_log,
            'config_dir': self.client_config_dir,
            'server_address': self.server_address,
            'server_port': self.server_port,
            'protocol': self.protocol,
            'server_conf': self.server_conf,
        }


@dataclass
class AppSettings:
    """Application-level configuration settings."""
    
    # Django settings
    secret_key: str = field(default_factory=lambda: get_env(
        'SECRET_KEY', 
        'django-insecure-change-me-in-production'
    ))
    debug: bool = field(default_factory=lambda: get_env_bool('DEBUG', False))
    allowed_hosts: List[str] = field(default_factory=lambda: get_env_list('ALLOWED_HOSTS', ['*']))
    
    # Database
    database_path: str = field(default_factory=lambda: get_env('DATABASE_PATH', '/app/data/db.sqlite3'))
    
    # Static files
    static_root: str = field(default_factory=lambda: get_env('STATIC_ROOT', '/app/staticfiles'))
    
    # Usage collector
    usage_collector_interval: float = field(default_factory=lambda: get_env_float('USAGE_COLLECTOR_INTERVAL', 2.0))
    usage_commit_interval: float = field(default_factory=lambda: get_env_float('USAGE_COMMIT_INTERVAL', 10.0))
    
    # Logging
    log_level: str = field(default_factory=lambda: get_env('LOG_LEVEL', 'INFO'))
    
    # CSRF settings for reverse proxy
    csrf_trusted_origins: List[str] = field(default_factory=lambda: get_env_list('CSRF_TRUSTED_ORIGINS', []))
    
    # Time zone
    time_zone: str = field(default_factory=lambda: get_env('TIME_ZONE', 'UTC'))


@dataclass
class Config:
    """Main configuration container."""
    
    openvpn: OpenVPNSettings = field(default_factory=OpenVPNSettings)
    app: AppSettings = field(default_factory=AppSettings)
    
    def validate(self) -> List[str]:
        """Validate configuration and return list of warnings/errors."""
        issues = []
        
        # Check critical paths exist (only warn, don't fail)
        if not os.path.exists(self.openvpn.openvpn_dir):
            issues.append(f"OpenVPN directory not found: {self.openvpn.openvpn_dir}")
        
        if not os.path.exists(self.openvpn.server_conf):
            issues.append(f"OpenVPN server.conf not found: {self.openvpn.server_conf}")
        
        # Check for default secret key in production
        if not self.app.debug and 'insecure' in self.app.secret_key:
            issues.append("Using insecure SECRET_KEY in production mode!")
        
        # Ensure database directory exists
        db_dir = os.path.dirname(self.app.database_path)
        if db_dir and not os.path.exists(db_dir):
            try:
                os.makedirs(db_dir, exist_ok=True)
            except OSError as e:
                issues.append(f"Cannot create database directory {db_dir}: {e}")
        
        # Ensure client config directory exists
        if not os.path.exists(self.openvpn.client_config_dir):
            try:
                os.makedirs(self.openvpn.client_config_dir, exist_ok=True)
            except OSError as e:
                issues.append(f"Cannot create client config directory: {e}")
        
        return issues


# Global configuration instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get or create the global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload configuration from environment variables."""
    global _config
    _config = Config()
    return _config


# Convenience functions
def get_openvpn_settings() -> OpenVPNSettings:
    """Get OpenVPN settings."""
    return get_config().openvpn


def get_app_settings() -> AppSettings:
    """Get application settings."""
    return get_config().app

