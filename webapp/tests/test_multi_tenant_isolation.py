import pytest
from webapp.auth import verify_password
from webapp.database import User, Establishment, SubscriptionFee


def test_tenant_isolation_establishments(consultant_a, consultant_b):
    """
    Verify that establishments and employee records created by Consultant A
    are completely isolated and invisible to Consultant B, and vice versa.
    """
    # 1. Consultant A creates an establishment
    res_a = consultant_a.post("/api/establishments", json={
        "code": "ORBBS0000001000",
        "name": "ALPHA ENTERPRISES",
        "address": "Bhubaneswar Tech Park",
        "coverage_date": "01-04-2024"
    })
    assert res_a.status_code == 200, f"Consultant A creation failed: {res_a.text}"
    est_a_id = res_a.json()["establishment"]["id"]

    # 2. Consultant B creates an establishment
    res_b = consultant_b.post("/api/establishments", json={
        "code": "ORCTC0000002000",
        "name": "BETA LOGISTICS",
        "address": "Cuttack Industrial Area",
        "coverage_date": "01-06-2024"
    })
    assert res_b.status_code == 200, f"Consultant B creation failed: {res_b.text}"
    est_b_id = res_b.json()["establishment"]["id"]

    # 3. Verify Consultant A only sees Alpha Enterprises
    list_a = consultant_a.get("/api/establishments").json()["establishments"]
    codes_a = [e["code"] for e in list_a]
    assert "ORBBS0000001000" in codes_a
    assert "ORCTC0000002000" not in codes_a

    # 4. Verify Consultant B only sees Beta Logistics
    list_b = consultant_b.get("/api/establishments").json()["establishments"]
    codes_b = [e["code"] for e in list_b]
    assert "ORCTC0000002000" in codes_b
    assert "ORBBS0000001000" not in codes_b

    # 5. Consultant A adds an employee to Alpha Enterprises
    consultant_a.set_establishment(est_a_id)
    emp_res = consultant_a.post("/api/employees", json={
        "member_id": "ORBBS00000010000000001",
        "name": "Rajesh Kumar",
        "uan": "100987654321",
        "dob": "15-05-1990",
        "doj": "01-04-2024",
        "sex": "M"
    })
    assert emp_res.status_code == 200, f"Failed adding employee: {emp_res.text}"

    # 6. Consultant B checks employee list under Beta Logistics
    consultant_b.set_establishment(est_b_id)
    b_emps = consultant_b.get("/api/employees").json()
    b_emp_names = [emp["name"] for emp in b_emps.get("employees", [])]
    assert "Rajesh Kumar" not in b_emp_names
    assert not any(emp.get("member_id") == "ORBBS00000010000000001" for emp in b_emps.get("employees", []))


def test_tenant_isolation_concurrent_requests(consultant_a, consultant_b):
    """
    Simulate fast interleaved requests between two consultant sessions in separate browser windows.
    Verifies that state isolation is strictly preserved at every step without cross-contamination.
    """
    # Step 1: A creates
    res_a = consultant_a.post("/api/establishments", json={
        "code": "ORCONCA00001",
        "name": "CONCURRENT ORG A",
        "address": "Zone A",
        "coverage_date": "01-01-2024"
    })
    assert res_a.status_code == 200
    est_a_id = res_a.json()["establishment"]["id"]

    # Step 2: B creates
    res_b = consultant_b.post("/api/establishments", json={
        "code": "ORCONCB00002",
        "name": "CONCURRENT ORG B",
        "address": "Zone B",
        "coverage_date": "01-02-2024"
    })
    assert res_b.status_code == 200
    est_b_id = res_b.json()["establishment"]["id"]

    # Step 3: A reads establishment list
    a_ests = [e["code"] for e in consultant_a.get("/api/establishments").json()["establishments"]]
    assert "ORCONCA00001" in a_ests
    assert "ORCONCB00002" not in a_ests

    # Step 4: B reads establishment list
    b_ests = [e["code"] for e in consultant_b.get("/api/establishments").json()["establishments"]]
    assert "ORCONCB00002" in b_ests
    assert "ORCONCA00001" not in b_ests

    # Step 5: A writes employee to A
    consultant_a.set_establishment(est_a_id)
    res_add_a = consultant_a.post("/api/employees", json={
        "member_id": "ORCONCA00001000001",
        "name": "Employee Alpha",
        "uan": "100111111111"
    })
    assert res_add_a.status_code == 200

    # Step 6: B reads employee list (must not see A's employee)
    consultant_b.set_establishment(est_b_id)
    b_emps = consultant_b.get("/api/employees").json().get("employees", [])
    assert not any(e["name"] == "Employee Alpha" for e in b_emps)

    # Step 7: B writes employee to B
    res_add_b = consultant_b.post("/api/employees", json={
        "member_id": "ORCONCB00002000001",
        "name": "Employee Beta",
        "uan": "100222222222"
    })
    assert res_add_b.status_code == 200

    # Step 8: A reads employee list (sees only Alpha)
    a_emps = consultant_a.get("/api/employees").json().get("employees", [])
    assert any(e["name"] == "Employee Alpha" for e in a_emps)
    assert not any(e["name"] == "Employee Beta" for e in a_emps)

    # Step 9: B reads employee list (sees only Beta)
    b_emps_final = consultant_b.get("/api/employees").json().get("employees", [])
    assert any(e["name"] == "Employee Beta" for e in b_emps_final)
    assert not any(e["name"] == "Employee Alpha" for e in b_emps_final)


