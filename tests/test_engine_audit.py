import json
import os
import signal
import shutil

import pytest

from govaios import engine
from govaios.audit.verify import verify
from govaios.desktop import Node
from govaios.engine import REPO, Runner, Stop

ACCT = "test@example.invalid"


def N(role, name="", **kw):
    return Node(role, name, **kw)


def google_home():
    return N("document", "Google", children=[
        N("link", "Gmail"), N("popup_button", f"Google Account: Tester ({ACCT})")])


def matches():
    card = N("article", children=[N("link", "SECRET-TITLE"), N("link", "SECRET-CO Verified"),
                                  N("link", "View job"), N("time", children=[N("text", "2d ago")])])
    return N("document", "Your matches | Himalayas", children=[
        N("heading", "Your matches"), N("banner"),
        N("group", dom_id="job-search-results", children=[card])])


def detail():
    return N("document", "SECRET-CO hiring SECRET-TITLE | Himalayas", children=[
        N("main", children=[N("heading", "SECRET-TITLE"), N("link", "SECRET-CO"),
                            N("article", children=[N("text", "SECRET-DESCRIPTION")])]),
        N("heading", "Apply now")])


class FakeDesktop:
    """Canned trees; records instead of sending input. Never touches the OS."""

    def __init__(self, answers):
        self.answers, self.calls, self.url, self.typed = list(answers), [], "about:blank", ""
        FakeDesktop.current = self

    def activate(self, app):
        self.calls.append("activate")

    def focused_window_id(self, app):
        return "win1"

    def pin_window(self, token):
        self.calls.append(("pin", token))

    def launch_application(self, app, profile=None):
        self.calls.append("launch")

    def press(self, key):
        self.calls.append(key)
        if key == "enter":
            self.url = self.typed
        elif key == "browser_back":
            self.url = "https://himalayas.app/jobs/matches"

    def type_text(self, t):
        self.typed = t

    def scroll_into_view(self, node):
        self.calls.append("scroll")

    def click(self, node):
        self.calls.append("click")
        self.url = "https://himalayas.app/jobs/secret-title"

    def current_url(self, app):
        return self.url + ("?utm=x" if "himalayas" in self.url else "")

    def window_title(self, app):
        return "x"

    def web_root(self, app):
        if "google.com" in self.url:
            return google_home()
        return detail() if "/jobs/secret" in self.url else matches()


@pytest.fixture(autouse=True)
def nosleep(monkeypatch):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def fake_auth(monkeypatch):
    """Scripted answers (from the FakeDesktop) stand in for Touch ID; never real prompts."""
    def approve(q, reason, home, channel="touch_id"):
        d = FakeDesktop.current
        d.calls.append("ask")
        ok = d.answers.pop(0) if d.answers else False
        return ok, "biometric" if ok else "failed"
    monkeypatch.setattr(engine.auth, "approve", approve)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)


def run(tmp_path, answers, desk=FakeDesktop, directory=None, preapprove=False, deliver=None, ticket=None, mint=False):
    src = tmp_path / "src"
    shutil.copytree(REPO / "flows", src / "flows")
    shutil.copytree(REPO / "pages", src / "pages")
    f = src / "flows" / "himalayas_job_vetting.yaml"
    t = f.read_text().replace("count: 5", "count: 1")
    t = t.replace("rupak.kumar.ambasta02@gmail.com", ACCT)
    t = t.replace("  deliver: { to: joblens, from: jd_selected, source: Himalayas }\n", "")   # start without deliver
    if directory:
        t = t.replace("directory: jd_selected", f"directory: {directory}")
    if deliver:
        t = t.replace("write_file, report]", "write_file, report, deliver]")
        t = t.replace("  steps:\n", f"  deliver: {deliver}\n  steps:\n", 1)
    f.write_text(t)
    r = Runner(f, desk(answers), tmp_path, ticket=ticket)
    if preapprove:
        r.approvals.approve_flow(r.flow["id"], r.digest)
    if mint:   # a panel would mint this for the approved flow
        from govaios.panel import tickets
        r.ticket = tickets.create(tmp_path, r.flow["id"], r.digest)
    try:
        r.run()
        err = None
    except Stop as e:
        err = e
    entries = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    return r, entries, err


