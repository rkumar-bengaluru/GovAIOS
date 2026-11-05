"""Standalone audit verifier: python verify.py audit.jsonl audit_pubkey.pem
Imports only stdlib + cryptography so it can be copied out and run alone."""
import base64
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ZERO = "0" * 64


@dataclass
class VerifyResult:
    ok: bool
    entries: int
    problem: str | None
    line: int | None


def verify(log_path: Path, pubkey_path: Path) -> VerifyResult:
    pub = serialization.load_pem_public_key(Path(pubkey_path).read_bytes())
    data = Path(log_path).read_bytes()
    lines = data.split(b"\n")
    tail = lines.pop()  # b"" when the file ends with a newline
    prev, n = ZERO, 0

    def fail(problem, line):
        return VerifyResult(False, n, problem, line)

    # shortcut: whole trailing lines removed at a line boundary are undetectable without an external anchor (last hash/count); add with the plan-2 sealed checkpoint.
    for i, raw in enumerate(lines, 1):
        try:
            e = json.loads(raw)
            # log.py writes insertion order, compact, ensure_ascii=False; this rejects whitespace, CRLF and duplicate keys
            if json.dumps(e, separators=(",", ":"), ensure_ascii=False).encode() != raw:
                return fail("bad hash", i)
            seq, h, sig, p = e["seq"], e.pop("hash"), e.pop("sig"), e["prev"]
            if not all(isinstance(x, str) for x in (h, sig, p)) or type(seq) is not int:
                raise ValueError
            canon = json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        except (ValueError, KeyError, TypeError, AttributeError):
            return fail("bad hash", i)  # malformed complete line is tampering, not a crash tail
        # shortcut: prev is checked before seq (a deleted line must read "broken chain"); "seq gap" fires only when prev is intact.
        if p != prev:
            return fail("broken chain", i)
        if seq != n + 1:
            return fail("seq gap", i)
        if hashlib.sha256(canon).hexdigest() != h:
            return fail("bad hash", i)
        try:
            pub.verify(base64.b64decode(sig, validate=True), h.encode(), ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, TypeError):
            return fail("bad signature", i)
        prev, n = h, i
    if tail:
        return fail("truncated tail", len(lines) + 1)
    if n == 0:
        return fail("empty log", 1)  # an emptied audit is tampering
    return VerifyResult(True, n, None, None)


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: verify.py audit.jsonl audit_pubkey.pem")
        return 1
    try:
        r = verify(Path(argv[0]), Path(argv[1]))
    except (OSError, ValueError) as e:
        print(f"FAIL: {e}")
        return 1
    print(f"OK {r.entries} entries" if r.ok else f"FAIL line {r.line}: {r.problem}")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
