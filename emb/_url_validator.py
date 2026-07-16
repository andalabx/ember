from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_blocked(addr_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(addr_str)
    except ValueError:
        return False
    # Unwrap IPv6-mapped IPv4.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    for network in _BLOCKED_NETWORKS:
        try:
            if addr in network:
                return True
        except TypeError:
            pass  # Ignore address family mismatch.
    return False


# DNS rebinding still needs network egress controls.
def validate_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Cannot resolve hostname {hostname!r}: {exc}") from exc

    for info in infos:
        addr_str = info[4][0]
        if _is_blocked(addr_str):
            raise ValueError(f"URL resolves to a blocked address ({addr_str})")
