"""
Tests for deterministic experience computation (services/experience.py).

These cover the failure modes that the old in-prompt LLM date math got wrong:
month precision, ongoing roles, overlapping/concurrent roles, and junk input.
"""
import datetime

from apps.core.services.experience import _abs_month, compute_experience_years

TODAY = datetime.date(2026, 6, 15)

def years(work_history):
    return compute_experience_years(work_history, today=TODAY)

def test_empty_and_invalid_input_is_zero():
    assert years([]) == 0.0
    assert years(None) == 0.0
    assert years("not a list") == 0.0
    assert years([{"start": "", "end": ""}]) == 0.0
    assert years([{"foo": "bar"}]) == 0.0

def test_year_only_span_non_inclusive():
    assert years([{"start": "2018", "end": "2020"}]) == 2.0

def test_month_precision():
    assert years([{"start": "Jan 2020", "end": "Dec 2022"}]) == round(35 / 12, 1)

def test_numeric_month_formats():
    assert years([{"start": "2020-03", "end": "2021-03"}]) == 1.0
    assert years([{"start": "03/2020", "end": "03/2021"}]) == 1.0

def test_day_month_year_order_uses_month_adjacent_to_year():
    assert years([{"start": "06/07/2018", "end": "06/01/2020"}]) == round(18 / 12, 1)
    assert years([{"start": "15/06/2018", "end": "15/06/2019"}]) == 1.0

def test_ongoing_uses_today():
    assert years([{"start": "Jan 2024", "end": "present"}]) == round(29 / 12, 1)
    assert years([{"start": "2024", "end": "ongoing"}]) == round(29 / 12, 1)

def test_missing_end_assumes_ongoing():
    assert years([{"start": "2024", "end": ""}]) == round(29 / 12, 1)

def test_sequential_roles_sum():
    wh = [
        {"start": "2018", "end": "2020"},
        {"start": "2020", "end": "2022"},
    ]
    assert years(wh) == 4.0

def test_overlapping_roles_not_double_counted():
    wh = [
        {"start": "Jan 2020", "end": "Jan 2023"},
        {"start": "Jan 2021", "end": "Jan 2022"},
    ]
    assert years(wh) == 3.0

def test_partial_overlap_merges():
    wh = [
        {"start": "Jan 2020", "end": "Jan 2022"},
        {"start": "Jan 2021", "end": "Jan 2023"},
    ]
    assert years(wh) == 3.0

def test_malformed_reversed_span_skipped():
    assert years([{"start": "2022", "end": "2019"}]) == 0.0

def test_future_end_clamps_to_today():
    expected_months = _abs_month(TODAY.year, TODAY.month) - _abs_month(2025, 1)
    assert years([{"start": "Jan 2025", "end": "Dec 2099"}]) == round(expected_months / 12.0, 1)

def test_future_start_is_zero():
    assert years([{"start": "Jan 2099", "end": "Dec 2099"}]) == 0.0
    assert years([{"start": "Jan 2099", "end": "present"}]) == 0.0

def test_clamp_preserves_overlap_value():
    wh = [
        {"start": "Jan 2020", "end": "Jan 2023"},
        {"start": "Jan 2021", "end": "Jan 2022"},
    ]
    assert years(wh) == 3.0

def test_bangla_year_only_matches_english():
    assert years([{"start": "২০২০", "end": "২০২২"}]) == years([{"start": "2020", "end": "2022"}])

def test_bangla_numeric_month_matches_english():
    assert years([{"start": "০৩/২০২০", "end": "০৩/২০২১"}]) == years([{"start": "03/2020", "end": "03/2021"}])

def test_mixed_bangla_english_does_not_crash():
    assert years([{"start": "Jan ২০২০", "end": "present"}]) == years([{"start": "Jan 2020", "end": "present"}])

def test_pure_english_unchanged():
    assert years([{"start": "Jan 2020", "end": "Dec 2022"}]) == round(35 / 12, 1)

def test_bangla_month_names_not_yet_mapped():
    # KNOWN LIMITATION, not desired behavior: Bangla month names are not in
    # _MONTHS, so they fall back to January and only the year is recovered —
    # জানুয়ারি ২০২০ - ডিসেম্বর ২০২২ yields the year-only value, not 2.9.
    # Follow-up: map Bangla month names for full month precision. When that
    # lands, this test will fail — that is the signal to update the expectation.
    assert years([{"start": "জানুয়ারি ২০২০", "end": "ডিসেম্বর ২০২২"}]) == years([{"start": "2020", "end": "2022"}])
