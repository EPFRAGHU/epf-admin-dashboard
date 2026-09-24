"""Read-only regression snapshot for the 2026-09-17 wage-ceiling change.

Reads EVERY establishment from the database in DATABASE_URL, recomputes every wage
month's calculated figures with the epf_engine of the checkout it is run from, and
writes one SHA-256 per (establishment, year, month) to a JSON file. Run it once on the
OLD commit and once on the NEW commit against the same database COPY, then compare:

    python scripts/ceiling_regression_snapshot.py --confirm-copy --out old.json   # old commit
    python scripts/ceiling_regression_snapshot.py --confirm-copy --out new.json   # new commit
    python scripts/ceiling_regression_snapshot.py --compare old.json new.json

The compare step must report ZERO differences for every month before September 2026
(FY 2026-27 month index 6), and may differ only from that month on.

Safety: this only ever SELECTs. It refuses to run without --confirm-copy, and prints
the database host first so you can check it is the Neon BRANCH / restored backup, not
production. It never writes to the database.
"""
import argparse
import hashlib
import json
import os
import sys
from urllib.parse import urlparse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUTOFF = ("2026", 6)  # (year_from, month_idx): first wage month that MAY legitimately differ


def _canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def snapshot(url):
    from sqlalchemy import create_engine, text
    sys.path.insert(0, REPO)
    from epf_engine import Project, MONTHS, generate_ecr_month, get_wage_ceilings_for_year, is_eps_zero_for_month

    engine = create_engine(url)
    out = {}
    selfcheck = []   # new-engine wage bases vs the legacy min(w, ceiling) formulas, pre-cutoff months only
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, code, name, data FROM establishments ORDER BY id")).fetchall()
    for est_id, code, name, data in rows:
        try:
            project = Project()
            project.load_from_dict(json.loads(data or "{}"))
        except Exception as exc:  # a broken blob is reported, never silently skipped
            out[f"est{est_id}:LOAD_ERROR"] = str(exc)
            continue
        for key in project.year_keys_sorted():
            yr = project.years[key]
            est = project.build_establishment_for_year(key)
            emps = project.build_employees_for_year(key)
            ceilings = [float(c) for c in get_wage_ceilings_for_year(yr.year_from)]
            explicit = [e.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                                     est.employer_epf_rate, est.employer_eps_rate,
                                     wage_ceilings=get_wage_ceilings_for_year(yr.year_from)) for e in emps]
            default = [e.month_rows(est.worker_epf_rate, est.worker_eps_rate,
                                    est.employer_epf_rate, est.employer_eps_rate) for e in emps]
            if hasattr(emps[0] if emps else None, "wage_bases"):
                for e in emps:
                    for i in range(12):
                        if (yr.year_from, i) >= CUTOFF:
                            continue
                        w = int(round(float(e.wages[i]))) if e.wages[i] else 0
                        c = get_wage_ceilings_for_year(yr.year_from)[i]
                        zero = (not e.eps_member) or is_eps_zero_for_month(e.dob, i, yr.year_from)
                        b = e.wage_bases(i, w, c, honor_pohw=False)
                        if (b.eps, b.edli) != (0 if zero else min(w, float(c)), min(w, float(c))):
                            selfcheck.append(f"est{est_id}|{key}|{i}|{e.member_id}")
            for i in range(12):
                payload = {
                    "ceiling": ceilings[i],
                    "explicit": [[e.member_id, r[i]] for e, r in zip(emps, explicit)],
                    "default": [[e.member_id, r[i]] for e, r in zip(emps, default)],
                    "ecr": generate_ecr_month(est, emps, yr, i),
                }
                out[f"est{est_id}|{key}|{i}|{MONTHS[i]}"] = hashlib.sha256(_canon(payload).encode()).hexdigest()
    out["__selfcheck__"] = selfcheck
    return out


def is_pre_cutoff(k):
    _, key, idx, _ = k.split("|")
    year_from = key.split("-")[0]
    return (year_from, int(idx)) < CUTOFF


def compare(old_path, new_path):
    old, new = json.load(open(old_path)), json.load(open(new_path))
    keys = sorted(k for k in set(old) | set(new) if not k.startswith("__"))
    bad_self = new.get("__selfcheck__", [])
    bad_pre = [k for k in keys if "LOAD_ERROR" in k or (is_pre_cutoff(k) and old.get(k) != new.get(k))]
    changed_post = [k for k in keys if "LOAD_ERROR" not in k and not is_pre_cutoff(k) and old.get(k) != new.get(k)]
    same_pre = sum(1 for k in keys if "LOAD_ERROR" not in k and is_pre_cutoff(k) and old.get(k) == new.get(k))
    print(f"pre-cutoff months identical : {same_pre}")
    print(f"pre-cutoff months DIFFERENT : {len(bad_pre)}   <- must be 0")
    for k in bad_pre[:50]:
        print("   ", k)
    print(f"Sep-2026-onward months changed: {len(changed_post)} (expected only where wages exceed 15,000)")
    print(f"new wage_bases vs legacy min(w, ceiling) formulas, pre-cutoff: {len(bad_self)} mismatches   <- must be 0")
    for k in bad_self[:50]:
        print("   ", k)
    return 1 if (bad_pre or bad_self) else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm-copy", action="store_true",
                    help="I confirm DATABASE_URL points at a COPY (Neon branch / restored backup), not production")
    ap.add_argument("--out")
    ap.add_argument("--compare", nargs=2, metavar=("OLD", "NEW"))
    a = ap.parse_args()
    if a.compare:
        sys.exit(compare(*a.compare))
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        sys.exit("Set DATABASE_URL to the database COPY first.")
    print("Database host:", urlparse(url).hostname or "(local file)", "| db:", (urlparse(url).path or "").lstrip("/"))
    if not a.confirm_copy:
        sys.exit("Refusing to run without --confirm-copy.")
    if not a.out:
        sys.exit("--out FILE is required.")
    result = snapshot(url)
    json.dump(result, open(a.out, "w"), indent=0, sort_keys=True)
    print(f"wrote {len(result)} month hashes -> {a.out}")
