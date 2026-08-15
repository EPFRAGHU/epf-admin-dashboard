# EPF Admin Dashboard — Comprehensive Project Documentation & Release History

Welcome to the **EPF Admin Dashboard & Statutory Management System** repository. This document records all architectural developments, statutory calculations, UI/UX designs, PDF engines, bug fixes, and the complete chronological release progression from project inception to the present date.

---

## 📌 Table of Contents
1. [Overview & Architecture](#overview--architecture)
2. [Chronological Version Progression (v1.0.0 → v1.6.0)](#chronological-version-progression-v100--v160)
3. [Key Modules & Capabilities](#key-modules--capabilities)
   - [1. Establishment Management](#1-establishment-management)
   - [2. Employee Master & UAN Validation](#2-employee-master--uan-validation)
   - [3. Financial Years & Ceiling Rules](#3-financial-years--ceiling-rules)
   - [4. Monthly Wage Entry & NCP Tracking](#4-monthly-wage-entry--ncp-tracking)
   - [5. Challan Remittances & Form 12A Grid](#5-challan-remittances--form-12a-grid)
   - [6. Statutory Reports & Direct PDF Generation](#6-statutory-reports--direct-pdf-generation)
   - [7. EPFO v3.0 ECR File Generator](#7-epfo-v30-ecr-file-generator)
   - [8. Employee Wage History Report](#8-employee-wage-history-report)
4. [Statutory Calculation Rules & Formulas](#statutory-calculation-rules--formulas)
5. [UI / UX Design & Left Sidebar Version Tracker](#ui--ux-design--left-sidebar-version-tracker)
6. [Technology Stack & System Requirements](#technology-stack--system-requirements)
7. [Installation & Deployment](#installation--deployment)
8. [Changelog & Conversation Record](#changelog--conversation-record)

---

## 🏗️ Overview & Architecture

The **EPF Admin Dashboard** is a cloud-ready, full-stack statutory compliance platform tailored for Indian Employees' Provident Fund (EPFO) compliance. It processes multi-year establishment data, calculates statutory contributions across Pre-1997 and Post-1997 schemes, and renders official, pixel-perfect government returns (Form 3A, Form 6A, Form 12A, Form 9, Form 5, Form 10, and ECR v3.0).

```
┌─────────────────────────────────────────────────────────────┐
│                   Web UI (Vanilla JS & CSS)                 │
│  - Dashboard & Charts   - Employee Master  - Wage Grid      │
│  - Challans (Form 12A)  - Reports & PDFs   - Version Modal  │
└──────────────────────────────┬──────────────────────────────┘
                               │ HTTP / JSON API
┌──────────────────────────────▼──────────────────────────────┐
│                    FastAPI Server Backend                   │
│                     (webapp/app.py v1.6.0)                  │
└──────────────┬───────────────────────────────┬──────────────┘
               │                               │
┌──────────────▼──────────────┐ ┌──────────────▼──────────────┐
│     EPF Statutory Engine    │ │   Direct ReportLab Engine   │
│       (epf_engine.py)       │ │  - Form 3A, 6A, 12A, 9, 5   │
│ - Pre/Post 1997 Rules       │ │  - ECR v3.0 Text Generator  │
│ - Zero-wage filtering       │ │  - Wage History PDF         │
│ - Whole Rupee Integer Math  │ └─────────────────────────────┘
└──────────────┬──────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│                     Persistence Layer                       │
│ - Supabase / PostgreSQL (Render Cloud Deployment)           │
│ - Local JSON Project Files (*.epfproj.json fallback)        │
└─────────────────────────────────────────────────────────────┘
```

---

## ⏱️ Chronological Version Progression (v1.0.0 → v1.6.0)

| Version | Date & Time (IST) | Status / Badge | Major Milestones & Highlights |
| :--- | :--- | :--- | :--- |
| **v1.6.0** | **14-08-2026 04:47** | **Present / Latest** | **Zero-Wage Auto-Filter, Rupee Integer Formatting & Live Version Tracking**<br>• Form 3A & Form 6A automatically filter out 0 total wage employees from statutory reports without altering PDF grid integrity.<br>• Wages and statutory contributions strictly rendered and saved as whole rupee integers with zero decimal artifacts (`.0` removed).<br>• Live Version Progression tracking in the left side panel with complete chronological timeline from project start to present time.<br>• Requirements & dependencies synced for Render cloud deployment with ReportLab & Pandas native acceleration. |
| **v1.5.0** | 14-08-2026 02:55 | High Performance | **Direct ReportLab Native PDF Engine & EPFO v3.0 ECR Generator**<br>• High-speed native ReportLab PDF generator replacing external LibreOffice and pywin32 desktop dependencies.<br>• Form 3A, Form 6A, Form 12A, Form 9, Form 5, and Form 10 exact statutory pixel-perfect table layouts with A4 landscape auto-wrap.<br>• Integrated ECR text file generator conforming strictly to EPFO v3.0 format with Higher EPF split.<br>• Form 12A Grand Total row span, TRRN/CRRN proximity formatting, and tight vertical spacing. |
| **v1.4.0** | 13-08-2026 23:55 | Major Feature | **Statutory Forms Compliance & Form 12A Challan Remittances**<br>• Multi-challan remittance support with 12-month static Form 12A Challan Management Grid.<br>• Auto-calculation for Account 2 (Admin Charges), Account 21 (EDLI), and Account 22 (EDLI Admin Charges).<br>• Repeating establishment headers on Form 9 and Form 6A with dynamic page footers and landscape fitting.<br>• Light theme UI styling propagated across all dashboard views, modals, and tables. |
| **v1.3.0** | 13-08-2026 11:56 | Feature Update | **Employee Wage History & Multi-Year Tabular Analytics**<br>• Comprehensive Employee Wage History report with year-wise tabular data across all financial years.<br>• Direct Print-to-PDF functionality with custom establishment header and clean tabular formatting.<br>• Individual Employee 📄 3A instant card download from Wage Entry.<br>• Higher EPF (EE and ER) contribution split support and dynamic wage ceiling handling. |
| **v1.2.0** | 13-08-2026 01:26 | Major Feature | **Monthly Wage Grid & Interactive Dashboards**<br>• Monthly bulk wage entry modal with previous month auto-copying and NCP work-days calculation.<br>• Interactive Month-wise Dashboard summaries, charts, and statutory distribution breakdowns.<br>• Global pagination across large employee datasets and superannuation age 58 tracking.<br>• Dynamic month selection defaulting to previous calendar month with March fallback. |
| **v1.1.0** | 12-08-2026 09:15 | Feature Update | **Multi-Sheet Excel Importer & Mandatory 12-Digit UAN**<br>• Bulk import multi-year Excel spreadsheets simultaneously with automatic financial year creation.<br>• Automatic Employee Master extraction and population (DOB, DOJ, DOE, Father Name, Gender).<br>• Mandatory 12-digit UAN validation and member ID establishment code verification.<br>• Robust file path checking on first save to prevent project data corruption. |
| **v1.0.0** | 11-08-2026 23:12 | Project Inception | **Project Inception & Core Statutory Engine**<br>• Initial repository setup and cloud-ready FastAPI backend architecture.<br>• Core EPF statutory computation engine supporting Pre-1997 and Post-1997 contribution rules.<br>• Multi-establishment database management with PostgreSQL/Supabase and local JSON fallback synchronization.<br>• Standard Form 3A and Form 6A annual return generation foundations. |

---

## ⚙️ Key Modules & Capabilities

### 1. Establishment Management
- Create, modify, switch, and back up multiple establishments.
- Supports Establishment Name, Establishment Code, Address, Extension / Sub-code, and Scheme Selection.
- Cloud persistence via Supabase PostgreSQL, synchronized with local JSON backups.

### 2. Employee Master & UAN Validation
- Centralized Employee Master maintaining:
  - Full Name, Father's / Husband's Name, Gender, Date of Birth (DOB).
  - Date of Joining (DOJ), Date of Exit (DOE), Reason for Leaving.
  - Member ID / PF Account Number and **Mandatory 12-Digit Universal Account Number (UAN)**.
- Superannuation tracking (identifies members reaching Age 58 to cease EPS contributions as per EPFO statutory guidelines).

### 3. Financial Years & Ceiling Rules
- Flexible financial year configuration (e.g. 2024-2025, 2025-2026).
- Statutory wage ceilings automatically applied according to historical EPF limits:
  - ₹15,000 ceiling (Post-01/09/2014)
  - ₹6,500 ceiling (01/06/2001 to 31/08/2014)
  - ₹5,000 ceiling (01/10/1997 to 31/05/2001)

### 4. Monthly Wage Entry & NCP Tracking
- Tabular wage entry with 12 months (March to February / April to March sequence).
- Auto-calculation of:
  - EPF Wages, EPS Wages, EDLI Wages.
  - Employee Contribution (12%).
  - Employer EPS Contribution (8.33% up to ceiling).
  - Employer EPF Contribution (Balance 3.67% or full contribution if exempt/over-age).
  - Higher EPF Voluntary Employee and Employer splits.
  - Non-Contributory Period (NCP Days) and Refund of Advances.
- Instant "Copy from Previous Month" and "Add Employee by UAN" features.

### 5. Challan Remittances & Form 12A Grid
- Static 12-month Form 12A Challan Management Grid.
- Automatic computation of statutory administrative and insurance accounts:
  - **Account 1**: EPF Contributions (EE + ER)
  - **Account 2**: EPF Administrative Charges (0.50% of EPF wages, min ₹500/₹75)
  - **Account 10**: EPS Contributions (8.33%)
  - **Account 21**: EDLI Contribution (0.50% of EDLI wages)
  - **Account 22**: EDLI Administrative Charges (0.00% / min ₹200)
- Multi-challan remittance support with TRRN, CRRN, Payment Date, Amount Paid, and Bank Name.

### 6. Statutory Reports & Direct PDF Generation
Powered by direct, high-performance ReportLab rendering (no external office software required):
- **Form 3A**: Individual Member's Annual Contribution Card (filters out zero-wage records; renders whole rupee numbers).
- **Form 6A**: Consolidated Annual Statement showing total wages, contributions, and account breakdowns.
- **Form 12A**: Statement of Remittances showing month-wise statutory dues vs. actual remittances.
- **Form 9**: Statutory Register of Employees qualifying for membership (with repeating headers and landscape flow).
- **Form 5 & Form 10**: New Joinees & Exited Employees monthly returns.

### 7. EPFO v3.0 ECR File Generator
- Generates official `#~#` delimited Electronic Challan cum Return (ECR) text files compliant with EPFO Unified Portal v3.0.
- Fields mapped: `UAN#~#Member_Name#~#Gross_Wages#~#EPF_Wages#~#EPS_Wages#~#EDLI_Wages#~#EE_Share#~#EPS_Share#~#ER_Share#~#NCP_Days#~#Refund_Advances`.

### 8. Employee Wage History Report
- Comprehensive cross-year employee ledger displaying year-by-year wages, contributions, and months worked.
- Search by UAN, Member ID, or Name with instant Print-to-PDF functionality.

---

## 📐 Statutory Calculation Rules & Formulas

1. **Employee EPF Contribution (Account 1)**:
   $$\text{EE EPF} = \text{round}\left(\text{EPF Wages} \times 12\%\right)$$
2. **Employer EPS Contribution (Account 10)**:
   $$\text{EPS Wages} = \min(\text{Actual Wages}, \text{Statutory Ceiling})$$
   $$\text{ER EPS} = \text{round}\left(\text{EPS Wages} \times 8.33\%\right) \quad (\text{if Age} < 58)$$
3. **Employer EPF Contribution (Account 1)**:
   $$\text{ER EPF} = \text{round}\left(\text{EPF Wages} \times 12\%\right) - \text{ER EPS}$$
4. **EDLI Contribution (Account 21)**:
   $$\text{ER EDLI} = \text{round}\left(\min(\text{Actual Wages}, \text{Statutory Ceiling}) \times 0.50\%\right)$$
5. **EPF Admin Charges (Account 2)**:
   $$\text{Admin Charges} = \max\left(\text{round}\left(\text{Total EPF Wages} \times 0.50\%\right), \text{Minimum Charge}\right)$$

---

## 🎨 UI / UX Design & Left Sidebar Version Tracker

- **Clean EPFO Theme**: Soft neutral surfaces (`#f8fafc`), clean borders (`#e2e8f0`), and accessible high-contrast typography.
- **Left Sidebar Version Card**:
  - Live Present Version indicator: `v1.6.0` with `Present` badge.
  - Project timeline span: `11-08-2026 → 14-08-2026`.
  - Clickable `📜 View Version History` button opening the complete interactive modal with timeline cards, milestones, timestamps, and feature lists.

---

## 💻 Technology Stack & System Requirements

- **Backend**: Python 3.8+, FastAPI, Uvicorn, SQLAlchemy, Pandas, ReportLab.
- **Frontend**: HTML5, Vanilla JavaScript (ES6+), CSS3 Design System.
- **Database**: PostgreSQL (Supabase) / JSON flat-file storage.
- **Dependencies**: `reportlab>=3.6.0`, `pandas>=1.5.0`, `fastapi>=0.95.0`, `uvicorn>=0.20.0`, `openpyxl>=3.0.0`.

---

## 🚀 Installation & Deployment

### Local Setup
```bash
# 1. Clone the repository
git clone https://github.com/EPFRAGHU/epf-admin-dashboard.git
cd epf-admin-dashboard

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the FastAPI server
python -m uvicorn webapp.app:app --reload --port 8000
```
Open browser at: `http://localhost:8000`

### Cloud Deployment (Render.com)
1. Link GitHub repository to Render Web Service.
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `uvicorn webapp.app:app --host 0.0.0.0 --port $PORT`
4. Set Environment Variables: `DATABASE_URL` (Supabase Postgres URI).

---

## 📜 Git Auto-Sync Protocol
All updates, database syncs, and releases are automatically versioned, committed, and pushed to `main`.
