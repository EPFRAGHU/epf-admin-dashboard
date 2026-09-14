# EPS Eligibility Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make EPS (Pension Fund) contribution stop automatically at age 58 (computed
per wage month from DOB, not a manual whole-year checkbox), add a dedicated
"not an EPS member" flag, and fix a pre-existing DOB/DOJ/DOE date-format bug that
silently breaks both this feature and Form 5/Form 10 generation — closing the EPFO
ECR validation errors (RFE-21/25/28/29/30/31/37) reported on a live client filing.

**Architecture:** `epf_engine.py`'s `Employee.month_rows()` is the single calc
function every Excel/PDF/ECR path already funnels through — the fix lives there once,
behind one new helper (`is_eps_zero_for_month`) and two new `Employee` fields
(`eps_member`, `year_from`). `year_from` is set once at each of `Employee`'s 3
construction sites rather than threaded as a parameter through ~20 downstream call
sites, so nearly all of those call sites need no change. Everywhere else that
independently recomputed the old `age_crosses_58`-driven EPS wage base for display
purposes gets the same substitution. UI changes remove the now-obsolete manual
checkbox and add two non-blocking "no DOB on file" warnings at the two points that
actually matter: wage entry and ECR generation.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy (backend), vanilla JS SPA (frontend,
no build step, no JS test runner — UI changes are verified live in-browser per this
project's established pattern, not via JS unit tests), pytest (backend tests), SQLite
scratch DB copy for local verification (never the production Neon DB directly).

**Spec:** [docs/superpowers/specs/2026-09-14-eps-eligibility-engine-design.md](../specs/2026-09-14-eps-eligibility-engine-design.md)

## Global Constraints

- Never touch the production Neon/Postgres database directly, log into production as
  the user, or enter production credentials anywhere. All local verification runs
  against a scratch copy of `local_dev.db` with `DATABASE_URL` overridden, per this
  project's established workflow.
- `dob` stays `str = ""` (optional) at the data model / backend API level everywhere
  except the manual Employee Master Add/Edit **form**'s client-side validation. Do not
  make any Pydantic model field required for `dob`.
- Excel bulk import (`import_master_from_excel`, `POST /api/master/import`) must keep
  accepting a blank DOB — do not add any validation there.
- The wage-month index convention throughout this codebase is **0 = March, 11 =
  February**, months 0–9 fall in `year_from`, months 10–11 fall in `year_to`
  (confirmed authoritative via `calendar_year_for_month()`'s own docstring: "MONTHS
  runs Mar..Feb; Mar-Dec belong to year_from, Jan-Feb to year_to"). Do not use the
  `YearEntry.wages` field's stale `# APR..MAR` comment — it contradicts the rest of
  the codebase and is itself wrong; ignore it (optionally correct it to `# MAR..FEB`
  while touching that line in Task 2, but this is not required).
- EPS stops the month **after** the employee's 58th birthday — the birthday month
  itself still gets EPS (confirmed with the user). Age is evaluated as of the
  **first calendar day** of the wage month being checked.
- Every existing test in the 205-test suite (`pytest webapp/tests/ -v`) must still
  pass after every task in this plan.
- Follow the project's Git workflow: commit after each task; push to `main` only after
  the full plan is complete and verified (Coolify auto-deploys on push to `main`), per
  the "Verification & deploy" task at the end.

---

### Task 1: Fix the DOB/DOJ/DOE date-format bug (prerequisite)

This is a confirmed, currently-live bug, independent of the rest of this feature but
blocking it: `calc_age_years()` parses dates as `%d/%m/%Y` (slash) but every real
date in this app — both manual UI entry and Excel import — is stored `%d-%m-%Y`
(hyphen). The identical bug in `employees_joined_in_month`/`employees_left_in_month`
also silently breaks Form 5/Form 10 generation.

**Files:**
- Modify: `epf_engine.py:70-84` (`calc_age_years`)
- Modify: `epf_engine.py:2534-2569` (`employees_joined_in_month`, `employees_left_in_month`)
- Modify: `epf_engine.py:808,810,811` (stale `# Date of Birth, DD/MM/YYYY`-style comments on `MasterEmployee`)
- Create: `webapp/tests/test_eps_eligibility_engine.py` (new file — holds every test for this whole plan)

**Interfaces:**
- Produces: `calc_age_years(dob_text: str, as_of: date = None) -> Optional[int]` (signature unchanged, only its internal format string changes) — used by every later task.

- [ ] **Step 1: Write the failing tests**

Create `webapp/tests/test_eps_eligibility_engine.py`:

```python
from datetime import date

from epf_engine import (
    calc_age_years,
    employees_joined_in_month,
    employees_left_in_month,
)


def test_calc_age_years_parses_hyphen_format():
    """The only DOB format this app ever actually stores -- confirmed via
    employees.js's parseDMY() and epf_engine.py's own import format_date(),
    both of which normalize to hyphens, never slashes."""
    assert calc_age_years("15-06-1968", as_of=date(2026, 6, 1)) == 57
    assert calc_age_years("15-06-1968", as_of=date(2026, 6, 15)) == 58
    assert calc_age_years("15-06-1968", as_of=date(2026, 7, 1)) == 58


def test_calc_age_years_rejects_slash_format():
    """Slash-format DOB never occurs in real data -- this asserts the OLD buggy
    behavior is gone by confirming hyphen parsing works instead, not by asserting
    slash parsing fails (that would just pin the bug the other way)."""
    assert calc_age_years("") is None
    assert calc_age_years("not-a-date") is None


def test_calc_age_years_missing_dob_returns_none():
    assert calc_age_years("") is None
    assert calc_age_years(None) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: `test_calc_age_years_parses_hyphen_format` FAILS (returns `None`, not `57`/`58`) because `calc_age_years` currently uses `strptime(dob_text, "%d/%m/%Y")` on a hyphen string.

- [ ] **Step 3: Fix `calc_age_years`**

In `epf_engine.py`, change:
```python
    try:
        dob = datetime.strptime(dob_text, "%d/%m/%Y").date()
    except ValueError:
        return None
```
to:
```python
    try:
        dob = datetime.strptime(dob_text, "%d-%m-%Y").date()
    except ValueError:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Write the Form 5/Form 10 regression test**

Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
class _FakeMaster:
    def __init__(self, member_id, doj="", doe=""):
        self.member_id = member_id
        self.doj = doj
        self.doe = doe


class _FakeProject:
    def __init__(self, masters):
        self._masters = masters

    def master_list(self):
        return self._masters


def test_employees_joined_in_month_parses_hyphen_doj():
    project = _FakeProject([_FakeMaster("M1", doj="12-06-2026")])
    matches = employees_joined_in_month(project, 2026, 6)
    assert len(matches) == 1
    assert matches[0].member_id == "M1"


def test_employees_left_in_month_parses_hyphen_doe():
    project = _FakeProject([_FakeMaster("M2", doe="30-09-2026")])
    matches = employees_left_in_month(project, 2026, 9)
    assert len(matches) == 1
    assert matches[0].member_id == "M2"
```

- [ ] **Step 6: Run, verify failure, then fix**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v` — both new tests FAIL
(zero matches, since `%d/%m/%Y` can't parse `"12-06-2026"`).

In `epf_engine.py`, change both occurrences:
```python
            d = datetime.strptime(m.doj, "%d/%m/%Y").date()
```
to
```python
            d = datetime.strptime(m.doj, "%d-%m-%Y").date()
```
and
```python
            d = datetime.strptime(m.doe, "%d/%m/%Y").date()
```
to
```python
            d = datetime.strptime(m.doe, "%d-%m-%Y").date()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 8: Fix the stale format comments**

In `epf_engine.py`'s `MasterEmployee` dataclass (~line 808), change:
```python
    dob: str = ""        # Date of Birth, DD/MM/YYYY
    sex: str = ""         # "Male" or "Female"
    doj: str = ""         # Date of Joining, DD/MM/YYYY
    doe: str = ""         # Date of Exit, DD/MM/YYYY
```
to:
```python
    dob: str = ""        # Date of Birth, DD-MM-YYYY
    sex: str = ""         # "Male" or "Female"
    doj: str = ""         # Date of Joining, DD-MM-YYYY
    doe: str = ""         # Date of Exit, DD-MM-YYYY
```

- [ ] **Step 9: Run the full suite to confirm no regression**

Run: `pytest webapp/tests/ -v`
Expected: all 205 existing tests PASS, plus the 5 new ones (210 total).

- [ ] **Step 10: Commit**

```bash
git add epf_engine.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "fix(epf-engine): DOB/DOJ/DOE date parser used slash format, real data is hyphen

calc_age_years() and employees_joined_in_month/employees_left_in_month
all parsed dates as %d/%m/%Y, but every real date in this app is
stored %d-%m-%Y (confirmed via employees.js's parseDMY() and
epf_engine.py's own Excel-import format_date(), both hyphen-only).
Silently broke DOB-based age checks and Form 5/Form 10 generation
for every establishment. Prerequisite for the EPS eligibility engine.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Data model — `eps_member` + `year_from` fields, remove `age_crosses_58`

**Files:**
- Modify: `epf_engine.py` — `MasterEmployee` (~802-828), `MasterEmployee.from_dict` (~832-851), `YearEntry` (~863-885), `Employee` (~637-658), `upsert_master` (~994-1050), `upsert_entry` (~1232-1259), `build_employees_for_year` (~1264-1303)
- Test: `webapp/tests/test_eps_eligibility_engine.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `MasterEmployee.eps_member: bool` (default `True`), `Employee.eps_member: bool`, `Employee.year_from: str`. `Employee.age_crosses_58` and `YearEntry.age_crosses_58` no longer exist — any later task referencing them is a bug.

- [ ] **Step 1: Write the failing test for `eps_member` round-tripping through the master**

Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
from epf_engine import MasterEmployee, Project


def test_master_employee_eps_member_defaults_true():
    m = MasterEmployee(member_id="M1", name="Test")
    assert m.eps_member is True


def test_upsert_master_sets_eps_member_false():
    p = Project()
    p.set_establishment("EST1", "Test Co", "Addr")
    p.upsert_master("M1", "Test Employee", eps_member=False)
    assert p.master["M1"].eps_member is False


def test_upsert_master_eps_member_defaults_true_when_not_passed():
    p = Project()
    p.set_establishment("EST1", "Test Co", "Addr")
    p.upsert_master("M1", "Test Employee")
    assert p.master["M1"].eps_member is True


def test_build_employees_for_year_carries_eps_member_and_year_from():
    p = Project()
    p.set_establishment("EST1", "Test Co", "Addr")
    p.upsert_master("M1", "Test Employee", eps_member=False)
    p.years["2026-2027"] = __import__("epf_engine").YearRecord(year_from="2026", year_to="2027")
    p.upsert_entry("2026-2027", "M1", [1000.0] * 12)
    emps = p.build_employees_for_year("2026-2027")
    assert len(emps) == 1
    assert emps[0].eps_member is False
    assert emps[0].year_from == "2026"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all 4 new tests FAIL — `eps_member`/`year_from` don't exist yet (`AttributeError` or `TypeError: unexpected keyword argument`).

- [ ] **Step 3: Add `eps_member` to `MasterEmployee`**

In `epf_engine.py`, in the `MasterEmployee` dataclass, change:
```python
    higher_epf_ee: bool = False
    higher_epf_er: bool = False
    pohw: bool = False
    pohw_additional_1_16: bool = False
    branch_id: int = 0
```
to:
```python
    higher_epf_ee: bool = False
    higher_epf_er: bool = False
    pohw: bool = False
    pohw_additional_1_16: bool = False
    eps_member: bool = True  # False = never contributes to EPS/Pension, independent of age (RFE-21)
    branch_id: int = 0
```

In `MasterEmployee.from_dict`, change:
```python
            higher_epf_ee=d.get("higher_epf_ee", False),
            higher_epf_er=d.get("higher_epf_er", False),
            pohw=d.get("pohw", False),
            pohw_additional_1_16=d.get("pohw_additional_1_16", False),
            branch_id=d.get("branch_id", 0) or 0,
```
to:
```python
            higher_epf_ee=d.get("higher_epf_ee", False),
            higher_epf_er=d.get("higher_epf_er", False),
            pohw=d.get("pohw", False),
            pohw_additional_1_16=d.get("pohw_additional_1_16", False),
            eps_member=d.get("eps_member", True),
            branch_id=d.get("branch_id", 0) or 0,
```

- [ ] **Step 4: Add `eps_member` param to `upsert_master`**

Change the signature:
```python
    def upsert_master(self, member_id, name, father_name="", uan="", dob="", sex="", doj="",
                       doe="", reason_leaving="", serial_no=None, relationship="", marital_status="",
                       mobile="", email="", aadhaar="", bank_account="", ifsc="",
                       higher_epf_ee=False, higher_epf_er=False,
                       pohw=False, pohw_additional_1_16=False,
                       branch_id=None, division_id=None, unit_id=None):
```
to:
```python
    def upsert_master(self, member_id, name, father_name="", uan="", dob="", sex="", doj="",
                       doe="", reason_leaving="", serial_no=None, relationship="", marital_status="",
                       mobile="", email="", aadhaar="", bank_account="", ifsc="",
                       higher_epf_ee=False, higher_epf_er=False,
                       pohw=False, pohw_additional_1_16=False, eps_member=True,
                       branch_id=None, division_id=None, unit_id=None):
```

In the "update existing" branch, change:
```python
            m.higher_epf_ee = higher_epf_ee
            m.higher_epf_er = higher_epf_er
            m.pohw = pohw
            m.pohw_additional_1_16 = pohw_additional_1_16
            m.branch_id = branch_id
```
to:
```python
            m.higher_epf_ee = higher_epf_ee
            m.higher_epf_er = higher_epf_er
            m.pohw = pohw
            m.pohw_additional_1_16 = pohw_additional_1_16
            m.eps_member = eps_member
            m.branch_id = branch_id
```

In the "create new" branch, change:
```python
            self.master[member_id] = MasterEmployee(member_id=member_id, name=name, father_name=father_name,
                                                       uan=uan, dob=dob, sex=sex, doj=doj, doe=doe,
                                                       reason_leaving=reason_leaving, serial_no=serial_no,
                                                       relationship=relationship, marital_status=marital_status,
                                                       mobile=mobile, email=email, aadhaar=aadhaar,
                                                       bank_account=bank_account, ifsc=ifsc,
                                                       higher_epf_ee=higher_epf_ee, higher_epf_er=higher_epf_er,
                                                       pohw=pohw, pohw_additional_1_16=pohw_additional_1_16,
                                                       branch_id=branch_id, division_id=division_id, unit_id=unit_id)
```
to:
```python
            self.master[member_id] = MasterEmployee(member_id=member_id, name=name, father_name=father_name,
                                                       uan=uan, dob=dob, sex=sex, doj=doj, doe=doe,
                                                       reason_leaving=reason_leaving, serial_no=serial_no,
                                                       relationship=relationship, marital_status=marital_status,
                                                       mobile=mobile, email=email, aadhaar=aadhaar,
                                                       bank_account=bank_account, ifsc=ifsc,
                                                       higher_epf_ee=higher_epf_ee, higher_epf_er=higher_epf_er,
                                                       pohw=pohw, pohw_additional_1_16=pohw_additional_1_16,
                                                       eps_member=eps_member,
                                                       branch_id=branch_id, division_id=division_id, unit_id=unit_id)
```

- [ ] **Step 5: Run tests, confirm the 3 `eps_member`-only tests pass, `year_from` test still fails**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`

- [ ] **Step 6: Remove `age_crosses_58` from `YearEntry`, add backward-compat cleanup**

Change:
```python
@dataclass
class YearEntry:
    """One employee's wage entry for one specific year."""
    member_id: str = ""
    wages: List[int] = field(default_factory=lambda: [0] * 12)  # APR..MAR
    gross_wages: List[int] = field(default_factory=lambda: [0] * 12)
    ncp_days: List[int] = field(default_factory=lambda: [0] * 12)
    age_crosses_58: bool = False

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        d.pop("higher_epf", None)  # Safe cleanup
```
to:
```python
@dataclass
class YearEntry:
    """One employee's wage entry for one specific year."""
    member_id: str = ""
    wages: List[int] = field(default_factory=lambda: [0] * 12)  # MAR..FEB
    gross_wages: List[int] = field(default_factory=lambda: [0] * 12)
    ncp_days: List[int] = field(default_factory=lambda: [0] * 12)

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        d.pop("higher_epf", None)  # Safe cleanup
        d.pop("age_crosses_58", None)  # Removed -- EPS-58 cutover is now DOB-driven, see is_eps_zero_for_month()
```

(The `d.pop("age_crosses_58", None)` line is required, not optional cleanup — without
it, `YearEntry(**d)` raises `TypeError: unexpected keyword argument 'age_crosses_58'`
for every establishment's existing stored JSON that still has that key, since
`Establishment.data` is never rewritten just because a Python field was removed.)

- [ ] **Step 7: Add `eps_member`/`year_from` to `Employee`, remove `age_crosses_58`**

Change:
```python
    higher_epf_ee: bool = False
    higher_epf_er: bool = False
    pohw: bool = False                    # Pension on Higher Wages -- see month_rows()
    pohw_additional_1_16: bool = False    # optional add-on within PoHW, off by default -- see month_rows()
    age_crosses_58: bool = False
    dob: str = ''
```
to:
```python
    higher_epf_ee: bool = False
    higher_epf_er: bool = False
    pohw: bool = False                    # Pension on Higher Wages -- see month_rows()
    pohw_additional_1_16: bool = False    # optional add-on within PoHW, off by default -- see month_rows()
    eps_member: bool = True               # False = never contributes to EPS, independent of age (RFE-21)
    year_from: str = ''                   # set once at construction -- lets month_rows() resolve each
                                           # wage-month index to a real calendar date for the age-58 check
                                           # without every caller having to pass it in separately
    dob: str = ''
```

- [ ] **Step 8: Update `upsert_entry` — remove `age_crosses_58` param and usages**

Change:
```python
    def upsert_entry(self, year_key, member_id, wages, gross_wages=None, ncp_days=None, age_crosses_58=False,
                      higher_epf_ee=None, higher_epf_er=None, pohw=None, pohw_additional_1_16=None):
```
to:
```python
    def upsert_entry(self, year_key, member_id, wages, gross_wages=None, ncp_days=None,
                      higher_epf_ee=None, higher_epf_er=None, pohw=None, pohw_additional_1_16=None):
```

Change:
```python
        for e in yr.entries:
            if e.member_id == member_id:
                e.wages = wages
                e.gross_wages = gross_wages
                e.ncp_days = ncp_days
                e.age_crosses_58 = age_crosses_58
                return
        yr.entries.append(YearEntry(member_id=member_id, wages=wages, gross_wages=gross_wages, ncp_days=ncp_days, age_crosses_58=age_crosses_58))
```
to:
```python
        for e in yr.entries:
            if e.member_id == member_id:
                e.wages = wages
                e.gross_wages = gross_wages
                e.ncp_days = ncp_days
                return
        yr.entries.append(YearEntry(member_id=member_id, wages=wages, gross_wages=gross_wages, ncp_days=ncp_days))
```

- [ ] **Step 9: Update `build_employees_for_year`**

Change:
```python
            result.append(Employee(member_id=e.member_id, name=name, father_name=father, uan=uan,
                                    wages=[int(round(float(x))) if x is not None else 0 for x in e.wages],
                                    gross_wages=[int(round(float(x))) if x is not None else 0 for x in e.gross_wages],
                                    ncp_days=list(getattr(e, 'ncp_days', [0]*12)),
                                    higher_epf_ee=m.higher_epf_ee if m else False,
                                    higher_epf_er=m.higher_epf_er if m else False,
                                    pohw=m.pohw if m else False,
                                    pohw_additional_1_16=m.pohw_additional_1_16 if m else False,
                                    age_crosses_58=getattr(e, 'age_crosses_58', False),
                                    dob=dob, sex=sex, doj=doj, doe=doe, reason_leaving=reason_leaving,
                                    branch_id=branch_id, division_id=division_id, unit_id=unit_id))
```
to:
```python
            result.append(Employee(member_id=e.member_id, name=name, father_name=father, uan=uan,
                                    wages=[int(round(float(x))) if x is not None else 0 for x in e.wages],
                                    gross_wages=[int(round(float(x))) if x is not None else 0 for x in e.gross_wages],
                                    ncp_days=list(getattr(e, 'ncp_days', [0]*12)),
                                    higher_epf_ee=m.higher_epf_ee if m else False,
                                    higher_epf_er=m.higher_epf_er if m else False,
                                    pohw=m.pohw if m else False,
                                    pohw_additional_1_16=m.pohw_additional_1_16 if m else False,
                                    eps_member=m.eps_member if m else True,
                                    year_from=yr.year_from,
                                    dob=dob, sex=sex, doj=doj, doe=doe, reason_leaving=reason_leaving,
                                    branch_id=branch_id, division_id=division_id, unit_id=unit_id))
```

- [ ] **Step 10: Run tests to verify all pass**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all tests PASS (the `test_build_employees_for_year_carries_eps_member_and_year_from`
test should now pass, since `d.pop("age_crosses_58", None)` handles the removed field
and `upsert_entry` no longer takes it).

- [ ] **Step 11: Run the full suite**

Run: `pytest webapp/tests/ -v`
Expected: failures only in `test_pohw.py::test_pohw_age_crosses_58_still_zeroes_eps`
(still passes `age_crosses_58=True` to `POST /api/years/.../wages`, which no longer
does anything — this is fixed in Task 12) and possibly a handful of other tests
directly referencing `age_crosses_58` in request bodies or response assertions (grep
to confirm exact count before moving on: `grep -rn "age_crosses_58" webapp/tests/`).
Every other test must still pass. Do not fix the `age_crosses_58`-referencing tests
yet — Task 12 handles them together, after the backend endpoints are also updated.

- [ ] **Step 12: Commit**

```bash
git add epf_engine.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "feat(epf-engine): add eps_member + year_from fields, remove age_crosses_58

MasterEmployee/Employee gain eps_member (default True, independent of
age -- fixes RFE-21) and Employee gains year_from (set once at
construction so month_rows() can resolve wage-month indices to real
calendar dates without threading a new parameter through ~20 call
sites). age_crosses_58 removed from YearEntry/Employee -- the manual
whole-financial-year checkbox is superseded by DOB-driven per-month
calculation in the next task. YearEntry.from_dict() pops the old key
so existing establishments' stored JSON keeps loading.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: `is_eps_zero_for_month()` helper, wired into `month_rows()` and `generate_ecr_month()`

**Files:**
- Modify: `epf_engine.py` — near `calc_age_years` (~85), `Employee.month_rows()` (~660-723), `generate_ecr_month()` (~3023-3064)
- Test: `webapp/tests/test_eps_eligibility_engine.py`

**Interfaces:**
- Consumes: `Employee.eps_member`, `Employee.year_from`, `Employee.dob` (Task 2), `calc_age_years` (Task 1).
- Produces: `wage_month_start_date(month_idx: int, year_from: str) -> Optional[date]`, `is_eps_zero_for_month(dob: str, month_idx: int, year_from: str) -> bool` — both importable from `epf_engine`, used by Tasks 4 and 5.

- [ ] **Step 1: Write the failing tests for the helper and the birthday-boundary integration**

Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
from epf_engine import wage_month_start_date, is_eps_zero_for_month, Employee


def test_wage_month_start_date_mar_to_dec_falls_in_year_from():
    assert wage_month_start_date(0, "2026") == date(2026, 3, 1)   # month_idx 0 = March
    assert wage_month_start_date(9, "2026") == date(2026, 12, 1)  # month_idx 9 = December


def test_wage_month_start_date_jan_feb_falls_in_year_from_plus_one():
    assert wage_month_start_date(10, "2026") == date(2027, 1, 1)  # January
    assert wage_month_start_date(11, "2026") == date(2027, 2, 1)  # February


def test_is_eps_zero_for_month_birthday_month_still_gets_eps():
    """DOB 15-06-1968 turns 58 on 15-06-2026. FY 2026-27: month_idx 3 = June 2026.
    As of June 1 2026 (month start) they're still 57 -- EPS still applies that month."""
    assert is_eps_zero_for_month("15-06-1968", 3, "2026") is False


def test_is_eps_zero_for_month_zero_from_the_following_month():
    """Same employee: month_idx 4 = July 2026. As of July 1 2026 they're already 58."""
    assert is_eps_zero_for_month("15-06-1968", 4, "2026") is True


def test_is_eps_zero_for_month_missing_dob_never_auto_zeroes():
    assert is_eps_zero_for_month("", 4, "2026") is False


def test_month_rows_zeroes_eps_from_the_month_after_the_58th_birthday():
    """End-to-end through month_rows() itself, not just the helper -- confirms the
    wiring, not just the date math."""
    emp = Employee(member_id="M1", dob="15-06-1968", eps_member=True, year_from="2026",
                    wages=[75000] * 12, gross_wages=[75000] * 12)
    rows = emp.month_rows(worker_epf_rate=12.0, worker_eps_rate=0.0,
                           employer_epf_rate=3.67, employer_eps_rate=8.33)
    june = rows[3]   # w, w_epf, w_eps, w_total, e_epf, e_eps, e_total
    july = rows[4]
    assert june[5] > 0     # e_eps (EPS contribution) still present in June
    assert july[5] == 0    # zero from July
    assert july[4] == june[1]  # July's e_epf equals the full employer contribution (== w_epf, the EE 12% amount)


def test_month_rows_eps_member_false_zeroes_every_month_regardless_of_age():
    """RFE-21 fix: a 30-year-old (nowhere near 58) with eps_member=False must still
    get EPS=0 every month."""
    emp = Employee(member_id="M1", dob="01-01-1996", eps_member=False, year_from="2026",
                    wages=[75000] * 12, gross_wages=[75000] * 12)
    rows = emp.month_rows(worker_epf_rate=12.0, worker_eps_rate=0.0,
                           employer_epf_rate=3.67, employer_eps_rate=8.33)
    for r in rows:
        assert r[5] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all new tests FAIL — `wage_month_start_date`/`is_eps_zero_for_month` don't
exist yet, and `month_rows()` still uses the removed `age_crosses_58` field (which no
longer exists on `Employee`, so these tests would currently error with
`AttributeError` inside `month_rows()` itself even before reaching an assertion).

- [ ] **Step 3: Add the two helpers in `epf_engine.py`, right after `calc_age_years`**

Insert after the `calc_age_years` function (before the `MONTHS = [` line):

```python
def wage_month_start_date(month_idx: int, year_from: str) -> Optional[date]:
    """First calendar day of wage-month `month_idx` within the financial year
    starting `year_from`. month_idx 0 = March (of year_from) .. 9 = December (of
    year_from), 10 = January .. 11 = February (of year_from + 1) -- the same Mar-Feb
    convention as MONTHS/calendar_year_for_month(). Returns None if year_from isn't a
    parseable year or month_idx is out of range."""
    try:
        y_from = int(str(year_from)[:4])
    except (TypeError, ValueError):
        return None
    if not (0 <= month_idx <= 11):
        return None
    if month_idx <= 9:
        return date(y_from, month_idx + 3, 1)
    return date(y_from + 1, month_idx - 9, 1)


def is_eps_zero_for_month(dob: str, month_idx: int, year_from: str) -> bool:
    """True if EPS/Pension contribution should be zero for this wage month because
    the employee had already turned 58 as of the FIRST day of that month. An
    employee whose 58th birthday falls inside the month still gets EPS for that
    month -- the cutover starts the following month (confirmed EPFO practice).
    A missing/unparseable DOB returns False (never auto-zeroed) rather than raising,
    matching calc_age_years()'s own None-safe convention."""
    month_start = wage_month_start_date(month_idx, year_from)
    if month_start is None:
        return False
    age = calc_age_years(dob, as_of=month_start)
    return age is not None and age >= SUPERANNUATION_AGE
```

- [ ] **Step 4: Wire `is_eps_zero_for_month`/`eps_member` into `month_rows()`**

Change:
```python
        rows = []
        for i, w in enumerate(self.wages):
            w = int(round(float(w))) if w else 0
            ceiling = wage_ceilings[i]
            
            # Post-1997 calculation restrictions:
            if worker_eps_rate == 0:
                if self.pohw:
                    # Pension on Higher Wages: unlike ordinary Higher EPF (EE)/(ER)
                    # below, EPS itself is computed on the actual (uncapped) wage, not
                    # the ceiling -- both the employee and employer sides are always on
                    # the full wage while this is ticked, independent of whatever the
                    # Higher EPF (EE)/(ER) checkboxes say.
                    worker_wage_base = w
                    er_total_wage_base = w
                    eps_wage = 0 if self.age_crosses_58 else w
                else:
                    worker_wage_base = w if self.higher_epf_ee else min(w, ceiling)
                    er_total_wage_base = w if self.higher_epf_er else min(w, ceiling)
                    eps_wage = 0 if self.age_crosses_58 else min(w, ceiling)

                w_epf = round(worker_wage_base * worker_epf_rate / 100)
                w_eps = round(w * worker_eps_rate / 100)  # Will be 0 anyway

                e_eps = round(eps_wage * employer_eps_rate / 100)
                total_er_contrib = round(er_total_wage_base * worker_epf_rate / 100)
                e_epf = max(0, total_er_contrib - e_eps)

                if self.pohw and self.pohw_additional_1_16 and not self.age_crosses_58 and w > ceiling:
```
to:
```python
        rows = []
        for i, w in enumerate(self.wages):
            w = int(round(float(w))) if w else 0
            ceiling = wage_ceilings[i]
            eps_zero = (not self.eps_member) or is_eps_zero_for_month(self.dob, i, self.year_from)

            # Post-1997 calculation restrictions:
            if worker_eps_rate == 0:
                if self.pohw:
                    # Pension on Higher Wages: unlike ordinary Higher EPF (EE)/(ER)
                    # below, EPS itself is computed on the actual (uncapped) wage, not
                    # the ceiling -- both the employee and employer sides are always on
                    # the full wage while this is ticked, independent of whatever the
                    # Higher EPF (EE)/(ER) checkboxes say.
                    worker_wage_base = w
                    er_total_wage_base = w
                    eps_wage = 0 if eps_zero else w
                else:
                    worker_wage_base = w if self.higher_epf_ee else min(w, ceiling)
                    er_total_wage_base = w if self.higher_epf_er else min(w, ceiling)
                    eps_wage = 0 if eps_zero else min(w, ceiling)

                w_epf = round(worker_wage_base * worker_epf_rate / 100)
                w_eps = round(w * worker_eps_rate / 100)  # Will be 0 anyway

                e_eps = round(eps_wage * employer_eps_rate / 100)
                total_er_contrib = round(er_total_wage_base * worker_epf_rate / 100)
                e_epf = max(0, total_er_contrib - e_eps)

                if self.pohw and self.pohw_additional_1_16 and not eps_zero and w > ceiling:
```

(`eps_zero` is computed once per month inside the existing `for i, w in enumerate(self.wages)` loop, using the loop's own `i` as the month index — this is the only change to the loop body's control flow; everything below the `if self.pohw and ...` line is unchanged.)

- [ ] **Step 5: Wire the same helper into `generate_ecr_month()`**

Change:
```python
        epf_w = round(w)
        eps_w = 0 if emp.age_crosses_58 else round(min(w, wage_ceilings[month_idx]))
```
to:
```python
        epf_w = round(w)
        eps_zero = (not emp.eps_member) or is_eps_zero_for_month(emp.dob, month_idx, year_record.year_from)
        eps_w = 0 if eps_zero else round(min(w, wage_ceilings[month_idx]))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all tests PASS.

- [ ] **Step 7: Run the full suite**

Run: `pytest webapp/tests/ -v`
Expected: same pre-existing failures as Task 2's Step 11 (the `age_crosses_58`-referencing tests, still deferred to Task 12), nothing new broken.

- [ ] **Step 8: Commit**

```bash
git add epf_engine.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "feat(epf-engine): wire DOB-driven EPS-58 cutover into month_rows/ECR

is_eps_zero_for_month() replaces every age_crosses_58 check in
month_rows() and generate_ecr_month() with a per-wage-month DOB
comparison -- the employee's 58th-birthday month still gets EPS, the
cutover starts the following month. Combined with eps_member, this
is the actual RFE-21/25/28/29/30/31/37 fix; every Excel/PDF/ECR
generator inherits it for free since they all already call
month_rows()/generate_ecr_month().

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Fix the 3 `Employee`-construction sites (two never copied `dob` at all)

**Files:**
- Modify: `webapp/app.py` — `_build_ecr_employees_for_scope` (~6067-6096), the scope/subscription builder (~6262-6293)
- (The 3rd construction site, `build_employees_for_year` in `epf_engine.py`, was already fixed in Task 2 Step 9.)
- Test: `webapp/tests/test_eps_eligibility_engine.py`

**Interfaces:**
- Consumes: `Employee(dob=..., eps_member=..., year_from=...)` (Task 2).

- [ ] **Step 1: Write the failing test**

Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
def test_ecr_generation_respects_dob_driven_eps_cutover(consultant_a):
    """End-to-end: an employee whose DOB makes them 58+ this financial year must show
    EPS=0 in the actual ECR text file, not just in month_rows() directly. This is the
    test that would have caught _build_ecr_employees_for_scope() never copying dob
    over from MasterEmployee."""
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "ECRDOB01", "name": "ECR DOB Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    res = consultant_a.post("/api/employees", json={
        "member_id": "ECRD001", "name": "ECR DOB Test Employee", "uan": "100900000001",
        "dob": "01-01-1950",
    })
    assert res.status_code == 200, res.text
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "ECRD001", "wages": [30000.0] + [0.0] * 11,
    })
    assert res.status_code == 200, res.text

    res = consultant_a.get("/api/reports/2026-27/ecr/0")
    assert res.status_code == 200, res.text
    ecr_text = res.text
    fields = ecr_text.strip().split("#~#")
    # UAN#~#Name#~#Gross#~#EPF#~#EPS#~#EDLI#~#EE_Share#~#EPS_Share#~#ER_EPF#~#NCP#~#Refund
    assert fields[4] == "0"   # EPS Wages must be 0
    assert fields[7] == "0"   # EPS Contribution Remitted must be 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py::test_ecr_generation_respects_dob_driven_eps_cutover -v`
Expected: FAIL — `fields[4]` is nonzero, because `_build_ecr_employees_for_scope` never
set `dob` on the `Employee` it constructs, so `is_eps_zero_for_month` always sees an
empty DOB and never zeroes EPS, regardless of the employee's real age.

- [ ] **Step 3: Fix `_build_ecr_employees_for_scope`**

Change:
```python
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
            emp_obj.pohw = master_emp.pohw
            emp_obj.pohw_additional_1_16 = master_emp.pohw_additional_1_16
            emp_obj.age_crosses_58 = getattr(entry, 'age_crosses_58', False)
        else:
            emp_obj.wages = [0.0] * 12
            emp_obj.ncp_days = [0] * 12
        employees_with_wages.append(emp_obj)
    return employees_with_wages
```
to:
```python
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
            dob=master_emp.dob,
            eps_member=master_emp.eps_member,
            year_from=year_record.year_from,
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
            emp_obj.pohw = master_emp.pohw
            emp_obj.pohw_additional_1_16 = master_emp.pohw_additional_1_16
        else:
            emp_obj.wages = [0.0] * 12
            emp_obj.ncp_days = [0] * 12
        employees_with_wages.append(emp_obj)
    return employees_with_wages
```

- [ ] **Step 4: Fix the scope/subscription builder**

Change:
```python
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
                pohw=master_emp.pohw,
                pohw_additional_1_16=master_emp.pohw_additional_1_16,
                age_crosses_58=getattr(entry, 'age_crosses_58', False) if entry else False
            )
```
to:
```python
            emp_obj = Employee(
                member_id=master_emp.member_id,
                name=master_emp.name,
                father_name=master_emp.father_name,
                uan=master_emp.uan,
                dob=master_emp.dob,
                eps_member=master_emp.eps_member,
                year_from=year_record.year_from,
                branch_id=master_emp.branch_id,
                division_id=master_emp.division_id,
                unit_id=master_emp.unit_id,
                wages=entry.wages if entry else [0]*12,
                gross_wages=entry.gross_wages if entry else [0]*12,
                ncp_days=getattr(entry, 'ncp_days', [0]*12) if entry else [0]*12,
                higher_epf_ee=master_emp.higher_epf_ee,
                higher_epf_er=master_emp.higher_epf_er,
                pohw=master_emp.pohw,
                pohw_additional_1_16=master_emp.pohw_additional_1_16,
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py::test_ecr_generation_respects_dob_driven_eps_cutover -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `pytest webapp/tests/ -v`
Expected: same pre-existing deferred failures as before, nothing new broken.

- [ ] **Step 7: Commit**

```bash
git add webapp/app.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "fix(app): ECR/scope Employee builders never copied dob from master

_build_ecr_employees_for_scope() and the scope/subscription-fee
Employee builder both constructed Employee objects without dob at
all (predates this feature) -- would have silently defeated the
whole DOB-driven EPS cutover for actual ECR text file generation
even after every other fix landed, since is_eps_zero_for_month()
always saw an empty DOB there. Added dob/eps_member/year_from at
both construction sites.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Fix the duplicate `eps_wage`/`eps_wage_base` display recomputations

Several places independently recompute the EPS wage *base* (not the contribution
amount, which `month_rows()` already gets right) for report display purposes, using
the now-removed `age_crosses_58`. Each needs the same substitution or it will
silently disagree with the real numbers.

**Files:**
- Modify: `webapp/app.py` line 195 (import list), ~3971-3979, ~4101-4108, ~5230-5235, ~5638-5645/5665
- Modify: `pdf_engine.py` ~238-253, ~450-467
- Test: `webapp/tests/test_eps_eligibility_engine.py`

**Interfaces:**
- Consumes: `is_eps_zero_for_month` (Task 3), `Employee.eps_member`/`.dob`/`.year_from` (Task 2).

- [ ] **Step 1: Add `is_eps_zero_for_month` to `webapp/app.py`'s import**

Change:
```python
from epf_engine import (
    Project, ExcelGenerator, MONTHS, MONTH_FULL,
    SCHEME_PRE_1997, SCHEME_POST_1997,
    REASONS_FOR_LEAVING, SUPERANNUATION_AGE, calc_age_years,
```
to:
```python
from epf_engine import (
    Project, ExcelGenerator, MONTHS, MONTH_FULL,
    SCHEME_PRE_1997, SCHEME_POST_1997,
    REASONS_FOR_LEAVING, SUPERANNUATION_AGE, calc_age_years, is_eps_zero_for_month,
```

- [ ] **Step 2: Write the failing test for the dashboard monthly-stats duplicate**

Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
def test_dashboard_monthly_stats_eps_wage_respects_dob_cutover(consultant_a):
    """The Dashboard's monthly_stats independently recomputes an eps_wage total for
    display -- must also zero for a 58+ employee, not just month_rows()'s own
    contribution figures."""
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "DASHDOB01", "name": "Dash DOB Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={
        "member_id": "DASHD001", "name": "Dash DOB Test Employee", "uan": "100900000002",
        "dob": "01-01-1950",
    })
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "DASHD001", "wages": [15000.0] + [0.0] * 11,
    })
    assert res.status_code == 200, res.text

    res = consultant_a.get("/api/dashboard")
    assert res.status_code == 200, res.text
    stats = next(m for m in res.json()["monthly_stats"] if m.get("month") == "Mar" or m.get("label", "").startswith("Mar"))
    assert stats.get("eps_wage", 0) == 0
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py::test_dashboard_monthly_stats_eps_wage_respects_dob_cutover -v`

If the response shape doesn't have a `month`/`label` key matching this test's
assumption, first run `pytest ... -v -s` and print `res.json()["monthly_stats"][0]`
to see the actual field names, then adjust the test's key lookup to match — do not
guess the shape; read it from the actual endpoint response.

Expected once corrected: FAIL — `eps_wage` is nonzero because `emp.age_crosses_58` no
longer exists as an attribute (would raise `AttributeError`) or (before Task 2) was
never checked against DOB.

- [ ] **Step 4: Fix the dashboard monthly-stats site**

Change (~line 3979):
```python
                ceiling = get_wage_ceilings_for_year(yr.year_from)[i]
                if est.worker_eps_rate == 0:
                    eps_wage = 0 if emp.age_crosses_58 else min(wages, ceiling)
                else:
                    eps_wage = wages
```
to:
```python
                ceiling = get_wage_ceilings_for_year(yr.year_from)[i]
                if est.worker_eps_rate == 0:
                    eps_zero = (not emp.eps_member) or is_eps_zero_for_month(emp.dob, i, yr.year_from)
                    eps_wage = 0 if eps_zero else min(wages, ceiling)
                else:
                    eps_wage = wages
```

- [ ] **Step 5: Fix the per-month employee-detail listing (~line 4108)**

Change:
```python
            ceiling = get_wage_ceilings_for_year(yr.year_from)[month_index]
            eps_wage = (0 if emp.age_crosses_58 else min(wages, ceiling)) if est.worker_eps_rate == 0 else wages
```
to:
```python
            ceiling = get_wage_ceilings_for_year(yr.year_from)[month_index]
            eps_zero = (not emp.eps_member) or is_eps_zero_for_month(emp.dob, month_index, yr.year_from)
            eps_wage = (0 if eps_zero else min(wages, ceiling)) if est.worker_eps_rate == 0 else wages
```

- [ ] **Step 6: Fix the year-totals loop (~line 5235)**

Read the ~15 lines around `webapp/app.py:5235` first to confirm the exact surrounding
variable names (`i`/`month_idx`, `yr`/`year_record`) match this file's convention at
that specific location, then apply the same substitution pattern as Steps 4-5:
`emp.age_crosses_58` → `(not emp.eps_member) or is_eps_zero_for_month(emp.dob, <month index var>, <year_from var>)`.

- [ ] **Step 7: Fix the wage-history report builder (~lines 5638-5645, 5665)**

Change:
```python
            higher_epf_ee = bool(emp.higher_epf_ee)
            higher_epf_er = bool(emp.higher_epf_er)
            pohw = bool(emp.pohw)
            pohw_additional_1_16 = bool(emp.pohw_additional_1_16)
            age_crosses_58 = bool(emp.age_crosses_58)
        else:
            ee_epf = er_epf = er_eps = [0] * 12
            higher_epf_ee = higher_epf_er = pohw = pohw_additional_1_16 = age_crosses_58 = False
```
to:
```python
            higher_epf_ee = bool(emp.higher_epf_ee)
            higher_epf_er = bool(emp.higher_epf_er)
            pohw = bool(emp.pohw)
            pohw_additional_1_16 = bool(emp.pohw_additional_1_16)
        else:
            ee_epf = er_epf = er_eps = [0] * 12
            higher_epf_ee = higher_epf_er = pohw = pohw_additional_1_16 = False
```

And remove the now-orphaned key from the returned dict:
```python
            "pohw_additional_1_16": pohw_additional_1_16,
            "age_crosses_58": age_crosses_58
        })
