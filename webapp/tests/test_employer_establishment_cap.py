"""Coverage for the Employer role's max_establishments cap (webapp/app.py POST /api/establishments,
POST /api/admin/users, PUT /api/admin/users/{id}) -- newer surface area with no prior dedicated test."""
from webapp.tests.conftest import AuthClient


def _create_employer(superadmin_session, email="employer_cap@testepf.com", max_establishments=1):
    res = superadmin_session.post("/api/admin/users", json={
        "name": "Cap Test Employer",
        "email": email,
        "password": "EmployerPass@123",
        "role": "employer",
        "max_establishments": max_establishments,
    })
    assert res.status_code == 200, res.text
    return res.json()["user"]


def _login_as(client, email, password="EmployerPass@123"):
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return AuthClient(client, res.json()["token"], res.json()["user"])


def test_admin_create_user_requires_positive_max_establishments_for_employer(superadmin_session):
    res = superadmin_session.post("/api/admin/users", json={
        "name": "No Cap Employer",
        "email": "employer_nocap@testepf.com",
        "password": "EmployerPass@123",
        "role": "employer",
    })
    assert res.status_code == 400
    assert "max_establishments" in res.text

    res = superadmin_session.post("/api/admin/users", json={
        "name": "Zero Cap Employer",
        "email": "employer_zerocap@testepf.com",
        "password": "EmployerPass@123",
        "role": "employer",
        "max_establishments": 0,
    })
    assert res.status_code == 400


def test_employer_establishment_cap_enforced_on_self_serve_creation(client, superadmin_session):
    _create_employer(superadmin_session, email="employer_cap1@testepf.com", max_establishments=1)
    employer = _login_as(client, "employer_cap1@testepf.com")

    res1 = employer.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": "CAPTEST01", "name": "Cap Test Est 1"})
    assert res1.status_code == 200, res1.text

    res2 = employer.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": "CAPTEST02", "name": "Cap Test Est 2"})
    assert res2.status_code == 403
    assert "limit" in res2.text.lower()


def test_employer_with_no_cap_is_unlimited(client, superadmin_session):
    superadmin_session.post("/api/admin/users", json={
        "name": "Unlimited Employer",
        "email": "employer_unlimited@testepf.com",
        "password": "EmployerPass@123",
        "role": "employer",
        "max_establishments": 5,
    })
    employer = _login_as(client, "employer_unlimited@testepf.com")

    for i in range(5):
        res = employer.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": f"UNLIM{i}", "name": f"Unlimited Est {i}"})
        assert res.status_code == 200, res.text

    res = employer.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": "UNLIM99", "name": "Over Cap"})
    assert res.status_code == 403


def test_raising_the_cap_unblocks_further_creation(client, superadmin_session):
    employer_user = _create_employer(superadmin_session, email="employer_cap2@testepf.com", max_establishments=1)
    employer = _login_as(client, "employer_cap2@testepf.com")

    res1 = employer.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": "RAISECAP1", "name": "Raise Cap Est 1"})
    assert res1.status_code == 200, res1.text

    res_blocked = employer.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": "RAISECAP2", "name": "Raise Cap Est 2"})
    assert res_blocked.status_code == 403

    res_update = superadmin_session.put(f"/api/admin/users/{employer_user['id']}", json={"max_establishments": 2})
    assert res_update.status_code == 200, res_update.text

    res2 = employer.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": "RAISECAP2", "name": "Raise Cap Est 2"})
    assert res2.status_code == 200, res2.text


def test_consultant_role_is_never_capped_even_if_max_establishments_field_sent(client, superadmin_session):
    superadmin_session.post("/api/admin/users", json={
        "name": "Cap Test Consultant",
        "email": "consultant_cap@testepf.com",
        "password": "EmployerPass@123",
        "role": "consultant",
        "max_establishments": 1,  # should be ignored for consultants
    })
    consultant = _login_as(client, "consultant_cap@testepf.com")

    for i in range(3):
        res = consultant.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": f"CONSCAP{i}", "name": f"Consultant Est {i}"})
        assert res.status_code == 200, res.text


def test_superadmin_creating_on_behalf_of_capped_employer_is_also_blocked(superadmin_session):
    employer_user = _create_employer(superadmin_session, email="employer_cap3@testepf.com", max_establishments=1)

    res1 = superadmin_session.post("/api/establishments", json={"coverage_date": "01-04-2015", 
        "code": "SUPERCAP1", "name": "Super-created Est 1", "owner_user_id": employer_user["id"]
    })
    assert res1.status_code == 200, res1.text

    res2 = superadmin_session.post("/api/establishments", json={"coverage_date": "01-04-2015", 
        "code": "SUPERCAP2", "name": "Super-created Est 2", "owner_user_id": employer_user["id"]
    })
    assert res2.status_code == 403


def test_update_max_establishments_rejected_for_consultant_and_non_positive(client, superadmin_session):
    res = superadmin_session.post("/api/admin/users", json={
        "name": "Plain Consultant",
        "email": "plain_consultant_cap@testepf.com",
        "password": "EmployerPass@123",
        "role": "consultant",
    })
    consultant_user = res.json()["user"]

    res_bad_role = superadmin_session.put(f"/api/admin/users/{consultant_user['id']}", json={"max_establishments": 3})
    assert res_bad_role.status_code == 400

    employer_user = _create_employer(superadmin_session, email="employer_cap4@testepf.com", max_establishments=1)
    res_bad_value = superadmin_session.put(f"/api/admin/users/{employer_user['id']}", json={"max_establishments": 0})
    assert res_bad_value.status_code == 400
