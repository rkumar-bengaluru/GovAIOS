"""One-use, 60 s run tickets: files in <home>/tickets/, wall-clock expiry (crosses processes)."""
import hashlib
import json
import os
import re
import secrets
import stat
import time
from pathlib import Path

from govaios.panel.totp import _write_new

TICKET_S = 60
_HEX64 = re.compile(r"[0-9a-f]{64}")


def inputs_digest(inputs: dict) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def run_id(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()[:16]


def create(home: Path, flow_id: str, digest: str, session: str, inputs: dict | None = None, now=time.time) -> str:
    d = Path(home) / "tickets"
    d.mkdir(mode=0o700, exist_ok=True)
    token = secrets.token_hex(32)
    _write_new(d / token, json.dumps({"flow": flow_id, "digest": digest, "session": session, "inputs_digest": inputs_digest(inputs or {}), "expires": now() + TICKET_S}).encode())
    return token


def consume(home: Path, token: str, flow_id: str, digest: str, inputs: dict | None = None, now=time.time) -> str | None:
    """The opening session id on success, else None."""
    if not isinstance(token, str) or not _HEX64.fullmatch(token):
        return None
    p = Path(home) / "tickets" / token
    mine = p.with_name(p.name + ".used-" + secrets.token_hex(4))
    try:
        os.rename(p, mine)  # atomic claim: only one consumer wins
    except OSError:
        return None
    try:
        fd = os.open(mine, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return None
            t = json.loads(f.read())
        sid = t["session"]
        good = t["flow"] == flow_id and t["digest"] == digest and t["inputs_digest"] == inputs_digest(inputs or {}) and 0 <= t["expires"] - now() <= TICKET_S
        return sid if good and isinstance(sid, str) and sid else None
    except (OSError, TypeError, ValueError, KeyError):
        return None
    finally:
        try:
            mine.unlink()
        except OSError:
            pass
