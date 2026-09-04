"""A/c 2 (EPF Administrative Charges) must never fall below Rs. 500/month once there's
wage data -- 0.50% of a small total (e.g. Rs. 70,000 wages -> Rs. 350) routinely falls
under this floor and must be topped up to Rs. 500. Reported live 2026-09-05: an
establishment was showing Rs. 138 instead of Rs. 500."""


def _create_est(consultant, code):
    res = consultant.post("/api/establishments", json={
        "coverage_date": "01-04-2026", "code": code, "name": f"{code} Co"
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def test_account2_charge_floors_at_500_when_percent_amount_is_lower(consultant_a):
    est_id = _create_est(consultant_a, "ACC2FLOOR001")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "ACC2FLOOR0011", "name": "Test Emp", "uan": "100000000601"})
    # 0.50% of Rs. 15,000 EPF wages = Rs. 75 -- well under the Rs. 500 floor.
    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 4, "employees": [{"member_id": "ACC2FLOOR0011", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text

    res = consultant_a.get("/api/dashboard")
    assert res.status_code == 200, res.text
    year_stats = next(y for y in res.json()["year_stats"] if y["key"] == "2026-27")
    month_row = next(m for m in year_stats["monthly_stats"] if m["month_idx"] == 4)
    assert month_row["acc_02"] == 500


def test_account2_charge_zero_when_no_wage_data_that_month(consultant_a):
    """The Rs. 500 floor must not appear on a month nothing was ever entered for."""
    est_id = _create_est(consultant_a, "ACC2FLOOR002")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})

    res = consultant_a.get("/api/dashboard")
    assert res.status_code == 200, res.text
    year_stats = next(y for y in res.json()["year_stats"] if y["key"] == "2026-27")
    month_row = next(m for m in year_stats["monthly_stats"] if m["month_idx"] == 0)
    assert month_row["acc_02"] == 0
