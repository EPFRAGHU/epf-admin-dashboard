# Month/Year Entry Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate wage-entry and financial-year creation so a consultant/employer can only enter data one chronological month at a time (anchored to the establishment's locked `coverage_date`), each month unlocking only once the previous one is paid — while never retroactively blocking data that already exists.

**Architecture:** One shared backend helper (`get_entry_lock_status`) walks an establishment's financial years in coverage-date order and reports the single current lock boundary (either "the next year that needs to be created" or "the next month that needs its predecessor paid first"). Three existing endpoints consult it (`POST /api/years`, `POST /api/years/{key}/wages/bulk_month`, and a new superadmin-only gate on `POST /api/years/bulk`); a new read-only status endpoint lets the frontend show lock state before the user even attempts a blocked action.

**Tech Stack:** FastAPI (Python) backend in `webapp/app.py`, SQLAlchemy models in `webapp/database.py`, vanilla JS frontend (`webapp/js/*.js`, no build step), pytest with `TestClient` (`webapp/tests/`).

**Spec:** `docs/superpowers/specs/2026-08-26-month-year-entry-gating-design.md`

## Global Constraints

- Grandfathering: the gating check is skipped entirely for any (year, month) that already has wage data for at least one employee (`count_ecr_employees_for_month(...) > 0`) — never retroactively lock existing data. (Spec 3.3, confirmed default.)
- An establishment's first financial year must be exactly the financial year containing its (mandatory, locked) `coverage_date` — no exceptions. (Spec 3.2/6.2, confirmed default.)
- No persisted "declaration" **flag** — no new column, no state that branches gating behavior. The declaration does get real backend behavior, scoped exactly to: an `ActivityLog` entry recorded the moment an establishment's very first financial year is created (Task 3), so there's a permanent, auditable record of when data entry started. Nothing reads this log entry back to change enforcement — the gating rule (Tasks 2/3/5) is derived live from chronological order + payment status every time, identically whether or not this log entry exists.
- Backward entry (backfilling years/months before an establishment's current point) uses the **exact same mechanism** as forward entry — `POST /api/years` and the wage-entry endpoints apply one chronological rule regardless of direction (an establishment starting from an old `coverage_date` is, from the gating logic's point of view, indistinguishable from one "catching up"). No separate backfill wizard, endpoint, or table. The UI work in Task 7/8 makes sure the *required next year/month* is always visible so backfilling is discoverable, not a hidden capability.
- Superadmins bypass every check added in this plan, consistent with every other payment gate in the app (402 downloads, trial system, billing mode).
- **Scope boundary**: this plan gates `POST /api/years/{key}/wages/bulk_month` (the actual "Monthly Wage Entry" page's save endpoint, which is what the whole spec is about) and `POST /api/years`. It deliberately does **not** touch `POST /api/years/{key}/wages` (the older, separate per-employee/whole-year-at-once endpoint used by the plain "Wage Entry" page) — that endpoint's semantics (one call spans all 12 months for one employee) don't map cleanly onto a single-month lock check, and gating it is a separate follow-up if wanted.

---

## Task 1: Financial-year-for-date helper + coverage-year lookup

**Files:**
- Modify: `webapp/app.py` (add helpers near `resolve_billing_mode`, ~line 237)
- Test: `webapp/tests/test_month_year_entry_gating.py` (new)

**Interfaces:**
- Produces: `get_financial_year_key_for_date(cal_year: int, cal_month: int) -> str`, `get_coverage_year_key(project: Project) -> Optional[str]`

- [ ] **Step 1: Write the failing tests**

```python
# webapp/tests/test_month_year_entry_gating.py
"""Coverage for chronological month/year entry gating: a consultant/employer can only
enter wage data one month at a time, anchored to the establishment's coverage_date,
each unlocking only once the previous one is paid. See
docs/superpowers/specs/2026-08-26-month-year-entry-gating-design.md."""
from webapp.app import get_financial_year_key_for_date, get_coverage_year_key
from epf_engine import Project


def test_get_financial_year_key_for_date_mar_to_dec_belongs_to_same_calendar_year():
    assert get_financial_year_key_for_date(2020, 3) == "2020-21"
    assert get_financial_year_key_for_date(2020, 12) == "2020-21"


def test_get_financial_year_key_for_date_jan_feb_belongs_to_previous_calendar_year():
    assert get_financial_year_key_for_date(2021, 1) == "2020-21"
    assert get_financial_year_key_for_date(2021, 2) == "2020-21"


def test_get_coverage_year_key_parses_ddmmyyyy():
    p = Project()
    p.coverage_date = "15-06-2020"
    assert get_coverage_year_key(p) == "2020-21"


def test_get_coverage_year_key_jan_date_belongs_to_previous_fy():
    p = Project()
    p.coverage_date = "10-01-2021"
    assert get_coverage_year_key(p) == "2020-21"


def test_get_coverage_year_key_returns_none_when_blank():
    p = Project()
    p.coverage_date = ""
    assert get_coverage_year_key(p) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_financial_year_key_for_date'`

- [ ] **Step 3: Write the implementation**

In `webapp/app.py`, immediately after the `resolve_billing_mode` function (ends around line 237, right before `def apply_advance_credit_if_available`), add:

```python
def get_financial_year_key_for_date(cal_year: int, cal_month: int) -> str:
    """EPF financial years run Mar-Feb (see MONTH_SHORT_NAMES / epf_engine.MONTHS): a
    calendar date in Mar-Dec belongs to the FY starting that same calendar year; a date
    in Jan-Feb belongs to the FY that started the PREVIOUS calendar year."""
    year_from = cal_year if cal_month >= 3 else cal_year - 1
    return f"{year_from}-{str(year_from + 1)[-2:]}"


def get_coverage_year_key(project: Project) -> Optional[str]:
    """Parse project.coverage_date (DD-MM-YYYY -- guaranteed valid and locked once set,
    see _normalize_coverage_date) into the financial-year key it falls in. This is the
    anchor the chronological entry-gating walk (get_entry_lock_status) starts from."""
    if not project.coverage_date:
        return None
    try:
        d = datetime.strptime(project.coverage_date, "%d-%m-%Y")
    except ValueError:
        return None
    return get_financial_year_key_for_date(d.year, d.month)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add webapp/app.py webapp/tests/test_month_year_entry_gating.py
git commit -m "feat: financial-year-for-date and coverage-year helpers for entry gating"
```

---

## Task 2: The chronological lock-status walk

**Files:**
- Modify: `webapp/app.py` (add helper right after Task 1's helpers)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `get_coverage_year_key(project)` (Task 1), `sync_subscription_fees_for_year(db, est_obj, project, year_key)` (existing, `webapp/app.py:276`), `count_ecr_employees_for_month(project, year_key, month_idx)` (existing, `webapp/app.py:177`), `MONTH_SHORT_NAMES` (existing module constant)
- Produces: `get_entry_lock_status(db: Session, est_obj: Establishment, project: Project) -> dict` with shape `{"coverage_year_key": Optional[str], "next_year_to_add": Optional[str], "locked_month": Optional[{"year_key": str, "month_idx": int, "month_abbr": str}]}`

- [ ] **Step 1: Write the failing tests**

Append to `webapp/tests/test_month_year_entry_gating.py`:

```python
from webapp.database import SessionLocal
from webapp.app import get_entry_lock_status


def _create_est(consultant, code, coverage_date="01-04-2026"):
    res = consultant.post("/api/establishments", json={
        "coverage_date": coverage_date, "code": code, "name": f"{code} Co"
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant.set_establishment(est_id)
    return est_id


def _load_est_and_project(est_id):
    from webapp.auth import load_establishment_project
    db = SessionLocal()
    try:
        est_obj, project = load_establishment_project(db, est_id)
        return db, est_obj, project
    finally:
        pass  # caller closes db


def test_lock_status_reports_coverage_year_as_next_year_to_add_when_no_years_exist(consultant_a):
    est_id = _create_est(consultant_a, "GATE001", coverage_date="01-04-2026")
    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["coverage_year_key"] == "2026-27"
        assert status["next_year_to_add"] == "2026-27"
        assert status["locked_month"] is None
    finally:
        db.close()


def test_lock_status_locks_second_month_until_first_is_paid(consultant_a):
    est_id = _create_est(consultant_a, "GATE002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000001"})
    # Mar (month_idx 0) gets wage data but is never paid.
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["next_year_to_add"] is None
        assert status["locked_month"] == {"year_key": "2026-27", "month_idx": 1, "month_abbr": "Apr"}
    finally:
        db.close()


def test_lock_status_unlocks_second_month_once_first_is_paid(consultant_a, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATE003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000002"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    fee.is_paid = True
    test_db.commit()

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["locked_month"] is None
    finally:
        db.close()
```

- [ ] **Step 2: Confirm `load_establishment_project` exists with this signature**

Run: `Select-String -Path webapp/auth.py -Pattern "def load_establishment_project"`
If the helper has a different name/signature, adjust the test helper `_load_est_and_project` above to match what's actually in `webapp/auth.py` (it's the same loader `get_active_establishment` uses internally) before proceeding.

- [ ] **Step 3: Run tests to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: FAIL with `ImportError: cannot import name 'get_entry_lock_status'`

- [ ] **Step 4: Write the implementation**

In `webapp/app.py`, right after `get_coverage_year_key` (Task 1), add:

```python
def get_entry_lock_status(db: Session, est_obj: Establishment, project: Project) -> dict:
    """Walks this establishment's financial years in coverage-date chronological order
    and reports the single current entry-gating boundary.

    Returns {"coverage_year_key": str|None, "next_year_to_add": str|None,
             "locked_month": {"year_key": str, "month_idx": int, "month_abbr": str} | None}

    - next_year_to_add is set when the walk reaches a year that doesn't exist in
      project.years yet -- POST /api/years may only create exactly this year next.
    - locked_month is set when it reaches a year that DOES exist, but hits a month
      with no wage data yet whose immediately-preceding month isn't paid (or empty).
      POST /api/years/{key}/wages/bulk_month must reject saves at or after this
      (year_key, month_idx) UNLESS grandfathered (see caller).
    - Both None means nothing is currently locked (every existing year is fully
      paid/data-filled and the next chronological year hasn't been requested yet, or
      coverage_year_key itself is unknown -- shouldn't happen once coverage_date is
      mandatory, but fails open rather than blocking anything).
    """
    coverage_key = get_coverage_year_key(project)
    result = {"coverage_year_key": coverage_key, "next_year_to_add": None, "locked_month": None}
    if not coverage_key:
        return result

    year_from = int(coverage_key.split("-")[0])
    prev_month_satisfied = True  # nothing precedes the very first month

    while True:
        year_key = f"{year_from}-{str(year_from + 1)[-2:]}"
        if year_key not in project.years:
            result["next_year_to_add"] = year_key
            return result

        fee_rows = sync_subscription_fees_for_year(db, est_obj, project, year_key) or {}
        for month_idx in range(12):
            month_abbr = MONTH_SHORT_NAMES[month_idx]
            has_data = count_ecr_employees_for_month(project, year_key, month_idx) > 0
            if not has_data:
                if not prev_month_satisfied:
                    result["locked_month"] = {"year_key": year_key, "month_idx": month_idx, "month_abbr": month_abbr}
                return result
            fee_row = fee_rows.get(month_abbr)
            prev_month_satisfied = (fee_row is None) or fee_row.is_paid or fee_row.amount_due <= 0

        year_from += 1
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/test_month_year_entry_gating.py
git commit -m "feat: get_entry_lock_status -- chronological entry-gating boundary walk"
```

---

## Task 3: Gate `POST /api/years` on chronological order

**Files:**
- Modify: `webapp/app.py:4610` (`add_year`)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `get_entry_lock_status` (Task 2)

- [ ] **Step 1: Write the failing tests**

```python
def test_create_first_year_must_match_coverage_year(consultant_a):
    _create_est(consultant_a, "GATEYR001", coverage_date="01-04-2026")
    res = consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})
    assert res.status_code == 400
    assert "2026-27" in res.text


def test_create_first_year_matching_coverage_year_succeeds(consultant_a):
    _create_est(consultant_a, "GATEYR002", coverage_date="01-04-2026")
    res = consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res.status_code == 200, res.text


def test_cannot_create_second_year_before_first_is_fully_paid(consultant_a):
    _create_est(consultant_a, "GATEYR003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})
    assert res.status_code == 400
    assert "2026-27" in res.text


def test_superadmin_bypasses_chronological_year_order(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "GATEYR004", coverage_date="01-04-2026")
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post("/api/years", json={"year_from": "2030", "year_to": "2031"})
    assert res.status_code == 200, res.text


def test_first_year_creation_logs_activity_entry(consultant_a, test_db):
    from webapp.database import ActivityLog
    est_id = _create_est(consultant_a, "GATEYR005", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    entry = test_db.query(ActivityLog).filter(
        ActivityLog.establishment_id == est_id, ActivityLog.action_type == "entry_gating_started"
    ).first()
    assert entry is not None
    assert "2026-27" in entry.description


def test_second_year_creation_does_not_log_a_second_start_entry(consultant_a, test_db):
    from webapp.database import ActivityLog, SubscriptionFee
    est_id = _create_est(consultant_a, "GATEYR006", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    # Pay every month of 2026-27 so the second year is allowed to be created.
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()
    consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})

    count = test_db.query(ActivityLog).filter(
        ActivityLog.establishment_id == est_id, ActivityLog.action_type == "entry_gating_started"
    ).count()
    assert count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v -k GATEYR`
Expected: FAIL — `test_create_first_year_must_match_coverage_year` and `test_cannot_create_second_year_before_first_is_fully_paid` get 200 instead of 400 (no gating yet).

- [ ] **Step 3: Write the implementation**

Read `webapp/app.py` around line 4610 (`async def add_year`) first to confirm the current body still matches (it was last touched only by unrelated changes this session):

```python
@app.post("/api/years")
async def add_year(
    d: YearIn,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    key = f"{d.year_from}-{d.year_to[-2:]}"
    if key in project.years:
        raise HTTPException(400, f"Year {key} already exists")

    is_first_year_ever = len(project.years) == 0

    if current_user.role != "superadmin":
        status = get_entry_lock_status(db, est_obj, project)
        if status["next_year_to_add"] and key != status["next_year_to_add"]:
            raise HTTPException(
                400,
                f"You can only add financial years in order, starting from your establishment's "
                f"EPF Coverage Date. The next year you can add is {status['next_year_to_add']}."
            )

    project.add_year(d.year_from, d.year_to, d.scheme,
                     d.epf_rate, d.fpf_rate,
                     d.emp_epf_rate, d.er_epf_rate, d.er_eps_rate)
    save_establishment_project(db, est_obj, project)

    if is_first_year_ever:
        # Permanent audit record of when chronological entry-gating started for this
        # establishment -- see docs/superpowers/specs/2026-08-26-month-year-entry-gating-design.md
        # section 3.1. Purely informational: nothing reads this back to change enforcement,
        # which is derived live from chronological order + payment status every time.
        log_activity(
            db, current_user.id, est_obj.id, "entry_gating_started",
            f"{project.name} ({project.code}) began chronological month-by-month wage entry "
            f"starting from financial year {key} (EPF Coverage Date: {project.coverage_date}).",
            {"first_year_key": key, "coverage_date": project.coverage_date}
        )

    return {"ok": True, "key": key}
```

This adds `current_user: User = Depends(get_current_user)` to the existing signature (check it isn't already there before adding a duplicate parameter) and inserts the gating check plus the audit-log call around the existing `project.add_year(...)` call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v -k GATEYR`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/ -q`
Expected: all pass. If any existing test creates a second/out-of-order year as a *consultant* (not superadmin) without paying the first, it will now fail — fix that test's fixture to either pay the prior year's months first or switch the creating session to `superadmin_session`, matching how real backfill is supposed to work. Search first: `Select-String -Path webapp/tests/*.py -Pattern '"/api/years"' -Context 0,3` and check each hit's year-creation order against its coverage_date.

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/
git commit -m "feat: gate POST /api/years on chronological coverage-date order"
```

---

## Task 4: Lock `POST /api/years/bulk` to superadmin only

**Files:**
- Modify: `webapp/app.py:4632` (`bulk_add_years`)
- Modify: `webapp/js/years.js` (hide the "Bulk Generate Years" entry point for non-superadmin)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `App.isSuperadmin()` (existing, `webapp/js/app.js:38`)

- [ ] **Step 1: Write the failing tests**

```python
def test_consultant_cannot_bulk_create_years(consultant_a):
    _create_est(consultant_a, "GATEBULK001", coverage_date="01-04-2026")
    res = consultant_a.post("/api/years/bulk", json={"start_year": 2020, "end_year": 2026})
    assert res.status_code == 403


def test_superadmin_can_still_bulk_create_years(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "GATEBULK002", coverage_date="01-04-1990")
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post("/api/years/bulk", json={"start_year": 1990, "end_year": 1995})
    assert res.status_code == 200, res.text
    assert res.json()["added"] == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v -k GATEBULK`
Expected: FAIL — `test_consultant_cannot_bulk_create_years` gets 200 instead of 403.

- [ ] **Step 3: Write the backend implementation**

In `webapp/app.py`, modify `bulk_add_years` (currently at line 4632):

```python
@app.post("/api/years/bulk")
async def bulk_add_years(
    d: dict,
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "superadmin":
        raise HTTPException(403, "Bulk year creation is superadmin-only. Add years one at a time in chronological order from your establishment's EPF Coverage Date.")
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
```

(Adds the `current_user` dependency and the role check as the first line of the function body; the rest of the function is unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v -k GATEBULK`
Expected: PASS (2 tests)

- [ ] **Step 5: Hide the bulk-years UI for non-superadmin**

Read `webapp/js/years.js` around the button that calls `showBulkYearsModal()` (search for it) and wrap it so it only renders when `App.isSuperadmin()` is true, e.g.:

```javascript
${App.isSuperadmin() ? `<button class="btn btn-glass" onclick="showBulkYearsModal()">⚡ Bulk Generate Years</button>` : ''}
```

Use the exact button markup/text already in that file — read the surrounding toolbar block first and replace only the button's own line, don't reformat the rest of the toolbar.

- [ ] **Step 6: Run the full suite to check for regressions**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/ -q`
Expected: all pass. Any existing test that calls `POST /api/years/bulk` as a non-superadmin session will now fail — switch those calls to use `superadmin_session` (search: `Select-String -Path webapp/tests/*.py -Pattern '"/api/years/bulk"' -Context 2,2`).

- [ ] **Step 7: Commit**

```bash
git add webapp/app.py webapp/js/years.js webapp/tests/
git commit -m "feat: restrict bulk year creation to superadmin"
```

---

## Task 5: Gate Monthly Wage Entry saves (`POST /api/years/{key}/wages/bulk_month`)

**Files:**
- Modify: `webapp/app.py:4900` (`bulk_month_wages`)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `get_entry_lock_status` (Task 2), `count_ecr_employees_for_month` (existing)

- [ ] **Step 1: Write the failing tests**

```python
def test_cannot_save_second_month_wages_before_first_month_is_paid(consultant_a):
    _create_est(consultant_a, "GATEWAGE001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000003"})
    res1 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })
    assert res1.status_code == 200, res1.text

    res2 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 1, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })
    assert res2.status_code == 409
    assert "Mar" in res2.text


def test_re_saving_an_already_entered_month_is_never_blocked(consultant_a):
    """Grandfathering: editing a month that already has data must always be allowed,
    even though it isn't paid yet."""
    _create_est(consultant_a, "GATEWAGE002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000004"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })
    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wages": 16000, "wages": 16000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text


def test_month_unlocks_once_previous_month_paid(consultant_a, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATEWAGE003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000005"})
    consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })
    fee = test_db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id == est_id, SubscriptionFee.month == "Mar"
    ).first()
    fee.is_paid = True
    test_db.commit()

    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 1, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text


def test_superadmin_bypasses_monthly_wage_entry_gating(superadmin_session, consultant_a):
    est_id = _create_est(consultant_a, "GATEWAGE004", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000006"})
    superadmin_session.set_establishment(est_id)
    res = superadmin_session.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 5, "employees": [{"member_id": "M1", "gross_wages": 15000, "wages": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v -k GATEWAGE`
Expected: FAIL — `test_cannot_save_second_month_wages_before_first_month_is_paid` gets 200 instead of 409.

- [ ] **Step 3: Write the implementation**

Read `webapp/app.py` around line 4900 (`async def bulk_month_wages`) to see its current full body before editing (it loops over `d.employees` and upserts each one). Insert the gating check immediately after the existing `month_idx` range validation and before the `for emp_update in d.employees:` loop:

```python
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

    if current_user.role != "superadmin" and count_ecr_employees_for_month(project, key, d.month_idx) == 0:
        status = get_entry_lock_status(db, est_obj, project)
        lock = status["locked_month"]
        if lock and key == lock["year_key"] and d.month_idx >= lock["month_idx"]:
            raise HTTPException(
                409,
                f"{lock['month_abbr']} {lock['year_key']} must be entered and its fee paid before you can enter "
                f"{MONTH_SHORT_NAMES[d.month_idx]} {key}."
            )

    for emp_update in d.employees:
        # ... existing loop body unchanged, do not modify below this point
```

The grandfathering check (`count_ecr_employees_for_month(...) == 0`) happens *before* computing `get_entry_lock_status` specifically so an edit to an already-entered month never even triggers the lock-status walk — cheaper, and matches spec 3.3 exactly ("skip the check if the target month already has wage data").

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v -k GATEWAGE`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/ -q`
Expected: all pass. Any existing test that saves wages for a non-Mar month before Mar's fee is paid (as a non-superadmin) will now fail with 409 — check each failure and either pay the earlier months first in that test's setup or switch to `superadmin_session`, whichever preserves what that test is actually trying to verify.

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/
git commit -m "feat: gate Monthly Wage Entry saves on chronological month-paid order"
```

---

## Task 6: Read-only lock-status endpoint + short month names in `/api/constants`

**Files:**
- Modify: `webapp/app.py:6039` (`/api/constants`)
- Modify: `webapp/app.py` (new endpoint, near the other `/api/establishment/...` routes around line 3710)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `get_entry_lock_status` (Task 2)
- Produces: `GET /api/establishment/entry-lock-status` — JSON `{"coverage_year_key": str|None, "next_year_to_add": str|None, "locked_month": {...}|None}`; `/api/constants` gains a `"month_short_names"` key.

- [ ] **Step 1: Write the failing tests**

```python
def test_entry_lock_status_endpoint_reports_current_boundary(consultant_a):
    _create_est(consultant_a, "GATESTATUS001", coverage_date="01-04-2026")
    res = consultant_a.get("/api/establishment/entry-lock-status")
    assert res.status_code == 200
    body = res.json()
    assert body["coverage_year_key"] == "2026-27"
    assert body["next_year_to_add"] == "2026-27"
    assert body["locked_month"] is None


def test_constants_endpoint_includes_short_month_names(client):
    res = client.get("/api/constants")
    assert res.status_code == 200
    body = res.json()
    assert body["month_short_names"] == ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
    # The existing long-form labels must be untouched -- other pages (ECR, remittances) rely on them.
    assert body["months"][0] == "Mar Paid in Apr"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v -k "GATESTATUS or short_month"`
Expected: FAIL — 404 on the new endpoint, `KeyError: 'month_short_names'` on `/api/constants`.

- [ ] **Step 3: Write the implementation**

In `webapp/app.py`, modify `/api/constants` (currently at line 6039):

```python
@app.get("/api/constants")
async def constants():
    return {
        "months": list(MONTHS),
        "month_short_names": list(MONTH_SHORT_NAMES),
        "reasons": REASONS_FOR_LEAVING,
        "schemes": [
            {"v": SCHEME_PRE_1997, "l": "Pre-1997 (EPF + FPF)"},
            {"v": SCHEME_POST_1997, "l": "1997-98 onwards (EPF 12% + EPS 8.33%)"},
        ],
    }
```

Then add a new endpoint near `GET /api/establishment/subscription-status` (currently at line 3710):

```python
@app.get("/api/establishment/entry-lock-status")
async def get_entry_lock_status_endpoint(
    active: Tuple[Establishment, Project] = Depends(get_active_establishment),
    db: Session = Depends(get_db)
):
    est_obj, project = active
    return get_entry_lock_status(db, est_obj, project)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: PASS (all tests in the file, ~20 total)

- [ ] **Step 5: Commit**

```bash
git add webapp/app.py webapp/tests/
git commit -m "feat: entry-lock-status endpoint + short month names in /api/constants"
```

---

## Task 7: Frontend — Monthly Wage Entry surfaces lock state

**Files:**
- Modify: `webapp/js/wages.js` (the `App.registerPage('wage-entry', ...)` handler, ~line 926, and `saveMonthlyWages()`)

**Interfaces:**
- Consumes: `GET /api/establishment/entry-lock-status` (Task 6), `constantsCache.month_short_names` (Task 6), `App.isSuperadmin()` (existing)

- [ ] **Step 1: Switch the month dropdown to plain month names**

In the `'wage-entry'` page handler (~line 961-962), change:

```javascript
const mths = constantsCache.months;
const monthOptions = mths.map((m, i) => `<option value="${i}">${m}</option>`).join('');
```

to:

```javascript
const mths = constantsCache.month_short_names;
const monthOptions = mths.map((m, i) => `<option value="${i}">${m}</option>`).join('');
```

(`constantsCache.months` — the "Mar Paid in Apr" long form — is left untouched everywhere else; only this one dropdown switches to the short form.)

- [ ] **Step 2: Fetch and store lock status when the page loads**

In the same handler, right after `currentWagesData = await App.get(...)` (~line 944), add:

```javascript
window._entryLockStatus = App.isSuperadmin() ? null : await App.get('/api/establishment/entry-lock-status').catch(() => null);
```

- [ ] **Step 3: Disable locked month options in the dropdown**

Change the `monthOptions` line from Step 1 to mark options at or after the lock boundary as disabled, when the lock applies to the currently-selected year:

```javascript
const lock = window._entryLockStatus && window._entryLockStatus.locked_month;
const monthOptions = mths.map((m, i) => {
  const isLocked = lock && lock.year_key === currentYearKey && i >= lock.month_idx;
  return `<option value="${i}" ${isLocked ? 'disabled' : ''}>${m}${isLocked ? ' 🔒' : ''}</option>`;
}).join('');
```

- [ ] **Step 4: Reject the save with a clear message if the selected month is locked**

Find `saveMonthlyWages()` in `webapp/js/wages.js` (search for `async function saveMonthlyWages` or `window.saveMonthlyWages`) and add a guard as its first lines, reading the currently-selected month from `document.getElementById('bulk-month-select').value`:

```javascript
async function saveMonthlyWages() {
  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  const lock = window._entryLockStatus && window._entryLockStatus.locked_month;
  if (lock && lock.year_key === currentYearKey && monthIdx >= lock.month_idx) {
    App.toast(`${lock.month_abbr} ${lock.year_key} must be entered and paid before you can enter this month.`, 'error');
    return;
  }
  // ... existing function body continues unchanged below this point
```

Read the existing function first to confirm its exact current signature/body before inserting this guard — do not duplicate the `async function saveMonthlyWages() {` line.

- [ ] **Step 5: Manual verification (this task has no automated frontend tests in this codebase)**

Start a throwaway local server (`DATABASE_URL` pointed at an isolated SQLite file, per this project's established convention — see any prior session's `Local DB safety` notes), seed a consultant + establishment with a locked coverage_date and one unpaid month of wage data, and in the browser confirm: the next month's dropdown option shows disabled with a 🔒, and attempting to save into it (e.g. via `document.getElementById('bulk-month-select').value = 'N'; saveMonthlyWages()` in the console, bypassing the disabled UI) shows the toast and does not call the API.

- [ ] **Step 6: Commit**

```bash
git add webapp/js/wages.js
git commit -m "feat: Monthly Wage Entry UI reflects chronological entry-lock status"
```

---

## Task 8: Frontend — one-time explainer modal on first financial year

The real backend record of "entry-gating started" is the `ActivityLog` row Task 3 already writes on first-year creation. This task is purely the UI companion — showing the user what that means, once, right when it happens. The `localStorage` flag below only prevents re-showing the same modal on every page load; it carries no gating logic of its own.

**Files:**
- Modify: `webapp/js/years.js` (wherever "Add Financial Year" success is handled)

**Interfaces:**
- Consumes: none new — a client-side `localStorage` flag per browser purely to avoid repeat pop-ups (per Global Constraints: no persisted flag that changes gating behavior).

- [ ] **Step 1: Find the Add Year success handler**

Search `webapp/js/years.js` for the function that calls `App.post('/api/years', ...)` (the single-year, non-bulk creation) and locate its success branch.

- [ ] **Step 2: Show the explainer once, only for a establishment's very first year**

Immediately after that success branch's existing `App.toast(...)` / `App.navigate(...)` calls, add:

```javascript
const estId = App.getCurrentEstablishmentId();
const seenKey = `epf_seen_entry_gating_explainer_${estId}`;
if (!localStorage.getItem(seenKey)) {
  localStorage.setItem(seenKey, '1');
  App.openModal(
    'How Monthly Wage Entry Works Now',
    `<p style="color:var(--text2); font-size:13px; line-height:1.6;">
      You can enter wages one month at a time, starting from your establishment's EPF Coverage Date.
      Each month unlocks for entry once the previous month's subscription fee is paid
      (or auto-covered from your Advance Credit balance).
    </p>
    <p style="color:var(--text2); font-size:13px; line-height:1.6; margin-top:10px;">
      Need to enter an earlier month or year? Add that financial year the same way you just did --
      you'll be asked to pay it in the same chronological order.
    </p>`,
    `<button class="btn btn-primary" onclick="App.closeModal()">Got it</button>`
  );
}
```

This uses a `localStorage` flag purely to avoid re-showing the same modal every time (a UX nicety), not as any kind of gating state — the actual gating logic (Tasks 2-5) works identically whether or not this modal was ever shown or dismissed.

- [ ] **Step 3: Manual verification**

In the browser, as a fresh consultant with no financial years yet, add the first year and confirm the modal appears exactly once; navigate away and add a second establishment's first year and confirm it appears again (per-establishment, via the `estId` in `seenKey`).

- [ ] **Step 4: Commit**

```bash
git add webapp/js/years.js
git commit -m "feat: one-time explainer modal on first financial year (UI-only, no backend state)"
```

---

## Task 9: Full-suite regression pass and manual end-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Run the complete backend test suite**

Run: `.\venv\Scripts\python.exe -m pytest webapp/tests/ -q`
Expected: all tests pass (pre-existing count + the ~20 new tests from Tasks 1-6).

- [ ] **Step 2: End-to-end manual verification in the browser**

Using a throwaway local server + isolated SQLite DB (never the production `DATABASE_URL`):
1. Create a consultant, create an establishment with a coverage date, confirm the explainer modal appears on adding the first year.
2. Add an employee, enter wages for the first month via Monthly Wage Entry, confirm the second month's dropdown option is locked.
3. Mark the first month's `SubscriptionFee` paid directly via the database (simulating a real payment, same technique used earlier this session for the Advance Credit balance verification), reload the page, confirm the second month unlocks.
4. As the same consultant, attempt `POST /api/years/bulk` via the browser console — confirm 403.
5. Log in as superadmin on the same establishment, confirm every lock is bypassed (locked month enterable, bulk years works).

- [ ] **Step 3: Clean up throwaway server/DB/log files, per this project's established convention.**

- [ ] **Step 4: Final commit if any fixes were needed during verification**

```bash
git add -A
git commit -m "fix: address issues found during month/year entry-gating verification"
```
