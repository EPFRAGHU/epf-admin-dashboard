"""
Consultant Monthly Plan -- fee waiver in billing sync
=====================================================
While a consultant's paid plan window covers the current IST month, every
establishment fee row with wage data (new, previously unpaid, or a former 0-due
placeholder) is waived: paid, amount 0, billing_mode 'consultant_plan'. Paid rows are never
rewritten, a lapsed plan claws nothing back, and consultants without an active plan are
billed exactly as before.
"""

import pytest

from webapp.app import PLAN_COVERED_REFERENCE, _confirm_plan_payment
from webapp.consultant_plan import current_month_ist
from webapp.database import ConsultantPlanPayment, SubscriptionFee, User

YEAR = "2026-27"


@pytest.fixture(autouse=True)
def _isolate_plan_state(test_db):
    """The test DB is shared across the whole session and consultant_a/b are reused by other
    modules, so plan state must never leak in or out of these tests."""
    def wipe():
        test_db.rollback()
        for email in ("consultant_a@testepf.com", "consultant_b@testepf.com"):
            u = test_db.query(User).filter(User.email == email).first()
            if u:
                u.consultant_plan_amount = None
                test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.user_id == u.id).delete()
        test_db.commit()
    wipe()
    yield
    wipe()


def _activate_plan(test_db, user_id, amount=500.0, months=1):
    """Give the user a plan amount and a manual-confirmed window starting this IST month."""
    user = test_db.query(User).filter(User.id == user_id).first()
    user.consultant_plan_amount = amount
    row = ConsultantPlanPayment(user_id=user_id, months=months, amount=amount * months, status="pending")
    test_db.add(row)
    test_db.commit()
    _confirm_plan_payment(test_db, row, "TEST/PLAN", source="manual")
    test_db.refresh(row)
    assert row.status == "manual" and row.covered_from == current_month_ist()
    return row


def _code_digits(code):
    """Deterministic 6-digit number derived from an establishment code (position-weighted
    sum of ord values, so CPB001/CPB010 differ), used to build unique 12-digit UANs."""
    return sum((i + 1) * ord(ch) for i, ch in enumerate(code)) % 10**6


