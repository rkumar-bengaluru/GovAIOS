import hashlib
import json
import os

from govaios.audit.log import AuditLog, _canon
from govaios.audit.verify import main, verify


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
        return [ls[0], json.dumps(e), ls[2]]

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
