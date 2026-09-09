"""The Social & Emotional Intelligence instrument: items, scoring, norms.

Transcribed from the HRARD assessment sheet. The column layout and both
multipliers were checked against the worked example printed on that sheet --
all six dimension totals, the grand total of 103 and the derived percentages
reproduce exactly, which is what makes the mapping below trustworthy.

Two decisions are recorded here rather than buried in a view:

  * The multipliers are the published 4.17 and 0.7, not the exact 100/24 and
    100/144. Kept so a score computed here matches one worked by hand on the
    paper sheet. The cost is that a perfect score reads 100.08 / 100.8 rather
    than 100.
  * A blank is never treated as a raw 0. On the twenty reverse-scored items a
    raw 0 becomes 3, so that reading would hand 60 points to a candidate who
    answered nothing. How blanks are handled instead depends on how many there
    are -- see COMPLETENESS below.

COMPLETENESS

    48 of 48    scored normally.
    44 to 47    scored, with each dimension pro-rated over the items that were
                answered. A blank neither adds nor subtracts; the dimension is
                scaled to its full eight-item equivalent.
    43 or fewer no score at all. Too much of the instrument is missing for the
                dimension norms to mean anything, so the sitting is reported as
                Invalid - Insufficient Responses and has to be taken again.
"""

TIME_LIMIT_MINUTES = 20

# Below this many answers there is no score, only a request to sit it again.
MINIMUM_VALID_ANSWERS = 44

COMPLETE = 'complete'
ADJUSTED = 'adjusted'
INVALID = 'invalid'
INVALID_LABEL = 'Invalid - Insufficient Responses'
MIN_RATING, MAX_RATING = 0, 3
ITEMS_PER_DIMENSION = 8

RATING_LABELS = (
    (0, 'Not true'),
    (1, 'A little true'),
    (2, 'Fairly true'),
    (3, 'Definitely true'),
)

ITEMS = {
    1: 'I can tell when I am getting upset and why',
    2: 'I get angry when I am criticized by my peers',
    3: 'I constantly worry about my weaknesses',
    4: 'When faced with a problem, I tend to postpone working on it if I can',
    5: 'I trust only myself to get things done',
    6: 'People like me',
    7: 'I often wish I was someone else',
    8: 'I prefer not to stir up problems, if I can avoid doing so',
    9: 'I have been continually frustrated in my life because of failures',
    10: 'I know I can find solutions to difficult problems',
    11: 'I can tell when my close friend is upset',
    12: 'When I have a problem I know whom to go to or what to do to help solve it',
    13: 'I accept myself even when I know that I am not perfect',
    14: 'I do not hesitate in expressing my disagreement',
    15: 'I can accomplish most of the things with my effort',
    16: 'I see challenge as opportunity for learning',
    17: "I can put myself in someone else's shoes",
    18: 'I find it difficult to establish contact with important persons',
    19: 'I cannot accept compliments easily',
    20: "I find it difficult to accept others' opinions different from mine",
    21: 'Circumstances are beyond my control',
    22: 'I find it difficult to bounce back (come back to normal self) after '
        'feeling disappointed',
    23: "I appreciate my friends' positive qualities",
    24: 'I can socialize well',
    25: 'I like myself as I am',
    26: "I know how to say 'no' when I have to",
    27: 'I greatly enjoy the activities I am involved in',
    28: 'I enjoy taking responsibility',
    29: "I cannot know about people's pain and problems unless they talk about it",
    30: 'I do not enjoy taking leadership roles',
    31: 'I am aware of my feelings',
    32: 'I think about what I want before I act',
    33: 'I experience eating problems (loss of appetite, overeating, no time to eat)',
    34: 'Studies are fun for me (I enjoy studies)',
    35: 'I use different ways of expressing my emotions, depending on who I am '
        'interacting with',
    36: 'I have several friends I can count on, as and when I need them',
    37: 'I am jealous of friends who score more than I do',
    38: 'I avoid confrontations (frank unpleasant discussions)',
    39: 'I have trouble in concentrating',
    40: 'I find it difficult to work under pressure',
    41: "I am not emotional and I am not moved by other persons' emotional "
        'experiences',
    42: 'I feel lonely and have very few good friends',
    43: 'I know what I want',
    44: 'I remain calm even in situations when others get angry',
    45: 'While sitting alone or day-dreaming, I recollect pleasant events and '
        'happenings',
    46: 'I can accomplish what I need to, if I put my mind to it',
    47: 'I do not care how others might feel',
    48: 'I enjoy taking roles and responsibilities in groups',
}

# Reverse-scored: 0<->3, 1<->2. Read from the starred (R) entries on the sheet.
REVERSED = frozenset({
    2, 3, 4, 5, 7, 9, 18, 19, 20, 21, 22, 30, 33, 37, 38, 39, 40, 41, 42, 47,
})

