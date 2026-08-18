import pytest


def _new_establishment(consultant, code, name):
    res = consultant.post("/api/establishments", json={"code": code, "name": name})
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def test_empty_year_can_be_deleted_normally(consultant_a):
    _new_establishment(consultant_a, "YRDEL0000001", "Empty Year Co")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})

    listing = consultant_a.get("/api/years").json()
    row = next(y for y in listing["years"] if y["key"] == "2026-27")
    assert row["can_delete"] is True
    assert row["delete_blockers"] == []

    res = consultant_a.delete("/api/years/2026-27")
    assert res.status_code == 200
    assert "2026-27" not in [y["key"] for y in consultant_a.get("/api/years").json()["years"]]


def test_year_with_wage_data_is_blocked_with_409_and_clear_reason(consultant_a):
    _new_establishment(consultant_a, "YRDEL0000002", "Wage Data Co")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "YD0002", "name": "Wage Employee", "uan": "100888800002"})
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "YD0002", "wages": [10000.0] + [0.0] * 11,
    })

    listing = consultant_a.get("/api/years").json()
    row = next(y for y in listing["years"] if y["key"] == "2026-27")
    assert row["can_delete"] is False
    assert "wage data" in " ".join(row["delete_blockers"])

    res = consultant_a.delete("/api/years/2026-27")
    assert res.status_code == 409
    assert "wage data" in res.json()["detail"]
    # nothing was actually removed
    assert "2026-27" in [y["key"] for y in consultant_a.get("/api/years").json()["years"]]


def test_year_with_filed_remittance_is_blocked(consultant_a):
    _new_establishment(consultant_a, "YRDEL0000003", "Remittance Co")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/years/2026-27/remittances/bulk", json={
        "remittances": [{"month_label": "Apr", "trrn": "TRRN12345", "crrn": "", "credit_date": ""}]
    })

    listing = consultant_a.get("/api/years").json()
    row = next(y for y in listing["years"] if y["key"] == "2026-27")
    assert row["can_delete"] is False
    assert "TRRN" in " ".join(row["delete_blockers"])

    res = consultant_a.delete("/api/years/2026-27")
    assert res.status_code == 409


def test_superadmin_gets_the_same_block_as_consultant_by_default(consultant_a, superadmin_session):
    est_id = _new_establishment(consultant_a, "YRDEL0000004", "Superadmin Same Rule Co")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "YD0004", "name": "Blocker Employee", "uan": "100888800004"})
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "YD0004", "wages": [5000.0] + [0.0] * 11,
    })

    superadmin_session.set_establishment(est_id)
    res = superadmin_session.delete("/api/years/2026-27")
    assert res.status_code == 409


def test_consultant_has_no_path_to_force_delete(consultant_a):
    _new_establishment(consultant_a, "YRDEL0000005", "No Escape Hatch Co")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "YD0005", "name": "Locked Employee", "uan": "100888800005"})
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "YD0005", "wages": [5000.0] + [0.0] * 11,
    })

    res = consultant_a.delete("/api/years/2026-27/force", json={
        "confirm_code": "YRDEL0000005", "confirm_year": "2026-27",
    })
    assert res.status_code == 403
    assert "2026-27" in [y["key"] for y in consultant_a.get("/api/years").json()["years"]]


def test_superadmin_force_delete_requires_exact_confirmation_text(consultant_a, superadmin_session):
    est_id = _new_establishment(consultant_a, "YRDEL0000006", "Force Delete Co")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "YD0006", "name": "Force Employee", "uan": "100888800006"})
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "YD0006", "wages": [5000.0] + [0.0] * 11,
    })

    superadmin_session.set_establishment(est_id)

    # wrong confirmation text is rejected, year survives
    res = superadmin_session.delete("/api/years/2026-27/force", json={
        "confirm_code": "WRONG_CODE", "confirm_year": "2026-27",
    })
    assert res.status_code == 400
    assert "2026-27" in [y["key"] for y in superadmin_session.get("/api/years").json()["years"]]

    # exact match succeeds despite the blocking data
    res = superadmin_session.delete("/api/years/2026-27/force", json={
        "confirm_code": "YRDEL0000006", "confirm_year": "2026-27",
    })
    assert res.status_code == 200
    assert "2026-27" not in [y["key"] for y in superadmin_session.get("/api/years").json()["years"]]


def test_year_deletion_isolated_between_consultants(consultant_a, consultant_b):
    est_a_id = _new_establishment(consultant_a, "YRDELISO000A", "Isolation Del Co A")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})

    _new_establishment(consultant_b, "YRDELISO000B", "Isolation Del Co B")

    # Consultant B cannot touch Consultant A's year by targeting A's establishment directly.
    res = consultant_b.delete("/api/years/2026-27", headers={"X-Establishment-Id": str(est_a_id)})
    assert res.status_code in (403, 404)
    consultant_a.set_establishment(est_a_id)
    assert "2026-27" in [y["key"] for y in consultant_a.get("/api/years").json()["years"]]
