"""web_sandbox flow: open the site the admin names (Touch ID on first contact), capture the pages they choose; read only."""
import json
import threading
import time

import pytest
import yaml

from govaios import applyfiles, engine, terms
from govaios.approvals import pages_used
from govaios.engine import REPO, Runner
from conftest import ACCT, FakeDesktop, N, google_home

FLOW = REPO / "flows" / "web_sandbox.yaml"
SITE = "https://shop.example.com/catalog?x=1"


class SiteDesk(FakeDesktop):
    def __init__(self, pages=None):
        super().__init__([])
        self.pages = pages or {}   # after each Capture, the admin has browsed to the next url

    def current_url(self, app):
        return self.url

    def press(self, key):
        self.calls.append(key)
        if key == "enter":
            self.url = self.typed

    def click(self, node):
        raise AssertionError("the sandbox never clicks")

    def type_into(self, node, text):
        raise AssertionError("the sandbox never types into a page")

    def web_root(self, app):
        if "google.com" in self.url:
            return google_home()
        return N("document", f"Page at {self.url}", children=[N("heading", "Catalog"), N("text_field", "Search"),
                                                              N("button", "Go"), N("link", "Next")])


def run_sandbox(tmp_path, desk, choices, monkeypatch, site=SITE, run_id="r1", first_contact=True):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))   # the start proof
    asked = []
    monkeypatch.setattr(engine.auth, "approve", lambda q, r, h, **k: (asked.append(q), (first_contact.pop(0) if isinstance(first_contact, list) else first_contact, "biometric"))[1])
    wf = yaml.safe_load(FLOW.read_text())
    wf["workflow"]["browser"]["account"] = ACCT
    src = tmp_path / "src"
    (src / "flows").mkdir(parents=True)
    (src / "pages").mkdir()
    (src / "flows" / "web_sandbox.yaml").write_text(yaml.safe_dump(wf))
    for p in (REPO / "pages").glob("*.yaml"):
        (src / "pages" / p.name).write_bytes(p.read_bytes())
    r = Runner(src / "flows" / "web_sandbox.yaml", desk, tmp_path, inputs={"site": site})
    r.approvals.approve_flow(r.flow["id"], r.digest)
    r.approvals.approve_destination(r.flow["id"], "https://www.google.com")
    r.run_id = run_id
    done, it = threading.Event(), iter(choices)

    def answer():
        while not done.is_set():
            ask = applyfiles.read_json(tmp_path, applyfiles.ASK)
            if ask and applyfiles.read_json(tmp_path, applyfiles.REPLY) is None:
                c = next(it)
                if c == "capture" and desk.pages:
                    desk.url = desk.pages.pop(0)
                applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": ask["run"], "card": c})
                while applyfiles.read_json(tmp_path, applyfiles.ASK) == ask and not done.is_set():
                    time.sleep(0.002)
            time.sleep(0.002)
    threading.Thread(target=answer, daemon=True).start()
    err = None
    try:
        r.run()
    except engine.Stop as e:
        err = e
    finally:
        done.set()
    e = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    return e, err, asked


def test_flow_is_read_only_with_a_site_input():
    wf = yaml.safe_load(FLOW.read_text())["workflow"]
    assert wf["app"] == "Web Sandbox" and wf["permissions"]["max_element_risk"] == "read"
    assert set(wf["permissions"]["allow"]) == {"launch_application", "navigate", "read_page", "ask_admin", "write_draft", "teach"}
    assert wf["destinations"] == ["https://www.google.com"] and wf["destination_inputs"] == ["site"]
    assert pages_used(wf) == {"google_home"}


def test_captures_each_page_the_admin_chooses(tmp_path, monkeypatch):
    d = SiteDesk(pages=[SITE, "https://shop.example.com/item/7", "https://login.other.example/x"])
    e, err, asked = run_sandbox(tmp_path, d, ["capture", "capture", "capture", "done"], monkeypatch)
    assert err is None and e[-1]["kind"] == "flow_end"
    assert len(asked) == 1 and "https://shop.example.com for the first time" in asked[0]   # Touch ID, once
    pages = applyfiles.read_json(tmp_path, applyfiles.SANDBOX)["pages"]
    assert [(p["url"], p["fields"], p["buttons"], p["links"]) for p in pages[:2]] == [
        ("https://shop.example.com/catalog", 1, 1, 1), ("https://shop.example.com/item/7", 1, 1, 1)]
    assert pages[2]["file"] is None and pages[2]["note"] == "another site: not captured"
    files = sorted((tmp_path / "captures").iterdir())
    assert len(files) == 2 and json.loads(files[0].read_text())["reason"] == "sandbox"
    assert any(x.get("decision") == "deny" and x.get("action") == "read_page" for x in e)   # the other site


LOOK = {"down": False, "pt": (0, 0), "hit": None, "focus": None, "url": SITE, "title": "Shop", "tab": True, "web": "w1"}


class LessonDesk(SiteDesk):
    def __init__(self, samples):
        super().__init__(pages=[SITE])
        self.samples = list(samples)

    def web_root(self, app):
        root = super().web_root(app)
        if "google.com" not in self.url:
            root.children.append(N("button", "Buy", handle="b1"))
        return root


def kinds(monkeypatch):
    seen, orig = [], engine.Runner.card
    monkeypatch.setattr(engine.Runner, "card", lambda self, kind, *a, **k: (seen.append(kind), orig(self, kind, *a, **k))[1])
    return seen


