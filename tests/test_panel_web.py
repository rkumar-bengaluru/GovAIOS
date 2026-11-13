import base64
import http.client
import json
import os
import re
from pathlib import Path
import shutil
import threading
import time
from http.cookies import SimpleCookie
from urllib.parse import urlencode

import pytest
import yaml

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
    gate = None   # a test sets an Event to hold __init__ (the run start) open

    def __init__(self, flow_path, ticket, inputs=None):
        if self.gate:
            self.entered.set()
            self.gate.wait(5)
        self.flow_path, self.ticket, self.inputs = flow_path, ticket, inputs
        self.done, self.started, self.stopped, self.stops = False, False, None, []
        self.code, self.summary, self.stopped_reason = None, None, None
        self._lines = ["step 3 <script>alert(1)</script>"]
        self.made.append(self)

    def start(self):
        self.started = True

    def lines(self):
        return list(self._lines)

    def stop(self, reason):
        self.stops.append(reason)
        self.stopped = self.stopped_reason = reason


def _fake_admin(home, tmp):
    """The Mac-password step without root: what ROOT_SCRIPT does, as this user."""
    from govaios.panel.helper import TARGETS

    def run(action, digest, agent="claude_code"):
        import hashlib
        folder, name, staged = TARGETS[agent]
        ms = tmp / ("ClaudeCode" if agent == "claude_code" else "codex")
        dst = ms / name
        if action == "remove":
            dst.unlink(missing_ok=True)
            return 0
        data = (home / staged).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            return 3
        ms.mkdir(exist_ok=True)
        dst.write_bytes(data)
        return 0
    return run


@pytest.fixture
def panel(tmp_path, monkeypatch, ui):
    from govaios import auth
    flows = tmp_path / "flows"
    shutil.copytree(REPO / "flows", flows)
    shutil.copytree(REPO / "pages", tmp_path / "pages")
    shutil.copy(Path(__file__).parent / "data" / "job_apply_link.yaml", flows / "job_apply.yaml")   # a flow with an input
    (flows / "web_sandbox.yaml").unlink()
    (flows / "teach.yaml").unlink()   # the Teach tests write their own
    for f, app in (("himalayas_job_vetting", "JobLens"), ("morning_inbox_briefing", "Inbox briefing")):
        p = flows / f"{f}.yaml"
        p.write_text(re.sub(r"(?m)^  app: .*\n", "", p.read_text(), count=1).replace("\n  name:", f"\n  app: {app}\n  name:", 1))
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
    from govaios.panel import settings
    settings.set_name(home, "Rupak")
    made = []
    launcher = type("L", (FakeLaunch,), {"made": made})
    admin_calls, admin_answer = [], [_fake_admin(home, tmp_path)]
    started = []
    spoken = []
    mono, wall = [0.0], [0.0]   # offsets added to the session's monotonic clock and the browser-session clock
    srv = make_server(home, flows_dir=flows, launcher=launcher, speak=spoken.append,
                            now=lambda: time.time() + wall[0], session=Session(lambda: time.monotonic() + mono[0]), tick_s=None,
                            chrome_state=tmp_path / "Local State",
                            managed={"claude_code": tmp_path / "ClaudeCode" / "managed-settings.json",
                                     "codex": tmp_path / "codex" / "requirements.toml"},
                            admin=lambda a, d, ag="claude_code": (admin_calls.append((a, d) if ag == "claude_code" else (a, d, ag)),
                                                                  admin_answer[0](a, d, ag))[1],
                            starter=lambda f, ag="claude_code": (started.append(f if ag == "claude_code" else (f, ag)), 0)[1])
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

    sid = ui.signin(srv)
    P = type("P", (), {})()
    P.home, P.flows, P.srv, P.made, P.answers, P.asked, P.req, P.sid = home, flows, srv, made, answers, asked, req, sid
    P.spoken, P.mono, P.wall, P.launcher, P.ui = spoken, mono, wall, launcher, ui
    P.admin_calls, P.admin_answer, P.tmp, P.started = admin_calls, admin_answer, tmp_path, started
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


def test_code_field_only_while_no_session(panel):
    P = panel
    assert "class=otp" not in P.get("/")[1]   # no authenticator set up yet
    secret = _secret(P)
    body = P.get("/")[1]
    assert "<label for=otp>Authenticator code</label>" in body and "autocomplete=one-time-code" in body
    assert "inputmode=numeric" in body and "maxlength=6" in body and body.count("autofocus") == 1
    P.say(code_at(secret, time.time()))   # the field posts to /say like the command box
    body = P.get("/")[1]
    assert "Session open: 30 min left" in body and "id=otp" not in body


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


def test_no_session_while_emergency_stop(panel):
    P = panel
    (P.home / "STOPPED").write_text("")
    P.say(code_at(_secret(P), time.time()))
    assert not P.srv.panel.session.active()
    assert "Emergency stop is on. Clear it first." in P.get("/")[1]
    e = _log(P.home, "session_open")[-1]
    assert (e["decision"], e["reason"]) == ("deny", "emergency_stop")


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
    assert "JobLens queued #1." in P.get("/")[1] and len(P.made) == 1
    P.made[0].done = True
    assert "refresh" in P.get("/")[1] and len(P.made) == 1
    P.srv.panel.tick()
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
    assert "Approve…</button>" in P.get("/approvals")[1]
    P.post("/approve", flow="morning_inbox_briefing")
    assert ap.read_bytes() == before
    import yaml
    wf = yaml.safe_load((P.flows / "morning_inbox_briefing.yaml").read_text())["workflow"]
    assert P.asked == [approval_question(wf, None)]
    P.answers["approve"] = True
    P.post("/approve", flow="morning_inbox_briefing")
    assert all(a.approved for a in list_apps(P.flows, P.home) if a.id != "job_apply")   # job_apply stays a draft
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
    assert s == 200 and "<th>started by</th>" in body and "OK 7 entries" in body
    assert "Panel" in P.get("/audit/app/a")[1] and "Terminal" in P.get("/audit/app/b")[1]
    assert P.get("/audit/run/2")[0] == 200 and P.get("/audit/log")[0] == 200   # seq 1 is the sign-in
    assert P.get("/log")[0] == 404 and P.get("/run/1")[0] == 404
    talk = P.get("/")[1]
    assert "started by" not in talk and "OK 7 entries" not in talk


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


def test_expiry_keeps_serving_and_run_reports(panel):
    """No self-shutdown: an expired sign-in leaves the run going, and the ticker still reports it."""
    P = panel
    L = _running(P)
    P.wall[0] += 8 * 3600
    assert "Sign in with Touch ID" in P.get("/")[1]
    _tick(P)
    assert P.srv.panel.session.active() and L.stopped is None
    L.code, L.done = 0, True
    _tick(P)
    assert P.spoken == ["Rupak, the JobLens flow is complete, thank you."]
    assert P.get("/audit")[0] == 303   # expired sign-in: back to the Locked page


def test_server_close_stops_live_run(panel):
    P = panel
    L = _running(P)
    P.srv.shutdown()
    P.srv.server_close()
    assert L.stops == ["session ended"] and not P.srv.panel.session.active()   # once: a 2nd SIGTERM can cut the app's stop entry
    assert _log(P.home, "session_end")[-1]["reason"] == "server_stop"


def test_server_close_stops_run_of_ended_session(panel):
    P = panel
    L = _running(P)
    P.srv.panel.session.end("x")   # session gone without its stop: the server still stops the run, once
    P.srv.shutdown()
    P.srv.server_close()
    assert L.stops == ["session ended"]


def test_ending_session_spends_unconsumed_ticket(panel):
    P = panel
    L = _running(P)
    t = P.home / "tickets" / L.ticket
    assert t.exists()
    P.post("/end")
    assert L.stops == ["session ended"] and not t.exists()   # a slow-starting app cannot start the run later


def test_end_racing_run_start_stops_that_run(panel):
    P = panel
    _open(P)
    P.launcher.gate, P.launcher.entered = threading.Event(), threading.Event()
    a = threading.Thread(target=P.say, args=("run joblens",))
    a.start()
    assert P.launcher.entered.wait(5)   # say() holds the panel lock, the run is being made
    b = threading.Thread(target=P.srv.panel.end_session, args=("ended",))
    b.start()
    b.join(0.2)
    P.launcher.gate.set()
    a.join(5), b.join(5)
    assert P.made and P.made[0].started and P.made[0].stopped == "session ended"
    assert not P.srv.panel.session.active()


def test_no_ticker_when_tick_s_none(tmp_path):
    before = threading.active_count()
    srv = make_server(tmp_path / "h", tick_s=None)
    assert threading.active_count() == before
    srv.server_close()


def test_say_uses_usr_bin_say(monkeypatch):
    import subprocess
    from govaios.audit import web
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append((a, k)))
    web._say("hi")
    assert calls == [((["/usr/bin/say", "hi"],), {"timeout": 60})]
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: 1 / 0)
    web._say("hi")   # errors ignored


def test_talk_without_apps_folder_says_how_to_start(tmp_path, ui):
    srv = make_server(tmp_path / "h", tick_s=None)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        sid = ui.signin(srv)
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        c.request("GET", "/", headers={"Cookie": f"s={sid}"})
        assert "No apps folder given. Start with: bin/gov-aios panel flows" in c.getresponse().read().decode()
    finally:
        srv.shutdown()
        srv.server_close()


def test_pages_share_stylesheet(panel):
    P = panel
    _open(P)
    P.say("run joblens")
    log = AuditLog(P.home)
    log.append("flow_start", flow="a")
    log.append("flow_end", flow="a", outcome="done")
    pages = [P.get(p)[1] for p in ("/", "/audit", "/audit/log", "/audit/run/" + str(_log(P.home, "flow_start")[0]["seq"]),
                                   "/approvals")]
    SecretStore(P.home).delete()
    pages.append(P.get("/totp/setup")[1])
    styles = {re.findall(r"<style>.*?</style>", b, re.S)[0] for b in pages}
    assert len(styles) == 1 and all(len(re.findall(r"<style", b)) == 1 for b in pages)
    assert "prefers-color-scheme" in styles.pop()
    for b in pages:
        assert "<main" in b and "<script" not in b.lower() and "http:" not in b and "https:" not in b
        assert 'name=viewport' in b


def test_rail_marks_current_page(panel):
    P = panel
    for path, link in (("/", "href='/' aria-current=page>Home"), ("/audit", "href='/audit' aria-current=page>Audit log"),
                       ("/approvals", "href='/approvals' aria-current=page>Approvals")):
        body = P.get(path)[1]
        assert link in body and body.count("aria-current=page") == 1


# --- sign in from the page (v2 Task 1)

def _port(P):
    return P.srv.server_address[1]


def _finish(P, r, word=None):
    """Type the code word of the last Touch ID prompt (or `word`) for the t cookie r set: the response."""
    return P.ui.code_post(_port(P), P.ui.t(r), word if word is not None else P.ui.WORD.search(P.asked[-1])[1])[2]


def test_signed_out_page_has_button_but_no_code(panel):
    P = panel
    s, body, r = P.ui.raw(_port(P), "GET", "/")
    assert s == 200 and "Sign in with Touch ID" in body and "Locked" in body and "class=word" not in body
    assert "you type it here next" in body and "name=word" not in body
    ck = r.getheader("Set-Cookie")
    assert ck.startswith("pre=") and "HttpOnly" in ck and "SameSite=Strict" in ck and "Max-Age=120" in ck
    assert re.search(r"name=pre value='([^']+)'", body)[1] == SimpleCookie(ck)["pre"].value
    assert r.getheader("Content-Security-Policy") == CSP and "<script" not in body.lower()
    assert "Type a command" not in body and "JobLens" not in body   # nothing of the panel while signed out