def test_run_writes_start_and_end(tmp_path):
    r, e, err = run(tmp_path, [True] * 10)
    assert err is None
    kinds = [x["kind"] for x in e]
    assert kinds[0] == "flow_start" and kinds[1] == "flow_approval" and kinds[-1] == "flow_end"
    assert verify(r.audit.path, r.audit.pub_path).ok


def test_click_target_is_element_ref(tmp_path):
    _, e, _ = run(tmp_path, [True] * 10)
    assert any(x["kind"] == "request" and x.get("target") == "himalayas_matches.job_cards[1].title" for x in e)
    assert any(x["kind"] == "action" and x["action"] == "click" and x["outcome"] == "done" for x in e)


def test_no_content_in_audit(tmp_path):
    run(tmp_path, [True] * 10)
    log = (tmp_path / "audit.jsonl").read_text()
    low = log.lower()
    assert "secret-description" not in low and "secret-co" not in low and "secret_" not in low
    assert ACCT not in log and "?utm" not in log   # bare "utm" can occur in a base64 signature


def test_denied_flow_approval_logged(tmp_path):
    r, e, err = run(tmp_path, [False])
    assert isinstance(err, Stop)
    assert [x["kind"] for x in e][-2:] == ["flow_approval", "stop"]
    assert e[-2]["decision"] == "deny"
    assert verify(r.audit.path, r.audit.pub_path).ok


def test_write_json_under_home(tmp_path):
    before = set(REPO.glob("*"))
    run(tmp_path, [True] * 10)
    assert len(list((tmp_path / "jd_selected").glob("*.json"))) == 1
    assert set(REPO.glob("*")) == before


def test_destination_url_redacted(tmp_path):
    _, e, _ = run(tmp_path, [True] * 10)
    req = [x for x in e if x["kind"] == "request" and x["step"] == "open_matches"]
    assert req and req[0]["destination"] == "https://himalayas.app/jobs/matches"


class BlankUrl(FakeDesktop):
    def current_url(self, app):
        return ""


def test_blank_url_denied(tmp_path):
    r, e, err = run(tmp_path, [True] * 10, BlankUrl)
    assert isinstance(err, Stop)
    assert [x["kind"] for x in e][-2:] == ["request", "stop"]
    assert e[-2]["decision"] == "deny" and e[-2]["reason"] == "no url"
    assert verify(r.audit.path, r.audit.pub_path).ok


@pytest.mark.parametrize("d", ["../../x", "/tmp/govaios-x"])
def test_write_json_outside_home_stops(tmp_path, d):
    home = tmp_path / "h"
    home.mkdir()
    _, e, err = run(home, [True] * 10, directory=d)
    assert isinstance(err, Stop) and e[-1]["kind"] == "stop"
    assert not (tmp_path / "x").exists() and not [p for p in home.glob("**/*.json") if p.name != "approvals.json"]


class LoggedOut(FakeDesktop):
    def web_root(self, app):
        if "himalayas" in self.url:
            return N("document", "Your matches | Himalayas",
                     children=[N("banner", children=[N("link", "Log in")])])
        return super().web_root(app)


def test_resume_denied_is_audited(tmp_path):
    r, e, err = run(tmp_path, [True, True, True, False], LoggedOut)
    assert isinstance(err, Stop)
    req = [x for x in e if x["kind"] == "request" and x["action"] == "resume"]
    assert len(req) == 1 and req[0]["decision"] == "deny" and req[0]["approver"] == "admin"
    assert req[0]["channel"] == "touch_id" and req[0]["auth"] == "failed" and e[-1]["kind"] == "stop"
    assert verify(r.audit.path, r.audit.pub_path).ok


