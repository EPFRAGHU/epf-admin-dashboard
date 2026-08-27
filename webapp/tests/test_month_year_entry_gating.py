"""Coverage for chronological month/year entry gating: a consultant/employer can only
enter wage data one month at a time, anchored to the establishment's coverage_date,
each unlocking only once the previous one is paid. See
docs/superpowers/specs/2026-08-26-month-year-entry-gating-design.md."""
from webapp.app import get_financial_year_key_for_date, get_coverage_year_key
from epf_engine import Project, normalize_member_id


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


def test_year_record_added_at_is_stamped_on_creation():
    from epf_engine import Project as _P
    from datetime import datetime as _dt
    p = _P()
    p.coverage_date = "01-04-2020"
    p.add_year("2020", "2021")
    added_at = p.years["2020-21"].added_at
    assert added_at
    _dt.fromisoformat(added_at)  # must not raise


def test_year_record_added_at_reflects_real_add_order_not_fy_order():
    """added_at must track when a year was actually added, not its financial-year
    order -- years can now be added out of order (backfill or forward-fill), so
    financial-year order can no longer be used to find "the most recently added
    year"."""
    from epf_engine import Project as _P
    p = _P()
    p.coverage_date = "01-04-2020"
    p.add_year("2025", "2026")  # added first, even though FY-later
    p.add_year("2020", "2021")  # added second, even though FY-earlier
    assert p.years["2020-21"].added_at > p.years["2025-26"].added_at


def test_year_record_from_dict_synthesizes_added_at_when_missing():
    """Establishments serialized before this change have no added_at in their JSON
    blob. Every one of their pre-existing years was necessarily added in strict
    chronological order under the old gate, so from_dict must reconstruct that
    relative order (via the year's own FY start) rather than leaving it blank --
    otherwise a legacy establishment's "most recently added year" would be
    undefined the first time it's loaded after this change ships."""
    from epf_engine import YearRecord
    d = {"year_from": "2020", "year_to": "2021", "entries": [], "remittances": []}
    yr = YearRecord.from_dict(d)
    assert yr.added_at == "2020-04-01T00:00:00"


def test_year_record_from_dict_preserves_real_added_at_when_present():
    from epf_engine import YearRecord
    d = {"year_from": "2020", "year_to": "2021", "added_at": "2026-08-27T10:00:00.123456",
         "entries": [], "remittances": []}
    yr = YearRecord.from_dict(d)
    assert yr.added_at == "2026-08-27T10:00:00.123456"


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
    assert body["can_add_year"] is True
    assert body["blocking_year"] is None