def test_signin_needs_the_code_typed_from_the_prompt(panel):
    from govaios.auth import shown_digest
    P = panel
    port = _port(P)
    n = len(_log(P.home, "ui_login"))   # the fixture's own sign-in
    _, pre, ck = P.ui.signed_out(port)
    s, _, r = P.ui.signin_post(port, ck, pre)
    assert s == 303 and r.getheader("Location") == "/" and P.ui.s(r) is None   # Touch ID alone is not a sign-in
    t = P.ui.t(r)
    assert t and "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Strict" in r.getheader("Set-Cookie")
    word = P.ui.WORD.search(P.asked[0])[1]
    s, body, _ = P.ui.raw(port, "GET", "/", f"t={t}")
    assert s == 200 and "Type the 4-letter code" in body and "name=word" in body and word not in body
    assert len(_log(P.home, "ui_login")) == n   # audited once, at the typed code
    s, _, r = P.ui.code_post(port, t, f" {word[:2].lower()} {word[2:]} ")   # case and spaces do not matter
    assert s == 303 and r.getheader("Location") == "/"
    sid = P.ui.s(r)
    assert "HttpOnly" in r.getheader("Set-Cookie") and "SameSite=Strict" in r.getheader("Set-Cookie")
    assert "t=;" in r.getheader("Set-Cookie") or any(h == "t=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"
                                                    for h in r.headers.get_all("Set-Cookie"))
    assert "Type a command" in P.req("/", cookie=sid)[1]
    e = _log(P.home, "ui_login")[-1]
    assert (e["decision"], e["approver"], e["channel"], e["auth"]) == ("allow", "admin", "touch_id", "biometric")
    assert e["shown"] == shown_digest(None, f"sign in to the GOV-AIOS panel, code {word}")
    assert P.ui.s(P.ui.code_post(port, t, word)[2]) is None   # a t token is spent by its one try
    s, _, r = P.ui.signin_post(port, ck, pre)   # a pre pair is spent by its one prompt
    assert (s, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/", None) and len(P.asked) == 1


def test_signin_wrong_code_refused_audited_and_paused(panel):
    P = panel
    port = _port(P)
    _, pre, ck = P.ui.signed_out(port)
    r = P.ui.signin_post(port, ck, pre)[2]
    t, word = P.ui.t(r), P.ui.WORD.search(P.asked[0])[1]
    wrong = "".join("B" if c == "A" else "A" for c in word)
    s, _, r = P.ui.code_post(port, t, wrong)
    assert (s, r.getheader("Location"), P.ui.s(r)) == (303, "/?m=code", None)
    e = _log(P.home, "ui_login")[-1]
    assert (e["decision"], e["auth"]) == ("deny", "wrong_code") and word not in json.dumps(e) and wrong not in json.dumps(e)
    body = P.ui.raw(port, "GET", "/?m=code")[1]
    assert "That code did not match" in body and "Sign-in paused. Try again in 10 s." in body
    assert P.ui.s(P.ui.code_post(port, t, word)[2]) is None   # one try: the right word after a wrong one is too late
    _, pre, ck = P.ui.signed_out(port)
    assert P.ui.signin_post(port, ck, pre)[2].getheader("Location") == "/" and len(P.asked) == 1   # paused


def test_signin_code_forged_or_stale(panel):
    P = panel
    port = _port(P)
    _, pre, ck = P.ui.signed_out(port)
    r = P.ui.signin_post(port, ck, pre)[2]
    t, word = P.ui.t(r), P.ui.WORD.search(P.asked[0])[1]
    n = len(_log(P.home, "ui_login"))
    assert P.ui.code_post(port, t, word, headers={"Origin": "http://evil"})[0] == 403
    for resp in (P.ui.code_post(port, None, word, field_t=t)[2],        # no t cookie
                 P.ui.code_post(port, t, word, field_t="other")[2],     # mismatched field
                 P.ui.code_post(port, "made-up", word)[2]):             # never issued
        assert (resp.status, resp.getheader("Location"), P.ui.s(resp)) == (303, "/", None)
    assert len(_log(P.home, "ui_login")) == n
    P.wall[0] += 121   # Touch ID was 2 minutes ago: start again
    assert P.ui.s(P.ui.code_post(port, t, word)[2]) is None


def test_signin_lock_before_typing_voids_the_prompt(panel, monkeypatch):
    from govaios import auth
    P = panel
    port = _port(P)
    _, pre, ck = P.ui.signed_out(port)
    r = P.ui.signin_post(port, ck, pre)[2]
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    P.srv.panel.tick()
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    assert P.ui.s(_finish(P, r)) is None


def test_signin_forged(panel):
    P = panel
    port = _port(P)
    _, pre, ck = P.ui.signed_out(port)
    _, pre2, ck2 = P.ui.signed_out(port)
    n = len(_log(P.home, "ui_login"))
    for r in (P.ui.raw(port, "POST", "/signin", "", {"pre": pre})[2],                       # no pre cookie
              P.ui.signin_post(port, ck2, pre)[2]):                                          # mismatched
        assert (r.status, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/", None)
    s, _, r = P.ui.signin_post(port, "made-up", "made-up")                               # never issued
    assert (s, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/", None)   # a fresh Locked page
    assert P.ui.signin_post(port, ck, pre, {"Origin": "http://evil"})[0] == 403
    assert P.ui.signin_post(port, ck, pre, {"Origin": "null"})[0] == 403
    assert P.ui.signin_post(port, ck, pre, {"Host": "evil.example"})[0] == 403
    assert P.asked == [] and len(_log(P.home, "ui_login")) == n
    s, _, r = P.ui.signin_post(port, ck2, pre2, {"Origin": f"http://127.0.0.1:{port}"})   # the page's own form
    assert s == 303 and P.ui.t(r)


def test_signin_stale_pre_gets_fresh_page(panel):
    P = panel
    _, pre, ck = P.ui.signed_out(_port(P))
    P.wall[0] += 100
    _, pre2, ck2 = P.ui.signed_out(_port(P))
    P.wall[0] += 121
    s, _, r = P.ui.signin_post(_port(P), ck, pre)
    assert (s, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/", None) and P.asked == []
    for _ in range(64):   # evicted by later page loads: also a fresh Locked page, not a bare 403
        P.ui.signed_out(_port(P))
    assert P.ui.signin_post(_port(P), ck2, pre2)[2].getheader("Location") == "/" and P.asked == []


def test_signin_one_prompt_at_a_time(panel, monkeypatch):
    from govaios import auth
    P = panel
    port = _port(P)
    entered, release, calls = threading.Event(), threading.Event(), []

    def prove(r, h, **k):
        calls.append(r)
        entered.set()
        release.wait(5)
        return True, "biometric"
    monkeypatch.setattr(auth, "prove", prove)
    _, pre, ck = P.ui.signed_out(port)
    _, pre2, ck2 = P.ui.signed_out(port)
    got = []
    t = threading.Thread(target=lambda: got.append(P.ui.signin_post(port, ck, pre)))
    t.start()
    assert entered.wait(5)
    s, _, r = P.ui.signin_post(port, ck2, pre2)
    assert s == 303 and r.getheader("Location") == "/?m=busy" and r.getheader("Set-Cookie") is None
    assert "Another sign-in is waiting for Touch ID." in P.ui.raw(port, "GET", "/?m=busy")[1]
    release.set()
    t.join(5)
    assert got[0][0] == 303 and P.ui.t(got[0][2]) and len(calls) == 1


def test_signin_pause_after_refusal(panel):
    P = panel
    port = _port(P)
    P.answers["prove"] = False
    _, pre, ck = P.ui.signed_out(port)
    s, _, r = P.ui.signin_post(port, ck, pre)
    assert s == 303 and r.getheader("Location") == "/?m=no" and r.getheader("Set-Cookie") is None
    e = _log(P.home, "ui_login")[-1]
    assert (e["decision"], e["channel"], e["auth"]) == ("deny", "touch_id", "biometric")
    P.answers["prove"] = True
    P.wall[0] += 9.9
    _, pre, ck = P.ui.signed_out(port)
    assert P.ui.signin_post(port, ck, pre)[2].getheader("Location") == "/" and len(P.asked) == 1
    assert "Sign-in paused. Try again in 1 s." in P.ui.raw(port, "GET", "/")[1]
    P.wall[0] += 0.1
    _, pre, ck = P.ui.signed_out(port)
    r = P.ui.signin_post(port, ck, pre)[2]
    assert len(P.asked) == 2 and P.ui.t(r)


def test_signed_out_get_reuses_valid_pre(panel):
    P = panel
    port = _port(P)
    _, pre, ck = P.ui.signed_out(port)
    s, body, r = P.ui.raw(port, "GET", "/", f"pre={ck}")
    assert (s, r.getheader("Set-Cookie")) == (200, None)
    assert re.search(r"name=pre value='([^']+)'", body)[1] == pre
    P.wall[0] += 121   # expired: a fresh pair
    assert P.ui.raw(port, "GET", "/", f"pre={ck}")[2].getheader("Set-Cookie").startswith("pre=")


def test_signed_out_other_paths_404_no_cookie(panel):
    P = panel
    for path in ("/favicon.ico", "/log", "/auditx"):
        s, _, r = P.ui.raw(_port(P), "GET", path)
        assert (s, r.getheader("Set-Cookie")) == (404, None)


def test_signed_out_panel_pages_go_to_locked_page_no_cookie(panel):
    P = panel
    for path in ("/audit", "/audit/log", "/audit/run/3", "/audit/app/joblens", "/approvals", "/totp/setup"):
        s, _, r = P.ui.raw(_port(P), "GET", path)
        assert (s, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/", None)


def test_signin_backoff_doubles_caps_and_resets(panel):
    P = panel
    port = _port(P)
    P.answers["prove"] = False

    def attempt():
        _, pre, ck = P.ui.signed_out(port)
        return P.ui.signin_post(port, ck, pre)[2].getheader("Location")
    for n, secs in enumerate((10, 20, 40, 80, 160, 300, 300), 1):
        assert attempt() == "/?m=no"
        asked = len(P.asked)
        P.wall[0] += secs - 0.5
        assert attempt() == "/" and len(P.asked) == asked   # still paused: no prompt
        assert f"Try again in 1 s." in P.ui.raw(port, "GET", "/")[1]
        P.wall[0] += 0.5
    P.answers["prove"] = True
    _, pre, ck = P.ui.signed_out(port)
    assert P.ui.s(_finish(P, P.ui.signin_post(port, ck, pre)[2]))   # a finished sign-in resets the count
    P.answers["prove"] = False
    assert attempt() == "/?m=no"
    P.wall[0] += 9.5
    assert attempt() == "/"   # n restarted at 1: a 10 s pause
    P.wall[0] += 0.5
    assert attempt() == "/?m=no"


def test_paused_page_shows_whole_seconds_rounded_up(panel):
    P = panel
    P.answers["prove"] = False
    _, pre, ck = P.ui.signed_out(_port(P))
    P.ui.signin_post(_port(P), ck, pre)
    P.wall[0] += 3.2
    assert "Sign-in paused. Try again in 7 s." in P.ui.raw(_port(P), "GET", "/")[1]


def test_signin_expires_after_8h(panel):
    P = panel
    P.wall[0] += 8 * 3600 - 1
    assert "Type a command" in P.get("/")[1]
    P.wall[0] += 1
    s, body, _ = P.get("/")
    assert s == 200 and "Sign in with Touch ID" in body and "Type a command" not in body
    assert P.req("/end", "POST", cookie=P.sid, body={"csrf": "x"})[0] == 403
    assert "Type a command" in P.req("/", cookie=P.ui.signin(P.srv))[1]   # still serving


def test_lock_signs_out_all_and_keeps_serving(panel, monkeypatch):
    from govaios import auth
    P = panel
    sid2 = P.ui.signin(P.srv)
    L = _running(P)
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    _tick(P)   # the ticker sees the lock
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    for sid in (P.sid, sid2):
        assert "Sign in with Touch ID" in P.req("/", cookie=sid)[1]
    assert _log(P.home, "session_end")[-1]["reason"] == "screen_lock" and L.stopped == "session ended"
    sid3, sid4 = P.ui.signin(P.srv), P.ui.signin(P.srv)
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    assert P.req("/", cookie=sid3)[0] == 403   # a request sees the lock
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    for sid in (sid3, sid4):
        assert "Sign in with Touch ID" in P.req("/", cookie=sid)[1]
    assert P.req("/")[0] == 200


def test_signout(panel):
    P = panel
    _open(P)
    sid2 = P.ui.signin(P.srv)
    s, _, r = P.post("/signout")
    assert s == 303 and r.getheader("Location") == "/"
    assert "Sign in with Touch ID" in P.get("/")[1]
    assert "Type a command" in P.req("/", cookie=sid2)[1]
    assert P.srv.panel.session.active()   # signing one browser out leaves the code session open
    assert P.req("/signout", "POST", cookie=sid2, body={"csrf": "wrong"})[0] == 403


@pytest.mark.parametrize("how", ["busy", "none"])
def test_signin_no_prompt_shown_is_busy_not_refused(panel, monkeypatch, how):
    """auth's own busy/none: no sheet was shown, so nothing was refused: no deny audit and no pause."""
    from govaios import auth
    P = panel
    port = _port(P)
    calls = []
    monkeypatch.setattr(auth, "prove", lambda r, h, **k: (calls.append(r), (False, how))[1])
    n = len(_log(P.home, "ui_login"))
    _, pre, ck = P.ui.signed_out(port)
    s, _, r = P.ui.signin_post(port, ck, pre)
    assert (s, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/?m=busy", None)
    assert len(_log(P.home, "ui_login")) == n
    monkeypatch.setattr(auth, "prove", lambda r, h, **k: (calls.append(r), (True, "biometric"))[1])
    _, pre, ck = P.ui.signed_out(port)
    r = P.ui.signin_post(port, ck, pre)[2]   # at once: no 10 s pause
    assert len(calls) == 2 and P.ui.t(r)


def test_signin_lock_during_prompt_no_session(panel, monkeypatch):
    from govaios import auth
    P = panel
    port = _port(P)
    locked = [False]
    monkeypatch.setattr(auth, "screen_locked", lambda: locked[0])

    def prove(r, h, **k):
        locked[0] = True   # the screen locks while the approved prompt returns
        return True, "biometric"
    monkeypatch.setattr(auth, "prove", prove)
    _, pre, ck = P.ui.signed_out(port)
    s, _, r = P.ui.signin_post(port, ck, pre)
    assert (s, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/", None)
    locked[0] = False
    assert P.srv.panel.tick() is None and "Sign in with Touch ID" in P.ui.raw(port, "GET", "/")[1]


def test_name_change_used_in_speech(panel):
    P = panel
    assert P.post("/name", name="Asha")[0] == 303
    e = _log(P.home, "setting")
    assert len(e) == 1 and e[0]["field"] == "name" and "Asha" not in json.dumps(e[0])
    L = _running(P)
    L.code, L.summary, L.done = 0, "x", True
    _tick(P)
    assert P.spoken == ["Asha, the JobLens flow is complete, thank you."]
    assert P.post("/name", name="")[0] == 400 and len(_log(P.home, "setting")) == 1
    assert P.req("/name", "POST", body={"name": "Zed"})[0] == 403


def test_name_escaped(panel):
    P = panel
    P.post("/name", name="<b>x")
    page = P.get("/")[1]
    assert "<b>x" not in page and "&lt;b&gt;x" in page
    assert "Your name" in P.get("/approvals")[1]


def test_name_not_written_when_audit_fails(panel, monkeypatch):
    P = panel
    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(AuditLog, "append", boom)
    assert P.post("/name", name="Asha")[0] == 500
    assert json.loads((P.home / "panel.json").read_text())["name"] == "Rupak" and P.srv.panel.name == "Rupak"


def test_name_forged_requests_403(panel):
    P = panel
    t = P.csrf()
    assert P.req("/name", "POST", cookie=P.sid, headers={"Origin": "http://evil"}, body={"csrf": t, "name": "Zed"})[0] == 403
    assert P.req("/name", "POST", cookie=P.sid, body={"csrf": "bad", "name": "Zed"})[0] == 403
    assert P.srv.panel.name == "Rupak" and not _log(P.home, "setting")


@pytest.mark.parametrize("gecos,shown", [("", "Admin"), ("<b>x Y", "&lt;b&gt;x")])
def test_default_name_from_account_on_page(tmp_path, monkeypatch, ui, gecos, shown):
    import pwd
    from govaios import auth
    real = pwd.getpwuid(__import__("os").getuid())
    monkeypatch.setattr(pwd, "getpwuid", lambda u: type("E", (), {"pw_gecos": gecos})())
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    srv = make_server(tmp_path, tick_s=None, speak=lambda t: None)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        sid = ui.signin(srv)
        c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1])
        c.request("GET", "/", headers={"Cookie": f"s={sid}"})
        page = c.getresponse().read().decode()
        assert shown in page and "<b>x" not in page
    finally:
        srv.shutdown()
        srv.server_close()


def _chrome(P, profiles):
    info = {d: {"name": n, "user_name": a} for d, n, a in profiles}
    (P.home.parent / "Local State").write_text(json.dumps({"profile": {"info_cache": info}}))


def test_marketplace_lists_templates_installed_and_not(panel):
    P = panel
    (P.flows / "morning_inbox_briefing.yaml").unlink()
    body = P.get("/market")[1]
    assert "Morning Gmail Briefing" in body and "SyncJobLens" in body and "Web Sandbox" in body
    assert "Installed as JobLens" in body and "href='/market/setup/morning_inbox_briefing'" in body
    assert "href='/market/setup/himalayas_job_vetting'" not in body and "aria-current=page>Marketplace" in body


def test_marketplace_setup_from_chrome_profile_makes_a_draft(panel):
    P = panel
    (P.flows / "morning_inbox_briefing.yaml").unlink()
    _chrome(P, [("Profile 3", "Work", "work.person@example.com"), ("Profile 4", "No Google", "")])
    body = P.get("/market/setup/morning_inbox_briefing")[1]
    assert "value='Profile 3'" in body and "work.person@example.com" in body and "Profile 4" not in body
    s, _, r = P.post("/market/setup", template="morning_inbox_briefing", profile="Profile 3",
                     account="attacker@example.com")   # ignored: the account comes from Chrome
    assert s == 303 and r.getheader("Location") == "/"
    b = yaml.safe_load((P.flows / "morning_inbox_briefing.yaml").read_text())["workflow"]["browser"]
    assert (b["profile_directory"], b["account"]) == ("Profile 3", "work.person@example.com")
    app = next(a for a in list_apps(P.flows, P.home) if a.id == "morning_inbox_briefing")
    assert not app.approved   # a draft until Touch ID approval
    body = P.get("/")[1]
    assert "Morning Gmail Briefing is set up as a draft. Approve it to let it run." in body
    e = _log(P.home, "setting")[-1]
    assert (e["field"], e["flow"]) == ("app_setup", "morning_inbox_briefing") and "example.com" not in json.dumps(e)
    assert "Installed as" in P.get("/market")[1].split("Morning Gmail Briefing")[1].split("</section>")[0]


def test_marketplace_setup_refuses_unknown_profile_installed_and_forged(panel):
    P = panel
    _chrome(P, [("Profile 3", "Work", "work.person@example.com")])
    before = (P.flows / "himalayas_job_vetting.yaml").read_text()
    assert P.post("/market/setup", template="himalayas_job_vetting", profile="Profile 3")[0] == 400   # installed
    assert (P.flows / "himalayas_job_vetting.yaml").read_text() == before
    (P.flows / "morning_inbox_briefing.yaml").unlink()
    assert P.post("/market/setup", template="morning_inbox_briefing", profile="Profile 9")[0] == 400
    assert P.post("/market/setup", template="nope", profile="Profile 3")[0] == 400
    s = P.req("/market/setup", "POST", cookie=P.sid, body={"csrf": "x", "template": "morning_inbox_briefing",
                                                          "profile": "Profile 3"})[0]
    assert s == 403 and not (P.flows / "morning_inbox_briefing.yaml").exists()


def test_marketplace_setup_typed_when_chrome_unreadable(panel):
    P = panel
    (P.flows / "morning_inbox_briefing.yaml").unlink()
    body = P.get("/market/setup/morning_inbox_briefing")[1]
    assert "could not be read" in body and "name=account" in body
    assert P.post("/market/setup", template="morning_inbox_briefing", profile="Profile 1",
                  account="bad\nname: x")[0] == 400
    assert P.post("/market/setup", template="morning_inbox_briefing", profile="Profile 1",
                  account="me@example.com")[0] == 303
    b = yaml.safe_load((P.flows / "morning_inbox_briefing.yaml").read_text())["workflow"]["browser"]
    assert (b["profile_directory"], b["account"]) == ("Profile 1", "me@example.com")


def test_marketplace_signed_out_goes_to_locked_page(panel):
    P = panel
    for path in ("/market", "/market/setup/morning_inbox_briefing"):
        s, _, r = P.ui.raw(P.srv.server_address[1], "GET", path)
        assert (s, r.getheader("Location"), r.getheader("Set-Cookie")) == (303, "/", None)



@pytest.fixture
def cc(panel, monkeypatch):
    from govaios import agents
    monkeypatch.setattr(agents, "root_owned", lambda p: p.exists())   # the fake step cannot chown to root
    proj = panel.tmp / "proj"
    proj.mkdir()
    panel.proj = proj
    return panel


def _tells(P):
    return [l for l in P.srv.panel.convo if l.startswith("GOV-AIOS -> ")]


def test_claude_code_card_and_page(cc):
    body = cc.get("/market")[1]
    assert "Claude Code, governed" in body and "href='/claude'" in body
    page = cc.get("/claude")[1]
    assert "<textarea id=folders name=folders" in page and "~/Documents/2026" in page and "<script" not in page


def test_claude_code_setup_approves_then_installs(cc):
    from govaios.executor import POLICY_PATH
    st, _, r = cc.post("/claude/setup", folders=str(cc.proj))
    assert st == 303 and r.getheader("Location") == "/"
    pol_text = (cc.home / POLICY_PATH).read_text()
    assert str(cc.proj.resolve()) in pol_text and any(pol_text in q for q in cc.asked)
    (act, digest), = cc.admin_calls
    assert act == "install" and len(digest) == 64
    assert "Claude Code is governed" in _tells(cc)[-1]
    assert "<p class=state>Governed</p>" in cc.get("/market")[1] and "Turn off" in cc.get("/claude")[1]
    fa = _log(cc.home, "flow_approval")[-1]
    assert fa["flow"] == "claude_code" and fa["decision"] == "allow" and len(fa["shown"]) == 64
    s = _log(cc.home, "setting")[-1]
    assert (s["field"], s["action"], s["outcome"]) == ("claude_code", "install", "0")


def test_claude_code_not_approved_writes_nothing(cc):
    from govaios.executor import POLICY_PATH
    cc.answers["approve"] = False
    cc.post("/claude/setup", folders=str(cc.proj))
    assert not (cc.home / POLICY_PATH).exists() and cc.admin_calls == []
    assert "not approved" in _tells(cc)[-1]


def test_claude_code_password_cancelled_then_retried(cc):
    cc.admin_answer[0], real = (lambda a, d, ag: 2), cc.admin_answer[0]
    cc.post("/claude/setup", folders=str(cc.proj))
    assert "Mac password was cancelled" in _tells(cc)[-1] and "Set up" in cc.get("/market")[1]
    cc.admin_answer[0] = real
    page = cc.get("/claude")[1]
    assert "existing policy" in page and "<textarea" not in page   # the approved folders are kept
    cc.post("/claude/setup")
    assert "Claude Code is governed" in _tells(cc)[-1]


@pytest.mark.parametrize("folders", ["", "relative/dir", "/no/such/folder", "~/no-such-folder-xyz"])
def test_claude_code_bad_folders_never_ask(cc, folders):
    n = len(cc.asked)
    cc.post("/claude/setup", folders=folders)
    assert len(cc.asked) == n and cc.admin_calls == [] and "was not set up" in _tells(cc)[-1]


def test_claude_code_protected_folder_refused(cc):
    n = len(cc.asked)
    cc.post("/claude/setup", folders=str(cc.home))
    assert len(cc.asked) == n and cc.admin_calls == [] and "protected path" in _tells(cc)[-1]


def test_claude_code_turn_off_needs_touch_id(cc):
    cc.post("/claude/setup", folders=str(cc.proj))
    cc.answers["prove"] = False
    cc.post("/claude/off")
    assert [a for a, _ in cc.admin_calls] == ["install"]
    cc.answers["prove"] = True
    cc.post("/claude/off")
    assert [a for a, _ in cc.admin_calls] == ["install", "remove"]
    assert "governance is off" in _tells(cc)[-1] and "Set up" in cc.get("/market")[1]


def test_claude_code_setup_forged_without_csrf(cc):
    st = cc.req("/claude/setup", "POST", cookie=cc.sid, body={"folders": str(cc.proj)})[0]
    assert st == 403 and cc.admin_calls == []


def test_claude_code_in_talk_and_audit(cc):
    assert "Claude Code<span" not in cc.get("/")[1] and "Coding agents" not in cc.get("/audit")[1]
    cc.post("/claude/setup", folders=str(cc.proj))
    log = AuditLog(cc.home)
    log.append("request", flow="claude_code", executor="claude_code", action="Bash", command="git status",
               decision="allow", approver="policy")
    log.append("request", flow="claude_code", executor="claude_code", action="Bash", command="make <b>",
               decision="deny", reason="not allowed", approver="admin", auth="biometric")
    log.append("request", flow="claude_code", executor="claude_code", action="Bash", command="make --version",
               decision="allow", approver="admin", auth="biometric")
    assert "Claude Code<span class=m> Governed: type /claude" in cc.get("/apps")[1]
    idx = cc.get("/audit")[1]
    assert "Coding agents" in idx and "href='/audit/app/claude_code'" in idx
    assert re.search(r"<td>Governed</td><td>3</td><td>1</td>", idx)
    assert "href='/audit/claude/earlier'>Earlier" in cc.get("/audit/app/claude_code")[1]   # no session recorded
    page = cc.get("/audit/claude/earlier")[1]
    assert page.index("git status") < page.index("make &lt;b&gt;") and "<b>" not in page.split("</h1>", 1)[1]
    assert "<td>GOV-AIOS policy</td>" in page and "<td>You, Touch ID</td>" in page
    assert "<td>You declined (Touch ID)</td><td>not allowed</td>" in page


def test_claude_code_sessions_grouped(cc):
    cc.post("/claude/setup", folders=str(cc.proj))
    log = AuditLog(cc.home)
    for sid, cmd in (("aaa-1", "git status"), ("bbb-2", "ls"), ("aaa-1", "git log")):
        log.append("request", flow="claude_code", executor="claude_code", action="Bash", command=cmd,
                   decision="allow", approver="policy", session=sid, folder=str(cc.proj))
    page = cc.get("/audit/app/claude_code")[1]
    assert page.index("Session 2") < page.index("Session 1")   # newest first
    assert re.search(r"/audit/claude/aaa-1'>Session 1</a></td><td>[^<]*</td><td>[^<]*proj</td><td>2</td>", page)
    one = cc.get("/audit/claude/aaa-1")[1]
    assert "git status" in one and "git log" in one and "<td>ls</td>" not in one
    assert cc.get("/audit/claude/nope")[0] == 404


def _cc_ready(cc):
    cc.post("/claude/setup", folders=str(cc.proj))
    for n in ("alpha", "Beta", ".hidden"):
        (cc.proj / n).mkdir()
    _open(cc)


def test_claude_start_form_suggests_approved_folders(cc):
    assert "action=/claude/start" not in cc.get("/")[1]   # not governed yet
    _cc_ready(cc)
    assert "action=/claude/start" not in cc.get("/")[1]   # the side list stays as it was
    cc.say("/claude")
    page = cc.get("/")[1]
    real = str(cc.proj.resolve())
    assert "<datalist id=ccdirs>" in page and f"<option value='{real}/alpha'>" in page
    assert ".hidden" not in page and f"<option value='{real}/Beta'>" in page
    cc.post("/claude/start", folder=f"{real}/alpha")
    assert cc.started == [f"{real}/alpha"] and "Starting Claude Code" in _tells(cc)[-1]
    assert "action=/claude/start" not in cc.get("/")[1]   # started: the card closes
    cc.say("/claude")
    assert f"id=ccf name=folder list=ccdirs value='{real}/alpha'" in cc.get("/")[1]   # the last folder is prefilled
    e = _log(cc.home, "claude_start")[-1]
    assert (e["target"], e["outcome"]) == (f"{real}/alpha", "0")


@pytest.mark.parametrize("text,ok", [("run claude beta", "Beta"), ("start claude code in alpha", "alpha"),
                                     ("/claude alpha", "alpha"),
                                     ("run claude", None), ("run claude /etc", None), ("open claude nope", None)])
def test_claude_start_typed(cc, text, ok):
    _cc_ready(cc)
    cc.say(text)
    real = str(cc.proj.resolve())
    assert cc.started == ([f"{real}/{ok}"] if ok else [])
    if not ok:
        assert "Which folder" in _tells(cc)[-1] or "not inside the approved" in _tells(cc)[-1]


def test_claude_start_needs_code_session(cc):
    cc.post("/claude/setup", folders=str(cc.proj))
    cc.post("/claude/start", folder=str(cc.proj))
    assert cc.started == [] and "authenticator" in _tells(cc)[-1]


def test_slash_commands_listed_and_app_card(cc):
    page = cc.get("/")[1]
    assert "<datalist id=cmds><option value='/joblens'><option value='/help'></datalist>" in page   # approved apps only
    cc.say("/joblens")
    page = cc.get("/")[1]
    assert "<h2>JobLens</h2>" in page and "name=text value='run JobLens'" in page and "account " in page
    cc.say("/inbox-briefing")
    assert "Draft: approve it first." in cc.get("/")[1]
    cc.say("/nope")
    assert "No command /nope" in _tells(cc)[-1] and cc.made == []
    cc.say("/")
    assert _tells(cc)[-1].startswith("GOV-AIOS -> Commands: /joblens, /help")


def test_slash_app_with_session_runs_and_closes_card(cc):
    _open(cc)
    cc.say("/joblens")
    cc.say("run JobLens")
    assert len(cc.made) == 1 and "value='run JobLens'" not in cc.get("/")[1]


def test_codex_set_up_start_and_audit(cc):
    from govaios.executor import load
    body = cc.get("/market")[1]
    assert "OpenAI Codex, governed" in body and "href='/codex'" in body
    assert "<textarea id=folders" in cc.get("/codex")[1]
    cc.post("/codex/setup", folders=str(cc.proj))
    (act, digest, ag), = cc.admin_calls
    assert (act, ag) == ("install", "codex") and len(digest) == 64
    assert "OpenAI Codex is governed" in _tells(cc)[-1]
    assert (cc.tmp / "codex" / "requirements.toml").read_text().startswith("# Written by GOV-AIOS")
    assert any("OpenAI Codex executor policy" in q for q in cc.asked)
    assert load(cc.home, "executors/codex.yaml")[0]["tools"] == ["Bash", "Write"]
    assert "Claude Code, governed" in cc.get("/market")[1] and "<p class=state>Governed</p>" in cc.get("/market")[1]
    talk = cc.get("/")[1]
    assert "OpenAI Codex<span class=m> Governed: type /codex" in cc.get("/apps")[1] and "<option value='/codex'>" in talk
    assert "<option value='/claude'>" not in talk   # Claude Code is not set up in this test
    _open(cc)
    cc.say("/codex")
    assert "action=/codex/start" in cc.get("/")[1] and "Start OpenAI Codex" in cc.get("/")[1]
    cc.say("run codex proj")
    assert cc.started == [(str(cc.proj.resolve()), "codex")] and "Starting OpenAI Codex" in _tells(cc)[-1]
    AuditLog(cc.home).append("request", flow="codex", executor="codex", action="apply_patch", target="/x/a.py",
                             decision="allow", approver="policy", session="s-9", folder=str(cc.proj))
    idx = cc.get("/audit")[1]
    assert "href='/audit/app/codex'>OpenAI Codex" in idx and "href='/audit/app/claude_code'" not in idx
    assert "/audit/codex/s-9'>Session 1" in cc.get("/audit/app/codex")[1]
    assert "<td>apply_patch</td>" in cc.get("/audit/codex/s-9")[1]
    cc.post("/codex/off")
    assert cc.admin_calls[-1][::2] == ("remove", "codex") and "OpenAI Codex governance is off" in _tells(cc)[-1]


def test_agents_are_independent(cc):
    cc.post("/claude/setup", folders=str(cc.proj))
    assert "Set up" in cc.get("/codex")[1] or "Approve and install" in cc.get("/codex")[1]
    cc.say("/codex")
    assert "OpenAI Codex is not governed yet" in _tells(cc)[-1]


LINK = "https://himalayas.app/companies/acme/jobs/senior-engineer"


def _approve_job_apply(P):
    ja = next(a for a in list_apps(P.flows, P.home) if a.name == "Job Apply")
    Approvals(P.home / "approvals.json").approve_flow(ja.id, ja.digest)
    return ja


def test_job_apply_card_has_input(cc):
    _approve_job_apply(cc)
    cc.say("/job-apply")
    page = cc.get("/")[1]
    assert "Himalayas job link" in page and "name='in:job_url'" in page and "name=text value='/job-apply'" in page
    assert "pattern='https://himalayas\\.app/companies/[a-z0-9\\-]+/jobs/[a-z0-9\\-]+/?([?#].*)?'" in page


def test_job_apply_starts_with_link_from_card_and_from_words(cc):
    ja = _approve_job_apply(cc)
    _open(cc)
    cc.post("/say", text="/job-apply", **{"in:job_url": LINK})
    assert [r.inputs for r in cc.made] == [{"job_url": LINK}]
    assert cc.made[0].started and cc.made[0].flow_path == ja.path
    cc.made[0].done = True
    cc.say(f"/job-apply {LINK}")
    assert [r.inputs for r in cc.made] == [{"job_url": LINK}] * 2


def test_job_apply_strips_tracking_and_slash(cc):
    _approve_job_apply(cc)
    _open(cc)
    cc.say(f"/job-apply {LINK}/?utm_source=x#top")
    assert [r.inputs for r in cc.made] == [{"job_url": LINK}]


def test_job_apply_rejects_bad_link(cc):
    _approve_job_apply(cc)
    _open(cc)
    cc.post("/say", text="/job-apply", **{"in:job_url": "https://evil.example/x"})
    cc.say("/job-apply not a link")
    cc.say("run Job Apply")
    assert cc.made == [] and _tells(cc)[-3:] == ["GOV-AIOS -> That isn't a valid Himalayas job link."] * 3
    assert "evil.example" not in "".join(_tells(cc))


def test_job_apply_needs_session(cc):
    _approve_job_apply(cc)
    cc.say(f"/job-apply {LINK}")
    assert cc.made == [] and "authenticator" in _tells(cc)[-1]


def test_apps_without_inputs_unchanged(cc):
    _open(cc)
    cc.say("/joblens")
    assert "name='in:" not in cc.get("/")[1]
    cc.say("/joblens extra words")
    assert len(cc.made) == 1 and cc.made[0].inputs is None


def test_job_apply_undeclared_inputs_dropped(cc):
    _approve_job_apply(cc)
    _open(cc)
    cc.post("/say", text="/job-apply", **{"in:job_url": LINK, "in:evil": "x"})
    assert [r.inputs for r in cc.made] == [{"job_url": LINK}]


def test_agent_slash_ignores_in_fields(cc):
    cc.post("/say", text="/claude", **{"in:x": "y"})
    assert cc.made == [] and "run claude None" not in "".join(cc.srv.panel.convo)
    assert "is not governed yet" in _tells(cc)[-1]


def _asking(P, fields):
    """A live Job Apply run whose engine has written ask.json; returns its run id."""
    from govaios import applyfiles
    from govaios.panel.tickets import run_id
    _approve_job_apply(P)
    _open(P)
    P.say(f"/job-apply {LINK}")
    rid = run_id(P.made[-1].ticket)
    applyfiles.write_json(P.home, applyfiles.ASK, {"run": rid, "fields": fields})
    return rid


ASKED = [{"key": "#why", "label": "Why us? <b>", "kind": "textarea", "options": []},
         {"key": "label:visa:0", "label": "Need a visa?", "kind": "radio", "options": ["Yes", "No"]}]


def _ask_digest(P):
    return re.search(r"name=ask value='([0-9a-f]+)'", P.get("/")[1])[1]


def test_answer_card_round_trip(cc):
    from govaios import applyfiles
    rid = _asking(cc, ASKED)
    page = cc.get("/")[1]
    assert "Why us? &lt;b&gt;" in page and "<b>" not in page.split("Why us?")[1][:20]
    assert "type=radio name='a:label:visa:0' value='Yes'" in page and "Save to my bank" in page
    cc.post("/apply/answer", ask=_ask_digest(cc), **{"a:#why": "Great team SECRETVAL", "save:#why": "1",
                                                     "a:label:visa:0": "No"})
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) == {
        "run": rid, "answers": {"#why": "Great team SECRETVAL", "label:visa:0": "No"}}
    b = _log(cc.home, "bank_updated")
    assert len(b) == 1 and b[0]["field"] == "#why" and "outcome" not in b[0]
    assert _log(cc.home, "apply_answer")[0]["outcome"] == "2"
    assert "SECRETVAL" not in AuditLog(cc.home).path.read_text() and "SECRETVAL" not in "".join(cc.srv.panel.convo)
    bank = yaml.safe_load((cc.home / applyfiles.BANK).read_text())
    assert bank["answers"] == [{"key": "why_us_b", "labels": ["Why us? <b>"], "answer": "Great team SECRETVAL"}]
    d = _ask_digest(cc) if "name=ask" in cc.get("/")[1] else "x"
    cc.post("/apply/answer", ask=d, **{"a:#why": "again"})   # a second reply to the same ask is refused
    assert applyfiles.read_json(cc.home, applyfiles.REPLY)["answers"]["#why"] == "Great team SECRETVAL"
    assert len(_log(cc.home, "apply_answer")) == 1


@pytest.mark.parametrize("bad", [{"a:label:visa:0": "Maybe"}, {"a:#why": "a\x00b"}, {"a:#why": "x" * 2001}])
def test_answer_rejects_option_not_offered_and_control_chars(cc, bad):
    from govaios import applyfiles
    _asking(cc, ASKED)
    cc.post("/apply/answer", ask=_ask_digest(cc), **bad)
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None and not _log(cc.home, "apply_answer")
    assert "Maybe" not in "".join(cc.srv.panel.convo)


def test_answer_needs_session(cc):
    from govaios import applyfiles
    _asking(cc, ASKED)
    d = _ask_digest(cc)
    cc.req("/apply/answer", "POST", body={"ask": d, "a:#why": "x"})   # no browser cookie
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None
    csrf = cc.csrf()
    cc.srv.panel.session.end("ended")   # code session over: no answering either
    cc.req("/apply/answer", "POST", cookie=cc.sid, body={"csrf": csrf, "ask": d, "a:#why": "x"})
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None


def test_answer_card_ignores_other_run(cc):
    from govaios import applyfiles
    _asking(cc, ASKED)
    applyfiles.write_json(cc.home, applyfiles.ASK, {"run": "0" * 16, "fields": ASKED})
    assert "Save to my bank" not in cc.get("/")[1]
    cc.post("/apply/answer", ask="0", **{"a:#why": "x"})
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None


def test_result_card_lists_labels_only(cc):
    from govaios import applyfiles
    rid = _asking(cc, ASKED)
    applyfiles.write_json(cc.home, applyfiles.RESULT, {"run": rid, "filled": 5, "total": 8,
                                                       "yourself": ["Resume/CV", "<i>Gender</i>"], "check": ["Phone"]})
    cc.made[-1].done, cc.made[-1].code = True, 0
    page = cc.get("/")[1]
    assert "Filled 5 of 8 fields. Review the form in Chrome and press Submit yourself." in page
    assert "Fill in Chrome yourself:" in page and "&lt;i&gt;Gender&lt;/i&gt;" in page and "<i>" not in page
    assert "Check:" in page and "Phone" in page
    applyfiles.write_json(cc.home, applyfiles.RESULT, {"run": "0" * 16, "filled": 1, "total": 1,
                                                       "yourself": [], "check": []})
    assert "Filled 1 of 1" not in cc.get("/")[1]


def test_done_run_cleans_ask_and_reply(cc):
    from govaios import applyfiles
    rid = _asking(cc, ASKED)
    applyfiles.write_json(cc.home, applyfiles.REPLY, {"run": rid, "answers": {}})
    cc.made[-1].done, cc.made[-1].stopped_reason = True, "killed"
    cc.srv.panel.tick()
    assert not (cc.home / applyfiles.ASK).exists() and not (cc.home / applyfiles.REPLY).exists()


def test_textarea_crlf_becomes_newline_and_engine_accepts(cc):
    from govaios import applyfiles
    from govaios.formfill import ok_value
    _asking(cc, ASKED)
    cc.post("/apply/answer", ask=_ask_digest(cc), **{"a:#why": "line1\r\nline2", "save:#why": "1"})
    v = applyfiles.read_json(cc.home, applyfiles.REPLY)["answers"]["#why"]
    assert v == "line1\nline2" and ok_value(v, "textarea")
    assert yaml.safe_load((cc.home / applyfiles.BANK).read_text())["answers"][0]["answer"] == "line1\nline2"


def test_crlf_in_text_field_still_refused(cc):
    from govaios import applyfiles
    _asking(cc, [{"key": "#n", "label": "Name", "kind": "text", "options": []}])
    cc.post("/apply/answer", ask=_ask_digest(cc), **{"a:#n": "a\r\nb"})
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None


def test_select_field_offers_options_and_checks_choice(cc):
    from govaios import applyfiles
    sel = [{"key": "#country", "label": "Country", "kind": "select", "options": ["India", "Other"]}]
    _asking(cc, sel)
    page = cc.get("/")[1]
    assert "type=radio name='a:#country' value='India'" in page and "value='Select...'" not in page
    cc.post("/apply/answer", ask=_ask_digest(cc), **{"a:#country": "Select..."})
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None
    cc.post("/apply/answer", ask=_ask_digest(cc), **{"a:#country": "India"})
    assert applyfiles.read_json(cc.home, applyfiles.REPLY)["answers"] == {"#country": "India"}


def test_bank_save_failure_still_sends_reply(cc, monkeypatch):
    from govaios import applyfiles
    from govaios.audit import web
    def boom(*a):
        raise OSError("disk")
    monkeypatch.setattr(web, "add_answer", boom)
    _asking(cc, ASKED)
    st, _, _ = cc.post("/apply/answer", ask=_ask_digest(cc), **{"a:#why": "SECRETVAL", "save:#why": "1"})
    assert st == 303 or st == 302
    assert applyfiles.read_json(cc.home, applyfiles.REPLY)["answers"]["#why"] == "SECRETVAL"
    assert "GOV-AIOS -> That answer couldn't be saved to your bank." in _tells(cc)
    assert _log(cc.home, "bank_updated")[-1]["outcome"] == "error"


def test_done_run_finish_message_survives_cleanup_error(cc):
    from govaios import applyfiles
    _asking(cc, ASKED)
    (cc.home / applyfiles.ASK).unlink()
    (cc.home / applyfiles.ASK).mkdir()   # unlink of a directory fails
    cc.made[-1].done, cc.made[-1].code = True, 0
    cc.srv.panel.tick()
    assert _tells(cc)[-1].startswith("GOV-AIOS -> Job Apply finished")


def test_long_field_key_capped_in_form(cc):
    _asking(cc, [{"key": "#" + "k" * 5000, "label": "L", "kind": "text", "options": []}])
    assert "k" * 300 not in cc.get("/")[1]


GOOD_BANK = "answers:\n- key: why\n  labels: [\"Why us?\"]\n  answer: BANKSECRET\n"


def test_bank_page_needs_session(cc):
    from govaios import applyfiles
    assert cc.req("/apply/bank", cookie=None)[0] == 303
    cc.req("/apply/bank", "POST", body={"text": GOOD_BANK})
    assert not (cc.home / applyfiles.BANK).exists()
    st, page = cc.get("/apply/bank")[:2]
    assert st == 200 and "<textarea" in page and "<script" not in page


def test_bank_page_saves_valid(cc):
    from govaios import applyfiles
    cc.post("/apply/bank", text=GOOD_BANK.replace("\n", "\r\n"))
    p = cc.home / applyfiles.BANK
    assert p.read_text() == GOOD_BANK and (p.stat().st_mode & 0o777) == 0o600
    assert not [x for x in p.parent.iterdir() if x.name != p.name]
    b = _log(cc.home, "bank_updated")
    assert len(b) == 1 and b[0]["field"] == "all" and "outcome" not in b[0]
    assert "BANKSECRET" not in AuditLog(cc.home).path.read_text() and "BANKSECRET" not in "".join(cc.srv.panel.convo)
    assert "BANKSECRET" in cc.get("/apply/bank")[1]


def test_bank_page_rejects_malformed_and_keeps_old(cc):
    from govaios import applyfiles
    p = cc.home / applyfiles.BANK
    cc.post("/apply/bank", text=GOOD_BANK)
    for bad in ("answers: [unclosed\n", "answers:\n- key: x\n  labels: [a]\n  answer: \"\\x01\"\n", "x" * 70000):
        cc.post("/apply/bank", text=bad)
        assert p.read_text() == GOOD_BANK
    cc.post("/apply/bank", text="answers: [unclosed SECRETBAD\n")
    page = cc.get("/apply/bank")[1]
    assert "YAML error" in page and page.count("SECRETBAD") == 1   # only inside the textarea
    assert "YAML error" not in cc.get("/apply/bank")[1]
    assert not [x for x in p.parent.iterdir() if x.name != p.name]
    assert "SECRETBAD" not in AuditLog(cc.home).path.read_text()


def _bad(cc, text):
    from govaios import applyfiles
    cc.post("/apply/bank", text=text)
    return (cc.home / applyfiles.BANK).exists(), cc.get("/apply/bank")[1]


def test_bank_page_refusals_keep_nothing(cc):
    for bad, msg in (("- a\n- b\n", "must be a mapping"),
                     ("answers:\n" + "".join(f"- key: k{i}\n  labels: [a]\n  answer: b\n" for i in range(301)), "at most 300"),
                     ("a: 2001-13-45\n", "YAML error"),
                     ("a: " + "[" * 5000 + "\n", "YAML error"),
                     ("cv_file: /etc/passwd.pdf\n", "inside your home"),
                     ("cv_file: ~/../../etc/x.pdf\n", "inside your home")):
        exists, page = _bad(cc, bad)
        assert not exists and msg in page, msg
    exists, _ = _bad(cc, "cv_file: ~/not-yet.pdf\n")   # a CV that is not there yet is fine
    assert exists


def test_bank_page_escapes_textarea_and_too_large_not_echoed(cc):
    cc.post("/apply/bank", text="# </textarea><b>x\nanswers: []\n")
    page = cc.get("/apply/bank")[1]
    assert "&lt;/textarea&gt;&lt;b&gt;x" in page and "</textarea><b>" not in page
    cc.post("/apply/bank", text="# BIGMARK\n" + "x" * 61000)
    page = cc.get("/apply/bank")[1]
    assert "too large" in page and "BIGMARK" not in page


def test_bank_page_post_needs_csrf(cc):
    from govaios import applyfiles
    cc.req("/apply/bank", "POST", cookie=cc.sid, body={"text": GOOD_BANK})
    cc.req("/apply/bank", "POST", cookie=cc.sid, body={"csrf": "wrong", "text": GOOD_BANK})
    assert not (cc.home / applyfiles.BANK).exists()


def test_bank_page_symlinked_dir_refused(cc):
    from govaios import applyfiles
    real = cc.tmp / "elsewhere"
    real.mkdir()
    (cc.home / "apply").symlink_to(real)
    _, page = _bad(cc, GOOD_BANK)
    assert "symlink" in page and list(real.iterdir()) == []


REFRESH = '<meta http-equiv="refresh" content="2">'


def test_answer_card_stops_refresh_and_autofocus(cc):
    from govaios import applyfiles
    _approve_job_apply(cc)
    _open(cc)
    cc.say(f"/job-apply {LINK}")
    page = cc.get("/")[1]   # live, nothing asked: today's refresh and focus
    assert REFRESH in page and re.search(r"<input id=cmd [^>]*autofocus", page)
    from govaios.panel.tickets import run_id
    rid = run_id(cc.made[-1].ticket)
    applyfiles.write_json(cc.home, applyfiles.ASK, {"run": rid, "fields": ASKED})
    page = cc.get("/")[1]   # the admin is typing: nothing may reload or steal focus
    assert "Save to my bank" in page and "refresh" not in page and not re.search(r"<input id=cmd [^>]*autofocus", page)
    applyfiles.write_json(cc.home, applyfiles.REPLY, {"run": rid, "answers": {}})
    page = cc.get("/")[1]
    assert REFRESH in page and re.search(r"<input id=cmd [^>]*autofocus", page)


def _result(cc, done_ok):
    from govaios import applyfiles
    rid = _asking(cc, ASKED)
    applyfiles.write_json(cc.home, applyfiles.RESULT, {"run": rid, "filled": 2, "total": 3,
                                                       "yourself": ["Resume/CV"], "check": []})
    cc.made[-1].done, cc.made[-1].code = True, 0 if done_ok else 70
    if not done_ok:
        cc.made[-1].stopped_reason = "emergency stop"
    return cc.get("/")[1]


def test_result_card_finished_says_submit_yourself(cc):
    page = _result(cc, True)
    assert "press Submit yourself" in page and "stopped" not in page.split("JobLens</h2>")[-1]


def test_result_card_stopped_run_says_check_form(cc):
    page = _result(cc, False).split("JobLens</h2>")[-1]
    assert "press Submit yourself" not in page
    assert "The run stopped. Check the form in Chrome." in page and "Resume/CV" in page


def test_bank_post_limit_raised_for_bank_only(cc):
    from govaios import applyfiles
    big = GOOD_BANK + ("#" + ":" * 99 + "\n") * 500   # ~50 KB; ':' and newline url-encode to 3 bytes each
    assert 50000 <= len(big) <= 60000 and len(urlencode({"text": big})) > 3 * 50000
    st = cc.post("/apply/bank", text=big)[0]
    assert st in (302, 303) and (cc.home / applyfiles.BANK).read_text() == big
    st = cc.post("/say", text="x" * 70000)[0]   # every other route keeps the old limit
    assert st == 400


def test_bank_page_get_refuses_symlink_and_fifo(cc):
    from govaios import applyfiles
    (cc.home / "apply").mkdir(mode=0o700)
    secret = cc.tmp / "secret.yaml"
    secret.write_text("answers: []\n# LINKEDSECRET\n")
    (cc.home / applyfiles.BANK).symlink_to(secret)
    st, page = cc.get("/apply/bank")[:2]
    assert st == 200 and "LINKEDSECRET" not in page
    (cc.home / applyfiles.BANK).unlink()
    os.mkfifo(cc.home / applyfiles.BANK)
    t = threading.Thread(target=lambda: cc.get("/apply/bank"), daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "GET /apply/bank hung on a FIFO"


def test_bank_page_get_refuses_symlinked_dir(cc):
    from govaios import applyfiles
    real = cc.tmp / "elsewhere2"
    real.mkdir()
    (real / "answers.yaml").write_text("# DIRSECRET\n")
    (cc.home / "apply").symlink_to(real)
    assert "DIRSECRET" not in cc.get("/apply/bank")[1]


def _carding(P, kind="fix", label="Notice <b>period</b>", job="", item=0):
    """A live Job Apply run waiting on one of its cards (applyfiles.CARDS)."""
    from govaios import applyfiles
    rid = _asking(P, ASKED)
    applyfiles.write_json(P.home, applyfiles.ASK, {"run": rid, "card": {"kind": kind, "label": label, "job": job,
                                                                        "item": item}})
    return rid


def _spoken_soon(P, n):
    for _ in range(200):
        if len(P.spoken) >= n:
            return P.spoken
        time.sleep(0.01)
    return P.spoken


@pytest.mark.parametrize("choice", ["continue", "skip"])
def test_fix_card_round_trip(cc, choice):
    from govaios import applyfiles
    rid = _carding(cc)
    page = cc.get("/")[1]
    assert "Fill this field in Chrome" in page and "Notice &lt;b&gt;period" in page and "<b>period" not in page
    assert 'http-equiv="refresh"' not in page   # no reload under the admin's click
    cc.get("/")
    assert _spoken_soon(cc, 1) == ["Rupak, I couldn't fill Notice <b>period</b>. Please fill it in Chrome, "
                                   "then press Continue."]   # once, not on every reload
    cc.post("/apply/card", ask=_ask_digest(cc), choice=choice)
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) == {"run": rid, "card": choice}
    assert [(x["outcome"], x["item"]) for x in _log(cc.home, "apply_card")] == [(choice, 0)]
    cc.post("/apply/card", ask="x", choice="skip")   # a second reply is refused
    assert applyfiles.read_json(cc.home, applyfiles.REPLY)["card"] == choice and len(_log(cc.home, "apply_card")) == 1


@pytest.mark.parametrize("body", [{"choice": "submit"}, {"choice": "next"}, {"choice": "continue", "ask": "0"}])
def test_card_rejects_other_choices_or_digest(cc, body):
    from govaios import applyfiles
    _carding(cc)   # a fix card: "next" belongs to another kind
    cc.post("/apply/card", **{"ask": _ask_digest(cc), **body})
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None and not _log(cc.home, "apply_card")


def test_card_needs_session_and_this_run(cc):
    from govaios import applyfiles
    _carding(cc)
    d = _ask_digest(cc)
    cc.req("/apply/card", "POST", body={"ask": d, "choice": "continue"})   # no browser cookie
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None
    applyfiles.write_json(cc.home, applyfiles.ASK, {"run": "0" * 16, "card": {"kind": "fix", "label": "x", "job": "",
                                                                             "item": 0}})
    assert "Fill this field in Chrome" not in cc.get("/")[1]


def _tasks(P, rid, ts):
    from govaios import applyfiles
    applyfiles.write_json(P.home, applyfiles.TASKS, {"run": rid, "tasks": ts})


def test_review_card_and_tasks_in_talk(cc):
    from govaios import applyfiles
    rid = _carding(cc, "review", "", "Acme <i>Test</i> \u2014 Lead", 2)
    _tasks(cc, rid, [{"n": 1, "title": "Old \u2014 Dev", "status": "done", "filled": 3, "total": 3},
                     {"n": 2, "title": "Acme <i>Test</i> \u2014 Lead", "status": "review", "filled": 5, "total": 6,
                      "yourself": ["Gender"]}, {"n": "x", "title": 3, "status": "bad"}])
    page = cc.get("/")[1]
    assert "Ready for you to submit" in page and "Acme &lt;i&gt;Test" in page and "<i>Test" not in page
    assert "<a href='/apply/task/1'>1. Old \u2014 Dev</a> \u00b7 Done" in page and "Ready to submit" in page
    assert "/apply/task/3" not in page   # a malformed task is not shown
    assert _spoken_soon(cc, 1)[-1] == "Rupak, Acme <i>Test</i> \u2014 Lead is ready. Please check it and submit it in Chrome."
    s, _, r = cc.post("/apply/card", ask=_ask_digest(cc), choice="next")
    assert r.getheader("Location") == "/apply/task/2"
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) == {"run": rid, "card": "next"}


def test_task_page_shows_its_log_counts_and_card(cc):
    from govaios.audit.log import AuditLog
    rid = _carding(cc, "stopped", "unexpected page", "Acme \u2014 Lead", 1)
    _tasks(cc, rid, [{"n": 1, "title": "Acme \u2014 Lead", "status": "stopped", "reason": "unexpected page",
                      "filled": 0, "total": 0}])
    log = AuditLog(cc.home)
    log.append("flow_start", flow="job_apply", flow_hash="h")
    log.append("action", flow="job_apply", step="open_job", action="click", target="Lead", outcome="done", item=1)
    log.append("action", flow="job_apply", step="other", action="click", target="Other job", outcome="done", item=2)
    page = cc.get("/apply/task/1")[1]
    assert "Job 1: Acme \u2014 Lead" in page and "Stopped: unexpected page" in page and "This job stopped" in page
    assert "open_job" in page and "Other job" not in page
    assert cc.get("/apply/task/9")[0] == 404
    assert cc.req("/apply/task/1")[0] in (302, 303)   # signed out: to the Locked page


def test_sandbox_card_lists_captured_pages(cc):
    from govaios import applyfiles
    rid = _carding(cc, "sandbox", "1 captured")
    applyfiles.write_json(cc.home, applyfiles.SANDBOX, {"run": rid, "pages": [
        {"title": "Shop <b>", "url": "https://shop.example", "file": "x.json", "fields": 2, "buttons": 3, "links": 4},
        {"title": "", "url": "https://other.example/", "file": None, "note": "another site: not captured"}]})
    page = cc.get("/")[1]
    assert "Capture this page" in page and "Shop &lt;b&gt;: 2 fields, 3 buttons, 4 links" in page
    assert "another site: not captured" in page
    s, _, r = cc.post("/apply/card", ask=_ask_digest(cc), choice="capture")
    assert r.getheader("Location") == "/" and applyfiles.read_json(cc.home, applyfiles.REPLY)["card"] == "capture"


@pytest.mark.parametrize("bad", [{"kind": ["fix"], "label": "x", "job": "", "item": 0}, {"kind": {}, "label": "x"}])
def test_malformed_card_or_tasks_never_break_talk(cc, bad):
    from govaios import applyfiles
    rid = _asking(cc, ASKED)
    applyfiles.write_json(cc.home, applyfiles.ASK, {"run": rid, "card": bad})
    _tasks(cc, rid, [{"n": 1, "title": "t", "status": ["done"]}, {"n": 2, "title": "t", "status": {}}])
    s, page, _ = cc.get("/")
    assert s == 200 and "JobLens jobs" not in page


def test_card_and_stop_name_the_saved_page(cc):
    from govaios import applyfiles
    rid = _asking(cc, ASKED)
    applyfiles.write_json(cc.home, applyfiles.ASK, {"run": rid, "card": {
        "kind": "stopped", "label": "unexpected page", "job": "A", "item": 1, "capture": "20261108-201918-912751-job_apply.json"}})
    assert "Saved page: <code>captures/20261108-201918-912751-job_apply.json</code>" in cc.get("/")[1]
    applyfiles.write_json(cc.home, applyfiles.ASK, {"run": rid, "card": {
        "kind": "stopped", "label": "x", "job": "A", "item": 1, "capture": "../../etc/passwd<b>"}})
    assert "Saved page" not in cc.get("/")[1]   # only a capture file name is ever shown
    r = cc.made[-1]
    r.done, r.code, r.capture = True, 1, "20261108-201918-912751-job_apply.json"
    cc.srv.panel.tick()
    assert _tells(cc)[-1].endswith("Saved page: captures/20261108-201918-912751-job_apply.json")


def test_stop_says_the_apps_reason_not_exit_code(cc):
    _asking(cc, ASKED)
    r = cc.made[-1]
    r.done, r.code, r.reason = True, 1, "no Ready jobs in JobLens"
    cc.srv.panel.tick()
    assert "stopped: no Ready jobs in JobLens" in _tells(cc)[-1] and "exit 1" not in _tells(cc)[-1]


def _studio_drafts(P):
    from govaios import studio
    b = {"application": "chrome", "profile_directory": "Profile 2", "account": "a@example.com"}
    jobs = studio.write_draft(P.flows, P.flows.parent / "pages", {"role": "document", "name": "Jobs <b>", "children": [
        {"role": "heading", "name": "Roles"}, {"role": "link", "name": "Lead <i>"},
        {"role": "button", "name": "Delete account"}]}, "https://acme.example/jobs", b, "c.json")
    return jobs


def test_studio_lists_drafts_and_never_offers_submit_clicks(cc):
    jobs = _studio_drafts(cc)
    s, page, _ = cc.get("/studio")
    assert s == 200 and jobs in page and "Check app" not in page and "New automation" in page and "aria-current=page>Studio" in page
    assert f"value='click:{jobs}.link_lead_i'>Click Lead &lt;i&gt;" in page and "<i>" not in page.split("Studio</h1>")[1]
    assert "Delete account" not in page   # rated submit: never composed into a click


def test_studio_compose_saves_a_draft_app(cc):
    jobs = _studio_drafts(cc)
    s, _, r = cc.post("/studio/compose", app="Acme apply", s1=f"open:{jobs}", s2=f"click:{jobs}.link_lead_i", s3="review")
    assert r.getheader("Location") == "/" and _tells(cc)[-1] == "GOV-AIOS -> Acme apply is saved as a draft app. Approve it to let it run."
    a = next(a for a in list_apps(cc.flows, cc.home) if a.id == "studio_acme_apply")
    assert a.name == "Acme apply" and not a.approved
    assert _log(cc.home, "setting")[-1]["field"] == "studio_compose"
    cc.post("/studio/compose", app="Acme apply", s1=f"open:{jobs}")   # never replaces an app
    assert _tells(cc)[-1] == "GOV-AIOS -> Studio: an app with that name exists."


def test_studio_compose_refuses_a_submit_click(cc):
    jobs = _studio_drafts(cc)
    s, _, r = cc.post("/studio/compose", app="Bad", s1=f"open:{jobs}", s2=f"click:{jobs}.button_delete_account")
    assert r.getheader("Location") == "/studio" and "that click stays yours" in _tells(cc)[-1]
    assert not (cc.flows / "studio_bad.yaml").exists()
    assert cc.req("/studio/compose", "POST", body={"app": "x", "s1": f"open:{jobs}"})[0] == 403   # no session


# --- Studio lessons: the teach cards, the terms form, What I learned and its Touch ID approval ---

def _lesson(P, flow="job_apply", digest=None, site="https://jobs.acme.example"):
    """A saved lesson of two pages on a new site, stuck at job_apply's on_form step; returns its name."""
    from govaios import lessons
    from govaios.desktop import Node
    ja = _approve_job_apply(P)
    (P.home / "apply").mkdir(mode=0o700, exist_ok=True)
    (P.home / "apply" / "answers.yaml").write_text("answers:\n  - {key: phone, labels: [Phone], answer: '99'}\n")

    def ev(kind, role, name, value=""):
        return {"kind": kind, "spec": {"role": role, "name": name}, "label": name, "value": value, "secure": False}
    a = Node("document", "Apply | Acme", children=[Node("heading", "Apply <b>here</b>"), Node("link", "Next"),
                                                   Node("text_field", "Email"), Node("text_field", "Passport number")])
    b = Node("document", "Review | Acme", children=[Node("heading", "Review"), Node("button", "Submit")])
    pages = [{"url": f"{site}/apply?t=1", "title": a.name, "tree": a,
              "events": [ev("fill", "text_field", "Email", "a@x.example"),
                         ev("fill", "text_field", "Passport number", "P<script>1"), ev("click", "link", "Next")]},
             {"url": f"{site}/review", "title": b.name, "tree": b,
              "events": [ev("click", "button", "Submit")]}]
    return lessons.save(P.home, flow, digest or ja.digest, "on_form", pages), ja


def _lesson_form(P, name):
    page = P.get(f"/lesson/{name}")[1]
    return re.search(r"name=p value='([0-9a-f]+)'", page)[1], page


def _snap(P):
    files = [*P.flows.glob("*.yaml"), *(P.flows.parent / "pages").glob("*.yaml"), *(P.home / "apply").glob("answers*")]
    return {f: f.read_bytes() for f in files}


def test_new_page_card_notifies_once(cc):
    notes = []
    cc.srv.panel.notify = notes.append
    _carding(cc, "new_page", "A page this flow does not know", "Acme — Lead", 1)
    page = cc.get("/")[1]
    assert "Job Apply can't go on: this page is new. Teach it?" in page
    assert "value=teach>Teach this page</button>" in page and "value=skip>Next job</button>" in page
    cc.get("/")
    _spoken_soon(cc, 1)
    for _ in range(200):
        if notes:
            break
        time.sleep(0.01)
    time.sleep(0.05)
    assert notes == ["Rupak, Job Apply can't go on: this page is new. Teach it?"] == cc.spoken


def test_notify_passes_text_as_an_argument(monkeypatch):
    from govaios.audit import web
    calls = []
    monkeypatch.setattr(web.subprocess, "run", lambda argv, **k: calls.append(argv))
    web._notify('x" & do shell script "rm')
    assert calls[0][0] == "/usr/bin/osascript" and calls[0][-1] == 'x" & do shell script "rm'
    assert not any("rm" in a for a in calls[0][:-1])


def test_teaching_card_shows_live_lines(cc):
    from govaios import applyfiles
    rid = _carding(cc, "teaching", "Do this page in Chrome")
    applyfiles.write_json(cc.home, applyfiles.LESSON_LIVE, {"run": rid, "lines": ["clicked <b>Apply</b>", "Email ← 17 chars"]})
    page = cc.get("/")[1]
    assert "Close the tab when you're done." in page and "clicked &lt;b&gt;Apply&lt;/b&gt;" in page
    assert "Email ← 17 chars" in page and '<meta http-equiv="refresh" content="2">' in page
    assert "value=done>Done</button>" in page and "value=cancel>Cancel lesson</button>" in page
    cc.post("/apply/card", ask=_ask_digest(cc), choice="done")
    assert applyfiles.read_json(cc.home, applyfiles.REPLY)["card"] == "done"
    assert _tells(cc)[-1] == "GOV-AIOS -> Lesson done: see what I learned."


def test_lesson_card_links_and_cannot_be_approved_by_the_card(cc):
    from govaios import applyfiles
    name, _ = _lesson(cc)
    _carding(cc, "lesson", name)
    page = cc.get("/")[1]
    assert f"<a class=go href='/lesson/{name}'>See what I learned</a>" in page and "name=choice" not in page
    from hashlib import sha256   # the card's own digest, as a forged form would send it
    d = sha256(json.dumps(applyfiles.read_json(cc.home, applyfiles.ASK), sort_keys=True).encode()).hexdigest()[:16]
    cc.post("/apply/card", ask=d, choice="approved")
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None and not _log(cc.home, "apply_card")


def test_lesson_page_lists_pages_steps_and_bank(cc):
    name, _ = _lesson(cc)
    s, page = cc.get(f"/lesson/{name}")[0], _lesson_form(cc, name)[1]
    assert s == 200 and "What I learned" in page
    assert page.count(" · new</h2>") == 2 and "jobs_acme_example_apply_acme" in page
    assert "name='del:0:0'" in page and "name='del:1:0'" in page   # a delete box per step line
    assert "Hand over: you check and submit" in page and "Click: Next" in page
    assert "New key <code>email</code> = “a@x.example”" in page
    assert "P&lt;script&gt;1" in page and "<script>" not in page   # the admin's own values, escaped
    assert re.search(r"Passport number”\) <b>sensitive</b>", page)
    assert "<option value=bank selected>Keep in bank</option>" in page and "value=job>This job only" in page
    assert "Approve with Touch ID" in page and "action=/lesson/discard" in page


def test_lesson_name_traversal_refused(cc):
    assert cc.get("/lesson/..%2Fx")[0] == 404
    assert cc.get("/lesson/20261109-000000-000000-job_apply.json")[0] == 404   # no such lesson
    assert cc.req("/lesson/x")[0] in (302, 303)   # signed out: the Locked page


def test_approve_writes_flow_pages_bank_and_approves(cc):
    from govaios import applyfiles
    from govaios.engine import Runner
    from govaios.formfill import load_bank
    name, ja = _lesson(cc)
    rid = _carding(cc, "lesson", name)
    p = _lesson_form(cc, name)[0]
    # keep the passport out of the bank; delete page 1's fill line (index 0)
    s, _, r = cc.post("/lesson/approve", name=name, p=p, **{"keep:1": "drop", "del:0:0": "1"})
    assert r.getheader("Location") == "/" and cc.asked[-1] == "Add what GOV-AIOS learned to Job Apply"
    wf = yaml.safe_load(ja.path.read_text())["workflow"]
    on = next(s for s in wf["steps"] if s["id"] == "on_form")["on_match"]
    assert on["jobs_acme_example_apply_acme"] == {
        "do": [{"id": "learned_jobs_acme_example_apply_acme_1", "action": "click",
                "target": "jobs_acme_example_apply_acme.link_next"}], "then": "again"}
    assert on["jobs_acme_example_review_acme"] == {
        "do": [{"id": "learned_jobs_acme_example_review_acme_1", "action": "hand_over"}], "then": "end"}
    assert list(on)[-1] == "unknown" and "https://jobs.acme.example" in wf["destinations"]
    pages = cc.flows.parent / "pages"
    assert (pages / "jobs_acme_example_apply_acme.yaml").exists() and (pages / "jobs_acme_example_review_acme.yaml").exists()
    new = next(a for a in list_apps(cc.flows, cc.home) if a.id == "job_apply")
    assert new.approved and new.digest != ja.digest
    Runner(ja.path, None, cc.home, "gov_runner_dev")   # loads: learned cases checked, every page bound
    bank = load_bank(cc.home / "apply" / "answers.yaml", cc.home)
    assert {e.key: (e.answer, e.learned) for e in bank.entries} == {"phone": ("99", False), "email": ("a@x.example", True)}
    assert list((cc.home / "apply").glob("answers.yaml.bak-*"))
    [e] = _log(cc.home, "lesson")
    assert e["outcome"] == "approved" and e["flow_hash"] == new.digest and e["target"] == name
    assert e["reason"] == "pages 2 (2 new), steps 2, bank 1" and "a@x" not in json.dumps(e)
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) == {"run": rid, "card": "approved"}
    cc.post("/lesson/approve", name=name, p=p)   # twice: the flow changed since this lesson
    assert _tells(cc)[-1] == "GOV-AIOS -> Job Apply changed since this lesson; teach it again"


@pytest.mark.parametrize("how", ["denied", "busy"])
def test_approve_refused_writes_nothing(cc, monkeypatch, how):
    from govaios import auth
    name, ja = _lesson(cc)
    p, before = _lesson_form(cc, name)[0], _snap(cc)
    monkeypatch.setattr(auth, "prove", lambda r, h, **k: (False, how))
    cc.post("/lesson/approve", name=name, p=p)
    assert _snap(cc) == before and not list((cc.home / "apply").glob("*.bak-*"))
    assert next(a for a in list_apps(cc.flows, cc.home) if a.id == "job_apply").digest == ja.digest
    assert [e["decision"] for e in _log(cc.home, "lesson")] == ["deny"]


def test_flow_changed_since_lesson_refused(cc):
    name, ja = _lesson(cc, digest="0" * 64)
    p, before = _lesson_form(cc, name)[0], _snap(cc)
    n = len(cc.asked)
    cc.post("/lesson/approve", name=name, p=p)
    assert _tells(cc)[-1] == "GOV-AIOS -> Job Apply changed since this lesson; teach it again"
    assert _snap(cc) == before and len(cc.asked) == n   # never asked for Touch ID


@pytest.mark.parametrize("bad", [{"keep:0": "all"}, {"keep:9": "bank"}, {"del:7:0": "1"}, {"x": "1"}, {"p": "0"}])
def test_approve_refuses_forged_edits(cc, bad):
    name, _ = _lesson(cc)
    before = _snap(cc)
    n = len(cc.asked)
    cc.post("/lesson/approve", **{"name": name, "p": _lesson_form(cc, name)[0], **bad})
    assert _snap(cc) == before and len(cc.asked) == n


def test_sandbox_lesson_writes_only_pages(cc):
    name, ja = _lesson(cc, flow="web_sandbox")
    before = _snap(cc)
    cc.post("/lesson/approve", name=name, p=_lesson_form(cc, name)[0])
    after = _snap(cc)
    assert {f.name for f in set(after) - set(before)} == {"jobs_acme_example_apply_acme.yaml",
                                                          "jobs_acme_example_review_acme.yaml"}
    assert all(after[f] == b for f, b in before.items())   # no flow, no bank change
    assert cc.asked[-1] == "Add what GOV-AIOS learned to Studio" and _log(cc.home, "lesson")[-1]["outcome"] == "approved"


def test_sandbox_lesson_pages_are_studio_drafts_and_deletable(cc):
    from govaios import studio
    name, _ = _lesson(cc, flow="web_sandbox")
    cc.post("/lesson/approve", name=name, p=_lesson_form(cc, name)[0])
    pages = cc.flows.parent / "pages"
    cat = studio.catalogue(cc.flows, pages)
    assert cat["jobs_acme_example_apply_acme"]["url"] == "https://jobs.acme.example/apply"   # never the query
    assert cat["jobs_acme_example_review_acme"]["url"] == "https://jobs.acme.example/review"
    assert (pages / "jobs_acme_example_review_acme.yaml").read_text().startswith("# Draft from the Web Sandbox lesson")
    _delete(cc, "page", "jobs_acme_example_review_acme")
    assert not (pages / "jobs_acme_example_review_acme.yaml").exists()


def test_sandbox_lesson_page_has_no_bank_section(cc):
    name, _ = _lesson(cc, flow="web_sandbox")
    page = _lesson_form(cc, name)[1]
    assert "Answer bank" not in page and "name='keep:" not in page
    assert "Answer bank" in _lesson_form(cc, _lesson(cc)[0])[1]


def test_bad_bank_op_refused_before_touch_id(cc):
    from govaios import lessons
    from govaios.desktop import Node
    ja = _approve_job_apply(cc)
    (cc.home / "apply").mkdir(mode=0o700, exist_ok=True)
    (cc.home / "apply" / "answers.yaml").write_text("answers:\n  - {key: phone, labels: [Phone], answer: '99'}\n")
    label = "Q" * 301   # longer than a bank label may be
    t = Node("document", "Apply | Acme", children=[Node("heading", "Apply"), Node("text_field", label)])
    name = lessons.save(cc.home, "job_apply", ja.digest, "on_form", [{"url": "https://jobs.acme.example/a", "title": t.name,
        "tree": t, "events": [{"kind": "fill", "spec": {"role": "text_field", "name": label}, "label": label,
                               "value": "x", "secure": False}]}])
    before, n = _snap(cc), len(cc.asked)
    cc.post("/lesson/approve", name=name, p=_lesson_form(cc, name)[0])
    assert _tells(cc)[-1].startswith("GOV-AIOS -> Not approved: op add") and len(cc.asked) == n
    assert _snap(cc) == before


@pytest.mark.parametrize("flow", ["job_apply", "web_sandbox"])
def test_lesson_never_writes_the_shipped_files(cc, monkeypatch, flow):
    from govaios import engine
    name, _ = _lesson(cc, flow=flow)
    p, before, n = _lesson_form(cc, name)[0], _snap(cc), len(cc.asked)
    monkeypatch.setattr(engine, "REPO", cc.flows.parent)   # as if the panel ran on the repo's own flows/
    cc.post("/lesson/approve", name=name, p=p)
    assert "shipped" in _tells(cc)[-1] and _snap(cc) == before and len(cc.asked) == n


def test_discard_audits_and_replies(cc):
    from govaios import applyfiles
    name, _ = _lesson(cc)
    rid = _carding(cc, "lesson", name)
    cc.post("/lesson/discard", name=name)
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) == {"run": rid, "card": "discarded"}
    assert [e["outcome"] for e in _log(cc.home, "lesson")] == ["discarded"]


def test_terms_post_validates_and_records(cc):
    from govaios import applyfiles, terms
    rid = _carding(cc, "terms", "https://apply.example.invalid")
    page = cc.get("/")[1]
    assert "action=/terms" in page and "href='https://apply.example.invalid'" in page
    ask = _ask_digest(cc)
    cc.post("/terms", ask=ask, verdict="maybe", link="https://apply.example.invalid/terms", clause="")
    assert _tells(cc)[-1].startswith("GOV-AIOS -> Terms not recorded: verdict must be")
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None
    cc.post("/terms", ask=ask, verdict="allowed", link="http://x.example/terms", clause="")   # not https
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) is None
    cc.post("/terms", ask=ask, verdict="allowed", link="https://apply.example.invalid/terms", clause="Personal use ok")
    assert terms.verdict(cc.home, "https://apply.example.invalid", []) == "allowed"
    assert applyfiles.read_json(cc.home, applyfiles.REPLY) == {"run": rid, "card": "checked"}
    cc.post("/apply/card", ask="x", choice="checked")   # checked only through the form
    assert _log(cc.home, "apply_card")[-1]["outcome"] == "checked" and len(_log(cc.home, "apply_card")) == 1


