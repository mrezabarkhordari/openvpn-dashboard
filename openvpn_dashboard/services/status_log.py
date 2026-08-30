"""
Parse OpenVPN status.log for version 1 and version 2.

The openvpn-status library only understands version 1
(``OpenVPN CLIENT LIST``). This stack writes version 2
(``TITLE,OpenVPN…`` / ``CLIENT_LIST,cn,…``).

``parse_status_log`` tries the library first, then falls back to a
manual parser that handles both formats. Returns a list of client dicts
with: common_name, name, real_address, virtual_address, bytes_received,
bytes_sent, connected_since.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_logged_library_fallback = False


def parse_status_log(content: str) -> List[Dict]:
    """
    Parse OpenVPN status log content (v1 or v2).

    Tries openvpn-status first; on failure uses the manual v1/v2 parser.
    """
    if not content or not str(content).strip():
        return []

    library_clients = _parse_with_library(content)
    if library_clients is not None:
        return library_clients

    return parse_status_log_manual(content)


def parse_status_log_file(path: str) -> List[Dict]:
    """Read ``path`` and parse it with :func:`parse_status_log`."""
    try:
        with open(path, 'r') as handle:
            return parse_status_log(handle.read())
    except FileNotFoundError:
        return []
    except OSError as exc:
        logger.error("Failed to read status log %s: %s", path, exc)
        return []


def parse_status_log_manual(content: str) -> List[Dict]:
    """Parse v2 ``CLIENT_LIST`` lines and legacy v1 client-list sections."""
    clients: List[Dict] = []
    virtual_by_cn: Dict[str, str] = {}
    lines = str(content).replace('\r\n', '\n').split('\n')

    in_v1_client_list = False
    in_v1_routing = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        if line.startswith('CLIENT_LIST,'):
            client = _parse_v2_client_list_line(line)
            if client:
                clients.append(client)
            continue

        if line.startswith('ROUTING_TABLE,'):
            parts = line.split(',')
            # ROUTING_TABLE,Virtual Address,Common Name,Real Address,...
            if len(parts) >= 3:
                vaddr, common_name = parts[1].strip(), parts[2].strip()
                if common_name and vaddr and vaddr != 'Virtual Address':
                    virtual_by_cn[common_name] = vaddr
            continue

        if line.startswith(('TITLE,', 'TIME,', 'HEADER,', 'GLOBAL_STATS,')) or line == 'END':
            continue

        if line.startswith('OpenVPN CLIENT LIST'):
            in_v1_client_list = True
            in_v1_routing = False
            continue
        if line.startswith('ROUTING TABLE'):
            in_v1_client_list = False
            in_v1_routing = True
            continue
        if line.startswith('GLOBAL STATS'):
            in_v1_client_list = False
            in_v1_routing = False
            continue
        if line.startswith(('Updated,', 'Common Name,', 'Virtual Address,')):
            continue

        if in_v1_client_list and ',' in line:
            client = _parse_v1_client_line(line)
            if client:
                clients.append(client)
            continue

        if in_v1_routing and ',' in line:
            parts = line.split(',')
            if len(parts) >= 2:
                vaddr, common_name = parts[0].strip(), parts[1].strip()
                if common_name and vaddr and common_name != 'Common Name':
                    virtual_by_cn[common_name] = vaddr

    for client in clients:
        if not client.get('virtual_address'):
            vaddr = virtual_by_cn.get(client['common_name'])
            if vaddr:
                client['virtual_address'] = vaddr

    return clients


def _parse_with_library(content: str) -> Optional[List[Dict]]:
    """Return client dicts from openvpn-status, or None if it cannot parse."""
    global _logged_library_fallback

    try:
        from openvpn_status import parse_status
    except ImportError:
        return None

    try:
        status = parse_status(content)
    except Exception as exc:
        if not _logged_library_fallback:
            logger.info(
                "Library parsing failed (%s); using v1/v2 fallback parser",
                exc,
            )
            _logged_library_fallback = True
        else:
            logger.debug("Library parsing failed: %s", exc)
        return None

    virtual_addresses: Dict[str, str] = {}
    routing_table = getattr(status, 'routing_table', None) or {}
    for vaddr, route in routing_table.items():
        virtual_addresses[getattr(route, 'common_name', '')] = str(vaddr)

    clients = []
    for real_addr, client in (getattr(status, 'client_list', None) or {}).items():
        common_name = getattr(client, 'common_name', '') or ''
        if not _usable_common_name(common_name):
            continue
        clients.append(_client_dict(
            common_name=common_name,
            real_address=str(real_addr),
            virtual_address=virtual_addresses.get(common_name),
            bytes_received=_safe_int(getattr(client, 'bytes_received', 0)),
            bytes_sent=_safe_int(getattr(client, 'bytes_sent', 0)),
            connected_since=getattr(client, 'connected_since', None),
        ))
    return clients


def _parse_v2_client_list_line(line: str) -> Optional[Dict]:
    """
    Parse a version-2 CLIENT_LIST row.

    OpenVPN 2.4+:
      CLIENT_LIST,CN,Real,Virtual,Virtual IPv6,Bytes Recv,Bytes Sent,Since,time_t,...

    OpenVPN 2.3 status-version 2:
      CLIENT_LIST,CN,Real,Virtual,Bytes Recv,Bytes Sent,Since,time_t
    """
    parts = line.split(',')
    if len(parts) < 7:
        return None

    common_name = parts[1].strip()
    if not _usable_common_name(common_name):
        return None

    # 2.4+ inserts Virtual IPv6 before the byte counters.
    if len(parts) >= 8 and _is_int_token(parts[5]) and not _is_int_token(parts[4]):
        virtual_address = parts[3].strip() or None
        bytes_received = _safe_int(parts[5])
        bytes_sent = _safe_int(parts[6])
        since_str = parts[7]
        time_t = parts[8] if len(parts) > 8 else None
    elif _is_int_token(parts[4]):
        virtual_address = parts[3].strip() or None
        bytes_received = _safe_int(parts[4])
        bytes_sent = _safe_int(parts[5])
        since_str = parts[6] if len(parts) > 6 else ''
        time_t = parts[7] if len(parts) > 7 else None
    else:
        return None

    return _client_dict(
        common_name=common_name,
        real_address=parts[2].strip(),
        virtual_address=virtual_address,
        bytes_received=bytes_received,
        bytes_sent=bytes_sent,
        connected_since=_parse_connected_since(since_str, time_t),
    )


def _parse_v1_client_line(line: str) -> Optional[Dict]:
    """Parse a version-1 client row: cn,real,bytes_recv,bytes_sent,connected_since."""
    parts = line.split(',')
    if len(parts) < 5:
        return None

    common_name = parts[0].strip()
    if not _usable_common_name(common_name):
        return None

    return _client_dict(
        common_name=common_name,
        real_address=parts[1].strip(),
        virtual_address=None,
        bytes_received=_safe_int(parts[2]),
        bytes_sent=_safe_int(parts[3]),
        connected_since=_parse_connected_since(parts[4], None),
    )


def _client_dict(
    common_name: str,
    real_address: str,
    virtual_address: Optional[str],
    bytes_received: int,
    bytes_sent: int,
    connected_since,
) -> Dict:
    return {
        'common_name': common_name,
        'name': common_name,
        'real_address': real_address or '',
        'virtual_address': virtual_address or None,
        'bytes_received': bytes_received,
        'bytes_sent': bytes_sent,
        'connected_since': connected_since,
    }


def _usable_common_name(common_name: str) -> bool:
    return bool(common_name) and common_name not in ('UNDEF', 'Common Name')


def _is_int_token(value: str) -> bool:
    try:
        int(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def _safe_int(value) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _parse_connected_since(since_str: Optional[str], time_t: Optional[str]):
    if since_str:
        token = since_str.strip()
        for fmt in ("%a %b %d %H:%M:%S %Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(token, fmt)
            except ValueError:
                pass

    if time_t:
        try:
            return datetime.fromtimestamp(int(float(str(time_t).strip())))
        except (TypeError, ValueError, OSError, OverflowError):
            pass

    return datetime.now()
