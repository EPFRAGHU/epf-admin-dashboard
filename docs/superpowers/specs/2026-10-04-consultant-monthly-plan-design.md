# Consultant Monthly Plan -- design

Date: 2026-10-04. Status: draft for review. Nothing in this document is built.

## 1. Goal

Let a consultant pay one flat amount per calendar month (e.g. Rs 2,000), in advance, for
unlimited use of every establishment he owns -- every financial year, back-years included --
instead of the per-establishment subscription fees. Payment goes into the Cashfree merchant
account the app already uses (or by UPI + UTR, verified by the superadmin).

Agreed with the product owner:
- Superadmin turns the plan on per consultant (same pattern as flat fee today).
- One payment covers a calendar month of access; paying N months ahead costs N x the amount
  (6 months = Rs 12,000).
- While the plan is active, per-establishment fees for his establishments are waived.
- Everyone else's billing is untouched.

Non-goals: partial months, proration, refunds/cancellation, plan tiers, reseller commission
on plan payments (see section 9), a monthly auto-debit job.

## 2. How billing works today (context)

- One `SubscriptionFee` row per establishment x financial year x month. Download gates
  (Forms, ECR, reports), the "add a year" gate and the 402 pay-prompt all read those rows via
  `sync_subscription_fees_for_year()` -> `get_unpaid_months_detail_for_year()` /
  `get_entry_lock_status()`.
- `apply_advance_credit_if_available()` already auto-marks a newly billed row paid from a
  per-establishment prepaid balance. The plan reuses this pattern.
- Cashfree orders are routed by id prefix (`sub_`, `adv_`) in `_route_cashfree_confirmation()`.
  UPI+UTR submissions go through the superadmin payment-verification queue.

## 3. Approach

Plan-covered fee rows. While a consultant's plan is active, `sync_subscription_fees_for_year()`
marks every unpaid fee row that has wage data as paid, amount 0, billing mode
`consultant_plan`, reference "Covered by consultant plan". All gates already trust paid rows,
so none of them change, and history stays paid after the plan lapses.

Rejected: bypassing the gate like a trial (rows stay unpaid and bill after lapse); a money
wallet with monthly deduction (needs a scheduler for the same result).

## 4. Data model

`users.consultant_plan_amount FLOAT NULL` -- monthly price. NULL = no plan (default, every
existing user). Settable only by superadmin; absent from every consultant-writable model.

New table `consultant_plan_payments`:

| column | notes |
|---|---|
| id, user_id (FK users, indexed, cascade) | the consultant |
| months INT | 1..24 |
| amount FLOAT | months x plan amount, computed server-side at creation |
| status | `pending` / `confirmed` / `manual` / `pending_verification` / `rejected` |
| covered_from, covered_to VARCHAR(7) | `YYYY-MM`, set on confirmation |
| cashfree_order_id (indexed), cashfree_payment_link_url, cashfree_payment_session_id | as AdvanceCreditLedger |
| payment_reference, notes | |
| submitted_utr, submitted_by, submitted_at, verified_by, verified_at, rejection_reason | UPI path, as AdvanceCreditLedger |
| created_at | |

Migration: explicit `ALTER TABLE users ADD COLUMN` and `CREATE TABLE` in
`_run_startup_migrations()` for both the Postgres and SQLite paths (create_all alone does not
add columns -- see feedback_postgres_ddl_migrations).

## 5. Behaviour

**Calendar month** = `YYYY-MM` of "now" in IST (fixed UTC+5:30 offset), not the server's
local date.

**Coverage on confirmation.** When a payment becomes confirmed/manual:
`start = max(current IST month, month after the latest covered_to among this user's confirmed
payments)`, `covered_from = start`, `covered_to = start + months - 1`. Allocating at
confirmation (not at purchase) means two simultaneous pending purchases cannot overlap or
double-cover. Confirmation is idempotent (a second webhook / refresh / approval is a no-op).

**Active** = some confirmed/manual payment with `covered_from <= current IST month <=
covered_to`. A plan amount of NULL means no plan, regardless of old payments.