def test_page_edit_after_construction_cannot_diverge(tmp_path):
    src = tmp_path / "src"
    shutil.copytree(REPO / "flows", src / "flows")
    shutil.copytree(REPO / "pages", src / "pages")
    r = Runner(src / "flows" / "himalayas_job_vetting.yaml", FakeDesktop([]), tmp_path)
    (src / "pages" / "google_home.yaml").write_text("# edited\n")
    from govaios.approvals import flow_hash
    assert r.digest != flow_hash(r.flow_path, r.pages_dir)


def test_report_goes_to_file_not_stdout(tmp_path, capsys):
    r, e, err = run(tmp_path, [True] * 10)
    assert err is None
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err and "report: 1 items -> " in out.out
    rep = list((tmp_path / "reports").glob("himalayas_job_vetting-*.txt"))
    assert len(rep) == 1 and "SECRET-TITLE" in rep[0].read_text()
    assert rep[0].stat().st_mode & 0o777 == 0o600
    assert any(x["kind"] == "request" and x["action"] == "report" and x["decision"] == "allow" for x in e)
    assert any(x["kind"] == "action" and x["action"] == "report" and x["outcome"] == "done" for x in e)


def test_executor_defaults_to_dev(tmp_path):
    _, e, _ = run(tmp_path, [True] * 10)
    assert {x["executor"] for x in e} == {"gov_runner_dev"}


def test_window_pinned_after_account_verified(tmp_path):
    r, _, err = run(tmp_path, [True] * 10)
    assert err is None and ("pin", "win1") in r.d.calls
    assert r.d.calls.index(("pin", "win1")) < r.d.calls.index("enter", r.d.calls.index("enter") + 1)


def test_app_reactivated_after_every_dialog_once_launched(tmp_path):
    r, _, _ = run(tmp_path, [True] * 10)
    c = r.d.calls
    first = c.index("ask")                       # flow approval, before launch: nothing to activate
    assert c[first + 1] != "activate"
    later = [i for i, x in enumerate(c) if x == "ask" and i > c.index("launch")]
    assert later and all(c[i + 1] == "activate" for i in later)


def test_extract_gate_uses_current_url(tmp_path):
    _, e, _ = run(tmp_path, [True] * 10)
    req = [x for x in e if x["kind"] == "request" and x["action"] == "extract_visible_text"]
    assert req and req[0]["destination"] == "https://himalayas.app/jobs/secret-title"


class ExtractBlank(FakeDesktop):
    def current_url(self, app):
        return "" if "/jobs/secret" in self.url else super().current_url(app)


def test_extract_blank_url_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.Runner, "do_click", lambda self, s: setattr(self.d, "url", "https://himalayas.app/jobs/secret-title"))
    _, e, err = run(tmp_path, [True] * 10, ExtractBlank)
    assert isinstance(err, Stop) and e[-2]["action"] == "extract_visible_text" and e[-2]["reason"] == "no url"


def test_click_outside_item_requires_identified_page(tmp_path, monkeypatch):
    clock = iter(range(0, 10**6, 5))
    monkeypatch.setattr(engine.time, "time", lambda: next(clock))
    r, e, err = run(tmp_path, [True] * 10)
    r.d.url, n = "https://example.invalid/", len(r.d.calls)   # matches() tree, not google_home
    with pytest.raises(Stop, match="not on google_home"):
        r.do_click({"id": "x", "action": "click", "target": "google_home.gmail_link"})
    assert "click" not in r.d.calls[n:]


def test_flow_parsed_from_hashed_bytes(tmp_path, monkeypatch):
    src = tmp_path / "src"
    shutil.copytree(REPO / "flows", src / "flows")
    shutil.copytree(REPO / "pages", src / "pages")
    f = src / "flows" / "himalayas_job_vetting.yaml"
    real = type(f).read_bytes
    seen = []

    def swapped(self, *a, **k):   # first read (the hashed one) is real; any later read sees the swap
        if self == f and seen:
            return b"workflow: {}"
        seen.append(self) if self == f else None
        return real(self, *a, **k)

    monkeypatch.setattr(type(f), "read_bytes", swapped)
    r = Runner(f, FakeDesktop([]), tmp_path)   # a second read of the flow would see the swapped text
    assert r.flow["id"] == "himalayas_job_vetting"


