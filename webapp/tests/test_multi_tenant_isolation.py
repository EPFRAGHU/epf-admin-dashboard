import pytest
from webapp.auth import verify_password
from webapp.database import User, Establishment, SubscriptionFee, AdvanceCreditLedger


def test_tenant_isolation_establishments(consultant_a, consultant_b):
    """
    Verify that establishments and employee records created by Consultant A
    are completely isolated and invisible to Consultant B, and vice versa.
    """
    # 1. Consultant A creates an establishment
    res_a = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2015", 
        "code": "ORBBS0000001000",
        "name": "ALPHA ENTERPRISES",
        "address": "Bhubaneswar Tech Park",
        "coverage_date": "01-04-2024"
    })
    assert res_a.status_code == 200, f"Consultant A creation failed: {res_a.text}"
    est_a_id = res_a.json()["establishment"]["id"]

    # 2. Consultant B creates an establishment
    res_b = consultant_b.post("/api/establishments", json={"coverage_date": "01-04-2015", 
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
    res_a = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2015", 
        "code": "ORCONCA00001",
        "name": "CONCURRENT ORG A",
        "address": "Zone A",
        "coverage_date": "01-01-2024"
    })
    assert res_a.status_code == 200
    est_a_id = res_a.json()["establishment"]["id"]

    # Step 2: B creates
    res_b = consultant_b.post("/api/establishments", json={"coverage_date": "01-04-2015", 
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
    res_a = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2015", 
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
    res_b_create = consultant_b.post("/api/establishments", json={"coverage_date": "01-04-2015", 
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


def test_logout_invalidates_token_server_side(consultant_a):
    """
    Security regression test: /api/auth/logout must genuinely invalidate the calling
    user's token server-side (via token_valid_after), not just tell the frontend to
    forget it. Before the fix, logout was a complete no-op and a captured token stayed
    valid for its full 7-day lifetime after "logging out".
    """
    # 1. Token works before logout
    res_before = consultant_a.get("/api/auth/me")
    assert res_before.status_code == 200

    # 2. Call logout with that same token
    res_logout = consultant_a.post("/api/auth/logout")
    assert res_logout.status_code == 200
    assert res_logout.json().get("ok") is True

    # 3. The SAME (pre-logout) token must now be rejected
    res_after = consultant_a.get("/api/auth/me")
    assert res_after.status_code == 401, (
        f"Token issued before logout still works after logout: {res_after.status_code} {res_after.text}"
    )

    # 4. A fresh login (new token) must still work -- logout invalidates old tokens,
    # it doesn't lock the account out
    res_login = consultant_a.client.post("/api/auth/login", json={
        "email": "consultant_a@testepf.com",
        "password": "PasswordA@123"
    })
    assert res_login.status_code == 200
    new_token = res_login.json()["token"]
    res_new = consultant_a.client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert res_new.status_code == 200


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
    res = consultant_a.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": "DELTACO001", "name": "Delta Bypass Co"})
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


# ─────────────────────────────────────────────────────────────────────────
# Task B security audit: IDOR sweep across every establishment-scoped
# resource type. Branch/Division/Unit/Employee/Wages/Remittances all live
# inside the single Establishment.data JSON blob and are only ever resolved
# from within the caller's own in-memory Project via get_active_establishment
# -- so the only way to attempt IDOR against them is to spoof the resolved
# establishment itself (X-Establishment-Id header / est_id query param)
# while authenticated as the wrong consultant. These tests confirm that
# spoofing is blocked at the get_active_establishment choke point, before
# any per-resource id is even looked at.
# ─────────────────────────────────────────────────────────────────────────

def _create_est(consultant, code, name):
    res = consultant.post("/api/establishments", json={"coverage_date": "01-04-2015", "code": code, "name": name})
    assert res.status_code == 200, res.text
    return res.json()["establishment"]["id"]


def test_org_structure_idor_branch_division_unit(consultant_a, consultant_b):
    """Consultant A creates a Branch/Division/Unit hierarchy; Consultant B, targeting
    A's establishment directly via a spoofed X-Establishment-Id header, must be
    blocked (403) on every read/write/delete -- for the branch itself and for the
    division/unit nested under it."""
    est_a = _create_est(consultant_a, "IDORORG0000A", "IDOR Org Structure Co")
    consultant_a.set_establishment(est_a)

    res = consultant_a.post("/api/org-structure/branches", json={"name": "HQ Branch"})
    assert res.status_code == 200
    branch_id = res.json()["branches"][-1]["id"]

    res = consultant_a.post("/api/org-structure/divisions", json={"name": "Ops Division", "branch_id": branch_id})
    assert res.status_code == 200
    division_id = res.json()["divisions"][-1]["id"]

    res = consultant_a.post("/api/org-structure/units", json={"name": "Support Unit", "division_id": division_id})
    assert res.status_code == 200
    unit_id = res.json()["units"][-1]["id"]

    _create_est(consultant_b, "IDORORG0000B", "IDOR Org Structure Co B")
    spoof_headers = {"X-Establishment-Id": str(est_a)}

    # Reads
    assert consultant_b.get("/api/org-structure", headers=spoof_headers).status_code == 403

    # Writes / renames
    assert consultant_b.put(f"/api/org-structure/branches/{branch_id}", json={"name": "Hijacked"}, headers=spoof_headers).status_code == 403
    assert consultant_b.put(f"/api/org-structure/divisions/{division_id}", json={"name": "Hijacked"}, headers=spoof_headers).status_code == 403
    assert consultant_b.put(f"/api/org-structure/units/{unit_id}", json={"name": "Hijacked"}, headers=spoof_headers).status_code == 403

    # Deletes
    assert consultant_b.delete(f"/api/org-structure/units/{unit_id}", headers=spoof_headers).status_code == 403
    assert consultant_b.delete(f"/api/org-structure/divisions/{division_id}", headers=spoof_headers).status_code == 403
    assert consultant_b.delete(f"/api/org-structure/branches/{branch_id}", headers=spoof_headers).status_code == 403

    # Confirm nothing was actually touched
    org = consultant_a.get("/api/org-structure").json()
    assert any(b["id"] == branch_id and b["name"] == "HQ Branch" for b in org["branches"])
    assert any(d["id"] == division_id and d["name"] == "Ops Division" for d in org["divisions"])
    assert any(u["id"] == unit_id and u["name"] == "Support Unit" for u in org["units"])


def test_employee_idor(consultant_a, consultant_b):
    """Consultant B cannot GET/PUT/DELETE Consultant A's employee master data by
    spoofing A's establishment id."""
    est_a = _create_est(consultant_a, "IDOREMP0000A", "IDOR Employee Co")
    consultant_a.set_establishment(est_a)
    res = consultant_a.post("/api/employees", json={"member_id": "IDE0001", "name": "Target Employee", "uan": "100777700001"})
    assert res.status_code == 200

    _create_est(consultant_b, "IDOREMP0000B", "IDOR Employee Co B")
    spoof_headers = {"X-Establishment-Id": str(est_a)}

    assert consultant_b.get("/api/employees", headers=spoof_headers).status_code == 403
    res = consultant_b.put("/api/employees/IDE0001", json={"member_id": "IDE0001", "name": "Hijacked", "uan": "100777700001"}, headers=spoof_headers)
    assert res.status_code == 403
    assert consultant_b.delete("/api/employees/IDE0001", headers=spoof_headers).status_code == 403

    # Employee survives untouched under A
    emps = consultant_a.get("/api/employees").json()["employees"]
    assert any(e["member_id"] == "IDE0001" and e["name"] == "Target Employee" for e in emps)


def test_remittance_idor(consultant_a, consultant_b):
    """Consultant B cannot read or overwrite Consultant A's Form 12A remittance rows
    by spoofing A's establishment id."""
    est_a = _create_est(consultant_a, "IDORREM0000A", "IDOR Remittance Co")
    consultant_a.set_establishment(est_a)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/years/2026-27/remittances/bulk", json={
        "remittances": [{"month_label": "Apr", "trrn": "TRRN_A_SECRET", "crrn": "", "credit_date": ""}]
    })
    assert res.status_code == 200

    _create_est(consultant_b, "IDORREM0000B", "IDOR Remittance Co B")
    spoof_headers = {"X-Establishment-Id": str(est_a)}

    res = consultant_b.get("/api/years/2026-27/remittances", headers=spoof_headers)
    assert res.status_code == 403
    assert "TRRN_A_SECRET" not in res.text

    res = consultant_b.post("/api/years/2026-27/remittances/bulk", json={
        "remittances": [{"month_label": "Apr", "trrn": "HIJACKED_TRRN", "crrn": "", "credit_date": ""}]
    }, headers=spoof_headers)
    assert res.status_code == 403


def test_subscription_fee_idor(consultant_a, consultant_b, test_db):
    """Consultant B cannot view or act on Consultant A's SubscriptionFee row -- neither
    by spoofing A's establishment on the consultant self-serve endpoints, nor via the
    superadmin-only per-establishment endpoints (which must reject a non-superadmin
    outright regardless of whose establishment is targeted)."""
    est_a = _create_est(consultant_a, "IDORFEE0000A", "IDOR Fee Co")
    consultant_a.set_establishment(est_a)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "IDF0001", "name": "Fee Employee", "uan": "100777700099"})
    consultant_a.post("/api/years/2026-27/wages", json={"member_id": "IDF0001", "wages": [15000.0] + [0.0] * 11})

    fee_row = SubscriptionFee(
        establishment_id=est_a, financial_year="2026-27", month="Apr",
        employee_count=1, rate_applied=10.0, amount_due=10.0,
        is_paid=False, paid_date="", payment_reference="", notes=""
    )
    test_db.add(fee_row)
    test_db.commit()

    _create_est(consultant_b, "IDORFEE0000B", "IDOR Fee Co B")
    spoof_headers = {"X-Establishment-Id": str(est_a)}

    # Consultant self-serve endpoint, spoofed establishment -> blocked before the fee row is ever looked at
    res = consultant_b.get("/api/establishment/subscription-fees/month-detail?year=2026-27&month=Apr", headers=spoof_headers)
    assert res.status_code == 403

    # Superadmin-only per-establishment endpoint targeted by a mere consultant -> flat 403, ownership irrelevant
    res = consultant_b.get(f"/api/admin/establishments/{est_a}/subscription-fees")
    assert res.status_code == 403


