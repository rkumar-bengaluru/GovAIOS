"""One-use, 60 s run tickets: files in <home>/tickets/, wall-clock expiry (crosses processes)."""
import json
import os
import re
import secrets
import time
from pathlib import Path

from govaios.panel.totp import _read_nofollow, _write_new

TICKET_S = 60
_HEX64 = re.compile(r"[0-9a-f]{64}")


def create(home: Path, flow_id: str, digest: str, now=time.time) -> str:
    d = Path(home) / "tickets"
    d.mkdir(mode=0o700, exist_ok=True)
    token = secrets.token_hex(32)
    _write_new(d / token, json.dumps({"flow": flow_id, "digest": digest, "expires": now() + TICKET_S}).encode())
    return token


def consume(home: Path, token: str, flow_id: str, digest: str, now=time.time) -> bool:
    if not isinstance(token, str) or not _HEX64.fullmatch(token):
        return False
    p = Path(home) / "tickets" / token
    try:
        raw = _read_nofollow(p)
    finally:
        p.unlink(missing_ok=True)
    try:
        t = json.loads(raw)
        n = now()
        return t["flow"] == flow_id and t["digest"] == digest and 0 <= t["expires"] - n <= TICKET_S
    except (TypeError, ValueError, KeyError):
        return False
