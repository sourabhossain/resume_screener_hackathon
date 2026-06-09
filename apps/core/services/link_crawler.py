"""
Link Crawler — fetches and extracts content from CV links.
Uses httpx for simple pages, Playwright for JS-heavy pages.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import httpx

from apps.core.services.url_safety import is_safe_public_http_url

logger = logging.getLogger(__name__)

# Timeout for all requests
REQUEST_TIMEOUT = 15  # seconds
MAX_CONTENT_LENGTH = 50_000  # chars


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
        async with httpx.AsyncClient(
            headers=cls.HEADERS,
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            verify=True,
        ) as client:
            response = await client.get(url)
            content = response.text[:MAX_CONTENT_LENGTH]
            title = cls._extract_title(content)
            return CrawlResult(
                url=url,
                success=response.status_code < 400,
                content=content,
                title=title,
                status_code=response.status_code
            )

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
