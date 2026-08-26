"""
Pay All Overdue — Whole-Year/Multi-Month Payment Prompt
=========================================================
Covers the structured 402 breakdown for Form 3A/6A/9/12A/5/10 and whole-year ECR
downloads, and the "pay all overdue months in one shot" manual-UTR path:
submit one UTR across every unpaid SubscriptionFee row, approve any one of them,
and confirm all covered months (and the blocked download) unlock together.
"""

import pytest


def _setup_establishment_with_three_unpaid_months(consultant_a, code):
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2026",
        "code": code, "name": f"{code} Pvt Ltd", "custom_rate_per_employee": 20.0
    })
    assert res.status_code == 200
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={
        "member_id": f"{code}001", "name": "Test Employee", "uan": "700000000001"
    })
    # Mar, Apr, May 2026 wages -- all already past their grace period relative to "today".
    wages = [15000.0, 15000.0, 15000.0] + [0.0] * 9
    res = consultant_a.post("/api/years/2026-27/wages", json={"member_id": f"{code}001", "wages": wages})
    assert res.status_code == 200
    return est_id


def test_form3a_402_breakdown_structure(consultant_a):
    """A Form 3A/6A download blocked by 3 unpaid/overdue months returns a structured
    breakdown (not a bare error string) with per-month amounts and a combined total."""
    _setup_establishment_with_three_unpaid_months(consultant_a, "PAYALL01")

    res = consultant_a.get("/api/reports/2026-27")
    assert res.status_code == 402
    detail = res.json()["detail"]
    assert isinstance(detail, dict), "402 detail must be structured, not a bare string"
    assert detail["financial_year"] == "2026-27"
    assert detail["count"] == 3
    assert len(detail["unpaid_months"]) == 3
    assert detail["total_due"] == pytest.approx(60.0)  # 3 months * 1 employee * Rs 20
    months = {m["month"] for m in detail["unpaid_months"]}
    assert months == {"Mar", "Apr", "May"}
    for m in detail["unpaid_months"]:
        assert m["amount_due"] == pytest.approx(20.0)
        assert "fee_id" in m and "display" in m


def test_ecr_zip_and_form9_and_employee_report_402_breakdown(consultant_a):
    """The same structured breakdown applies to the whole-year ECR zip, the multi-year
    Form 9 endpoint, and the per-employee Form 3A endpoint -- not just the combined
    Form 3A/6A/12A/5/10 endpoint."""
    _setup_establishment_with_three_unpaid_months(consultant_a, "PAYALL02")

    res = consultant_a.get("/api/reports/2026-27/ecr")
    assert res.status_code == 402
    assert isinstance(res.json()["detail"], dict)
    assert res.json()["detail"]["count"] == 3

    res = consultant_a.get("/api/reports/form9/download")
    assert res.status_code == 402
    detail = res.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["financial_year"] is None  # Form 9 spans every year, not scoped to one
    assert detail["count"] == 3

    res = consultant_a.get("/api/reports/2026-27/employee/PAYALL02001")
    assert res.status_code == 402
    assert isinstance(res.json()["detail"], dict)
    assert res.json()["detail"]["count"] == 3


def test_pay_all_overdue_manual_utr_unlocks_every_month_and_download(consultant_a, superadmin_session):
    """Submitting ONE UTR across all 3 unpaid months, then a superadmin approving just
    ONE of those fee rows, must cascade to mark all 3 paid -- and the Form 3A download
    must succeed immediately after, without any further action."""
    est_id = _setup_establishment_with_three_unpaid_months(consultant_a, "PAYALL03")

    res = consultant_a.get("/api/reports/2026-27")
    assert res.status_code == 402
    detail = res.json()["detail"]
    fee_ids = [m["fee_id"] for m in detail["unpaid_months"]]
    assert len(fee_ids) == 3
    total_due = detail["total_due"]

    # Submit one UTR covering the combined total for all 3 months at once.
    res = consultant_a.post("/api/establishment/subscription-fees/pay-all/submit-utr", json={
        "fee_ids": fee_ids, "utr": "PAYALL03UTR001"
    })
    assert res.status_code == 200
    assert res.json()["payment_status"] == "pending_verification"

    # Still blocked -- pending verification isn't a payment yet.
    res = consultant_a.get("/api/reports/2026-27")
    assert res.status_code == 402

    # Superadmin approves just ONE of the three fee rows via the shared queue endpoint.
    res = superadmin_session.post(f"/api/admin/payment-verifications/fee-{fee_ids[0]}/approve", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["payment_status"] == "paid"
    assert len(body.get("months_approved", [])) == 3  # cascaded to both siblings

    # All 3 fee rows are now paid.
    res = superadmin_session.get(f"/api/admin/establishments/{est_id}/subscription-fees?year=2026-27")
    months = {m["month"]: m for m in res.json()["months"]}
    assert months["Mar"]["is_paid"] is True
    assert months["Apr"]["is_paid"] is True
    assert months["May"]["is_paid"] is True

    # The blocked Form 3A download now succeeds immediately, no further action needed.
    res = consultant_a.get("/api/reports/2026-27")
    assert res.status_code == 200

    # refresh-status also reflects the DB-confirmed state (covers the frontend's polling path).
    res = consultant_a.post("/api/establishment/subscription-fees/pay-all/refresh-status", json={"fee_ids": fee_ids})
    assert res.status_code == 200
    assert res.json()["is_paid"] is True
    assert res.json()["is_paid"] is True

    # Reusing the same UTR again (e.g. a duplicate submission) is rejected.
    res = consultant_a.post("/api/establishment/subscription-fees/pay-all/submit-utr", json={
        "fee_ids": fee_ids, "utr": "PAYALL03UTR001"
    })
    assert res.status_code == 400

    # The consultant's own Subscription page immediately reflects all 3 months as paid too --
    # same SubscriptionFee rows, no separate cache, no lag between this prompt and that page.
    res = consultant_a.get("/api/establishment/subscription-status?year=2026-27")
    assert res.status_code == 200
    sub_status = res.json()
    assert sub_status["has_overdue"] is False
    assert sub_status["unpaid_months"] == []


def test_all_months_paid_no_prompt_shown(consultant_a):
    """An establishment with every wage-bearing month already paid must download immediately
    (200, no 402 at all) -- the breakdown must never appear once nothing is actually unpaid."""
    est_id = _setup_establishment_with_three_unpaid_months(consultant_a, "PAYALL04")

    res = consultant_a.get("/api/reports/2026-27")
    assert res.status_code == 402
    fee_ids = [m["fee_id"] for m in res.json()["detail"]["unpaid_months"]]

    # Pay every unpaid month directly (simulating prior payment via the Subscription page).
    res = consultant_a.post("/api/establishment/subscription-fees/pay-all/submit-utr", json={
        "fee_ids": fee_ids, "utr": "PAYALL04UTR001"
    })
    assert res.status_code == 200

    from webapp.database import SubscriptionFee, SessionLocal
    db = SessionLocal()
    try:
        for f in db.query(SubscriptionFee).filter(SubscriptionFee.id.in_(fee_ids)).all():
            f.is_paid = True
            f.payment_status = "paid"
        db.commit()
    finally:
        db.close()

    # No prompt at all -- the download succeeds immediately.
    res = consultant_a.get("/api/reports/2026-27")
    assert res.status_code == 200

    # The Subscription page agrees -- nothing left unpaid.
    res = consultant_a.get("/api/establishment/subscription-status?year=2026-27")
    assert res.json()["has_overdue"] is False
    assert res.json()["unpaid_months"] == []
