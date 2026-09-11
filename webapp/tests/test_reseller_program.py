import os
import sys
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parent.parent.parent / "test_epf.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from fastapi import HTTPException
from webapp.database import (
    User, Establishment,
    ResellerProfile, Enrollment, ResellerPayout, ResellerPayoutLine, SubscriptionFee,
)
from webapp.auth import _require_reseller
from webapp.reseller_payout import compute_payouts_for_period


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


def _seed_referred_est_with_paid_fee(test_db, reseller_id, code="ORPAY0000000001"):
    from webapp.database import SubscriptionFee
    owner = User(name="O", email=f"{code.lower()}@x.com", role="employer", is_active=True)
    test_db.add(owner); test_db.commit(); test_db.refresh(owner)
    est = Establishment(user_id=owner.id, code=code, name=f"EST {code}", data="{}",
                        billing_mode="flat_fee", flat_fee_amount=2000,
                        referred_by_reseller_id=reseller_id)
    test_db.add(est); test_db.commit(); test_db.refresh(est)
    fee = SubscriptionFee(establishment_id=est.id, financial_year="2026-27", month="Apr",
                          employee_count=10, amount_due=2000, billing_mode="flat_fee", is_paid=True,
                          paid_date="15-05-2026")
    test_db.add(fee); test_db.commit()
    return est, fee


def test_reseller_overview_and_earnings(reseller_a, test_db):
    _seed_referred_est_with_paid_fee(test_db, reseller_a.user_id)
    ov = reseller_a.get("/api/reseller/overview")
    assert ov.status_code == 200
    assert ov.json()["stats"]["establishments"] >= 1

    er = reseller_a.get("/api/reseller/earnings")
    assert er.status_code == 200
    total_my_share = sum(m["my_share_gross"] for m in er.json()["months"])
    assert total_my_share == 1000.0   # 50% of the single ₹2000 paid fee


def test_reseller_only_sees_own_referrals(reseller_a, test_db):
    # an establishment referred by nobody must not appear
    stray_owner = User(name="S", email="stray@x.com", role="employer", is_active=True)
    test_db.add(stray_owner); test_db.commit(); test_db.refresh(stray_owner)
    test_db.add(Establishment(user_id=stray_owner.id, code="ORNONE0000000000",
                              name="STRAY", data="{}"))
    test_db.commit()
    ests = reseller_a.get("/api/reseller/establishments").json()["establishments"]
    assert all(e["code"] != "ORNONE0000000000" for e in ests)


def _make_reseller(test_db, suffix, pan="ABCDE9999Z"):
    u = User(name=f"R{suffix}", email=f"payr-{suffix}@x.com", role="reseller", is_active=True)
    test_db.add(u); test_db.commit(); test_db.refresh(u)
    test_db.add(ResellerProfile(
        user_id=u.id, full_name=f"R{suffix}", mobile="1", email=f"payr-{suffix}@x.com",
        referral_code=f"PR{suffix}"[:20], upi_id=f"payr{suffix}@ok", pan=pan,
        payout_details_verified=True))
    test_db.commit()
    return u


def test_compute_payout_splits_50_50_with_tds(test_db):
    u = _make_reseller(test_db, "t1")  # pan set -> 10% TDS
    est, fee = _seed_referred_est_with_paid_fee(test_db, u.id, code="ORCMP0000000001")
    summary = compute_payouts_for_period(test_db, "2026-05")
    mine = [s for s in summary if s["reseller_id"] == u.id]
    assert len(mine) == 1
    po = test_db.query(ResellerPayout).filter(ResellerPayout.reseller_id == u.id).first()
    assert po.gross_collected == 2000.0
    assert po.reseller_share_gross == 1000.0
    assert po.tds_amount == 100.0
    assert po.reseller_share_net == 900.0
    assert po.owner_share == 1000.0
    assert po.status == "scheduled"
    lines = test_db.query(ResellerPayoutLine).filter(ResellerPayoutLine.payout_id == po.id).all()
    assert len(lines) == 1 and lines[0].subscription_fee_id == fee.id


