"""Regression: POST /api/master/import discarded import_master_from_excel's
(records, warnings) tuple return value into a single `records` variable, so `records`
was actually the whole tuple -- iterating it hit the records-list itself first, and
`.get()` on a list raised "'list' object has no attribute 'get'" on every CSV/Excel
employee-master upload. Found live 2026-09-04."""
from webapp.database import Establishment


def _create_est(consultant, code):
    res = consultant.post("/api/establishments", json={
        "coverage_date": "01-04-2026", "code": code, "name": f"{code} Co"
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def test_import_master_csv_does_not_crash_on_list_object(consultant_a):
    est_id = _create_est(consultant_a, "ORBBS4030797000")
    csv_content = (
        "Member ID,Name,UAN,DOB,Sex,DOJ\n"
        "ORBBS40307970000001,Test Employee,100000000012,01-01-1990,M,01-04-2026\n"
    )
    res = consultant_a.post(
        "/api/master/import",
        files={"file": ("master.csv", csv_content, "text/csv")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 1
    assert body["skipped"] == 0
