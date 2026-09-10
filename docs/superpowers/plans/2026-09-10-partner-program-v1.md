# Partner / Reseller Program v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the v1 Partner/Reseller Program — a superadmin enrols resellers, a reseller creates establishment accounts that stay tagged to them, both sides see a transparent rollup of every referred establishment's ECR activity and subscription collections, and a monthly job computes each reseller's 50% (less TDS) into `scheduled` payout rows the owner settles by hand.

**Architecture:** Pure additive layer on the existing app. One new nullable FK (`Establishment.referred_by_reseller_id`) drives every reseller/owner query; earnings are a rollup of the existing `SubscriptionFee` rows, not a new billing calculation. One new role (`reseller`) with a `get_reseller` dependency mirroring `get_superadmin`. Three new tables (`ResellerProfile`, `Enrollment`, `ResellerPayout` + `ResellerPayoutLine`). Payouts are computed by a GitHub Actions cron calling a script (same pattern as the existing Neon→Supabase backup) and paid manually — no payout-API integration in v1. Frontend adds two vanilla-JS SPA modules (`reseller.js`, `referral-program.js`) registered as pages, gated by role.

**Tech Stack:** FastAPI (single-router `webapp/app.py`), SQLAlchemy (`webapp/database.py`), PyJWT auth (`webapp/auth.py`), `itsdangerous` (already a dependency) for set-password tokens, vanilla-JS SPA (`webapp/js/*.js`), pytest + FastAPI `TestClient` (`webapp/tests/`), GitHub Actions cron.

**Spec:** `docs/superpowers/specs/2026-09-10-partner-program-design.md` — read it before starting. All 8 open decisions are settled in its "Decisions (settled 2026-09-10)" section; v1 scope is frozen there.

## Global Constraints

