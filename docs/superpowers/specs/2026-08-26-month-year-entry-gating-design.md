# Month/Year Subscription-Fee Entry Gating — Design Spec

Status: **draft, not yet approved for implementation**
Date: 2026-08-26

## 1. Problem

Today, data entry (wage entry, financial-year creation) is never blocked by payment status — only *downloads* are (`GET /api/reports/...` returns 402 if any month in the requested year has an overdue `SubscriptionFee`). A consultant/employer can enter unlimited months and years of wage data without ever paying, and only hits a paywall when they try to download a form.

The user wants payment gating moved earlier, onto *entry itself*, with a specific sequential/chronological shape:

- **Forward**: a new establishment enters and pays for one month at a time — month N+1's entry fields stay locked until month N's fee is paid.
- **Backward**: entering any earlier month/year than where the establishment currently stands requires advance payment (auto-debited from the existing Advance Credit wallet if funds are available), and must proceed **chronologically from the earliest missing year forward** — you cannot cherry-pick 2005 while skipping 2000, and each year must be fully paid, month by month, before the next one unlocks.
- No bulk multi-year creation for consultants/employers (superadmin only).

This spec covers that gating mechanism. It does **not** cover the tiered base-fee pricing discussed the same day ([[project_tiered_base_fee_pricing_proposal]]) — that's billing-rate calculation, orthogonal to this entry-gating mechanism, and not required for it.

## 2. What already exists (verified against current code, 2026-08-26)

- `Establishment.coverage_date` is now mandatory and locked once set ([[project_coverage_date_lock]], shipped `a110b1b`) — this is the anchor for "what is the earliest financial year this establishment could possibly have wage data for."
- `apply_advance_credit_if_available()` (`webapp/app.py:239`) already auto-debits a newly-billed month's fee from `Establishment.advance_credit_balance` the moment the fee row is created, if the balance covers it. No new work needed for "auto-debit from wallet."
- `sync_subscription_fees_for_year()` already computes/tracks `SubscriptionFee` rows per month, per year, from actual wage data.
- Form 3A/6A/12A/5/10 (`GET /api/reports/{key}`) and Form 9 (`GET /api/reports/form9/download`) already require **every month in the year** (Form 9: every year on file) to be paid before generating. ECR (`GET /api/reports/{year_key}/ecr/{month_idx}`) is the only per-month artifact. So "only ECR is available for an in-progress year" is already true today — no new restriction needed there.
- `POST /api/years/bulk` creates any year range instantly with **no** permission check and **no** payment awareness at all — this is the endpoint to lock down.
- Wage entry (`POST /api/years/{key}/wages`, `POST /api/years/{key}/wages/bulk_month`) has no payment check at all today.
- `POST /api/years` (single-year creation) has no payment or chronological-order check today.

## 3. Design

### 3.1 No new "declaration" flag — it's a one-time informational modal, not stored state

Earlier discussion floated a persisted "forward-only declaration" per establishment. On reflection this isn't needed as data: the enforcement rule (3.2 below) is uniform regardless of whether someone "declared" anything — it always requires prior months paid, recursively, back to the coverage-date month. So the "declaration" becomes a **one-time explanatory modal**, shown the first time an establishment adds its first financial year, that just explains how entry unlocking works going forward. It sets expectations; it doesn't change backend behavior. This avoids a new flag with its own edge cases (what if they change their mind, what if it's per-year vs per-establishment, etc.) — YAGNI.

### 3.2 The enforcement rule

For a given establishment, define the **chronological year sequence** starting from the financial year containing `coverage_date`. For establishment X with `coverage_date` in FY 2020-21, the sequence is 2020-21, 2021-22, 2022-23, ... up to the current real-world financial year.

A month `M` in year `Y` may be **entered** (wage save accepted) only if:
1. Every month before `M` within `Y` is fully paid (existing per-month `SubscriptionFee.is_paid`), **and**
2. Every year before `Y` in the chronological sequence is fully paid (all 12 months), **and**
3. `Y` itself has been added to the establishment (years are still added one at a time, per 3.4).

A year `Y` may be **created** (`POST /api/years`) only if it is the next unadded year in the chronological sequence (i.e., all earlier years in the sequence already exist and are fully paid, or `Y` is the very first year = the coverage-date year).

This single rule handles forward entry (month N+1 blocked until N is paid) and backward/chronological backfill (year 2001-02 blocked until 2000-01 is fully paid) with the same logic — no separate "forward mode" vs "backward mode" branching needed.

### 3.3 Grandfathering — critical, do not skip

This rule must **only apply to months/years that don't yet have any wage data**. It must never retroactively block:
- Editing a month that already has wage rows (regardless of payment status) — existing consultants have used the app freely until now; don't lock them out of correcting a typo in data they already entered.
- Any establishment/year/month combination that already exists in the database as of the day this ships.

Concretely: the check in `POST /api/years/{key}/wages` only fires when saving would be the **first** wage entry for that member+month (or, more simply and safely: skip the check entirely if the month already has *any* non-zero wage row for *any* employee in the establishment — meaning entry into that month has already begun under the old rules, so it stays open).

### 3.4 Bulk year creation

`POST /api/years/bulk` gets a `require_permission`-style superadmin-only gate (matching the pattern already used for `billing_mode`/`trial_ends_on`) — reject with 403 for consultant/employer. The frontend's bulk-year UI (wherever it's exposed to consultants today) is removed/hidden for non-superadmin roles.

