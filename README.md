# EPF Admin Dashboard — Comprehensive Project Documentation & Release History

Welcome to the **EPF Admin Dashboard & Statutory Management System** repository. This document records all architectural developments, statutory calculations, UI/UX designs, PDF engines, bug fixes, and the complete chronological release progression from project inception to the present date.

---

## 📌 Table of Contents
1. [Overview & Architecture](#overview--architecture)
2. [Chronological Version Progression (v1.0.0 → v1.8.0)](#chronological-version-progression-v100--v180)
3. [Key Modules & Capabilities](#key-modules--capabilities)
   - [1. Establishment Management](#1-establishment-management)
   - [2. Employee Master & UAN Validation](#2-employee-master--uan-validation)
   - [3. Financial Years & Ceiling Rules](#3-financial-years--ceiling-rules)
   - [4. Monthly Wage Entry & NCP Tracking](#4-monthly-wage-entry--ncp-tracking)
   - [5. Challan Remittances & Form 12A Grid](#5-challan-remittances--form-12a-grid)
   - [6. Statutory Reports & Direct PDF Generation](#6-statutory-reports--direct-pdf-generation)
   - [7. EPFO v3.0 ECR File Generator](#7-epfo-v30-ecr-file-generator)
   - [8. Employee Wage History Report](#8-employee-wage-history-report)
   - [9. Consultant Default Billing Inheritance](#9-consultant-default-billing-inheritance)
   - [10. Manual UPI/UTR Payment Verification](#10-manual-upiutr-payment-verification)
4. [Billing Mode Resolution Logic](#billing-mode-resolution-logic)
5. [Statutory Calculation Rules & Formulas](#statutory-calculation-rules--formulas)
6. [UI / UX Design & Left Sidebar Version Tracker](#ui--ux-design--left-sidebar-version-tracker)
7. [Technology Stack & System Requirements](#technology-stack--system-requirements)
8. [Installation & Deployment](#installation--deployment)
9. [Git Auto-Sync Protocol](#git-auto-sync-protocol)

---

## 🏗️ Overview & Architecture

The **EPF Admin Dashboard** is a cloud-ready, full-stack statutory compliance platform tailored for Indian Employees' Provident Fund (EPFO) compliance. It processes multi-year establishment data, calculates statutory contributions across Pre-1997 and Post-1997 schemes, and renders official, pixel-perfect government returns (Form 3A, Form 6A, Form 12A, Form 9, Form 5, Form 10, and ECR v3.0).

```
+-------------------------------------------------------------+
|                   Web UI (Vanilla JS & CSS)                 |
|  - Dashboard & Charts   - Employee Master  - Wage Grid      |
|  - Challans (Form 12A)  - Reports & PDFs   - Version Modal  |
|  - Admin Panel (Superadmin) -- Consultant & Billing Mgmt    |
+------------------------------+------------------------------+
                               | HTTP / JSON API
+------------------------------v------------------------------+
|                    FastAPI Server Backend                   |
|                     (webapp/app.py v1.8.0)                  |
+--------------+-------------------------------+--------------+
               |                               |
+--------------v--------------+ +--------------v--------------+
|     EPF Statutory Engine    | |   Direct ReportLab Engine   |
|       (epf_engine.py)       | |  - Form 3A, 6A, 12A, 9, 5   |
| - Pre/Post 1997 Rules       | |  - ECR v3.0 Text Generator  |
| - Zero-wage filtering       | |  - Wage History PDF         |
| - Whole Rupee Integer Math  | +-----------------------------+
+--------------+--------------+
               |
+--------------v--------------------------------------------------+
|              Billing & Subscription Layer                       |
| - resolve_billing_mode(): est -> consultant default -> global   |
| - Consultant default_billing_mode / default_flat_fee cols       |
| - Establishment billing_mode nullable (null = inherit)          |
| - Cashfree Payment Links, Advance Credits, Webhooks             |
+--------------+--------------------------------------------------+
               |
+--------------v--------------------------------------------------+
|                     Persistence Layer                           |
| - Supabase / PostgreSQL (Render Cloud Deployment)               |
| - Local JSON Project Files (*.epfproj.json fallback)            |
+-----------------------------------------------------------------+
```

---

## ⏱️ Chronological Version Progression (v1.0.0 → v1.8.0)

| Version | Date (IST) | Status | Major Milestones |
| :--- | :--- | :--- | :--- |
| **v1.9.0** | **19-08-2026** | **Present** | **Manual UPI/UTR Payment Verification & QR Code Generation** — Consultant/employer-facing "Pay via UPI (Manual)" path added alongside Cashfree inside the subscription-fee download-lock modal: shows the payee UPI ID/name from `GET /api/upi-settings`, renders a live scannable QR code (`qrcodejs`, loaded via CDN like Chart.js) encoding `upi://pay?pa=...&pn=...&am=...&cu=INR` with the exact amount due, and a UTR submission form (`POST /api/subscription-fees/{id}/submit-utr`) that moves `payment_status` to `pending_verification` while keeping the download locked. Superadmin-side "Payment Verifications" tab lists pending UTR submissions for approval (`POST /api/admin/payment-verifications/{id}/approve` — sets `payment_status='paid'`, records `payment_reference`, logs `utr_approved` activity) or rejection with a reason; a paired "UPI Settings" tab lets the superadmin configure the payee UPI ID/name used platform-wide. Fixed two shipped-but-broken pieces found during audit: the two admin nav tabs called functions that didn't exist anywhere in `admin.js` (crashed on click, so no UTR could ever be submitted), and the QR panel silently never rendered an actual QR image — it only linked to a mobile-only `upi://` deep link. End-to-end verified live on production with a real ₹10 UPI payment, a real UTR, and real superadmin approval unlocking the download. |
| **v1.8.0** | 18-08-2026 | Stable | **Consultant-Level Default Billing Inheritance Layer** — `User.default_billing_mode` + `User.default_flat_fee_per_establishment` columns on consultant accounts; `Establishment.billing_mode` nullable (`null` = inherit, existing explicit values preserved); central `resolve_billing_mode()` helper (est → consultant default → global tiered); `PUT /api/admin/users/{user_id}/default-billing` endpoint (superadmin-only, validates mode, ActivityLog old→new); `billing_mode='inherit'` accepted on establishment endpoint to clear override; consultant edit modal adds 3-way toggle (No Default / Per Employee / Flat Fee) with ₹200/₹300/₹400/₹500 presets + custom input; establishment cards show `(inherited)` vs `(override)` badge; Manage Billing Modal shows blue/amber banners + "↩ Reset to Consultant Default" footer button; `GET /api/admin/users/{user_id}/establishments` enriched with `billing_mode_explicit`, `billing_mode_own`, `flat_fee_amount_own` per establishment and `default_billing_mode` / `default_flat_fee_per_establishment` on the `user` object. |
| **v1.7.0** | 15-08-2026 | Stable | **Subscription Billing, Cashfree Payments & Calc Fixes** — Fixed A/C 1 double-subtracted EPS share and A/C 22 post-2017 ₹200 minimum bug; Gross/EPF/EPS/EDLI breakdown columns in Challan Remittance table; per-establishment per-month Software Subscription Fee tracker with 3-tier rate resolution and download-gating; Advance Credit prepay system with consultant-facing Subscription History; Cashfree Payment Links (webhook-confirmed, signature-verified); Wage History redesigned with EE/ER/EPS per month + ReportLab PDF export; global default rate ₹10/employee/month. |
| **v1.6.0** | 14-08-2026 | Stable | **Zero-Wage Filter, Integer Formatting & Version Tracking** — Form 3A/6A auto-filter 0-wage employees; all contributions as whole rupees; live Version Progression card in sidebar with interactive history modal. |
| **v1.5.0** | 14-08-2026 | High Perf | **Native ReportLab PDF Engine & ECR v3.0** — Replaces LibreOffice/pywin32; Form 3A/6A/12A/9/5/10 statutory layouts; ECR v3.0 text generator. |
| **v1.4.0** | 13-08-2026 | Major | **Form 12A Challan Remittances** — Multi-challan support; A/C 2/21/22 auto-calc; repeating headers on Form 9 & 6A; light theme. |
| **v1.3.0** | 13-08-2026 | Update | **Employee Wage History** — Cross-year report; Print-to-PDF; Higher EPF split. |
| **v1.2.0** | 13-08-2026 | Major | **Monthly Wage Grid & Dashboards** — Bulk entry modal; previous month copy; NCP; charts; pagination. |
| **v1.1.0** | 12-08-2026 | Update | **Excel Importer & UAN Validation** — Multi-year Excel import; Employee Master auto-extraction; 12-digit UAN validation. |
| **v1.0.0** | 11-08-2026 | Inception | **Core Statutory Engine** — FastAPI backend; Pre/Post 1997 EPF computation; PostgreSQL + JSON persistence; Form 3A/6A foundations. |

---

## ⚙️ Key Modules & Capabilities

### 1. Establishment Management
- Create, modify, switch, and back up multiple establishments (Name, Code, Address, Extension/Sub-code, Scheme).
- Cloud persistence via Supabase PostgreSQL + local JSON backup.
- Per-establishment billing mode: `per_employee` (tiered), `flat_fee` (₹/month fixed), or `null` to inherit from consultant default.

### 2. Employee Master & UAN Validation
- Full Name, Father's/Husband's Name, Gender, DOB, DOJ, DOE, Reason for Leaving, Member ID, **mandatory 12-digit UAN**.
- Superannuation tracking (age 58 — cease EPS as per EPFO guidelines).

### 3. Financial Years & Ceiling Rules
- Flexible financial year config. Statutory wage ceilings auto-applied:
  - ₹15,000 (post 01/09/2014)
  - ₹6,500 (01/06/2001 – 31/08/2014)
  - ₹5,000 (01/10/1997 – 31/05/2001)

### 4. Monthly Wage Entry & NCP Tracking
- 12-month tabular entry. Auto-calculates EPF/EPS/EDLI wages, EE/ER contributions, Higher EPF voluntary splits, NCP Days, Refund of Advances.
- "Copy from Previous Month" and "Add Employee by UAN" helpers.

### 5. Challan Remittances & Form 12A Grid
- 12-month static Form 12A grid. Auto-computes A/C 1 (EPF), A/C 2 (Admin), A/C 10 (EPS), A/C 21 (EDLI), A/C 22 (EDLI Admin).
- Multi-challan support: TRRN, CRRN, Payment Date, Amount, Bank Name.

### 6. Statutory Reports & Direct PDF Generation
- **Form 3A**: Individual Annual Member Statement (whole rupee).
- **Form 6A**: Consolidated Annual Statement.
- **Form 12A**: Statement of Remittances (dues vs. remittances).
- **Form 9**: Statutory Register of Members (repeating headers, landscape).
- **Form 5 & Form 10**: New Joinees & Exited Employees monthly returns.

### 7. EPFO v3.0 ECR File Generator
- Official `#~#`-delimited ECR files compliant with EPFO Unified Portal v3.0.
- Fields: `UAN#~#Member_Name#~#Gross_Wages#~#EPF_Wages#~#EPS_Wages#~#EDLI_Wages#~#EE_Share#~#EPS_Share#~#ER_Share#~#NCP_Days#~#Refund_Advances`.

### 8. Employee Wage History Report
- Cross-year ledger: EE/ER/EPS contributions per month grouped by financial year.
- Search by UAN, Member ID, or Name. Browser Print-to-PDF + server-side ReportLab PDF (repeating headers, pagination).

### 9. Consultant Default Billing Inheritance
- Consultant sets one default billing mode → applied to all their establishments unless individually overridden.
- `establishment.billing_mode = null` = inherit (no per-establishment row needed).
- `PUT /api/admin/users/{user_id}/default-billing` — superadmin sets consultant default.
- `PUT /api/admin/establishments/{id}/billing-mode` with `billing_mode='inherit'` — clears override.
- Admin UI: `(inherited)` (indigo) vs `(override)` (amber) badge per establishment card; Manage Billing Modal shows contextual banners + one-click reset button.

### 10. Manual UPI/UTR Payment Verification
- Alternative to Cashfree for settling an overdue subscription-fee month: consultant/employer scans a QR code or opens a `upi://pay` deep link, pays the payee UPI ID directly, then submits the UTR/transaction reference number through the app.
- `POST /api/subscription-fees/{id}/submit-utr` — records the UTR, sets `payment_status='pending_verification'`; download stays locked until superadmin review.
- `GET /api/upi-settings` — any authenticated user can read the configured payee UPI ID/name/QR string to render the payment panel.
- Superadmin "Payment Verifications" tab — list, approve (`POST /api/admin/payment-verifications/{id}/approve`), or reject-with-reason pending UTR submissions.
- Superadmin "UPI Settings" tab — configure the platform-wide payee UPI ID, payee name, and optional static QR string (`PUT /api/admin/settings/upi`).

---

## 💳 Billing Mode Resolution Logic

```
resolve_billing_mode(establishment, consultant_user)

1. establishment.billing_mode IS NOT NULL  →  use establishment explicit mode + flat_fee_amount
2. consultant.default_billing_mode IS NOT NULL  →  use consultant default + default_flat_fee_per_establishment
3. Fallback  →  per_employee (global tiered rate)
```

**Per-employee tiers (global default, configurable by superadmin):**

| Employees | Rate |
| :--- | :--- |
| 1 – 10 | ₹10/employee/month |
| 11 – 25 | ₹8/employee/month |
| 26+ | ₹6/employee/month |

---

## 📐 Statutory Calculation Rules & Formulas

1. **Employee EPF (A/C 1):** `round(EPF_Wages × 12%)`
2. **Employer EPS (A/C 10):** `EPS_Wages = min(Actual_Wages, Ceiling)` → `round(EPS_Wages × 8.33%)` (age < 58)
3. **Employer EPF (A/C 1):** `round(EPF_Wages × 12%) − ER_EPS`
4. **EDLI (A/C 21):** `round(min(Actual_Wages, Ceiling) × 0.50%)`
5. **EPF Admin (A/C 2):** `max(round(Total_EPF_Wages × 0.50%), Minimum_Charge)`

---

## 🎨 UI / UX Design & Left Sidebar Version Tracker

- **Clean EPFO Theme**: Soft neutral surfaces (`#f8fafc`), clean borders (`#e2e8f0`), accessible high-contrast typography.
- **Left Sidebar Version Card**: `v1.8.0` Present badge; timeline `11-08-2026 → 18-08-2026`; `📜 View Version History` opens interactive modal with timeline cards and feature lists.
- **Admin Panel — Consultant Default Billing UI**:
  - 3-way toggle in consultant edit modal: **No Default** / **Per Employee** / **Flat Fee**.
  - Quick presets: ₹200 / ₹300 / ₹400 / ₹500/establishment/month + custom amount input.
  - Establishment billing chips: `(inherited)` indigo badge or `(override)` amber badge with tooltip.
  - Manage Billing Modal: blue info banner (inheriting) or amber warning banner (override) + "↩ Reset to Consultant Default" button.

---

## 💻 Technology Stack & System Requirements

- **Backend**: Python 3.8+, FastAPI, Uvicorn, SQLAlchemy, Pandas, ReportLab.
- **Frontend**: HTML5, Vanilla JavaScript (ES6+), CSS3 Design System.
- **Database**: PostgreSQL (Supabase) / JSON flat-file storage.
- **Payments**: Cashfree Payment Gateway (Payment Links API, webhook signature verification); manual UPI/UTR verification workflow with QR code generation (`qrcodejs` via CDN).
- **Dependencies**: `reportlab>=3.6.0`, `pandas>=1.5.0`, `fastapi>=0.95.0`, `uvicorn>=0.20.0`, `openpyxl>=3.0.0`.

---

## 🚀 Installation & Deployment

### Local Setup
```bash
# 1. Clone the repository
git clone https://github.com/EPFRAGHU/epf-admin-dashboard.git
cd epf-admin-dashboard

# 2. Install dependencies
pip install -r webapp/requirements.txt

# 3. Set environment variables (create a .env file, or export directly)
# Required: DATABASE_URL, SECRET_KEY
# Optional (feature-gated): CASHFREE_APP_ID, CASHFREE_SECRET_KEY, SUPERADMIN_EMAIL

# 4. Start the server -- schema migrations run automatically on startup
uvicorn webapp.app:app --reload --host 0.0.0.0 --port 8000
```

### Running Automated Test Suite
```bash
pip install -r requirements-dev.txt
pytest webapp/tests/ -v
```
Tests run against an isolated disposable SQLite database (`test_epf.db`) — never touches production.

---

## 📜 Git Auto-Sync Protocol
All updates, database syncs, and releases are automatically versioned, committed, and pushed to `main`.
