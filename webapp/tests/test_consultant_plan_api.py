"""
Consultant Monthly Plan -- consultant-facing API (Cashfree link, webhook, refresh, UTR)
=======================================================================================
Cashfree is never called: link creation, status polling and webhook signature checks are
monkeypatched. The client never sends an amount; the server derives it from the stored
plan amount and `months`.
"""

import json

import pytest

from webapp import app as app_module
from webapp.consultant_plan import add_months, current_month_ist
from webapp.database import AdvanceCreditLedger, ConsultantPlanPayment, User

PLAN_EMAILS = ("consultant_a@testepf.com", "consultant_b@testepf.com")


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
        test_db.query(AdvanceCreditLedger).filter(AdvanceCreditLedger.submitted_utr.like("PLANAPI%")).delete(
            synchronize_session=False)
        test_db.commit()
    wipe()
    yield
    wipe()


@pytest.fixture
def mock_cashfree(monkeypatch):
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return {"method": "link", "link_url": "https://x/pay", "payment_session_id": "s1"}

    monkeypatch.setattr(app_module.cashfree_client, "create_payment_link_or_order", fake_create)
    monkeypatch.setattr(app_module.cashfree_client, "verify_webhook_signature", lambda *a, **k: True)
    return calls


def _set_plan(test_db, user_id, amount):
    user = test_db.query(User).filter(User.id == user_id).first()
    user.consultant_plan_amount = amount
    test_db.commit()


def _fire_webhook(client, link_id):
    payload = {
        "type": "PAYMENT_LINK_EVENT",
        "data": {
            "link_id": link_id, "link_status": "PAID",
            "order": {"order_id": f"CFPay_{link_id}", "transaction_id": 99887766, "transaction_status": "SUCCESS"},
        },
    }
    return client.post(
        "/api/webhooks/cashfree", data=json.dumps(payload),
        headers={"Content-Type": "application/json", "x-webhook-timestamp": "1", "x-webhook-signature": "sig"},
    )


def test_my_plan_without_amount_is_inactive_and_link_rejected(consultant_a, superadmin_session, mock_cashfree):
    res = consultant_a.get("/api/my-plan")
    assert res.status_code == 200
    assert res.json() == {"plan_amount": None, "active": False, "covered_through": None, "payments": []}

    res = consultant_a.post("/api/my-plan/create-link", json={"months": 3})
    assert res.status_code == 400
    assert "No monthly plan" in res.json()["detail"]
    res = consultant_a.post("/api/my-plan/submit-utr", json={"months": 3, "utr": "PLANAPI-NOPLAN"})
    assert res.status_code == 400
    assert mock_cashfree == []

    # A superadmin has no plan on their own account either.
    assert superadmin_session.get("/api/my-plan").json()["plan_amount"] is None
    assert superadmin_session.post("/api/my-plan/create-link", json={"months": 1}).status_code == 400


def test_create_link_computes_amount_server_side(consultant_a, test_db, mock_cashfree):
    _set_plan(test_db, consultant_a.user_id, 2000.0)
    res = consultant_a.post("/api/my-plan/create-link", json={"months": 6, "amount": 1})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["link_url"] == "https://x/pay"
    assert body["order_id"].startswith(f"plan_{consultant_a.user_id}_")

    assert mock_cashfree[0]["amount"] == 12000.0
    assert mock_cashfree[0]["link_id"] == body["order_id"]
    assert "type=plan" in mock_cashfree[0]["return_url"]

    row = test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.cashfree_order_id == body["order_id"]).one()
    assert row.user_id == consultant_a.user_id
    assert row.months == 6
    assert row.amount == 12000.0
    assert row.status == "pending"
    assert row.covered_from is None and row.covered_to is None

    mine = consultant_a.get("/api/my-plan").json()
    assert mine["plan_amount"] == 2000.0
    assert mine["active"] is False
    assert len(mine["payments"]) == 1
    assert mine["payments"][0]["status"] == "pending"


