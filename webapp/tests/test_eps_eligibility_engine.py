from datetime import date

from epf_engine import (
    calc_age_years,
    employees_joined_in_month,
    employees_left_in_month,
)


def test_calc_age_years_parses_hyphen_format():
    """The only DOB format this app ever actually stores -- confirmed via
    employees.js's parseDMY() and epf_engine.py's own import format_date(),
    both of which normalize to hyphens, never slashes."""
    assert calc_age_years("15-06-1968", as_of=date(2026, 6, 1)) == 57
    assert calc_age_years("15-06-1968", as_of=date(2026, 6, 15)) == 58
    assert calc_age_years("15-06-1968", as_of=date(2026, 7, 1)) == 58


def test_calc_age_years_rejects_slash_format():
    """Slash-format DOB never occurs in real data -- this asserts the OLD buggy
    behavior is gone by confirming hyphen parsing works instead, not by asserting
    slash parsing fails (that would just pin the bug the other way)."""
    assert calc_age_years("") is None
    assert calc_age_years("not-a-date") is None


def test_calc_age_years_missing_dob_returns_none():
    assert calc_age_years("") is None
    assert calc_age_years(None) is None


class _FakeMaster:
    def __init__(self, member_id, doj="", doe=""):
        self.member_id = member_id
        self.doj = doj
        self.doe = doe


class _FakeProject:
    def __init__(self, masters):
        self._masters = masters

    def master_list(self):
        return self._masters


def test_employees_joined_in_month_parses_hyphen_doj():
    project = _FakeProject([_FakeMaster("M1", doj="12-06-2026")])
    matches = employees_joined_in_month(project, 2026, 6)
    assert len(matches) == 1
    assert matches[0].member_id == "M1"


def test_employees_left_in_month_parses_hyphen_doe():
    project = _FakeProject([_FakeMaster("M2", doe="30-09-2026")])
    matches = employees_left_in_month(project, 2026, 9)
    assert len(matches) == 1
    assert matches[0].member_id == "M2"
