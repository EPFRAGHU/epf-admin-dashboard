"""Pure month/coverage logic for the consultant monthly plan.

No database access. Calendar months are 'YYYY-MM' strings in IST
(fixed UTC+5:30), never the server's local date.
"""
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Tuple

MAX_PLAN_MONTHS = 24
IST = timezone(timedelta(hours=5, minutes=30))


def current_month_ist(now: Optional[datetime] = None) -> str:
    """Return the current calendar month as 'YYYY-MM' in IST.

    `now` may be tz-aware or naive (naive is treated as UTC).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(IST).strftime("%Y-%m")


def _to_index(ym: str) -> int:
    year, month = ym.split("-")
    return int(year) * 12 + (int(month) - 1)


def _from_index(idx: int) -> str:
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


def add_months(ym: str, n: int) -> str:
    """Add n months (may be 0 or negative) to a 'YYYY-MM' string."""
    return _from_index(_to_index(ym) + n)


def compute_coverage(
    current_ym: str, latest_covered_to: Optional[str], months: int
) -> Tuple[str, str]:
    """Return (start, end) of a new purchase of `months` months.

    Starts the month after the latest existing coverage, or at the current
    month if there is none or that coverage has already lapsed.
    """
    if latest_covered_to is None:
        start = current_ym
    else:
        start = max(current_ym, add_months(latest_covered_to, 1))
    return start, add_months(start, months - 1)


def covers(ym: str, windows: Iterable[Tuple[str, str]]) -> bool:
    """True if any (from, to) window includes ym (inclusive bounds)."""
    return any(frm <= ym <= to for frm, to in windows)


def validate_months(months) -> int:
    """Accept an int (not bool) in 1..MAX_PLAN_MONTHS, else raise ValueError."""
    if isinstance(months, bool) or not isinstance(months, int):
        raise ValueError("months must be an integer")
    if not 1 <= months <= MAX_PLAN_MONTHS:
        raise ValueError("months must be between 1 and %d" % MAX_PLAN_MONTHS)
    return months
