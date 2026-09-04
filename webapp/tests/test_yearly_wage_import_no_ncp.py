"""Yearly wage import must accept a plain UAN | NAME | MAR | APR | ... | FEB sheet
(wages only, no NCP Days columns) -- the parser already supported this before the
Import modal's own instructions text was fixed to stop implying NCP columns were
needed (previously showed 'APR | APR NCP | MAY | MAY NCP ...', wrong on two counts:
NCP not required, and this app's financial year starts Mar not Apr everywhere else)."""
import io
import openpyxl


def _create_est(consultant, code):
    res = consultant.post("/api/establishments", json={
        "coverage_date": "01-04-2026", "code": code, "name": f"{code} Co"
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def _build_yearly_wage_xlsx_bytes():
    """UAN | NAME | Mar | Apr | ... | Feb -- wages only, deliberately no NCP columns."""
    wb = openpyxl.Workbook()
    ws = wb.active
    months = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
    ws.append(["UAN", "NAME"] + months)
    ws.append(["100000000701", "Import Emp", 15000, 16000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_yearly_import_accepts_bare_month_columns_no_ncp(consultant_a):
    est_id = _create_est(consultant_a, "YIMPORT001")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})

    xlsx_bytes = _build_yearly_wage_xlsx_bytes()
    res = consultant_a.post(
        "/api/import/2026-27",
        data={"import_type": "yearly", "month_idx": "-1"},
        files={"file": ("wages.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["imported"] == 1

    wages_res = consultant_a.get("/api/years/2026-27/wages")
    assert wages_res.status_code == 200
    emp = next(e for e in wages_res.json()["employees"] if e["uan"] == "100000000701")
    assert emp["wages"][0] == 15000  # Mar
    assert emp["wages"][1] == 16000  # Apr
    assert emp["ncp_days"] == [0] * 12  # no NCP column in the file -- must default to 0, not error
