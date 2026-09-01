"""
Utility functions for OpenVPN Dashboard management.
This module provides the interface between Django views and the OpenVPN manager.
"""

import os
import logging
from typing import Optional, Dict, List
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse

from config.config import get_openvpn_settings

# Configure logging
logger = logging.getLogger(__name__)

# Get OpenVPN settings from centralized config
_ovpn_settings = get_openvpn_settings()

# Configuration - can be overridden in Django settings (for backwards compatibility)
OPENVPN_CONFIG = getattr(settings, 'OPENVPN_CONFIG', {})

# Paths from centralized config
CCD_PATH = OPENVPN_CONFIG.get('ccd_path', _ovpn_settings.ccd_dir)
CONFIG_DIR = OPENVPN_CONFIG.get('config_dir', _ovpn_settings.client_config_dir)
SERVER_ADDRESS = OPENVPN_CONFIG.get('server_address', _ovpn_settings.server_address)
SERVER_PORT = OPENVPN_CONFIG.get('server_port', _ovpn_settings.server_port)
STATUS_LOG = OPENVPN_CONFIG.get('status_log', _ovpn_settings.status_log)

# Flag to check if OpenVPN is available
_openvpn_available: Optional[bool] = None


def is_openvpn_available() -> bool:
    """Check if OpenVPN is installed and configured."""
    global _openvpn_available
    
    if _openvpn_available is None:
        server_conf = OPENVPN_CONFIG.get('server_conf', '/etc/openvpn/server.conf')
        _openvpn_available = os.path.exists(server_conf)
        if not _openvpn_available:
            logger.warning(
                f"OpenVPN not available (server.conf not found at {server_conf}). "
                "Some features will be disabled."
            )
    
    return _openvpn_available


def get_openvpn_manager():
    """
    Get or create the OpenVPN manager instance.
    
    Returns:
        OpenVPNManager instance or None if OpenVPN is not available.
    """
    if not is_openvpn_available():
        return None
    
    try:
        from .openvpn_manager import (
            OpenVPNManager,
            OpenVPNConfig,
        )
        
        config = OpenVPNConfig(
            ccd_dir=CCD_PATH,
            client_config_dir=CONFIG_DIR,
            server_address=SERVER_ADDRESS,
            server_port=SERVER_PORT,
            status_log=STATUS_LOG,
        )
        return OpenVPNManager(config)
    except Exception as e:
        logger.error(f"Failed to initialize OpenVPN manager: {e}")
        return None


def create_openvpn_config(account: str, password: Optional[str] = None) -> str:
    """
    Create a new OpenVPN client configuration.
    
    Args:
        account: The account/client name.
        password: Optional password for private key protection.
    
    Returns:
        Path to the generated .ovpn file.
    
    Raises:
        Exception: If OpenVPN is not available or creation fails.
    """
    manager = get_openvpn_manager()
    if not manager:
        raise Exception("OpenVPN is not installed or configured on this system.")
    
    try:
        from .openvpn_manager import ClientExistsError, EasyRSAError
        
        ovpn_path = manager.create_client(account, password)
        logger.info(f"Created OpenVPN config for '{account}' at {ovpn_path}")
        return ovpn_path
    except ClientExistsError:
        logger.warning(f"Client '{account}' already exists")
        raise
    except EasyRSAError as e:
        logger.error(f"Failed to create client '{account}': {e}")
        raise Exception(f"Failed to create OpenVPN config: {e}")
    except Exception as e:
        logger.error(f"Unexpected error creating client '{account}': {e}")
        raise


def disable_openvpn_user(account: str) -> Dict[str, str]:
    """
    Disable an OpenVPN user by creating a CCD file.
    
    Args:
        account: The account/client name to disable.
    
    Returns:
        Dictionary with status message.
    """
    manager = get_openvpn_manager()
    if manager:
        try:
            manager.disable_client(account)
            logger.info(f"Disabled OpenVPN user '{account}'")
            return {"message": f"User '{account}' disabled successfully."}
        except Exception as e:
            logger.error(f"Failed to disable user '{account}': {e}")
    
    # Fallback to direct file creation
    return _disable_user_fallback(account)


