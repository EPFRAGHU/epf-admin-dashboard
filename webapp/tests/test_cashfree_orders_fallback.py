"""
Cashfree Orders-API Fallback Tests
===================================
Unlike test_cashfree_integration.py (which hits the real Cashfree sandbox), these
tests mock requests.post/requests.get directly so the fallback logic in
cashfree_client.create_payment_link_or_order()/get_payment_status() can be exercised
deterministically -- sandbox almost certainly doesn't reproduce the
"feature_not_enabled" error production hit, so there's no reliable way to trigger the
real fallback path against a live API in a test.
"""

import hashlib
import hmac
import base64
import json
import time
from unittest.mock import Mock, patch

import pytest
import requests

from webapp import cashfree_client as cf


def _mock_response(status_code, json_body, raises=False):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = json.dumps(json_body)
    if raises:
        err = requests.HTTPError(response=resp)
        resp.raise_for_status.side_effect = err
    else:
        resp.raise_for_status.return_value = None
    return resp


# ── cashfree_client unit tests ──────────────────────────────────────────────

@patch("webapp.cashfree_client.requests.post")
def test_create_payment_link_or_order_falls_back_on_feature_not_enabled(mock_post):
    link_fail = _mock_response(403, {
        "code": "PaymentLink_link_creation_api_failed",
        "message": "link_creation_api is not enabled or approved. Please reach out to care@cashfree.com.",
        "type": "feature_not_enabled",
    }, raises=True)
    order_ok = _mock_response(200, {
        "order_id": "sub_123_999", "order_status": "ACTIVE", "payment_session_id": "session_fake_abc",
    })
    mock_post.side_effect = [link_fail, order_ok]

    result = cf.create_payment_link_or_order(
        link_id="sub_123_999", amount=100.0, purpose="test", customer_phone="9999999999",
    )

    assert result == {"method": "order", "order_id": "sub_123_999", "link_url": None, "payment_session_id": "session_fake_abc"}
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[0].args[0].endswith("/links")
    assert mock_post.call_args_list[1].args[0].endswith("/orders")


@patch("webapp.cashfree_client.requests.post")
def test_create_order_does_not_send_order_tags(mock_post):
    """Regression guard: order_tags.checkout_context tripped a real production
    "order_tags_invalid" error (100-char limit, no HTML/URL/line-break/emoji) for
    ordinary purpose strings that embed an establishment name -- create_order() must
    not send order_tags at all, for any purpose string, long or short."""
    mock_post.return_value = _mock_response(200, {
        "order_id": "sub_1_1", "order_status": "ACTIVE", "payment_session_id": "session_fake",
    })

    long_purpose = "Software subscription fee — 3 month(s) (Mar 2026-27, Apr 2026-27, May 2026-27) — " \
                    "A Very Long Establishment Name Private Limited (ORXYZ0000001000)"
    cf.create_order(
        order_id="sub_1_1", amount=100.0, purpose=long_purpose, customer_phone="9999999999",
    )

    sent_body = mock_post.call_args.kwargs["json"]
    assert "order_tags" not in sent_body


@patch("webapp.cashfree_client.requests.post")
def test_create_payment_link_or_order_succeeds_without_fallback(mock_post):
    mock_post.return_value = _mock_response(200, {"link_id": "sub_1_1", "link_url": "https://payments.cashfree.com/links/abc", "link_status": "ACTIVE"})

    result = cf.create_payment_link_or_order(
        link_id="sub_1_1", amount=50.0, purpose="test", customer_phone="9999999999",
    )

    assert result == {"method": "link", "order_id": "sub_1_1", "link_url": "https://payments.cashfree.com/links/abc", "payment_session_id": None}
    assert mock_post.call_count == 1


@patch("webapp.cashfree_client.requests.post")
def test_create_payment_link_or_order_does_not_mask_unrelated_errors(mock_post):
    """Only the specific 'feature_not_enabled' error should trigger a fallback --
    anything else (bad request, auth failure, etc.) must propagate normally so it
    isn't silently hidden behind a confusing second API call."""
    mock_post.return_value = _mock_response(401, {
        "code": "authentication_error", "message": "Invalid credentials", "type": "authentication_error",
    }, raises=True)

    with pytest.raises(requests.HTTPError):
        cf.create_payment_link_or_order(
            link_id="sub_1_2", amount=50.0, purpose="test", customer_phone="9999999999",
        )
    assert mock_post.call_count == 1  # never attempted the Orders-API fallback


