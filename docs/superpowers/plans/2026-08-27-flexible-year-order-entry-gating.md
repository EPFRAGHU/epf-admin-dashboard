# Flexible Year-Order Entry Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the strict chronological month/year wage-entry gate with a flexible one: financial years can be added in any order (backfill or forward-fill) as long as the most-recently-added year is fully paid, and months within an added year become entirely free-form (no order, no per-month payment gate) — only the calendar ceiling (can't enter a month that hasn't ended yet) survives.

**Architecture:** `epf_engine.YearRecord` gains an `added_at` timestamp so "most recently added" can be determined even when years are added out of financial-year order. `get_entry_lock_status` in `webapp/app.py` is rewritten from an O(N-years) chronological walk into an O(1) check of just that one year. Three endpoints (`POST /api/years`, `POST /api/years/{key}/wages/bulk_month`, `GET /api/establishment/entry-lock-status`) consume the new contract; a fourth (`POST /api/years/{key}/wages`, the legacy whole-year endpoint) loses a stopgap guard that no longer applies. Two frontend files (`years.js`, `wages.js`) drop UI built around the old contract.

**Tech Stack:** FastAPI + SQLAlchemy (Postgres/SQLite) backend in `webapp/app.py`, a dataclass-based domain model in `epf_engine.py`, vanilla JS frontend, pytest.

**Spec:** [docs/superpowers/specs/2026-08-27-flexible-year-order-entry-gating-design.md](../specs/2026-08-27-flexible-year-order-entry-gating-design.md)

## Global Constraints

- `coverage_date` stays mandatory at creation and locked except for superadmin — unchanged, do not touch `_normalize_coverage_date` or the `PUT /api/establishment` lock logic.
- Download gating (`get_unpaid_months_for_year`, `is_month_overdue`, the 402 flow, Cashfree, advance credit, trial exemption on downloads) is unchanged — do not touch it.
- `POST /api/years/bulk` stays superadmin-only and untouched (it doesn't call `sync_subscription_fees_for_year` today and doesn't need to).
- Superadmin bypasses every rule this plan touches (year floor, year-order payment condition, month calendar ceiling) — every new backend check must be gated behind `if current_user.role != "superadmin":`, matching the code being replaced.
- Every backend test in this plan uses the existing fixtures/helpers already defined in `webapp/tests/test_month_year_entry_gating.py`: `consultant_a`, `superadmin_session`, `test_db`, `client` (from `webapp/tests/conftest.py`), and `_create_est(consultant, code, coverage_date=...)` / `_load_est_and_project(est_id)` (defined at the top of that same test file, lines 41–65 as of this plan). Do not redefine them.
- Run `pytest webapp/tests/test_month_year_entry_gating.py -v` after every task's test-writing step, and `pytest webapp/tests/ -q` as the final full-suite check in the last task.
- This is statutory compliance software for a production system with a real production Postgres database — do not run anything against production; tests already isolate themselves onto `test_epf.db` via `webapp/tests/conftest.py`.

---

## Task 1: `epf_engine.YearRecord` gains `added_at`

**Files:**
- Modify: `epf_engine.py:875-913` (the `YearRecord` dataclass) and `epf_engine.py:1131-1140` (`Project.add_year`)
- Test: `webapp/tests/test_month_year_entry_gating.py` (append new tests near the top, after the existing `test_get_coverage_year_key_returns_none_when_blank` at line 31)

**Interfaces:**
- Produces: `YearRecord.added_at: str` (ISO 8601 datetime string, e.g. `"2026-08-27T14:23:01.123456"`), populated by `Project.add_year(...)` and by `YearRecord.from_dict(...)` (with a synthetic fallback when missing from old data). Later tasks read `project.years[key].added_at`.

- [ ] **Step 1: Write the failing tests**

Open `webapp/tests/test_month_year_entry_gating.py` and insert this block immediately after `test_get_coverage_year_key_returns_none_when_blank` (currently ending at line 34) and before the `from webapp.database import SessionLocal` import at line 37:

```python
def test_year_record_added_at_is_stamped_on_creation():
    from epf_engine import Project as _P
    from datetime import datetime as _dt
    p = _P()
    p.coverage_date = "01-04-2020"
    p.add_year("2020", "2021")
    added_at = p.years["2020-21"].added_at
    assert added_at
    _dt.fromisoformat(added_at)  # must not raise


def test_year_record_added_at_reflects_real_add_order_not_fy_order():
    """added_at must track when a year was actually added, not its financial-year
    order -- years can now be added out of order (backfill or forward-fill), so
    financial-year order can no longer be used to find "the most recently added
    year"."""
    from epf_engine import Project as _P
    p = _P()
    p.coverage_date = "01-04-2020"
    p.add_year("2025", "2026")  # added first, even though FY-later
    p.add_year("2020", "2021")  # added second, even though FY-earlier
    assert p.years["2020-21"].added_at > p.years["2025-26"].added_at


def test_year_record_from_dict_synthesizes_added_at_when_missing():
    """Establishments serialized before this change have no added_at in their JSON
    blob. Every one of their pre-existing years was necessarily added in strict
    chronological order under the old gate, so from_dict must reconstruct that
    relative order (via the year's own FY start) rather than leaving it blank --
    otherwise a legacy establishment's "most recently added year" would be
    undefined the first time it's loaded after this change ships."""
    from epf_engine import YearRecord
    d = {"year_from": "2020", "year_to": "2021", "entries": [], "remittances": []}
    yr = YearRecord.from_dict(d)
    assert yr.added_at == "2020-04-01T00:00:00"


def test_year_record_from_dict_preserves_real_added_at_when_present():
    from epf_engine import YearRecord
    d = {"year_from": "2020", "year_to": "2021", "added_at": "2026-08-27T10:00:00.123456",
         "entries": [], "remittances": []}
    yr = YearRecord.from_dict(d)
    assert yr.added_at == "2026-08-27T10:00:00.123456"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k added_at -v`
Expected: FAIL — `AttributeError: 'YearRecord' object has no attribute 'added_at'` (or similar) on all four.

- [ ] **Step 3: Add `added_at` to `YearRecord` and stamp it in `Project.add_year`**

In `epf_engine.py`, the `YearRecord` dataclass currently reads (lines 875-885):

```python
class YearRecord(ContributionSchemeMixin):
    year_from: str = ""
    year_to: str = ""
    scheme: str = SCHEME_PRE_1997          # SCHEME_PRE_1997 or SCHEME_POST_1997
    epf_rate: float = 6.84       # PRE-1997 only
    fpf_rate: float = 1.16       # PRE-1997 only
    emp_epf_rate: float = 12.0   # POST-1997 only: worker's EPF %
    er_epf_rate: float = 3.67    # POST-1997 only: employer's EPF portion %
    er_eps_rate: float = 8.33    # POST-1997 only: employer's Pension Fund portion %
    entries: List[YearEntry] = field(default_factory=list)
    remittances: List[dict] = field(default_factory=list)
```

Add `added_at` before `entries`:

```python
class YearRecord(ContributionSchemeMixin):
    year_from: str = ""
    year_to: str = ""
    scheme: str = SCHEME_PRE_1997          # SCHEME_PRE_1997 or SCHEME_POST_1997
    epf_rate: float = 6.84       # PRE-1997 only
    fpf_rate: float = 1.16       # PRE-1997 only
    emp_epf_rate: float = 12.0   # POST-1997 only: worker's EPF %
    er_epf_rate: float = 3.67    # POST-1997 only: employer's EPF portion %
    er_eps_rate: float = 8.33    # POST-1997 only: employer's Pension Fund portion %
    # ISO 8601 datetime string, stamped once by Project.add_year(). Source of truth for
    # "most recently added year" in webapp/app.py's get_entry_lock_status -- NOT
    # financial-year order, since years can now be added out of order (backfill or
    # forward-fill). See docs/superpowers/specs/2026-08-27-flexible-year-order-entry-gating-design.md.
    added_at: str = ""
    entries: List[YearEntry] = field(default_factory=list)
    remittances: List[dict] = field(default_factory=list)
```