@pytest.mark.parametrize("bad", [0, -1, 25, "3", 2.5, True, None])
def test_months_validation(consultant_a, test_db, mock_cashfree, bad):
    _set_plan(test_db, consultant_a.user_id, 2000.0)
    res = consultant_a.post("/api/my-plan/create-link", json={"months": bad})
    assert res.status_code in (400, 422), res.text
    res = consultant_a.post("/api/my-plan/submit-utr", json={"months": bad, "utr": "PLANAPI-BADMONTHS"})
    assert res.status_code in (400, 422), res.text
    assert test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.user_id == consultant_a.user_id).count() == 0
    assert mock_cashfree == []


def test_webhook_confirms_once_and_activates_plan(client, consultant_a, test_db, mock_cashfree):
    _set_plan(test_db, consultant_a.user_id, 2000.0)
    order_id = consultant_a.post("/api/my-plan/create-link", json={"months": 3}).json()["order_id"]
    assert consultant_a.get("/api/my-plan").json()["active"] is False

    assert _fire_webhook(client, order_id).status_code == 200
    mine = consultant_a.get("/api/my-plan").json()
    now = current_month_ist()
    assert mine["active"] is True
    assert mine["covered_through"] == add_months(now, 2)
    pay = mine["payments"][0]
    assert pay["status"] == "confirmed"
    assert pay["covered_from"] == now and pay["covered_to"] == add_months(now, 2)

    # A retried webhook must not extend coverage or add anything.
    assert _fire_webhook(client, order_id).status_code == 200
    again = consultant_a.get("/api/my-plan").json()
    assert again["covered_through"] == add_months(now, 2)
    assert len(again["payments"]) == 1
    test_db.expire_all()
    assert test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.user_id == consultant_a.user_id).count() == 1


def test_refresh_status_confirms_paid_order_and_is_idempotent(consultant_a, test_db, mock_cashfree, monkeypatch):
    _set_plan(test_db, consultant_a.user_id, 500.0)
    order_id = consultant_a.post("/api/my-plan/create-link", json={"months": 2}).json()["order_id"]

    polled = []
    monkeypatch.setattr(app_module.cashfree_client, "get_payment_status",
                        lambda oid: polled.append(oid) or {"paid": False, "payment_ref": "x"})
    res = consultant_a.post("/api/my-plan/refresh-status", json={"order_id": order_id})
    assert res.status_code == 200 and res.json()["status"] == "pending"
    assert consultant_a.get("/api/my-plan").json()["active"] is False

    monkeypatch.setattr(app_module.cashfree_client, "get_payment_status",
                        lambda oid: polled.append(oid) or {"paid": True, "payment_ref": "CFREF123"})
    res = consultant_a.post("/api/my-plan/refresh-status", json={"order_id": order_id})
    assert res.status_code == 200 and res.json()["status"] == "confirmed"
    now = current_month_ist()
    mine = consultant_a.get("/api/my-plan").json()
    assert mine["active"] is True and mine["covered_through"] == add_months(now, 1)

    # Already confirmed: no second Cashfree poll, no extra coverage.
    n_polls = len(polled)
    res = consultant_a.post("/api/my-plan/refresh-status", json={"order_id": order_id})
    assert res.status_code == 200 and res.json()["status"] == "confirmed"
    assert len(polled) == n_polls
    assert consultant_a.get("/api/my-plan").json()["covered_through"] == add_months(now, 1)

    assert consultant_a.post("/api/my-plan/refresh-status", json={"order_id": "plan_0_0"}).status_code == 404


def test_submit_utr_pending_grants_nothing_until_approved(consultant_a, test_db):
    _set_plan(test_db, consultant_a.user_id, 750.0)
    res = consultant_a.post("/api/my-plan/submit-utr", json={"months": 4, "utr": "  PLANAPI-UTR-1  ", "amount": 1})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending_verification"

    row = test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.user_id == consultant_a.user_id).one()
    assert row.status == "pending_verification"
    assert row.months == 4 and row.amount == 3000.0
    assert row.submitted_utr == "PLANAPI-UTR-1"
    assert row.submitted_by == consultant_a.user_id
    assert row.submitted_at is not None
    assert row.covered_from is None

    mine = consultant_a.get("/api/my-plan").json()
    assert mine["active"] is False and mine["covered_through"] is None
    assert mine["payments"][0]["status"] == "pending_verification"

    assert consultant_a.post("/api/my-plan/submit-utr", json={"months": 1, "utr": "   "}).status_code == 400