- **v1 enrollment path:** "create the account" only. No referral-link route, no send-invite route. Do not build `/r/<code>` handling.
- **Reseller cannot self-refer:** the contact email on a create-the-account request must not match the reseller's own `User.email` (case-insensitive). Reject with HTTP 400.
- **Reseller never sees or sets a password.** Account handover is always a one-time signed set-password link (7-day expiry), surfaced in the UI for the reseller/superadmin to deliver manually (copy button). There is no email/SMS infrastructure in this app — do not add one; do not attempt to send the link.
- **Split base:** 50% of **gross** collected — the full `SubscriptionFee.amount_due` of every fee row where `is_paid == True`. No netting of gateway fee / GST.
- **Price control:** the reseller sets any price. No owner price-band validation.
- **Payouts are manual in v1.** The cron only computes and writes `ResellerPayout` / `ResellerPayoutLine` rows at `status='scheduled'`. The owner marks them `paid` with a UTR from the admin UI. No RazorpayX / Cashfree Payouts call, no automated retry.
- **TDS:** when the reseller's `ResellerProfile.pan` is non-empty, deduct `tds_rate` (default `10.0`) percent of that reseller's 50% share; store gross share, TDS, and net separately. Form 16A / quarterly filing is out of scope (owner's accountant handles it off-app).
- **Postgres DDL rule (from CLAUDE.md):** every new column/table needs an explicit `_try_ddl(...)` line in `_run_startup_migrations()` in `webapp/app.py`. `Base.metadata.create_all()` alone will NOT add columns to the production Neon database.
- **Ownership checks:** every `/api/reseller/...` endpoint must confirm `establishment.referred_by_reseller_id == current_user.id` before returning or acting on establishment data — mirror the existing `est.user_id != current_user.id` pattern in `webapp/auth.py`. A reseller must never read another reseller's data and must never edit any establishment's wage/ECR data.
- **Activity logging:** call `log_activity(db, user_id, establishment_id, action_type, description, metadata_dict)` for every create/mutate action, best-effort (it swallows its own exceptions).
- **Commit style:** conventional commits (`feat:`, `test:`, `chore:`, `docs:`). End every commit message body with:
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`
- **PowerShell commit gotcha (this machine):** here-string commit messages break if the message contains a literal `"` character — phrase messages without double-quotes.
- **Workflow-file push gotcha (this machine):** a `git push` that touches `.github/workflows/*` fails unless `gh auth refresh -h github.com -s workflow` has been run first (see `memory/feedback_github_workflow_push_auth.md`). Task 6 is the only task that adds a workflow file.
- **Run the full suite before each commit:** `pytest webapp/tests/ -v`. Tests use an isolated SQLite DB and never touch production.

---

## File Structure

**New files:**
- `webapp/reseller_tokens.py` — `itsdangerous`-based generate/verify for the set-password token. One responsibility: signing.
- `webapp/reseller_payout.py` — `compute_payouts_for_period(db, period_label)`: the 50:50 + TDS rollup. One responsibility: the payout math. Importable by both the app and the cron script; contains no FastAPI/route code.
- `scripts/run_reseller_payouts.py` — CLI wrapper: set up DB session from `DATABASE_URL`, call `compute_payouts_for_period`, print a summary, exit 0/1. Mirrors `scripts/backup_neon_to_supabase.py`.
- `.github/workflows/reseller-payout-run.yml` — monthly cron calling the script.
- `webapp/set_password.html` — standalone page (outside the SPA shell, same pattern as `webapp/signup.html`) where the invitee sets their own password.
- `webapp/js/reseller.js` — the reseller SPA dashboard module (overview / enroll / my establishments / ECR activity / earnings / payout history).
- `webapp/js/referral-program.js` — the superadmin "Referral Program" SPA module (overview / resellers / establishments / ECR activity / payouts).
- `webapp/tests/test_reseller_program.py` — all backend tests for this feature.

**Modified files:**
- `webapp/database.py` — 3 new model classes + 1 new `Establishment` column.
- `webapp/auth.py` — `get_reseller` dependency.
- `webapp/app.py` — migrations, Pydantic models, all `/api/admin/resellers/...`, `/api/admin/referral-program/...`, `/api/admin/payouts/...`, `/api/reseller/...`, `/api/auth/set-password`, `GET /set-password` routes.
- `webapp/index.html` — `<script src="/js/reseller.js">` and `<script src="/js/referral-program.js">`.
- `webapp/js/app.js` — `renderSidebarNav()` reseller + superadmin-referral nav items; `navigate()` `titles` map entries; `init()` landing-page branch for `role === 'reseller'`.
- `docs/superpowers/specs/2026-09-10-partner-program-design.md` — flip Status line to "v1 implemented" at the end (Task 7 step).

---

## Task 1: Schema, role plumbing, migrations

**Files:**
- Modify: `webapp/database.py` (add models after `SignupRequest`, add column to `Establishment`)
- Modify: `webapp/auth.py` (add `get_reseller` after `get_superadmin`, ~line 104)
- Modify: `webapp/app.py:_run_startup_migrations` (add `_try_ddl` lines in the `with engine.connect() as conn:` block, ~line 674)
- Test: `webapp/tests/test_reseller_program.py` (new)
- Modify: `webapp/tests/conftest.py` (add a `reseller_a` fixture + import the new models)

**Interfaces:**
- Produces: `ResellerProfile`, `Enrollment`, `ResellerPayout`, `ResellerPayoutLine` model classes; `Establishment.referred_by_reseller_id` column; `webapp.auth.get_reseller` FastAPI dependency (returns `User` with `role == 'reseller'`, else raises 403); conftest `reseller_a` fixture returning an `AuthClient`.

- [ ] **Step 1: Write the failing test**

Create `webapp/tests/test_reseller_program.py`:

```python
import os
import sys
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parent.parent.parent / "test_epf.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from webapp.database import (
    SessionLocal, User, Establishment,
    ResellerProfile, Enrollment, ResellerPayout, ResellerPayoutLine,
)


def test_reseller_profile_and_fk_exist(test_db):
    u = User(name="Reseller One", email="r1@x.com", role="reseller", is_active=True)
    test_db.add(u)
    test_db.commit()
    test_db.refresh(u)

    prof = ResellerProfile(
        user_id=u.id, full_name="RESELLER ONE", mobile="9000000001",
        email="r1@x.com", referral_code="RO1234", upi_id="r1@okhdfc",
        bank_account_number="123", bank_ifsc="HDFC0000001",
        bank_name="HDFC", bank_branch="BBSR", pan="ABCDE1234F",
    )
    test_db.add(prof)
    test_db.commit()

    est = Establishment(user_id=u.id, code="ORTEST0000000000", name="T",
                        data="{}", referred_by_reseller_id=u.id)
    test_db.add(est)
    test_db.commit()
    test_db.refresh(est)
    assert est.referred_by_reseller_id == u.id


def test_get_reseller_rejects_consultant(consultant_a):
    r = consultant_a.get("/api/reseller/overview")
    assert r.status_code == 403


def test_get_reseller_allows_reseller(reseller_a):
    r = reseller_a.get("/api/reseller/overview")
    # 200 once Task 5 lands; for Task 1 just assert it's not a 403 auth rejection.
    assert r.status_code != 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest webapp/tests/test_reseller_program.py -v`
Expected: FAIL — `ImportError` on `ResellerProfile` (models don't exist), `reseller_a` fixture missing.

- [ ] **Step 3: Add the models to `webapp/database.py`**

Add after the `SignupRequest` class (before `SessionLocal = None`):

```python
class ResellerProfile(Base):
    __tablename__ = "reseller_profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    full_name = Column(String(255), nullable=False)          # as per PAN
    mobile = Column(String(50), nullable=False)
    email = Column(String(255), nullable=False)              # payout-notification address
    referral_code = Column(String(20), nullable=False, unique=True, index=True)
    status = Column(String(20), nullable=False, default="active")   # 'active' | 'suspended'
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    upi_id = Column(String(120), nullable=True)
    bank_account_number = Column(String(50), nullable=True)
    bank_ifsc = Column(String(20), nullable=True)
    bank_name = Column(String(120), nullable=True)
    bank_branch = Column(String(120), nullable=True)
    # v1: no automated penny-drop. Superadmin sends Re.1 by hand and toggles this.
    payout_details_verified = Column(Boolean, nullable=False, default=False)
    payout_verified_at = Column(DateTime(timezone=True), nullable=True)

    pan = Column(String(15), nullable=True)
    tds_rate = Column(Float, nullable=False, default=10.0)

    user = relationship("User")


class Enrollment(Base):
    __tablename__ = "reseller_enrollments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reseller_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    establishment_id = Column(Integer, ForeignKey("establishments.id", ondelete="SET NULL"), nullable=True, index=True)
    account_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # the employer/consultant user created
    method = Column(String(30), nullable=False, default="create_handover")   # v1 always 'create_handover'
    contact_name = Column(String(255), nullable=True)
    contact_mobile = Column(String(50), nullable=True)
    contact_email = Column(String(255), nullable=True)
    stage = Column(String(40), nullable=False, default="account_created")
    # stage: account_created -> password_set -> awaiting_first_payment -> active
    set_password_jti = Column(String(64), nullable=True)   # opaque id embedded in the current token; rotated on resend
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    activated_at = Column(DateTime(timezone=True), nullable=True)


class ResellerPayout(Base):
    __tablename__ = "reseller_payouts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    reseller_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)   # 'YYYY-MM' label of the run
    gross_collected = Column(Float, nullable=False, default=0.0)   # sum of fee.amount_due on this payout's lines
    reseller_share_gross = Column(Float, nullable=False, default=0.0)   # 50% of gross_collected
    tds_amount = Column(Float, nullable=False, default=0.0)
    reseller_share_net = Column(Float, nullable=False, default=0.0)     # gross share - TDS
    owner_share = Column(Float, nullable=False, default=0.0)            # the other 50%
    status = Column(String(20), nullable=False, default="scheduled")   # 'scheduled' | 'paid' | 'failed'
    upi_id = Column(String(120), nullable=True)   # snapshot of the reseller's UPI at run time
    upi_reference = Column(String(255), nullable=True)   # UTR, entered by the owner on mark-paid
    notes = Column(Text, nullable=True)
    run_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("reseller_id", "period", name="uq_reseller_payouts_reseller_period"),)


class ResellerPayoutLine(Base):
    __tablename__ = "reseller_payout_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payout_id = Column(Integer, ForeignKey("reseller_payouts.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_fee_id = Column(Integer, ForeignKey("subscription_fees.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    establishment_id = Column(Integer, ForeignKey("establishments.id", ondelete="SET NULL"), nullable=True, index=True)
    establishment_name = Column(String(255), nullable=True)   # snapshot for display if the est is later deleted
    financial_year = Column(String(50), nullable=True)
    month = Column(String(20), nullable=True)
    fee_amount = Column(Float, nullable=False, default=0.0)         # the gross fee for this line
    reseller_share = Column(Float, nullable=False, default=0.0)     # 50% of fee_amount

    payout = relationship("ResellerPayout")
```

Add the column to `Establishment` (after `flat_fee_amount`, before `data`):

```python
    referred_by_reseller_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
```

- [ ] **Step 4: Add `get_reseller` to `webapp/auth.py`**

After `get_superadmin` (line ~104):

```python
async def get_reseller(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "reseller":
        raise HTTPException(status_code=403, detail="Access denied. This area is for reseller accounts.")
    return current_user
```

- [ ] **Step 5: Add the migrations to `webapp/app.py`**

In `_run_startup_migrations()`, inside `with engine.connect() as conn:`, after the last existing `_try_ddl(...)` line (~line 674):

```python
                # ── Partner / Reseller Program ──────────────────────────────
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN IF NOT EXISTS referred_by_reseller_id INTEGER REFERENCES users(id) ON DELETE SET NULL;")
                _try_ddl(conn, "ALTER TABLE establishments ADD COLUMN referred_by_reseller_id INTEGER;")
                _try_ddl(conn, "CREATE INDEX IF NOT EXISTS idx_establishments_referred_by_reseller ON establishments(referred_by_reseller_id);")
```

(The new tables themselves are created by the `Base.metadata.create_all(bind=engine)` call at the top of `_run_startup_migrations` — only the `Establishment` column needs an explicit ALTER, because that table already exists in prod.)

- [ ] **Step 6: Add the `reseller_a` fixture to `webapp/tests/conftest.py`**

Add to the imports on line 15: `ResellerProfile` (and the other new names are import-safe to add). Then add this fixture after `consultant_b`:

```python
@pytest.fixture
def reseller_a(client, test_db) -> AuthClient:
    """Create Reseller A (role='reseller') with a verified ResellerProfile and return an authed client."""
    from webapp.database import ResellerProfile
    email = "reseller_a@testepf.com"
    password = "ResellerA@123"

    user = test_db.query(User).filter(User.email == email).first()
    if not user:
        user = User(serial_no=201, name="Reseller Alpha", email=email,
                    mobile="9876511001", password_hash=hash_password(password),
                    role="reseller", is_active=True)
        test_db.add(user)
        test_db.commit()
        test_db.refresh(user)
        test_db.add(ResellerProfile(
            user_id=user.id, full_name="RESELLER ALPHA", mobile="9876511001",
            email=email, referral_code="RA2001", upi_id="resellera@okhdfc",
            bank_account_number="00011122233", bank_ifsc="HDFC0000123",
            bank_name="HDFC Bank", bank_branch="Bhubaneswar", pan="ABCDE1111F",
            payout_details_verified=True,
        ))
        test_db.commit()

    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Reseller A login failed: {res.text}"
    return AuthClient(client, res.json()["token"], res.json()["user"])
```

- [ ] **Step 7: Run tests**

Run: `pytest webapp/tests/test_reseller_program.py -v`
Expected: `test_reseller_profile_and_fk_exist` PASS, `test_get_reseller_rejects_consultant` PASS (404? no — the route doesn't exist yet, so it's 404 not 403). **Adjust:** for Task 1, change those two tests to assert against `get_reseller` directly rather than a route. Replace `test_get_reseller_rejects_consultant` / `test_get_reseller_allows_reseller` with:

```python
import pytest
from fastapi import HTTPException
from webapp.auth import get_reseller


@pytest.mark.asyncio
async def test_get_reseller_rejects_non_reseller(test_db):
    consultant = User(name="C", email="c-grd@x.com", role="consultant", is_active=True)
    with pytest.raises(HTTPException) as ei:
        await get_reseller(current_user=consultant)
    assert ei.value.status_code == 403


@pytest.mark.asyncio
async def test_get_reseller_allows_reseller(test_db):
    r = User(name="R", email="r-grd@x.com", role="reseller", is_active=True)
    assert (await get_reseller(current_user=r)) is r
```

Check `pytest-asyncio` is available: `grep pytest-asyncio webapp/requirements.txt`. If absent, instead call the dependency's underlying sync check — rewrite `get_reseller`'s body into a plain helper `_require_reseller(user)` that `get_reseller` wraps, and test the helper. Prefer this (no new dep):

```python
def _require_reseller(user: User) -> User:
    if user.role != "reseller":
        raise HTTPException(status_code=403, detail="Access denied. This area is for reseller accounts.")
    return user

async def get_reseller(current_user: User = Depends(get_current_user)) -> User:
    return _require_reseller(current_user)
```

Then tests call `_require_reseller` synchronously.

Run again. Expected: all Task 1 tests PASS.

- [ ] **Step 8: Run the full suite**

Run: `pytest webapp/tests/ -v`
Expected: all green (Task 1 is purely additive — no existing test should change).

- [ ] **Step 9: Commit**

```bash
git add webapp/database.py webapp/auth.py webapp/app.py webapp/tests/conftest.py webapp/tests/test_reseller_program.py
git commit -m @'
feat(reseller): add reseller role, ResellerProfile/Enrollment/ResellerPayout tables, referred_by_reseller_id

Schema + get_reseller dependency only, no behaviour change. Establishment gets a
nullable referred_by_reseller_id FK with an explicit startup migration.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

---

## Task 2: Set-password token module + handover page

**Files:**
- Create: `webapp/reseller_tokens.py`
- Create: `webapp/set_password.html`
- Modify: `webapp/app.py` (Pydantic `SetPasswordIn`; `GET /set-password` route near the other page routes ~line 858; `POST /api/auth/set-password` near the auth routes ~line 1225)
- Test: `webapp/tests/test_reseller_program.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `webapp.reseller_tokens.make_set_password_token(user_id: int, jti: str) -> str`
  - `webapp.reseller_tokens.read_set_password_token(token: str, max_age_days: int = 7) -> dict | None` → `{"user_id": int, "jti": str}` or `None` if invalid/expired
  - `POST /api/auth/set-password` `{token: str, password: str}` → `{ok: True}`; sets `User.password_hash`, and if an `Enrollment` row has a matching `set_password_jti` advances its `stage` to `password_set`.
  - `GET /set-password` → serves `webapp/set_password.html`.

- [ ] **Step 1: Write the failing test**

Add to `webapp/tests/test_reseller_program.py`:

```python
from webapp.reseller_tokens import make_set_password_token, read_set_password_token


def test_set_password_token_roundtrip():
    tok = make_set_password_token(user_id=42, jti="abc123")
    got = read_set_password_token(tok)
    assert got == {"user_id": 42, "jti": "abc123"}


def test_set_password_token_rejects_tamper():
    tok = make_set_password_token(user_id=42, jti="abc123")
    assert read_set_password_token(tok[:-3] + "zzz") is None


def test_set_password_token_expires():
    tok = make_set_password_token(user_id=42, jti="abc123")
    assert read_set_password_token(tok, max_age_days=0) is None


def test_set_password_endpoint_sets_hash(client, test_db):
    u = User(name="Invitee", email="invitee@x.com", role="employer",
             is_active=True, password_hash=None)
    test_db.add(u)
    test_db.commit()
    test_db.refresh(u)
    tok = make_set_password_token(user_id=u.id, jti="jti-1")

    r = client.post("/api/auth/set-password", json={"token": tok, "password": "NewPass@123"})
    assert r.status_code == 200

    login = client.post("/api/auth/login", json={"email": "invitee@x.com", "password": "NewPass@123"})
    assert login.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest webapp/tests/test_reseller_program.py -k set_password -v`
Expected: FAIL — `ModuleNotFoundError: webapp.reseller_tokens`.

- [ ] **Step 3: Create `webapp/reseller_tokens.py`**

```python
"""Signed, expiring tokens for the one-time set-password handover link.

No email/SMS is sent by this app -- the link is surfaced in the UI for the
superadmin / reseller to deliver manually. The token is stateless and signed
with the same JWT_SECRET the rest of the app uses; an Enrollment row also
stores the token's `jti` so a resend can invalidate the previous link.
"""
import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

_SECRET = os.environ.get("JWT_SECRET", "epf-keka-theme-super-secret-jwt-key-2026")
_SALT = "reseller-set-password-v1"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_SECRET, salt=_SALT)


def make_set_password_token(user_id: int, jti: str) -> str:
    return _serializer().dumps({"user_id": int(user_id), "jti": str(jti)})


def read_set_password_token(token: str, max_age_days: int = 7):
    try:
        data = _serializer().loads(token, max_age=max_age_days * 86400)
    except (BadSignature, SignatureExpired, Exception):
        return None
    if not isinstance(data, dict) or "user_id" not in data or "jti" not in data:
        return None
    return {"user_id": int(data["user_id"]), "jti": str(data["jti"])}
```

- [ ] **Step 4: Add the endpoint + page route to `webapp/app.py`**

Pydantic model (with the other `*In` models near the top of the models section):

```python
class SetPasswordIn(BaseModel):
    token: str
    password: str
```

Page route (near `signup_page`, ~line 858):

```python
@app.get("/set-password")
async def set_password_page():
    return FileResponse(str(WEBAPP_DIR / "set_password.html"))
```

(Check how `signup_page` resolves its path — reuse the exact same `WEBAPP_DIR` / `os.path.join` idiom that's already there.)

Endpoint (near `login`, ~line 1225):

```python
@app.post("/api/auth/set-password")
async def set_password(d: SetPasswordIn, db: Session = Depends(get_db)):
    from webapp.reseller_tokens import read_set_password_token
    if not d.password or len(d.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    data = read_set_password_token(d.token)
    if not data:
        raise HTTPException(400, "This set-password link is invalid or has expired. Ask for a new one.")
    user = db.query(User).filter(User.id == data["user_id"]).first()
    if not user:
        raise HTTPException(404, "Account not found.")

    user.password_hash = hash_password(d.password)
    db.commit()

    enr = db.query(Enrollment).filter(Enrollment.set_password_jti == data["jti"]).first()
    if enr and enr.stage == "account_created":
        enr.stage = "password_set"
        db.commit()

    log_activity(db, user.id, enr.establishment_id if enr else None,
                 "set_password", f"{user.name} set their password via handover link",
                 {"user_id": user.id})
    return {"ok": True}
```

Add `Enrollment` to the `from .database import (...)` line at the top of `app.py`.

- [ ] **Step 5: Create `webapp/set_password.html`**

Copy the `<head>` / theme-script / stylesheet block from `webapp/signup.html` verbatim, then a minimal card:

```html
<body>
  <div style="display:flex; justify-content:center; align-items:center; min-height:100vh; background:var(--bg); padding:20px;">
    <div class="card" style="width:100%; max-width:420px; padding:36px 40px;">
      <div id="sp-form">
        <h2 style="margin:0 0 6px; font-size:20px; font-weight:800; color:var(--text1);">Set your password</h2>
        <p style="color:var(--text2); font-size:13px; margin-bottom:20px;">Choose a password for your EPF Admin Dashboard account. You can also sign in with Google later.</p>
        <div id="sp-status" style="display:none; font-size:12px; padding:10px 12px; border-radius:var(--radius-sm); margin-bottom:14px;"></div>
        <label class="form-label" style="font-weight:600;">New password</label>
        <input type="password" id="sp-pw" class="form-input" placeholder="At least 8 characters" style="margin-bottom:12px;">
        <label class="form-label" style="font-weight:600;">Confirm password</label>
        <input type="password" id="sp-pw2" class="form-input" placeholder="Re-enter" style="margin-bottom:18px;">
        <button id="sp-btn" class="btn btn-primary" style="width:100%; padding:12px; font-weight:700;">Set password</button>
      </div>
      <div id="sp-done" style="display:none; text-align:center;">
        <span style="font-size:44px;">✅</span>
        <h2 style="font-size:18px; font-weight:800; color:var(--text1);">Password set</h2>
        <a href="/" class="btn btn-ghost" style="margin-top:16px; display:inline-block;">Go to sign in</a>
      </div>
    </div>
  </div>
  <script>
    (function () {
      var token = new URLSearchParams(location.search).get("token") || "";
      var $ = function (id) { return document.getElementById(id); };
      function status(msg, ok) {
        var el = $("sp-status");
        el.style.display = "block";
        el.textContent = msg;
        el.style.background = ok ? "rgba(34,197,94,0.12)" : "rgba(239,68,68,0.12)";
        el.style.color = ok ? "var(--green)" : "var(--red)";
      }
      if (!token) status("This link is missing its token. Ask for a new set-password link.", false);
      $("sp-btn").addEventListener("click", function () {
        var pw = $("sp-pw").value, pw2 = $("sp-pw2").value;
        if (pw.length < 8) return status("Password must be at least 8 characters.", false);
        if (pw !== pw2) return status("The two passwords do not match.", false);
        $("sp-btn").disabled = true;
        fetch("/api/auth/set-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: token, password: pw })
        }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
          .then(function (res) {
            if (!res.ok) { $("sp-btn").disabled = false; return status(res.j.detail || "Could not set password.", false); }
            $("sp-form").style.display = "none";
            $("sp-done").style.display = "block";
          }).catch(function () { $("sp-btn").disabled = false; status("Network error. Try again.", false); });
      });
    })();
  </script>
</body>
```

- [ ] **Step 6: Run tests**

Run: `pytest webapp/tests/test_reseller_program.py -k set_password -v`
Expected: all PASS.

- [ ] **Step 7: Run the full suite**

Run: `pytest webapp/tests/ -v` — expected all green.

- [ ] **Step 8: Commit**

```bash
git add webapp/reseller_tokens.py webapp/set_password.html webapp/app.py webapp/tests/test_reseller_program.py
git commit -m @'
feat(reseller): signed set-password handover token module and standalone page

itsdangerous-signed 7-day token, POST /api/auth/set-password sets the users own
hash and advances the matching Enrollment to password_set. No email is sent; the
link is surfaced in the UI for manual delivery.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

---

## Task 3: Superadmin "Enrol a reseller" — backend

**Files:**
- Modify: `webapp/app.py` (Pydantic models; `/api/admin/resellers` routes near the other `/api/admin/users` routes ~line 1448)
- Test: `webapp/tests/test_reseller_program.py`

**Interfaces:**
- Consumes: `make_set_password_token` (Task 2), `ResellerProfile` / `Enrollment` (Task 1), `get_superadmin`.
- Produces:
  - `_generate_referral_code(db, name) -> str` (module-level helper in `app.py`)
  - `POST /api/admin/resellers` `ResellerEnrolIn` → `{ok, reseller: {...}, set_password_url}`
  - `GET /api/admin/resellers` → `{resellers: [{id, full_name, email, mobile, referral_code, status, payout_details_verified, referral_count, mrr, lifetime_paid_net}]}`
  - `GET /api/admin/resellers/{id}` → full profile incl. masked bank
  - `PATCH /api/admin/resellers/{id}` `ResellerProfileUpdateIn` → `{ok}`; changing any of `upi_id`/`bank_*` resets `payout_details_verified=False`, `payout_verified_at=None`
  - `POST /api/admin/resellers/{id}/verify-payout` → `{ok}`; sets `payout_details_verified=True`, `payout_verified_at=now`

- [ ] **Step 1: Write the failing test**

```python
def test_enrol_reseller_creates_user_profile_and_link(superadmin_session, test_db):
    payload = {
        "full_name": "SURESH PATRA", "mobile": "9776100200",
        "email": "suresh.patra@x.com", "upi_id": "suresh@okaxis",
        "bank_account_number": "11122233344", "bank_ifsc": "SBIN0001234",
        "bank_name": "SBI", "bank_branch": "Cuttack", "pan": "AAAPP1234C",
    }
    r = superadmin_session.post("/api/admin/resellers", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["set_password_url"].startswith("http")
    assert "/set-password?token=" in body["set_password_url"]
    assert len(body["reseller"]["referral_code"]) >= 4

    u = test_db.query(User).filter(User.email == "suresh.patra@x.com").first()
    assert u is not None and u.role == "reseller" and u.password_hash is None

    from webapp.database import ResellerProfile
    prof = test_db.query(ResellerProfile).filter(ResellerProfile.user_id == u.id).first()
    assert prof is not None and prof.payout_details_verified is False


def test_enrol_reseller_rejects_duplicate_email(superadmin_session):
    p = {"full_name": "A", "mobile": "1", "email": "dupe-r@x.com", "upi_id": "a@ok",
         "bank_account_number": "1", "bank_ifsc": "X", "bank_name": "X",
         "bank_branch": "X", "pan": "X"}
    assert superadmin_session.post("/api/admin/resellers", json=p).status_code == 200
    assert superadmin_session.post("/api/admin/resellers", json=p).status_code == 400


def test_verify_payout_toggle(superadmin_session, test_db):
    p = {"full_name": "V", "mobile": "1", "email": "verify-r@x.com", "upi_id": "v@ok",
         "bank_account_number": "1", "bank_ifsc": "X", "bank_name": "X",
         "bank_branch": "X", "pan": "X"}
    rid = superadmin_session.post("/api/admin/resellers", json=p).json()["reseller"]["id"]
    assert superadmin_session.post(f"/api/admin/resellers/{rid}/verify-payout").status_code == 200
    from webapp.database import ResellerProfile
    prof = test_db.query(ResellerProfile).filter(ResellerProfile.user_id == rid).first()
    test_db.refresh(prof)
    assert prof.payout_details_verified is True

    superadmin_session.patch(f"/api/admin/resellers/{rid}", json={"upi_id": "v2@ok"})
    test_db.refresh(prof)
    assert prof.payout_details_verified is False


def test_enrol_reseller_forbidden_for_consultant(consultant_a):
    assert consultant_a.post("/api/admin/resellers", json={}).status_code == 403
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest webapp/tests/test_reseller_program.py -k reseller -v` → FAIL (routes 404).

- [ ] **Step 3: Add Pydantic models to `webapp/app.py`**

```python
class ResellerEnrolIn(BaseModel):
    full_name: str
    mobile: str
    email: str
    upi_id: str
    bank_account_number: str
    bank_ifsc: str
    bank_name: str
    bank_branch: str
    pan: str
    tds_rate: Optional[float] = 10.0


class ResellerProfileUpdateIn(BaseModel):
    full_name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    upi_id: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    bank_branch: Optional[str] = None
    pan: Optional[str] = None
    tds_rate: Optional[float] = None
    status: Optional[str] = None
```

- [ ] **Step 4: Add the referral-code helper + the base-URL helper**

```python
import secrets as _secrets

def _generate_referral_code(db: Session, name: str) -> str:
    prefix = "".join(ch for ch in (name or "").upper() if ch.isalpha())[:2] or "RS"
    for _ in range(50):
        code = f"{prefix}{_secrets.randbelow(9000) + 1000}"
        if not db.query(ResellerProfile).filter(ResellerProfile.referral_code == code).first():
            return code
    return f"{prefix}{_secrets.token_hex(3).upper()}"

def _public_base_url(request: Request) -> str:
    # Behind Traefik on Coolify the app sees the external host via forwarded headers.
    env = (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")
    if env:
        return env
    return str(request.base_url).rstrip("/")
```

Add `ResellerProfile` to the `from .database import (...)` line.

- [ ] **Step 5: Add the routes to `webapp/app.py`**

```python
@app.post("/api/admin/resellers")
async def admin_enrol_reseller(d: ResellerEnrolIn, request: Request,
                               admin: User = Depends(get_superadmin),
                               db: Session = Depends(get_db)):
    from webapp.reseller_tokens import make_set_password_token
    email = d.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "A valid email is required.")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(400, f"An account with email '{email}' already exists.")
    for label, val in (("UPI ID", d.upi_id), ("bank account number", d.bank_account_number),
                       ("IFSC", d.bank_ifsc), ("PAN", d.pan), ("full name", d.full_name),
                       ("mobile", d.mobile)):
        if not (val or "").strip():
            raise HTTPException(400, f"The reseller's {label} is required.")

    max_serial = db.query(func.max(User.serial_no)).scalar() or 0
    user = User(serial_no=max_serial + 1, name=d.full_name.strip(), mobile=d.mobile.strip(),
                email=email, password_hash=None, role="reseller", is_active=True)
    db.add(user); db.commit(); db.refresh(user)

    code = _generate_referral_code(db, d.full_name)
    prof = ResellerProfile(
        user_id=user.id, full_name=d.full_name.strip(), mobile=d.mobile.strip(), email=email,
        referral_code=code, upi_id=d.upi_id.strip(),
        bank_account_number=d.bank_account_number.strip(), bank_ifsc=d.bank_ifsc.strip().upper(),
        bank_name=d.bank_name.strip(), bank_branch=d.bank_branch.strip(),
        pan=d.pan.strip().upper(), tds_rate=d.tds_rate if d.tds_rate is not None else 10.0,
        payout_details_verified=False,
    )
    db.add(prof); db.commit()

    jti = _secrets.token_hex(16)
    token = make_set_password_token(user.id, jti)
    enr = Enrollment(reseller_id=user.id, account_user_id=user.id, method="reseller_self",
                     contact_name=d.full_name, contact_email=email, contact_mobile=d.mobile,
                     stage="account_created", set_password_jti=jti,
                     token_expires_at=datetime.utcnow() + timedelta(days=7))
    db.add(enr); db.commit()

    set_password_url = f"{_public_base_url(request)}/set-password?token={token}"
    log_activity(db, admin.id, None, "reseller_enrolled",
                 f"Enrolled reseller {user.name} ({email}), code {code}",
                 {"reseller_id": user.id, "referral_code": code})
    return {"ok": True, "set_password_url": set_password_url,
            "reseller": {"id": user.id, "full_name": prof.full_name, "email": email,
                         "referral_code": code}}


def _reseller_rollup(db: Session, reseller_id: int) -> dict:
    """referral_count, MRR (sum of current unpaid+paid amount_due for the latest FY),
    lifetime_paid_net (sum of ResellerPayout.reseller_share_net where status='paid')."""
    ref_ests = db.query(Establishment).filter(Establishment.referred_by_reseller_id == reseller_id).all()
    ref_ids = [e.id for e in ref_ests]
    mrr = 0.0
    if ref_ids:
        latest_fy = db.query(func.max(SubscriptionFee.financial_year)).filter(
            SubscriptionFee.establishment_id.in_(ref_ids)).scalar()
        if latest_fy:
            mrr = db.query(func.coalesce(func.sum(SubscriptionFee.amount_due), 0.0)).filter(
                SubscriptionFee.establishment_id.in_(ref_ids),
                SubscriptionFee.financial_year == latest_fy).scalar() or 0.0
    lifetime = db.query(func.coalesce(func.sum(ResellerPayout.reseller_share_net), 0.0)).filter(
        ResellerPayout.reseller_id == reseller_id, ResellerPayout.status == "paid").scalar() or 0.0
    return {"referral_count": len(ref_ids), "mrr": round(mrr, 2), "lifetime_paid_net": round(lifetime, 2)}


@app.get("/api/admin/resellers")
async def admin_list_resellers(admin: User = Depends(get_superadmin), db: Session = Depends(get_db)):
    out = []
    for prof in db.query(ResellerProfile).order_by(ResellerProfile.joined_at.desc()).all():
        roll = _reseller_rollup(db, prof.user_id)
        out.append({"id": prof.user_id, "full_name": prof.full_name, "email": prof.email,
                    "mobile": prof.mobile, "referral_code": prof.referral_code,
                    "status": prof.status, "payout_details_verified": prof.payout_details_verified,
                    **roll})
    return {"resellers": out}


def _mask(s: str, keep: int = 4) -> str:
    s = s or ""
    return ("•" * max(0, len(s) - keep)) + s[-keep:] if s else ""


@app.get("/api/admin/resellers/{reseller_id}")
async def admin_get_reseller(reseller_id: int, admin: User = Depends(get_superadmin),
                             db: Session = Depends(get_db)):
    prof = db.query(ResellerProfile).filter(ResellerProfile.user_id == reseller_id).first()
    if not prof:
        raise HTTPException(404, "Reseller not found.")
    roll = _reseller_rollup(db, reseller_id)
    return {"reseller": {
        "id": prof.user_id, "full_name": prof.full_name, "email": prof.email, "mobile": prof.mobile,
        "referral_code": prof.referral_code, "status": prof.status, "joined_at": _isodt(prof.joined_at),
        "upi_id": prof.upi_id, "bank_account_masked": _mask(prof.bank_account_number),
        "bank_ifsc": prof.bank_ifsc, "bank_name": prof.bank_name, "bank_branch": prof.bank_branch,
        "pan": prof.pan, "tds_rate": prof.tds_rate,
        "payout_details_verified": prof.payout_details_verified,
        "payout_verified_at": _isodt(prof.payout_verified_at), **roll}}


@app.patch("/api/admin/resellers/{reseller_id}")
async def admin_update_reseller(reseller_id: int, d: ResellerProfileUpdateIn,
                                admin: User = Depends(get_superadmin), db: Session = Depends(get_db)):
    prof = db.query(ResellerProfile).filter(ResellerProfile.user_id == reseller_id).first()
    if not prof:
        raise HTTPException(404, "Reseller not found.")
    payout_fields = {"upi_id", "bank_account_number", "bank_ifsc", "bank_name", "bank_branch"}
    touched_payout = False
    for f in ("full_name", "mobile", "email", "upi_id", "bank_account_number", "bank_ifsc",
              "bank_name", "bank_branch", "pan", "tds_rate", "status"):
        v = getattr(d, f)
        if v is not None:
            setattr(prof, f, v.strip().upper() if f in ("bank_ifsc", "pan") and isinstance(v, str)
                    else (v.strip() if isinstance(v, str) else v))
            if f in payout_fields:
                touched_payout = True
    if touched_payout:
        prof.payout_details_verified = False
        prof.payout_verified_at = None
    db.commit()
    log_activity(db, admin.id, None, "reseller_updated",
                 f"Updated reseller profile #{reseller_id}" + (" (payout details changed, re-verify)" if touched_payout else ""),
                 {"reseller_id": reseller_id, "payout_reset": touched_payout})
    return {"ok": True, "payout_details_verified": prof.payout_details_verified}


@app.post("/api/admin/resellers/{reseller_id}/verify-payout")
async def admin_verify_reseller_payout(reseller_id: int, admin: User = Depends(get_superadmin),
                                       db: Session = Depends(get_db)):
    prof = db.query(ResellerProfile).filter(ResellerProfile.user_id == reseller_id).first()
    if not prof:
        raise HTTPException(404, "Reseller not found.")
    prof.payout_details_verified = True
    prof.payout_verified_at = datetime.utcnow()
    db.commit()
    log_activity(db, admin.id, None, "reseller_payout_verified",
                 f"Marked payout details verified for reseller #{reseller_id}", {"reseller_id": reseller_id})
    return {"ok": True}
```

Add helper `_isodt` if the file doesn't already have one:

```python
def _isodt(dt):
    return dt.isoformat() if dt else None
```

(grep first: `grep -n "_isodt\|def _iso" webapp/app.py` — reuse an existing one if present.)

- [ ] **Step 5b: Add `ResellerPayout` to the `from .database import` line** (needed by `_reseller_rollup`).

- [ ] **Step 6: Run tests**

Run: `pytest webapp/tests/test_reseller_program.py -k reseller -v` → all PASS.

- [ ] **Step 7: Full suite** → `pytest webapp/tests/ -v` green.

- [ ] **Step 8: Commit**

```bash
git add webapp/app.py webapp/tests/test_reseller_program.py
git commit -m @'
feat(reseller): superadmin enrol-a-reseller endpoints

POST /api/admin/resellers creates the reseller User + ResellerProfile + referral
code + a set-password handover link. List/detail/patch endpoints; changing any
payout field resets the manual verified flag; verify-payout toggles it back.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

---

## Task 4: "Create the account" enrollment — reseller backend

**Files:**
- Modify: `webapp/app.py` (Pydantic `ResellerCreateEstablishmentIn`; `/api/reseller/establishments` + `/api/reseller/enrollments` routes — put all `/api/reseller/...` routes together in one new section near the end of the route definitions)
- Test: `webapp/tests/test_reseller_program.py`

**Interfaces:**
- Consumes: `get_reseller` (Task 1), `make_set_password_token` (Task 2), `_public_base_url`, `_normalize_coverage_date` (existing in `app.py`), `_generate_referral_code` not needed here.
- Produces:
  - `POST /api/reseller/establishments` `ResellerCreateEstablishmentIn` → `{ok, establishment: {...}, set_password_url, enrollment_id}`
  - `GET /api/reseller/enrollments` → `{enrollments: [{id, establishment_name, contact_name, contact_email, stage, created_at, token_expires_at, establishment_id}]}`
  - `POST /api/reseller/enrollments/{id}/resend` → `{ok, set_password_url}` (new `jti`, new 7-day expiry; only while `stage in ('account_created','password_set')`)

- [ ] **Step 1: Write the failing test**

```python
def _create_est_payload(**over):
    p = {"code": "ORBBS9990000000", "name": "SAMPLE UDYOG", "address": "Cuttack",
         "coverage_date": "2020-04-01", "contact_name": "Manoj Das",
         "contact_email": "manoj.das@sampleudyog.com", "contact_mobile": "9800012345",
         "billing_mode": "flat_fee", "flat_fee_amount": 2000, "custom_rate_per_employee": None}
    p.update(over)
    return p


def test_reseller_creates_tagged_establishment_and_user(reseller_a, test_db):
    r = reseller_a.post("/api/reseller/establishments", json=_create_est_payload())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "/set-password?token=" in body["set_password_url"]

    est = test_db.query(Establishment).filter(Establishment.code == "ORBBS9990000000").first()
    assert est is not None
    assert est.referred_by_reseller_id == reseller_a.user_id
    assert est.billing_mode == "flat_fee" and est.flat_fee_amount == 2000

    owner = test_db.query(User).filter(User.email == "manoj.das@sampleudyog.com").first()
    assert owner is not None and owner.role == "employer" and owner.password_hash is None
    assert est.user_id == owner.id


def test_reseller_per_employee_billing(reseller_a, test_db):
    r = reseller_a.post("/api/reseller/establishments", json=_create_est_payload(
        code="ORBBS9990000001", contact_email="c2@x.com",
        billing_mode="per_employee", flat_fee_amount=None, custom_rate_per_employee=30))
    assert r.status_code == 200
    est = test_db.query(Establishment).filter(Establishment.code == "ORBBS9990000001").first()
    assert est.billing_mode == "per_employee" and est.custom_rate_per_employee == 30


def test_reseller_cannot_self_refer(reseller_a):
    r = reseller_a.post("/api/reseller/establishments",
                        json=_create_est_payload(contact_email="reseller_a@testepf.com"))
    assert r.status_code == 400


def test_reseller_enrollment_pipeline_and_resend(reseller_a, test_db):
    reseller_a.post("/api/reseller/establishments", json=_create_est_payload(
        code="ORBBS9990000002", contact_email="pipe@x.com"))
    lst = reseller_a.get("/api/reseller/enrollments").json()["enrollments"]
    assert any(e["contact_email"] == "pipe@x.com" and e["stage"] == "account_created" for e in lst)
    eid = [e["id"] for e in lst if e["contact_email"] == "pipe@x.com"][0]
    rs = reseller_a.post(f"/api/reseller/enrollments/{eid}/resend")
    assert rs.status_code == 200 and "/set-password?token=" in rs.json()["set_password_url"]


def test_consultant_cannot_hit_reseller_create(consultant_a):
    assert consultant_a.post("/api/reseller/establishments", json=_create_est_payload()).status_code == 403
```

- [ ] **Step 2: Run to verify fail** → `pytest webapp/tests/test_reseller_program.py -k "reseller_creates or self_refer or pipeline or reseller_per_employee or reseller_create" -v` → FAIL (404).

- [ ] **Step 3: Pydantic model**

```python
class ResellerCreateEstablishmentIn(BaseModel):
    code: str
    name: str
    address: Optional[str] = ""
    coverage_date: str
    contact_name: str
    contact_email: str
    contact_mobile: Optional[str] = ""
    billing_mode: str            # 'flat_fee' | 'per_employee'
    flat_fee_amount: Optional[float] = None
    custom_rate_per_employee: Optional[float] = None
```

- [ ] **Step 4: Routes**

```python
# ══ Reseller dashboard ═══════════════════════════════════════════════════════

def _reseller_est_or_403(db: Session, reseller: User, est_id: int) -> Establishment:
    est = db.query(Establishment).filter(Establishment.id == est_id).first()
    if not est:
        raise HTTPException(404, "Establishment not found.")
    if est.referred_by_reseller_id != reseller.id:
        raise HTTPException(403, "This establishment was not referred by you.")
    return est


@app.post("/api/reseller/establishments")
async def reseller_create_establishment(d: ResellerCreateEstablishmentIn, request: Request,
                                        reseller: User = Depends(get_reseller),
                                        db: Session = Depends(get_db)):
    from webapp.reseller_tokens import make_set_password_token
    code = d.code.strip().upper()
    name = d.name.strip()
    contact_email = d.contact_email.strip().lower()
    if not code or not name:
        raise HTTPException(400, "Establishment code and name are required.")
    if not contact_email or "@" not in contact_email:
        raise HTTPException(400, "A valid contact email is required.")
    if contact_email == (reseller.email or "").lower():
        raise HTTPException(400, "You cannot enroll an establishment against your own email (no self-referral).")
    if d.billing_mode not in ("flat_fee", "per_employee"):
        raise HTTPException(400, "billing_mode must be 'flat_fee' or 'per_employee'.")
    if d.billing_mode == "flat_fee" and not (d.flat_fee_amount and d.flat_fee_amount > 0):
        raise HTTPException(400, "A monthly flat fee amount is required for flat_fee billing.")
    if d.billing_mode == "per_employee" and not (d.custom_rate_per_employee and d.custom_rate_per_employee > 0):
        raise HTTPException(400, "A per-employee rate is required for per_employee billing.")
    try:
        coverage_date = _normalize_coverage_date(d.coverage_date)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if db.query(Establishment).filter(func.upper(Establishment.code) == code).first():
        raise HTTPException(409, DUPLICATE_ESTABLISHMENT_MESSAGE)

    existing_user = db.query(User).filter(func.lower(User.email) == contact_email).first()
    if existing_user:
        raise HTTPException(400, f"An account with email '{contact_email}' already exists. "
                                 "Enrollment must use a fresh contact email in v1.")

    max_serial = db.query(func.max(User.serial_no)).scalar() or 0
    owner = User(serial_no=max_serial + 1, name=d.contact_name.strip(),
                 mobile=(d.contact_mobile or "").strip(), email=contact_email,
                 password_hash=None, role="employer", max_establishments=1, is_active=True)
    db.add(owner); db.commit(); db.refresh(owner)

    p = Project()
    p.set_establishment(code, name, (d.address or "").strip(), coverage_date)
    est = Establishment(
        user_id=owner.id, code=code, name=name, address=(d.address or "").strip(),
        coverage_date=coverage_date, billing_mode=d.billing_mode,
        flat_fee_amount=d.flat_fee_amount if d.billing_mode == "flat_fee" else None,
        custom_rate_per_employee=d.custom_rate_per_employee if d.billing_mode == "per_employee" else None,
        referred_by_reseller_id=reseller.id,
        data=json.dumps(p.to_dict(), ensure_ascii=False),
    )
    db.add(est); db.commit(); db.refresh(est)

    jti = _secrets.token_hex(16)
    token = make_set_password_token(owner.id, jti)
    enr = Enrollment(reseller_id=reseller.id, establishment_id=est.id, account_user_id=owner.id,
                     method="create_handover", contact_name=d.contact_name,
                     contact_mobile=d.contact_mobile, contact_email=contact_email,
                     stage="account_created", set_password_jti=jti,
                     token_expires_at=datetime.utcnow() + timedelta(days=7))
    db.add(enr); db.commit(); db.refresh(enr)

    log_activity(db, reseller.id, est.id, "reseller_created_establishment",
                 f"Reseller {reseller.name} created {est.code} — {est.name} for {contact_email}",
                 {"reseller_id": reseller.id, "establishment_id": est.id, "owner_user_id": owner.id})

    return {"ok": True, "enrollment_id": enr.id,
            "set_password_url": f"{_public_base_url(request)}/set-password?token={token}",
            "establishment": {"id": est.id, "code": est.code, "name": est.name,
                              "billing_mode": est.billing_mode, "flat_fee_amount": est.flat_fee_amount,
                              "custom_rate_per_employee": est.custom_rate_per_employee}}


@app.get("/api/reseller/enrollments")
async def reseller_list_enrollments(reseller: User = Depends(get_reseller), db: Session = Depends(get_db)):
    rows = db.query(Enrollment).filter(
        Enrollment.reseller_id == reseller.id, Enrollment.method == "create_handover"
    ).order_by(Enrollment.created_at.desc()).all()
    est_names = {e.id: e.name for e in db.query(Establishment).filter(
        Establishment.referred_by_reseller_id == reseller.id).all()}
    return {"enrollments": [{
        "id": r.id, "establishment_id": r.establishment_id,
        "establishment_name": est_names.get(r.establishment_id, "—"),
        "contact_name": r.contact_name, "contact_email": r.contact_email,
        "stage": r.stage, "created_at": _isodt(r.created_at),
        "token_expires_at": _isodt(r.token_expires_at),
    } for r in rows]}


@app.post("/api/reseller/enrollments/{enrollment_id}/resend")
async def reseller_resend_set_password(enrollment_id: int, request: Request,
                                       reseller: User = Depends(get_reseller),
                                       db: Session = Depends(get_db)):
    from webapp.reseller_tokens import make_set_password_token
    enr = db.query(Enrollment).filter(Enrollment.id == enrollment_id,
                                      Enrollment.reseller_id == reseller.id).first()
    if not enr:
        raise HTTPException(404, "Enrollment not found.")
    if enr.stage not in ("account_created", "password_set"):
        raise HTTPException(400, "This account has already progressed past the set-password step.")
    if not enr.account_user_id:
        raise HTTPException(400, "No account is linked to this enrollment.")
    jti = _secrets.token_hex(16)
    enr.set_password_jti = jti
    enr.token_expires_at = datetime.utcnow() + timedelta(days=7)
    db.commit()
    token = make_set_password_token(enr.account_user_id, jti)
    log_activity(db, reseller.id, enr.establishment_id, "reseller_resent_set_password",
                 f"Reseller re-sent the set-password link for enrollment #{enr.id}", {"enrollment_id": enr.id})
    return {"ok": True, "set_password_url": f"{_public_base_url(request)}/set-password?token={token}"}
```

- [ ] **Step 5: Run tests** → the Task 4 subset PASS.

- [ ] **Step 6: Full suite** → green. (Watch: creating an employer with `max_establishments=1` — confirm no existing test counts total employer users.)

- [ ] **Step 7: Commit**

```bash
git add webapp/app.py webapp/tests/test_reseller_program.py
git commit -m @'
feat(reseller): create-the-account enrollment endpoint + pending pipeline

POST /api/reseller/establishments makes a referred Establishment plus a
no-password employer User and a set-password handover link, stamped with the
reseller id. Self-referral by contact email is blocked. Enrollment list + resend.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

---

## Task 5: Reseller dashboard — read views (backend + frontend)

**Files:**
- Modify: `webapp/app.py` (`/api/reseller/overview|establishments|ecr-activity|earnings|payouts` in the reseller section)
- Create: `webapp/js/reseller.js`
- Modify: `webapp/index.html` (add `<script src="/js/reseller.js"></script>` after `wage-entry-batch.js`)
- Modify: `webapp/js/app.js` (`renderSidebarNav` reseller branch; `navigate` titles; `init` landing branch)
- Test: `webapp/tests/test_reseller_program.py` (backend), then a live browser check.

**Interfaces:**
- Consumes: `get_reseller`, `_reseller_est_or_403`, `sync_subscription_fees_for_year` (existing), `count_ecr_employees_for_month` (existing).
- Produces:
  - `GET /api/reseller/overview` → `{reseller:{full_name,referral_code,upi_id,payout_details_verified}, stats:{establishments,active,collected_this_period,my_share_this_period,paid_to_date_net,next_run_date}, billing_mix:{flat_count,per_employee_count,flat_amount,per_employee_amount}, recent_ecr:[...]}`
  - `GET /api/reseller/establishments` → `{establishments:[{id,code,name,type,billing_mode,fee_display,status,latest_ecr_month,joined}]}`
  - `GET /api/reseller/ecr-activity?scope=current|previous` → `{rows:[{establishment,code,wage_month,employees,filed_at}]}`
  - `GET /api/reseller/earnings` → `{months:[{period,gross,my_share_gross,tds,my_share_net,status,lines:[{establishment,fy,month,fee,my_share}]}]}`
  - `GET /api/reseller/payouts` → `{payouts:[{period,gross_collected,reseller_share_net,status,upi_reference,paid_at}]}`
- Frontend produces pages: `reseller-overview`, `reseller-enroll`, `reseller-establishments`, `reseller-ecr`, `reseller-earnings`, `reseller-payouts`.

- [ ] **Step 1: Write the failing backend test**

```python
def _seed_referred_est_with_paid_fee(test_db, reseller_id, code="ORPAY0000000001"):
    from webapp.database import SubscriptionFee
    owner = User(name="O", email=f"{code.lower()}@x.com", role="employer", is_active=True)
    test_db.add(owner); test_db.commit(); test_db.refresh(owner)
    est = Establishment(user_id=owner.id, code=code, name=f"EST {code}", data="{}",
                        billing_mode="flat_fee", flat_fee_amount=2000,
                        referred_by_reseller_id=reseller_id)
    test_db.add(est); test_db.commit(); test_db.refresh(est)
    fee = SubscriptionFee(establishment_id=est.id, financial_year="2026-27", month="Apr",
                          employee_count=10, amount_due=2000, billing_mode="flat_fee", is_paid=True,
                          paid_date="15-05-2026")
    test_db.add(fee); test_db.commit()
    return est, fee


def test_reseller_overview_and_earnings(reseller_a, test_db):
    _seed_referred_est_with_paid_fee(test_db, reseller_a.user_id)
    ov = reseller_a.get("/api/reseller/overview")
    assert ov.status_code == 200
    assert ov.json()["stats"]["establishments"] >= 1

    er = reseller_a.get("/api/reseller/earnings")
    assert er.status_code == 200
    total_my_share = sum(m["my_share_gross"] for m in er.json()["months"])
    assert total_my_share == 1000.0   # 50% of the single ₹2000 paid fee


def test_reseller_only_sees_own_referrals(reseller_a, test_db):
    # an establishment referred by nobody must not appear
    stray_owner = User(name="S", email="stray@x.com", role="employer", is_active=True)
    test_db.add(stray_owner); test_db.commit(); test_db.refresh(stray_owner)
    test_db.add(Establishment(user_id=stray_owner.id, code="ORNONE0000000000",
                              name="STRAY", data="{}"))
    test_db.commit()
    ests = reseller_a.get("/api/reseller/establishments").json()["establishments"]
    assert all(e["code"] != "ORNONE0000000000" for e in ests)
```

- [ ] **Step 2: Run to verify fail** → 404s.

- [ ] **Step 3: Implement the read endpoints in `webapp/app.py`**

```python
def _reseller_paid_fees(db: Session, reseller_id: int):
    ref_ids = [e.id for e in db.query(Establishment.id).filter(
        Establishment.referred_by_reseller_id == reseller_id).all()]
    if not ref_ids:
        return []
    return db.query(SubscriptionFee).filter(
        SubscriptionFee.establishment_id.in_(ref_ids), SubscriptionFee.is_paid == True).all()  # noqa: E712


def _next_payout_date_iso() -> str:
    today = date.today()
    first_next = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    return first_next.isoformat()


@app.get("/api/reseller/overview")
async def reseller_overview(reseller: User = Depends(get_reseller), db: Session = Depends(get_db)):
    prof = db.query(ResellerProfile).filter(ResellerProfile.user_id == reseller.id).first()
    ests = db.query(Establishment).filter(Establishment.referred_by_reseller_id == reseller.id).all()
    est_ids = [e.id for e in ests]
    paid_fees = _reseller_paid_fees(db, reseller.id)

    # "this period" = fees not yet attached to any ResellerPayoutLine
    paid_ids_on_lines = {l.subscription_fee_id for l in db.query(ResellerPayoutLine.subscription_fee_id).all()
                         if l.subscription_fee_id is not None}
    pending_fees = [f for f in paid_fees if f.id not in paid_ids_on_lines]
    collected = round(sum(f.amount_due for f in pending_fees), 2)

    lifetime_net = db.query(func.coalesce(func.sum(ResellerPayout.reseller_share_net), 0.0)).filter(
        ResellerPayout.reseller_id == reseller.id, ResellerPayout.status == "paid").scalar() or 0.0

    flat = [e for e in ests if (e.billing_mode or "per_employee") == "flat_fee"]
    per_emp = [e for e in ests if (e.billing_mode or "per_employee") == "per_employee"]

    active_ids = {f.establishment_id for f in paid_fees}
    return {
        "reseller": {"full_name": prof.full_name if prof else reseller.name,
                     "referral_code": prof.referral_code if prof else "",
                     "upi_id": prof.upi_id if prof else "",
                     "payout_details_verified": prof.payout_details_verified if prof else False},
        "stats": {"establishments": len(ests), "active": len(active_ids),
                  "collected_this_period": collected,
                  "my_share_this_period": round(collected / 2, 2),
                  "paid_to_date_net": round(lifetime_net, 2),
                  "next_run_date": _next_payout_date_iso()},
        "billing_mix": {"flat_count": len(flat), "per_employee_count": len(per_emp),
                        "flat_amount": round(sum(f.amount_due for f in pending_fees
                                                 if f.establishment_id in {e.id for e in flat}), 2),
                        "per_employee_amount": round(sum(f.amount_due for f in pending_fees
                                                        if f.establishment_id in {e.id for e in per_emp}), 2)},
        "recent_ecr": _reseller_ecr_rows(db, est_ids, limit=8),
    }


def _reseller_ecr_rows(db: Session, est_ids, scope="current", limit=None):
    """Rows from each referred establishment's ECR/wage history. Reuses
    count_ecr_employees_for_month over the establishment's Project years."""
    if not est_ids:
        return []
    rows = []
    ests = db.query(Establishment).filter(Establishment.id.in_(est_ids)).all()
    for est in ests:
        try:
            proj = Project()
            proj.load_from_dict(json.loads(est.data or "{}"))
        except Exception:
            continue
        for yk, yr in (proj.years or {}).items():
            for m_idx in range(12):
                cnt = count_ecr_employees_for_month(proj, yk, m_idx)
                if cnt > 0:
                    rows.append({"establishment": est.name, "code": est.code,
                                 "wage_month": f"{MONTH_SHORT_NAMES[m_idx]} {yk}",
                                 "employees": cnt, "filed_at": None})
    rows.sort(key=lambda r: r["wage_month"], reverse=True)
    return rows[:limit] if limit else rows


@app.get("/api/reseller/establishments")
async def reseller_establishments(reseller: User = Depends(get_reseller), db: Session = Depends(get_db)):
    ests = db.query(Establishment).filter(Establishment.referred_by_reseller_id == reseller.id).all()
    paid_ids = {f.establishment_id for f in _reseller_paid_fees(db, reseller.id)}
    owners = {u.id: u for u in db.query(User).filter(
        User.id.in_([e.user_id for e in ests] or [0])).all()}
    out = []
    for e in ests:
        mode = e.billing_mode or "per_employee"
        fee_display = (f"₹{int(e.flat_fee_amount or 0)}/mo flat" if mode == "flat_fee"
                       else f"₹{int(e.custom_rate_per_employee or 0)}/emp/mo")
        out.append({"id": e.id, "code": e.code, "name": e.name,
                    "type": owners.get(e.user_id).role if owners.get(e.user_id) else "employer",
                    "billing_mode": mode, "fee_display": fee_display,
                    "status": "active" if e.id in paid_ids else "pending",
                    "joined": _isodt(e.created_at)})
    return {"establishments": out}


@app.get("/api/reseller/ecr-activity")
async def reseller_ecr_activity(scope: str = "current", reseller: User = Depends(get_reseller),
                                db: Session = Depends(get_db)):
    est_ids = [e.id for e in db.query(Establishment.id).filter(
        Establishment.referred_by_reseller_id == reseller.id).all()]
    return {"rows": _reseller_ecr_rows(db, est_ids, scope=scope)}


@app.get("/api/reseller/earnings")
async def reseller_earnings(reseller: User = Depends(get_reseller), db: Session = Depends(get_db)):
    prof = db.query(ResellerProfile).filter(ResellerProfile.user_id == reseller.id).first()
    tds_rate = (prof.tds_rate if prof and prof.pan else 0.0) or 0.0

    # settled months = ResellerPayout rows
    months = []
    for po in db.query(ResellerPayout).filter(ResellerPayout.reseller_id == reseller.id
                                              ).order_by(ResellerPayout.period.desc()).all():
        lines = db.query(ResellerPayoutLine).filter(ResellerPayoutLine.payout_id == po.id).all()
        months.append({"period": po.period, "gross": po.gross_collected,
                       "my_share_gross": po.reseller_share_gross, "tds": po.tds_amount,
                       "my_share_net": po.reseller_share_net, "status": po.status,
                       "lines": [{"establishment": l.establishment_name, "fy": l.financial_year,
                                  "month": l.month, "fee": l.fee_amount,
                                  "my_share": l.reseller_share} for l in lines]})

    # current unsettled accrual
    on_lines = {l.subscription_fee_id for l in db.query(ResellerPayoutLine.subscription_fee_id).all()
                if l.subscription_fee_id is not None}
    pending = [f for f in _reseller_paid_fees(db, reseller.id) if f.id not in on_lines]
    if pending:
        est_names = {e.id: e.name for e in db.query(Establishment).filter(
            Establishment.referred_by_reseller_id == reseller.id).all()}
        gross = round(sum(f.amount_due for f in pending), 2)
        share_gross = round(gross / 2, 2)
        tds = round(share_gross * tds_rate / 100, 2)
        months.insert(0, {"period": "accruing", "gross": gross, "my_share_gross": share_gross,
                          "tds": tds, "my_share_net": round(share_gross - tds, 2), "status": "accruing",
                          "lines": [{"establishment": est_names.get(f.establishment_id, "—"),
                                     "fy": f.financial_year, "month": f.month, "fee": f.amount_due,
                                     "my_share": round(f.amount_due / 2, 2)} for f in pending]})
    return {"months": months}


@app.get("/api/reseller/payouts")
async def reseller_payouts(reseller: User = Depends(get_reseller), db: Session = Depends(get_db)):
    rows = db.query(ResellerPayout).filter(ResellerPayout.reseller_id == reseller.id
                                           ).order_by(ResellerPayout.period.desc()).all()
    return {"payouts": [{"period": p.period, "gross_collected": p.gross_collected,
                         "reseller_share_net": p.reseller_share_net, "status": p.status,
                         "upi_reference": p.upi_reference, "paid_at": _isodt(p.paid_at)} for p in rows]}
```

Add `ResellerPayoutLine` to the `from .database import` line. Confirm `count_ecr_employees_for_month` and `MONTH_SHORT_NAMES` are module-level in `app.py` (grep).

- [ ] **Step 4: Run backend tests** → Task 5 subset PASS. Full suite green.

- [ ] **Step 5: Commit backend**

```bash
git add webapp/app.py webapp/tests/test_reseller_program.py
git commit -m @'
feat(reseller): reseller dashboard read endpoints (overview, establishments, ecr, earnings, payouts)

All are rollups of SubscriptionFee / Project ECR data filtered by
referred_by_reseller_id. Earnings shows settled ResellerPayout months plus a
live "accruing" bucket of paid fees not yet on a payout line.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

- [ ] **Step 6: Create `webapp/js/reseller.js`**

Follow the `Admin` IIFE pattern (`const Reseller = (() => { ... })()`), register one page per view, and reset all module-level state at the top of each `render`. Full module:

```javascript
/* ================================================================
   reseller.js — Reseller dashboard (Partner Program)
   Role-gated: only users with role === 'reseller' get these pages.
   ================================================================ */
const Reseller = (() => {
  const esc = (s) => (window.App ? App.esc(s) : String(s == null ? '' : s));
  const money = (n) => '₹' + Number(n || 0).toLocaleString('en-IN');

  function shell(title, bodyHtml) {
    return `<div class="card" style="padding:22px 24px; margin-bottom:16px;">
      <h2 style="margin:0 0 4px; font-size:18px; font-weight:800; color:var(--text1);">${esc(title)}</h2>
    </div>${bodyHtml}`;
  }

  async function renderOverview(c) {
    c.innerHTML = '<div class="page-loading"><div class="spinner"></div></div>';
    let d;
    try { d = await App.get('/api/reseller/overview'); }
    catch (e) { c.innerHTML = shell('My overview', `<div class="card" style="padding:20px;">Could not load.</div>`); return; }
    const s = d.stats, mix = d.billing_mix;
    const verifyWarn = d.reseller.payout_details_verified ? '' :
      `<div class="card" style="padding:12px 16px; margin-bottom:14px; border-left:4px solid var(--amber); background:var(--bg2);">
        Your payout details are not verified yet — the superadmin will confirm your UPI before the first payout.</div>`;
    c.innerHTML = shell('My overview', `
      ${verifyWarn}
      <div class="card" style="padding:14px 16px; margin-bottom:14px; background:var(--bg2); font-size:13px; color:var(--text2);">
        You see every establishment you referred, every ECR it files, and every rupee collected — the same figures the owner sees. Your share is 50% of every subscription payment, paid to <b>${esc(d.reseller.upi_id || 'your UPI')}</b> on the 1st.
      </div>
      <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px;">
        ${statTile('My establishments', s.establishments)}
        ${statTile('Active (paying)', s.active)}
        ${statTile('Collected this period', money(s.collected_this_period))}
        ${statTile('My 50% this period', money(s.my_share_this_period))}
        ${statTile('Paid to me (net, to date)', money(s.paid_to_date_net))}
        ${statTile('Next payout run', s.next_run_date)}
      </div>
      <div class="card" style="padding:16px;">
        <h3 style="margin:0 0 10px; font-size:14px;">Billing mix</h3>
        <div style="font-size:13px; color:var(--text2); line-height:1.9;">
          Flat-fee referrals: <b>${mix.flat_count}</b> — ${money(mix.flat_amount)} this period<br>
          Per-employee referrals: <b>${mix.per_employee_count}</b> — ${money(mix.per_employee_amount)} this period
          <span style="color:var(--text3);">(moves with each month's ECR headcount)</span>
        </div>
      </div>
      <div class="card" style="padding:16px; margin-top:14px;">
        <h3 style="margin:0 0 10px; font-size:14px;">Recent ECR activity</h3>
        ${ecrTable(d.recent_ecr)}
      </div>
    `);
  }

  function statTile(label, val) {
    return `<div class="card" style="padding:14px 16px;">
      <div style="font-size:11px; color:var(--text3); text-transform:uppercase; letter-spacing:.04em;">${esc(label)}</div>
      <div style="font-size:20px; font-weight:800; color:var(--text1); margin-top:4px;">${esc(val)}</div></div>`;
  }
  function ecrTable(rows) {
    if (!rows || !rows.length) return `<p style="color:var(--text3); font-size:13px;">No ECR activity yet.</p>`;
    return `<div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Establishment</th><th>Wage month</th><th style="text-align:right;">Employees</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td>${esc(r.establishment)}<div style="font-size:11px; color:var(--text3); font-family:monospace;">${esc(r.code)}</div></td>
        <td>${esc(r.wage_month)}</td><td style="text-align:right;">${r.employees}</td></tr>`).join('')}</tbody></table></div>`;
  }

  async function renderEnroll(c) {
    c.innerHTML = shell('Enroll an establishment', `
      <div class="card" style="padding:20px; max-width:640px;">
        <div id="rs-enroll-status" style="display:none; font-size:12px; padding:10px 12px; border-radius:var(--radius-sm); margin-bottom:14px;"></div>
        <div class="su-grid-2" style="display:grid; grid-template-columns:1fr 1fr; gap:0 16px;">
          ${field('rs-code', 'Establishment Code *', 'ORBBS1990770000')}
          ${field('rs-name', 'Establishment Name *', 'ODISHA UDYOG')}
          ${field('rs-cov', 'Date of Coverage *', '', 'date')}
          ${field('rs-addr', 'Address', 'City')}
          ${field('rs-cname', 'Contact person *', 'Manoj Das')}
          ${field('rs-cemail', 'Contact email *', 'manoj@company.com', 'email')}
          ${field('rs-cmobile', 'Contact mobile', '9800000000')}
        </div>
        <div style="margin:12px 0 6px; font-weight:700; font-size:13px;">Billing</div>
        <label style="font-size:13px; display:block; margin-bottom:6px;">
          <input type="radio" name="rs-bmode" value="flat_fee" checked onchange="Reseller.onBmode()"> Flat monthly fee</label>
        <label style="font-size:13px; display:block; margin-bottom:6px;">
          <input type="radio" name="rs-bmode" value="per_employee" onchange="Reseller.onBmode()"> Per employee / month</label>
        <div id="rs-flat-wrap">${field('rs-flat', 'Flat fee ₹/month *', '2000', 'number')}</div>
        <div id="rs-peremp-wrap" style="display:none;">
          <label class="form-label" style="font-weight:600;">Per-employee rate ₹ *</label>
          <select id="rs-rate" class="form-input">
            ${[10,20,30,40,50,60,70,80,90,100].map(v => `<option value="${v}">₹${v}</option>`).join('')}
            <option value="custom">Custom (Enterprise)…</option>
          </select>
          <input type="number" id="rs-rate-custom" class="form-input" placeholder="Custom ₹/emp" style="display:none; margin-top:8px;">
        </div>
        <button class="btn btn-primary" style="width:100%; margin-top:16px; padding:11px; font-weight:700;" onclick="Reseller.submitEnroll()">Create the account</button>
        <p style="font-size:11px; color:var(--text3); margin-top:10px;">
          On create: the establishment is made and tagged to you, plus a login for the contact with <b>no password</b>. You'll get a one-time set-password link (7-day expiry) to pass to them — you never see or set their password.</p>
      </div>
      <div id="rs-enroll-result" style="display:none;" class="card"></div>
      <div class="card" style="padding:16px; margin-top:16px;">
        <h3 style="margin:0 0 10px; font-size:14px;">Pending enrollments</h3>
        <div id="rs-pending">Loading…</div>
      </div>
    `);
    loadPending();
  }
  function field(id, label, ph, type) {
    return `<div class="form-group" style="margin-bottom:12px;">
      <label class="form-label" style="font-weight:600;">${esc(label)}</label>
      <input type="${type || 'text'}" id="${id}" class="form-input" placeholder="${esc(ph)}"></div>`;
  }
  function onBmode() {
    const m = document.querySelector('input[name="rs-bmode"]:checked').value;
    document.getElementById('rs-flat-wrap').style.display = m === 'flat_fee' ? '' : 'none';
    document.getElementById('rs-peremp-wrap').style.display = m === 'per_employee' ? '' : 'none';
  }
  function onRateChange() {
    const sel = document.getElementById('rs-rate');
    document.getElementById('rs-rate-custom').style.display = sel.value === 'custom' ? '' : 'none';
  }
  async function submitEnroll() {
    const g = (id) => (document.getElementById(id).value || '').trim();
    const mode = document.querySelector('input[name="rs-bmode"]:checked').value;
    let flat = null, rate = null;
    if (mode === 'flat_fee') flat = Number(g('rs-flat')) || 0;
    else {
      const sv = document.getElementById('rs-rate').value;
      rate = sv === 'custom' ? Number(g('rs-rate-custom')) : Number(sv);
    }
    const body = { code: g('rs-code'), name: g('rs-name'), address: g('rs-addr'),
      coverage_date: g('rs-cov'), contact_name: g('rs-cname'), contact_email: g('rs-cemail'),
      contact_mobile: g('rs-cmobile'), billing_mode: mode, flat_fee_amount: flat,
      custom_rate_per_employee: rate };
    const st = document.getElementById('rs-enroll-status');
    try {
      const r = await App.post('/api/reseller/establishments', body);
      const res = document.getElementById('rs-enroll-result');
      res.style.display = 'block';
      res.style.padding = '16px';
      res.innerHTML = `<h3 style="margin:0 0 8px; font-size:14px;">✅ ${esc(res && body.name)} created</h3>
        <p style="font-size:13px; color:var(--text2);">Send this one-time set-password link to <b>${esc(body.contact_email)}</b> (expires in 7 days):</p>
        <div style="display:flex; gap:8px; margin-top:8px;">
          <input class="form-input" readonly value="${esc(r.set_password_url)}" id="rs-link" style="font-size:12px;">
          <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('rs-link').value); App.toast('Link copied','success')">Copy</button>
        </div>`;
      st.style.display = 'none';
      loadPending();
    } catch (e) {
      st.style.display = 'block';
      st.textContent = e.message || 'Could not create the account.';
      st.style.background = 'rgba(239,68,68,0.12)'; st.style.color = 'var(--red)';
    }
  }
  async function loadPending() {
    const el = document.getElementById('rs-pending');
    if (!el) return;
    try {
      const d = await App.get('/api/reseller/enrollments');
      if (!d.enrollments.length) { el.innerHTML = '<p style="color:var(--text3); font-size:13px;">None.</p>'; return; }
      el.innerHTML = `<div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Establishment</th><th>Contact</th><th>Stage</th><th>Link expires</th><th></th></tr></thead>
        <tbody>${d.enrollments.map(e => `<tr>
          <td>${esc(e.establishment_name)}</td><td>${esc(e.contact_email)}</td>
          <td><span class="badge low">${esc(e.stage.replace(/_/g,' '))}</span></td>
          <td style="font-size:11px; color:var(--text3);">${e.token_expires_at ? new Date(e.token_expires_at).toLocaleDateString() : '—'}</td>
          <td>${['account_created','password_set'].includes(e.stage)
            ? `<button class="btn btn-ghost btn-sm" onclick="Reseller.resend(${e.id})">Resend link</button>` : ''}</td>
        </tr>`).join('')}</tbody></table></div>`;
    } catch (_) { el.innerHTML = 'Could not load.'; }
  }
  async function resend(id) {
    try {
      const r = await App.post(`/api/reseller/enrollments/${id}/resend`, {});
      await App.confirm('New link (copy it now):\n\n' + r.set_password_url, { okText: 'Done', title: 'Set-password link' });
      navigator.clipboard.writeText(r.set_password_url).catch(() => {});
    } catch (_) {}
  }

  async function renderList(c) {
    c.innerHTML = shell('My establishments', '<div class="card" style="padding:16px;" id="rs-list">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/establishments');
      document.getElementById('rs-list').innerHTML = d.establishments.length ? `
        <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Billing</th><th>Status</th></tr></thead>
        <tbody>${d.establishments.map(e => `<tr>
          <td style="font-family:monospace;">${esc(e.code)}</td><td>${esc(e.name)}</td>
          <td>${esc(e.type)}</td><td>${esc(e.fee_display)}</td>
          <td><span class="badge ${e.status === 'active' ? 'success' : 'low'}">${esc(e.status)}</span></td>
        </tr>`).join('')}</tbody></table></div>` : '<p style="color:var(--text3);">No referrals yet.</p>';
    } catch (_) { document.getElementById('rs-list').innerHTML = 'Could not load.'; }
  }

  async function renderEcr(c) {
    c.innerHTML = shell('ECR activity', '<div class="card" style="padding:16px;" id="rs-ecr">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/ecr-activity');
      document.getElementById('rs-ecr').innerHTML = ecrTable(d.rows);
    } catch (_) { document.getElementById('rs-ecr').innerHTML = 'Could not load.'; }
  }

  async function renderEarnings(c) {
    c.innerHTML = shell('My earnings', '<div id="rs-earn">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/earnings');
      document.getElementById('rs-earn').innerHTML = d.months.map(m => `
        <div class="card" style="padding:16px; margin-bottom:12px;">
          <div style="display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px;">
            <b>${esc(m.period === 'accruing' ? 'Accruing (not yet paid)' : m.period)}</b>
            <span class="badge ${m.status === 'paid' ? 'success' : 'low'}">${esc(m.status)}</span>
          </div>
          <div style="font-size:13px; color:var(--text2); margin:8px 0;">
            Gross ${money(m.gross)} · my 50% ${money(m.my_share_gross)} · TDS ${money(m.tds)} · <b>net ${money(m.my_share_net)}</b></div>
          <table class="data-table" style="width:100%; font-size:12px;">
            <thead><tr><th>Establishment</th><th>Month</th><th style="text-align:right;">Fee</th><th style="text-align:right;">My 50%</th></tr></thead>
            <tbody>${m.lines.map(l => `<tr><td>${esc(l.establishment)}</td><td>${esc(l.month)} ${esc(l.fy)}</td>
              <td style="text-align:right;">${money(l.fee)}</td><td style="text-align:right;">${money(l.my_share)}</td></tr>`).join('')}</tbody>
          </table>
        </div>`).join('') || '<div class="card" style="padding:16px;">No earnings yet.</div>';
    } catch (_) { document.getElementById('rs-earn').innerHTML = 'Could not load.'; }
  }

  async function renderPayouts(c) {
    c.innerHTML = shell('Payout history', '<div class="card" style="padding:16px;" id="rs-po">Loading…</div>');
    try {
      const d = await App.get('/api/reseller/payouts');
      document.getElementById('rs-po').innerHTML = (d.payouts.length ? `
        <table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Period</th><th style="text-align:right;">Net to me</th><th>Status</th><th>UTR</th><th>Paid</th></tr></thead>
        <tbody>${d.payouts.map(p => `<tr><td>${esc(p.period)}</td>
          <td style="text-align:right;">${money(p.reseller_share_net)}</td>
          <td><span class="badge ${p.status === 'paid' ? 'success' : 'low'}">${esc(p.status)}</span></td>
          <td style="font-family:monospace; font-size:11px;">${esc(p.upi_reference || '—')}</td>
          <td>${p.paid_at ? new Date(p.paid_at).toLocaleDateString() : '—'}</td></tr>`).join('')}</tbody></table>`
        : '<p style="color:var(--text3);">No payouts yet.</p>') +
        `<p style="font-size:11px; color:var(--text3); margin-top:12px;">How it works: on the 1st of each month a job totals the previous period's paid subscription fees for your referrals, splits 50:50, deducts TDS if a PAN is on file, and the owner transfers your net to your UPI, recording the UTR here.</p>`;
    } catch (_) { document.getElementById('rs-po').innerHTML = 'Could not load.'; }
  }

  if (typeof App !== 'undefined' && App.registerPage) {
    App.registerPage('reseller-overview', renderOverview);
    App.registerPage('reseller-enroll', renderEnroll);
    App.registerPage('reseller-establishments', renderList);
    App.registerPage('reseller-ecr', renderEcr);
    App.registerPage('reseller-earnings', renderEarnings);
    App.registerPage('reseller-payouts', renderPayouts);
  }
  return { onBmode, onRateChange, submitEnroll, resend };
})();
```

Add `onchange="Reseller.onRateChange()"` to the `#rs-rate` select (fix inline in the template above — it's referenced but not wired; add it).

