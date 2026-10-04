# Consultant Monthly Plan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A consultant pays one flat monthly amount (set per consultant by the superadmin, e.g. Rs 2,000) in advance for unlimited use of all his establishments; while a paid month is active, his per-establishment subscription fee rows are waived.

**Architecture:** A pure month-math module plus one new table (`consultant_plan_payments`) and one new `users` column. `sync_subscription_fees_for_year()` marks wage-bearing unpaid fee rows paid at Rs 0 while the plan is active, so every existing download/"add year"/402 gate keeps working unchanged. Payment reuses the existing Cashfree link/webhook (`plan_` order prefix) and UPI+UTR verification queue (`plan-N` ids).

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy (SQLite tests / Postgres prod), vanilla JS SPA, pytest.

**Spec:** `docs/superpowers/specs/2026-10-04-consultant-monthly-plan-design.md`

## Global Constraints

- NEVER run `git push`, ever, in any task (production auto-deploys on push; an implementer once broke live production this way). Commit locally only.
- Every commit message ends with the line `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` verbatim. In PowerShell, do not put literal double quotes inside the `-m` message.
- Never touch production data/DB. Tests use the isolated SQLite `test_epf.db`; any manual run overrides `DATABASE_URL` to a scratch copy of `local_dev.db` first.
- Billing for any consultant without `consultant_plan_amount` must stay byte-identical to today.
- Calendar month = `YYYY-MM` in IST (fixed UTC+5:30), never the server's local date.
- Plan months per purchase: integer 1..24 (`MAX_PLAN_MONTHS = 24`). Amount = `months x consultant_plan_amount`, computed server-side; the client never sends an amount.
- `payment_status`/ledger-style status values: `pending`, `confirmed`, `manual`, `pending_verification`, `rejected`. Only `confirmed` and `manual` rows grant coverage.
- Fee-row waiver text: `payment_reference = "Covered by consultant plan"`, `billing_mode = "consultant_plan"`, `amount_due = 0`.
- New DB column/table need explicit DDL in `_run_startup_migrations()` for both Postgres and SQLite paths (`create_all` does not add columns).
- Composite string ids (`plan-12`) must stay quoted inside `onclick` attributes.
- Windows/PowerShell: variables do not persist between tool calls; no `&&`; use `python -m pytest`.

## Review Focus

- Plan amount cleared to NULL while old confirmed payments exist: plan is NOT active, billing is as today. (Task 2, Task 3)
- Duplicate/retried Cashfree webhook or double approval: coverage and balance allocated exactly once. (Task 2, Task 4, Task 5)
- `months` of 0, -1, 25, a string, or a client-supplied `amount`: rejected / ignored, amount is always server-computed. (Task 4)
- Month rollover: coverage ends with the last covered IST month; a payment confirmed at 23:30 UTC on the 30th (already the 1st in IST) starts in the IST month. (Task 1)
- Fee rows with no wage data are not waived; rows waived earlier stay paid after the plan lapses; a rejected or pending UTR grants nothing. (Task 3, Task 5)

---

### Task 1: Pure month/coverage logic

**Files:**
- Create: `webapp/consultant_plan.py`
- Test: `webapp/tests/test_consultant_plan_logic.py`

**Interfaces:**
- Produces (all in `webapp/consultant_plan.py`):
  - `MAX_PLAN_MONTHS = 24`, `IST = timezone(timedelta(hours=5, minutes=30))`
  - `current_month_ist(now: Optional[datetime] = None) -> str` -- `'YYYY-MM'`; `now` (tz-aware or naive-UTC) defaults to `datetime.now(timezone.utc)`; converts to IST.
  - `add_months(ym: str, n: int) -> str`
  - `compute_coverage(current_ym: str, latest_covered_to: Optional[str], months: int) -> Tuple[str, str]` -- `start = max(current_ym, add_months(latest_covered_to, 1))` (just `current_ym` when `latest_covered_to` is None); returns `(start, add_months(start, months - 1))`.
  - `covers(ym: str, windows: Iterable[Tuple[str, str]]) -> bool` -- true if any `from <= ym <= to` (string compare is valid for `YYYY-MM`).
  - `validate_months(months) -> int` -- accepts int (not bool) in 1..24 else raises `ValueError`.