@pytest.mark.parametrize("bad", ["../x", "a/b", "Upper", ""])
def test_invalid_flow_id_refused(tmp_path, bad):
    src = tmp_path / "src"
    shutil.copytree(REPO / "flows", src / "flows")
    shutil.copytree(REPO / "pages", src / "pages")
    f = src / "flows" / "himalayas_job_vetting.yaml"
    f.write_text(f.read_text().replace("id: himalayas_job_vetting", f"id: '{bad}'", 1))
    with pytest.raises(Stop, match="invalid flow id"):
        Runner(f, FakeDesktop([]), tmp_path)


def test_revoked_flow_stops_at_next_gate(tmp_path):
    from govaios.approvals import Approvals

    class Revoker(FakeDesktop):
        def click(self, node):
            super().click(node)
            Approvals(tmp_path / "approvals.json").revoke_flow("himalayas_job_vetting")

    r, entries, err = run(tmp_path, [True] * 10, desk=Revoker)
    assert isinstance(err, Stop)
    assert entries[-1]["kind"] == "stop" and entries[-1]["reason"] == "revoked"
    assert r.d.calls.count("click") == 1


def test_approved_flow_start_needs_proof(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (False, "failed"))
    r, e, err = run(tmp_path, [True] * 10, preapprove=True)
    assert isinstance(err, Stop) and "launch" not in r.d.calls and "ask" not in r.d.calls
    req = [x for x in e if x.get("action") == "run_start"]
    assert len(req) == 1 and req[0]["decision"] == "deny" and req[0]["auth"] == "failed"
    assert req[0]["approver"] == "admin" and req[0]["channel"] == "touch_id"


def test_unapproved_flow_one_prompt(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("prove must not run")
    monkeypatch.setattr(engine.auth, "prove", boom)
    _, e, err = run(tmp_path, [True] * 10)
    fa = [x for x in e if x["kind"] == "flow_approval"]
    assert err is None and fa[0]["auth"] == "biometric" and fa[0]["channel"] == "touch_id"
    assert not [x for x in e if x.get("action") == "run_start"]


def test_first_contact_records_auth(tmp_path):
    _, e, _ = run(tmp_path, [True] * 10)
    asks = [x for x in e if x["kind"] == "request" and x["approver"] == "admin"]
    assert asks and all(x["channel"] == "touch_id" and x["auth"] == "biometric" for x in asks)
    assert all(x["auth"] is None for x in e if x["kind"] == "request" and x["approver"] == "policy")


def test_busy_deny_names_busy_not_content(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.auth, "approve", lambda *a, **k: (False, "busy"))
    _, e, err = run(tmp_path, [])
    assert isinstance(err, Stop) and "busy" in str(err) and e[-2]["auth"] == "busy"


def test_lock_mid_run_stops(tmp_path, monkeypatch):
    n = []
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: bool(n.append(1)) or len(n) > 1)
    r, e, err = run(tmp_path, [True] * 10)
    assert isinstance(err, Stop) and e[-1]["reason"] == "screen_locked"
    assert [x["action"] for x in e if x["kind"] == "action"] == ["launch_application"]


class StopOnLaunch(FakeDesktop):
    def launch_application(self, app, profile=None):
        raise Stop("start Chrome, then run the flow again")


def test_stop_from_launch_is_audited_with_reason(tmp_path):
    _, e, err = run(tmp_path, [True] * 10, StopOnLaunch)
    assert isinstance(err, Stop)
    assert e[-1]["kind"] == "stop" and e[-1]["reason"] == "start Chrome, then run the flow again"


class TermOnClick(FakeDesktop):
    def click(self, node):
        os.kill(os.getpid(), signal.SIGTERM)   # the guard's emergency stop, aimed at this run


def test_sigterm_stops_run(tmp_path):
    before = signal.getsignal(signal.SIGTERM)
    r, e, err = run(tmp_path, [True] * 10, TermOnClick)
    assert isinstance(err, Stop) and str(err) == "emergency stop"
    assert e[-1]["kind"] == "stop" and e[-1]["reason"] == "emergency stop"
    assert signal.getsignal(signal.SIGTERM) is before
    assert verify(r.audit.path, r.audit.pub_path).ok


