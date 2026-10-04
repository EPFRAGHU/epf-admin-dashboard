"""Pure month/coverage logic for the consultant monthly plan (no DB)."""
from datetime import datetime, timezone

import pytest

from webapp.consultant_plan import (
    add_months,
    compute_coverage,
    covers,
    current_month_ist,
    validate_months,
)


def test_current_month_ist_rolls_over_at_ist_midnight():
    assert current_month_ist(datetime(2026, 10, 31, 19, 0, tzinfo=timezone.utc)) == "2026-11"
    assert current_month_ist(datetime(2026, 10, 31, 18, 29, tzinfo=timezone.utc)) == "2026-10"


def test_add_months_crosses_year():
    assert add_months("2026-11", 3) == "2027-02"
    assert add_months("2026-12", 0) == "2026-12"


def test_compute_coverage_fresh_starts_current_month():
    assert compute_coverage("2026-10", None, 6) == ("2026-10", "2027-03")


def test_compute_coverage_extends_after_latest():
    assert compute_coverage("2026-10", "2026-12", 2) == ("2027-01", "2027-02")


def test_compute_coverage_lapsed_restarts_at_current():
    assert compute_coverage("2026-10", "2026-05", 1) == ("2026-10", "2026-10")


def test_covers_inclusive_bounds():
    windows = [("2026-10", "2026-12")]
    assert covers("2026-10", windows)
    assert covers("2026-12", windows)
    assert not covers("2026-09", windows)
    assert not covers("2027-01", windows)


def test_validate_months_rejects_bad_values():
    for bad in (0, -1, 25, "3", True, 2.5):
        with pytest.raises(ValueError):
            validate_months(bad)
    assert validate_months(1) == 1
    assert validate_months(24) == 24