- [ ] **Step 1: Write failing tests** in `test_consultant_plan_logic.py`:
  `test_current_month_ist_rolls_over_at_ist_midnight` (`datetime(2026,10,31,19,0,tzinfo=utc)` -> `'2026-11'`; `datetime(2026,10,31,18,29,tzinfo=utc)` -> `'2026-10'`);
  `test_add_months_crosses_year` (`add_months('2026-11', 3) == '2027-02'`, `add_months('2026-12', 0) == '2026-12'`);
  `test_compute_coverage_fresh_starts_current_month` (`compute_coverage('2026-10', None, 6) == ('2026-10','2027-03')`);
  `test_compute_coverage_extends_after_latest` (`compute_coverage('2026-10', '2026-12', 2) == ('2027-01','2027-02')`);
  `test_compute_coverage_lapsed_restarts_at_current` (`compute_coverage('2026-10', '2026-05', 1) == ('2026-10','2026-10')`);
  `test_covers_inclusive_bounds` (window `('2026-10','2026-12')` covers `'2026-10'` and `'2026-12'`, not `'2026-09'`/`'2027-01'`);
  `test_validate_months_rejects_bad_values` (0, -1, 25, `'3'`, `True`, `2.5` raise `ValueError`; 1, 24 pass).
- [ ] **Step 2: Run** `python -m pytest webapp/tests/test_consultant_plan_logic.py -q` -- expect ImportError/FAIL.
- [ ] **Step 3: Implement** the module with the signatures above (`datetime.timezone`, plain int math on year*12+month).
- [ ] **Step 4: Run** the same command -- expect all pass.
- [ ] **Step 5: Commit** `git add webapp/consultant_plan.py webapp/tests/test_consultant_plan_logic.py` then `git commit -m 'feat(plan): month and coverage logic'` plus the Co-Authored-By trailer.

### Task 2: Data model, migration, activity check, confirmation

**Files:**
- Modify: `webapp/database.py` (add `User.consultant_plan_amount`; add `ConsultantPlanPayment`)
- Modify: `webapp/app.py` (migrations in `_run_startup_migrations()` near the `advance_credit_ledger` DDL at ~L660; helpers beside `apply_advance_credit_if_available` ~L351; import the new module)
- Test: `webapp/tests/test_consultant_plan_core.py`

**Interfaces:**
- Consumes: `compute_coverage`, `covers`, `current_month_ist` from Task 1.
- Produces:
  - `User.consultant_plan_amount = Column(Float, nullable=True)`
  - `class ConsultantPlanPayment(Base)`, table `consultant_plan_payments`: `id`, `user_id` (FK users.id, ondelete CASCADE, indexed), `months` Integer not null, `amount` Float not null, `status` String(20) not null default `'pending'`, `covered_from`/`covered_to` String(7) null, `cashfree_order_id` String(120) indexed null, `cashfree_payment_link_url` Text, `cashfree_payment_session_id` Text, `payment_reference` String(255), `notes` Text, `submitted_utr` String(255), `submitted_by`/`verified_by` Integer FK users.id SET NULL, `submitted_at`/`verified_at` DateTime(timezone=True), `rejection_reason` Text, `created_at` DateTime(timezone=True) server_default now.
  - `app.py`: `is_consultant_plan_active(db: Session, user_id: Optional[int], now: Optional[datetime] = None) -> bool` (False when user missing, `consultant_plan_amount` is NULL, or no confirmed/manual window covers `current_month_ist(now)`);
    `_confirm_plan_payment(db: Session, row: ConsultantPlanPayment, payment_ref: str, source: str = "cashfree", verified_by: Optional[int] = None, now: Optional[datetime] = None) -> None` -- idempotent (no-op if status already `confirmed`/`manual`); sets `status='confirmed'`, `payment_reference`, allocates `covered_from/covered_to` via `compute_coverage` using the max `covered_to` of this user's other confirmed/manual rows, commits, calls `log_activity(..., "plan_payment_confirmed", ...)`.
    `_plan_payment_amount(user: User, months: int) -> float` -- `round(months * user.consultant_plan_amount, 2)`.
    `PLAN_COVERED_REFERENCE = "Covered by consultant plan"`.