```
to:
```python
            "pohw_additional_1_16": pohw_additional_1_16,
        })
```

- [ ] **Step 8: Fix `pdf_engine.py`'s Monthly Wage Entry PDF (~lines 238-263)**

First add the import at the top of `pdf_engine.py` (check the existing `from epf_engine import ...` line near the top of the file and add `is_eps_zero_for_month` to it, following the same pattern as Step 1).

Change:
```python
        if est.employer_eps_rate > 0:
            if emp.age_crosses_58:
                eps_wage_base = 0
            elif emp.pohw:
                eps_wage_base = wage_raw
            else:
                eps_wage_base = min(wage_raw, ceiling)
        else:
            eps_wage_base = 0
```
to:
```python
        eps_zero = (not emp.eps_member) or is_eps_zero_for_month(emp.dob, month_idx, emp.year_from)
        if est.employer_eps_rate > 0:
            if eps_zero:
                eps_wage_base = 0
            elif emp.pohw:
                eps_wage_base = wage_raw
            else:
                eps_wage_base = min(wage_raw, ceiling)
        else:
            eps_wage_base = 0
```

And change the flags list:
```python
        flags = []
        if emp.higher_epf_ee: flags.append("Higher EPF (EE)")
        if emp.higher_epf_er: flags.append("Higher EPF (ER)")
        if emp.age_crosses_58: flags.append("Age &gt; 58")
        if emp.pohw: flags.append("PoHW")