- [ ] **Step 7: Wire the frontend in `webapp/index.html`**

After line 130 (`<script src="/js/wage-entry-batch.js"></script>`):

```html
    <script src="/js/reseller.js"></script>
    <script src="/js/referral-program.js"></script>
```

(referral-program.js is created in Task 7; a missing file just 404s harmlessly, but to avoid a console error, add its `<script>` line in Task 7 instead. For Task 5 add only the reseller.js line.)

- [ ] **Step 8: Wire role routing in `webapp/js/app.js`**

In `renderSidebarNav()`, at the very top of the function body, before the `if (isSuper)` block:

```javascript
    if (user && user.role === 'reseller') {
      nav.innerHTML = [
        navItem('reseller-overview', '📊', 'My Overview'),
        navItem('reseller-enroll', '➕', 'Enroll Establishment'),
        navItem('reseller-establishments', '🏢', 'My Establishments'),
        navItem('reseller-ecr', '🗂️', 'ECR Activity'),
        navItem('reseller-earnings', '💰', 'My Earnings'),
        navItem('reseller-payouts', '🧾', 'Payout History'),
      ].join('');
      nav.querySelectorAll('.nav-item').forEach(el => el.addEventListener('click', (e) => {
        e.preventDefault(); navigate(el.dataset.page);
      }));
      return;
    }
```

