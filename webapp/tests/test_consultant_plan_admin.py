"""
Consultant Monthly Plan -- superadmin controls and verification-queue integration
=================================================================================
Superadmin sets/clears a consultant's monthly plan amount, records manual payments, reads a
consultant's plan, and approves/rejects UPI+UTR plan submissions from the shared
payment-verification queue (composite id ``plan-N``). Cashfree is never called.
"""

import pytest

from webapp.app import _billing_display
from webapp.auth import hash_password
from webapp.consultant_plan import add_months, current_month_ist
from webapp.database import (
    AdvanceCreditLedger, ConsultantPlanPayment, Establishment, SubscriptionFee, User,
)

YEAR = "2026-27"
PLAN_EMAILS = ("consultant_a@testepf.com", "consultant_b@testepf.com")
EMPLOYER_EMAIL = "plan_admin_employer@testepf.com"


@pytest.fixture(autouse=True)
def _isolate_plan_state(test_db):
    """The test DB is shared across the whole session and consultant_a/b are reused by other
    modules, so plan state must never leak in or out of these tests."""
    def wipe():
        test_db.rollback()
        for email in PLAN_EMAILS:
            u = test_db.query(User).filter(User.email == email).first()
            if u:
                u.consultant_plan_amount = None
                test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.user_id == u.id).delete()
        test_db.query(SubscriptionFee).filter(SubscriptionFee.submitted_utr.like("PLANADM%")).delete(
            synchronize_session=False)
        test_db.query(AdvanceCreditLedger).filter(AdvanceCreditLedger.submitted_utr.like("PLANADM%")).delete(
            synchronize_session=False)
        test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.submitted_utr.like("PLANADM%")).delete(
            synchronize_session=False)
        emp = test_db.query(User).filter(User.email == EMPLOYER_EMAIL).first()
        if emp:
            test_db.delete(emp)
        test_db.commit()
    wipe()
    yield
    wipe()


def _set_plan(test_db, user_id, amount):
    user = test_db.query(User).filter(User.id == user_id).first()
    user.consultant_plan_amount = amount
    test_db.commit()


def _plan_rows(test_db, user_id):
    test_db.expire_all()
    return test_db.query(ConsultantPlanPayment).filter(
        ConsultantPlanPayment.user_id == user_id).order_by(ConsultantPlanPayment.id).all()


def _queue(superadmin_session, status="pending_verification"):
    res = superadmin_session.get(f"/api/admin/payment-verifications?status={status}&limit=100")
    assert res.status_code == 200, res.text
    return res.json()["items"]


def _submit_plan_utr(consultant, utr, months=2):
    res = consultant.post("/api/my-plan/submit-utr", json={"months": months, "utr": utr})
    assert res.status_code == 200, res.text
    return res.json()["payment_id"]


# ── set / clear the plan amount ────────────────────────────────────────────

def test_only_superadmin_can_set_plan_amount(superadmin_session, consultant_a, consultant_b, test_db):
    # A consultant cannot set a plan amount, on anyone (not even themselves).
    for target in (consultant_a.user_id, consultant_b.user_id):
        res = consultant_a.put(f"/api/admin/users/{target}/consultant-plan", json={"amount": 100.0})
        assert res.status_code == 403, res.text
    assert consultant_a.post(
        f"/api/admin/users/{consultant_a.user_id}/plan-payment", json={"months": 1, "reference": "X"}
    ).status_code == 403
    assert consultant_a.get(f"/api/admin/users/{consultant_a.user_id}/plan").status_code == 403
    test_db.expire_all()
    assert test_db.query(User).filter(User.id == consultant_a.user_id).first().consultant_plan_amount is None

    # Superadmin and employer accounts are not valid plan targets.
    res = superadmin_session.put(
        f"/api/admin/users/{superadmin_session.user_id}/consultant-plan", json={"amount": 100.0})
    assert res.status_code == 400, res.text
    emp = User(name="Plan Employer", email=EMPLOYER_EMAIL, mobile="9000000077",
               password_hash=hash_password("Employer@123"), role="employer", is_active=True)
    test_db.add(emp)
    test_db.commit()
    test_db.refresh(emp)
    res = superadmin_session.put(f"/api/admin/users/{emp.id}/consultant-plan", json={"amount": 100.0})
    assert res.status_code == 400, res.text
    assert superadmin_session.post(
        f"/api/admin/users/{emp.id}/plan-payment", json={"months": 1, "reference": "X"}).status_code == 400

    assert superadmin_session.put("/api/admin/users/999999/consultant-plan", json={"amount": 100.0}).status_code == 404