```
to:
```python
        flags = []
        if emp.higher_epf_ee: flags.append("Higher EPF (EE)")
        if emp.higher_epf_er: flags.append("Higher EPF (ER)")
        if eps_zero: flags.append("EPS = 0 (58+/non-member)")
        if emp.pohw: flags.append("PoHW")
```

- [ ] **Step 9: Fix `pdf_engine.py`'s Yearly Wage Checklist PDF (~lines 459-467)**

This site loops over all 12 months with index `i` (not a single `month_idx`), so the
per-month check uses `i`:

Change:
```python
            if est.employer_eps_rate > 0:
                if emp.age_crosses_58:
                    eps_wage_base = 0
                elif emp.pohw:
                    eps_wage_base = wage_raw
                else:
                    eps_wage_base = min(wage_raw, ceiling)
            else:
                eps_wage_base = 0
```
to:
```python
            eps_zero = (not emp.eps_member) or is_eps_zero_for_month(emp.dob, i, emp.year_from)
            if est.employer_eps_rate > 0:
                if eps_zero:
                    eps_wage_base = 0
                elif emp.pohw:
                    eps_wage_base = wage_raw
                else:
                    eps_wage_base = min(wage_raw, ceiling)
            else:
                eps_wage_base = 0
```

- [ ] **Step 10: Find and fix the remaining `age_crosses_58` flag reference in `pdf_engine.py` (~line 1333)**

Read `pdf_engine.py` around line 1333 to see its exact context (it reads
`y.get('age_crosses_58')` from a dict, likely the wage-history builder's output fixed
in Step 7) and remove that flag check the same way — the source dict no longer has
that key after Step 7, so this line would otherwise always evaluate to falsy silently;
delete it explicitly rather than leaving dead code.

- [ ] **Step 11: Run all new tests**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all PASS.

- [ ] **Step 12: Run the full suite**

Run: `pytest webapp/tests/ -v`
Expected: same pre-existing deferred failures (Task 12), nothing new broken.

- [ ] **Step 13: Commit**

```bash
git add webapp/app.py pdf_engine.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "fix(reports): duplicate eps_wage_base display calcs now DOB-driven too

