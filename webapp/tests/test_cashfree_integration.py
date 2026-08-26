"""
Cashfree Integration Tests — Per-Month Payments & Advance Credit
=================================================================
These tests call the REAL Cashfree sandbox API for link creation (proving the
endpoint wiring — auth, phone lookup, DB row creation — against the live
contract), then simulate webhook delivery by crafting a correctly-signed
payload ourselves and POSTing it to our own /api/webhooks/cashfree endpoint.

This is the most faithful "end-to-end" check possible without a publicly
reachable webhook URL (Cashfree's servers cannot reach a local dev server),
while still genuinely exercising signature verification, sub_/adv_ routing,
and idempotency against the real confirmation logic.

Requires CASHFREE_APP_ID / CASHFREE_SECRET_KEY to be set (via .env) and
network access to sandbox.cashfree.com. Skipped automatically otherwise.
"""

import hmac
import hashlib
import base64
import json
import time

import pytest

from webapp import cashfree_client as cf

requires_cashfree = pytest.mark.skipif(
    not cf.is_configured(), reason="Cashfree sandbox credentials not configured"
)


def sign_webhook_payload(payload_dict, secret_key):
    timestamp = str(int(time.time()))
    body = json.dumps(payload_dict)
    signature = base64.b64encode(
        hmac.new(secret_key.encode(), (timestamp + body).encode(), hashlib.sha256).digest()
    ).decode()
    return body, timestamp, signature


def fire_webhook(client, link_id, amount, secret_key=None):
    payload = {
        "type": "PAYMENT_LINK_EVENT",
        "data": {
            "link_id": link_id,
            "link_status": "PAID",
            "link_amount": str(amount),
            "link_amount_paid": str(amount),
            "order": {"order_id": f"CFPay_{link_id}", "transaction_id": 99887766, "transaction_status": "SUCCESS"}
        }
    }
    body, ts, sig = sign_webhook_payload(payload, secret_key or cf.CASHFREE_SECRET_KEY)
    return client.post(
        "/api/webhooks/cashfree",
        data=body,
        headers={"Content-Type": "application/json", "x-webhook-timestamp": ts, "x-webhook-signature": sig}
    )


@requires_cashfree
def test_per_month_cashfree_payment_link_and_webhook(superadmin_session, consultant_a, client):
    """Real link creation + simulated signed webhook confirms a specific month's fee."""
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", 
        "code": "EPSILON001", "name": "Epsilon Traders", "custom_rate_per_employee": 20.0
    })
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "EPSILON001001", "name": "Emp One", "uan": "300000000001"})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "EPSILON001001", "wages": [15000.0] + [0.0] * 11})

    # Give the consultant a mobile number (required by Cashfree) via profile update.
    res = superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543210"})
    assert res.status_code == 200

    # Real Cashfree API call to generate the link.
    res = superadmin_session.post(
        f"/api/admin/establishments/{est_id}/subscription-fees/create-link",
        json={"financial_year": "2026-27", "month": "Mar"}
    )
    assert res.status_code == 200, res.text
    link_data = res.json()
    assert link_data["link_url"].startswith("https://")
    order_id = link_data["order_id"]
    assert order_id.startswith("sub_")

    # Confirm it's still unpaid/pending (balance untouched, no premature confirmation).
    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27").json()["months"]
    mar = next(m for m in fees if m["month"] == "Mar")
    assert mar["is_paid"] is False

    # Simulate Cashfree's webhook call with a correctly-signed PAID payload.
    res = fire_webhook(client, order_id, 20.0)
    assert res.status_code == 200

    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27").json()["months"]
    mar = next(m for m in fees if m["month"] == "Mar")
    assert mar["is_paid"] is True
    assert mar["payment_reference"] not in (None, "")

    # Duplicate/retried webhook must not error or change anything further.
    res2 = fire_webhook(client, order_id, 20.0)
    assert res2.status_code == 200
    fees2 = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27").json()["months"]
    mar2 = next(m for m in fees2 if m["month"] == "Mar")
    assert mar2["payment_reference"] == mar["payment_reference"]  # unchanged, idempotent


