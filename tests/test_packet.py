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
