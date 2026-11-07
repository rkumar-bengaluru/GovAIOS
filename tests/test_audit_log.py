import sys
import json
import multiprocessing
import os
import stat

import pytest

from govaios.home import data_home
from govaios.audit.log import AuditError, AuditLog, url_for_audit


@pytest.fixture
def home():
    return data_home()


def _worker(home, n):
    log = AuditLog(home)
    for _ in range(n):
        log.append("action", flow="f")


def _lines(home):
    return [json.loads(x) for x in (home / "audit.jsonl").read_text().splitlines()]


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: audit key file mode 0600")
def test_first_entry_links_to_zero(home):
    e = AuditLog(home).append("flow_start", flow="f")
    assert e["seq"] == 1 and e["prev"] == "0" * 64
    assert (home / "audit_key.pem").stat().st_mode & 0o777 == 0o600
    assert (home / "audit_pubkey.pem").exists()


def test_chain_links_and_signature(home):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import base64

    log = AuditLog(home)
    a = log.append("flow_start", flow="f")
    b = log.append("action", step="s1")
    assert b["prev"] == a["hash"] and b["seq"] == 2
    pub = serialization.load_pem_public_key((home / "audit_pubkey.pem").read_bytes())
    pub.verify(base64.b64decode(b["sig"]), b["hash"].encode(), ec.ECDSA(hashes.SHA256()))


def test_unknown_field_rejected(home):
    with pytest.raises(AuditError):
        AuditLog(home).append("action", body="secret")


def test_unknown_kind_rejected(home):
    with pytest.raises(AuditError):
        AuditLog(home).append("bogus", flow="f")


def test_url_for_audit():
    assert url_for_audit("https://mail.google.com/mail/u/0/?q=x#inbox/123") == "https://mail.google.com/mail/u/0/"


def test_missing_key_with_existing_log_refuses(home):
    AuditLog(home).append("flow_start", flow="f")
    (home / "audit_key.pem").unlink()
    with pytest.raises(AuditError, match="audit key missing"):
        AuditLog(home).append("action", flow="f")


def test_truncated_tail_refuses_append(home):
    log = AuditLog(home)
    log.append("flow_start", flow="f")
    log.append("action", flow="f")
    with open(home / "audit.jsonl", "ab") as f:
        f.write(b'{"seq": 3, "ts')
    with pytest.raises(AuditError, match="truncated"):
        log.append("action", flow="f")


def test_concurrent_appends_stay_chained(home):
    ps = [multiprocessing.Process(target=_worker, args=(home, 50)) for _ in range(2)]
    [p.start() for p in ps]
    [p.join() for p in ps]
    assert all(p.exitcode == 0 for p in ps)
    ents = _lines(home)
    assert [e["seq"] for e in ents] == list(range(1, 101))
    assert ents[0]["prev"] == "0" * 64
    assert all(ents[i]["prev"] == ents[i - 1]["hash"] for i in range(1, 100))


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: UF_APPEND flag")
def test_file_is_append_only_flag(home):
    AuditLog(home).append("flow_start", flow="f")
    assert os.stat(home / "audit.jsonl").st_flags & stat.UF_APPEND


def test_url_for_audit_drops_userinfo():
    assert url_for_audit("https://alice:hunter2@mail.google.com:443/mail/?q=x#y") == "https://mail.google.com:443/mail/"


@pytest.mark.parametrize("v", [{"body": "secret"}, 1.5, float("nan"), "\ud800", b"x", ["a"]])
def test_bad_values_rejected(home, v):
    with pytest.raises(AuditError):
        AuditLog(home).append("action", target=v)
    assert not (home / "audit.jsonl").exists()


def test_corrupt_key_raises_audit_error(home):
    AuditLog(home).append("flow_start", flow="f")
    (home / "audit_key.pem").write_text("")
    with pytest.raises(AuditError):
        AuditLog(home).append("action", flow="f")


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: UF_APPEND flag (os.chflags)")
def test_append_only_flag_rearmed(home):
    log = AuditLog(home)
    log.append("flow_start", flow="f")
    os.chflags(home / "audit.jsonl", 0)
    log.append("action", flow="f")
    assert os.stat(home / "audit.jsonl").st_flags & stat.UF_APPEND


def test_url_for_audit_non_http_has_no_payload():
    from govaios.audit.log import url_for_audit
    assert url_for_audit("data:text/html,<b>secret</b>") == "data:"
    assert url_for_audit("javascript:alert(1)") == "javascript:"