def test_set_and_clear_plan_amount(superadmin_session, consultant_a, test_db):
    url = f"/api/admin/users/{consultant_a.user_id}/consultant-plan"
    res = superadmin_session.put(url, json={"amount": 2000})
    assert res.status_code == 200, res.text
    assert res.json() == {"ok": True, "consultant_plan_amount": 2000.0}
    test_db.expire_all()
    assert test_db.query(User).filter(User.id == consultant_a.user_id).first().consultant_plan_amount == 2000.0

    # The consultant sees it on their own plan and the admin payloads expose it.
    assert consultant_a.get("/api/my-plan").json()["plan_amount"] == 2000.0
    detail = superadmin_session.get(f"/api/admin/users/{consultant_a.user_id}/establishments").json()
    assert detail["user"]["consultant_plan_amount"] == 2000.0
    listed = {u["id"]: u for u in superadmin_session.get("/api/admin/users").json()["users"]}
    assert listed[consultant_a.user_id]["consultant_plan_amount"] == 2000.0

    # Zero, negative and non-numeric are rejected and leave the amount untouched.
    for bad in (0, -5, 0.0):
        assert superadmin_session.put(url, json={"amount": bad}).status_code == 400
    assert superadmin_session.put(url, json={"amount": "abc"}).status_code == 422
    test_db.expire_all()
    assert test_db.query(User).filter(User.id == consultant_a.user_id).first().consultant_plan_amount == 2000.0

    res = superadmin_session.put(url, json={"amount": None})
    assert res.status_code == 200 and res.json() == {"ok": True, "consultant_plan_amount": None}
    test_db.expire_all()
    assert test_db.query(User).filter(User.id == consultant_a.user_id).first().consultant_plan_amount is None

    logs = superadmin_session.get("/api/admin/activity-log?action_type=consultant_plan_changed&limit=50")
    assert logs.status_code == 200, logs.text
    assert logs.json()["total"] >= 2  # one entry for the set, one for the clear


# ── manual payments ────────────────────────────────────────────────────────

def test_manual_payment_validation(superadmin_session, consultant_a, test_db):
    url = f"/api/admin/users/{consultant_a.user_id}/plan-payment"
    # No plan amount yet -> cannot price a payment.
    assert superadmin_session.post(url, json={"months": 1, "reference": "CASH-1"}).status_code == 400
    _set_plan(test_db, consultant_a.user_id, 1000.0)
    for bad in (0, -1, 25):
        assert superadmin_session.post(url, json={"months": bad, "reference": "CASH-1"}).status_code == 400
    for bad in ("3", 2.5, True, None):
        assert superadmin_session.post(url, json={"months": bad, "reference": "CASH-1"}).status_code in (400, 422)
    assert superadmin_session.post(url, json={"months": 1, "reference": "   "}).status_code == 400
    assert _plan_rows(test_db, consultant_a.user_id) == []