def test_teach_cancelled_returns_to_the_sandbox_card(tmp_path, monkeypatch):
    terms.record(tmp_path, SITE, "allowed", "https://shop.example.com/terms", "ok")
    seen = kinds(monkeypatch)
    d = LessonDesk([LOOK] * 3)
    e, err, _ = run_sandbox(tmp_path, d, ["capture", "teach", "cancel", "capture", "done"], monkeypatch)
    assert err is None and e[-1]["kind"] == "flow_end"
    assert "teaching" in seen and "terms" not in seen and "new_page" not in seen


def test_teach_on_the_typed_site_asks_for_its_terms(tmp_path, monkeypatch):
    seen = kinds(monkeypatch)   # no verdict stored: the typed site is not terms-exempt
    e, err, _ = run_sandbox(tmp_path, LessonDesk([LOOK]), ["capture", "teach", "cancel", "done"], monkeypatch)
    assert err is None and "terms" in seen and "teaching" not in seen


def test_full_lesson_returns_to_the_sandbox_card(tmp_path, monkeypatch):
    terms.record(tmp_path, SITE, "allowed", "https://shop.example.com/terms", "ok")
    seen = kinds(monkeypatch)
    d = LessonDesk([LOOK, {**LOOK, "down": True, "hit": "b1"}])   # then the tab is gone
    e, err, _ = run_sandbox(tmp_path, d, ["capture", "teach", "done", "approved", "done"], monkeypatch)
    assert err is None and e[-1]["kind"] == "flow_end"
    assert seen[seen.index("teaching"):][:3] == ["teaching", "lesson", "sandbox"]
    assert len(list((tmp_path / "lessons").iterdir())) == 1


def test_refused_touch_id_at_teach_returns_to_the_card(tmp_path, monkeypatch):
    other = "https://other.example.org/x"   # the typed site is already approved: Touch ID asks on another site
    terms.record(tmp_path, other, "allowed", "https://other.example.org/terms", "ok")
    seen = kinds(monkeypatch)
    d = LessonDesk([LOOK])
    d.pages = [other]
    e, err, _ = run_sandbox(tmp_path, d, ["capture", "teach", "done"], monkeypatch, first_contact=[True, False, False])
    assert err is None and e[-1]["kind"] == "flow_end" and "teaching" not in seen and d.samples == [LOOK]



def test_site_refused_at_touch_id_stops(tmp_path, monkeypatch):
    e, err, asked = run_sandbox(tmp_path, SiteDesk(), ["done"], monkeypatch, first_contact=False)
    assert str(err).startswith("denied navigate")
    for f in (tmp_path / "captures").iterdir():   # the stop's capture is of the Google page, never the refused site
        assert json.loads(f.read_text())["url"] == "https://www.google.com"


@pytest.mark.parametrize("site", ["http://shop.example.com/", "https://shop.example.com/ x", "file:///etc/passwd",
                                  "https://user@shop.example.com/"])
def test_bad_site_input_refused(tmp_path, monkeypatch, site):
    e, err, asked = run_sandbox(tmp_path, SiteDesk(), [], monkeypatch, site=site)
    assert str(err) == "bad run input" and not asked


def test_cli_run_captures_the_site_once(tmp_path, monkeypatch):
    e, err, asked = run_sandbox(tmp_path, SiteDesk(), [], monkeypatch, run_id=None)
    assert err is None and len(list((tmp_path / "captures").iterdir())) == 1


def test_page_that_moves_while_captured_is_not_saved(tmp_path, monkeypatch):
    class Moving(SiteDesk):
        def web_root(self, app):
            root = super().web_root(app)
            if "shop.example" in self.url and "google" not in self.url:
                self.url = "https://evil.example/landing"   # the tab moved on during the read
            return root
    d = Moving()
    e, err, asked = run_sandbox(tmp_path, d, ["capture", "done"], monkeypatch)
    [p] = applyfiles.read_json(tmp_path, applyfiles.SANDBOX)["pages"]
    assert p["file"] is None and p["note"] == "page changed while capturing: not captured"
    assert not (tmp_path / "captures").exists() or not any(
        "evil.example" in f.read_text() for f in (tmp_path / "captures").iterdir())


def test_site_typed_with_case_and_default_port_still_matches(tmp_path, monkeypatch):
    d = SiteDesk()
    d.press = lambda k: (d.calls.append(k), setattr(d, "url", d.typed.lower().replace(":443", "")) if k == "enter" else None)
    e, err, asked = run_sandbox(tmp_path, d, ["capture", "done"], monkeypatch, site="https://Shop.Example.com:443/a")
    assert err is None and "https://shop.example.com for the first time" in asked[0]
    [p] = applyfiles.read_json(tmp_path, applyfiles.SANDBOX)["pages"]
    assert p["file"] is not None


def test_each_capture_writes_a_draft_page_and_no_check_app(tmp_path, monkeypatch):
    from govaios.panel.apps import list_apps
    d = SiteDesk(pages=[SITE])
    e, err, asked = run_sandbox(tmp_path, d, ["capture", "done"], monkeypatch)
    [p] = applyfiles.read_json(tmp_path, applyfiles.SANDBOX)["pages"]
    pid = p["draft"]
    assert pid == "shop_example_com_page_at_https_shop_example_com"
    src = tmp_path / "src"
    page = yaml.safe_load((src / "pages" / f"{pid}.yaml").read_text())["page"]
    assert page["elements"]["button_go"] == {"role": "button", "name": "Go", "risk": "submit"}
    apps = {a.id: a for a in list_apps(src / "flows", tmp_path)}
    assert not any(i.startswith("check_") for i in apps)   # no Check app any more
    assert any(x.get("action") == "write_draft" and x.get("outcome") == "done" for x in e)
    assert any(x.get("action") == "write_draft" and x.get("decision") == "allow" for x in e)
