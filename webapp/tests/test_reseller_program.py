import os
import sys
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parent.parent.parent / "test_epf.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from fastapi import HTTPException
from webapp.database import (
    SessionLocal, User, Establishment,
    ResellerProfile, Enrollment, ResellerPayout, ResellerPayoutLine,
)
from webapp.auth import _require_reseller


def test_reseller_profile_and_fk_exist(test_db):
    u = User(name="Reseller One", email="r1@x.com", role="reseller", is_active=True)
    test_db.add(u); test_db.commit(); test_db.refresh(u)
    prof = ResellerProfile(
        user_id=u.id, full_name="RESELLER ONE", mobile="9000000001",
        email="r1@x.com", referral_code="RO1234", upi_id="r1@okhdfc",
        bank_account_number="123", bank_ifsc="HDFC0000001",
        bank_name="HDFC", bank_branch="BBSR", pan="ABCDE1234F",
    )
    test_db.add(prof); test_db.commit()
    est = Establishment(user_id=u.id, code="ORTEST0000000000", name="T",
                        data="{}", referred_by_reseller_id=u.id)
    test_db.add(est); test_db.commit(); test_db.refresh(est)
    assert est.referred_by_reseller_id == u.id


def test_enrollment_and_payout_models_exist(test_db):
    u = User(name="R2", email="r2@x.com", role="reseller", is_active=True)
    test_db.add(u); test_db.commit(); test_db.refresh(u)
    enr = Enrollment(reseller_id=u.id, method="create_handover",
                     contact_email="c@x.com", stage="account_created")
    test_db.add(enr); test_db.commit(); test_db.refresh(enr)
    po = ResellerPayout(reseller_id=u.id, period="2026-05", gross_collected=2000.0,
                        reseller_share_gross=1000.0, tds_amount=100.0,
                        reseller_share_net=900.0, owner_share=1000.0, status="scheduled")
    test_db.add(po); test_db.commit(); test_db.refresh(po)
    line = ResellerPayoutLine(payout_id=po.id, establishment_name="X", fee_amount=2000.0,
                              reseller_share=1000.0)
    test_db.add(line); test_db.commit()
    assert enr.stage == "account_created" and po.status == "scheduled"


def test_require_reseller_rejects_non_reseller():
    c = User(name="C", email="c-grd@x.com", role="consultant", is_active=True)
    with pytest.raises(HTTPException) as ei:
        _require_reseller(c)
    assert ei.value.status_code == 403


def test_require_reseller_allows_reseller():
    r = User(name="R", email="r-grd@x.com", role="reseller", is_active=True)
    assert _require_reseller(r) is r


from webapp.reseller_tokens import make_set_password_token, read_set_password_token


def test_set_password_token_roundtrip():
    tok = make_set_password_token(user_id=42, jti="abc123")
    got = read_set_password_token(tok)
    assert got == {"user_id": 42, "jti": "abc123"}


def test_set_password_token_rejects_tamper():
    tok = make_set_password_token(user_id=42, jti="abc123")
    assert read_set_password_token(tok[:-3] + "zzz") is None


def test_set_password_token_expires():
    tok = make_set_password_token(user_id=42, jti="abc123")
    assert read_set_password_token(tok, max_age_days=-1) is None


def test_read_set_password_token_handles_garbage():
    assert read_set_password_token("") is None
    assert read_set_password_token("not-a-token") is None


def test_set_password_endpoint_sets_hash(client, test_db):
    from webapp.database import Enrollment
    u = User(name="Invitee", email="invitee@x.com", role="employer",
             is_active=True, password_hash=None)
    test_db.add(u); test_db.commit(); test_db.refresh(u)
    test_db.add(Enrollment(reseller_id=u.id, account_user_id=u.id, method="create_handover",
                           contact_email="invitee@x.com", stage="account_created",
                           set_password_jti="jti-1"))
    test_db.commit()
    tok = make_set_password_token(user_id=u.id, jti="jti-1")

    r = client.post("/api/auth/set-password", json={"token": tok, "password": "NewPass@123"})
    assert r.status_code == 200

    login = client.post("/api/auth/login", json={"email": "invitee@x.com", "password": "NewPass@123"})
    assert login.status_code == 200

    r2 = client.post("/api/auth/set-password", json={"token": tok, "password": "Other@123"})
    assert r2.status_code == 400   # consumed link cannot be reused


