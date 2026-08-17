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
from datetime import datetime, date, timedelta

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query, Header, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

# Database and models
from .database import (
    SessionLocal, engine, get_db, Base,
    User, Establishment, Payment, SubscriptionFee, AdvanceCreditLedger, ActivityLog, ProjectData, Setting, DATABASE_URL,
    FeatureFlag, RolePermission, UserPermissionOverride
)

# Auth helpers and dependencies
from .auth import (
    hash_password, verify_password, create_access_token, decode_access_token,
    get_current_user, get_superadmin, get_active_establishment, save_establishment_project
)

from . import cashfree_client

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
FEATURE_FLAG_DEFAULTS = {
    "subscription_enforcement_enabled": (True, "Blocks report/ECR downloads for establishments with unpaid, overdue subscription fees"),
    "cashfree_payments_enabled": (True, "Enables Cashfree payment-link generation for subscription fees and advance credit"),
    "branch_feature_enabled": (True, "Enables branch/division/unit ECR filtering and by-branch ZIP downloads"),
    "advance_credit_enabled": (True, "Enables prepaying advance credit toward future subscription fees"),
}


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
    normalize_member_id, get_excel_sheet_names, get_month_num
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
    especially noticeable right after the DB's connection has been idle."""
    rate = resolve_rate(db, est_obj)
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
                amount_due=round(emp_count * rate, 2),
                is_paid=False
            )
            db.add(fee_row)
            # Newly-billed row -- give prepaid advance credit a chance to cover it.
            apply_advance_credit_if_available(db, est_obj, fee_row)
        else:
            if not fee_row.is_paid:
                was_unbilled = fee_row.amount_due <= 0
                fee_row.employee_count = emp_count
                fee_row.rate_applied = rate
                fee_row.amount_due = round(emp_count * rate, 2)
                if was_unbilled and fee_row.amount_due > 0:
                    # This row existed as a 0-due placeholder (no wage data yet) and has
                    # just been billed for the first time -- same as a fresh row.
                    apply_advance_credit_if_available(db, est_obj, fee_row)
            else:
                fee_row.employee_count = emp_count
                fee_row.amount_due = round(emp_count * fee_row.rate_applied, 2)

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

def get_unpaid_months_for_year(db: Session, establishment: Establishment, project: Project, year_key: str) -> List[str]:
    """Returns list of formatted month names for which wages exist, fee is unpaid, and grace period has elapsed."""
    if not is_feature_enabled(db, "subscription_enforcement_enabled"):
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
                unpaid_overdue.append(f"{MONTH_FULL.get(month_abbr.upper(), month_abbr)} {cal_yr}")

    return unpaid_overdue

# ── App setup ──────────────────────────────────────────────────────────────
app = FastAPI(title="EPF Admin Dashboard", version="2.1.0")

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
                # SQLite doesn't support "IF NOT EXISTS" on ADD COLUMN -- this is a
                # harmless no-op there once the column exists, and on Postgres it's a
                # no-op too now that _try_ddl rolls back instead of poisoning the
                # connection for the statements that follow.
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN advance_credit_balance FLOAT DEFAULT 0;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS cashfree_order_id VARCHAR(120);")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN IF NOT EXISTS cashfree_payment_link_url TEXT;")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN cashfree_order_id VARCHAR(120);")
                _try_ddl(conn, "ALTER TABLE subscription_fees ADD COLUMN cashfree_payment_link_url TEXT;")
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


@app.on_event("startup")
def on_startup():
    _run_startup_migrations()


# ── Static Index Route ─────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


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

class PaymentUpdateItem(BaseModel):
    month: str
    is_paid: bool = False
    amount: Optional[float] = None
    paid_date: Optional[str] = None
    notes: Optional[str] = None

class PaymentsSaveIn(BaseModel):
    financial_year: str
    payments: List[PaymentUpdateItem]

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
    branch: str = ""
    division: str = ""
    unit: str = ""

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

class OrgItemIn(BaseModel):
    name: str


