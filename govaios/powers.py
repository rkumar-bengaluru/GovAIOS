"""Admin review of who else holds the OS powers (row 24). No API lists other apps' grants without FDA: an attestation."""
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import auth

PANES = ("Privacy_Accessibility", "Privacy_ListenEvent", "Privacy_ScreenCapture")
STATEMENT = "Only gov-aios and the apps you keep hold these; no terminal or AI agent does"
MAX_AGE = timedelta(days=30)
FILE = "powers_review.json"


def review(home: Path, kept: list[str], audit) -> bool:
    for pane in PANES:
        subprocess.run(["/usr/bin/open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"], check=False)
    names = ", ".join(kept) or "(none)"
    ok, how = auth.approve(f"{STATEMENT}.\n\nApps you keep: {names}", "confirm the OS powers review", home)
    audit.append("powers_review", target=names, decision="allow" if ok else "deny", approver="admin",
                 channel="touch_id", auth=how)   # first: a review is never on file without its record
    if ok:
        Path(home).mkdir(parents=True, exist_ok=True, mode=0o700)
        p = Path(home) / FILE
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "kept": list(kept)}))
        os.replace(tmp, p)
    return ok


def last(home: Path) -> datetime | None:
    """Time of the last review, None if missing or unreadable (naive stamps count as unreadable)."""
    try:
        ts = datetime.fromisoformat(json.loads((Path(home) / FILE).read_text())["ts"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return ts if ts.tzinfo else None


def fresh(home: Path, now: datetime | None = None) -> bool:
    ts = last(home)
    now = now or datetime.now(timezone.utc)
    return ts is not None and timedelta(0) <= now - ts < MAX_AGE   # a future stamp would never expire