def _approved_now(P):
    return next(a for a in list_apps(P.flows, P.home) if a.id == "job_apply").approved


def test_bound_page_changed_during_touch_id_not_approved(cc, monkeypatch):
    from govaios import auth
    name, ja = _lesson(cc)
    p = _lesson_form(cc, name)[0]
    gh = cc.flows.parent / "pages" / "greenhouse_application.yaml"   # bound by on_form
    monkeypatch.setattr(auth, "prove", lambda r, h, **k: (gh.write_text(gh.read_text() + "# swapped\n"), (True, "biometric"))[1])
    cc.post("/lesson/approve", name=name, p=p)
    assert not _approved_now(cc) and _log(cc.home, "lesson")[-1]["outcome"] == "error"
    assert Approvals(cc.home / "approvals.json").snapshot()["flows"]["job_apply"] == ja.digest   # the old one only


def test_http_site_is_never_added(cc):
    name, _ = _lesson(cc, site="http://jobs.acme.example")
    before, n = _snap(cc), len(cc.asked)
    cc.post("/lesson/approve", name=name, p=_lesson_form(cc, name)[0])
    assert _tells(cc)[-1] == "GOV-AIOS -> Not approved: only https sites can be added, not http://jobs.acme.example."
    assert _snap(cc) == before and len(cc.asked) == n


