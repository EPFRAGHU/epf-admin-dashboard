# Partner / Reseller Program — design

Date: 2026-09-10
Status: **prototype built and reviewed; not implemented.** No code, schema, auth,
or payout logic exists yet. This document is the spec; the interactive prototype
(owner + reseller dashboards, sample data, no backend) is at
`https://claude.ai/code/artifact/4c6e31e3-9fa6-4c90-8395-24302ba66157`.

## Why

The owner (superadmin of `epf-dashboard.xyz`) wants to grow the establishment base
through a network of friends ("resellers" / "partners") who sell the software to
employers and consultants. Each reseller keeps **50% of every subscription payment**
their referrals make, for as long as that referral stays subscribed. The owner keeps
the other 50%. Payouts run monthly to the reseller's UPI.

The whole program hinges on **transparency**: a reseller must be able to see every
establishment they referred, every ECR that establishment files, and every rupee
collected against their referrals — the exact figures the owner sees. Nothing hidden
on either side.

## Roles

Extends the existing `User.role` set (`superadmin` / `consultant` / `employer` — see
`webapp/database.py`) with one new value:

| Role | Sees | Auth dependency |
|---|---|---|
| `superadmin` (the owner) | Every reseller, every referred establishment, all ECR activity, all subscription revenue, all payout runs. This is a **new section inside the existing admin dashboard** (`webapp/js/admin.js`), superadmin-gated — NOT a separate site. | existing `get_superadmin` |
| `reseller` (new) | Only their own referrals — establishments, ECR filings, subscription amounts, their 50% share, payout history, enrollment tools. | new `get_reseller`, modelled on `get_superadmin` |
| `employer` / `consultant` | Their own establishment(s), exactly as today. A reseller-referred establishment is a **normal establishment** — the employer/consultant works it with no visible difference. | existing `get_active_establishment` |

Login is the **same** `epf-dashboard.xyz` login page, same email+password / Google,
same JWT (`webapp/auth.py`). `role == 'reseller'` routes to the reseller dashboard
instead of the consultant one. The prototype's "Viewing as" toggle is only a review
convenience — in production these are role-gated views of one app.

## Data model changes

1. **`User.role`** — add `'reseller'` as a valid value. Reseller users also need
   payout fields: `upi_id` (String), and KYC fields for TDS (`pan`, name as per PAN).
   Could live on `User` or a new `ResellerProfile` table (1:1) — the latter keeps
   `User` clean and matches the `SignupRequest` pattern.