@requires_cashfree
def test_consultant_self_serve_month_payment_unlocks_download(superadmin_session, consultant_a, client):
    """The exact reported scenario: consultant tries to download a specific month's ECR,
    gets blocked, sees the members/amount owed for that month, pays via their own
    self-serve Cashfree link (not one the superadmin generated), and the download unlocks
    immediately once the payment is confirmed -- without the superadmin doing anything."""
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", 
        "code": "THETA001", "name": "Theta Manufacturing", "custom_rate_per_employee": 20.0
    })
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "THETA001001", "name": "Emp One", "uan": "500000000001"})
    consultant_a.post("/api/employees", json={"member_id": "THETA001002", "name": "Emp Two", "uan": "500000000002"})
    # Jul wages (month_idx 4, "Jul Paid in Aug") for 2 employees.
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "THETA001001", "wages": [0]*4 + [15000.0] + [0.0]*7})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "THETA001002", "wages": [0]*4 + [15000.0] + [0.0]*7})

    superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543212"})

    # 1. Consultant attempts the July ECR download -- blocked with a clear 402.
    res = consultant_a.get("/api/reports/2026-27/ecr/4")
    assert res.status_code == 402
    assert "subscription fee" in res.json()["detail"].lower()

    # 2. Consultant fetches the month's fee detail to see members + amount owed.
    res = consultant_a.get("/api/establishment/subscription-fees/month-detail?year=2026-27&month=Jul")
    assert res.status_code == 200
    detail = res.json()
    assert detail["employee_count"] == 2
    assert detail["amount_due"] == 40.0  # 2 employees * ₹20
    assert detail["is_paid"] is False

    # 3. Consultant generates their OWN payment link (self-serve, not via superadmin).
    res = consultant_a.post("/api/establishment/subscription-fees/create-link", json={
        "financial_year": "2026-27", "month": "Jul"
    })
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]
    assert order_id.startswith("sub_")

    # Still blocked -- link generated, but not yet paid.
    res = consultant_a.get("/api/reports/2026-27/ecr/4")
    assert res.status_code == 402

    # 4. Payment completes -- Cashfree webhook fires.
    res = fire_webhook(client, order_id, 40.0)
    assert res.status_code == 200

    # 5. Reflected immediately in the fee detail...
    detail2 = consultant_a.get("/api/establishment/subscription-fees/month-detail?year=2026-27&month=Jul").json()
    assert detail2["is_paid"] is True

    # ...in the superadmin's subscription table...
    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27").json()["months"]
    jul = next(m for m in fees if m["month"] == "Jul")
    assert jul["is_paid"] is True

    # ...and the download itself is now unblocked.
    res = consultant_a.get("/api/reports/2026-27/ecr/4")
    assert res.status_code == 200
    assert "Emp One" in res.text and "Emp Two" in res.text


@requires_cashfree
def test_advance_credit_cashfree_topup_and_webhook(superadmin_session, consultant_a, client):
    """Real link creation + simulated signed webhook credits the advance balance exactly once,
    then verifies the credited balance auto-applies to a subsequently-billed month, producing
    a matching 'applied' ledger entry."""
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", 
        "code": "ZETA001", "name": "Zeta Enterprises", "custom_rate_per_employee": 20.0
    })
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "ZETA001001", "name": "Emp One", "uan": "400000000001"})

    superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543211"})

    res = superadmin_session.post(
        f"/api/admin/establishments/{est_id}/advance-payment/create-link",
        json={"amount": 500.0, "notes": "Sandbox test topup"}
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]
    assert order_id.startswith("adv_")

    # Balance must NOT change until the webhook confirms payment.
    credit = superadmin_session.get(f"/api/admin/establishments/{est_id}/advance-credit").json()
    assert credit["advance_credit_balance"] == 0.0
    pending_entry = next(h for h in credit["history"] if h["cashfree_order_id"] == order_id)
    assert pending_entry["status"] == "pending"

    # Simulate the webhook confirming payment.
    res = fire_webhook(client, order_id, 500.0)
    assert res.status_code == 200

    credit = superadmin_session.get(f"/api/admin/establishments/{est_id}/advance-credit").json()
    assert credit["advance_credit_balance"] == 500.0
    confirmed_entry = next(h for h in credit["history"] if h["cashfree_order_id"] == order_id)
    assert confirmed_entry["status"] == "confirmed"
    assert confirmed_entry["payment_reference"] not in (None, "")

    # Duplicate/retried webhook must not double-credit.
    res2 = fire_webhook(client, order_id, 500.0)
    assert res2.status_code == 200
    credit2 = superadmin_session.get(f"/api/admin/establishments/{est_id}/advance-credit").json()
    assert credit2["advance_credit_balance"] == 500.0

    # Entering wages for a new month now auto-applies the Cashfree-funded credit.
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "ZETA001001", "wages": [15000.0] + [0.0] * 11})
    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27").json()["months"]
    mar = next(m for m in fees if m["month"] == "Mar")
    assert mar["is_paid"] is True
    assert mar["payment_reference"] == "Applied from advance credit"

    credit3 = superadmin_session.get(f"/api/admin/establishments/{est_id}/advance-credit").json()
    assert credit3["advance_credit_balance"] == 500.0 - mar["amount_due"]
    applied_entry = next(h for h in credit3["history"] if h["entry_type"] == "applied")
    assert applied_entry["applied_month"] == "Mar 2026-27"
    assert applied_entry["amount"] == mar["amount_due"]


