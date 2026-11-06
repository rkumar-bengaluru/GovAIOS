import base64
import http.client
import json
import re
import shutil
import threading
import time
from urllib.parse import urlencode

import pytest

from govaios.approvals import Approvals
from govaios.audit.log import AuditLog
from govaios.audit.web import make_server
from govaios.engine import REPO, approval_question
from govaios.panel.apps import list_apps
from govaios.panel.session import Session
from govaios.panel.totp import SecretStore, code_at

CHAIN = {"seq", "ts", "prev", "hash", "sig"}   # chain metadata, not entry content
CSP = "default-src 'none'; style-src 'unsafe-inline'"


class FakeLaunch:
    def __init__(self, flow_path, ticket):
        self.flow_path, self.ticket = flow_path, ticket
        self.done, self.started, self.stopped = False, False, None
        self.code, self.summary, self.stopped_reason = None, None, None
        self._lines = ["step 3 <script>alert(1)</script>"]
        self.made.append(self)

    def start(self):
        self.started = True

    def lines(self):
        return list(self._lines)

    def stop(self, reason):
        self.stopped = self.stopped_reason = reason


@pytest.fixture
def panel(tmp_path, monkeypatch):
    from govaios import auth
    flows = tmp_path / "flows"
    shutil.copytree(REPO / "flows", flows)
    shutil.copytree(REPO / "pages", tmp_path / "pages")
    for f, app in (("himalayas_job_vetting", "JobLens"), ("morning_inbox_briefing", "Inbox briefing")):
        p = flows / f"{f}.yaml"
        p.write_text(p.read_text().replace("\n  name:", f"\n  app: {app}\n  name:", 1))
    home = tmp_path / "home"
    home.mkdir()
    jl = next(a for a in list_apps(flows, home) if a.name == "JobLens")
    Approvals(home / "approvals.json").approve_flow(jl.id, jl.digest)
    answers = {"approve": True, "prove": True}
    asked = []
    from govaios import identity
    monkeypatch.setattr(identity, "check", lambda: {"bundle_id": "com.govaios.cli"})
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    monkeypatch.setattr(auth, "approve", lambda q, r, h, **k: (asked.append(q), (answers["approve"], "biometric"))[1])
    monkeypatch.setattr(auth, "prove", lambda r, h, **k: (asked.append(r), (answers["prove"], "biometric"))[1])
    made = []
    launcher = type("L", (FakeLaunch,), {"made": made})
    spoken = []
    mono, wall = [0.0], [0.0]   # offsets added to the session's monotonic clock and the browser-session clock
    srv, code = make_server(home, flows_dir=flows, launcher=launcher, speak=spoken.append,
                            now=lambda: time.time() + wall[0], session=Session(lambda: time.monotonic() + mono[0]))
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
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

    sid = req(f"/login?c={code}")[2].getheader("Set-Cookie").split(";")[0][2:]
    P = type("P", (), {})()
    P.home, P.flows, P.srv, P.made, P.answers, P.asked, P.req, P.sid = home, flows, srv, made, answers, asked, req, sid
    P.spoken, P.mono, P.wall = spoken, mono, wall
    P.get = lambda path: req(path, cookie=sid)
    P.csrf = lambda: re.search(r"name=csrf value='([^']+)'", P.get("/")[1])[1]
    P.post = lambda path, headers=None, **f: req(path, "POST", cookie=sid, headers=headers,
                                                  body={"csrf": P.csrf(), **f})
    P.say = lambda text: P.post("/say", text=text)
    yield P
    srv.shutdown()
    srv.server_close()


