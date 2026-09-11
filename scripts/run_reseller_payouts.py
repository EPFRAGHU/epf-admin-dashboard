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
    y, m = today.year, today.month - 1
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
