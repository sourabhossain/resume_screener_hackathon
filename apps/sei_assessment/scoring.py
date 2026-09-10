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

THE READINGS

Each dimension carries the sheet's own two-column interpretation: one list for
Average-or-High, one for Below-average, selected by the band. Transcribed
verbatim apart from the sheet's typos ('enotions', 'amd', 'arid', 'lending
teams', 'string up', 'You what you want in life'), which are corrected.

The wording addresses the candidate in the second person because the sheet
does. The report presents it as a quotation rather than as its own prose, so an
HR reader is not addressed as the person being described.

One sentence is deliberately NOT carried: the Empathy Average-or-High row
reading "...since you are emotional and you are not moved by other persons'
emotional experiences" contradicts itself in the source. Reproducing it would
print nonsense in a hiring file and rewriting it would put words into a
published instrument, so it is dropped and the remaining Empathy rows stand.
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
              'weaknesses.',
     'above': (
         'have the ability to convey when you are getting upset by clearly '
         'articulating the reason for it.',
         'tend to live with your originality and rarely regret on yourself '
         'even at the time of passing through the hardships. You like '
         'yourself as you are.',
         'almost in all occasion you accept yourself even when you know that '
         'you are not perfect.',
         'value in accepting compliments easily.',
         'are mostly aware of your feelings; you know what you want in life.',
     ),
     'below': (
         'need to improve your ability to express when you are getting upset '
         'by clearly articulating the reason for it.',
         'often wish you were someone else especially when you are facing '
         'hardships. You need to practice in liking yourself as you are in '
         'any difficult situation.',
         'would require to develop your ability in accepting yourself in all '
         'spheres of your life in spite of knowing the fact that you are not '
         'perfect.',
         'need to win over your hesitations to accept compliments.',
         'need to increase your awareness on your feelings by identifying '
         'what actually you want in your life.',
     )},
    {'key': 'self_management', 'label': 'Self-management',
     'items': (2, 8, 14, 20, 26, 32, 38, 44),
     'norm': (55, 65),
     'blurb': 'The ability to redirect and control disruptive impulses and '
              'moods, to judge how others might feel before acting, and to '
              'postpone immediate gratification for long-term goals.',
     'above': (
         'mostly behave normal even when you are getting criticized by '
         'others. You remain calm even in situations when others get annoyed '
         'on you.',
         'usually think about what you want before you act and hence you '
         'prefer avoiding hue and cry towards facing problems; you would '
         'rather become proactive towards not to stir up problems.',
         "do not hesitate in expressing your disagreement since you know how "
         "to say 'no' when you require to do so.",
         'usually do not avoid any frank unpleasant discussions since you '
         "have the ability to easily accept others' opinions even if that is "
         'different from yours.',
     ),
     'below': (
         'need to control your temperament even when you get criticized by '
         'others. You need to remain calm even in situations when others get '
         'annoyed on you.',
         'would require to adapt proactive approach so as to avoid stirring '
         'up of any problem. You need to think about what you want before '
         'you act.',
         'need to remove your hesitations in expressing your disagreement by '
         "acquiring the competency of knowing how to say 'no' when you "
         'require to do so.',
         'need to confront the frank unpleasant discussions since you '
         "generally find it difficult to accept others' opinions different "
         'from yours.',
     )},
    {'key': 'internality', 'label': 'Internality and optimism',
     'items': (3, 9, 15, 21, 27, 33, 39, 45),
     'norm': (64, 74),
     'blurb': 'Taking charge of situations, seeing failures as temporary, and '
              'intense involvement in experiences rather than brooding over '
              'them.',
     'above': (
         'can accomplish most of the things with your effort since you are '
         'mostly living with pleasant events and happenings.',
         'greatly enjoy the activities you are involved in without worrying '
         'about your weakness.',
         'mostly finish all of your assignments in time since you have the '
         'ability to concentrate without being frustrated in your life '
         'because of past failures.',
     ),
     'below': (
         'need to improve your ability to concentrate on the current '
         'assignments rather than being continually frustrated in your life '
         'because of failures.',
         'need to enjoy the activities you are involved in without '
         'constantly worrying about your weaknesses.',
         'would require to improve your self-confidence that you can '
         'accomplish most of the things with your effort rather than '
         'exaggerating that circumstances are beyond your control.',
     )},
    {'key': 'motivation', 'label': 'Motivation',
     'items': (4, 10, 16, 22, 28, 34, 40, 46),
     'norm': (65, 75),
     'blurb': 'Working for reasons beyond money or status, bouncing back from '
              'disappointment, and pursuing goals with energy and persistence.',
     'above': (
         'usually take responsibility and put your mind to accomplish the '
         'assigned job/task.',
         'know you can find solutions to difficult problems since you take '
         'challenge as opportunity for learning.',
     ),
     'below': (
         'need to learn coping with the stress since you find it difficult '
         'to bounce back (come back to normal self) after feeling '
         'disappointed.',
         'would require to adapt the ability to work under pressure since '
         'you have a tendency to avoid in accomplishing any particular task '
         '/ job when faced with a problem.',
     )},
    {'key': 'empathy', 'label': 'Empathy',
     'items': (5, 11, 17, 23, 29, 35, 41, 47),
     'norm': (47, 57),
     'blurb': 'Understanding the emotional makeup of other people, and dealing '
              'with them according to their emotional reaction.',
     # The sheet's second Average-or-High row is dropped -- see THE READINGS.
     'above': (
         'tend to trust others to get things done even though you may '
         "sometimes face challenges to know about people's pain and problems "
         'unless they talk about it.',
     ),
     'below': (
         'need to improve your interpersonal trust level since generally you '
         'trust only yourself to get things done. You need to enhance your '
         "caring attitude to get moved by other persons' emotional "
         'experiences.',
         'need to acquire abilities to use different ways of expressing your '
         'emotions. You need to learn appreciating the positive qualities of '
         'the person whom you are interacting with.',
     )},
    {'key': 'social_skills', 'label': 'Social skills',
     'items': (6, 12, 18, 24, 30, 36, 42, 48),
     'norm': (62, 72),
     'blurb': 'Proficiency in managing relationships and building networks, '
              'reflected in building and leading teams.',
     'above': (
         'can socialize well since people like you. Hence it is not '
         'difficult for you to establish contact with important persons.',
         'can get many helping hands as and when you need them and therefore '
         'when you face a problem you know whom to go to or what to do to '
         'help solve it.',
         'enjoy taking leadership roles and responsibilities in groups.',
     ),
     'below': (
         'need to build social network since you very often feel lonely.',
         'need to acquire team effectiveness since you must know whom to go '
         'to or what to do to help solve the problem that you face in life.',
         'would require to adapt the mindset of enjoying the accomplishment '
         'of your roles and responsibilities in groups since you find it '
         'difficult to establish contact with important persons.',
     )},
)