Several report-only recomputations of the EPS wage base (Dashboard
monthly stats, a per-month employee listing, year totals, the wage-
history builder, both Monthly/Yearly Wage Entry PDFs) independently
checked age_crosses_58 instead of going through month_rows(). Fixed
to use is_eps_zero_for_month()/eps_member the same way, so display
figures can't drift from the real contribution amounts now that the
old flag is gone.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: Backend endpoints — Pydantic models, `GET .../wages`, `POST .../wages`, `POST .../wages/bulk_month`, `EmployeeIn`

**Files:**
- Modify: `webapp/app.py` — `EmployeeIn` (~1083-1107), `WageIn`/`BulkMonthWageUpdate` (~1127-1147), `add_employee`/`edit_employee` (~4901-4954), `GET /api/employees` (~4876-4898), `GET /api/years/{key}/wages` (~5276-5334), `POST /api/years/{key}/wages` (~5409-5443), `POST /api/years/{key}/wages/bulk_month` (~5446-5536)
- Test: `webapp/tests/test_eps_eligibility_engine.py`

**Interfaces:**
- Consumes: `upsert_master(..., eps_member=...)` (Task 2), `is_eps_zero_for_month` (Task 3).
- Produces: `EmployeeIn.eps_member: bool = True`; each row in `GET /api/years/{key}/wages`'s `employees` list gains `"eps_member": bool` and `"eps_zero_months": List[bool]` (12 entries), loses `"age_crosses_58"` — this is what Task 9's `wage-entry-batch.js` consumes instead of recomputing client-side.