def test_sigterm_during_touch_id_records_emergency_stop(tmp_path, monkeypatch):
    """The real auth path: SIGTERM lands while Touch ID waits; the run's last entry is the emergency stop."""
    monkeypatch.undo()   # drop fake_auth: the real prove() and LAContext wait run
    a = engine.auth

    class Ctx:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def setTouchIDAuthenticationAllowableReuseDuration_(self, v):
            pass

        def setLocalizedFallbackTitle_(self, v):
            pass

        def canEvaluatePolicy_error_(self, p, _):
            return True, None

        def evaluatePolicy_localizedReason_reply_(self, p, reason, block):
            os.kill(os.getpid(), signal.SIGTERM)   # the guard's stop arrives while the prompt is up

        def invalidate(self):
            pass
    monkeypatch.setattr(a.LA, "LAContext", Ctx)
    monkeypatch.setattr(a, "_cg_session_dict", lambda: {a.Quartz.kCGSessionOnConsoleKey: True})
    monkeypatch.setattr(engine, "auth", a)
    r, e, err = run(tmp_path, [], preapprove=True)
    assert isinstance(err, Stop) and str(err) == "emergency stop"
    assert e[-1]["kind"] == "stop" and e[-1]["reason"] == "emergency stop"


@pytest.mark.parametrize("at", ["launch_application", "click"])
def test_stopped_file_mid_run_stops_without_signal(tmp_path, at):
    """Row 28 / I-1: STOPPED written (no SIGTERM, e.g. the guard died after writing it) stops the run."""
    class StopsOn(FakeDesktop):
        pass

    def write_stopped(self, *a, **k):
        (tmp_path / "STOPPED").touch()
        return getattr(FakeDesktop, at)(self, *a, **k)
    setattr(StopsOn, at, write_stopped)
    r, e, err = run(tmp_path, [True] * 10, StopsOn)
    assert isinstance(err, Stop) and str(err) == "emergency stop"
    assert e[-1]["kind"] == "stop" and e[-1]["reason"] == "emergency stop"
    acts = [x for x in e if x["kind"] in ("action", "request")]
    assert acts[-1]["kind"] == "action" and acts[-1]["action"] == at   # nothing gated or done after it


def test_destination_remembered_only_after_audit(tmp_path, monkeypatch):
    """M-14: approve_destination happens after the request entry is on record."""
    from govaios.audit.log import AuditLog
    real = AuditLog.append

    def boom(self, kind, **f):
        if kind == "request" and f.get("approver") == "admin" and f.get("destination"):
            raise OSError("disk full")
        return real(self, kind, **f)
    monkeypatch.setattr(AuditLog, "append", boom)
    seen = []
    real_init = Runner.__init__
    monkeypatch.setattr(Runner, "__init__", lambda self, *a, **k: (real_init(self, *a, **k), seen.append(self))[0])
    with pytest.raises(OSError):
        run(tmp_path, [True] * 10, preapprove=True)
    assert seen[0].approvals.snapshot()["destinations"] == {}


def test_resume_reason_names_unknown_page(tmp_path, monkeypatch):
    """M-19: no "resume None" in the prompt reason."""
    reasons = []
    monkeypatch.setattr(engine.auth, "approve", lambda q, reason, home, channel="touch_id": (reasons.append(reason), (False, "failed"))[1])
    r, e, err = run(tmp_path, [], preapprove=True)
    r.ctx, r.step = {}, "x"
    monkeypatch.setattr(r, "wait_for_page", lambda c, t: (None, None))
    with pytest.raises(Stop):
        r.do_classify_page({"on_match": {"a": "continue", "unknown": "stop_and_request_user"}})
    assert reasons[-1].endswith("resume unknown page")


GOOD_DELIVER = "{ to: joblens, from: jd_selected, source: Himalayas }"


