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
    srv = make_server(home, now=clock)
    threading.Thread(target=srv.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()
    return srv


def _client(srv, ui):
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
    return req, ui.signin(srv)


@pytest.fixture
def web(tmp_path, ui):
    home = tmp_path / "home"
    log = AuditLog(home)
    log.append("flow_start", flow="demo_flow")
    log.append("action", step=1, action="click", target="p.btn", decision="allow", outcome="ok",
               reason="<script>x</script>")
    log.append("flow_end", flow="demo_flow", outcome="done")
    Approvals(home / "approvals.json").approve_flow("demo_flow", "abc123")
    srv = _start(home, Clock())
    req, sid = _client(srv, ui)

    def get(path, method="GET", tok=True):
        return req(path, method, cookie=sid if tok else None)

    get.req, get.sid = req, sid
    yield home, srv, get
    srv.shutdown()
    srv.server_close()


def test_pages_need_cookie(web):
    get = web[2]
    for p in ("/", "/audit", "/audit/log", "/approvals"):
        s, body, _ = get(p, tok=False)
        assert s == 200 and "Sign in with Touch ID" in body and "demo_flow" not in body and "Revoke" not in body
        assert get(p)[0] == 200 and "Sign in with Touch ID" not in get(p)[1]
    assert "demo_flow" not in get.req("/audit", cookie="forged")[1]


def test_host_header_checked(web):
    s = web[2].req("/", cookie=web[2].sid, headers={"Host": "evil.example"})[0]
    assert s == 403


def test_signin_expires_and_lock_never_end_server(tmp_path, monkeypatch, ui):
    from govaios import auth
    clock = Clock()
    srv = _start(tmp_path / "h", clock)
    monkeypatch.setattr(srv, "shutdown", lambda: pytest.fail("the panel never shuts itself down"))
    req, sid = _client(srv, ui)
    assert req("/", cookie=sid)[0] == 200
    clock.t += 8 * 3600
    assert "Sign in with Touch ID" in req("/", cookie=sid)[1]
    sid = _client(srv, ui)[1]
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    assert req("/", cookie=sid)[0] == 403
    srv.panel.tick()
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    assert "Sign in with Touch ID" in req("/", cookie=sid)[1]
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
    s, body, _ = web[2]("/audit")
    assert s == 200 and "demo_flow" in body and "OK 4 entries" in body


def test_run_and_approvals(web):
    s, body, _ = web[2]("/audit/run/1")
    assert s == 200 and "click" in body
    s, body, _ = web[2]("/approvals")
    assert s == 200 and "demo_flow" in body and "abc123" in body
    assert web[2]("/audit/run/x")[0] == 404 and web[2]("/audit/run/999")[0] == 404


def test_tampered_log_banner(web):
    home, _, get = web
    p = AuditLog(home).path
    os.chflags(p, 0)
    p.write_text(p.read_text().replace("click", "clack"))
    assert "FAIL line" in get("/audit")[1]


def test_post_rejected(web):
    home, _, get = web
    before = AuditLog(home).path.read_bytes()
    assert get("/", method="POST")[0] == 405 and get("/log", method="PUT")[0] == 405
    assert AuditLog(home).path.read_bytes() == before


def test_unknown_path_404(web):
    assert web[2]("/../audit_key.pem")[0] == 404


def test_escapes_html(web):
    body = web[2]("/audit/run/1")[1]
    assert "<script>x</script>" not in body and "&lt;script&gt;" in body


def test_binds_localhost_only(web):
    assert web[1].server_address[0] == "127.0.0.1"


def test_no_store_headers(web):
    for r in (web[2]("/", tok=False)[2], web[2]("/")[2], web[2]("/log", method="POST")[2], web[2]("/nope")[2], web[2]("/", method="POST")[2]):
        assert r.getheader("Cache-Control") == "no-store"
        assert r.getheader("Referrer-Policy") == "same-origin"
        assert r.getheader("X-Content-Type-Options") == "nosniff"
        assert "default-src 'none'" in r.getheader("Content-Security-Policy")


def test_missing_log_no_crash(tmp_path, ui):
    srv = _start(tmp_path / "empty", Clock())
    req, sid = _client(srv, ui)
    p = AuditLog(tmp_path / "empty").path   # sign-in wrote ui_login; take the log away again
    os.chflags(p, 0)
    p.unlink()
    status, body, _ = req("/audit", cookie=sid)
    srv.shutdown(); srv.server_close()
    assert status == 200 and "No apps yet" in body and "FAIL" in body


def _raw_server(tmp_path, ui, lines, approvals=None):
    import json as _j
    home = tmp_path / "h2"
    AuditLog(home).append("action", step=1)  # creates keys/home
    srv = _start(home, Clock())
    req, sid = _client(srv, ui)   # sign in (audits ui_login) before the log is replaced
    p = home / "audit.jsonl"
    os.chflags(p, 0)
    p.write_text("".join(l + "\n" for l in lines))
    if approvals is not None:
        (home / "approvals.json").write_text(approvals)
    return srv, lambda path: req(path, cookie=sid)


def test_missing_seq_and_hostile_seq(tmp_path, ui):
    srv, get = _raw_server(tmp_path, ui, ['{"kind":"flow_start","flow":"f"}',
                                      '{"seq":"\\"><b>x","kind":"flow_start","flow":"g"}'])
    for path in ("/audit", "/audit/log"):
        s, body, _ = get(path)
        assert s == 200 and "FAIL" in body and "<b>x" not in body
    srv.shutdown(); srv.server_close()


def test_malformed_approvals_notice(tmp_path, ui):
    for bad in ('{"flows":[1]}', "not json", '{"destinations":{"f":"x"}}', "[1]", '"x"'):
        srv, get = _raw_server(tmp_path, ui, [], bad)
        s, body, _ = get("/approvals")
        srv.shutdown(); srv.server_close()
        assert s == 200 and "approvals.json unreadable" in body


def test_orphans_visible(tmp_path, ui):
    srv, get = _raw_server(tmp_path, ui, ['{"seq":1,"kind":"action","flow":"f","outcome":"ORPHANOUT"}', "garbage<i>",
                                      '{"seq":2,"kind":"flow_start","flow":"f"}'])
    assert "2 entries outside any run" in get("/audit")[1]
    body = get("/audit/log")[1]
    assert "ORPHANOUT" in body and "unparsed: garbage&lt;i&gt;" in body
    srv.shutdown(); srv.server_close()


def test_render_exception_500(web, monkeypatch):
    import govaios.audit.web as w

    def boom(*a):
        raise RuntimeError("secret")
    monkeypatch.setattr(w, "_page", boom)
    s, body, r = web[2]("/audit")
    assert s == 500 and body == "internal error" and "secret" not in body
    assert r.getheader("Cache-Control") == "no-store"


def test_host_checked_on_post_and_other_methods(web):
    get = web[2]
    h = {"Host": "evil.example"}
    assert get.req("/revoke", "POST", cookie=get.sid, headers=h, body={"kind": "all"})[0] == 403
    assert get.req("/", "PUT", cookie=get.sid, headers=h)[0] == 403
    assert get.req("/", "PUT", cookie=get.sid)[0] == 405


def test_locked_signin_refused_and_server_stays(tmp_path, monkeypatch, ui):
    from govaios import auth
    srv = _start(tmp_path / "h", Clock())
    monkeypatch.setattr(srv, "shutdown", lambda: pytest.fail("the panel never shuts itself down"))
    port = srv.server_address[1]
    _, pre, ck, _ = ui.signed_out(port)
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    assert ui.signin_post(port, ck, pre)[0] == 403   # no_auth: prove would fail the test
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    assert ui.raw(port, "GET", "/")[0] == 200
    srv.server_close()


def test_revoke_303_has_security_headers(web):
    get = web[2]
    r = get.req("/revoke", "POST", cookie=get.sid, body={"csrf": _csrf(get), "kind": "all"})[2]
    assert r.status == 303 and r.getheader("Referrer-Policy") == "same-origin"
    assert "default-src 'none'" in r.getheader("Content-Security-Policy")
    assert r.getheader("X-Content-Type-Options") == "nosniff"


def test_command_and_auth_columns_escaped(tmp_path, ui):
    srv, get = _raw_server(tmp_path, ui, ['{"seq":1,"kind":"request","command":"echo <b>hi</b>","auth":"biometric"}',
                                      "garbage"])
    body = get("/audit/log")[1]
    assert "<th>auth</th>" in body and "<th>command</th>" in body and "biometric" in body
    assert "<b>hi" not in body and "echo &lt;b&gt;hi&lt;/b&gt;" in body
    assert "colspan=17 " in body   # seq, ts and every COLS column
    srv.shutdown(); srv.server_close()


def test_normal_entries_outside_runs_not_flagged(tmp_path, ui):
    """M-13: hook requests, stops, logins, revocations and dump are expected outside runs."""
    srv, get = _raw_server(tmp_path, ui, ['{"seq":1,"kind":"request","flow":"claude_code","action":"Bash"}',
                                      '{"seq":2,"kind":"emergency_stop"}', '{"seq":3,"kind":"ui_login"}',
                                      '{"seq":4,"kind":"request","action":"dump"}', '{"seq":5,"kind":"revoke"}',
                                      '{"seq":6,"kind":"request","flow":"f1","action":"deliver"}'])
    assert "outside any run" not in get("/audit")[1]
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


def test_revoke_buttons_say_what_they_revoke(web):
    home, _, get = web
    Approvals(home / "approvals.json").approve_destination("demo_flow", "org1")
    body = get("/approvals")[1]
    assert "Revoke flow</button>" in body and "Revoke site</button>" in body


def test_delivery_entry_shows_its_fields(tmp_path, ui):
    srv, get = _raw_server(tmp_path, ui, ['{"seq":1,"kind":"delivery","flow":"f1","target":"joblens","file_hash":"ab12",'
                                      '"response_code":202,"listing_id":4711,"outcome":"delivered"}'])
    body = get("/audit/log")[1]
    for c in ("flow", "response_code", "listing_id", "file_hash"):
        assert f"<th>{c}</th>" in body
    assert "<td>202</td>" in body and "<td>4711</td>" in body and "<td>ab12</td>" in body and "<td>f1</td>" in body
    srv.shutdown(); srv.server_close()


def _app_server(tmp_path, ui, entries, flows=True):
    home = tmp_path / "home"
    log = AuditLog(home)
    for kind, f in entries:
        log.append(kind, **f)
    fd = None
    if flows:
        fd = home / "apps" / "flows"
        fd.mkdir(parents=True)
        (home / "apps" / "pages").mkdir()
        for i, n in (("alpha", "Alpha App"), ("beta", "Beta App")):
            (fd / f"{i}.yaml").write_text(f"workflow:\n  id: {i}\n  name: {n}\n  app: {n}\n  steps: []\n")
    srv = make_server(home, now=Clock(), flows_dir=fd)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    req, sid = _client(srv, ui)
    return srv, lambda p: req(p, cookie=sid)


RUNS = [("flow_start", {"flow": "alpha"}), ("request", {"action": "run_start", "channel": "totp_session"}),
        ("delivery", {"flow": "alpha", "outcome": "delivered"}), ("delivery", {"flow": "alpha", "outcome": "delivered"}),
        ("delivery", {"flow": "alpha", "outcome": "duplicate"}), ("flow_end", {"flow": "alpha", "outcome": "done"}),
        ("flow_start", {"flow": "alpha"}), ("request", {"action": "run_start", "channel": "touch_id"}),
        ("flow_end", {"flow": "alpha", "outcome": "failed"}),
        ("flow_start", {"flow": "gone_app"}), ("flow_end", {"flow": "gone_app", "outcome": "done"})]


def test_audit_lists_apps(tmp_path, ui):
    srv, get = _app_server(tmp_path, ui, RUNS)
    body = get("/audit")[1]
    assert body.index("Alpha App") < body.index("Beta App") < body.index("Removed apps") < body.index("gone_app")
    assert "href='/audit/app/alpha'" in body and "<td>2</td>" in body and "failed" in body and "Terminal" in body
    srv.shutdown(); srv.server_close()


def test_audit_app_page_only_its_runs(tmp_path, ui):
    srv, get = _app_server(tmp_path, ui, RUNS)
    s, body, _ = get("/audit/app/alpha")
    assert s == 200 and "gone_app" not in body and "delivered 2, duplicate 1" in body
    assert body.index("<td>failed") < body.index("<td>done") and "Panel" in body and "Terminal" in body
    assert "href='/audit/run/" in body and "/audit/log" in body
    assert get("/audit/app/gone_app")[0] == 200 and get("/audit/app/nosuch")[0] == 404
    srv.shutdown(); srv.server_close()


def test_audit_app_bad_id_404(tmp_path, ui):
    srv, get = _app_server(tmp_path, ui, RUNS)
    for bad in ("../x", "A", "%2e%2e", "a" * 65):
        assert get(f"/audit/app/{bad}")[0] == 404
    srv.shutdown(); srv.server_close()


def test_old_runs_started_by_dash(tmp_path, ui):
    srv, get = _app_server(tmp_path, ui, [("flow_start", {"flow": "alpha"}), ("flow_end", {"flow": "alpha", "outcome": "done"})])
    assert "<td>—</td>" in get("/audit/app/alpha")[1]
    srv.shutdown(); srv.server_close()


def test_audit_without_flows_dir_state_dash(tmp_path, ui):
    srv, get = _app_server(tmp_path, ui, RUNS, flows=False)
    body = get("/audit")[1]
    assert "gone_app" in body and "Removed" not in body
    srv.shutdown(); srv.server_close()