def test_advance_credit_ledger_idor(consultant_a, consultant_b, test_db):
    """Consultant B cannot refresh or view Consultant A's AdvanceCreditLedger row by
    spoofing A's establishment id on the consultant self-serve endpoint."""
    est_a = _create_est(consultant_a, "IDORADV0000A", "IDOR Advance Co")
    consultant_a.set_establishment(est_a)

    ledger_row = AdvanceCreditLedger(
        establishment_id=est_a, entry_type="topup", amount=500.0,
        status="pending", cashfree_order_id="adv_idor_test_order"
    )
    test_db.add(ledger_row)
    test_db.commit()

    _create_est(consultant_b, "IDORADV0000B", "IDOR Advance Co B")
    spoof_headers = {"X-Establishment-Id": str(est_a)}

    res = consultant_b.post("/api/establishment/advance-credit/refresh-status", json={"order_id": "adv_idor_test_order"}, headers=spoof_headers)
    assert res.status_code == 403

    # Superadmin-only per-establishment ledger endpoint -- flat 403 for a consultant regardless of target
    res = consultant_b.post(f"/api/admin/establishments/{est_a}/advance-credit/{ledger_row.id}/refresh-status", json={})
    assert res.status_code == 403


def test_signup_does_not_leak_other_pending_requests(client):
    """POST /api/signup's response must never surface any other pending signup
    request's data -- only a generic ack for the caller's own submission, even when
    a duplicate-email/duplicate-establishment-code rejection path is hit."""
    res1 = client.post("/api/signup", json={
        "role": "employer", "name": "First Applicant", "email": "first.applicant@idortest.com",
        "password": "Password@123", "agreed_to_terms": True,
        "establishment_code": "IDORSIGNUP001", "establishment_name": "First Applicant Co",
        "coverage_date": "01-04-2015",
    })
    assert res1.status_code == 200
    body1 = res1.json()
    assert set(body1.keys()) <= {"ok", "message"}

    # Second applicant tries the same establishment code -- rejected, but the error
    # must be a generic duplicate message, not a leak of the first applicant's details.
    res2 = client.post("/api/signup", json={
        "role": "employer", "name": "Second Applicant", "email": "second.applicant@idortest.com",
        "password": "Password@123", "agreed_to_terms": True,
        "establishment_code": "IDORSIGNUP001", "establishment_name": "Second Applicant Co",
        "coverage_date": "01-04-2015",
    })
    assert res2.status_code == 400
    assert "First Applicant" not in res2.text
    assert "first.applicant@idortest.com" not in res2.text


