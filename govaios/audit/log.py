"""Signed, hash-chained, append-only audit log (home/audit.jsonl).

Entry keys, in order: seq (from 1), ts, kind, caller fields, prev, hash, sig.
ts is UTC ISO-8601 with seconds and a "Z" suffix, e.g. 2026-11-05T09:30:00Z.
hash = SHA-256 hex of canonical JSON (sort_keys, separators (",",":"), ensure_ascii=False)
of the entry without hash/sig. sig = base64 DER ECDSA-P256-SHA256 over the hash string's UTF-8 bytes.
prev = previous entry's hash, 64 zeros for seq 1. Only metadata is allowed: no content.
"""
import base64
import fcntl
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

KINDS = {"flow_start", "flow_approval", "request", "action", "verify", "stop", "flow_end"}
FIELDS = {"flow", "flow_version", "flow_hash", "executor", "step", "action", "risk", "target",
          "destination", "decision", "approver", "channel", "outcome", "reason"}
ZERO = "0" * 64


class AuditError(Exception):
    pass


def url_for_audit(url: str) -> str:
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}{u.path}"


def _canon(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class AuditLog:
    def __init__(self, home: Path):
        self.home = Path(home)
        self.path = self.home / "audit.jsonl"
        self.key_path = self.home / "audit_key.pem"
        self.pub_path = self.home / "audit_pubkey.pem"

    def _key(self):
        # shortcut: key on disk (0600), not Secure Enclave; move to Secure Enclave in the deployment plan.
        if self.key_path.exists():
            return serialization.load_pem_private_key(self.key_path.read_bytes(), None)
        if self.path.exists() and self.path.stat().st_size > 0:
            raise AuditError("audit key missing but audit log exists; refusing to start a new chain")
        key = ec.generate_private_key(ec.SECP256R1())
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        self.pub_path.write_bytes(key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        return key

    def _last(self):
        """(seq, hash) of the last entry; refuses on a partial or unreadable tail."""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0, ZERO
        with open(self.path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            n = 4096
            while True:  # read backwards until the last line is fully in the buffer
                n = min(n, size)
                f.seek(size - n)
                buf = f.read(n)
                if n == size or buf[:-1].count(b"\n") >= 1:
                    break
                n *= 2
        if not buf.endswith(b"\n"):
            raise AuditError("audit log has a truncated tail; resolve it before appending")
        try:
            last = json.loads(buf[:-1].split(b"\n")[-1])
            return last["seq"], last["hash"]
        except (ValueError, KeyError) as e:
            raise AuditError(f"audit log last line unreadable: {e}")

    def append(self, kind: str, **fields) -> dict:
        if kind not in KINDS:
            raise AuditError(f"unknown audit kind: {kind}")
        bad = set(fields) - FIELDS
        if bad:
            raise AuditError(f"audit field(s) not allowed: {sorted(bad)}")
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        with open(self.home / "audit.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            key = self._key()
            seq, prev = self._last()
            entry = {"seq": seq + 1, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "kind": kind, **fields, "prev": prev}
            entry["hash"] = hashlib.sha256(_canon(entry).encode()).hexdigest()
            entry["sig"] = base64.b64encode(key.sign(entry["hash"].encode(), ec.ECDSA(hashes.SHA256()))).decode()
            new = not self.path.exists()
            with open(self.path, "ab") as f:
                f.write((_canon_line(entry) + "\n").encode())
                f.flush()
                os.fsync(f.fileno())
            if new:
                os.chflags(self.path, stat.UF_APPEND)
        return entry


def _canon_line(entry: dict) -> str:
    # Written in insertion order (seq, ts, kind, fields, prev, hash, sig); verifiers re-canonicalize.
    return json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
