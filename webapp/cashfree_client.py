"""
Cashfree integration — shared client for both the per-month SubscriptionFee "Pay Now"
flow and the Advance Credit top-up flow.

Primarily uses Cashfree's Payment Links API (POST /pg/links) -- a payment link is a
shareable URL, which matches how both flows are meant to be used (superadmin or
consultant generates a link, shares/opens it, pays, webhook confirms). Falls back to
the Orders/Checkout API (POST /pg/orders + the JS SDK's checkout()) via
create_payment_link_or_order() when Payment Links itself isn't enabled/approved for
this account -- see that function's docstring for why this fallback exists.
"""

import os
import hmac
import hashlib
import base64
import time
import requests

CASHFREE_APP_ID = os.environ.get("CASHFREE_APP_ID", "")
CASHFREE_SECRET_KEY = os.environ.get("CASHFREE_SECRET_KEY", "")
CASHFREE_ENV = os.environ.get("CASHFREE_ENV", "SANDBOX").strip().upper()
CASHFREE_API_VERSION = os.environ.get("CASHFREE_API_VERSION", "2023-08-01")

BASE_URL = (
    "https://api.cashfree.com/pg"
    if CASHFREE_ENV == "PRODUCTION"
    else "https://sandbox.cashfree.com/pg"
)


class CashfreeConfigError(RuntimeError):
    """Raised when Cashfree credentials are missing at call time."""


def is_configured() -> bool:
    return bool(CASHFREE_APP_ID and CASHFREE_SECRET_KEY)


def _headers() -> dict:
    if not is_configured():
        raise CashfreeConfigError(
            "Cashfree is not configured — set CASHFREE_APP_ID and CASHFREE_SECRET_KEY."
        )
    return {
        "x-client-id": CASHFREE_APP_ID,
        "x-client-secret": CASHFREE_SECRET_KEY,
        "x-api-version": CASHFREE_API_VERSION,
        "Content-Type": "application/json",
    }