def test_manual_payment_activates_plan_and_unlocks_billing(superadmin_session, consultant_a, test_db):
    from webapp.tests.test_consultant_plan_billing import _fees, _make_est

    est_id = _make_est(consultant_a, "CPA001")
    assert _fees(superadmin_session, est_id)["Mar"]["is_paid"] is False

    _set_plan(test_db, consultant_a.user_id, 2000.0)
    res = superadmin_session.post(
        f"/api/admin/users/{consultant_a.user_id}/plan-payment",
        json={"months": 3, "reference": "CASH-RECEIPT-77", "amount": 1})
    assert res.status_code == 200, res.text
    now = current_month_ist()
    body = res.json()
    assert body["ok"] is True
    assert body["payment"]["status"] == "manual"
    assert body["payment"]["amount"] == 6000.0  # server computed; the client amount is ignored
    assert body["payment"]["covered_from"] == now
    assert body["payment"]["covered_to"] == add_months(now, 2)

    row = _plan_rows(test_db, consultant_a.user_id)[0]
    assert row.status == "manual" and row.months == 3 and row.amount == 6000.0
    assert row.payment_reference == "CASH-RECEIPT-77"

    mar = _fees(superadmin_session, est_id)["Mar"]
    assert mar["is_paid"] is True and mar["amount_due"] == 0
    assert mar["billing_mode"] == "consultant_plan"
    consultant_a.set_establishment(est_id)
    assert consultant_a.get(f"/api/reports/{YEAR}/ecr/0").status_code == 200

    # The admin read mirrors GET /api/my-plan.
    admin_view = superadmin_session.get(f"/api/admin/users/{consultant_a.user_id}/plan").json()
    assert admin_view == consultant_a.get("/api/my-plan").json()
    assert admin_view["active"] is True and admin_view["covered_through"] == add_months(now, 2)

    # A second manual payment stacks after the first (no overlap).
    res = superadmin_session.post(
        f"/api/admin/users/{consultant_a.user_id}/plan-payment", json={"months": 2, "reference": "CASH-RECEIPT-78"})
    assert res.json()["payment"]["covered_from"] == add_months(now, 3)
    assert res.json()["payment"]["covered_to"] == add_months(now, 4)


def test_admin_plan_view_for_unknown_or_non_consultant(superadmin_session):
    assert superadmin_session.get("/api/admin/users/999999/plan").status_code == 404
    assert superadmin_session.get(f"/api/admin/users/{superadmin_session.user_id}/plan").status_code == 400


# ── verification queue ─────────────────────────────────────────────────────

def test_queue_lists_plan_utr_and_approve_activates(superadmin_session, consultant_a, test_db):
    _set_plan(test_db, consultant_a.user_id, 750.0)
    pid = _submit_plan_utr(consultant_a, "PLANADM-UTR-1", months=2)

    items = {it["id"]: it for it in _queue(superadmin_session)}
    it = items[f"plan-{pid}"]
    assert it["source"] == "consultant_plan"
    assert it["establishment_name"] == "Consultant Alpha"
    assert it["establishment_code"] == "CONSULTANT PLAN"
    assert it["establishment_id"] is None
    assert it["financial_year"] is None and it["month"] is None
    assert it["display_name"] == "Monthly Plan - 2 month(s)"
    assert it["amount_due"] == 1500.0
    assert it["payment_status"] == "pending_verification"
    assert it["submitted_utr"] == "PLANADM-UTR-1"
    assert it["submitted_by"] == consultant_a.user_id
    assert it["submitted_by_name"] == "Consultant Alpha"
    assert it["submitted_at"]
    assert "_sort_dt" not in it
    assert consultant_a.get("/api/my-plan").json()["active"] is False

    res = superadmin_session.post(f"/api/admin/payment-verifications/plan-{pid}/approve", json={})
    assert res.status_code == 200, res.text
    assert res.json()["payment_status"] == "paid"

    now = current_month_ist()
    mine = consultant_a.get("/api/my-plan").json()
    assert mine["active"] is True and mine["covered_through"] == add_months(now, 1)
    row = _plan_rows(test_db, consultant_a.user_id)[0]
    assert row.status == "confirmed"
    assert row.payment_reference == "PLANADM-UTR-1"
    assert row.verified_by == superadmin_session.user_id and row.verified_at is not None
    assert (row.covered_from, row.covered_to) == (now, add_months(now, 1))

    # Approving again is refused and does not allocate coverage a second time.
    res = superadmin_session.post(f"/api/admin/payment-verifications/plan-{pid}/approve", json={})
    assert res.status_code == 400
    again = consultant_a.get("/api/my-plan").json()
    assert again["covered_through"] == add_months(now, 1) and len(again["payments"]) == 1

    # It moves from the pending list to the paid list, verifier name filled in.
    assert f"plan-{pid}" not in [i["id"] for i in _queue(superadmin_session)]
    paid = {i["id"]: i for i in _queue(superadmin_session, "paid")}
    assert paid[f"plan-{pid}"]["payment_status"] == "paid"
    assert paid[f"plan-{pid}"]["verified_by_name"] == superadmin_session.user["name"]
    assert f"plan-{pid}" not in [i["id"] for i in _queue(superadmin_session, "unpaid")]


