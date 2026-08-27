# Flexible year-order entry gating — design

Date: 2026-08-27
Supersedes the month-level and year-order rules from
[2026-08-26-month-year-entry-gating-design.md](2026-08-26-month-year-entry-gating-design.md)
(the calendar ceiling, coverage_date floor, download gating, trial exemption, and
superadmin bypass from that spec are all kept unchanged — only the *ordering* rules
change).

## Why

The original design forced strict chronological entry: one financial year at a time,
exactly the next one after coverage_date, and inside a year, one month at a time,
gated on the previous month's payment. That's correct for a brand-new establishment,
but real onboarding often means a consultant/employer bringing in an establishment
with a 20-year-old coverage date — forcing 20 years of sequential paid backfill before
they can touch current data is unworkable. Confirmed via user discussion
(2026-08-27): this is a real scenario, not a theoretical one, and consultants/
employers themselves (not just superadmin) need to be able to work around it.

## What changes

**Financial years** can now be added in any order — backfill or forward-fill — subject
to only two rules:
1. Never before the establishment's locked `coverage_date` (the floor is unchanged
   from the original design).
2. The most-recently-*added* year (by real add time, not financial-year order) must
   have no outstanding subscription-fee due before another year can be added. Trial
   establishments are exempt from this payment condition (never from the floor),
   matching every other payment gate in the app.

**Months within an already-added year** are now free-form: no chronological order, no
per-month payment gate. The only thing that still blocks entering a specific month is
the calendar ceiling — a month that hasn't ended yet in real life can never be entered,
regardless of year or payment status. This is unchanged from the original design
(deliberately not a payment/ordering rule).

**Downloads/reports** stay gated exactly as today via the separate
`get_unpaid_months_for_year` / `is_month_overdue` mechanism (CLAUDE.md's "Subscription-
fee download gating" section) — entering data is decoupled from payment now, but
printing/downloading it for a month with an outstanding fee is not.

**Superadmin** keeps its existing full bypass of all of this (year floor, year-order
payment condition, month calendar ceiling was already superadmin-exempt for save
targets — see `test_superadmin_bypasses_monthly_wage_entry_gating` precedent) — no
change in spirit from the original design, which already treated superadmin as
unrestricted.

## What is explicitly NOT changing

- `coverage_date`: still mandatory at creation, still locked except for superadmin.
- Download gating (`get_unpaid_months_for_year`, `is_month_overdue`, the 402 flow,
  Cashfree, advance credit, trial exemption on downloads).
- The calendar ceiling itself (`get_current_wage_month`, `get_max_enterable_month`) —
  only *which* things it's checked against changes (every month in every year, instead
  of only "the next" month).
- `POST /api/years/bulk` stays superadmin-only.
- Grandfathering ("never retroactively block a month that already has wage data") is
  moot for months now (nothing blocks a month by order/payment anymore), but the
  underlying principle — never punish already-entered data — carries over naturally
  since there's no more retroactive locking of any kind.

## Data model change

`epf_engine.YearRecord` gains an `added_at` field (ISO 8601 datetime string), stamped
by `Project.add_year()` at creation time. This is the source of truth for "most
recently added year" — NOT financial-year order, since years can now be added out of
order.

Rejected alternative: deriving "most recently added" from `ActivityLog` instead. Logs
are meant to be a side effect; making them load-bearing for an enforcement decision in
statutory-compliance software means a failed/pruned log write silently changes gate
behavior. `ActivityLog` still gets a row on every year addition (not just the first,
unlike the original design) for audit visibility — but it's descriptive, not
authoritative.

**Backward compatibility**: existing `YearRecord`s serialized before this change have
no `added_at`. `YearRecord.from_dict()` falls back to a synthetic timestamp derived
from the year's own financial-year start (e.g. `"{year_from}-04-01T00:00:00"`) when the
field is missing. Every establishment's pre-existing years were necessarily added in
strict chronological order under the old gate, so this fallback reconstructs the
correct relative ordering without a database migration — the data lives in the JSON
blob (`Establishment.data`), not a SQL column, so there is nothing to `ALTER TABLE`.

## API contract changes

### `get_entry_lock_status(db, est_obj, project)` — replaced