`to_dict()` (a few lines below, uses `asdict(self)`) needs no change — `added_at` serializes automatically.

Replace `from_dict` (currently):

```python
    @staticmethod
    def from_dict(d):
        entries = [YearEntry.from_dict(e) for e in d.get("entries", [])]
        return YearRecord(year_from=d.get("year_from", ""), year_to=d.get("year_to", ""),
                           scheme=d.get("scheme", SCHEME_PRE_1997),
                           epf_rate=d.get("epf_rate", 6.84), fpf_rate=d.get("fpf_rate", 1.16),
                           emp_epf_rate=d.get("emp_epf_rate", 12.0),
                           er_epf_rate=d.get("er_epf_rate", 3.67),
                           er_eps_rate=d.get("er_eps_rate", 8.33),
                           entries=entries,
                           remittances=d.get("remittances", []))
```

with:

```python
    @staticmethod
    def from_dict(d):
        entries = [YearEntry.from_dict(e) for e in d.get("entries", [])]
        year_from = d.get("year_from", "")
        # Pre-existing data has no added_at -- synthesize one from the year's own FY
        # start so relative order among a legacy establishment's years is preserved
        # (they were all necessarily added in strict chronological order under the old
        # gate). Falls back to "now" only in the pathological case of no year_from at all.
        added_at = d.get("added_at") or (
            f"{year_from}-04-01T00:00:00" if year_from else datetime.now().isoformat()
        )
        return YearRecord(year_from=year_from, year_to=d.get("year_to", ""),
                           scheme=d.get("scheme", SCHEME_PRE_1997),
                           epf_rate=d.get("epf_rate", 6.84), fpf_rate=d.get("fpf_rate", 1.16),
                           emp_epf_rate=d.get("emp_epf_rate", 12.0),
                           er_epf_rate=d.get("er_epf_rate", 3.67),
                           er_eps_rate=d.get("er_eps_rate", 8.33),
                           added_at=added_at,
                           entries=entries,
                           remittances=d.get("remittances", []))
```

Now update `Project.add_year` (currently, lines 1131-1140):

```python
    def add_year(self, year_from, year_to, scheme=SCHEME_PRE_1997,
                 epf_rate=6.84, fpf_rate=1.16,
                 emp_epf_rate=12.0, er_epf_rate=3.67, er_eps_rate=8.33):
        yr = YearRecord(year_from=year_from, year_to=year_to, scheme=scheme,
                         epf_rate=epf_rate, fpf_rate=fpf_rate,
                         emp_epf_rate=emp_epf_rate, er_epf_rate=er_epf_rate, er_eps_rate=er_eps_rate)
        key = yr.long_label
        self.years[key] = yr
        self.current_year_key = key
        return key
```

to:

```python
    def add_year(self, year_from, year_to, scheme=SCHEME_PRE_1997,
                 epf_rate=6.84, fpf_rate=1.16,
                 emp_epf_rate=12.0, er_epf_rate=3.67, er_eps_rate=8.33):
        yr = YearRecord(year_from=year_from, year_to=year_to, scheme=scheme,
                         epf_rate=epf_rate, fpf_rate=fpf_rate,
                         emp_epf_rate=emp_epf_rate, er_epf_rate=er_epf_rate, er_eps_rate=er_eps_rate,
                         added_at=datetime.now().isoformat())
        key = yr.long_label
        self.years[key] = yr
        self.current_year_key = key
        return key
```