def test_paid_filter_includes_manual_plan_rows(superadmin_session, consultant_a, test_db):
    _set_plan(test_db, consultant_a.user_id, 500.0)
    res = superadmin_session.post(
        f"/api/admin/users/{consultant_a.user_id}/plan-payment", json={"months": 1, "reference": "CASH-9"})
    pid = res.json()["payment"]["id"]
    paid = {i["id"]: i for i in _queue(superadmin_session, "paid")}
    assert paid[f"plan-{pid}"]["payment_status"] == "paid"
    assert f"plan-{pid}" not in [i["id"] for i in _queue(superadmin_session)]


def test_reject_requires_reason_and_grants_nothing(superadmin_session, consultant_a, test_db):
    _set_plan(test_db, consultant_a.user_id, 750.0)
    pid = _submit_plan_utr(consultant_a, "PLANADM-UTR-2", months=3)
    url = f"/api/admin/payment-verifications/plan-{pid}/reject"

    assert superadmin_session.post(url, json={"rejection_reason": "   "}).status_code == 400
    assert _plan_rows(test_db, consultant_a.user_id)[0].status == "pending_verification"

    res = superadmin_session.post(url, json={"rejection_reason": "UTR not found in bank statement"})
    assert res.status_code == 200, res.text
    assert res.json()["payment_status"] == "unpaid"
    row = _plan_rows(test_db, consultant_a.user_id)[0]
    assert row.status == "rejected"
    assert row.rejection_reason == "UTR not found in bank statement"
    assert row.verified_by == superadmin_session.user_id and row.verified_at is not None
    assert row.covered_from is None and row.covered_to is None
    mine = consultant_a.get("/api/my-plan").json()
    assert mine["active"] is False and mine["covered_through"] is None

    # Neither action can be repeated on a settled row, and a rejected row cannot be approved.
    assert superadmin_session.post(url, json={"rejection_reason": "again"}).status_code == 400
    assert superadmin_session.post(
        f"/api/admin/payment-verifications/plan-{pid}/approve", json={}).status_code == 400
    assert consultant_a.get("/api/my-plan").json()["active"] is False

    unpaid = {i["id"]: i for i in _queue(superadmin_session, "unpaid")}
    assert unpaid[f"plan-{pid}"]["payment_status"] == "unpaid"
    assert unpaid[f"plan-{pid}"]["rejection_reason"] == "UTR not found in bank statement"
    assert f"plan-{pid}" not in [i["id"] for i in _queue(superadmin_session)]


def test_plan_ids_not_found_and_consultant_forbidden(superadmin_session, consultant_a, test_db):
    assert superadmin_session.post("/api/admin/payment-verifications/plan-999999/approve", json={}).status_code == 404
    assert superadmin_session.post(
        "/api/admin/payment-verifications/plan-999999/reject", json={"rejection_reason": "x"}).status_code == 404
    _set_plan(test_db, consultant_a.user_id, 750.0)
    pid = _submit_plan_utr(consultant_a, "PLANADM-UTR-3")
    assert consultant_a.post(f"/api/admin/payment-verifications/plan-{pid}/approve", json={}).status_code == 403
    assert consultant_a.post(
        f"/api/admin/payment-verifications/plan-{pid}/reject", json={"rejection_reason": "x"}).status_code == 403
    assert _plan_rows(test_db, consultant_a.user_id)[0].status == "pending_verification"