@patch("webapp.cashfree_client.requests.get")
def test_get_payment_status_uses_link_status_when_available(mock_get):
    mock_get.return_value = _mock_response(200, {"link_status": "PAID", "cf_link_id": "cflink_555"})

    result = cf.get_payment_status("sub_1_1")

    assert result == {"paid": True, "payment_ref": "cflink_555"}
    assert mock_get.call_args.args[0].endswith("/links/sub_1_1")


@patch("webapp.cashfree_client.requests.get")
def test_get_payment_status_falls_back_to_order_status_on_404(mock_get):
    link_404 = _mock_response(404, {"code": "link_not_found"}, raises=True)
    order_ok = _mock_response(200, {"order_id": "sub_123_999", "order_status": "PAID"})
    mock_get.side_effect = [link_404, order_ok]

    result = cf.get_payment_status("sub_123_999")

    assert result == {"paid": True, "payment_ref": "sub_123_999"}
    assert mock_get.call_count == 2
    assert mock_get.call_args_list[1].args[0].endswith("/orders/sub_123_999")


@patch("webapp.cashfree_client.requests.get")
def test_get_payment_status_does_not_mask_unrelated_errors(mock_get):
    mock_get.return_value = _mock_response(500, {"code": "internal_error"}, raises=True)

    with pytest.raises(requests.HTTPError):
        cf.get_payment_status("sub_1_3")
    assert mock_get.call_count == 1  # a 500 isn't "this wasn't a link", don't guess it's an order either


# ── Endpoint-level tests (mocking cashfree_client at the app.py call site) ──

def _new_establishment(consultant, code, name):
    res = consultant.post("/api/establishments", json={"coverage_date": "01-04-2026", "code": code, "name": name})
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def _fake_order_fallback(link_id, amount, purpose, customer_phone, customer_name="", customer_email="", notify_url=None, return_url=None):
    """Mirrors create_payment_link_or_order()'s real contract (order_id always echoes
    the given link_id) so DB rows and the /pay/{order_id} URL stay consistent, exactly
    as they would against the real API."""
    return {"method": "order", "order_id": link_id, "link_url": None, "payment_session_id": f"session_fake_{link_id}"}


@patch("webapp.app.cashfree_client.create_payment_link_or_order", side_effect=_fake_order_fallback)
def test_subscription_fee_link_creation_falls_back_to_pay_redirect_url(mock_create, superadmin_session, consultant_a):
    """When the Orders-API fallback is used, the endpoint must return this app's own
    /pay/{order_id} URL (not a raw, unusable payment_session_id) as link_url, and must
    persist cashfree_payment_session_id on the row so /pay/{order_id} can find it later."""
    est_id = _new_establishment(consultant_a, "FALLBACK0001", "Fallback Test Co")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "FB0001", "name": "Test Employee", "uan": "300111100001"})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "FB0001", "wages": [15000.0] + [0.0] * 11})

    res = superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543210"})
    assert res.status_code == 200

    res = superadmin_session.post(
        f"/api/admin/establishments/{est_id}/subscription-fees/create-link",
        json={"financial_year": "2026-27", "month": "Mar"}
    )
    assert res.status_code == 200, res.text
    data = res.json()
    order_id = data["order_id"]
    assert order_id.startswith("sub_")
    assert data["link_url"].endswith(f"/pay/{order_id}")  # our own redirect page, not a raw Cashfree URL

    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27").json()["months"]
    mar = next(m for m in fees if m["month"] == "Mar")
    assert mar["cashfree_order_id"] == order_id