The old function walked every financial year from `coverage_year_key` forward,
computing `next_year_to_add` / `next_open_month` / `locked_month`. That whole
mechanism is gone. Its replacement (same file, `webapp/app.py`) does a single O(1)
check — no walk, no `sync_subscription_fees_for_year` loop:

```
{
  "coverage_year_key": str | None,
  "can_add_year": bool,
  "blocking_year": {"year_key": str, "amount_due": float} | None
}
```

- `coverage_year_key`: unchanged meaning (fails open to `None` for a legacy
  establishment with no coverage_date, same as before).
- `blocking_year`: the most-recently-added year (by `added_at`), only when it still
  has an outstanding due. `amount_due` is the sum of `amount_due` across that year's 12
  months (trivially just the unpaid ones, since a month with no wage data already has
  `amount_due <= 0`), for display. `None` when there are no years yet, or the
  most-recent one is fully paid, or the establishment is in trial.
- `can_add_year`: `False` only when `blocking_year` is set (i.e. convenience flag,
  `blocking_year is None`).

This also incidentally resolves the just-shipped performance concern about walking
every year on every check (commit `5dc4406`, "batch get_entry_lock_status per-year fee
syncs into one commit") — the new check only ever looks at one year, not N.

### `POST /api/years`

For non-superadmin: drop the `key == next_year_to_add` exact-match requirement.
Replace with:
1. `int(key.split("-")[0]) >= int(coverage_year_key.split("-")[0])` when
   `coverage_year_key` is set (fails open otherwise, same as today).
2. `key not in project.years` (unchanged).
3. `status["can_add_year"]` from the new `get_entry_lock_status`, using its
   `blocking_year` in the error message ("FY {blocking_year.year_key} has ₹{amount_due}
   outstanding — pay it before adding another year.").

Every year addition (not just the first) logs an `ActivityLog` row for audit
visibility (see Data model change above).

### `POST /api/years/{key}/wages/bulk_month`

Drop the entire `next_open_month` / `locked_month` block. Replace with just the
calendar ceiling, applied uniformly to any month in any already-added year (not only
"the next" one):

```
target = (int(key.split("-")[0]), d.month_idx)
max_year_from, max_month_idx = get_max_enterable_month()
if current_user.role != "superadmin" and target > (max_year_from, max_month_idx):
    raise HTTPException(409, "<month> <year> cannot be entered until that month has ended.")
```

No trial exemption here — unchanged from today, the calendar ceiling is absolute.

### `GET /api/establishment/entry-lock-status`

Returns the new `get_entry_lock_status` shape directly (see above).

## Frontend changes

**`webapp/js/years.js`**: the `next_year_to_add` banner and Add Year form auto-prefill
are replaced with a `can_add_year` / `blocking_year` banner ("Pay ₹{amount_due} for FY
{year_key} before adding another year" when blocked; nothing when not). The Add Year
form's year field is no longer force-prefilled or effectively read-only — the
consultant/employer types any year at or after the coverage year. The one-time
explainer modal's copy is updated to describe: pay for a year before adding the next
one, months inside a year are free-form, the calendar ceiling still applies.

**`webapp/js/wages.js`**: all `next_open_month` / `locked_month` UI (disabled month
buttons, lock icons, "must enter X first" messaging) is removed — every month in the
selected year is selectable. The calendar ceiling still needs to disable not-yet-ended
months in the month selector; since `entry-lock-status` no longer carries calendar
info, `/api/constants` gains a `max_enterable_month: {"year_key": str, "month_idx":
int}` field (pure calendar fact, independent of establishment) for this purpose, and
`wages.js` stops calling `entry-lock-status` entirely.

## Test impact

Most of the ~30 chronological month-gate tests in
`webapp/tests/test_month_year_entry_gating.py` test behavior that no longer exists
(month-level locking, exact-next-year enforcement) and need rewriting, not just
touching up. Kept as-is in spirit, re-pointed at the new contract: trial exemption,
coverage_date floor/lock, superadmin bypass, `entry_gating_started` logging (now
extended to every addition), the member_id-truncation regression, financial-year-key
parsing helpers. New coverage needed: free-form month entry within a year (any order,
any payment status) still respecting the calendar ceiling; pay-per-added-year ordering
allowing genuine backfill-then-forward-fill sequences; `added_at` migration fallback
for pre-existing years loaded without it.

## Open implementation questions for the plan

- Exact wording for the Add Year banner and explainer modal copy.
