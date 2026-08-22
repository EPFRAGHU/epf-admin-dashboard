#!/usr/bin/env python3
"""
Nightly backup: dumps the production Neon Postgres database (READ-ONLY) and restores it into
a separate Supabase Postgres project, so there's an independent copy of production data that
doesn't depend on Neon's own infrastructure staying up.

Run on a schedule via .github/workflows/neon-to-supabase-backup.yml -- not intended to be run
manually against production unless you specifically mean to (it fully replaces whatever is
currently in the Supabase target with a fresh copy of Neon's current state).

Required environment variables (never hardcoded here -- same pattern as every other credential
in this app, read via os.environ):
    DATABASE_URL            Production Neon connection string (source). Only ever touched via
                             `pg_dump`, which issues zero write statements against the database
                             it dumps -- there is no code path here that can write to Neon.
    SUPABASE_DATABASE_URL   Supabase connection string (target). This is the ONLY database this
                             script ever writes to; it gets fully replaced on every run.

Exit code 0 on success, 1 on any failure -- this is what GitHub Actions uses to decide whether
the scheduled run "failed" (which triggers GitHub's own automatic failure-notification email
to the repo owner, with zero additional email/SMTP setup needed).
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Harmless in CI (GitHub Actions secrets are already in os.environ, and load_dotenv() never
# overrides an existing variable) -- lets this also be run locally for manual testing.
load_dotenv()

LOG_PATH = Path(__file__).resolve().parent.parent / "backup.log"


def _log(message: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {message}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _pg_env_from_url(url: str) -> dict:
    """Translates a postgres:// connection URL into libpq PG* environment variables, so the
    password is never passed as a bare command-line argument (which would be visible to
    anything reading process listings on the machine running this)."""
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    parsed = urlparse(url)
    env = os.environ.copy()
    env["PGHOST"] = parsed.hostname or ""
    env["PGPORT"] = str(parsed.port or 5432)
    env["PGUSER"] = parsed.username or ""
    env["PGPASSWORD"] = parsed.password or ""
    env["PGDATABASE"] = (parsed.path or "").lstrip("/")
    # Both Neon and Supabase require SSL connections.
    env.setdefault("PGSSLMODE", "require")
    return env


def run_backup() -> bool:
    neon_url = os.environ.get("DATABASE_URL")
    supabase_url = os.environ.get("SUPABASE_DATABASE_URL")

    if not neon_url:
        _log("FAILED: DATABASE_URL is not set -- nothing to back up from.")
        return False
    if not supabase_url:
        _log("FAILED: SUPABASE_DATABASE_URL is not set -- no backup target configured.")
        return False

    source_env = _pg_env_from_url(neon_url)
    target_env = _pg_env_from_url(supabase_url)

    with tempfile.TemporaryDirectory() as tmp:
        dump_path = Path(tmp) / "neon_backup.dump"

        _log("Starting pg_dump from Neon (read-only -- pg_dump issues no write statements against its source)...")
        dump_cmd = [
            "pg_dump",
            "--format=custom",   # compressed, restorable with pg_restore
            "--no-owner",        # Neon/Supabase roles differ -- don't fight over object ownership
            "--no-privileges",
            "--file", str(dump_path),
        ]
        result = subprocess.run(dump_cmd, env=source_env, capture_output=True, text=True)
        if result.returncode != 0:
            _log(f"FAILED: pg_dump exited {result.returncode}: {result.stderr.strip()[:2000]}")
            return False
        _log(f"pg_dump complete ({dump_path.stat().st_size} bytes).")

        _log("Restoring into Supabase (--clean --if-exists replaces the prior backup with this run's snapshot)...")
        restore_cmd = [
            "pg_restore",
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
            "--dbname", target_env["PGDATABASE"],
            str(dump_path),
        ]
        result = subprocess.run(restore_cmd, env=target_env, capture_output=True, text=True)
        # pg_restore commonly exits 1 on non-fatal warnings (e.g. "does not exist, skipping" the
        # very first time there's nothing yet to --clean) -- treat stderr content, not just the
        # exit code, as the real fail signal.
        if result.returncode != 0 and "error" in result.stderr.lower():
            _log(f"FAILED: pg_restore reported errors: {result.stderr.strip()[:2000]}")
            return False
        if result.stderr.strip():
            _log(f"pg_restore completed with warnings: {result.stderr.strip()[:1000]}")

    _log("SUCCESS: Neon -> Supabase backup complete.")
    return True


if __name__ == "__main__":
    ok = run_backup()
    sys.exit(0 if ok else 1)
