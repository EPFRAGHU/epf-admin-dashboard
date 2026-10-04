"""Core tests for the consultant monthly plan: activity check and confirmation."""
import uuid
from datetime import datetime, timezone

from webapp.database import User, ConsultantPlanPayment, ActivityLog
from webapp.app import (
    is_consultant_plan_active, _confirm_plan_payment, _plan_payment_amount,
    PLAN_COVERED_REFERENCE,
)

OCT_2026 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
NOV_2026 = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)


def _make_user(db, plan_amount=2000.0):
    user = User(
        name="Plan Test",
        email="plan_%s@testepf.com" % uuid.uuid4().hex[:10],
        password_hash="x",
        role="consultant",
        is_active=True,
        consultant_plan_amount=plan_amount,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_row(db, user, months=1, status="pending", covered_from=None, covered_to=None):
    row = ConsultantPlanPayment(
        user_id=user.id, months=months, amount=months * 2000.0, status=status,
        covered_from=covered_from, covered_to=covered_to,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _plan_logs(db, user):
    return db.query(ActivityLog).filter(
        ActivityLog.action_type == "plan_payment_confirmed",
        ActivityLog.user_id == user.id,
    ).all()


def test_constant_and_amount_helper(test_db):
    assert PLAN_COVERED_REFERENCE == "Covered by consultant plan"
    user = _make_user(test_db, plan_amount=1999.99)
    assert _plan_payment_amount(user, 3) == round(3 * 1999.99, 2)


def test_inactive_for_missing_user(test_db):
    assert is_consultant_plan_active(test_db, None, now=OCT_2026) is False
    assert is_consultant_plan_active(test_db, 99999999, now=OCT_2026) is False


def test_inactive_without_plan_amount_even_with_old_payments(test_db):
    user = _make_user(test_db, plan_amount=None)
    _make_row(test_db, user, months=3, status="manual",
              covered_from="2026-10", covered_to="2026-12")
    assert is_consultant_plan_active(test_db, user.id, now=OCT_2026) is False


def test_manual_payment_covers_current_month_only(test_db):
    user = _make_user(test_db)
    row = _make_row(test_db, user, months=1, status="pending")
    assert is_consultant_plan_active(test_db, user.id, now=OCT_2026) is False

    _confirm_plan_payment(test_db, row, "CASH-1", source="manual", now=OCT_2026)
    test_db.refresh(row)
    assert row.status == "manual"
    assert row.payment_reference == "CASH-1"
    assert (row.covered_from, row.covered_to) == ("2026-10", "2026-10")
    assert is_consultant_plan_active(test_db, user.id, now=OCT_2026) is True
    assert is_consultant_plan_active(test_db, user.id, now=NOV_2026) is False


def test_cashfree_confirmation_sets_confirmed(test_db):
    user = _make_user(test_db)
    row = _make_row(test_db, user, months=2)
    _confirm_plan_payment(test_db, row, "CF-123", now=OCT_2026)
    test_db.refresh(row)
    assert row.status == "confirmed"
    assert (row.covered_from, row.covered_to) == ("2026-10", "2026-11")
    assert is_consultant_plan_active(test_db, user.id, now=NOV_2026) is True


def test_back_to_back_purchases_extend_not_overlap(test_db):
    user = _make_user(test_db)
    first = _make_row(test_db, user, months=6)
    second = _make_row(test_db, user, months=3)
    _confirm_plan_payment(test_db, first, "R1", now=OCT_2026)
    _confirm_plan_payment(test_db, second, "R2", now=OCT_2026)
    test_db.refresh(first)
    test_db.refresh(second)
    assert (first.covered_from, first.covered_to) == ("2026-10", "2027-03")
    assert (second.covered_from, second.covered_to) == ("2027-04", "2027-06")


def test_confirm_is_idempotent(test_db):
    user = _make_user(test_db)
    row = _make_row(test_db, user, months=2)
    _confirm_plan_payment(test_db, row, "R1", verified_by=user.id, now=OCT_2026)
    test_db.refresh(row)
    before = (row.covered_from, row.covered_to)
    # Second call, even later and with a different reference, must be a no-op.
    _confirm_plan_payment(test_db, row, "R2", verified_by=user.id, now=NOV_2026)
    test_db.refresh(row)
    assert (row.covered_from, row.covered_to) == before == ("2026-10", "2026-11")
    assert row.payment_reference == "R1"
    assert len(_plan_logs(test_db, user)) == 1


def test_confirm_writes_one_activity_log(test_db):
    user = _make_user(test_db)
    row = _make_row(test_db, user, months=1)
    before = test_db.query(ActivityLog).filter(
        ActivityLog.action_type == "plan_payment_confirmed").count()
    _confirm_plan_payment(test_db, row, "R1", verified_by=user.id, now=OCT_2026)
    _confirm_plan_payment(test_db, row, "R1", verified_by=user.id, now=OCT_2026)
    after = test_db.query(ActivityLog).filter(
        ActivityLog.action_type == "plan_payment_confirmed").count()
    assert after - before == 1


def test_pending_and_rejected_rows_grant_nothing(test_db):
    user = _make_user(test_db)
    # Even with coverage fields populated, only confirmed/manual statuses count.
    _make_row(test_db, user, status="pending", covered_from="2026-10", covered_to="2026-12")
    _make_row(test_db, user, status="pending_verification", covered_from="2026-10", covered_to="2026-12")
    _make_row(test_db, user, status="rejected", covered_from="2026-10", covered_to="2026-12")
    assert is_consultant_plan_active(test_db, user.id, now=OCT_2026) is False


def test_confirmed_row_without_coverage_grants_nothing(test_db):
    user = _make_user(test_db)
    _make_row(test_db, user, status="confirmed")
    assert is_consultant_plan_active(test_db, user.id, now=OCT_2026) is False


def test_other_pending_rows_do_not_shift_allocation(test_db):
    user = _make_user(test_db)
    # A rejected row with stale coverage must not push the next window out.
    _make_row(test_db, user, status="rejected", covered_from="2026-10", covered_to="2027-09")
    row = _make_row(test_db, user, months=1)
    _confirm_plan_payment(test_db, row, "R1", now=OCT_2026)
    test_db.refresh(row)
    assert (row.covered_from, row.covered_to) == ("2026-10", "2026-10")


def test_lapsed_window_not_active_next_month(test_db):
    user = _make_user(test_db)
    row = _make_row(test_db, user, months=1)
    _confirm_plan_payment(test_db, row, "R1", now=OCT_2026)
    assert is_consultant_plan_active(test_db, user.id, now=OCT_2026) is True
    assert is_consultant_plan_active(test_db, user.id, now=NOV_2026) is False
    # A purchase after lapse starts from the current month, not the old window.
    later = _make_row(test_db, user, months=1)
    _confirm_plan_payment(test_db, later, "R2", now=NOV_2026)
    test_db.refresh(later)
    assert (later.covered_from, later.covered_to) == ("2026-11", "2026-11")
    assert is_consultant_plan_active(test_db, user.id, now=NOV_2026) is True


def test_ist_month_boundary(test_db):
    user = _make_user(test_db)
    row = _make_row(test_db, user, months=1)
    # 2026-10-31 20:00 UTC is already 2026-11-01 in IST.
    boundary = datetime(2026, 10, 31, 20, 0, tzinfo=timezone.utc)
    _confirm_plan_payment(test_db, row, "R1", now=boundary)
    test_db.refresh(row)
    assert row.covered_from == "2026-11"
