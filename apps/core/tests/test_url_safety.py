"""Tests for SSRF guard used by link crawling."""
import ipaddress


from apps.core.services.url_safety import is_safe_public_http_url


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
