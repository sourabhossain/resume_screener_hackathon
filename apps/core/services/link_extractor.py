"""
CV Link Extractor — finds and classifies URLs from resume text.
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import List

from apps.core.services.url_safety import is_safe_public_http_url


class LinkType(str, Enum):
    GITHUB = "github"
    LINKEDIN = "linkedin"
    PORTFOLIO = "portfolio"
    BEHANCE = "behance"
    DRIBBBLE = "dribbble"
    STACKOVERFLOW = "stackoverflow"
    SCHOLAR = "scholar"
    OTHER = "other"


@dataclass
class ExtractedLink:
    url: str
    link_type: LinkType
    raw_text: str  # surrounding text in CV for context


class LinkExtractor:
    # Regex to find URLs in text
    URL_PATTERN = re.compile(
        r'(?:https?://)?'
        r'(?:www\.)?'
        r'('
        r'github\.com/[^\s,)>\]"\']+|'
        r'linkedin\.com/in/[^\s,)>\]"\']+|'
        r'behance\.net/[^\s,)>\]"\']+|'
        r'dribbble\.com/[^\s,)>\]"\']+|'
        r'stackoverflow\.com/users/[^\s,)>\]"\']+|'
        r'scholar\.google\.com/[^\s,)>\]"\']+|'
        r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s,)>\]"\']*)?'
        r')',
        re.IGNORECASE
    )

    SKIP_DOMAINS = {
        'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com',
        'facebook.com', 'twitter.com', 'instagram.com',
        'example.com', 'test.com'
    }

    @classmethod
    def extract(cls, text: str) -> List[ExtractedLink]:
        """Extract and classify all URLs from CV text."""
        links = []
        seen_urls = set()

        for match in cls.URL_PATTERN.finditer(text):
            if cls._is_not_a_link(text, match):
                continue
            raw_url = match.group(0)
            url = cls._normalize_url(raw_url)

            if url in seen_urls:
                continue
            safe, _ = is_safe_public_http_url(url, resolve_dns=False)
            if not safe:
                continue
            if cls._should_skip(url):
                continue

            seen_urls.add(url)
            link_type = cls._classify(url)

            # Get surrounding context (50 chars before and after)
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 50)
            context = text[start:end].strip()

            links.append(ExtractedLink(
                url=url,
                link_type=link_type,
                raw_text=context
            ))

        return links[:10]  # max 10 links per CV

    # A bare "word.word" is often no link at all: either half of an email address
    # (asha.rahman@...), a degree (B.Sc, M.Com) or a file name. Crawling one fails
    # and drags the candidate's verification score to 0.
    FILE_SUFFIXES = {'pdf', 'doc', 'docx', 'txt', 'png', 'jpg', 'jpeg', 'js', 'py', 'html', 'csv', 'xlsx'}

    @classmethod
    def _is_not_a_link(cls, text: str, match) -> bool:
        if '@' in (text[match.start() - 1:match.start()], text[match.end():match.end() + 1]):
            return True
        raw = match.group(0)
        if re.match(r'(?:https?://|www\.)', raw, re.IGNORECASE) or '/' in raw:
            return False
        labels = raw.rstrip('.,)').split('.')
        return len(labels[0]) < 2 or labels[-1].lower() in cls.FILE_SUFFIXES

    @classmethod
    def _normalize_url(cls, url: str) -> str:
        url = url.strip('.,)')
        if not url.startswith('http'):
            url = 'https://' + url
        return url

    @classmethod
    def _should_skip(cls, url: str) -> bool:
        for domain in cls.SKIP_DOMAINS:
            if domain in url.lower():
                return True
        return False

    @classmethod
    def _classify(cls, url: str) -> LinkType:
        url_lower = url.lower()
        if 'github.com' in url_lower:
            return LinkType.GITHUB
        if 'linkedin.com' in url_lower:
            return LinkType.LINKEDIN
        if 'behance.net' in url_lower:
            return LinkType.BEHANCE
        if 'dribbble.com' in url_lower:
            return LinkType.DRIBBBLE
        if 'stackoverflow.com' in url_lower:
            return LinkType.STACKOVERFLOW
        if 'scholar.google.com' in url_lower:
            return LinkType.SCHOLAR
        return LinkType.PORTFOLIO
