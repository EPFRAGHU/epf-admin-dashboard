"""
Automated Test Suite for Software Subscription Fee Tracking & Download Enforcement
===================================================================================
Tests cover:
1. Exact ECR employee count and fee calculation (count × resolved_rate)
2. 3-tier rate precedence: Establishment override > Consultant override > Global default
3. Data entry non-blocking: Employees, wages, and remittances are NEVER blocked
4. Download gating (HTTP 402 Payment Required) for ECR txt/zip and statutory reports
5. Superadmin bypass: Superadmins can always download regardless of fee status
6. Unlocking on payment: Marking fee as paid immediately restores download access
7. Audit trail: Activity logs for 'rate_changed' and 'subscription_paid'
"""

import pytest


def test_subscription_fee_rate_hierarchy(superadmin_session, consultant_a):
    """Verify 3-tier rate precedence: Establishment override > Consultant override > Global default."""
    # 1. Check initial global default rate (10.0)
    res = superadmin_session.get("/api/admin/settings/subscription-rate")
    assert res.status_code == 200
    assert res.json()["default_rate"] == 10.0

    # 2. Consultant A creates Establishment Alpha
    res = consultant_a.post("/api/establishments", json={"code": "ALPHA001", "name": "Alpha Corp"})
    assert res.status_code == 200
    alpha_id = res.json()["establishment"]["id"]

    # 3. Query subscription fees for Alpha Corp — should resolve to global default (10.0)
    res = superadmin_session.get(f"/api/admin/establishments/{alpha_id}/subscription-fees?year=2026-27")
    assert res.status_code == 200
    data = res.json()
    assert data["rates"]["global_default"] == 10.0
    assert data["rates"]["consultant_override"] is None
    assert data["rates"]["establishment_override"] is None
    assert data["rates"]["effective_rate"] == 10.0

    # 4. Set Consultant A override to ₹18.0
    res = superadmin_session.put(f"/api/admin/users/{consultant_a.user_id}", json={"custom_rate_per_employee": 18.0})
    assert res.status_code == 200

    # Query subscription fees again — effective rate should now be 18.0
    res = superadmin_session.get(f"/api/admin/establishments/{alpha_id}/subscription-fees?year=2026-27")
    assert res.status_code == 200
    data = res.json()
    assert data["rates"]["consultant_override"] == 18.0
    assert data["rates"]["effective_rate"] == 18.0

    # 5. Set Establishment Alpha override to ₹15.0
    consultant_a.set_establishment(alpha_id)
    res = consultant_a.put("/api/establishment", json={"code": "ALPHA001", "name": "Alpha Corp", "custom_rate_per_employee": 15.0})
    assert res.status_code == 200

    # Query subscription fees again — effective rate should now be 15.0 (Establishment override takes top precedence)
    res = superadmin_session.get(f"/api/admin/establishments/{alpha_id}/subscription-fees?year=2026-27")
    assert res.status_code == 200
    data = res.json()
    assert data["rates"]["establishment_override"] == 15.0
    assert data["rates"]["effective_rate"] == 15.0


def test_fee_calculation_and_data_entry_unblocked(superadmin_session, consultant_a):
    """Verify fee calculation matches active ECR employee count and data entry is never blocked."""
    # Create establishment Beta
    res = consultant_a.post("/api/establishments", json={"code": "BETA001", "name": "Beta Industries", "custom_rate_per_employee": 10.0})
    assert res.status_code == 200
    beta_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(beta_id)

    # Add Year 2026-27
    res = consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res.status_code == 200

    # Add 3 employees to Master
    for i in range(1, 4):
        res = consultant_a.post("/api/employees", json={
            "member_id": f"BETA001{i:03d}",
            "name": f"Employee {i}",
            "uan": f"10000000000{i}"
        })
        assert res.status_code == 200

    # Enter wages for Month 0 (Mar) and Month 1 (Apr)
    # Emp 1: Mar=15000, Apr=15000
    # Emp 2: Mar=12000, Apr=0
    # Emp 3: Mar=0, Apr=10000
    wages_1 = [15000.0, 15000.0] + [0.0] * 10
    wages_2 = [12000.0, 0.0] + [0.0] * 10
    wages_3 = [0.0, 10000.0] + [0.0] * 10

    res = consultant_a.post("/api/years/2026-27/wages", json={"member_id": "BETA001001", "wages": wages_1})
    assert res.status_code == 200
    res = consultant_a.post("/api/years/2026-27/wages", json={"member_id": "BETA001002", "wages": wages_2})
    assert res.status_code == 200
    res = consultant_a.post("/api/years/2026-27/wages", json={"member_id": "BETA001003", "wages": wages_3})
    assert res.status_code == 200

    # Superadmin checks fees:
    # Month 0 (Mar): 2 employees > 0 => Fee = 2 * 10.0 = 20.0
    # Month 1 (Apr): 2 employees > 0 => Fee = 2 * 10.0 = 20.0
    # Month 2 (May): 0 employees > 0 => Fee = 0.0
    res = superadmin_session.get(f"/api/admin/establishments/{beta_id}/subscription-fees?year=2026-27")
    assert res.status_code == 200
    months = res.json()["months"]
    mar_fee = next(m for m in months if m["month"] == "Mar")
    apr_fee = next(m for m in months if m["month"] == "Apr")
    may_fee = next(m for m in months if m["month"] == "May")

    assert mar_fee["employee_count"] == 2
    assert mar_fee["amount_due"] == 20.0
    assert apr_fee["employee_count"] == 2
    assert apr_fee["amount_due"] == 20.0
    assert may_fee["employee_count"] == 0
    assert may_fee["amount_due"] == 0.0

    # Data entry: Adding remittances is NOT blocked
    remit_payload = {
        "remittances": [
            {"month_label": "Mar Paid in Apr", "trrn": "10126040001", "crrn": "CRN001", "credit_date": "15-04-2026"}
        ]
    }
    res = consultant_a.post("/api/years/2026-27/remittances/bulk", json=remit_payload)
    assert res.status_code == 200


