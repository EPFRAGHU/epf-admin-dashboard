"""Self-service profile editing (PUT /api/me) -- lets a consultant/employer/superadmin
update their OWN name/mobile/email once so it sticks everywhere from then on, notably
the customer_details sent to Cashfree on every payment link/order this account
generates."""
import pytest


def test_consultant_can_update_own_name_mobile_email(consultant_a):
    res = consultant_a.put("/api/me", json={
        "name": "Real Consultant Name", "mobile": "9123456780", "email": "realname@testepf.com",
    })
    assert res.status_code == 200, res.text
    data = res.json()["user"]
    assert data["name"] == "Real Consultant Name"
    assert data["mobile"] == "9123456780"
    assert data["email"] == "realname@testepf.com"

    # Persisted -- a fresh GET /api/auth/me reflects it, not just the PUT response.
    me = consultant_a.get("/api/auth/me").json()["user"]
    assert me["name"] == "Real Consultant Name"
    assert me["mobile"] == "9123456780"
    assert me["email"] == "realname@testepf.com"


def test_cannot_set_empty_name(consultant_a):
    res = consultant_a.put("/api/me", json={"name": "   "})
    assert res.status_code == 400
    assert "name" in res.json()["detail"].lower()


def test_cannot_set_empty_email(consultant_a):
    res = consultant_a.put("/api/me", json={"email": "   "})
    assert res.status_code == 400
    assert "email" in res.json()["detail"].lower()


def test_cannot_take_another_users_email(consultant_a, consultant_b):
    res = consultant_a.put("/api/me", json={"email": "consultant_b@testepf.com"})
    assert res.status_code == 400
    assert "already in use" in res.json()["detail"].lower()

    # Consultant A's own email must be untouched by the rejected attempt.
    me = consultant_a.get("/api/auth/me").json()["user"]
    assert me["email"] == "consultant_a@testepf.com"


def test_partial_update_leaves_other_fields_unchanged(consultant_a):
    consultant_a.put("/api/me", json={"mobile": "9000000001"})
    me = consultant_a.get("/api/auth/me").json()["user"]
    assert me["mobile"] == "9000000001"
    assert me["name"] == "Consultant Alpha"  # untouched -- name wasn't part of this request


def test_cannot_change_admin_only_fields_via_self_service_endpoint(consultant_a, superadmin_session):
    """MyProfileUpdateIn has no is_active/custom_rate_per_employee/max_establishments/
    password fields at all -- passing them should just be silently ignored by Pydantic
    (extra fields dropped), never applied."""
    res = consultant_a.put("/api/me", json={
        "name": "Still Me", "is_active": False, "custom_rate_per_employee": 999, "password": "hacked123",
    })
    assert res.status_code == 200, res.text

    # Confirm via the superadmin view that none of the admin-only fields moved.
    users = superadmin_session.get("/api/admin/users").json()["users"]
    me_as_admin_sees = next(u for u in users if u["email"] == "consultant_a@testepf.com")
    assert me_as_admin_sees["is_active"] is True
    assert me_as_admin_sees.get("custom_rate_per_employee") in (None, 0)
