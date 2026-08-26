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


def test_re_saving_an_already_entered_month_is_never_blocked(consultant_a, superadmin_session):
    """Grandfathering: editing a month that already has data must always be allowed,
    even though it isn't paid yet -- and specifically when that month is PAST the
    current lock boundary, not just the still-open frontier month. (Resaving the
    frontier month itself -- the last contiguously-entered month -- would return 200
    even without any grandfathering check, since the lock boundary always sits at or
    after the frontier by the walk's own construction; that wouldn't prove anything.)
    Mar is entered+left unpaid by consultant_a, which locks Apr (month_idx 1) onward.
    Superadmin then bypasses the lock to seed Jun (month_idx 3) with data. A regular
    consultant re-saving Jun -- which is past the lock boundary and still unpaid --
    must still succeed; without the grandfathering skip this would be a 409 (3 >= 1)."""
    est_id = _create_est(consultant_a, "GATEWAGE002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000004"})
    res0 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res0.status_code == 200, res0.text

    superadmin_session.set_establishment(est_id)
    res_seed = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 3, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res_seed.status_code == 200, res_seed.text

    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 3, "employees": [{"member_id": "M1", "gross_wage": 16000, "epf_wage": 16000, "ncp_days": 0}]
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
    """Establish a REAL active lock first (Mar entered+unpaid locks Apr onward for a
    regular consultant), then have superadmin save into a month at/after that lock
    boundary. Without the superadmin bypass this would be a 409 (5 >= 1); saving into
    an untouched establishment with nothing locked yet (as the original version of this
    test did) wouldn't distinguish the bypass from "there was nothing to block"."""
    est_id = _create_est(consultant_a, "GATEWAGE004", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000006"})
    res0 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res0.status_code == 200, res0.text

    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text


def test_entry_lock_status_endpoint_reports_current_boundary(consultant_a):
    _create_est(consultant_a, "GATESTATUS001", coverage_date="01-04-2026")
    res = consultant_a.get("/api/establishment/entry-lock-status")
    assert res.status_code == 200
    body = res.json()
    assert body["coverage_year_key"] == "2026-27"
    assert body["next_year_to_add"] == "2026-27"
    assert body["locked_month"] is None


def test_constants_endpoint_includes_short_month_names(client):
    res = client.get("/api/constants")
    assert res.status_code == 200
    body = res.json()
    assert body["month_short_names"] == ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
    # The existing long-form labels must be untouched -- other pages (ECR, remittances) rely on them.
    assert body["months"][0] == "Mar Paid in Apr"


# ── Finding 1: the entry gate must never payment-lock a trial establishment ────────

def test_trial_establishment_is_never_locked_pending_payment(consultant_a, superadmin_session):
    """Previously get_entry_lock_status never checked is_establishment_in_trial, unlike
    every other payment gate in the app. A brand-new trial establishment could enter its
    first month fine, but then got permanently blocked entering month 2 even though it's
    still within its free trial -- the opposite of what a trial should do."""
    est_id = _create_est(consultant_a, "GATETRIAL001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000010"})
    res0 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res0.status_code == 200, res0.text
    # Mar is entered and left unpaid -- outside of a trial this would lock Apr onward.

    superadmin_session.set_establishment(est_id)
    res_trial = superadmin_session.put(f"/api/admin/establishments/{est_id}/trial", json={"trial_ends_on": "2099-12-31"})
    assert res_trial.status_code == 200, res_trial.text

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["locked_month"] is None
    finally:
        db.close()

    res1 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 1, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res1.status_code == 200, res1.text


def test_trial_status_does_not_break_chronological_year_add_ordering(consultant_a, superadmin_session):
    """A trial establishment's payment-lock relief must not accidentally disable the
    (unrelated, non-payment) chronological year-add ordering check in add_year -- that
    check is driven by next_year_to_add, which must still reflect the real walk result
    even while the establishment is in trial."""
    est_id = _create_est(consultant_a, "GATETRIAL002", coverage_date="01-04-2026")
    superadmin_session.set_establishment(est_id)
    res_trial = superadmin_session.put(f"/api/admin/establishments/{est_id}/trial", json={"trial_ends_on": "2099-12-31"})
    assert res_trial.status_code == 200, res_trial.text

    res = consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res.status_code == 200, res.text