def test_site_added_normalised(cc):
    name, ja = _lesson(cc, site="https://Jobs.Acme.Example:443")
    cc.post("/lesson/approve", name=name, p=_lesson_form(cc, name)[0])
    assert yaml.safe_load(ja.path.read_text())["workflow"]["destinations"][-1] == "https://jobs.acme.example"


def test_revoked_flow_is_not_reapproved_by_a_lesson(cc):
    name, ja = _lesson(cc)
    p = _lesson_form(cc, name)[0]
    Approvals(cc.home / "approvals.json").revoke_flow("job_apply")
    before, n = _snap(cc), len(cc.asked)
    cc.post("/lesson/approve", name=name, p=p)
    assert _tells(cc)[-1] == "GOV-AIOS -> Approve Job Apply first, then add what it learned."
    assert _snap(cc) == before and len(cc.asked) == n and not _approved_now(cc)


@pytest.mark.parametrize("how", ["no_session", "bad_csrf", "origin"])
def test_lesson_approve_needs_session_csrf_and_origin(cc, how):
    name, _ = _lesson(cc)
    p = _lesson_form(cc, name)[0]
    before, n = _snap(cc), len(cc.asked)
    body = {"csrf": cc.csrf(), "name": name, "p": p}
    if how == "no_session":
        s = cc.req("/lesson/approve", "POST", body=body)[0]
    elif how == "bad_csrf":
        s = cc.req("/lesson/approve", "POST", cookie=cc.sid, body={**body, "csrf": "x"})[0]
    else:
        s = cc.req("/lesson/approve", "POST", cookie=cc.sid, body=body, headers={"Origin": "http://evil.example"})[0]
    assert s == 403 and _snap(cc) == before and len(cc.asked) == n