def create_payment_link(
    link_id: str,
    amount: float,
    purpose: str,
    customer_phone: str,
    customer_name: str = "",
    customer_email: str = "",
    notify_url: str = None,
    return_url: str = None,
) -> dict:
    """Creates a Cashfree Payment Link. Returns the raw Cashfree response dict
    (notably `link_url`, `link_status`, `cf_link_id`). Raises requests.HTTPError
    on a non-2xx response."""
    body = {
        "link_id": link_id,
        "link_amount": round(float(amount), 2),
        "link_currency": "INR",
        "link_purpose": purpose[:500],
        "customer_details": {
            "customer_phone": customer_phone,
            "customer_name": customer_name or "",
            "customer_email": customer_email or "",
        },
        "link_notify": {"send_sms": False, "send_email": bool(customer_email)},
    }
    meta = {}
    if notify_url:
        meta["notify_url"] = notify_url
    if return_url:
        meta["return_url"] = return_url
    if meta:
        body["link_meta"] = meta

    resp = requests.post(f"{BASE_URL}/links", json=body, headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_payment_link_status(link_id: str) -> dict:
    """Fetches current status of a payment link (used by the manual 'refresh' button
    when a webhook hasn't arrived yet). Raises requests.HTTPError on non-2xx."""
    resp = requests.get(f"{BASE_URL}/links/{link_id}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def create_order(
    order_id: str,
    amount: float,
    purpose: str,
    customer_phone: str,
    customer_name: str = "",
    customer_email: str = "",
    return_url: str = None,
) -> dict:
    """Creates a Cashfree Order (POST /pg/orders) -- the Orders/Checkout API, not
    Payment Links. Returns the raw Cashfree response dict (notably `payment_session_id`,
    `order_status`). Unlike a payment link, this doesn't give a directly-shareable URL --
    the caller must load Cashfree's JS SDK and call cashfree.checkout() with the
    payment_session_id to actually open a checkout page. Raises requests.HTTPError on a
    non-2xx response."""
    body = {
        "order_id": order_id,
        "order_amount": round(float(amount), 2),
        "order_currency": "INR",
        "customer_details": {
            # Orders API requires a customer_id (Payment Links doesn't) -- reuse order_id
            # since this app doesn't track a separate persistent Cashfree customer id.
            "customer_id": order_id,
            "customer_phone": customer_phone,
            "customer_name": customer_name or "Customer",
            "customer_email": customer_email or "",
        },
    }
    if return_url:
        body["order_meta"] = {"return_url": return_url}
    # `purpose` is deliberately NOT sent as order_tags.checkout_context: that field has a
    # strict 100-char limit and rejects any HTML/URL/line-break/emoji (confirmed live --
    # this app's purpose strings, which embed establishment names, tripped
    # "order_tags_invalid" in production). It's a purely cosmetic checkout-page
    # description, not required for the order to work, so it's simplest and most robust
    # to just not send it rather than sanitize business names against an unpredictable
    # validation rule.

    resp = requests.post(f"{BASE_URL}/orders", json=body, headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_order_status(order_id: str) -> dict:
    """Fetches current status of an order (GET /pg/orders/{order_id}). An order is
    successful when order_status == 'PAID'. Raises requests.HTTPError on non-2xx."""
    resp = requests.get(f"{BASE_URL}/orders/{order_id}", headers=_headers(), timeout=20)
    resp.raise_for_status()
    return resp.json()


def _is_link_creation_not_enabled(err: "requests.HTTPError") -> bool:
    """True only for the specific 'Payment Links API isn't approved for this account'
    error (type: feature_not_enabled) -- every other failure (bad request, auth error,
    rate limit, network issue surfaced as HTTPError) should propagate normally rather
    than silently triggering a fallback to a completely different API."""
    if err.response is None:
        return False
    try:
        body = err.response.json()
    except Exception:
        return False
    return body.get("type") == "feature_not_enabled"


def create_payment_link_or_order(
    link_id: str,
    amount: float,
    purpose: str,
    customer_phone: str,
    customer_name: str = "",
    customer_email: str = "",
    notify_url: str = None,
    return_url: str = None,
) -> dict:
    """Tries the Payment Links API first; if Cashfree specifically rejects it because
    Payment Links isn't enabled/approved for this account yet (type: feature_not_enabled
    -- confirmed via a real production API call on 2026-08-26, error:
    "link_creation_api is not enabled or approved"), transparently falls back to
    creating an Order instead (POST /pg/orders, confirmed working on the same account).
    Any OTHER error from either API propagates as a normal requests.HTTPError -- this
    only masks that one specific, known gap.

    Returns a dict with exactly one of "link_url" (Payment Links path -- a real,
    directly shareable Cashfree URL) or "payment_session_id" (Orders path -- must be
    used with the Cashfree JS SDK client-side) set; the other is None. Also returns
    "method": "link" or "order" so callers -- get_payment_status() below, and the
    /pay/{order_id} redirect route in app.py -- know which Cashfree object this
    order_id actually is without needing to guess or store it separately."""
    try:
        resp = create_payment_link(
            link_id, amount, purpose, customer_phone, customer_name, customer_email,
            notify_url=notify_url, return_url=return_url,
        )
        return {"method": "link", "order_id": link_id, "link_url": resp.get("link_url"), "payment_session_id": None}
    except requests.HTTPError as e:
        if not _is_link_creation_not_enabled(e):
            raise
        resp = create_order(
            link_id, amount, purpose, customer_phone, customer_name, customer_email,
            return_url=return_url,
        )
        return {"method": "order", "order_id": link_id, "link_url": None, "payment_session_id": resp.get("payment_session_id")}


def get_payment_status(order_id: str) -> dict:
    """Normalized status check that works regardless of whether `order_id` was created
    via Payment Links or the Orders-API fallback -- tries the Payment Links status
    endpoint first, and if that 404s (this id was never a real payment link), falls back
    to the Orders status endpoint. Returns {"paid": bool, "payment_ref": str} either way,
    so the four refresh-status endpoints and the webhook's confirmation logic never need
    to know or care which underlying API actually holds this payment."""
    try:
        resp = get_payment_link_status(order_id)
        return {"paid": resp.get("link_status") == "PAID", "payment_ref": str(resp.get("cf_link_id") or order_id)}
    except requests.HTTPError as e:
        if e.response is None or e.response.status_code != 404:
            raise
        resp = get_order_status(order_id)
        return {"paid": resp.get("order_status") == "PAID", "payment_ref": order_id}


def verify_webhook_signature(timestamp: str, raw_body: bytes, signature: str) -> bool:
    """Cashfree webhook signature scheme: base64(HMAC-SHA256(secret_key, timestamp + raw_body)),
    compared against the x-webhook-signature header. Uses the raw (unparsed) body."""
    if not CASHFREE_SECRET_KEY or not timestamp or not signature:
        return False
    body_str = raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else raw_body
    signed_payload = f"{timestamp}{body_str}".encode("utf-8")
    computed = base64.b64encode(
        hmac.new(CASHFREE_SECRET_KEY.encode("utf-8"), signed_payload, hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(computed, signature)


def new_order_id(prefix: str, entity_id) -> str:
    """Generates a Cashfree link_id with a prefix the webhook handler uses to route
    ('sub_' for per-month SubscriptionFee payments, 'adv_' for Advance Credit top-ups)."""
    return f"{prefix}_{entity_id}_{int(time.time())}"