def _disable_user_fallback(account: str) -> Dict[str, str]:
    """Fallback method to disable user directly via file system."""
    file_path = os.path.join(CCD_PATH, account)
    
    try:
        os.makedirs(CCD_PATH, exist_ok=True)
        with open(file_path, "w") as file:
            file.write("disable\n")
        return {"message": f"CCD file for '{account}' created successfully."}
    except Exception as e:
        logger.error(f"Fallback disable failed for '{account}': {e}")
        return {"message": f"Failed to disable user (no write access to CCD): {e}"}


def enable_openvpn_user(account: str) -> Dict[str, str]:
    """
    Enable an OpenVPN user by removing the CCD file.
    
    Args:
        account: The account/client name to enable.
    
    Returns:
        Dictionary with status message.
    """
    manager = get_openvpn_manager()
    if manager:
        try:
            manager.enable_client(account)
            logger.info(f"Enabled OpenVPN user '{account}'")
            return {"message": f"User '{account}' enabled successfully."}
        except Exception as e:
            logger.error(f"Failed to enable user '{account}': {e}")
    
    # Fallback to direct file removal
    return _enable_user_fallback(account)


def _enable_user_fallback(account: str) -> Dict[str, str]:
    """Fallback method to enable user directly via file system."""
    file_path = os.path.join(CCD_PATH, account)
    
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            return {"message": f"CCD file for '{account}' removed successfully."}
        except Exception as e:
            logger.error(f"Fallback enable failed for '{account}': {e}")
            return {"message": f"Failed to enable user: {e}"}
    else:
        return {"message": f"CCD file for '{account}' does not exist."}


def delete_openvpn_user(account: str) -> Dict[str, str]:
    """
    Revoke and delete an OpenVPN user.
    
    Args:
        account: The account/client name to delete.
    
    Returns:
        Dictionary with status message.
    """
    manager = get_openvpn_manager()
    if not manager:
        logger.warning(f"OpenVPN not available, skipping revocation for '{account}'")
        return {"message": f"OpenVPN not available, user '{account}' not revoked."}
    
    try:
        from .openvpn_manager import ClientNotFoundError
        
        manager.revoke_client(account)
        logger.info(f"Revoked OpenVPN user '{account}'")
        return {"message": f"User '{account}' revoked successfully."}
    except ClientNotFoundError:
        logger.warning(f"Client '{account}' not found for deletion")
        return {"message": f"User '{account}' not found."}
    except Exception as e:
        logger.error(f"Failed to revoke user '{account}': {e}")
        return {"message": f"Failed to delete OpenVPN user: {e}"}


def renew_openvpn_user(account: str, cert_days: Optional[int] = None) -> str:
    """
    Renew an OpenVPN user's certificate.
    
    This function follows the new renewal process:
    - Backs up the old certificate
    - Renews the certificate (with optional custom duration)
    - Revokes the old certificate using revoke-renewed
    - Regenerates the CRL
    - Regenerates the .ovpn configuration file
    
    Args:
        account: The account/client name to renew.
        cert_days: Optional number of days the certificate should be valid for.
                  If None, uses the default EasyRSA certificate validity.
    
    Returns:
        Path to the new .ovpn file.
    
    Raises:
        Exception: If OpenVPN is not available, client not found, or renewal fails.
    """
    manager = get_openvpn_manager()
    if not manager:
        raise Exception("OpenVPN is not installed or configured on this system.")
    
    try:
        from .openvpn_manager import ClientNotFoundError
        
        ovpn_path = manager.renew_client(account, cert_days=cert_days)
        logger.info(f"Renewed certificate for '{account}'")
        return ovpn_path
    except ClientNotFoundError:
        logger.warning(f"Client '{account}' not found for renewal")
        raise Exception(f"User '{account}' not found.")
    except Exception as e:
        logger.error(f"Failed to renew user '{account}': {e}")
        raise Exception(f"Failed to renew certificate: {e}")


