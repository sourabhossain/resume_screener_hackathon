import re
import markdown as md_lib
from django import template
from django.utils.safestring import mark_safe
from django.utils.html import escape

register = template.Library()

_HEADER_RE = re.compile(
    r'^([A-Z][A-Za-z &/\(\)]{2,60}):?\s*$'
)
_BULLET_RE = re.compile(r'^[•·\-\*]\s+(.+)$')


def _looks_like_markdown(text):
    return bool(re.search(r'^#{1,4} ', text, re.MULTILINE))


def _plain_to_html(text):
    """Convert plain-text job descriptions (• bullets, standalone headers) to HTML."""
    lines = text.splitlines()
    html_parts = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        bullet_match = _BULLET_RE.match(stripped)
        header_match = _HEADER_RE.match(stripped) if stripped else None

        if bullet_match:
            if not in_list:
                html_parts.append('<ul>')
                in_list = True
            html_parts.append(f'<li>{escape(bullet_match.group(1))}</li>')

        elif header_match and stripped:
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            # strip trailing colon
            label = stripped.rstrip(':')
            html_parts.append(f'<h3>{escape(label)}</h3>')

        elif stripped == '':
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            html_parts.append('')

        else:
            if in_list:
                html_parts.append('</ul>')
                in_list = False
            html_parts.append(f'<p>{escape(stripped)}</p>')

    if in_list:
        html_parts.append('</ul>')

    # collapse consecutive empty strings
    result = re.sub(r'(<p></p>|\n\s*\n)+', '', '\n'.join(html_parts))
    return result


# Every href/src the renderer produced is checked against an allow-list of
# schemes. A block-list (javascript:, data:) is not enough: browsers strip
# leading control characters and whitespace, so "\x01javascript:" still runs.
# Markdown text is recruiter-authored but shown on PUBLIC careers pages.
_LINK_ATTR_RE = re.compile(r'(href|src)\s*=\s*(["\'])(.*?)\2', re.IGNORECASE | re.DOTALL)
_SAFE_LINK_RE = re.compile(r'^(?:https?://|mailto:|#|/(?!/))', re.IGNORECASE)
_INVISIBLE_RE = re.compile(r'[\x00-\x20\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]')


def _safe_link(match) -> str:
    attr, quote, value = match.groups()
    cleaned = _INVISIBLE_RE.sub('', value)
    if not _SAFE_LINK_RE.match(cleaned):
        cleaned = '#'
    return f'{attr}={quote}{cleaned}{quote}'


def _strip_unsafe_links(html: str) -> str:
    return _LINK_ATTR_RE.sub(_safe_link, html)


@register.filter
def markdown(value):
    if not value:
        return ''
    if _looks_like_markdown(value):
        # Escape the input first so raw HTML (<script>…) cannot pass through the
        # markdown renderer; markdown syntax (#, -, *, [](…)) needs no <,>,&.
        html = md_lib.markdown(escape(value), extensions=['nl2br', 'sane_lists'])
    else:
        html = _plain_to_html(value)
    # Final guard: strip javascript:/data: hrefs from whichever branch produced links.
    html = _strip_unsafe_links(html)
    return mark_safe(html)


_MD_SYNTAX_RE = re.compile(
    r'^#{1,6}\s+'          # ATX headings
    r'|^[\s>*+\-]+'        # leading bullets / blockquotes (line start)
    r'|[*_`~]+'            # emphasis / code / strike markers
    r'|\[(.*?)\]\(.*?\)',  # links → keep label only (handled below)
)


@register.filter
def plaintext(value):
    """Strip markdown/markup so previews don't leak raw syntax (## , **, etc.)."""
    if not value:
        return ''
    text = str(value)
    # Replace markdown links [label](url) with just the label
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    # Drop heading hashes and blockquote/bullet markers at line starts
    text = re.sub(r'(?m)^[\s>]*#{1,6}\s+', '', text)
    text = re.sub(r'(?m)^[\s]*[*+\-]\s+', '', text)
    # Remove inline emphasis/code markers
    text = re.sub(r'[*_`~]+', '', text)
    # Collapse whitespace to a clean single-paragraph preview
    text = re.sub(r'\s+', ' ', text).strip()
    return text
