import http.client
import os
import threading

import pytest

from govaios.approvals import Approvals
from govaios.audit.log import AuditLog
from govaios.audit.web import make_server


@pytest.fixture
def web(tmp_path):
    home = tmp_path / "home"
    log = AuditLog(home)
    log.append("flow_start", flow="demo_flow")
    log.append("action", step=1, action="click", target="p.btn", decision="allow", outcome="ok",
               reason="<script>x</script>")
    log.append("flow_end", flow="demo_flow", outcome="done")
    Approvals(home / "approvals.json").approve_flow("demo_flow", "abc123")
    srv, token = make_server(home)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def get(path, method="GET", tok=True):
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        sep = "&" if "?" in path else "?"
        c.request(method, path + (f"{sep}t={token}" if tok else ""))
        r = c.getresponse()
        return r.status, r.read().decode(), r

    yield home, srv, get
    srv.shutdown()
    srv.server_close()


def test_requires_token(web):
    assert web[2]("/", tok=False)[0] == 403


def test_wrong_token_unknown_path_403(web):
    assert web[2]("/nope?t=wrong", tok=False)[0] == 403


def test_index_lists_run(web):
    s, body, _ = web[2]("/")
    assert s == 200 and "demo_flow" in body and "OK 3 entries" in body


def test_run_and_approvals(web):
    s, body, _ = web[2]("/run/1")
    assert s == 200 and "click" in body
    s, body, _ = web[2]("/approvals")
    assert s == 200 and "demo_flow" in body and "abc123" in body
    assert web[2]("/run/x")[0] == 404 and web[2]("/run/999")[0] == 404


def test_tampered_log_banner(web):
    home, _, get = web
    p = AuditLog(home).path
    os.chflags(p, 0)
    p.write_text(p.read_text().replace("click", "clack"))
    assert "FAIL line" in get("/")[1]


def test_post_rejected(web):
    home, _, get = web
    before = AuditLog(home).path.read_bytes()
    assert get("/", method="POST")[0] == 405
    assert AuditLog(home).path.read_bytes() == before


def test_unknown_path_404(web):
    assert web[2]("/../audit_key.pem")[0] == 404


def test_escapes_html(web):
    body = web[2]("/run/1")[1]
    assert "<script>x</script>" not in body and "&lt;script&gt;" in body


def test_binds_localhost_only(web):
    assert web[1].server_address[0] == "127.0.0.1"


def test_no_store_headers(web):
    for r in (web[2]("/", tok=False)[2], web[2]("/")[2], web[2]("/nope")[2], web[2]("/", method="POST")[2]):
        assert r.getheader("Cache-Control") == "no-store"
        assert r.getheader("Referrer-Policy") == "no-referrer"
        assert r.getheader("X-Content-Type-Options") == "nosniff"
        assert "default-src 'none'" in r.getheader("Content-Security-Policy")


def test_missing_log_no_crash(tmp_path):
    srv, token = make_server(tmp_path / "empty")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    c.request("GET", f"/?t={token}")
    r = c.getresponse()
    body = r.read().decode()
    srv.shutdown(); srv.server_close()
    assert r.status == 200 and "No runs yet" in body and "FAIL" in body
