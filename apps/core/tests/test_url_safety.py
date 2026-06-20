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
