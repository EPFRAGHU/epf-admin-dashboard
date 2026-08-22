"""
EPF Admin Dashboard — Multi-Tenant Web Backend
==============================================
FastAPI server with JWT authentication, tenant-scoped data isolation,
superadmin management, consultant establishment tracking, and payment compliance.
"""

import os
import sys
import tempfile
import json
import uuid
import calendar
import requests
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from datetime import datetime, date, timedelta, timezone
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query, Header, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

# Database and models
from .database import (
    SessionLocal, engine, get_db, Base,
    User, Establishment, Payment, SubscriptionFee, AdvanceCreditLedger, ActivityLog, ProjectData, Setting, DATABASE_URL,
    FeatureFlag, RolePermission, UserPermissionOverride, SignupRequest
)

# Auth helpers and dependencies
from .auth import (
    hash_password, verify_password, create_access_token, decode_access_token,
    get_current_user, get_superadmin, get_active_establishment, save_establishment_project,
    JWT_SECRET
)

from . import cashfree_client
from . import google_oauth
from . import version_info

def log_activity(
    db: Session,
    user_id: Optional[int],
    establishment_id: Optional[int],
    action_type: str,
    description: str,
    metadata: Optional[dict] = None
):
    """Additive, resilient activity logger that never crashes parent endpoints."""
    if not db:
        return
    try:
        log_entry = ActivityLog(
            user_id=user_id,
            establishment_id=establishment_id,
            action_type=action_type,
            description=description,
            extra_data=json.dumps(metadata or {}, ensure_ascii=False)
        )
        db.add(log_entry)
        db.commit()
    except Exception as e:
        print(f"[ActivityLog] Warning: failed to record activity: {e}")
        try:
            db.rollback()
        except Exception:
            pass


# ── Permission / Feature-Flag System ────────────────────────────────────────
# Finite list of CRUD-level actions this permission system governs. Not every
# UI element -- just the app's real create/edit/delete/download operations.
PERMISSION_ACTIONS = [
    "employee.add", "employee.edit", "employee.delete",
    "establishment.add", "establishment.edit", "establishment.delete",
    "wages.edit", "wages.delete",
    "ecr.download", "forms.download",
]

# key -> (default value, description). All default True so this system is purely
# additive on deploy -- nothing changes until a superadmin toggles something off.
# NOTE: subscription enforcement is deliberately NOT one of these -- it's controlled
# per-establishment via Establishment.trial_ends_on instead (see is_establishment_in_trial),
# since a platform-wide kill-switch was too blunt a tool for "give this one establishment
# a free trial."
FEATURE_FLAG_DEFAULTS = {
    "cashfree_payments_enabled": (True, "Enables Cashfree payment-link generation for subscription fees and advance credit"),
    "branch_feature_enabled": (True, "Enables branch/division/unit ECR filtering and by-branch ZIP downloads"),
    "advance_credit_enabled": (True, "Enables prepaying advance credit toward future subscription fees"),
}

# Feature-flag keys previously seeded that no longer mean anything -- cleaned up at
# startup so the superadmin's Feature Flags UI doesn't show a dead toggle.
OBSOLETE_FEATURE_FLAG_KEYS = ["subscription_enforcement_enabled"]


def is_establishment_in_trial(establishment: Establishment) -> bool:
    """True while establishment.trial_ends_on is set and today is on or before it."""
    return establishment.trial_ends_on is not None and date.today() <= establishment.trial_ends_on


def get_trial_days_left(establishment: Establishment) -> Optional[int]:
    if not is_establishment_in_trial(establishment):
        return None
    return (establishment.trial_ends_on - date.today()).days


def has_permission(db: Session, user: User, action: str) -> bool:
    """Superadmin always passes. Otherwise: a per-user override (if one exists for
    this action) wins; failing that, the user's role default applies; failing that
    (an action this rollout doesn't know about yet), fail OPEN so nothing gets
    accidentally locked out -- but log it so the gap gets noticed."""
    if not db or user.role == "superadmin":
        return True

    override = db.query(UserPermissionOverride).filter(
        UserPermissionOverride.user_id == user.id,
        UserPermissionOverride.action == action
    ).first()
    if override is not None:
        return override.allowed

    role_perm = db.query(RolePermission).filter(
        RolePermission.role == user.role,
        RolePermission.action == action
    ).first()
    if role_perm is not None:
        return role_perm.allowed

    print(f"  [WARN] has_permission: no RolePermission row for role={user.role!r} action={action!r} -- defaulting to allowed=True")
    return True


def require_permission(db: Session, user: User, action: str):
    if not has_permission(db, user, action):
        raise HTTPException(status_code=403, detail=f"Your account does not have permission to do this ({action}). Contact your administrator.")


def is_feature_enabled(db: Session, key: str) -> bool:
    """Defaults to True (fail-open) if the flag row doesn't exist yet."""
    if not db:
        return True
    flag = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
    if flag is None:
        return True
    return bool(flag.value)


def require_feature_enabled(db: Session, key: str, feature_label: str):
    if not is_feature_enabled(db, key):
        raise HTTPException(status_code=403, detail=f"{feature_label} is currently disabled by your administrator.")


# Engine
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from epf_engine import (
    Project, ExcelGenerator, MONTHS, MONTH_FULL,
    SCHEME_PRE_1997, SCHEME_POST_1997,
    REASONS_FOR_LEAVING, SUPERANNUATION_AGE, calc_age_years,
    import_wages_from_excel, generate_form9, import_master_from_excel,
    natural_sort_key, get_wage_ceilings_for_year,
    account2_rate_percent, account22_rate_percent,
    ACCOUNT_21_RATE, ACCOUNT_22_MIN,
    generate_ecr_month, calendar_year_for_month, Employee,
    normalize_member_id, get_excel_sheet_names, get_month_num,
    filter_employees_by_scope, resolve_scope_path_for_ids, resolve_employee_scope_path,
)

MONTH_SHORT_NAMES = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]

def count_ecr_employees_for_month(project: Project, year_key: str, month_idx: int) -> int:
    """Returns exact count of employees who have wage > 0 in this month (matches ECR row count)."""
    year_record = project.years.get(year_key)
    if not year_record:
        return 0
    count = 0
    for entry in year_record.entries:
        if entry.wages and len(entry.wages) > month_idx:
            w = entry.wages[month_idx]
            if w is not None and float(w) > 0:
                count += 1
    return count

def build_establishment_wage_grid(project: Project) -> list:
    """Per financial year, per-month (Mar..Feb) wage-entry status -- drives the
    green/red status-box grid on the Establishment page's establishment list."""
    grid = []
    for year_key, yr in sorted(project.years.items(), key=lambda kv: kv[1].year_from, reverse=True):
        months = []
        for i, m_abbr in enumerate(MONTH_SHORT_NAMES):
            emp_count = count_ecr_employees_for_month(project, year_key, i)
            cal_yr = calendar_year_for_month(m_abbr, yr.year_from, yr.year_to)
            months.append({
                "month": m_abbr,
                "label": f"{MONTH_FULL.get(m_abbr.upper(), m_abbr)} {cal_yr}",
                "employees": emp_count,
                "has_wages": emp_count > 0,
            })
        grid.append({"year": year_key, "months": months})
    return grid

def resolve_rate(db: Session, establishment: Establishment, user: Optional[User] = None) -> float:
    """Resolve rate per employee: Establishment override > Consultant override > Global default (10.0)."""
    if establishment.custom_rate_per_employee is not None and establishment.custom_rate_per_employee > 0:
        return float(establishment.custom_rate_per_employee)
    if user is None and establishment.user_id:
        user = db.query(User).filter(User.id == establishment.user_id).first()
    if user and user.custom_rate_per_employee is not None and user.custom_rate_per_employee > 0:
        return float(user.custom_rate_per_employee)
    setting = db.query(Setting).filter(Setting.key == "default_rate_per_employee").first()
    if setting and setting.value:
        try:
            return float(setting.value)
        except ValueError:
            pass
    return 10.0

def resolve_billing_mode(db: Session, establishment: Establishment, consultant: Optional[User] = None) -> Tuple[str, Optional[float]]:
    """Resolve (billing_mode, flat_fee_amount): Establishment explicit override > Consultant
    default > global fallback ('per_employee', tiered/custom rate resolved separately via
    resolve_rate()). An explicit non-null establishment.billing_mode always wins outright --
    even 'per_employee' with no flat_fee_amount counts as a deliberate override and must NOT
    fall through to the consultant's default, since that's how a specific establishment stays
    an intentional exception to a later consultant-level change."""
    if establishment.billing_mode is not None:
        return establishment.billing_mode, establishment.flat_fee_amount
    if consultant is None and establishment.user_id:
        consultant = db.query(User).filter(User.id == establishment.user_id).first()
    if consultant and consultant.default_billing_mode is not None:
        return consultant.default_billing_mode, consultant.default_flat_fee_per_establishment
    return "per_employee", None

def apply_advance_credit_if_available(db: Session, est_obj: Establishment, fee_row: SubscriptionFee):
    """If the establishment has enough prepaid advance credit to cover this newly-billed,
    still-unpaid month, auto-mark it paid and deduct the credit. Never applies partially --
    a month is either fully covered or left as a normal unpaid row."""
    if fee_row.is_paid or fee_row.amount_due <= 0:
        return
    balance = est_obj.advance_credit_balance or 0.0
    if balance < fee_row.amount_due:
        return

    fee_row.is_paid = True
    fee_row.payment_status = "paid"
    fee_row.payment_reference = "Applied from advance credit"
    est_obj.advance_credit_balance = round(balance - fee_row.amount_due, 2)
    db.flush()  # ensure fee_row.id is assigned before we reference it as a FK below

    db.add(AdvanceCreditLedger(
        establishment_id=est_obj.id,
        entry_type="applied",
        amount=fee_row.amount_due,
        applied_to_fee_id=fee_row.id,
        status="confirmed",
        notes=f"Auto-applied to {fee_row.month} {fee_row.financial_year}"
    ))

    log_activity(
        db, None, est_obj.id, "advance_credit_applied",
        f"Advance credit applied: ₹{fee_row.amount_due} for {fee_row.month} {fee_row.financial_year} — "
        f"{est_obj.name} ({est_obj.code}). Remaining balance: ₹{est_obj.advance_credit_balance}",
        {
            "financial_year": fee_row.financial_year, "month": fee_row.month,
            "amount_applied": fee_row.amount_due, "remaining_balance": est_obj.advance_credit_balance,
            "code": est_obj.code
        }
    )


def sync_subscription_fees_for_year(db: Session, est_obj: Establishment, project: Project, year_key: str):
    """Sync or auto-generate 12-month subscription fee records for an establishment and financial year.

    Fetches all 12 months' existing rows in a single query up front (instead of one
    query per month) -- this endpoint is on the hot path for page loads (Reports,
    Challans, the subscription-status banner), and 12 sequential round-trips to a
    remote DB (Neon Postgres in production) measurably added seconds to page load,
    especially noticeable right after the DB's connection has been idle.

    billing_mode governs HOW amount_due is computed, nothing else -- enforcement
    (download-locking, Cashfree, advance credit, trials) is identical either way.
    resolve_billing_mode() resolves the inheritance chain (explicit establishment override >
    consultant's default_billing_mode > global 'per_employee' fallback) fresh on every sync,
    so a consultant-level default change takes effect for every inheriting establishment's
    NEXT sync with zero per-establishment configuration. resolve_rate()'s tiered-rate lookup
    is only run when the resolved mode is 'per_employee'; there's no rate to resolve in
    flat-fee mode. A still-unpaid row always live-adopts the CURRENTLY resolved
    mode/rate/amount on every sync (these are the "future months"). A PAID row is historical
    and frozen: it remembers the mode it was actually billed under (its own billing_mode, not
    a re-resolved one) and its amount_due is never rewritten by a later mode switch -- only
    employee_count is refreshed, for reporting/visibility."""
    mode, resolved_flat_amount = resolve_billing_mode(db, est_obj)
    flat_amount = round(float(resolved_flat_amount), 2) if (mode == "flat_fee" and resolved_flat_amount) else 0.0
    rate = resolve_rate(db, est_obj) if mode == "per_employee" else None

    year_record = project.years.get(year_key)
    if not year_record:
        return

    existing_rows = {
        f.month: f for f in db.query(SubscriptionFee).filter(
            SubscriptionFee.establishment_id == est_obj.id,
            SubscriptionFee.financial_year == year_key
        ).all()
    }

    for month_idx in range(12):
        month_abbr = MONTH_SHORT_NAMES[month_idx]
        emp_count = count_ecr_employees_for_month(project, year_key, month_idx)

        fee_row = existing_rows.get(month_abbr)

        if not fee_row:
            fee_row = SubscriptionFee(
                establishment_id=est_obj.id,
                financial_year=year_key,
                month=month_abbr,
                employee_count=emp_count,
                rate_applied=rate,
                amount_due=flat_amount if mode == "flat_fee" else round(emp_count * rate, 2),
                billing_mode=mode,
                is_paid=False
            )
            db.add(fee_row)
            # Newly-billed row -- give prepaid advance credit a chance to cover it.
            apply_advance_credit_if_available(db, est_obj, fee_row)
        else:
            if not fee_row.is_paid:
                was_unbilled = fee_row.amount_due <= 0
                fee_row.employee_count = emp_count
                fee_row.billing_mode = mode
                fee_row.rate_applied = rate
                fee_row.amount_due = flat_amount if mode == "flat_fee" else round(emp_count * rate, 2)
                if was_unbilled and fee_row.amount_due > 0:
                    # This row existed as a 0-due placeholder (no wage data yet) and has
                    # just been billed for the first time -- same as a fresh row.
                    apply_advance_credit_if_available(db, est_obj, fee_row)
            else:
                # Paid -- historical. Recompute amount_due using the row's OWN frozen
                # billing_mode, not the establishment's possibly-since-changed one, so a
                # mode switch never rewrites an already-billed/paid month.
                fee_row.employee_count = emp_count
                row_mode = fee_row.billing_mode or "per_employee"
                if row_mode == "per_employee" and fee_row.rate_applied is not None:
                    fee_row.amount_due = round(emp_count * fee_row.rate_applied, 2)
                # flat_fee paid rows: amount_due stays exactly as billed, headcount-independent.

        existing_rows[month_abbr] = fee_row

    db.commit()
    return existing_rows

def is_month_overdue(year_key: str, month_idx: int) -> bool:
    """A month is overdue if current date is strictly greater than 1 day past month end."""
    year_parts = year_key.split("-")
    try:
        yf = int(year_parts[0])
        yt = int(year_parts[1]) if len(year_parts) > 1 else yf + 1
        if yt < 100: yt += 2000
    except Exception:
        yf = 2026
        yt = 2027

    month_abbr = MONTH_SHORT_NAMES[month_idx]
    cal_m = get_month_num(month_abbr)
    cal_y = calendar_year_for_month(month_abbr, str(yf), str(yt))
    if not cal_y or not cal_m:
        return True

    last_day = calendar.monthrange(cal_y, cal_m)[1]
    grace_cutoff = date(cal_y, cal_m, last_day) + timedelta(days=1)
    return date.today() > grace_cutoff

def get_unpaid_months_detail_for_year(db: Session, establishment: Establishment, project: Project, year_key: str) -> List[dict]:
    """Like get_unpaid_months_for_year but returns structured {fee_id, month, display, amount_due,
    financial_year} rows instead of formatted strings, so callers can turn a 402 into an actionable
    payment breakdown (exact amount per month + a payable total) instead of a bare error string."""
    if is_establishment_in_trial(establishment):
        return []
    fee_rows = sync_subscription_fees_for_year(db, establishment, project, year_key)
    year_record = project.years.get(year_key)
    if not year_record:
        return []

    unpaid_overdue = []
    for month_idx in range(12):
        month_abbr = MONTH_SHORT_NAMES[month_idx]
        emp_count = count_ecr_employees_for_month(project, year_key, month_idx)
        if emp_count == 0:
            continue

        fee_row = (fee_rows or {}).get(month_abbr)

        if fee_row and not fee_row.is_paid:
            if is_month_overdue(year_key, month_idx):
                cal_yr = calendar_year_for_month(month_abbr, year_record.year_from, year_record.year_to)
                unpaid_overdue.append({
                    "fee_id": fee_row.id,
                    "month": month_abbr,
                    "financial_year": year_key,
                    "display": f"{MONTH_FULL.get(month_abbr.upper(), month_abbr)} {cal_yr}",
                    "amount_due": fee_row.amount_due,
                })

    return unpaid_overdue

def get_unpaid_months_for_year(db: Session, establishment: Establishment, project: Project, year_key: str) -> List[str]:
    """Returns list of formatted month names for which wages exist, fee is unpaid, and grace period has elapsed."""
    return [row["display"] for row in get_unpaid_months_detail_for_year(db, establishment, project, year_key)]

def _year_payment_required_detail(unpaid_rows: List[dict], financial_year: Optional[str] = None) -> dict:
    """Builds the structured 402 body for a whole-year (or multi-year, for Form 9) blocked
    download -- an actionable breakdown the frontend renders as a payment prompt (Cashfree +
    QR for the combined total) instead of a bare error string."""
    total_due = round(sum(r["amount_due"] for r in unpaid_rows), 2)
    months_str = ", ".join(r["display"] for r in unpaid_rows)
    return {
        "message": f"Download blocked — software subscription fee for {months_str} is unpaid. Settle it below to unlock the download.",
        "financial_year": financial_year,
        "unpaid_months": unpaid_rows,
        "total_due": total_due,
        "count": len(unpaid_rows),
    }

# ── App setup ──────────────────────────────────────────────────────────────
app = FastAPI(title="EPF Admin Dashboard", version=version_info.get_version_info()["version"])

# Required by Authlib's OAuth client to stash the Google auth state/nonce (and, for the
# signup flow, the role/establishment fields chosen before redirecting to Google) across
# the redirect round-trip. Reuses JWT_SECRET as a default so this works out of the box in
# dev without a second secret to configure -- override with SESSION_SECRET_KEY in production.
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET_KEY", JWT_SECRET))

WEB = Path(__file__).resolve().parent
app.mount("/css", StaticFiles(directory=str(WEB / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB / "js")), name="js")
app.mount("/docs", StaticFiles(directory=str(WEB / "static_docs")), name="docs")


# ── Startup Data Migration & Seed ──────────────────────────────────────────
def _run_startup_migrations():
    if not SessionLocal:
        return
    # 0. Ensure all tables and additive columns exist
    if engine:
        try:
            Base.metadata.create_all(bind=engine)

            def _try_ddl(conn, ddl):
                """Run one additive-column DDL statement, tolerating 'already exists'
                errors. Critically, rolls back on failure -- on Postgres, a failed
                statement leaves the connection's transaction ABORTED, and every
                subsequent statement on that same connection would silently fail too
                (caught by the caller's own try/except) until it's rolled back. This
                bit us for real: the SQLite-only fallback ALTER for
                advance_credit_balance (no IF NOT EXISTS) failed on Postgres because
                the column already existed, which silently poisoned the connection and
                prevented the cashfree_order_id/cashfree_payment_link_url columns from
                ever being added in production."""
                try:
                    conn.execute(text(ddl))
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass

            with engine.connect() as conn:
                _try_ddl(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS custom_rate_per_employee FLOAT;")
                _try_ddl(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS max_establishments INTEGER;")
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN IF NOT EXISTS custom_rate_per_employee FLOAT;")
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN IF NOT EXISTS advance_credit_balance FLOAT DEFAULT 0;")
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN IF NOT EXISTS trial_ends_on DATE;")
                _try_ddl(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS google_id VARCHAR(255);")
                _try_ddl(conn, "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id);")
                _try_ddl(conn, "ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;")
                _try_ddl(conn, "ALTER TABLE signup_requests ADD COLUMN IF NOT EXISTS google_id VARCHAR(255);")
                _try_ddl(conn, "ALTER TABLE signup_requests ADD COLUMN IF NOT EXISTS email_verified_via_google BOOLEAN DEFAULT false;")
                _try_ddl(conn, "ALTER TABLE signup_requests ALTER COLUMN password_hash DROP NOT NULL;")
                # SQLite doesn't support "IF NOT EXISTS" on ADD COLUMN -- this is a
                # harmless no-op there once the column exists, and on Postgres it's a
                # no-op too now that _try_ddl rolls back instead of poisoning the
                # connection for the statements that follow.
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN advance_credit_balance FLOAT DEFAULT 0;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS cashfree_order_id VARCHAR(120);")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS cashfree_payment_link_url TEXT;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN cashfree_order_id VARCHAR(120);")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN cashfree_payment_link_url TEXT;")
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN IF NOT EXISTS billing_mode VARCHAR(20) DEFAULT 'per_employee';")
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN IF NOT EXISTS flat_fee_amount FLOAT;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS billing_mode VARCHAR(20) DEFAULT 'per_employee';")
                _try_ddl(conn, "ALTER TABLE subscription_fees ALTER COLUMN rate_applied DROP NOT NULL;")
                # billing_mode becomes nullable so null can mean "inherit from consultant".
                # This does NOT touch existing rows' stored values -- every establishment
                # created before this migration already has an explicit 'per_employee' or
                # 'flat_fee' value written to it, and DROP NOT NULL never rewrites data.
                # Only establishments created AFTER this migration, with no billing_mode
                # passed at creation, will actually end up null/inheriting.
                _try_ddl(conn, "ALTER TABLE establishments ALTER COLUMN billing_mode DROP NOT NULL;")
                _try_ddl(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS default_billing_mode VARCHAR(20);")
                _try_ddl(conn, "ALTER TABLE users ADD COLUMN IF NOT EXISTS default_flat_fee_per_establishment FLOAT;")
                # UPI payment path columns on subscription_fees
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS payment_status VARCHAR(30) DEFAULT 'unpaid';")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS submitted_utr VARCHAR(255);")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS submitted_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS verified_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS rejection_reason TEXT;")
                # SQLite fallbacks (no IF NOT EXISTS, _try_ddl tolerates duplicate-column errors)
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN payment_status VARCHAR(30) DEFAULT 'unpaid';")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN submitted_utr VARCHAR(255);")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN submitted_by INTEGER;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN submitted_at TIMESTAMP;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN verified_by INTEGER;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN verified_at TIMESTAMP;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN rejection_reason TEXT;")
                # UPI payment path columns on advance_credit_ledger (same pattern as subscription_fees above)
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN IF NOT EXISTS submitted_utr VARCHAR(255);")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN IF NOT EXISTS submitted_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN IF NOT EXISTS submitted_at TIMESTAMPTZ;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN IF NOT EXISTS verified_by INTEGER REFERENCES users(id) ON DELETE SET NULL;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN IF NOT EXISTS rejection_reason TEXT;")
                # SQLite fallbacks
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN submitted_utr VARCHAR(255);")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN submitted_by INTEGER;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN submitted_at TIMESTAMP;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN verified_by INTEGER;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN verified_at TIMESTAMP;")
                _try_ddl(conn, "ALTER TABLE advance_credit_ledger ADD COLUMN rejection_reason TEXT;")
        except Exception as e:
            print(f"  [WARN] DDL check error: {e}")

    with SessionLocal() as db:
        # 1. Seed Primary Superadmin (Raghunatha Maharana)
        raghu_admin = db.query(User).filter(func.lower(User.email) == "raghunatha.maharana@gmail.com").first()
        if not raghu_admin:
            raghu_admin = User(
                serial_no=None,
                name="Raghunatha Maharana",
                mobile="9876543210",
                email="raghunatha.maharana@gmail.com",
                password_hash=hash_password("Raghu@1234"),
                role="superadmin",
                is_active=True
            )
            db.add(raghu_admin)
            db.commit()
            print("  [OK] Seeded superadmin: raghunatha.maharana@gmail.com")
        else:
            raghu_admin.role = "superadmin"
            raghu_admin.is_active = True
            db.commit()

        # 2. Seed Generic Superadmin (admin@epfdashboard.com)
        superadmin = db.query(User).filter(func.lower(User.email) == "admin@epfdashboard.com").first()
        if not superadmin:
            s_email = os.environ.get("SUPERADMIN_EMAIL", "admin@epfdashboard.com").strip().lower()
            s_pass = os.environ.get("SUPERADMIN_PASSWORD", "Admin@12345")
            superadmin = User(
                serial_no=None,
                name="System Superadmin",
                mobile="9999999999",
                email=s_email,
                password_hash=hash_password(s_pass),
                role="superadmin",
                is_active=True
            )
            db.add(superadmin)
            db.commit()
            print(f"  [OK] Seeded superadmin: {s_email}")

        # 3. Seed Default Consultant
        consultant = db.query(User).filter(User.role == "consultant").first()
        if not consultant:
            consultant = User(
                serial_no=1,
                name="Consultant 1",
                mobile="9876543210",
                email="consultant@epfdashboard.com",
                password_hash=hash_password("Consultant@123"),
                role="consultant",
                is_active=True
            )
            db.add(consultant)
            db.commit()
            db.refresh(consultant)
            print(f"  [OK] Seeded default consultant: consultant@epfdashboard.com")

        # 3. Migrate Existing Establishment Data
        est_count = db.query(Establishment).count()
        if est_count == 0:
            migrated = 0
            # A. Check ProjectData table
            try:
                projects_in_db = db.query(ProjectData).all()
                for p_row in projects_in_db:
                    try:
                        p_dict = json.loads(p_row.data)
                        code = p_dict.get("code") or "ORBBS1990770000"
                        name = p_dict.get("name") or p_row.filename.replace("_project.epfproj.json", "").replace(".json", "")
                        addr = p_dict.get("address") or ""
                        cov = p_dict.get("coverage_date") or ""
                        est = Establishment(
                            user_id=consultant.id,
                            code=code,
                            name=name,
                            address=addr,
                            coverage_date=cov,
                            data=p_row.data
                        )
                        db.add(est)
                        migrated += 1
                    except Exception as e:
                        print(f"  [ERR] Failed migrating project from DB ({p_row.filename}): {e}")
                db.commit()
            except Exception as e:
                print(f"  [ERR] Querying ProjectData: {e}")

            # B. If still 0, check file system .epfproj.json files
            if db.query(Establishment).count() == 0:
                parent = Path(__file__).resolve().parent.parent
                json_files = sorted([f for f in parent.iterdir() if f.name.lower().endswith(".epfproj.json")])
                for jf in json_files:
                    try:
                        with open(jf, "r", encoding="utf-8") as f:
                            p_dict = json.load(f)
                        code = p_dict.get("code") or "ORBBS1990770000"
                        name = p_dict.get("name") or jf.name.replace("_project.epfproj.json", "").replace(".json", "")
                        addr = p_dict.get("address") or ""
                        cov = p_dict.get("coverage_date") or ""
                        est = Establishment(
                            user_id=consultant.id,
                            code=code,
                            name=name,
                            address=addr,
                            coverage_date=cov,
                            data=json.dumps(p_dict, ensure_ascii=False)
                        )
                        db.add(est)
                        migrated += 1
                    except Exception as e:
                        print(f"  [ERR] Failed migrating project file ({jf.name}): {e}")
                db.commit()

            if migrated > 0:
                print(f"  [OK] Successfully migrated {migrated} establishment(s) to consultant {consultant.email}")

        # 4. Seed Feature Flags (all default ON -- matches current live behavior exactly;
        # nothing is disabled until a superadmin deliberately flips one off)
        flags_added = 0
        for flag_key, (default_value, description) in FEATURE_FLAG_DEFAULTS.items():
            if not db.query(FeatureFlag).filter(FeatureFlag.key == flag_key).first():
                db.add(FeatureFlag(key=flag_key, value=default_value, description=description))
                flags_added += 1
        if flags_added:
            db.commit()
            print(f"  [OK] Seeded {flags_added} feature flag(s)")

        obsolete_removed = db.query(FeatureFlag).filter(FeatureFlag.key.in_(OBSOLETE_FEATURE_FLAG_KEYS)).delete(synchronize_session=False)
        if obsolete_removed:
            db.commit()
            print(f"  [OK] Removed {obsolete_removed} obsolete feature flag(s)")

        # 5. Seed Role Permissions -- both roles allowed everything by default, so this
        # rollout is purely additive: nothing newly blocked until the superadmin changes it
        perms_added = 0
        for seed_role in ("consultant", "employer"):
            for seed_action in PERMISSION_ACTIONS:
                if not db.query(RolePermission).filter(RolePermission.role == seed_role, RolePermission.action == seed_action).first():
                    db.add(RolePermission(role=seed_role, action=seed_action, allowed=True))
                    perms_added += 1
        if perms_added:
            db.commit()
            print(f"  [OK] Seeded {perms_added} role permission row(s)")

        # 6. Seed UPI Settings (idempotent)
        upi_id_setting = db.query(Setting).filter(Setting.key == "upi_id").first()
        if not upi_id_setting:
            db.add(Setting(key="upi_id", value=""))
        upi_name_setting = db.query(Setting).filter(Setting.key == "upi_name").first()
        if not upi_name_setting:
            db.add(Setting(key="upi_name", value=""))
        qr_setting = db.query(Setting).filter(Setting.key == "upi_qr_code").first()
        if not qr_setting:
            db.add(Setting(key="upi_qr_code", value=""))
        db.commit()

