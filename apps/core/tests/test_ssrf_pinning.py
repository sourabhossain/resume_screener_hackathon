"""Regression tests for SSRF DNS-pinning and the link crawler's pinned-connection,
redirect re-validation, streaming byte-cap, and batch-isolation behavior.

Pins the anti-DNS-rebinding guarantee: a URL is validated and resolved once, the
safe IP is pinned, and the crawler dials that exact IP while carrying the original
hostname only via the Host header + TLS SNI — never re-resolving at connect time.
Every redirect hop is re-validated before it is followed.
"""
import asyncio
import ipaddress

import httpx
import pytest

from apps.core.services import link_crawler, url_safety
from apps.core.services.link_crawler import (
    CrawlResult,
    LinkCrawler,
    MAX_CONTENT_BYTES,
    MAX_CONTENT_LENGTH,
)
from apps.core.services.url_safety import validate_and_pin


class _FakeStreamResponse:
    """Stand-in for an httpx streaming response (no network)."""

    def __init__(self, *, status_code=200, chunks=(), encoding='utf-8',
                 is_redirect=False, headers=None):
        self.status_code = status_code
        self.encoding = encoding
        self.is_redirect = is_redirect
        self.headers = headers or {}
        self._chunks = list(chunks)
        self.chunks_consumed = 0

    async def aiter_bytes(self):
        for chunk in self._chunks:
            self.chunks_consumed += 1
            yield chunk


class _FakeStreamCM:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc):
        return False


def _patch_stream(monkeypatch, response, capture):
    def fake_stream(self, method, url, *, headers=None, extensions=None, **kwargs):
        capture['calls'] = capture.get('calls', 0) + 1
        capture['method'] = method
        capture['url'] = url
        capture['headers'] = dict(headers or {})
        capture['extensions'] = dict(extensions or {})
        return _FakeStreamCM(response)

    monkeypatch.setattr(httpx.AsyncClient, 'stream', fake_stream)


@pytest.mark.parametrize('internal_ip', ['10.0.0.1', '169.254.169.254', '127.0.0.1', '::1'])
def test_validate_and_pin_blocks_internal_resolved_ip(monkeypatch, internal_ip):
    monkeypatch.setattr(url_safety, '_resolved_ips',
                        lambda host: [ipaddress.ip_address(internal_ip)])
    ok, reason, pinned, host, port = validate_and_pin('http://evil.example.com/x')
    assert ok is False
    assert reason == 'blocked resolved ip'
    assert (pinned, host, port) == (None, None, None)


def test_validate_and_pin_allows_public_and_returns_pinned_ip(monkeypatch):
    monkeypatch.setattr(url_safety, '_resolved_ips',
                        lambda host: [ipaddress.ip_address('93.184.216.34')])
    ok, reason, pinned, host, port = validate_and_pin('http://good.example.com/path')
    assert ok is True
    assert reason == ''
    assert pinned == '93.184.216.34'
    assert host == 'good.example.com'
    assert port == 80


def test_crawler_connects_to_pinned_ip_not_rebound_host(monkeypatch):
    monkeypatch.setattr(
        link_crawler, 'validate_and_pin',
        lambda url: (True, '', '93.184.216.34', 'good.example.com', 80),
    )
    capture = {}
    response = _FakeStreamResponse(
        status_code=200, chunks=[b'<html><title>ok</title></html>'],
    )
    _patch_stream(monkeypatch, response, capture)

    result = asyncio.run(LinkCrawler._crawl_with_httpx('http://good.example.com/x'))

    assert result.success is True
    assert capture['url'].host == '93.184.216.34'
    assert capture['headers'].get('Host') == 'good.example.com'
    assert capture['extensions'].get('sni_hostname') == 'good.example.com'


def test_crawler_blocks_redirect_to_internal_host(monkeypatch):
    def fake_validate(url):
        if 'internal' in url:
            return (False, 'blocked resolved ip', None, None, None)
        return (True, '', '93.184.216.34', 'good.example.com', 80)

    monkeypatch.setattr(link_crawler, 'validate_and_pin', fake_validate)

    capture = {}
    redirect = _FakeStreamResponse(
        status_code=301, is_redirect=True,
        headers={'location': 'http://internal.example.com/'},
        chunks=[b'SHOULD-NOT-BE-READ'],
    )
    _patch_stream(monkeypatch, redirect, capture)

    result = asyncio.run(LinkCrawler._crawl_with_httpx('http://good.example.com/'))

    assert result.success is False
    assert 'blocked' in result.error
    assert result.content == ''
    assert capture['calls'] == 1


def test_crawler_streaming_byte_cap_aborts_without_error(monkeypatch):
    monkeypatch.setattr(
        link_crawler, 'validate_and_pin',
        lambda url: (True, '', '93.184.216.34', 'good.example.com', 80),
    )
    chunk = b'a' * (MAX_CONTENT_BYTES // 2)
    response = _FakeStreamResponse(status_code=200, chunks=[chunk] * 5)
    _patch_stream(monkeypatch, response, {})

    result = asyncio.run(LinkCrawler._crawl_with_httpx('http://good.example.com/'))

    assert result.success is True
    assert len(result.content) <= MAX_CONTENT_LENGTH
    assert response.chunks_consumed < 5


def test_crawl_many_isolates_one_failing_link(monkeypatch):
    async def fake_crawl(url):
        if 'bad' in url:
            raise RuntimeError('boom')
        return CrawlResult(url=url, success=True, status_code=200)

    monkeypatch.setattr(LinkCrawler, 'crawl', staticmethod(fake_crawl))

    urls = [
        'http://good1.example.com',
        'http://bad.example.com',
        'http://good2.example.com',
    ]
    results = asyncio.run(LinkCrawler.crawl_many(urls))

    by_url = {r.url: r for r in results}
    assert len(results) == 3
    assert by_url['http://good1.example.com'].success is True
    assert by_url['http://good2.example.com'].success is True
    assert by_url['http://bad.example.com'].success is False
    assert by_url['http://bad.example.com'].error
