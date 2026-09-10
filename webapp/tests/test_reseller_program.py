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