### 3.5 Backfill UX: "month wise or year wise"

When an employer/consultant wants to enter data for a month/year that isn't the next chronological slot, present a choice:
- **Month wise**: they're missing specific months within a year that's already partially entered (e.g., a gap). Pick the year, pick the month(s), pay/auto-debit per month as today's flow already does.
- **Year wise**: open an entirely new prior financial year. Requires that year to be the next one in chronological sequence (3.2, rule for year creation) — if it isn't, the UI should say which year needs to be added first (see 3.6).

Either path still only ever operates on **one year at a time** — never a bulk range.

### 3.6 Notification of chronological order

If someone tries to add/enter a year or month that skips ahead of the chronological sequence, the error response should name the actual next required year/month, e.g.: *"You have unpaid or unadded months before this. Start from FY 2000-01 (Mar 2000) — the earliest year based on this establishment's EPF Coverage Date."* This is a clear 400/409 error message, not a silent block.

### 3.7 Wage-entry month dropdown

Simplify the month-select dropdown in Monthly Wage Entry (`webapp/js/wages.js`) to plain month names (Mar, Apr, ... Feb) instead of the current "Mar Paid in Apr" phrasing. Scoped to this one dropdown only — `reports.js`'s month-wise summary table keeps its own "Paid in" labels, since that's legitimately describing a remittance due date, not an entry gate.

### 3.8 Superadmin bypass

Consistent with every other payment gate in the app (402 download gate, trial system, billing mode), superadmins bypass all of the above — they can create any year, enter any month, in any order, regardless of payment status.

## 4. Enforcement points (implementation surface)

- `POST /api/years` — add chronological-next-year check (3.2).
- `POST /api/years/bulk` — superadmin-only (3.4).
- `POST /api/years/{key}/wages` and `POST /api/years/{key}/wages/bulk_month` — add the "prior months/years paid, unless month already has data" check (3.2 + 3.3).
- New shared helper, e.g. `get_next_required_unlock(db, est_obj, project) -> Optional[(year_key, month_idx)]`, used by all three endpoints above plus surfaced via a new read-only status endpoint the frontend can call to render lock state in the UI (which months/years to show as locked, and what the "add previous year" flow should offer).
- Frontend: Monthly Wage Entry needs to gray out/disable locked months, wire in payment prompts, and drop the year picker back to "current year only" by default with a separate "Add Previous Year" entry point for the month-wise/year-wise backfill choice (3.5).

## 5. Explicitly out of scope for this spec

- Tiered base-fee billing (separate proposal, [[project_tiered_base_fee_pricing_proposal]]).
- Auto-recurring billing / stored payment methods (Cashfree e-mandate/UPI Autopay) — the existing manual pay-per-month-link flow, plus the already-working advance-credit auto-debit, is sufficient for this design.
- Annual-plan discount framing — can be layered on later without changing this gating mechanism, since "advance-pay a whole year" already falls naturally out of 3.2.

## 6. Open questions for review

1. Confirm the grandfathering rule in 3.3 (skip the check if the month already has any wage data) is the right boundary — or should it be date-based (e.g., only establishments/years created after a specific ship date are gated at all)?
2. Confirm year creation gating (3.2, year-creation rule) should block out-of-order year creation even for an establishment's very first year if, hypothetically, `coverage_date` implies an earlier year should exist first — i.e., does the first `POST /api/years` call always have to be exactly the coverage-date year, with no flexibility?
3. Confirm no persisted "declaration" flag is wanted (3.1) — purely a one-time UI modal, no backend behavior change from it.
