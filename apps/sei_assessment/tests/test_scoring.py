"""The SEI scoring model, pinned to the worked example on the paper sheet.

The instrument is scored by hand today. If this file and the paper ever
disagree, the paper is right and this is the bug -- so the whole of the printed
example is reproduced here rather than a couple of spot checks.
"""
import pytest

from apps.sei_assessment import scoring

# Every response printed in the filled example on the assessment sheet, already
# reversed there. Stored raw here so the reversal is exercised, not assumed.
WORKED_EXAMPLE_SCORED = {
    1: 2, 2: 2, 3: 2, 4: 2, 5: 1, 6: 3, 7: 1, 8: 3, 9: 3, 10: 3, 11: 2, 12: 2,
    13: 2, 14: 2, 15: 3, 16: 3, 17: 2, 18: 2, 19: 3, 20: 3, 21: 2, 22: 2,
    23: 2, 24: 2, 25: 2, 26: 1, 27: 2, 28: 2, 29: 1, 30: 3, 31: 2, 32: 2,
    33: 3, 34: 3, 35: 2, 36: 2, 37: 2, 38: 1, 39: 2, 40: 2, 41: 2, 42: 1,
    43: 2, 44: 2, 45: 3, 46: 2, 47: 2, 48: 3,
}
# What the candidate actually ticked: reverse the reversed ones back.
WORKED_EXAMPLE_RAW = {
    item: (scoring.MAX_RATING - value) if item in scoring.REVERSED else value
    for item, value in WORKED_EXAMPLE_SCORED.items()
}
EXPECTED = {
    'self_awareness':  (16, 66.72),
    'self_management': (16, 66.72),
    'internality':     (20, 83.40),
    'motivation':      (19, 79.23),
    'empathy':         (14, 58.38),
    'social_skills':   (18, 75.06),
}


# ── the instrument itself ────────────────────────────────────────────────
def test_every_item_belongs_to_exactly_one_dimension():
    used = sorted(i for d in scoring.DIMENSIONS for i in d['items'])
    assert used == list(range(1, 49))


def test_each_dimension_holds_eight_items():
    for dimension in scoring.DIMENSIONS:
        assert len(dimension['items']) == scoring.ITEMS_PER_DIMENSION, dimension['key']


def test_every_item_has_text():
    assert len(scoring.ITEMS) == 48
    for number, text in scoring.ITEMS.items():
        assert text.strip(), number


def test_the_reverse_scored_set_matches_the_sheet():
    assert scoring.REVERSED == {
        2, 3, 4, 5, 7, 9, 18, 19, 20, 21, 22, 30, 33, 37, 38, 39, 40, 41, 42, 47,
    }


@pytest.mark.parametrize('raw,expected', [(0, 3), (1, 2), (2, 1), (3, 0)])
def test_a_reverse_item_flips(raw, expected):
    assert scoring.reversed_value(2, raw) == expected


@pytest.mark.parametrize('raw', [0, 1, 2, 3])
def test_a_forward_item_does_not(raw):
    assert scoring.reversed_value(1, raw) == raw


# ── the worked example ───────────────────────────────────────────────────
def test_the_printed_example_reproduces_exactly():
    result = scoring.score(WORKED_EXAMPLE_RAW)
    got = {d['key']: (d['raw'], d['percent']) for d in result['dimensions']}

    assert got == EXPECTED, got


def test_the_printed_grand_total_reproduces():
    result = scoring.score(WORKED_EXAMPLE_RAW)

    assert result['total_raw'] == 103
    assert result['total_percent'] == 72.1


def test_the_printed_example_lands_in_the_printed_bands():
    """The same raw 16 is Low on self-awareness and High on self-management --
    the norms differ per dimension, and mixing them up would misreport people."""
    result = scoring.score(WORKED_EXAMPLE_RAW)
    bands = {d['key']: d['band'] for d in result['dimensions']}

    assert bands['self_awareness'] == 'low'
    assert bands['self_management'] == 'high'
    assert bands['internality'] == 'high'
    assert bands['motivation'] == 'high'
    assert bands['empathy'] == 'high'
    assert bands['social_skills'] == 'high'
    assert result['total_band'] == 'high'


# ── how many answers make a paper scoreable ──────────────────────────────
def _partial(missing):
    """The worked example with `missing` items removed from the end."""
    return {k: v for k, v in WORKED_EXAMPLE_RAW.items() if k <= 48 - missing}


@pytest.mark.parametrize('answered', [48, 47, 46, 45, 44])
def test_forty_four_or_more_is_scored(answered):
    result = scoring.score(_partial(48 - answered))

    assert result['answered'] == answered
    assert result['validity'] == (scoring.COMPLETE if answered == 48
                                  else scoring.ADJUSTED)
    assert result['total_percent'] is not None


@pytest.mark.parametrize('answered', [43, 40, 20, 1, 0])
def test_forty_three_or_fewer_is_not_scored_at_all(answered):
    """A report built on half an instrument would be read as a finding rather
    than as a gap, so nothing is reported and the sitting is taken again."""
    result = scoring.score(_partial(48 - answered))

    assert result['validity'] == scoring.INVALID
    assert result['validity_label'] == 'Invalid - Insufficient Responses'
    assert result['total_percent'] is None
    assert result['total_raw'] is None
    assert result['dimensions'] == []
    assert result['answered'] == answered


