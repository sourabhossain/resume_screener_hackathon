"""
Deterministic experience-duration computation.

The extraction prompt returns raw work-history date spans only; it never does
date math (LLM arithmetic is non-deterministic and was the root cause of
corrupted experience scores). This module converts those raw spans into a
total years-of-experience figure with month precision, merging overlapping or
concurrent roles so they are not double-counted.
"""
import datetime
import re
from typing import List, Optional, Tuple

_MONTHS = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
    'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9, 'oct': 10,
    'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}

_PRESENT = {'present', 'current', 'ongoing', 'now', 'till date', 'to date', 'date'}

_YEAR_RE = re.compile(r'(19|20)\d{2}')

def _abs_month(year: int, month: int) -> int:
    """Absolute month index so durations are simple subtraction."""
    return year * 12 + (month - 1)

def _parse_endpoint(raw: Optional[str], *, is_end: bool, today: datetime.date) -> Optional[int]:
    """
    Parse one raw date string into an absolute month index.

    Returns None when nothing usable is found. Year-only values anchor to
    January, so "2018"->"2020" spans 24 months (the common resume reading)
    rather than inclusively counting both endpoints.
    """
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None

    if is_end and any(token in text for token in _PRESENT):
        return _abs_month(today.year, today.month)

    year_match = _YEAR_RE.search(text)
    if not year_match:
        return None
    year = int(year_match.group(0))

    month = None
    for name, num in _MONTHS.items():
        if re.search(rf'\b{name}\b', text):
            month = num
            break
    if month is None:
        year_start, year_end = year_match.span()
        candidates = []
        for m in re.finditer(r'\d{1,2}', text):
            s, e = m.span()
            if s >= year_start and e <= year_end:
                continue
            value = int(m.group(0))
            if 1 <= value <= 12:
                distance = year_start - e if e <= year_start else s - year_end
                candidates.append((distance, value))
        if candidates:
            candidates.sort(key=lambda c: c[0])
            month = candidates[0][1]
    if month is None:
        month = 1

    return _abs_month(year, month)

def _intervals(work_history, today: datetime.date) -> List[Tuple[int, int]]:
    intervals: List[Tuple[int, int]] = []
    if not isinstance(work_history, list):
        return intervals
    for entry in work_history:
        if not isinstance(entry, dict):
            continue
        start = _parse_endpoint(entry.get('start'), is_end=False, today=today)
        end = _parse_endpoint(entry.get('end'), is_end=True, today=today)
        if start is None:
            continue
        if end is None:
            end = _abs_month(today.year, today.month)
        if end < start:
            continue
        intervals.append((start, end))
    return intervals

def _merge(intervals: List[Tuple[int, int]]) -> int:
    """Total months covered by the union of intervals (overlaps counted once)."""
    if not intervals:
        return 0
    intervals.sort()
    total = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end:
            cur_end = max(cur_end, end)
        else:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
    total += cur_end - cur_start
    return total

def compute_experience_years(work_history, today: Optional[datetime.date] = None) -> float:
    """
    Total years of experience from raw work-history spans.

    Deterministic, month-precise, and overlap-safe. Returns 0.0 for empty or
    unparseable input. Rounds to one decimal place.
    """
    today = today or datetime.date.today()
    months = _merge(_intervals(work_history, today))
    return round(months / 12.0, 1)