def test_download_gating_402_and_superadmin_bypass(superadmin_session, consultant_a):
    """Verify downloads return 402 when subscription fee is unpaid/overdue, superadmin bypasses, and unlocks on payment."""
    # Setup establishment Gamma with wage entries in 2026-27
    res = consultant_a.post("/api/establishments", json={"code": "GAMMA001", "name": "Gamma Tech"})
    assert res.status_code == 200
    gamma_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(gamma_id)

    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "GAMMA001001", "name": "Rajesh Kumar", "uan": "100000000099"})
    # Mar wage entry
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "GAMMA001001", "wages": [15000.0] + [0.0]*11})

    # 1. Consultant attempts to download ECR for month 0 (Mar) — overdue and unpaid
    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 402
    assert "subscription fee" in res.json()["detail"].lower()

    # 2. Consultant attempts to download full year ECR zip — should return 402
    res = consultant_a.get("/api/reports/2026-27/ecr")
    assert res.status_code == 402

    # 3. Consultant attempts to download Form 3A/6A annual reports — should return 402
    res = consultant_a.get("/api/reports/2026-27")
    assert res.status_code == 402

    # 4. Superadmin downloads same reports with X-Establishment-Id header — BYPASSES 402 and succeeds (200)
    superadmin_session.set_establishment(gamma_id)
    res = superadmin_session.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200
    assert "Rajesh Kumar" in res.text

    # 5. Superadmin marks March fee as PAID
    save_fee_payload = {
        "financial_year": "2026-27",
        "fees": [
            {
                "month": "Mar",
                "is_paid": True,
                "paid_date": "15-05-2026",
                "payment_reference": "UPI/20260515/001",
                "notes": "Paid via GPay"
            }
        ]
    }
    res = superadmin_session.post(f"/api/admin/establishments/{gamma_id}/subscription-fees", json=save_fee_payload)
    assert res.status_code == 200

    # 6. Consultant now downloads ECR for month 0 — immediately succeeds with 200!
    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200
    assert "Rajesh Kumar" in res.text

    # 7. Check Activity Log for 'subscription_paid'
    res = superadmin_session.get("/api/admin/activity-log?action_type=subscription_paid")
    assert res.status_code == 200
    logs = res.json()["logs"]
    assert any("subscription fee PAID" in l["description"] and "GAMMA001" in l["description"] for l in logs)


def test_subscription_history_pages(superadmin_session, consultant_a):
    """Verify the consultant-facing Subscription History page and the superadmin's
    cross-establishment Subscription Payments tab both surface the same paid record,
    with correct source attribution and display month/year."""
    res = consultant_a.post("/api/establishments", json={
        "code": "IOTA001", "name": "Iota Services", "custom_rate_per_employee": 20.0
    })
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    for i in range(1, 4):
        consultant_a.post("/api/employees", json={
            "member_id": f"IOTA001{i:03d}", "name": f"Employee {i}", "uan": f"600000000{i:03d}"
        })
        consultant_a.post("/api/years/2026-27/wages", json={
            "member_id": f"IOTA001{i:03d}", "wages": [15000.0] + [0.0] * 11
        })

    # Manually mark Mar (3 employees * ₹20 = ₹60) as paid.
    res = superadmin_session.post(f"/api/admin/establishments/{est_id}/subscription-fees", json={
        "financial_year": "2026-27",
        "fees": [{"month": "Mar", "is_paid": True, "paid_date": "10-04-2026", "payment_reference": "UPI/MANUAL/001"}]
    })
    assert res.status_code == 200

    # Consultant's own Subscription History page.
    res = consultant_a.get("/api/establishment/subscription-payments")
    assert res.status_code == 200
    data = res.json()
    assert data["establishment"]["code"] == "IOTA001"
    assert data["count"] == 1
    assert data["total_paid"] == 60.0
    row = data["payments"][0]
    assert row["month"] == "Mar"
    assert row["display_name"] == "March 2026"
    assert row["employee_count"] == 3
    assert row["amount_due"] == 60.0
    assert row["source"] == "manual"
    assert row["payment_reference"] == "UPI/MANUAL/001"

    # Superadmin's cross-establishment Subscription Payments tab sees the same record,
    # correctly attributed to this consultant.
    res = superadmin_session.get("/api/admin/subscription-payments?search=IOTA001")
    assert res.status_code == 200
    admin_data = res.json()
    assert admin_data["total"] == 1
    admin_row = admin_data["payments"][0]
    assert admin_row["establishment_code"] == "IOTA001"
    assert admin_row["consultant_email"] == "consultant_a@testepf.com"
    assert admin_row["amount_due"] == 60.0
    assert admin_row["source"] == "manual"

    # Filtering by a different consultant excludes it.
    res = superadmin_session.get(f"/api/admin/subscription-payments?consultant_id=999999")
    assert res.json()["total"] == 0


