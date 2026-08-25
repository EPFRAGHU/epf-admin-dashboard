"""
Derives the app's version/build identity from git metadata instead of a hand-maintained
version string. Computed once at process startup (Render restarts the process on every
deploy, so this is always accurate for the running build) and served via GET /api/version.
"""
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SEP = "\x1f"  # unit separator -- safe delimiter for commit subjects, which may contain ":" or "|"


def _run_git(args, timeout=5):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _deepen_if_shallow():
    """Render (and most CI/deploy pipelines) clone with `--depth 1` for speed, which
    leaves the working copy able to see only its single most recent commit -- every
    git-history-dependent value below (commit_count, the version badge, the "recent
    commits" list) silently degenerates to "v1" / one entry in that state, with no error
    to signal it. Detect that and fetch full history once at startup so production
    matches what a full local clone already shows. Best-effort: if there's no network,
    no remote, or it's slow, every caller below already tolerates a None/short git
    history gracefully, so failure here just means the badge stays understated, not
    that the app breaks."""
    if _run_git(["rev-parse", "--is-shallow-repository"]) != "true":
        return
    _run_git(["fetch", "--unshallow", "--quiet"], timeout=25)


def _format_display(iso_str):
    if not iso_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%d-%m-%Y %H:%M")
    except Exception:
        return iso_str


def _compute_version_info():
    _deepen_if_shallow()

    render_commit = os.environ.get("RENDER_GIT_COMMIT", "")

    short_hash = _run_git(["rev-parse", "--short", "HEAD"]) or (render_commit[:7] if render_commit else "unknown")
    full_hash = _run_git(["rev-parse", "HEAD"]) or render_commit or short_hash
    branch = (
        _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        or os.environ.get("RENDER_GIT_BRANCH", "")
        or "unknown"
    )

    commit_count_raw = _run_git(["rev-list", "--count", "HEAD"])
    commit_count = int(commit_count_raw) if commit_count_raw and commit_count_raw.isdigit() else None

    commit_date_iso = _run_git(["log", "-1", "--format=%cI"]) or datetime.now(timezone.utc).isoformat()
    commit_message = _run_git(["log", "-1", "--format=%s"]) or ""

    version = f"v{commit_count}" if commit_count else f"v{short_hash}"

    log_raw = _run_git(["log", "-30", f"--pretty=format:%h{_SEP}%cI{_SEP}%s"]) or ""
    history = []
    for line in log_raw.splitlines():
        parts = line.split(_SEP)
        if len(parts) != 3:
            continue
        h, iso_date, subject = parts
        if subject.startswith("auto-commit:"):
            # Session-checkpoint noise from the dev tooling, not a meaningful release entry.
            continue
        history.append({
            "hash": h,
            "date": iso_date,
            "date_display": _format_display(iso_date),
            "message": subject,
        })

    return {
        "version": version,
        "short_hash": short_hash,
        "full_hash": full_hash,
        "branch": branch,
        "commit_count": commit_count,
        "commit_date": commit_date_iso,
        "commit_date_display": _format_display(commit_date_iso),
        "commit_message": commit_message,
        "history": history,
    }


_VERSION_INFO = _compute_version_info()


def get_version_info():
    return _VERSION_INFO