@patch("webapp.app.cashfree_client.create_payment_link_or_order", side_effect=_fake_order_fallback)
def test_pay_redirect_route_serves_checkout_sdk_page_for_order_fallback(mock_create, superadmin_session, consultant_a, client):
    est_id = _new_establishment(consultant_a, "FALLBACK0002", "Fallback Test Co 2")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "FB0002", "name": "Test Employee 2", "uan": "300111100002"})
    # PAYMENT_MONTHS index 1 == "Apr" -- must match the month requested below. Seeded via
    # superadmin -- this test is about the payment-link/pay-redirect flow, not the
    # chronological entry gate, and the gate would otherwise reject writing directly
    # into Apr without Mar existing first.
    superadmin_session.set_establishment(est_id)
    res_seed = superadmin_session.post("/api/years/2026-27/wages", json={"member_id": "FB0002", "wages": [0.0, 15000.0] + [0.0] * 10})
    assert res_seed.status_code == 200, res_seed.text
    consultant_a.set_establishment(est_id)
    superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543210"})

    res = superadmin_session.post(
        f"/api/admin/establishments/{est_id}/subscription-fees/create-link",
        json={"financial_year": "2026-27", "month": "Apr"}
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    # /pay/{order_id} must be reachable with NO auth at all -- it's the link itself.
    pay_res = client.get(f"/pay/{order_id}", follow_redirects=False)
    assert pay_res.status_code == 200
    assert "sdk.cashfree.com/js/v3/cashfree.js" in pay_res.text
    assert f"session_fake_{order_id}" in pay_res.text


def test_pay_redirect_route_404s_for_unknown_order(client):
    res = client.get("/pay/sub_does_not_exist_123")
    assert res.status_code == 404


# ── Webhook: Orders-API payload shape ───────────────────────────────────────

def _sign(payload_dict, secret_key):
    timestamp = str(int(time.time()))
    body = json.dumps(payload_dict)
    signature = base64.b64encode(
        hmac.new(secret_key.encode(), (timestamp + body).encode(), hashlib.sha256).digest()
    ).decode()
    return body, timestamp, signature


@patch("webapp.app.cashfree_client.create_payment_link_or_order", side_effect=_fake_order_fallback)
def test_webhook_confirms_payment_from_orders_api_shaped_payload(mock_create, superadmin_session, consultant_a, client):
    """The Orders-API webhook shape (data.order.order_id + data.payment.payment_status)
    is structurally different from the Payment Links shape (data.link_id) -- this
    confirms the webhook handler's new branch correctly routes and confirms it."""
    est_id = _new_establishment(consultant_a, "FALLBACK0003", "Fallback Test Co 3")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "FB0003", "name": "Test Employee 3", "uan": "300111100003"})
    # PAYMENT_MONTHS index 2 == "May" -- must match the month requested below. Seeded via
    # superadmin -- this test is about the Orders-API webhook shape, not the
    # chronological entry gate, and the gate would otherwise reject writing directly
    # into May without Mar/Apr existing first.
    superadmin_session.set_establishment(est_id)
    res_seed = superadmin_session.post("/api/years/2026-27/wages", json={"member_id": "FB0003", "wages": [0.0, 0.0, 15000.0] + [0.0] * 9})
    assert res_seed.status_code == 200, res_seed.text
    consultant_a.set_establishment(est_id)
    superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543210"})

    res = superadmin_session.post(
        f"/api/admin/establishments/{est_id}/subscription-fees/create-link",
        json={"financial_year": "2026-27", "month": "May"}
    )
    assert res.status_code == 200, res.text
    order_id = res.json()["order_id"]

    payload = {
        "type": "PAYMENT_SUCCESS_WEBHOOK",
        "data": {
            "order": {"order_id": order_id},
            "payment": {"cf_payment_id": "cfpay_777888", "payment_status": "SUCCESS", "payment_amount": 20.0},
        },
    }
    test_secret = "test-cashfree-secret-for-webhook-signing"
    body, ts, sig = _sign(payload, test_secret)
    with patch.object(cf, "CASHFREE_SECRET_KEY", test_secret):
        webhook_res = client.post(
            "/api/webhooks/cashfree", data=body,
            headers={"Content-Type": "application/json", "x-webhook-timestamp": ts, "x-webhook-signature": sig},
        )
    assert webhook_res.status_code == 200, webhook_res.text

    fees = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27").json()["months"]
    may = next(m for m in fees if m["month"] == "May")
    assert may["is_paid"] is True
