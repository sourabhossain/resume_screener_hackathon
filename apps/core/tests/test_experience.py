"""
Tests for deterministic experience computation (services/experience.py).

These cover the failure modes that the old in-prompt LLM date math got wrong:
month precision, ongoing roles, overlapping/concurrent roles, and junk input.
"""
import datetime

from apps.core.services.experience import compute_experience_years

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