def _make_est(consultant, code, rate=10.0, wage_months=1, employees=1, seed_wages=True):
    """Create an establishment with one financial year; wage data for the first
    `wage_months` months (Mar, Apr, ...) for each employee."""
    res = consultant.post("/api/establishments", json={
        "coverage_date": "01-04-2026", "code": code, "name": f"{code} Ltd", "custom_rate_per_employee": rate
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    assert consultant.post("/api/years", json={"year_from": "2026", "year_to": "2027"}).status_code == 200
    for i in range(1, employees + 1):
        res = consultant.post("/api/employees", json={
            "member_id": f"{code}{i:03d}", "name": f"Employee {i}", "uan": f"81{_code_digits(code):06d}{i:04d}"
        })
        assert res.status_code == 200, res.text
    if seed_wages:
        _enter_wages(consultant, code, employees, wage_months)
    return est_id


def _enter_wages(consultant, code, employees, wage_months):
    for i in range(1, employees + 1):
        res = consultant.post(f"/api/years/{YEAR}/wages", json={
            "member_id": f"{code}{i:03d}", "wages": [15000.0] * wage_months + [0.0] * (12 - wage_months)
        })
        assert res.status_code == 200, res.text


def _fees(superadmin_session, est_id):
    res = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year={YEAR}")
    assert res.status_code == 200, res.text
    return {m["month"]: m for m in res.json()["months"]}


def test_no_plan_billing_unchanged(superadmin_session, consultant_a):
    est_id = _make_est(consultant_a, "CPB001")
    mar = _fees(superadmin_session, est_id)["Mar"]
    assert mar["is_paid"] is False
    assert mar["amount_due"] == 10.0
    assert mar["billing_mode"] == "per_employee"
    assert mar["payment_reference"] == ""


def test_active_plan_waives_wage_rows_across_two_establishments(superadmin_session, consultant_a, test_db):
    _activate_plan(test_db, consultant_a.user_id)
    est1 = _make_est(consultant_a, "CPB002")
    est2 = _make_est(consultant_a, "CPB003", rate=20.0, employees=2)

    for est_id, count in ((est1, 1), (est2, 2)):
        mar = _fees(superadmin_session, est_id)["Mar"]
        assert mar["employee_count"] == count
        assert mar["is_paid"] is True
        assert mar["amount_due"] == 0
        assert mar["billing_mode"] == "consultant_plan"
        assert mar["payment_reference"] == PLAN_COVERED_REFERENCE
        assert mar["paid_date"]

    # Consultant downloads are unlocked for both establishments (would be 402 if unpaid).
    for est_id in (est1, est2):
        consultant_a.set_establishment(est_id)
        assert consultant_a.get(f"/api/reports/{YEAR}/ecr/0").status_code == 200
        assert consultant_a.get(f"/api/reports/{YEAR}").status_code == 200


def test_rows_without_wages_not_waived(superadmin_session, consultant_a, test_db):
    _activate_plan(test_db, consultant_a.user_id)
    est_id = _make_est(consultant_a, "CPB004")
    months = _fees(superadmin_session, est_id)
    assert months["Mar"]["billing_mode"] == "consultant_plan"
    may = months["May"]
    assert may["employee_count"] == 0
    assert may["is_paid"] is False
    assert may["amount_due"] == 0
    assert may["billing_mode"] != "consultant_plan"
    assert may["payment_reference"] == ""


def test_previously_unpaid_rows_waived_on_next_sync(superadmin_session, consultant_a, test_db):
    est_id = _make_est(consultant_a, "CPB005")
    before = _fees(superadmin_session, est_id)["Mar"]
    assert before["is_paid"] is False and before["amount_due"] == 10.0

    _activate_plan(test_db, consultant_a.user_id)
    after = _fees(superadmin_session, est_id)["Mar"]
    assert after["is_paid"] is True
    assert after["amount_due"] == 0
    assert after["billing_mode"] == "consultant_plan"
    assert after["payment_reference"] == PLAN_COVERED_REFERENCE


def test_zero_due_placeholder_waived_once_wages_arrive(superadmin_session, consultant_a, test_db):
    est_id = _make_est(consultant_a, "CPB006", seed_wages=False)
    placeholder = _fees(superadmin_session, est_id)["Mar"]  # creates the 0-due placeholder row
    assert placeholder["amount_due"] == 0 and placeholder["is_paid"] is False

    _activate_plan(test_db, consultant_a.user_id)
    _enter_wages(consultant_a, "CPB006", 1, 1)
    mar = _fees(superadmin_session, est_id)["Mar"]
    assert mar["employee_count"] == 1
    assert mar["is_paid"] is True
    assert mar["billing_mode"] == "consultant_plan"
    assert mar["amount_due"] == 0


def test_lapse_keeps_waived_rows_paid_and_bills_new_rows(superadmin_session, consultant_a, test_db):
    row = _activate_plan(test_db, consultant_a.user_id)
    est_id = _make_est(consultant_a, "CPB007")
    assert _fees(superadmin_session, est_id)["Mar"]["is_paid"] is True

    # The plan window slides into the past: nothing is clawed back, new months bill normally.
    row.covered_from, row.covered_to = "2020-01", "2020-02"
    test_db.commit()
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post(f"/api/years/{YEAR}/wages", json={
        "member_id": "CPB007001", "wages": [15000.0, 15000.0] + [0.0] * 10
    })
    assert res.status_code == 200, res.text

    months = _fees(superadmin_session, est_id)
    assert months["Mar"]["is_paid"] is True
    assert months["Mar"]["amount_due"] == 0
    assert months["Mar"]["billing_mode"] == "consultant_plan"
    assert months["Apr"]["is_paid"] is False
    assert months["Apr"]["amount_due"] == 10.0
    assert months["Apr"]["billing_mode"] == "per_employee"


def test_other_consultant_unaffected(superadmin_session, consultant_a, consultant_b, test_db):
    _activate_plan(test_db, consultant_a.user_id)
    est_a = _make_est(consultant_a, "CPB008")
    est_b = _make_est(consultant_b, "CPB009")

    assert _fees(superadmin_session, est_a)["Mar"]["is_paid"] is True
    mar_b = _fees(superadmin_session, est_b)["Mar"]
    assert mar_b["is_paid"] is False
    assert mar_b["amount_due"] == 10.0
    assert mar_b["billing_mode"] == "per_employee"
    consultant_b.set_establishment(est_b)
    assert consultant_b.get(f"/api/reports/{YEAR}/ecr/0").status_code == 402


def test_advance_credit_not_consumed_when_waived(superadmin_session, consultant_a, test_db):
    _activate_plan(test_db, consultant_a.user_id)
    est_id = _make_est(consultant_a, "CPB010", rate=20.0)
    res = superadmin_session.post(f"/api/admin/establishments/{est_id}/advance-payment", json={
        "amount": 2000.0, "payment_reference": "UPI/ADV/PLAN", "notes": "prepay"
    })
    assert res.status_code == 200, res.text

    mar = _fees(superadmin_session, est_id)["Mar"]
    assert mar["is_paid"] is True
    assert mar["payment_reference"] == PLAN_COVERED_REFERENCE
    assert mar["billing_mode"] == "consultant_plan"
    credit = superadmin_session.get(f"/api/admin/establishments/{est_id}/advance-credit").json()
    assert credit["advance_credit_balance"] == 2000.0


def test_plan_amount_null_with_old_payment_bills_normally(superadmin_session, consultant_a, test_db):
    row = _activate_plan(test_db, consultant_a.user_id)
    user = test_db.query(User).filter(User.id == consultant_a.user_id).first()
    user.consultant_plan_amount = None  # plan removed; the old paid window must not waive anything
    test_db.commit()
    assert row.status == "manual"

    est_id = _make_est(consultant_a, "CPB011")
    mar = _fees(superadmin_session, est_id)["Mar"]
    assert mar["is_paid"] is False
    assert mar["amount_due"] == 10.0
    assert mar["billing_mode"] == "per_employee"


def _mar_fee_row(test_db, est_id):
    test_db.expire_all()
    return test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.financial_year == YEAR,
        SubscriptionFee.month == "Mar"
    ).first()


def test_pending_verification_row_not_waived_by_plan(superadmin_session, consultant_a, test_db):
    """A UTR awaiting admin approval may represent real money: a plan activating afterwards
    must not silently waive the row, or the admin could no longer approve/reject it."""
    est_id = _make_est(consultant_a, "CPB012")
    _fees(superadmin_session, est_id)  # lazy sync creates the fee rows
    fee_id = _mar_fee_row(test_db, est_id).id
    res = consultant_a.post(f"/api/subscription-fees/{fee_id}/submit-utr", json={"utr": "UTR-PLAN-PENDING-001"})
    assert res.status_code == 200, res.text

    _activate_plan(test_db, consultant_a.user_id)
    mar = _fees(superadmin_session, est_id)["Mar"]  # triggers a sync under the active plan

    row = _mar_fee_row(test_db, est_id)
    assert row.payment_status == "pending_verification"
    assert row.is_paid is False
    assert row.submitted_utr == "UTR-PLAN-PENDING-001"
    assert row.billing_mode == "per_employee"
    assert row.payment_reference in (None, "")
    assert mar["is_paid"] is False and mar["amount_due"] == 10.0

    res = superadmin_session.get("/api/admin/payment-verifications")
    assert res.status_code == 200, res.text
    assert f"fee-{fee_id}" in [it["id"] for it in res.json()["items"]]


def test_already_paid_row_untouched_when_plan_activates(superadmin_session, consultant_a, test_db):
    est_id = _make_est(consultant_a, "CPB013", rate=20.0)
    _fees(superadmin_session, est_id)  # create the fee rows
    res = superadmin_session.post(f"/api/admin/establishments/{est_id}/subscription-fees", json={
        "financial_year": YEAR,
        "fees": [{"month": "Mar", "is_paid": True, "paid_date": "15-04-2026", "payment_reference": "UPI/REAL/CPB013"}]
    })
    assert res.status_code == 200, res.text
    before = _mar_fee_row(test_db, est_id)
    assert before.is_paid is True
    snapshot = (before.payment_reference, before.amount_due, before.billing_mode, before.paid_date)
    assert snapshot[0] == "UPI/REAL/CPB013" and snapshot[1] == 20.0

    _activate_plan(test_db, consultant_a.user_id)
    mar = _fees(superadmin_session, est_id)["Mar"]  # sync under the active plan

    after = _mar_fee_row(test_db, est_id)
    assert (after.payment_reference, after.amount_due, after.billing_mode, after.paid_date) == snapshot
    assert mar["is_paid"] is True and mar["payment_reference"] == "UPI/REAL/CPB013"
    assert mar["billing_mode"] == "per_employee"


def test_waiver_works_for_flat_fee_establishment(superadmin_session, consultant_a, test_db):
    _activate_plan(test_db, consultant_a.user_id)
    est_id = _make_est(consultant_a, "CPB014", seed_wages=False)
    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })
    assert res.status_code == 200, res.text
    _enter_wages(consultant_a, "CPB014", 1, 1)

    mar = _fees(superadmin_session, est_id)["Mar"]
    assert mar["employee_count"] == 1
    assert mar["is_paid"] is True
    assert mar["amount_due"] == 0
    assert mar["billing_mode"] == "consultant_plan"
    assert mar["payment_reference"] == PLAN_COVERED_REFERENCE


