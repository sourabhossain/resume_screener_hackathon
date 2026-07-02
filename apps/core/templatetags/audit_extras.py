"""Presentation helpers for the Audit Trail page (display-only, no data changes)."""
import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

_KEY_EQ_RE = re.compile(r'(\b\w+)=')
_UUID_RE = re.compile(
    r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'
)

# Single source of truth for action -> semantic category. Kept here (not inline
# in the template) so the badge colours stay consistent everywhere.
_CATEGORY_BY_ACTION = {}
for _action in ('job.deleted', 'resume.deleted', 'interview.deleted',
                'user.deactivated', 'interview.eval_link_deleted'):
    _CATEGORY_BY_ACTION[_action] = 'destructive'
for _action in ('resume.score_overridden', 'resume.rescreen_requested'):
    _CATEGORY_BY_ACTION[_action] = 'override'
for _action in ('job.created', 'resume.uploaded', 'interview.created',
                'user.created', 'user.activated'):
    _CATEGORY_BY_ACTION[_action] = 'creation'
for _action in ('job.auto_closed', 'resume.screening_completed',
                'resume.screening_failed', 'resume.screening_needs_review'):
    _CATEGORY_BY_ACTION[_action] = 'system'

# Everything not mapped above (updates, status changes, renewals,
# evaluation_submitted, job.restored, ...) falls through to 'neutral'.
_CATEGORY_CLASSES = {
    'destructive': 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    'override': 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    'creation': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    'system': 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    'neutral': 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
}


@register.filter
def audit_category(action):
    """Semantic category for an action string (destructive/override/creation/system/neutral)."""
    return _CATEGORY_BY_ACTION.get(action, 'neutral')


@register.filter
def audit_badge(action):
    """Tailwind colour classes for an action badge, keyed by its category."""
    return _CATEGORY_CLASSES[audit_category(action)]


@register.filter
def audit_details(value):
    """Render machine 'key=value' details as a readable 'key: value' line.

    Rewrites each `key=` marker to `key: ` (values may contain spaces, e.g. an
    override reason). Any full UUID is truncated to its first 8 chars for
    display, with the full value in a title tooltip. Defensive: text with no
    key= markers passes through unchanged, so free-text details still display
    as-is.

    Returns escaped, safe HTML. Details are untrusted (public submissions), so
    every non-UUID segment is escaped; only the tooltip spans we build are
    marked safe.
    """
    if not value:
        return ''
    text = _KEY_EQ_RE.sub(r'\1: ', str(value))

    parts = []
    last = 0
    for m in _UUID_RE.finditer(text):
        parts.append(escape(text[last:m.start()]))
        full = m.group(0)
        parts.append(format_html(
            '<span class="cursor-help underline decoration-dotted" '
            'title="{}">{}…</span>', full, full[:8]))
        last = m.end()
    parts.append(escape(text[last:]))
    return mark_safe(''.join(parts))
