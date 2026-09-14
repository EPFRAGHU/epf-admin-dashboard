# EPS eligibility engine — design

Date: 2026-09-14

## Why

A real production client (Magnova Consulting Pvt Ltd, `ORBBS2012397000`) got ECR
validation errors on the EPFO employer portal after uploading a text file generated
by this app:

- RFE-30/31 — EPS wages/contribution not allowed for employees aged above 60.
- RFE-28/29 — EPS wages/contribution not allowed for employees above 58 who haven't
  opted for deferred pension.
- RFE-21 — "UAN is not a member of pension scheme" — EPS wages/contribution should be
  zero.
- RFE-37/25 — Employer PF contribution must equal Due EPF − Due EPS; EPS contribution
  must be exactly 8.33% of EPS wages.

Investigation (code-reading only, no production data touched) found:

1. `epf_engine.py`'s `Employee.month_rows()` already computes Employer PF as the
   *remainder* of the employer's total contribution after EPS is subtracted
   (`e_epf = max(0, total_er_contrib - e_eps)`) — RFE-37/25 are not an independent bug,
   they're downstream symptoms of EPS wages/contribution being wrong first. Once EPS is
   correctly zeroed for an employee, the employer-PF split self-corrects.
2. The only existing age-58 handling is a single manual `age_crosses_58` boolean
   checkbox, stored **once per employee per financial year** (`YearEntry.age_crosses_58`
   in `epf_engine.py`, surfaced as an "Age > 58 (EPS = 0)" checkbox in `wages.js` and
   `wage-entry-batch.js`). An employee who turns 58 partway through a financial year has
   no way to get the correct answer for some months and not others — the flag is
   all-or-nothing for all 12 months. This explains why only some ECR line numbers in a
   given filing error and not others: it's a partial-year mismatch, not a random one.
3. There is no field anywhere for "not an EPS member" (RFE-21). This is not an age
   condition — EPFO's UAN master can mark a member as EPS-excluded independent of age
   (e.g. certain international workers, or members who opted out at a pre-Sept-2014
   enrollment). The app has no way to represent this at all today.
4. **A confirmed, currently-live, unrelated bug that blocks this whole design**:
   `calc_age_years()` (`epf_engine.py:79`) parses DOB with
   `datetime.strptime(dob_text, "%d/%m/%Y")` — **slash**-separated. But every real DOB
   in this app is stored **hyphen**-separated (`DD-MM-YYYY`): the Employee Master UI's
   own `parseDMY()` in `employees.js` splits on `-`, and the Excel-import path's
   `format_date()` helper in `epf_engine.py` explicitly does
   `val.replace("/", "-")` before storing. No code path ever produces slash-format DOB.
   Result: `calc_age_years()` returns `None` for every real employee, always —
   `is_due_superannuation`/the Employee Master "58+" badge has never actually fired for
   anyone. The identical bug exists in `employees_joined_in_month`/
   `employees_left_in_month` (`epf_engine.py:2545`/`2564`), which parse DOJ/DOE the same
   slash-format way — and those two functions feed **Form 5 (new joiners) and Form 10
   (employees left)** generation in both Excel and PDF. Confirmed live/shipping, found
   while investigating this design, unrelated to the ECR errors that prompted it — user
   confirmed (2026-09-14) to fold the fix into this same pass since it's the identical
   one-line format-string fix in three places.

## What changes

1. **Age-58/60 EPS cutover becomes automatic, derived from DOB**, replacing the manual
   per-financial-year checkbox. `MasterEmployee.dob` is already collected and already
   drives `is_due_superannuation`/`age_years` (used today only for an informational
   "58+" badge in the Employee Master list) — this design makes that same DOB math
   load-bearing for the actual EPS calculation, evaluated per wage month instead of
   once a year.
2. **New `eps_member` flag** on `MasterEmployee`, default `True`, independent of age.
   When `False`, EPS wages and EPS contribution are always zero for that employee, every
   month, regardless of age — this is the RFE-21 fix.
3. **`calc_age_years()` and `employees_joined_in_month`/`employees_left_in_month` fixed**
   to parse `DD-MM-YYYY` (matching what's actually stored), not `DD/MM/YYYY`. This is a
   prerequisite for #1 above (the whole age-58 design is built on `calc_age_years()`
   actually working) and also fixes Form 5/Form 10 generation as a side effect.