# ── Finding 2: the wage-save gate must be chronological across years, not just within
#    the exact locked year_key ──────────────────────────────────────────────────────

def test_wage_save_gate_blocks_later_years_when_earlier_year_is_locked(consultant_a, superadmin_session):
    """A later financial year must be gated by an earlier, still-locked year -- not just
    the exact locked year_key. Superadmin's bulk-create (seeding backfill ranges) can
    leave many years existing at once; the gate previously only compared
    key == lock['year_key'], so month saves into any LATER year sailed through even
    while an earlier year sat locked and unpaid."""
    est_id = _create_est(consultant_a, "GATECHRON001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000020"})
    res0 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res0.status_code == 200, res0.text
    # Mar 2026-27 is unpaid -- this locks Apr 2026-27 onward chronologically.

    superadmin_session.set_establishment(est_id)
    res_bulk = superadmin_session.post("/api/years/bulk", json={"start_year": 2026, "end_year": 2028})
    assert res_bulk.status_code == 200, res_bulk.text

    # The consultant tries to save month 0 (Mar) of the LATER year 2027-28. That year
    # didn't even exist when the lock was computed, but chronologically it is well past
    # the still-unpaid 2026-27/Apr boundary and must be blocked too.
    res = consultant_a.post("/api/years/2027-28/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 409, res.text


# ── Finding 4: the older whole-year wages endpoint must not be usable to smuggle data
#    past the entry lock ────────────────────────────────────────────────────────────

def test_legacy_wage_endpoint_cannot_smuggle_data_past_the_entry_lock(consultant_a):
    """POST /api/years/{key}/wages (the older, ungated 12-month-at-once endpoint used by
    the plain Wage Entry page, distinct from bulk_month_wages) must not be usable to
    write data into a genuinely-new month at or after the current entry-lock boundary --
    that would silently satisfy get_entry_lock_status's has_data check for that month and
    clear locked_month back to None, unlocking bulk_month_wages for months nothing was
    ever paid for."""
    est_id = _create_est(consultant_a, "GATELEGACY001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000030"})
    res0 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res0.status_code == 200, res0.text
    # Mar unpaid -- Apr (month_idx 1) onward is now locked.

    wages = [0] * 12
    wages[1] = 15000  # Apr -- genuinely new, at/after the lock boundary
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "M1", "wages": wages, "gross_wages": wages
    })
    assert res.status_code in (400, 409), res.text

    # And it must not have leaked past the lock via the write that was rejected.
    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["locked_month"] == {"year_key": "2026-27", "month_idx": 1, "month_abbr": "Apr"}
    finally:
        db.close()


def test_legacy_wage_endpoint_still_allows_edits_to_already_entered_months(consultant_a):
    """The stopgap guard must not over-block: editing a month that already has data
    (Mar, already entered above) must remain allowed through this endpoint exactly as
    before, even though it's unpaid."""
    est_id = _create_est(consultant_a, "GATELEGACY002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000031"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    wages = [0] * 12
    wages[0] = 16000  # editing Mar, which already has data -- must remain allowed
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "M1", "wages": wages, "gross_wages": wages
    })
    assert res.status_code == 200, res.text


def test_legacy_wage_endpoint_allows_writes_before_the_lock_boundary(consultant_a, superadmin_session):
    """Writing a genuinely-new month that is chronologically BEFORE the current lock
    boundary (e.g. a superadmin-seeded historical backfill year) must remain unaffected
    by the stopgap guard -- it only targets months at or after the lock."""
    est_id = _create_est(consultant_a, "GATELEGACY003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000032"})
    res0 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res0.status_code == 200, res0.text
    # Mar unpaid -- Apr (month_idx 1) 2026-27 onward is now locked.

    superadmin_session.set_establishment(est_id)
    res_bulk = superadmin_session.post("/api/years/bulk", json={"start_year": 2020, "end_year": 2025})
    assert res_bulk.status_code == 200, res_bulk.text

    # 2020-21 is chronologically well before the 2026-27/Apr lock boundary -- a
    # superadmin-seeded historical backfill year must remain freely writable through
    # this endpoint.
    wages = [0] * 12
    wages[0] = 12000
    res = consultant_a.post("/api/years/2020-21/wages", json={
        "member_id": "M1", "wages": wages, "gross_wages": wages
    })
    assert res.status_code == 200, res.text
