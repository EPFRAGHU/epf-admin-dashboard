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


from webapp.database import SessionLocal
from webapp.app import get_entry_lock_status


def _create_est(consultant, code, coverage_date="01-04-2026"):
    res = consultant.post("/api/establishments", json={
        "coverage_date": coverage_date, "code": code, "name": f"{code} Co"
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def _load_est_and_project(est_id):
    """Replicates the small inline load done by get_active_establishment() in
    webapp/auth.py (that function is a FastAPI dependency wired to Request/
    current_user, not a plain callable a test can invoke directly)."""
    import json
    from webapp.database import Establishment
    from epf_engine import Project
    db = SessionLocal()
    est_obj = db.query(Establishment).filter(Establishment.id == est_id).first()
    project = Project()
    if est_obj.data:
        project.load_from_dict(json.loads(est_obj.data))
    else:
        project.set_establishment(est_obj.code, est_obj.name, est_obj.address or "", est_obj.coverage_date or "")
    return db, est_obj, project


def test_lock_status_reports_coverage_year_as_next_year_to_add_when_no_years_exist(consultant_a):
    est_id = _create_est(consultant_a, "GATE001", coverage_date="01-04-2026")
    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["coverage_year_key"] == "2026-27"
        assert status["next_year_to_add"] == "2026-27"
        assert status["locked_month"] is None
    finally:
        db.close()


def test_lock_status_locks_second_month_until_first_is_paid(consultant_a):
    est_id = _create_est(consultant_a, "GATE002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000001"})
    # Mar (month_idx 0) gets wage data but is never paid.
    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["next_year_to_add"] is None
        assert status["locked_month"] == {"year_key": "2026-27", "month_idx": 1, "month_abbr": "Apr"}
    finally:
        db.close()


def test_lock_status_unlocks_second_month_once_first_is_paid(consultant_a, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATE003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000002"})
    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    fee.is_paid = True
    test_db.commit()

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["locked_month"] is None
    finally:
        db.close()