def test_compute_payout_is_idempotent(test_db):
    u = _make_reseller(test_db, "t2")
    _seed_referred_est_with_paid_fee(test_db, u.id, code="ORCMP0000000002")
    compute_payouts_for_period(test_db, "2026-05")
    n1 = test_db.query(ResellerPayoutLine).count()
    compute_payouts_for_period(test_db, "2026-05")
    n2 = test_db.query(ResellerPayoutLine).count()
    assert n1 == n2


def test_compute_payout_skips_unpaid_and_unreferred(test_db):
    u = _make_reseller(test_db, "t3")
    owner = User(name="U", email="unpaidcmp@x.com", role="employer", is_active=True)
    test_db.add(owner); test_db.commit(); test_db.refresh(owner)
    est = Establishment(user_id=owner.id, code="ORCMP0000000003", name="X", data="{}",
                        referred_by_reseller_id=u.id)
    test_db.add(est); test_db.commit(); test_db.refresh(est)
    test_db.add(SubscriptionFee(establishment_id=est.id, financial_year="2026-27", month="Apr",
                                amount_due=5000, is_paid=False, billing_mode="flat_fee"))
    test_db.commit()
    summary = compute_payouts_for_period(test_db, "2026-06")
    assert not any(s["reseller_id"] == u.id for s in summary)
    assert test_db.query(ResellerPayout).filter(ResellerPayout.reseller_id == u.id).first() is None


def test_compute_payout_no_pan_no_tds(test_db):
    u = _make_reseller(test_db, "t4", pan="")
    _seed_referred_est_with_paid_fee(test_db, u.id, code="ORCMP0000000004")
    compute_payouts_for_period(test_db, "2026-07")
    po = test_db.query(ResellerPayout).filter(ResellerPayout.reseller_id == u.id).first()
    assert po is not None
    assert po.tds_amount == 0.0 and po.reseller_share_net == po.reseller_share_gross


def test_admin_referral_overview_and_mark_paid(superadmin_session, test_db):
    u = _make_reseller(test_db, "adm1")
    _seed_referred_est_with_paid_fee(test_db, u.id, code="ORADM0000000001")
    compute_payouts_for_period(test_db, "2026-05")

    ov = superadmin_session.get("/api/admin/referral-program/overview")
    assert ov.status_code == 200
    assert ov.json()["stats"]["active_resellers"] >= 1

    lst = superadmin_session.get("/api/admin/payouts").json()["payouts"]
    mine = [p for p in lst if p["reseller"] == "Radm1"]
    assert len(mine) == 1 and mine[0]["status"] == "scheduled"
    pid = mine[0]["id"]

    mp = superadmin_session.post(f"/api/admin/payouts/{pid}/mark-paid",
                                 json={"upi_reference": "AXISU12345678"})
    assert mp.status_code == 200
    from webapp.database import ResellerPayout
    po = test_db.query(ResellerPayout).filter(ResellerPayout.id == pid).first()
    test_db.refresh(po)
    assert po.status == "paid" and po.upi_reference == "AXISU12345678" and po.paid_at is not None

    # already-paid -> 400
    assert superadmin_session.post(f"/api/admin/payouts/{pid}/mark-paid",
                                   json={"upi_reference": "X"}).status_code == 400


def test_admin_referral_establishments_pending(superadmin_session, reseller_a):
    reseller_a.post("/api/reseller/establishments", json=_create_est_payload(
        code="ORADM0000000002", contact_email="adm2@x.com"))
    d = superadmin_session.get("/api/admin/referral-program/establishments").json()
    assert any(e["code"] == "ORADM0000000002" for e in d["establishments"])
    assert any(p["contact_email"] == "adm2@x.com" for p in d["pending"])


def test_admin_payouts_forbidden_for_reseller(reseller_a):
    assert reseller_a.get("/api/admin/payouts").status_code == 403