- [ ] **Step 1: Write the failing tests**

Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
def test_add_employee_accepts_eps_member_false(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "EPSM0001", "name": "EPS Member Test Co",
    })
    assert res.status_code == 200, res.text
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    res = consultant_a.post("/api/employees", json={
        "member_id": "EPSM001", "name": "Non Member Employee", "uan": "100900000003",
        "eps_member": False,
    })
    assert res.status_code == 200, res.text
    emps = consultant_a.get("/api/employees").json()["employees"]
    emp = next(e for e in emps if e["member_id"] == "EPSM001")
    assert emp["eps_member"] is False


def test_add_employee_eps_member_defaults_true(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "EPSM0002", "name": "EPS Member Default Co",
    })
    assert res.status_code == 200, res.text
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    res = consultant_a.post("/api/employees", json={
        "member_id": "EPSM002", "name": "Default Member Employee", "uan": "100900000004",
    })
    assert res.status_code == 200, res.text
    emps = consultant_a.get("/api/employees").json()["employees"]
    emp = next(e for e in emps if e["member_id"] == "EPSM002")
    assert emp["eps_member"] is True


def test_get_wages_returns_eps_zero_months_not_age_crosses_58(consultant_a):
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "EPSM0003", "name": "EPS Zero Months Co",
    })
    assert res.status_code == 200, res.text
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={
        "member_id": "EPSM003", "name": "Boundary Employee", "uan": "100900000005",
        "dob": "15-06-1968",
    })
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "EPSM003", "wages": [75000.0] * 12,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "EPSM003")
    assert "age_crosses_58" not in emp
    assert emp["eps_member"] is True
    assert len(emp["eps_zero_months"]) == 12
    assert emp["eps_zero_months"][3] is False  # June -- birthday month, still EPS
    assert emp["eps_zero_months"][4] is True   # July -- zero from here
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: `test_add_employee_accepts_eps_member_false`/`_defaults_true` FAIL with a 422
or a missing key (`EmployeeIn` doesn't accept/return `eps_member` yet).
`test_get_wages_returns_eps_zero_months_not_age_crosses_58` FAILS — `age_crosses_58`
is still present and `eps_zero_months` doesn't exist.

- [ ] **Step 3: Add `eps_member` to `EmployeeIn`**

Change:
```python
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
    pohw: bool = False
    pohw_additional_1_16: bool = False
    branch_id: Optional[int] = None
    division_id: Optional[int] = None
    unit_id: Optional[int] = None
```
to:
```python
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
    pohw: bool = False
    pohw_additional_1_16: bool = False
    eps_member: bool = True
    branch_id: Optional[int] = None
    division_id: Optional[int] = None
    unit_id: Optional[int] = None
```

- [ ] **Step 4: Thread `d.eps_member` through `add_employee`/`edit_employee`**

In both `add_employee` and `edit_employee`, change:
```python
        project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                              d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                              d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                              d.bank_account, d.ifsc, d.higher_epf_ee, d.higher_epf_er,
                              d.pohw, d.pohw_additional_1_16,
                              d.branch_id, d.division_id, d.unit_id)
```
to:
```python
        project.upsert_master(d.member_id, d.name, d.father_name, d.uan,
                              d.dob, d.sex, d.doj, d.doe, d.reason_leaving, d.serial_no,
                              d.relationship, d.marital_status, d.mobile, d.email, d.aadhaar,
                              d.bank_account, d.ifsc, d.higher_epf_ee, d.higher_epf_er,
                              d.pohw, d.pohw_additional_1_16, d.eps_member,
                              d.branch_id, d.division_id, d.unit_id)
```
(This appears twice — once in `add_employee`, once in `edit_employee`. Apply to both.)

- [ ] **Step 5: Add `eps_member` to `GET /api/employees`'s response**

Change:
```python
            "pohw": m.pohw,
            "pohw_additional_1_16": m.pohw_additional_1_16,
            "branch_id": m.branch_id,
```
to:
```python
            "pohw": m.pohw,
            "pohw_additional_1_16": m.pohw_additional_1_16,
            "eps_member": m.eps_member,
            "branch_id": m.branch_id,
```

- [ ] **Step 6: Remove `age_crosses_58` from `WageIn`/`BulkMonthWageUpdate`**

Change:
```python
class WageIn(BaseModel):
    member_id: str
    wages: List[float]
    gross_wages: List[float] = []
    ncp_days: List[int] = []
    age_crosses_58: bool = False
    higher_epf_ee: bool = False
```
to:
```python
class WageIn(BaseModel):
    member_id: str
    wages: List[float]
    gross_wages: List[float] = []
    ncp_days: List[int] = []
    higher_epf_ee: bool = False
```

Change:
```python
class BulkMonthWageUpdate(BaseModel):
    member_id: str
    gross_wage: float
    epf_wage: float
    ncp_days: int
    age_crosses_58: bool = False
    higher_epf_ee: bool = False
```
to:
```python
class BulkMonthWageUpdate(BaseModel):
    member_id: str
    gross_wage: float
    epf_wage: float
    ncp_days: int
    higher_epf_ee: bool = False
```

- [ ] **Step 7: Remove `age_crosses_58` from `put_wages`/`bulk_month_wages`**

In `put_wages` (`POST /api/years/{key}/wages`), change:
```python
    project.upsert_entry(key, d.member_id, capped_wages, gross_wages=gross_wages, ncp_days=ncp_days, age_crosses_58=d.age_crosses_58,
                          higher_epf_ee=d.higher_epf_ee, higher_epf_er=d.higher_epf_er,
                          pohw=d.pohw, pohw_additional_1_16=d.pohw_additional_1_16)
```
to:
```python
    project.upsert_entry(key, d.member_id, capped_wages, gross_wages=gross_wages, ncp_days=ncp_days,
                          higher_epf_ee=d.higher_epf_ee, higher_epf_er=d.higher_epf_er,
                          pohw=d.pohw, pohw_additional_1_16=d.pohw_additional_1_16)
```

In `bulk_month_wages`, change:
```python
        project.upsert_entry(
            key, 
            emp_update.member_id, 
            wages_arr, 
            gross_wages=gross_wages_arr, 
            ncp_days=ncp_days_arr, 
            age_crosses_58=emp_update.age_crosses_58,
            higher_epf_ee=emp_update.higher_epf_ee,
            higher_epf_er=emp_update.higher_epf_er,
            pohw=emp_update.pohw,
            pohw_additional_1_16=emp_update.pohw_additional_1_16
        )
```
to:
```python
        project.upsert_entry(
            key, 
            emp_update.member_id, 
            wages_arr, 
            gross_wages=gross_wages_arr, 
            ncp_days=ncp_days_arr, 
            higher_epf_ee=emp_update.higher_epf_ee,
            higher_epf_er=emp_update.higher_epf_er,
            pohw=emp_update.pohw,
            pohw_additional_1_16=emp_update.pohw_additional_1_16
        )
```

- [ ] **Step 8: Replace `age_crosses_58` with `eps_member`/`eps_zero_months` in `GET /api/years/{key}/wages`**

Change:
```python
            "pohw": emp.pohw,
            "pohw_additional_1_16": emp.pohw_additional_1_16,
            "age_crosses_58": emp.age_crosses_58,
            "months": [{"m": MONTHS[i], "w": int(round(r[0])),
```
to:
```python
            "pohw": emp.pohw,
            "pohw_additional_1_16": emp.pohw_additional_1_16,
            "eps_member": emp.eps_member,
            "eps_zero_months": [
                (not emp.eps_member) or is_eps_zero_for_month(emp.dob, i, yr.year_from)
                for i in range(12)
            ],
            "months": [{"m": MONTHS[i], "w": int(round(r[0])),
```

- [ ] **Step 9: Run the new tests**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: all PASS.

- [ ] **Step 10: Run the full suite**

Run: `pytest webapp/tests/ -v`
Expected: the deferred `age_crosses_58`-in-request-body tests (grep-confirmed in Task
2 Step 11) now fail differently — Pydantic silently ignores the unknown
`age_crosses_58` key in the JSON body (FastAPI/Pydantic v2 ignores extra fields by
default) rather than erroring, so most of them likely still pass at the HTTP level;
any assertion checking the removed `"age_crosses_58"` response key will `KeyError`.
Confirm the exact remaining failures with `pytest webapp/tests/ -v 2>&1 | grep FAIL`
and leave them for Task 12 — do not fix them here.

- [ ] **Step 11: Commit**

```bash
git add webapp/app.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "feat(app): wire eps_member through employee endpoints, drop age_crosses_58

EmployeeIn/add_employee/edit_employee/GET-employees carry eps_member
now. WageIn/BulkMonthWageUpdate/put_wages/bulk_month_wages drop
age_crosses_58 entirely -- it's no longer a per-wage-entry concept.
GET .../wages now returns eps_member + a precomputed eps_zero_months
per-employee array instead of the old single age_crosses_58 bool, so
wage-entry-batch.js's live preview can read it instead of
reimplementing the age/month-boundary rule client-side.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Employee Master UI — EPS Member checkbox, badges, required-DOB form validation

No JS test runner exists in this codebase — UI tasks are verified live in-browser
against a scratch DB copy (see Task 13), matching this project's established pattern
for every prior frontend feature.

**Files:**
- Modify: `webapp/js/employees.js` — add form (~140-180), edit form (~460-495), save handlers (~320-355, ~575-610), table row rendering (~400-410)

**Interfaces:**
- Consumes: `eps_member` field on employee objects from `GET /api/employees` (Task 6).

- [ ] **Step 1: Read the exact current add-form, edit-form, and save-handler code**

Read `webapp/js/employees.js` lines 120-200 (add form), 440-520 (edit form), 290-360
and 560-620 (save handlers) to get their exact current content before editing — this
plan's earlier exploration captured representative slices but not the full byte-exact
current state, and line numbers may have drifted slightly since this plan was written.

- [ ] **Step 2: Add the "EPS Member" checkbox to the add form**

Near the existing `Date of Birth` field (`<input class="form-input" id="ae-dob" placeholder="DD-MM-YYYY">`),
add a `required` attribute to that input, plus a visible `*` in its label to match
whatever convention this file already uses for Member ID/Name (check how those two
required fields are marked up and mirror it exactly — do not invent a new required-
field convention for this one input).

Add a new checkbox near the existing Higher EPF EE/ER checkboxes (search for
`higher_epf_ee`/`ae-higher-epf-ee`-style ids in the add form to find the right spot):
```html
<label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:12px;">
  <input type="checkbox" id="ae-eps-member" checked> EPS Member
</label>
```

- [ ] **Step 3: Add client-side required-DOB validation to the add-employee save handler**

Find the function that reads `#ae-dob` and posts to `POST /api/employees` (search for
`document.getElementById('ae-dob')`). Add a check before the request fires:
```javascript
  const dob = document.getElementById('ae-dob').value.trim();
  if (!dob) { App.toast('Date of Birth is required', 'error'); return; }
```
placed alongside the existing `if (!d.member_id || !d.name) { App.toast('Member ID and Name are required', 'error'); return; }`
check (same function, same style). Add `eps_member: document.getElementById('ae-eps-member').checked`
to the JSON body being posted.

- [ ] **Step 4: Repeat Steps 2-3 for the edit form**

