# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

EPF Admin Dashboard — a multi-tenant statutory compliance platform for Indian EPFO (Employees' Provident Fund) filings. It computes Pre-1997/Post-1997 scheme contributions, tracks monthly wages/NCP days, and renders official government forms (Form 3A, 6A, 12A, 9, 5, 10) plus EPFO v3.0 ECR text files.

## Commands

```bash
# Run the server locally (from repo root)
uvicorn webapp.app:app --reload --host 0.0.0.0 --port 8000

# Install dependencies
pip install -r webapp/requirements.txt

# Run the full test suite
pytest webapp/tests/ -v

# Run a single test file / single test
pytest webapp/tests/test_multi_tenant_isolation.py -v
pytest webapp/tests/test_multi_tenant_isolation.py::test_ownership_enforcement -v
```

Tests spin up their own isolated SQLite DB (`test_epf.db` at repo root, created/dropped by `webapp/tests/conftest.py`) by setting `DATABASE_URL` **before** `webapp.app` is imported — this must happen first in any new test module, same as `conftest.py` does. Tests never touch the production Postgres/Supabase database.

Production deploy (Render, see `Procfile`): `python sync_to_supabase.py && uvicorn webapp.app:app --host 0.0.0.0 --port $PORT`.

## Architecture

```
Web UI (webapp/index.html, webapp/js/*.js, vanilla JS SPA)
        │ HTTP/JSON, JWT bearer auth
FastAPI backend — webapp/app.py (single large router file, all endpoints)
        │
        ├── webapp/auth.py     — JWT issue/verify, get_current_user / get_superadmin /
        │                        get_active_establishment FastAPI dependencies
        ├── webapp/database.py — SQLAlchemy models + engine/session setup
        │
        ├── epf_engine.py      — statutory calc engine: Project/Establishment/Employee/
        │                        YearRecord classes, contribution formulas, wage-ceiling
        │                        rules, openpyxl-based ExcelGenerator (Form 3A/6A/12A/9/5/10),
        │                        ECR v3.0 text generator
        └── pdf_engine.py      — direct ReportLab PDF generation for the same forms
                                  (used when a client requests format=pdf)
```

### Multi-tenancy model

- `User` rows have `role` = `"superadmin"` or `"consultant"`.
- `Establishment` rows belong to exactly one consultant (`user_id`). Consultants can only see/act on their own establishments; superadmins can access all. This is enforced per-request in `webapp/auth.get_active_establishment` and inline `current_user.role != "superadmin"` checks scattered through `webapp/app.py` — when adding a new establishment-scoped endpoint, follow the same ownership-check pattern rather than trusting the client-supplied establishment id.
- The active establishment is resolved from (in order) the `establishment_id`/`est_id` query param, the `X-Establishment-Id` header, or the consultant's first establishment.
- All statutory/employee data for an establishment lives as one JSON blob in `Establishment.data` (a serialized `epf_engine.Project`), not in normalized SQL tables. `Project.load_from_dict` / `Project.to_dict()` are the (de)serialization boundary; `webapp/auth.save_establishment_project` persists it back.

### epf_engine.Project — the domain model

`Project` is the in-memory representation of one establishment's entire history: `master` (employee master records keyed by member id), `years` (dict of `YearRecord` per financial year, each holding wages/NCP/remittance data), and establishment identity fields (code, name, address, coverage_date). Almost every `/api/...` handler in `app.py` works by: load `Project` from `Establishment.data` via `get_active_establishment`, mutate it, call `save_establishment_project`. Wage ceilings and contribution rates are date/year-dependent (see `get_wage_ceilings_for_year`, `account2_rate_percent`, `account22_rate_percent` in `epf_engine.py`) — don't hardcode rates when adding calculation logic.

### Subscription-fee download gating

Report/PDF download endpoints (`/api/reports/...`) check `get_unpaid_months_for_year` and return HTTP 402 for consultants (not superadmins) if any month with wage data has an overdue, unpaid `SubscriptionFee` record (grace period = 1 day past month end, see `is_month_overdue`). `sync_subscription_fees_for_year` auto-derives fee rows from employee counts × the effective per-employee rate (establishment override → consultant override → global `Setting` → ₹20 default, resolved by `resolve_rate`). This is distinct from `Payment` records, which track actual EPF statutory remittance compliance (TRRN/CRRN), not platform subscription billing.

### Activity logging

`log_activity()` in `app.py` writes an `ActivityLog` row for auditable actions (logins, establishment/consultant CRUD, payment/rate changes). It swallows its own exceptions so a logging failure never breaks the parent request — follow this pattern (best-effort, non-blocking) for any new activity log calls.

### Frontend

Vanilla JS SPA, no build step. `webapp/js/app.js` is the core module (routing, JWT storage in `localStorage`, the `api()` fetch wrapper that attaches `Authorization` and `X-Establishment-Id` headers). Each dashboard section is its own file (`dashboard.js`, `employees.js`, `wages.js`, `years.js`, `challans.js`, `reports.js`, `org-structure.js`, `establishment.js`, `admin.js` for the superadmin views, `my-establishments.js`). Static assets are served directly by FastAPI (`app.mount("/css", ...)`, `/js`) — no bundler/transpiler is involved.

## Git workflow

Per `.agents/AGENTS.md`, after completing a significant feature/fix, commit and push automatically (`git add .`, `git commit -m "..."`, `git push`) without waiting to be asked.