def test_verification_id_forms_still_work(superadmin_session, consultant_a, test_db):
    from webapp.tests.test_consultant_plan_billing import _fees, _make_est
    from webapp.app import _split_verification_id

    assert _split_verification_id("plan-12") == ("plan", 12)
    assert _split_verification_id("fee-3") == ("fee", 3)
    assert _split_verification_id("adv-4") == ("adv", 4)
    assert _split_verification_id("7") == ("fee", 7)

    est_id = _make_est(consultant_a, "CPA002")
    _fees(superadmin_session, est_id)  # create fee rows
    test_db.expire_all()
    fee_rows = {f.month: f for f in test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.financial_year == YEAR)}
    fee_a, fee_b = fee_rows["Mar"], fee_rows["Apr"]
    fee_a_id, fee_b_id = fee_a.id, fee_b.id
    for fee in (fee_a, fee_b):
        fee.employee_count = 1
        fee.amount_due = 10.0
    test_db.commit()
    consultant_a.set_establishment(est_id)
    assert consultant_a.post(f"/api/subscription-fees/{fee_a_id}/submit-utr", json={"utr": "PLANADM-FEE-A"}).status_code == 200
    assert consultant_a.post(f"/api/subscription-fees/{fee_b_id}/submit-utr", json={"utr": "PLANADM-FEE-B"}).status_code == 200

    ledger = AdvanceCreditLedger(establishment_id=est_id, entry_type="topup", amount=300.0,
                                 status="pending_verification", submitted_utr="PLANADM-ADV-1")
    test_db.add(ledger)
    test_db.commit()
    test_db.refresh(ledger)

    _set_plan(test_db, consultant_a.user_id, 100.0)
    pid = _submit_plan_utr(consultant_a, "PLANADM-PLAN-1", months=1)

    ids = [i["id"] for i in _queue(superadmin_session)]
    assert {f"fee-{fee_a_id}", f"fee-{fee_b_id}", f"adv-{ledger.id}", f"plan-{pid}"} <= set(ids)

    # Composite fee id (approve), bare digits (reject, legacy), adv id (approve), plan id (approve).
    res = superadmin_session.post(f"/api/admin/payment-verifications/fee-{fee_a_id}/approve", json={})
    assert res.status_code == 200 and res.json()["payment_status"] == "paid"
    res = superadmin_session.post(
        f"/api/admin/payment-verifications/{fee_b_id}/reject", json={"rejection_reason": "bad utr"})
    assert res.status_code == 200 and res.json()["payment_status"] == "unpaid"
    res = superadmin_session.post(f"/api/admin/payment-verifications/adv-{ledger.id}/approve", json={})
    assert res.status_code == 200, res.text
    assert res.json()["advance_credit_balance"] == 300.0
    res = superadmin_session.post(f"/api/admin/payment-verifications/plan-{pid}/approve", json={})
    assert res.status_code == 200 and res.json()["payment_status"] == "paid"

    assert superadmin_session.post("/api/admin/payment-verifications/bogus/approve", json={}).status_code == 400
    assert superadmin_session.post("/api/admin/payment-verifications/plan-x/approve", json={}).status_code in (400, 422)

    # Cleanup of the advance credit this test granted.
    est = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    test_db.expire_all()
    est.advance_credit_balance = 0.0
    test_db.commit()


# ── billing display for plan-covered rows ──────────────────────────────────

def test_billing_display_helper_consultant_plan():
    assert _billing_display("consultant_plan", None, 0) == "Consultant plan"
    assert _billing_display("consultant_plan", 10.0, 0) == "Consultant plan"
    # Other modes are unchanged.
    assert _billing_display("flat_fee", None, 500.0) == "₹500.0/month flat rate"
    assert _billing_display("per_employee", 10.0, 10.0) == "₹10.0/employee"
    assert _billing_display("per_employee", None, 0) == "Default rate"


