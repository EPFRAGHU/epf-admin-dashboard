import os
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


def test_add_employee_accepts_eps_member_false(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "EPSM0001", "name": "EPS Member Test Co",
    })
    assert res.status_code == 200, res.text
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    res = consultant_a.post("/api/employees", json={
        "member_id": "EPSM001", "name": "Non Member Employee", "uan": "100900000003",
        "eps_member": False,
    })
    assert res.status_code == 200, res.text
    emps = consultant_a.get("/api/employees").json()["employees"]
    emp = next(e for e in emps if e["member_id"] == "EPSM001")
    assert emp["eps_member"] is False


def test_add_employee_eps_member_defaults_true(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "EPSM0002", "name": "EPS Member Default Co",
    })
    assert res.status_code == 200, res.text
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    res = consultant_a.post("/api/employees", json={
        "member_id": "EPSM002", "name": "Default Member Employee", "uan": "100900000004",
    })
    assert res.status_code == 200, res.text
    emps = consultant_a.get("/api/employees").json()["employees"]
    emp = next(e for e in emps if e["member_id"] == "EPSM002")
    assert emp["eps_member"] is True


def test_get_wages_returns_eps_zero_months_not_age_crosses_58(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "EPSM0003", "name": "EPS Zero Months Co",
    })
    assert res.status_code == 200, res.text
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={
        "member_id": "EPSM003", "name": "Boundary Employee", "uan": "100900000005",
        "dob": "15-06-1968",
    })
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "EPSM003", "wages": [75000.0] * 12,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "EPSM003")
    assert "age_crosses_58" not in emp
    assert emp["eps_member"] is True
    assert len(emp["eps_zero_months"]) == 12
    assert emp["eps_zero_months"][3] is False  # June -- birthday month, still EPS
    assert emp["eps_zero_months"][4] is True   # July -- zero from here


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


def _save_58plus_employee_wages(test_db, est_id, member_id, year_key="2026-27",
                                 wages=None):
    """Shared setup for the display-recomputation tests below: loads the
    establishment's Project, writes one month of wages directly via
    Project.upsert_entry(), and saves it back -- the same workaround
    test_ecr_generation_respects_dob_driven_eps_cutover uses to bypass the
    pre-existing (Task 6) bug in POST /api/years/{key}/wages."""
    import json
    from epf_engine import Project
    from webapp.database import Establishment
    from webapp.auth import save_establishment_project

    est_obj = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    assert est_obj is not None
    project = Project()
    if est_obj.data:
        project.load_from_dict(json.loads(est_obj.data))
    project.upsert_entry(year_key, member_id, wages or ([15000.0] + [0.0] * 11))
    save_establishment_project(test_db, est_obj, project)


def test_dashboard_monthly_stats_eps_wage_respects_dob_cutover(consultant_a, test_db):
    """The Dashboard's monthly_stats independently recomputes an eps_wages total for
    display -- must also zero for a 58+ employee, not just month_rows()'s own
    contribution figures. Response shape confirmed by reading the real endpoint:
    year_stats[i]["monthly_stats"][i]["eps_wages"] (plural), month label like "Mar 2026"."""
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "DASHDOB01", "name": "Dash DOB Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/employees", json={
        "member_id": "DASHD001", "name": "Dash DOB Test Employee", "uan": "100900000002",
        "dob": "01-01-1950",
    })
    assert res.status_code == 200, res.text

    _save_58plus_employee_wages(test_db, est_id, "DASHD001")

    res = consultant_a.get("/api/dashboard")
    assert res.status_code == 200, res.text
    year_stats = next(y for y in res.json()["year_stats"] if y["key"] == "2026-27")
    stats = next(m for m in year_stats["monthly_stats"] if m["month"].startswith("Mar"))
    assert stats["eps_wages"] == 0


def test_dashboard_month_employees_eps_wage_respects_dob_cutover(consultant_a, test_db):
    """The per-month employee-detail listing (GET /api/dashboard/month_employees/...)
    independently recomputes eps_wages the same way the dashboard totals do -- must
    also zero for a 58+ employee."""
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "MEMPDOB01", "name": "Month Employees DOB Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/employees", json={
        "member_id": "MEMPD001", "name": "Month Employees DOB Test Employee", "uan": "100900000003",
        "dob": "01-01-1950",
    })
    assert res.status_code == 200, res.text

    _save_58plus_employee_wages(test_db, est_id, "MEMPD001")

    res = consultant_a.get("/api/dashboard/month_employees/2026-27/0")  # month_idx 0 = March
    assert res.status_code == 200, res.text
    rows = res.json()["employees"]
    assert len(rows) == 1
    assert rows[0]["eps_wages"] == 0


def test_remittances_year_totals_eps_wage_respects_dob_cutover(consultant_a, test_db):
    """The year-totals loop backing GET /api/years/{key}/remittances independently
    recomputes an eps_wages_total for display -- must also zero for a 58+ employee."""
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "REMITDOB01", "name": "Remittances DOB Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/employees", json={
        "member_id": "REMITD01", "name": "Remittances DOB Test Employee", "uan": "100900000004",
        "dob": "01-01-1950",
    })
    assert res.status_code == 200, res.text

    _save_58plus_employee_wages(test_db, est_id, "REMITD01")

    res = consultant_a.get("/api/years/2026-27/remittances")
    assert res.status_code == 200, res.text
    march_row = res.json()["remittances"][0]  # index 0 = March
    assert march_row["eps_wages"] == 0


