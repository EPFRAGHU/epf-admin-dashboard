"""GET /api/years/{key}/wages/{month_idx}/pdf -- Monthly Wage Entry grid as a standalone
PDF (not a statutory form, no subscription-fee gate, per user request)."""


def _create_est(consultant, code):
    res = consultant.post("/api/establishments", json={
        "coverage_date": "01-04-2026", "code": code, "name": f"{code} Co"
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def test_download_monthly_wage_entry_pdf(consultant_a):
    est_id = _create_est(consultant_a, "MWEPDF001")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "MWEPDF0011", "name": "Test Emp", "uan": "100000000401"})
    res_wage = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "MWEPDF0011", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res_wage.status_code == 200, res_wage.text

    res = consultant_a.get("/api/years/2026-27/wages/0/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")
    assert len(res.content) > 500


def test_download_monthly_wage_entry_pdf_no_payment_gate(consultant_a, test_db):
    """Unlike report downloads, this one must never 402 -- confirm by leaving the
    month's subscription fee unpaid and downloading anyway."""
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "MWEPDF002")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "MWEPDF0021", "name": "Test Emp 2", "uan": "100000000402"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "MWEPDF0021", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    assert fee is not None and not fee.is_paid

    res = consultant_a.get("/api/years/2026-27/wages/0/pdf")
    assert res.status_code == 200


def test_download_monthly_wage_entry_pdf_invalid_month_index(consultant_a):
    _create_est(consultant_a, "MWEPDF003")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.get("/api/years/2026-27/wages/12/pdf")
    assert res.status_code == 400