def test_waived_row_billing_display_in_admin_fees_endpoint(superadmin_session, consultant_a, test_db):
    from webapp.tests.test_consultant_plan_billing import _activate_plan, _fees, _make_est

    est_id = _make_est(consultant_a, "CPA003")
    before = _fees(superadmin_session, est_id)["Mar"]
    assert before["billing_display"] == "₹10.0/employee"  # unchanged for a normally billed row

    _activate_plan(test_db, consultant_a.user_id)
    months = _fees(superadmin_session, est_id)
    assert months["Mar"]["billing_mode"] == "consultant_plan"
    assert months["Mar"]["billing_display"] == "Consultant plan"
    assert "None" not in months["Mar"]["billing_display"]
    # A placeholder (no wage data) month still shows the ordinary text.
    assert months["May"]["billing_mode"] != "consultant_plan"
    assert months["May"]["billing_display"] != "Consultant plan"


def test_waived_row_billing_display_in_consultant_endpoints(superadmin_session, consultant_a, test_db):
    from webapp.tests.test_consultant_plan_billing import _activate_plan, _fees, _make_est

    est_id = _make_est(consultant_a, "CPA004")
    _activate_plan(test_db, consultant_a.user_id)
    _fees(superadmin_session, est_id)  # sync waives the Mar row

    consultant_a.set_establishment(est_id)
    detail = consultant_a.get(f"/api/establishment/subscription-fees/month-detail?year={YEAR}&month=Mar").json()
    assert detail["billing_mode"] == "consultant_plan"
    assert detail["billing_display"] == "Consultant plan"

    history = consultant_a.get("/api/establishment/subscription-payments").json()
    mar = [p for p in history["payments"] if p["month"] == "Mar"][0]
    assert mar["billing_display"] == "Consultant plan"

    admin_tab = superadmin_session.get(f"/api/admin/subscription-payments?establishment_id={est_id}")
    assert admin_tab.status_code == 200, admin_tab.text
    waived = [p for p in admin_tab.json()["payments"] if p["month"] == "Mar"]
    assert len(waived) == 1
    assert waived[0]["billing_display"] == "Consultant plan"


def test_admin_users_list_includes_default_billing_fields(superadmin_session, consultant_a, consultant_b):
    # The admin UI loads its consultants array from this list and the Edit modal reads the
    # default billing fields from it; omitting them made Save silently clear the default.
    url = f"/api/admin/users/{consultant_a.user_id}/default-billing"
    try:
        res = superadmin_session.put(
            url, json={"default_billing_mode": "flat_fee", "default_flat_fee_per_establishment": 300})
        assert res.status_code == 200, res.text
        listed = {u["id"]: u for u in superadmin_session.get("/api/admin/users").json()["users"]}
        assert listed[consultant_a.user_id]["default_billing_mode"] == "flat_fee"
        assert listed[consultant_a.user_id]["default_flat_fee_per_establishment"] == 300
        # A consultant with no default shows both as None (keys present).
        assert "default_billing_mode" in listed[consultant_b.user_id]
        assert listed[consultant_b.user_id]["default_billing_mode"] is None
        assert listed[consultant_b.user_id]["default_flat_fee_per_establishment"] is None
    finally:
        superadmin_session.put(url, json={"default_billing_mode": None})


# ── input limits (final review) ────────────────────────────────────────────