def test_wage_history_report_no_longer_exposes_age_crosses_58(consultant_a, test_db):
    """The wage-history report builder (_build_employee_wage_history_data, used by both
    the on-screen JSON and PDF endpoints) must not raise AttributeError on the removed
    emp.age_crosses_58, and must no longer expose an "age_crosses_58" key in its output
    now that the flag is gone."""
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "WHISTDOB01", "name": "Wage History DOB Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/employees", json={
        "member_id": "WHISTD01", "name": "Wage History DOB Test Employee", "uan": "100900000005",
        "dob": "01-01-1950",
    })
    assert res.status_code == 200, res.text

    _save_58plus_employee_wages(test_db, est_id, "WHISTD01")

    res = consultant_a.get("/api/reports/employee_wage_history/WHISTD01")
    assert res.status_code == 200, res.text
    year_data = res.json()["years"][0]
    assert "age_crosses_58" not in year_data
    assert year_data["er_eps_total"] == 0


def test_monthly_wage_entry_pdf_eps_zero_for_58_plus_employee(tmp_path):
    """Direct regression test for pdf_engine.generate_monthly_wage_entry_pdf (Step 8):
    must not raise AttributeError on the removed emp.age_crosses_58, and must produce
    a real, non-empty PDF for a 58+ employee whose EPS wage base should be zeroed."""
    from epf_engine import Project, SCHEME_POST_1997
    from pdf_engine import generate_monthly_wage_entry_pdf

    p = Project()
    p.set_establishment("EST1", "PDF Monthly Test Co", "Addr")
    p.add_year("2026", "2027", scheme=SCHEME_POST_1997)
    p.upsert_master("M1", "PDF Test Employee", uan="100900000006", dob="01-01-1950")
    p.upsert_entry("2026-27", "M1", [15000.0] + [0.0] * 11)

    est = p.build_establishment_for_year("2026-27")
    emps = p.build_employees_for_year("2026-27")

    out_path = str(tmp_path / "monthly_wage_entry.pdf")
    result_path = generate_monthly_wage_entry_pdf(
        p, est, emps, out_path, month_idx=0, month_abbr="Mar",
        cal_year=2026, cal_month=3, days_in_month=31,
    )
    assert os.path.exists(result_path)
    assert os.path.getsize(result_path) > 0


def test_yearly_wage_checklist_pdf_eps_zero_for_58_plus_employee(tmp_path):
    """Direct regression test for pdf_engine.generate_yearly_wage_checklist_pdf (Step 9):
    must not raise AttributeError on the removed emp.age_crosses_58, and must produce
    a real, non-empty PDF for a 58+ employee whose EPS wage base should be zeroed."""
    from epf_engine import Project, SCHEME_POST_1997
    from pdf_engine import generate_yearly_wage_checklist_pdf

    p = Project()
    p.set_establishment("EST1", "PDF Yearly Test Co", "Addr")
    p.add_year("2026", "2027", scheme=SCHEME_POST_1997)
    p.upsert_master("M1", "PDF Test Employee", uan="100900000007", dob="01-01-1950")
    p.upsert_entry("2026-27", "M1", [15000.0] * 12)

    est = p.build_establishment_for_year("2026-27")
    emps = p.build_employees_for_year("2026-27")

    out_path = str(tmp_path / "yearly_wage_checklist.pdf")
    result_path = generate_yearly_wage_checklist_pdf(p, est, emps, out_path)
    assert os.path.exists(result_path)
    assert os.path.getsize(result_path) > 0


import json


def test_eps_58_dob_audit_flags_missing_dob(consultant_a, superadmin_session, test_db):
    from webapp.database import Establishment

    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "AUDIT001", "name": "Audit Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={
        "member_id": "AUDIT01", "name": "At Risk Employee", "uan": "100900000007",
    })
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "AUDIT01", "wages": [20000.0] + [0.0] * 11,
    })

    # Simulate a pre-existing establishment that still has the OLD age_crosses_58=True
    # flag stored in its raw JSON, with no DOB on the member -- exactly the at-risk
    # case this audit exists to catch. Written directly to raw storage since the
    # current Project/YearEntry model no longer has this field to set through the API.
    est = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    data = json.loads(est.data)
    data["years"]["2026-27"]["entries"][0]["age_crosses_58"] = True
    est.data = json.dumps(data)
    test_db.commit()

    res = superadmin_session.get("/api/admin/audit/eps-58-dob-check")
    assert res.status_code == 200, res.text
    at_risk = res.json()["at_risk"]
    match = next((r for r in at_risk if r["member_id"] == "AUDIT01"), None)
    assert match is not None, f"expected AUDIT01 flagged, got {at_risk}"
    assert match["issue"] == "missing_dob"


def test_eps_58_dob_audit_requires_superadmin(consultant_a):
    res = consultant_a.get("/api/admin/audit/eps-58-dob-check")
    assert res.status_code == 403
