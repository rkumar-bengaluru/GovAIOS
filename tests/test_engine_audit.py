import json
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

    def ask_admin(self, q, timeout_s=60):
        self.calls.append("ask")
        return self.answers.pop(0) if self.answers else False

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


def run(tmp_path, answers, desk=FakeDesktop, directory=None):
    src = tmp_path / "src"
    shutil.copytree(REPO / "flows", src / "flows")
    shutil.copytree(REPO / "pages", src / "pages")
    f = src / "flows" / "himalayas_job_vetting.yaml"
    t = f.read_text().replace("count: 5", "count: 1")
    t = t.replace("rupak.kumar.ambasta02@gmail.com", ACCT)
    if directory:
        t = t.replace("directory: jd_selected", f"directory: {directory}")
    f.write_text(t)
    r = Runner(f, desk(answers), tmp_path)
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
    assert req[0]["channel"] == "desktop_dialog" and e[-1]["kind"] == "stop"
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
    real = type(f).read_text
    monkeypatch.setattr(type(f), "read_text", lambda self, *a, **k: "workflow: {}" if self == f else real(self, *a, **k))
    r = Runner(f, FakeDesktop([]), tmp_path)   # a second read of the flow would see the swapped text
    assert r.flow["id"] == "himalayas_job_vetting"