def _flat_fee_est_with_one_wage_month(superadmin_session, consultant_a, code):
    est_id = _make_est(consultant_a, code, seed_wages=False)
    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 300.0
    })
    assert res.status_code == 200, res.text
    _enter_wages(consultant_a, code, 1, 1)  # wages in Mar only
    return est_id


def test_flat_fee_plan_zero_employee_months_do_not_block_add_year(superadmin_session, consultant_a, test_db):
    _activate_plan(test_db, consultant_a.user_id)
    est_id = _flat_fee_est_with_one_wage_month(superadmin_session, consultant_a, "CPB015")

    months = _fees(superadmin_session, est_id)
    assert months["Mar"]["billing_mode"] == "consultant_plan" and months["Mar"]["amount_due"] == 0
    for m in ("Apr", "May", "Feb"):
        assert months[m]["employee_count"] == 0
        assert months[m]["is_paid"] is False
        assert months[m]["amount_due"] == 0  # placeholder, not the flat amount

    consultant_a.set_establishment(est_id)
    res = consultant_a.get("/api/establishment/entry-lock-status")
    assert res.status_code == 200, res.text
    assert res.json()["can_add_year"] is True
    assert res.json()["blocking_year"] is None


def test_flat_fee_without_plan_zero_employee_months_keep_flat_amount(superadmin_session, consultant_a, test_db):
    est_id = _flat_fee_est_with_one_wage_month(superadmin_session, consultant_a, "CPB016")

    months = _fees(superadmin_session, est_id)
    for m in ("Mar", "Apr", "May", "Feb"):
        assert months[m]["is_paid"] is False
        assert months[m]["amount_due"] == 300.0
        assert months[m]["billing_mode"] == "flat_fee"

    consultant_a.set_establishment(est_id)
    res = consultant_a.get("/api/establishment/entry-lock-status")
    assert res.status_code == 200, res.text
    assert res.json()["can_add_year"] is False
    assert res.json()["blocking_year"]["amount_due"] == 3600.0