# One column of the score sheet each, eight items apiece.
DIMENSIONS = (
    {'key': 'self_awareness', 'label': 'Self-awareness',
     'items': (1, 7, 13, 19, 25, 31, 37, 43),
     'norm': (70, 80),
     'blurb': "The ability to recognise and understand one's own moods, "
              'emotions and drives, and to accept oneself with strengths and '
              'weaknesses.'},
    {'key': 'self_management', 'label': 'Self-management',
     'items': (2, 8, 14, 20, 26, 32, 38, 44),
     'norm': (55, 65),
     'blurb': 'The ability to redirect and control disruptive impulses and '
              'moods, to judge how others might feel before acting, and to '
              'postpone immediate gratification for long-term goals.'},
    {'key': 'internality', 'label': 'Internality and optimism',
     'items': (3, 9, 15, 21, 27, 33, 39, 45),
     'norm': (64, 74),
     'blurb': 'Taking charge of situations, seeing failures as temporary, and '
              'intense involvement in experiences rather than brooding over '
              'them.'},
    {'key': 'motivation', 'label': 'Motivation',
     'items': (4, 10, 16, 22, 28, 34, 40, 46),
     'norm': (65, 75),
     'blurb': 'Working for reasons beyond money or status, bouncing back from '
              'disappointment, and pursuing goals with energy and persistence.'},
    {'key': 'empathy', 'label': 'Empathy',
     'items': (5, 11, 17, 23, 29, 35, 41, 47),
     'norm': (47, 57),
     'blurb': 'Understanding the emotional makeup of other people, and dealing '
              'with them according to their emotional reaction.'},
    {'key': 'social_skills', 'label': 'Social skills',
     'items': (6, 12, 18, 24, 30, 36, 42, 48),
     'norm': (62, 72),
     'blurb': 'Proficiency in managing relationships and building networks, '
              'reflected in building and leading teams.'},
)

TOTAL_NORM = (61, 71)
DIMENSION_FACTOR = 4.17   # published; exact would be 100/24
TOTAL_FACTOR = 0.7        # published; exact would be 100/144


def reversed_value(item: int, raw: int) -> int:
    """The raw answer as it counts towards the score."""
    return (MAX_RATING - raw) if item in REVERSED else raw


def band(value: float, norm) -> str:
    low, high = norm
    if value < low:
        return 'low'
    return 'high' if value > high else 'average'


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
    """Score a set of answers keyed by item number (values 0-3, as given).

    Below MINIMUM_VALID_ANSWERS nothing is scored: the caller gets
    validity='invalid' and no dimensions, because a report built on half an
    instrument would read as a finding rather than as a gap.
    """
    answers = answers or {}
    answered = answered_items(answers)
    total_items = len(ITEMS)

    if answered < MINIMUM_VALID_ANSWERS:
        return {
            'validity': INVALID,
            'validity_label': INVALID_LABEL,
            'dimensions': [],
            'total_raw': None,
            'total_percent': None,
            'total_band': None,
            'total_norm': TOTAL_NORM,
            'answered': answered,
            'total_items': total_items,
            'minimum': MINIMUM_VALID_ANSWERS,
        }

    validity = COMPLETE if answered == total_items else ADJUSTED
    dimensions, grand_raw = [], 0.0

    for spec in DIMENSIONS:
        raw, counted = 0, 0
        for item in spec['items']:
            value = _usable(answers, item)
            if value is None:
                continue
            counted += 1
            raw += reversed_value(item, value)

        # Pro-rated to the full eight items, so a blank neither adds nor
        # subtracts. Scaling rather than zero-filling is the whole reason the
        # 44-47 band is scoreable at all.
        adjusted = raw * (ITEMS_PER_DIMENSION / counted) if counted else 0.0
        percent = round(adjusted * DIMENSION_FACTOR, 2)
        grand_raw += adjusted

        dimensions.append({
            'key': spec['key'],
            'label': spec['label'],
            'blurb': spec['blurb'],
            'raw': raw,
            'adjusted_raw': round(adjusted, 2),
            'answered': counted,
            'of': ITEMS_PER_DIMENSION,
            'prorated': counted < ITEMS_PER_DIMENSION,
            'percent': percent,
            'band': band(percent, spec['norm']),
            'norm': spec['norm'],
        })

    total_percent = round(grand_raw * TOTAL_FACTOR, 2)
    return {
        'validity': validity,
        'validity_label': ('Complete' if validity == COMPLETE
                           else f'Adjusted - {answered} of {total_items} answered'),
        'dimensions': dimensions,
        'total_raw': round(grand_raw, 2),
        'total_percent': total_percent,
        'total_band': band(total_percent, TOTAL_NORM),
        'total_norm': TOTAL_NORM,
        'answered': answered,
        'total_items': total_items,
        'minimum': MINIMUM_VALID_ANSWERS,
    }