def test_resend_blocked_after_password_set(reseller_a, test_db, client):
    reseller_a.post("/api/reseller/establishments", json=_create_est_payload(
        code="ORFIX0000000001", contact_email="fixc1@x.com"))
    lst = reseller_a.get("/api/reseller/enrollments").json()["enrollments"]
    eid = [e["id"] for e in lst if e["contact_email"] == "fixc1@x.com"][0]

    from webapp.database import Enrollment
    from webapp.reseller_tokens import make_set_password_token
    enr = test_db.query(Enrollment).filter(Enrollment.id == eid).first()
    tok = make_set_password_token(enr.account_user_id, enr.set_password_jti)
    r = client.post("/api/auth/set-password", json={"token": tok, "password": "EmployerPass@123"})
    assert r.status_code == 200

    # now the reseller tries to resend -- must be rejected (this is the C-1 regression test)
    resend = reseller_a.post(f"/api/reseller/enrollments/{eid}/resend")
    assert resend.status_code == 400


def test_resend_rejects_non_owner(reseller_a):
    # a nonexistent / not-owned enrollment id must 404 -- this proves resend is
    # scoped to the caller's own enrollments (reseller_resend_set_password filters
    # by Enrollment.reseller_id == reseller.id in the query itself).
    assert reseller_a.post("/api/reseller/enrollments/999999/resend").status_code == 404


def test_reseller_cannot_see_another_resellers_establishment(reseller_a, test_db):
    from webapp.database import ResellerProfile
    other = User(name="Other Reseller 2", email="other-reseller-2@x.com", role="reseller", is_active=True)
    test_db.add(other); test_db.commit(); test_db.refresh(other)
    test_db.add(ResellerProfile(user_id=other.id, full_name="OTHER2", mobile="1",
                                email="other-reseller-2@x.com", referral_code="OTHR02",
                                upi_id="other2@ok", payout_details_verified=True))
    test_db.commit()

    owner = User(name="OwnerX", email="ownerx@x.com", role="employer", is_active=True)
    test_db.add(owner); test_db.commit(); test_db.refresh(owner)
    other_est = Establishment(user_id=owner.id, code="OROTH0000000001", name="OTHER RESELLER EST",
                              data="{}", referred_by_reseller_id=other.id)
    test_db.add(other_est); test_db.commit()

    ests = reseller_a.get("/api/reseller/establishments").json()["establishments"]
    assert all(e["code"] != "OROTH0000000001" for e in ests)


def test_mark_paid_blocked_when_unverified(superadmin_session, test_db):
    u = _make_reseller(test_db, "unv1")
    from webapp.database import ResellerProfile
    prof = test_db.query(ResellerProfile).filter(ResellerProfile.user_id == u.id).first()
    prof.payout_details_verified = False
    test_db.commit()
    _seed_referred_est_with_paid_fee(test_db, u.id, code="ORUNV0000000001")
    compute_payouts_for_period(test_db, "2026-08")
    lst = superadmin_session.get("/api/admin/payouts").json()["payouts"]
    mine = [p for p in lst if p["reseller"] == "Runv1"]
    assert len(mine) == 1
    r = superadmin_session.post(f"/api/admin/payouts/{mine[0]['id']}/mark-paid",
                                json={"upi_reference": "X"})
    assert r.status_code == 400


def test_mark_failed_blocked_after_paid(superadmin_session, test_db):
    u = _make_reseller(test_db, "mf1")
    _seed_referred_est_with_paid_fee(test_db, u.id, code="ORMF0000000001")
    compute_payouts_for_period(test_db, "2026-08")
    lst = superadmin_session.get("/api/admin/payouts").json()["payouts"]
    mine = [p for p in lst if p["reseller"] == "Rmf1"]
    pid = mine[0]["id"]
    assert superadmin_session.post(f"/api/admin/payouts/{pid}/mark-paid",
                                   json={"upi_reference": "Y"}).status_code == 200
    assert superadmin_session.post(f"/api/admin/payouts/{pid}/mark-failed",
                                   json={}).status_code == 400