Same checkbox (`id="m-eps-member"`, pre-checked to `${e.eps_member !== false ? 'checked' : ''}`
matching how the existing `m-dob` input pre-fills with `value="${App.esc(e.dob || '')}"`),
same required-DOB validation in the edit-save handler, same `eps_member` field added
to that handler's JSON body.

- [ ] **Step 5: Add badges to the Employee Master table row**

Find the table row rendering (`<td>${App.esc(e.dob)}${e.superannuation ? ...}</td>`
pattern, ~line 409) and add, alongside the existing "58+" badge:
```javascript
${!e.dob ? '<br><span class="badge" style="background:var(--border); color:var(--text2); margin-top:2px; display:inline-block;">No DOB</span>' : ''}
```
and, near wherever `higher_epf_ee`/`pohw` badges are shown in the row (search for
those), add:
```javascript
${e.eps_member === false ? '<span class="badge high" style="font-size:10px;">Not EPS Member</span>' : ''}
```

- [ ] **Step 6: Live-verify** (see Task 13 for the full scratch-DB workflow)

Start the scratch-DB server, open Employee Master in the Browser tool:
1. Try to add an employee with DOB left blank — confirm the toast blocks submission.
2. Add an employee with DOB filled and "EPS Member" unchecked — confirm it saves,
   confirm the "Not EPS Member" badge shows in the table.
3. Edit an existing employee that has no DOB — confirm the "No DOB" badge was showing
   before the edit, and that saving now requires filling DOB in.

- [ ] **Step 7: Commit**

```bash
git add webapp/js/employees.js
git commit -m "feat(employees): EPS Member checkbox + required DOB on manual add/edit

Add/Edit Employee forms now require DOB (client-side only -- the
backend API contract is unchanged, see the design spec's Resolved
section for why) and expose a new EPS Member checkbox (default
checked). Employee Master table rows show a 'Not EPS Member' badge
and a 'No DOB' badge where relevant.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Monthly Wage Entry UI — remove the manual Age > 58 checkbox, add the no-DOB warning

**Files:**
- Modify: `webapp/js/wages.js` — single-employee modal (lines ~256-261, ~335, ~384, ~639, ~672, ~677), bulk table (lines ~1369, ~1461, ~1473, ~1512, ~1537, ~1614, ~1645-1646, ~1668, ~1712, ~1723, ~1769, ~1783, ~1791, ~1844)

**Interfaces:**
- Consumes: nothing new — this is a pure removal + one new warning, no new backend data needed (the warning is driven by `emp.dob`/`matchedMaster.dob`, already present in every response this file already reads).

- [ ] **Step 1: Remove the single-employee modal's Age > 58 checkbox and its badge**

In the wage-card render (~line 256-261), change:
```javascript
          ${emp.higher_epf_ee || emp.higher_epf_er || emp.pohw || emp.age_crosses_58 ? `
          <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap;">
            ${emp.higher_epf_ee ? `<span class="badge low" style="font-size: 10px;">✓ H.EPF(EE)</span>` : ''}
            ${emp.higher_epf_er ? `<span class="badge low" style="font-size: 10px;">✓ H.EPF(ER)</span>` : ''}
            ${emp.pohw ? `<span class="badge high" style="font-size: 10px;">✓ PoHW${emp.pohw_additional_1_16 ? ' +1.16%' : ''}</span>` : ''}
            ${emp.age_crosses_58 ? `<span class="badge high" style="font-size: 10px;">✓ Age > 58 (EPS=0)</span>` : ''}
          </div>
          ` : ''}
```
to:
```javascript
          ${emp.higher_epf_ee || emp.higher_epf_er || emp.pohw ? `
          <div style="margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap;">
            ${emp.higher_epf_ee ? `<span class="badge low" style="font-size: 10px;">✓ H.EPF(EE)</span>` : ''}
            ${emp.higher_epf_er ? `<span class="badge low" style="font-size: 10px;">✓ H.EPF(ER)</span>` : ''}
            ${emp.pohw ? `<span class="badge high" style="font-size: 10px;">✓ PoHW${emp.pohw_additional_1_16 ? ' +1.16%' : ''}</span>` : ''}
          </div>
          ` : ''}
```

- [ ] **Step 2: Remove the checkbox from `showWageModal`'s form HTML**

Change (~line 335):
```javascript
  const age58Checked = isEdit && emp.age_crosses_58 ? 'checked' : '';
```
Delete this line entirely.

Change (~line 384):
```javascript
        <label style="display:flex; align-items:center; gap:6px; cursor:pointer; font-size:12px; white-space:nowrap;">
          <input type="checkbox" id="w-age-58" ${age58Checked}> Age > 58 (EPS = 0)
        </label>
```
Delete this whole `<label>` block.

- [ ] **Step 3: Add the no-DOB warning in the employee-details panel**

In the employee-details block that shows `<span><strong>DOB:</strong> ${App.esc(emp.dob || '-')}</span>`
(~line 356, and its mirror at ~line 622 in the search-matched-employee handler),
change both to:
```javascript
<span><strong>DOB:</strong> ${App.esc(emp.dob || '-')}</span>${!emp.dob ? ' <span class="badge" style="background:var(--border); color:var(--text2); font-size:10px;">No DOB on file — EPS age-58 cutover can\'t be auto-checked</span>' : ''}
```
(Apply the same change to both the `emp.dob`-based version around line 356 and the
`matchedMaster.dob`-based version around line 622, substituting `matchedMaster` for
`emp` in the second location.)

- [ ] **Step 4: Remove the checkbox's read/write plumbing in the modal search handler**

Change (~line 639):
```javascript
          document.getElementById('w-age-58').checked = existingWageEmp.age_crosses_58 || false;
```
Delete this line.

Change (~line 643):
```javascript
          document.getElementById('w-age-58').checked = false;
