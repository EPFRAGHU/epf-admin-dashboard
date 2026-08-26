"""Coverage for chronological month/year entry gating: a consultant/employer can only
enter wage data one month at a time, anchored to the establishment's coverage_date,
each unlocking only once the previous one is paid. See
docs/superpowers/specs/2026-08-26-month-year-entry-gating-design.md."""
from webapp.app import get_financial_year_key_for_date, get_coverage_year_key
from epf_engine import Project


def test_get_financial_year_key_for_date_mar_to_dec_belongs_to_same_calendar_year():
    assert get_financial_year_key_for_date(2020, 3) == "2020-21"
    assert get_financial_year_key_for_date(2020, 12) == "2020-21"


def test_get_financial_year_key_for_date_jan_feb_belongs_to_previous_calendar_year():
    assert get_financial_year_key_for_date(2021, 1) == "2020-21"
    assert get_financial_year_key_for_date(2021, 2) == "2020-21"


def test_get_coverage_year_key_parses_ddmmyyyy():
    p = Project()
    p.coverage_date = "15-06-2020"
    assert get_coverage_year_key(p) == "2020-21"


def test_get_coverage_year_key_jan_date_belongs_to_previous_fy():
    p = Project()
    p.coverage_date = "10-01-2021"
    assert get_coverage_year_key(p) == "2020-21"


def test_get_coverage_year_key_returns_none_when_blank():
    p = Project()
    p.coverage_date = ""
    assert get_coverage_year_key(p) is None
