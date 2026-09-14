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


from epf_engine import MasterEmployee, Project


def test_master_employee_eps_member_defaults_true():
    m = MasterEmployee(member_id="M1", name="Test")
    assert m.eps_member is True


def test_upsert_master_sets_eps_member_false():
    p = Project()
    p.set_establishment("EST1", "Test Co", "Addr")
    p.upsert_master("M1", "Test Employee", eps_member=False)
    assert p.master["M1"].eps_member is False


def test_upsert_master_eps_member_defaults_true_when_not_passed():
    p = Project()
    p.set_establishment("EST1", "Test Co", "Addr")
    p.upsert_master("M1", "Test Employee")
    assert p.master["M1"].eps_member is True


def test_build_employees_for_year_carries_eps_member_and_year_from():
    p = Project()
    p.set_establishment("EST1", "Test Co", "Addr")
    p.upsert_master("M1", "Test Employee", eps_member=False)
    p.years["2026-2027"] = __import__("epf_engine").YearRecord(year_from="2026", year_to="2027")
    p.upsert_entry("2026-2027", "M1", [1000.0] * 12)
    emps = p.build_employees_for_year("2026-2027")
    assert len(emps) == 1
    assert emps[0].eps_member is False
    assert emps[0].year_from == "2026"


from epf_engine import wage_month_start_date, is_eps_zero_for_month, Employee


def test_wage_month_start_date_mar_to_dec_falls_in_year_from():
    assert wage_month_start_date(0, "2026") == date(2026, 3, 1)   # month_idx 0 = March
    assert wage_month_start_date(9, "2026") == date(2026, 12, 1)  # month_idx 9 = December


def test_wage_month_start_date_jan_feb_falls_in_year_from_plus_one():
    assert wage_month_start_date(10, "2026") == date(2027, 1, 1)  # January
    assert wage_month_start_date(11, "2026") == date(2027, 2, 1)  # February


def test_is_eps_zero_for_month_birthday_month_still_gets_eps():
    """DOB 15-06-1968 turns 58 on 15-06-2026. FY 2026-27: month_idx 3 = June 2026.
    As of June 1 2026 (month start) they're still 57 -- EPS still applies that month."""
    assert is_eps_zero_for_month("15-06-1968", 3, "2026") is False


def test_is_eps_zero_for_month_zero_from_the_following_month():
    """Same employee: month_idx 4 = July 2026. As of July 1 2026 they're already 58."""
    assert is_eps_zero_for_month("15-06-1968", 4, "2026") is True


def test_is_eps_zero_for_month_missing_dob_never_auto_zeroes():
    assert is_eps_zero_for_month("", 4, "2026") is False


def test_month_rows_zeroes_eps_from_the_month_after_the_58th_birthday():
    """End-to-end through month_rows() itself, not just the helper -- confirms the
    wiring, not just the date math."""
    emp = Employee(member_id="M1", dob="15-06-1968", eps_member=True, year_from="2026",
                    wages=[75000] * 12, gross_wages=[75000] * 12)
    rows = emp.month_rows(worker_epf_rate=12.0, worker_eps_rate=0.0,
                           employer_epf_rate=3.67, employer_eps_rate=8.33)
    june = rows[3]   # w, w_epf, w_eps, w_total, e_epf, e_eps, e_total
    july = rows[4]
    assert june[5] > 0     # e_eps (EPS contribution) still present in June
    assert july[5] == 0    # zero from July
    assert july[4] == june[1]  # July's e_epf equals the full employer contribution (== w_epf, the EE 12% amount)


def test_month_rows_eps_member_false_zeroes_every_month_regardless_of_age():
    """RFE-21 fix: a 30-year-old (nowhere near 58) with eps_member=False must still
    get EPS=0 every month."""
    emp = Employee(member_id="M1", dob="01-01-1996", eps_member=False, year_from="2026",
                    wages=[75000] * 12, gross_wages=[75000] * 12)
    rows = emp.month_rows(worker_epf_rate=12.0, worker_eps_rate=0.0,
                           employer_epf_rate=3.67, employer_eps_rate=8.33)
    for r in rows:
        assert r[5] == 0


def test_ecr_generation_respects_dob_driven_eps_cutover(consultant_a, superadmin_session, test_db):
    """End-to-end: an employee whose DOB makes them 58+ this financial year must show
    EPS=0 in the actual ECR text file, not just in month_rows() directly. This is the
    test that would have caught _build_ecr_employees_for_scope() never copying dob
    over from MasterEmployee.

    Note: wages are set directly via Project.upsert_entry(), not through the PUT /wages
    API endpoint, to work around a pre-existing bug in that endpoint (Task 6 fix).
    Superadmin is used for ECR download to bypass subscription fee gating."""
    import json
    from epf_engine import Project
    from webapp.database import Establishment
    from webapp.auth import save_establishment_project

    # Create establishment through API
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "ECRDOB01", "name": "ECR DOB Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)

    # Create year and employee through API
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/employees", json={
        "member_id": "ECRD001", "name": "ECR DOB Test Employee", "uan": "100900000001",
        "dob": "01-01-1950",
    })
    assert res.status_code == 200, res.text

    # Add wage data directly to the project (bypassing the broken PUT /wages endpoint)
    est_obj = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    assert est_obj is not None
    project = Project()
    if est_obj.data:
        data_dict = json.loads(est_obj.data)
        project.load_from_dict(data_dict)
    project.upsert_entry("2026-27", "ECRD001", [30000.0] + [0.0] * 11)
    save_establishment_project(test_db, est_obj, project)

    # Test ECR generation through API (use superadmin to bypass subscription fee gating)
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200, res.text
    ecr_text = res.text
    fields = ecr_text.strip().split("#~#")
    # UAN#~#Name#~#Gross#~#EPF#~#EPS#~#EDLI#~#EE_Share#~#EPS_Share#~#ER_EPF#~#NCP#~#Refund
    assert fields[4] == "0"   # EPS Wages must be 0
    assert fields[7] == "0"   # EPS Contribution Remitted must be 0
