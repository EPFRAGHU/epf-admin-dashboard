"""
Flat Fee Billing Mode — Tests
==============================
Covers the four verification criteria from the feature spec:
1. Switching an establishment to flat_fee (₹5,000) generates SubscriptionFee rows
   at exactly ₹5,000/month regardless of headcount.
2. Switching back to per_employee resumes tiered/custom calculation for future
   months only; already-paid flat-fee months stay frozen at their billed amount.
3. Consultant/Employer accounts have no reachable way to set billing_mode or
   flat_fee_amount.
4. Download-locking, Cashfree payment links, advance credit, and trial periods
   all continue to work identically regardless of billing mode.
"""

import pytest

from webapp import cashfree_client as cf

requires_cashfree = pytest.mark.skipif(
    not cf.is_configured(), reason="Cashfree sandbox credentials not configured"
)


def _months(superadmin_session, est_id, year="2026-27"):
    return superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year={year}").json()["months"]


def test_flat_fee_generates_fixed_amount_regardless_of_headcount(superadmin_session, consultant_a):
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", "code": "FLAT001", "name": "Flat Fee Corp"})
    assert res.status_code == 200
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})

    for i in range(1, 6):
        consultant_a.post("/api/employees", json={
            "member_id": f"FLAT001{i:03d}", "name": f"Employee {i}", "uan": f"70000000{i:04d}"
        })

    # Mar: 5 employees. Apr: 1 employee. May: 0 employees.
    for i in range(1, 6):
        consultant_a.post("/api/years/2026-27/wages", json={
            "member_id": f"FLAT001{i:03d}", "wages": [15000.0] + [0.0] * 11
        })
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "FLAT001001", "wages": [15000.0, 15000.0] + [0.0] * 10
    })

    # Switch to flat_fee ₹5000.
    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })
    assert res.status_code == 200
    assert res.json()["billing_mode"] == "flat_fee"
    assert res.json()["flat_fee_amount"] == 5000.0

    months = _months(superadmin_session, est_id)
    mar = next(m for m in months if m["month"] == "Mar")
    apr = next(m for m in months if m["month"] == "Apr")
    may = next(m for m in months if m["month"] == "May")

    assert mar["employee_count"] == 5
    assert mar["amount_due"] == 5000.0
    assert mar["billing_mode"] == "flat_fee"

    assert apr["employee_count"] == 1
    assert apr["amount_due"] == 5000.0

    # Even a month with zero employees is billed the flat fee -- headcount-independent.
    assert may["employee_count"] == 0
    assert may["amount_due"] == 5000.0

    # resolve_rate() never ran for this establishment -- rate_applied stays null for flat rows.
    assert mar["rate_applied"] is None
    assert "flat" in mar["billing_display"].lower()

    # Activity log records the switch.
    logs = superadmin_session.get("/api/admin/activity-log?action_type=billing_mode_changed").json()["logs"]
    assert any("FLAT001" in l["description"] for l in logs)


def test_switch_back_to_per_employee_freezes_paid_flat_months(superadmin_session, consultant_a):
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", 
        "code": "FLAT002", "name": "Flat Then Tiered Corp", "custom_rate_per_employee": 10.0
    })
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    for i in range(1, 4):
        consultant_a.post("/api/employees", json={
            "member_id": f"FLAT002{i:03d}", "name": f"Employee {i}", "uan": f"71000000{i:04d}"
        })
        consultant_a.post("/api/years/2026-27/wages", json={
            "member_id": f"FLAT002{i:03d}", "wages": [15000.0, 15000.0] + [0.0] * 10
        })

    # Switch to flat_fee ₹5000 and pay Mar.
    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })
    assert res.status_code == 200

    # Trigger a sync first so Mar's row is actually created under flat_fee (amount_due=5000)
    # before it gets marked paid -- otherwise "mark paid" would create it from column
    # defaults (per_employee, ₹0), which isn't what's being tested here.
    _months(superadmin_session, est_id)

    res = superadmin_session.post(f"/api/admin/establishments/{est_id}/subscription-fees", json={
        "financial_year": "2026-27",
        "fees": [{"month": "Mar", "is_paid": True, "paid_date": "15-04-2026", "payment_reference": "UPI/FLAT/001"}]
    })
    assert res.status_code == 200

    months = _months(superadmin_session, est_id)
    mar_paid = next(m for m in months if m["month"] == "Mar")
    assert mar_paid["amount_due"] == 5000.0
    assert mar_paid["is_paid"] is True
    apr_before = next(m for m in months if m["month"] == "Apr")
    assert apr_before["amount_due"] == 5000.0
    assert apr_before["is_paid"] is False

    # Switch back to per_employee (establishment rate pinned at ₹10).
    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "per_employee"
    })
    assert res.status_code == 200
    assert res.json()["billing_mode"] == "per_employee"
    assert res.json()["flat_fee_amount"] is None

    months = _months(superadmin_session, est_id)

    # Mar was already paid as a flat-fee month -- stays frozen at ₹5000, untouched by the switch.
    mar_after = next(m for m in months if m["month"] == "Mar")
    assert mar_after["amount_due"] == 5000.0
    assert mar_after["billing_mode"] == "flat_fee"
    assert mar_after["is_paid"] is True

    # Apr was never paid -- it's a "future" month and live-adopts the new mode:
    # 3 employees * ₹10 = ₹30.
    apr_after = next(m for m in months if m["month"] == "Apr")
    assert apr_after["amount_due"] == 30.0
    assert apr_after["billing_mode"] == "per_employee"
    assert apr_after["rate_applied"] == 10.0