# ── Auth Endpoints ─────────────────────────────────────────────────────────
@app.post("/api/auth/login")
async def login(d: LoginIn, db: Session = Depends(get_db)):
    email = d.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
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

    return {
        "total_consultants": total_consultants,
        "total_employers": total_employers,
        "total_users": total_consultants + total_employers,
        "total_establishments": total_establishments,
        "total_employees": total_employees,
        "payment_compliance_pct": compliance_pct,
        "current_financial_year": current_fy
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

        rows.append({
            "id": est.id,
            "code": est.code,
            "name": est.name,
            "address": est.address or "—",
            "coverage_date": est.coverage_date or "—",
            "custom_rate_per_employee": est.custom_rate_per_employee,
            "employee_count": emp_count,
            "unpaid_subscription_months": unpaid,
            "has_overdue_subscription": len(unpaid) > 0,
            "created_at": est.created_at.strftime("%d-%m-%Y") if est.created_at else "—"
        })

    return {
        "establishments": rows,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "custom_rate_per_employee": user.custom_rate_per_employee
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
    effective_rate = resolve_rate(db, est, consultant)

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

        months_data.append({
            "month_idx": i,
            "month": m_abbr,
            "display_name": display_name,
            "employee_count": f_obj.employee_count if f_obj else emp_count,
            "rate_applied": f_obj.rate_applied if f_obj else effective_rate,
            "amount_due": f_obj.amount_due if f_obj else round(emp_count * effective_rate, 2),
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
            "custom_rate": est.custom_rate_per_employee
        },
        "consultant": {
            "id": consultant.id if consultant else None,
            "name": consultant.name if consultant else "",
            "email": consultant.email if consultant else "",
            "role": consultant.role if consultant else None,
            "custom_rate": consultant.custom_rate_per_employee if consultant else None
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
            f_obj.paid_date = item.paid_date or ""
            f_obj.payment_reference = item.payment_reference or ""
            f_obj.notes = item.notes or ""
        else:
            f_obj = SubscriptionFee(
                establishment_id=est_id,
                financial_year=fy,
                month=item.month,
                is_paid=item.is_paid,
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


def _confirm_advance_credit_ledger_row(db: Session, ledger_row: AdvanceCreditLedger, payment_ref: str):
    """Shared confirmation logic used by both the webhook and the manual refresh button.
    Idempotent -- a no-op if the row is already confirmed."""
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

    log_activity(
        db, None, est.id, "advance_payment_received",
        f"Advance subscription payment of ₹{ledger_row.amount} received via Cashfree for {est.name} ({est.code}) "
        f"— Ref: {payment_ref}. New balance: ₹{est.advance_credit_balance}",
        {
            "amount": ledger_row.amount, "payment_reference": payment_ref,
            "old_balance": old_balance, "new_balance": est.advance_credit_balance,
            "code": est.code, "source": "cashfree", "cashfree_order_id": ledger_row.cashfree_order_id
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
        fee_row = db.query(SubscriptionFee).filter(SubscriptionFee.cashfree_order_id == link_id).first()
        if not fee_row:
            print(f"[CashfreeWebhook] No SubscriptionFee found for order_id={link_id}")
            return {"ok": True}
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
        try:
            data_dict = json.loads(est.data) if est.data else {}
            emp_count = len(data_dict.get("master", {}))
            year_count = len(data_dict.get("years", {}))
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

    if current_user.role == "employer" and current_user.max_establishments is not None:
        existing_count = db.query(Establishment).filter(Establishment.user_id == current_user.id).count()
        if existing_count >= current_user.max_establishments:
            raise HTTPException(403, f"You've reached your limit of {current_user.max_establishments} establishment(s). Contact your administrator to increase this.")

    p = Project()
    p.set_establishment(code, name, d.address.strip(), d.coverage_date.strip())

    new_est = Establishment(
        user_id=current_user.id,
        code=code,
        name=name,
        address=d.address.strip(),
        coverage_date=d.coverage_date.strip(),
        custom_rate_per_employee=d.custom_rate_per_employee,
        data=json.dumps(p.to_dict(), ensure_ascii=False)
    )
    db.add(new_est)
    db.commit()
    db.refresh(new_est)

    log_activity(
        db, current_user.id, new_est.id, "establishment_created",
        f"Added establishment {new_est.code} — {new_est.name}",
        {"code": new_est.code, "name": new_est.name, "coverage_date": new_est.coverage_date, "custom_rate": new_est.custom_rate_per_employee}
    )

    return {
        "ok": True,
        "establishment": {
            "id": new_est.id,
            "code": new_est.code,
            "name": new_est.name,
            "address": new_est.address,
            "coverage_date": new_est.coverage_date,
            "custom_rate_per_employee": new_est.custom_rate_per_employee
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
    branch: Optional[str] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    year_stats = []
    total_w = total_c = 0
    for yk in project.year_keys_sorted():
        yr = project.years[yk]
        est = project.build_establishment_for_year(yk)
        emps = project.build_employees_for_year(yk)
        if branch:
            if branch == "Unassigned":
                emps = [e for e in emps if not getattr(project.master.get(e.member_id), 'branch', '')]
            else:
                emps = [e for e in emps if getattr(project.master.get(e.member_id), 'branch', '') == branch]
        
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
    emp_count = len(project.master) if not branch else (
        len([m for m in project.master.values() if not m.branch]) if branch == "Unassigned"
        else len([m for m in project.master.values() if m.branch == branch])
    )
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
        "total_overdue": len(unpaid)
    }


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
        "paid_date": f.paid_date or "",
        "payment_reference": f.payment_reference or "",
        "cashfree_order_id": f.cashfree_order_id or "",
        "notes": f.notes or "",
        "source": source,
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

    return {
        "month": fee_row.month,
        "financial_year": fee_row.financial_year,
        "display_name": display_name,
        "employee_count": fee_row.employee_count,
        "rate_applied": fee_row.rate_applied,
        "amount_due": fee_row.amount_due,
        "is_paid": fee_row.is_paid,
        "is_overdue": overdue and not fee_row.is_paid,
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


# ── Org Structure Endpoints ───────────────────────────────────────────────
@app.get("/api/org-structure")
async def get_org_structure(active: Tuple[Establishment, Project] = Depends(get_active_establishment)):
    est_obj, project = active
    return {
        "branches": getattr(project, "branches", []),
        "divisions": getattr(project, "divisions", []),
        "units": getattr(project, "units", [])
    }

@app.post("/api/org-structure/branches")
async def add_branch(
    d: OrgItemIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Branch name cannot be empty")
    if not hasattr(project, "branches"): project.branches = []
    if name not in project.branches:
        project.branches.append(name)
        save_establishment_project(db, est_obj, project)
    return {"ok": True, "branches": project.branches}

@app.delete("/api/org-structure/branches/{name:path}")
async def delete_branch(
    name: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = name.strip()
    affected = [m for m in project.master.values() if getattr(m, 'branch', '') == name]
    if affected:
        raise HTTPException(400, f"Cannot delete branch '{name}' because it is assigned to {len(affected)} employee(s)")
    if hasattr(project, "branches") and name in project.branches:
        project.branches.remove(name)
        save_establishment_project(db, est_obj, project)
    return {"ok": True, "branches": project.branches}

@app.post("/api/org-structure/divisions")
async def add_division(
    d: OrgItemIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Division name cannot be empty")
    if not hasattr(project, "divisions"): project.divisions = []
    if name not in project.divisions:
        project.divisions.append(name)
        save_establishment_project(db, est_obj, project)
    return {"ok": True, "divisions": project.divisions}

@app.delete("/api/org-structure/divisions/{name:path}")
async def delete_division(
    name: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = name.strip()
    affected = [m for m in project.master.values() if getattr(m, 'division', '') == name]
    if affected:
        raise HTTPException(400, f"Cannot delete division '{name}' because it is assigned to {len(affected)} employee(s)")
    if hasattr(project, "divisions") and name in project.divisions:
        project.divisions.remove(name)
        save_establishment_project(db, est_obj, project)
    return {"ok": True, "divisions": project.divisions}

@app.post("/api/org-structure/units")
async def add_unit(
    d: OrgItemIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = d.name.strip()
    if not name: raise HTTPException(400, "Unit name cannot be empty")
    if not hasattr(project, "units"): project.units = []
    if name not in project.units:
        project.units.append(name)
        save_establishment_project(db, est_obj, project)
    return {"ok": True, "units": project.units}

@app.delete("/api/org-structure/units/{name:path}")
async def delete_unit(
    name: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    name = name.strip()
    affected = [m for m in project.master.values() if getattr(m, 'unit', '') == name]
    if affected:
        raise HTTPException(400, f"Cannot delete unit '{name}' because it is assigned to {len(affected)} employee(s)")
    if hasattr(project, "units") and name in project.units:
        project.units.remove(name)
        save_establishment_project(db, est_obj, project)
    return {"ok": True, "units": project.units}


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
            "branch": getattr(m, "branch", ""),
            "division": getattr(m, "division", ""),
            "unit": getattr(m, "unit", ""),
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
    project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                          d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                          d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                          d.bank_account, d.ifsc, d.higher_epf_ee, d.higher_epf_er,
                          d.branch, d.division, d.unit)
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
    project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                          d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                          d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                          d.bank_account, d.ifsc, d.higher_epf_ee, d.higher_epf_er,
                          d.branch, d.division, d.unit)
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
@app.get("/api/years")
async def list_years(active: Tuple[Establishment, Project] = Depends(get_active_establishment)):
    est_obj, project = active
    rows = []
    for yk in project.year_keys_sorted():
        yr = project.years[yk]
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
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    project.remove_year(key)
    save_establishment_project(db, est_obj, project)
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
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "forms.download")
    est_obj, project = active
    if current_user.role != "superadmin":
        unpaid = get_unpaid_months_for_year(db, est_obj, project, key)
        if unpaid:
            months_str = ", ".join(unpaid)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Download blocked — software subscription fee for {months_str} is unpaid. Contact your administrator to settle platform fees."
            )

    if key not in project.years:
        raise HTTPException(404, "Year not found")
    yr = project.years[key]
    est = project.build_establishment_for_year(key)
    emps = project.build_employees_for_year(key)
    if not emps:
        raise HTTPException(400, "No wage entries for this year")
    
    forms_list = [f.strip() for f in forms.split(',')] if forms else ['3A', '6A', '12A', '5', '10']
    gen = ExcelGenerator(est, emps, project=project, forms_to_generate=forms_list)
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
            if f == '3A': generate_form_3a_pdf(project, key, pdf_path)
            elif f == '6A': generate_form_6a_pdf(project, key, pdf_path)
            elif f == '12A': generate_form_12a_pdf(project, key, pdf_path)
            elif f == '5': generate_form_5_pdf(project, pdf_path)
            elif f == '10': generate_form_10_pdf(project, pdf_path)
            elif f == '9': generate_form_9_pdf(project, pdf_path)
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
        unpaid = get_unpaid_months_for_year(db, est_obj, project, key)
        if unpaid:
            months_str = ", ".join(unpaid)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Download blocked — software subscription fee for {months_str} is unpaid. Contact your administrator to settle platform fees."
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
    gen = ExcelGenerator(est, [emp], project=project, forms_to_generate=forms_list)
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
            orig_build = project.build_employees_for_year
            project.build_employees_for_year = lambda yk: [emp] if yk == key else orig_build(yk)
            try:
                pdf_engine.generate_form_3a_pdf(project, key, pdf_path)
            finally:
                project.build_employees_for_year = orig_build
                
            return FileResponse(pdf_path, filename=pdf_fname, media_type="application/pdf")
        except Exception as e:
            raise HTTPException(500, f"PDF generation failed: {str(e)}")
            
    return FileResponse(path, filename=fname, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


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
        all_unpaid = []
        for yk in project.years.keys():
            all_unpaid.extend(get_unpaid_months_for_year(db, est_obj, project, yk))
        if all_unpaid:
            months_str = ", ".join(sorted(list(set(all_unpaid))))
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Download blocked — software subscription fee for {months_str} is unpaid. Contact your administrator to settle platform fees."
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

@app.get("/api/reports/{year_key}/ecr/{month_idx}")
async def generate_ecr_txt(
    year_key: str,
    month_idx: int,
    branch: Optional[str] = None,
    division: Optional[str] = None,
    unit: Optional[str] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "ecr.download")
    est_obj, project = active
    if branch or division or unit:
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
            if fee_row and not fee_row.is_paid and is_month_overdue(year_key, month_idx) and is_feature_enabled(db, "subscription_enforcement_enabled"):
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

    employees_with_wages = []
    for master_emp in project.master.values():
        if branch:
            if branch == "Unassigned" and master_emp.branch: continue
            elif branch != "Unassigned" and master_emp.branch != branch: continue
        if division and master_emp.division != division: continue
        if unit and master_emp.unit != unit: continue

        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        emp_obj = Employee(
            member_id=master_emp.member_id,
            name=master_emp.name,
            father_name=master_emp.father_name,
            uan=master_emp.uan,
            branch=master_emp.branch,
            division=master_emp.division,
            unit=master_emp.unit
        )
        if entry:
            emp_obj.wages = entry.wages
            emp_obj.gross_wages = entry.gross_wages
            emp_obj.ncp_days = getattr(entry, 'ncp_days', [0]*12)
            emp_obj.higher_epf_ee = master_emp.higher_epf_ee
            emp_obj.higher_epf_er = master_emp.higher_epf_er
            emp_obj.age_crosses_58 = getattr(entry, 'age_crosses_58', False)
        else:
            emp_obj.wages = [0.0] * 12
            emp_obj.ncp_days = [0] * 12
        employees_with_wages.append(emp_obj)

    est = project.build_establishment_for_year(year_key)
    txt = generate_ecr_month(est, employees_with_wages, year_record, month_idx)
    
    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    month_str = MONTHS[month_idx][:3].upper()
    cal_year = calendar_year_for_month(MONTHS[month_idx], year_record.year_from, year_record.year_to)
    
    if branch:
        clean_b = "".join(c for c in branch if c.isalnum() or c in ('_', '-')) or "Unassigned"
        fname = f"{est_code}_ECR_{clean_b}_{month_str}_{cal_year}.txt"
    else:
        fname = f"{est_code}_ECR_{month_str}_{cal_year}.txt"
    return Response(content=txt, media_type="text/plain", headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/api/reports/{year_key}/ecr/{month_idx}/by-branch")
async def get_ecr_by_branch_stats(
    year_key: str,
    month_idx: int,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    require_feature_enabled(db, "branch_feature_enabled", "Branch-wise ECR breakdown")
    est_obj, project = active
    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")
        
    branch_stats = {}
    for master_emp in project.master.values():
        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        if not entry: continue
        w = entry.wages[month_idx] if entry.wages and len(entry.wages) > month_idx else 0
        g = entry.gross_wages[month_idx] if entry.gross_wages and len(entry.gross_wages) > month_idx else 0
        if w > 0 or g > 0:
            b_name = master_emp.branch or "Unassigned"
            if b_name not in branch_stats:
                branch_stats[b_name] = {"branch": b_name, "employee_count": 0, "total_wages": 0}
            branch_stats[b_name]["employee_count"] += 1
            branch_stats[b_name]["total_wages"] += w

    return {"branches": sorted(branch_stats.values(), key=lambda x: x["branch"])}


@app.get("/api/reports/{year_key}/ecr/{month_idx}/zip-by-branch")
async def generate_ecr_zip_by_branch(
    year_key: str,
    month_idx: int,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "ecr.download")
    require_feature_enabled(db, "branch_feature_enabled", "Branch-wise ECR download")
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
            if fee_row and not fee_row.is_paid and is_month_overdue(year_key, month_idx) and is_feature_enabled(db, "subscription_enforcement_enabled"):
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

    branch_emps = {}
    for master_emp in project.master.values():
        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        w = entry.wages[month_idx] if entry and entry.wages and len(entry.wages) > month_idx else 0
        g = entry.gross_wages[month_idx] if entry and entry.gross_wages and len(entry.gross_wages) > month_idx else 0
        if w > 0 or g > 0:
            b_name = master_emp.branch or "Unassigned"
            if b_name not in branch_emps:
                branch_emps[b_name] = []
            emp_obj = Employee(
                member_id=master_emp.member_id,
                name=master_emp.name,
                father_name=master_emp.father_name,
                uan=master_emp.uan,
                branch=master_emp.branch,
                division=master_emp.division,
                unit=master_emp.unit,
                wages=entry.wages if entry else [0]*12,
                gross_wages=entry.gross_wages if entry else [0]*12,
                ncp_days=getattr(entry, 'ncp_days', [0]*12) if entry else [0]*12,
                higher_epf_ee=master_emp.higher_epf_ee,
                higher_epf_er=master_emp.higher_epf_er,
                age_crosses_58=getattr(entry, 'age_crosses_58', False) if entry else False
            )
            branch_emps[b_name].append(emp_obj)

    est = project.build_establishment_for_year(year_key)
    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    month_str = MONTHS[month_idx][:3].upper()
    cal_year = calendar_year_for_month(MONTHS[month_idx], year_record.year_from, year_record.year_to)
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for b_name, emps_list in sorted(branch_emps.items()):
            txt = generate_ecr_month(est, emps_list, year_record, month_idx)
            clean_b = "".join(c for c in b_name if c.isalnum() or c in ('_', '-')) or "Unassigned"
            fname = f"{est_code}_ECR_{clean_b}_{month_str}_{cal_year}.txt"
            zip_file.writestr(fname, txt)
            
    zip_buffer.seek(0)
    zip_fname = f"{est_code}_ECR_Branches_{month_str}_{cal_year}.zip"
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={zip_fname}"})


@app.get("/api/reports/{year_key}/ecr")
async def generate_ecr_zip(
    year_key: str,
    branch: Optional[str] = None,
    division: Optional[str] = None,
    unit: Optional[str] = None,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    require_permission(db, current_user, "ecr.download")
    est_obj, project = active
    if branch or division or unit:
        require_feature_enabled(db, "branch_feature_enabled", "Branch/division/unit filtering")
    if current_user.role != "superadmin":
        unpaid = get_unpaid_months_for_year(db, est_obj, project, year_key)
        if unpaid:
            months_str = ", ".join(unpaid)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Download blocked — software subscription fee for {months_str} is unpaid. Contact your administrator to settle platform fees."
            )

    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")
        
    employees_with_wages = []
    for master_emp in project.master.values():
        if branch:
            if branch == "Unassigned" and master_emp.branch: continue
            elif branch != "Unassigned" and master_emp.branch != branch: continue
        if division and master_emp.division != division: continue
        if unit and master_emp.unit != unit: continue

        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        emp_obj = Employee(
            member_id=master_emp.member_id,
            name=master_emp.name,
            father_name=master_emp.father_name,
            uan=master_emp.uan,
            branch=master_emp.branch,
            division=master_emp.division,
            unit=master_emp.unit
        )
        if entry:
            emp_obj.wages = entry.wages
            emp_obj.gross_wages = entry.gross_wages
            emp_obj.ncp_days = getattr(entry, 'ncp_days', [0]*12)
            emp_obj.higher_epf_ee = master_emp.higher_epf_ee
            emp_obj.higher_epf_er = master_emp.higher_epf_er
            emp_obj.age_crosses_58 = getattr(entry, 'age_crosses_58', False)
        else:
            emp_obj.wages = [0.0] * 12
            emp_obj.ncp_days = [0] * 12
        employees_with_wages.append(emp_obj)

    est = project.build_establishment_for_year(year_key)
    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    clean_b = ("_" + "".join(c for c in branch if c.isalnum() or c in ('_', '-'))) if branch else ""
    
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
