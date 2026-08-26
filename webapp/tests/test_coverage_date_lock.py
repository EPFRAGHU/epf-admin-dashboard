"""Coverage for the EPF Coverage Date requirement: mandatory at establishment creation
(all creation paths -- consultant/employer self-serve, superadmin admin-panel, and
approved signup requests), locked to the value it was first saved as for everyone
except superadmin."""
from webapp.tests.conftest import AuthClient


def test_create_establishment_requires_coverage_date(consultant_a):
    res = consultant_a.post("/api/establishments", json={"code": "COVREQ001", "name": "No Coverage Co"})
    assert res.status_code == 400
    assert "Coverage Date" in res.text


def test_create_establishment_rejects_unparseable_coverage_date(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "code": "COVREQ002", "name": "Bad Date Co", "coverage_date": "not-a-date"
    })
    assert res.status_code == 400
    assert "valid date" in res.text.lower()


def test_create_establishment_accepts_iso_and_normalizes_to_ddmmyyyy(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "code": "COVREQ003", "name": "ISO Date Co", "coverage_date": "2015-04-01"
    })
    assert res.status_code == 200, res.text
    assert res.json()["establishment"]["coverage_date"] == "01-04-2015"


def test_consultant_cannot_change_coverage_date_once_set(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "code": "COVLOCK001", "name": "Locked Co", "coverage_date": "01-04-2015"
    })
    assert res.status_code == 200
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)

    # Re-saving the SAME value (a normal full-form re-save) must still be allowed.
    res = consultant_a.put("/api/establishment", json={
        "code": "COVLOCK001", "name": "Locked Co Renamed", "coverage_date": "01-04-2015"
    })
    assert res.status_code == 200, res.text

    # Attempting to actually change it must be rejected for a non-superadmin.
    res = consultant_a.put("/api/establishment", json={
        "code": "COVLOCK001", "name": "Locked Co Renamed", "coverage_date": "01-04-2016"
    })
    assert res.status_code == 403
    assert "locked" in res.text.lower()

    res = consultant_a.get("/api/establishment")
    assert res.json()["coverage_date"] == "01-04-2015"


def test_superadmin_can_change_coverage_date_after_set(superadmin_session, consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "code": "COVLOCK002", "name": "Superadmin Editable Co", "coverage_date": "01-04-2015"
    })
    est_id = res.json()["establishment"]["id"]
    superadmin_session.set_establishment(est_id)

    res = superadmin_session.put("/api/establishment", json={
        "code": "COVLOCK002", "name": "Superadmin Editable Co", "coverage_date": "01-04-2016"
    })
    assert res.status_code == 200, res.text

    res = superadmin_session.get("/api/establishment")
    assert res.json()["coverage_date"] == "01-04-2016"


def test_legacy_blank_coverage_date_can_be_set_once_then_locks(consultant_a, test_db):
    """An establishment created before this field was required (blank coverage_date)
    gets one free pass to set it -- then locks the same as any other."""
    from webapp.database import Establishment

    res = consultant_a.post("/api/establishments", json={
        "code": "COVLEGACY01", "name": "Legacy Co", "coverage_date": "01-04-2015"
    })
    est_id = res.json()["establishment"]["id"]

    # Simulate a pre-existing row with no coverage_date on file.
    est_row = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    est_row.coverage_date = ""
    test_db.commit()

    consultant_a.set_establishment(est_id)
    res = consultant_a.put("/api/establishment", json={
        "code": "COVLEGACY01", "name": "Legacy Co", "coverage_date": "01-04-2010"
    })
    assert res.status_code == 200, res.text
    assert consultant_a.get("/api/establishment").json()["coverage_date"] == "01-04-2010"

    # Now that it's set, it locks immediately.
    res = consultant_a.put("/api/establishment", json={
        "code": "COVLEGACY01", "name": "Legacy Co", "coverage_date": "01-04-2011"
    })
    assert res.status_code == 403


def test_employer_signup_requires_coverage_date(client):
    res = client.post("/api/signup", json={
        "role": "employer", "name": "No Coverage Applicant", "email": "nocoverage@testepf.com",
        "password": "Password@123", "agreed_to_terms": True,
        "establishment_code": "COVSIGNUP001", "establishment_name": "No Coverage Signup Co",
    })
    assert res.status_code == 400
    assert "Coverage Date" in res.text


def test_employer_signup_with_coverage_date_approves_and_locks(superadmin_session, client):
    res = client.post("/api/signup", json={
        "role": "employer", "name": "Coverage Applicant", "email": "coverageok@testepf.com",
        "password": "Password@123", "agreed_to_terms": True,
        "establishment_code": "COVSIGNUP002", "establishment_name": "Coverage Signup Co",
        "coverage_date": "2015-04-01",  # ISO, as the HTML date input sends it
    })
    assert res.status_code == 200

    pending = superadmin_session.get("/api/admin/signup-requests?status=pending").json()
    req = next(r for r in pending["requests"] if r["email"] == "coverageok@testepf.com")

    res = superadmin_session.post(f"/api/admin/signup-requests/{req['id']}/approve")
    assert res.status_code == 200, res.text

    new_user_login = client.post("/api/auth/login", json={"email": "coverageok@testepf.com", "password": "Password@123"})
    assert new_user_login.status_code == 200
    employer = AuthClient(client, new_user_login.json()["token"], new_user_login.json()["user"])

    ests = employer.get("/api/establishments").json()["establishments"]
    assert len(ests) == 1
    assert ests[0]["coverage_date"] == "01-04-2015"
