"""The Personal Effectiveness scoring model, pinned to the worked example.

The instrument is scored by hand today. If this file and the paper ever
disagree, the paper is right and this is the bug -- so the whole of the printed
example is reproduced here rather than a couple of spot checks.
"""
import pytest

from apps.sei_assessment import pe_scoring as pe

# The score sheet's filled example, already reversed there. Column order is
# Self-disclosure, Openness to feedback, Perceptiveness.
WORKED_EXAMPLE_SCORED = {
    1: 1, 4: 1, 7: 3, 10: 2, 13: 2,      # totals 9
    2: 4, 5: 4, 8: 2, 11: 1, 14: 4,      # totals 15
    3: 4, 6: 2, 9: 3, 12: 2, 15: 2,      # totals 13
}
# What the candidate actually ticked: reverse the reversed ones back.
WORKED_EXAMPLE_RAW = {
    item: (pe.MAX_RATING - value) if item in pe.REVERSED else value
    for item, value in WORKED_EXAMPLE_SCORED.items()
}
EXPECTED_TOTALS = {'self_disclosure': 9, 'openness': 15, 'perceptiveness': 13}


# ── the instrument itself ────────────────────────────────────────────────
def test_every_item_belongs_to_exactly_one_dimension():
    used = sorted(i for d in pe.DIMENSIONS for i in d['items'])
    assert used == list(range(1, 16))


def test_each_dimension_holds_five_items():
    for dimension in pe.DIMENSIONS:
        assert len(dimension['items']) == pe.ITEMS_PER_DIMENSION, dimension['key']


def test_every_item_has_text():
    assert len(pe.ITEMS) == 15
    for number, text in pe.ITEMS.items():
        assert text.strip(), number


def test_the_columns_match_the_score_sheet():
    """The sheet's three columns, read down. Mixing two items between columns
    would still total 45 overall and still produce three letters, so only the
    exact membership catches it."""
    assert {d['key']: d['items'] for d in pe.DIMENSIONS} == {
        'self_disclosure': (1, 4, 7, 10, 13),
        'openness': (2, 5, 8, 11, 14),
        'perceptiveness': (3, 6, 9, 12, 15),
    }


def test_the_reverse_scored_set_matches_the_sheet():
    assert pe.REVERSED == {1, 3, 4, 5, 6, 10, 11, 12, 15}


def test_item_eight_is_scored_directly():
    """The sheet leaves 8 out of both its lists; the table carries no (R) on
    it. Pinned because the worked example cannot settle it -- 8 was answered 2
    and 2 reverses to itself."""
    assert 8 not in pe.REVERSED
    assert pe.reversed_value(8, 4) == 4


@pytest.mark.parametrize('raw,expected', [(0, 4), (1, 3), (2, 2), (3, 1), (4, 0)])
def test_a_reverse_item_flips_on_the_nought_to_four_scale(raw, expected):
    """4 - x, not 3 - x: the sheet's own example says 1 becomes 3."""
    assert pe.reversed_value(1, raw) == expected


@pytest.mark.parametrize('raw', [0, 1, 2, 3, 4])
def test_a_forward_item_does_not(raw):
    assert pe.reversed_value(2, raw) == raw


# ── the worked example ───────────────────────────────────────────────────
def test_the_printed_example_reproduces_exactly():
    result = pe.score(WORKED_EXAMPLE_RAW)

    assert {d['key']: d['raw'] for d in result['dimensions']} == EXPECTED_TOTALS


def test_the_printed_example_gives_the_printed_letters_and_category():
    result = pe.score(WORKED_EXAMPLE_RAW)

    assert result['marks'] == ('L', 'H', 'H')
    assert result['category'] == 'Secretive'


# ── the H/L line ─────────────────────────────────────────────────────────
@pytest.mark.parametrize('total,expected', [
    (0, 'L'), (10, 'L'), (11, 'L'), (12, 'H'), (20, 'H'),
])
def test_eleven_itself_is_low(total, expected):
    """The sheet reads 'H if above 11, L if less than or equal to 11', so the
    boundary value belongs to Low."""
    assert pe.mark(total) == expected


def test_every_letter_combination_names_a_category():
    """Eight columns on the sheet, eight reachable combinations. A missing key
    would raise on a real candidate rather than at import."""
    from itertools import product
    assert set(pe.CATEGORIES) == set(product('HL', repeat=3))
    assert len(set(pe.CATEGORIES.values())) == 8


def test_the_category_table_matches_the_sheet():
    assert pe.CATEGORIES[('H', 'H', 'H')] == 'Effective'
    assert pe.CATEGORIES[('H', 'H', 'L')] == 'Insensitive'
    assert pe.CATEGORIES[('H', 'L', 'L')] == 'Egocentric'
    assert pe.CATEGORIES[('H', 'L', 'H')] == 'Dogmatic'
    assert pe.CATEGORIES[('L', 'H', 'H')] == 'Secretive'
    assert pe.CATEGORIES[('L', 'H', 'L')] == 'Task-obsessed'
    assert pe.CATEGORIES[('L', 'L', 'H')] == 'Lonely-empathic'
    assert pe.CATEGORIES[('L', 'L', 'L')] == 'Ineffective'


def test_a_perfect_and_a_blank_paper_sit_at_the_two_ends():
    top = pe.score({i: (0 if i in pe.REVERSED else 4) for i in pe.ITEMS})
    bottom = pe.score({i: (4 if i in pe.REVERSED else 0) for i in pe.ITEMS})

    assert [d['raw'] for d in top['dimensions']] == [20, 20, 20]
    assert top['category'] == 'Effective'
    assert [d['raw'] for d in bottom['dimensions']] == [0, 0, 0]
    assert bottom['category'] == 'Ineffective'


# ── completeness ─────────────────────────────────────────────────────────
@pytest.mark.parametrize('missing', [1, 2, 7, 14])
def test_one_blank_makes_the_paper_unscoreable(missing):
    """Five items to a column: one blank can move a total by 4, which is enough
    to cross the H/L line on its own. There is nothing to pro-rate against."""
    partial = {k: v for k, v in WORKED_EXAMPLE_RAW.items()
               if k != sorted(WORKED_EXAMPLE_RAW)[missing]}
    result = pe.score(partial)

    assert result['validity'] == pe.INVALID
    assert result['category'] is None
    assert result['marks'] is None
    assert result['dimensions'] == []
    assert result['answered'] == 14


@pytest.mark.parametrize('bad', [{7: 9}, {7: -1}, {7: 'three'}, {7: None},
                                 {99: 3}])
def test_unusable_answers_do_not_count_towards_the_threshold(bad):
    result = pe.score({**WORKED_EXAMPLE_RAW, **bad})

    assert result['answered'] == (15 if 99 in bad else 14)
    assert result['validity'] == (pe.COMPLETE if 99 in bad else pe.INVALID)


def test_answers_keyed_by_string_work_too():
    """They arrive from JSON, where keys are always strings."""
    as_strings = {str(k): v for k, v in WORKED_EXAMPLE_RAW.items()}

    assert pe.score(as_strings)['category'] == 'Secretive'


def test_a_full_paper_is_complete():
    result = pe.score(WORKED_EXAMPLE_RAW)

    assert result['validity'] == pe.COMPLETE
    assert result['answered'] == 15
    assert result['minimum'] == 15
