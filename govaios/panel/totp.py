"""RFC 6238 TOTP (SHA-1, 6 digits, 30 s) plus the authenticator secret store. Never log codes or secrets."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from pathlib import Path

import segno

LOCK_AFTER, LOCK_SECS = 5, 15 * 60


def new_secret() -> bytes:
    return secrets.token_bytes(20)


def otpauth_uri(secret: bytes, account: str = "Admin") -> str:
    b32 = base64.b32encode(secret).decode().rstrip("=")
    return f"otpauth://totp/GOV-AIOS:{account}?secret={b32}&issuer=GOV-AIOS"


def qr_svg(uri: str) -> str:
    return segno.make(uri).svg_inline(scale=4)


def _hotp(secret: bytes, step: int) -> str:
    d = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    o = d[-1] & 15
    return f"{(struct.unpack('>I', d[o:o + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


def code_at(secret: bytes, t: float) -> str:
    return _hotp(secret, int(t // 30))


def _hits(secret: bytes, code: str, t: float) -> list[int]:
    """Matching steps among -1/0/+1; every window compared (no early exit) so timing does not reveal which matched."""
    step = int(t // 30)
    return [s for s in (step - 1, step, step + 1) if hmac.compare_digest(_hotp(secret, s).encode(), str(code).encode())]


def matches(secret: bytes, code: str, t: float) -> int | None:
    """Setup check against a secret not yet stored: the matched step, else None."""
    hits = _hits(secret, code, t)
    return hits[0] if hits else None


def mark_used(home: Path, step: int) -> None:
    """After setup: the setup code's step counts as used, so it cannot also open a session."""
    _replace(Path(home) / "totp.state", json.dumps({"last_step": step}).encode())


def _read_nofollow(path: Path) -> bytes | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:  # missing, or a symlink (ELOOP)
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read()


def _write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _replace(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    _write_new(tmp, data)
    os.replace(tmp, path)


class SecretStore:
    # shortcut: file 0600 like audit_key.pem, not the Keychain; move with the Secure Enclave work.
    def __init__(self, home: Path):
        self.home = Path(home)
        self.path = self.home / "totp.key"

    def load(self) -> bytes | None:
        return _read_nofollow(self.path)

    def save(self, secret: bytes) -> None:
        _replace(self.path, secret)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
        (self.home / "totp.state").unlink(missing_ok=True)


class Verifier:
    def __init__(self, path: Path, clock=time.time):
        self.path, self.clock = Path(path), clock

    def verify(self, code: str) -> str:
        secret = SecretStore(self.path.parent).load()
        if secret is None:
            return "no_secret"
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            st = {}
        except OSError:  # symlink or unreadable: fail closed
            return "locked_out"
        else:
            try:
                with os.fdopen(fd, "rb") as f:
                    st = json.loads(f.read())
                if not isinstance(st, dict):
                    raise ValueError
            except (OSError, ValueError):
                return "locked_out"
        now = self.clock()
        if now < st.get("locked_until", 0):
            return "locked_out"
        hits = _hits(secret, code, now)
        if not hits:
            fails = st.get("fails", 0) + 1
            st["fails"] = fails
            if fails >= LOCK_AFTER:
                st["locked_until"], st["fails"] = now + LOCK_SECS, 0
            result = "bad_code"
        elif hits[0] <= st.get("last_step", -1):
            return "replay"
        else:
            st.update(last_step=hits[0], fails=0, locked_until=0)
            result = "ok"
        _replace(self.path, json.dumps(st).encode())
        return result
