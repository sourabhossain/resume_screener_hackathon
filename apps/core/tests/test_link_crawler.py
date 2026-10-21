"""Crawling a link from a CV without loading an unbounded body."""
import asyncio

import httpx

from apps.core.services import link_crawler

CHUNK = 64 * 1024


def test_a_huge_page_is_read_only_up_to_the_byte_cap(monkeypatch):
    produced = []

    async def endless_body():
        while True:
            produced.append(CHUNK)
            yield b'<html><title>Big</title>' + b'x' * CHUNK

    def handler(request):
        return httpx.Response(200, headers={'content-type': 'text/html'}, content=endless_body())

    monkeypatch.setattr(link_crawler, 'is_safe_public_http_url', lambda url: (True, ''))
    monkeypatch.setattr(link_crawler, '_pinned_async_client', lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False))

    result = asyncio.run(link_crawler.LinkCrawler._crawl_with_httpx('https://example.com/cv'))

    assert result.success and result.title == 'Big'
    assert len(result.content) == link_crawler.MAX_CONTENT_LENGTH
    assert sum(produced) <= link_crawler.MAX_BODY_BYTES + 2 * CHUNK


def test_every_redirect_hop_is_checked_again(monkeypatch):
    def handler(request):
        if request.url.path == '/start':
            return httpx.Response(302, headers={'location': 'http://10.0.0.5/admin'})
        return httpx.Response(200, text='internal')

    monkeypatch.setattr(link_crawler, '_pinned_async_client', lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False))
    monkeypatch.setattr(link_crawler, 'is_safe_public_http_url',
                        lambda url: (not url.startswith('http://10.'), 'blocked ip literal'))

    result = asyncio.run(link_crawler.LinkCrawler._crawl_with_httpx('https://example.com/start'))

    assert not result.success
    assert result.error.startswith('blocked')
