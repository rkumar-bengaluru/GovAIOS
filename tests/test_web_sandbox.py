"""web_sandbox flow: open the site the admin names (Touch ID on first contact), capture the pages they choose; read only."""
import json
import threading
import time

import pytest
import yaml

from govaios import applyfiles, engine
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
    monkeypatch.setattr(engine.auth, "approve", lambda q, r, h, **k: (asked.append(q), (first_contact, "biometric"))[1])
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
    assert set(wf["permissions"]["allow"]) == {"launch_application", "navigate", "read_page", "ask_admin"}
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
