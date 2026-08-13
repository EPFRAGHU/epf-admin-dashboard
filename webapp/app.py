"""
EPF Admin Dashboard — Web Backend
==================================
FastAPI server wrapping epf_engine.py for the EPF Form 3A / 6A
Admin Dashboard web application.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
import json

from .database import SessionLocal, ProjectData, Setting, DATABASE_URL

# Import the existing engine from parent directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from epf_engine import (
    Project, ExcelGenerator, MONTHS, MONTH_FULL,
    SCHEME_PRE_1997, SCHEME_POST_1997,
    REASONS_FOR_LEAVING, SUPERANNUATION_AGE, calc_age_years,
    import_wages_from_excel, generate_form9, import_master_from_excel,
    natural_sort_key, convert_excel_to_pdf, get_wage_ceilings_for_year,
)

# ── App setup ──────────────────────────────────────────────────────────────
app = FastAPI(title="EPF Admin Dashboard", version="1.0")
project = Project()
project_filepath: Optional[str] = None


def _save_settings(filename):
    if DATABASE_URL and SessionLocal:
        try:
            with SessionLocal() as db:
                setting = db.query(Setting).filter(Setting.key == 'last_project').first()
                if setting:
                    setting.value = filename
                else:
                    setting = Setting(key='last_project', value=filename)
                    db.add(setting)
                db.commit()
        except Exception as e:
            print(f"DB Error save_settings: {e}")
    else:
        if os.environ.get("RENDER"):
            raise RuntimeError("Cannot save to JSON on Render. Supabase is required.")
        try:
            settings_path = Path(__file__).resolve().parent.parent / "settings.json"
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump({"last_project": filename}, f)
        except Exception:
            pass

def _load_settings():
    if DATABASE_URL and SessionLocal:
        try:
            with SessionLocal() as db:
                setting = db.query(Setting).filter(Setting.key == 'last_project').first()
                if setting:
                    return setting.value
        except Exception as e:
            print(f"DB Error load_settings: {e}")
    else:
        if os.environ.get("RENDER"):
            raise RuntimeError("Cannot read from JSON on Render. Supabase is required.")
        try:
            settings_path = Path(__file__).resolve().parent.parent / "settings.json"
            if settings_path.exists():
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return settings.get("last_project")
        except Exception:
            pass
    return None

def _get_project_list():
    if DATABASE_URL and SessionLocal:
        try:
            with SessionLocal() as db:
                projects = db.query(ProjectData.filename).all()
                return sorted([p[0] for p in projects])
        except Exception as e:
            print(f"DB Error get_project_list: {e}")
            return []
    else:
        if os.environ.get("RENDER"):
            raise RuntimeError("Cannot read from JSON on Render. Supabase is required.")
        parent = Path(__file__).resolve().parent.parent
        return sorted([f.name for f in parent.iterdir() if f.name.lower().endswith(".epfproj.json")])

def _load_project_data(filename):
    if DATABASE_URL and SessionLocal:
        try:
            with SessionLocal() as db:
                project_row = db.query(ProjectData).filter(ProjectData.filename == filename).first()
                if project_row:
                    return json.loads(project_row.data)
        except Exception as e:
            print(f"DB Error load_project_data: {e}")
    else:
        if os.environ.get("RENDER"):
            raise RuntimeError("Cannot read from JSON on Render. Supabase is required.")
        path = Path(__file__).resolve().parent.parent / filename
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
    return None

def _save_project_data(filename, data_dict):
    if DATABASE_URL and SessionLocal:
        try:
            with SessionLocal() as db:
                project_row = db.query(ProjectData).filter(ProjectData.filename == filename).first()
                if project_row:
                    project_row.data = json.dumps(data_dict, ensure_ascii=False)
                else:
                    project_row = ProjectData(filename=filename, data=json.dumps(data_dict, ensure_ascii=False))
                    db.add(project_row)
                db.commit()
        except Exception as e:
            print(f"DB Error save_project_data: {e}")
    else:
        if os.environ.get("RENDER"):
            raise RuntimeError("Cannot save to JSON on Render. Supabase is required.")
        path = Path(__file__).resolve().parent.parent / filename
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data_dict, f, indent=2, ensure_ascii=False)

def _auto_load():
    global project_filepath
    last = _load_settings()
    if last:
        data = _load_project_data(last)
        if data:
            project.load_from_dict(data)
            project_filepath = last
            print(f"  [OK] Loaded from settings: {last}")
            return

    for f in _get_project_list():
        try:
            data = _load_project_data(f)
            if data:
                project.load_from_dict(data)
                project_filepath = f
                print(f"  [OK] Loaded: {f}")
                print(f"    {project.name} ({project.code}) - "
                      f"{len(project.master)} employees, {len(project.years)} years")
                return
        except Exception as e:
            print(f"  [ERR] {f}: {e}")
    print("  No .epfproj.json found — starting empty.")

_auto_load()

# ── Static files ───────────────────────────────────────────────────────────
WEB = Path(__file__).resolve().parent
app.mount("/css", StaticFiles(directory=str(WEB / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB / "js")), name="js")


@app.get("/", response_class=HTMLResponse)
async def index():
    return (WEB / "index.html").read_text(encoding="utf-8")


def _save():
    global project_filepath
    if not project_filepath:
        safe_name = project.name.replace("/", "-").replace("\\", "-").strip() if project.name else "Default_Establishment"
        filename = f"{safe_name}_project.epfproj.json"
        project_filepath = filename
        _save_settings(filename)
    try:
        _save_project_data(project_filepath, project.to_dict())
    except Exception:
        pass


def _is_valid_for_establishment(member_id: str, est_code: str) -> bool:
    if not est_code or not member_id or member_id.startswith('__UAN__'):
        return True
    est_clean = "".join(c for c in est_code if c.isalnum())[:15].upper()
    if not est_clean:
        return True
    
    # EPFO full member IDs are typically 22 chars (15 est code + 7 member id)
    if len(member_id) >= len(est_clean):
        return member_id.upper().startswith(est_clean)
    return True

def _is_valid_uan(uan) -> bool:
    if not uan:
        return False
    uan_str = str(uan).strip()
    return len(uan_str) == 12 and uan_str.isdigit()

# ── Pydantic schemas ──────────────────────────────────────────────────────
class EstablishmentIn(BaseModel):
    code: str
    name: str
    address: str
    coverage_date: str = ""


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
    higher_epf: bool = False
    age_crosses_58: bool = False

class BulkMonthWageUpdate(BaseModel):
    member_id: str
    gross_wage: float
    epf_wage: float
    ncp_days: int
    higher_epf: bool = False
    age_crosses_58: bool = False

class BulkMonthWagesIn(BaseModel):
    month_idx: int
    employees: List[BulkMonthWageUpdate]


# ── Dashboard ─────────────────────────────────────────────────────────────
@app.get("/api/dashboard")
async def dashboard():
    year_stats = []
    total_w = total_c = 0
    for yk in project.year_keys_sorted():
        yr = project.years[yk]
        est = project.build_establishment_for_year(yk)
        emps = project.build_employees_for_year(yk)
        
        # Monthly accumulators for the new table
        monthly_stats = []
        months = ['Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb']
        year_from_int = int(yr.year_from)
        
        yw = ywt = yet = 0
        
        for i in range(12):
            m_emp_count = 0
            m_gross = 0
            m_epf_wage = 0
            m_eps_wage = 0
            m_worker = 0
            m_employer = 0
            
            for emp in emps:
                wages = emp.wages[i] if emp.wages and len(emp.wages) > i else 0
                gross = emp.gross_wages[i] if emp.gross_wages and len(emp.gross_wages) > i else 0
                
                # Use the existing month_rows function to get precise calculations for this month
                mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                                     est.employer_epf_rate, est.employer_eps_rate,
                                     wage_ceilings=get_wage_ceilings_for_year(yr.year_from))
                
                _, w_epf, w_eps, w_tot, e_epf, e_eps, e_tot = mrows[i]
                
                ceiling = get_wage_ceilings_for_year(yr.year_from)[i]
                if est.worker_eps_rate == 0:
                    eps_wage = 0 if emp.age_crosses_58 else min(wages, ceiling)
                else:
                    eps_wage = wages
                    
                if wages > 0 or gross > 0 or (hasattr(emp, 'ncp_days') and emp.ncp_days and emp.ncp_days[i] < 31):
                    m_emp_count += 1
                    
                m_gross += gross
                m_epf_wage += wages
                m_eps_wage += eps_wage
                m_worker += w_tot
                m_employer += e_tot
            
            month_year = f"{months[i]} {year_from_int if i < 10 else year_from_int + 1}"
            monthly_stats.append({
                "month": month_year,
                "employees": m_emp_count,
                "gross_wages": m_gross,
                "epf_wages": m_epf_wage,
                "eps_wages": m_eps_wage,
                "worker_share": m_worker,
                "employer_share": m_employer,
                "total": m_worker + m_employer
            })
            
            yw += m_epf_wage
            ywt += m_worker
            yet += m_employer

        total_w += yw; total_c += ywt + yet
        
        # Calculate yearly totals from the monthly stats
        year_total_gross = sum(m["gross_wages"] for m in monthly_stats)
        year_total_epf = sum(m["epf_wages"] for m in monthly_stats)
        year_total_eps = sum(m["eps_wages"] for m in monthly_stats)
        year_total_worker = sum(m["worker_share"] for m in monthly_stats)
        year_total_employer = sum(m["employer_share"] for m in monthly_stats)
        year_total = year_total_worker + year_total_employer
        
        year_stats.append({
            "key": yk, "label": yr.long_label,
            "employees": len(emps), "wages": yw,
            "worker": ywt, "employer": yet,
            "total": ywt + yet,
            "scheme": "Post-1997" if yr.is_post_1997 else "Pre-1997",
            "monthly_stats": monthly_stats,
            "totals": {
                "gross_wages": year_total_gross,
                "epf_wages": year_total_epf,
                "eps_wages": year_total_eps,
                "worker_share": year_total_worker,
                "employer_share": year_total_employer,
                "total": year_total
            }
        })
    return {
        "establishment": {"code": project.code, "name": project.name,
                          "address": project.address},
        "employees": len(project.master),
        "years": len(project.years),
        "total_wages": total_w,
        "total_contributions": total_c,
        "year_stats": year_stats,
    }


@app.get("/api/dashboard/month_employees/{key}/{month_index}")
async def dashboard_month_employees(key: str, month_index: int):
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
        
        if wages > 0 or gross > 0 or (hasattr(emp, 'ncp_days') and emp.ncp_days and emp.ncp_days[month_index] < 31):
            mrows = emp.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                                 est.employer_epf_rate, est.employer_eps_rate,
                                 wage_ceilings=get_wage_ceilings_for_year(yr.year_from))
            
            _, w_epf, w_eps, w_tot, e_epf, e_eps, e_tot = mrows[month_index]
            
            ceiling = get_wage_ceilings_for_year(yr.year_from)[month_index]
            if est.worker_eps_rate == 0:
                eps_wage = 0 if emp.age_crosses_58 else min(wages, ceiling)
            else:
                eps_wage = wages
                
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


# ── Establishment ─────────────────────────────────────────────────────────
@app.get("/api/establishment")
async def get_est():
    return {"code": project.code, "name": project.name,
            "address": project.address, "coverage_date": project.coverage_date}


@app.put("/api/establishment")
async def put_est(d: EstablishmentIn):
    project.set_establishment(d.code, d.name, d.address, d.coverage_date)
    _save()
    return {"ok": True}


# ── Employees ─────────────────────────────────────────────────────────────
@app.get("/api/employees")
async def list_employees():
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
        })
    return {"employees": rows, "total": len(rows)}


@app.post("/api/employees")
async def add_employee(d: EmployeeIn):
    if project.get_master(d.member_id):
        raise HTTPException(400, f"Account {d.member_id} already exists")
    project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                          d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                          d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                          d.bank_account, d.ifsc)
    _save()
    return {"ok": True}


@app.put("/api/employees/{acc:path}")
async def edit_employee(acc: str, d: EmployeeIn):
    if d.member_id != acc:
        if project.get_master(d.member_id):
            raise HTTPException(400, f"Account {d.member_id} already exists")
        project.rename_account(acc, d.member_id)
    project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                          d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                          d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                          d.bank_account, d.ifsc)
    _save()
    return {"ok": True}


@app.delete("/api/employees/{acc:path}")
async def del_employee(acc: str):
    if not project.get_master(acc):
        raise HTTPException(404, "Not found")
    project.remove_master(acc)
    _save()
    return {"ok": True}


@app.post("/api/employees/import")
async def import_master(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower() or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(await file.read()); tmp.close()
        records, warnings = import_master_from_excel(tmp.name)
        
        imported_count = 0
        skipped_count = 0
        
        existing_uans = {m.uan for m in project.master.values() if m.uan}
        existing_ids = {m.member_id for m in project.master.values() if m.member_id}
        
        for r in records:
            member_id = r.get("member_id", "") or r.get("account_no", "")
            uan = r.get("uan", "")
            # Need to normalize the extracted member_id to match how it's stored
            from epf_engine import normalize_member_id
            norm_id = normalize_member_id(member_id)
            
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
            
        _save()
        return {"ok": True, "imported": imported_count, "skipped": skipped_count, "warnings": warnings[:20]}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        os.unlink(tmp.name)

# ── Years ─────────────────────────────────────────────────────────────────
@app.get("/api/years")
async def list_years():
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
async def add_year(d: YearIn):
    key = f"{d.year_from}-{d.year_to[-2:]}"
    if key in project.years:
        raise HTTPException(400, f"Year {key} already exists")
    project.add_year(d.year_from, d.year_to, d.scheme,
                     d.epf_rate, d.fpf_rate,
                     d.emp_epf_rate, d.er_epf_rate, d.er_eps_rate)
    _save()
    return {"ok": True, "key": key}


@app.put("/api/years/{key}")
async def edit_year(key: str, d: YearRatesIn):
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    project.update_year_rates(key, d.scheme, d.epf_rate, d.fpf_rate,
                              d.emp_epf_rate, d.er_epf_rate, d.er_eps_rate)
    _save()
    return {"ok": True}


@app.delete("/api/years/{key}")
async def del_year(key: str):
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    project.remove_year(key)
    _save()
    return {"ok": True}


@app.post("/api/years/bulk")
async def bulk_add_years(d: dict):
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
        _save()
    return {"ok": True, "added": added}

# ── Wages ─────────────────────────────────────────────────────────────────
@app.get("/api/years/{key}/wages")
async def get_wages(key: str):
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
            "wages": emp.wages,
            "gross_wages": emp.gross_wages,
            "ncp_days": getattr(emp, 'ncp_days', [0]*12),
            "higher_epf": emp.higher_epf,
            "age_crosses_58": emp.age_crosses_58,
            "months": [{"m": MONTHS[i], "w": r[0],
                        "we": r[1], "ws": r[2], "wt": r[3],
                        "ee": r[4], "es": r[5], "et": r[6]}
                       for i, r in enumerate(mrows)],
            "totals": {"w": wt, "we": we, "ws": ws, "wt": wto,
                       "ee": ee, "es": es, "et": eto},
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
        "grand": {"w": g[0], "we": g[1], "ws": g[2], "wt": g[3],
                  "ee": g[4], "es": g[5], "et": g[6]},
        "count": len(rows),
    }


@app.post("/api/years/{key}/wages")
async def put_wages(key: str, d: WageIn):
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    if len(d.wages) != 12:
        raise HTTPException(400, "Need exactly 12 wage values")
    # Auto-create master entry if needed
    if not project.get_master(d.member_id):
        raise HTTPException(404, f"Employee {d.member_id} not in master")
    
    gross_wages = d.gross_wages if d.gross_wages and len(d.gross_wages) == 12 else d.wages.copy()
    capped_wages = [min(w, g) for w, g in zip(d.wages, gross_wages)]
    ncp_days = d.ncp_days if d.ncp_days and len(d.ncp_days) == 12 else [0] * 12
    project.upsert_entry(key, d.member_id, capped_wages, gross_wages=gross_wages, ncp_days=ncp_days, higher_epf=d.higher_epf, age_crosses_58=d.age_crosses_58)
    _save()
    return {"ok": True}


@app.post("/api/years/{key}/wages/bulk_month")
async def bulk_month_wages(key: str, d: BulkMonthWagesIn):
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    
    if not (0 <= d.month_idx <= 11):
        raise HTTPException(400, "Invalid month index")

    for emp_update in d.employees:
        # Check if master exists, if not continue or create? We assume it exists because they were rendered.
        if not project.get_master(emp_update.member_id):
            continue
            
        # Get existing wages for this employee in this year, or create default 0 arrays
        yr = project.years[key]
        existing_emp = next((e for e in yr.entries if e.member_id == emp_update.member_id), None)
        
        if existing_emp:
            wages_arr = existing_emp.wages.copy()
            gross_wages_arr = existing_emp.gross_wages.copy()
            ncp_days_arr = existing_emp.ncp_days.copy()
        else:
            wages_arr = [0.0] * 12
            gross_wages_arr = [0.0] * 12
            ncp_days_arr = [0] * 12
            
        capped_epf_wage = min(emp_update.epf_wage, emp_update.gross_wage)
        
        # Update just the specific month index
        wages_arr[d.month_idx] = capped_epf_wage
        gross_wages_arr[d.month_idx] = emp_update.gross_wage
        ncp_days_arr[d.month_idx] = emp_update.ncp_days
        
        project.upsert_entry(
            key, 
            emp_update.member_id, 
            wages_arr, 
            gross_wages=gross_wages_arr, 
            ncp_days=ncp_days_arr, 
            higher_epf=emp_update.higher_epf, 
            age_crosses_58=emp_update.age_crosses_58
        )
        
    _save()
    return {"ok": True, "count": len(d.employees)}


@app.delete("/api/years/{key}/wages/{acc:path}")
async def del_wages(key: str, acc: str):
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    yr = project.years[key]
    idx = next((i for i, e in enumerate(yr.entries) if e.member_id == acc), None)
    if idx is None:
        raise HTTPException(404, "Entry not found")
    project.remove_entry(key, idx)
    _save()
    return {"ok": True}


@app.delete("/api/years/{key}/wages")
async def del_all_wages(key: str):
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    project.years[key].entries.clear()
    _save()
    return {"ok": True}


# ── Reports ───────────────────────────────────────────────────────────────
@app.get("/api/reports/{key}")
async def generate_report(key: str, format: str = 'excel', forms: str = ''):
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
            convert_excel_to_pdf(path, pdf_path)
            return FileResponse(pdf_path, filename=pdf_fname, media_type="application/pdf")
        except Exception as e:
            raise HTTPException(500, f"PDF conversion failed: {str(e)}")
            
    return FileResponse(path, filename=fname,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/reports/{key}/employee/{member_id}")
async def generate_employee_report(key: str, member_id: str, format: str = 'pdf', forms: str = '3A'):
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    est = project.build_establishment_for_year(key)
    emps = project.build_employees_for_year(key)
    
    from epf_engine import normalize_member_id
    acc = normalize_member_id(member_id)
    emp = next((e for e in emps if e.member_id == acc), None)
    if not emp:
        raise HTTPException(404, "Employee not found in this year")
    
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
            convert_excel_to_pdf(path, pdf_path)
            return FileResponse(pdf_path, filename=pdf_fname, media_type="application/pdf")
        except Exception as e:
            raise HTTPException(500, f"PDF conversion failed: {str(e)}")
            
    return FileResponse(path, filename=fname,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/reports/form9/download")
async def report_form9(format: str = 'excel'):
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
            convert_excel_to_pdf(path, pdf_path)
            return FileResponse(pdf_path, filename=pdf_fname, media_type="application/pdf")
        except Exception as e:
            raise HTTPException(500, f"PDF conversion failed: {str(e)}")
            
    return FileResponse(path, filename=fname,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

import zipfile
import io

@app.get("/api/reports/{year_key}/ecr/{month_idx}")
async def generate_ecr_txt(year_key: str, month_idx: int):
    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")
        
    from epf_engine import generate_ecr_month, MONTHS, calendar_year_for_month, Employee
    
    employees_with_wages = []
    for master_emp in project.master.values():
        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        emp_obj = Employee(
            member_id=master_emp.member_id,
            name=master_emp.name,
            father_name=master_emp.father_name,
            uan=master_emp.uan
        )
        if entry:
            emp_obj.wages = entry.wages
            emp_obj.gross_wages = entry.gross_wages
            emp_obj.ncp_days = getattr(entry, 'ncp_days', [0]*12)
            emp_obj.higher_epf = entry.higher_epf
            emp_obj.age_crosses_58 = entry.age_crosses_58
        else:
            emp_obj.wages = [0.0] * 12
            emp_obj.ncp_days = [0] * 12
        employees_with_wages.append(emp_obj)

    est = project.build_establishment_for_year(year_key)
    txt = generate_ecr_month(est, employees_with_wages, year_record, month_idx)
    
    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    month_str = MONTHS[month_idx][:3].upper()
    cal_year = calendar_year_for_month(MONTHS[month_idx], year_record.year_from, year_record.year_to)
    
    fname = f"{est_code}_ECR_{month_str}_{cal_year}.txt"
    return Response(content=txt, media_type="text/plain", headers={"Content-Disposition": f"attachment; filename={fname}"})

@app.get("/api/reports/{year_key}/ecr")
async def generate_ecr_zip(year_key: str):
    year_record = project.years.get(year_key)
    if not year_record:
        raise HTTPException(404, "Year not found")
        
    from epf_engine import generate_ecr_month, MONTHS, calendar_year_for_month, Employee
    
    employees_with_wages = []
    for master_emp in project.master.values():
        entry = next((e for e in year_record.entries if e.member_id == master_emp.member_id), None)
        emp_obj = Employee(
            member_id=master_emp.member_id,
            name=master_emp.name,
            father_name=master_emp.father_name,
            uan=master_emp.uan
        )
        if entry:
            emp_obj.wages = entry.wages
            emp_obj.gross_wages = entry.gross_wages
            emp_obj.ncp_days = getattr(entry, 'ncp_days', [0]*12)
            emp_obj.higher_epf = entry.higher_epf
            emp_obj.age_crosses_58 = entry.age_crosses_58
        else:
            emp_obj.wages = [0.0] * 12
            emp_obj.ncp_days = [0] * 12
        employees_with_wages.append(emp_obj)

    est = project.build_establishment_for_year(year_key)
    est_code = "".join(c for c in est.code if c.isalnum())[:15] or "EST"
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for idx in range(12):
            txt = generate_ecr_month(est, employees_with_wages, year_record, idx)
            month_str = MONTHS[idx][:3].upper()
            cal_year = calendar_year_for_month(MONTHS[idx], year_record.year_from, year_record.year_to)
            fname = f"{est_code}_ECR_{month_str}_{cal_year}.txt"
            zip_file.writestr(fname, txt)
            
    zip_buffer.seek(0)
    zip_fname = f"{est_code}_ECR_{year_record.year_from}_{year_record.year_to}.zip"
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename={zip_fname}"})

# ── Bulk Import ───────────────────────────────────────────────────────────
import uuid
from typing import List

BULK_IMPORT_CACHE = {}

@app.post("/api/wages/bulk_analyze")
async def bulk_analyze_wages(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower() or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    tmp.write(await file.read()); tmp.close()
    
    try:
        from epf_engine import get_excel_sheet_names
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
async def bulk_import_wages(req: BulkImportReq):
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
                
                from epf_engine import SCHEME_PRE_1997, SCHEME_POST_1997
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
        
        _save()
        return {"ok": True, "imported": total_imported, "warnings": all_warnings}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        os.unlink(filepath)
        del BULK_IMPORT_CACHE[req.token]

# ── Import ────────────────────────────────────────────────────────────────
@app.post("/api/import/{key}")
async def import_wages(key: str, import_type: str = Form("yearly"), month_idx: int = Form(-1), file: UploadFile = File(...)):
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
        _save()
        return {"ok": True, "imported": len(records), "warnings": warnings[:20]}
    finally:
        os.unlink(tmp.name)


# ── Save ──────────────────────────────────────────────────────────────────
@app.post("/api/save")
async def save_project():
    global project_filepath
    if not project_filepath:
        safe_name = project.name.replace("/", "-").replace("\\", "-").strip() if project.name else "Default_Establishment"
        filename = f"{safe_name}_project.epfproj.json"
        project_filepath = filename
        _save_settings(filename)
    try:
        _save_project_data(project_filepath, project.to_dict())
    except Exception:
        pass
    return {"ok": True, "file": project_filepath}


# ── Projects ──────────────────────────────────────────────────────────────
@app.get("/api/projects")
async def list_projects():
    files = _get_project_list()
    active = project_filepath if project_filepath else None
    return {"projects": files, "active": active}

@app.post("/api/projects/switch")
async def switch_project(d: dict):
    global project, project_filepath
    filename = d.get("filename")
    
    data = _load_project_data(filename)
    if not data:
        raise HTTPException(404, "Project not found")
        
    new_proj = Project()
    new_proj.load_from_dict(data)
    project = new_proj
    project_filepath = filename
    _save_settings(filename)
    return {"ok": True}

@app.post("/api/projects/new")
async def new_project(d: dict):
    global project, project_filepath
    name = d.get("name", "New Establishment")
    code = d.get("code", "")
    address = d.get("address", "")
    coverage_date = d.get("coverage_date", "")
    
    safe_name = name.replace("/", "-").replace("\\", "-").strip()
    filename = f"{safe_name}_project.epfproj.json"
    
    if _load_project_data(filename):
        raise HTTPException(400, "Project already exists")
    
    new_proj = Project()
    new_proj.name = name
    new_proj.code = code
    new_proj.address = address
    new_proj.coverage_date = coverage_date
    _save_project_data(filename, new_proj.to_dict())
    
    project = new_proj
    project_filepath = filename
    _save_settings(filename)
    return {"ok": True, "filename": filename}

@app.post("/api/projects/update_details")
async def update_project_details(d: dict):
    filename = d.get("filename")
    if not filename:
        raise HTTPException(400, "Filename required")
        
    data = _load_project_data(filename)
    if not data:
        raise HTTPException(404, "Project not found")
        
    data["code"] = d.get("code", data.get("code", ""))
    data["name"] = d.get("name", data.get("name", ""))
    data["address"] = d.get("address", data.get("address", ""))
    data["coverage_date"] = d.get("coverage_date", data.get("coverage_date", ""))
    
    _save_project_data(filename, data)
    
    # If it's the currently active project, update it in memory too
    global project, project_filepath
    if project_filepath == filename:
        project.load_from_dict(data)
        
    return {"ok": True}


# ── All Establishments ────────────────────────────────────────────────────────
@app.get("/api/all_establishments")
async def get_all_establishments():
    projects = _get_project_list()
    result = []
    for filename in projects:
        data = _load_project_data(filename)
        if not data:
            continue
        
        created_at = data.get("created_at")
        if not created_at:
            created_at = datetime.now().strftime("%d-%m-%Y")
            
        wage_summary = {}
        years_data = data.get("years", {})
        for y_key, y_record in years_data.items():
            months_entered = [False] * 12
            for entry in y_record.get("entries", []):
                wages = entry.get("wages", [])
                for i in range(12):
                    if i < len(wages) and (wages[i] or 0) > 0:
                        months_entered[i] = True
            wage_summary[y_key] = months_entered
            
        result.append({
            "filename": filename,
            "code": data.get("code", ""),
            "name": data.get("name", ""),
            "address": data.get("address", ""),
            "coverage_date": data.get("coverage_date", ""),
            "created_at": created_at,
            "is_active": data.get("is_active", True),
            "wage_summary": wage_summary
        })
    return {"establishments": result}

@app.post("/api/establishments/toggle_status")
async def toggle_establishment_status(d: dict):
    filename = d.get("filename")
    if not filename:
        raise HTTPException(400, "Filename required")
        
    data = _load_project_data(filename)
    if not data:
        raise HTTPException(404, "Project not found")
        
    data["is_active"] = not data.get("is_active", True)
    _save_project_data(filename, data)
    return {"ok": True, "is_active": data["is_active"]}


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
    print("\n--- EPF Admin Dashboard ---")
    print("=" * 40)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
