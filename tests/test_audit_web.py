import http.client
from urllib.parse import urlencode
import os
import threading

import pytest

from govaios.approvals import Approvals
from govaios.audit.log import AuditLog
from govaios.audit.web import make_server


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def no_auth(monkeypatch):
    from govaios import auth
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    monkeypatch.setattr(auth, "prove", lambda *a, **k: pytest.fail("prove must not be called"))


def _start(home, clock):
    srv, code = make_server(home, now=clock)
    threading.Thread(target=srv.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()
    return srv, code


def _client(srv, code):
    port = srv.server_address[1]

    def req(path, method="GET", cookie=None, headers=None, body=None):
        c = http.client.HTTPConnection("127.0.0.1", port)
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = f"s={cookie}"
        if body is not None:
            h["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body=urlencode(body) if body is not None else None, headers=h)
        r = c.getresponse()
        return r.status, r.read().decode(), r
    r = req(f"/login?c={code}")
    ck = r[2].getheader("Set-Cookie")
    return req, ck.split(";")[0][2:] if ck else None


@pytest.fixture
def web(tmp_path):
    home = tmp_path / "home"
    log = AuditLog(home)
    log.append("flow_start", flow="demo_flow")
    log.append("action", step=1, action="click", target="p.btn", decision="allow", outcome="ok",
               reason="<script>x</script>")
    log.append("flow_end", flow="demo_flow", outcome="done")
    Approvals(home / "approvals.json").approve_flow("demo_flow", "abc123")
    srv, code = _start(home, Clock())
    req, sid = _client(srv, code)

    def get(path, method="GET", tok=True):
        return req(path, method, cookie=sid if tok else None)

    get.req, get.sid, get.code = req, sid, code
    yield home, srv, get
    srv.shutdown()
    srv.server_close()


def test_login_code_single_use_and_expiry(tmp_path):
    clock = Clock()
    srv, code = _start(tmp_path / "h", clock)
    req = _client(srv, code)[0]
    s, _, r = req(f"/login?c={code}")
    assert s == 403  # already used by _client
    srv.shutdown(); srv.server_close()
    srv, code = _start(tmp_path / "h", clock)
    port = srv.server_address[1]
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("GET", f"/login?c={code}")
    r = c.getresponse()
    ck = r.getheader("Set-Cookie")
    assert r.status == 303 and r.getheader("Location") == "/"
    assert ck.startswith("s=") and "HttpOnly" in ck and "SameSite=Strict" in ck and "Path=/" in ck
    srv.shutdown(); srv.server_close()
    clock2 = Clock()
    srv, code = _start(tmp_path / "h", clock2)
    clock2.t += 61
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    c.request("GET", f"/login?c={code}")
    assert c.getresponse().status == 403
    srv.shutdown(); srv.server_close()


def test_pages_need_cookie(web):
    get = web[2]
    for p in ("/", "/log", "/approvals"):
        assert get(p, tok=False)[0] == 403 and get(p)[0] == 200
    assert get(f"/?t={get.code}", tok=False)[0] == 403


def test_host_header_checked(web):
    s = web[2].req("/", cookie=web[2].sid, headers={"Host": "evil.example"})[0]
    assert s == 403


def test_session_expires_and_lock_ends_server(tmp_path, monkeypatch):
    from govaios import auth
    clock = Clock()
    srv, code = _start(tmp_path / "h", clock)
    req, sid = _client(srv, code)
    assert req("/", cookie=sid)[0] == 200
    clock.t += 3601
    called = threading.Event()
    real = srv.shutdown
    monkeypatch.setattr(srv, "shutdown", lambda: (called.set(), real()))
    assert req("/", cookie=sid)[0] == 403
    assert called.wait(2)
    srv.server_close()
    srv, code = _start(tmp_path / "h2", Clock())
    req, sid = _client(srv, code)
    called = threading.Event()
    real = srv.shutdown
    monkeypatch.setattr(srv, "shutdown", lambda: (called.set(), real()))
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    assert req("/", cookie=sid)[0] == 403
    assert called.wait(2)
    srv.server_close()


def _csrf(get):
    import re
    return re.search(r"name=csrf value='([^']+)'", get("/approvals")[1])[1]


def _revokes(home):
    import json
    return [json.loads(l) for l in AuditLog(home).path.read_text().splitlines() if '"revoke"' in l]


def test_revoke_flow(web):
    home, _, get = web
    s, _, r = get.req("/revoke", "POST", cookie=get.sid, body={"csrf": _csrf(get), "kind": "flow", "flow": "demo_flow"})
    assert s == 303 and r.getheader("Location") == "/approvals"
    assert not Approvals(home / "approvals.json").flow_ok("demo_flow", "abc123")
    e = _revokes(home)
    assert len(e) == 1 and e[0]["flow"] == "demo_flow"


def test_revoke_destination(web):
    home, _, get = web
    Approvals(home / "approvals.json").approve_destination("demo_flow", "org1")
    b = {"csrf": _csrf(get), "kind": "destination", "flow": "demo_flow", "destination": "org1"}
    assert get.req("/revoke", "POST", cookie=get.sid, body=b)[0] == 303
    assert not Approvals(home / "approvals.json").destination_ok("demo_flow", "org1")
    assert _revokes(home)[0]["destination"] == "org1"


def test_revoke_rejects_bad_csrf_or_origin(web):
    home, _, get = web
    ok = Approvals(home / "approvals.json")
    t = _csrf(get)
    base = {"kind": "flow", "flow": "demo_flow"}
    for body, hdr in (({**base, "csrf": "wrong"}, {}), (base, {}),
                      ({**base, "csrf": t}, {"Origin": "http://evil"})):
        assert get.req("/revoke", "POST", cookie=get.sid, body=body, headers=hdr)[0] == 403
    assert ok.flow_ok("demo_flow", "abc123") and not _revokes(home)
    assert get.req("/revoke", "POST", cookie=get.sid, body={**base, "csrf": t})[0] == 303


def test_revoke_with_browser_origin(web):
    """What Chrome sends for the page's own form under Referrer-Policy same-origin; `null` stays refused."""
    home, srv, get = web
    own = {"Origin": f"http://127.0.0.1:{srv.server_address[1]}"}
    body = {"csrf": _csrf(get), "kind": "flow", "flow": "demo_flow"}
    assert get.req("/revoke", "POST", cookie=get.sid, body=body, headers={"Origin": "null"})[0] == 403
    assert get.req("/revoke", "POST", cookie=get.sid, body=body, headers=own)[0] == 303
    assert not Approvals(home / "approvals.json").flow_ok("demo_flow", "abc123")


def test_revoke_all(web):
    home, _, get = web
    Approvals(home / "approvals.json").approve_destination("demo_flow", "org1")
    assert get.req("/revoke", "POST", cookie=get.sid, body={"csrf": _csrf(get), "kind": "all"})[0] == 303
    assert Approvals(home / "approvals.json").snapshot() == {"flows": {}, "destinations": {}}
    assert _revokes(home)[0]["reason"] == "all"


def test_values_still_escaped(web):
    home, _, get = web
    Approvals(home / "approvals.json").approve_flow("<script>f</script>", "h")
    body = get("/approvals")[1]
    assert "<script>f" not in body and body.count("&lt;script&gt;f") >= 2


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
    assert get("/", method="POST")[0] == 405 and get("/log", method="PUT")[0] == 405
    assert AuditLog(home).path.read_bytes() == before


def test_unknown_path_404(web):
    assert web[2]("/../audit_key.pem")[0] == 404


def test_escapes_html(web):
    body = web[2]("/run/1")[1]
    assert "<script>x</script>" not in body and "&lt;script&gt;" in body


def test_binds_localhost_only(web):
    assert web[1].server_address[0] == "127.0.0.1"


def test_no_store_headers(web):
    for r in (web[2]("/", tok=False)[2], web[2]("/")[2], web[2]("/log", method="POST")[2], web[2]("/nope")[2], web[2]("/", method="POST")[2]):
        assert r.getheader("Cache-Control") == "no-store"
        assert r.getheader("Referrer-Policy") == "same-origin"
        assert r.getheader("X-Content-Type-Options") == "nosniff"
        assert "default-src 'none'" in r.getheader("Content-Security-Policy")


def test_missing_log_no_crash(tmp_path):
    srv, code = _start(tmp_path / "empty", Clock())
    req, sid = _client(srv, code)
    status, body, _ = req("/", cookie=sid)
    srv.shutdown(); srv.server_close()
    assert status == 200 and "No runs yet" in body and "FAIL" in body


def _raw_server(tmp_path, lines, approvals=None):
    import json as _j
    home = tmp_path / "h2"
    AuditLog(home).append("action", step=1)  # creates keys/home
    p = home / "audit.jsonl"
    os.chflags(p, 0)
    p.write_text("".join(l + "\n" for l in lines))
    if approvals is not None:
        (home / "approvals.json").write_text(approvals)
    srv, code = _start(home, Clock())
    req, sid = _client(srv, code)
    return srv, lambda path: req(path, cookie=sid)


def test_missing_seq_and_hostile_seq(tmp_path):
    srv, get = _raw_server(tmp_path, ['{"kind":"flow_start","flow":"f"}',
                                      '{"seq":"\\"><b>x","kind":"flow_start","flow":"g"}'])
    for path in ("/", "/log"):
        s, body, _ = get(path)
        assert s == 200 and "FAIL" in body and "<b>x" not in body
    srv.shutdown(); srv.server_close()


def test_malformed_approvals_notice(tmp_path):
    for bad in ('{"flows":[1]}', "not json", '{"destinations":{"f":"x"}}', "[1]", '"x"'):
        srv, get = _raw_server(tmp_path, [], bad)
        s, body, _ = get("/approvals")
        srv.shutdown(); srv.server_close()
        assert s == 200 and "approvals.json unreadable" in body


def test_orphans_visible(tmp_path):
    srv, get = _raw_server(tmp_path, ['{"seq":1,"kind":"action","flow":"f","outcome":"ORPHANOUT"}', "garbage<i>",
                                      '{"seq":2,"kind":"flow_start","flow":"f"}'])
    assert "2 entries outside any run" in get("/")[1]
    body = get("/log")[1]
    assert "ORPHANOUT" in body and "unparsed: garbage&lt;i&gt;" in body
    srv.shutdown(); srv.server_close()


def test_render_exception_500(web, monkeypatch):
    import govaios.audit.web as w

    def boom(*a):
        raise RuntimeError("secret")
    monkeypatch.setattr(w, "_page", boom)
    s, body, r = web[2]("/")
    assert s == 500 and body == "internal error" and "secret" not in body
    assert r.getheader("Cache-Control") == "no-store"


def test_host_checked_on_post_and_other_methods(web):
    get = web[2]
    h = {"Host": "evil.example"}
    assert get.req("/revoke", "POST", cookie=get.sid, headers=h, body={"kind": "all"})[0] == 403
    assert get.req("/", "PUT", cookie=get.sid, headers=h)[0] == 403
    assert get.req("/", "PUT", cookie=get.sid)[0] == 405


def test_locked_login_shuts_down(tmp_path, monkeypatch):
    from govaios import auth
    srv, code = _start(tmp_path / "h", Clock())
    called = threading.Event()
    real = srv.shutdown
    monkeypatch.setattr(srv, "shutdown", lambda: (called.set(), real()))
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
    c.request("GET", f"/login?c={code}")
    assert c.getresponse().status == 403 and called.wait(2)
    srv.server_close()


def test_revoke_303_has_security_headers(web):
    get = web[2]
    r = get.req("/revoke", "POST", cookie=get.sid, body={"csrf": _csrf(get), "kind": "all"})[2]
    assert r.status == 303 and r.getheader("Referrer-Policy") == "same-origin"
    assert "default-src 'none'" in r.getheader("Content-Security-Policy")
    assert r.getheader("X-Content-Type-Options") == "nosniff"


def test_command_and_auth_columns_escaped(tmp_path):
    srv, get = _raw_server(tmp_path, ['{"seq":1,"kind":"request","command":"echo <b>hi</b>","auth":"biometric"}',
                                      "garbage"])
    body = get("/log")[1]
    assert "<th>auth</th>" in body and "<th>command</th>" in body and "biometric" in body
    assert "<b>hi" not in body and "echo &lt;b&gt;hi&lt;/b&gt;" in body
    assert "colspan=13 " in body   # seq, ts and every COLS column
    srv.shutdown(); srv.server_close()


def test_normal_entries_outside_runs_not_flagged(tmp_path):
    """M-13: hook requests, stops, logins, revocations and dump are expected outside runs."""
    srv, get = _raw_server(tmp_path, ['{"seq":1,"kind":"request","flow":"claude_code","action":"Bash"}',
                                      '{"seq":2,"kind":"emergency_stop"}', '{"seq":3,"kind":"ui_login"}',
                                      '{"seq":4,"kind":"request","action":"dump"}', '{"seq":5,"kind":"revoke"}'])
    assert "outside any run" not in get("/")[1]
    srv.shutdown(); srv.server_close()


def test_revoke_failure_audited_as_error(web, monkeypatch):
    """M-16: the log never says revoked while the approval stands."""
    home, _, get = web

    def boom(self, flow):
        raise OSError("disk")
    monkeypatch.setattr(Approvals, "revoke_flow", boom)
    s = get.req("/revoke", "POST", cookie=get.sid, body={"csrf": _csrf(get), "kind": "flow", "flow": "demo_flow"})[0]
    assert s == 500 and Approvals(home / "approvals.json").flow_ok("demo_flow", "abc123")
    e = _revokes(home)
    assert [x.get("outcome") for x in e] == [None, "error"] and e[1]["flow"] == "demo_flow"