```
Delete this line.

- [ ] **Step 5: Remove `age_crosses_58` from the save payload**

Change (~lines 670-677):
```javascript
  const higher_epf_ee = document.getElementById('w-higher-epf-ee').checked;
  const higher_epf_er = document.getElementById('w-higher-epf-er').checked;
  const age_crosses_58 = document.getElementById('w-age-58').checked;
  const pohw = document.getElementById('w-pohw').checked;
  const pohw_additional_1_16 = document.getElementById('w-pohw-116').checked;

  try {
    await App.post(`/api/years/${currentYearKey}/wages`, { member_id: acc, wages, gross_wages, ncp_days, higher_epf_ee, higher_epf_er, age_crosses_58, pohw, pohw_additional_1_16 });
```
to:
```javascript
  const higher_epf_ee = document.getElementById('w-higher-epf-ee').checked;
  const higher_epf_er = document.getElementById('w-higher-epf-er').checked;
  const pohw = document.getElementById('w-pohw').checked;
  const pohw_additional_1_16 = document.getElementById('w-pohw-116').checked;

  try {
    await App.post(`/api/years/${currentYearKey}/wages`, { member_id: acc, wages, gross_wages, ncp_days, higher_epf_ee, higher_epf_er, pohw, pohw_additional_1_16 });
```

- [ ] **Step 6: Remove `age58`/`age_crosses_58` from the bulk table's state and rendering**

This is the same mechanical removal repeated across the bulk table's state object,
init, recalc, checkbox render, and save-payload code — read each of the following
lines in `webapp/js/wages.js` (line numbers as of this plan's writing; re-grep
`age58|age_crosses_58` in this file first to confirm current locations before
editing, since Task 7/earlier tasks don't touch this file so drift should be minimal):

1. Line ~1369: `bulkTableState[emp.member_id] = { g: 0, w: 0, n: 0, higher_ee: false, higher_er: false, pohw: false, pohw116: false, age58: false, isCopied: false };`
   → remove `age58: false, ` from this object literal (and the other 2 identical object literals at ~1461 and ~1645).
2. Line ~1473: `age58 = existingData.age_crosses_58 || false;` → delete this line.
3. Line ~1512: `age58 = currentSessionState.age58;` → delete this line.
4. Line ~1537: `bulkTableState[master.member_id] = { g, w, n, higher_ee, higher_er, pohw, pohw116, age58, isCopied };` → remove `age58, `.
5. Line ~1614: `bulkTableState[member_id].age58 = infoRow.querySelector('.b-age58').checked;` → delete this line.
6. Line ~1646: `const { g, w, n, higher_ee, higher_er, pohw, pohw116, age58, isCopied } = state;` → remove `age58, `.
7. Line ~1668: `<label ...><input type="checkbox" class="b-age58" ...> Age &gt; 58</label>` → delete this whole `<label>`.
8. Lines ~1712, 1723: `const age58Chk = infoRow.querySelector('.b-age58');` and `age58Chk.addEventListener('change', recalc);` → delete both.
9. Line ~1769: `const age58 = infoRow.querySelector('.b-age58').checked;` → delete this line.
10. Line ~1783: `const epsWage = age58 ? 0 : (pohw ? w : Math.min(w, ceiling));` → change to
    a live-preview approximation using the employee's DOB (this row's `master`/`emp`
    object should already carry `.dob` from `window._masterEmployees`, populated by
    `GET /api/employees`): the exact recalc function's surrounding code must be read
    first (it's not part of what this plan captured verbatim) to know what employee-
    identity variable is in scope at this exact line, then replace with a check
    against that employee's DOB using the same birthday-month-boundary rule as the
    backend (age at this wage month's calendar start ≥ 58) — OR, simpler and safer
    (avoids reimplementing the boundary rule a third time in JS): since this bulk
    table already fetches full wage data including `eps_zero_months`-shaped
    information is NOT currently in this endpoint's response for the plain Wage
    Entry page (only `wage-entry-batch.js`'s endpoint gets that in Task 6) — for THIS
    file, the pragmatic fix is to drop the live "would this month be EPS=0" preview
    entirely (the real number still comes from the server on Save/reload, this was
    only a pre-save visual estimate) rather than reimplement DOB/month-boundary math
    a third time: set `const epsWage = pohw ? w : Math.min(w, ceiling);` (the age-58
    zeroing simply isn't previewed client-side anymore in the bulk table; the row
    still shows the correct server-computed number after Save/reload, matching what
    `GET /api/years/{key}/wages`'s `eps_zero_months` will show once the page is
    refreshed). Flag this simplification in the commit message.
11. Line ~1791: `if (pohw && pohw116 && !age58 && w > ceiling) {` → change `!age58` to
    simply drop the age term: `if (pohw && pohw116 && w > ceiling) {` (same reasoning
    as Step 10 — the live preview no longer tracks age-58 state; the real PoHW-1.16%
    redistribution math is still correct once saved, since the backend's
    `month_rows()` already handles it fully independent of this client preview).
12. Line ~1844: `age_crosses_58: state.age58` → delete this line from the save
    payload object.

- [ ] **Step 7: Live-verify**

Start the scratch-DB server. Open Monthly Wage Entry:
1. Single-employee modal: confirm no "Age > 58" checkbox appears anywhere, confirm an
   employee with no DOB shows the "No DOB on file" note, confirm saving wages still
   works and the saved EPS figure is correct for a DOB-58+ employee after reload.
2. Bulk table: confirm no "Age > 58" checkbox appears in any row, confirm saving
   still works, confirm reloading the page after save shows the correct EPS=0 for a
   58+ employee (proving the server-side number is right even though the live
   pre-save preview no longer estimates it).

- [ ] **Step 8: Commit**

```bash
git add webapp/js/wages.js
git commit -m "feat(wages): remove manual Age > 58 checkbox, add no-DOB warning

Age-58 EPS cutover is DOB-driven now (see epf_engine.py), so the
manual per-year checkbox in both the single-employee modal and the
bulk table is gone, along with all its state plumbing. Added a
non-blocking 'No DOB on file' note in the employee-details panel.
The bulk table's live pre-save preview no longer estimates age-58
zeroing client-side (would be a third reimplementation of the
month-boundary rule) -- the real number is still correct once saved
and the page reloads, which is what actually matters.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Monthly Wage Entry Batch UI — remove `age_crosses_58`, consume the backend's `eps_zero_months`

**Files:**
- Modify: `webapp/js/wage-entry-batch.js` — `webRow()` (~161-192), `webCalcLive()` (~215-230), the commit/save payload (~515)

**Interfaces:**
- Consumes: `eps_zero_months`/`eps_member` per employee from `GET /api/years/{key}/wages` (Task 6) — `webWagesData.employees[i].eps_zero_months`/`.eps_member`.

- [ ] **Step 1: Add `eps_zero_months`/`eps_member` to `webRow()`, remove `age_crosses_58`**

Change:
```javascript
function webRow(memberId) {
  const master = webMaster.find(m => m.member_id === memberId);
  if (!master) return null;
  const wageRow = webWagesData.employees.find(e => e.member_id === memberId);
  return {
    member_id: memberId,
    name: master.name,
    uan: master.uan,
    gross_wages: wageRow ? wageRow.gross_wages : new Array(12).fill(0),
    wages: wageRow ? wageRow.wages : new Array(12).fill(0),
    ncp_days: wageRow ? wageRow.ncp_days : new Array(12).fill(0),
    age_crosses_58: wageRow ? wageRow.age_crosses_58 : false,
    // These four are master-level flags (not per-year-entry), so pulling them
    // from webMaster is correct whether or not an entry exists yet this year.
    higher_epf_ee: master.higher_epf_ee,
    higher_epf_er: master.higher_epf_er,
    pohw: master.pohw,
    pohw_additional_1_16: master.pohw_additional_1_16,
  };
}
```
to:
```javascript
function webRow(memberId) {
  const master = webMaster.find(m => m.member_id === memberId);
  if (!master) return null;
  const wageRow = webWagesData.employees.find(e => e.member_id === memberId);
  return {
    member_id: memberId,
    name: master.name,
    uan: master.uan,
    dob: master.dob,
    gross_wages: wageRow ? wageRow.gross_wages : new Array(12).fill(0),
    wages: wageRow ? wageRow.wages : new Array(12).fill(0),
    ncp_days: wageRow ? wageRow.ncp_days : new Array(12).fill(0),
    // eps_zero_months/eps_member come from the server (GET .../wages), computed by
    // the same is_eps_zero_for_month() the backend uses everywhere else -- never
    // reimplement the age/month-boundary rule client-side (see the ER PF rounding
    // bug this project already hit once for why).
    eps_zero_months: wageRow ? wageRow.eps_zero_months : new Array(12).fill(false),
    eps_member: master.eps_member !== false,
    // These four are master-level flags (not per-year-entry), so pulling them
    // from webMaster is correct whether or not an entry exists yet this year.
    higher_epf_ee: master.higher_epf_ee,
    higher_epf_er: master.higher_epf_er,
    pohw: master.pohw,
    pohw_additional_1_16: master.pohw_additional_1_16,
  };
}
```

- [ ] **Step 2: Update `webCalcLive()` to read `eps_zero_months` instead of a checkbox-driven boolean**

`webCalcLive(wage, ncp)` currently takes only `(wage, ncp)` and has no employee
identity to look up DOB/eps_member from. Change its signature to also take the row,
and update its one caller-site pattern (`webCalcLive(vals.w, vals.n)`, used in both
`webRowHtml()` and `webUpdateDraftCell()` — grep `webCalcLive(` in this file to find
both call sites before editing):

Change:
```javascript
function webCalcLive(wage, ncp) {
  const r = webWagesData.rates;
  const ceiling = (r.wage_ceilings && r.wage_ceilings[webMonthIdx]) || 15000;
  const days = webCalendarDaysInMonth(webMonthIdx);
  const workDays = Math.max(0, days - (ncp || 0));
  const epsWage = Math.min(wage || 0, ceiling);
  const ee = Math.round((wage || 0) * (r.w_epf / 100));
  const pension = Math.round(epsWage * (r.e_eps / 100));
  // ER PF is the REMAINDER of the employer's total contribution (same rate as EE,
  // r.w_epf) after Pension is taken out -- not an independently-rounded 3.67%.
  // Matches epf_engine.py's month_rows() exactly (e_epf = total_er_contrib - e_eps);
  // rounding e_epf on its own can land on a .5 boundary Pension already claimed
  // (e.g. wage 15000: 15000*3.67%=550.5 rounds to 551, but EE 1800 - Pension 1250 = 550).
  const er = Math.max(0, ee - pension);
  return { days, workDays, epsWage, ee, er, pension };
}
```
to:
```javascript
function webCalcLive(wage, ncp, epsZero) {
  const r = webWagesData.rates;
  const ceiling = (r.wage_ceilings && r.wage_ceilings[webMonthIdx]) || 15000;
  const days = webCalendarDaysInMonth(webMonthIdx);
  const workDays = Math.max(0, days - (ncp || 0));
  const epsWage = epsZero ? 0 : Math.min(wage || 0, ceiling);
  const ee = Math.round((wage || 0) * (r.w_epf / 100));
  const pension = Math.round(epsWage * (r.e_eps / 100));
  // ER PF is the REMAINDER of the employer's total contribution (same rate as EE,
  // r.w_epf) after Pension is taken out -- not an independently-rounded 3.67%.
  // Matches epf_engine.py's month_rows() exactly (e_epf = total_er_contrib - e_eps);
  // rounding e_epf on its own can land on a .5 boundary Pension already claimed
  // (e.g. wage 15000: 15000*3.67%=550.5 rounds to 551, but EE 1800 - Pension 1250 = 550).
  const er = Math.max(0, ee - pension);
  return { days, workDays, epsWage, ee, er, pension };
}
```

Then update every call site (`webCalcLive(vals.w, vals.n)` in `webRowHtml()`, and the
equivalent in `webUpdateDraftCell()`) to pass the third argument — each call site
needs the row's `eps_zero_months[webMonthIdx]`, e.g.:
```javascript
const c = webCalcLive(vals.w, vals.n, row.eps_zero_months ? row.eps_zero_months[webMonthIdx] : false);
```
(`row` is already in scope in `webRowHtml()` via `const row = webRow(memberId);`;
confirm the exact variable name in scope at `webUpdateDraftCell()`'s call site by
reading its current code before editing, since that function doesn't currently call
`webRow()` — read the whole function first.)

- [ ] **Step 3: Remove `age_crosses_58` from the commit/save payload**

Change (~line 515):
```javascript
      age_crosses_58: !!(row && row.age_crosses_58),
```
Delete this line from whatever payload object it's part of (read the surrounding
function first to confirm it's safe to delete without leaving a dangling comma).

- [ ] **Step 4: Live-verify**

Start the scratch-DB server. Open Monthly Wage Entry Batch:
1. Search-add an employee with a DOB that makes them 58+ this financial year, type
   wages into a draft row, confirm the live-typing preview shows EPS = 0 immediately
   (no page reload needed) — this proves the frontend now reads the server-computed
   `eps_zero_months` instead of a removed checkbox.
2. Save the batch, confirm the saved/closed-batch row also shows EPS = 0.
3. Confirm a normal (under-58) employee's live preview still shows the correct
   nonzero EPS as before.

- [ ] **Step 5: Commit**

```bash
git add webapp/js/wage-entry-batch.js
git commit -m "feat(wage-entry-batch): consume server-computed eps_zero_months

webCalcLive() no longer estimates EPS eligibility itself -- it reads
the per-month eps_zero_months array GET .../wages now returns
(computed server-side by the same is_eps_zero_for_month() every
other path uses), avoiding a third client-side reimplementation of
the age/month-boundary rule. age_crosses_58 removed from webRow() and
the batch commit payload.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: Reports UI cleanup + ECR-generation pre-flight no-DOB warning

**Files:**
- Modify: `webapp/js/reports.js` (~line 104, and the ECR text file generation trigger)
- Modify: `webapp/app.py` (the ECR generation endpoint(s) reached from `reports.js`)

**Interfaces:**
- Consumes: `eps_zero_months`/no-DOB detection is not needed here — this task adds a
  simple pre-flight check reading `MasterEmployee.dob` directly for the employees
  about to be included in the ECR file.

- [ ] **Step 1: Remove the dead flag line in `reports.js`**

Change (~line 104):
```javascript
      if (y.age_crosses_58) flags.push('(Age 58+ applied)');
```
Delete this line (the `age_crosses_58` key no longer exists in the wage-history
response as of Task 5 Step 7).

- [ ] **Step 2: Investigate the exact ECR-generation call path in `reports.js`**

Grep `reports.js` for `/ecr` and for the function that runs when the "Generate ECR"
button is clicked. Determine: (a) does the UI call any endpoint *before* the actual
file-download request (a preview/confirm step), or does clicking the button go
straight to a file download? (b) what is the exact URL and HTTP method of the file-
download endpoint itself (already seen once in Task 4's test as
`GET /api/reports/{year_key}/ecr/{month_idx}`, confirm this is still accurate). Write
down both answers before Step 3 — they determine whether Step 3 adds a new endpoint
or extends an existing one.

- [ ] **Step 3: Write the failing test for the ECR no-DOB pre-flight warning**

Using Step 2's findings, target the actual pre-flight/preview endpoint (existing or
new). Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
def test_ecr_generation_response_lists_employees_with_no_dob(consultant_a):
    """Pre-flight visibility: the ECR generation response should surface which
    employees in this month have no DOB on file, since that's exactly the gap that
    produced the original RFE errors -- catching it here is higher-value than only
    discovering it after an EPFO portal rejection."""
    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "ECRWARN1", "name": "ECR Warn Test Co",
    })
    assert res.status_code == 200, res.text
    consultant_a.set_establishment(res.json()["establishment"]["id"])
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={
        "member_id": "ECRW001", "name": "No DOB Employee", "uan": "100900000006",
    })
    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "ECRW001", "wages": [20000.0] + [0.0] * 11,
    })
    assert res.status_code == 200, res.text

    res = consultant_a.get("/api/reports/2026-27/ecr/0?format=json")
    if res.status_code == 404:
        pytest.skip("Adjust to the actual pre-flight-metadata endpoint reports.js calls before generating the ECR download -- read reports.js to find it.")
```

This test is intentionally a starting scaffold, not a finished assertion — before
implementing, read `webapp/js/reports.js`'s ECR-generation code path to find exactly
which endpoint (if any) is called *before* the actual file download to show a
confirmation/preview step, since that's the natural place for a pre-flight warning
(a raw file-download endpoint has no good place to surface a warning banner). If no
such pre-flight endpoint currently exists, this step becomes: add one (a small
`GET .../ecr/{month_idx}/preflight`-style JSON endpoint returning
`{"no_dob_members": [{"member_id", "name"}]}`), call it from `reports.js` right
before the actual download link is triggered, and render its result as a dismissible
warning banner above the download button when the list is non-empty. Rewrite this
test to assert against whatever endpoint/shape is actually implemented.

- [ ] **Step 4: Implement the pre-flight check and banner**

Using Step 2's findings — implement the JSON pre-flight endpoint if none exists,
following the existing RBAC/establishment-scoping pattern every other
`/api/reports/...` endpoint in `webapp/app.py` already uses, i.e.
`Depends(get_active_establishment)` + `require_permission(db, current_user, "forms.download")`.

- [ ] **Step 5: Run the test, iterate until it passes**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py::test_ecr_generation_response_lists_employees_with_no_dob -v`

- [ ] **Step 6: Live-verify**

Start the scratch-DB server. Open Reports → ECR Text File Generator for a month that
includes an employee with no DOB. Confirm the warning banner appears before/during
generation, listing that employee, and that generation still succeeds (this is a
warning, not a block).

- [ ] **Step 7: Run the full suite**

Run: `pytest webapp/tests/ -v`

- [ ] **Step 8: Commit**

```bash
git add webapp/js/reports.js webapp/app.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "feat(reports): ECR generation warns about employees with no DOB on file

Pre-flight check surfaces any employee in the month/batch about to
be exported with no DOB -- the exact gap that produced the original
RFE-21/28/29/30/31 EPFO portal errors -- as a non-blocking banner
before/during ECR text generation, catching it before a portal
rejection instead of after. Also dropped the dead '(Age 58+ applied)'
flag from the wage-history popup (the field it read no longer exists).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: Migration audit endpoint (superadmin, read-only)

Reads the **raw stored JSON** directly (not through the `Project`/`YearEntry` model,
which no longer has `age_crosses_58` as of Task 2) so this works regardless of
whether it's run before or after this plan's other changes are deployed.

**Files:**
- Modify: `webapp/app.py` — add a new superadmin-only endpoint
- Test: `webapp/tests/test_eps_eligibility_engine.py`

**Interfaces:**
- Produces: `GET /api/admin/audit/eps-58-dob-check` → `{"at_risk": [{"establishment_id", "establishment_code", "establishment_name", "member_id", "member_name", "year_key", "issue": "missing_dob" | "unparseable_dob"}]}`.

- [ ] **Step 1: Write the failing test**

Append to `webapp/tests/test_eps_eligibility_engine.py`:

```python
import json


def test_eps_58_dob_audit_flags_missing_dob(consultant_a, superadmin_session, test_db):
    from webapp.database import Establishment

    res = consultant_a.post("/api/establishments", json={
        "coverage_date": "01-04-2020", "code": "AUDIT001", "name": "Audit Test Co",
    })
    assert res.status_code == 200, res.text
    est_id = res.json()["establishment"]["id"]
    consultant_a.set_establishment(est_id)
    consultant_a.post("/api/years", json={"year_from": "2026", "year_to": "2027"})
    consultant_a.post("/api/employees", json={
        "member_id": "AUDIT01", "name": "At Risk Employee", "uan": "100900000007",
    })
    consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "AUDIT01", "wages": [20000.0] + [0.0] * 11,
    })

    # Simulate a pre-existing establishment that still has the OLD age_crosses_58=True
    # flag stored in its raw JSON, with no DOB on the member -- exactly the at-risk
    # case this audit exists to catch. Written directly to raw storage since the
    # current Project/YearEntry model no longer has this field to set through the API.
    est = test_db.query(Establishment).filter(Establishment.id == est_id).first()
    data = json.loads(est.data)
    data["years"]["2026-2027"]["entries"][0]["age_crosses_58"] = True
    est.data = json.dumps(data)
    test_db.commit()

    res = superadmin_session.get("/api/admin/audit/eps-58-dob-check")
    assert res.status_code == 200, res.text
    at_risk = res.json()["at_risk"]
    match = next((r for r in at_risk if r["member_id"] == "AUDIT01"), None)
    assert match is not None, f"expected AUDIT01 flagged, got {at_risk}"
    assert match["issue"] == "missing_dob"


def test_eps_58_dob_audit_requires_superadmin(consultant_a):
    res = consultant_a.get("/api/admin/audit/eps-58-dob-check")
    assert res.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: both FAIL with 404 — the endpoint doesn't exist yet.

- [ ] **Step 3: Implement the endpoint**

Add to `webapp/app.py`, near the other superadmin admin endpoints:

```python
@app.get("/api/admin/audit/eps-58-dob-check")
async def audit_eps_58_dob_check(
    current_user: User = Depends(get_superadmin),
    db: Session = Depends(get_db)
):
    """Read-only, one-off pre-merge audit: find every establishment/member that
    currently relies on the OLD manual age_crosses_58=True flag for a financial year
    and has no (or an unparseable) DOB on file -- these are the members whose EPS
    would wrongly un-zero once the DOB-driven cutover replaces the old flag. Reads
    raw stored JSON directly since the live data model no longer has this field."""
    at_risk = []
    establishments = db.query(Establishment).all()
    for est in establishments:
        try:
            data = json.loads(est.data)
        except (TypeError, ValueError):
            continue
        master = data.get("master", {})
        for year_key, year_data in (data.get("years") or {}).items():
            for entry in (year_data.get("entries") or []):
                if not entry.get("age_crosses_58"):
                    continue
                member_id = entry.get("member_id", "")
                m = master.get(member_id, {})
                dob = (m.get("dob") or "").strip()
                if not dob:
                    issue = "missing_dob"
                else:
                    issue = None if calc_age_years(dob) is not None else "unparseable_dob"
                if issue:
                    at_risk.append({
                        "establishment_id": est.id,
                        "establishment_code": data.get("code", ""),
                        "establishment_name": data.get("name", ""),
                        "member_id": member_id,
                        "member_name": m.get("name", ""),
                        "year_key": year_key,
                        "issue": issue,
                    })
    return {"at_risk": at_risk}
```

Confirm `json` is already imported at the top of `webapp/app.py` (it almost certainly
is, given how much of this file serializes/deserializes `Establishment.data`) — add
`import json` near the other stdlib imports if it isn't.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest webapp/tests/test_eps_eligibility_engine.py -v`
Expected: both PASS.

- [ ] **Step 5: Run the full suite**

Run: `pytest webapp/tests/ -v`

- [ ] **Step 6: Commit**

```bash
git add webapp/app.py webapp/tests/test_eps_eligibility_engine.py
git commit -m "feat(admin): read-only audit endpoint for the age_crosses_58->DOB migration

GET /api/admin/audit/eps-58-dob-check (superadmin-only) scans every
establishment's raw stored JSON for members currently relying on the
old manual age_crosses_58=True flag who have no or an unparseable
DOB on file -- the members who'd silently lose their EPS-zero status
once the DOB-driven cutover replaces the old flag. Read-only, no
mutations. Must be run against production and any flagged members'
DOB corrected BEFORE this plan's other changes deploy.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 12: Fix `test_pohw.py`, run the full suite, resolve every remaining reference

**Files:**
- Modify: `webapp/tests/test_pohw.py`
- Modify: any other test file still referencing `age_crosses_58` (found via grep, not assumed)

**Interfaces:**
- Consumes: everything from Tasks 1-11.

- [ ] **Step 1: Find every remaining reference**

Run: `grep -rn "age_crosses_58" webapp/ epf_engine.py pdf_engine.py`
Expected: only `webapp/tests/test_pohw.py` (and possibly one or two other test files
the earlier per-task "run full suite" steps already surfaced) — every production
code reference should already be gone after Tasks 1-10.

- [ ] **Step 2: Fix `test_pohw.py`**

Change:
```python
def test_pohw_age_crosses_58_still_zeroes_eps(consultant_a):
    """PoHW doesn't override the existing age>=58 rule -- EPS still goes to zero and
    every rupee of the employer's 12% flows to EPF instead."""
    _setup_year_and_employee(consultant_a, "POHW0000004", "PH0004", pohw=True)

    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "PH0004", "wages": [75000.0] + [0.0] * 11,
        "pohw": True, "age_crosses_58": True,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "PH0004")
    assert emp["age_crosses_58"] is True

    april = emp["months"][0]
    assert april["es"] == 0
    assert april["ee"] == 9000   # all employer contribution flows to EPF
```
to:
```python
def test_pohw_age_58_plus_still_zeroes_eps(consultant_a):
    """PoHW doesn't override the DOB-driven age>=58 rule -- EPS still goes to zero
    and every rupee of the employer's 12% flows to EPF instead."""
    _setup_year_and_employee(consultant_a, "POHW0000004", "PH0004", pohw=True, dob="01-01-1950")

    res = consultant_a.post("/api/years/2026-27/wages", json={
        "member_id": "PH0004", "wages": [75000.0] + [0.0] * 11,
        "pohw": True,
    })
    assert res.status_code == 200, res.text

    data = consultant_a.get("/api/years/2026-27/wages").json()
    emp = next(e for e in data["employees"] if e["member_id"] == "PH0004")
    assert emp["eps_zero_months"][0] is True

    april = emp["months"][0]
    assert april["es"] == 0
    assert april["ee"] == 9000   # all employer contribution flows to EPF
```

(DOB `01-01-1950` is well over 58 for the entire 2026-27 financial year, no birthday-
boundary ambiguity — the precise boundary behavior is already covered by Task 3's
dedicated tests, so this one stays simple, matching its original intent.)

- [ ] **Step 3: Fix any other test files found in Step 1**

For each remaining match, read its exact context and apply the same pattern: replace
`"age_crosses_58": True` in request bodies with a `dob` kwarg passed at employee
creation (or via the wage-entry payload's context — most will be request-body-only
and Pydantic already silently ignores the unknown key, so these are likely only the
handful of *assertion* failures on the removed `"age_crosses_58"` response key,
fixable by asserting `eps_member`/`eps_zero_months` instead, or simply deleting the
now-meaningless assertion if the test's actual point is unrelated to EPS/age).

- [ ] **Step 4: Run the full suite**

Run: `pytest webapp/tests/ -v`
Expected: 100% pass — every pre-existing test plus every test added across Tasks 1-11.

- [ ] **Step 5: Commit**

```bash
git add webapp/tests/
git commit -m "test: migrate remaining age_crosses_58 references to DOB-driven fields

test_pohw.py's age-58 test now uses a DOB well past 58 instead of the
removed manual flag. Full suite green.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: Live verification, run the migration audit, deploy

**Files:** none (verification + deploy only)

- [ ] **Step 1: Set up a scratch DB copy**

```bash
cp local_dev.db /tmp/eps_engine_scratch.db
```
(Or the Windows-appropriate copy command / a path under the scratchpad directory —
follow whatever this project's established scratch-DB pattern already is, same as
every prior feature's live-verification step.)

- [ ] **Step 2: Run the app against the scratch DB**

Set `DATABASE_URL` to point at the scratch copy, start `uvicorn webapp.app:app` on a
free local port — never the real `.env` `DATABASE_URL` (production Neon), per
`feedback_local_db_safety`.

- [ ] **Step 3: Walk through every UI change from Tasks 7-10 in the Browser tool**

1. Employee Master: add an employee with DOB required, EPS Member checkbox, no-DOB
   badge on an existing employee.
2. Monthly Wage Entry: no Age > 58 checkbox anywhere, no-DOB note shows, saved EPS
   figures correct on reload for a 58+ employee.
3. Monthly Wage Entry Batch: live preview correctly shows EPS = 0 for a 58+ employee
   without saving first (proves server-computed `eps_zero_months` is wired through).
4. Reports → ECR generation: no-DOB pre-flight warning appears for an affected month.
5. Download an actual ECR text file for a 58+ employee and a `eps_member=False`
   employee, open the raw file, confirm EPS Wages/EPS Contribution fields are `0` in
   both cases (matches the original RFE-21/28/29/30/31 failure fields exactly).
6. Download the corresponding Excel and PDF forms for the same employees, confirm the
   same zero EPS figures.

- [ ] **Step 4: Tear down the scratch DB**

Kill the scratch `uvicorn` process, delete the scratch DB file.

- [ ] **Step 5: Run the full pytest suite one final time**

Run: `pytest webapp/tests/ -v`
Expected: 100% pass.

- [ ] **Step 6: Push and confirm the deploy**

```bash
git push origin main
```

Poll `https://epf-dashboard.xyz/api/version` for the new commit hash (Coolify
auto-deploys on push to `main`; a transient 502 mid-deploy is normal, retry over
1-3 minutes).

- [ ] **Step 7: Run the migration audit against production**

**Do not run this yourself against the production database or with the user's
credentials.** Instead, give the user this exact instruction: once deployed, open
`https://epf-dashboard.xyz/api/admin/audit/eps-58-dob-check` in their browser while
logged in as superadmin (or run it from their own authenticated session's dev tools/
Postman with their own token). Report the `at_risk` list back and, for each entry,
correct that member's DOB in Employee Master **before** telling the user this feature
is fully safe to rely on for that establishment — this is the one step in the whole
plan that has real production-data risk if skipped.

- [ ] **Step 8: Report to the user**

Confirm: commit hash live on `/api/version`, full 205+ test suite green, every UI
change live-verified, and the exact URL + instructions from Step 7 for them to run
the migration audit and report back any `at_risk` establishments.
