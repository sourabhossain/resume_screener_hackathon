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
    # 2018 -> 2020 reads as ~2 years (Jan 2018 to Jan 2020), not 3.
    assert years([{"start": "2018", "end": "2020"}]) == 2.0


def test_month_precision():
    # Jan 2020 -> Dec 2022 = 35 months ~= 2.9 years.
    assert years([{"start": "Jan 2020", "end": "Dec 2022"}]) == round(35 / 12, 1)


def test_numeric_month_formats():
    # 2020-03 -> 2021-03 = 12 months = 1.0 year.
    assert years([{"start": "2020-03", "end": "2021-03"}]) == 1.0
    assert years([{"start": "03/2020", "end": "03/2021"}]) == 1.0


def test_day_month_year_order_uses_month_adjacent_to_year():
    # DD/MM/YYYY (common in Bangladesh): the token next to the year is the month.
    # 06/07/2018 -> Jul 2018; 06/01/2020 -> Jan 2020 = 18 months.
    assert years([{"start": "06/07/2018", "end": "06/01/2020"}]) == round(18 / 12, 1)
    # Leading day > 12 was already unambiguous; keep it correct (Jun 2018 -> Jun 2019).
    assert years([{"start": "15/06/2018", "end": "15/06/2019"}]) == 1.0


def test_ongoing_uses_today():
    # Jan 2024 -> present, today = Jun 2026 => 29 months.
    assert years([{"start": "Jan 2024", "end": "present"}]) == round(29 / 12, 1)
    assert years([{"start": "2024", "end": "ongoing"}]) == round(29 / 12, 1)


def test_missing_end_assumes_ongoing():
    assert years([{"start": "2024", "end": ""}]) == round(29 / 12, 1)


def test_sequential_roles_sum():
    wh = [
        {"start": "2018", "end": "2020"},  # 24 months
        {"start": "2020", "end": "2022"},  # 24 months
    ]
    assert years(wh) == 4.0


def test_overlapping_roles_not_double_counted():
    # Concurrent roles must count the union, not the sum.
    wh = [
        {"start": "Jan 2020", "end": "Jan 2023"},  # 36 months
        {"start": "Jan 2021", "end": "Jan 2022"},  # fully inside the above
    ]
    assert years(wh) == 3.0


def test_partial_overlap_merges():
    wh = [
        {"start": "Jan 2020", "end": "Jan 2022"},  # 24 months
        {"start": "Jan 2021", "end": "Jan 2023"},  # overlaps 12 months
    ]
    # Union Jan 2020 -> Jan 2023 = 36 months = 3.0 years.
    assert years(wh) == 3.0


def test_malformed_reversed_span_skipped():
    assert years([{"start": "2022", "end": "2019"}]) == 0.0
