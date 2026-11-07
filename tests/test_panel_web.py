import base64
import http.client
import json
import re
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

    def __init__(self, flow_path, ticket):
        if self.gate:
            self.entered.set()
            self.gate.wait(5)
        self.flow_path, self.ticket = flow_path, ticket
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


def _fake_admin(home, ms):
    """The Mac-password step without root: what ROOT_SCRIPT does, as this user."""
    def run(action, digest):
        import hashlib
        dst = ms / "managed-settings.json"
        if action == "remove":
            dst.unlink(missing_ok=True)
            return 0
        data = (home / "executors" / "managed-settings.json").read_bytes()
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
    from govaios.panel import settings
    settings.set_name(home, "Rupak")
    made = []
    launcher = type("L", (FakeLaunch,), {"made": made})
    admin_calls, admin_answer = [], [_fake_admin(home, tmp_path / "ClaudeCode")]
    spoken = []
    mono, wall = [0.0], [0.0]   # offsets added to the session's monotonic clock and the browser-session clock
    srv = make_server(home, flows_dir=flows, launcher=launcher, speak=spoken.append,
                            now=lambda: time.time() + wall[0], session=Session(lambda: time.monotonic() + mono[0]), tick_s=None,
                            chrome_state=tmp_path / "Local State", managed=tmp_path / "ClaudeCode" / "managed-settings.json",
                            admin=lambda a, d: (admin_calls.append((a, d)), admin_answer[0](a, d))[1])
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
    P.admin_calls, P.admin_answer, P.tmp = admin_calls, admin_answer, tmp_path
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
    for path, link in (("/", "href='/' aria-current=page>Talk"), ("/audit", "href='/audit' aria-current=page>Audit log"),
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
    assert "Morning Gmail Briefing" in body and "Sync Himalayas to JobLens" in body
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
    from govaios import claudecode
    monkeypatch.setattr(claudecode, "root_owned", lambda p: p.exists())   # the fake step cannot chown to root
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
    cc.admin_answer[0], real = (lambda a, d: 2), cc.admin_answer[0]
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
               decision="deny", reason="not allowed")
    assert "Claude Code<span class=m>Governed" in cc.get("/")[1]
    idx = cc.get("/audit")[1]
    assert "Coding agents" in idx and "href='/audit/app/claude_code'" in idx
    assert re.search(r"<td>Governed</td><td>2</td><td>1</td>", idx)
    page = cc.get("/audit/app/claude_code")[1]
    assert page.index("make &lt;b&gt;") < page.index("git status") and "<b>" not in page.split("</h1>", 1)[1]
