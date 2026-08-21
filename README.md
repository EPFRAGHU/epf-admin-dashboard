# EPF Admin Dashboard

A multi-tenant statutory compliance platform for Indian EPFO (Employees' Provident Fund) filings. It computes Pre-1997/Post-1997 scheme contributions, tracks monthly wages/NCP days, and renders official government forms (Form 3A, 6A, 12A, 9, 5, 10) plus EPFO v3.0 ECR text files — with a built-in subscription-billing layer to charge consultants/employers for platform usage.

---

## Architecture

```
Web UI (webapp/index.html, webapp/js/*.js — vanilla JS SPA, no build step)
        │ HTTP/JSON, JWT bearer auth
FastAPI backend — webapp/app.py (single router file, all endpoints)
        │
        ├── webapp/auth.py     — JWT issue/verify, role/ownership dependencies
        ├── webapp/database.py — SQLAlchemy models + engine/session setup
        │
        ├── epf_engine.py      — statutory calc engine: Project/Establishment/Employee/
        │                        YearRecord classes, contribution formulas, wage-ceiling
        │                        rules, openpyxl ExcelGenerator (Form 3A/6A/12A/9/5/10),
        │                        ECR v3.0 text generator
        └── pdf_engine.py      — direct ReportLab PDF generation for the same forms
```

Deployed on Render (Postgres via Supabase/Neon); `python sync_to_supabase.py && uvicorn webapp.app:app` is the production start command.

---

## Multi-tenancy

Three roles, enforced per-request via ownership checks in `webapp/auth.py` / `webapp/app.py`:

- **Superadmin** — sees and manages every consultant, employer, and establishment; owns platform-wide settings (rates, billing defaults, feature flags, UPI payment config, signup approvals).
- **Consultant** — a payroll/compliance professional managing establishments on behalf of one or more employers; can hold their own custom per-employee rate and a default billing mode applied to establishments they own.
- **Employer** — an establishment owner managing their own filings directly, without a consultant intermediary.

A three-layer permission system (`FeatureFlag`, `RolePermission`, `UserPermissionOverride` in `webapp/database.py`) lets a superadmin turn features on/off globally, per role (consultant vs. employer), or per individual user.

New accounts arrive either via superadmin-created logins or the public `/signup` page, which queues a `SignupRequest` for superadmin approval. Google OAuth is available as an additional sign-in method (login only, not for self-service signup).

### Branch / Division / Unit hierarchy

Employees within an establishment can optionally be organized into a nested **Branch → Division → Unit** structure (behind the `branch_feature_enabled` flag), used to scope employee lists, filter ECR generation, and produce by-branch ZIP downloads. Establishments that don't use it behave exactly as flat employee lists.

---

## Core EPF compliance features

- **Establishment management** — create/switch/back up multiple establishments (name, code, address, sub-code, scheme, coverage date).
- **Employee master** — full demographic + UAN (12-digit, validated) records, superannuation tracking (EPS ceases at age 58), Excel import.
- **Monthly wage entry** — per-employee, per-month EPF/EPS/EDLI wage capture with NCP days, "copy from previous month," and DOJ/DOE-aware visibility (an employee only appears in the months they were actually employed).
- **Financial years & wage ceilings** — date-dependent statutory ceilings applied automatically (₹15,000 post 01/09/2014, ₹6,500 for 2001–2014, ₹5,000 for 1997–2001); see `get_wage_ceilings_for_year` in `epf_engine.py`.
- **Challan / remittance tracking** — Form 12A grid with multi-challan support (TRRN, CRRN, payment date, amount, bank) and A/C 1/2/10/21/22 auto-computation.
- **Statutory reports** — Form 3A (individual annual statement), Form 6A (consolidated annual statement), Form 12A (remittance statement), Form 9 (register of members), Form 5 & 10 (new joinees / exits) — as Excel (openpyxl) or direct PDF (ReportLab).
- **ECR v3.0** — official `#~#`-delimited EPFO Unified Portal text file generator.
- **Employee wage history** — cross-year EE/ER/EPS ledger per employee, browser print or server-side PDF.

---

## Subscription billing

Distinct from EPF statutory remittance tracking (`Payment`/TRRN/CRRN) — this is what the platform charges consultants/employers for using it.

- **Per-employee billing** — a resolved rate (establishment override → consultant/employer override → global default, ₹10/employee/month out of the box) times that month's employee count. Resolution logic lives in `resolve_rate()` (`webapp/app.py`).
- **Flat-fee billing** — a superadmin-configurable alternative: a fixed ₹/month per establishment instead of per-employee. Mode inheritance (establishment → consultant default → global `per_employee` fallback) is resolved by `resolve_billing_mode()`.
- **Download gating** — report/PDF/ECR endpoints return a structured HTTP 402 for consultants/employers (not superadmins) when any month with wage data has an overdue, unpaid subscription fee (1-day grace period past month end), with a combined pay-all-overdue total shown to the user.
- **Payment options** — Cashfree Payment Links (webhook-verified) or manual UPI: a scannable QR code plus UTR submission, reviewed and approved/rejected by a superadmin.
- **Advance credit** — consultants/employers can prepay a lump sum that auto-applies to future unpaid months as wage data arrives.
- **Trials** — a per-establishment `trial_ends_on` date can suspend billing enforcement for a given establishment, replacing an earlier global on/off flag.

---

## Technology stack

- **Backend**: Python, FastAPI, Uvicorn, SQLAlchemy, Pandas, ReportLab, openpyxl, PyJWT, Authlib (Google OAuth).
- **Frontend**: HTML5, vanilla JavaScript (ES6+), no bundler — static files served directly by FastAPI.
- **Database**: PostgreSQL (Supabase/Neon in production), SQLite for the isolated test suite.
- **Payments**: Cashfree Payment Links API + manual UPI/QR (`qrcodejs` via CDN).

---

## Running locally

```bash
pip install -r webapp/requirements.txt

# DATABASE_URL and SECRET_KEY are required; DATABASE_URL must point at a local/dev
# database, not the production one in .env
uvicorn webapp.app:app --reload --host 0.0.0.0 --port 8000
```

### Tests

```bash
pytest webapp/tests/ -v
```

Tests set `DATABASE_URL` to an isolated SQLite file (`test_epf.db`, created/dropped by `conftest.py`) before `webapp.app` is imported, and never touch the production database.

---

See `CHANGELOG.md` for a running record of what's shipped recently.