Add a small helper near `renderSidebarNav`:

```javascript
    function navItem(page, icon, label) {
      return `<a class="nav-item ${currentPage === page ? 'active' : ''}" data-page="${page}">
        <span class="nav-icon">${icon}</span><span>${label}</span></a>`;
    }
```

In `navigate()`'s `titles` map, add:

```javascript
      'reseller-overview': '📊 My Overview',
      'reseller-enroll': '➕ Enroll Establishment',
      'reseller-establishments': '🏢 My Establishments',
      'reseller-ecr': '🗂️ ECR Activity',
      'reseller-earnings': '💰 My Earnings',
      'reseller-payouts': '🧾 Payout History',
```

In `init()`, in the landing-page block, add a branch before the `isSuperadmin()` check:

```javascript
      if (currentUser && currentUser.role === 'reseller') {
        navigate((currentPage && currentPage.startsWith('reseller-')) ? currentPage : 'reseller-overview');
      } else if (isSuperadmin()) {
```

(and adjust the existing `if (isSuperadmin())` to `else if`.)

Also: `refreshTopbar()` calls `GET /api/establishment` which will 404 for a reseller — wrap is already in `try/catch (_){}` so it's harmless; verify in the browser check that no uncaught error appears.

- [ ] **Step 9: Live browser verification**