@app.on_event("startup")
def on_startup():
    _run_startup_migrations()


# ── Static Index Route ─────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


# ── App Version (no auth required — sourced live from git, not a hand-edited string) ──
@app.get("/api/version")
async def get_app_version():
    return version_info.get_version_info()


# ── Public Signup / Terms / Privacy Pages (no auth required) ───────────────
@app.get("/signup", response_class=HTMLResponse)
async def signup_page():
    return (WEB / "signup.html").read_text(encoding="utf-8")


@app.get("/terms", response_class=HTMLResponse)
async def terms_page():
    return (WEB / "terms.html").read_text(encoding="utf-8")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page():
    return (WEB / "privacy.html").read_text(encoding="utf-8")


@app.get("/refund", response_class=HTMLResponse)
async def refund_page():
    return (WEB / "refund.html").read_text(encoding="utf-8")


# ── Schemas ────────────────────────────────────────────────────────────────
class LoginIn(BaseModel):
    email: str
    password: str

class UserCreateIn(BaseModel):
    name: str
    mobile: Optional[str] = ""
    email: str
    password: str
    role: str = "consultant"  # 'consultant' or 'employer'
    max_establishments: Optional[int] = None  # required for role='employer'; ignored for 'consultant'
    custom_rate_per_employee: Optional[float] = None

class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    custom_rate_per_employee: Optional[float] = None
    max_establishments: Optional[int] = None  # only applied when the target user's role is 'employer'
    is_active: Optional[bool] = None

class EstablishmentIn(BaseModel):
    code: str
    name: str
    address: str = ""
    coverage_date: str = ""
    custom_rate_per_employee: Optional[float] = None
    trial_ends_on: Optional[str] = None  # "YYYY-MM-DD"; superadmin-only, ignored otherwise
    owner_user_id: Optional[int] = None  # superadmin-only: create on behalf of this user

class TrialUpdateIn(BaseModel):
    trial_ends_on: Optional[str] = None  # "YYYY-MM-DD", or null/omitted to clear the trial

class BillingModeUpdateIn(BaseModel):
    billing_mode: str  # 'per_employee', 'flat_fee', or 'inherit' (clears the establishment's own override back to null)
    flat_fee_amount: Optional[float] = None  # required (>0) when billing_mode='flat_fee'; ignored otherwise

class ConsultantDefaultBillingIn(BaseModel):
    default_billing_mode: Optional[str] = None  # 'per_employee' | 'flat_fee' | null (clears consultant-level default)
    default_flat_fee_per_establishment: Optional[float] = None  # ₹/month; required (>0) when default_billing_mode='flat_fee'

class SignupIn(BaseModel):
    role: str  # 'employer' or 'consultant'
    name: str
    email: str
    mobile: str = ""
    password: str
    agreed_to_terms: bool = False
    establishment_code: Optional[str] = None
    establishment_name: Optional[str] = None
    establishment_address: str = ""
    coverage_date: str = ""

class SignupRejectIn(BaseModel):
    rejection_reason: Optional[str] = None

class DefaultRateIn(BaseModel):
    default_rate: float

class FeatureFlagsUpdateIn(BaseModel):
    flags: Dict[str, bool]  # flag key -> new value

class RolePermissionRow(BaseModel):
    role: str
    action: str
    allowed: bool

class RolePermissionsUpdateIn(BaseModel):
    permissions: List[RolePermissionRow]

class PermissionOverrideIn(BaseModel):
    action: str
    allowed: bool

class SubscriptionFeeItemIn(BaseModel):
    month: str
    is_paid: bool = False
    paid_date: Optional[str] = None
    payment_reference: Optional[str] = None
    notes: Optional[str] = None

class SubscriptionFeesSaveIn(BaseModel):
    financial_year: str
    fees: List[SubscriptionFeeItemIn]

class AdvancePaymentIn(BaseModel):
    amount: float
    payment_reference: str = ""
    notes: str = ""

class CreateFeeLinkIn(BaseModel):
    financial_year: str
    month: str

class PayAllOverdueIn(BaseModel):
    fee_ids: List[int]

class RefreshBatchStatusIn(BaseModel):
    fee_ids: List[int]

class BatchSubmitUTRIn(BaseModel):
    fee_ids: List[int]
    utr: str

class PaymentUpdateItem(BaseModel):
    month: str
    is_paid: bool = False
    amount: Optional[float] = None
    paid_date: Optional[str] = None
    notes: Optional[str] = None

class PaymentsSaveIn(BaseModel):
    financial_year: str
    payments: List[PaymentUpdateItem]

# UPI Payment Path Schemas
class SubmitUTRIn(BaseModel):
    utr: str

class AdvanceSubmitUTRIn(BaseModel):
    amount: float
    utr: str

class ApprovePaymentIn(BaseModel):
    pass  # no body needed; superadmin is implicit

class RejectPaymentIn(BaseModel):
    rejection_reason: str

class UPISettingsIn(BaseModel):
    upi_id: Optional[str] = None
    upi_name: Optional[str] = None
    qr_code_data: Optional[str] = None  # raw UPI QR string; if provided, upi_id/upi_name are extracted

class EmployeeIn(BaseModel):
    member_id: str
    name: str
    father_name: str = ""
    uan: str = ""
    dob: str = ""
    sex: str = ""
    doj: str = ""
    doe: str = ""
    reason_leaving: str = ""
    serial_no: Optional[int] = None
    relationship: str = ""
    marital_status: str = ""
    mobile: str = ""
    email: str = ""
    aadhaar: str = ""
    bank_account: str = ""
    ifsc: str = ""
    higher_epf_ee: bool = False
    higher_epf_er: bool = False
    branch_id: Optional[int] = None
    division_id: Optional[int] = None
    unit_id: Optional[int] = None

class YearIn(BaseModel):
    year_from: str
    year_to: str
    scheme: str = SCHEME_POST_1997
    epf_rate: float = 6.84
    fpf_rate: float = 1.16
    emp_epf_rate: float = 12.0
    er_epf_rate: float = 3.67
    er_eps_rate: float = 8.33

class YearRatesIn(BaseModel):
    scheme: str
    epf_rate: float = 6.84
    fpf_rate: float = 1.16
    emp_epf_rate: float = 12.0
    er_epf_rate: float = 3.67
    er_eps_rate: float = 8.33

class WageIn(BaseModel):
    member_id: str
    wages: List[float]
    gross_wages: List[float] = []
    ncp_days: List[int] = []
    age_crosses_58: bool = False
    higher_epf_ee: bool = False
    higher_epf_er: bool = False

class BulkMonthWageUpdate(BaseModel):
    member_id: str
    gross_wage: float
    epf_wage: float
    ncp_days: int
    age_crosses_58: bool = False
    higher_epf_ee: bool = False
    higher_epf_er: bool = False

class BulkMonthWagesIn(BaseModel):
    month_idx: int
    employees: List[BulkMonthWageUpdate]

class RemittanceIn(BaseModel):
    month_label: str
    trrn: str = ""
    crrn: str = ""
    credit_date: str = ""
    members: int = 0
    acc_01: int = 0
    acc_02: int = 0
    acc_10: int = 0
    acc_21: int = 0
    acc_22: int = 0

class BulkRemittanceIn(BaseModel):
    remittances: List[RemittanceIn]

class BranchIn(BaseModel):
    name: str

class DivisionIn(BaseModel):
    name: str
    branch_id: int

class UnitIn(BaseModel):
    name: str
    division_id: int

class RenameIn(BaseModel):
    name: str


# ── Auth Endpoints ─────────────────────────────────────────────────────────
@app.post("/api/auth/login")
async def login(d: LoginIn, db: Session = Depends(get_db)):
    email = d.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user and not user.password_hash:
        raise HTTPException(status_code=401, detail="This account uses Google Sign-In. Please use the \"Sign in with Google\" button instead.")
    if not user or not verify_password(d.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your account has been deactivated. Please contact support.")

    token = create_access_token(user.id, user.email, user.role)
    log_activity(
        db, user.id, None,
        "superadmin_login" if user.role == "superadmin" else f"{user.role}_login",
        f"User logged in: {user.name} ({user.email})",
        {"role": user.role, "email": user.email}
    )
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": user.id,
            "serial_no": user.serial_no,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "mobile": user.mobile,
            "max_establishments": user.max_establishments
        }
    }


@app.get("/api/auth/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "user": {
            "id": current_user.id,
            "serial_no": current_user.serial_no,
            "name": current_user.name,
            "email": current_user.email,
            "role": current_user.role,
            "mobile": current_user.mobile,
            "max_establishments": current_user.max_establishments,
            "created_at": current_user.created_at.strftime("%d-%m-%Y") if current_user.created_at else None
        }
    }


@app.post("/api/auth/logout")
async def logout():
    return {"ok": True, "message": "Logged out successfully"}


# ── Google OAuth ("Sign in with Google" — login only, not a signup path) ───
DUPLICATE_ESTABLISHMENT_MESSAGE = "This establishment has already been registered on our platform. If you believe this is an error, please contact support."


@app.get("/api/auth/google/login")
async def google_login(request: Request):
    """Kicks off the Google consent screen redirect. Login-only: Google sign-in is not
    an entry point for creating a new account (SignupRequest) -- new accounts are
    requested exclusively through the manual /signup form. An unrecognized Google
    identity is sent to /signup to fill that form in instead of being auto-created."""
    if not google_oauth.is_configured():
        raise HTTPException(503, "Google Sign-In is not configured on this server yet.")

    redirect_uri = f"{_app_base_url(request)}/api/auth/google/callback"
    return await google_oauth.oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/api/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not google_oauth.is_configured():
        raise HTTPException(503, "Google Sign-In is not configured on this server yet.")

    try:
        token = await google_oauth.oauth.google.authorize_access_token(request)
    except Exception:
        return RedirectResponse(url="/?google_error=" + quote("Google sign-in failed. Please try again."))

    userinfo = token.get("userinfo") or {}
    google_sub = userinfo.get("sub")
    google_email = (userinfo.get("email") or "").strip().lower()
    google_name = userinfo.get("name") or (google_email.split("@")[0] if google_email else "")

    if not google_sub or not google_email or not userinfo.get("email_verified"):
        return RedirectResponse(url="/?google_error=" + quote("Google did not return a verified email address."))

    # An account already exists for this Google identity (matched by google_id first,
    # then by email so an existing password-based account can link up) -- log them in.
    user = db.query(User).filter(User.google_id == google_sub).first()
    if not user:
        user = db.query(User).filter(func.lower(User.email) == google_email).first()

    if user:
        if not user.is_active:
            return RedirectResponse(url="/?google_error=" + quote("Your account has been deactivated. Please contact support."))
        if not user.google_id:
            user.google_id = google_sub  # backfill the link for a pre-existing password account
            db.commit()

        jwt_token = create_access_token(user.id, user.email, user.role)
        log_activity(
            db, user.id, None,
            "superadmin_login" if user.role == "superadmin" else f"{user.role}_login",
            f"User logged in via Google: {user.name} ({user.email})",
            {"role": user.role, "email": user.email, "via": "google"}
        )
        return RedirectResponse(url=f"/?google_token={jwt_token}")

    # No matching account -- nothing is auto-created. Send them to the signup page to
    # fill in the (manual, password-based) request form; email/name are passed only to
    # pre-fill it, never as anything trusted.
    return RedirectResponse(url=f"/signup?google_no_account=1&google_email={quote(google_email)}&google_name={quote(google_name)}")


# ── Public Signup (no auth required) ────────────────────────────────────────