def test_duplicate_utr_rejected_across_tables(consultant_a, consultant_b, test_db):
    _set_plan(test_db, consultant_a.user_id, 750.0)
    _set_plan(test_db, consultant_b.user_id, 750.0)

    # Same table.
    assert consultant_a.post("/api/my-plan/submit-utr", json={"months": 1, "utr": "PLANAPI-DUP1"}).status_code == 200
    res = consultant_b.post("/api/my-plan/submit-utr", json={"months": 1, "utr": "PLANAPI-DUP1"})
    assert res.status_code == 400 and "already been submitted" in res.json()["detail"]

    # A UTR already used on an advance-credit row blocks a plan submission.
    est_id = consultant_b.post("/api/establishments", json={
        "coverage_date": "01-04-2026", "code": "PLANAPI001", "name": "Plan Api Ltd"
    }).json()["establishment"]["id"]
    test_db.add(AdvanceCreditLedger(
        establishment_id=est_id, entry_type="topup", amount=100.0,
        status="pending_verification", submitted_utr="PLANAPI-DUP2",
    ))
    test_db.commit()
    res = consultant_a.post("/api/my-plan/submit-utr", json={"months": 1, "utr": "PLANAPI-DUP2"})
    assert res.status_code == 400

    # A UTR already used on a plan row blocks the advance-credit and fee flows (shared guard).
    consultant_b.set_establishment(est_id)
    res = consultant_b.post("/api/establishment/advance-payment/submit-utr", json={"amount": 50.0, "utr": "PLANAPI-DUP1"})
    assert res.status_code == 400

    # Only one plan row exists (the rejected submissions created nothing).
    assert test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.submitted_utr.like("PLANAPI%")).count() == 1

    from webapp.app import _utr_already_submitted
    assert _utr_already_submitted(test_db, "PLANAPI-DUP1") is True
    assert _utr_already_submitted(test_db, "PLANAPI-NEVER") is False


def test_create_link_needs_mobile(consultant_a, test_db, mock_cashfree):
    _set_plan(test_db, consultant_a.user_id, 2000.0)
    user = test_db.query(User).filter(User.id == consultant_a.user_id).first()
    original_mobile = user.mobile
    user.mobile = ""
    test_db.commit()
    try:
        res = consultant_a.post("/api/my-plan/create-link", json={"months": 1})
        assert res.status_code == 400
        assert "mobile" in res.json()["detail"].lower()
        assert mock_cashfree == []
        assert test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.user_id == consultant_a.user_id).count() == 0
    finally:
        user = test_db.query(User).filter(User.id == consultant_a.user_id).first()
        user.mobile = original_mobile
        test_db.commit()


def test_other_user_cannot_see_my_plan_rows(consultant_a, consultant_b, test_db, mock_cashfree, monkeypatch):
    _set_plan(test_db, consultant_a.user_id, 2000.0)
    _set_plan(test_db, consultant_b.user_id, 2000.0)
    order_id = consultant_a.post("/api/my-plan/create-link", json={"months": 2}).json()["order_id"]

    assert consultant_b.get("/api/my-plan").json()["payments"] == []

    # B cannot poll/confirm A's order, even if the order id leaks.
    monkeypatch.setattr(app_module.cashfree_client, "get_payment_status",
                        lambda oid: {"paid": True, "payment_ref": "STOLEN"})
    assert consultant_b.post("/api/my-plan/refresh-status", json={"order_id": order_id}).status_code == 404
    test_db.expire_all()
    row = test_db.query(ConsultantPlanPayment).filter(ConsultantPlanPayment.cashfree_order_id == order_id).one()
    assert row.status == "pending"
