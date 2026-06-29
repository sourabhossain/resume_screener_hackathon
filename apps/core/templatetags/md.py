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

    result = re.sub(r'(<p></p>|\n\s*\n)+', '', '\n'.join(html_parts))
    return result

_UNSAFE_LINK_RE = re.compile(
    r'(href|src)\s*=\s*(["\'])\s*(?:javascript|data|vbscript):[^"\']*\2',
    re.IGNORECASE,
)

def _strip_unsafe_links(html: str) -> str:
    return _UNSAFE_LINK_RE.sub(r'\1=\2#\2', html)

@register.filter
def markdown(value):
    if not value:
        return ''
    if _looks_like_markdown(value):
        html = md_lib.markdown(escape(value), extensions=['nl2br', 'sane_lists'])
    else:
        html = _plain_to_html(value)
    html = _strip_unsafe_links(html)
    return mark_safe(html)

_MD_SYNTAX_RE = re.compile(
    r'^#{1,6}\s+'
    r'|^[\s>*+\-]+'
    r'|[*_`~]+'
    r'|\[(.*?)\]\(.*?\)',
)

@register.filter
def plaintext(value):
    """Strip markdown/markup so previews don't leak raw syntax (## , **, etc.)."""
    if not value:
        return ''
    text = str(value)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'(?m)^[\s>]*#{1,6}\s+', '', text)
    text = re.sub(r'(?m)^[\s]*[*+\-]\s+', '', text)
    text = re.sub(r'[*_`~]+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