def test_write_json_name_has_url_hash(tmp_path):
    import re
    r = Runner.__new__(Runner)
    r.ctx = {"record": {"title": "Same Title", "url": "https://a.example/1"}, "item": {}}
    r.flow = {"id": "x", "version": 1}
    r.home = tmp_path
    r._act = lambda name, fn, *a, target=None: fn(*a)
    r.gate = lambda *a, **k: None
    for u in ("https://a.example/1", "https://a.example/2"):
        r.ctx["record"]["url"] = u
        r.do_write_json({"directory": "out"})
    names = [p.name for p in (tmp_path / "out").glob("*.json")]
    assert len(names) == 2 and all(re.fullmatch(r"\d{8}-[a-z0-9-]+-[0-9a-f]{8}\.json", n) for n in names)


def test_bad_deliver_block_stops_at_load(tmp_path):
    with pytest.raises(Stop, match="^bad deliver block"):
        run(tmp_path, [], deliver="{ to: other, from: jd_selected, source: Himalayas }")


def test_approval_dialog_names_delivery(tmp_path, monkeypatch):
    qs = []
    real = engine.auth.approve
    monkeypatch.setattr(engine.auth, "approve", lambda q, *a, **k: (qs.append(q), real(q, *a, **k))[1])
    run(tmp_path, [True] * 10, deliver=GOOD_DELIVER)
    assert "delivers to: joblens (local). Approve this flow?" in qs[0]
    qs.clear()
    (tmp_path / "b").mkdir()
    run(tmp_path / "b", [True] * 10)
    assert "delivers" not in qs[0]


def test_flow_ends_by_closing_its_window(tmp_path):
    r, e, err = run(tmp_path, [True] * 10)
    assert err is None and r.d.calls[-1] == "close_window"
    req = [x for x in e if x["kind"] == "request" and x.get("action") == "close_window"]
    assert req and req[0]["decision"] == "allow" and e[-1]["kind"] == "flow_end"


def _no_prompts(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("no prompt for a panel run")
    monkeypatch.setattr(engine.auth, "prove", boom)
    monkeypatch.setattr(engine.auth, "approve", boom)


def test_ticket_run_skips_touch_id(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Touch ID")))
    r, e, err = run(tmp_path, [True] * 10, preapprove=True, mint=True)
    assert err is None
    req = [x for x in e if x.get("action") == "run_start"]
    assert len(req) == 1 and req[0]["decision"] == "allow" and req[0]["approver"] == "admin"
    assert req[0]["channel"] == "totp_session" and req[0]["auth"] == "ticket"


def test_bad_ticket_stops_without_prompt(tmp_path, monkeypatch):
    _no_prompts(monkeypatch)
    r, e, err = run(tmp_path, [], preapprove=True, ticket="0" * 64)
    assert isinstance(err, Stop) and str(err) == "run ticket not valid" and "launch" not in r.d.calls


def test_ticket_for_unapproved_flow_stops(tmp_path, monkeypatch):
    _no_prompts(monkeypatch)
    r, e, err = run(tmp_path, [], ticket="0" * 64)
    assert isinstance(err, Stop) and str(err) == "run ticket not valid"


def test_terminal_run_still_proves(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (calls.append(1), (True, "biometric"))[1])
    run(tmp_path, [True] * 10, preapprove=True)
    assert calls == [1]


def test_approval_question_unchanged(tmp_path, monkeypatch):
    qs = []
    real = engine.auth.approve
    monkeypatch.setattr(engine.auth, "approve", lambda q, *a, **k: (qs.append(q), real(q, *a, **k))[1])
    r, _, _ = run(tmp_path, [True] * 10, deliver=GOOD_DELIVER)
    f = r.flow
    want = (f"First run of flow '{f['id']}' (v{f['version']}). It may: {', '.join(f['permissions']['allow'])}; "
            f"max element risk {f['permissions']['max_element_risk']}; destinations "
            f"{', '.join(f['destinations'])}; delivers to: joblens (local). Approve this flow?")
    assert qs[0] == want == engine.approval_question(f, r.deliver)
