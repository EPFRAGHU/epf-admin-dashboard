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
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query, Header, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

# Database and models
from .database import (
    SessionLocal, engine, get_db, Base,
    User, Establishment, Payment, ProjectData, Setting, DATABASE_URL
)

# Auth helpers and dependencies
from .auth import (
    hash_password, verify_password, create_access_token, decode_access_token,
    get_current_user, get_superadmin, get_active_establishment, save_establishment_project
)

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

# ── App setup ──────────────────────────────────────────────────────────────
app = FastAPI(title="EPF Admin Dashboard", version="2.0.0")

WEB = Path(__file__).resolve().parent
app.mount("/css", StaticFiles(directory=str(WEB / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB / "js")), name="js")


# ── Startup Data Migration & Seed ──────────────────────────────────────────
def _run_startup_migrations():
    if not SessionLocal:
        return
    with SessionLocal() as db:
        # 1. Seed Superadmin
        superadmin = db.query(User).filter(User.role == "superadmin").first()
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
            db.refresh(superadmin)
            print(f"  [OK] Seeded superadmin: {s_email}")

        # 2. Seed Default Consultant
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

class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None

class EstablishmentIn(BaseModel):
    code: str
    name: str
    address: str = ""
    coverage_date: str = ""

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
    return {
        "ok": True,
        "token": token,
        "user": {
            "id": user.id,
            "serial_no": user.serial_no,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "mobile": user.mobile
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
        "total_establishments": total_establishments,
        "total_employees": total_employees,
        "payment_compliance_pct": compliance_pct,
        "current_financial_year": current_fy
    }


@app.get("/api/admin/users")
async def admin_list_users(
    admin: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    users = db.query(User).filter(User.role == "consultant").order_by(User.serial_no.asc()).all()
    rows = []
    for u in users:
        est_count = db.query(Establishment).filter(Establishment.user_id == u.id).count()
        rows.append({
            "id": u.id,
            "serial_no": u.serial_no,
            "name": u.name,
            "mobile": u.mobile or "—",
            "email": u.email,
            "establishment_count": est_count,
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

    # Next serial number
    max_serial = db.query(func.max(User.serial_no)).scalar() or 0
    next_serial = max_serial + 1

    new_user = User(
        serial_no=next_serial,
        name=d.name.strip(),
        mobile=d.mobile.strip() if d.mobile else "",
        email=email,
        password_hash=hash_password(d.password),
        role="consultant",
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "ok": True,
        "user": {
            "id": new_user.id,
            "serial_no": new_user.serial_no,
            "name": new_user.name,
            "email": new_user.email,
            "mobile": new_user.mobile,
            "role": new_user.role
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
        raise HTTPException(400, f"Cannot delete consultant because they have {est_count} establishment(s). Delete or reassign their establishments first.")

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

        rows.append({
            "id": est.id,
            "code": est.code,
            "name": est.name,
            "address": est.address or "—",
            "coverage_date": est.coverage_date or "—",
            "employee_count": emp_count,
            "created_at": est.created_at.strftime("%d-%m-%Y") if est.created_at else "—"
        })

    return {"establishments": rows, "user": {"id": user.id, "name": user.name, "email": user.email}}


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
    return {"ok": True}


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
    code = d.code.strip().upper()
    name = d.name.strip()
    if not code or not name:
        raise HTTPException(400, "Establishment Code and Name are required")

    p = Project()
    p.set_establishment(code, name, d.address.strip(), d.coverage_date.strip())

    new_est = Establishment(
        user_id=current_user.id,
        code=code,
        name=name,
        address=d.address.strip(),
        coverage_date=d.coverage_date.strip(),
        data=json.dumps(p.to_dict(), ensure_ascii=False)
    )
    db.add(new_est)
    db.commit()
    db.refresh(new_est)

    return {
        "ok": True,
        "establishment": {
            "id": new_est.id,
            "code": new_est.code,
            "name": new_est.name,
            "address": new_est.address,
            "coverage_date": new_est.coverage_date
        }
    }


@app.delete("/api/establishments/{est_id}")
async def delete_establishment(
    est_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
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
    a22_amt = max(round(wages_total * a22_rate / 100), ACCOUNT_22_MIN) if wages_total > 0 else 0
    
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
        "coverage_date": project.coverage_date
    }


@app.put("/api/establishment")
async def put_est(
    d: EstablishmentIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    project.set_establishment(d.code, d.name, d.address, d.coverage_date)
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


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
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if project.get_master(d.member_id):
        raise HTTPException(400, f"Account {d.member_id} already exists")
    project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                          d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                          d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                          d.bank_account, d.ifsc, d.higher_epf_ee, d.higher_epf_er,
                          d.branch, d.division, d.unit)
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


@app.put("/api/employees/{acc:path}")
async def edit_employee(
    acc: str,
    d: EmployeeIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
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
    results = []
    
    for i, month_label in enumerate(MONTHS):
        wages_total = sum(rows[i][0] for rows in all_month_rows)
        ee_total = sum(rows[i][1] for rows in all_month_rows)
        er_total = sum(rows[i][4] for rows in all_month_rows)
        a10_total = sum(rows[i][5] for rows in all_month_rows)
        members = sum(1 for rows in all_month_rows if rows[i][0] > 0)
        
        row_data = compute_remittance_row(yr, est, i, wages_total, ee_total, er_total, a10_total, members)
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
    db: Session = Depends(get_db)
):
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
    return {"ok": True}


@app.post("/api/years/{key}/wages/bulk_month")
async def bulk_month_wages(
    key: str,
    d: BulkMonthWagesIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
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
    return {"ok": True, "count": len(d.employees)}


@app.delete("/api/years/{key}/wages/{acc:path}")
async def del_wages(
    key: str,
    acc: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
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
    db: Session = Depends(get_db)
):
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    project.years[key].entries.clear()
    save_establishment_project(db, est_obj, project)
    return {"ok": True}


# ── Reports & Form Exports ─────────────────────────────────────────────────
@app.get("/api/reports/employee_wage_history/{member_id:path}")
async def report_employee_wage_history(
    member_id: str,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
    master = project.get_master(member_id)
    if not master:
        raise HTTPException(404, "Employee not found")

    years_data = []
    for yk in project.year_keys_sorted():
        yr = project.years[yk]
        emps = project.build_employees_for_year(yk)
        emp = next((e for e in emps if e.member_id == member_id), None)
        
        wages = emp.wages if (emp and emp.wages) else [0] * 12
        total_wages = sum((int(w) if w else 0) for w in wages)
        
        years_data.append({
            "year": f"{yr.year_from}-{yr.year_to}",
            "wages": wages,
            "total": total_wages
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


@app.get("/api/reports/{key}")
def generate_report(
    key: str,
    format: str = 'excel',
    forms: str = '',
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
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
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
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
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
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
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
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
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
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
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
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
    active: Tuple[Establishment, Project] = Depends(get_active_establishment)
):
    est_obj, project = active
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
