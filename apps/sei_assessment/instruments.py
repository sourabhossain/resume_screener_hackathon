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


# One hue at rising intensity, so the scale reads as "more of this", not as
# good versus bad. `ink` is the text colour that clears the fill it sits on.
#
# Dark needs its own steps rather than the same hexes: on a dark ground the
# lightest step is the loudest, which would stand the scale on its head -- the
# first option would shout and the last would disappear. These rise in
# lightness instead, and every step stays visible against the dark card.
# One colour per answer on a one-question screen, from "not at all" (slate)
# to "most" (green): (badge, fill, text) in light, then in dark. Each badge
# carries white text at 4.5:1 or better; each dark badge carries near-black.
_TONES_5 = (('#475569', '#eef0f4', '#3f4a5c'), ('#c2410c', '#fdf1e3', '#9a3412'),
            ('#7e22ce', '#f4ebfe', '#6b21a8'), ('#4338ca', '#e8e9fd', '#3730a3'),
            ('#15803d', '#e3f6ea', '#166534'))
_DARK_5 = (('#94a3b8', '#262a31', '#cbd5e1'), ('#fb923c', '#33261b', '#fdba74'),
           ('#c084fc', '#2d2238', '#d8b4fe'), ('#818cf8', '#24253d', '#c7d2fe'),
           ('#4ade80', '#1c2e24', '#86efac'))
_TONES_4 = (_TONES_5[0], _TONES_5[1], _TONES_5[3], _TONES_5[4])
_DARK_4 = (_DARK_5[0], _DARK_5[1], _DARK_5[3], _DARK_5[4])


@dataclass(frozen=True)
class Instrument:
    """One sittable questionnaire, as the rest of the app sees it."""

    key: str
    label: str
    short_label: str
    blurb: str
    items: dict
    rating_labels: tuple
    rating_short: tuple
    ramp: tuple
    dark_ramp: tuple
    min_rating: int
    max_rating: int
    time_limit_minutes: int
    minimum_answers: int
    score: Callable[[dict], dict]
    answered_items: Callable[[dict], int]
    report_template: str
    # What the candidate sees. They are never shown `label`: a named test
    # invites rehearsed answers, so the portal only ever says "Part 1".
    per_page: int
    noun: str
    noun_plural: str
    prompt: str
    practice: str
    accent: tuple

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def sorted_items(self):
        return sorted(self.items.items())

    @property
    def scale(self):
        """One row of the response scale: value, what the candidate reads, and
        its colours in both themes as CSS custom properties."""
        letters = 'ABCDEFGHIJ'
        return [
            {'value': value, 'label': label, 'full': full, 'letter': letters[i],
             'tone': (f'--oc:{badge};--ob:{fill};--ot:{text};'
                      f'--ocd:{dbadge};--obd:{dfill};--otd:{dtext};')}
            for i, ((value, label), (_, full), (badge, fill, text), (dbadge, dfill, dtext))
            in enumerate(zip(self.rating_short, self.rating_labels,
                             self.ramp, self.dark_ramp))
        ]

    @property
    def accent_style(self) -> str:
        """CSS custom properties for this part's colour, light and dark."""
        fill, ink, dark_fill, dark_ink = self.accent
        return f'--c:{fill};--ci:{ink};--cd:{dark_fill};--cdi:{dark_ink};'

    def page_of(self, item_no: int) -> int:
        """The zero-based screen an item is shown on."""
        return (item_no - 1) // self.per_page

    def paginate(self, answers: dict):
        """The statements in screens of `per_page`, each carrying the answer
        already stored for it so a resumed sitting comes back filled."""
        answers = answers or {}
        items = [
            {'no': no, 'text': text, 'value': answers.get(str(no))}
            for no, text in self.sorted_items
        ]
        return [items[i:i + self.per_page]
                for i in range(0, len(items), self.per_page)]


REGISTRY = {
    SEI: Instrument(
        key=SEI,
        label='Social and emotional intelligence',
        short_label='SEI',
        blurb='Forty-eight statements rated 0 to 3, scored against published '
              'norms on six dimensions.',
        items=scoring.ITEMS,
        rating_labels=scoring.RATING_LABELS,
        rating_short=scoring.RATING_SHORT,
        ramp=_TONES_4,
        dark_ramp=_DARK_4,
        min_rating=scoring.MIN_RATING,
        max_rating=scoring.MAX_RATING,
        time_limit_minutes=scoring.TIME_LIMIT_MINUTES,
        minimum_answers=scoring.MINIMUM_VALID_ANSWERS,
        score=scoring.score,
        answered_items=scoring.answered_items,
        report_template='sei_assessment/report.html',
        per_page=5,
        noun='statement',
        noun_plural='statements',
        prompt='Select how true each statement is about you.',
        practice='I enjoy learning new things.',
        accent=('#0f766e', '#ffffff', '#2dd4bf', '#042f2e'),
    ),
    PE: Instrument(
        key=PE,
        label='Personal effectiveness',
        short_label='PE',
        blurb='Fifteen statements rated 0 to 4, scored as three column totals '
              'that read High or Low and name one of eight categories.',
        items=pe_scoring.ITEMS,
        rating_labels=pe_scoring.RATING_LABELS,
        rating_short=pe_scoring.RATING_SHORT,
        ramp=_TONES_5,
        dark_ramp=_DARK_5,
        min_rating=pe_scoring.MIN_RATING,
        max_rating=pe_scoring.MAX_RATING,
        time_limit_minutes=8,
        minimum_answers=len(pe_scoring.ITEMS),
        score=pe_scoring.score,
        answered_items=pe_scoring.answered_items,
        report_template='sei_assessment/report_pe.html',
        per_page=1,
        noun='question',
        noun_plural='questions',
        prompt='Select how characteristic each statement is of you.',
        practice='I enjoy meeting new people.',
        accent=('#284699', '#ffffff', '#8ba6f2', '#0b1633'),
    ),
}

# Order matters: it is the order a candidate takes them (Part 1, Part 2) and
# the order the checkboxes appear on the job form. The shorter one goes first
# so a candidate settles in before the long one.
ORDER = (PE, SEI)


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