def test_set_plan_amount_edge_cases(superadmin_session, consultant_a, test_db):
    url = f"/api/admin/users/{consultant_a.user_id}/consultant-plan"
    # Rounds to 0.00 -> rejected; absurdly large -> rejected (24-month price would overflow to inf).
    assert superadmin_session.put(url, json={"amount": 0.004}).status_code == 400
    assert superadmin_session.put(url, json={"amount": 1e308}).status_code == 400
    assert superadmin_session.put(url, json={"amount": 1000000.01}).status_code == 400
    test_db.expire_all()
    assert test_db.query(User).filter(User.id == consultant_a.user_id).first().consultant_plan_amount is None

    res = superadmin_session.put(url, json={"amount": 1000000})
    assert res.status_code == 200 and res.json()["consultant_plan_amount"] == 1000000.0
    res = superadmin_session.put(url, json={"amount": 2000})
    assert res.status_code == 200 and res.json()["consultant_plan_amount"] == 2000.0
    res = superadmin_session.put(url, json={"amount": 0.01})
    assert res.status_code == 200 and res.json()["consultant_plan_amount"] == 0.01


def test_manual_payment_reference_length_cap(superadmin_session, consultant_a, test_db):
    _set_plan(test_db, consultant_a.user_id, 1000.0)
    url = f"/api/admin/users/{consultant_a.user_id}/plan-payment"
    res = superadmin_session.post(url, json={"months": 1, "reference": "R" * 101})
    assert res.status_code == 400 and "100" in res.json()["detail"]
    assert _plan_rows(test_db, consultant_a.user_id) == []
    # Whitespace is stripped before the cap is applied.
    res = superadmin_session.post(url, json={"months": 1, "reference": "  " + "R" * 100 + "  "})
    assert res.status_code == 200, res.text
    assert _plan_rows(test_db, consultant_a.user_id)[0].payment_reference == "R" * 100


# ------------------------------------- plan shown next to the per-employee rate (admin display)

def test_admin_payloads_carry_plan_active_flags(superadmin_session, consultant_a, test_db):
    """Users list, the consultant's establishments view and the establishment fee view must say
    whether a paid plan month is active, so the UI can show the plan next to the old rate instead
    of only 'Rs N/emp' (display only)."""
    from webapp.tests.test_consultant_plan_billing import _make_est
    est_id = _make_est(consultant_a, "CPA090")
    uid = consultant_a.user_id

    def _row():
        users = superadmin_session.get("/api/admin/users").json()["users"]
        return next(u for u in users if u["id"] == uid)

    # no plan at all
    r = _row()
    assert (r["consultant_plan_amount"], r["consultant_plan_active"], r["consultant_plan_covered_through"]) == (None, False, None)

    # plan amount set, nothing paid: shown, but NOT active
    _set_plan(test_db, uid, 2000.0)
    r = _row()
    assert r["consultant_plan_amount"] == 2000.0 and r["consultant_plan_active"] is False
    assert r["consultant_plan_covered_through"] is None

    # one paid month: active through the current IST month, in all three payloads
    res = superadmin_session.post(f"/api/admin/users/{uid}/plan-payment", json={"months": 1, "reference": "OCT-CASH"})
    assert res.status_code == 200, res.text
    now = current_month_ist()
    r = _row()
    assert r["consultant_plan_active"] is True and r["consultant_plan_covered_through"] == now

    ests = superadmin_session.get(f"/api/admin/users/{uid}/establishments").json()
    assert ests["user"]["consultant_plan_amount"] == 2000.0
    assert ests["user"]["consultant_plan_active"] is True
    assert ests["user"]["consultant_plan_covered_through"] == now

    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year={YEAR}").json()
    assert fees["consultant"]["consultant_plan_amount"] == 2000.0
    assert fees["consultant"]["consultant_plan_active"] is True
    assert fees["consultant"]["consultant_plan_covered_through"] == now
    # the per-employee rate fields are untouched (the rate is still what applies when the plan is not paid)
    assert "effective_rate" in fees["rates"]


def test_plan_status_fields_for_a_consultant_without_a_plan_stay_inactive(superadmin_session, consultant_b, test_db):
    from webapp.tests.test_consultant_plan_billing import _make_est
    est_id = _make_est(consultant_b, "CPA091")
    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year={YEAR}").json()
    assert fees["consultant"]["consultant_plan_amount"] is None
    assert fees["consultant"]["consultant_plan_active"] is False