def _log(home, kind=None):
    p = AuditLog(home).path
    es = [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []
    return [e for e in es if kind is None or e["kind"] == kind]


def _secret(P):
    s = b"0123456789abcdefghij"
    SecretStore(P.home).save(s)
    return s


def _wrong(secret):
    t = time.time()
    near = {code_at(secret, t + d) for d in (-60, -30, 0, 30, 60)}
    return next(c for c in (f"{i:06d}" for i in range(731946, 10**6)) if c not in near)


def test_forged_requests_never_run(panel):
    P = panel
    code = code_at(_secret(P), time.time())
    t = P.csrf()
    port = P.srv.server_address[1]
    assert P.req("/say", "POST", body={"csrf": t, "text": code})[0] == 403
    assert P.req("/say", "POST", cookie=P.sid, headers={"Origin": "http://evil"}, body={"csrf": t, "text": code})[0] == 403
    assert P.req("/say", "POST", cookie=P.sid, headers={"Origin": "null"}, body={"csrf": t, "text": code})[0] == 403
    assert P.req("/say", "POST", cookie=P.sid, body={"csrf": "wrong", "text": code})[0] == 403
    assert P.req("/say", "POST", cookie=P.sid, body={"text": code})[0] == 403
    assert not _log(P.home, "session_open")
    own = {"Origin": f"http://127.0.0.1:{port}"}
    assert P.post("/say", headers=own, text=code)[0] == 303   # the page's own form works
    assert len(_log(P.home, "session_open")) == 1
    for s in (P.req("/say", "POST", body={"csrf": t, "text": "run joblens"})[0],
              P.req("/say", "POST", cookie=P.sid, headers={"Origin": "http://evil"}, body={"csrf": t, "text": "run joblens"})[0],
              P.req("/say", "POST", cookie=P.sid, body={"csrf": "x", "text": "run joblens"})[0]):
        assert s == 403
    assert not P.made


def test_code_opens_session_then_run(panel):
    P = panel
    code = code_at(_secret(P), time.time())
    assert "No session" in P.get("/")[1]
    assert P.say(code)[0] == 303
    e = _log(P.home, "session_open")
    assert len(e) == 1 and e[0]["decision"] == "allow" and e[0]["session"]
    assert not any(code in str(v) for k, v in e[0].items() if k not in CHAIN)
    body = P.get("/")[1]
    assert "Session open: 30 min left" in body and "Admin -&gt; ••••••" in body and code not in body
    assert "End session" in body
    P.say("Run the JobLens app now")
    assert len(P.made) == 1
    L = P.made[0]
    assert str(L.flow_path) == str(P.flows / "himalayas_job_vetting.yaml") and L.started
    t = json.loads((P.home / "tickets" / L.ticket).read_text())
    assert t["flow"] == "himalayas_job_vetting" and t["session"] == e[0]["session"]
    assert P.srv.panel.run is L and P.srv.panel.session.active()


def test_no_session_asks_for_code(panel):
    P = panel
    _secret(P)
    P.say("run joblens")
    body = P.get("/")[1]
    assert "Admin -&gt; run joblens" in body and "Enter the 6-digit code from your authenticator." in body
    assert not P.made and not _log(P.home, "session_open")


def test_wrong_code_audited_without_code(panel):
    P = panel
    bad = _wrong(_secret(P))
    P.say(bad)
    e = _log(P.home, "session_open")
    assert len(e) == 1 and e[0]["decision"] == "deny" and e[0]["reason"] == "bad_code"
    assert not any(bad in str(v) for k, v in e[0].items() if k not in CHAIN)
    body = P.get("/")[1]
    assert "That code did not work." in body and bad not in body and "No session" in body
    for _ in range(5):
        P.say(bad)
    assert _log(P.home, "session_open")[-1]["reason"] == "locked_out"
    assert "Too many wrong codes. Try again in 15 minutes." in P.get("/")[1]
    assert not P.srv.panel.session.active()


def _open(P):
    P.say(code_at(_secret(P), time.time()))
    assert P.srv.panel.session.active()


def test_draft_refused_text(panel):
    P = panel
    _open(P)
    P.say("run inbox briefing")
    assert "Inbox briefing is a draft. Get it approved first." in P.get("/")[1] and not P.made


def test_unknown_and_ambiguous_texts(panel):
    P = panel
    _open(P)
    P.say("run mail")
    assert "I don&#x27;t know that app. Approved apps: JobLens." in P.get("/")[1]
    src = (P.flows / "himalayas_job_vetting.yaml").read_text()
    (P.flows / "two.yaml").write_text(src.replace("id: himalayas_job_vetting", "id: himalayas_two", 1))
    P.say("run joblens")
    assert "Which app: JobLens, JobLens?" in P.get("/")[1] and not P.made


def test_busy_text(panel):
    P = panel
    _open(P)
    P.say("run joblens")
    assert '<meta http-equiv="refresh" content="2">' in P.get("/")[1]
    P.say("run joblens")
    assert "JobLens is still running." in P.get("/")[1] and len(P.made) == 1
    P.made[0].done = True
    assert "refresh" not in P.get("/")[1]
    P.say("run joblens")
    assert len(P.made) == 2


def test_setup_requires_code_then_touch_id(panel):
    P = panel
    store = SecretStore(P.home)
    assert "href='/totp/setup'>Set up</a>" in P.get("/approvals")[1]
    s, body, _ = P.get("/totp/setup")
    assert s == 200 and "<svg" in body
    key = re.search(r"<code>([A-Z2-7]+)</code>", body)[1]
    assert P.get("/totp/setup")[1].count(key) == 1   # pending secret kept across GETs
    secret = base64.b32decode(key + "=" * (-len(key) % 8))
    P.post("/totp/setup", code=_wrong(secret))
    assert store.load() is None and not P.asked
    P.answers["approve"] = False
    P.post("/totp/setup", code=code_at(secret, time.time()))
    assert store.load() is None and P.asked == ["Set up the authenticator for GOV-AIOS?"] and not _log(P.home, "totp_setup")
    P.answers["approve"] = True
    used = code_at(secret, time.time())
    assert P.post("/totp/setup", code=used)[0] == 303
    assert store.load() == secret and len(_log(P.home, "totp_setup")) == 1
    assert (P.home / "totp.state").stat().st_mode & 0o777 == 0o600
    P.say(used)   # the setup code is spent: it cannot also open a session
    assert _log(P.home, "session_open")[-1]["reason"] == "replay" and not P.srv.panel.session.active()
    assert P.get("/totp/setup")[0] == 404
    assert "Reset authenticator</button>" in P.get("/approvals")[1]


def test_reset_and_end_session(panel):
    P = panel
    _open(P)
    sid = P.srv.panel.session.id
    P.post("/end")
    assert not P.srv.panel.session.active()
    assert _log(P.home, "session_end")[-1] == {**_log(P.home, "session_end")[-1], "session": sid, "reason": "ended"}
    P.answers["prove"] = False
    P.post("/totp/reset")
    assert SecretStore(P.home).load() is not None and not _log(P.home, "totp_reset")
    P.say(code_at(SecretStore(P.home).load(), time.time() + 30))
    P.say("run joblens")
    P.answers["prove"] = True
    P.post("/totp/reset")
    assert SecretStore(P.home).load() is None and len(_log(P.home, "totp_reset")) == 1
    assert _log(P.home, "session_end")[-1]["reason"] == "reset" and not P.srv.panel.session.active()
    assert P.made[0].stopped == "session ended"


def test_approve_draft_uses_native_dialog(panel):
    P = panel
    ap = P.home / "approvals.json"
    before = ap.read_bytes()
    P.answers["approve"] = False
    assert "Approve…</button>" in P.get("/")[1]
    P.post("/approve", flow="morning_inbox_briefing")
    assert ap.read_bytes() == before
    import yaml
    wf = yaml.safe_load((P.flows / "morning_inbox_briefing.yaml").read_text())["workflow"]
    assert P.asked == [approval_question(wf, None)]
    P.answers["approve"] = True
    P.post("/approve", flow="morning_inbox_briefing")
    assert all(a.approved for a in list_apps(P.flows, P.home))
    fa = _log(P.home, "flow_approval")
    assert [e["decision"] for e in fa] == ["deny", "allow"] and {e["executor"] for e in fa} == {"gov_runner"}
    P.post("/approve", flow="no_such_flow")
    assert len(P.asked) == 2


def test_audit_pages_moved(panel):
    P = panel
    log = AuditLog(P.home)
    log.append("flow_start", flow="a")
    log.append("request", action="run_start", channel="totp_session", auth="ticket", session="s1")
    log.append("flow_end", flow="a", outcome="done")
    log.append("flow_start", flow="b")
    log.append("request", action="run_start", channel="touch_id", auth="biometric")
    log.append("flow_end", flow="b", outcome="done")
    s, body, _ = P.get("/audit")
    assert s == 200 and "<th>started by</th>" in body and "OK 6 entries" in body
    assert "Panel, session code" in body and "Terminal, Touch ID" in body
    assert P.get("/audit/run/1")[0] == 200 and P.get("/audit/log")[0] == 200
    assert P.get("/log")[0] == 404 and P.get("/run/1")[0] == 404
    talk = P.get("/")[1]
    assert "started by" not in talk and "OK 6 entries" not in talk


def test_page_has_no_script_and_csp_unchanged(panel):
    P = panel
    _open(P)
    P.say("run joblens")
    for path in ("/", "/audit", "/audit/log", "/approvals"):
        s, body, r = P.get(path)
        assert s == 200 and "<script" not in body.lower()
        assert r.getheader("Content-Security-Policy") == CSP
    SecretStore(P.home).delete()
    s, body, r = P.get("/totp/setup")
    assert s == 200 and "<script" not in body.lower() and r.getheader("Content-Security-Policy") == CSP


def test_no_content_in_page(panel):
    P = panel
    (P.home / "jobs").mkdir()
    (P.home / "jobs" / "job.json").write_text(json.dumps({"title": "ZQXMARKER", "body": "ZQXMARKER"}))
    _open(P)
    P.say("run joblens")
    body = P.get("/")[1]
    assert "step 3 &lt;script&gt;alert(1)&lt;/script&gt;" in body and "ZQXMARKER" not in body
    for path in ("/audit", "/audit/log", "/approvals"):
        assert "ZQXMARKER" not in P.get(path)[1]


def test_digits_masked_in_admin_line(panel):
    P = panel
    _open(P)
    for text in ("code 123 456", "code 123456 now", "x9876543y"):
        P.say(text)
    body = P.get("/")[1]
    assert "Admin -&gt; code •••••• now" in body and "Admin -&gt; code ••••••<" in body and "x••••••3y" in body
    assert "123" not in body and "456" not in body and "987654" not in body


def _running(P):
    _open(P)
    P.say("run joblens")
    assert len(P.made) == 1
    return P.made[0]


def _tick(P):
    P.srv.panel.tick()
    if P.srv.panel.voice:
        P.srv.panel.voice.join(5)


def test_expiry_stops_run(panel):
    P = panel
    L = _running(P)
    sid = P.srv.panel.session.id
    P.mono[0] += 30 * 60
    _tick(P)
    assert L.stopped == "session ended"
    assert [(e["session"], e["reason"]) for e in _log(P.home, "session_end")] == [(sid, "expired")]
    _tick(P)   # ended once: a second tick (or a racing request) adds nothing
    P.say("run joblens")
    assert len(_log(P.home, "session_end")) == 1 and len(P.made) == 1


def test_lock_then_unlock_between_requests_ends_session(panel, monkeypatch):
    from govaios import auth
    P = panel
    L = _running(P)
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    _tick(P)
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    assert not P.srv.panel.session.active() and L.stopped == "session ended"
    assert _log(P.home, "session_end")[-1]["reason"] == "screen_lock"


def test_stopped_flag_ends_session(panel):
    P = panel
    L = _running(P)
    (P.home / "STOPPED").write_text("")
    _tick(P)
    assert not P.srv.panel.session.active() and L.stopped == "session ended"
    assert _log(P.home, "session_end")[-1]["reason"] == "emergency_stop"
    L.done = True   # hotkey stop: the run ends and the page says stopped
    _tick(P)
    assert "JobLens stopped: session ended" in P.get("/")[1]


def test_done_run_speaks_complete(panel):
    P = panel
    L = _running(P)
    L.code, L.summary, L.done = 0, "deliver joblens: delivered 2, duplicate 3", True
    _tick(P)
    _tick(P)
    assert P.spoken == ["Rupak, the JobLens flow is complete, thank you."]
    body = P.get("/")[1]
    assert body.count("JobLens finished: delivered 2, duplicate 3") == 1


def test_stopped_run_speaks_reason(panel):
    P = panel
    L = _running(P)
    P.post("/end")
    assert L.stopped == "session ended"
    L.code, L.done = 143, True
    _tick(P)
    assert P.spoken == ["Rupak, the JobLens flow stopped: session ended."]
    assert "JobLens stopped: session ended" in P.get("/")[1]
    P.say(code_at(SecretStore(P.home).load(), time.time() + 30))   # the first code is spent
    P.say("run joblens")
    L2 = P.made[-1]
    L2.code, L2.done = 3, True
    _tick(P)
    assert P.spoken[-1] == "Rupak, the JobLens flow stopped: exit 3."


def test_server_waits_for_live_run(panel, monkeypatch):
    P = panel
    L = _running(P)
    down = threading.Event()
    real = P.srv.shutdown
    monkeypatch.setattr(P.srv, "shutdown", lambda: (down.set(), real()))
    P.wall[0] += 3601
    assert P.get("/")[0] == 403   # browser session over
    _tick(P)
    assert not down.wait(0.3) and P.get("/")[0] == 403   # still serving while the run is live
    assert P.srv.panel.session.active() and L.stopped is None
    L.code, L.done = 0, True
    _tick(P)
    assert down.wait(2) and P.spoken == ["Rupak, the JobLens flow is complete, thank you."]


def test_server_close_stops_live_run(panel):
    P = panel
    L = _running(P)
    P.srv.shutdown()
    P.srv.server_close()
    assert L.stopped == "session ended" and not P.srv.panel.session.active()
    assert _log(P.home, "session_end")[-1]["reason"] == "ended"


def test_say_uses_usr_bin_say(monkeypatch):
    import subprocess
    from govaios.audit import web
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    web._say("hi")
    assert calls == [((["/usr/bin/say", "hi"],), {"timeout": 60})]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: 1 / 0)
    web._say("hi")   # errors ignored