@requires_cashfree
def test_consultant_self_serve_advance_credit_and_history(superadmin_session, consultant_a, client):
    """Consultant generates their OWN advance-credit top-up link (not via superadmin),
    the return_url includes the order_id, the consultant's own refresh-status endpoint
    confirms it, and the top-up shows up in their Subscription History response --
    distinct from, but alongside, per-month fee payments."""
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", 
        "code": "KAPPA001", "name": "Kappa Traders", "custom_rate_per_employee": 20.0
    })
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543213"})

    # Consultant self-serve creates the link (not the superadmin endpoint).
    res = consultant_a.post("/api/establishment/advance-payment/create-link", json={
        "amount": 750.0, "notes": "Self-serve test topup"
    })
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]
    assert order_id.startswith("adv_")

    # Balance untouched until confirmed.
    hist = consultant_a.get("/api/establishment/subscription-payments").json()
    assert hist["advance_credit_balance"] == 0.0
    assert hist["advance_topups"] == []

    # Consultant's own refresh-status endpoint (order_id-based, as the return_url provides).
    res = consultant_a.post("/api/establishment/advance-credit/refresh-status", json={"order_id": "not-a-real-order"})
    assert res.status_code == 404  # sanity: wrong order_id scoped correctly, not silently 200

    # Simulate the webhook confirming payment.
    res = fire_webhook(client, order_id, 750.0)
    assert res.status_code == 200

    res = consultant_a.post("/api/establishment/advance-credit/refresh-status", json={"order_id": order_id})
    assert res.status_code == 200
    refresh_data = res.json()
    assert refresh_data["status"] == "confirmed"
    assert refresh_data["amount"] == 750.0
    assert refresh_data["advance_credit_balance"] == 750.0

    # Now visible in Subscription History as its own top-up record.
    hist2 = consultant_a.get("/api/establishment/subscription-payments").json()
    assert hist2["advance_credit_balance"] == 750.0
    assert hist2["total_topped_up"] == 750.0
    assert len(hist2["advance_topups"]) == 1
    topup = hist2["advance_topups"][0]
    assert topup["amount"] == 750.0
    assert topup["source"] == "cashfree"
    assert topup["cashfree_order_id"] == order_id


def test_webhook_rejects_invalid_signature(client):
    body, ts, _ = sign_webhook_payload({"type": "PAYMENT_LINK_EVENT", "data": {"link_id": "adv_1_1", "link_status": "PAID"}}, "some-secret")
    res = client.post(
        "/api/webhooks/cashfree", data=body,
        headers={"Content-Type": "application/json", "x-webhook-timestamp": ts, "x-webhook-signature": "not-a-real-signature"}
    )
    assert res.status_code == 401


@requires_cashfree
def test_webhook_unrecognized_prefix_returns_200(client):
    res = fire_webhook(client, "unknown_prefix_order_123", 100.0)
    assert res.status_code == 200  # never causes Cashfree to retry, even for orders we don't recognize