def test_bank_failure_midway_leaves_flow_unapproved(cc, monkeypatch):
    from govaios import formfill
    name, _ = _lesson(cc)
    p = _lesson_form(cc, name)[0]
    monkeypatch.setattr(formfill, "apply_ops",   # the dry run passes; the bank changes before the real write
                        lambda p, o, dry=False: None if dry else (_ for _ in ()).throw(formfill.BankError("bank full")))
    cc.post("/lesson/approve", name=name, p=p)
    assert not _approved_now(cc) and _log(cc.home, "lesson")[-1]["outcome"] == "error"
    assert _log(cc.home, "lesson")[-1]["reason"] == "BankError"


def test_new_page_made_during_touch_id_is_never_replaced(cc, monkeypatch):
    from govaios import auth
    name, _ = _lesson(cc)
    p = _lesson_form(cc, name)[0]
    other = cc.flows.parent / "pages" / "jobs_acme_example_review_acme.yaml"
    monkeypatch.setattr(auth, "prove", lambda r, h, **k: (other.write_text("mine\n"), (True, "biometric"))[1])
    cc.post("/lesson/approve", name=name, p=p)
    assert other.read_text() == "mine\n" and "jobs_acme" not in (cc.flows / "job_apply.yaml").read_text()
    assert _log(cc.home, "lesson")[-1]["outcome"] == "error"