(`datetime` is already imported at the top of `epf_engine.py` — `from datetime import datetime, date`.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k added_at -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full existing suite in this file to confirm nothing else broke**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: all pass (the new `added_at` field is additive and doesn't change any existing behavior yet)

- [ ] **Step 6: Commit**

```bash
git add epf_engine.py webapp/tests/test_month_year_entry_gating.py
git commit -m "feat: stamp YearRecord.added_at to track real year-addition order"
```

---

## Task 2: Rewrite `get_entry_lock_status` to the new O(1) contract

**Files:**
- Modify: `webapp/app.py:283-355` (the whole `get_entry_lock_status` function) and `webapp/app.py:394` (`sync_subscription_fees_for_year`'s signature — revert the now-unused `commit` parameter added in commit `5dc4406`)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `YearRecord.added_at` from Task 1; `is_establishment_in_trial(est_obj)`, `get_coverage_year_key(project)`, `sync_subscription_fees_for_year(db, est_obj, project, year_key)` (all already in `webapp/app.py`).
- Produces: `get_entry_lock_status(db, est_obj, project) -> dict` returning `{"coverage_year_key": str|None, "can_add_year": bool, "blocking_year": {"year_key": str, "amount_due": float}|None}`. Tasks 3 and 4 consume this new shape.

**Why the `commit` parameter reverts:** it was added in commit `5dc4406` specifically so the old `get_entry_lock_status`'s multi-year walk could batch its per-year `sync_subscription_fees_for_year` calls into one commit instead of N. The new version below only ever syncs a single year, so nothing will call it with `commit=False` again after this task — keeping an unused parameter around is dead flexibility.

- [ ] **Step 1: Remove the now-obsolete tests that exercised the multi-year walk**

These tests assert on `next_year_to_add`, `next_open_month`, or `locked_month` — fields that no longer exist — or exercise the walk-across-years mechanism that no longer exists. Delete these test functions entirely from `webapp/tests/test_month_year_entry_gating.py`:

- `test_lock_status_reports_coverage_year_as_next_year_to_add_when_no_years_exist` (currently lines 68-77)
- `test_lock_status_locks_second_month_until_first_is_paid` (lines 80-96)
- `test_lock_status_unlocks_second_month_once_first_is_paid` (lines 99-119)
- `test_lock_status_locks_current_month_even_when_fully_paid` (lines 512-528)
- `test_cannot_skip_ahead_of_an_open_but_unentered_month` (lines 563-593) — its skip-ahead assertions test a mechanism removed in Task 4; remove here since it also asserts on `next_open_month`/`locked_month`
- `test_entry_lock_status_multi_year_walk_persists_all_synced_years` (currently near the end of the file, after the member-id-truncation regression test) — this test specifically proves the multi-year commit-batching this task removes; it has nothing left to prove once the walk is gone

Also delete `test_entry_lock_status_endpoint_reports_current_boundary` (currently lines 280-287) — it will be replaced by a new version of the same test in Step 2 below (same name, new assertions against the new contract).

Run: `pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: the file still collects and runs (fewer tests now); everything remaining still passes, since none of it has been touched yet.

- [ ] **Step 2: Write the new failing tests**

Add these near where `test_entry_lock_status_endpoint_reports_current_boundary` used to be (its replacement is the first one below):

```python
def test_entry_lock_status_endpoint_reports_current_boundary(consultant_a):
    _create_est(consultant_a, "GATESTATUS001", coverage_date="01-04-2026")
    res = consultant_a.get("/api/establishment/entry-lock-status")
    assert res.status_code == 200
    body = res.json()
    assert body["coverage_year_key"] == "2026-27"
    assert body["can_add_year"] is True
    assert body["blocking_year"] is None


def test_lock_status_blocking_year_is_none_when_only_year_is_fully_paid(consultant_a, test_db):
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATESTATUS002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["can_add_year"] is True
        assert status["blocking_year"] is None
    finally:
        db.close()


def test_lock_status_blocking_year_reports_the_most_recently_added_unpaid_year(consultant_a):
    est_id = _create_est(consultant_a, "GATESTATUS003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000060"})
    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text
    # Mar 2026-27 has wage data and is unpaid -- this is the only (and therefore most
    # recently added) year, so it must block.

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["can_add_year"] is False
        assert status["blocking_year"]["year_key"] == "2026-27"
        assert status["blocking_year"]["amount_due"] > 0
    finally:
        db.close()


def test_lock_status_ignores_older_years_and_only_checks_the_most_recently_added_one(consultant_a, superadmin_session, test_db):
    """A year added earlier being unpaid must NOT block further additions once a LATER-
    added year (even if it's chronologically earlier as a financial year) is fully
    paid -- only the most-recently-ADDED year matters."""
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATESTATUS004", coverage_date="01-04-2020")
    superadmin_session.set_establishment(est_id)
    # Superadmin backfills 2020-21 (added first) and leaves it with no fee rows at all
    # (nothing billed, nothing paid) -- irrelevant, since it won't be "most recent".
    res1 = superadmin_session.post("/api/years", json={"year_from": "2020", "year_to": "2021"})
    assert res1.status_code == 200, res1.text

    # Consultant adds 2026-27 next (added SECOND, even though it's a later FY) and pays
    # every month of it.
    res2 = consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res2.status_code == 200, res2.text
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()

    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["can_add_year"] is True
        assert status["blocking_year"] is None
    finally:
        db.close()


def test_lock_status_can_add_year_true_when_no_years_exist_yet(consultant_a):
    est_id = _create_est(consultant_a, "GATESTATUS005", coverage_date="01-04-2026")
    db, est_obj, project = _load_est_and_project(est_id)
    try:
        status = get_entry_lock_status(db, est_obj, project)
        assert status["coverage_year_key"] == "2026-27"
        assert status["can_add_year"] is True
        assert status["blocking_year"] is None
    finally:
        db.close()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k "blocking_year or entry_lock_status_endpoint or can_add_year_true" -v`
Expected: FAIL — `KeyError: 'can_add_year'` (the old function doesn't return this key yet).

- [ ] **Step 4: Replace `get_entry_lock_status` and revert `sync_subscription_fees_for_year`'s `commit` parameter**

In `webapp/app.py`, replace the entire function currently at lines 283-355 (from `def get_entry_lock_status(db: Session, ...` through the final `year_from += 1` and its blank line before `def apply_advance_credit_if_available`) with:

```python
def get_entry_lock_status(db: Session, est_obj: Establishment, project: Project) -> dict:
    """Reports whether a new financial year may be added right now.

    Returns {"coverage_year_key": str|None, "can_add_year": bool,
             "blocking_year": {"year_key": str, "amount_due": float} | None}

    Financial years may be added in any order (backfill or forward-fill), not
    strictly chronologically -- see
    docs/superpowers/specs/2026-08-27-flexible-year-order-entry-gating-design.md.
    The only ordering rule left is: the most-recently-ADDED year (by
    YearRecord.added_at, NOT financial-year order -- years can be added out of
    order) must have no outstanding subscription-fee due before another year can
    be added. Trial establishments are exempt from this payment condition (never
    from the coverage_date floor, which callers check separately using
    coverage_year_key -- see POST /api/years).

    coverage_year_key is None only for a legacy establishment with no
    coverage_date on file -- callers fail open (no gating at all) in that case,
    same as before this rewrite.
    """
    coverage_key = get_coverage_year_key(project)
    result = {"coverage_year_key": coverage_key, "can_add_year": True, "blocking_year": None}
    if not project.years:
        return result

    latest_key = max(project.years, key=lambda k: datetime.fromisoformat(project.years[k].added_at))

    if is_establishment_in_trial(est_obj):
        return result

    fee_rows = sync_subscription_fees_for_year(db, est_obj, project, latest_key) or {}
    amount_due = round(sum(row.amount_due for row in fee_rows.values() if not row.is_paid and row.amount_due > 0), 2)
    if amount_due > 0:
        result["can_add_year"] = False
        result["blocking_year"] = {"year_key": latest_key, "amount_due": amount_due}
    return result
```

Then find `sync_subscription_fees_for_year`'s definition (now a few lines below) and revert its signature and final commit from:

```python
def sync_subscription_fees_for_year(db: Session, est_obj: Establishment, project: Project, year_key: str, commit: bool = True):
    """Sync or auto-generate 12-month subscription fee records for an establishment and financial year.

    commit=False lets a caller that syncs several years in one request (e.g.
    get_entry_lock_status's chronological walk) batch them into a single commit instead
    of one round-trip per year -- see that function for why this matters. Every other
    caller wants the default (commit immediately, as before).
```

to:

```python
def sync_subscription_fees_for_year(db: Session, est_obj: Establishment, project: Project, year_key: str):
    """Sync or auto-generate 12-month subscription fee records for an establishment and financial year.
```

and, further down in the same function, revert:

```python
    if commit:
        db.commit()
    return existing_rows
```

back to:

```python
    db.commit()
    return existing_rows
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: everything in the file up to this point passes. (Tests belonging to Tasks 3-9 that reference old behaviors not yet updated will still fail or error — that's expected and resolved in later tasks. If you're executing this plan task-by-task, only the tests written so far need to be green; the rest of the file may reference names like `next_open_month` until later tasks touch them.)

Since the rest of the file still has tests referencing the old contract, run just the tests written up through this task instead for a clean signal:

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k "added_at or blocking_year or entry_lock_status_endpoint or can_add_year_true or financial_year_key or coverage_year_key" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/test_month_year_entry_gating.py
git commit -m "feat: rewrite get_entry_lock_status as an O(1) most-recent-year check"
```

---

## Task 3: `POST /api/years` — flexible order, pay-per-added-year, audit every addition

**Files:**
- Modify: `webapp/app.py:4754-4808` (`add_year`)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `get_entry_lock_status(db, est_obj, project)` from Task 2 (`can_add_year`, `blocking_year`, `coverage_year_key`).
- Produces: no new interface for later tasks — this task's behavior is consumed only via the HTTP endpoint in tests and the frontend (Task 8).

- [ ] **Step 1: Remove tests that assert the old exact-next-year ordering or old error text**

Delete these test functions (they test the "must add years in exact chronological order" rule, which no longer exists):

- `test_create_first_year_must_match_coverage_year` (lines 122-126)
- `test_trial_status_does_not_break_chronological_year_add_ordering` (lines 332-343) — superseded by new coverage below
- `test_cannot_create_second_year_before_first_is_fully_paid` (lines 135-140) — this test never posts any wage data for the first year, so under the new "an empty year has nothing due" rule (an established, deliberate part of this design — see Task 2's `get_entry_lock_status`) it would now wrongly get a 200, not the 400 it asserts. Superseded by `test_cannot_add_another_year_while_most_recently_added_one_is_unpaid` below, which posts real wage data so there's an actual amount due to block on.

Run: `pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: file still collects; remaining tests you haven't touched yet still behave as before.

- [ ] **Step 2: Write the new failing tests**

```python
def test_cannot_add_year_before_coverage_year(consultant_a):
    _create_est(consultant_a, "GATEYR007", coverage_date="01-04-2026")
    res = consultant_a.post("/api/years", json={"year_from": "2025", "year_to": "2026"})
    assert res.status_code == 400
    assert "2026-27" in res.text


def test_can_add_a_forward_year_directly_as_the_first_year(consultant_a):
    """Years no longer need to exactly match the coverage year -- only be at or after
    it. A consultant onboarding an establishment can jump straight to a current/recent
    year without being forced through the coverage year first."""
    _create_est(consultant_a, "GATEYR008", coverage_date="01-04-2020")
    res = consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res.status_code == 200, res.text


def test_can_backfill_an_earlier_year_after_forward_filling_once_it_is_paid(consultant_a, test_db):
    """The core flexible-order scenario: add a recent year first, pay it off, then go
    back and add an older year -- order is free as long as coverage_date is respected
    and whatever was added most recently is paid up."""
    from webapp.database import SubscriptionFee
    est_id = _create_est(consultant_a, "GATEYR009", coverage_date="01-04-2020")
    res1 = consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    assert res1.status_code == 200, res1.text
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()

    res2 = consultant_a.post("/api/years", json={"year_from": "2020", "year_to": "2021"})
    assert res2.status_code == 200, res2.text


def test_cannot_add_another_year_while_most_recently_added_one_is_unpaid(consultant_a):
    est_id = _create_est(consultant_a, "GATEYR010", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000061"})
    res_wage = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res_wage.status_code == 200, res_wage.text

    res = consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})
    assert res.status_code == 400
    assert "2026-27" in res.text


def test_trial_establishment_can_add_next_year_despite_unpaid_prior_year(consultant_a, superadmin_session):
    """Trial establishments must never be payment-locked -- see
    is_establishment_in_trial. Confirms this now applies at the year-add gate."""
    est_id = _create_est(consultant_a, "GATETRIAL003", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000062"})
    res_wage = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res_wage.status_code == 200, res_wage.text
    # 2026-27 has data and is unpaid -- would block a normal establishment.

    superadmin_session.set_establishment(est_id)
    res_trial = superadmin_session.put(f"/api/admin/establishments/{est_id}/trial", json={"trial_ends_on": "2099-12-31"})
    assert res_trial.status_code == 200, res_trial.text

    res = consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})
    assert res.status_code == 200, res.text


def test_every_year_addition_logs_an_activity_entry(consultant_a, test_db):
    """Unlike entry_gating_started (logged once, on the first year only), a new
    'year.add' entry is logged on EVERY addition -- audit visibility for statutory
    compliance, per docs/superpowers/specs/2026-08-27-flexible-year-order-entry-gating-design.md."""
    from webapp.database import ActivityLog, SubscriptionFee
    est_id = _create_est(consultant_a, "GATEYR011", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    for m in ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]:
        test_db.add(SubscriptionFee(establishment_id=est_id, financial_year="2026-27", month=m,
                                     employee_count=0, amount_due=0, is_paid=True, billing_mode="per_employee"))
    test_db.commit()
    consultant_a.post("/api/years", json={"year_from": "2027", "year_to": "2028"})

    count = test_db.query(ActivityLog).filter(
        ActivityLog.establishment_id == est_id, ActivityLog.action_type == "year.add"
    ).count()
    assert count == 2
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k "add_year_before or forward_year_directly or backfill_an_earlier or cannot_add_another_year or trial_establishment_can_add_next_year or every_year_addition" -v`
Expected: FAIL (old endpoint still enforces exact-next-year matching and doesn't log `year.add`).

- [ ] **Step 4: Rewrite `add_year`**

Replace the whole function currently at `webapp/app.py:4754-4808`:

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
        if status["coverage_year_key"] and int(key.split("-")[0]) < int(status["coverage_year_key"].split("-")[0]):
            raise HTTPException(
                400,
                f"You cannot add a financial year before your establishment's EPF Coverage Date "
                f"(FY {status['coverage_year_key']})."
            )
        if not status["can_add_year"]:
            blocking = status["blocking_year"]
            raise HTTPException(
                400,
                f"FY {blocking['year_key']} has ₹{blocking['amount_due']} outstanding in subscription "
                f"fees -- pay it before adding another financial year."
            )

    project.add_year(d.year_from, d.year_to, d.scheme,
                     d.epf_rate, d.fpf_rate,
                     d.emp_epf_rate, d.er_epf_rate, d.er_eps_rate)
    save_establishment_project(db, est_obj, project)

    if is_first_year_ever:
        # Permanent audit record of when wage entry started for this establishment --
        # see docs/superpowers/specs/2026-08-26-month-year-entry-gating-design.md
        # section 3.1. Purely informational: nothing reads this back to change
        # enforcement, which is derived live from added_at + payment status every time.
        log_activity(
            db, current_user.id, est_obj.id, "entry_gating_started",
            f"{project.name} ({project.code}) began wage entry starting from financial year "
            f"{key} (EPF Coverage Date: {project.coverage_date}).",
            {"first_year_key": key, "coverage_date": project.coverage_date}
        )

    # Every addition (not just the first) is logged for audit visibility -- see
    # docs/superpowers/specs/2026-08-27-flexible-year-order-entry-gating-design.md,
    # "Data model change". Descriptive only, never read back to drive enforcement.
    log_activity(
        db, current_user.id, est_obj.id, "year.add",
        f"Added financial year {key} for {project.name} ({project.code}).",
        {"year_key": key}
    )

    return {"ok": True, "key": key}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k "add_year_before or forward_year_directly or backfill_an_earlier or cannot_add_another_year or trial_establishment_can_add_next_year or every_year_addition or GATEYR or first_year_creation_logs or second_year_creation_does_not or superadmin_bypasses_chronological or matching_coverage_year_succeeds" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/test_month_year_entry_gating.py
git commit -m "feat: allow adding financial years in any order, gated on the last-added one being paid"
```

---

## Task 4: `POST /api/years/{key}/wages/bulk_month` — free-form months, calendar ceiling only

**Files:**
- Modify: `webapp/app.py:5125-5200` (the gating block inside `bulk_month_wages`, up to where the `for emp_update in d.employees:` loop begins)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `get_max_enterable_month()` (already in `webapp/app.py`, unchanged).
- Produces: no new interface — behavior consumed via the HTTP endpoint by tests, the frontend (Task 9), and the download-gate tests (unaffected, verified in Task 7).

- [ ] **Step 1: Remove tests that assert the old month-order/payment gate**

Delete these test functions (they test month-level chronological/payment locking, which no longer exists):

- `test_cannot_save_second_month_wages_before_first_month_is_paid` (lines 192-205)
- `test_re_saving_an_already_entered_month_is_never_blocked` (lines 208-236) — grandfathering is moot once nothing blocks any month
- `test_month_unlocks_once_previous_month_paid` (lines 239-256)
- `test_superadmin_bypasses_monthly_wage_entry_gating` (lines 259-277) — redundant with `test_superadmin_bypasses_calendar_ceiling`, which remains
- `test_wage_save_gate_blocks_later_years_when_earlier_year_is_locked` (lines 349-374, including its preceding `# ── Finding 2 ──` comment block)
- `test_trial_establishment_is_never_locked_pending_payment` (lines 301-329) — superseded by `test_trial_establishment_can_add_next_year_despite_unpaid_prior_year` from Task 3

Run: `pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: file still collects; remaining tests behave as before (some may still fail — from tasks not yet done — that's expected).

- [ ] **Step 2: Write the new failing tests**

```python
def test_months_can_be_entered_in_any_order_within_a_year(consultant_a):
    """Core free-form behavior: entering a later month first, with an earlier month
    still empty and unpaid, must succeed -- no chronological order within a year."""
    est_id = _create_est(consultant_a, "GATEFREE001", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000070"})

    res = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 3, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res.status_code == 200, res.text

    res2 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res2.status_code == 200, res2.text


def test_months_can_be_entered_regardless_of_prior_month_payment_status(consultant_a):
    est_id = _create_est(consultant_a, "GATEFREE002", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000071"})

    res1 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 0, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res1.status_code == 200, res1.text
    # Mar left unpaid on purpose -- Apr must still be enterable.

    res2 = consultant_a.post("/api/years/2026-27/wages/bulk_month", json={
        "month_idx": 1, "employees": [{"member_id": "M1", "gross_wage": 15000, "epf_wage": 15000, "ncp_days": 0}]
    })
    assert res2.status_code == 200, res2.text
```

Now update the existing calendar-ceiling tests to remove their now-obsolete "skip-ahead isolation" framing and `next_open_month`/`locked_month` assertions. Replace `test_lock_status_locks_current_month_even_when_fully_paid` (already deleted in Task 2 -- skip) and `test_cannot_save_current_month_wages_even_fully_paid_through_previous` (currently lines 531-544, still present) is kept as-is (it only asserts on the `bulk_month_wages` HTTP response, not on `get_entry_lock_status`'s shape) — no change needed for it in this task.

Update `test_trial_establishment_still_bound_by_calendar_ceiling` (currently lines 596-622): its docstring references the now-removed "skip-ahead check". Replace just the docstring, keeping the rest of the test body identical:

Find:
```python
def test_trial_establishment_still_bound_by_calendar_ceiling(superadmin_session, consultant_a, test_db):
    """Trial exemption relaxes PAYMENT, never the calendar ceiling -- a month that
    hasn't ended yet can't be entered no matter how generous the billing terms are."""
```

Replace with:
```python
def test_trial_establishment_still_bound_by_calendar_ceiling(superadmin_session, consultant_a, test_db):
    """Trial exemption relaxes PAYMENT, never the calendar ceiling -- a month that
    hasn't ended yet can't be entered no matter how generous the billing terms are.
    Months are free-form now, so filling Mar..Jul below no longer needs to "isolate"
    anything -- it just demonstrates that entering several unpaid months succeeds
    freely, right up until the calendar ceiling itself stops Aug."""
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k "any_order_within_a_year or regardless_of_prior_month_payment" -v`
Expected: FAIL — 409 responses from the old gate.

- [ ] **Step 4: Replace the gating block in `bulk_month_wages`**

In `webapp/app.py`, the function currently reads (lines 5125-5202, ending right before `for emp_update in d.employees:`):

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
        next_open = status["next_open_month"]
        if next_open:
            ... [the whole block through the final raise HTTPException(409, ...) for the "unpaid" reason] ...

    for emp_update in d.employees:
```

Replace everything from `require_permission(db, current_user, "wages.edit")` through the line right before `for emp_update in d.employees:` with:

```python
    require_permission(db, current_user, "wages.edit")
    est_obj, project = active
    if key not in project.years:
        raise HTTPException(404, "Year not found")
    if not (0 <= d.month_idx <= 11):
        raise HTTPException(400, "Invalid month index")

    # Months within an already-added year are free-form -- no order, no per-month
    # payment gate. The only thing that can still block a specific month is the
    # calendar ceiling: a month that hasn't ended yet in real life can never be
    # entered, regardless of year or payment status. See
    # docs/superpowers/specs/2026-08-27-flexible-year-order-entry-gating-design.md.
    if current_user.role != "superadmin":
        target_year_from = int(key.split("-")[0])
        max_year_key, max_month_idx = get_max_enterable_month()
        max_year_from = int(max_year_key.split("-")[0])
        if (target_year_from, d.month_idx) > (max_year_from, max_month_idx):
            if d.month_idx <= 9:
                cal_month, cal_year = d.month_idx + 3, target_year_from
            else:
                cal_month, cal_year = d.month_idx - 9, target_year_from + 1
            opens_month, opens_year = cal_month + 1, cal_year
            if opens_month > 12:
                opens_month, opens_year = 1, opens_year + 1
            raise HTTPException(
                409,
                f"{MONTH_SHORT_NAMES[d.month_idx]} {key} cannot be entered until that month has ended "
                f"-- it opens on 01-{opens_month:02d}-{opens_year}."
            )

    for emp_update in d.employees:
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k "any_order_within_a_year or regardless_of_prior_month_payment or CEIL or calendar_ceiling" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/test_month_year_entry_gating.py
git commit -m "feat: make month entry free-form within a year, keep only the calendar ceiling"
```

---

## Task 5: Remove the obsolete stopgap guard from the legacy `POST /api/years/{key}/wages`

**Files:**
- Modify: `webapp/app.py:5051-5122` (`put_wages`)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — this task only removes now-broken code (it referenced `status["next_open_month"]` / `status["locked_month"]`, which no longer exist after Task 2, so left as-is this endpoint would `KeyError` on every non-superadmin call).

- [ ] **Step 1: Remove tests for the guard being deleted**

Delete these test functions (they test the stopgap guard's smuggle-prevention, which no longer applies once there's nothing to smuggle past):

- `test_legacy_wage_endpoint_cannot_smuggle_data_past_the_entry_lock` (lines 380-409, including its preceding `# ── Finding 4 ──` comment block)
- `test_legacy_wage_endpoint_still_allows_edits_to_already_entered_months` (lines 412-427)
- `test_legacy_wage_endpoint_allows_writes_before_the_lock_boundary` (lines 430-455)

Run: `pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: file still collects.

- [ ] **Step 2: Write the new failing test**

```python
def test_legacy_wage_endpoint_writes_any_month_freely(consultant_a):
    """POST /api/years/{key}/wages (the older 12-month-at-once endpoint) used to carry
    a stopgap guard against smuggling data past the entry lock (Finding 4 in the prior
    design). That lock no longer exists for months, so this endpoint needs no special
    guard at all -- writing into any month, entered or not, must simply succeed."""
    est_id = _create_est(consultant_a, "GATELEGACY004", coverage_date="01-04-2026")
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={"member_id": "M1", "name": "Emp One", "uan": "100000000072"})

    wages = [0] * 12
    wages[5] = 15000  # a month with no data yet, arbitrarily chosen
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "M1", "wages": wages, "gross_wages": wages
    })
    assert res.status_code == 200, res.text
```

- [ ] **Step 3: Run the test to verify it currently errors**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k legacy_wage_endpoint_writes_any_month_freely -v`
Expected: FAIL with a 500 / `KeyError: 'next_open_month'` (the guard still calls `get_entry_lock_status` and reads a field that no longer exists after Task 2).

- [ ] **Step 4: Delete the obsolete guard**

In `webapp/app.py`, `put_wages` currently contains (between the `ncp_days = ...` line and `project.upsert_entry(...)`):

```python
    # Finding 4 stopgap: this older, whole-year-in-one-call endpoint was deliberately
    # left out of the month-by-month entry gate (different semantics, doesn't map onto
    # a single-month check) -- but writing wage data into a month at/after the current
    # lock boundary would silently satisfy get_entry_lock_status's has_data check for
    # that month and clear locked_month back to None, unlocking bulk_month_wages for
    # months nothing was ever paid for. Block only the specific case that can dissolve
    # the gate: a NON-ZERO value going into a month that (a) is at/after the lock
    # boundary and (b) doesn't already have data from anyone (i.e. is the exact
    # condition bulk_month_wages itself would refuse). Edits to months that already
    # have data, and any month before the lock boundary, are left untouched.
    if current_user.role != "superadmin":
        status = get_entry_lock_status(db, est_obj, project)
        next_open = status["next_open_month"]
        if next_open:
            # Gate on next_open_month, not merely locked_month -- a month strictly AFTER
            # it is always blocked (skipping ahead), even when next_open_month itself
            # isn't currently locked for any reason. next_open_month itself is only
            # blocked when status["locked_month"] says so (see get_entry_lock_status /
            # bulk_month_wages for the full rationale) -- otherwise it's the legitimate
            # next slot and this write must be allowed to land on it.
            next_open_key = (int(next_open["year_key"].split("-")[0]), next_open["month_idx"])
            lock = status["locked_month"]
            target_year_from = int(key.split("-")[0])
            for month_idx in range(12):
                target = (target_year_from, month_idx)
                if target < next_open_key:
                    continue
                if target == next_open_key and not lock:
                    continue
                if capped_wages[month_idx] and capped_wages[month_idx] > 0 and \
                        count_ecr_employees_for_month(project, key, month_idx) == 0:
                    raise HTTPException(
                        409,
                        f"{MONTH_SHORT_NAMES[month_idx]} {key} is locked pending chronological entry and "
                        f"payment of an earlier month. Use Monthly Wage Entry to enter months in order."
                    )

    project.upsert_entry(key, d.member_id, capped_wages, ...
```

Delete the entire commented/guarded block (from `# Finding 4 stopgap:` through the closing of the `if current_user.role != "superadmin":` block), leaving:

```python
    project.upsert_entry(key, d.member_id, capped_wages, ...
```

directly after the `ncp_days = ...` line, with no gating in between.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k legacy_wage_endpoint -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/test_month_year_entry_gating.py
git commit -m "fix: remove obsolete entry-lock stopgap guard from legacy wages endpoint"
```

---

## Task 6: `/api/constants` gains `max_enterable_month`

**Files:**
- Modify: `webapp/app.py:6334-6344` (`constants`)
- Test: `webapp/tests/test_month_year_entry_gating.py`

**Interfaces:**
- Consumes: `get_max_enterable_month()` (already in `webapp/app.py`, unchanged).
- Produces: `/api/constants` response gains `"max_enterable_month": {"year_key": str, "month_idx": int}`. Task 9 (`wages.js`) consumes this.

- [ ] **Step 1: Extend the existing test**

`test_constants_endpoint_includes_short_month_names` (currently lines 290-297) already exists and stays — extend it in place. Find:

```python
def test_constants_endpoint_includes_short_month_names(client):
    res = client.get("/api/constants")
    assert res.status_code == 200
    body = res.json()
    assert body["month_short_names"] == ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
    # The existing long-form labels must be untouched -- other pages (ECR, remittances) rely on them.
    assert body["months"][0] == "Mar Paid in Apr"
```

Replace with:

```python
def test_constants_endpoint_includes_short_month_names(client):
    res = client.get("/api/constants")
    assert res.status_code == 200
    body = res.json()
    assert body["month_short_names"] == ["Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]
    # The existing long-form labels must be untouched -- other pages (ECR, remittances) rely on them.
    assert body["months"][0] == "Mar Paid in Apr"


def test_constants_endpoint_includes_max_enterable_month(client):
    with patch("webapp.app.date", _FrozenDate):
        res = client.get("/api/constants")
        assert res.status_code == 200
        body = res.json()
        assert body["max_enterable_month"] == {"year_key": "2026-27", "month_idx": 4}  # Jul, per _FrozenDate = 2026-08-26
```

This new test uses `_FrozenDate` and `patch`, both already imported further down in this same file (`from unittest.mock import patch` and the `_FrozenDate` class, currently around line 462-475) — since Python resolves names at call time, not definition time, this works even though the new test appears earlier in the file than those imports, as long as they're imported at module level before the test actually runs (they are, since the whole module loads before any test executes).

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k max_enterable_month -v`
Expected: FAIL — `KeyError: 'max_enterable_month'`.

- [ ] **Step 3: Update `/api/constants`**

In `webapp/app.py`, replace:

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

with:

```python
@app.get("/api/constants")
async def constants():
    max_year_key, max_month_idx = get_max_enterable_month()
    return {
        "months": list(MONTHS),
        "month_short_names": list(MONTH_SHORT_NAMES),
        "reasons": REASONS_FOR_LEAVING,
        "schemes": [
            {"v": SCHEME_PRE_1997, "l": "Pre-1997 (EPF + FPF)"},
            {"v": SCHEME_POST_1997, "l": "1997-98 onwards (EPF 12% + EPS 8.33%)"},
        ],
        # Pure calendar fact, independent of any establishment -- the latest
        # (year_key, month_idx) wage entry is ever allowed for. Drives the Monthly
        # Wage Entry month selector's calendar-ceiling disabling client-side
        # (webapp/js/wages.js) now that per-month server-side locking is gone.
        "max_enterable_month": {"year_key": max_year_key, "month_idx": max_month_idx},
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k max_enterable_month -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add webapp/app.py webapp/tests/test_month_year_entry_gating.py
git commit -m "feat: expose max_enterable_month via /api/constants"
```

---

## Task 7: Full backend verification pass

**Files:** none modified — verification only.

**Interfaces:** none.

- [ ] **Step 1: Run the entire gating test file**

Run: `pytest webapp/tests/test_month_year_entry_gating.py -v`
Expected: every test passes. If anything fails, it's very likely a leftover reference to `next_year_to_add` / `next_open_month` / `locked_month` somewhere not yet cleaned up by Tasks 2-5 — grep the file for those three strings and resolve any remaining occurrence before proceeding.

Run: `pytest webapp/tests/test_month_year_entry_gating.py -k "not added_at and not blocking_year"` with `-v` if you want to specifically re-confirm the download-gate tests (`NOGRACE*`) and the member-id-truncation regression (`test_entering_a_later_month_does_not_wipe_an_earlier_months_wages_for_long_member_id`) are untouched and still green — they should require no changes at all in this plan.

- [ ] **Step 2: Run the whole project test suite**

Run: `pytest webapp/tests/ -q`
Expected: all tests across every file pass (confirms nothing outside `test_month_year_entry_gating.py` depended on the old contract — Task 2's exploration already grepped the whole `webapp/tests/` tree and found no other references, but this is the real confirmation).

- [ ] **Step 3: Grep the whole webapp/ tree for any leftover reference to the removed contract fields**

Run: `grep -rn "next_year_to_add\|next_open_month\|locked_month" webapp/ epf_engine.py` (or the PowerShell equivalent: `Select-String -Path webapp\*.py,webapp\js\*.js,epf_engine.py -Pattern "next_year_to_add|next_open_month|locked_month" -Recurse`)
Expected: no matches (Tasks 8 and 9, not yet done at this point if executing in order, will still contain matches in `webapp/js/years.js` and `webapp/js/wages.js` — that's expected; this step is a checkpoint to confirm the *backend* is fully clean before moving to frontend work).

- [ ] **Step 4: Commit** (only if Step 3 required any fix; otherwise skip — this task is verification-only)

```bash
git add -A
git commit -m "test: verify full suite green after backend flexible-year-order rewrite"
```

---

## Task 8: `webapp/js/years.js` — new banner, free year-entry field, updated explainer copy

**Files:**
- Modify: `webapp/js/years.js` (whole file is only 309 lines; changes are scattered across it)

**Interfaces:**
- Consumes: `GET /api/establishment/entry-lock-status` response shape from Task 2 (`coverage_year_key`, `can_add_year`, `blocking_year`).
- Produces: nothing new for other files.

There is no backend test coverage for frontend JS in this codebase (no JS test runner is configured) — verify this task manually via the `run` skill / browser preview instead of pytest, per this task's own Step 4.

- [ ] **Step 1: Replace the `next_year_to_add` banner with the new `can_add_year` / `blocking_year` banner**

In `webapp/js/years.js`, find (near the top of the `App.registerPage('years', ...)` handler):

```javascript
  __lockStatus = await App.get('/api/establishment/entry-lock-status').catch(() => null);
  const nextYear = __lockStatus && __lockStatus.next_year_to_add;
```

Replace with:

```javascript
  __lockStatus = await App.get('/api/establishment/entry-lock-status').catch(() => null);
  const blockingYear = __lockStatus && __lockStatus.blocking_year;
```

Find:

```javascript
    ${nextYear ? `<div class="card" style="padding:10px 16px; margin-bottom:16px; font-size:13px; color:var(--text2);">
      📌 Next year you can add: <strong style="color:var(--text1);">${App.esc(nextYear)}</strong>
    </div>` : ''}
```

Replace with:

```javascript
    ${blockingYear ? `<div class="card" style="padding:10px 16px; margin-bottom:16px; font-size:13px; color:var(--text2);">
      💳 FY <strong style="color:var(--text1);">${App.esc(blockingYear.year_key)}</strong> has
      <strong style="color:var(--text1);">₹${App.esc(String(blockingYear.amount_due))}</strong> outstanding in
      subscription fees — pay it before adding another financial year.
    </div>` : ''}
```

- [ ] **Step 2: Stop force-prefilling the Add Year form's year field**

Find (inside `showYearModal`):

```javascript
  setTimeout(() => {
    if (!isEdit) {
      const nextYear = __lockStatus && __lockStatus.next_year_to_add;
      if (nextYear) {
        document.getElementById('y-from').value = nextYear.split('-')[0];
        autoFillToYear();
      } else {
        autoFillRates();
      }
    } else {
      toggleSchemeFields(yr.scheme);
    }
  }, 10);
```

Replace with:

```javascript
  setTimeout(() => {
    if (!isEdit) {
      // Years can now be added in any order (backfill or forward-fill) -- no single
      // "next year" to force into the field. Leave it blank; autoFillToYear() (wired
      // to oninput on y-from) fills the scheme/rates in once the consultant/employer
      // types a year.
      autoFillRates();
    } else {
      toggleSchemeFields(yr.scheme);
    }
  }, 10);
```

- [ ] **Step 3: Update the one-time explainer modal copy**

Find (inside `saveYear`):

```javascript
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
```

Replace with:

```javascript
        App.openModal(
          'How Wage Entry Works Now',
          `<p style="color:var(--text2); font-size:13px; line-height:1.6;">
            You can add financial years in any order — backfill an older year or jump straight to a
            recent one — as long as it's not before your establishment's EPF Coverage Date. Within a
            year, months can be entered in any order too.
          </p>
          <p style="color:var(--text2); font-size:13px; line-height:1.6; margin-top:10px;">
            Before adding another financial year, the one you most recently added needs its
            subscription fees fully paid (or auto-covered from your Advance Credit balance). A month
            can never be entered before it's actually ended on the calendar, no matter which year.
          </p>`,
          `<button class="btn btn-primary" onclick="App.closeModal()">Got it</button>`
        );
```

- [ ] **Step 4: Manually verify in the browser preview**

Use the `run` skill (or `preview_start` with the project's dev-server launch config) to start the app, sign in as a consultant with an establishment that has no years yet, open the Years page, and confirm:
- No "Next year you can add" banner appears when nothing is blocking.
- The Add Year modal's Year From field is blank (not pre-filled/read-only).
- After adding a year with unpaid wage data, the new "FY ... outstanding" banner appears.
- The one-time explainer modal (first year only) shows the new copy.

- [ ] **Step 5: Commit**

```bash
git add webapp/js/years.js
git commit -m "feat: update Years UI for flexible year-order entry gating"
```

---

## Task 9: `webapp/js/wages.js` — remove month-locking UI, use `max_enterable_month`

**Files:**
- Modify: `webapp/js/wages.js:926-1013` (page load / month-dropdown construction) and `webapp/js/wages.js:1736-1790` (`saveMonthlyWages`'s client-side pre-check)

**Interfaces:**
- Consumes: `max_enterable_month` from `/api/constants` (Task 6), already fetched into `constantsCache` at the top of `App.registerPage('wage-entry', ...)`.
- Produces: nothing new.

Same as Task 8, verify manually — no JS test runner in this codebase.

- [ ] **Step 1: Drop the `entry-lock-status` fetch and the `next_open_month`/`locked_month`-based month-disabling logic**

Find (inside `App.registerPage('wage-entry', ...)`):

```javascript
  window._entryLockStatus = App.isSuperadmin() ? null : await App.get('/api/establishment/entry-lock-status').catch(() => null);

  // Ensure master employees are loaded
```

Replace with:

```javascript
  // Ensure master employees are loaded
```

Find:

```javascript
  const mths = constantsCache.month_short_names;
  // Gate on next_open_month, not merely locked_month -- a month strictly AFTER it is
  // always blocked (skipping ahead), even when next_open_month itself isn't currently
  // locked for any reason. next_open_month itself is only disabled when locked_month
  // says so -- otherwise it's the legitimate next slot and must stay enabled. See
  // get_entry_lock_status / bulk_month_wages in webapp/app.py for the full rationale.
  const nextOpen = window._entryLockStatus && window._entryLockStatus.next_open_month;
  const isLockedField = window._entryLockStatus && window._entryLockStatus.locked_month;
  // Compare chronologically (year_from, month_idx), not year_key equality -- a month in
  // a LATER financial year than the next-open one is also at/after the boundary, not
  // just months within the exact next-open year (Finding 2).
  const nextOpenYearFrom = nextOpen ? parseInt(nextOpen.year_key.split('-')[0], 10) : null;
  const currentYearFrom = parseInt(currentYearKey.split('-')[0], 10);
  const isDisabled = (i) => {
    if (!nextOpen) return false;
    const isAfter = currentYearFrom > nextOpenYearFrom || (currentYearFrom === nextOpenYearFrom && i > nextOpen.month_idx);
    if (isAfter) return true;
    const isExactlyNextOpen = currentYearFrom === nextOpenYearFrom && i === nextOpen.month_idx;
    return isExactlyNextOpen && !!isLockedField;
  };
  const monthOptions = mths.map((m, i) => {
    const isLocked = isDisabled(i);
    return `<option value="${i}" ${isLocked ? 'disabled' : ''}>${m}${isLocked ? ' 🔒' : ''}</option>`;
  }).join('');
```

Replace with:

```javascript
  const mths = constantsCache.month_short_names;
  // Months are free-form now -- the only thing that can still disable a month in this
  // dropdown is the calendar ceiling (a month that hasn't ended yet in real life),
  // which applies uniformly regardless of which year is selected. Superadmin bypasses
  // it entirely, same as the backend (webapp/app.py, bulk_month_wages).
  const maxEnterable = constantsCache.max_enterable_month;
  const currentYearFrom = parseInt(currentYearKey.split('-')[0], 10);
  const isDisabled = (i) => {
    if (App.isSuperadmin() || !maxEnterable) return false;
    const maxYearFrom = parseInt(maxEnterable.year_key.split('-')[0], 10);
    return currentYearFrom > maxYearFrom || (currentYearFrom === maxYearFrom && i > maxEnterable.month_idx);
  };
  const monthOptions = mths.map((m, i) => {
    const isLocked = isDisabled(i);
    return `<option value="${i}" ${isLocked ? 'disabled' : ''}>${m}${isLocked ? ' 🔒' : ''}</option>`;
  }).join('');
```

- [ ] **Step 2: Simplify `saveMonthlyWages`'s client-side pre-check to the calendar ceiling only**

Find (the whole block at the top of `window.saveMonthlyWages`):

```javascript
window.saveMonthlyWages = async () => {
  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  const nextOpen = window._entryLockStatus && window._entryLockStatus.next_open_month;
  const lock = window._entryLockStatus && window._entryLockStatus.locked_month;
  if (nextOpen) {
    // Compare chronologically (year_from, month_idx), not year_key equality -- a save
    // into a LATER financial year than next_open_month must also be blocked
    // client-side (Finding 2), matching the backend's chronological comparison.
    const nextOpenYearFrom = parseInt(nextOpen.year_key.split('-')[0], 10);
    const currentYearFrom = parseInt(currentYearKey.split('-')[0], 10);
    const isAtOrAfterNextOpen = currentYearFrom > nextOpenYearFrom || (currentYearFrom === nextOpenYearFrom && monthIdx >= nextOpen.month_idx);
    const isExactlyNextOpen = currentYearFrom === nextOpenYearFrom && monthIdx === nextOpen.month_idx;
    const monthShortNames = constantsCache.month_short_names;

    if (isAtOrAfterNextOpen && !isExactlyNextOpen) {
      // Skipping straight past a month that hasn't been entered yet, even though
      // that month itself might not currently carry a lock reason.
      App.toast(`${nextOpen.month_abbr} ${nextOpen.year_key} must be entered before you can enter ${monthShortNames[monthIdx]} ${currentYearKey}.`, 'error');
      return;
    }

    if (isExactlyNextOpen && lock) {
      if (lock.reason === 'not_yet_due') {
        // The locked month itself hasn't finished on the calendar yet -- naming a
        // "prior month" makes no sense here, since payment isn't the issue. Mirrors
        // the backend's "opens on" date math (webapp/app.py, bulk_month_wages).
        const lockYearFrom = parseInt(lock.year_key.split('-')[0], 10);
        let calMonth, calYear;
        if (lock.month_idx <= 9) { calMonth = lock.month_idx + 3; calYear = lockYearFrom; }
        else { calMonth = lock.month_idx - 9; calYear = lockYearFrom + 1; }
        let opensMonth = calMonth + 1, opensYear = calYear;
        if (opensMonth > 12) { opensMonth = 1; opensYear += 1; }
        const opensStr = `01-${String(opensMonth).padStart(2, '0')}-${opensYear}`;
        App.toast(`${lock.month_abbr} ${lock.year_key} cannot be entered until that month has ended -- it opens on ${opensStr}.`, 'error');
        return;
      }
      // Name the actual PRIOR month that must be entered/paid (not the locked month
      // itself, which is self-contradictory -- "Apr must be entered before you can
      // enter Apr"). Mirrors the backend's bulk_month_wages 409 message construction
      // (webapp/app.py), including the Feb-of-previous-year wraparound (Finding 3).
      const lockYearFrom = parseInt(lock.year_key.split('-')[0], 10);
      const prevMonthIdx = lock.month_idx - 1;
      let prevAbbr, prevYearKey;
      if (prevMonthIdx >= 0) {
        prevAbbr = monthShortNames[prevMonthIdx];
        prevYearKey = lock.year_key;
      } else {
        prevAbbr = monthShortNames[11];
        const prevYearFrom = lockYearFrom - 1;
        prevYearKey = `${prevYearFrom}-${String(prevYearFrom + 1).slice(-2)}`;
      }
      App.toast(`${prevAbbr} ${prevYearKey} must be entered and its fee paid before you can enter ${monthShortNames[monthIdx]} ${currentYearKey}.`, 'error');
      return;
    }
  }

  syncBulkTableState();
```

Replace with:

```javascript
window.saveMonthlyWages = async () => {
  const monthIdx = parseInt(document.getElementById('bulk-month-select').value, 10);
  // Months are free-form now -- only the calendar ceiling can still block a save,
  // mirrored client-side from the same maxEnterable used to build the month dropdown
  // above. Superadmin bypasses it entirely, matching the backend.
  const maxEnterable = constantsCache.max_enterable_month;
  if (!App.isSuperadmin() && maxEnterable) {
    const maxYearFrom = parseInt(maxEnterable.year_key.split('-')[0], 10);
    const currentYearFrom = parseInt(currentYearKey.split('-')[0], 10);
    const isAfterCeiling = currentYearFrom > maxYearFrom || (currentYearFrom === maxYearFrom && monthIdx > maxEnterable.month_idx);
    if (isAfterCeiling) {
      const monthShortNames = constantsCache.month_short_names;
      let calMonth, calYear;
      if (monthIdx <= 9) { calMonth = monthIdx + 3; calYear = currentYearFrom; }
      else { calMonth = monthIdx - 9; calYear = currentYearFrom + 1; }
      let opensMonth = calMonth + 1, opensYear = calYear;
      if (opensMonth > 12) { opensMonth = 1; opensYear += 1; }
      const opensStr = `01-${String(opensMonth).padStart(2, '0')}-${opensYear}`;
      App.toast(`${monthShortNames[monthIdx]} ${currentYearKey} cannot be entered until that month has ended -- it opens on ${opensStr}.`, 'error');
      return;
    }
  }

  syncBulkTableState();
```

- [ ] **Step 3: Manually verify in the browser preview**

Using the same preview session as Task 8's Step 4, go to Monthly Wage Entry for an establishment/year with no wage data yet, and confirm:
- Every past/current-ended month in the dropdown is selectable (no 🔒 icons on months that would have been locked under the old chronological rule).
- A future month (if the selected year includes one relative to today) still shows 🔒 and is disabled.
- Saving a future month (if reachable, e.g. by manually enabling the option via devtools for the test) still shows the "cannot be entered until that month has ended" toast.
- As superadmin, every month is selectable including future ones.

- [ ] **Step 4: Commit**

```bash
git add webapp/js/wages.js
git commit -m "feat: make Monthly Wage Entry month selection free-form, calendar-ceiling only"
```

---

## Task 10: Final full-project verification and grep sweep

**Files:** none modified — verification only.

- [ ] **Step 1: Full backend test suite**

Run: `pytest webapp/tests/ -q`
Expected: all tests pass.

- [ ] **Step 2: Confirm no leftover references anywhere in the tree**

Run: `grep -rn "next_year_to_add\|next_open_month\|locked_month" webapp/ epf_engine.py` (or PowerShell: `Select-String -Path webapp\*.py,webapp\js\*.js,epf_engine.py -Pattern "next_year_to_add|next_open_month|locked_month" -Recurse`)
Expected: no matches anywhere in the tree.

- [ ] **Step 3: Update CLAUDE.md's "Month/year entry gating" mental model if present**

Check whether `CLAUDE.md` documents the old chronological gate anywhere (it currently does not — the repo's `CLAUDE.md` as of this plan has no dedicated section on it, only the general "Subscription-fee download gating" section, which this plan doesn't touch). If a future edit to `CLAUDE.md` ever adds a description of the old month/year gate, it should describe this new flexible-order behavior instead — no action needed right now since no such section exists yet.

- [ ] **Step 4: Push**

```bash
git push
```

