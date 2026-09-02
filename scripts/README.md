# Neon → Supabase Backup

Nightly, automated, off-provider backup of the production database. Runs on a schedule via
GitHub Actions (`.github/workflows/neon-to-supabase-backup.yml`), independent of Render and
Neon both staying up.

## How it works

- `backup_neon_to_supabase.py` — the backup itself. `pg_dump`s the Neon database (read-only —
  `pg_dump` never issues write statements against its source) and `pg_restore`s it into a
  Supabase Postgres project, fully replacing whatever was there from the previous run. After
  the restore, it also re-enables Row-Level Security (default-deny, no policies) on every
  table in the Supabase target — belt-and-suspenders against Supabase's own auto-exposed REST
  API (PostgREST) ever serving this data publicly, on top of that project's Data API being
  disabled at the dashboard level (Project Settings → Data API). Neither this script nor
  `verify_backup.py` is affected, since both connect directly as the table owner, which
  Postgres RLS doesn't restrict by default.
- `verify_backup.py` — manual spot-check that compares row counts for the key tables
  (`users`, `establishments`, `payments`, `subscription_fees`, etc.) between Neon and
  Supabase. Read-only on both sides, safe to run against production any time.
- The GitHub Actions workflow runs `backup_neon_to_supabase.py` daily at 02:00 UTC, and
  uploads its log as a build artifact every run (success or failure) so there's always a
  record to check.
- If a scheduled run fails, GitHub automatically emails the repository owner — no extra
  email/SMTP setup needed for that part.

## One-time setup (you need to do this — I can't create accounts or set secrets on your behalf)

1. **Create a free Supabase project** at [supabase.com](https://supabase.com) if you haven't
   already. Once it's created, go to Project Settings → Database → Connection string, and
   copy the URI form (`postgresql://postgres:[PASSWORD]@...supabase.co:5432/postgres`). Use
   the **direct connection** string, not the pooled/transaction one — `pg_dump`/`pg_restore`
   need a direct connection.

2. **Add two GitHub Actions secrets** on this repo (Settings → Secrets and variables →
   Actions → New repository secret):
   - `DATABASE_URL` — the same production Neon connection string already used on Render.
   - `SUPABASE_DATABASE_URL` — the Supabase connection string from step 1.

   (These are GitHub Actions secrets, separate from Render's environment variables — the
   workflow runs on GitHub's own infrastructure, not on Render.)

3. **Trigger a test run**: go to the repo's Actions tab → "Nightly Neon → Supabase Backup" →
   "Run workflow" (this works because the workflow has `workflow_dispatch` enabled). Watch it
   run, download the `backup-log` artifact from the completed run, and confirm it ends with
   `SUCCESS: Neon -> Supabase backup complete.`

4. **Verify row counts match**: with `DATABASE_URL` and `SUPABASE_DATABASE_URL` set in your
   local `.env` (or exported in your shell), run:
   ```bash
   python scripts/verify_backup.py
   ```
   This should print `OK` for every table.

After that, it just runs nightly on its own — check the Actions tab occasionally, or wait for
a failure email if something breaks.
