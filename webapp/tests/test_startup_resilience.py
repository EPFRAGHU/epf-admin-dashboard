"""Startup must be idempotent and resilient: a seed/migration problem never stops the app, and a
failed database connection never silently switches to a local SQLite file when DATABASE_URL is set."""
import os
import subprocess
import sys
from pathlib import Path

import webapp.app as appmod
from webapp.database import SessionLocal, User

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIMARY = "raghunatha.maharana@gmail.com"


def _count_users(email_lower):
    db = SessionLocal()
    try:
        return db.query(User).filter(User.email.ilike(email_lower)).count()
    finally:
        db.close()


def test_superadmin_seed_is_idempotent_when_env_email_equals_primary(monkeypatch):
    """Regression: with SUPERADMIN_EMAIL set to the primary superadmin's address, the second seed
    looked for the hard-coded default address, found nothing, and re-inserted the SAME email ->
    UNIQUE constraint failed: users.email, which killed startup."""
    monkeypatch.setenv("SUPERADMIN_EMAIL", PRIMARY.upper())  # also proves the match is case-insensitive
    appmod._run_startup_migrations()
    appmod._run_startup_migrations()  # a second boot against the same DB must also be fine
    assert _count_users(PRIMARY) == 1


def test_failing_seed_step_is_skipped_and_later_steps_still_run(monkeypatch, capsys):
    monkeypatch.setattr(appmod, "FEATURE_FLAG_DEFAULTS", {"broken_flag": "not-a-pair"})  # unpack error
    appmod._run_startup_migrations()  # must not raise
    out = capsys.readouterr().out
    assert "Startup step 'seed feature flags' failed and was skipped" in out
    # steps after the broken one still ran and left the session usable
    db = SessionLocal()
    try:
        assert db.query(User).count() >= 1
    finally:
        db.close()


def test_on_startup_never_raises_even_if_migrations_blow_up(monkeypatch, capsys):
    def boom():
        raise RuntimeError("simulated migration failure")
    monkeypatch.setattr(appmod, "_run_startup_migrations", boom)
    appmod.on_startup()  # must swallow and log, not stop the app
    assert "Startup migrations failed, continuing without them" in capsys.readouterr().out


def test_no_silent_sqlite_fallback_when_database_url_is_set(tmp_path):
    """DATABASE_URL set + connection/driver failure -> clear RuntimeError, never a local SQLite DB.
    Run in a subprocess because webapp.database connects at import time. The URL names a dialect
    that does not exist, so create_engine fails immediately and nothing is ever contacted."""
    env = dict(os.environ)
    env["DATABASE_URL"] = "postgresql+nosuchdriver://user:pw@127.0.0.1:1/db"
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", "import webapp.database"],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert "Refusing to fall back to a local SQLite database" in proc.stderr
    assert not (tmp_path / "epf_app.db").exists()
