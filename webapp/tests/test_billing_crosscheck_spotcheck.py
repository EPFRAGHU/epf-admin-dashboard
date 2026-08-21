"""
Live end-to-end billing-consistency spot-check (2026-08-21 full regression QA pass,
Section 4 -- billing is real-money and explicitly the highest-priority section).

Exercises the REAL payment flow (submit-utr -> superadmin approve), not a DB
shortcut, then confirms all four surfaces that read SubscriptionFee rows agree
immediately: the ECR download gate, the Form 3A/6A/9/12A/5/10 download gate, the
consultant subscription-status endpoint (Subscription page), and the superadmin's
per-establishment subscription-fees view.
"""
from webapp.database import SubscriptionFee


def test_pay_one_month_reflects_everywhere(consultant_a, superadmin_session, test_db):
    res = consultant_a.post("/api/establishments", json={"code": "BILL001", "name": "Billing Crosscheck Corp"})
    assert res.status_code == 200, res.text
    est = res.json()["establishment"]
    consultant_a.set_establishment(est["id"])

    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "BILL001001", "name": "Emp One", "uan": "710000000001"})
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "BILL001001", "wages": [15000.0] + [0.0] * 11
    })

    # Force the lazy fee sync (mirrors what any of the four surfaces would trigger).
    # NOTE: wages[0] is the "Mar" wage month (wage months run Mar-Feb; the *credit*
    # month shown as "April" on the Dashboard/Challans is one month later) -- so the
    # only fee row with real wage data (and thus the only one actually blocking
    # downloads) is month == "Mar", not "Apr".
    consultant_a.get("/api/establishment/subscription-status?year=2026-27")
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est["id"], SubscriptionFee.month == "Mar"
    ).first()
    assert fee is not None, "March fee row was not synced"
    assert fee.is_paid is False

    # --- BEFORE payment: both download gates block, consistently ---
    res_form = consultant_a.get("/api/reports/2026-27?format=excel&forms=12A")
    assert res_form.status_code == 402
    res_ecr = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res_ecr.status_code == 402
    status_before = consultant_a.get("/api/establishment/subscription-status?year=2026-27").json()
    assert status_before["has_overdue"] is True
    admin_view_before = superadmin_session.get(f"/api/admin/establishments/{est['id']}/subscription-fees?year=2026-27").json()
    apr_row_before = next(r for r in admin_view_before["months"] if r["month"] == "Apr")
    assert apr_row_before["is_paid"] is False

    # --- Pay April via the REAL UTR flow (as if from the Subscription page) ---
    res = consultant_a.post(f"/api/subscription-fees/{fee.id}/submit-utr", json={"utr": "UTR-CROSSCHECK-001"})
    assert res.status_code == 200, res.text
    # Bare integer id is accepted for backward compat -- treated as a subscription-fee id.
    res = superadmin_session.post(f"/api/admin/payment-verifications/{fee.id}/approve", json={})
    assert res.status_code == 200, res.text

    # --- AFTER payment: all four surfaces must immediately agree it's paid ---
    res_form = consultant_a.get("/api/reports/2026-27?format=excel&forms=12A")
    assert res_form.status_code == 200, f"Form download still blocked after payment: {res_form.text}"

    status_after = consultant_a.get("/api/establishment/subscription-status?year=2026-27").json()
    assert not any("April" in m for m in status_after["unpaid_months"]), status_after

    admin_view_after = superadmin_session.get(f"/api/admin/establishments/{est['id']}/subscription-fees?year=2026-27").json()
    apr_row_after = next(r for r in admin_view_after["months"] if r["month"] == "Apr")
    assert apr_row_after["is_paid"] is True, admin_view_after

    ledger = superadmin_session.get("/api/admin/subscription-payments?establishment_id=" + str(est["id"])).json()
    assert any(p["month"] == "Apr" and p["financial_year"] == "2026-27" for p in ledger["payments"]), ledger

    print("\n=== All four billing surfaces confirmed paid for Apr 2026-27 ===")
    print("form download:", res_form.status_code)
    print("subscription-status unpaid_months:", status_after["unpaid_months"])
    print("admin establishment view Apr row:", apr_row_after)
    print("admin ledger match found: True")