def test_ownership_enforcement(consultant_a, consultant_b):
    """
    Verify that Consultant B cannot read, modify, or delete Consultant A's establishment
    even if the ID is known or targeted directly in URL parameters or headers.
    """
    # 1. Consultant A creates an establishment
    res_a = consultant_a.post("/api/establishments", json={
        "code": "OROWN0000001000",
        "name": "OWNERSHIP TEST ORG A",
        "address": "Address A",
        "coverage_date": "01-01-2025"
    })
    assert res_a.status_code == 200
    a_est_id = res_a.json()["establishment"]["id"]

    # 2. Consultant B attempts GET on A's establishment
    res_b_get = consultant_b.get(f"/api/establishment?est_id={a_est_id}")
    assert res_b_get.status_code in (403, 404), "Consultant B should not have access to A's establishment"
    assert "OWNERSHIP TEST ORG A" not in res_b_get.text

    # 3. Consultant B attempts PUT / edit on A's establishment
    res_b_put = consultant_b.put(f"/api/establishment?est_id={a_est_id}", json={
        "name": "HIJACKED ORG NAME",
        "code": "ORHIJACK0001",
        "address": "Hijacked Address",
        "coverage_date": "01-01-2025"
    })
    assert res_b_put.status_code in (403, 404)

    # Verify A's establishment remains intact and untouched
    res_a_check = consultant_a.get(f"/api/establishment?est_id={a_est_id}")
    assert res_a_check.status_code == 200
    assert res_a_check.json()["name"] == "OWNERSHIP TEST ORG A"

    # 4. Consultant B attempts DELETE on A's establishment
    res_b_del = consultant_b.delete(f"/api/establishments/{a_est_id}")
    assert res_b_del.status_code in (403, 404)

    # 5. Verify A's establishment was NOT deleted
    res_a_still_exists = consultant_a.get(f"/api/establishment?est_id={a_est_id}")
    assert res_a_still_exists.status_code == 200

    # 6. Test reverse direction: Consultant B creates establishment, Consultant A attempts DELETE
    res_b_create = consultant_b.post("/api/establishments", json={
        "code": "OROWN0000002000",
        "name": "OWNERSHIP TEST ORG B",
        "address": "Address B",
        "coverage_date": "01-01-2025"
    })
    assert res_b_create.status_code == 200
    b_est_id = res_b_create.json()["establishment"]["id"]

    res_a_del_b = consultant_a.delete(f"/api/establishments/{b_est_id}")
    assert res_a_del_b.status_code in (403, 404)


def test_role_separation(consultant_a, superadmin_session):
    """
    Verify that Superadmin endpoints strictly reject Consultant sessions with 403 Forbidden,
    while Superadmin sessions succeed with 200 OK.
    """
    admin_get_endpoints = [
        "/api/admin/overview",
        "/api/admin/users",
        "/api/admin/activity-log",
    ]

    # 1. Consultant attempts admin endpoints -> MUST receive 403
    for endpoint in admin_get_endpoints:
        res = consultant_a.get(endpoint)
        assert res.status_code == 403, f"Consultant was not blocked on {endpoint} (Got {res.status_code})"
        assert "Access denied" in res.text or "Superadmin privileges required" in res.text

    # Consultant attempts to create a user -> MUST receive 403
    res_create_user = consultant_a.post("/api/admin/users", json={
        "name": "Unauthorized User",
        "email": "unauthorized@testepf.com",
        "password": "Password@123"
    })
    assert res_create_user.status_code == 403

    # 2. Superadmin calls the same endpoints -> MUST succeed (200 OK)
    for endpoint in admin_get_endpoints:
        res = superadmin_session.get(endpoint)
        assert res.status_code == 200, f"Superadmin failed on {endpoint}: {res.text}"

    # Superadmin views activity log with filters
    res_act = superadmin_session.get("/api/admin/activity-log?page=1&limit=10")
    assert res_act.status_code == 200
    assert "logs" in res_act.json()


def test_auth_required(client):
    """
    Verify that unauthenticated requests (no token, no headers) to protected routes
    return 401 Unauthorized with no data leakage.
    """
    protected_endpoints = [
        "/api/auth/me",
        "/api/establishments",
        "/api/establishment",
        "/api/employees",
        "/api/admin/overview",
        "/api/admin/activity-log",
    ]

    for endpoint in protected_endpoints:
        res = client.get(endpoint)
        assert res.status_code == 401, f"Expected 401 for unauthenticated request to {endpoint}, got {res.status_code}"
        assert "Authentication required" in res.text or "Invalid or expired token" in res.text
        # Ensure no establishment or user payload is leaked
        data = res.json()
        assert "establishments" not in data
        assert "employees" not in data
        assert "users" not in data


