import sys
import pytest
import hashlib
import json
import os

from govaios.audit.log import AuditLog, _canon
from govaios.audit.verify import main, verify

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="macOS: audit log UF_APPEND flag (os.chflags)")


def _mk(home, n=3):
    log = AuditLog(home)
    for i in range(n):
        log.append("action", step=i, outcome="ok")
    os.chflags(log.path, 0)
    return log.path, log.pub_path


def _rewrite(path, fn):
    lines = path.read_text().splitlines()
    path.write_text("".join(l + "\n" for l in fn(lines)))


def _r(res):
    return res.problem, res.line


def test_clean_log_ok(tmp_path):
    p, k = _mk(tmp_path)
    r = verify(p, k)
    assert r.ok and r.entries == 3 and r.problem is None


def test_edited_field_bad_hash(tmp_path):
    p, k = _mk(tmp_path)
    _rewrite(p, lambda ls: [ls[0], ls[1].replace('"ok"', '"x"'), ls[2]])
    assert _r(verify(p, k)) == ("bad hash", 2)


def test_rehashed_edit_bad_signature(tmp_path):
    p, k = _mk(tmp_path)

    def edit(ls):
        e = json.loads(ls[1])
        e["outcome"] = "x"
        e.pop("hash"), e.pop("sig")
        h = hashlib.sha256(_canon(e).encode()).hexdigest()
        e["hash"] = h
        e["sig"] = json.loads(ls[1])["sig"]
        return [ls[0], json.dumps(e, separators=(",", ":"), ensure_ascii=False), ls[2]]

    _rewrite(p, edit)
    assert _r(verify(p, k)) == ("bad signature", 2)


def test_deleted_middle_entry(tmp_path):
    p, k = _mk(tmp_path)
    _rewrite(p, lambda ls: [ls[0], ls[2]])
    assert _r(verify(p, k)) == ("broken chain", 2)


def test_truncated_tail_reported(tmp_path):
    p, k = _mk(tmp_path)
    with open(p, "a") as f:
        f.write('{"seq":4,"ts"')
    assert _r(verify(p, k)) == ("truncated tail", 4)


def test_cli_exit_codes(tmp_path, capsys):
    p, k = _mk(tmp_path)
    assert main([str(p), str(k)]) == 0
    assert capsys.readouterr().out.strip() == "OK 3 entries"
    _rewrite(p, lambda ls: [ls[0], ls[2]])
    assert main([str(p), str(k)]) == 1
    assert capsys.readouterr().out.strip() == "FAIL line 2: broken chain"


def test_empty_log_fails(tmp_path):
    p, k = _mk(tmp_path)
    p.write_bytes(b"")
    assert _r(verify(p, k)) == ("empty log", 1)


def test_spacing_is_bad_hash(tmp_path):
    p, k = _mk(tmp_path)
    _rewrite(p, lambda ls: [json.dumps(json.loads(ls[0]), separators=(", ", ": ")), *ls[1:]])
    assert _r(verify(p, k)) == ("bad hash", 1)


def test_crlf_is_bad_hash(tmp_path):
    p, k = _mk(tmp_path)
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert _r(verify(p, k)) == ("bad hash", 1)


def test_key_swap_bad_signature(tmp_path):
    p, _ = _mk(tmp_path / "a")
    _, other = _mk(tmp_path / "b")
    assert _r(verify(p, other)) == ("bad signature", 1)


def test_non_json_line_bad_hash(tmp_path):
    p, k = _mk(tmp_path)
    _rewrite(p, lambda ls: [ls[0], "not json", ls[2]])
    assert _r(verify(p, k)) == ("bad hash", 2)


def test_seq_gap(tmp_path):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import base64
    log = AuditLog(tmp_path)
    log.append("action", step=0)
    os.chflags(log.path, 0)
    first = json.loads(log.path.read_text().splitlines()[0])
    e = {"seq": 3, "ts": first["ts"], "kind": "action", "prev": first["hash"]}
    e["hash"] = hashlib.sha256(_canon(e).encode()).hexdigest()
    key = serialization.load_pem_private_key(log.key_path.read_bytes(), None)
    e["sig"] = base64.b64encode(key.sign(e["hash"].encode(), ec.ECDSA(hashes.SHA256()))).decode()
    with open(log.path, "a") as f:
        f.write(json.dumps(e, separators=(",", ":"), ensure_ascii=False) + "\n")
    assert _r(verify(log.path, log.pub_path)) == ("seq gap", 2)