def test_lesson_page_warns_about_end_and_other_apps(cc):
    pages = cc.flows.parent / "pages"
    (pages / "acme_apply.yaml").write_text(
        "page:\n  id: acme_apply\n  identification: {title_matches: '^Apply \\| Acme$', anchors: [heading]}\n"
        "  elements:\n    heading: {role: heading, name: 'Apply <b>here</b>', risk: read}\n")
    other = cc.flows / "other.yaml"
    other.write_text((cc.flows / "job_apply.yaml").read_text().replace("id: job_apply", "id: other_flow", 1)
                     .replace('app: "Job Apply"', 'app: "Other <i>app</i>"', 1)
                     .replace("greenhouse_application: continue", "acme_apply: continue", 1))
    name, _ = _lesson(cc)
    page = _lesson_form(cc, name)[1]
    assert "acme_apply</code> \u00b7 known" in page and "Adds to this page: next</p>" in page
    assert "Changing this page means approving again: Other &lt;i&gt;app&lt;/i&gt;." in page
    assert "the run does not end there" not in page
    # the last page already has a case in the step: no learned case, so no then: end
    on_form = cc.flows / "job_apply.yaml"
    on_form.write_text(on_form.read_text().replace("lever_application: continue", "lever_application: continue\n"
                                                   "        jobs_acme_example_review_acme: continue", 1))
    (pages / "jobs_acme_example_review_acme.yaml").write_text(
        "page:\n  id: jobs_acme_example_review_acme\n  identification: {title_matches: '^Review \\| Acme$'}\n"
        "  elements: {}\n")
    assert "the run does not end there" in _lesson_form(cc, name)[1]


