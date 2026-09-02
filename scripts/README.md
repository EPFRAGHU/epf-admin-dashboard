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
- **Optional**: if `HEALTHCHECKS_PING_URL` is set (see step 5 below), the script also pings
  [healthchecks.io](https://healthchecks.io) (or any compatible dead-man's-switch service) at
  the end of every run — success or failure. This is a second, independent layer on top of
  GitHub's own failure email: GitHub only notices a run that actually happened and failed;
  Healthchecks.io also catches the case where the scheduled run never fires at all (e.g. GitHub
  Actions scheduling silently stops triggering it, which does happen on inactive repos), since
  it alerts on a *missing* ping, not just a failing one. If the env var isn't set, this is
  skipped entirely and the backup behaves exactly as before.

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

5. **(Optional) Set up Healthchecks.io** to get a dashboard of "did last night's backup
   actually run" plus alerting on a missed/failed run:
   - Sign up for a free account at [healthchecks.io](https://healthchecks.io) (I can't create
     this account for you).
   - Create a new check. Name it something like `epf-dashboard-nightly-backup`. Set its
     schedule to a **Cron expression**: `30 20 * * *`, timezone **UTC** — this must match
     `.github/workflows/neon-to-supabase-backup.yml`'s own `cron:` value exactly, or the two
     will disagree about when a run is "late." Leave the grace period at its default (a few
     hours is plenty of slack for a job that normally takes 1-2 minutes).
   - Copy the check's **Ping URL** (looks like `https://hc-ping.com/<uuid>`).
   - Add it as a GitHub Actions secret named `HEALTHCHECKS_PING_URL` (same place as the other
     two secrets in step 2).
   - Trigger a manual run (step 3) and confirm the check flips to "Up" on the Healthchecks.io
     dashboard within a minute or two of the run finishing.

After that, it just runs nightly on its own — check the Actions tab occasionally, check
Healthchecks.io's dashboard if you set it up, or wait for an alert email if something breaks.
