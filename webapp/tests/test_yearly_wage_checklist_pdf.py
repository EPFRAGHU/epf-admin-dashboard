"""GET /api/years/{key}/wages/checklist/pdf -- one block per employee for the whole
financial year (Gross/EPF/EPS Wages + EE/EPS Cont/ER Share, Mar-Feb), plus a grand
total. Not a statutory form, no subscription-fee gate, per user request."""


def _create_est(consultant, code):
    res = consultant.post("/api/establishments", json={
        "coverage_date": "01-04-2026", "code": code, "name": f"{code} Co"
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def test_download_yearly_wage_checklist_pdf(consultant_a):
    est_id = _create_est(consultant_a, "YCHK001")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "YCHK0011", "name": "Test Emp", "uan": "100000000801"})
    res_wage = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "YCHK0011", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res_wage.status_code == 200, res_wage.text

    res = consultant_a.get("/api/years/2026-27/wages/checklist/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF")
    assert len(res.content) > 500


def test_yearly_checklist_pdf_route_not_shadowed_by_month_idx_route(consultant_a):
    """Regression: /wages/checklist/pdf must not be swallowed by the earlier-declared
    /wages/{month_idx}/pdf route (FastAPI matches route structure before coercing
    {month_idx} to int -- 'checklist' would 422 there if route order were wrong)."""
    est_id = _create_est(consultant_a, "YCHK002")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.get("/api/years/2026-27/wages/checklist/pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"


def test_yearly_checklist_pdf_no_payment_gate(consultant_a, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "YCHK003")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "YCHK0031", "name": "Test Emp 3", "uan": "100000000803"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "YCHK0031", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    assert fee is not None and not fee.is_paid

    res = consultant_a.get("/api/years/2026-27/wages/checklist/pdf")
    assert res.status_code == 200


def test_yearly_checklist_pdf_no_employees(consultant_a):
    """Empty year must not crash -- the PDF just has no employee blocks."""
    _create_est(consultant_a, "YCHK004")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.get("/api/years/2026-27/wages/checklist/pdf")
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF")
