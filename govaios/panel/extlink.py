"""Chrome extension pairing: one connection, a hashed bearer token pinned to the extension's Origin. Never log tokens or codes."""
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from govaios.panel.totp import Verifier, _read_nofollow, _replace

_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}")


def _load(home: Path) -> dict | None:
    raw = _read_nofollow(Path(home) / "extension.json")  # a symlink reads as None
    try:
        d = json.loads(raw) if raw else None
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


def pair(home: Path, code: str, origin: str, clock=time.time) -> str | None:
    home = Path(home)
    # fullmatch: "$" would let a trailing newline through. Checked before the code so a bad caller does not burn it.
    if not _ORIGIN.fullmatch(origin or "") or (home / "extension.json").is_symlink():
        return None
    if Verifier(home / "totp.state", clock).verify(code) != "ok":
        return None
    token = secrets.token_urlsafe(32)
    rec = {"hash": hashlib.sha256(token.encode()).hexdigest(), "origin": origin,
           "at": datetime.now(timezone.utc).isoformat()}
    _replace(home / "extension.json", json.dumps(rec).encode())
    return token


def check(home: Path, token: str | None, origin: str | None) -> bool:
    rec = _load(home)
    if not rec or not token or not origin:
        return False
    ok_hash = hmac.compare_digest(rec.get("hash", "").encode(), hashlib.sha256(token.encode()).hexdigest().encode())
    ok_origin = hmac.compare_digest(str(rec.get("origin", "")).encode(), origin.encode())
    return ok_hash and ok_origin


def disconnect(home: Path) -> None:
    (Path(home) / "extension.json").unlink(missing_ok=True)


def connected(home: Path) -> bool:
    return _load(home) is not None
