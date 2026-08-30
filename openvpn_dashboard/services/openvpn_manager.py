"""
OpenVPN Manager - Python implementation
Replaces shell script functionality for better control and integration.

This module provides functions to manage OpenVPN clients:
- Create new clients
- List clients
- Disable/Enable clients
- Revoke clients
- Renew client certificates
- Get client status using openvpn-status library

Based on: https://github.com/angristan/openvpn-install
Status parsing: https://github.com/tonyseek/openvpn-status
"""

import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)


def _get_config_default(key: str, default: str) -> str:
    """Get configuration from environment or use default."""
    import os
    return os.environ.get(key, default)


@dataclass
class OpenVPNConfig:
    """Configuration for OpenVPN paths and settings.
    
    All paths can be configured via environment variables for Docker deployment.
    """
    # Base paths - configurable via environment variables
    openvpn_dir: str = None
    easy_rsa_dir: str = None
    ccd_dir: str = None
    log_dir: str = None
    
    # Status log path
    status_log: str = None
    
    # Client config output directory
    client_config_dir: str = None
    
    # Server settings (read from server.conf or set defaults)
    server_address: str = None
    server_port: str = None
    protocol: str = None
    
    # Certificate settings
    hmac_alg: str = None
    cipher: str = None
    cc_cipher: str = None
    cert_expire_days: int = None
    
    def __post_init__(self):
        """Initialize with environment variables or defaults."""
        import os
        
        # Base paths
        self.openvpn_dir = self.openvpn_dir or os.environ.get('OPENVPN_DIR', '/etc/openvpn')
        self.easy_rsa_dir = self.easy_rsa_dir or os.environ.get('OPENVPN_EASY_RSA_DIR', '/etc/openvpn/easy-rsa')
        self.ccd_dir = self.ccd_dir or os.environ.get('OPENVPN_CCD_DIR', '/etc/openvpn/ccd')
        self.log_dir = self.log_dir or os.environ.get('OPENVPN_LOG_DIR', '/var/log/openvpn')
        
        # Status and config paths
        self.status_log = self.status_log or os.environ.get('OPENVPN_STATUS_LOG', '/var/log/openvpn/status.log')
        self.client_config_dir = self.client_config_dir or os.environ.get('OPENVPN_CLIENT_CONFIG_DIR', '/app/configs')
        
        # Server settings
        self.server_address = self.server_address or os.environ.get('OPENVPN_SERVER_ADDRESS', 'vpn.example.com')
        self.server_port = self.server_port or os.environ.get('OPENVPN_SERVER_PORT', '443')
        self.protocol = self.protocol or os.environ.get('OPENVPN_PROTOCOL', 'udp')
        
        # Certificate settings
        self.hmac_alg = self.hmac_alg or os.environ.get('OPENVPN_HMAC_ALG', 'SHA256')
        self.cipher = self.cipher or os.environ.get('OPENVPN_CIPHER', 'AES-128-GCM')
        self.cc_cipher = self.cc_cipher or os.environ.get('OPENVPN_CC_CIPHER', 'TLS-ECDHE-ECDSA-WITH-AES-128-GCM-SHA256')
        try:
            self.cert_expire_days = int(
                self.cert_expire_days
                if self.cert_expire_days is not None
                else os.environ.get('OPENVPN_CERT_EXPIRE', os.environ.get('EASYRSA_CERT_EXPIRE', '825'))
            )
        except (TypeError, ValueError):
            self.cert_expire_days = 825
    
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


@dataclass
class ClientInfo:
    """Information about an OpenVPN client."""
    common_name: str
    status: str  # 'V' = Valid, 'R' = Revoked, 'E' = Expired
    expiration_date: Optional[datetime] = None
    revocation_date: Optional[datetime] = None
    serial: Optional[str] = None
    
    @property
    def is_valid(self) -> bool:
        return self.status == 'V'
    
    @property
    def is_revoked(self) -> bool:
        return self.status == 'R'


