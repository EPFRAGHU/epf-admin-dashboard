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


def test_create_first_year_must_match_coverage_year(consultant_a):
    _create_est(consultant_a, "GATEYR001", coverage_date="01-04-2026")
    res = consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})
    assert res.status_code == 400
    assert "2026-27" in res.text


def test_create_first_year_matching_coverage_year_succeeds(consultant_a):
    _create_est(consultant_a, "GATEYR002", coverage_date="01-04-2026")
    res = consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res.status_code == 200, res.text


def test_cannot_create_second_year_before_first_is_fully_paid(consultant_a):
    _create_est(consultant_a, "GATEYR003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})
    assert res.status_code == 400
    assert "2026-27" in res.text


def test_superadmin_bypasses_chronological_year_order(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "GATEYR004", coverage_date="01-04-2026")
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post("/api/years", json={"year_from": "2030", "year_to": "2031"})
    assert res.status_code == 200, res.text


def test_first_year_creation_logs_activity_entry(consultant_a, test_db):
    from webapp.database import ActivityLog
    est_id = _create_est(consultant_a, "GATEYR005", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    entry = test_db.query(ActivityLog).filter(
        ActivityLog.establishment_id == est_id, ActivityLog.action_type == "entry_gating_started"
    ).first()
    assert entry is not None
    assert "2026-27" in entry.description


def test_second_year_creation_does_not_log_a_second_start_entry(consultant_a, test_db):
    from webapp.database import ActivityLog, SubscriptionFee
    est_id = _create_est(consultant_a, "GATEYR006", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    # Pay every month of 2026-27 so the second year is allowed to be created.
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()
    consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})

    count = test_db.query(ActivityLog).filter(
        ActivityLog.establishment_id == est_id, ActivityLog.action_type == "entry_gating_started"
    ).count()
    assert count == 1


def test_consultant_cannot_bulk_create_years(consultant_a):
    _create_est(consultant_a, "GATEBULK001", coverage_date="01-04-2026")
    res = consultant_a.post("/api/years/bulk", json={"start_year": 2020, "end_year": 2026})
    assert res.status_code == 403


def test_superadmin_can_still_bulk_create_years(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "GATEBULK002", coverage_date="01-04-1990")
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post("/api/years/bulk", json={"start_year": 1990, "end_year": 1995})
    assert res.status_code == 200, res.text
    assert res.json()["added"] == 6


def test_cannot_save_second_month_wages_before_first_month_is_paid(consultant_a):
    _create_est(consultant_a, "GATEWAGE001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000003"})
    res1 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res1.status_code == 200, res1.text

    res2 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 1, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res2.status_code == 409
    assert "Mar" in res2.text


def test_re_saving_an_already_entered_month_is_never_blocked(consultant_a):
    """Grandfathering: editing a month that already has data must always be allowed,
    even though it isn't paid yet."""
    _create_est(consultant_a, "GATEWAGE002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000004"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 16000, "epf_wage": 16000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text


def test_month_unlocks_once_previous_month_paid(consultant_a, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATEWAGE003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000005"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    fee.is_paid = True
    test_db.commit()

    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 1, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text


def test_superadmin_bypasses_monthly_wage_entry_gating(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "GATEWAGE004", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000006"})
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text
