"""The instruments a job can ask a candidate to sit, behind one interface.

Two things are deliberately kept apart here:

  * DELIVERY is shared. The token, the emailed code, the clock, the autosave,
    the lock that stops two tabs losing each other's answers, the sweep that
    closes an abandoned sitting -- one implementation, used by every
    instrument. That code is the security-sensitive half; a second copy of it
    is a second place for a bug to survive a fix.
  * SCORING is not. Each instrument keeps its own module because the scoring
    models genuinely differ -- SEI runs 0-3 with percentages against published
    norm bands, PE runs 0-4 with raw column totals and an H/L cut. Forcing one
    shape on both would mean inventing numbers neither sheet prints.

Adding a third instrument means writing its scoring module and adding one
entry below. Nothing else in the app needs to know it exists.

NAMING DEBT: the app package and its table are still called `sei_assessment`
from when SEI was the only instrument. Renaming a Django app label and table
with live rows in it is a migration risk that buys nothing functional, so it
is left for a release of its own.
"""
from dataclasses import dataclass
from typing import Callable

from . import pe_scoring, scoring

SEI = 'sei'
PE = 'pe'


@dataclass(frozen=True)
class Instrument:
    """One sittable questionnaire, as the rest of the app sees it."""

    key: str
    label: str
    short_label: str
    blurb: str
    items: dict
    rating_labels: tuple
    min_rating: int
    max_rating: int
    time_limit_minutes: int
    minimum_answers: int
    score: Callable[[dict], dict]
    answered_items: Callable[[dict], int]
    report_template: str

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def sorted_items(self):
        return sorted(self.items.items())


REGISTRY = {
    SEI: Instrument(
        key=SEI,
        label='Social and emotional intelligence',
        short_label='SEI',
        blurb='Forty-eight statements rated 0 to 3, scored against published '
              'norms on six dimensions.',
        items=scoring.ITEMS,
        rating_labels=scoring.RATING_LABELS,
        min_rating=scoring.MIN_RATING,
        max_rating=scoring.MAX_RATING,
        time_limit_minutes=scoring.TIME_LIMIT_MINUTES,
        minimum_answers=scoring.MINIMUM_VALID_ANSWERS,
        score=scoring.score,
        answered_items=scoring.answered_items,
        report_template='sei_assessment/report.html',
    ),
    PE: Instrument(
        key=PE,
        label='Personal effectiveness',
        short_label='PE',
        blurb='Fifteen statements rated 0 to 4, scored as three column totals '
              'that read High or Low and name one of eight categories.',
        items=pe_scoring.ITEMS,
        rating_labels=pe_scoring.RATING_LABELS,
        min_rating=pe_scoring.MIN_RATING,
        max_rating=pe_scoring.MAX_RATING,
        time_limit_minutes=8,
        minimum_answers=len(pe_scoring.ITEMS),
        score=pe_scoring.score,
        answered_items=pe_scoring.answered_items,
        report_template='sei_assessment/report_pe.html',
    ),
}

# Order matters: it is the order a candidate is emailed them and the order the
# checkboxes appear on the job form.
ORDER = (SEI, PE)


def get(key: str) -> Instrument:
    """The instrument for `key`. Raises KeyError on an unknown one."""
    return REGISTRY[key]


def all_instruments():
    return [REGISTRY[key] for key in ORDER]


def choices():
    """(key, label) pairs for a form field."""
    return [(key, REGISTRY[key].label) for key in ORDER]


def clean_keys(keys) -> list:
    """The known keys out of `keys`, in ORDER, without duplicates.

    Job.assessments is a JSONField, so whatever is in it came from a form, a
    fixture or a shell. A key that no longer exists must not stop a candidate
    being shortlisted, so unknown ones are dropped rather than raised.
    """
    seen = set(keys or ())
    return [key for key in ORDER if key in seen]