def test_studio_new_automation_saves_a_draft_and_refuses_http(cc):
    Approvals(cc.home / "approvals.json").revoke_all()   # nothing approved: no browser block to copy
    s, page, _ = cc.get("/studio")
    assert "action=/studio/new" in page and "No approved app has a browser profile" in page
    cc.post("/studio/new", app="Acme", url="https://acme.example/start")
    assert "browser profile" in _tells(cc)[-1] and not (cc.flows / "studio_acme.yaml").exists()
    _approve_job_apply(cc)
    assert "Runs in Profile" in cc.get("/studio")[1]
    cc.post("/studio/new", app="Acme", url="https://acme.example/start")
    a = next(a for a in list_apps(cc.flows, cc.home) if a.id == "studio_acme")
    assert not a.approved and _log(cc.home, "setting")[-1]["field"] == "studio_new"
    cc.post("/studio/new", app="Plain", url="http://acme.example/")
    assert "https" in _tells(cc)[-1] and not (cc.flows / "studio_plain.yaml").exists()
    assert "Delete" in cc.get("/studio")[1] and "Delete" in cc.get("/approvals")[1]


def _delete(cc, kind, name):
    return cc.post("/apps/delete", kind=kind, name=name, back="/studio")


def test_delete_only_studio_and_check_apps(cc):
    from govaios import studio
    studio.new_automation(cc.flows, "Acme", "https://acme.example", {"application": "chrome", "profile_directory": "P", "account": "a@x.y"})
    (cc.flows / "check_old.yaml").write_text("workflow: {id: check_old, steps: []}")
    ap = Approvals(cc.home / "approvals.json")
    ap.approve_flow("studio_acme", "d")
    for bad in ("job_apply", "himalayas", "web_sandbox", "morning_inbox_briefing", "../job_apply", "studio_acme.yaml", "studio_/../x"):
        _delete(cc, "flow", bad)
    assert (cc.flows / "job_apply.yaml").exists() and (cc.flows / "morning_inbox_briefing.yaml").exists()
    _delete(cc, "flow", "studio_acme")
    _delete(cc, "flow", "check_old")
    assert not (cc.flows / "studio_acme.yaml").exists() and not (cc.flows / "check_old.yaml").exists()
    assert "studio_acme" not in json.loads((cc.home / "approvals.json").read_text())["flows"]   # revoked first
    assert [e["target"] for e in _log(cc.home, "setting") if e.get("field") == "delete"] == ["studio_acme.yaml", "check_old.yaml"]
    assert cc.req("/apps/delete", "POST", body={"kind": "flow", "name": "check_x"})[0] == 403   # no session


def test_delete_app_needs_touch_id_and_shows_on_apps(cc):
    from govaios import studio
    studio.new_automation(cc.flows, "Acme", "https://acme.example", {"application": "chrome", "profile_directory": "P", "account": "a@x.y"})
    app = next(a for a in list_apps(cc.flows, cc.home) if a.id == "studio_acme")
    Approvals(cc.home / "approvals.json").approve_flow(app.id, app.digest)
    assert "name=name value='studio_acme'><input type=hidden name=back value='/apps'>" in cc.get("/apps")[1]
    cc.answers["prove"] = False
    cc.post("/apps/delete", kind="flow", name="studio_acme", back="/apps")
    assert (cc.flows / "studio_acme.yaml").exists() and cc.asked[-1] == "Delete the app studio_acme"
    assert _log(cc.home, "setting")[-1]["decision"] == "deny"
    cc.answers["prove"] = True
    cc.post("/apps/delete", kind="flow", name="studio_acme", back="/apps")
    assert not (cc.flows / "studio_acme.yaml").exists()
    e = _log(cc.home, "setting")[-1]
    assert (e["field"], e["channel"], e["auth"]) == ("delete", "touch_id", "biometric")


def test_delete_symlink_refused(cc, tmp_path):
    (cc.home / "t.yaml").write_text("x")
    (cc.flows / "studio_link.yaml").symlink_to(cc.home / "t.yaml")
    _delete(cc, "flow", "studio_link")
    assert (cc.home / "t.yaml").exists() and (cc.flows / "studio_link.yaml").is_symlink()


def test_delete_draft_page_used_by_approved_flow_refused(cc):
    jobs = _studio_drafts(cc)
    _approve_job_apply(cc)
    pages = cc.flows.parent / "pages"
    cc.post("/studio/compose", app="Acme apply", s1=f"open:{jobs}")   # an unapproved flow binds it too
    _delete(cc, "page", jobs)
    assert (pages / f"{jobs}.yaml").exists() and "used by an app" in _tells(cc)[-1]
    _delete(cc, "page", "google_home")   # bound by job_apply
    assert (pages / "google_home.yaml").exists()
    _delete(cc, "flow", "studio_acme_apply")
    _delete(cc, "page", jobs)
    assert not (pages / f"{jobs}.yaml").exists()


def test_delete_refuses_an_unbound_page_that_is_not_a_draft(cc):
    pages = cc.flows.parent / "pages"
    (pages / "plain.yaml").write_text("page: {id: plain, identification: {title_matches: x}, elements: {}}")
    _delete(cc, "page", "plain")
    assert (pages / "plain.yaml").exists() and "only draft pages" in _tells(cc)[-1]


def test_known_draft_page_keeps_its_header_when_a_lesson_adds_to_it(cc):
    from govaios import lessons, studio
    from govaios.desktop import Node
    pages = cc.flows.parent / "pages"
    t = {"role": "document", "name": "Shop", "children": [{"role": "heading", "name": "Shop"},
                                                         {"role": "link", "name": "Cart"}]}
    pid = studio.write_draft(cc.flows, pages, t, "https://shop.example/home", None, "c.json")
    doc = yaml.safe_load((pages / f"{pid}.yaml").read_text())
    del doc["page"]["elements"]["link_cart"]
    (pages / f"{pid}.yaml").write_text("# Draft from the Web Sandbox capture c.json\n# Start link: https://shop.example/home\n"
                                       + yaml.safe_dump(doc))
    tree = Node("document", "Shop", children=[Node("heading", "Shop"), Node("link", "Cart")])
    name = lessons.save(cc.home, "web_sandbox", None, None, [{"url": "https://shop.example/home", "title": "Shop",
        "tree": tree, "events": [{"kind": "click", "spec": {"role": "link", "name": "Cart"}, "label": "Cart",
                                  "value": "", "secure": False}]}])
    cc.post("/lesson/approve", name=name, p=_lesson_form(cc, name)[0])
    text = (pages / f"{pid}.yaml").read_text()
    assert text.startswith("# Draft from the Web Sandbox capture c.json\n# Start link: https://shop.example/home\n")
    assert "Cart" in text and pid in studio.catalogue(cc.flows, pages)


def test_teach_approve_then_the_next_run_uses_the_learned_page(cc, monkeypatch):
    """End to end: a run teaches an unknown page, the panel approves the lesson with Touch ID, a new run of the same
    flow on that page clicks what was taught, with no new_page card."""
    import test_job_apply_flow as jaf
    import test_teach as tt
    from govaios import engine, terms
    from conftest import ACCT, N
    import itertools
    import types
    clock = itertools.count(0, 30)   # page waits time out at once (jaf.fast_clock); the panel keeps real time
    monkeypatch.setattr(engine, "time", types.SimpleNamespace(sleep=lambda s: None, time=lambda: next(clock),
                                                             monotonic=time.monotonic))
    monkeypatch.setattr(engine, "user_home", lambda: cc.home)
    (cc.home / "apply").mkdir(mode=0o700, exist_ok=True)
    (cc.home / "apply" / "answers.yaml").write_text(json.dumps({"answers": jaf.BANK, "cv_file": "~/" + jaf.CV}))
    (cc.home / jaf.CV).write_bytes(b"%PDF")
    wf = yaml.safe_load((REPO / "flows" / "job_apply.yaml").read_text())
    wf["workflow"]["browser"]["account"] = ACCT
    flow = cc.flows / "job_apply.yaml"
    flow.write_text(yaml.safe_dump(wf))
    terms.record(cc.home, tt.ODD, "allowed", "https://example.invalid/terms", "ok")

    class Desk(tt.TeachDesk):
        def web_root(self, app):
            if self.url == tt.ODD:
                return N("document", "Somewhere else", children=[N("heading", "Before you apply"),
                                                                 N("link", "Continue", handle="l1")])
            return super().web_root(app)

    def run(desk, answers):
        r = engine.Runner(flow, desk, cc.home)
        r.approvals.approve_flow("job_apply", r.digest)
        for o in jaf.DESTS:
            r.approvals.approve_destination("job_apply", o)
        r.run_id, seen = "r1", []
        done = tt.answer_cards(cc.home, lambda c: (lambda a: a(c) if callable(a) else a)(answers.get(c["kind"], "next")),
                               seen)
        try:
            r.run()
        finally:
            done.set()
        return seen

    def approve(card):   # the admin opens What I learned and approves it with Touch ID (auth.prove: True)
        p = _lesson_form(cc, card["label"])[0]
        cc.post("/lesson/approve", name=card["label"], p=p)
        return "approved"
    look = {**tt.LOOK, "title": "Somewhere else"}
    seen = run(Desk([look, {**look, "down": True, "hit": "l1"}]), {"new_page": "teach", "teaching": None, "lesson": approve})
    kinds = [c["kind"] for c in seen if c["kind"] != "teaching"]   # the teaching card may end before it is seen
    assert kinds == ["new_page", "lesson", "stopped", "review"]   # approving kept the run: job 2 ran
    assert _log(cc.home, "lesson")[-1]["outcome"] == "approved"
    learned = yaml.safe_load(flow.read_text())["workflow"]
    assert "https://apply.example.invalid" in learned["destinations"]
    desk = Desk()
    seen = run(desk, {})
    assert ("click", "Continue") in desk.calls and "new_page" not in [c["kind"] for c in seen]
    assert [c["kind"] for c in seen] == ["review", "review"]


def test_nav_is_home_apps_studio_market_audit_approvals(panel):
    nav = re.search(r"<nav class=rail.*?</nav>", panel.get("/")[1], re.S)[0]
    assert re.findall(r">([A-Za-z ]+)</a>", nav) == ["Home", "Apps", "Studio", "Marketplace", "Audit log", "Approvals"]
    assert "<h2>Approved</h2>" not in nav and "<h2>Drafts</h2>" not in nav


def test_apps_page_shows_approved_apps_as_cards(panel):
    body = panel.get("/apps")[1]
    assert body.count("class=appcard") == 1 and "JobLens" in body and "Inbox briefing" not in body
    assert "Himalayas Job Vetting" in body and "Never run" in body
    assert "name=text value='run himalayas job vetting'" in body


def test_apps_card_shows_running_and_queued(panel):
    from test_panel_queue import _busy_with_inbox_queued
    _busy_with_inbox_queued(panel)
    body = panel.get("/apps")[1]
    assert "<a class=go href='/'>Running…</a>" in body and "Queued #1" in body
    assert "action=/unqueue" in body and "name=next value=/apps" in body
    assert "<button aria-label='Take Inbox briefing out of the queue'>✕</button>" in body


def test_app_with_inputs_runs_through_its_input_card(panel):
    from test_panel_queue import _approve
    _approve(panel, "job_apply")
    assert re.search(r"name=text value='/[a-z0-9-]+'", panel.get("/apps")[1])   # "/<slug>", not "run ..."


def test_apps_card_shows_last_started(panel):
    log = AuditLog(panel.home)
    log.append("flow_start", flow="himalayas_job_vetting")
    log.append("request", action="run_start", channel="totp_session", auth="ticket", session="s1")
    log.append("flow_end", flow="himalayas_job_vetting", outcome="done")
    body = panel.get("/apps")[1]
    assert "Last started 20" in body and "Never run" not in body


def test_apps_page_escapes_names(panel):
    p = panel.flows / "himalayas_job_vetting.yaml"
    p.write_text(re.sub(r"(?m)^  app: .*$", "  app: '<b>x</b>'", p.read_text(), count=1))
    from test_panel_queue import _approve
    _approve(panel, "himalayas_job_vetting")
    body = panel.get("/apps")[1]
    assert "&lt;b&gt;x&lt;/b&gt;" in body and "<b>x</b>" not in body


def test_drafts_are_on_approvals(panel):
    body = panel.get("/approvals")[1]
    assert "Waiting for approval" in body and "Inbox briefing" in body and "action=/approve" in body


def test_coding_agents_line_is_on_apps(panel):
    assert "Governed: type /" not in panel.get("/")[1]


def test_home_is_newest_first_with_the_talk_box_on_top(panel):
    P = panel; _open(P); P.say("run mail"); P.say("run joblens")
    body = P.get("/")[1]
    assert body.index("class=cmd") < body.index("class=talk")
    assert body.index("Starting JobLens.") < body.index("I don&#x27;t know that app.")   # newest first


def test_the_live_card_stays_under_the_talk_box(cc):
    _carding(cc)
    for i in range(5):
        cc.say(f"run nothing{i}")
    body = cc.get("/")[1]
    assert body.index("class=cmd") < body.index("/apply/card") < body.index("class=talk")


def test_joblens_jobs_newest_first(cc):
    rid = _carding(cc, "review", "", "A", 2)
    _tasks(cc, rid, [{"n": 1, "title": "One", "status": "done"}, {"n": 2, "title": "Two", "status": "review"}])
    page = cc.get("/")[1]
    assert page.index("/apply/task/2'") < page.index("/apply/task/1'")


# --- Chrome extension endpoints (/ext/*) ---
EXT = "chrome-extension://" + "a" * 32


def _ext(P, path, body=None, token=None, origin=EXT, method=None):
    c = http.client.HTTPConnection("127.0.0.1", P.srv.server_address[1])
    h = {k: v for k, v in (("Origin", origin), ("X-GovAIOS-Token", token)) if v}
    c.request(method or "POST", path, body=json.dumps({} if body is None else body), headers=h)
    r = c.getresponse()
    return r.status, json.loads(r.read() or b"null"), r


def _paired(P):
    # the next step's code: a session code spent just before must not be the one reused (single use)
    s, j, r = _ext(P, "/ext/pair", {"code": code_at(_secret(P), time.time() + 30)})
    assert s == 200 and r.getheader("Content-Type") == "application/json" and r.getheader("X-Content-Type-Options")
    return j["token"]