def test_login_rejects_wrong_password(client, consultant_a):
    """
    Verify that POST /api/auth/login rejects incorrect credentials and does not issue JWT tokens.
    """
    # 1. Valid email with wrong password
    res_wrong_pass = client.post("/api/auth/login", json={
        "email": "consultant_a@testepf.com",
        "password": "CompletelyWrongPassword123"
    })
    assert res_wrong_pass.status_code in (401, 400)
    assert "token" not in res_wrong_pass.json()

    # 2. Non-existent email
    res_non_existent = client.post("/api/auth/login", json={
        "email": "does.not.exist@epfdashboard.com",
        "password": "Password@123"
    })
    assert res_non_existent.status_code in (401, 400)
    assert "token" not in res_non_existent.json()


def test_passwords_are_hashed(superadmin_session, test_db):
    """
    Verify that user passwords are encrypted/hashed using a secure algorithm
    (e.g., werkzeug scrypt/pbkdf2) and never stored in plaintext in the database.
    """
    plaintext_pass = "TestSecurePassword@2026"
    test_email = "hash.verification@testepf.com"

    # Create user through the real administrative API endpoint
    res = superadmin_session.post("/api/admin/users", json={
        "name": "Hash Verification User",
        "email": test_email,
        "mobile": "9998887776",
        "password": plaintext_pass
    })
    assert res.status_code == 200, f"User creation failed: {res.text}"

    # Query the user row directly from the database
    user = test_db.query(User).filter(User.email == test_email).first()
    assert user is not None, "Created user not found in database"

    # (a) Password hash is not plaintext
    assert user.password_hash != plaintext_pass, "Password is being stored in plaintext!"

    # (b) Password hash starts with recognized hash scheme (e.g. scrypt:, pbkdf2:, $2b$, etc.)
    assert any(user.password_hash.startswith(prefix) for prefix in ["scrypt:", "pbkdf2:", "$2b$", "$2a$", "$2y$"]), \
        f"Password hash does not match expected secure format: {user.password_hash[:15]}..."

    # (c) Verifies correctly with verify_password
    assert verify_password(plaintext_pass, user.password_hash) is True
    assert verify_password("WrongPassword123", user.password_hash) is False


def test_superadmin_bypasses_download_gate_via_role_not_payment_status(superadmin_session, consultant_a, test_db):
    """
    Verify the superadmin download bypass is a genuine role-based short-circuit, not
    something that happens to work because a fee row got marked paid some other way.

    Unlike test_download_gating_402_and_superadmin_bypass (which lets the lazy-sync
    mechanism create the SubscriptionFee row from wage entry), this test constructs the
    unpaid, past-grace-period SubscriptionFee row DIRECTLY via the DB session -- so the
    only thing that can possibly explain the superadmin succeeding is
    `current_user.role == "superadmin"` in the endpoint itself, exactly as read in
    webapp/app.py (generate_ecr_txt, generate_report, etc: the entire
    get_unpaid_months_for_year/SubscriptionFee check sits inside
    `if current_user.role != "superadmin":`, so it never runs at all for a superadmin).
    """
    res = consultant_a.post("/api/establishments", json={"code": "DELTACO001", "name": "Delta Bypass Co"})
    assert res.status_code == 200
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)

    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "DELTACO001001", "name": "Priya Sharma", "uan": "700000000001"})
    res = consultant_a.post("/api/years/2026-27/wages", json={"member_id": "DELTACO001001", "wages": [15000.0] + [0.0] * 11})
    assert res.status_code == 200

    # Directly construct the unpaid, overdue SubscriptionFee row -- bypassing the lazy
    # sync path entirely so this test doesn't depend on it.
    fee_row = SubscriptionFee(
        establishment_id=est_id, financial_year="2026-27", month="Mar",
        employee_count=1, rate_applied=10.0, amount_due=10.0,
        is_paid=False, paid_date="", payment_reference="", notes=""
    )
    test_db.add(fee_row)
    test_db.commit()

    # Confirm the row is genuinely unpaid and past grace period (grace cutoff for March
    # is 1 day after March 31 -- comfortably in the past relative to any real test run).
    check = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    assert check is not None and check.is_paid is False

    # Consultant session: blocked with 402, as expected.
    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 402
    assert "subscription fee" in res.json()["detail"].lower()

    # Superadmin session, same establishment, same unpaid/overdue row untouched: succeeds.
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200
    assert "Priya Sharma" in res.text

    # The fee row is still unpaid -- the superadmin's success was NOT because the row
    # got marked paid as a side effect; it's a pure role-based bypass.
    still_unpaid = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    assert still_unpaid.is_paid is False

    # Whole-year Form 3A/6A bundle and full-year ECR zip: same bypass.
    res = superadmin_session.get("/api/reports/2026-27")
    assert res.status_code == 200
    res = superadmin_session.get("/api/reports/2026-27/ecr")
    assert res.status_code == 200