@dataclass 
class ConnectedClient:
    """Information about a currently connected OpenVPN client."""
    common_name: str
    real_address: str
    bytes_received: int
    bytes_sent: int
    connected_since: datetime
    virtual_address: Optional[str] = None
    
    @property
    def bytes_received_human(self) -> str:
        return self._format_bytes(self.bytes_received)
    
    @property
    def bytes_sent_human(self) -> str:
        return self._format_bytes(self.bytes_sent)
    
    @staticmethod
    def _format_bytes(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"


class OpenVPNManagerError(Exception):
    """Base exception for OpenVPN Manager errors."""
    pass


class ClientExistsError(OpenVPNManagerError):
    """Raised when trying to create a client that already exists."""
    pass


class ClientNotFoundError(OpenVPNManagerError):
    """Raised when a client is not found."""
    pass


class EasyRSAError(OpenVPNManagerError):
    """Raised when an EasyRSA command fails."""
    pass


class OpenVPNManager:
    """
    Manages OpenVPN clients using EasyRSA.
    
    This class provides a Python interface for managing OpenVPN clients,
    replacing the shell script functionality for better control and error handling.
    """
    
    def __init__(self, config: Optional[OpenVPNConfig] = None):
        """
        Initialize the OpenVPN Manager.
        
        Args:
            config: OpenVPNConfig instance with paths and settings.
                   If None, uses default configuration.
        """
        self.config = config or OpenVPNConfig()
        self._validate_installation()
        self._load_server_config()
    
    def _validate_installation(self) -> None:
        """Validate that OpenVPN and EasyRSA are properly installed."""
        if not os.path.exists(self.config.server_conf):
            raise OpenVPNManagerError(
                f"OpenVPN server config not found at {self.config.server_conf}. "
                "Please install OpenVPN first."
            )
        
        if not os.path.exists(self.config.easy_rsa_dir):
            raise OpenVPNManagerError(
                f"EasyRSA not found at {self.config.easy_rsa_dir}. "
                "Please install EasyRSA first."
            )
    
    def _load_server_config(self) -> None:
        """Load server configuration from server.conf."""
        try:
            with open(self.config.server_conf, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('port '):
                        self.config.server_port = line.split()[1]
                    elif line.startswith('proto '):
                        proto = line.split()[1]
                        self.config.protocol = proto.replace('6', '')  # Remove '6' suffix
                    elif line.startswith('auth '):
                        self.config.hmac_alg = line.split()[1]
                    elif line.startswith('cipher '):
                        self.config.cipher = line.split()[1]
                    elif line.startswith('tls-cipher '):
                        self.config.cc_cipher = line.split()[1]
        except Exception as e:
            logger.warning(f"Could not load server config: {e}")
    
    def _cert_expire_env(self, cert_days: Optional[int] = None) -> Dict[str, str]:
        """Easy-RSA env for end-entity cert lifetime (OPENVPN_CERT_EXPIRE, default 825)."""
        days = cert_days if cert_days is not None else self.config.cert_expire_days
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 825
        if days < 1:
            days = 825
        return {"EASYRSA_CERT_EXPIRE": str(days)}

    def _run_easyrsa(self, *args, env: Optional[Dict] = None) -> subprocess.CompletedProcess:
        """
        Run an EasyRSA command.
        
        Args:
            *args: Command arguments to pass to EasyRSA.
            env: Optional environment variables.
        
        Returns:
            CompletedProcess instance.
        
        Raises:
            EasyRSAError: If the command fails.
        """
        easyrsa_script = os.path.join(self.config.easy_rsa_dir, "easyrsa")
        cmd = [easyrsa_script] + list(args)
        
        run_env = os.environ.copy()
        if env:
            run_env.update(env)
        
        try:
            result = subprocess.run(
                cmd,
                cwd=self.config.easy_rsa_dir,
                env=run_env,
                capture_output=True,
                text=True,
                check=True
            )
            return result
        except subprocess.CalledProcessError as e:
            logger.error(f"EasyRSA command failed: {e.stderr}")
            raise EasyRSAError(f"EasyRSA command failed: {e.stderr}")
    
    def _get_server_name(self) -> str:
        """Get the server name from server.conf or generated file."""
        # Try to get from server.conf (new script method)
        try:
            with open(self.config.server_conf, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('cert '):
                        cert_path = line.split()[1]
                        # Extract basename and remove .crt extension
                        server_name = os.path.basename(cert_path)
                        if server_name.endswith('.crt'):
                            server_name = server_name[:-4]
                        if server_name:
                            return server_name
        except Exception:
            pass
        
        # Fallback to old method (read from generated file)
        server_name_file = os.path.join(self.config.easy_rsa_dir, "SERVER_NAME_GENERATED")
        try:
            with open(server_name_file, 'r') as f:
                return f.read().strip()
        except FileNotFoundError:
            raise OpenVPNManagerError(
                "Could not determine server certificate name. "
                "Please check server.conf or ensure OpenVPN is properly installed."
            )
    
    def _get_tls_type(self) -> str:
        """Determine if server uses tls-crypt or tls-auth."""
        try:
            with open(self.config.server_conf, 'r') as f:
                content = f.read()
                if 'tls-crypt' in content:
                    return 'tls-crypt'
                elif 'tls-auth' in content:
                    return 'tls-auth'
        except Exception:
            pass
        return 'tls-crypt'  # Default
    
    def _validate_and_fix_index_file(self) -> None:
        """
        Validate and fix the EasyRSA index.txt file.
        
        Removes or fixes entries with invalid date formats that can cause
        EasyRSA certificate creation to fail.
        
        The index.txt format is:
        - Status (V=Valid, R=Revoked, E=Expired)
        - Expiration date (YYMMDDHHMMSSZ) - 13 characters
        - Revocation date (YYMMDDHHMMSSZ) - 13 characters, only for revoked
        - Serial number
        - Filename or subject
        
        Invalid dates are those that don't match the YYMMDDHHMMSSZ format.
        """
        if not os.path.exists(self.config.index_file):
            return
        
        import re
        import shutil
        from datetime import datetime
        
        def is_valid_date(date_str: str) -> bool:
            """
            Validate that a date string matches YYMMDDHHMMSSZ format and is parseable.
            
            Args:
                date_str: Date string in YYMMDDHHMMSSZ format
                
            Returns:
                True if valid, False otherwise
            """
            if not date_str:
                return True  # Empty dates are allowed for non-revoked certs
            
            # Must be exactly 13 characters ending with Z
            if not re.match(r'^\d{12}Z$', date_str):
                return False
            
            try:
                # Parse the date: YYMMDDHHMMSSZ
                year = int(date_str[0:2])
                month = int(date_str[2:4])
                day = int(date_str[4:6])
                hour = int(date_str[6:8])
                minute = int(date_str[8:10])
                second = int(date_str[10:12])
                
                # Convert 2-digit year to 4-digit (assume 2000-2099)
                full_year = 2000 + year if year < 100 else year
                
                # Try to create a datetime object to validate the date
                datetime(full_year, month, day, hour, minute, second)
                return True
            except (ValueError, IndexError):
                return False
        
        try:
            # Backup the original file
            backup_path = f"{self.config.index_file}.bak"
            shutil.copy2(self.config.index_file, backup_path)
            logger.info(f"Backed up index.txt to {backup_path}")
            
            # Read and validate all lines
            valid_lines = []
            invalid_count = 0
            
            with open(self.config.index_file, 'r') as f:
                lines = f.readlines()
            
            for line_num, line in enumerate(lines, start=1):
                line = line.rstrip('\n\r')
                
                # Skip empty lines
                if not line.strip():
                    valid_lines.append(line + '\n')
                    continue
                
                # Parse the line (tab-separated)
                parts = line.split('\t')
                
                if len(parts) < 2:
                    # Keep lines that don't match expected format (might be comments or headers)
                    valid_lines.append(line + '\n')
                    continue
                
                status = parts[0].strip()
                exp_date = parts[1].strip() if len(parts) > 1 else ''
                rev_date = parts[2].strip() if len(parts) > 2 else ''
                
                # Validate dates
                exp_date_valid = is_valid_date(exp_date)
                rev_date_valid = is_valid_date(rev_date)
                
                # For revoked certificates (R), both dates should be valid
                # For valid certificates (V), expiration date should be valid
                if status == 'R':
                    if not exp_date_valid or not rev_date_valid:
                        logger.warning(
                            f"Removing invalid entry at line {line_num}: "
                            f"status={status}, exp_date={exp_date}, rev_date={rev_date}"
                        )
                        invalid_count += 1
                        continue
                elif status == 'V' or status == 'E':
                    if not exp_date_valid:
                        logger.warning(
                            f"Removing invalid entry at line {line_num}: "
                            f"status={status}, exp_date={exp_date}"
                        )
                        invalid_count += 1
                        continue
                
                # Line is valid, keep it
                valid_lines.append(line + '\n')
            
            # Write back the cleaned file
            if invalid_count > 0:
                with open(self.config.index_file, 'w') as f:
                    f.writelines(valid_lines)
                logger.info(
                    f"Fixed index.txt: removed {invalid_count} invalid entries. "
                    f"Backup saved to {backup_path}"
                )
            else:
                # Remove backup if no changes were needed
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                    
        except Exception as e:
            logger.error(f"Failed to validate/fix index.txt: {e}")
            # Don't raise - we'll let EasyRSA handle it, but log the error
    
    def client_exists(self, client_name: str) -> bool:
        """
        Check if a client certificate already exists.
        
        Args:
            client_name: The client name to check.
        
        Returns:
            True if client exists and is valid, False otherwise.
        """
        if not os.path.exists(self.config.index_file):
            return False
        
        try:
            with open(self.config.index_file, 'r') as f:
                for line in f:
                    if line.startswith('V') and f"/CN={client_name}" in line:
                        return True
        except Exception:
            pass
        return False
    
    def list_clients(self) -> List[ClientInfo]:
        """
        List all clients from the EasyRSA index.
        
        Returns:
            List of ClientInfo objects.
        """
        clients = []
        
        if not os.path.exists(self.config.index_file):
            return clients
        
        try:
            with open(self.config.index_file, 'r') as f:
                for line in f:
                    parts = line.strip().split('\t')
                    if len(parts) >= 5:
                        status = parts[0]
                        # Skip the server certificate
                        cn_part = parts[-1]
                        if '/CN=' in cn_part:
                            cn = cn_part.split('/CN=')[-1]
                            # Skip server certificates
                            if cn.startswith('server_') or cn.startswith('cn_'):
                                continue
                            
                            client = ClientInfo(
                                common_name=cn,
                                status=status,
                                serial=parts[3] if len(parts) > 3 else None
                            )
                            clients.append(client)
        except Exception as e:
            logger.error(f"Failed to list clients: {e}")
        
        return clients
    
    def get_valid_clients(self) -> List[ClientInfo]:
        """Get only valid (non-revoked) clients."""
        return [c for c in self.list_clients() if c.is_valid]
    
    def create_client(
        self, 
        client_name: str, 
        password: Optional[str] = None
    ) -> str:
        """
        Create a new OpenVPN client.
        
        Args:
            client_name: Name for the new client (alphanumeric, underscore, dash only).
            password: Optional password to protect the private key.
        
        Returns:
            Path to the generated .ovpn file.
        
        Raises:
            ClientExistsError: If client already exists.
            EasyRSAError: If certificate generation fails.
            ValueError: If client_name is invalid.
        """
        # Validate client name
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', client_name):
            raise ValueError(
                "Client name must consist of alphanumeric characters, "
                "underscores, or dashes only."
            )
        
        # Check if client already exists
        if self.client_exists(client_name):
            raise ClientExistsError(
                f"Client '{client_name}' already exists. Choose another name."
            )
        
        # Validate and fix index.txt file before creating certificate
        # This prevents failures due to invalid date formats in the index
        self._validate_and_fix_index_file()
        
        # Build client certificate
        logger.info(
            f"Creating client certificate for '{client_name}' "
            f"(valid {self.config.cert_expire_days} days)..."
        )
        
        cert_env = self._cert_expire_env()
        if password:
            # With password protection
            self._run_easyrsa("--batch", "build-client-full", client_name, env=cert_env)
        else:
            # Without password (nopass)
            self._run_easyrsa("--batch", "build-client-full", client_name, "nopass", env=cert_env)
        
        logger.info(f"Client certificate for '{client_name}' created successfully.")
        
        # Generate the .ovpn configuration file
        ovpn_path = self._generate_client_config(client_name)
        
        return ovpn_path
    
    def _generate_client_config(self, client_name: str) -> str:
        """
        Generate the .ovpn configuration file for a client.
        
        Args:
            client_name: The client name.
        
        Returns:
            Path to the generated .ovpn file.
        """
        server_name = self._get_server_name()
        tls_type = self._get_tls_type()
        
        # Paths to certificate files
        ca_cert = self.config.ca_cert
        client_cert = os.path.join(self.config.pki_dir, "issued", f"{client_name}.crt")
        client_key = os.path.join(self.config.pki_dir, "private", f"{client_name}.key")
        
        # Read certificate contents
        with open(ca_cert, 'r') as f:
            ca_content = f.read()
        
        # Extract only the certificate part (between BEGIN and END)
        with open(client_cert, 'r') as f:
            cert_content = f.read()
            # Extract certificate block
            import re
            cert_match = re.search(
                r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
                cert_content,
                re.DOTALL
            )
            cert_content = cert_match.group(0) if cert_match else cert_content
        
        with open(client_key, 'r') as f:
            key_content = f.read()
        
        # TLS key content
        if tls_type == 'tls-crypt':
            tls_key_path = self.config.tls_crypt_key
        else:
            tls_key_path = self.config.tls_auth_key
        
        with open(tls_key_path, 'r') as f:
            tls_key_content = f.read()
        
        # Build the configuration
        config_lines = [
            "client",
            f"proto {self.config.protocol}",
        ]
        
        if self.config.protocol == 'udp':
            config_lines.append("explicit-exit-notify")
        
        config_lines.extend([
            f"remote {self.config.server_address} {self.config.server_port}",
            "dev tun",
            "resolv-retry infinite",
            "nobind",
            "persist-key",
            "persist-tun",
            "remote-cert-tls server",
            f"verify-x509-name {server_name} name",
            f"auth {self.config.hmac_alg}",
            "auth-nocache",
            f"cipher {self.config.cipher}",
            "tls-client",
            "tls-version-min 1.2",
            f"tls-cipher {self.config.cc_cipher}",
            "ignore-unknown-option block-outside-dns",
            "setenv opt block-outside-dns",
            "verb 3",
            "",
            "<ca>",
            ca_content.strip(),
            "</ca>",
            "",
            "<cert>",
            cert_content.strip(),
            "</cert>",
            "",
            "<key>",
            key_content.strip(),
            "</key>",
            "",
        ])
        
        if tls_type == 'tls-crypt':
            config_lines.extend([
                "<tls-crypt>",
                tls_key_content.strip(),
                "</tls-crypt>",
            ])
        else:
            config_lines.extend([
                "key-direction 1",
                "<tls-auth>",
                tls_key_content.strip(),
                "</tls-auth>",
            ])
        
        # Write the configuration file
        ovpn_path = os.path.join(self.config.client_config_dir, f"{client_name}.ovpn")
        with open(ovpn_path, 'w') as f:
            f.write('\n'.join(config_lines))
        
        logger.info(f"Configuration file written to {ovpn_path}")
        return ovpn_path
    
    def disable_client(self, client_name: str) -> bool:
        """
        Disable a client by adding a CCD file with --disable directive.
        
        Args:
            client_name: The client name to disable.
        
        Returns:
            True if successful.
        """
        ccd_file = os.path.join(self.config.ccd_dir, client_name)
        
        # Ensure CCD directory exists
        os.makedirs(self.config.ccd_dir, exist_ok=True)
        
        with open(ccd_file, 'w') as f:
            f.write("disable\n")
        
        logger.info(f"Client '{client_name}' disabled.")
        return True
    
    def enable_client(self, client_name: str) -> bool:
        """
        Enable a client by removing the CCD disable file.
        
        Args:
            client_name: The client name to enable.
        
        Returns:
            True if successful.
        """
        ccd_file = os.path.join(self.config.ccd_dir, client_name)
        
        if os.path.exists(ccd_file):
            os.remove(ccd_file)
            logger.info(f"Client '{client_name}' enabled.")
        else:
            logger.info(f"Client '{client_name}' was not disabled.")
        
        return True
    
    def is_client_disabled(self, client_name: str) -> bool:
        """Check if a client is disabled via CCD."""
        ccd_file = os.path.join(self.config.ccd_dir, client_name)
        return os.path.exists(ccd_file)
    
    def revoke_client(self, client_name: str) -> bool:
        """
        Revoke a client certificate.
        
        Args:
            client_name: The client name to revoke.
        
        Returns:
            True if successful.
        
        Raises:
            ClientNotFoundError: If client doesn't exist.
            EasyRSAError: If revocation fails.
        """
        if not self.client_exists(client_name):
            raise ClientNotFoundError(f"Client '{client_name}' not found.")
        
        # Revoke the certificate
        self._run_easyrsa("--batch", "revoke", client_name)
        
        # Regenerate CRL
        self._regenerate_crl()
        
        # Remove client config files
        self._cleanup_client_files(client_name)
        
        # Remove from ipp.txt if present
        ipp_file = os.path.join(self.config.openvpn_dir, "ipp.txt")
        if os.path.exists(ipp_file):
            with open(ipp_file, 'r') as f:
                lines = f.readlines()
            with open(ipp_file, 'w') as f:
                for line in lines:
                    if not line.startswith(f"{client_name},"):
                        f.write(line)
        
        logger.info(f"Client '{client_name}' revoked successfully.")
        return True
    
    def _cleanup_client_files(self, client_name: str) -> None:
        """Remove client configuration files."""
        # Remove from /root
        ovpn_file = os.path.join("/root", f"{client_name}.ovpn")
        if os.path.exists(ovpn_file):
            os.remove(ovpn_file)
        
        # Remove from home directories
        for home_dir in Path("/home").iterdir():
            if home_dir.is_dir():
                ovpn_file = home_dir / f"{client_name}.ovpn"
                if ovpn_file.exists():
                    ovpn_file.unlink()
        
        # Remove CCD file if exists
        ccd_file = os.path.join(self.config.ccd_dir, client_name)
        if os.path.exists(ccd_file):
            os.remove(ccd_file)
    
    def _regenerate_crl(self, crl_days: int = 3650) -> None:
        """
        Regenerate the Certificate Revocation List (CRL).
        
        Args:
            crl_days: Number of days the CRL should be valid for.
        
        Raises:
            EasyRSAError: If CRL regeneration fails.
        """
        # Regenerate CRL
        self._run_easyrsa("gen-crl", env={"EASYRSA_CRL_DAYS": str(crl_days)})
        
        # Update CRL in OpenVPN directory
        crl_src = os.path.join(self.config.pki_dir, "crl.pem")
        crl_dst = os.path.join(self.config.openvpn_dir, "crl.pem")
        
        # Remove old CRL if it exists
        if os.path.exists(crl_dst):
            os.remove(crl_dst)
        
        # Copy new CRL
        shutil.copy(crl_src, crl_dst)
        os.chmod(crl_dst, 0o644)
        
        logger.info("CRL regenerated successfully.")
    
    def renew_client(self, client_name: str, cert_days: Optional[int] = None) -> str:
        """
        Renew a client certificate.
        
        This method follows the new script's renewal process:
        1. Backs up the old certificate
        2. Renews the certificate (with optional custom duration)
        3. Revokes the old certificate using revoke-renewed
        4. Regenerates the CRL
        5. Regenerates the .ovpn configuration file
        
        Args:
            client_name: The client name to renew.
            cert_days: Optional number of days the certificate should be valid for.
                      If None, uses the default EasyRSA certificate validity.
        
        Returns:
            Path to the new .ovpn file.
        
        Raises:
            ClientNotFoundError: If client doesn't exist.
            EasyRSAError: If renewal fails.
        """
        if not self.client_exists(client_name):
            raise ClientNotFoundError(f"Client '{client_name}' not found.")
        
        logger.info(f"Renewing certificate for '{client_name}'...")
        
        # Backup the old certificate before renewal
        old_cert_path = os.path.join(self.config.pki_dir, "issued", f"{client_name}.crt")
        if os.path.exists(old_cert_path):
            backup_path = f"{old_cert_path}.bak"
            shutil.copy(old_cert_path, backup_path)
            logger.info(f"Backed up old certificate to {backup_path}")
        
        env = self._cert_expire_env(cert_days)
        
        # Renew the certificate
        self._run_easyrsa("--batch", "renew", client_name, env=env)
        
        # Revoke the old certificate using revoke-renewed
        try:
            self._run_easyrsa("--batch", "revoke-renewed", client_name)
            logger.info(f"Old certificate for '{client_name}' revoked.")
        except EasyRSAError as e:
            # If revoke-renewed fails, log warning but continue
            logger.warning(f"Failed to revoke old certificate (this may be normal for first renewal): {e}")
        
        # Regenerate the CRL
        self._regenerate_crl()
        
        # Regenerate the .ovpn file
        ovpn_path = self._generate_client_config(client_name)
        
        logger.info(f"Client '{client_name}' certificate renewed successfully.")
        return ovpn_path
    
    def renew_server(self, cert_days: Optional[int] = None, restart_service: bool = True) -> bool:
        """
        Renew the server certificate.
        
        This method follows the new script's renewal process:
        1. Backs up the old certificate
        2. Renews the certificate (with optional custom duration)
        3. Revokes the old certificate using revoke-renewed
        4. Regenerates the CRL
        5. Copies the new certificate to the OpenVPN server directory
        6. Optionally restarts the OpenVPN service
        
        Args:
            cert_days: Optional number of days the certificate should be valid for.
                      If None, uses the default EasyRSA certificate validity.
            restart_service: Whether to restart the OpenVPN service after renewal.
                           Defaults to True.
        
        Returns:
            True if successful.
        
        Raises:
            OpenVPNManagerError: If server certificate cannot be determined or renewal fails.
            EasyRSAError: If renewal fails.
        """
        # Get the server name from the config
        server_name = self._get_server_name()
        
        logger.info(f"Renewing server certificate '{server_name}'...")
        
        # Backup the old certificate before renewal
        old_cert_path = os.path.join(self.config.pki_dir, "issued", f"{server_name}.crt")
        if os.path.exists(old_cert_path):
            backup_path = f"{old_cert_path}.bak"
            shutil.copy(old_cert_path, backup_path)
            logger.info(f"Backed up old server certificate to {backup_path}")
        
        env = self._cert_expire_env(cert_days)
        
        # Renew the certificate
        self._run_easyrsa("--batch", "renew", server_name, env=env)
        
        # Revoke the old certificate using revoke-renewed
        try:
            self._run_easyrsa("--batch", "revoke-renewed", server_name)
            logger.info(f"Old server certificate revoked.")
        except EasyRSAError as e:
            # If revoke-renewed fails, log warning but continue
            logger.warning(f"Failed to revoke old server certificate (this may be normal for first renewal): {e}")
        
        # Regenerate the CRL
        self._regenerate_crl()
        
        # Copy the new certificate to /etc/openvpn/server/
        new_cert_src = os.path.join(self.config.pki_dir, "issued", f"{server_name}.crt")
        new_cert_dst = os.path.join(self.config.openvpn_dir, f"{server_name}.crt")
        
        if not os.path.exists(new_cert_src):
            raise OpenVPNManagerError(f"Renewed certificate not found at {new_cert_src}")
        
        shutil.copy(new_cert_src, new_cert_dst)
        logger.info(f"Copied new server certificate to {new_cert_dst}")
        
        # Restart OpenVPN service if requested
        if restart_service:
            try:
                result = subprocess.run(
                    ["systemctl", "restart", "openvpn-server@server"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                logger.info("OpenVPN service restarted successfully.")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to restart OpenVPN service: {e.stderr}")
                # Don't fail the renewal if restart fails - admin can restart manually
            except FileNotFoundError:
                logger.warning("systemctl not found. Please restart OpenVPN service manually.")
        
        logger.info(f"Server certificate '{server_name}' renewed successfully.")
        return True
    
    def get_client_config_path(self, client_name: str) -> Optional[str]:
        """
        Get the path to a client's .ovpn configuration file.
        
        Args:
            client_name: The client name.
        
        Returns:
            Path to the .ovpn file if it exists, None otherwise.
        """
        ovpn_path = os.path.join(self.config.client_config_dir, f"{client_name}.ovpn")
        return ovpn_path if os.path.exists(ovpn_path) else None
    
    def get_connected_clients(self) -> List[ConnectedClient]:
        """
        Get list of currently connected clients.

        Tries openvpn-status (v1), then the shared v1/v2 fallback so
        status-version 2 CLIENT_LIST rows are visible.
        
        Returns:
            List of ConnectedClient objects.
        """
        if not os.path.exists(self.config.status_log):
            logger.warning(f"Status log not found at {self.config.status_log}")
            return []

        try:
            from .status_log import parse_status_log_file
            return self._clients_from_parsed(parse_status_log_file(self.config.status_log))
        except Exception as e:
            logger.error(f"Failed to parse status log: {e}")
            return self._get_connected_clients_fallback()

    def _clients_from_parsed(self, parsed) -> List[ConnectedClient]:
        clients = []
        for item in parsed:
            common_name = item.get('common_name') or item.get('name') or ''
            if not common_name:
                continue
            connected_since = item.get('connected_since') or datetime.now()
            clients.append(ConnectedClient(
                common_name=common_name,
                real_address=item.get('real_address') or '',
                bytes_received=int(item.get('bytes_received') or 0),
                bytes_sent=int(item.get('bytes_sent') or 0),
                connected_since=connected_since,
                virtual_address=item.get('virtual_address'),
            ))
        return clients
    
    def _get_connected_clients_fallback(self) -> List[ConnectedClient]:
        """Fallback method to parse status log (v2 CLIENT_LIST and legacy v1)."""
        if not os.path.exists(self.config.status_log):
            return []
        
        try:
            from .status_log import parse_status_log_file
            return self._clients_from_parsed(parse_status_log_file(self.config.status_log))
        except Exception as e:
            logger.error(f"Failed to parse status log (fallback): {e}")
            return []
    
    def get_status_summary(self) -> Dict:
        """
        Get a summary of OpenVPN server status.
        
        Returns:
            Dictionary with status information.
        """
        connected = self.get_connected_clients()
        all_clients = self.list_clients()
        valid_clients = [c for c in all_clients if c.is_valid]
        revoked_clients = [c for c in all_clients if c.is_revoked]
        
        return {
            "connected_count": len(connected),
            "connected_clients": [c.common_name for c in connected],
            "total_clients": len(valid_clients),
            "revoked_clients": len(revoked_clients),
            "total_bytes_received": sum(c.bytes_received for c in connected),
            "total_bytes_sent": sum(c.bytes_sent for c in connected),
        }


# Convenience functions for direct use
_manager: Optional[OpenVPNManager] = None


def get_manager() -> OpenVPNManager:
    """Get or create the global OpenVPN manager instance."""
    global _manager
    if _manager is None:
        _manager = OpenVPNManager()
    return _manager


def create_client(client_name: str, password: Optional[str] = None) -> str:
    """Create a new OpenVPN client."""
    return get_manager().create_client(client_name, password)


def disable_client(client_name: str) -> bool:
    """Disable an OpenVPN client."""
    return get_manager().disable_client(client_name)


def enable_client(client_name: str) -> bool:
    """Enable an OpenVPN client."""
    return get_manager().enable_client(client_name)


def revoke_client(client_name: str) -> bool:
    """Revoke an OpenVPN client certificate."""
    return get_manager().revoke_client(client_name)


def list_clients() -> List[ClientInfo]:
    """List all OpenVPN clients."""
    return get_manager().list_clients()


def get_connected_clients() -> List[ConnectedClient]:
    """Get currently connected clients."""
    return get_manager().get_connected_clients()


def renew_client(client_name: str, cert_days: Optional[int] = None) -> str:
    """Renew an OpenVPN client certificate."""
    return get_manager().renew_client(client_name, cert_days)


def renew_server(cert_days: Optional[int] = None, restart_service: bool = True) -> bool:
    """Renew the OpenVPN server certificate."""
    return get_manager().renew_server(cert_days, restart_service)