def _approve_teach(P):
    (P.flows / "teach.yaml").write_text(
        "workflow:\n  id: teach\n  app: Teach\n  name: Teach a page\n  version: 1\n  inputs:\n"
        "    lesson: { label: Lesson, pattern: 'new|[0-9-]{22}-[a-z0-9_]{1,64}\\.json' }\n"
        "  permissions: { allow: [launch_application], max_element_risk: read }\n  steps:\n"
        "    - { id: launch_chrome, action: launch_application }\n")
    a = next(a for a in list_apps(P.flows, P.home) if a.id == "teach")
    Approvals(P.home / "approvals.json").approve_flow(a.id, a.digest)


def test_ext_pair_and_state(panel):
    tok = _paired(panel)
    s, j, _ = _ext(panel, "/ext/state", token=tok)
    assert s == 200 and j["signed_in"] is False and j["recording"] is False and j["lesson"] is None and j["yaml"] == ""
    assert tok not in json.dumps(_log(panel.home))


def test_ext_refuses_web_origin(panel):
    code = code_at(_secret(panel), time.time())
    assert _ext(panel, "/ext/pair", {"code": code}, origin="http://localhost:8100")[0] == 403
    tok = _paired(panel)
    assert _ext(panel, "/ext/state", token=tok, origin="http://localhost:8100")[:2] == (401, {"unpaired": True})


def test_ext_refuses_without_token(panel):
    _paired(panel)
    assert _ext(panel, "/ext/state")[:2] == (401, {"unpaired": True})
    assert _ext(panel, "/ext/state", token="nope")[:2] == (401, {"unpaired": True})


def test_ext_state_is_a_post(panel):
    tok = _paired(panel)   # Chrome sends no Origin on the extension's GETs: a GET would unpair it
    assert _ext(panel, "/ext/state", token=tok, method="GET")[0] == 404
    assert _ext(panel, "/ext/state", token=tok)[0] == 200


def test_ext_screen_lock_is_403_and_keeps_the_pairing(panel, monkeypatch):
    from govaios import auth
    tok = _paired(panel)
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    assert _ext(panel, "/ext/state", token=tok)[0] == 403   # not 401: the extension keeps its token
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    assert _ext(panel, "/ext/state", token=tok)[0] == 200


def test_studio_disconnect_stops_a_live_teach_run(panel):
    _open(panel)
    tok = _paired(panel)
    _approve_teach(panel)
    assert _ext(panel, "/ext/teach", {}, token=tok)[0] == 200
    run = panel.made[-1]
    assert run.started and not run.stops
    assert panel.post("/studio/disconnect")[0] == 303
    assert run.stops and not (panel.home / "extension.json").exists()


def test_ext_event_needs_live_teach_run(panel):
    _open(panel)
    tok = _paired(panel)
    s, j, _ = _ext(panel, "/ext/event", {"kind": "down"}, token=tok)
    assert s == 409 and j["note"]
    assert _ext(panel, "/ext/teach", {"tab_url": "https://x.example/"}, token=tok)[0] == 409   # Teach not approved
    _approve_teach(panel)
    panel.post("/end")
    s, j, _ = _ext(panel, "/ext/teach", {}, token=tok)
    assert s == 409 and "session" in j["note"] and not panel.made   # no run session


def test_ext_teach_starts_the_teach_app(panel):
    _open(panel)
    tok = _paired(panel)
    _approve_teach(panel)
    s, _, _ = _ext(panel, "/ext/teach", {"tab_url": "https://x.example/"}, token=tok)
    assert s == 200 and panel.made[-1].inputs == {"lesson": "new"} and panel.made[-1].started
    assert _ext(panel, "/ext/teach", {}, token=tok)[0] == 409   # a run is live


def test_ext_event_appended_with_run_id(panel):
    _open(panel)
    tok = _paired(panel)
    _approve_teach(panel)
    _ext(panel, "/ext/teach", {}, token=tok)
    s, _, _ = _ext(panel, "/ext/event", {"kind": "down", "x": 3, "y": float("inf"), "name": "n" * 300, "role": "button",
                                       "value": "secret", "evil": 1}, token=tok)
    assert s == 200
    last = json.loads((panel.home / "apply/teach_in.jsonl").read_text().splitlines()[-1])
    assert last["run"] == panel.srv.panel.run_id and last["kind"] == "down" and last["x"] == 3 and len(last["name"]) == 200
    assert set(last) <= {"run", "kind", "x", "y", "name", "role", "tag", "url", "t"} and "y" not in last
    assert _ext(panel, "/ext/event", {"kind": "bogus"}, token=tok)[0] == 400
    assert _ext(panel, "/ext/event", {"kind": "x" * 5000}, token=tok)[0] == 400   # body over 4096


def test_studio_disconnect_ends_open_lesson(panel):
    from govaios import applyfiles
    _paired(panel)
    name = "20261112-101010-123456-teach.json"
    (panel.home / "lessons").mkdir()
    (panel.home / "lessons" / name).write_text("{}")
    applyfiles.write_json(panel.home, applyfiles.TEACH_OPEN, {"lesson": name})
    assert "action=/studio/disconnect" in panel.get("/studio")[1]
    assert panel.post("/studio/disconnect")[0] == 303
    assert not (panel.home / "extension.json").exists() and not (panel.home / applyfiles.TEACH_OPEN).exists()
    assert not (panel.home / "lessons" / name).exists()
    assert _log(panel.home, "extension")[-1]["outcome"] == "disconnected"


def test_ext_state_reads_teach_out_for_the_live_run(panel):
    from govaios import applyfiles
    _open(panel)
    tok = _paired(panel)
    _approve_teach(panel)
    _ext(panel, "/ext/teach", {}, token=tok)
    name = "20261112-101010-123456-teach.json"
    applyfiles.write_json(panel.home, applyfiles.TEACH_OUT, {"run": "stale", "lesson": name, "paused": True, "note": "old", "lines": ["x"]})
    j = _ext(panel, "/ext/state", token=tok)[1]
    assert not j["recording"] and not j["paused"] and j["note"] == "" and j["lines"] == [] and j["lesson"] is None   # another run's file
    applyfiles.write_json(panel.home, applyfiles.TEACH_OUT, {"run": panel.srv.panel.run_id, "lesson": name, "paused": True,
                                                              "note": "n" * 300, "lines": ["click button Save", 5]})
    j = _ext(panel, "/ext/state", token=tok)[1]
    assert j["recording"] and j["paused"] and j["lines"] == ["click button Save"] and j["lesson"] == name and j["note"] == "n" * 200
    applyfiles.write_json(panel.home, applyfiles.TEACH_OUT, {"run": panel.srv.panel.run_id, "lesson": "../x.json"})
    assert _ext(panel, "/ext/state", token=tok)[1]["lesson"] is None
    assert _ext(panel, "/ext/event", {"kind": "down", "x": 10 ** 400, "y": float("nan")}, token=tok)[0] == 200   # no OverflowError
    last = json.loads((panel.home / applyfiles.TEACH_IN).read_text().splitlines()[-1])
    assert "x" not in last and "y" not in last


def test_ext_discard(panel):
    from govaios import applyfiles
    tok = _paired(panel)
    name = "20261112-101010-123456-teach.json"
    (panel.home / "lessons").mkdir()
    (panel.home / "lessons" / name).write_text("{}")
    (panel.home / "x.json").write_text("{}")
    applyfiles.write_json(panel.home, applyfiles.TEACH_OPEN, {"lesson": "../x.json"})
    assert _ext(panel, "/ext/discard", {}, token=tok)[0] == 200
    assert (panel.home / "x.json").exists() and (panel.home / "lessons" / name).exists()   # a bad name deletes nothing
    applyfiles.write_json(panel.home, applyfiles.TEACH_OPEN, {"lesson": name})
    assert _ext(panel, "/ext/discard", {}, token=tok)[0] == 200
    assert not (panel.home / "lessons" / name).exists() and not (panel.home / applyfiles.TEACH_OPEN).exists()


def test_ext_discard_refused_while_teach_is_live(panel):
    from govaios import applyfiles
    _open(panel)
    tok = _paired(panel)
    _approve_teach(panel)
    _ext(panel, "/ext/teach", {}, token=tok)
    name = "20261112-101010-123456-teach.json"
    (panel.home / "lessons").mkdir()
    (panel.home / "lessons" / name).write_text("{}")
    applyfiles.write_json(panel.home, applyfiles.TEACH_OPEN, {"lesson": name})
    s, j, _ = _ext(panel, "/ext/discard", {}, token=tok)
    assert s == 409 and j["note"] == "Press Cancel to end the lesson that is recording."
    assert (panel.home / "lessons" / name).exists()


def _teach_lesson(P):
    """The recorder's open lesson after Done on JobLens (two pages, the last press a submit); returns its name."""
    from govaios import applyfiles, capture, lessons
    from govaios.desktop import Node
    home = Node("document", "JobLens", children=[Node("heading", "Applications"), Node("link", "Discover")])
    disc = Node("document", "JobLens", children=[Node("heading", "Discover"), Node("button", "Review")])

    def click(name, risk="navigate"):
        return {"kind": "click", "spec": {"role": "link" if name == "Discover" else "button", "name": name},
                "label": name, "value": "", "secure": False, "submit": risk != "navigate", "risk": risk, "sure": True}
    name = lessons.new_name("teach_new")
    lessons.write(P.home, name, {"flow": "teach_new", "digest": None, "step": None, "at": "2026-11-12T10:00:00", "new_app": True,
                                 "pages": [{"url": "http://localhost:8100/", "title": "JobLens · Applications",
                                            "tree": capture.tree(home), "events": [click("Discover")]},
                                           {"url": "http://localhost:8100/discover", "title": "JobLens · Discover",
                                            "tree": capture.tree(disc), "events": [click("Review"), click("Approve & promote", "submit")]}]})
    applyfiles.write_json(P.home, applyfiles.TEACH_OPEN, {"lesson": name})
    return name


def _done(P):
    from govaios import applyfiles
    tok = _paired(P)
    assert _ext(P, "/ext/done", {"name": "Approve shortlisted"}, token=tok)[0] == 409   # no lesson open
    name = _teach_lesson(P)
    assert "joblens_applications" in _ext(P, "/ext/state", token=tok)[1]["yaml"]
    s, j, _ = _ext(P, "/ext/done", {"name": "Approve shortlisted"}, token=tok)
    assert s == 200 and j == {"lesson_url": f"/lesson/{name}"} and not (P.home / applyfiles.TEACH_OPEN).exists()
    assert (P.flows / "studio_approve_shortlisted.yaml").exists()
    e = _log(P.home, "lesson")[-1]
    assert (e["outcome"], e["flow"], e["target"]) == ("bound", "studio_approve_shortlisted", name)
    return name


def test_ext_state_lines_agree_with_the_yaml(panel):
    from govaios import lessons
    from govaios.formfill import Bank
    tok = _paired(panel)
    name = _teach_lesson(panel)
    j = _ext(panel, "/ext/state", token=tok)[1]
    want = lessons.preview(lessons.load(panel.home, name), panel.flows.parent / "pages", Bank())[0]
    assert j["lines"] == want and want


def test_ext_done_retry_after_a_failed_bind(panel, monkeypatch):
    from govaios.audit import web
    tok = _paired(panel)
    _teach_lesson(panel)
    real = web.read_bound
    monkeypatch.setattr(web, "read_bound", lambda *a: (_ for _ in ()).throw(ValueError("bad page")))
    assert _ext(panel, "/ext/done", {"name": "Approve shortlisted"}, token=tok)[0] == 409
    assert not (panel.flows / "studio_approve_shortlisted.yaml").exists()   # the Draft is removed: the name is free
    monkeypatch.setattr(web, "read_bound", real)
    assert _ext(panel, "/ext/done", {"name": "Approve shortlisted"}, token=tok)[0] == 200


def test_new_app_lesson_approves_the_draft(panel):
    name = _done(panel)
    panel.post("/lesson/approve", name=name, p=_lesson_form(panel, name)[0])
    text = "Approve the new app Approve shortlisted and what GOV-AIOS learned"
    assert panel.asked.count(text) == 1 and panel.asked[-1] == text
    app = next(a for a in list_apps(panel.flows, panel.home) if a.id == "studio_approve_shortlisted")
    assert app.approved and Approvals(panel.home / "approvals.json").flow_ok(app.id, app.digest)


def test_new_app_lesson_refused_if_draft_edited(panel):
    name = _done(panel)
    p = panel.flows / "studio_approve_shortlisted.yaml"
    p.write_text(p.read_text() + "# edited\n")
    panel.post("/lesson/approve", name=name, p=_lesson_form(panel, name)[0])
    assert "changed since this lesson" in _tells(panel)[-1] and not any("new app" in a for a in panel.asked)
    assert "studio_approve_shortlisted" not in Approvals(panel.home / "approvals.json").snapshot()["flows"]


def test_approvals_sends_a_teach_draft_to_its_lesson(panel):
    name = _done(panel)
    page = panel.get("/approvals")[1]
    assert f"href='/lesson/{name}'>Approve it with what I learned</a>" in page
    assert "name=flow value='studio_approve_shortlisted'><button>Approve" not in page
    panel.post("/lesson/approve", name=name, p=_lesson_form(panel, name)[0])
    assert "studio_approve_shortlisted" in Approvals(panel.home / "approvals.json").snapshot()["flows"]


def test_new_app_rule_needs_never_approved(panel):
    name = _done(panel)
    panel.post("/approve", flow="studio_approve_shortlisted")
    assert Approvals(panel.home / "approvals.json").snapshot()["flows"].get("studio_approve_shortlisted")
    panel.post("/revoke", kind="flow", flow="studio_approve_shortlisted")
    panel.post("/lesson/approve", name=name, p=_lesson_form(panel, name)[0])
    assert "Approve Approve shortlisted first" in _tells(panel)[-1] and not any("new app" in a for a in panel.asked)
    assert "studio_approve_shortlisted" not in Approvals(panel.home / "approvals.json").snapshot()["flows"]


def test_ext_done_refused_while_teach_is_live(panel):
    _open(panel)
    tok = _paired(panel)
    _approve_teach(panel)
    _ext(panel, "/ext/teach", {}, token=tok)
    _teach_lesson(panel)
    s, j, _ = _ext(panel, "/ext/done", {"name": "Approve shortlisted"}, token=tok)
    assert s == 409 and j["note"] and not (panel.flows / "studio_approve_shortlisted.yaml").exists()


def test_new_app_lesson_never_re_approves_after_revoke(panel):
    name = _done(panel)
    pages = panel.flows.parent / "pages"
    before = {f: f.read_bytes() for f in (*panel.flows.glob("*.yaml"), *pages.glob("*.yaml"))}
    panel.post("/lesson/approve", name=name, p=_lesson_form(panel, name)[0])
    assert Approvals(panel.home / "approvals.json").snapshot()["flows"].get("studio_approve_shortlisted")
    panel.post("/revoke", kind="flow", flow="studio_approve_shortlisted")
    for f in (*panel.flows.glob("*.yaml"), *pages.glob("*.yaml")):   # the app's bytes as they were when bound
        f.unlink() if f not in before else f.write_bytes(before[f])
    n = len(panel.asked)
    panel.post("/lesson/approve", name=name, p=_lesson_form(panel, name)[0])
    assert "Approve Approve shortlisted first" in _tells(panel)[-1] and len(panel.asked) == n
    assert "studio_approve_shortlisted" not in Approvals(panel.home / "approvals.json").snapshot()["flows"]


def test_press_line_words():
    from govaios.panel import lesson as pl
    prop = {"pages": [{"id": "p", "steps": [{"kind": "click", "label": "Approve & promote", "target": "p.a",
                                              "keep": True, "press": True}], "added": [], "new": True}], "bank": []}
    html = pl.page("n", {"pages": [{"title": "T", "url": "http://localhost:8100/"}]}, prop, set(), {}, "")
    assert "Press: Approve &amp; promote (asks Touch ID before the first run's press)" in html