def test_lock_status_blocking_year_is_none_when_only_year_is_fully_paid(consultant_a, superadmin_session, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATESTATUS002", coverage_date="01-04-2026")
    superadmin_session.set_establishment(est_id)
    superadmin_session.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["can_add_year"] is True
        assert status["blocking_year"] is None
    finally:
        db.close()


def test_lock_status_blocking_year_reports_the_most_recently_added_unpaid_year(consultant_a, superadmin_session):
    est_id = _create_est(consultant_a, "GATESTATUS003", coverage_date="01-04-2026")
    superadmin_session.set_establishment(est_id)
    superadmin_session.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000060"})
    res = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text
    # Mar 2026-27 has wage data and is unpaid -- this is the only (and therefore most
    # recently added) year, so it must block.

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["can_add_year"] is False
        assert status["blocking_year"]["year_key"] == "2026-27"
        assert status["blocking_year"]["amount_due"] > 0
    finally:
        db.close()


def test_lock_status_ignores_older_years_and_only_checks_the_most_recently_added_one(consultant_a, superadmin_session, test_db):
    """A year added earlier being unpaid must NOT block further additions once a LATER-
    added year (even if it's chronologically earlier as a financial year) is fully
    paid -- only the most-recently-ADDED year matters."""
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATESTATUS004", coverage_date="01-04-2020")
    superadmin_session.set_establishment(est_id)
    # Superadmin backfills 2020-21 (added first) and leaves it with no fee rows at all
    # (nothing billed, nothing paid) -- irrelevant, since it won't be "most recent".
    res1 = superadmin_session.post("/api/years", json={"year_from": "2020", "year_to": "2021"})
    assert res1.status_code == 200, res1.text

    # 2026-27 is added SECOND (even though it's a later FY) and paid in full. Seeded via
    # superadmin (same as 2020-21 above) purely to sidestep add_year's/bulk_month_wages's
    # non-superadmin gating -- not yet updated to the new get_entry_lock_status contract
    # until Tasks 3/4 land; this test is only about get_entry_lock_status itself.
    res2 = superadmin_session.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res2.status_code == 200, res2.text
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["can_add_year"] is True
        assert status["blocking_year"] is None
    finally:
        db.close()


def test_lock_status_can_add_year_true_when_no_years_exist_yet(consultant_a):
    est_id = _create_est(consultant_a, "GATESTATUS005", coverage_date="01-04-2026")
    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["coverage_year_key"] == "2026-27"
        assert status["can_add_year"] is True
        assert status["blocking_year"] is None
    finally:
        db.close()


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
        assert status["locked_month"] == {"year_key": "2026-27", "month_idx": 1, "month_abbr": "Apr", "reason": "unpaid"}
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


# ── Calendar ceiling: a month can never be entered until it has actually ended ──
# "If the current month is August 2026, wage entry is allowed up to July 2026
# only -- in no circumstances the current or a subsequent month, since August is
# the due month FOR July. On 01-09-2026, August itself becomes enterable."
from datetime import date as _real_date
from unittest.mock import patch
from webapp.app import get_current_wage_month, get_max_enterable_month, get_entry_lock_status


class _FrozenDate(_real_date):
    """Subclassing (not MagicMock-ing) date preserves real date(y,m,d) construction
    everywhere else in app.py (calendar_year_for_month, is_month_overdue, ...) while
    only date.today() is frozen."""
    _frozen = _real_date(2026, 8, 26)

    @classmethod
    def today(cls):
        return cls._frozen


def test_get_current_wage_month_matches_mar_feb_layout():
    with patch("webapp.app.date", _FrozenDate):
        assert get_current_wage_month() == ("2026-27", 5)  # Aug -> month_idx 5


def test_get_max_enterable_month_is_the_previous_month():
    with patch("webapp.app.date", _FrozenDate):
        assert get_max_enterable_month() == ("2026-27", 4)  # Jul -> month_idx 4


def test_get_max_enterable_month_wraps_to_prior_fy_feb_in_march():
    class _MarchDate(_real_date):
        @classmethod
        def today(cls):
            return _real_date(2026, 3, 15)
    with patch("webapp.app.date", _MarchDate):
        assert get_max_enterable_month() == ("2025-26", 11)  # Feb of the prior FY


def _enter_and_pay_month(consultant_a, test_db, est_id, key, month_idx, month_abbr, member_id="M1"):
    res = consultant_a.post(f"/api/years/{key}/wages/bulk_month", json={
        "month_idx": month_idx, "employees": [{"member_id": member_id, "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text
    from webapp.database import SubscriptionFee
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id,
        SubscriptionFee.financial_year == key,
        SubscriptionFee.month == month_abbr
    ).first()
    fee.is_paid = True
    test_db.commit()


def test_cannot_save_current_month_wages_even_fully_paid_through_previous(consultant_a, test_db):
    est_id = _create_est(consultant_a, "CEIL002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000041"})

    with patch("webapp.app.date", _FrozenDate):
        for m_idx, m_abbr in enumerate(["Mar", "Apr", "May", "Jun", "Jul"]):
            _enter_and_pay_month(consultant_a, test_db, est_id, "2026-27", m_idx, m_abbr)

        res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res.status_code == 409
        assert "opens on 01-09-2026" in res.text


def test_can_save_the_last_fully_ended_month(consultant_a, test_db):
    est_id = _create_est(consultant_a, "CEIL003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000042"})

    with patch("webapp.app.date", _FrozenDate):
        for m_idx, m_abbr in enumerate(["Mar", "Apr", "May", "Jun"]):
            _enter_and_pay_month(consultant_a, test_db, est_id, "2026-27", m_idx, m_abbr)

        # Jul (month_idx 4) is the last month that has actually ended -- must be enterable.
        res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 4, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res.status_code == 200, res.text


def test_trial_establishment_still_bound_by_calendar_ceiling(superadmin_session, consultant_a, test_db):
    """Trial exemption relaxes PAYMENT, never the calendar ceiling -- a month that
    hasn't ended yet can't be entered no matter how generous the billing terms are."""
    from webapp.database import Establishment
    from datetime import timedelta
    est_id = _create_est(consultant_a, "CEIL004", coverage_date="01-04-2026")
    est_row = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    est_row.trial_ends_on = _FrozenDate._frozen + timedelta(days=30)
    test_db.commit()
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000043"})

    with patch("webapp.app.date", _FrozenDate):
        # Trial exempts payment, so these all succeed unpaid -- filling Mar..Jul makes
        # Aug (month_idx 5) itself the next_open_month, isolating the calendar-ceiling
        # check from the (separate) skip-ahead check.
        for m_idx in range(5):
            res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
                "month_idx": m_idx, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
            })
            assert res.status_code == 200, res.text

        res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res.status_code == 409
        assert "opens on" in res.text