```
1. preview_start {name: "epf-local"} — if .claude/launch.json has no such entry, create it:
   { "version": "0.0.1", "configurations": [
     { "name": "epf-local", "runtimeExecutable": "python",
       "runtimeArgs": ["-m","uvicorn","webapp.app:app","--port","8030"], "port": 8030 }]}
   Set DATABASE_URL to a local sqlite copy first (see memory/feedback_local_db_safety.md):
   copy local_dev.db to a scratch db, export DATABASE_URL=sqlite:///./local_qaP.db
2. In a python shell against that DB: create a superadmin, enrol a reseller via
   POST /api/admin/resellers, open the returned set_password_url in the browser tab,
   set a password, then log in as the reseller.
3. Confirm: sidebar shows only the 6 reseller items; My Overview loads with the
   transparency banner + stat tiles; Enroll Establishment form toggles flat/per-employee;
   submitting creates an establishment and shows the copyable set-password link;
   Pending enrollments table shows the new row; My Establishments lists it.
4. read_console_messages — no uncaught errors.
5. computer screenshot of My Overview + Enroll — attach to the user via SendUserFile.
6. Stop the server, delete the scratch db.
```

- [ ] **Step 10: Commit**

```bash
git add webapp/js/reseller.js webapp/index.html webapp/js/app.js
git commit -m @'
feat(reseller): reseller SPA dashboard (overview, enroll, establishments, ECR, earnings, payouts)

Role-gated nav + landing page for role=reseller. Enroll form drives the
create-the-account endpoint and surfaces the one-time set-password link with a
copy button. All views are read-only rollups.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

---

## Task 6: Monthly payout computation + cron

**Files:**
- Create: `webapp/reseller_payout.py`
- Create: `scripts/run_reseller_payouts.py`
- Create: `.github/workflows/reseller-payout-run.yml`
- Test: `webapp/tests/test_reseller_program.py`

**Interfaces:**
- Consumes: `ResellerProfile`, `ResellerPayout`, `ResellerPayoutLine`, `Establishment`, `SubscriptionFee` (Task 1).
- Produces:
  - `webapp.reseller_payout.compute_payouts_for_period(db, period_label: str) -> list[dict]`
    - For each `ResellerProfile` with `status='active'`: gather every `SubscriptionFee` where `establishment.referred_by_reseller_id == reseller_id`, `is_paid == True`, and `fee.id` not already on any `ResellerPayoutLine`. If the set is empty, skip. Otherwise: `gross = sum(amount_due)`, `share_gross = round(gross/2, 2)`, `tds = round(share_gross * tds_rate/100, 2)` when `pan` non-empty else `0`, `share_net = share_gross - tds`, `owner_share = gross - share_gross`. Create one `ResellerPayout` (`status='scheduled'`, `period=period_label`, `upi_id` snapshot) + one `ResellerPayoutLine` per fee. Return a summary list.
    - Idempotent: because lines are keyed 1:1 to `subscription_fee_id` (unique), a second run in the same period picks up only fees paid since the first run. If a `ResellerPayout` already exists for `(reseller_id, period_label)`, attach new lines to it and update its totals rather than violating the unique constraint.

- [ ] **Step 1: Write the failing test**

```python
from webapp.reseller_payout import compute_payouts_for_period
from webapp.database import ResellerPayout, ResellerPayoutLine, SubscriptionFee