4. **`dob` becomes a required field on the manual Add/Edit Employee forms only** —
   matching how Member ID/Name are already required there. **Excel bulk import stays
   lenient and does NOT require DOB** (user's explicit call, 2026-09-14): a row with a
   blank DOB still imports, same as every other already-optional import column
   (father_name, sex, etc.) — real EPFO-portal exports often don't carry it, and losing
   the rest of that employee's data over one missing field is worse than importing it
   and catching the gap later. The DOB/age-58/eps-member check instead happens **at the
   point it actually matters**: wage entry and ECR generation (see new section below),
   not at data-entry time. (Existing employees already saved without a DOB — whether via
   import or old manual entry — are not retroactively touched by any of this; see
   Migration/rollout.)

Confirmed with the user (2026-09-14): pure DOB-driven automation, no manual override
checkbox retained (see "What is explicitly NOT changing" for why); DOB required, not
optional-with-a-warning; both pre-existing date-format bugs folded into this same pass.

## Business rule: the exact month boundary

Confirmed with the user: **the wage month in which an employee turns 58 is still a
normal EPS month — the cutover starts the following month.**

Concretely: for wage month M, compute the employee's age as of the *first calendar day*
of M (reusing the existing `calc_age_years(dob, as_of=...)` helper, which already
accepts an `as_of` date). If that age is ≥ 58, EPS is zero for month M. An employee who
turns 58 partway through month M has age < 58 as of M's start, so month M still gets
EPS; month M+1 does not.

This same rule handles both the "above 58, no deferred pension" (RFE-28/29) and "above
60" (RFE-30/31) cases identically — anyone ≥ 60 is necessarily also ≥ 58, so one
age-58 cutover rule satisfies both EPFO checks without separate logic.

## What is explicitly NOT changing

- The remainder-method Employer PF calculation in `month_rows()`
  (`e_epf = max(0, total_er_contrib - e_eps)`) — already correct, not touched.
- **Deferred pension (EPS Para 11(3)/Table D)** — an employee who explicitly opts to
  keep contributing to EPS past 58 (up to 60). Out of scope: none of the establishment's
  current ECR errors indicate a deferred-pension employee, and adding it now would mean
  building a manual-override escape hatch this design deliberately avoids. If a real
  need comes up later, it's a small follow-up: one more `MasterEmployee` boolean that
  skips the age-58 zeroing.
- The pre-1997 contribution scheme branch of `month_rows()` (the `else` branch when
  `worker_eps_rate != 0`) — EPS/Pension Fund as a concept didn't exist before 1995;
  this branch has no age-58 logic today and none is being added.
- The ECR/Excel/PDF generators themselves (`epf_engine.py`'s `ExcelGenerator`,
  `pdf_engine.py`, `generate_ecr_month`) — no direct changes beyond the date-format fix
  below. They already consume `month_rows()`/`annual_totals()` exclusively (confirmed
  by code trace), which is the entire point of fixing this at the one shared calc
  function.
- The *storage* format of `dob`/`doj`/`doe` (`DD-MM-YYYY`, hyphen-separated) — already
  correct and already what every entry path produces. Only the buggy *parser* changes
  to match it (see "Prerequisite bug fix" above) — this is not a data migration, no
  stored date string needs to change.

## Data model changes

`epf_engine.py`:

- `calc_age_years()`: fix `strptime` format from `"%d/%m/%Y"` to `"%d-%m-%Y"`.
- `employees_joined_in_month()`/`employees_left_in_month()`: same fix, same reason —
  these feed Form 5/Form 10.
- `MasterEmployee`: add `eps_member: bool = True`; `dob` becomes required (no default
  empty string accepted by the create/update path — enforced in `webapp/app.py`'s
  Pydantic request models, matching how `member_id`/`name` are already required there).
- `YearEntry`: remove `age_crosses_58` (no longer meaningful — the calc no longer
  reads a per-year flag).
- Calc-engine `Employee` dataclass: remove `age_crosses_58`; add `eps_member: bool`,
  populated in `build_employees_for_year()` from the matching `MasterEmployee` (same
  pattern already used for `higher_epf_ee`/`higher_epf_er`/`pohw`).
- `Employee.month_rows(...)` gains a `year_from: str` parameter — needed to resolve a
  wage-month index (0=Mar..11=Feb) to an actual calendar date for the age check. Every
  current caller (`annual_totals`, the Excel generator, `pdf_engine.py`,
  `generate_ecr_month`) already has `year_from` available via `YearRecord`/`Project`,
  so this is a mechanical threading change, not a new lookup.
- `annual_totals(...)` passes `year_from` through to `month_rows(...)`.

## Calc engine changes

`epf_engine.py`:

- New module-level helper, near `calc_age_years`:
  `is_eps_zero_for_month(dob: str, month_idx: int, year_from: str) -> bool` — resolves
  month_idx's calendar start date for the given financial year (reusing the same
  month-index → calendar-date convention already established by `get_wage_ceiling`),
  then returns `calc_age_years(dob, as_of=<that date>) >= 58` (treating a missing/
  unparseable DOB, i.e. `calc_age_years` returning `None`, as "not eligible for
  cutover" — see Open Items).
- In `month_rows()`, every place that currently reads `self.age_crosses_58` (3 sites:
  `eps_wage` under PoHW, `eps_wage` under the ordinary branch, and the `pohw_additional_1_16`
  guard) is replaced with:
  `eps_zero = (not self.eps_member) or is_eps_zero_for_month(self.dob, i, year_from)`
  and `eps_wage = 0 if eps_zero else ...`.
- `generate_ecr_month`'s own duplicate `eps_w = 0 if emp.age_crosses_58 else ...` (line
  ~3056) is replaced with a call to the same `is_eps_zero_for_month` helper (plus the
  `eps_member` check) — not re-derived a second time, to avoid reintroducing the class
  of duplicate-calc drift already fixed once this project (the wage-entry-batch ER PF
  rounding bug).