def test_superadmin_bypasses_calendar_ceiling(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "CEIL005", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000044"})
    superadmin_session.set_establishment(est_id)

    with patch("webapp.app.date", _FrozenDate):
        res = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res.status_code == 200, res.text


# ── Download gate: no grace period -- any unpaid month with data blocks immediately ──
#
# These specifically target a month that the OLD is_month_overdue() grace logic would
# NOT yet consider overdue (still within its "1 day past month-end" window, or not even
# ended yet) -- proving the new no-grace policy, not just re-confirming an already-
# elapsed grace period that the real calendar date would trigger regardless. Wage data
# for the current month is seeded via superadmin (bypasses entry-gating, which is a
# separate concern from the download gate under test here).

def test_ecr_download_blocked_immediately_for_current_unpaid_month_no_grace(superadmin_session, consultant_a):
    """Before this change, is_month_overdue() gave a 1-day-past-month-end grace window
    before a download was blocked. Policy change: every download requires payment
    upfront, even for the current, still-in-progress month."""
    est_id = _create_est(consultant_a, "NOGRACE001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000045"})
    superadmin_session.set_establishment(est_id)

    with patch("webapp.app.date", _FrozenDate):
        # Aug 2026 (month_idx 5) is TODAY's own in-progress month under the frozen
        # date -- old grace logic wouldn't consider it overdue until 01-09-2026.
        res_seed = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res_seed.status_code == 200, res_seed.text

        res = consultant_a.get("/api/reports/2026-27/ecr/5")
        assert res.status_code == 402
        assert "unpaid" in res.text.lower()


def test_whole_year_form_download_blocked_immediately_no_grace(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "NOGRACE002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000046"})
    superadmin_session.set_establishment(est_id)

    with patch("webapp.app.date", _FrozenDate):
        res_seed = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res_seed.status_code == 200, res_seed.text

        res = consultant_a.get("/api/reports/2026-27")
        assert res.status_code == 402


def test_download_unlocks_immediately_once_paid(superadmin_session, consultant_a, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "NOGRACE003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000047"})
    superadmin_session.set_establishment(est_id)

    with patch("webapp.app.date", _FrozenDate):
        res_seed = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res_seed.status_code == 200, res_seed.text

        fee = test_db.query(SubscriptionFee).filter(SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Aug").first()
        fee.is_paid = True
        test_db.commit()

        res = consultant_a.get("/api/reports/2026-27/ecr/5")
        assert res.status_code == 200


def test_superadmin_bypasses_no_grace_download_gate(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "NOGRACE004", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000048"})
    superadmin_session.set_establishment(est_id)

    with patch("webapp.app.date", _FrozenDate):
        res_seed = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
            "month_idx": 5, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
        })
        assert res_seed.status_code == 200, res_seed.text

        res = superadmin_session.get("/api/reports/2026-27/ecr/5")
        assert res.status_code == 200


# ── Regression: bulk_month_wages must not wipe a prior month's wages for a member_id
# longer than 7 characters (found while writing the calendar-ceiling tests above) ──

def test_entering_a_later_month_does_not_wipe_an_earlier_months_wages_for_long_member_id(consultant_a, test_db):
    """upsert_entry() (epf_engine.py) stores/looks up entries by normalize_member_id()
    (last 7 chars), not the raw id. bulk_month_wages's own existing-entry lookup used to
    compare against the RAW member_id -- for any id longer than 7 characters that lookup
    always missed, so it rebuilt wages_arr from all zeros and set only the new month,
    which upsert_entry then saved over the real entry (matched by normalized id),
    silently erasing every previously-entered month. Real member ids in production are
    routinely longer than 7 characters (e.g. "DELTA001001"), so this was a live
    data-loss bug, not a hypothetical one."""
    est_id = _create_est(consultant_a, "LONGID001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    long_id = "DELTA001001"  # 11 chars -- longer than normalize_member_id's 7-char keep
    consultant_a.post("/api/employees", json={"member_id": long_id, "name": "Emp One", "uan": "100000000050"})

    res_mar = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": long_id, "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res_mar.status_code == 200, res_mar.text

    from webapp.database import SubscriptionFee
    fee = test_db.query(SubscriptionFee).filter(SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar").first()
    fee.is_paid = True
    test_db.commit()

    res_apr = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 1, "employees": [{"member_id": long_id, "gross_wage": 18000, "epf_wage": 18000, "ncp_days": 0}]
    })
    assert res_apr.status_code == 200, res_apr.text

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        entry = next(e for e in project.years["2026-27"].entries if e.member_id == normalize_member_id(long_id))
        assert entry.wages[0] == 15000, "Mar's wage must survive Apr being entered afterward"
        assert entry.wages[1] == 18000
    finally:
        db.close()