def _client_config_path(account_number: str) -> str:
    """Return the on-disk path for an account's .ovpn file."""
    return os.path.join(CONFIG_DIR, f"{account_number}.ovpn")


def _config_not_found_response(request, account_number: str) -> HttpResponse:
    message = (
        f'Configuration file not found for account "{account_number}". '
        'The .ovpn file may not have been generated yet.'
    )
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': False, 'error': message}, status=404)
    return HttpResponse("Configuration file not found", status=404)


def _load_client_config_content(account_number: str) -> Optional[str]:
    """
    Read an account's .ovpn file and rewrite the remote line from dashboard settings.
    Returns None if the file does not exist.
    """
    from openvpn_dashboard.models import Setting
    import re

    config_path = _client_config_path(account_number)
    if not os.path.exists(config_path):
        return None

    with open(config_path, 'r') as file:
        config_content = file.read()

    server_url = Setting.get_value('server_url', '').strip()
    server_port = Setting.get_value('server_port', '').strip()

    if server_url or server_port:
        remote_pattern = r'^remote\s+(\S+)\s+(\d+)(.*)$'

        def replace_remote(match):
            original_address = match.group(1)
            original_port = match.group(2)
            rest = match.group(3)
            new_address = server_url if server_url else original_address
            new_port = server_port if server_port else original_port
            return f'remote {new_address} {new_port}{rest}'

        config_content = re.sub(remote_pattern, replace_remote, config_content, flags=re.MULTILINE)

    return config_content


def get_openvpn_config(request, account_number: str) -> HttpResponse:
    """
    Download the OpenVPN configuration file for an account.

    The config is modified on-the-fly to replace the server address and port
    with the values from settings (server_url and server_port).

    Pass ?import=1 to serve the profile inline with the OpenVPN Connect MIME type
    so a phone can open the scanned URL directly in the VPN app.
    """
    config_content = _load_client_config_content(account_number)
    if config_content is None:
        return _config_not_found_response(request, account_number)

    config_filename = f"{account_number}.ovpn"
    as_profile = request.GET.get('import') == '1'
    if as_profile:
        response = HttpResponse(
            config_content.encode('utf-8'),
            content_type='application/x-openvpn-profile',
        )
        response['Content-Disposition'] = f'inline; filename="{config_filename}"'
        return response

    response = HttpResponse(
        config_content.encode('utf-8'),
        content_type='application/octet-stream',
    )
    response['Content-Disposition'] = f'attachment; filename="{config_filename}"'
    return response


@login_required
def get_openvpn_config_qr(request, account_number: str) -> HttpResponse:
    """
    Return an SVG QR code that encodes the mobile import URL for this account.

    The .ovpn itself is too large to embed in a QR code (~5KB with certificates),
    so the code points at the dashboard download URL instead.
    """
    import io
    from django.urls import reverse
    import segno

    if not os.path.exists(_client_config_path(account_number)):
        return _config_not_found_response(request, account_number)

    profile_url = request.build_absolute_uri(
        reverse('download_file', args=[account_number])
    )
    if not profile_url.endswith('/'):
        profile_url += '/'
    profile_url += '?import=1'

    qr = segno.make(profile_url, error='m')
    buffer = io.BytesIO()
    qr.save(buffer, kind='svg', scale=8, border=2, dark='#0f172a', light='#ffffff')
    return HttpResponse(buffer.getvalue(), content_type='image/svg+xml')


def list_openvpn_clients() -> List:
    """
    List all OpenVPN clients.
    
    Returns:
        List of ClientInfo objects or empty list if unavailable.
    """
    manager = get_openvpn_manager()
    if not manager:
        return []
    
    try:
        return manager.list_clients()
    except Exception as e:
        logger.error(f"Failed to list clients: {e}")
        return []


class MockConnectedClient:
    """Mock connected client for when OpenVPN is not available."""
    def __init__(self):
        self.common_name = ""
        self.real_address = ""
        self.bytes_sent = 0
        self.bytes_received = 0
        self.bytes_sent_human = "0 B"
        self.bytes_received_human = "0 B"


