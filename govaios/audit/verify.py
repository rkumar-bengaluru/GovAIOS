"""Standalone audit verifier: python verify.py audit.jsonl audit_pubkey.pem
Proof packet:               python verify.py --packet packet.json
Imports only stdlib + cryptography so it can be copied out and run alone.

Packet mode checks each entry's hash and signature, the per-run chain (run_prev from 64 zeros,
run_seq 1..n, one run, flow_start first), the context entries and the export entry. It does not check prev.
Fingerprint rule (item_left outcomes): sha256 hex of f"{run}\\n{round}\\n{norm(identity)}", where norm =
Unicode NFC, strip, collapse whitespace, casefold. A fingerprint is a commitment: anyone who can guess
the item's name can recompute it and confirm it."""
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


@dataclass
class PacketResult:
    ok: bool
    complete: bool
    notes: list
    problem: str | None


def _signed(e, pub):
    """None when e's hash and signature hold, else the problem."""
    try:
        h, sig = e["hash"], e["sig"]
        body = {k: v for k, v in e.items() if k not in ("hash", "sig")}
        canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        if hashlib.sha256(canon).hexdigest() != h:
            return "bad hash"
    except (KeyError, TypeError, ValueError, AttributeError):
        return "bad hash"
    try:
        pub.verify(base64.b64decode(sig, validate=True), h.encode(), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        return "bad signature"
    return None


def verify_packet(p: dict) -> PacketResult:
    def fail(problem):
        return PacketResult(False, False, [], problem)

    try:
        pub = serialization.load_pem_public_key(p["pubkey"].encode())
        entries, context, export, run = p["entries"], p["context"], p["export"], p["run"]
        if not entries or entries[0].get("kind") != "flow_start":
            return fail("flow_start is not first")
        prev = ZERO
        for i, e in enumerate(entries, 1):
            bad = _signed(e, pub)
            if bad:
                return fail(bad)
            if e.get("run") != run:
                return fail("entry from another run")
            if e.get("run_prev") != prev:
                return fail(f"run_prev broken at entry {i}")
            if e.get("run_seq") != i:
                return fail(f"run_seq gap at entry {i}")
            prev = e["hash"]
        for e in context:
            bad = _signed(e, pub)
            if bad:
                return fail(bad)
            if e.get("flow_hash") != entries[0].get("flow_hash"):
                return fail("context is for another flow")
        bad = _signed(export, pub)
        if bad:
            return fail(bad)
        if export.get("target") != run:
            return fail("export is for another run")
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        return fail(f"malformed packet: {e}")
    notes = []
    outs = [e for e in entries if e["kind"] == "outcome"]
    if any(e.get("outcome") == "unchecked" for e in outs):
        notes.append("no outcome check")
    counted = {e.get("step") for e in outs if e.get("outcome") == "confirmed" and "count_after" in e}
    itemed = {e.get("step") for e in outs if "fingerprint" in e}
    if counted - itemed:
        notes.append("count changed; item not matched")
    return PacketResult(True, entries[-1]["kind"] in ("flow_end", "stop"), notes, None)


def main(argv) -> int:
    if len(argv) == 2 and argv[0] == "--packet":
        try:
            r = verify_packet(json.loads(Path(argv[1]).read_text()))
        except (OSError, ValueError) as e:
            print(f"FAIL: {e}")
            return 1
        if not r.ok:
            print(f"FAIL: {r.problem}")
            return 1
        print(f"OK packet {'complete' if r.complete else 'incomplete (no end entry)'}")
        for n in r.notes:
            print(n)
        return 0
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
