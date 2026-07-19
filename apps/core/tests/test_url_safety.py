"""Tests for SSRF guard used by link crawling."""
import ipaddress

import pytest

from apps.core.services.url_safety import (
    UnsafeHostError,
    is_safe_public_http_url,
    pinned_ip_for_host,
)


def test_blocks_loopback_literal():
    ok, _ = is_safe_public_http_url('http://127.0.0.1/')
    assert ok is False


def test_blocks_private_literal():
    ok, _ = is_safe_public_http_url('https://192.168.0.5/')
    assert ok is False


def test_blocks_metadata_ip_literal():
    ok, _ = is_safe_public_http_url('http://169.254.169.254/latest/meta-data/')
    assert ok is False


def test_blocks_non_http_scheme():
    ok, _ = is_safe_public_http_url('file:///etc/passwd')
    assert ok is False


def test_public_ip_literal_allowed():
    ok, reason = is_safe_public_http_url('https://8.8.8.8/')
    assert ok is True, reason


def test_blocks_placeholder_framework_hostname():
    ok, reason = is_safe_public_http_url('https://node.js/')
    assert ok is False
    assert 'artifact' in reason or 'resume' in reason


def test_hostname_allowed_when_resolve_public(monkeypatch):
    import apps.core.services.url_safety as us

    def fake_ips(hostname):
        return [ipaddress.ip_address('8.8.8.8')]

    monkeypatch.setattr(us, '_resolved_ips', fake_ips)
    ok, _ = is_safe_public_http_url('https://resolve-me.example/')
    assert ok is True


def test_hostname_blocked_when_resolve_private(monkeypatch):
    import apps.core.services.url_safety as us

    def fake_ips(hostname):
        return [ipaddress.ip_address('10.0.0.5')]

    monkeypatch.setattr(us, '_resolved_ips', fake_ips)
    ok, _ = is_safe_public_http_url('https://evil.example/')
    assert ok is False


def test_nat64_wrapped_public_ipv4_allowed(monkeypatch):
    """Docker/NAT64 resolves public hosts to 64:ff9b::<public-v4>; that must be
    allowed (judge the embedded IPv4), not treated as reserved and blocked."""
    import apps.core.services.url_safety as us

    def fake_ips(hostname):
        # github-style: a public IPv4 plus its NAT64-wrapped form
        return [ipaddress.ip_address('20.205.243.166'),
                ipaddress.ip_address('64:ff9b::14cd:f3a6')]

    monkeypatch.setattr(us, '_resolved_ips', fake_ips)
    ok, reason = is_safe_public_http_url('https://github.com/torvalds')
    assert ok is True, reason


def test_nat64_wrapped_private_ipv4_blocked(monkeypatch):
    """64:ff9b::<private-v4> must still be blocked (no SSRF bypass via NAT64)."""
    import apps.core.services.url_safety as us

    def fake_ips(hostname):
        return [ipaddress.ip_address('64:ff9b::0a00:0001')]  # embeds 10.0.0.1

    monkeypatch.setattr(us, '_resolved_ips', fake_ips)
    ok, _ = is_safe_public_http_url('https://sneaky.example/')
    assert ok is False


def test_ipv4_mapped_loopback_blocked(monkeypatch):
    import apps.core.services.url_safety as us
    monkeypatch.setattr(us, '_resolved_ips', lambda h: [ipaddress.ip_address('::ffff:127.0.0.1')])
    ok, _ = is_safe_public_http_url('https://mapped.example/')
    assert ok is False


# --- pinned_ip_for_host: DNS-rebinding backstop (validate the exact connect IP) ---

def test_pin_blocks_metadata_hostname():
    with pytest.raises(UnsafeHostError):
        pinned_ip_for_host('169.254.169.254')


def test_pin_blocks_localhost_hostname():
    with pytest.raises(UnsafeHostError):
        pinned_ip_for_host('localhost')


def test_pin_blocks_private_literal():
    with pytest.raises(UnsafeHostError):
        pinned_ip_for_host('10.0.0.1')


def test_pin_returns_validated_public_ip(monkeypatch):
    import apps.core.services.url_safety as us
    monkeypatch.setattr(us, '_resolved_ips', lambda h: [ipaddress.ip_address('93.184.216.34')])
    assert pinned_ip_for_host('example.com') == '93.184.216.34'


def test_pin_rebinding_to_private_is_blocked(monkeypatch):
    """The rebinding case: a hostname whose (connect-time) resolution yields only
    private/metadata IPs must raise, so the pinned backend never opens the socket."""
    import apps.core.services.url_safety as us
    monkeypatch.setattr(us, '_resolved_ips', lambda h: [ipaddress.ip_address('169.254.169.254')])
    with pytest.raises(UnsafeHostError):
        pinned_ip_for_host('evil-rebind.example')


def test_pin_picks_public_when_mixed(monkeypatch):
    """If resolution returns a public and a private IP, connect only to the public one."""
    import apps.core.services.url_safety as us
    monkeypatch.setattr(us, '_resolved_ips',
                        lambda h: [ipaddress.ip_address('93.184.216.34'), ipaddress.ip_address('10.0.0.1')])
    assert pinned_ip_for_host('mixed.example') == '93.184.216.34'