def get_connected_clients() -> List:
    """
    Get currently connected OpenVPN clients.
    
    Uses the shared status-log parser (openvpn-status for v1, then a
    v2 CLIENT_LIST / v1 fallback) so the account-list green dot can light.
    
    Returns:
        List of ConnectedClient objects or empty list if unavailable.
    """
    from datetime import datetime

    if os.path.exists(STATUS_LOG):
        try:
            from .status_log import parse_status_log_file
            from .openvpn_manager import ConnectedClient
            
            clients = []
            for item in parse_status_log_file(STATUS_LOG):
                common_name = item.get('common_name') or item.get('name') or ''
                if not common_name:
                    continue
                clients.append(ConnectedClient(
                    common_name=common_name,
                    real_address=item.get('real_address') or '',
                    bytes_received=int(item.get('bytes_received') or 0),
                    bytes_sent=int(item.get('bytes_sent') or 0),
                    connected_since=item.get('connected_since') or datetime.now(),
                    virtual_address=item.get('virtual_address'),
                ))
            return clients
        except ImportError:
            logger.debug("status log parser not available")
        except Exception as e:
            logger.debug(f"Failed to parse status log: {e}")
    
    # Return empty list if status log doesn't exist or parsing fails
    return []


def get_client_traffic_data() -> Dict[str, Dict[str, int]]:
    """
    Get traffic data for connected clients.
    
    Returns:
        Dictionary mapping client names to their traffic data.
    """
    clients = get_connected_clients()
    traffic_data = {}
    
    for client in clients:
        traffic_data[client.common_name] = {
            'bytes_sent': client.bytes_sent,
            'bytes_received': client.bytes_received,
            'bytes_sent_human': client.bytes_sent_human,
            'bytes_received_human': client.bytes_received_human,
        }
    
    return traffic_data


def get_user_data_for_template() -> Dict[str, str]:
    """
    Get user traffic data formatted for the account_list template.
    
    This replaces the old .prom file parsing with live status data.
    
    Returns:
        Dictionary with keys like 'username_upload', 'username_download'.
    """
    user_data = {}
    
    try:
        clients = get_connected_clients()
        
        for client in clients:
            # Format: account_number_upload, account_number_download
            user_data[f"{client.common_name}_upload"] = str(client.bytes_sent)
            user_data[f"{client.common_name}_download"] = str(client.bytes_received)
    except Exception as e:
        logger.debug(f"Failed to get user data for template: {e}")
    
    return user_data


def is_client_connected(account: str) -> bool:
    """
    Check if a client is currently connected.
    
    Args:
        account: The account/client name to check.
    
    Returns:
        True if connected, False otherwise.
    """
    clients = get_connected_clients()
    return any(c.common_name == account for c in clients)


def get_server_status() -> Dict:
    """
    Get OpenVPN server status summary.
    
    Returns:
        Dictionary with server status information.
    """
    connected = get_connected_clients()
    
    return {
        "connected_count": len(connected),
        "connected_clients": [c.common_name for c in connected],
        "total_bytes_received": sum(c.bytes_received for c in connected),
        "total_bytes_sent": sum(c.bytes_sent for c in connected),
        "openvpn_available": is_openvpn_available(),
    }


def replace_content_in_file(file_path: str, old_content: str, new_content: str) -> None:
    """
    Replace content in a file (utility function).
    
    Args:
        file_path: Path to the file.
        old_content: Content to find (line prefix).
        new_content: New content to replace with.
    """
    try:
        with open(file_path, 'r') as file:
            lines = file.readlines()
        
        for i in range(len(lines)):
            if lines[i].startswith(old_content):
                lines[i] = new_content + "\n"
                break
        
        with open(file_path, 'w') as file:
            file.writelines(lines)
            
    except FileNotFoundError:
        raise Exception(f"File '{file_path}' not found.")
    except Exception as e:
        raise Exception(f"Failed to replace content in file: {str(e)}")
