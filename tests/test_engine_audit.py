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
        return self.answers.pop(0) if self.answers else False

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


def run(tmp_path, answers):
    src = tmp_path / "src"
    shutil.copytree(REPO / "flows", src / "flows")
    shutil.copytree(REPO / "pages", src / "pages")
    f = src / "flows" / "himalayas_job_vetting.yaml"
    t = f.read_text().replace("count: 5", "count: 1")
    t = t.replace("rupak.kumar.ambasta02@gmail.com", ACCT)
    f.write_text(t)
    r = Runner(f, FakeDesktop(answers), tmp_path)
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
    assert "SECRET" not in log and ACCT not in log and "utm" not in log


def test_denied_flow_approval_logged(tmp_path):
    _, e, err = run(tmp_path, [False])
    assert isinstance(err, Stop)
    assert [x["kind"] for x in e][-2:] == ["flow_approval", "stop"]
    assert e[-2]["decision"] == "deny"


def test_write_json_under_home(tmp_path):
    before = set(REPO.glob("*"))
    run(tmp_path, [True] * 10)
    assert len(list((tmp_path / "jd_selected").glob("*.json"))) == 1
    assert set(REPO.glob("*")) == before


def test_destination_url_redacted(tmp_path):
    _, e, _ = run(tmp_path, [True] * 10)
    req = [x for x in e if x["kind"] == "request" and x["step"] == "open_matches"]
    assert req and req[0]["destination"] == "https://himalayas.app/jobs/matches"