def test_compute_payout_splits_50_50_with_tds(reseller_a, test_db):
    est, fee = _seed_referred_est_with_paid_fee(test_db, reseller_a.user_id, code="ORCMP0000000001")
    # reseller_a fixture has pan set -> 10% TDS applies
    summary = compute_payouts_for_period(test_db, "2026-05")
    assert len(summary) == 1
    po = test_db.query(ResellerPayout).filter(ResellerPayout.reseller_id == reseller_a.user_id).first()
    assert po.gross_collected == 2000.0
    assert po.reseller_share_gross == 1000.0
    assert po.tds_amount == 100.0
    assert po.reseller_share_net == 900.0
    assert po.owner_share == 1000.0
    assert po.status == "scheduled"
    lines = test_db.query(ResellerPayoutLine).filter(ResellerPayoutLine.payout_id == po.id).all()
    assert len(lines) == 1 and lines[0].subscription_fee_id == fee.id


def test_compute_payout_is_idempotent(reseller_a, test_db):
    _seed_referred_est_with_paid_fee(test_db, reseller_a.user_id, code="ORCMP0000000002")
    compute_payouts_for_period(test_db, "2026-05")
    n1 = test_db.query(ResellerPayoutLine).count()
    compute_payouts_for_period(test_db, "2026-05")   # nothing new paid
    n2 = test_db.query(ResellerPayoutLine).count()
    assert n1 == n2


def test_compute_payout_skips_unpaid_and_unreferred(reseller_a, test_db):
    owner = User(name="U", email="unpaidcmp@x.com", role="employer", is_active=True)
    test_db.add(owner); test_db.commit(); test_db.refresh(owner)
    est = Establishment(user_id=owner.id, code="ORCMP0000000003", name="X", data="{}",
                        referred_by_reseller_id=reseller_a.user_id)
    test_db.add(est); test_db.commit(); test_db.refresh(est)
    test_db.add(SubscriptionFee(establishment_id=est.id, financial_year="2026-27", month="Apr",
                                amount_due=5000, is_paid=False, billing_mode="flat_fee"))
    test_db.commit()
    summary = compute_payouts_for_period(test_db, "2026-06")
    assert summary == []


def test_compute_payout_no_pan_no_tds(test_db, client):
    from webapp.database import ResellerProfile
    u = User(name="NoPan", email="nopan-r@x.com", role="reseller", is_active=True)
    test_db.add(u); test_db.commit(); test_db.refresh(u)
    test_db.add(ResellerProfile(user_id=u.id, full_name="NOPAN", mobile="1", email="nopan-r@x.com",
                                referral_code="NP9999", upi_id="np@ok", pan="", payout_details_verified=True))
    test_db.commit()
    _seed_referred_est_with_paid_fee(test_db, u.id, code="ORCMP0000000004")
    compute_payouts_for_period(test_db, "2026-07")
    po = test_db.query(ResellerPayout).filter(ResellerPayout.reseller_id == u.id).first()
    assert po.tds_amount == 0.0 and po.reseller_share_net == po.reseller_share_gross
```

- [ ] **Step 2: Run to verify fail** → `ModuleNotFoundError: webapp.reseller_payout`.

- [ ] **Step 3: Create `webapp/reseller_payout.py`**

```python
"""Monthly 50:50 reseller payout computation.

v1 is manual-settlement: this only writes ResellerPayout / ResellerPayoutLine
rows at status='scheduled'. The owner transfers each reseller's net to their UPI
by hand and marks the row 'paid' with a UTR from the admin UI. No payout-API call
lives here.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from webapp.database import (
    ResellerProfile, ResellerPayout, ResellerPayoutLine,
    Establishment, SubscriptionFee,
)


def _round2(x: float) -> float:
    return round(float(x or 0.0), 2)


def compute_payouts_for_period(db: Session, period_label: str) -> list:
    """period_label is 'YYYY-MM' -- a bookkeeping label for the run. Fee selection
    is by 'paid and not yet on a payout line', so late payments are always caught
    on the next run regardless of which month they land in."""
    already_lined = {
        row[0] for row in db.query(ResellerPayoutLine.subscription_fee_id).all()
        if row[0] is not None
    }
    summary = []

    for prof in db.query(ResellerProfile).filter(ResellerProfile.status == "active").all():
        est_rows = db.query(Establishment).filter(
            Establishment.referred_by_reseller_id == prof.user_id
        ).all()
        if not est_rows:
            continue
        est_by_id = {e.id: e for e in est_rows}

        fees = db.query(SubscriptionFee).filter(
            SubscriptionFee.establishment_id.in_(list(est_by_id.keys())),
            SubscriptionFee.is_paid == True,  # noqa: E712
        ).all()
        new_fees = [f for f in fees if f.id not in already_lined]
        if not new_fees:
            continue

        gross = _round2(sum(f.amount_due for f in new_fees))
        share_gross = _round2(gross / 2)
        tds_rate = (prof.tds_rate or 0.0) if (prof.pan or "").strip() else 0.0
        tds = _round2(share_gross * tds_rate / 100.0)
        share_net = _round2(share_gross - tds)
        owner_share = _round2(gross - share_gross)

        payout = db.query(ResellerPayout).filter(
            ResellerPayout.reseller_id == prof.user_id,
            ResellerPayout.period == period_label,
        ).first()
        if payout is None:
            payout = ResellerPayout(
                reseller_id=prof.user_id, period=period_label,
                gross_collected=gross, reseller_share_gross=share_gross,
                tds_amount=tds, reseller_share_net=share_net, owner_share=owner_share,
                status="scheduled", upi_id=prof.upi_id, run_at=datetime.utcnow(),
            )
            db.add(payout)
            db.flush()
        else:
            payout.gross_collected = _round2(payout.gross_collected + gross)
            payout.reseller_share_gross = _round2(payout.reseller_share_gross + share_gross)
            payout.tds_amount = _round2(payout.tds_amount + tds)
            payout.reseller_share_net = _round2(payout.reseller_share_net + share_net)
            payout.owner_share = _round2(payout.owner_share + owner_share)

        for f in new_fees:
            est = est_by_id.get(f.establishment_id)
            db.add(ResellerPayoutLine(
                payout_id=payout.id, subscription_fee_id=f.id,
                establishment_id=f.establishment_id,
                establishment_name=est.name if est else None,
                financial_year=f.financial_year, month=f.month,
                fee_amount=_round2(f.amount_due), reseller_share=_round2(f.amount_due / 2),
            ))
            already_lined.add(f.id)

        db.commit()
        summary.append({"reseller_id": prof.user_id, "period": period_label,
                        "gross": gross, "net_to_reseller": share_net, "fees": len(new_fees)})

    return summary
```

- [ ] **Step 4: Run tests** → Task 6 subset PASS. Full suite green.

- [ ] **Step 5: Create `scripts/run_reseller_payouts.py`**

```python
#!/usr/bin/env python3
"""Monthly reseller payout run. Computes each active reseller's 50% (less TDS) of
the previous period's paid subscription fees into scheduled ResellerPayout rows.
Settlement is manual -- see webapp/reseller_payout.py. Runs via
.github/workflows/reseller-payout-run.yml.

