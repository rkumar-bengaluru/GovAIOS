import json, yaml
from govaios import engine, lessons
from govaios.engine import Runner, Stop
from govaios.formfill import Bank
from conftest import FakeDesktop
from govaios.desktop import Node as N
import test_lessons as TL

class Desk(FakeDesktop):
    def __init__(self, names, promoted=7, stuck=False):
        super().__init__([])
        self.url = "http://localhost:8100/discover"
        self.cards = list(names); self.promoted = promoted; self.popup = None; self.stuck = stuck
    def current_url(self, app): return self.url
    def link_url(self, node): return None
    def web_root(self, app):
        kids = [N("heading", "Discover"), N("tab", f"Shortlisted ({len(self.cards)})"), N("tab", f"Promoted ({self.promoted})"),
                N("link", "Inbox (3)")]
        kids += [N("row", "", children=[N("cell", c), N("button", "Review")]) for c in self.cards]
        if self.popup is not None:
            kids.append(N("dialog", children=[N("button", "Approve & promote")]))
        return N("document", "JobLens", children=kids)
    def click(self, node):
        self.calls.append(("click", node.name))
        if node.name == "Review": self.popup = 0
        elif node.name == "Approve & promote":
            if not self.stuck:
                self.cards.pop(0); self.promoted += 1
            self.popup = None

def build(tmp_path):
    les, app = TL.joblens_outcomes(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    plan = TL._plan(tmp_path, les, app, prop, repeats={1: 10}, outcomes=TL._tick(prop, lambda o: o.get("label") != "Inbox"))
    lessons.apply(plan, tmp_path / "pages", tmp_path / "answers.yaml")
    doc = yaml.safe_load(open(app))
    wf = doc["workflow"]; wf["browser"]["application"] = "chrome"
    wf["steps"] = [s for s in wf["steps"] if s["id"] == "on_start"]
    open(app, "w").write(yaml.safe_dump(doc, sort_keys=False))
    return app

def go(tmp_path, monkeypatch, desk):
    app = build(tmp_path)
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    t = iter(range(10**6)); monkeypatch.setattr(engine.time, "time", lambda: next(t))
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    (tmp_path / "home").mkdir(exist_ok=True)
    r = Runner(app, desk, tmp_path / "home")
    r.approvals.approve_flow(r.flow["id"], r.digest)
    for d in r.flow["destinations"]: r.approvals.approve_destination(r.flow["id"], d)
    r.approvals.grant_presses(r.flow["id"], r.digest)
    err = None
    try: r.run()
    except Stop as e: err = e
    lines = [json.loads(l) for l in (tmp_path / "home" / "audit.jsonl").read_text().splitlines()]
    return err, lines, desk

def test_ok(tmp_path, monkeypatch):
    err, lines, desk = go(tmp_path, monkeypatch, Desk(["Acme", "Globex"]))
    print(err, [ (e["kind"], e.get("step"), e.get("outcome")) for e in lines])
    print(desk.calls)
    assert [e["outcome"] for e in lines if e["kind"] == "outcome"].count("confirmed") >= 2
    assert "Acme" not in json.dumps(lines)

def test_stuck(tmp_path, monkeypatch):
    err, lines, desk = go(tmp_path, monkeypatch, Desk(["Acme", "Globex"], stuck=True))
    print(err, [(e["kind"], e.get("step"), e.get("outcome")) for e in lines])
    assert str(err).startswith("result not seen")
    assert [c for c in desk.calls if c == ("click", "Approve & promote")] == [("click", "Approve & promote")]
