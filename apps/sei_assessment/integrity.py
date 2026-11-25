"""What the assessment page saw the candidate do while a part was running.

A browser cannot stop a candidate opening another tab or reaching for a phone;
it can make copying awkward and say when the page lost the candidate's
attention. The page sends those moments with its autosaves, they are kept on the
sitting (SEIAssessment.integrity), and the recruiter sees them on the report.
They are signals to weigh, not proof: a notification or a lost connection can
also move focus away.
"""
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone

# type -> label on the report. Order is the order the report lists them.
LABELS = {
    'tab_hidden': 'Switched tab or minimised the browser',
    'window_blur': 'Left the window for another app or window',
    'fullscreen_exit': 'Left full screen',
    'second_tab': 'Opened the assessment in a second tab',
    'reopened': 'Opened the part again (reload, or another window or device)',
    'copy': 'Tried to copy',
    'cut': 'Tried to cut',
    'paste': 'Tried to paste',
    'contextmenu': 'Right-clicked',
    'shortcut': 'Pressed a blocked shortcut',
    'print': 'Tried to print',
    'screenshot_key': 'Pressed Print Screen',
    'fullscreen_refused': 'Did not allow full screen',
}
# Recorded for the timeline but not counted as a flag.
NOT_FLAGS = frozenset({'reopened'})
# Only the server writes these; the page may not send them.
SERVER_ONLY = frozenset({'reopened'})

MAX_EVENTS = 300
MAX_PER_TYPE = 40
MAX_PER_REQUEST = 50


def _when(value, floor=None):
    """An event time from the page (ms since epoch), kept within the sitting."""
    now = timezone.now()
    try:
        at = datetime.fromtimestamp(float(value) / 1000, tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return now
    if at > now:
        return now
    return floor if floor and at < floor else at


def _stored(sitting):
    """The stored record, or an empty one if it was ever written in another shape."""
    data = sitting.integrity if isinstance(sitting.integrity, dict) else {}
    counts = data.get('counts') if isinstance(data.get('counts'), dict) else {}
    events = data.get('events') if isinstance(data.get('events'), list) else []
    counts = {k: v for k, v in counts.items() if isinstance(v, int) and not isinstance(v, bool)}
    return data, counts, [e for e in events if isinstance(e, dict)]


def record(sitting, events, *, from_page=True):
    """Merge events into the sitting's record (not saved here).

    The timeline keeps at most MAX_PER_TYPE of each kind, so a page flooding
    one harmless kind cannot push the others off it; counts are always kept.
    """
    data, counts, timeline = _stored(sitting)
    data = dict(data)
    per_type = {}
    for entry in timeline:
        per_type[entry.get('type')] = per_type.get(entry.get('type'), 0) + 1
    for event in (events or [])[:MAX_PER_REQUEST]:
        if not isinstance(event, dict) or event.get('type') not in LABELS:
            continue
        kind = event['type']
        if from_page and kind in SERVER_ONLY:
            continue
        entry = {'type': kind, 'at': _when(event.get('at'), sitting.started_at).isoformat()}
        seconds = event.get('seconds')
        if isinstance(seconds, (int, float)) and 0 <= seconds < 86400:
            entry['seconds'] = round(seconds)
        detail = event.get('detail')
        if isinstance(detail, str) and detail:
            entry['detail'] = detail[:40]
        counts[kind] = counts.get(kind, 0) + 1
        if len(timeline) < MAX_EVENTS and per_type.get(kind, 0) < MAX_PER_TYPE:
            timeline.append(entry)
            per_type[kind] = per_type.get(kind, 0) + 1
    data['counts'] = counts
    data['events'] = timeline
    sitting.integrity = data
    return data


def summary(sitting):
    """(flag count, [(label, count)], [timeline rows]) for the report."""
    _, counts, events = _stored(sitting)
    rows = [(LABELS[kind], counts[kind]) for kind in LABELS if counts.get(kind)]
    flags = sum(n for kind, n in counts.items() if kind in LABELS and kind not in NOT_FLAGS)
    timeline = []
    for entry in events:
        try:
            at = timezone.localtime(datetime.fromisoformat(entry['at']))
        except (KeyError, TypeError, ValueError):
            continue
        timeline.append({'at': at, 'label': LABELS.get(entry.get('type'), entry.get('type')),
                         'seconds': entry.get('seconds'), 'detail': entry.get('detail', '')})
    return flags, rows, timeline
