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

MAX_EVENTS = 300
MAX_PER_REQUEST = 50


def _when(value):
    """An event time from the page (ms since epoch), kept within the sitting."""
    now = timezone.now()
    try:
        at = datetime.fromtimestamp(float(value) / 1000, tz=dt_timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return now
    return now if at > now else at


def record(sitting, events):
    """Merge events sent by the page into the sitting's record (not saved here)."""
    data = dict(sitting.integrity or {})
    counts = dict(data.get('counts') or {})
    timeline = list(data.get('events') or [])
    for event in (events or [])[:MAX_PER_REQUEST]:
        if not isinstance(event, dict) or event.get('type') not in LABELS:
            continue
        kind = event['type']
        entry = {'type': kind, 'at': _when(event.get('at')).isoformat()}
        seconds = event.get('seconds')
        if isinstance(seconds, (int, float)) and 0 <= seconds < 86400:
            entry['seconds'] = round(seconds)
        detail = event.get('detail')
        if isinstance(detail, str) and detail:
            entry['detail'] = detail[:40]
        counts[kind] = counts.get(kind, 0) + 1
        if len(timeline) < MAX_EVENTS:
            timeline.append(entry)
    data['counts'] = counts
    data['events'] = timeline
    sitting.integrity = data
    return data


def summary(sitting):
    """(flag count, [(label, count)], [timeline rows]) for the report."""
    data = sitting.integrity or {}
    counts = data.get('counts') or {}
    rows = [(LABELS[kind], counts[kind]) for kind in LABELS if counts.get(kind)]
    flags = sum(n for kind, n in counts.items() if kind in LABELS and kind not in NOT_FLAGS)
    timeline = []
    for entry in data.get('events') or []:
        try:
            at = timezone.localtime(datetime.fromisoformat(entry['at']))
        except (KeyError, TypeError, ValueError):
            continue
        timeline.append({'at': at, 'label': LABELS.get(entry.get('type'), entry.get('type')),
                         'seconds': entry.get('seconds'), 'detail': entry.get('detail', '')})
    return flags, rows, timeline