def test_waived_row_is_labelled_consultant_plan_in_history(superadmin_session, consultant_a, test_db):
    _activate_plan(test_db, consultant_a.user_id)
    est_id = _make_est(consultant_a, "CPB017")
    _fees(superadmin_session, est_id)  # sync -> waive Mar
    consultant_a.set_establishment(est_id)
    res = consultant_a.get("/api/establishment/subscription-payments")
    assert res.status_code == 200, res.text
    mar = [p for p in res.json()["payments"] if p["month"] == "Mar"][0]
    assert mar["source"] == "consultant_plan"
    assert mar["billing_display"] == "Consultant plan"
    admin = superadmin_session.get("/api/admin/subscription-payments?limit=200")
    assert admin.status_code == 200, admin.text
    rows = [p for p in admin.json()["payments"] if p["establishment_id"] == est_id and p["month"] == "Mar"]
    assert rows and rows[0]["source"] == "consultant_plan"


def test_payment_on_plan_waived_row_is_logged_without_changing_row(superadmin_session, consultant_a, test_db):
    import json
    from webapp.app import _confirm_subscription_fee_paid
    from webapp.database import ActivityLog

    _activate_plan(test_db, consultant_a.user_id)
    est_id = _make_est(consultant_a, "CPB018")
    _fees(superadmin_session, est_id)
    row = _mar_fee_row(test_db, est_id)
    assert row.payment_reference == PLAN_COVERED_REFERENCE and row.is_paid is True
    row.cashfree_order_id = "CPB018-ORDER-1"
    test_db.commit()

    _confirm_subscription_fee_paid(test_db, row, "CF-PAY-REAL-1")

    after = _mar_fee_row(test_db, est_id)
    assert after.payment_reference == PLAN_COVERED_REFERENCE  # untouched
    assert after.amount_due == 0 and after.billing_mode == "consultant_plan"
    logs = test_db.query(ActivityLog).filter(
        ActivityLog.establishment_id == est_id, ActivityLog.action_type == "fee_payment_on_plan_waived_row"
    ).all()
    assert len(logs) == 1
    assert "CF-PAY-REAL-1" in logs[0].description and "CPB018-ORDER-1" in logs[0].description
    meta = json.loads(logs[0].extra_data)
    assert meta["month"] == "Mar" and meta["payment_reference"] == "CF-PAY-REAL-1"

    # An ordinary already-paid row (not plan-waived) stays a silent no-op.
    after.payment_reference = "UPI/REAL"
    test_db.commit()
    _confirm_subscription_fee_paid(test_db, after, "CF-PAY-REAL-2")
    assert test_db.query(ActivityLog).filter(
        ActivityLog.establishment_id == est_id, ActivityLog.action_type == "fee_payment_on_plan_waived_row"
    ).count() == 1