TOTAL_NORM = (61, 71)
DIMENSION_FACTOR = 4.17   # published; exact would be 100/24
TOTAL_FACTOR = 0.7        # published; exact would be 100/144

DIMENSION_MAX_RAW = ITEMS_PER_DIMENSION * MAX_RATING
TOTAL_MAX_RAW = len(ITEMS) * MAX_RATING

# An SSL Wireless hiring rule, NOT part of the instrument. The sheet sets norms
# and interpretation text and says nothing about hiring; this line is the only
# place the company's own cut-off lives, so changing the policy is one edit.
#
# Three things to know before moving it:
#   * The sheet's own Low boundary is TOTAL_NORM[0] = 61, not 60. At 60 a paper
#     the instrument calls Low can still clear the bar.
#   * TOTAL_FACTOR is the published 0.7 rather than the exact 100/144, so a
#     displayed total runs ~0.8% high. An exact 59.6 shows as 60.2 and passes.
#     Any hard cut-off sits inside that rounding.
#   * It is applied to the total only. The dimension norms sit anywhere from 47
#     to 80, so one number cannot mean the same thing across them.
HIRING_THRESHOLD = 60


def reversed_value(item: int, raw: int) -> int:
    """The raw answer as it counts towards the score."""
    return (MAX_RATING - raw) if item in REVERSED else raw


def band(value: float, norm) -> str:
    low, high = norm
    if value < low:
        return 'low'
    return 'high' if value > high else 'average'


def track(value: float, norm) -> dict:
    """Where a score and its average band sit on a shared 0-100 axis.

    The report draws all seven scores against the same axis, which is the only
    way to see that the bands themselves sit in different places -- Empathy is
    Average from 47, Self-awareness only from 70. Computed here because a
    template cannot subtract, and clamped because the published multipliers put
    a perfect paper slightly over 100.
    """
    low, high = norm
    return {
        'marker': round(min(max(value, 0.0), 100.0), 2),
        'band_start': low,
        'band_width': high - low,
    }


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
            'by_band': {'high': (), 'average': (), 'low': ()},
            'dimensions': [],
            'total_raw': None,
            'total_percent': None,
            'total_band': None,
            'total_norm': TOTAL_NORM,
            'total_track': None,
            'total_max_raw': TOTAL_MAX_RAW,
            # No score means no decision: an unscoreable paper is a retake, not
            # a rejection.
            'threshold': HIRING_THRESHOLD,
            'below_threshold': False,
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
        verdict = band(percent, spec['norm'])

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
            'band': verdict,
            'norm': spec['norm'],
            'max_raw': DIMENSION_MAX_RAW,
            'track': track(percent, spec['norm']),
            'reading': spec['below'] if verdict == 'low' else spec['above'],
        })

    total_percent = round(grand_raw * TOTAL_FACTOR, 2)
    by_band = {
        name: tuple(d['label'] for d in dimensions if d['band'] == name)
        for name in ('high', 'average', 'low')
    }
    return {
        'by_band': by_band,
        'validity': validity,
        'validity_label': ('Complete' if validity == COMPLETE
                           else f'Adjusted - {answered} of {total_items} answered'),
        'dimensions': dimensions,
        'total_raw': round(grand_raw, 2),
        'total_percent': total_percent,
        'total_band': band(total_percent, TOTAL_NORM),
        'total_norm': TOTAL_NORM,
        'total_track': track(total_percent, TOTAL_NORM),
        'total_max_raw': TOTAL_MAX_RAW,
        'threshold': HIRING_THRESHOLD,
        'below_threshold': total_percent < HIRING_THRESHOLD,
        'answered': answered,
        'total_items': total_items,
        'minimum': MINIMUM_VALID_ANSWERS,
    }