def test_advance_credit_covers_future_months(superadmin_session, consultant_a):
    """Verify prepaid advance credit auto-covers new SubscriptionFee rows as their wage
    data arrives (even for months that didn't exist yet when the credit was added),
    draining the balance in order and leaving under-funded months unpaid as normal."""
    # Rate pinned explicitly at establishment level (₹20) so this test's math is
    # deterministic regardless of any consultant-level override other tests may have set.
    res = consultant_a.post("/api/establishments", json={"code": "DELTA001", "name": "Delta Corp", "custom_rate_per_employee": 20.0})
    assert res.status_code == 200
    delta_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(delta_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})

    for i in range(1, 51):
        res = consultant_a.post("/api/employees", json={
            "member_id": f"DELTA001{i:03d}", "name": f"Employee {i}", "uan": f"20000000{i:04d}"
        })
        assert res.status_code == 200

    # Advance payment recorded BEFORE any wage data exists for the months it will cover.
    res = superadmin_session.post(f"/api/admin/establishments/{delta_id}/advance-payment", json={
        "amount": 2000.0, "payment_reference": "UPI/ADV/TEST", "notes": "Lump sum prepay"
    })
    assert res.status_code == 200
    assert res.json()["advance_credit_balance"] == 2000.0

    def enter_month_wages(month_idx):
        payload = {"month_idx": month_idx, "employees": [
            {"member_id": f"DELTA001{i:03d}", "gross_wage": 15000.0, "epf_wage": 15000.0, "ncp_days": 0}
            for i in range(1, 51)
        ]}
        res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json=payload)
        assert res.status_code == 200

    # Month 1 (Mar): 50 employees * ₹20 = ₹1000 due -- auto-paid from credit.
    enter_month_wages(0)
    months = superadmin_session.get(f"/api/admin/establishments/{delta_id}/subscription-fees?year=2026-27").json()["months"]
    mar = next(m for m in months if m["month"] == "Mar")
    assert mar["employee_count"] == 50
    assert mar["amount_due"] == 1000.0
    assert mar["is_paid"] is True
    assert mar["payment_reference"] == "Applied from advance credit"
    assert superadmin_session.get(f"/api/admin/establishments/{delta_id}/advance-credit").json()["advance_credit_balance"] == 1000.0

    # Month 2 (Apr): another ₹1000 due -- drains the balance to ₹0.
    enter_month_wages(1)
    months = superadmin_session.get(f"/api/admin/establishments/{delta_id}/subscription-fees?year=2026-27").json()["months"]
    apr = next(m for m in months if m["month"] == "Apr")
    assert apr["is_paid"] is True
    assert apr["payment_reference"] == "Applied from advance credit"
    assert superadmin_session.get(f"/api/admin/establishments/{delta_id}/advance-credit").json()["advance_credit_balance"] == 0.0

    # Month 3 (May): insufficient balance -- created unpaid as normal.
    enter_month_wages(2)
    months = superadmin_session.get(f"/api/admin/establishments/{delta_id}/subscription-fees?year=2026-27").json()["months"]
    may = next(m for m in months if m["month"] == "May")
    assert may["is_paid"] is False
    assert may["amount_due"] == 1000.0

    # Consultant can download ECR for the two advance-covered months at any time...
    assert consultant_a.get("/api/reports/2026-27/ecr/0").status_code == 200
    assert consultant_a.get("/api/reports/2026-27/ecr/1").status_code == 200
    # ...but May is unpaid and past its grace period, so it's still blocked normally.
    res = consultant_a.get("/api/reports/2026-27/ecr/2")
    assert res.status_code == 402

    # Activity log records both the advance payment and each auto-application.
    logs = superadmin_session.get("/api/admin/activity-log?action_type=advance_payment_received").json()["logs"]
    assert any("DELTA001" in l["description"] for l in logs)
    logs = superadmin_session.get("/api/admin/activity-log?action_type=advance_credit_applied").json()["logs"]
    assert sum(1 for l in logs if "DELTA001" in l["description"]) == 2