2. **`Establishment.referred_by_reseller_id`** — nullable FK → `users.id`, indexed.
   Set once at creation, never by the employer. This single column drives every
   reseller/owner dashboard query (filter establishments by it, then roll up
   subscription fees / ECR activity from existing data). Needs an explicit
   `ALTER TABLE ... ADD COLUMN` in `_run_startup_migrations()` (per CLAUDE.md's
   Postgres-DDL rule — `create_all()` alone won't add it to prod).

3. **`Enrollment`** (new table) — tracks a referral from first touch to Active, for
   the "Pending enrollments" pipeline:
   - `reseller_id` FK, `establishment_id` FK (null until the establishment row exists),
     `method` (`'referral_link'` | `'invite'` | `'create_handover'`),
     `contact_name`, `contact_mobile`, `contact_email`,
     `stage` (see pipeline below), `set_password_token` + `token_expires_at`,
     `created_at`, `activated_at`.

4. **`ResellerPayout`** (new table) — one row per reseller per month:
   - `reseller_id` FK, `period` (e.g. `'2026-09'`), `gross_collected` (₹),
     `owner_share` (₹), `reseller_share` (₹), `upi_id`, `upi_reference` (UTR),
     `status` (`'scheduled'` | `'paid'` | `'failed'` | `'retrying'`),
     `run_at`, `paid_at`.
   - Optionally a `ResellerPayoutLine` child table (one per establishment per period)
     to back the per-establishment breakdown screen — or compute it on read from
     `SubscriptionFee` rows filtered by `referred_by_reseller_id`.

**Reuse, do not reinvent:** `Establishment.custom_rate_per_employee`,
`Establishment.billing_mode` (`'per_employee'` | `'flat_fee'`),
`Establishment.flat_fee_amount` already exist — the pricing model below maps straight
onto them. `SubscriptionFee` rows are already generated monthly per establishment
(`sync_subscription_fees_for_year`) — reseller earnings are a rollup of those, not a
new billing calculation.

## Pricing model

Set on the establishment at enrollment (and editable by the reseller / owner later,
subject to whatever price-band policy is chosen — see open decisions).

**Flat plan fee** (`billing_mode = 'flat_fee'`, `flat_fee_amount` set):

| Plan | Fee / month |
|---|---|
| Starter | ₹1,000 |
| Growth | ₹2,000 |
| Pro | ₹5,000 |
| Enterprise | custom amount, reseller enters it |

A reseller can also **override the flat fee** for a larger establishment on any plan
(the prototype's "Custom monthly amount" field).

**Per-employee** (`billing_mode = 'per_employee'`, `custom_rate_per_employee` set):

- Available on **Growth / Pro / Enterprise only — NOT Starter**.
- Rate: ₹10 / 20 / 30 / 40 / 50 / 60 / 70 / 80 / 90 / 100 per employee per month.
- **Enterprise** additionally allows a fully **custom per-employee rate** outside that
  band (e.g. ₹8 for a very large client, ₹150 for a small specialised one).
- The monthly fee = rate × the headcount in that month's ECR, so it moves up and down
  with the establishment automatically. This is exactly what `custom_rate_per_employee`
  + the existing per-employee `SubscriptionFee` derivation already do.

The owner and reseller dashboards both isolate per-employee referrals in their own
panel/summary, because their amounts change month to month while flat ones don't.

## Revenue split & payout

- **50 : 50** of gross collected, every month, per referral, for as long as the
  referral stays subscribed. (Split on gross vs net-of-gateway-fees/GST/TDS is an open
  decision — see below.)
- A **monthly payout run** at **00:30 on the 1st**, for the *previous* month's
  collections. Owner keeps 50%; each reseller's 50% goes to their registered UPI.
- Per reseller: total last month's `SubscriptionFee` (paid) for establishments where
  `referred_by_reseller_id == reseller.id` → halve → create/settle a `ResellerPayout`
  row → call a UPI payout API (**RazorpayX Payouts** or **Cashfree Payouts**).
- A failed transfer holds that row at `retrying` / `failed` and notifies; the other
  rows still go out; the amount is never lost.
- Pending / churned establishments contribute **nothing**: an establishment only
  counts once its **first invoice is paid** (moves to `Active`); a churned one stops
  contributing from the month it lapses, but the reseller keeps everything already
  paid.

## Enrollment flows

Three ways a referral is attributed to a reseller, all from the logged-in reseller's
dashboard:

1. **Referral link** — `epf-dashboard.xyz/r/<code>`, permanent per reseller. Anyone who
   signs up through it is auto-tagged (`referred_by_reseller_id` set from the code).
   For self-serve.

2. **Send an invite** — reseller enters the establishment name, type, contact
   mobile/email, optional plan. System sends a signup link tagged with the reseller id.
   The employer/consultant completes signup, KYC and the first payment themselves.

3. **Create the account** (the main flow the owner wants) — reseller fills the full
   form (name, EPF code, coverage date, contact, **billing**) sitting with the client.
   System creates:
   - the `Establishment` row, with `referred_by_reseller_id` set and the chosen
     `billing_mode` / rate / fee, and
   - an `employer` (or `consultant`) `User` row using the contact email/mobile, **with
     no password**.
   Then it emails + SMSes a **one-time set-password link** (7-day expiry). The employer
   opens it and sets **their own** password, or signs in with **Google** on that email.
   **The reseller never sees or sets the password.** This is the existing
   establishment-creation + existing signup/set-password mechanics, initiated by a
   reseller and stamped with the reseller id.

### Pending pipeline stages (`Enrollment.stage`)

- create/handover: `account_created` → `password_set` → `awaiting_first_payment` → `active`
- invite: `invite_sent` → `awaiting_signup` → `awaiting_first_payment` → `active`
- referral link: `signed_up_via_link` → (`adding_establishments`, for a consultant) → `awaiting_first_payment` → `active`

A set-password link expires in 7 days and can be resent from the pending row. An
invite never completed drops off after 30 days. An enrollment only earns once it
reaches `active`.

## Dashboards (what the prototype shows)

### Owner (superadmin) — a "Referral Program" section in the admin dashboard

- **Overview** — stat tiles (active resellers, referral count, collected this month
  split flat vs per-employee, owner 50%, payouts due, next run date), a resellers
  summary table (UPI, employer/consultant counts, collected, your 50 / their 50,
  payout status), this month's ECR-activity feed, and the upcoming payout run.
- **Resellers** — full list (joined, referrals, active, MRR, paid to date) + drill
  into one reseller's referrals.
- **Establishments** — every referred account (type, referred-by, billing, fee,
  status, latest ECR, joined); a dedicated **Per-employee referrals** panel isolating
  the per-employee-billed ones with rate × headcount → fee → owner 50%; and a
  **Pending enrollments — all resellers** pipeline.
- **ECR Activity** — which referred establishment entered how many employees, for
  which wage month, when filed; current + previous month.
- **Payouts** — upcoming run + completed runs with per-reseller lines and UTR
  references.
- **Design notes** — the open-decisions list (mirrors this spec's section below).

### Reseller — their own scoped view

- **My overview** — transparency banner, stat tiles (my establishments, collected,
  my 50%, next payout to my UPI, paid to date), my establishments, my earnings this
  month, and a **Billing mix** panel (flat vs per-employee split, and which line moves
  with headcount).
- **Enroll establishment** — the referral link (copyable) + the "Create the account"
  form (billing selector: flat plan / per-employee, with the pricing options above)
  and its "what happens next" confirmation (set-password link sent, 7-day expiry, no
  password set by reseller) + the pending-enrollments pipeline.
- **My establishments** — full detail per referral, expandable to the employee-level
  ECR rows the establishment entered for a given month (read-only — only the
  establishment can edit its own wage data).
- **ECR activity** — every filing by their referrals, newest first.
- **My earnings** — month-by-month roll-up **and** a per-establishment / per-payout-
  batch breakdown (each month's payout = the sum of its establishment lines; a
  per-employee line shows rate × that month's ECR headcount so the reseller sees why
  an amount moved).
- **Payout history** — every UPI transfer with UTR, and a plain-language "how it
  works" note.

## Ownership / security

Every reseller-scoped endpoint must check "is this establishment referred by this
reseller" — mirroring the existing `est.user_id != current_user.id` pattern in
`webapp/auth.py` and the inline `current_user.role != "superadmin"` checks in
`webapp/app.py`. A reseller must never be able to read another reseller's data or any
establishment they didn't refer, and never edit an establishment's wage data at all.

## What is explicitly NOT in scope for v1

- The `₹75/month non-functional-establishment` admin-charge floor (unrelated EPF
  statutory item, separately deferred — see
  `.claude/.../memory/project_deferred_tasks.md`).
- Multi-currency, non-UPI payouts.
- A reseller editing establishment wage/ECR data.

## Open decisions (must be settled before implementation)

1. **Attribution** — allow all three enrollment paths, or only "create the account"?
   Can an establishment be re-assigned to a different reseller later? Can a reseller
   enroll their own establishment?
2. **Split base** — 50% of gross collected, or of net after payment-gateway fees / GST
   / TDS? Does the 50% apply to a custom/overridden price the reseller themselves set?
3. **Price control** — can a reseller set any price, or only within a band the owner
   fixes per plan?
4. **Part-months & edge cases** — first-month proration, refunds, a client who pays
   late, a client who churns mid-month — how each affects the reseller's 50%.
5. **Multi-level** — if a reseller's referred *consultant* brings 20 establishments,
   does the reseller earn on all 20, and at what rate?
6. **Payout mechanics** — which UPI payout API; minimum payout threshold; failure &
   retry policy; TDS deduction and Form 16A / quarterly filing for reseller income;
   monthly statement to the reseller.
7. **Reseller onboarding** — superadmin-created vs a signup+approval queue; KYC / PAN
   collection; UPI verification (penny-drop); a signed agreement.
8. **Employer login after reseller-create** — set-password link expiry window; whether
   the reseller keeps temporary co-access to help enter the first ECR; whether the
   contact email/mobile can be changed later without re-verifying.

## Implementation order (rough)

1. `reseller` role + `get_reseller` + `Establishment.referred_by_reseller_id` column
   & migration. No behaviour change yet — just the plumbing.
2. Enrollment: the "create the account" backend (establishment + no-password user +
   set-password token + email/SMS), stamped with the reseller id. Reuse existing
   establishment-create and signup/set-password code.
3. Reseller dashboard read views — all are `SubscriptionFee` / ECR / establishment
   rollups filtered by `referred_by_reseller_id`. No new billing math.
4. `ResellerPayout` table + the monthly cron that computes 50:50 and writes
   `scheduled` rows. Owner "Payouts" screen reads these.
5. UPI payout API integration — the actual transfer + UTR capture + retry.
6. Owner "Referral Program" admin section.
7. Referral link + invite enrollment paths.
8. TDS handling.
