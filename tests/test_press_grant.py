"""A submit press on the admin's own app needs one Touch ID per version of the app."""
import json

import pytest
import yaml

from govaios import engine
from govaios.approvals import Approvals
from govaios.engine import Runner, Stop
from conftest import FakeDesktop, N

SITE = "http://localhost:8100"


class Desk(FakeDesktop):
    def __init__(self):
        super().__init__([])
        self.url = SITE + "/discover"

    def current_url(self, app):
        return self.url

    def click(self, node):
        self.calls.append(("click", node.name))

    def web_root(self, app):
        return N("document", "Discover", children=[N("button", "Approve & promote")])


def make(tmp_path, extra=""):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True, exist_ok=True), pages.mkdir(exist_ok=True)
    (pages / "disc.yaml").write_text(yaml.safe_dump({"page": {
        "id": "disc", "identification": {"title_matches": "^Discover$", "anchors": []},
        "elements": {"approve": {"role": "button", "name": "Approve & promote", "risk": "submit"}}}}))
    f = flows / "jl.yaml"
    f.write_text(yaml.safe_dump({"workflow": {
        "id": "jl", "app": "JobLens test", "version": 1, "browser": {"application": "chrome", "account": "x"},
        "permissions": {"allow": ["click", "read_page"], "max_element_risk": "submit"},
        "destinations": [SITE], "steps": [{"id": "go", "action": "click", "target": "disc.approve"}], "x": extra}}))
    return f


def go(tmp_path, monkeypatch, answers, extra="", keep=False, url=None, holder=None):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    asked = []
    if holder is None:
        monkeypatch.setattr(engine.auth, "approve", lambda q, r, h: (asked.append(q), (answers.pop(0), "biometric"))[1])
    d = Desk()
    d.url = url or d.url
    r = Runner(tmp_path / "apps" / "flows" / "jl.yaml" if keep else make(tmp_path, extra), d, tmp_path)
    if holder is not None:
        holder["r"] = r
    r.approvals.approve_flow("jl", r.digest)
    r.approvals.approve_destination("jl", SITE)
    try:
        r.run()
    except Stop as e:
        return d, asked, str(e)
    return d, asked, None


def grants(tmp_path):
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    return [e for e in map(json.loads, lines) if e["kind"] == "press_grant"]


def test_first_submit_press_asks_once_then_presses(tmp_path, monkeypatch):
    d, asked, _ = go(tmp_path, monkeypatch, [True])
    assert asked == ["Let 'JobLens test' press Approve & promote on http://localhost:8100?"]
    assert ("click", "Approve & promote") in d.calls
    d, asked, _ = go(tmp_path, monkeypatch, [])
    assert asked == [] and ("click", "Approve & promote") in d.calls
    assert [g["decision"] for g in grants(tmp_path)] == ["allow"]


def test_refused_grant_stops_before_the_press(tmp_path, monkeypatch):
    d, asked, why = go(tmp_path, monkeypatch, [False])
    assert why == "press grant refused" and not any(isinstance(c, tuple) and c[0] == "click" for c in d.calls)
    assert [g["decision"] for g in grants(tmp_path)] == ["deny"]


def test_edited_flow_asks_again(tmp_path, monkeypatch):
    go(tmp_path, monkeypatch, [True])
    _, asked, _ = go(tmp_path, monkeypatch, [True], extra="edited")
    assert len(asked) == 1


def _flow_edit(tmp_path, **kw):
    f = tmp_path / "apps" / "flows" / "jl.yaml"
    d = yaml.safe_load(f.read_text())
    d["workflow"].update(kw)
    f.write_text(yaml.safe_dump(d))


def test_ceiling_below_submit_never_prompts_or_grants(tmp_path, monkeypatch):
    make(tmp_path)
    _flow_edit(tmp_path, permissions={"allow": ["click", "read_page"], "max_element_risk": "navigate"})
    d, asked, why = go(tmp_path, monkeypatch, [], keep=True)
    assert asked == [] and why and why.startswith("denied click")
    assert Approvals(tmp_path / "approvals.json").snapshot()["presses"] == {}


def test_submit_on_non_own_url_denied_without_prompt(tmp_path, monkeypatch):
    make(tmp_path)
    _flow_edit(tmp_path, destinations=["https://boards.greenhouse.io"])
    d, asked, why = go(tmp_path, monkeypatch, [], keep=True, url="https://boards.greenhouse.io/x")
    assert asked == [] and why.startswith("denied click") and ("click", "Approve & promote") not in d.calls


def test_payment_click_denied_without_prompt(tmp_path, monkeypatch):
    make(tmp_path)
    p = tmp_path / "apps" / "pages" / "disc.yaml"
    t = yaml.safe_load(p.read_text())
    t["page"]["elements"]["approve"]["risk"] = "payment"
    p.write_text(yaml.safe_dump(t))
    _flow_edit(tmp_path, permissions={"allow": ["click", "read_page"], "max_element_risk": "payment"})
    d, asked, why = go(tmp_path, monkeypatch, [], keep=True)
    assert asked == [] and why.startswith("denied click") and ("click", "Approve & promote") not in d.calls


def test_grant_not_stored_if_flow_revoked_during_prompt(tmp_path, monkeypatch):
    holder = {}
    make(tmp_path)
    monkeypatch.setattr(engine.auth, "approve", lambda q, r, h: (holder["r"].approvals.revoke_flow("jl"), (True, "biometric"))[1])
    d, asked, why = go(tmp_path, monkeypatch, [], keep=True, holder=holder)
    assert why == "revoked" and not holder["r"].approvals.press_ok("jl", holder["r"].digest)


def test_empty_submit_list_falls_back_to_the_clicked_name(tmp_path, monkeypatch):
    make(tmp_path)
    r = Runner(tmp_path / "apps" / "flows" / "jl.yaml", Desk(), tmp_path)
    r.flow["steps"] = [{"id": "c", "action": "classify_page", "on_match": {"disc": {"click": "approve"}}}]
    assert r.submit_buttons() == ["Approve & promote"]
    r.flow["steps"] = []
    r.approvals.approve_flow("jl", r.digest)
    assert r.submit_buttons() == []
    seen = []
    monkeypatch.setattr(r, "ask", lambda q, why: (seen.append(q), (True, "x"))[1])
    r._press_grant(SITE, {"name": "Go"})
    assert seen == ["Let 'JobLens test' press Go on http://localhost:8100?"]


def test_attach_on_a_submit_element_is_denied(tmp_path, monkeypatch):
    make(tmp_path)
    r = Runner(tmp_path / "apps" / "flows" / "jl.yaml", Desk(), tmp_path)
    monkeypatch.setattr(engine, "cv_path", lambda bank, home: tmp_path / "cv.pdf")
    monkeypatch.setattr(r, "_new_apply", lambda: {"yourself": [], "bank": {}})
    monkeypatch.setattr(r, "write_result", lambda: None)
    with pytest.raises(Stop, match="attach on a submit element denied"):
        r.do_attach_file({"target": "disc.approve", "check": "disc.approve"})
