#!/usr/bin/env python3
"""
Manual spot-check: compares row counts for the key tables between the production Neon
database and the Supabase backup, to confirm a backup run actually produced a complete copy.

Read-only on BOTH sides (SELECT COUNT(*) only) -- safe to run against production at any time.

Usage:
    python scripts/verify_backup.py

Required environment variables: DATABASE_URL (Neon), SUPABASE_DATABASE_URL (Supabase).
"""
import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

TABLES = [
    "users",
    "establishments",
    "payments",
    "subscription_fees",
    "advance_credit_ledger",
    "activity_logs",
    "projects",
]


def _normalize(url: str) -> str:
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def count_rows(conn_url: str) -> dict:
    conn = psycopg2.connect(_normalize(conn_url))
    conn.set_session(readonly=True)
    counts = {}
    try:
        with conn.cursor() as cur:
            for table in TABLES:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    counts[table] = cur.fetchone()[0]
                except Exception as e:
                    counts[table] = f"ERROR: {e}"
                    conn.rollback()
    finally:
        conn.close()
    return counts


def main():
    neon_url = os.environ.get("DATABASE_URL")
    supabase_url = os.environ.get("SUPABASE_DATABASE_URL")

    if not neon_url or not supabase_url:
        print("Set both DATABASE_URL and SUPABASE_DATABASE_URL before running this.")
        sys.exit(1)

    print("Counting rows in Neon (production)...")
    neon_counts = count_rows(neon_url)
    print("Counting rows in Supabase (backup)...")
    supabase_counts = count_rows(supabase_url)

    print(f"\n{'TABLE':<24}{'NEON':>12}{'SUPABASE':>12}{'MATCH':>10}")
    print("-" * 58)
    all_match = True
    for table in TABLES:
        n = neon_counts.get(table)
        s = supabase_counts.get(table)
        match = "OK" if n == s else "MISMATCH"
        if match == "MISMATCH":
            all_match = False
        print(f"{table:<24}{str(n):>12}{str(s):>12}{match:>10}")

    print()
    if all_match:
        print("All row counts match. Backup looks complete.")
    else:
        print("Row count mismatch found above -- investigate before trusting this backup.")
        sys.exit(1)


if __name__ == "__main__":
    main()