@app.post("/api/signup")
async def public_signup(d: SignupIn, db: Session = Depends(get_db)):
    role = (d.role or "").strip().lower()
    if role not in ("consultant", "employer"):
        raise HTTPException(400, "Role must be 'consultant' or 'employer'")

    if not d.agreed_to_terms:
        raise HTTPException(400, "You must agree to the Terms of Service and Privacy Policy to sign up.")

    name = d.name.strip()
    email = d.email.strip().lower()
    if not name or not email:
        raise HTTPException(400, "Name and Email are required")
    if not d.password or len(d.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(400, "An account with this email already exists. Please log in instead.")
    if db.query(SignupRequest).filter(func.lower(SignupRequest.email) == email, SignupRequest.status == "pending").first():
        raise HTTPException(400, "A signup request with this email is already pending review.")

    establishment_code = None
    establishment_name = None
    if role == "employer":
        establishment_code = (d.establishment_code or "").strip().upper()
        establishment_name = (d.establishment_name or "").strip()
        if not establishment_code or not establishment_name:
            raise HTTPException(400, "Establishment Code and Name are required for an Employer signup")

        code_taken = (
            db.query(Establishment).filter(func.upper(Establishment.code) == establishment_code).first()
            or db.query(SignupRequest).filter(
                func.upper(SignupRequest.establishment_code) == establishment_code,
                SignupRequest.status == "pending"
            ).first()
        )
        if code_taken:
            raise HTTPException(400, DUPLICATE_ESTABLISHMENT_MESSAGE)

    # The signup form's date picker submits "YYYY-MM-DD"; the rest of the app stores
    # coverage_date as a "DD-MM-YYYY" display string, so normalize it here.
    coverage_date_value = (d.coverage_date or "").strip()
    if role == "employer" and coverage_date_value:
        try:
            coverage_date_value = datetime.strptime(coverage_date_value, "%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError:
            pass  # already in another format (or malformed) -- store as submitted rather than reject

    req = SignupRequest(
        role=role,
        name=name,
        email=email,
        mobile=(d.mobile or "").strip(),
        password_hash=hash_password(d.password),
        establishment_code=establishment_code,
        establishment_name=establishment_name,
        establishment_address=(d.establishment_address or "").strip() if role == "employer" else None,
        coverage_date=coverage_date_value if role == "employer" else None,
        agreed_to_terms=True,
        status="pending"
    )
    db.add(req)
    db.commit()

    return {"ok": True, "message": "Your request has been submitted and is pending approval."}


# ── Superadmin Endpoints (/api/admin/...) ──────────────────────────────────
@app.get("/api/admin/overview")
async def admin_overview(
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    total_consultants = db.query(User).filter(User.role == "consultant").count()
    total_employers = db.query(User).filter(User.role == "employer").count()
    total_establishments = db.query(Establishment).count()
    
    # Total employees across all establishments
    all_ests = db.query(Establishment).all()
    total_employees = 0
    for est in all_ests:
        try:
            p_data = json.loads(est.data) if est.data else {}
            total_employees += len(p_data.get("master", {}))
        except Exception:
            pass

    # Payment compliance
    current_fy = "2026-27"
    total_expected_payments = total_establishments * 12
    paid_payments = db.query(Payment).filter(
        Payment.financial_year == current_fy,
        Payment.is_paid == True
    ).count()

    compliance_pct = round((paid_payments / total_expected_payments * 100), 1) if total_expected_payments > 0 else 100.0
    pending_signups = db.query(SignupRequest).filter(SignupRequest.status == "pending").count()

    return {
        "total_consultants": total_consultants,
        "total_employers": total_employers,
        "total_users": total_consultants + total_employers,
        "total_establishments": total_establishments,
        "total_employees": total_employees,
        "payment_compliance_pct": compliance_pct,
        "current_financial_year": current_fy,
        "pending_signups": pending_signups
    }


@app.get("/api/admin/users")
async def admin_list_users(
    role: Optional[str] = Query(None),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    query = db.query(User).filter(User.role.in_(["consultant", "employer"]))
    if role and role.lower() in ("consultant", "employer"):
        query = query.filter(User.role == role.lower())
    users = query.order_by(User.serial_no.asc()).all()
    rows = []
    for u in users:
        est_count = db.query(Establishment).filter(Establishment.user_id == u.id).count()
        rows.append({
            "id": u.id,
            "serial_no": u.serial_no,
            "name": u.name,
            "mobile": u.mobile or "—",
            "email": u.email,
            "role": u.role,
            "custom_rate_per_employee": u.custom_rate_per_employee,
            "establishment_count": est_count,
            "max_establishments": u.max_establishments,
            "is_active": u.is_active,
            "created_at": u.created_at.strftime("%d-%m-%Y") if u.created_at else "—"
        })
    return {"users": rows, "total": len(rows)}


@app.post("/api/admin/users")
async def admin_create_user(
    d: UserCreateIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    email = d.email.strip().lower()
    if not email:
        raise HTTPException(400, "Email is required")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(400, f"User with email '{email}' already exists")

    role = (d.role or "consultant").strip().lower()
    if role not in ("consultant", "employer"):
        raise HTTPException(400, "Role must be 'consultant' or 'employer'")

    max_establishments = None
    if role == "employer":
        if d.max_establishments is None or d.max_establishments <= 0:
            raise HTTPException(400, "max_establishments is required for Employer accounts and must be a positive integer.")
        max_establishments = d.max_establishments
    # Consultants remain unlimited -- any max_establishments submitted for a consultant is ignored.

    # Next serial number
    max_serial = db.query(func.max(User.serial_no)).scalar() or 0
    next_serial = max_serial + 1

    new_user = User(
        serial_no=next_serial,
        name=d.name.strip(),
        mobile=d.mobile.strip() if d.mobile else "",
        email=email,
        password_hash=hash_password(d.password),
        role=role,
        max_establishments=max_establishments,
        custom_rate_per_employee=d.custom_rate_per_employee,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_activity(
        db, admin.id, None, f"{role}_created",
        f"Created new {role} account: {new_user.name} (S.No: {new_user.serial_no}, Email: {new_user.email})" + (f" — limit {max_establishments} establishment(s)" if max_establishments else ""),
        {"user_id": new_user.id, "serial_no": new_user.serial_no, "name": new_user.name, "email": new_user.email, "role": role, "max_establishments": max_establishments, "custom_rate": new_user.custom_rate_per_employee}
    )

    return {
        "ok": True,
        "user": {
            "id": new_user.id,
            "serial_no": new_user.serial_no,
            "name": new_user.name,
            "email": new_user.email,
            "mobile": new_user.mobile,
            "custom_rate_per_employee": new_user.custom_rate_per_employee,
            "role": new_user.role,
            "max_establishments": new_user.max_establishments
        }
    }


@app.put("/api/admin/users/{user_id}")
async def admin_update_user(
    user_id: int,
    d: UserUpdateIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    if d.email:
        email = d.email.strip().lower()
        existing = db.query(User).filter(func.lower(User.email) == email, User.id != user_id).first()
        if existing:
            raise HTTPException(400, f"Email '{email}' is already in use by another user")
        user.email = email

    if d.name is not None: user.name = d.name.strip()
    if d.mobile is not None: user.mobile = d.mobile.strip()
    if d.password: user.password_hash = hash_password(d.password)
    if d.is_active is not None: user.is_active = d.is_active
    
    old_rate = user.custom_rate_per_employee
    if d.custom_rate_per_employee is not None:
        user.custom_rate_per_employee = d.custom_rate_per_employee if d.custom_rate_per_employee > 0 else None
        if old_rate != user.custom_rate_per_employee:
            log_activity(
                db, admin.id, None, "rate_changed",
                f"Updated {user.name}'s rate override to ₹{user.custom_rate_per_employee if user.custom_rate_per_employee else 'Default'}/emp",
                {"user_id": user.id, "role": user.role, "old_rate": old_rate, "new_rate": user.custom_rate_per_employee, "scope": "user"}
            )

    if d.max_establishments is not None:
        if user.role != "employer":
            raise HTTPException(400, "max_establishments only applies to Employer accounts")
        if d.max_establishments <= 0:
            raise HTTPException(400, "max_establishments must be a positive integer")
        old_limit = user.max_establishments
        if old_limit != d.max_establishments:
            user.max_establishments = d.max_establishments
            log_activity(
                db, admin.id, None, "establishment_limit_changed",
                f"Updated {user.name}'s establishment limit from {old_limit if old_limit is not None else 'Unlimited'} to {d.max_establishments}",
                {"user_id": user.id, "role": user.role, "old_limit": old_limit, "new_limit": d.max_establishments}
            )

    db.commit()
    return {"ok": True}


@app.put("/api/admin/users/{user_id}/default-billing")
async def admin_set_consultant_default_billing(
    user_id: int,
    d: ConsultantDefaultBillingIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Set (or clear) a Consultant's default billing mode that auto-applies to all
    their establishments that have no explicit billing_mode override of their own.
    Superadmin-only. Only valid for Consultant accounts."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if user.role != "consultant":
        raise HTTPException(400, "default_billing_mode can only be set on Consultant accounts")

    new_mode = (d.default_billing_mode or "").strip() or None
    if new_mode and new_mode not in ("per_employee", "flat_fee"):
        raise HTTPException(400, "default_billing_mode must be 'per_employee', 'flat_fee', or null/omitted to clear")

    flat_amount: Optional[float] = None
    if new_mode == "flat_fee":
        if d.default_flat_fee_per_establishment is None or d.default_flat_fee_per_establishment <= 0:
            raise HTTPException(400, "default_flat_fee_per_establishment must be a positive number when default_billing_mode='flat_fee'")
        flat_amount = round(float(d.default_flat_fee_per_establishment), 2)

    old_mode = user.default_billing_mode
    old_flat = user.default_flat_fee_per_establishment

    user.default_billing_mode = new_mode
    user.default_flat_fee_per_establishment = flat_amount
    db.commit()

    def _fmt(mode, flat):
        if mode == "flat_fee":
            return f"Flat ₹{flat}/establishment"
        if mode == "per_employee":
            return "Per Employee (tiered)"
        return "None (no consultant-level default)"

    log_activity(
        db, admin.id, None, "consultant_default_billing_changed",
        f"Updated {user.name}'s default billing: {_fmt(old_mode, old_flat)} → {_fmt(new_mode, flat_amount)}",
        {"user_id": user.id, "old_mode": old_mode, "old_flat": old_flat,
         "new_mode": new_mode, "new_flat": flat_amount}
    )

    return {
        "ok": True,
        "default_billing_mode": user.default_billing_mode,
        "default_flat_fee_per_establishment": user.default_flat_fee_per_establishment
    }


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    
    # Check if user has active establishments
    est_count = db.query(Establishment).filter(Establishment.user_id == user_id).count()
    if est_count > 0:
        raise HTTPException(400, f"Cannot delete user because they have {est_count} establishment(s). Delete or reassign their establishments first.")

    db.delete(user)
    db.commit()
    return {"ok": True}


# ── Signup Request Approval Queue (superadmin) ──────────────────────────────
@app.get("/api/admin/signup-requests")
async def admin_list_signup_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    query = db.query(SignupRequest)
    if status_filter and status_filter.lower() != "all":
        query = query.filter(SignupRequest.status == status_filter.lower())
    rows = query.all()
    # Pending first, then most-recently-submitted first within each status.
    rows.sort(key=lambda r: (0 if r.status == "pending" else 1, -(r.submitted_at.timestamp() if r.submitted_at else 0)))

    reviewer_ids = list({r.reviewed_by for r in rows if r.reviewed_by})
    reviewers_map = {u.id: u for u in db.query(User).filter(User.id.in_(reviewer_ids)).all()} if reviewer_ids else {}

    return {
        "requests": [
            {
                "id": r.id,
                "role": r.role,
                "name": r.name,
                "email": r.email,
                "mobile": r.mobile or "—",
                "email_verified_via_google": r.email_verified_via_google,
                "establishment_code": r.establishment_code,
                "establishment_name": r.establishment_name,
                "establishment_address": r.establishment_address,
                "coverage_date": r.coverage_date,
                "status": r.status,
                "submitted_at": r.submitted_at.strftime("%d-%m-%Y %I:%M %p") if r.submitted_at else "—",
                "reviewed_at": r.reviewed_at.strftime("%d-%m-%Y %I:%M %p") if r.reviewed_at else None,
                "reviewed_by": reviewers_map[r.reviewed_by].name if r.reviewed_by in reviewers_map else None,
                "rejection_reason": r.rejection_reason
            }
            for r in rows
        ],
        "pending_count": db.query(SignupRequest).filter(SignupRequest.status == "pending").count()
    }


@app.post("/api/admin/signup-requests/{request_id}/approve")
async def admin_approve_signup_request(
    request_id: int,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    req = db.query(SignupRequest).filter(SignupRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, "Signup request not found")
    if req.status != "pending":
        raise HTTPException(400, f"This request has already been {req.status}.")

    if db.query(User).filter(func.lower(User.email) == req.email.lower()).first():
        raise HTTPException(400, f"An account with email '{req.email}' already exists — cannot approve this request.")

    if req.role == "employer":
        # Re-check for a duplicate establishment code at approval time too -- another
        # pending request for the same code may have been approved first.
        existing_est = db.query(Establishment).filter(func.upper(Establishment.code) == (req.establishment_code or "").upper()).first()
        if existing_est:
            raise HTTPException(
                409,
                f"Establishment code '{req.establishment_code}' was already approved for another request "
                f"(now belongs to an existing establishment). Reject this request instead, or resolve the "
                f"conflict manually before approving."
            )

    max_serial = db.query(func.max(User.serial_no)).scalar() or 0
    new_user = User(
        serial_no=max_serial + 1,
        name=req.name,
        mobile=req.mobile or "",
        email=req.email,
        password_hash=req.password_hash,  # already hashed at signup -- reused as-is, no reset step needed (null for Google-only accounts)
        google_id=req.google_id if req.email_verified_via_google else None,
        role=req.role,
        max_establishments=1 if req.role == "employer" else None,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    new_est_id = None
    if req.role == "employer":
        p = Project()
        p.set_establishment(req.establishment_code, req.establishment_name, req.establishment_address or "", req.coverage_date or "")
        new_est = Establishment(
            user_id=new_user.id,
            code=req.establishment_code,
            name=req.establishment_name,
            address=req.establishment_address or "",
            coverage_date=req.coverage_date or "",
            data=json.dumps(p.to_dict(), ensure_ascii=False)
        )
        db.add(new_est)
        db.commit()
        db.refresh(new_est)
        new_est_id = new_est.id
        log_activity(
            db, admin.id, new_est.id, "establishment_created",
            f"Added establishment {new_est.code} — {new_est.name} (via approved signup)",
            {"code": new_est.code, "name": new_est.name, "owner_user_id": new_user.id}
        )

    req.status = "approved"
    req.reviewed_at = datetime.utcnow()
    req.reviewed_by = admin.id
    db.commit()

    log_activity(
        db, admin.id, new_est_id, "signup_approved",
        f"Approved {req.role} signup for {req.name} ({req.email})",
        {"request_id": req.id, "role": req.role, "email": req.email, "user_id": new_user.id}
    )

    return {"ok": True, "user_id": new_user.id, "establishment_id": new_est_id}


@app.post("/api/admin/signup-requests/{request_id}/reject")
async def admin_reject_signup_request(
    request_id: int,
    d: SignupRejectIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    req = db.query(SignupRequest).filter(SignupRequest.id == request_id).first()
    if not req:
        raise HTTPException(404, "Signup request not found")
    if req.status != "pending":
        raise HTTPException(400, f"This request has already been {req.status}.")

    req.status = "rejected"
    req.reviewed_at = datetime.utcnow()
    req.reviewed_by = admin.id
    req.rejection_reason = (d.rejection_reason or "").strip() or None
    db.commit()

    log_activity(
        db, admin.id, None, "signup_rejected",
        f"Rejected {req.role} signup for {req.name} ({req.email})" + (f" — Reason: {req.rejection_reason}" if req.rejection_reason else ""),
        {"request_id": req.id, "role": req.role, "email": req.email, "rejection_reason": req.rejection_reason}
    )

    return {"ok": True}


@app.get("/api/admin/users/{user_id}/establishments")
async def admin_user_establishments(
    user_id: int,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    ests = db.query(Establishment).filter(Establishment.user_id == user_id).order_by(Establishment.id.asc()).all()
    rows = []
    for est in ests:
        emp_count = 0
        try:
            data_dict = json.loads(est.data) if est.data else {}
            emp_count = len(data_dict.get("master", {}))
        except Exception:
            pass

        # Check unpaid subscription fee months
        p = Project()
        if est.data:
            try:
                p.load_from_dict(json.loads(est.data))
            except Exception:
                pass
        unpaid = get_unpaid_months_for_year(db, est, p, "2026-27")
        resolved_mode, resolved_flat = resolve_billing_mode(db, est, user)

        rows.append({
            "id": est.id,
            "code": est.code,
            "name": est.name,
            "address": est.address or "—",
            "coverage_date": est.coverage_date or "—",
            "custom_rate_per_employee": est.custom_rate_per_employee,
            "billing_mode": resolved_mode,
            "flat_fee_amount": resolved_flat,
            "billing_mode_explicit": est.billing_mode is not None,
            "billing_mode_own": est.billing_mode,
            "flat_fee_amount_own": est.flat_fee_amount,
            "employee_count": emp_count,
            "unpaid_subscription_months": unpaid,
            "has_overdue_subscription": len(unpaid) > 0,
            "trial_ends_on": est.trial_ends_on.isoformat() if est.trial_ends_on else None,
            "is_in_trial": is_establishment_in_trial(est),
            "trial_days_left": get_trial_days_left(est),
            "created_at": est.created_at.strftime("%d-%m-%Y") if est.created_at else "—"
        })

    return {
        "establishments": rows,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "custom_rate_per_employee": user.custom_rate_per_employee,
            "default_billing_mode": user.default_billing_mode,
            "default_flat_fee_per_establishment": user.default_flat_fee_per_establishment
        }
    }


# ── Global Default Rate Settings ──────────────────────────────────────────
@app.get("/api/admin/settings/subscription-rate")
async def admin_get_default_rate(
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    setting = db.query(Setting).filter(Setting.key == "default_rate_per_employee").first()
    val = float(setting.value) if setting and setting.value else 10.0
    return {"default_rate": val}


@app.post("/api/admin/settings/subscription-rate")
async def admin_set_default_rate(
    d: DefaultRateIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    if d.default_rate < 0:
        raise HTTPException(400, "Rate cannot be negative")
    setting = db.query(Setting).filter(Setting.key == "default_rate_per_employee").first()
    old_rate = float(setting.value) if setting and setting.value else 10.0
    if not setting:
        setting = Setting(key="default_rate_per_employee", value=str(d.default_rate))
        db.add(setting)
    else:
        setting.value = str(d.default_rate)
    db.commit()
    
    log_activity(
        db, admin.id, None, "rate_changed",
        f"Updated global default subscription rate from ₹{old_rate}/emp to ₹{d.default_rate}/emp",
        {"old_rate": old_rate, "new_rate": d.default_rate, "scope": "global"}
    )
    return {"ok": True, "default_rate": d.default_rate}


# ── UPI Settings ──────────────────────────────────────────────────────────────
@app.get("/api/admin/settings/upi")
async def admin_get_upi_settings(
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    upi_id = db.query(Setting).filter(Setting.key == "upi_id").first()
    upi_name = db.query(Setting).filter(Setting.key == "upi_name").first()
    qr_code = db.query(Setting).filter(Setting.key == "upi_qr_code").first()
    return {
        "upi_id": upi_id.value if upi_id else "",
        "upi_name": upi_name.value if upi_name else "",
        "qr_code_data": qr_code.value if qr_code else "",
    }


@app.put("/api/admin/settings/upi")
async def admin_set_upi_settings(
    d: UPISettingsIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    # If QR code provided, extract UPI ID and name from it
    upi_id_val = d.upi_id
    upi_name_val = d.upi_name
    qr_val = d.qr_code_data
    
    if d.qr_code_data and not (d.upi_id and d.upi_name):
        # Parse UPI QR string: upi://pay?pa=upi_id&pn=upi_name&...
        try:
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(d.qr_code_data)
            params = parse_qs(parsed.query)
            if "pa" in params:
                upi_id_val = params["pa"][0]
            if "pn" in params:
                upi_name_val = params["pn"][0]
        except Exception:
            pass  # If parsing fails, use provided values
    
    # Update/insert settings
    for key, val in [("upi_id", upi_id_val), ("upi_name", upi_name_val), ("upi_qr_code", qr_val)]:
        setting = db.query(Setting).filter(Setting.key == key).first()
        if not setting:
            setting = Setting(key=key, value=val or "")
            db.add(setting)
        else:
            setting.value = val or ""
    
    db.commit()
    return {"ok": True, "upi_id": upi_id_val, "upi_name": upi_name_val, "qr_code_data": qr_val}


@app.get("/api/upi-settings")
async def get_upi_settings_for_payer(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Read-only UPI display info for consultants/employers submitting a manual payment."""
    upi_id = db.query(Setting).filter(Setting.key == "upi_id").first()
    upi_name = db.query(Setting).filter(Setting.key == "upi_name").first()
    qr_code = db.query(Setting).filter(Setting.key == "upi_qr_code").first()
    return {
        "upi_id": upi_id.value if upi_id else "",
        "upi_name": upi_name.value if upi_name else "",
        "qr_code_data": qr_code.value if qr_code else "",
    }


# ── Permissions & Feature Flags (superadmin-managed, no code changes needed) ──
@app.get("/api/admin/feature-flags")
async def admin_list_feature_flags(
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    rows = db.query(FeatureFlag).order_by(FeatureFlag.key.asc()).all()
    existing_keys = {r.key for r in rows}
    # Surface any flag defined in code but not yet seeded (e.g. right after a deploy,
    # before startup migration has run against this connection) so the UI never 404s.
    for key, (default_value, description) in FEATURE_FLAG_DEFAULTS.items():
        if key not in existing_keys:
            rows.append(FeatureFlag(key=key, value=default_value, description=description))
    return {"flags": [{"key": r.key, "value": r.value, "description": r.description} for r in rows]}


@app.put("/api/admin/feature-flags")
async def admin_update_feature_flags(
    d: FeatureFlagsUpdateIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    changed = []
    for key, new_value in d.flags.items():
        flag = db.query(FeatureFlag).filter(FeatureFlag.key == key).first()
        if not flag:
            default_value, description = FEATURE_FLAG_DEFAULTS.get(key, (True, None))
            flag = FeatureFlag(key=key, value=default_value, description=description)
            db.add(flag)
        if flag.value != new_value:
            changed.append((key, flag.value, new_value))
            flag.value = new_value
    db.commit()

    for key, old_value, new_value in changed:
        log_activity(
            db, admin.id, None, "feature_flag_changed",
            f"Feature flag '{key}' changed from {old_value} to {new_value}",
            {"key": key, "old_value": old_value, "new_value": new_value}
        )
    return {"ok": True, "changed": len(changed)}


@app.get("/api/admin/role-permissions")
async def admin_list_role_permissions(
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    rows = db.query(RolePermission).all()
    existing = {(r.role, r.action) for r in rows}
    result = [{"role": r.role, "action": r.action, "allowed": r.allowed} for r in rows]
    for seed_role in ("consultant", "employer"):
        for seed_action in PERMISSION_ACTIONS:
            if (seed_role, seed_action) not in existing:
                result.append({"role": seed_role, "action": seed_action, "allowed": True})
    return {"permissions": result, "actions": PERMISSION_ACTIONS}


@app.put("/api/admin/role-permissions")
async def admin_update_role_permissions(
    d: RolePermissionsUpdateIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    changed = []
    for row in d.permissions:
        if row.role not in ("consultant", "employer"):
            raise HTTPException(400, f"Invalid role '{row.role}' — must be 'consultant' or 'employer'")
        perm = db.query(RolePermission).filter(RolePermission.role == row.role, RolePermission.action == row.action).first()
        if not perm:
            perm = RolePermission(role=row.role, action=row.action, allowed=row.allowed)
            db.add(perm)
            if row.allowed is False:
                changed.append((row.role, row.action, True, row.allowed))
        elif perm.allowed != row.allowed:
            changed.append((row.role, row.action, perm.allowed, row.allowed))
            perm.allowed = row.allowed
    db.commit()

    for role, action, old_value, new_value in changed:
        log_activity(
            db, admin.id, None, "role_permission_changed",
            f"Permission '{action}' for role '{role}' changed from {old_value} to {new_value}",
            {"role": role, "action": action, "old_value": old_value, "new_value": new_value}
        )
    return {"ok": True, "changed": len(changed)}


@app.get("/api/admin/users/{user_id}/permission-overrides")
async def admin_list_user_permission_overrides(
    user_id: int,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    rows = db.query(UserPermissionOverride).filter(UserPermissionOverride.user_id == user_id).order_by(UserPermissionOverride.action.asc()).all()
    return {
        "overrides": [{"id": r.id, "action": r.action, "allowed": r.allowed} for r in rows],
        "actions": PERMISSION_ACTIONS
    }


@app.post("/api/admin/users/{user_id}/permission-overrides")
async def admin_add_user_permission_override(
    user_id: int,
    d: PermissionOverrideIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    if d.action not in PERMISSION_ACTIONS:
        raise HTTPException(400, f"Unknown action '{d.action}'")

    existing = db.query(UserPermissionOverride).filter(UserPermissionOverride.user_id == user_id, UserPermissionOverride.action == d.action).first()
    if existing:
        old_value = existing.allowed
        existing.allowed = d.allowed
    else:
        old_value = None
        db.add(UserPermissionOverride(user_id=user_id, action=d.action, allowed=d.allowed))
    db.commit()

    log_activity(
        db, admin.id, None, "permission_override_added",
        f"Permission override for {user.name}: '{d.action}' set to {d.allowed}" + (f" (was {old_value})" if old_value is not None else ""),
        {"user_id": user_id, "action": d.action, "old_value": old_value, "new_value": d.allowed}
    )
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}/permission-overrides/{override_id}")
async def admin_delete_user_permission_override(
    user_id: int,
    override_id: int,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    override = db.query(UserPermissionOverride).filter(UserPermissionOverride.id == override_id, UserPermissionOverride.user_id == user_id).first()
    if not override:
        raise HTTPException(404, "Override not found")
    user = db.query(User).filter(User.id == user_id).first()
    action, old_value = override.action, override.allowed
    db.delete(override)
    db.commit()

    log_activity(
        db, admin.id, None, "permission_override_removed",
        f"Removed permission override for {user.name if user else user_id}: '{action}' (was {old_value}) — now falls back to role default",
        {"user_id": user_id, "action": action, "old_value": old_value, "new_value": None}
    )
    return {"ok": True}


# ── Subscription Fee Management Endpoints ─────────────────────────────────
@app.get("/api/admin/establishments/{est_id}/subscription-fees")
async def admin_get_establishment_subscription_fees(
    est_id: int,
    year: str = Query("2026-27"),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")
    consultant = db.query(User).filter(User.id == est.user_id).first()

    p = Project()
    if est.data:
        try:
            p.load_from_dict(json.loads(est.data))
        except Exception:
            pass

    sync_subscription_fees_for_year(db, est, p, year)

    default_setting = db.query(Setting).filter(Setting.key == "default_rate_per_employee").first()
    default_rate = float(default_setting.value) if default_setting and default_setting.value else 10.0
    billing_mode, resolved_flat_amount = resolve_billing_mode(db, est, consultant)
    billing_mode_explicit = est.billing_mode is not None
    # No "rate per employee" concept exists in flat-fee mode -- skip resolve_rate() entirely
    # rather than compute a figure that would just be confusing and unused.
    effective_rate = resolve_rate(db, est, consultant) if billing_mode == "per_employee" else None

    fee_rows = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id,
        SubscriptionFee.financial_year == year
    ).all()
    fee_map = {f.month: f for f in fee_rows}

    months_data = []
    yf = year.split("-")[0]
    yt = str(int(yf) + 1)  # financial years are always consecutive -- avoids passing a 2-digit "27" into calendar_year_for_month

    for i, m_abbr in enumerate(MONTH_SHORT_NAMES):
        f_obj = fee_map.get(m_abbr)
        emp_count = count_ecr_employees_for_month(p, year, i)
        cal_yr = calendar_year_for_month(m_abbr, yf, yt)
        display_name = f"{MONTH_FULL.get(m_abbr.upper(), m_abbr)} {cal_yr}"
        overdue = is_month_overdue(year, i) and emp_count > 0 and (not f_obj or not f_obj.is_paid)

        row_mode = (f_obj.billing_mode if f_obj else billing_mode) or "per_employee"
        amount_due = f_obj.amount_due if f_obj else (resolved_flat_amount if billing_mode == "flat_fee" else round(emp_count * (effective_rate or 0), 2))
        billing_display = f"₹{amount_due}/month flat rate" if row_mode == "flat_fee" else f"₹{f_obj.rate_applied if f_obj else effective_rate}/employee"

        months_data.append({
            "month_idx": i,
            "month": m_abbr,
            "display_name": display_name,
            "employee_count": f_obj.employee_count if f_obj else emp_count,
            "rate_applied": f_obj.rate_applied if f_obj else effective_rate,
            "amount_due": amount_due,
            "billing_mode": row_mode,
            "billing_display": billing_display,
            "is_paid": f_obj.is_paid if f_obj else False,
            "paid_date": f_obj.paid_date or "" if f_obj else "",
            "payment_reference": f_obj.payment_reference or "" if f_obj else "",
            "notes": f_obj.notes or "" if f_obj else "",
            "is_overdue": overdue,
            "cashfree_order_id": (f_obj.cashfree_order_id or "") if f_obj else "",
            "cashfree_payment_link_url": (f_obj.cashfree_payment_link_url or "") if f_obj else ""
        })

    return {
        "establishment": {
            "id": est.id,
            "code": est.code,
            "name": est.name,
            "custom_rate": est.custom_rate_per_employee,
            "billing_mode": billing_mode,
            "flat_fee_amount": resolved_flat_amount,
            "billing_mode_explicit": billing_mode_explicit,
            "billing_mode_own": est.billing_mode,
            "flat_fee_amount_own": est.flat_fee_amount,
            "trial_ends_on": est.trial_ends_on.isoformat() if est.trial_ends_on else None,
            "is_in_trial": is_establishment_in_trial(est),
            "trial_days_left": get_trial_days_left(est)
        },
        "consultant": {
            "id": consultant.id if consultant else None,
            "name": consultant.name if consultant else "",
            "email": consultant.email if consultant else "",
            "role": consultant.role if consultant else None,
            "custom_rate": consultant.custom_rate_per_employee if consultant else None,
            "default_billing_mode": consultant.default_billing_mode if consultant else None,
            "default_flat_fee_per_establishment": consultant.default_flat_fee_per_establishment if consultant else None
        },
        "rates": {
            "global_default": default_rate,
            "consultant_override": consultant.custom_rate_per_employee if consultant else None,
            "establishment_override": est.custom_rate_per_employee,
            "effective_rate": effective_rate
        },
        "financial_year": year,
        "months": months_data
    }


@app.put("/api/admin/establishments/{est_id}/trial")
async def admin_update_establishment_trial(
    est_id: int,
    d: TrialUpdateIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Set, extend, or clear (trial_ends_on=null) an establishment's free trial, independent
    of establishment creation -- e.g. to start a trial for an already-live paying
    establishment, extend one that's about to lapse, or end one early."""
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    old_date = est.trial_ends_on
    new_date = None
    if d.trial_ends_on:
        try:
            new_date = datetime.strptime(d.trial_ends_on, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "trial_ends_on must be in YYYY-MM-DD format")

    if old_date == new_date:
        return {
            "ok": True,
            "trial_ends_on": new_date.isoformat() if new_date else None,
            "is_in_trial": is_establishment_in_trial(est),
            "trial_days_left": get_trial_days_left(est)
        }

    est.trial_ends_on = new_date
    db.commit()

    old_str = old_date.strftime('%d-%m-%Y') if old_date else "None"
    new_str = new_date.strftime('%d-%m-%Y') if new_date else "None"
    if old_date is None:
        action_type, desc = "trial_started", f"Started free trial for {est.name} ({est.code}) until {new_str}"
    elif new_date is None:
        action_type, desc = "trial_ended", f"Ended free trial early for {est.name} ({est.code}) (was until {old_str})"
    else:
        action_type, desc = "trial_extended", f"Changed free trial for {est.name} ({est.code}) from {old_str} to {new_str}"

    log_activity(
        db, admin.id, est.id, action_type, desc,
        {"old_trial_ends_on": old_date.isoformat() if old_date else None, "new_trial_ends_on": new_date.isoformat() if new_date else None}
    )

    return {
        "ok": True,
        "trial_ends_on": new_date.isoformat() if new_date else None,
        "is_in_trial": is_establishment_in_trial(est),
        "trial_days_left": get_trial_days_left(est)
    }


def _describe_billing_mode(mode: Optional[str], flat_amount: Optional[float]) -> str:
    if mode is None:
        return "Inherit (consultant's default, or global default if none set)"
    if mode == "flat_fee":
        return f"Flat ₹{flat_amount}/month"
    return "Per Employee (tiered/custom rate)"


@app.put("/api/admin/establishments/{est_id}/billing-mode")
async def admin_update_establishment_billing_mode(
    est_id: int,
    d: BillingModeUpdateIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Switch an establishment between per-employee (tiered/custom rate), flat-fee billing,
    or 'inherit' (clears the establishment's own override so it resumes following its
    consultant's default_billing_mode, or the global default if the consultant has none set)
    -- a superadmin-only decision, never reachable from any Consultant/Employer endpoint.
    Only affects FUTURE (still-unpaid) SubscriptionFee months; already-paid rows remember
    their own billing_mode and stay frozen at whatever amount was correct when they were
    billed (see sync_subscription_fees_for_year)."""
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    mode = (d.billing_mode or "").strip()
    if mode not in ("per_employee", "flat_fee", "inherit"):
        raise HTTPException(400, "billing_mode must be 'per_employee', 'flat_fee', or 'inherit'")

    flat_amount = None
    if mode == "flat_fee":
        if d.flat_fee_amount is None or d.flat_fee_amount <= 0:
            raise HTTPException(400, "flat_fee_amount must be a positive number for flat_fee billing mode")
        flat_amount = round(float(d.flat_fee_amount), 2)

    new_mode_raw = None if mode == "inherit" else mode  # 'inherit' is stored as null, not a literal mode
    old_mode_raw = est.billing_mode
    old_amount = est.flat_fee_amount

    if old_mode_raw == new_mode_raw and old_amount == flat_amount:
        resolved_mode, resolved_flat = resolve_billing_mode(db, est)
        return {"ok": True, "billing_mode": est.billing_mode, "flat_fee_amount": est.flat_fee_amount,
                "is_explicit": est.billing_mode is not None, "effective_billing_mode": resolved_mode, "effective_flat_fee_amount": resolved_flat}

    est.billing_mode = new_mode_raw
    est.flat_fee_amount = flat_amount
    db.commit()

    log_activity(
        db, admin.id, est.id, "billing_mode_changed",
        f"Changed billing mode for {est.name} ({est.code}): "
        f"{_describe_billing_mode(old_mode_raw, old_amount)} → {_describe_billing_mode(new_mode_raw, flat_amount)}",
        {
            "old_billing_mode": old_mode_raw, "old_flat_fee_amount": old_amount,
            "new_billing_mode": new_mode_raw, "new_flat_fee_amount": flat_amount
        }
    )

    resolved_mode, resolved_flat = resolve_billing_mode(db, est)
    return {"ok": True, "billing_mode": est.billing_mode, "flat_fee_amount": est.flat_fee_amount,
            "is_explicit": est.billing_mode is not None, "effective_billing_mode": resolved_mode, "effective_flat_fee_amount": resolved_flat}


@app.post("/api/admin/establishments/{est_id}/subscription-fees")
async def admin_save_establishment_subscription_fees(
    est_id: int,
    d: SubscriptionFeesSaveIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    fy = d.financial_year.strip()
    newly_paid = []
    for item in d.fees:
        f_obj = db.query(SubscriptionFee).filter(
            SubscriptionFee.establishment_id == est_id,
            SubscriptionFee.financial_year == fy,
            SubscriptionFee.month == item.month
        ).first()

        if f_obj:
            if not f_obj.is_paid and item.is_paid:
                newly_paid.append(item.month)
            f_obj.is_paid = item.is_paid
            f_obj.payment_status = "paid" if item.is_paid else "unpaid"
            f_obj.paid_date = item.paid_date or ""
            f_obj.payment_reference = item.payment_reference or ""
            f_obj.notes = item.notes or ""
        else:
            f_obj = SubscriptionFee(
                establishment_id=est_id,
                financial_year=fy,
                month=item.month,
                is_paid=item.is_paid,
                payment_status="paid" if item.is_paid else "unpaid",
                paid_date=item.paid_date or "",
                payment_reference=item.payment_reference or "",
                notes=item.notes or ""
            )
            db.add(f_obj)
            if item.is_paid:
                newly_paid.append(item.month)

    db.commit()

    if newly_paid:
        log_activity(
            db, admin.id, est.id, "subscription_paid",
            f"Marked software subscription fee PAID for {est.name} ({est.code}) — {', '.join(newly_paid)} (FY {fy})",
            {"financial_year": fy, "months_paid": newly_paid, "code": est.code}
        )

    return {"ok": True}


def _confirm_subscription_fee_paid(db: Session, fee_row: SubscriptionFee, payment_ref: str, source: str = "cashfree"):
    """Shared confirmation logic used by both the webhook and the manual refresh button.
    Idempotent -- a no-op if the row is already paid."""
    if fee_row.is_paid:
        return
    fee_row.is_paid = True
    fee_row.payment_status = "paid"
    fee_row.payment_reference = payment_ref
    fee_row.paid_date = date.today().strftime("%d-%m-%Y")
    db.commit()

    log_activity(
        db, None, fee_row.establishment_id, "subscription_paid",
        f"Software subscription fee PAID via Cashfree for {fee_row.month} (FY {fee_row.financial_year}) — Ref: {payment_ref}",
        {
            "financial_year": fee_row.financial_year, "month": fee_row.month,
            "amount": fee_row.amount_due, "cashfree_order_id": fee_row.cashfree_order_id,
            "source": source
        }
    )


def _app_base_url(request: Request) -> str:
    """Public base URL the browser should be sent back to after a Cashfree payment.
    Prefers APP_BASE_URL (set this on Render, where the proxy can obscure the real
    public scheme/host) and falls back to the incoming request's own host -- which is
    correct as-is for local dev (http://localhost:8000)."""
    override = os.environ.get("APP_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    return str(request.base_url).rstrip("/")


def _create_fee_payment_link(db: Session, est: Establishment, fee_row: SubscriptionFee, return_url: str = None) -> dict:
    """Shared by both the superadmin and consultant-facing create-link endpoints."""
    if fee_row.is_paid:
        raise HTTPException(400, "This month is already marked paid.")
    if fee_row.amount_due <= 0:
        raise HTTPException(400, "No fee due for this month.")

    consultant = db.query(User).filter(User.id == est.user_id).first()
    phone = (consultant.mobile or "").strip() if consultant else ""
    if not phone:
        raise HTTPException(400, "Consultant has no mobile number on file — required by Cashfree to generate a payment link.")

    order_id = cashfree_client.new_order_id("sub", fee_row.id)
    try:
        link_resp = cashfree_client.create_payment_link(
            link_id=order_id,
            amount=fee_row.amount_due,
            purpose=f"Software subscription fee — {fee_row.month} {fee_row.financial_year} — {est.name} ({est.code})",
            customer_phone=phone,
            customer_name=consultant.name if consultant else "",
            customer_email=consultant.email if consultant else "",
            return_url=return_url,
        )
    except cashfree_client.CashfreeConfigError as e:
        raise HTTPException(500, str(e))
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree link creation failed: {e.response.text if e.response is not None else str(e)}")

    fee_row.cashfree_order_id = order_id
    fee_row.cashfree_payment_link_url = link_resp.get("link_url")
    db.commit()

    return {"ok": True, "link_url": link_resp.get("link_url"), "order_id": order_id}


@app.post("/api/admin/establishments/{est_id}/subscription-fees/create-link")
async def admin_create_subscription_fee_link(
    est_id: int,
    d: CreateFeeLinkIn,
    request: Request,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Generates a Cashfree Payment Link for one month's already-billed SubscriptionFee row."""
    require_feature_enabled(db, "cashfree_payments_enabled", "Cashfree payments")
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    fee_row = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id,
        SubscriptionFee.financial_year == d.financial_year,
        SubscriptionFee.month == d.month
    ).first()
    if not fee_row:
        raise HTTPException(404, "Subscription fee row not found for this month — load the Subscription Fees grid first.")

    return_url = f"{_app_base_url(request)}/?cf_payment_return=1&type=sub&year={fee_row.financial_year}&month={fee_row.month}&est_id={est.id}"
    return _create_fee_payment_link(db, est, fee_row, return_url=return_url)


@app.post("/api/admin/establishments/{est_id}/subscription-fees/refresh-status")
async def admin_refresh_subscription_fee_status(
    est_id: int,
    d: CreateFeeLinkIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Manually polls Cashfree for a pending per-month link's status, in case the webhook
    is delayed."""
    fee_row = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id,
        SubscriptionFee.financial_year == d.financial_year,
        SubscriptionFee.month == d.month
    ).first()
    if not fee_row:
        raise HTTPException(404, "Subscription fee row not found")
    if fee_row.is_paid or not fee_row.cashfree_order_id:
        return {"ok": True, "is_paid": fee_row.is_paid}

    try:
        status_resp = cashfree_client.get_payment_link_status(fee_row.cashfree_order_id)
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree status check failed: {e.response.text if e.response is not None else str(e)}")

    if status_resp.get("link_status") == "PAID":
        _confirm_subscription_fee_paid(db, fee_row, payment_ref=str(status_resp.get("cf_link_id") or fee_row.cashfree_order_id))

    return {"ok": True, "is_paid": fee_row.is_paid}


# ── UPI Payment Path Endpoints ────────────────────────────────────────────────
# These allow consultants/employers to submit UTR for manual UPI payments,
# and superadmin to approve/reject those submissions.

def _utr_already_submitted(db: Session, utr: str, exclude_fee_id: Optional[int] = None) -> bool:
    """A UTR is a bank-issued transaction reference -- the same one should never be
    submitted twice, whether for two different fees or reused across the subscription-fee
    and advance-credit flows. Checks both tables."""
    fee_q = db.query(SubscriptionFee).filter(SubscriptionFee.submitted_utr == utr)
    if exclude_fee_id:
        fee_q = fee_q.filter(SubscriptionFee.id != exclude_fee_id)
    if fee_q.first():
        return True
    return db.query(AdvanceCreditLedger).filter(AdvanceCreditLedger.submitted_utr == utr).first() is not None


@app.post("/api/subscription-fees/{fee_id}/submit-utr")
async def submit_utr(
    fee_id: int,
    d: SubmitUTRIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Consultant or Employer submits UTR for a subscription fee payment."""
    fee = db.query(SubscriptionFee).filter(SubscriptionFee.id == fee_id).first()
    if not fee:
        raise HTTPException(404, "Subscription fee not found")

    est = db.query(Establishment).filter(Establishment.id == fee.establishment_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    if current_user.role != "superadmin" and est.user_id != current_user.id:
        raise HTTPException(403, "Not authorized for this establishment")

    if fee.payment_status == "paid":
        raise HTTPException(400, "This fee is already paid")

    utr = d.utr.strip()
    if not utr:
        raise HTTPException(400, "UTR cannot be empty")

    if _utr_already_submitted(db, utr, exclude_fee_id=fee.id):
        raise HTTPException(400, "This UTR has already been submitted for verification.")

    fee.payment_status = "pending_verification"
    fee.submitted_utr = utr
    fee.submitted_by = current_user.id
    fee.submitted_at = datetime.now(timezone.utc)
    fee.rejection_reason = None
    db.commit()

    log_activity(
        db, current_user.id, est.id, "utr_submitted",
        f"UTR submitted for {fee.month} {fee.financial_year} — {est.name} ({est.code}): {utr}",
        {"financial_year": fee.financial_year, "month": fee.month, "utr": utr}
    )

    return {"ok": True, "payment_status": "pending_verification"}


_LEDGER_STATUS_DISPLAY = {
    "pending_verification": "pending_verification",
    "confirmed": "paid",
    "rejected": "unpaid",
    "pending": "unpaid",
    "manual": "paid",
}


def _split_verification_id(item_id: str) -> Tuple[str, int]:
    """Payment-verification queue items are composite ids ('fee-5' / 'adv-12') so the
    approve/reject endpoints can tell which table a row came from. A bare integer is
    still accepted for backward compatibility with any old bookmarked links -- it's
    always treated as a subscription-fee id, matching this endpoint's original (and only
    prior) behavior."""
    if item_id.startswith("fee-"):
        return "fee", int(item_id[4:])
    if item_id.startswith("adv-"):
        return "adv", int(item_id[4:])
    if item_id.isdigit():
        return "fee", int(item_id)
    raise HTTPException(400, "Invalid verification id")


@app.get("/api/admin/payment-verifications")
async def payment_verifications(
    status: str = Query("pending_verification"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Superadmin lists subscription fees AND advance-credit top-ups awaiting UTR
    verification via the manual UPI/QR path, merged into a single queue."""
    fee_q = db.query(SubscriptionFee)
    ledger_q = db.query(AdvanceCreditLedger).filter(AdvanceCreditLedger.entry_type == "topup")

    if status == "pending_verification":
        fee_q = fee_q.filter(SubscriptionFee.payment_status == "pending_verification")
        ledger_q = ledger_q.filter(AdvanceCreditLedger.status == "pending_verification")
    elif status == "paid":
        fee_q = fee_q.filter(SubscriptionFee.payment_status == "paid")
        ledger_q = ledger_q.filter(AdvanceCreditLedger.status == "confirmed")
    elif status == "unpaid":
        fee_q = fee_q.filter(SubscriptionFee.payment_status == "unpaid")
        ledger_q = ledger_q.filter(AdvanceCreditLedger.status == "rejected")

    fee_rows = fee_q.all()
    ledger_rows = ledger_q.all()

    est_ids = {r.establishment_id for r in fee_rows} | {r.establishment_id for r in ledger_rows}
    ests_map = {e.id: e for e in db.query(Establishment).filter(Establishment.id.in_(est_ids)).all()} if est_ids else {}

    user_ids = (
        {r.submitted_by for r in fee_rows if r.submitted_by} | {r.verified_by for r in fee_rows if r.verified_by} |
        {r.submitted_by for r in ledger_rows if r.submitted_by} | {r.verified_by for r in ledger_rows if r.verified_by}
    )
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    items = []
    for r in fee_rows:
        est = ests_map.get(r.establishment_id)
        submitted_by_user = users_map.get(r.submitted_by) if r.submitted_by else None
        verified_by_user = users_map.get(r.verified_by) if r.verified_by else None

        yf = r.financial_year.split("-")[0]
        yt = str(int(yf) + 1)
        cal_yr = calendar_year_for_month(r.month, yf, yt)
        display_name = f"{MONTH_FULL.get(r.month.upper(), r.month)} {cal_yr}"

        items.append({
            "id": f"fee-{r.id}",
            "source": "subscription_fee",
            "establishment_id": r.establishment_id,
            "establishment_code": est.code if est else "",
            "establishment_name": est.name if est else "",
            "financial_year": r.financial_year,
            "month": r.month,
            "display_name": display_name,
            "amount_due": r.amount_due,
            "payment_status": r.payment_status,
            "submitted_utr": r.submitted_utr or "",
            "submitted_by": r.submitted_by,
            "submitted_by_name": submitted_by_user.name if submitted_by_user else "",
            "submitted_by_email": submitted_by_user.email if submitted_by_user else "",
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else "",
            "verified_by": r.verified_by,
            "verified_by_name": verified_by_user.name if verified_by_user else "",
            "verified_at": r.verified_at.isoformat() if r.verified_at else "",
            "rejection_reason": r.rejection_reason or "",
            "_sort_dt": r.submitted_at.isoformat() if r.submitted_at else "",
        })

    for r in ledger_rows:
        est = ests_map.get(r.establishment_id)
        submitted_by_user = users_map.get(r.submitted_by) if r.submitted_by else None
        verified_by_user = users_map.get(r.verified_by) if r.verified_by else None
        sort_dt = r.submitted_at or r.created_at

        items.append({
            "id": f"adv-{r.id}",
            "source": "advance_credit",
            "establishment_id": r.establishment_id,
            "establishment_code": est.code if est else "",
            "establishment_name": est.name if est else "",
            "financial_year": None,
            "month": None,
            "display_name": "Advance Credit Top-up",
            "amount_due": r.amount,
            "payment_status": _LEDGER_STATUS_DISPLAY.get(r.status, r.status),
            "submitted_utr": r.submitted_utr or "",
            "submitted_by": r.submitted_by,
            "submitted_by_name": submitted_by_user.name if submitted_by_user else "",
            "submitted_by_email": submitted_by_user.email if submitted_by_user else "",
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else "",
            "verified_by": r.verified_by,
            "verified_by_name": verified_by_user.name if verified_by_user else "",
            "verified_at": r.verified_at.isoformat() if r.verified_at else "",
            "rejection_reason": r.rejection_reason or "",
            "_sort_dt": sort_dt.isoformat() if sort_dt else "",
        })

    items.sort(key=lambda it: it["_sort_dt"], reverse=True)
    total = len(items)
    offset = (page - 1) * limit
    page_items = items[offset:offset + limit]
    for it in page_items:
        it.pop("_sort_dt", None)

    return {"items": page_items, "total": total, "page": page, "limit": limit}


@app.post("/api/admin/payment-verifications/{item_id}/approve")
async def approve_payment(
    item_id: str,
    d: ApprovePaymentIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Superadmin approves a UTR submission -- marks a subscription fee as paid, or
    confirms an advance-credit top-up and credits the establishment's balance."""
    kind, real_id = _split_verification_id(item_id)

    if kind == "fee":
        fee = db.query(SubscriptionFee).filter(SubscriptionFee.id == real_id).first()
        if not fee:
            raise HTTPException(404, "Subscription fee not found")

        if fee.payment_status != "pending_verification":
            raise HTTPException(400, "Only pending_verification fees can be approved")

        # A "pay all overdue" batch submits the SAME utr across every covered
        # SubscriptionFee row (no new linking table) -- so approving any one row
        # of the batch must cascade to its still-pending siblings sharing that utr.
        sibling_fees = []
        if fee.submitted_utr:
            sibling_fees = db.query(SubscriptionFee).filter(
                SubscriptionFee.establishment_id == fee.establishment_id,
                SubscriptionFee.submitted_utr == fee.submitted_utr,
                SubscriptionFee.payment_status == "pending_verification",
                SubscriptionFee.id != fee.id,
            ).all()

        now = datetime.now(timezone.utc)
        today_str = date.today().strftime("%d-%m-%Y")
        approved_months = [f"{fee.month} {fee.financial_year}"]
        for row in [fee] + sibling_fees:
            row.payment_status = "paid"
            row.is_paid = True
            row.verified_by = admin.id
            row.verified_at = now
            row.payment_reference = row.submitted_utr
            row.paid_date = today_str
            if row is not fee:
                approved_months.append(f"{row.month} {row.financial_year}")
        db.commit()

        est = db.query(Establishment).filter(Establishment.id == fee.establishment_id).first()
        months_str = ", ".join(approved_months)
        log_activity(
            db, admin.id, fee.establishment_id, "utr_approved",
            f"Approved UTR payment for {months_str} — {est.name if est else ''}: {fee.submitted_utr}",
            {"financial_year": fee.financial_year, "month": fee.month, "utr": fee.submitted_utr, "months": approved_months}
        )

        return {"ok": True, "payment_status": "paid", "months_approved": approved_months}

    ledger_row = db.query(AdvanceCreditLedger).filter(AdvanceCreditLedger.id == real_id).first()
    if not ledger_row:
        raise HTTPException(404, "Advance credit entry not found")
    if ledger_row.status != "pending_verification":
        raise HTTPException(400, "Only pending_verification entries can be approved")

    ledger_row.verified_by = admin.id
    ledger_row.verified_at = datetime.now(timezone.utc)
    _confirm_advance_credit_ledger_row(db, ledger_row, payment_ref=ledger_row.submitted_utr, source="manual_utr")

    est = db.query(Establishment).filter(Establishment.id == ledger_row.establishment_id).first()
    return {"ok": True, "payment_status": "paid", "advance_credit_balance": est.advance_credit_balance if est else None}


@app.post("/api/admin/payment-verifications/{item_id}/reject")
async def reject_payment(
    item_id: str,
    d: RejectPaymentIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Superadmin rejects a UTR submission with a reason -- for a subscription fee, it
    goes back to unpaid for resubmission; for an advance-credit top-up, the ledger row is
    marked rejected (the balance is never touched) and the consultant can submit a fresh
    top-up."""
    kind, real_id = _split_verification_id(item_id)

    if kind == "fee":
        fee = db.query(SubscriptionFee).filter(SubscriptionFee.id == real_id).first()
        if not fee:
            raise HTTPException(404, "Subscription fee not found")

        if fee.payment_status != "pending_verification":
            raise HTTPException(400, "Only pending_verification fees can be rejected")

        reason = d.rejection_reason.strip()
        if not reason:
            raise HTTPException(400, "Rejection reason is required")

        fee.payment_status = "unpaid"
        fee.rejection_reason = reason
        fee.verified_by = admin.id
        fee.verified_at = datetime.now(timezone.utc)
        db.commit()

        est = db.query(Establishment).filter(Establishment.id == fee.establishment_id).first()
        log_activity(
            db, admin.id, fee.establishment_id, "utr_rejected",
            f"Rejected UTR for {fee.month} {fee.financial_year} — {est.name if est else ''}: {reason}",
            {"financial_year": fee.financial_year, "month": fee.month, "utr": fee.submitted_utr, "reason": reason}
        )

        return {"ok": True, "payment_status": "unpaid", "rejection_reason": reason}

    ledger_row = db.query(AdvanceCreditLedger).filter(AdvanceCreditLedger.id == real_id).first()
    if not ledger_row:
        raise HTTPException(404, "Advance credit entry not found")
    if ledger_row.status != "pending_verification":
        raise HTTPException(400, "Only pending_verification entries can be rejected")

    reason = d.rejection_reason.strip()
    if not reason:
        raise HTTPException(400, "Rejection reason is required")

    ledger_row.status = "rejected"
    ledger_row.rejection_reason = reason
    ledger_row.verified_by = admin.id
    ledger_row.verified_at = datetime.now(timezone.utc)
    db.commit()

    est = db.query(Establishment).filter(Establishment.id == ledger_row.establishment_id).first()
    log_activity(
        db, admin.id, ledger_row.establishment_id, "utr_rejected",
        f"Rejected UTR for advance-credit top-up of ₹{ledger_row.amount} — {est.name if est else ''}: {reason}",
        {"amount": ledger_row.amount, "utr": ledger_row.submitted_utr, "reason": reason}
    )

    return {"ok": True, "payment_status": "unpaid", "rejection_reason": reason}


# ── Advance Subscription Credit Endpoints ──────────────────────────────────
def _ledger_history_for_establishment(db: Session, est_id: int):
    rows = db.query(AdvanceCreditLedger).filter(
        AdvanceCreditLedger.establishment_id == est_id
    ).order_by(AdvanceCreditLedger.created_at.desc(), AdvanceCreditLedger.id.desc()).all()

    fee_ids = list({r.applied_to_fee_id for r in rows if r.applied_to_fee_id})
    fees_map = {f.id: f for f in db.query(SubscriptionFee).filter(SubscriptionFee.id.in_(fee_ids)).all()} if fee_ids else {}

    history = []
    for r in rows:
        fee = fees_map.get(r.applied_to_fee_id) if r.applied_to_fee_id else None
        history.append({
            "id": r.id,
            "entry_type": r.entry_type,
            "amount": r.amount,
            "status": r.status,
            "cashfree_order_id": r.cashfree_order_id,
            "cashfree_payment_link_url": r.cashfree_payment_link_url,
            "payment_reference": r.payment_reference,
            "notes": r.notes,
            "applied_month": f"{fee.month} {fee.financial_year}" if fee else None,
            "time_formatted": r.created_at.strftime("%d-%m-%Y %I:%M %p") if r.created_at else "—"
        })
    return history


@app.post("/api/admin/establishments/{est_id}/advance-payment")
async def admin_add_advance_payment(
    est_id: int,
    d: AdvancePaymentIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Manual advance top-up (superadmin recorded it by hand -- UPI/cash/etc, no Cashfree)."""
    require_feature_enabled(db, "advance_credit_enabled", "Advance credit")
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")
    if d.amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    old_balance = est.advance_credit_balance or 0.0
    est.advance_credit_balance = round(old_balance + d.amount, 2)

    db.add(AdvanceCreditLedger(
        establishment_id=est.id, entry_type="topup", amount=d.amount,
        payment_reference=d.payment_reference or None, notes=d.notes or None,
        status="manual"
    ))
    db.commit()

    log_activity(
        db, admin.id, est.id, "advance_payment_received",
        f"Advance subscription payment of ₹{d.amount} received for {est.name} ({est.code})"
        f"{' — Ref: ' + d.payment_reference if d.payment_reference else ''}. New balance: ₹{est.advance_credit_balance}",
        {
            "amount": d.amount, "payment_reference": d.payment_reference, "notes": d.notes,
            "old_balance": old_balance, "new_balance": est.advance_credit_balance, "code": est.code, "source": "manual"
        }
    )
    return {"ok": True, "advance_credit_balance": est.advance_credit_balance}


@app.post("/api/admin/establishments/{est_id}/advance-payment/create-link")
async def admin_create_advance_payment_link(
    est_id: int,
    d: AdvancePaymentIn,
    request: Request,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Generates a Cashfree Payment Link for an advance top-up. The balance is NOT touched
    here -- only the webhook (or a manual refresh) confirming actual payment updates it."""
    require_feature_enabled(db, "cashfree_payments_enabled", "Cashfree payments")
    require_feature_enabled(db, "advance_credit_enabled", "Advance credit")
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")
    if d.amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    consultant = db.query(User).filter(User.id == est.user_id).first()
    phone = (consultant.mobile or "").strip() if consultant else ""
    if not phone:
        raise HTTPException(400, "Consultant has no mobile number on file — required by Cashfree to generate a payment link.")

    order_id = cashfree_client.new_order_id("adv", est.id)
    return_url = f"{_app_base_url(request)}/?cf_payment_return=1&type=adv&est_id={est.id}&order_id={order_id}"
    try:
        link_resp = cashfree_client.create_payment_link(
            link_id=order_id,
            amount=d.amount,
            purpose=f"Advance subscription credit — {est.name} ({est.code})",
            customer_phone=phone,
            customer_name=consultant.name if consultant else "",
            customer_email=consultant.email if consultant else "",
            return_url=return_url,
        )
    except cashfree_client.CashfreeConfigError as e:
        raise HTTPException(500, str(e))
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree link creation failed: {e.response.text if e.response is not None else str(e)}")

    ledger_row = AdvanceCreditLedger(
        establishment_id=est.id, entry_type="topup", amount=d.amount,
        cashfree_order_id=order_id, cashfree_payment_link_url=link_resp.get("link_url"),
        notes=d.notes or None, status="pending"
    )
    db.add(ledger_row)
    db.commit()

    return {"ok": True, "link_url": link_resp.get("link_url"), "order_id": order_id}


@app.post("/api/admin/establishments/{est_id}/advance-credit/{ledger_id}/refresh-status")
async def admin_refresh_advance_credit_status(
    est_id: int,
    ledger_id: int,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Manually polls Cashfree for a pending advance-credit link's status, in case the
    webhook is delayed. Applies the exact same confirmation logic as the webhook."""
    ledger_row = db.query(AdvanceCreditLedger).filter(
        AdvanceCreditLedger.id == ledger_id, AdvanceCreditLedger.establishment_id == est_id
    ).first()
    if not ledger_row:
        raise HTTPException(404, "Ledger entry not found")
    if ledger_row.status != "pending" or not ledger_row.cashfree_order_id:
        return {"ok": True, "status": ledger_row.status, "advance_credit_balance": None}

    try:
        status_resp = cashfree_client.get_payment_link_status(ledger_row.cashfree_order_id)
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree status check failed: {e.response.text if e.response is not None else str(e)}")

    if status_resp.get("link_status") == "PAID":
        _confirm_advance_credit_ledger_row(db, ledger_row, payment_ref=str(status_resp.get("cf_link_id") or ledger_row.cashfree_order_id))

    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    return {"ok": True, "status": ledger_row.status, "advance_credit_balance": est.advance_credit_balance if est else None}


def _confirm_advance_credit_ledger_row(db: Session, ledger_row: AdvanceCreditLedger, payment_ref: str, source: str = "cashfree"):
    """Shared confirmation logic used by the Cashfree webhook, the manual refresh button,
    and superadmin approval of a manually-submitted UTR. Idempotent -- a no-op if the row
    is already confirmed."""
    if ledger_row.status == "confirmed":
        return
    est = db.query(Establishment).filter(Establishment.id == ledger_row.establishment_id).first()
    if not est:
        return

    ledger_row.status = "confirmed"
    ledger_row.payment_reference = payment_ref
    old_balance = est.advance_credit_balance or 0.0
    est.advance_credit_balance = round(old_balance + ledger_row.amount, 2)
    db.commit()

    via = "Cashfree" if source == "cashfree" else "manual UTR verification"
    log_activity(
        db, ledger_row.verified_by, est.id, "advance_payment_received",
        f"Advance subscription payment of ₹{ledger_row.amount} received via {via} for {est.name} ({est.code}) "
        f"— Ref: {payment_ref}. New balance: ₹{est.advance_credit_balance}",
        {
            "amount": ledger_row.amount, "payment_reference": payment_ref,
            "old_balance": old_balance, "new_balance": est.advance_credit_balance,
            "code": est.code, "source": source, "cashfree_order_id": ledger_row.cashfree_order_id
        }
    )


@app.get("/api/admin/establishments/{est_id}/advance-credit")
async def admin_get_advance_credit(
    est_id: int,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    return {
        "establishment": {"id": est.id, "code": est.code, "name": est.name},
        "advance_credit_balance": est.advance_credit_balance or 0.0,
        "history": _ledger_history_for_establishment(db, est_id)
    }


# ── Cashfree Webhook ────────────────────────────────────────────────────────
# Unauthenticated by design (Cashfree calls this directly) -- trust is established
# purely via HMAC signature verification below, never via JWT/session.
@app.post("/api/webhooks/cashfree")
async def cashfree_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    timestamp = request.headers.get("x-webhook-timestamp", "")
    signature = request.headers.get("x-webhook-signature", "")

    if not cashfree_client.verify_webhook_signature(timestamp, raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    data = payload.get("data") or {}
    link_id = data.get("link_id") or ""
    link_status = data.get("link_status") or ""

    if not link_id:
        print("[CashfreeWebhook] Payload missing data.link_id -- ignoring.")
        return {"ok": True}

    if link_status != "PAID":
        # Ignore ACTIVE/EXPIRED/PARTIALLY_PAID/etc -- we only act on a fully-paid link.
        return {"ok": True}

    order_info = data.get("order") or {}
    payment_ref = str(order_info.get("transaction_id") or order_info.get("order_id") or data.get("cf_link_id") or link_id)

    if link_id.startswith("sub_"):
        # A "pay all overdue" batch order writes the SAME cashfree_order_id across every
        # covered SubscriptionFee row, so .all() (not .first()) is required to confirm
        # every month the order paid for, not just one.
        fee_rows = db.query(SubscriptionFee).filter(SubscriptionFee.cashfree_order_id == link_id).all()
        if not fee_rows:
            print(f"[CashfreeWebhook] No SubscriptionFee found for order_id={link_id}")
            return {"ok": True}
        for fee_row in fee_rows:
            _confirm_subscription_fee_paid(db, fee_row, payment_ref=payment_ref, source="cashfree")

    elif link_id.startswith("adv_"):
        ledger_row = db.query(AdvanceCreditLedger).filter(AdvanceCreditLedger.cashfree_order_id == link_id).first()
        if not ledger_row:
            print(f"[CashfreeWebhook] No AdvanceCreditLedger row found for order_id={link_id}")
            return {"ok": True}
        _confirm_advance_credit_ledger_row(db, ledger_row, payment_ref=payment_ref)

    else:
        print(f"[CashfreeWebhook] Unrecognized order_id prefix, ignoring: {link_id}")

    return {"ok": True}


# ── EPF Monthly Payments (TRRN Remittance) Endpoints ──────────────────────
@app.get("/api/admin/establishments/{est_id}/payments")
async def admin_get_establishment_payments(
    est_id: int,
    year: str = Query("2026-27"),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    records = db.query(Payment).filter(
        Payment.establishment_id == est_id,
        Payment.financial_year == year
    ).all()
    payments_by_month = {p.month: p for p in records}

    PAYMENT_MONTHS = ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
    grid = []
    for idx, m in enumerate(PAYMENT_MONTHS):
        p = payments_by_month.get(m)
        next_m = PAYMENT_MONTHS[(idx + 1) % 12]
        grid.append({
            "month": m,
            "display_name": f"{m} (Paid in {next_m})",
            "is_paid": p.is_paid if p else False,
            "amount": p.amount if p else None,
            "paid_date": p.paid_date if p else "",
            "notes": p.notes if p else ""
        })

    return {
        "establishment": {"id": est.id, "code": est.code, "name": est.name},
        "financial_year": year,
        "months": grid
    }


@app.post("/api/admin/establishments/{est_id}/payments")
async def admin_save_establishment_payments(
    est_id: int,
    d: PaymentsSaveIn,
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")

    fy = d.financial_year.strip()
    for item in d.payments:
        payment = db.query(Payment).filter(
            Payment.establishment_id == est_id,
            Payment.financial_year == fy,
            Payment.month == item.month
        ).first()

        if not payment:
            payment = Payment(
                establishment_id=est_id,
                financial_year=fy,
                month=item.month,
                is_paid=item.is_paid,
                amount=item.amount,
                paid_date=item.paid_date or "",
                notes=item.notes or ""
            )
            db.add(payment)
        else:
            payment.is_paid = item.is_paid
            payment.amount = item.amount
            payment.paid_date = item.paid_date or ""
            payment.notes = item.notes or ""

    db.commit()
    paid_count = sum(1 for item in d.payments if item.is_paid)
    log_activity(
        db, admin.id, est.id, "payment_marked",
        f"Marked EPF payment compliance for {est.name} ({est.code}) — FY {fy} ({paid_count} months paid)",
        {"financial_year": fy, "paid_count": paid_count, "code": est.code}
    )
    return {"ok": True}


@app.get("/api/admin/subscription-payments")
async def admin_get_subscription_payments(
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=200),
    consultant_id: Optional[int] = Query(None),
    establishment_id: Optional[int] = Query(None),
    financial_year: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Cross-establishment, cross-consultant paid-subscription ledger -- lets the
    superadmin see, in one place, which consultant paid for which establishment, for
    which month, for how many employees, without opening each establishment individually."""
    query = db.query(SubscriptionFee).filter(SubscriptionFee.is_paid == True)

    if establishment_id:
        query = query.filter(SubscriptionFee.establishment_id == establishment_id)
    if financial_year:
        query = query.filter(SubscriptionFee.financial_year == financial_year)
    if consultant_id:
        est_ids = [e.id for e in db.query(Establishment.id).filter(Establishment.user_id == consultant_id).all()]
        query = query.filter(SubscriptionFee.establishment_id.in_(est_ids or [-1]))
    if search:
        s = f"%{search.strip().lower()}%"
        est_ids = [e.id for e in db.query(Establishment.id).filter(
            func.lower(Establishment.name).like(s) | func.lower(Establishment.code).like(s)
        ).all()]
        query = query.filter(SubscriptionFee.establishment_id.in_(est_ids or [-1]))

    total = query.count()
    total_amount = query.with_entities(func.sum(SubscriptionFee.amount_due)).scalar() or 0.0

    offset = (page - 1) * limit
    rows = query.order_by(SubscriptionFee.financial_year.desc(), SubscriptionFee.id.desc()).offset(offset).limit(limit).all()

    est_ids_needed = list({r.establishment_id for r in rows})
    ests_map = {e.id: e for e in db.query(Establishment).filter(Establishment.id.in_(est_ids_needed)).all()} if est_ids_needed else {}
    consultant_ids_needed = list({e.user_id for e in ests_map.values()})
    consultants_map = {u.id: u for u in db.query(User).filter(User.id.in_(consultant_ids_needed)).all()} if consultant_ids_needed else {}

    payments = []
    for r in rows:
        est = ests_map.get(r.establishment_id)
        if not est:
            continue
        payments.append(_subscription_payment_dict(r, est, consultants_map.get(est.user_id)))

    return {
        "payments": payments,
        "total": total,
        "total_amount": round(total_amount, 2),
        "page": page,
        "limit": limit
    }


@app.get("/api/admin/activity-log")
async def admin_get_activity_log(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user_id: Optional[int] = Query(None),
    establishment_id: Optional[int] = Query(None),
    action_type: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    query = db.query(ActivityLog)

    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    if establishment_id:
        query = query.filter(ActivityLog.establishment_id == establishment_id)
    if action_type and action_type.lower() != "all":
        query = query.filter(ActivityLog.action_type == action_type)
    if since:
        try:
            if "-" in since and len(since.split("-")[0]) == 2:
                dt_since = datetime.strptime(since, "%d-%m-%Y")
            else:
                dt_since = datetime.fromisoformat(since)
            query = query.filter(ActivityLog.timestamp >= dt_since)
        except Exception:
            pass
    if search:
        s = f"%{search.strip().lower()}%"
        query = query.filter(func.lower(ActivityLog.description).like(s))

    total = query.count()
    offset = (page - 1) * limit
    logs = query.order_by(ActivityLog.timestamp.desc(), ActivityLog.id.desc()).offset(offset).limit(limit).all()

    # Preload users and establishments
    user_ids = list({l.user_id for l in logs if l.user_id})
    est_ids = list({l.establishment_id for l in logs if l.establishment_id})
    
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
    ests_map = {e.id: e for e in db.query(Establishment).filter(Establishment.id.in_(est_ids)).all()} if est_ids else {}

    rows = []
    for l in logs:
        u = users_map.get(l.user_id)
        e = ests_map.get(l.establishment_id)
        
        meta = {}
        if l.extra_data:
            try:
                meta = json.loads(l.extra_data)
            except Exception:
                meta = {}

        rows.append({
            "id": l.id,
            "timestamp": l.timestamp.isoformat() if l.timestamp else "",
            "time_formatted": l.timestamp.strftime("%d-%m-%Y %I:%M %p") if l.timestamp else "—",
            "user_id": l.user_id,
            "user_name": u.name if u else ("System" if not l.user_id else "Unknown User"),
            "user_email": u.email if u else "",
            "user_role": u.role if u else "",
            "establishment_id": l.establishment_id,
            "establishment_name": e.name if e else ("—" if not l.establishment_id else "Unknown Establishment"),
            "establishment_code": e.code if e else "",
            "action_type": l.action_type,
            "description": l.description,
            "metadata": meta
        })

    return {
        "logs": rows,
        "total": total,
        "page": page,
        "limit": limit
    }


# ── Establishments Management (/api/establishments) ────────────────────────
@app.get("/api/establishments")
async def list_establishments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Establishment)
    if current_user.role != "superadmin":
        query = query.filter(Establishment.user_id == current_user.id)
    ests = query.order_by(Establishment.id.asc()).all()

    rows = []
    for est in ests:
        emp_count = 0
        year_count = 0
        wage_grid = []
        try:
            if est.data:
                data_dict = json.loads(est.data)
                p = Project()
                p.load_from_dict(data_dict)
                emp_count = len(p.master)
                year_count = len(p.years)
                wage_grid = build_establishment_wage_grid(p)
        except Exception:
            pass

        rows.append({
            "id": est.id,
            "user_id": est.user_id,
            "code": est.code,
            "name": est.name,
            "address": est.address or "—",
            "coverage_date": est.coverage_date or "—",
            "employee_count": emp_count,
            "year_count": year_count,
            "wage_grid": wage_grid,
            "created_at": est.created_at.strftime("%d-%m-%Y") if est.created_at else "—"
        })

    return {"establishments": rows, "total": len(rows)}


@app.post("/api/establishments")
async def create_establishment(
    d: EstablishmentIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "establishment.add")
    code = d.code.strip().upper()
    name = d.name.strip()
    if not code or not name:
        raise HTTPException(400, "Establishment Code and Name are required")

    # owner_user_id and trial_ends_on are superadmin-only levers -- silently ignored
    # (not an error) for anyone else, so a Consultant/Employer can never grant
    # themselves or someone else an establishment/trial via this same endpoint.
    owner = current_user
    if current_user.role == "superadmin" and d.owner_user_id:
        owner = db.query(User).filter(User.id == d.owner_user_id).first()
        if not owner:
            raise HTTPException(404, "Target user not found")
        if owner.role not in ("consultant", "employer"):
            raise HTTPException(400, "Establishments can only be owned by a Consultant or Employer account")

    if owner.role == "employer" and owner.max_establishments is not None:
        existing_count = db.query(Establishment).filter(Establishment.user_id == owner.id).count()
        if existing_count >= owner.max_establishments:
            raise HTTPException(403, f"{owner.name} has reached their limit of {owner.max_establishments} establishment(s). Increase their allocation first.")

    trial_ends_on_value = None
    if current_user.role == "superadmin" and d.trial_ends_on:
        try:
            trial_ends_on_value = datetime.strptime(d.trial_ends_on, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "trial_ends_on must be in YYYY-MM-DD format")

    p = Project()
    p.set_establishment(code, name, d.address.strip(), d.coverage_date.strip())

    new_est = Establishment(
        user_id=owner.id,
        code=code,
        name=name,
        address=d.address.strip(),
        coverage_date=d.coverage_date.strip(),
        custom_rate_per_employee=d.custom_rate_per_employee,
        trial_ends_on=trial_ends_on_value,
        data=json.dumps(p.to_dict(), ensure_ascii=False)
    )
    db.add(new_est)
    db.commit()
    db.refresh(new_est)

    log_activity(
        db, current_user.id, new_est.id, "establishment_created",
        f"Added establishment {new_est.code} — {new_est.name}" + (f" (on behalf of {owner.name})" if owner.id != current_user.id else ""),
        {"code": new_est.code, "name": new_est.name, "coverage_date": new_est.coverage_date, "custom_rate": new_est.custom_rate_per_employee, "owner_user_id": owner.id}
    )
    if trial_ends_on_value:
        log_activity(
            db, current_user.id, new_est.id, "trial_started",
            f"Started free trial for {new_est.name} ({new_est.code}) until {trial_ends_on_value.strftime('%d-%m-%Y')}",
            {"old_trial_ends_on": None, "new_trial_ends_on": trial_ends_on_value.isoformat()}
        )

    return {
        "ok": True,
        "establishment": {
            "id": new_est.id,
            "code": new_est.code,
            "name": new_est.name,
            "address": new_est.address,
            "coverage_date": new_est.coverage_date,
            "custom_rate_per_employee": new_est.custom_rate_per_employee,
            "trial_ends_on": trial_ends_on_value.isoformat() if trial_ends_on_value else None
        }
    }


@app.delete("/api/establishments/{est_id}")
async def delete_establishment(
    est_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "establishment.delete")
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found")
    if current_user.role != "superadmin" and est.user_id != current_user.id:
        raise HTTPException(403, "Access denied")

    db.delete(est)
    db.commit()
    return {"ok": True}


# ── Establishment Details (Scoped to Active Establishment) ────────────────
def _is_valid_for_establishment(member_id: str, est_code: str) -> bool:
    if not est_code or not member_id or member_id.startswith('__UAN__'):
        return True
    est_clean = "".join(c for c in est_code if c.isalnum())[:15].upper()
    if not est_clean:
        return True
    if len(member_id) >= len(est_clean):
        return member_id.upper().startswith(est_clean)
    return True

def _is_valid_uan(uan) -> bool:
    if not uan:
        return False
    uan_str = str(uan).strip()
    return len(uan_str) == 12 and uan_str.isdigit()

def compute_remittance_row(yr, est, month_idx, wages_total, ee_total, er_total, a10_total, members):
    remit_list = getattr(yr, 'remittances', [])
    saved_remit = None
    for r in remit_list:
        if isinstance(r, dict) and r.get("month_label") == MONTHS[month_idx]:
            saved_remit = r
            break
            
    trrn = saved_remit.get("trrn", "") if saved_remit else ""
    crrn = saved_remit.get("crrn", "") if saved_remit else ""
    credit_date = saved_remit.get("credit_date", "") if saved_remit else ""
    
    cal_year = calendar_year_for_month(MONTHS[month_idx], yr.year_from, yr.year_to)
    m_num = get_month_num(MONTHS[month_idx])
    
    a2_rate = account2_rate_percent(cal_year, m_num)
    a22_rate = account22_rate_percent(cal_year, m_num)
    
    acc_01 = ee_total + (er_total - a10_total)
    a2_amt = round(wages_total * a2_rate / 100) if wages_total > 0 else 0
    a21_amt = round(wages_total * ACCOUNT_21_RATE / 100) if wages_total > 0 else 0
    a22_amt = (max(round(wages_total * a22_rate / 100), ACCOUNT_22_MIN)
               if (a22_rate > 0 and wages_total > 0) else 0)
    
    return {
        "month_label": MONTHS[month_idx],
        "trrn": trrn,
        "crrn": crrn,
        "credit_date": credit_date,
        "members": members,
        "acc_01": acc_01,
        "acc_02": a2_amt,
        "acc_10": a10_total,
        "acc_21": a21_amt,
        "acc_22": a22_amt
    }


# ── Dashboard ─────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
async def dashboard(
    branch_id: Optional[int] = None,
    division_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    scoped = branch_id is not None or division_id is not None or unit_id is not None
    year_stats = []
    total_w = total_c = 0
    for yk in project.year_keys_sorted():
        yr = project.years[yk]
        est = project.build_establishment_for_year(yk)
        emps = project.build_employees_for_year(yk)
        if scoped:
            emps = filter_employees_by_scope(emps, branch_id=branch_id, division_id=division_id, unit_id=unit_id)

        monthly_stats = []
        year_from_int = int(yr.year_from)
        yw = ywt = yet = 0
        
        for i in range(12):
            m_emp_count = 0
            m_gross = 0
            m_epf_wage = 0
            m_eps_wage = 0
            m_worker = 0
            m_employer = 0
            m_ee_epf = 0
            m_er_epf = 0
            m_er_eps = 0
            
            for emp in emps:
                wages = emp.wages[i] if emp.wages and len(emp.wages) > i else 0
                gross = emp.gross_wages[i] if emp.gross_wages and len(emp.gross_wages) > i else 0
                
                mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                                     est.employer_epf_rate, est.employer_eps_rate,
                                     wage_ceilings=get_wage_ceilings_for_year(yr.year_from))
                
                _, w_epf, w_eps, w_tot, e_epf, e_eps, e_tot = mrows[i]
                
                ceiling = get_wage_ceilings_for_year(yr.year_from)[i]
                if est.worker_eps_rate == 0:
                    eps_wage = 0 if emp.age_crosses_58 else min(wages, ceiling)
                else:
                    eps_wage = wages
                    
                if wages > 0 or gross > 0:
                    m_emp_count += 1
                    m_gross += gross
                    m_epf_wage += wages
                    m_eps_wage += eps_wage
                    m_worker += w_tot
                    m_employer += e_tot
                    m_ee_epf += w_epf
                    m_er_epf += e_epf
                    m_er_eps += e_eps
            
            yw += m_epf_wage
            ywt += m_worker
            yet += m_employer
            
            remit_row = compute_remittance_row(
                yr, est, i,
                wages_total=m_epf_wage,
                ee_total=m_ee_epf,
                er_total=(m_er_epf + m_er_eps),
                a10_total=m_er_eps,
                members=m_emp_count
            )
            
            cal_yr = year_from_int if i < 10 else year_from_int + 1
            month_total = remit_row["acc_01"] + remit_row["acc_02"] + remit_row["acc_10"] + remit_row["acc_21"] + remit_row["acc_22"]
            
            monthly_stats.append({
                "month_idx": i,
                "month": f"{MONTHS[i]} {cal_yr}",
                "employees": m_emp_count,
                "gross_wages": m_gross,
                "epf_wages": m_epf_wage,
                "eps_wages": m_eps_wage,
                "worker_share": m_worker,
                "employer_share": m_employer,
                "total": m_worker + m_employer,
                "trrn": remit_row["trrn"],
                "crrn": remit_row["crrn"],
                "credit_date": remit_row["credit_date"],
                "acc_01": remit_row["acc_01"],
                "acc_02": remit_row["acc_02"],
                "acc_10": remit_row["acc_10"],
                "acc_21": remit_row["acc_21"],
                "acc_22": remit_row["acc_22"],
                "remit_total": month_total
            })

        total_w += yw
        total_c += (ywt + yet)
        
        tot_acc_01 = sum(m["acc_01"] for m in monthly_stats)
        tot_acc_02 = sum(m["acc_02"] for m in monthly_stats)
        tot_acc_10 = sum(m["acc_10"] for m in monthly_stats)
        tot_acc_21 = sum(m["acc_21"] for m in monthly_stats)
        tot_acc_22 = sum(m["acc_22"] for m in monthly_stats)
        tot_remit_total = sum(m["remit_total"] for m in monthly_stats)
        
        year_stats.append({
            "key": yk, "label": yr.long_label, "scheme": yr.scheme,
            "epf_wages": yw, "worker_total": ywt, "employer_total": yet,
            "total_contributions": ywt + yet,
            "monthly_stats": monthly_stats,
            "totals": {
                "gross_wages": sum(m["gross_wages"] for m in monthly_stats),
                "epf_wages": yw,
                "eps_wages": sum(m["eps_wages"] for m in monthly_stats),
                "worker_share": ywt,
                "employer_share": yet,
                "total": ywt + yet,
                "acc_01": tot_acc_01,
                "acc_02": tot_acc_02,
                "acc_10": tot_acc_10,
                "acc_21": tot_acc_21,
                "acc_22": tot_acc_22,
                "remit_total": tot_remit_total
            }
        })

    grand_remit_total = sum(y["totals"]["remit_total"] for y in year_stats)
    if scoped:
        emp_count = len(filter_employees_by_scope(project.master_list(), branch_id=branch_id, division_id=division_id, unit_id=unit_id))
    else:
        emp_count = len(project.master)
    return {
        "establishment": {"id": est_obj.id, "code": project.code, "name": project.name, "address": project.address},
        "employees": emp_count,
        "years": len(project.years),
        "total_wages": total_w,
        "total_contributions": total_c,
        "grand_remit_total": grand_remit_total,
        "year_stats": year_stats,
    }


@app.get("/api/dashboard/month_employees/{key}/{month_index}")
async def dashboard_month_employees(
    key: str,
    month_index: int,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
        
    yr = project.years[key]
    est = project.build_establishment_for_year(key)
    emps = project.build_employees_for_year(key)
    
    if month_index < 0 or month_index > 11:
        raise HTTPException(400, "Invalid month index")
        
    results = []
    for emp in emps:
        wages = emp.wages[month_index] if emp.wages and len(emp.wages) > month_index else 0
        gross = emp.gross_wages[month_index] if emp.gross_wages and len(emp.gross_wages) > month_index else 0
        
        if wages > 0 or gross > 0:
            mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                                 est.employer_epf_rate, est.employer_eps_rate,
                                 wage_ceilings=get_wage_ceilings_for_year(yr.year_from))
            
            _, w_epf, w_eps, w_tot, e_epf, e_eps, e_tot = mrows[month_index]
            
            ceiling = get_wage_ceilings_for_year(yr.year_from)[month_index]
            eps_wage = (0 if emp.age_crosses_58 else min(wages, ceiling)) if est.worker_eps_rate == 0 else wages
                
            results.append({
                "uan": emp.uan,
                "name": emp.name,
                "gross_wages": gross,
                "epf_wages": wages,
                "eps_wages": eps_wage,
                "worker_share": w_tot,
                "employer_share": e_tot,
                "employer_pf": e_epf,
                "employer_eps": e_eps
            })
            
    return {
        "employees": results,
        "establishment": {
            "name": project.name,
            "code": project.code
        }
    }


# ── Establishment Endpoints ───────────────────────────────────────────────
@app.get("/api/establishment")
async def get_est(active: Tuple[Establishment, Project] = Depends(get_active_establishment)):
    est_obj, project = active
    return {
        "id": est_obj.id,
        "code": project.code,
        "name": project.name,
        "address": project.address,
        "coverage_date": project.coverage_date,
        "custom_rate_per_employee": est_obj.custom_rate_per_employee
    }


@app.put("/api/establishment")
async def put_est(
    d: EstablishmentIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "establishment.edit")
    est_obj, project = active
    project.set_establishment(d.code, d.name, d.address, d.coverage_date)

    old_rate = est_obj.custom_rate_per_employee
    if d.custom_rate_per_employee is not None:
        est_obj.custom_rate_per_employee = d.custom_rate_per_employee if d.custom_rate_per_employee > 0 else None
        if old_rate != est_obj.custom_rate_per_employee:
            log_activity(
                db, current_user.id, est_obj.id, "rate_changed",
                f"Updated establishment {project.name} rate override to ₹{est_obj.custom_rate_per_employee if est_obj.custom_rate_per_employee else 'Default'}/emp",
                {"establishment_id": est_obj.id, "old_rate": old_rate, "new_rate": est_obj.custom_rate_per_employee, "scope": "establishment"}
            )

    save_establishment_project(db, est_obj, project)
    return {"ok": True}


@app.get("/api/establishment/subscription-status")
async def get_establishment_subscription_status(
    year: str = Query("2026-27"),
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    unpaid = get_unpaid_months_for_year(db, est_obj, project, year)
    return {
        "financial_year": year,
        "has_overdue": len(unpaid) > 0,
        "unpaid_months": unpaid,
        "total_overdue": len(unpaid),
        "is_in_trial": is_establishment_in_trial(est_obj),
        "trial_ends_on": est_obj.trial_ends_on.isoformat() if est_obj.trial_ends_on else None,
        "trial_days_left": get_trial_days_left(est_obj),
        "billing_mode": est_obj.billing_mode or "per_employee",
        "flat_fee_amount": est_obj.flat_fee_amount
    }


def _billing_display(mode: str, rate_applied: Optional[float], amount_due: float) -> str:
    if mode == "flat_fee":
        return f"₹{amount_due}/month flat rate"
    return f"₹{rate_applied}/employee" if rate_applied is not None else "Default rate"


def _subscription_payment_dict(f: SubscriptionFee, est: Establishment, consultant: Optional[User] = None) -> dict:
    """Shared row shape for both the consultant's own Subscription History page and the
    superadmin's cross-establishment Subscription Payments tab."""
    if f.payment_reference == "Applied from advance credit":
        source = "advance_credit"
    elif f.cashfree_order_id:
        source = "cashfree"
    else:
        source = "manual"

    yf = f.financial_year.split("-")[0]
    yt = str(int(yf) + 1)
    cal_yr = calendar_year_for_month(f.month, yf, yt)
    display_name = f"{MONTH_FULL.get(f.month.upper(), f.month)} {cal_yr}"
    row_mode = f.billing_mode or "per_employee"

    return {
        "id": f.id,
        "establishment_id": est.id,
        "establishment_code": est.code,
        "establishment_name": est.name,
        "consultant_name": consultant.name if consultant else "",
        "consultant_email": consultant.email if consultant else "",
        "financial_year": f.financial_year,
        "month": f.month,
        "display_name": display_name,
        "employee_count": f.employee_count,
        "rate_applied": f.rate_applied,
        "amount_due": f.amount_due,
        "billing_mode": row_mode,
        "billing_display": _billing_display(row_mode, f.rate_applied, f.amount_due),
        "paid_date": f.paid_date or "",
        "payment_reference": f.payment_reference or "",
        "cashfree_order_id": f.cashfree_order_id or "",
        "notes": f.notes or "",
        "source": source,
        # UPI payment path fields
        "payment_status": f.payment_status or "unpaid",
        "submitted_utr": f.submitted_utr or "",
        "submitted_by": f.submitted_by,
        "submitted_at": f.submitted_at.isoformat() if f.submitted_at else "",
        "verified_by": f.verified_by,
        "verified_at": f.verified_at.isoformat() if f.verified_at else "",
        "rejection_reason": f.rejection_reason or "",
    }


@app.get("/api/establishment/subscription-payments")
async def get_establishment_subscription_payments(
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Paid subscription-fee history for the caller's own active establishment, across
    every financial year -- powers the consultant-facing Subscription History page."""
    est_obj, project = active
    consultant = db.query(User).filter(User.id == est_obj.user_id).first()

    rows = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_obj.id,
        SubscriptionFee.is_paid == True
    ).order_by(SubscriptionFee.financial_year.desc(), SubscriptionFee.id.desc()).all()

    payments = [_subscription_payment_dict(f, est_obj, consultant) for f in rows]
    total_paid = round(sum(p["amount_due"] for p in payments), 2)

    # Advance-credit top-ups are a distinct kind of "payment towards subscription" --
    # money paid in before any month existed to bill against -- shown as their own
    # section so it's clear which rupees came in as a lump sum vs. a specific month's fee.
    topup_rows = db.query(AdvanceCreditLedger).filter(
        AdvanceCreditLedger.establishment_id == est_obj.id,
        AdvanceCreditLedger.entry_type == "topup",
        AdvanceCreditLedger.status.in_(["confirmed", "manual"])
    ).order_by(AdvanceCreditLedger.created_at.desc(), AdvanceCreditLedger.id.desc()).all()

    advance_topups = [{
        "id": t.id,
        "amount": t.amount,
        "date": t.created_at.strftime("%d-%m-%Y") if t.created_at else "",
        "time_formatted": t.created_at.strftime("%d-%m-%Y %I:%M %p") if t.created_at else "",
        "payment_reference": t.payment_reference or "",
        "cashfree_order_id": t.cashfree_order_id or "",
        "notes": t.notes or "",
        "source": "cashfree" if t.status == "confirmed" else "manual",
    } for t in topup_rows]
    total_topped_up = round(sum(t["amount"] for t in advance_topups), 2)

    return {
        "establishment": {"id": est_obj.id, "code": est_obj.code, "name": est_obj.name},
        "payments": payments,
        "total_paid": total_paid,
        "count": len(payments),
        "advance_topups": advance_topups,
        "total_topped_up": total_topped_up,
        "advance_credit_balance": est_obj.advance_credit_balance or 0.0
    }


@app.get("/api/establishment/subscription-fees/month-detail")
async def get_establishment_fee_month_detail(
    year: str = Query(...),
    month: str = Query(...),
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Per-month fee detail (members, rate, amount due) for the caller's own active
    establishment -- powers the download-blocked screen's 'here's what's owed' view."""
    est_obj, project = active
    sync_subscription_fees_for_year(db, est_obj, project, year)

    fee_row = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_obj.id,
        SubscriptionFee.financial_year == year,
        SubscriptionFee.month == month
    ).first()
    if not fee_row:
        raise HTTPException(404, "No fee record for this month")

    month_idx = MONTH_SHORT_NAMES.index(month) if month in MONTH_SHORT_NAMES else -1
    overdue = is_month_overdue(year, month_idx) if month_idx >= 0 else False
    year_record = project.years.get(year)
    cal_yr = calendar_year_for_month(month, year_record.year_from, year_record.year_to) if year_record else ""
    display_name = f"{MONTH_FULL.get(month.upper(), month)} {cal_yr}".strip()

    row_mode = fee_row.billing_mode or "per_employee"
    return {
        "fee_id": fee_row.id,
        "month": fee_row.month,
        "financial_year": fee_row.financial_year,
        "display_name": display_name,
        "employee_count": fee_row.employee_count,
        "rate_applied": fee_row.rate_applied,
        "amount_due": fee_row.amount_due,
        "billing_mode": row_mode,
        "billing_display": _billing_display(row_mode, fee_row.rate_applied, fee_row.amount_due),
        "is_paid": fee_row.is_paid,
        "is_overdue": overdue and not fee_row.is_paid,
        "payment_status": fee_row.payment_status or "unpaid",
        "submitted_utr": fee_row.submitted_utr or "",
        "rejection_reason": fee_row.rejection_reason or "",
    }


@app.post("/api/establishment/subscription-fees/create-link")
async def establishment_create_fee_link(
    d: CreateFeeLinkIn,
    request: Request,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Consultant self-serve version of the superadmin per-month payment-link endpoint,
    scoped to the caller's own active establishment."""
    require_feature_enabled(db, "cashfree_payments_enabled", "Cashfree payments")
    est_obj, project = active
    fee_row = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_obj.id,
        SubscriptionFee.financial_year == d.financial_year,
        SubscriptionFee.month == d.month
    ).first()
    if not fee_row:
        raise HTTPException(404, "Subscription fee row not found for this month.")

    return_url = f"{_app_base_url(request)}/?cf_payment_return=1&type=sub&year={fee_row.financial_year}&month={fee_row.month}&est_id={est_obj.id}"
    return _create_fee_payment_link(db, est_obj, fee_row, return_url=return_url)


@app.post("/api/establishment/subscription-fees/refresh-status")
async def establishment_refresh_fee_status(
    d: CreateFeeLinkIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Consultant self-serve version of the superadmin per-month status-refresh endpoint."""
    est_obj, project = active
    fee_row = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_obj.id,
        SubscriptionFee.financial_year == d.financial_year,
        SubscriptionFee.month == d.month
    ).first()
    if not fee_row:
        raise HTTPException(404, "Subscription fee row not found")
    if fee_row.is_paid or not fee_row.cashfree_order_id:
        return {"ok": True, "is_paid": fee_row.is_paid}

    try:
        status_resp = cashfree_client.get_payment_link_status(fee_row.cashfree_order_id)
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree status check failed: {e.response.text if e.response is not None else str(e)}")

    if status_resp.get("link_status") == "PAID":
        _confirm_subscription_fee_paid(db, fee_row, payment_ref=str(status_resp.get("cf_link_id") or fee_row.cashfree_order_id))

    return {"ok": True, "is_paid": fee_row.is_paid}


def _load_batch_fee_rows(db: Session, est_id: int, fee_ids: List[int]) -> List[SubscriptionFee]:
    """Shared loader for the 'pay all overdue' endpoints -- loads and validates the
    SubscriptionFee rows a batch payment covers, scoped to one establishment."""
    if not fee_ids:
        raise HTTPException(400, "No fee_ids provided")
    fee_rows = db.query(SubscriptionFee).filter(
        SubscriptionFee.id.in_(fee_ids),
        SubscriptionFee.establishment_id == est_id,
    ).all()
    if len(fee_rows) != len(set(fee_ids)):
        raise HTTPException(404, "One or more subscription fee rows were not found for this establishment.")
    unpaid_rows = [f for f in fee_rows if not f.is_paid]
    if not unpaid_rows:
        raise HTTPException(400, "All selected months are already paid.")
    return unpaid_rows


@app.post("/api/establishment/subscription-fees/pay-all/create-link")
async def establishment_pay_all_overdue_create_link(
    d: PayAllOverdueIn,
    request: Request,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Creates ONE Cashfree Payment Link for the combined total of several unpaid/overdue
    SubscriptionFee rows -- the 'pay all overdue in one shot' path. Reuses the exact same
    cashfree_order_id column each row already has (writing the same order_id across every
    covered row) so the existing webhook/refresh-status code just needs .first() -> .all()
    to confirm every covered month, instead of introducing a new linking table."""
    require_feature_enabled(db, "cashfree_payments_enabled", "Cashfree payments")
    est_obj, project = active
    fee_rows = _load_batch_fee_rows(db, est_obj.id, d.fee_ids)

    total_due = round(sum(f.amount_due for f in fee_rows), 2)
    if total_due <= 0:
        raise HTTPException(400, "No fee due for the selected months.")

    consultant = db.query(User).filter(User.id == est_obj.user_id).first()
    phone = (consultant.mobile or "").strip() if consultant else ""
    if not phone:
        raise HTTPException(400, "Consultant has no mobile number on file — required by Cashfree to generate a payment link.")

    order_id = cashfree_client.new_order_id("sub", f"batch{est_obj.id}")
    months_str = ", ".join(f"{f.month} {f.financial_year}" for f in fee_rows)
    return_url = f"{_app_base_url(request)}/?cf_payment_return=1&type=sub_batch&est_id={est_obj.id}"
    try:
        link_resp = cashfree_client.create_payment_link(
            link_id=order_id,
            amount=total_due,
            purpose=f"Software subscription fee — {len(fee_rows)} month(s) ({months_str}) — {est_obj.name} ({est_obj.code})",
            customer_phone=phone,
            customer_name=consultant.name if consultant else "",
            customer_email=consultant.email if consultant else "",
            return_url=return_url,
        )
    except cashfree_client.CashfreeConfigError as e:
        raise HTTPException(500, str(e))
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree link creation failed: {e.response.text if e.response is not None else str(e)}")

    for f in fee_rows:
        f.cashfree_order_id = order_id
        f.cashfree_payment_link_url = link_resp.get("link_url")
    db.commit()

    return {"ok": True, "link_url": link_resp.get("link_url"), "order_id": order_id, "total_due": total_due}


@app.post("/api/establishment/subscription-fees/pay-all/refresh-status")
async def establishment_pay_all_overdue_refresh_status(
    d: RefreshBatchStatusIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Polls payment status for a batch of fee rows. Checks DB state first (covers both a
    webhook that already landed AND a superadmin manual-UTR approval, either of which flips
    is_paid directly) before falling back to a live Cashfree status check."""
    est_obj, project = active
    fee_rows = db.query(SubscriptionFee).filter(
        SubscriptionFee.id.in_(d.fee_ids),
        SubscriptionFee.establishment_id == est_obj.id,
    ).all()
    if not fee_rows:
        raise HTTPException(404, "Subscription fee rows not found")

    if all(f.is_paid for f in fee_rows):
        return {"ok": True, "is_paid": True}

    order_id = next((f.cashfree_order_id for f in fee_rows if f.cashfree_order_id), None)
    if not order_id:
        return {"ok": True, "is_paid": False}

    try:
        status_resp = cashfree_client.get_payment_link_status(order_id)
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree status check failed: {e.response.text if e.response is not None else str(e)}")

    if status_resp.get("link_status") == "PAID":
        payment_ref = str(status_resp.get("cf_link_id") or order_id)
        for f in fee_rows:
            if f.cashfree_order_id == order_id:
                _confirm_subscription_fee_paid(db, f, payment_ref=payment_ref, source="cashfree")

    return {"ok": True, "is_paid": all(f.is_paid for f in fee_rows)}


@app.post("/api/establishment/subscription-fees/pay-all/submit-utr")
async def establishment_pay_all_overdue_submit_utr(
    d: BatchSubmitUTRIn,
    current_user: User = Depends(get_current_user),
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Manual UPI/QR path for 'pay all overdue in one shot' -- submits the SAME utr across
    every covered SubscriptionFee row, so approve_payment's sibling-cascade logic marks
    them all paid together once a superadmin approves any one of them."""
    est_obj, project = active
    fee_rows = _load_batch_fee_rows(db, est_obj.id, d.fee_ids)

    utr = d.utr.strip()
    if not utr:
        raise HTTPException(400, "UTR cannot be empty")
    if _utr_already_submitted(db, utr):
        raise HTTPException(400, "This UTR has already been submitted for verification.")

    now = datetime.now(timezone.utc)
    for f in fee_rows:
        f.payment_status = "pending_verification"
        f.submitted_utr = utr
        f.submitted_by = current_user.id
        f.submitted_at = now
        f.rejection_reason = None
    db.commit()

    months_str = ", ".join(f"{f.month} {f.financial_year}" for f in fee_rows)
    log_activity(
        db, current_user.id, est_obj.id, "utr_submitted",
        f"UTR submitted for {len(fee_rows)} month(s) ({months_str}) — {est_obj.name} ({est_obj.code}): {utr}",
        {"months": months_str, "utr": utr, "fee_ids": [f.id for f in fee_rows]}
    )

    return {"ok": True, "payment_status": "pending_verification"}


@app.post("/api/establishment/advance-payment/create-link")
async def consultant_create_advance_payment_link(
    d: AdvancePaymentIn,
    request: Request,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Self-serve advance-credit top-up -- lets a consultant generate their own Cashfree
    link for their active establishment, without waiting on the superadmin."""
    require_feature_enabled(db, "cashfree_payments_enabled", "Cashfree payments")
    require_feature_enabled(db, "advance_credit_enabled", "Advance credit")
    est_obj, project = active
    if d.amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    phone = (current_user.mobile or "").strip()
    if not phone:
        raise HTTPException(400, "Add a mobile number to your account to generate a Cashfree payment link.")

    order_id = cashfree_client.new_order_id("adv", est_obj.id)
    return_url = f"{_app_base_url(request)}/?cf_payment_return=1&type=adv&est_id={est_obj.id}&order_id={order_id}"
    try:
        link_resp = cashfree_client.create_payment_link(
            link_id=order_id,
            amount=d.amount,
            purpose=f"Advance subscription credit — {est_obj.name} ({est_obj.code})",
            customer_phone=phone,
            customer_name=current_user.name,
            customer_email=current_user.email,
            return_url=return_url,
        )
    except cashfree_client.CashfreeConfigError as e:
        raise HTTPException(500, str(e))
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree link creation failed: {e.response.text if e.response is not None else str(e)}")

    db.add(AdvanceCreditLedger(
        establishment_id=est_obj.id, entry_type="topup", amount=d.amount,
        cashfree_order_id=order_id, cashfree_payment_link_url=link_resp.get("link_url"),
        notes=d.notes or None, status="pending"
    ))
    db.commit()

    return {"ok": True, "link_url": link_resp.get("link_url"), "order_id": order_id}


class AdvanceCreditRefreshIn(BaseModel):
    order_id: str


@app.post("/api/establishment/advance-credit/refresh-status")
async def establishment_refresh_advance_credit_status(
    d: AdvanceCreditRefreshIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    """Consultant self-serve version of the superadmin advance-credit status-refresh
    endpoint -- looked up by order_id (known from the Cashfree return_url) rather than
    ledger_id, since the browser has no in-memory state after the redirect back."""
    est_obj, project = active
    ledger_row = db.query(AdvanceCreditLedger).filter(
        AdvanceCreditLedger.cashfree_order_id == d.order_id,
        AdvanceCreditLedger.establishment_id == est_obj.id
    ).first()
    if not ledger_row:
        raise HTTPException(404, "Advance credit payment not found")
    if ledger_row.status != "pending":
        return {"ok": True, "status": ledger_row.status, "amount": ledger_row.amount, "advance_credit_balance": est_obj.advance_credit_balance}

    try:
        status_resp = cashfree_client.get_payment_link_status(ledger_row.cashfree_order_id)
    except requests.HTTPError as e:
        raise HTTPException(502, f"Cashfree status check failed: {e.response.text if e.response is not None else str(e)}")

    if status_resp.get("link_status") == "PAID":
        _confirm_advance_credit_ledger_row(db, ledger_row, payment_ref=str(status_resp.get("cf_link_id") or ledger_row.cashfree_order_id))

    return {"ok": True, "status": ledger_row.status, "amount": ledger_row.amount, "advance_credit_balance": est_obj.advance_credit_balance}


@app.post("/api/establishment/advance-payment/submit-utr")
async def consultant_submit_advance_utr(
    d: AdvanceSubmitUTRIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manual-UPI/QR alternative to the Cashfree advance-credit top-up above -- the
    consultant pays via the establishment's UPI QR code directly and submits the UTR for
    superadmin verification, same flow as the per-month subscription-fee UTR path."""
    require_feature_enabled(db, "advance_credit_enabled", "Advance credit")
    est_obj, project = active
    if d.amount <= 0:
        raise HTTPException(400, "Amount must be positive")

    utr = d.utr.strip()
    if not utr:
        raise HTTPException(400, "UTR cannot be empty")

    if _utr_already_submitted(db, utr):
        raise HTTPException(400, "This UTR has already been submitted for verification.")

    ledger_row = AdvanceCreditLedger(
        establishment_id=est_obj.id, entry_type="topup", amount=d.amount,
        status="pending_verification", submitted_utr=utr,
        submitted_by=current_user.id, submitted_at=datetime.now(timezone.utc),
    )
    db.add(ledger_row)
    db.commit()
    db.refresh(ledger_row)

    log_activity(
        db, current_user.id, est_obj.id, "utr_submitted",
        f"Submitted UTR for advance-credit top-up of ₹{d.amount} — {est_obj.name} ({est_obj.code}): {utr}",
        {"amount": d.amount, "utr": utr}
    )

    return {"ok": True, "status": "pending_verification", "ledger_id": ledger_row.id}


# ── Org Structure Endpoints ───────────────────────────────────────────────
@app.get("/api/org-structure")
async def get_org_structure(active: Tuple[Establishment, Project] = Depends(get_active_establishment)):
    est_obj, project = active
    counts = {"branch": {}, "division": {}, "unit": {}}
    for m in project.master_list():
        if m.branch_id is not None:
            counts["branch"][m.branch_id] = counts["branch"].get(m.branch_id, 0) + 1
        if m.division_id is not None:
            counts["division"][m.division_id] = counts["division"].get(m.division_id, 0) + 1
        if m.unit_id is not None:
            counts["unit"][m.unit_id] = counts["unit"].get(m.unit_id, 0) + 1
    return {
        "branches": [dict(b.to_dict(), employee_count=counts["branch"].get(b.id, 0)) for b in project.branches],
        "divisions": [dict(d.to_dict(), employee_count=counts["division"].get(d.id, 0)) for d in project.divisions],
        "units": [dict(u.to_dict(), employee_count=counts["unit"].get(u.id, 0)) for u in project.units],
        "migration_warnings": project.org_migration_warnings,
    }

@app.post("/api/org-structure/migration-warnings/dismiss")
async def dismiss_migration_warnings(
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    project.org_migration_warnings = []
    save_establishment_project(db, est_obj, project)
    return {"ok": True}

@app.post("/api/org-structure/branches")
async def add_branch(
    d: BranchIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Branch name cannot be empty")
    project.add_branch(name)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "branches": [b.to_dict() for b in project.branches]}

@app.put("/api/org-structure/branches/{branch_id}")
async def rename_branch(
    branch_id: int,
    d: RenameIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Branch name cannot be empty")
    if not project.get_branch(branch_id):
        raise HTTPException(404, "Branch not found")
    project.rename_branch(branch_id, name)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "branches": [b.to_dict() for b in project.branches]}

@app.delete("/api/org-structure/branches/{branch_id}")
async def delete_branch(
    branch_id: int,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if not project.get_branch(branch_id):
        raise HTTPException(404, "Branch not found")
    if len(project.branches) <= 1:
        raise HTTPException(400, "Cannot delete the only remaining branch -- an establishment must always have at least one branch")
    affected = [m for m in project.master_list() if m.branch_id == branch_id]
    if affected:
        raise HTTPException(400, f"Cannot delete this branch because it is assigned to {len(affected)} employee(s)")
    child_divisions = [d for d in project.divisions if d.branch_id == branch_id]
    if child_divisions:
        raise HTTPException(400, f"Cannot delete this branch because it has {len(child_divisions)} division(s) under it")
    project.remove_branch(branch_id)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "branches": [b.to_dict() for b in project.branches]}

@app.post("/api/org-structure/divisions")
async def add_division(
    d: DivisionIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Division name cannot be empty")
    try:
        project.add_division(d.branch_id, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "divisions": [d.to_dict() for d in project.divisions]}

@app.put("/api/org-structure/divisions/{division_id}")
async def rename_division(
    division_id: int,
    d: RenameIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Division name cannot be empty")
    if not project.get_division(division_id):
        raise HTTPException(404, "Division not found")
    project.rename_division(division_id, name)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "divisions": [d.to_dict() for d in project.divisions]}

@app.delete("/api/org-structure/divisions/{division_id}")
async def delete_division(
    division_id: int,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if not project.get_division(division_id):
        raise HTTPException(404, "Division not found")
    affected = [m for m in project.master_list() if m.division_id == division_id]
    if affected:
        raise HTTPException(400, f"Cannot delete this division because it is assigned to {len(affected)} employee(s)")
    child_units = [u for u in project.units if u.division_id == division_id]
    if child_units:
        raise HTTPException(400, f"Cannot delete this division because it has {len(child_units)} unit(s) under it")
    project.remove_division(division_id)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "divisions": [d.to_dict() for d in project.divisions]}

@app.post("/api/org-structure/units")
async def add_unit(
    d: UnitIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Unit name cannot be empty")
    try:
        project.add_unit(d.division_id, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "units": [u.to_dict() for u in project.units]}

@app.put("/api/org-structure/units/{unit_id}")
async def rename_unit(
    unit_id: int,
    d: RenameIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Unit name cannot be empty")
    if not project.get_unit(unit_id):
        raise HTTPException(404, "Unit not found")
    project.rename_unit(unit_id, name)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "units": [u.to_dict() for u in project.units]}

@app.delete("/api/org-structure/units/{unit_id}")
async def delete_unit(
    unit_id: int,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if not project.get_unit(unit_id):
        raise HTTPException(404, "Unit not found")
    affected = [m for m in project.master_list() if m.unit_id == unit_id]
    if affected:
        raise HTTPException(400, f"Cannot delete this unit because it is assigned to {len(affected)} employee(s)")
    project.remove_unit(unit_id)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "units": [u.to_dict() for u in project.units]}


# ── Employees Endpoints ───────────────────────────────────────────────────
@app.get("/api/employees")
async def list_employees(active: Tuple[Establishment, Project] = Depends(get_active_establishment)):
    est_obj, project = active
    rows = []
    for m in project.master_list():
        age = calc_age_years(m.dob)
        rows.append({
            "member_id": m.member_id, "name": m.name,
            "father_name": m.father_name, "uan": m.uan,
            "dob": m.dob, "sex": m.sex, "doj": m.doj, "doe": m.doe,
            "reason_leaving": m.reason_leaving,
            "serial_no": m.serial_no, "age": age,
            "superannuation": age is not None and age >= SUPERANNUATION_AGE,
            "higher_epf_ee": m.higher_epf_ee,
            "higher_epf_er": m.higher_epf_er,
            "branch_id": m.branch_id,
            "division_id": m.division_id,
            "unit_id": m.unit_id,
            "scope_path": resolve_employee_scope_path(m, project),
        })
    return {"employees": rows, "total": len(rows)}


@app.post("/api/employees")
async def add_employee(
    d: EmployeeIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "employee.add")
    est_obj, project = active
    if project.get_master(d.member_id):
        raise HTTPException(400, f"Account {d.member_id} already exists")
    try:
        project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                              d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                              d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                              d.bank_account, d.ifsc, d.higher_epf_ee, d.higher_epf_er,
                              d.branch_id, d.division_id, d.unit_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    save_establishment_project(db, est_obj, project)
    log_activity(
        db, est_obj.user_id, est_obj.id, "employee_added",
        f"Added employee {d.name} (UAN: {d.uan or '—'}, Member ID: {d.member_id}) to {project.name}",
        {"member_id": d.member_id, "name": d.name, "uan": d.uan, "establishment_name": project.name}
    )
    return {"ok": True}


@app.put("/api/employees/{acc:path}")
async def edit_employee(
    acc: str,
    d: EmployeeIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "employee.edit")
    est_obj, project = active
    if d.member_id != acc:
        if project.get_master(d.member_id):
            raise HTTPException(400, f"Account {d.member_id} already exists")
        project.rename_account(acc, d.member_id)
    try:
        project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                              d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                              d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                              d.bank_account, d.ifsc, d.higher_epf_ee, d.higher_epf_er,
                              d.branch_id, d.division_id, d.unit_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


@app.delete("/api/employees/{acc:path}")
async def del_employee(
    acc: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "employee.delete")
    est_obj, project = active
    if not project.get_master(acc):
        raise HTTPException(404, "Not found")
    project.remove_master(acc)
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


# ── Years Endpoints ───────────────────────────────────────────────────────
def get_year_deletion_blockers(project: Project, est_obj: Establishment, key: str, db: Session) -> List[str]:
    """Real-data checks that must block a year from being deleted -- run for every
    caller including superadmins (see /force for the deliberate, separately-gated
    escape hatch). Note: this codebase does not track ECR/report download history
    anywhere (no such table or activity_log action exists), so those two checks
    from the original spec are not implemented -- flagging rather than fabricating
    a signal that isn't actually there."""
    yr = project.years.get(key)
    if not yr:
        return []
    blockers = []

    wage_employee_count = sum(
        1 for e in yr.entries
        if any(e.wages) or any(e.gross_wages) or any(e.ncp_days)
    )
    if wage_employee_count:
        blockers.append(f"{wage_employee_count} employee(s) have wage data entered")

    filed_months = sum(
        1 for r in yr.remittances
        if r.get("trrn") or r.get("crrn") or r.get("credit_date")
    )
    if filed_months:
        blockers.append(f"{filed_months} month(s) have filed TRRN/CRRN remittances")

    paid_fee_count = db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_obj.id,
        SubscriptionFee.financial_year == key,
        SubscriptionFee.is_paid == True,
    ).count()
    if paid_fee_count:
        blockers.append(f"{paid_fee_count} paid subscription fee record(s) exist for this year")

    return blockers


@app.get("/api/years")
async def list_years(
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    rows = []
    for yk in project.year_keys_sorted():
        yr = project.years[yk]
        blockers = get_year_deletion_blockers(project, est_obj, yk, db)
        rows.append({
            "key": yk, "year_from": yr.year_from, "year_to": yr.year_to,
            "label": yr.long_label, "short": yr.short_label,
            "scheme": yr.scheme,
            "scheme_label": "Post-1997" if yr.is_post_1997 else "Pre-1997",
            "epf_rate": yr.epf_rate, "fpf_rate": yr.fpf_rate,
            "emp_epf_rate": yr.emp_epf_rate,
            "er_epf_rate": yr.er_epf_rate, "er_eps_rate": yr.er_eps_rate,
            "entries": len(yr.entries),
            "rate_text": yr.statutory_rate_text,
            "can_delete": not blockers,
            "delete_blockers": blockers,
        })
    return {"years": rows, "total": len(rows)}


@app.post("/api/years")
async def add_year(
    d: YearIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    key = f"{d.year_from}-{d.year_to[-2:]}"
    if key in project.years:
        raise HTTPException(400, f"Year {key} already exists")
    project.add_year(d.year_from, d.year_to, d.scheme,
                     d.epf_rate, d.fpf_rate,
                     d.emp_epf_rate, d.er_epf_rate, d.er_eps_rate)
    save_establishment_project(db, est_obj, project)
    return {"ok": True, "key": key}


@app.put("/api/years/{key}")
async def edit_year(
    key: str,
    d: YearRatesIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    project.update_year_rates(key, d.scheme, d.epf_rate, d.fpf_rate,
                              d.emp_epf_rate, d.er_epf_rate, d.er_eps_rate)
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


@app.delete("/api/years/{key}")
async def del_year(
    key: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    # Applies to every caller, including superadmins -- deleting real filed
    # compliance data is never a casual one-click action. See /force below for
    # the deliberate, separately-gated superadmin escape hatch.
    blockers = get_year_deletion_blockers(project, est_obj, key, db)
    if blockers:
        raise HTTPException(
            409,
            f"Cannot delete FY {key}: " + ", ".join(blockers) + ". Remove or archive this data first."
        )
    project.remove_year(key)
    save_establishment_project(db, est_obj, project)
    log_activity(db, current_user.id, est_obj.id, "year.delete",
                 f"Deleted empty year {key} for {est_obj.name} ({est_obj.code})")
    return {"ok": True}


class YearForceDeleteIn(BaseModel):
    confirm_code: str
    confirm_year: str


@app.delete("/api/years/{key}/force")
async def force_del_year(
    key: str,
    d: YearForceDeleteIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Superadmin-only escape hatch for deleting a year that DOES have real data.
    Deliberately a separate endpoint from the normal delete (never exposed to
    consultants/employers under any circumstance, UI or direct API call) and
    requires typing the establishment code and year back, GitHub-repo-deletion
    style, so it can never be triggered by a stray click."""
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    if d.confirm_code.strip() != est_obj.code or d.confirm_year.strip() != key:
        raise HTTPException(400, "Confirmation text did not match. Type the establishment code and year exactly to force-delete.")
    blockers = get_year_deletion_blockers(project, est_obj, key, db)
    project.remove_year(key)
    save_establishment_project(db, est_obj, project)
    log_activity(db, admin.id, est_obj.id, "year.force_delete",
                 f"FORCE-deleted year {key} for {est_obj.name} ({est_obj.code}) despite blockers: "
                 + ("; ".join(blockers) if blockers else "(none -- year was actually empty)"))
    return {"ok": True}


@app.post("/api/years/bulk")
async def bulk_add_years(
    d: dict,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    start_y = int(d.get("start_year", 1980))
    end_y = int(d.get("end_year", 2026))
    added = 0
    for y in range(start_y, end_y + 1):
        year_from = str(y)
        year_to = str(y + 1)
        key = f"{year_from}-{year_to[-2:]}"
        if key not in project.years:
            if y < 1997:
                project.add_year(year_from, year_to, SCHEME_PRE_1997, 8.33, 1.16, 10.0, 10.0, 0.0)
            else:
                project.add_year(year_from, year_to, SCHEME_POST_1997, 0.0, 0.0, 12.0, 3.67, 8.33)
            added += 1
    if added > 0:
        save_establishment_project(db, est_obj, project)
    return {"ok": True, "added": added}


# ── Remittances Endpoints ─────────────────────────────────────────────────
@app.get("/api/years/{key}/remittances")
async def get_remittances(
    key: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
        
    yr = project.years[key]
    est = project.build_establishment_for_year(key)
    employees = project.build_employees_for_year(key)
    employees = [emp for emp in employees if sum(emp.wages) > 0]
    
    all_month_rows = [emp.month_rows(est.worker_epf_rate, est.worker_eps_rate, est.employer_epf_rate, est.employer_eps_rate) for emp in employees]
    wage_ceilings = get_wage_ceilings_for_year(yr.year_from)
    results = []

    for i, month_label in enumerate(MONTHS):
        wages_total = sum(rows[i][0] for rows in all_month_rows)
        ee_total = sum(rows[i][1] for rows in all_month_rows)
        er_total = sum(rows[i][6] for rows in all_month_rows)
        a10_total = sum(rows[i][5] for rows in all_month_rows)
        members = sum(1 for rows in all_month_rows if rows[i][0] > 0)

        # Gross/EPF/EPS wages -- mirrors dashboard()'s per-employee aggregation
        # exactly so the two pages can never drift apart on these figures.
        ceiling = wage_ceilings[i]
        gross_wages_total = 0
        eps_wages_total = 0
        edli_wages_total = 0
        for emp in employees:
            wages = emp.wages[i] if emp.wages and len(emp.wages) > i else 0
            gross = emp.gross_wages[i] if emp.gross_wages and len(emp.gross_wages) > i else 0
            gross_wages_total += gross
            if est.worker_eps_rate == 0:
                eps_wages_total += 0 if emp.age_crosses_58 else min(wages, ceiling)
            else:
                eps_wages_total += wages
            # EDLI wages: same ceiling-capped basis as generate_ecr_month() --
            # capped even when Higher EPF lets EPF wages exceed the ceiling,
            # and (unlike EPS) not zeroed out past age 58.
            edli_wages_total += min(wages, ceiling)

        row_data = compute_remittance_row(yr, est, i, wages_total, ee_total, er_total, a10_total, members)
        row_data["gross_wages"] = gross_wages_total
        row_data["epf_wages"] = wages_total
        row_data["eps_wages"] = eps_wages_total
        row_data["edli_wages"] = edli_wages_total
        results.append(row_data)
        
    return {"remittances": results}


@app.post("/api/years/{key}/remittances/bulk")
async def save_remittances_bulk(
    key: str,
    data: BulkRemittanceIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
        
    yr = project.years[key]
    yr.remittances = [r.dict() for r in data.remittances]
    save_establishment_project(db, est_obj, project)
    log_activity(
        db, est_obj.user_id, est_obj.id, "challan_saved",
        f"Saved Form 12A challan remittances for FY {key} in {project.name}",
        {"year_key": key, "establishment_code": project.code}
    )
    return {"ok": True}


# ── Wages Endpoints ───────────────────────────────────────────────────────
@app.get("/api/years/{key}/wages")
async def get_wages(
    key: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    yr = project.years[key]
    est = project.build_establishment_for_year(key)
    emps = project.build_employees_for_year(key)
    rows = []
    g = [0] * 7
    wage_ceilings = get_wage_ceilings_for_year(yr.year_from)
    for emp in emps:
        mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                               est.employer_epf_rate, est.employer_eps_rate,
                               wage_ceilings=wage_ceilings)
        wt, we, ws, wto, ee, es, eto = emp.annual_totals(
            est.worker_epf_rate, est.worker_eps_rate,
            est.employer_epf_rate, est.employer_eps_rate,
            wage_ceilings=wage_ceilings)
        m = project.master.get(emp.member_id)
        rows.append({
            "member_id": emp.member_id, "name": emp.name, "uan": emp.uan,
            "father_name": emp.father_name,
            "dob": m.dob if m else "", "sex": m.sex if m else "",
            "doj": m.doj if m else "", "doe": m.doe if m else "",
            "wages": [int(round(float(w))) if w is not None else 0 for w in emp.wages],
            "gross_wages": [int(round(float(g_val))) if g_val is not None else 0 for g_val in emp.gross_wages],
            "ncp_days": getattr(emp, 'ncp_days', [0]*12),
            "higher_epf_ee": emp.higher_epf_ee,
            "higher_epf_er": emp.higher_epf_er,
            "age_crosses_58": emp.age_crosses_58,
            "months": [{"m": MONTHS[i], "w": int(round(r[0])),
                        "we": int(round(r[1])), "ws": int(round(r[2])), "wt": int(round(r[3])),
                        "ee": int(round(r[4])), "es": int(round(r[5])), "et": int(round(r[6]))}
                       for i, r in enumerate(mrows)],
            "totals": {"w": int(round(wt)), "we": int(round(we)), "ws": int(round(ws)), "wt": int(round(wto)),
                       "ee": int(round(ee)), "es": int(round(es)), "et": int(round(eto))},
        })
        g[0] += wt; g[1] += we; g[2] += ws; g[3] += wto
        g[4] += ee; g[5] += es; g[6] += eto
    return {
        "key": key, "label": yr.long_label,
        "scheme": yr.scheme,
        "rates": {
            "w_epf": est.worker_epf_rate, "w_eps": est.worker_eps_rate,
            "e_epf": est.employer_epf_rate, "e_eps": est.employer_eps_rate,
            "eps_label": est.eps_label, "text": est.statutory_rate_text,
            "wage_ceilings": wage_ceilings,
        },
        "employees": rows,
        "grand": {"w": int(round(g[0])), "we": int(round(g[1])), "ws": int(round(g[2])), "wt": int(round(g[3])),
                  "ee": int(round(g[4])), "es": int(round(g[5])), "et": int(round(g[6]))},
        "count": len(rows),
    }


@app.post("/api/years/{key}/wages")
async def put_wages(
    key: str,
    d: WageIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "wages.edit")
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    if len(d.wages) != 12:
        raise HTTPException(400, "Need exactly 12 wage values")
    if not project.get_master(d.member_id):
        raise HTTPException(404, f"Employee {d.member_id} not in master")
    
    gross_wages = [int(round(float(g))) if g is not None else 0 for g in (d.gross_wages if d.gross_wages and len(d.gross_wages) == 12 else d.wages)]
    wages_int = [int(round(float(w))) if w is not None else 0 for w in d.wages]
    capped_wages = [min(w, g) for w, g in zip(wages_int, gross_wages)]
    ncp_days = d.ncp_days if d.ncp_days and len(d.ncp_days) == 12 else [0] * 12
    project.upsert_entry(key, d.member_id, capped_wages, gross_wages=gross_wages, ncp_days=ncp_days, age_crosses_58=d.age_crosses_58, higher_epf_ee=d.higher_epf_ee, higher_epf_er=d.higher_epf_er)
    save_establishment_project(db, est_obj, project)
    sync_subscription_fees_for_year(db, est_obj, project, key)
    
    emp_name = project.get_master(d.member_id).name if project.get_master(d.member_id) else d.member_id
    log_activity(
        db, est_obj.user_id, est_obj.id, "wages_saved",
        f"Updated 12-month wages for {emp_name} (FY {key}) in {project.name}",
        {"year_key": key, "member_id": d.member_id, "establishment_name": project.name}
    )
    return {"ok": True}


@app.post("/api/years/{key}/wages/bulk_month")
async def bulk_month_wages(
    key: str,
    d: BulkMonthWagesIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "wages.edit")
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    if not (0 <= d.month_idx <= 11):
        raise HTTPException(400, "Invalid month index")

    for emp_update in d.employees:
        if not project.get_master(emp_update.member_id):
            continue
            
        yr = project.years[key]
        existing_emp = next((e for e in yr.entries if e.member_id == emp_update.member_id), None)
        
        if existing_emp:
            wages_arr = [int(round(float(w))) if w is not None else 0 for w in existing_emp.wages]
            gross_wages_arr = [int(round(float(g))) if g is not None else 0 for g in existing_emp.gross_wages]
            ncp_days_arr = existing_emp.ncp_days.copy()
        else:
            wages_arr = [0] * 12
            gross_wages_arr = [0] * 12
            ncp_days_arr = [0] * 12
            
        capped_epf_wage = int(round(float(min(emp_update.epf_wage, emp_update.gross_wage))))
        gross_wage = int(round(float(emp_update.gross_wage)))
        
        wages_arr[d.month_idx] = capped_epf_wage
        gross_wages_arr[d.month_idx] = gross_wage
        ncp_days_arr[d.month_idx] = emp_update.ncp_days
        
        project.upsert_entry(
            key, 
            emp_update.member_id, 
            wages_arr, 
            gross_wages=gross_wages_arr, 
            ncp_days=ncp_days_arr, 
            age_crosses_58=emp_update.age_crosses_58,
            higher_epf_ee=emp_update.higher_epf_ee,
            higher_epf_er=emp_update.higher_epf_er
        )
        
    save_establishment_project(db, est_obj, project)
    sync_subscription_fees_for_year(db, est_obj, project, key)
    month_name = MONTHS[d.month_idx] if 0 <= d.month_idx < len(MONTHS) else f"Month {d.month_idx}"
    log_activity(
        db, est_obj.user_id, est_obj.id, "wages_saved",
        f"Saved monthly bulk wages for {month_name} (FY {key}) in {project.name} ({len(d.employees)} employees)",
        {"year_key": key, "month_idx": d.month_idx, "employee_count": len(d.employees), "establishment_name": project.name}
    )
    return {"ok": True, "count": len(d.employees)}


@app.delete("/api/years/{key}/wages/{acc:path}")
async def del_wages(
    key: str,
    acc: str,
    month_idx: Optional[int] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "wages.delete")
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    yr = project.years[key]
    idx = next((i for i, e in enumerate(yr.entries) if e.member_id == acc), None)
    if idx is None:
        raise HTTPException(404, "Entry not found")

    if month_idx is not None:
        if not (0 <= month_idx <= 11):
            raise HTTPException(400, "Invalid month index")
        month_label = MONTHS[month_idx]
        remit = next(
            (r for r in yr.remittances if isinstance(r, dict) and r.get("month_label") == month_label),
            None
        )
        if remit and (remit.get("trrn") or remit.get("crrn")):
            raise HTTPException(
                409,
                f"Cannot delete: {month_label} (FY {key}) has already been filed "
                f"(TRRN: {remit.get('trrn') or '—'}, CRRN: {remit.get('crrn') or '—'}). "
                f"A filed month's wage data cannot be deleted."
            )
        entry = yr.entries[idx]
        entry.wages[month_idx] = 0
        entry.gross_wages[month_idx] = 0
        entry.ncp_days[month_idx] = 0
        if not any(entry.wages) and not any(entry.gross_wages) and not any(entry.ncp_days):
            project.remove_entry(key, idx)
        save_establishment_project(db, est_obj, project)
        sync_subscription_fees_for_year(db, est_obj, project, key)
        log_activity(
            db, est_obj.user_id, est_obj.id, "wage_month_deleted",
            f"Deleted {month_label} wage entry for member {acc} (FY {key}) in {project.name}",
            {"year_key": key, "month_idx": month_idx, "member_id": acc, "establishment_name": project.name}
        )
        return {"ok": True}

    project.remove_entry(key, idx)
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


@app.delete("/api/years/{key}/wages")
async def del_all_wages(
    key: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "wages.delete")
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    project.years[key].entries.clear()
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


# ── Reports & Form Exports ─────────────────────────────────────────────────
def _build_employee_wage_history_data(project: Project, member_id: str) -> Optional[dict]:
    """Shared data-builder for the Employee Wage History report -- used by both the JSON
    endpoint (on-screen HTML) and the PDF endpoint, so the two can never compute this
    a second, possibly-inconsistent way. Returns None if the employee isn't found."""
    master = project.get_master(member_id)
    if not master:
        return None

    years_data = []
    for yk in project.year_keys_sorted():
        yr = project.years[yk]
        emps = project.build_employees_for_year(yk)
        emp = next((e for e in emps if e.member_id == member_id), None)

        wages = emp.wages if (emp and emp.wages) else [0] * 12
        total_wages = sum((int(w) if w else 0) for w in wages)

        if emp:
            # Reuse the exact same per-month contribution calc used by the Dashboard and
            # Challans pages (Employee.month_rows), so these figures can never drift from
            # what those pages show for the same employee/month.
            est = project.build_establishment_for_year(yk)
            wage_ceilings = get_wage_ceilings_for_year(yr.year_from)
            mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                                    est.employer_epf_rate, est.employer_eps_rate,
                                    wage_ceilings=wage_ceilings)
            ee_epf = [int(round(r[1])) for r in mrows]   # w_epf -- employee's own EPF deduction
            er_epf = [int(round(r[4])) for r in mrows]   # e_epf -- employer's EPF-only share
            er_eps = [int(round(r[5])) for r in mrows]   # e_eps -- employer's EPS/pension share
            higher_epf_ee = bool(emp.higher_epf_ee)
            higher_epf_er = bool(emp.higher_epf_er)
            age_crosses_58 = bool(emp.age_crosses_58)
        else:
            ee_epf = er_epf = er_eps = [0] * 12
            higher_epf_ee = higher_epf_er = age_crosses_58 = False

        month_total = [ee_epf[i] + er_epf[i] + er_eps[i] for i in range(12)]

        years_data.append({
            "year": f"{yr.year_from}-{yr.year_to}",
            "wages": wages,
            "total": total_wages,
            "ee_epf": ee_epf,
            "ee_epf_total": sum(ee_epf),
            "er_epf": er_epf,
            "er_epf_total": sum(er_epf),
            "er_eps": er_eps,
            "er_eps_total": sum(er_eps),
            "month_total": month_total,
            "month_total_total": sum(month_total),
            "higher_epf_ee": higher_epf_ee,
            "higher_epf_er": higher_epf_er,
            "age_crosses_58": age_crosses_58
        })

    return {
        "establishment": {
            "name": project.name,
            "code": project.code
        },
        "profile": {
            "member_id": master.member_id,
            "uan": master.uan,
            "name": master.name,
            "father_name": master.father_name,
            "dob": master.dob.isoformat() if hasattr(master.dob, 'isoformat') else master.dob,
            "doj": master.doj.isoformat() if hasattr(master.doj, 'isoformat') else master.doj,
            "doe": master.doe.isoformat() if hasattr(master.doe, 'isoformat') else master.doe,
            "reason_leaving": master.reason_leaving
        },
        "years": years_data
    }


@app.get("/api/reports/employee_wage_history/{member_id:path}/pdf")
async def report_employee_wage_history_pdf(
    member_id: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    data = _build_employee_wage_history_data(project, member_id)
    if data is None:
        raise HTTPException(404, "Employee not found")

    from pdf_engine import generate_employee_wage_history_pdf
    tmp = tempfile.mkdtemp()
    safe_name = (data["profile"]["name"] or "Employee").replace("/", "-").replace("\\", "-").strip() or "Employee"
    safe_uan = (data["profile"]["uan"] or "NO_UAN").strip() or "NO_UAN"
    fname = f"{safe_name}_{safe_uan}_WageHistory.pdf"
    path = os.path.join(tmp, fname)
    try:
        generate_employee_wage_history_pdf(data, path)
    except Exception as e:
        raise HTTPException(500, f"PDF generation failed: {str(e)}")

    return FileResponse(path, filename=fname, media_type="application/pdf")


@app.get("/api/reports/employee_wage_history/{member_id:path}")
async def report_employee_wage_history(
    member_id: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    data = _build_employee_wage_history_data(project, member_id)
    if data is None:
        raise HTTPException(404, "Employee not found")
    return data


@app.get("/api/reports/{key}")
def generate_report(
    key: str,
    format: str = 'excel',
    forms: str = '',
    branch_id: Optional[int] = None,
    division_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "forms.download")
    est_obj, project = active
    if current_user.role != "superadmin":
        unpaid_detail = get_unpaid_months_detail_for_year(db, est_obj, project, key)
        if unpaid_detail:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_year_payment_required_detail(unpaid_detail, key)
            )

    if key not in project.years:
        raise HTTPException(404, "Year not found")
    yr = project.years[key]
    est = project.build_establishment_for_year(key)
    emps = project.build_employees_for_year(key)
    scoped = branch_id is not None or division_id is not None or unit_id is not None
    if scoped:
        emps = filter_employees_by_scope(emps, branch_id=branch_id, division_id=division_id, unit_id=unit_id)
        scope_member_ids = {e.member_id for e in filter_employees_by_scope(
            project.master_list(), branch_id=branch_id, division_id=division_id, unit_id=unit_id)}
    else:
        scope_member_ids = None
    if not emps:
        raise HTTPException(400, "No wage entries for this year" if not scoped else "No employees in the selected scope for this year")

    forms_list = [f.strip() for f in forms.split(',')] if forms else ['3A', '6A', '12A', '5', '10']
    gen = ExcelGenerator(est, emps, project=project, forms_to_generate=forms_list, scope_member_ids=scope_member_ids)
    safe = (project.code or "EPF").replace("/", "-").replace("\\", "-").strip() or "EPF"
    fname = f"{safe}_{yr.short_label}.xlsx"
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, fname)
    gen.build(path)

    if format == 'pdf':
        pdf_fname = fname.replace('.xlsx', '.pdf')
        pdf_path = os.path.join(tmp, pdf_fname)
        try:
            from pdf_engine import generate_form_9_pdf, generate_form_3a_pdf, generate_form_6a_pdf, generate_form_12a_pdf, generate_form_5_pdf, generate_form_10_pdf

            f = forms_list[0] if forms_list else '3A'
            if f == '3A': generate_form_3a_pdf(project, key, pdf_path, member_ids=scope_member_ids)
            elif f == '6A': generate_form_6a_pdf(project, key, pdf_path, member_ids=scope_member_ids)
            elif f == '12A': generate_form_12a_pdf(project, key, pdf_path, member_ids=scope_member_ids)
            elif f == '5': generate_form_5_pdf(project, pdf_path, member_ids=scope_member_ids)
            elif f == '10': generate_form_10_pdf(project, pdf_path, member_ids=scope_member_ids)
            elif f == '9': generate_form_9_pdf(project, pdf_path, member_ids=scope_member_ids)
            else: raise ValueError(f"Unknown form for PDF generation: {f}")

            return FileResponse(pdf_path, filename=pdf_fname, media_type="application/pdf")
        except Exception as e:
            raise HTTPException(500, f"PDF generation failed: {str(e)}")

    return FileResponse(path, filename=fname, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/reports/{key}/employee/{member_id:path}")
def generate_employee_report(
    key: str,
    member_id: str,
    format: str = 'pdf',
    forms: str = '3A',
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "forms.download")
    est_obj, project = active
    if current_user.role != "superadmin":
        unpaid_detail = get_unpaid_months_detail_for_year(db, est_obj, project, key)
        if unpaid_detail:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_year_payment_required_detail(unpaid_detail, key)
            )

    if key not in project.years:
        raise HTTPException(404, "Year not found")
    est = project.build_establishment_for_year(key)
    emps = project.build_employees_for_year(key)

    acc = normalize_member_id(member_id)
    emp = next((e for e in emps if e.member_id == acc), None)
    if not emp:
        raise HTTPException(404, "Employee not found in this year")
    
    total_w = sum(w or 0 for w in (emp.wages or []))
    if total_w <= 0:
        raise HTTPException(400, "Form 3A cannot be generated for an employee with 0 total wages")
    
    forms_list = [f.strip() for f in forms.split(',')] if forms else ['3A']
    gen = ExcelGenerator(est, [emp], project=project, forms_to_generate=forms_list, scope_member_ids={acc})
    safe = (emp.name or "Employee").replace("/", "-").replace("\\", "-").strip() or "Employee"
    fname = f"{safe}_Form3A.xlsx"
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, fname)
    gen.build(path)

    if format == 'pdf':
        pdf_fname = fname.replace('.xlsx', '.pdf')
        pdf_path = os.path.join(tmp, pdf_fname)
        try:
            import pdf_engine
            pdf_engine.generate_form_3a_pdf(project, key, pdf_path, member_ids={acc})
            return FileResponse(pdf_path, filename=pdf_fname, media_type="application/pdf")
        except Exception as e:
            raise HTTPException(500, f"PDF generation failed: {str(e)}")
            
    return FileResponse(path, filename=fname, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/reports/employee/{member_id:path}/form3a-multi-year")
def generate_employee_form3a_multi_year(
    member_id: str,
    years: Optional[str] = Query(None, description="Comma-separated financial year keys, e.g. 2023-24,2024-25,2025-26"),
    from_year: Optional[str] = Query(None, description="Range start year key, used with to_year if 'years' isn't given"),
    to_year: Optional[str] = Query(None, description="Range end year key, used with from_year if 'years' isn't given"),
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """One employee's Form 3A across several financial years, combined into a single PDF.
    Reuses pdf_engine.generate_form_3a_multi_year_pdf, which itself reuses the exact same
    per-employee block-builder as the single-year endpoint above -- no separate Form 3A
    calculation logic exists here."""
    require_permission(db, current_user, "forms.download")
    est_obj, project = active
    acc = normalize_member_id(member_id)

    if years:
        year_keys = [y.strip() for y in years.split(',') if y.strip()]
    elif from_year and to_year:
        all_keys = project.year_keys_sorted()
        if from_year not in all_keys or to_year not in all_keys:
            raise HTTPException(400, "from_year/to_year must be existing financial year keys")
        start_idx, end_idx = sorted((all_keys.index(from_year), all_keys.index(to_year)))
        year_keys = all_keys[start_idx:end_idx + 1]
    else:
        raise HTTPException(400, "Provide either 'years' (comma-separated) or both 'from_year' and 'to_year'")

    if not year_keys:
        raise HTTPException(400, "No financial years specified")

    # Same download-gating rule as every other /api/reports/... endpoint, scoped to only the
    # years actually requested here (not every year on file, since this request doesn't touch
    # those).
    if current_user.role != "superadmin":
        unpaid_detail = []
        for yk in year_keys:
            if yk in project.years:
                unpaid_detail.extend(get_unpaid_months_detail_for_year(db, est_obj, project, yk))
        if unpaid_detail:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_year_payment_required_detail(unpaid_detail, None)
            )

    master = project.get_master(acc)
    emp_name = (master.name if master else None) or "Employee"

    import pdf_engine
    tmp = tempfile.mkdtemp()
    safe = emp_name.replace("/", "-").replace("\\", "-").strip() or "Employee"
    fname = f"{safe}_Form3A_MultiYear.pdf"
    path = os.path.join(tmp, fname)

    try:
        result = pdf_engine.generate_form_3a_multi_year_pdf(project, year_keys, acc, path)
    except Exception as e:
        raise HTTPException(500, f"PDF generation failed: {str(e)}")

    if not result["generated_years"]:
        reasons = "; ".join(f"{s['year']}: {s['reason']}" for s in result["skipped_years"])
        raise HTTPException(404, f"Form 3A could not be generated for any of the requested years — {reasons}")

    return FileResponse(
        result["path"], filename=fname, media_type="application/pdf",
        headers={
            "X-Generated-Years": ",".join(result["generated_years"]),
            "X-Skipped-Years": json.dumps(result["skipped_years"]),
        }
    )


@app.get("/api/reports/form9/download")
def report_form9(
    format: str = 'excel',
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "forms.download")
    est_obj, project = active
    if current_user.role != "superadmin":
        all_unpaid_detail = []
        for yk in project.years.keys():
            all_unpaid_detail.extend(get_unpaid_months_detail_for_year(db, est_obj, project, yk))
        if all_unpaid_detail:
            # Form 9 spans every year on file, unlike the other forms which are scoped to one
            # financial year -- so financial_year is left None (multi-year) rather than a single key.
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_year_payment_required_detail(all_unpaid_detail, None)
            )

    if not project.master:
        raise HTTPException(400, "No employees")
    tmp = tempfile.mkdtemp()
    safe_name = (project.name or 'EPF').replace("/", "-").replace("\\", "-").strip() or 'EPF'
    fname = f"{safe_name}_Form9.xlsx"
    path = os.path.join(tmp, fname)
    generate_form9(project, path)
    
    if format == 'pdf':
        pdf_fname = fname.replace('.xlsx', '.pdf')
        pdf_path = os.path.join(tmp, pdf_fname)
        try:
            from pdf_engine import generate_form_9_pdf
            generate_form_9_pdf(project, pdf_path)
            return FileResponse(pdf_path, filename=pdf_fname, media_type="application/pdf")
        except Exception as e:
            raise HTTPException(500, f"PDF generation failed: {str(e)}")
            
    return FileResponse(path, filename=fname, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


import zipfile
import io

def _build_ecr_employees_for_scope(project: Project, year_record, branch_id=None, division_id=None, unit_id=None):
    """The single builder for ECR-shaped Employee objects, used by every ECR
    endpoint below -- never reimplement this filtering loop per-endpoint."""
    masters = filter_employees_by_scope(project.master_list(), branch_id=branch_id, division_id=division_id, unit_id=unit_id)
    employees_with_wages = []
    for master_emp in masters:
        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        emp_obj = Employee(
            member_id=master_emp.member_id,
            name=master_emp.name,
            father_name=master_emp.father_name,
            uan=master_emp.uan,
            branch_id=master_emp.branch_id,
            division_id=master_emp.division_id,
            unit_id=master_emp.unit_id,
        )
        if entry:
            emp_obj.wages = entry.wages
            emp_obj.gross_wages = entry.gross_wages
            emp_obj.ncp_days = getattr(entry, 'ncp_days', [0] * 12)
            emp_obj.higher_epf_ee = master_emp.higher_epf_ee
            emp_obj.higher_epf_er = master_emp.higher_epf_er
            emp_obj.age_crosses_58 = getattr(entry, 'age_crosses_58', False)
        else:
            emp_obj.wages = [0.0] * 12
            emp_obj.ncp_days = [0] * 12
        employees_with_wages.append(emp_obj)
    return employees_with_wages


@app.get("/api/reports/{year_key}/ecr/{month_idx}")
async def generate_ecr_txt(
    year_key: str,
    month_idx: int,
    branch_id: Optional[int] = None,
    division_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "ecr.download")
    est_obj, project = active
    scoped = branch_id is not None or division_id is not None or unit_id is not None
    if scoped:
        require_feature_enabled(db, "branch_feature_enabled", "Branch/division/unit filtering")
    if current_user.role != "superadmin":
        if not (0 <= month_idx < 12):
            raise HTTPException(400, "Invalid month index")
        emp_count = count_ecr_employees_for_month(project, year_key, month_idx)
        if emp_count > 0:
            sync_subscription_fees_for_year(db, est_obj, project, year_key)
            m_abbr = MONTH_SHORT_NAMES[month_idx]
            fee_row = db.query(SubscriptionFee).filter(
                SubscriptionFee.establishment_id == est_obj.id,
                SubscriptionFee.financial_year == year_key,
                SubscriptionFee.month == m_abbr
            ).first()
            if fee_row and not fee_row.is_paid and is_month_overdue(year_key, month_idx) and not is_establishment_in_trial(est_obj):
                year_record = project.years.get(year_key)
                cal_yr = calendar_year_for_month(m_abbr, year_record.year_from, year_record.year_to) if year_record else ""
                display_m = f"{MONTH_FULL.get(m_abbr.upper(), m_abbr)} {cal_yr}".strip()
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Download blocked — software subscription fee for {display_m} is unpaid. Contact your administrator to settle platform fees."
                )

    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")

    employees_with_wages = _build_ecr_employees_for_scope(
        project, year_record, branch_id=branch_id, division_id=division_id, unit_id=unit_id)

    est = project.build_establishment_for_year(year_key)
    txt = generate_ecr_month(est, employees_with_wages, year_record, month_idx)

    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    month_str = MONTHS[month_idx][:3].upper()
    cal_year = calendar_year_for_month(MONTHS[month_idx], year_record.year_from, year_record.year_to)

    if scoped:
        scope_name = resolve_scope_path_for_ids(project, branch_id=branch_id, division_id=division_id, unit_id=unit_id)
        clean_b = "".join(c for c in scope_name if c.isalnum() or c in ('_', '-')) or "Unassigned"
        fname = f"{est_code}_ECR_{clean_b}_{month_str}_{cal_year}.txt"
    else:
        fname = f"{est_code}_ECR_{month_str}_{cal_year}.txt"
    return Response(content=txt, media_type="text/plain", headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/api/reports/{year_key}/ecr/{month_idx}/by-scope")
async def get_ecr_by_scope_stats(
    year_key: str,
    month_idx: int,
    level: str = "branch",
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    require_feature_enabled(db, "branch_feature_enabled", "Branch-wise ECR breakdown")
    if level not in ("branch", "division", "unit"):
        raise HTTPException(400, "level must be one of: branch, division, unit")
    est_obj, project = active
    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")

    scope_stats = {}
    for master_emp in project.master_list():
        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        if not entry: continue
        w = entry.wages[month_idx] if entry.wages and len(entry.wages) > month_idx else 0
        g = entry.gross_wages[month_idx] if entry.gross_wages and len(entry.gross_wages) > month_idx else 0
        if w > 0 or g > 0:
            node_id = getattr(master_emp, f"{level}_id", None)
            key = node_id if node_id is not None else "Unassigned"
            if key not in scope_stats:
                display_name = (
                    resolve_scope_path_for_ids(project, **{f"{level}_id": node_id})
                    if node_id is not None else "Unassigned"
                )
                scope_stats[key] = {"id": node_id, "name": display_name, "employee_count": 0, "total_wages": 0}
            scope_stats[key]["employee_count"] += 1
            scope_stats[key]["total_wages"] += w

    return {"level": level, "scopes": sorted(scope_stats.values(), key=lambda x: x["name"])}


@app.get("/api/reports/{year_key}/ecr/{month_idx}/zip-by-scope")
async def generate_ecr_zip_by_scope(
    year_key: str,
    month_idx: int,
    level: str = "branch",
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "ecr.download")
    require_feature_enabled(db, "branch_feature_enabled", "Branch-wise ECR download")
    if level not in ("branch", "division", "unit"):
        raise HTTPException(400, "level must be one of: branch, division, unit")
    est_obj, project = active
    if current_user.role != "superadmin":
        if not (0 <= month_idx < 12):
            raise HTTPException(400, "Invalid month index")
        emp_count = count_ecr_employees_for_month(project, year_key, month_idx)
        if emp_count > 0:
            sync_subscription_fees_for_year(db, est_obj, project, year_key)
            m_abbr = MONTH_SHORT_NAMES[month_idx]
            fee_row = db.query(SubscriptionFee).filter(
                SubscriptionFee.establishment_id == est_obj.id,
                SubscriptionFee.financial_year == year_key,
                SubscriptionFee.month == m_abbr
            ).first()
            if fee_row and not fee_row.is_paid and is_month_overdue(year_key, month_idx) and not is_establishment_in_trial(est_obj):
                year_record = project.years.get(year_key)
                cal_yr = calendar_year_for_month(m_abbr, year_record.year_from, year_record.year_to) if year_record else ""
                display_m = f"{MONTH_FULL.get(m_abbr.upper(), m_abbr)} {cal_yr}".strip()
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"Download blocked — software subscription fee for {display_m} is unpaid. Contact your administrator to settle platform fees."
                )

    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")

    scope_emps = {}
    for master_emp in project.master_list():
        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        w = entry.wages[month_idx] if entry and entry.wages and len(entry.wages) > month_idx else 0
        g = entry.gross_wages[month_idx] if entry and entry.gross_wages and len(entry.gross_wages) > month_idx else 0
        if w > 0 or g > 0:
            node_id = getattr(master_emp, f"{level}_id", None)
            key = node_id if node_id is not None else "Unassigned"
            if key not in scope_emps:
                display_name = (
                    resolve_scope_path_for_ids(project, **{f"{level}_id": node_id})
                    if node_id is not None else "Unassigned"
                )
                scope_emps[key] = (display_name, [])
            emp_obj = Employee(
                member_id=master_emp.member_id,
                name=master_emp.name,
                father_name=master_emp.father_name,
                uan=master_emp.uan,
                branch_id=master_emp.branch_id,
                division_id=master_emp.division_id,
                unit_id=master_emp.unit_id,
                wages=entry.wages if entry else [0]*12,
                gross_wages=entry.gross_wages if entry else [0]*12,
                ncp_days=getattr(entry, 'ncp_days', [0]*12) if entry else [0]*12,
                higher_epf_ee=master_emp.higher_epf_ee,
                higher_epf_er=master_emp.higher_epf_er,
                age_crosses_58=getattr(entry, 'age_crosses_58', False) if entry else False
            )
            scope_emps[key][1].append(emp_obj)

    est = project.build_establishment_for_year(year_key)
    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    month_str = MONTHS[month_idx][:3].upper()
    cal_year = calendar_year_for_month(MONTHS[month_idx], year_record.year_from, year_record.year_to)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for display_name, emps_list in sorted(scope_emps.values(), key=lambda v: v[0]):
            txt = generate_ecr_month(est, emps_list, year_record, month_idx)
            clean_b = "".join(c for c in display_name if c.isalnum() or c in ('_', '-')) or "Unassigned"
            fname = f"{est_code}_ECR_{clean_b}_{month_str}_{cal_year}.txt"
            zip_file.writestr(fname, txt)

    zip_buffer.seek(0)
    zip_fname = f"{est_code}_ECR_{level.capitalize()}s_{month_str}_{cal_year}.zip"
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={zip_fname}"})


@app.get("/api/reports/{year_key}/ecr")
async def generate_ecr_zip(
    year_key: str,
    branch_id: Optional[int] = None,
    division_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "ecr.download")
    est_obj, project = active
    scoped = branch_id is not None or division_id is not None or unit_id is not None
    if scoped:
        require_feature_enabled(db, "branch_feature_enabled", "Branch/division/unit filtering")
    if current_user.role != "superadmin":
        unpaid_detail = get_unpaid_months_detail_for_year(db, est_obj, project, year_key)
        if unpaid_detail:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_year_payment_required_detail(unpaid_detail, year_key)
            )

    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")

    employees_with_wages = _build_ecr_employees_for_scope(
        project, year_record, branch_id=branch_id, division_id=division_id, unit_id=unit_id)

    est = project.build_establishment_for_year(year_key)
    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    if scoped:
        scope_name = resolve_scope_path_for_ids(project, branch_id=branch_id, division_id=division_id, unit_id=unit_id)
        clean_b = "_" + ("".join(c for c in scope_name if c.isalnum() or c in ('_', '-')) or "Unassigned")
    else:
        clean_b = ""

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for idx in range(12):
            txt = generate_ecr_month(est, employees_with_wages, year_record, idx)
            month_str = MONTHS[idx][:3].upper()
            cal_year = calendar_year_for_month(MONTHS[idx], year_record.year_from, year_record.year_to)
            fname = f"{est_code}_ECR{clean_b}_{month_str}_{cal_year}.txt"
            zip_file.writestr(fname, txt)
            
    zip_buffer.seek(0)
    zip_fname = f"{est_code}_ECR{clean_b}_{year_record.year_from}_{year_record.year_to}.zip"
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={zip_fname}"})


# ── Bulk Import & Import Endpoints ─────────────────────────────────────────
BULK_IMPORT_CACHE = {}

@app.post("/api/wages/bulk_analyze")
async def bulk_analyze_wages(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user)
):
    ext = os.path.splitext(file.filename)[1].lower() or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(await file.read()); tmp.close()
    
    try:
        sheets = get_excel_sheet_names(tmp.name)
        token = str(uuid.uuid4())
        BULK_IMPORT_CACHE[token] = tmp.name
        return {"ok": True, "token": token, "sheets": sheets}
    except Exception as e:
        os.unlink(tmp.name)
        raise HTTPException(400, str(e))

class BulkImportReq(BaseModel):
    token: str
    sheets: List[str]

@app.post("/api/wages/bulk_import")
async def bulk_import_wages(
    req: BulkImportReq,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if req.token not in BULK_IMPORT_CACHE:
        raise HTTPException(400, "File expired or not found. Please upload again.")
        
    filepath = BULK_IMPORT_CACHE[req.token]
    total_imported = 0
    all_warnings = []
    
    try:
        for sheet_name in req.sheets:
            year_key = sheet_name.strip()
            if year_key not in project.years:
                is_post_1997 = True
                if any(str(y) in year_key for y in range(1952, 1997)):
                    is_post_1997 = False
                
                scheme = SCHEME_POST_1997 if is_post_1997 else SCHEME_PRE_1997
                if is_post_1997:
                    project.add_year(year_key, year_key, scheme=scheme, 
                                     epf_rate=0, fpf_rate=0, 
                                     emp_epf_rate=12.0, er_epf_rate=3.67, er_eps_rate=8.33)
                else:
                    project.add_year(year_key, year_key, scheme=scheme, 
                                     epf_rate=8.33, fpf_rate=1.16, 
                                     emp_epf_rate=10.0, er_epf_rate=10.0, er_eps_rate=0)
            
            records, warnings = import_wages_from_excel(filepath, sheet_name=sheet_name)
            for r in records:
                uan = r.get("uan", "")
                resolved_id = project.resolve_member_id(r["member_id"], uan)
                
                if not _is_valid_uan(uan):
                    warnings.append(f"Skipped {resolved_id or r.get('name', 'Unknown')}: Missing or invalid 12-digit UAN")
                    continue
                    
                if not _is_valid_for_establishment(resolved_id, project.code):
                    warnings.append(f"Skipped {resolved_id}: Does not belong to establishment {project.code}")
                    continue

                project.upsert_master(
                    resolved_id, 
                    r["name"], 
                    uan=r.get("uan", ""),
                    father_name=r.get("father_name", ""),
                    dob=r.get("dob", ""),
                    sex=r.get("sex", ""),
                    doj=r.get("doj", ""),
                    doe=r.get("doe", ""),
                    reason_leaving=r.get("reason_leaving", ""),
                    serial_no=r.get("serial_no")
                )
                project.upsert_entry(year_key, resolved_id, r["wages"])
            total_imported += len(records)
            if warnings:
                all_warnings.append(f"[{sheet_name}] " + ", ".join(warnings[:3]))
        
        save_establishment_project(db, est_obj, project)
        return {"ok": True, "imported": total_imported, "warnings": all_warnings}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        os.unlink(filepath)
        del BULK_IMPORT_CACHE[req.token]


@app.post("/api/import/{key}")
async def import_wages(
    key: str,
    import_type: str = Form("yearly"),
    month_idx: int = Form(-1),
    file: UploadFile = File(...),
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    ext = os.path.splitext(file.filename)[1].lower() or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(await file.read()); tmp.close()
        records, warnings = import_wages_from_excel(tmp.name, import_type=import_type, month_idx=month_idx if month_idx >= 0 else None)
        for r in records:
            uan = r.get("uan", "")
            resolved_id = project.resolve_member_id(r["member_id"], uan)
            
            if not _is_valid_uan(uan):
                warnings.append(f"Skipped {resolved_id or r.get('name', 'Unknown')}: Missing or invalid 12-digit UAN")
                continue
                
            if not _is_valid_for_establishment(resolved_id, project.code):
                warnings.append(f"Skipped {resolved_id}: Does not belong to establishment {project.code}")
                continue
                
            project.upsert_master(
                resolved_id, 
                r["name"], 
                uan=r.get("uan", ""),
                father_name=r.get("father_name", ""),
                dob=r.get("dob", ""),
                sex=r.get("sex", ""),
                doj=r.get("doj", ""),
                doe=r.get("doe", ""),
                reason_leaving=r.get("reason_leaving", ""),
                serial_no=r.get("serial_no")
            )
            if import_type == "monthly" and month_idx >= 0:
                existing = project.get_entry(key, resolved_id)
                if existing:
                    new_wages = list(existing.wages)
                    new_gross = list(existing.gross_wages)
                    new_ncp = list(getattr(existing, 'ncp_days', [0]*12))
                else:
                    new_wages = [0.0] * 12
                    new_gross = [0.0] * 12
                    new_ncp = [0] * 12
                new_wages[month_idx] = r["wages"][month_idx]
                new_gross[month_idx] = r["gross_wages"][month_idx]
                new_ncp[month_idx] = r.get("ncp_days", [0]*12)[month_idx]
                project.upsert_entry(key, resolved_id, new_wages, new_gross, new_ncp)
            else:
                project.upsert_entry(key, resolved_id, r["wages"], r.get("gross_wages"), r.get("ncp_days"))
        save_establishment_project(db, est_obj, project)
        return {"ok": True, "imported": len(records), "warnings": warnings[:20]}
    finally:
        os.unlink(tmp.name)


@app.post("/api/master/import")
async def import_master_file(
    file: UploadFile = File(...),
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    ext = os.path.splitext(file.filename)[1].lower() or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(await file.read()); tmp.close()
        records = import_master_from_excel(tmp.name)
        existing_uans = {m.uan for m in project.master.values() if m.uan}
        existing_ids = set(project.master.keys())
        imported_count = 0
        skipped_count = 0
        warnings = []
        
        for r in records:
            uan = r.get("uan", "")
            norm_id = project.resolve_member_id(r["member_id"], uan)
            if not _is_valid_uan(uan):
                warnings.append(f"Skipped {norm_id or r.get('name', 'Unknown')}: Missing or invalid 12-digit UAN")
                skipped_count += 1
                continue
                
            if (uan and uan in existing_uans) or (norm_id and norm_id in existing_ids):
                skipped_count += 1
                continue
                
            if not _is_valid_for_establishment(norm_id, project.code):
                warnings.append(f"Skipped {norm_id}: Member ID does not belong to establishment {project.code}")
                skipped_count += 1
                continue
                
            project.upsert_master(norm_id, r["name"], r.get("father_name", ""),
                                  uan, r.get("dob", ""), r.get("sex", ""),
                                  r.get("doj", ""), r.get("doe", ""), r.get("reason_leaving", ""),
                                  r.get("serial_no"))
            if uan: existing_uans.add(uan)
            if norm_id: existing_ids.add(norm_id)
            imported_count += 1
            
        save_establishment_project(db, est_obj, project)
        return {"ok": True, "imported": imported_count, "skipped": skipped_count, "warnings": warnings[:20]}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        os.unlink(tmp.name)


# ── Constants ─────────────────────────────────────────────────────────────
@app.get("/api/constants")
async def constants():
    return {
        "months": list(MONTHS),
        "reasons": REASONS_FOR_LEAVING,
        "schemes": [
            {"v": SCHEME_PRE_1997, "l": "Pre-1997 (EPF + FPF)"},
            {"v": SCHEME_POST_1997, "l": "1997-98 onwards (EPF 12% + EPS 8.33%)"},
        ],
    }


if __name__ == "__main__":
    import uvicorn
    print("\n--- EPF Admin Dashboard (Multi-Tenant) ---")
    print("=" * 40)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