def test_the_threshold_sits_exactly_between_43_and_44():
    assert scoring.score(_partial(4))['validity'] == scoring.ADJUSTED   # 44
    assert scoring.score(_partial(5))['validity'] == scoring.INVALID    # 43


# ── how a blank is handled in the scoreable band ─────────────────────────
def test_a_blank_neither_adds_nor_subtracts():
    """Pro-rated, not zero-filled. Zero-filling would punish a blank; treating
    a blank as a raw 0 and reversing it would reward one.

    Every item is answered so that it *scores* 3 -- which means 0 on the
    reverse-scored ones. Answering a plain 3 everywhere would not do: reversal
    turns those into zeros and the paper would no longer be uniform, so scaling
    could not be expected to reproduce the same figure.
    """
    top_marks = {item: (0 if item in scoring.REVERSED else 3)
                 for item in scoring.ITEMS}
    minus_four = {k: v for k, v in top_marks.items() if k > 4}

    scored_full = scoring.score(top_marks)
    scored_partial = scoring.score(minus_four)

    assert scored_partial['answered'] == 44
    assert scored_partial['total_percent'] == scored_full['total_percent']


def test_a_pro_rated_dimension_says_so():
    """The scaling rests on fewer answers than the norms assume, and HR has to
    be able to see which dimension that was."""
    minus_two_from_one_dimension = {
        k: v for k, v in WORKED_EXAMPLE_RAW.items() if k not in (1, 7)
    }
    result = scoring.score(minus_two_from_one_dimension)
    by_key = {d['key']: d for d in result['dimensions']}

    assert by_key['self_awareness']['prorated'] is True
    assert by_key['self_awareness']['answered'] == 6
    assert by_key['self_management']['prorated'] is False
    assert by_key['self_management']['answered'] == 8


def test_scaling_is_per_dimension_not_across_the_whole_paper():
    """Four blanks in one dimension must not be spread over the other five --
    each dimension carries its own norms."""
    missing_half_of_one = {
        k: v for k, v in WORKED_EXAMPLE_RAW.items() if k not in (1, 7, 13, 19)
    }
    result = scoring.score(missing_half_of_one)
    by_key = {d['key']: d for d in result['dimensions']}

    assert by_key['self_awareness']['answered'] == 4
    # Untouched dimensions keep exactly the printed figures.
    assert by_key['internality']['percent'] == 83.40
    assert by_key['empathy']['percent'] == 58.38


@pytest.mark.parametrize('bad', [{43: 9}, {43: -1}, {43: 'three'}, {43: None},
                                 {99: 3}])
def test_unusable_answers_do_not_count_towards_the_threshold(bad):
    """Otherwise a paper padded with nonsense would look complete enough to
    score. The junk goes on items the partial left blank, so it can only push
    the count up if it is wrongly counted."""
    forty_two = _partial(6)
    assert scoring.answered_items(forty_two) == 42

    result = scoring.score({**forty_two, **bad})

    assert result['answered'] == 42
    assert result['validity'] == scoring.INVALID


def test_an_unusable_answer_replaces_a_good_one_rather_than_adding():
    """Overwriting a real answer with junk lowers the count, it does not keep
    the old value alive."""
    forty_four = _partial(4)
    assert scoring.answered_items(forty_four) == 44

    spoiled = scoring.score({**forty_four, 1: 'nonsense'})

    assert spoiled['answered'] == 43
    assert spoiled['validity'] == scoring.INVALID


def test_answers_keyed_by_string_work_too():
    """They arrive from JSON, where keys are always strings."""
    as_strings = {str(k): v for k, v in WORKED_EXAMPLE_RAW.items()}

    assert scoring.score(as_strings)['total_percent'] == 72.1


# ── the norms ────────────────────────────────────────────────────────────
def test_a_perfect_paper_uses_the_published_multipliers():
    """The sheet's 4.17 and 0.7 are rounded, so a perfect score reads slightly
    over 100. Kept deliberately so these numbers match one worked by hand --
    pinned here so the choice is a decision rather than a surprise."""
    result = scoring.score({item: (0 if item in scoring.REVERSED else 3)
                            for item in scoring.ITEMS})

    assert result['total_raw'] == 144.0
    assert result['total_percent'] == 100.8
    assert all(d['percent'] == 100.08 for d in result['dimensions'])


@pytest.mark.parametrize('value,expected', [
    (69.99, 'low'), (70, 'average'), (80, 'average'), (80.01, 'high'),
])
def test_band_edges_are_inclusive_of_the_average_range(value, expected):
    assert scoring.band(value, (70, 80)) == expected


def test_no_reachable_score_lands_exactly_on_a_band_edge():
    """The bands are written <70 / 70-80 / >80, so an exact 70 or 80 would be
    arguable. No multiple of the multipliers reaches one, which is why the
    ambiguity never has to be resolved."""
    dimension_scores = {round(raw * scoring.DIMENSION_FACTOR, 2) for raw in range(25)}
    edges = {edge for d in scoring.DIMENSIONS for edge in d['norm']}
    assert not (dimension_scores & edges)

    total_scores = {round(raw * scoring.TOTAL_FACTOR, 2) for raw in range(145)}
    assert not (total_scores & set(scoring.TOTAL_NORM))
