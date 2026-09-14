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

Confirmed with the user (2026-09-14): pure DOB-driven automation, no manual override
checkbox retained (see "What is explicitly NOT changing" for why).

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
  `pdf_engine.py`, `generate_ecr_month`) — no direct changes. They already consume
  `month_rows()`/`annual_totals()` exclusively (confirmed by code trace), which is the
  entire point of fixing this at the one shared calc function.
- Making `dob` a required field at employee creation (see "Open items" below for why,
  and the mitigation).

## Data model changes

`epf_engine.py`:

- `MasterEmployee`: add `eps_member: bool = True`.
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
  any employee row where it's unchecked.
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
missing or clearly-wrong DOB so it can be corrected in Employee Master first.

No SQL/database migration is needed — establishment data is one JSON blob
(`Establishment.data`), and old `age_crosses_58` values simply become inert once the
code stops reading them.

## Testing

- New `pytest` cases in the calc-engine test file: an employee whose DOB puts their
  58th birthday in each of several different wage months (including across the
  Mar-start financial-year wrap, e.g. a January or February birthday), asserting EPS
  is present through the birthday month and zero from the next month on.
- `eps_member=False` zeroes EPS every month regardless of age.
- Missing/unparseable DOB with `eps_member=True` never auto-zeroes (documented
  fallback, not a bug — see Open Items).
- Full existing suite (205 tests as of this design) must still pass; any test
  asserting the old `age_crosses_58` behavior is migrated to the new fields.
- Live verification on a throwaway scratch-DB copy via the Claude_Browser tool, per
  this project's established pattern — Employee Master's new EPS Member checkbox,
  both wage-entry pages with the old checkbox gone, and a generated ECR/Excel/PDF
  correctly zeroing EPS for both a DOB-58+ employee and an `eps_member=False` employee.

## Open items

- **Missing DOB**: `dob` is not a required field today (only Member ID and Name are).
  This design makes it load-bearing for a compliance-critical calculation for the
  first time — an employee with no DOB on file simply never gets the age-58 cutover
  applied automatically (same as "not yet 58"), which is the same failure mode as
  today, not a new one, but is worth being visible about rather than silent.
  Recommendation: keep `dob` optional (don't force a breaking mandatory-field change
  onto existing employees or bulk Excel imports), but surface a non-blocking warning
  — in the Employee Master list and/or at wage-entry time — for any employee with no
  DOB on file, so a consultant filing near someone's 58th birthday notices before it
  becomes an ECR rejection instead of after.