**Fee waiver in sync.** `sync_subscription_fees_for_year()` resolves `plan_active` once per
call. For a row with wage data (`emp_count > 0`) that is new or unpaid and `plan_active`:
`is_paid=True`, `payment_status='paid'`, `amount_due=0`, `billing_mode='consultant_plan'`,
`payment_reference='Covered by consultant plan'`. Rows with no wage data stay 0-due
placeholders. Decision: unpaid rows owed from before the plan started are also waived when
synced during an active plan (the plan is access for the month); the alternative -- waive only
rows created while active -- is a one-line change if preferred. Already-paid rows are never
rewritten. Advance credit is not consumed for plan-covered rows.

**Lapse.** After `covered_to`, nothing is clawed back. Rows covered earlier stay paid. New
syncs bill per the establishment's normal resolved mode (per-employee / flat fee / trial).

**Interactions.** Trial establishments keep their trial. Superadmin bypass unchanged. A
consultant with a plan amount set but no active payment bills exactly as today.

## 6. API

Consultant (JWT, consultant/employer owner of the account):
- `GET /api/my-plan` -> `{plan_amount|null, active, covered_through, payments[]}`
- `POST /api/my-plan/create-link {months}` -> Cashfree link/order (needs mobile number, same
  feature flags as advance credit: `cashfree_payments_enabled`), order id `plan_<user>_<ts>`
- `POST /api/my-plan/submit-utr {months, utr}` -> `pending_verification` row; duplicate-UTR
  guard `_utr_already_submitted()` extended to this table
- `POST /api/my-plan/refresh-status {order_id}` -> polls Cashfree like the advance-credit one

Superadmin:
- `PUT /api/admin/users/{id}/consultant-plan {amount|null}` (consultants only, amount > 0)
- `POST /api/admin/users/{id}/plan-payment {months, reference}` -> status `manual`, confirmed
  immediately (cash / bank / direct UPI)
- `GET /api/admin/users/{id}/plan` -> amount, coverage, payment history
- Verification queue (`/api/admin/payment-verifications`): includes plan rows with composite id
  `plan-N`; approve/reject reuse the existing handlers (`_split_verification_id` gains a `plan`
  branch).

Webhook: `_route_cashfree_confirmation()` gains a `plan_` branch -> `_confirm_plan_payment()`.

The client never sends an amount; the server derives it from `months` and the stored plan
amount.

## 7. UI

- Consultant: "My Plan" card on the My Establishments page (only when `plan_amount` is set):
  status ("Active -- paid through Mar 2027" / "Not active"), monthly price, a months selector
  (1/3/6/12) showing the total, "Pay with Cashfree" and "Pay via UPI" (reuses the UPI panel),
  payment history.
- Superadmin: on the consultant row/detail, a "Monthly plan" field + "Record payment" button
  and plan history; plan items appear in the existing verification queue.
- JS gotcha to honour (project_advance_credit_upi_qr): composite string ids (`plan-12`) must be
  quoted in `onclick` attributes.

## 8. Testing

pytest (new `test_consultant_plan.py`): no plan -> billing unchanged; plan set but unpaid ->
unchanged; manual payment -> establishments' synced rows paid at 0 and downloads unlocked;
multi-month coverage windows and back-to-back purchases; lapse leaves covered rows paid and
bills new rows normally; Cashfree webhook confirms once (idempotent); UTR submit -> approve /
reject; amount cannot be tampered with; one consultant's plan never affects another's;
consultant cannot set the plan amount; existing billing/flat-fee/advance-credit tests stay
green. Then a live click-through on a scratch DB copy with Cashfree mocked (as the existing
Cashfree tests do) before any deploy. Never against production data.

## 9. Open items flagged, not in scope

- Reseller commission is computed from paid `SubscriptionFee` rows; plan payments are not
  `SubscriptionFee` rows, so they earn no reseller commission, and plan-covered rows (amount 0)
  earn none either. If a plan consultant was referred by a reseller, that needs a follow-up
  decision.
- Admin revenue/fee reports that sum `SubscriptionFee` will not include plan payments until a
  follow-up adds them.
- No auto-renewal or expiry reminder; the consultant tops up manually.