Env: DATABASE_URL (production Neon). Optional: HEALTHCHECKS_PING_URL, PAYOUT_PERIOD
(YYYY-MM; defaults to the previous calendar month).
"""
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def _prev_month_label() -> str:
    today = date.today()
    first_this = today.replace(day=1)
    last_prev = first_this.replace(day=1)
    y, m = last_prev.year, last_prev.month - 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y:04d}-{m:02d}"


def _ping(ok: bool):
    url = (os.environ.get("HEALTHCHECKS_PING_URL") or "").strip()
    if not url:
        return
    try:
        urllib.request.urlopen(url if ok else url.rstrip("/") + "/fail", timeout=10)
    except Exception:
        pass


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 1
    from webapp.database import SessionLocal
    from webapp.reseller_payout import compute_payouts_for_period

    period = os.environ.get("PAYOUT_PERIOD") or _prev_month_label()
    db = SessionLocal()
    try:
        summary = compute_payouts_for_period(db, period)
    finally:
        db.close()

    total_net = sum(s["net_to_reseller"] for s in summary)
    print(f"Period {period}: {len(summary)} payout row(s), total net to resellers ₹{total_net:.2f}")
    for s in summary:
        print(f"  reseller {s['reseller_id']}: {s['fees']} fees, gross ₹{s['gross']:.2f}, net ₹{s['net_to_reseller']:.2f}")
    _ping(True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"payout run failed: {e}", file=sys.stderr)
        _ping(False)
        sys.exit(1)
```

- [ ] **Step 6: Create `.github/workflows/reseller-payout-run.yml`**

```yaml
name: Monthly Reseller Payout Run

on:
  schedule:
    # 01:00 UTC on the 1st = 06:30 IST on the 1st. Exact minute is not important --
    # this only writes 'scheduled' rows; the owner settles them by hand.
    - cron: '0 1 1 * *'
  workflow_dispatch:
    inputs:
      period:
        description: 'Period label YYYY-MM (blank = previous month)'
        required: false

jobs:
  payout:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r webapp/requirements.txt
      - name: Run reseller payout computation
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          HEALTHCHECKS_PING_URL: ${{ secrets.RESELLER_PAYOUT_HEALTHCHECK_URL }}
          PAYOUT_PERIOD: ${{ github.event.inputs.period }}
        run: python3 scripts/run_reseller_payouts.py
```

- [ ] **Step 7: Commit** (workflow-file push — run `gh auth refresh -h github.com -s workflow` first if the push is rejected)

```bash
git add webapp/reseller_payout.py scripts/run_reseller_payouts.py .github/workflows/reseller-payout-run.yml webapp/tests/test_reseller_program.py
git commit -m @'
feat(reseller): monthly 50:50 payout computation + GitHub Actions cron

compute_payouts_for_period selects paid subscription fees not yet on a payout
line, splits 50:50 on gross, deducts TDS when a PAN is on file, and writes
scheduled ResellerPayout rows. Idempotent. Settlement stays manual in v1.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

---

## Task 7: Owner "Referral Program" admin section

**Files:**
- Modify: `webapp/app.py` (`/api/admin/referral-program/overview|establishments|ecr-activity`, `/api/admin/payouts`, `/api/admin/payouts/{id}/mark-paid`)
- Create: `webapp/js/referral-program.js`
- Modify: `webapp/index.html` (add `<script src="/js/referral-program.js"></script>`)
- Modify: `webapp/js/app.js` (`renderSidebarNav` superadmin branch — add a "Referral Program" nav item under the Admin Dashboard item; `titles` map; `navigate` already handles unknown → registered page)
- Modify: `docs/superpowers/specs/2026-09-10-partner-program-design.md` (Status line)
- Test: `webapp/tests/test_reseller_program.py` + live browser check

**Interfaces:**
- Consumes: everything from Tasks 1/3/5/6, `get_superadmin`.
- Produces:
  - `GET /api/admin/referral-program/overview` → `{stats:{active_resellers,referral_count,collected_this_period,flat_vs_per_employee:{flat,per_employee},owner_share_this_period,payouts_due,next_run_date}, resellers:[<same shape as /api/admin/resellers rows + your50/their50 this period + payout_status>], recent_ecr:[...]}`
  - `GET /api/admin/referral-program/establishments` → `{establishments:[{id,code,name,type,reseller,reseller_code,billing_mode,fee_display,status,latest_ecr,joined}], per_employee:[{...rate,headcount,fee,owner_share}], pending:[{reseller,establishment_name,contact_email,stage,created_at}]}`
  - `GET /api/admin/referral-program/ecr-activity?scope=current|previous`
  - `GET /api/admin/payouts?status=` → `{payouts:[{id,reseller,period,gross_collected,reseller_share_net,owner_share,status,upi_id,upi_reference,run_at,paid_at}]}`
  - `POST /api/admin/payouts/{id}/mark-paid` `{upi_reference: str}` → `{ok}`; sets `status='paid'`, `upi_reference`, `paid_at=now`. Guard: only from `status='scheduled'` or `'failed'`.
  - `POST /api/admin/payouts/{id}/mark-failed` `{notes?: str}` → `{ok}` (sets `status='failed'`).

- [ ] **Step 1: Write the failing test**

```python
def test_admin_referral_overview_and_mark_paid(superadmin_session, reseller_a, test_db):
    _seed_referred_est_with_paid_fee(test_db, reseller_a.user_id, code="ORADM0000000001")
    compute_payouts_for_period(test_db, "2026-05")

    ov = superadmin_session.get("/api/admin/referral-program/overview")
    assert ov.status_code == 200
    assert ov.json()["stats"]["active_resellers"] >= 1

    lst = superadmin_session.get("/api/admin/payouts").json()["payouts"]
    assert len(lst) == 1 and lst[0]["status"] == "scheduled"
    pid = lst[0]["id"]

    mp = superadmin_session.post(f"/api/admin/payouts/{pid}/mark-paid",
                                 json={"upi_reference": "AXISU12345678"})
    assert mp.status_code == 200
    from webapp.database import ResellerPayout
    po = test_db.query(ResellerPayout).filter(ResellerPayout.id == pid).first()
    test_db.refresh(po)
    assert po.status == "paid" and po.upi_reference == "AXISU12345678" and po.paid_at is not None


def test_admin_referral_establishments_pending(superadmin_session, reseller_a):
    reseller_a.post("/api/reseller/establishments", json=_create_est_payload(
        code="ORADM0000000002", contact_email="adm2@x.com"))
    d = superadmin_session.get("/api/admin/referral-program/establishments").json()
    assert any(e["code"] == "ORADM0000000002" for e in d["establishments"])
    assert any(p["contact_email"] == "adm2@x.com" for p in d["pending"])


def test_admin_payouts_forbidden_for_reseller(reseller_a):
    assert reseller_a.get("/api/admin/payouts").status_code == 403
```

- [ ] **Step 2: Run to verify fail** → 404 / 403.

- [ ] **Step 3: Implement the admin endpoints**

```python
class MarkPaidIn(BaseModel):
    upi_reference: str


class MarkFailedIn(BaseModel):
    notes: Optional[str] = None


@app.get("/api/admin/referral-program/overview")
async def admin_referral_overview(admin: User = Depends(get_superadmin), db: Session = Depends(get_db)):
    profs = db.query(ResellerProfile).all()
    all_ref_ests = db.query(Establishment).filter(
        Establishment.referred_by_reseller_id.isnot(None)).all()
    est_by_reseller = {}
    for e in all_ref_ests:
        est_by_reseller.setdefault(e.referred_by_reseller_id, []).append(e)

    on_lines = {r[0] for r in db.query(ResellerPayoutLine.subscription_fee_id).all() if r[0] is not None}
    rows, collected, owner_share, flat_amt, pe_amt = [], 0.0, 0.0, 0.0, 0.0
    for prof in profs:
        ests = est_by_reseller.get(prof.user_id, [])
        est_ids = [e.id for e in ests]
        pending_fees = []
        if est_ids:
            pending_fees = [f for f in db.query(SubscriptionFee).filter(
                SubscriptionFee.establishment_id.in_(est_ids),
                SubscriptionFee.is_paid == True).all() if f.id not in on_lines]  # noqa: E712
        g = round(sum(f.amount_due for f in pending_fees), 2)
        collected += g
        owner_share += round(g / 2, 2)
        flat_ids = {e.id for e in ests if (e.billing_mode or "per_employee") == "flat_fee"}
        flat_amt += sum(f.amount_due for f in pending_fees if f.establishment_id in flat_ids)
        pe_amt += sum(f.amount_due for f in pending_fees if f.establishment_id not in flat_ids)
        last_payout = db.query(ResellerPayout).filter(
            ResellerPayout.reseller_id == prof.user_id).order_by(ResellerPayout.period.desc()).first()
        rows.append({"id": prof.user_id, "full_name": prof.full_name, "referral_code": prof.referral_code,
                     "upi_id": prof.upi_id, "payout_details_verified": prof.payout_details_verified,
                     "referral_count": len(ests), "collected_this_period": g,
                     "your_50": round(g / 2, 2), "their_50": round(g / 2, 2),
                     "payout_status": last_payout.status if last_payout else "—"})

    payouts_due = db.query(ResellerPayout).filter(ResellerPayout.status == "scheduled").count()
    return {"stats": {"active_resellers": sum(1 for p in profs if p.status == "active"),
                      "referral_count": len(all_ref_ests),
                      "collected_this_period": round(collected, 2),
                      "flat_vs_per_employee": {"flat": round(flat_amt, 2), "per_employee": round(pe_amt, 2)},
                      "owner_share_this_period": round(owner_share, 2),
                      "payouts_due": payouts_due, "next_run_date": _next_payout_date_iso()},
            "resellers": rows,
            "recent_ecr": _reseller_ecr_rows(db, [e.id for e in all_ref_ests], limit=10)}


@app.get("/api/admin/referral-program/establishments")
async def admin_referral_establishments(admin: User = Depends(get_superadmin), db: Session = Depends(get_db)):
    ests = db.query(Establishment).filter(Establishment.referred_by_reseller_id.isnot(None)).all()
    prof_by_id = {p.user_id: p for p in db.query(ResellerProfile).all()}
    owners = {u.id: u for u in db.query(User).filter(
        User.id.in_([e.user_id for e in ests] or [0])).all()}
    paid_ids = set()
    if ests:
        paid_ids = {f.establishment_id for f in db.query(SubscriptionFee.establishment_id).filter(
            SubscriptionFee.establishment_id.in_([e.id for e in ests]),
            SubscriptionFee.is_paid == True).all()}  # noqa: E712

    out, per_emp = [], []
    for e in ests:
        prof = prof_by_id.get(e.referred_by_reseller_id)
        mode = e.billing_mode or "per_employee"
        fee_display = (f"₹{int(e.flat_fee_amount or 0)}/mo" if mode == "flat_fee"
                       else f"₹{int(e.custom_rate_per_employee or 0)}/emp")
        row = {"id": e.id, "code": e.code, "name": e.name,
               "type": owners[e.user_id].role if e.user_id in owners else "employer",
               "reseller": prof.full_name if prof else "—",
               "reseller_code": prof.referral_code if prof else "—",
               "billing_mode": mode, "fee_display": fee_display,
               "status": "active" if e.id in paid_ids else "pending",
               "joined": _isodt(e.created_at)}
        out.append(row)
        if mode == "per_employee":
            try:
                proj = Project(); proj.load_from_dict(json.loads(e.data or "{}"))
                latest_fy = max(proj.years.keys()) if proj.years else None
                headcount = 0
                if latest_fy:
                    headcount = max((count_ecr_employees_for_month(proj, latest_fy, m) for m in range(12)), default=0)
            except Exception:
                headcount = 0
            rate = e.custom_rate_per_employee or 0
            per_emp.append({"name": e.name, "reseller": prof.full_name if prof else "—",
                            "rate": rate, "headcount": headcount, "fee": rate * headcount,
                            "owner_share": round(rate * headcount / 2, 2)})

    pending = []
    for enr in db.query(Enrollment).filter(Enrollment.method == "create_handover",
                                           Enrollment.stage != "active").all():
        prof = prof_by_id.get(enr.reseller_id)
        pending.append({"reseller": prof.full_name if prof else "—",
                        "establishment_name": next((e.name for e in ests if e.id == enr.establishment_id), "—"),
                        "contact_email": enr.contact_email, "stage": enr.stage,
                        "created_at": _isodt(enr.created_at)})
    return {"establishments": out, "per_employee": per_emp, "pending": pending}


@app.get("/api/admin/referral-program/ecr-activity")
async def admin_referral_ecr(scope: str = "current", admin: User = Depends(get_superadmin),
                             db: Session = Depends(get_db)):
    est_ids = [e.id for e in db.query(Establishment.id).filter(
        Establishment.referred_by_reseller_id.isnot(None)).all()]
    return {"rows": _reseller_ecr_rows(db, est_ids, scope=scope)}


@app.get("/api/admin/payouts")
async def admin_list_payouts(status: Optional[str] = None, admin: User = Depends(get_superadmin),
                             db: Session = Depends(get_db)):
    q = db.query(ResellerPayout)
    if status:
        q = q.filter(ResellerPayout.status == status)
    names = {p.user_id: p.full_name for p in db.query(ResellerProfile).all()}
    rows = q.order_by(ResellerPayout.run_at.desc()).all()
    return {"payouts": [{"id": p.id, "reseller": names.get(p.reseller_id, f"#{p.reseller_id}"),
                         "period": p.period, "gross_collected": p.gross_collected,
                         "reseller_share_gross": p.reseller_share_gross, "tds_amount": p.tds_amount,
                         "reseller_share_net": p.reseller_share_net, "owner_share": p.owner_share,
                         "status": p.status, "upi_id": p.upi_id, "upi_reference": p.upi_reference,
                         "run_at": _isodt(p.run_at), "paid_at": _isodt(p.paid_at)} for p in rows]}


@app.post("/api/admin/payouts/{payout_id}/mark-paid")
async def admin_mark_payout_paid(payout_id: int, d: MarkPaidIn, admin: User = Depends(get_superadmin),
                                 db: Session = Depends(get_db)):
    po = db.query(ResellerPayout).filter(ResellerPayout.id == payout_id).first()
    if not po:
        raise HTTPException(404, "Payout not found.")
    if po.status == "paid":
        raise HTTPException(400, "This payout is already marked paid.")
    if not d.upi_reference.strip():
        raise HTTPException(400, "A UPI reference / UTR is required.")
    po.status = "paid"
    po.upi_reference = d.upi_reference.strip()
    po.paid_at = datetime.utcnow()
    db.commit()
    log_activity(db, admin.id, None, "reseller_payout_paid",
                 f"Marked payout #{po.id} ({po.period}) paid to reseller #{po.reseller_id}, UTR {po.upi_reference}",
                 {"payout_id": po.id, "reseller_id": po.reseller_id, "net": po.reseller_share_net})
    return {"ok": True}


@app.post("/api/admin/payouts/{payout_id}/mark-failed")
async def admin_mark_payout_failed(payout_id: int, d: MarkFailedIn, admin: User = Depends(get_superadmin),
                                   db: Session = Depends(get_db)):
    po = db.query(ResellerPayout).filter(ResellerPayout.id == payout_id).first()
    if not po:
        raise HTTPException(404, "Payout not found.")
    po.status = "failed"
    if d.notes:
        po.notes = d.notes.strip()
    db.commit()
    log_activity(db, admin.id, None, "reseller_payout_failed",
                 f"Marked payout #{po.id} failed", {"payout_id": po.id})
    return {"ok": True}
```

- [ ] **Step 4: Run tests** → Task 7 subset PASS. Full suite green.

- [ ] **Step 5: Create `webapp/js/referral-program.js`**

Same IIFE + `App.registerPage` pattern. One page `referral-program` with an in-page tab strip (overview / resellers / establishments / ECR / payouts), matching how `Admin` does `activeTab`. Key parts:

```javascript
/* referral-program.js — Superadmin "Referral Program" section (Partner Program) */
const ReferralProgram = (() => {
  let tab = 'overview';
  const esc = (s) => App.esc(s);
  const money = (n) => '₹' + Number(n || 0).toLocaleString('en-IN');

  async function render(c) {
    tab = (App.currentPage === 'referral-program') ? tab : 'overview';
    c.innerHTML = `
      <div class="card" style="padding:16px 20px; margin-bottom:14px; display:flex; gap:8px; flex-wrap:wrap;">
        ${['overview','resellers','establishments','ecr','payouts'].map(t =>
          `<button class="btn btn-sm ${tab===t?'btn-primary':'btn-ghost'}" onclick="ReferralProgram.go('${t}')">${t[0].toUpperCase()+t.slice(1)}</button>`).join('')}
      </div>
      <div id="rp-body"><div class="page-loading"><div class="spinner"></div></div></div>`;
    const body = document.getElementById('rp-body');
    try {
      if (tab === 'overview') return void (body.innerHTML = await overviewHtml());
      if (tab === 'resellers') return void (body.innerHTML = await resellersHtml());
      if (tab === 'establishments') return void (body.innerHTML = await estHtml());
      if (tab === 'ecr') return void (body.innerHTML = await ecrHtml());
      if (tab === 'payouts') return void (body.innerHTML = await payoutsHtml());
    } catch (e) { body.innerHTML = `<div class="card" style="padding:20px;">Could not load: ${esc(e.message)}</div>`; }
  }
  function go(t) { tab = t; render(document.getElementById('content')); }

  async function overviewHtml() {
    const d = await App.get('/api/admin/referral-program/overview'); const s = d.stats;
    return `<div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px;">
      ${tile('Active resellers', s.active_resellers)}${tile('Referred establishments', s.referral_count)}
      ${tile('Collected this period', money(s.collected_this_period))}
      ${tile('Your 50% this period', money(s.owner_share_this_period))}
      ${tile('Payouts due', s.payouts_due)}${tile('Next run', s.next_run_date)}</div>
      <div class="card" style="padding:16px; margin-bottom:14px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Flat vs per-employee (this period)</h3>
        <div style="font-size:13px; color:var(--text2);">Flat ${money(s.flat_vs_per_employee.flat)} · Per-employee ${money(s.flat_vs_per_employee.per_employee)}</div></div>
      <div class="card" style="padding:16px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Resellers</h3>
        <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
        <thead><tr><th>Reseller</th><th>Code</th><th>UPI</th><th>Refs</th><th style="text-align:right;">Collected</th><th style="text-align:right;">Their 50%</th><th>Last payout</th></tr></thead>
        <tbody>${d.resellers.map(r => `<tr><td>${esc(r.full_name)} ${r.payout_details_verified?'✅':'⏳'}</td>
          <td style="font-family:monospace;">${esc(r.referral_code)}</td><td>${esc(r.upi_id||'—')}</td>
          <td>${r.referral_count}</td><td style="text-align:right;">${money(r.collected_this_period)}</td>
          <td style="text-align:right;">${money(r.their_50)}</td><td>${esc(r.payout_status)}</td></tr>`).join('')}</tbody></table></div></div>`;
  }
  function tile(l,v){return `<div class="card" style="padding:14px 16px;"><div style="font-size:11px; color:var(--text3); text-transform:uppercase;">${esc(l)}</div><div style="font-size:20px; font-weight:800; margin-top:4px;">${esc(v)}</div></div>`;}

  async function resellersHtml() {
    const d = await App.get('/api/admin/resellers');
    return `<div class="card" style="padding:16px;">
      <button class="btn btn-primary btn-sm" style="margin-bottom:12px;" onclick="ReferralProgram.enrolForm()">➕ Enrol a reseller</button>
      <div id="rp-enrol"></div>
      <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Name</th><th>Code</th><th>Email</th><th>Payout</th><th>Refs</th><th style="text-align:right;">MRR</th><th style="text-align:right;">Paid (net)</th><th></th></tr></thead>
      <tbody>${d.resellers.map(r => `<tr><td>${esc(r.full_name)}</td><td style="font-family:monospace;">${esc(r.referral_code)}</td>
        <td>${esc(r.email)}</td><td>${r.payout_details_verified?'✅ verified':'⏳ unverified'}</td>
        <td>${r.referral_count}</td><td style="text-align:right;">${money(r.mrr)}</td>
        <td style="text-align:right;">${money(r.lifetime_paid_net)}</td>
        <td><button class="btn btn-ghost btn-sm" onclick="ReferralProgram.profile(${r.id})">View</button>
        ${r.payout_details_verified?'':`<button class="btn btn-ghost btn-sm" onclick="ReferralProgram.verify(${r.id})">Verify payout</button>`}</td></tr>`).join('')}</tbody></table></div></div>`;
  }
  function enrolForm() {
    const el = document.getElementById('rp-enrol');
    el.innerHTML = `<div class="card" style="padding:16px; margin-bottom:12px; background:var(--bg2);">
      <div class="su-grid-2" style="display:grid; grid-template-columns:1fr 1fr; gap:0 14px;">
        ${inp('rp-fn','Full name (as per PAN) *')}${inp('rp-mob','Mobile *')}${inp('rp-em','Email *')}
        ${inp('rp-upi','UPI ID *')}${inp('rp-acc','Bank account number *')}${inp('rp-ifsc','IFSC *')}
        ${inp('rp-bank','Bank name *')}${inp('rp-branch','Branch *')}${inp('rp-pan','PAN *')}${inp('rp-tds','TDS rate %','10')}
      </div>
      <button class="btn btn-primary btn-sm" style="margin-top:10px;" onclick="ReferralProgram.enrolSubmit()">Create reseller</button>
      <div id="rp-enrol-out" style="margin-top:10px;"></div></div>`;
  }
  function inp(id,label,val){return `<div class="form-group" style="margin-bottom:10px;"><label class="form-label" style="font-weight:600;">${esc(label)}</label><input id="${id}" class="form-input" value="${val||''}"></div>`;}
  async function enrolSubmit() {
    const g = (id) => (document.getElementById(id).value || '').trim();
    try {
      const r = await App.post('/api/admin/resellers', {
        full_name:g('rp-fn'), mobile:g('rp-mob'), email:g('rp-em'), upi_id:g('rp-upi'),
        bank_account_number:g('rp-acc'), bank_ifsc:g('rp-ifsc'), bank_name:g('rp-bank'),
        bank_branch:g('rp-branch'), pan:g('rp-pan'), tds_rate:Number(g('rp-tds'))||10 });
      document.getElementById('rp-enrol-out').innerHTML =
        `<div style="font-size:13px;">✅ Reseller created — code <b>${esc(r.reseller.referral_code)}</b>. Send them this set-password link:
        <div style="display:flex; gap:8px; margin-top:6px;"><input class="form-input" readonly id="rp-spl" value="${esc(r.set_password_url)}" style="font-size:12px;">
        <button class="btn btn-ghost btn-sm" onclick="navigator.clipboard.writeText(document.getElementById('rp-spl').value);App.toast('Copied','success')">Copy</button></div></div>`;
      go('resellers');
    } catch (_) {}
  }
  async function verify(id) {
    if (!(await App.confirm('Confirm you have sent ₹1 to this reseller\\'s UPI and it landed?', {okText:'Mark verified'}))) return;
    try { await App.post(`/api/admin/resellers/${id}/verify-payout`, {}); App.toast('Payout details verified','success'); go('resellers'); } catch (_) {}
  }
  async function profile(id) {
    const d = (await App.get(`/api/admin/resellers/${id}`)).reseller;
    App.openModal(`Reseller — ${esc(d.full_name)}`, `<div style="font-size:13px; line-height:1.9;">
      Code <b>${esc(d.referral_code)}</b><br>Email ${esc(d.email)} · ${esc(d.mobile)}<br>
      UPI ${esc(d.upi_id||'—')}<br>Bank ${esc(d.bank_name||'—')} ${esc(d.bank_account_masked)} (${esc(d.bank_ifsc||'—')}), ${esc(d.bank_branch||'—')}<br>
      PAN ${esc(d.pan||'—')} · TDS ${d.tds_rate}%<br>
      Payout ${d.payout_details_verified?'✅ verified':'⏳ unverified'}<br>
      Referrals ${d.referral_count} · MRR ${money(d.mrr)} · Paid to date (net) ${money(d.lifetime_paid_net)}</div>`,
      '<button class="btn btn-primary" onclick="App.closeModal()">Close</button>', true);
  }

  async function estHtml() {
    const d = await App.get('/api/admin/referral-program/establishments');
    return `<div class="card" style="padding:16px; margin-bottom:12px;">
      <h3 style="margin:0 0 8px; font-size:14px;">Referred establishments</h3>
      <div style="overflow-x:auto;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Code</th><th>Name</th><th>Type</th><th>Reseller</th><th>Billing</th><th>Status</th></tr></thead>
      <tbody>${d.establishments.map(e => `<tr><td style="font-family:monospace;">${esc(e.code)}</td><td>${esc(e.name)}</td>
        <td>${esc(e.type)}</td><td>${esc(e.reseller)} <span style="color:var(--text3); font-family:monospace;">${esc(e.reseller_code)}</span></td>
        <td>${esc(e.fee_display)}</td><td><span class="badge ${e.status==='active'?'success':'low'}">${esc(e.status)}</span></td></tr>`).join('')}</tbody></table></div></div>
      <div class="card" style="padding:16px; margin-bottom:12px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Per-employee referrals</h3>
        <table class="data-table" style="width:100%; font-size:13px;"><thead><tr><th>Establishment</th><th>Reseller</th><th style="text-align:right;">Rate</th><th style="text-align:right;">Headcount</th><th style="text-align:right;">Fee</th><th style="text-align:right;">Your 50%</th></tr></thead>
        <tbody>${d.per_employee.map(r => `<tr><td>${esc(r.name)}</td><td>${esc(r.reseller)}</td>
          <td style="text-align:right;">₹${r.rate}</td><td style="text-align:right;">${r.headcount}</td>
          <td style="text-align:right;">${money(r.fee)}</td><td style="text-align:right;">${money(r.owner_share)}</td></tr>`).join('') || '<tr><td colspan="6" style="color:var(--text3);">None.</td></tr>'}</tbody></table></div>
      <div class="card" style="padding:16px;">
        <h3 style="margin:0 0 8px; font-size:14px;">Pending enrollments — all resellers</h3>
        <table class="data-table" style="width:100%; font-size:13px;"><thead><tr><th>Reseller</th><th>Establishment</th><th>Contact</th><th>Stage</th></tr></thead>
        <tbody>${d.pending.map(p => `<tr><td>${esc(p.reseller)}</td><td>${esc(p.establishment_name)}</td><td>${esc(p.contact_email)}</td><td><span class="badge low">${esc(p.stage.replace(/_/g,' '))}</span></td></tr>`).join('') || '<tr><td colspan="4" style="color:var(--text3);">None.</td></tr>'}</tbody></table></div>`;
  }

  async function ecrHtml() {
    const d = await App.get('/api/admin/referral-program/ecr-activity');
    return `<div class="card" style="padding:16px;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Establishment</th><th>Wage month</th><th style="text-align:right;">Employees</th></tr></thead>
      <tbody>${d.rows.map(r => `<tr><td>${esc(r.establishment)} <span style="color:var(--text3); font-family:monospace;">${esc(r.code)}</span></td><td>${esc(r.wage_month)}</td><td style="text-align:right;">${r.employees}</td></tr>`).join('') || '<tr><td colspan="3" style="color:var(--text3);">No activity.</td></tr>'}</tbody></table></div>`;
  }

  async function payoutsHtml() {
    const d = await App.get('/api/admin/payouts');
    return `<div class="card" style="padding:16px;"><table class="data-table" style="width:100%; font-size:13px;">
      <thead><tr><th>Reseller</th><th>Period</th><th style="text-align:right;">Gross</th><th style="text-align:right;">Net to reseller</th><th style="text-align:right;">Your 50%</th><th>UPI</th><th>Status</th><th></th></tr></thead>
      <tbody>${d.payouts.map(p => `<tr><td>${esc(p.reseller)}</td><td>${esc(p.period)}</td>
        <td style="text-align:right;">${money(p.gross_collected)}</td><td style="text-align:right;">${money(p.reseller_share_net)}</td>
        <td style="text-align:right;">${money(p.owner_share)}</td><td>${esc(p.upi_id||'—')}</td>
        <td><span class="badge ${p.status==='paid'?'success':(p.status==='failed'?'danger':'low')}">${esc(p.status)}</span>${p.upi_reference?`<div style="font-size:11px; font-family:monospace; color:var(--text3);">${esc(p.upi_reference)}</div>`:''}</td>
        <td>${p.status!=='paid'?`<button class="btn btn-primary btn-sm" onclick="ReferralProgram.markPaid(${p.id})">Mark paid</button>`:''}</td></tr>`).join('') || '<tr><td colspan="8" style="color:var(--text3);">No payout runs yet.</td></tr>'}</tbody></table>
      <p style="font-size:11px; color:var(--text3); margin-top:12px;">The monthly job writes these as <b>scheduled</b>. Transfer each reseller's net to their UPI, then mark it paid with the UTR.</p></div>`;
  }
  async function markPaid(id) {
    const utr = await App.confirm('Enter the UPI reference / UTR for this transfer:', { prompt: true, okText: 'Mark paid' });
    // If App.confirm has no prompt mode, use a small openModal with an input instead — check app.js.
    if (!utr) return;
    try { await App.post(`/api/admin/payouts/${id}/mark-paid`, { upi_reference: utr }); App.toast('Payout marked paid','success'); go('payouts'); } catch (_) {}
  }

  if (typeof App !== 'undefined' && App.registerPage) App.registerPage('referral-program', render);
  return { go, enrolForm, enrolSubmit, verify, profile, markPaid };
})();
```

**Check `App.confirm` capabilities** (grep `function confirm` in app.js) — if it has no prompt/input mode, `markPaid` and `verify` must use `App.openModal` with an `<input>` + a button that reads the value. Implement whichever the codebase supports; do not assume a prompt mode.

- [ ] **Step 6: Wire `webapp/index.html` + `webapp/js/app.js`**

`index.html` — add after the reseller.js line:

```html
    <script src="/js/referral-program.js"></script>
```

`app.js` `renderSidebarNav()` — in the `if (isSuper)` branch, right after the Admin Dashboard `items.push(...)`:

```javascript
      items.push(`
        <a class="nav-item ${currentPage === 'referral-program' ? 'active' : ''}" data-page="referral-program" style="background:rgba(217,164,65,0.08); border-left:3px solid var(--amber, #d9a441);">
          <span class="nav-icon">🤝</span><span>Referral Program</span>
        </a>
      `);
```

`app.js` `navigate()` `titles` map — add:

```javascript
      'referral-program': '🤝 Referral Program',
```

- [ ] **Step 7: Run full suite** → `pytest webapp/tests/ -v` green.

- [ ] **Step 8: Live browser verification**

```
1. Same local-server setup as Task 5 step 9.
2. As superadmin: sidebar shows "Referral Program"; open it.
   - Resellers tab: "Enrol a reseller" form creates one, shows the set-password link.
   - Copy the link, open it in a new tab, set a password.
   - Verify payout on that reseller (confirm dialog -> ✅).
   - Log in as that reseller in a separate context, create an establishment.
   - Back as superadmin: Establishments tab shows it + the pending row.
3. In a python shell against the local DB: mark that establishment's Apr fee is_paid=True,
   then run:  DATABASE_URL=sqlite:///./local_qaP.db PAYOUT_PERIOD=2026-05 python scripts/run_reseller_payouts.py
   Confirm it prints one payout row.
4. Reload Referral Program -> Payouts tab: one 'scheduled' row. Click "Mark paid",
   enter a UTR. Row flips to 'paid' with the UTR shown.
5. Log in as the reseller: My Earnings shows the settled month; Payout History shows the UTR.
6. read_console_messages -> no uncaught errors. Screenshot Payouts tab + reseller Earnings.
   SendUserFile both screenshots.
7. Stop server, delete local_qaP.db.
```

- [ ] **Step 9: Flip the spec status line**

In `docs/superpowers/specs/2026-09-10-partner-program-design.md`, change the `Status:` line under the title to:

```
Status: **v1 implemented** (2026-09-10). "Create the account" enrollment, reseller
+ owner dashboards, and manual monthly 50:50 payouts are live. Deferred items
(referral-link/invite paths, automated UPI payout API, automated penny-drop,
multi-level attribution, Form 16A automation) remain per the "Still genuinely
open" list below.
```

- [ ] **Step 10: Commit**

```bash
git add webapp/app.py webapp/js/referral-program.js webapp/index.html webapp/js/app.js webapp/tests/test_reseller_program.py docs/superpowers/specs/2026-09-10-partner-program-design.md
git commit -m @'
feat(reseller): superadmin Referral Program section (overview, resellers, establishments, ECR, payouts)

Owner-side dashboard: enrol resellers, verify payout details, see every referred
establishment + per-employee panel + pending pipeline, and settle scheduled
payouts by marking them paid with a UTR.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
git push
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| Roles — new `reseller`, `get_reseller` | Task 1 |
| `User.role` reseller + `ResellerProfile` (all fields incl. PAN/TDS, bank, UPI) | Task 1 (model), Task 3 (populated) |
| `Establishment.referred_by_reseller_id` + migration | Task 1 |
| `Enrollment` table + pipeline stages | Task 1 (model), Task 4 (`account_created`/`password_set`), Task 2 (`password_set` transition). *Gap:* `awaiting_first_payment` / `active` transitions are never written by code in v1 — acceptable: the pending panel just shows `password_set`; "active" is derived from a paid fee existing, not from the stage. Noted as a known v1 simplification. |
| `ResellerPayout` (+ optional line table) | Task 1 (both), Task 6 (populated) |
| Pricing model maps onto `billing_mode`/`flat_fee_amount`/`custom_rate_per_employee` | Task 4 |
| Enrolling a reseller (superadmin form + backend, referral code, set-password invite, penny-drop) | Task 3 (penny-drop replaced by manual verify per settled decision 7) |
| Referral enrollment — "create the account" | Task 4 |
| Referral link / invite | Deferred (Global Constraints) — not built |
| Revenue split & monthly payout run 00:30 on the 1st | Task 6 (cron at 01:00 UTC ≈ 06:30 IST — the settled decision says exact minute doesn't matter for manual settlement) |
| Owner dashboard — Overview/Resellers/Establishments/ECR/Payouts/Design-notes | Task 7 (Design-notes screen omitted — it duplicated the spec's open-decisions list; the spec itself is the canonical place. Acceptable.) |
| Reseller dashboard — Overview/Enroll/My establishments/ECR/My earnings/Payout history | Task 5 |
| Ownership/security — every reseller endpoint checks referral | Tasks 4, 5 (`_reseller_est_or_403`, every query filtered by `referred_by_reseller_id == reseller.id`) |
| Not-in-scope items | Respected (no ₹75 floor, no multi-currency, no reseller editing wage data) |

**2. Placeholder scan** — no "TBD"/"add validation"/"similar to Task N". Two spots say "grep first / check what the codebase supports" (`_isodt`, `App.confirm` prompt mode, `count_ecr_employees_for_month` location, `WEBAPP_DIR` idiom) — these are real verification instructions with a concrete fallback given, not placeholders.

**3. Type consistency**
- `_reseller_ecr_rows(db, est_ids, scope, limit)` — same signature in Tasks 5 and 7. ✓
- `_reseller_paid_fees(db, reseller_id)` — Task 5, reused Task 6? No — Task 6's `compute_payouts_for_period` re-queries independently (it's in a different module and must not import from `app.py`). Consistent by design. ✓
- `ResellerPayout` fields (`reseller_share_gross`, `reseller_share_net`, `tds_amount`, `owner_share`, `gross_collected`, `upi_reference`, `period`, `status`) — identical across Tasks 1, 6, 7. ✓
- `Enrollment.set_password_jti` / `stage` values (`account_created` → `password_set`) — consistent Tasks 1, 2, 4. ✓
- Frontend page names (`reseller-overview` etc., `referral-program`) — consistent between `reseller.js`/`referral-program.js`, `app.js` nav, and `titles`. ✓
- `/api/reseller/establishments` returns `{establishments: [...]}` in Task 4 (create returns `{establishment: {...}}` singular) and Task 5 (list, plural) — different endpoints, POST vs GET, no clash. ✓

**Known v1 simplifications (documented, not gaps):**
- `Enrollment.stage` never advances past `password_set` in code; "active" status is derived from a paid `SubscriptionFee`, not the stage column.
- ECR activity rows have `filed_at: null` — the `Project` year data has wage figures but no reliable per-month "filed at" timestamp; the row shows the wage month, which is the useful key.
- `count_ecr_employees_for_month` is called per establishment per month on dashboard load — fine for the expected v1 volume (tens of establishments); revisit with a cached rollup if it gets slow.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-10-partner-program-v1.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