- [ ] **Step 1: Write failing tests** in `test_consultant_plan_core.py` (use `test_db`, create `User`/`ConsultantPlanPayment` rows directly): `test_inactive_without_plan_amount_even_with_old_payments`; `test_manual_payment_covers_current_month_only` (`now` fixed in Oct 2026, 1 month); `test_back_to_back_purchases_extend_not_overlap` (6 months then 3 months -> second starts month after first's end); `test_confirm_is_idempotent` (calling twice leaves `covered_from/to` unchanged and one activity log); `test_pending_and_rejected_rows_grant_nothing`; `test_lapsed_window_not_active_next_month`.
- [ ] **Step 2: Run** `python -m pytest webapp/tests/test_consultant_plan_core.py -q` -- expect FAIL (names undefined).
- [ ] **Step 3: Implement** the model/column; add Postgres DDL (`ALTER TABLE users ADD COLUMN IF NOT EXISTS consultant_plan_amount FLOAT;`, `CREATE TABLE IF NOT EXISTS consultant_plan_payments (...)` with the columns above) and the SQLite equivalents in the same try-each style the file already uses (`_try_ddl`); then the three helpers and the constant.
- [ ] **Step 4: Run** the file -- expect pass. Also run `python -m pytest webapp/tests/test_billing_mode.py -q` to confirm no regression.
- [ ] **Step 5: Commit** `feat(plan): consultant plan table and confirmation`.

### Task 3: Fee waiver in billing sync

**Files:**
- Modify: `webapp/app.py` -- `sync_subscription_fees_for_year()` (~L388-468)
- Test: `webapp/tests/test_consultant_plan_billing.py`

**Interfaces:**
- Consumes: `is_consultant_plan_active`, `PLAN_COVERED_REFERENCE` (Task 2).
- Produces: behaviour only -- during an active plan every unpaid fee row with `emp_count > 0` (new row, existing unpaid row, or a previously 0-due placeholder) becomes `is_paid=True`, `payment_status='paid'`, `amount_due=0`, `billing_mode='consultant_plan'`, `payment_reference=PLAN_COVERED_REFERENCE`, `paid_date` today. Rows with `emp_count == 0` untouched. Already-paid rows never rewritten (their `employee_count` refresh stays). Advance credit is not consumed for waived rows. Resolve `plan_active` once per call from `est_obj.user_id`.

- [ ] **Step 1: Write failing tests** (API-level using `consultant_a`, `superadmin_session`, `test_db`; create plan payment via `ConsultantPlanPayment(status='manual', ...)` + `_confirm_plan_payment`, or set `covered_from/to` directly around today's IST month): `test_no_plan_billing_unchanged` (rate-billed row stays unpaid with amount > 0); `test_active_plan_waives_wage_rows_across_two_establishments` (two establishments, wages entered, both months paid at 0, `GET .../subscription-fees` shows reference text, a Form 3A download returns 200 not 402); `test_rows_without_wages_not_waived`; `test_previously_unpaid_rows_waived_on_next_sync`; `test_lapse_keeps_waived_rows_paid_and_bills_new_rows` (move `now`/coverage window into the past, new wage month bills normally); `test_other_consultant_unaffected` (consultant_b still billed); `test_advance_credit_not_consumed_when_waived`; `test_plan_amount_null_with_old_payment_bills_normally`.
- [ ] **Step 2: Run** `python -m pytest webapp/tests/test_consultant_plan_billing.py -q` -- expect FAIL.
- [ ] **Step 3: Implement** the waiver inside the existing new-row and unpaid-row branches of `sync_subscription_fees_for_year` via a small local helper `_waive_for_plan(fee_row)`; keep `apply_advance_credit_if_available` for the non-plan path only. Leave the paid-row branch as is (it already ignores unknown `billing_mode`s except `per_employee`).
- [ ] **Step 4: Run** the file, then `python -m pytest webapp/tests/test_subscription_fee.py webapp/tests/test_billing_mode.py webapp/tests/test_pay_all_overdue.py -q` -- all pass.
- [ ] **Step 5: Commit** `feat(plan): waive establishment fees while plan active`.

### Task 4: Consultant API, Cashfree and UTR paths

**Files:**
- Modify: `webapp/app.py` (new endpoints near the advance-credit ones ~L4737; `_route_cashfree_confirmation` ~L3526; `_utr_already_submitted` ~L2866)
- Test: `webapp/tests/test_consultant_plan_api.py`

**Interfaces:**
- Consumes: Task 2 helpers; `cashfree_client.create_payment_link_or_order(link_id, amount, purpose, customer_phone, customer_name, customer_email, return_url) -> {"link_url", "payment_session_id", ...}`, `cashfree_client.new_order_id("plan", user_id)`, `cashfree_client.get_payment_status(order_id)` (read how `establishment_refresh_advance_credit_status` ~L4790 uses it and mirror it).
- Produces (all `Depends(get_current_user)`; consultant/employer act on their own account only):
  - `GET /api/my-plan` -> `{"plan_amount": float|None, "active": bool, "covered_through": "YYYY-MM"|None, "payments": [{"id","months","amount","status","covered_from","covered_to","created_at"}...]}`
  - `POST /api/my-plan/create-link` body `PlanMonthsIn(months: int)` -> `{"ok": True, "link_url", "order_id"}`; 400 if no plan amount, no mobile, or invalid months; creates a `pending` row with order id `plan_<user_id>_<ts>` and server-computed `amount`.
  - `POST /api/my-plan/submit-utr` body `PlanUtrIn(months: int, utr: str)` -> creates `pending_verification` row; 400 on empty/duplicate UTR; `_utr_already_submitted` also checks `ConsultantPlanPayment.submitted_utr`.
  - `POST /api/my-plan/refresh-status` body `PlanRefreshIn(order_id: str)`.
  - `_route_cashfree_confirmation`: new `order_id.startswith("plan_")` branch -> look up rows by `cashfree_order_id`, `_confirm_plan_payment(..., source="cashfree")` each.
  - Pydantic models `PlanMonthsIn`, `PlanUtrIn`, `PlanRefreshIn` (none has an `amount` field).

- [ ] **Step 1: Write failing tests** (monkeypatch `webapp.app.cashfree_client.create_payment_link_or_order` to return `{"link_url": "https://x/pay", "payment_session_id": "s1"}` and `webapp.app.cashfree_client.verify_webhook_signature` to `lambda *a, **k: True`; fire webhooks with the payload shape of `fire_webhook` in `test_cashfree_integration.py`): `test_my_plan_without_amount_is_inactive_and_link_rejected`; `test_create_link_computes_amount_server_side` (superadmin sets 2000; months=6 -> row amount 12000; extra `"amount": 1` in the body is ignored); `test_months_validation` (0, -1, 25, `"3"` -> 422 or 400); `test_webhook_confirms_once_and_activates_plan` (second webhook leaves coverage unchanged; `GET /api/my-plan` shows `active` true and the right `covered_through`); `test_submit_utr_pending_grants_nothing_until_approved` (approval is Task 5; here only assert status and `active` false); `test_duplicate_utr_rejected_across_tables`; `test_create_link_needs_mobile`; `test_other_user_cannot_see_my_plan_rows`.
- [ ] **Step 2: Run** `python -m pytest webapp/tests/test_consultant_plan_api.py -q` -- expect FAIL.
- [ ] **Step 3: Implement** the endpoints and routing branch; reuse `_cashfree_shareable_url`, `_app_base_url`, `require_feature_enabled(db, "cashfree_payments_enabled", ...)` exactly as `consultant_create_advance_payment_link` does.
- [ ] **Step 4: Run** the file plus `python -m pytest webapp/tests/test_cashfree_orders_fallback.py webapp/tests/test_pay_all_overdue.py -q`.
- [ ] **Step 5: Commit** `feat(plan): consultant plan payment API`.

### Task 5: Superadmin API and verification queue

**Files:**
- Modify: `webapp/app.py` (admin endpoints beside `admin_set_consultant_default_billing` ~L1876; `_split_verification_id`, `payment_verifications`, `approve_payment`, `reject_payment` ~L2932-3187)
- Test: `webapp/tests/test_consultant_plan_admin.py`

**Interfaces:**
- Consumes: Task 2/4 helpers and models.
- Produces (all `Depends(get_superadmin)`):
  - `PUT /api/admin/users/{user_id}/consultant-plan` body `PlanAmountIn(amount: Optional[float])` -- consultants only (400 otherwise), `amount` must be `> 0` or null (clears); logs activity `consultant_plan_changed`; returns `{"ok": True, "consultant_plan_amount": ...}`.
  - `POST /api/admin/users/{user_id}/plan-payment` body `PlanManualPaymentIn(months: int, reference: str)` -> `manual` row confirmed immediately via `_confirm_plan_payment`.
  - `GET /api/admin/users/{user_id}/plan` -> same shape as `GET /api/my-plan`.
  - `_split_verification_id` accepts `plan-N` -> `("plan", N)`.
  - Queue items for plan rows: `id=f"plan-{r.id}"`, `source="consultant_plan"`, `establishment_name=<consultant name>`, `establishment_code="CONSULTANT PLAN"`, `display_name=f"Monthly Plan - {months} month(s)"`, `amount_due=r.amount`, `payment_status` via `_LEDGER_STATUS_DISPLAY`, UTR/submitted/verified fields as the ledger items; `financial_year`/`month` None. Status filters (`pending_verification`/`paid`/`unpaid`) apply to plan rows like ledger rows (`confirmed`+`manual` count as paid).
  - Approve: only `pending_verification`; sets `verified_by`/`verified_at`, `_confirm_plan_payment(..., source="manual_utr")`. Reject: needs non-empty reason, sets `rejected`, never grants coverage.
- Also consider: `GET /api/admin/users/{id}` payload and the consultants list already return per-user fields -- add `consultant_plan_amount` to the dict built near ~L2175 so the admin UI can show it.

- [ ] **Step 1: Write failing tests**: `test_only_superadmin_can_set_plan_amount` (consultant gets 403; employer/superadmin target gets 400); `test_set_and_clear_plan_amount`; `test_manual_payment_activates_plan_and_unlocks_billing` (end-to-end with a wage-bearing establishment from Task 3 style); `test_queue_lists_plan_utr_and_approve_activates` (consultant submits via `/api/my-plan/submit-utr`, superadmin sees `plan-N`, approves, `GET /api/my-plan` active; approving twice -> 400; coverage allocated once); `test_reject_requires_reason_and_grants_nothing`; `test_verification_id_forms_still_work` (`fee-N`, `adv-N`, bare digits).
- [ ] **Step 2: Run** `python -m pytest webapp/tests/test_consultant_plan_admin.py -q` -- expect FAIL.
- [ ] **Step 3: Implement** endpoints and queue/approve/reject branches.
- [ ] **Step 4: Run** the file plus `python -m pytest webapp/tests/test_cline_utr_audit.py -q` if it exists (`Glob webapp/tests/*utr*`) and `python -m pytest webapp/tests -q -k "verification or utr"`.
- [ ] **Step 5: Commit** `feat(plan): superadmin plan controls and verification queue`.

### Task 6: Consultant "My Plan" card

**Files:**
- Modify: `webapp/js/my-establishments.js` (render a card above the establishment cards when `GET /api/my-plan` returns `plan_amount != null`; export new handlers in the module's return object ~L408)
- Modify: `webapp/js/app.js` (add `showPlanUPIPanel(months, amount)` + `submitPlanUTR(months)` modeled on `showAdvanceUPIPanel`/`submitAdvanceUTR` ~L347-420; export them ~L1490; the UTR POST goes to `/api/my-plan/submit-utr` with `{months, utr}`)
- No new test file (JS); verified in Task 8.

**Interfaces:**
- Consumes: Task 4 endpoints. Months selector options 1/3/6/12 showing `months x plan_amount`; "Pay with Cashfree" calls `POST /api/my-plan/create-link` and opens `link_url` like the advance flow does; "Pay via UPI" opens `App.showPlanUPIPanel(months, total)`; the card shows "Active - paid through <Mon YYYY>" or "Not active", and the last few payments with status badges.
- Produces: `MyEstablishments.payPlanCashfree(months)`, `MyEstablishments.openPlanUPIPanel()` (names used by the card's onclicks).

- [ ] **Step 1: Implement** the card and handlers, escaping every interpolated value with `App.esc`, quoting string args in `onclick`.
- [ ] **Step 2: Syntax-check** both files: `node --check webapp/js/my-establishments.js` and `node --check webapp/js/app.js` -- no output means pass.
- [ ] **Step 3: Commit** `feat(plan): consultant My Plan card`.

### Task 7: Superadmin UI

**Files:**
- Modify: `webapp/js/admin.js` (consultant edit modal ~L1640-1730: add a "Monthly plan" amount input + Save/Clear using `PUT /api/admin/users/{id}/consultant-plan`, a "Record payment" action calling `POST /api/admin/users/{id}/plan-payment`, and a small plan-history list from `GET /api/admin/users/{id}/plan`; the payment-verification table ~L959 needs no change because plan items reuse its fields and quoted ids)
- No new test file; verified in Task 8.

**Interfaces:**
- Consumes: Task 5 endpoints and the `consultant_plan_amount` field on the consultant payload.

- [ ] **Step 1: Implement** the modal section (only for role `consultant`), with `App.esc` on all values and a confirm before recording a payment.
- [ ] **Step 2: Syntax-check** `node --check webapp/js/admin.js`.
- [ ] **Step 3: Commit** `feat(plan): superadmin plan controls UI`.

### Task 8: End-to-end verification and regression

**Files:** none modified unless a bug is found (then fix with a test in the owning task's test file).

- [ ] **Step 1: Full suite** `python -m pytest webapp/tests -q` -- expect all pass (baseline was 285 passed before this plan).
- [ ] **Step 2: Live click-through on a scratch DB** (never production): copy `local_dev.db` (old schema, so the startup migration is exercised) to a temp file, set `DATABASE_URL` to it, start `uvicorn webapp.app:app --port <free>`, log in via the Browser tools as a test consultant and as superadmin (set a known test password via a one-off Python call to `hash_password`, field is `password_hash`). Verify: superadmin sets plan amount 2000 on the consultant; consultant sees the card "Not active"; two establishments with wages show unpaid/blocked; superadmin records a 1-month manual payment; card shows active; both establishments' downloads unlock; UTR submit appears in the verification queue as a `plan-N` item and approve/reject work. Cashfree itself cannot be reached from scratch: confirm the link button reports a clear error or is skipped, and rely on Task 4's mocked webhook test.
- [ ] **Step 3: Clean up** the scratch DB, logs and server process.
- [ ] **Step 4: Report** results to the user; do NOT commit a version bump or push. Deployment is a separate step the user must approve (traffic note, rollback hash, smoke test), as with the ceiling change.
