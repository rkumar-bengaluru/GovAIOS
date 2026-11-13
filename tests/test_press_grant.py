"""A submit press on the admin's own app needs one Touch ID per version of the app."""
import json
import yaml

from govaios import engine
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


def go(tmp_path, monkeypatch, answers, extra=""):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    asked = []
    monkeypatch.setattr(engine.auth, "approve", lambda q, r, h: (asked.append(q), (answers.pop(0), "biometric"))[1])
    d = Desk()
    r = Runner(make(tmp_path, extra), d, tmp_path)
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
