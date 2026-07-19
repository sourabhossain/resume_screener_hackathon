"""
Link Crawler — fetches and extracts content from CV links.
Uses httpx for simple pages, Playwright for JS-heavy pages.
"""
import asyncio
import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import httpcore
import httpx

from apps.core.services.url_safety import (
    UnsafeHostError,
    is_safe_public_http_url,
    pinned_ip_for_host,
)

logger = logging.getLogger(__name__)


class _SSRFValidatingBackend(httpcore.AnyIOBackend):
    """Connects to the validated resolved IP, not the hostname — closes DNS-rebinding; TLS still verifies the name."""

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        ip = pinned_ip_for_host(host)
        return await super().connect_tcp(
            ip, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )


def _pinned_async_client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(verify=True)
    transport._pool._network_backend = _SSRFValidatingBackend()
    return httpx.AsyncClient(
        transport=transport,
        headers=LinkCrawler.HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=False,
    )

# Timeout for all requests
REQUEST_TIMEOUT = 15  # seconds
MAX_CONTENT_LENGTH = 50_000  # chars
MAX_REDIRECTS = 5


@dataclass
class CrawlResult:
    url: str
    success: bool
    content: str = ""
    title: str = ""
    status_code: int = 0
    error: str = ""


class LinkCrawler:

    HEADERS = {
        'User-Agent': (
            'Mozilla/5.0 (compatible; ResumeVerifier/1.0; '
            '+https://your-domain.com/bot)'
        )
    }

    # Sites that need JS rendering
    JS_REQUIRED_DOMAINS = {'github.com', 'linkedin.com'}

    @classmethod
    async def crawl(cls, url: str) -> CrawlResult:
        """Crawl a single URL and return content."""
        try:
            safe, reason = is_safe_public_http_url(url)
            if not safe:
                if 'resume extraction artifact' in reason:
                    logger.debug('Skipped crawl (bogus URL): %s — %s', url, reason)
                else:
                    logger.info('Blocked crawl (SSRF guard): %s — %s', url, reason)
                return CrawlResult(url=url, success=False, error=f'blocked: {reason}')

            domain = cls._get_domain(url)
            if domain in cls.JS_REQUIRED_DOMAINS:
                return await cls._crawl_with_playwright(url)
            else:
                return await cls._crawl_with_httpx(url)
        except Exception as e:
            logger.warning(f"Crawl failed for {url}: {e}")
            return CrawlResult(url=url, success=False, error=str(e))

    @classmethod
    async def crawl_many(cls, urls: list[str]) -> list[CrawlResult]:
        results = []
        batches = [urls[i:i+3] for i in range(0, len(urls), 3)]
        for idx, batch in enumerate(batches):
            batch_results = await asyncio.gather(
                *[cls.crawl(url) for url in batch],
                return_exceptions=True
            )
            for url, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results.append(CrawlResult(url=url, success=False, error=str(result)))
                else:
                    results.append(result)
            # Polite delay between batches to avoid hammering servers
            if idx < len(batches) - 1:
                await asyncio.sleep(2)
        return results

    @classmethod
    async def _crawl_with_httpx(cls, url: str) -> CrawlResult:
        # Follow redirects manually and re-check each hop (auto-follow could reach an internal host).
        async with _pinned_async_client() as client:
            current = url
            for _ in range(MAX_REDIRECTS + 1):
                safe, reason = is_safe_public_http_url(current)
                if not safe:
                    logger.info('Blocked crawl hop (SSRF guard): %s — %s', current, reason)
                    return CrawlResult(url=url, success=False, error=f'blocked: {reason}')

                try:
                    response = await client.get(current)
                except UnsafeHostError as e:
                    logger.info('Blocked crawl hop (SSRF pin): %s — %s', current, e)
                    return CrawlResult(url=url, success=False, error=f'blocked: {e}')

                if response.is_redirect and response.headers.get('location'):
                    nxt = response.next_request
                    current = str(nxt.url) if nxt is not None else urljoin(current, response.headers['location'])
                    continue

                content = response.text[:MAX_CONTENT_LENGTH]
                title = cls._extract_title(content)
                return CrawlResult(
                    url=url,
                    success=response.status_code < 400,
                    content=content,
                    title=title,
                    status_code=response.status_code
                )

            return CrawlResult(url=url, success=False, error='too many redirects')

    @classmethod
    async def _crawl_with_playwright(cls, url: str) -> CrawlResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed — falling back to httpx")
            return await cls._crawl_with_httpx(url)

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(
                        user_agent=cls.HEADERS['User-Agent']
                    )

                    # SSRF-check every request, not just navigations.
                    async def _ssrf_guard(route, request):
                        safe, reason = is_safe_public_http_url(request.url)
                        if not safe:
                            logger.info(
                                'Blocked Playwright request (SSRF guard): %s — %s',
                                request.url, reason,
                            )
                            await route.abort('blockedbyclient')
                            return
                        await route.continue_()

                    await page.route('**/*', _ssrf_guard)

                    await page.goto(url, timeout=REQUEST_TIMEOUT * 1000)
                    await page.wait_for_load_state('networkidle', timeout=10000)
                    content = await page.content()
                    title = await page.title()
                    return CrawlResult(
                        url=url,
                        success=True,
                        content=content[:MAX_CONTENT_LENGTH],
                        title=title,
                        status_code=200
                    )
                finally:
                    await browser.close()
        except Exception as e:
            err = str(e)
            if 'Executable doesn' in err or 'BrowserType.launch' in err:
                logger.warning(
                    'Playwright Chromium missing in this environment (install with '
                    '`python -m playwright install chromium --with-deps`). '
                    'Falling back to httpx for %s',
                    url,
                )
            else:
                logger.warning('Playwright failed for %s: %s', url, e)
            return await cls._crawl_with_httpx(url)

    @staticmethod
    def _get_domain(url: str) -> str:
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.replace('www.', '')
        except Exception:
            return ''

    @staticmethod
    def _extract_title(html: str) -> str:
        import re
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        return match.group(1).strip()[:200] if match else ''