def test_admin_signup_requests_is_superadmin_only(consultant_a, superadmin_session, client):
    """GET /api/admin/signup-requests (which returns every pending applicant's name,
    email, mobile, and establishment details) must be genuinely superadmin-only."""
    client.post("/api/signup", json={
        "role": "consultant", "name": "Gate Check Applicant", "email": "gatecheck@idortest.com",
        "password": "Password@123", "agreed_to_terms": True,
    })

    res = consultant_a.get("/api/admin/signup-requests")
    assert res.status_code == 403
    assert "Gate Check Applicant" not in res.text

    res = client.get("/api/admin/signup-requests")
    assert res.status_code == 401

    res = superadmin_session.get("/api/admin/signup-requests")
    assert res.status_code == 200
    assert any(r["name"] == "Gate Check Applicant" for r in res.json()["requests"])


def test_rate_override_never_leaks_via_establishment_list(consultant_a, consultant_b, superadmin_session, test_db):
    """custom_rate_per_employee is billing-sensitive; GET /api/establishments (the
    list endpoint) must never include it for a non-superadmin caller, and it must
    never surface Consultant A's rate override to Consultant B."""
    est_a = _create_est(consultant_a, "IDORRATE0000A", "IDOR Rate Co")
    est_row = test_db.query(Establishment).filter(Establishment.id == est_a).first()
    est_row.custom_rate_per_employee = 42.0
    test_db.commit()

    listing = consultant_a.get("/api/establishments").json()["establishments"]
    for row in listing:
        assert "custom_rate_per_employee" not in row

    _create_est(consultant_b, "IDORRATE0000B", "IDOR Rate Co B")
    listing_b = consultant_b.get("/api/establishments").json()["establishments"]
    for row in listing_b:
        assert "custom_rate_per_employee" not in row

    # Superadmin's cross-tenant establishment list is allowed to see it -- it's the
    # billing admin, and the rate is scoped to the specific establishment row.
    admin_listing = superadmin_session.get(f"/api/admin/users/{consultant_a.user_id}/establishments").json()
    assert any(e["id"] == est_a and e.get("custom_rate_per_employee") == 42.0 for e in admin_listing["establishments"])
