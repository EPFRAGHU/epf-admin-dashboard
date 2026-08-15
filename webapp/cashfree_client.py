"""
Cashfree Payment Links integration — shared client for both the per-month
SubscriptionFee "Pay Now" flow and the Advance Credit top-up flow.

Uses Cashfree's Payment Links API (POST /pg/links), not the Orders/Checkout
API — a payment link is a shareable URL, which matches how both flows are
meant to be used (superadmin or consultant generates a link, shares/opens
it, pays, webhook confirms).
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
