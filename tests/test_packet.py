import json

import pytest

from govaios.audit import packet, verify
from govaios.audit.log import AuditLog

R = "run1"
Z = "0" * 64


def _mk(tmp_path, outs=()):
    log = AuditLog(tmp_path)
    log.append("flow_approval", flow="f", flow_hash="H", decision="allow")
    prev, seq = Z, 0
    kinds = [("flow_start", {"flow_hash": "H"}), *[("outcome", o) for o in outs
             or [{"step": "s1", "outcome": "confirmed", "count_before": 1, "count_after": 2, "expected": 1}]],
             ("flow_end", {})]
    for k, f in kinds:
        seq += 1
        prev = log.append(k, run=R, run_seq=seq, run_prev=prev, **f)["hash"]
        log.append("request", executor="claude_code", target="x")
    exp = log.append("packet_export", target=R, chain_count=seq, chain_head=prev)
    entries = [json.loads(l) for l in log.path.read_text().splitlines()]
    pem = log.pub_path.read_text()
    return packet.build(entries, R, exp, pem)


def test_packet_has_only_run_entries_and_context(tmp_path):
    p = _mk(tmp_path)
    assert len(p["entries"]) == 3 and [e["kind"] for e in p["context"]] == ["flow_approval"]
    assert all(e.get("executor") != "claude_code" for e in p["entries"] + p["context"])


def test_packet_verifies(tmp_path):
    r = verify.verify_packet(_mk(tmp_path))
    assert r.ok and r.complete and r.problem is None


def test_tampered_entry_fails(tmp_path):
    p = _mk(tmp_path)
    p["entries"][1]["count_after"] = 9
    assert verify.verify_packet(p).problem == "bad hash"


def test_dropped_entry_fails(tmp_path):
    p = _mk(tmp_path)
    del p["entries"][1]
    r = verify.verify_packet(p)
    assert not r.ok and "run_prev" in r.problem


def test_incomplete_without_end(tmp_path):
    p = _mk(tmp_path)
    p["entries"].pop()
    r = verify.verify_packet(p)
    assert r.ok and not r.complete


def test_notes(tmp_path):
    p = _mk(tmp_path, [{"step": "s1", "outcome": "unchecked"}])
    assert "no outcome check" in verify.verify_packet(p).notes


def test_count_only_note(tmp_path):
    assert "count changed; item not matched" in verify.verify_packet(_mk(tmp_path)).notes


def test_cli(tmp_path, capsys):
    f = tmp_path / "p.json"
    f.write_text(json.dumps(_mk(tmp_path)))
    assert verify.main(["--packet", str(f)]) == 0
    assert "OK packet complete" in capsys.readouterr().out


def _resign(e, key):
    import base64
    import hashlib
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from govaios.audit.log import _canon
    body = {k: v for k, v in e.items() if k not in ("hash", "sig")}
    e["hash"] = hashlib.sha256(_canon(body).encode()).hexdigest()
    e["sig"] = base64.b64encode(key.sign(e["hash"].encode(), ec.ECDSA(hashes.SHA256()))).decode()


def _chain(es, key):
    prev = Z
    for e in es:
        if "run_prev" in e:
            e["run_prev"] = prev
        _resign(e, key)
        prev = e["hash"]


def test_other_run_entry_fails(tmp_path):
    p = _mk(tmp_path)
    log = AuditLog(tmp_path)
    p["entries"].append(log.append("flow_end", run="other", run_seq=4, run_prev=p["entries"][-1]["hash"]))
    assert verify.verify_packet(p).problem == "entry from another run"


def test_context_other_flow_fails(tmp_path):
    p = _mk(tmp_path)
    p["context"][0]["flow_hash"] = "X"
    assert not verify.verify_packet(p).ok


def test_context_other_flow_signed_fails(tmp_path):
    p = _mk(tmp_path)
    e = AuditLog(tmp_path).append("flow_approval", flow="f", flow_hash="OTHER", decision="allow")
    p["context"] = [e]
    assert verify.verify_packet(p).problem == "context is for another flow"


def test_context_deny_fails(tmp_path):
    p = _mk(tmp_path)
    p["context"] = [AuditLog(tmp_path).append("flow_approval", flow="f", flow_hash="H", decision="deny")]
    assert verify.verify_packet(p).problem == "context entry is not an approval"


def test_export_other_run_fails(tmp_path):
    p = _mk(tmp_path)
    p["export"] = AuditLog(tmp_path).append("packet_export", target="zzz", chain_count=3, chain_head="a")
    assert verify.verify_packet(p).problem == "export is for another run"


def test_export_not_packet_export(tmp_path):
    p = _mk(tmp_path)
    p["export"] = AuditLog(tmp_path).append("request", target=R)
    assert verify.verify_packet(p).problem == "export is not a packet_export"
    p["export"] = AuditLog(tmp_path).append("packet_export", target=R, run=R, run_seq=1)
    assert verify.verify_packet(p).problem == "export is not a packet_export"


def test_no_approval_note(tmp_path):
    p = _mk(tmp_path)
    p["context"] = []
    assert "no approval entry in this packet" in verify.verify_packet(p).notes


def test_tampered_sig(tmp_path):
    p = _mk(tmp_path)
    p["entries"][0]["sig"] = p["entries"][1]["sig"]
    assert verify.verify_packet(p).problem == "bad signature"


def test_malformed_and_format(tmp_path):
    p = _mk(tmp_path)
    p["format"] = "x"
    assert not verify.verify_packet(p).ok
    p = _mk(tmp_path)
    del p["entries"][-1]["kind"]
    _chain(p["entries"][-1:], __import__("govaios.audit.log", fromlist=["x"]).AuditLog(tmp_path)._key())
    r = verify.verify_packet(p)  # must not raise
    assert not r.ok


def test_resigned_packet_shows_other_key(tmp_path, capsys):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    p = _mk(tmp_path)
    real = verify.verify_packet(p).key_fingerprint
    atk = ec.generate_private_key(ec.SECP256R1())
    for e in p["entries"] + p["context"] + [p["export"]]:
        pass
    _chain(p["entries"], atk)
    _chain(p["context"], atk)
    _resign(p["export"], atk)
    p["pubkey"] = atk.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    r = verify.verify_packet(p)
    assert r.ok and r.key_fingerprint != real
    f = tmp_path / "p.json"
    f.write_text(json.dumps(p))
    assert verify.main(["--packet", str(f), "--pubkey", str(tmp_path / "audit_pubkey.pem")]) == 1
    assert "packet key is not the given key" in capsys.readouterr().out
    assert verify.main(["--packet", str(f)]) == 0
    assert "signed by key " + r.key_fingerprint in capsys.readouterr().out
