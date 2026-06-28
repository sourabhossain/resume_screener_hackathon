"""
SSRF mitigation for outbound HTTP requests (e.g. resume link verification).
Blocks non-public schemes/hosts and resolves hostnames to reject private/link-local IPs.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_METADATA_AND_LOCAL_HOSTS = frozenset({
    'localhost',
    'metadata.google.internal',
    'metadata',
    'metadata.azure.com',
    '169.254.169.254',
})

# Hostnames that parsers often derive from bullets like "Node.js → https://node.js".
_GARBAGE_EXTRACTED_HOSTS = frozenset({
    'node.js',
    'react.js',
    'express.js',
    'nest.js',
    'vue.js',
    'angular.js',
    'svelte.js',
    'ember.js',
    'next.js',
    'nuxt.js',
    'jquery.js',
    'typescript.js',
})


_NAT64_PREFIX = ipaddress.ip_network('64:ff9b::/96')


def _effective_ip(ip):
    """Unwrap IPv6 forms that embed an IPv4 so we judge the REAL destination.

    Docker/IPv6 networks often resolve public hosts via NAT64 (64:ff9b::/96) or
    IPv4-mapped (::ffff:0:0/96) addresses. The wrapper IPv6 looks "reserved" to
    ipaddress and was wrongly blocking legitimate public hosts (e.g. github.com).
    We extract the embedded IPv4 and judge that — so 64:ff9b::<public-v4> is
    allowed while 64:ff9b::<private-v4> is still blocked.
    """
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            return ip.ipv4_mapped
        if ip in _NAT64_PREFIX:
            return ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
    return ip


def _blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    ip = _effective_ip(ip)
    if ip == ipaddress.ip_address('169.254.169.254'):
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolved_ips(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    out: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        addr = info[4][0]
        out.append(ipaddress.ip_address(addr))
    return out


def is_safe_public_http_url(url: str, *, resolve_dns: bool = True) -> tuple[bool, str]:
    """
    Return (allowed, reason_if_blocked).
    When resolve_dns is True (default), hostnames are resolved and private/link-local
    addresses are rejected — used before outbound HTTP.
    When False, only scheme/literal-IP/hostname blocklist checks run — used when
    extracting links from text so DNS outages do not drop obvious public URLs.
    """
    if not url or not isinstance(url, str):
        return False, 'empty or invalid url'

    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False, 'parse error'

    if parsed.scheme not in ('http', 'https'):
        return False, 'only http/https allowed'

    host = parsed.hostname
    if not host:
        return False, 'missing host'

    hl = host.lower().strip('.')
    if hl in _METADATA_AND_LOCAL_HOSTS:
        return False, 'blocked hostname'

    if hl in _GARBAGE_EXTRACTED_HOSTS:
        return False, 'not a crawlable URL (resume extraction artifact)'

    try:
        ip = ipaddress.ip_address(host)
        if _blocked_ip(ip):
            return False, 'blocked ip literal'
        return True, ''
    except ValueError:
        pass

    if not resolve_dns:
        return True, ''

    try:
        ips = _resolved_ips(host)
    except socket.gaierror as e:
        logger.debug('DNS resolution failed for %s: %s', host, e)
        return False, 'dns resolution failed'

    if not ips:
        return False, 'no resolved addresses'

    for ip in ips:
        if _blocked_ip(ip):
            return False, 'blocked resolved ip'

    return True, ''


def validate_and_pin(url: str) -> tuple[bool, str, str | None, str | None, int | None]:
    """
    Validate a URL for outbound fetching AND return a single resolved IP to pin.

    Returns (allowed, reason, pinned_ip, host, port).

    The crawler must connect to the EXACT IP validated here. If it instead let
    httpx resolve the hostname again at connect time, an attacker controlling DNS
    could answer the guard's lookup with a public IP and the connection's lookup
    with 127.0.0.1 / 169.254.169.254 / 10.x (DNS rebinding / TOCTOU), bypassing
    the whole SSRF check. Resolving once and pinning closes that window.
    """
    ok, reason = is_safe_public_http_url(url, resolve_dns=False)
    if not ok:
        return False, reason, None, None, None

    parsed = urlparse(url.strip())
    host = parsed.hostname
    scheme = parsed.scheme
    port = parsed.port or (443 if scheme == 'https' else 80)

    # Literal IP host: already validated by is_safe_public_http_url above.
    try:
        ipaddress.ip_address(host)
        return True, '', host, host, port
    except ValueError:
        pass

    try:
        ips = _resolved_ips(host)
    except socket.gaierror as e:
        logger.debug('DNS resolution failed for %s: %s', host, e)
        return False, 'dns resolution failed', None, None, None

    if not ips:
        return False, 'no resolved addresses', None, None, None

    safe_ip = None
    for ip in ips:
        if _blocked_ip(ip):
            return False, 'blocked resolved ip', None, None, None
        if safe_ip is None:
            safe_ip = ip

    return True, '', str(safe_ip), host, port