def test_flat_fee_endpoint_requires_positive_amount_and_valid_mode(superadmin_session, consultant_a):
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", "code": "FLAT003", "name": "Bad Input Corp"})
    est_id = res.json()["establishment"]["id"]

    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={"billing_mode": "bogus"})
    assert res.status_code == 400

    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={"billing_mode": "flat_fee"})
    assert res.status_code == 400

    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": -100
    })
    assert res.status_code == 400

    res = superadmin_session.put("/api/admin/establishments/999999/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 1000
    })
    assert res.status_code == 404


def test_consultant_cannot_set_billing_mode_through_any_reachable_endpoint(superadmin_session, consultant_a):
    # 1. Creation payload with billing fields is silently ignored -- default stays per_employee.
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", 
        "code": "FLAT004", "name": "Sneaky Corp",
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })
    assert res.status_code == 200
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)

    months = _months(superadmin_session, est_id)
    assert all(m["billing_mode"] == "per_employee" for m in months)

    # 2. Establishment self-edit payload with billing fields is also silently ignored.
    res = consultant_a.put("/api/establishment", json={
        "coverage_date": "01-04-2026", "code": "FLAT004", "name": "Sneaky Corp",
        "billing_mode": "flat_fee", "flat_fee_amount": 9999.0
    })
    assert res.status_code == 200

    months = _months(superadmin_session, est_id)
    assert all(m["billing_mode"] == "per_employee" for m in months)

    # 3. The dedicated superadmin-only endpoint rejects a consultant caller outright.
    res = consultant_a.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })
    assert res.status_code == 403

    # Establishment is untouched.
    months = _months(superadmin_session, est_id)
    assert all(m["billing_mode"] == "per_employee" for m in months)


def test_flat_fee_download_gating(superadmin_session, consultant_a):
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", "code": "FLAT005", "name": "Flat Gating Corp"})
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "FLAT005001", "name": "Emp One", "uan": "720000000001"})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "FLAT005001", "wages": [15000.0] + [0.0] * 11})

    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })
    assert res.status_code == 200

    # Unpaid + overdue -> 402, exactly as per_employee mode would behave.
    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 402

    # Superadmin bypasses regardless of billing mode.
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200

    # Manually marking the flat-fee month paid unlocks the download immediately.
    res = superadmin_session.post(f"/api/admin/establishments/{est_id}/subscription-fees", json={
        "financial_year": "2026-27",
        "fees": [{"month": "Mar", "is_paid": True, "paid_date": "15-04-2026", "payment_reference": "UPI/FLAT/002"}]
    })
    assert res.status_code == 200
    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200


def test_flat_fee_advance_credit_auto_applies(superadmin_session, consultant_a):
    """Advance credit added BEFORE a flat-fee month's SubscriptionFee row exists auto-applies
    the moment the row is first created (mirrors the per_employee advance-credit behavior)."""
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", "code": "FLAT008", "name": "Flat Advance Corp"})
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})

    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })
    assert res.status_code == 200

    # Advance payment recorded before any SubscriptionFee row exists for this establishment/year.
    res = superadmin_session.post(f"/api/admin/establishments/{est_id}/advance-payment", json={
        "amount": 5000.0, "payment_reference": "UPI/FLAT/ADV"
    })
    assert res.status_code == 200
    assert res.json()["advance_credit_balance"] == 5000.0

    # First wage entry triggers the first sync -> creates Mar's row fresh -> credit auto-applies.
    consultant_a.post("/api/employees", json={"member_id": "FLAT008001", "name": "Emp One", "uan": "750000000001"})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "FLAT008001", "wages": [15000.0] + [0.0] * 11})

    months = _months(superadmin_session, est_id)
    mar = next(m for m in months if m["month"] == "Mar")
    assert mar["is_paid"] is True
    assert mar["amount_due"] == 5000.0
    assert mar["payment_reference"] == "Applied from advance credit"
    assert superadmin_session.get(f"/api/admin/establishments/{est_id}/advance-credit").json()["advance_credit_balance"] == 0.0

    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200

    # A later month with no remaining credit is unpaid as normal.
    apr = next(m for m in months if m["month"] == "Apr")
    assert apr["is_paid"] is False
    assert apr["amount_due"] == 5000.0


def test_flat_fee_trial_bypasses_gating(superadmin_session, consultant_a):
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", "code": "FLAT006", "name": "Flat Trial Corp"})
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "FLAT006001", "name": "Emp One", "uan": "730000000001"})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "FLAT006001", "wages": [15000.0] + [0.0] * 11})

    superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 5000.0
    })

    # Blocked before the trial starts.
    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 402

    # Start a trial far in the future -- bypasses gating identically to per_employee mode.
    res = superadmin_session.put(f"/api/admin/establishments/{est_id}/trial", json={"trial_ends_on": "2099-12-31"})
    assert res.status_code == 200

    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200


@requires_cashfree
def test_flat_fee_cashfree_link_uses_flat_amount(superadmin_session, consultant_a):
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026", "code": "FLAT007", "name": "Flat Cashfree Corp"})
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "FLAT007001", "name": "Emp One", "uan": "740000000001"})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "FLAT007001", "wages": [15000.0] + [0.0] * 11})

    superadmin_session.put(f"/api/admin/establishments/{est_id}/billing-mode", json={
        "billing_mode": "flat_fee", "flat_fee_amount": 4321.0
    })
    superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"mobile": "9876543299"})

    res = superadmin_session.post(
        f"/api/admin/establishments/{est_id}/subscription-fees/create-link",
        json={"financial_year": "2026-27", "month": "Mar"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["link_url"].startswith("https://")
