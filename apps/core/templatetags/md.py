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


@register.filter
def markdown(value):
    if not value:
        return ''
    if _looks_like_markdown(value):
        html = md_lib.markdown(value, extensions=['nl2br', 'sane_lists'])
    else:
        html = _plain_to_html(value)
    return mark_safe(html)