def test_enrol_reseller_creates_user_profile_and_link(superadmin_session, test_db):
    payload = {
        "full_name": "SURESH PATRA", "mobile": "9776100200",
        "email": "suresh.patra@x.com", "upi_id": "suresh@okaxis",
        "bank_account_number": "11122233344", "bank_ifsc": "SBIN0001234",
        "bank_name": "SBI", "bank_branch": "Cuttack", "pan": "AAAPP1234C",
    }
    r = superadmin_session.post("/api/admin/resellers", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["set_password_url"].startswith("http")
    assert "/set-password?token=" in body["set_password_url"]
    assert len(body["reseller"]["referral_code"]) >= 4

    u = test_db.query(User).filter(User.email == "suresh.patra@x.com").first()
    assert u is not None and u.role == "reseller" and u.password_hash is None

    from webapp.database import ResellerProfile
    prof = test_db.query(ResellerProfile).filter(ResellerProfile.user_id == u.id).first()
    assert prof is not None and prof.payout_details_verified is False


def test_enrol_reseller_rejects_duplicate_email(superadmin_session):
    p = {"full_name": "A", "mobile": "1", "email": "dupe-r@x.com", "upi_id": "a@ok",
         "bank_account_number": "1", "bank_ifsc": "X", "bank_name": "X",
         "bank_branch": "X", "pan": "X"}
    assert superadmin_session.post("/api/admin/resellers", json=p).status_code == 200
    assert superadmin_session.post("/api/admin/resellers", json=p).status_code == 400


def test_verify_payout_toggle(superadmin_session, test_db):
    p = {"full_name": "V", "mobile": "1", "email": "verify-r@x.com", "upi_id": "v@ok",
         "bank_account_number": "1", "bank_ifsc": "X", "bank_name": "X",
         "bank_branch": "X", "pan": "X"}
    rid = superadmin_session.post("/api/admin/resellers", json=p).json()["reseller"]["id"]
    assert superadmin_session.post(f"/api/admin/resellers/{rid}/verify-payout").status_code == 200
    from webapp.database import ResellerProfile
    prof = test_db.query(ResellerProfile).filter(ResellerProfile.user_id == rid).first()
    test_db.refresh(prof)
    assert prof.payout_details_verified is True

    superadmin_session.patch(f"/api/admin/resellers/{rid}", json={"upi_id": "v2@ok"})
    test_db.refresh(prof)
    assert prof.payout_details_verified is False


def test_enrol_reseller_forbidden_for_consultant(consultant_a):
    p = {"full_name": "X", "mobile": "1", "email": "forbid-r@x.com", "upi_id": "x@ok",
         "bank_account_number": "1", "bank_ifsc": "X", "bank_name": "X",
         "bank_branch": "X", "pan": "X"}
    assert consultant_a.post("/api/admin/resellers", json=p).status_code == 403


def test_patch_reseller_email_syncs_user_and_blocks_dup(superadmin_session, test_db):
    p = {"full_name": "Sync Me", "mobile": "1", "email": "sync-r@x.com", "upi_id": "s@ok",
         "bank_account_number": "1", "bank_ifsc": "X", "bank_name": "X",
         "bank_branch": "X", "pan": "X"}
    rid = superadmin_session.post("/api/admin/resellers", json=p).json()["reseller"]["id"]

    r = superadmin_session.patch(f"/api/admin/resellers/{rid}", json={"email": "sync2-r@x.com"})
    assert r.status_code == 200
    u = test_db.query(User).filter(User.id == rid).first()
    test_db.refresh(u)
    assert u.email == "sync2-r@x.com"

    # dup against an existing account
    dup = superadmin_session.patch(f"/api/admin/resellers/{rid}",
                                   json={"email": "superadmin.test@epfdashboard.com"})
    assert dup.status_code == 400


def test_patch_reseller_rejects_bad_status(superadmin_session):
    p = {"full_name": "St", "mobile": "1", "email": "status-r@x.com", "upi_id": "s@ok",
         "bank_account_number": "1", "bank_ifsc": "X", "bank_name": "X",
         "bank_branch": "X", "pan": "X"}
    rid = superadmin_session.post("/api/admin/resellers", json=p).json()["reseller"]["id"]
    assert superadmin_session.patch(f"/api/admin/resellers/{rid}",
                                    json={"status": "bogus"}).status_code == 400


def _create_est_payload(**over):
    p = {"code": "ORBBS9990000000", "name": "SAMPLE UDYOG", "address": "Cuttack",
         "coverage_date": "2020-04-01", "contact_name": "Manoj Das",
         "contact_email": "manoj.das@sampleudyog.com", "contact_mobile": "9800012345",
         "billing_mode": "flat_fee", "flat_fee_amount": 2000, "custom_rate_per_employee": None}
    p.update(over)
    return p


def test_reseller_creates_tagged_establishment_and_user(reseller_a, test_db):
    r = reseller_a.post("/api/reseller/establishments", json=_create_est_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "/set-password?token=" in body["set_password_url"]

    est = test_db.query(Establishment).filter(Establishment.code == "ORBBS9990000000").first()
    assert est is not None
    assert est.referred_by_reseller_id == reseller_a.user_id
    assert est.billing_mode == "flat_fee" and est.flat_fee_amount == 2000

    owner = test_db.query(User).filter(User.email == "manoj.das@sampleudyog.com").first()
    assert owner is not None and owner.role == "employer" and owner.password_hash is None
    assert est.user_id == owner.id


def test_reseller_per_employee_billing(reseller_a, test_db):
    r = reseller_a.post("/api/reseller/establishments", json=_create_est_payload(
        code="ORBBS9990000001", contact_email="c2@x.com",
        billing_mode="per_employee", flat_fee_amount=None, custom_rate_per_employee=30))
    assert r.status_code == 200
    est = test_db.query(Establishment).filter(Establishment.code == "ORBBS9990000001").first()
    assert est.billing_mode == "per_employee" and est.custom_rate_per_employee == 30


def test_reseller_cannot_self_refer(reseller_a):
    r = reseller_a.post("/api/reseller/establishments",
                        json=_create_est_payload(contact_email="reseller_a@testepf.com"))
    assert r.status_code == 400


def test_reseller_enrollment_pipeline_and_resend(reseller_a, test_db):
    reseller_a.post("/api/reseller/establishments", json=_create_est_payload(
        code="ORBBS9990000002", contact_email="pipe@x.com"))
    lst = reseller_a.get("/api/reseller/enrollments").json()["enrollments"]
    assert any(e["contact_email"] == "pipe@x.com" and e["stage"] == "account_created" for e in lst)
    eid = [e["id"] for e in lst if e["contact_email"] == "pipe@x.com"][0]
    rs = reseller_a.post(f"/api/reseller/enrollments/{eid}/resend")
    assert rs.status_code == 200 and "/set-password?token=" in rs.json()["set_password_url"]


def test_consultant_cannot_hit_reseller_create(consultant_a):
    assert consultant_a.post("/api/reseller/establishments", json=_create_est_payload()).status_code == 403
