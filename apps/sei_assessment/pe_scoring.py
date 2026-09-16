"""The Personal Effectiveness Scale: items, scoring, categories.

Transcribed from the TDA/CIMS score sheet. The column layout, the reversed
set and the H/L rule were checked against the worked example printed on that
sheet -- 9 / 15 / 13 giving L, H, H and the category Secretive -- which is what
makes the mapping below trustworthy.

Differences from the SEI instrument in scoring.py, all of them deliberate:

  * Ratings run 0-4, not 0-3, so a reversal is 4 - x. The sheet's own example
    ("if the original response is say 1, then you have to actually enter 3")
    only works on that scale.
  * There is no percentage and no norm band. Each column is a raw total out of
    20, marked H above 11 and L at 11 or below, and the three letters together
    name one of eight categories.
  * Every one of the fifteen must be answered. With only five items per column
    a single blank moves that column's total by up to 4, which is enough to
    cross the H/L line on its own -- there is nothing here to pro-rate against.

ITEM 8

    The sheet marks nine items (R) and lists five as copied directly, which
    leaves item 8 in neither list. The score-sheet table is the authority and
    it carries no (R) on 8, so it is scored directly. The worked example cannot
    settle it either way -- 8 was answered 2, and 2 reverses to itself -- but
    the statement is a plainly positive one ("I take steps to find out how my
    behavior has been perceived"), which agrees with the table.
"""

MIN_RATING, MAX_RATING = 0, 4
ITEMS_PER_DIMENSION = 5

COMPLETE = 'complete'
INVALID = 'invalid'
INVALID_LABEL = 'Invalid - Insufficient Responses'

# Above this a column is High; at it or below, Low.
HIGH_ABOVE = 11

RATING_LABELS = (
    (0, 'Not at all characteristic'),
    (1, 'Not true, only occasionally'),
    (2, 'Somewhat true'),
    (3, 'Fairly true, quite often'),
    (4, 'Most characteristic'),
)

ITEMS = {
    1: 'I find it difficult to be frank with people unless I know them very well',
    2: "I listen carefully to others' opinions about my behaviour",
    3: 'I tend to say things that turn out to be out of place',
    4: 'Generally, I hesitate to express my feelings to others',
    5: 'When someone directly tells me how he or she feels about my behaviour, '
       'I tend to close up and stop listening',
    6: 'On hindsight, I regret why I said something tactlessly',
    7: 'I express my opinions in a group or to a person without hesitation',
    8: 'I take steps to find out how my behaviour has been perceived by the '
       'person with whom I have been interacting',
    9: 'I deliberately observe how a person will take what I am going to tell '
       'them, and communicate accordingly',
    10: 'When someone discusses their personal problems, I do not spontaneously '
        'share my own experiences and problems of a similar nature with them',
    11: 'If someone criticizes me, I hear them at that time but do not bother '
        'myself about it later',
    12: "I fail to pick up cues about others' feelings and reactions when I am "
        'involved in an argument or a conversation',
    13: 'I enjoy talking to others about my personal concerns and matters',
    14: 'I value what people have to say about my style, behaviour and so on',
    15: 'I am often surprised to discover, or to be told, that people were put '
        'off, bored or annoyed when I thought they were enjoying interacting '
        'with me',
}

# Starred (R) on the score sheet. Reversal on this instrument is 4 - x.
REVERSED = frozenset({1, 3, 4, 5, 6, 10, 11, 12, 15})

# One column of the score sheet each, five items apiece.
DIMENSIONS = (
    {'key': 'self_disclosure', 'label': 'Self-disclosure',
     'items': (1, 4, 7, 10, 13)},
    {'key': 'openness', 'label': 'Openness to feedback',
     'items': (2, 5, 8, 11, 14)},
    {'key': 'perceptiveness', 'label': 'Perceptiveness',
     'items': (3, 6, 9, 12, 15)},
)

DIMENSION_MAX = ITEMS_PER_DIMENSION * MAX_RATING

# The sheet's own table, keyed by the three letters in column order.
CATEGORIES = {
    ('H', 'H', 'H'): 'Effective',
    ('H', 'H', 'L'): 'Insensitive',
    ('H', 'L', 'L'): 'Egocentric',
    ('H', 'L', 'H'): 'Dogmatic',
    ('L', 'H', 'H'): 'Secretive',
    ('L', 'H', 'L'): 'Task-obsessed',
    ('L', 'L', 'H'): 'Lonely-empathic',
    ('L', 'L', 'L'): 'Ineffective',
}


def reversed_value(item: int, raw: int) -> int:
    """The raw answer as it counts towards the score."""
    return (MAX_RATING - raw) if item in REVERSED else raw


def mark(total: int) -> str:
    """H or L for one column total."""
    return 'H' if total > HIGH_ABOVE else 'L'


def _usable(answers: dict, item: int):
    """The answer to one item, or None if it is missing or unusable."""
    value = answers.get(item, answers.get(str(item)))
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if MIN_RATING <= value <= MAX_RATING else None


def answered_items(answers: dict) -> int:
    return sum(1 for item in ITEMS if _usable(answers, item) is not None)


def score(answers: dict) -> dict:
    """Score a set of answers keyed by item number (values 0-4, as given).

    Anything short of all fifteen is not scored: see the module docstring.
    """
    answers = answers or {}
    answered = answered_items(answers)
    total_items = len(ITEMS)

    if answered < total_items:
        return {
            'validity': INVALID,
            'validity_label': INVALID_LABEL,
            'dimensions': [],
            'category': None,
            'marks': None,
            'answered': answered,
            'total_items': total_items,
            'minimum': total_items,
            'dimension_max': DIMENSION_MAX,
        }

    dimensions, marks = [], []
    for spec in DIMENSIONS:
        raw = sum(reversed_value(item, _usable(answers, item))
                  for item in spec['items'])
        letter = mark(raw)
        marks.append(letter)
        dimensions.append({
            'key': spec['key'],
            'label': spec['label'],
            'items': spec['items'],
            'raw': raw,
            'max': DIMENSION_MAX,
            'mark': letter,
            'is_high': letter == 'H',
            'high_above': HIGH_ABOVE,
            # Where the total and the H/L line sit on a shared 0-20 track.
            'percent_of_max': round(raw / DIMENSION_MAX * 100, 2),
            'cut_percent': round(HIGH_ABOVE / DIMENSION_MAX * 100, 2),
        })

    return {
        'validity': COMPLETE,
        'validity_label': 'Complete',
        'dimensions': dimensions,
        'marks': tuple(marks),
        'category': CATEGORIES[tuple(marks)],
        'answered': answered,
        'total_items': total_items,
        'minimum': total_items,
        'dimension_max': DIMENSION_MAX,
    }