## UI changes

- **Employee Master** (`employees.js`): new "EPS Member" checkbox in the add/edit
  forms, default checked. A small badge (matching the existing "58+" badge pattern) on
  any employee row where it's unchecked, and a second small badge/indicator for "No DOB
  on file" so it's visible without having to go elsewhere to discover it. `Date of
  Birth` becomes required on the **manual** add form and edit form only — the Excel
  import path is explicitly exempted (see "What changes" #4) and does not validate or
  require it.
- **Monthly Wage Entry / Wage Entry Batch** (`wages.js`, `wage-entry-batch.js`): when
  saving wages for a member with no DOB on file, show a non-blocking warning ("No DOB on
  file — age-58 EPS cutover can't be auto-checked for this employee") rather than
  silently proceeding. Doesn't block the save (wage entry is not the place to force a
  Employee Master edit) — just makes the gap visible at the moment it's actually
  relevant, instead of only surfacing as an EPFO ECR rejection days later.
- **ECR text file generation** (`reports.js` + the `/api/reports/.../ecr` endpoint):
  before/alongside generating the file, list any employee in that month/batch with no
  DOB on file as a pre-flight warning — the exact failure mode that produced the RFE
  errors this design exists to fix, so this is the highest-value place to catch it.
- **Monthly Wage Entry** (`wages.js`): remove the "Age > 58 (EPS = 0)" checkbox from
  both the single-employee modal and the bulk-table row, and its `age_crosses_58` /
  `age58` state plumbing (`bulkTableState`, save payload, the read-side flag badge).
- **Monthly Wage Entry Batch** (`wage-entry-batch.js`): remove `age_crosses_58` from
  `webRow()`/`webCalcLive()`/the commit payload. `webCalcLive()`'s live-typing preview
  currently recomputes EPS client-side from a checkbox value — since the rule is now
  DOB-driven, the backend (`GET .../wages`, `GET .../wage-batches/...`) should return a
  precomputed **per-month "EPS applies" boolean** for each employee alongside the wage
  data, and the JS reads that instead of reimplementing the age-58/month-boundary rule
  a second time. This is the same lesson as the ER PF rounding bug: any client-side
  duplicate of a statutory calc is a standing drift risk.
- **Reports** (`reports.js`): the `(Age 58+ applied)` flag badge (driven today by the
  now-removed `age_crosses_58`) is dropped — there's no more a manually-set flag to
  call out; the per-month EPS-zero state is now just a computed fact, not a
  user-entered one worth flagging separately.

## Backend endpoint changes

`webapp/app.py`:

- `GET /api/years/{key}/wages` and `GET /api/years/{key}/wage-batches/{month_idx}`
  (or wherever the batch page currently sources `webWagesData`) additionally return,
  per employee, the per-month `eps_zero`/`eps_applies` array described above — computed
  server-side via the same `is_eps_zero_for_month` helper, not duplicated.
- `POST /api/years/{key}/wages` and `POST /api/years/{key}/wages/bulk_month` stop
  accepting `age_crosses_58` in the request body (silently ignored if an old client
  sends it, rather than erroring, to tolerate any in-flight requests during deploy).

## Migration / rollout risk

This is the one real risk in this design, and it needs to be handled **before** merge,
not after:

Any establishment currently relying on the manual `age_crosses_58=True` flag for a
financial year will, after this ships, get its EPS-zero behavior from DOB instead. If
that employee's `dob` in Employee Master is present and correct, the result stays
correct (and becomes more precise — per-month instead of whole-year). **If DOB is
missing or wrong for such an employee, their EPS wrongly un-zeroes after deploy** — a
real regression for a live-filing client.

Required before merge: a one-off read-only audit across all establishments for any
`YearEntry.age_crosses_58 == True`, cross-checked against that member's
`MasterEmployee.dob` — flag (to the user, not auto-fixed) any such member with a
missing or clearly-wrong DOB so it can be corrected in Employee Master first. Making
`dob` required going forward (see "Resolved during design review") stops the problem
from growing, but doesn't retroactively backfill anyone already saved without one —
this audit is still the only thing that catches the existing at-risk employees before
they silently lose their EPS-zero status.

No SQL/database migration is needed — establishment data is one JSON blob
(`Establishment.data`), and old `age_crosses_58` values simply become inert once the
code stops reading them.

## Testing

- Regression tests for the date-format fix itself: `calc_age_years("15-06-1965")`
  (hyphen input, the only real format) returns the correct age;
  `employees_joined_in_month`/`employees_left_in_month` correctly match a hyphen-format
  DOJ/DOE — plus a live-verified Form 5/Form 10 generation against a scratch employee
  with a DOJ/DOE in this financial year, confirming they now actually appear (they
  would not have, before this fix).
- New `pytest` cases in the calc-engine test file: an employee whose DOB puts their
  58th birthday in each of several different wage months (including across the
  Mar-start financial-year wrap, e.g. a January or February birthday), asserting EPS
  is present through the birthday month and zero from the next month on.
- `eps_member=False` zeroes EPS every month regardless of age.
- Full existing suite (205 tests as of this design) must still pass; any test
  asserting the old `age_crosses_58` behavior is migrated to the new fields.
- Excel import with a blank-DOB row: confirm the employee still imports fully (not
  rejected), and that the resulting record shows the "No DOB on file" indicator.
- Live verification on a throwaway scratch-DB copy via the Claude_Browser tool, per
  this project's established pattern — Employee Master's new EPS Member checkbox and
  manual-form required-DOB validation, both wage-entry pages with the old checkbox
  gone and the new no-DOB warning showing for an affected employee, ECR generation's
  pre-flight no-DOB warning, and a generated ECR/Excel/PDF correctly zeroing EPS for
  both a DOB-58+ employee and an `eps_member=False` employee.

## Resolved during design review

- **DOB required-ness**: originally proposed keeping `dob` optional everywhere with a
  warning. User's final call (2026-09-14, two rounds): required on the **manual**
  Add/Edit Employee forms (matching Member ID/Name), but **Excel bulk import stays
  lenient** — a blank-DOB row still imports in full, since real EPFO-portal exports
  often lack it and the priority there is not losing the rest of that employee's data.
  The actual age-58/EPS-member check happens downstream, at wage-entry and
  ECR-generation time (see UI changes), which is where the original RFE errors were
  actually caught in the first place. Existing employees saved without a DOB — via
  import or old manual entry — are not retroactively edited by any of this; they
  simply can't be re-saved via the manual form without adding one going forward, and
  the wage-entry/ECR warnings catch them in the meantime.
