"""Task 7: a learned page in classify_page ({do: [steps], then: again|end}) runs on the next run."""
import json

import pytest
import yaml

from govaios import engine
from govaios.engine import Runner, Stop
from conftest import FakeDesktop, N

SITE = "https://acme.example"
PAGES = {
    "page_a": {"title_matches": "^Step A$", "elements": {
        "next": {"role": "button", "name": "Next", "risk": "navigate"},
        "send": {"role": "button", "name": "Send", "risk": "submit"}}},
    "page_b": {"title_matches": "^Step B$", "elements": {"done": {"role": "button", "name": "Done", "risk": "navigate"}}},
    "page_c": {"title_matches": "^Step C$", "elements": {"go": {"role": "button", "name": "Go", "risk": "navigate"}}},
}


class Desk(FakeDesktop):
    def __init__(self):
        super().__init__([])
        self.title, self.url = "Step A", SITE + "/a"

    def current_url(self, app):
        return self.url

    def click(self, node):
        self.calls.append(("click", node.name))
        assert node.name != "Send", "a submit-rated element was clicked"
        self.title = {"Next": "Step B", "Go": "Step A"}.get(node.name, self.title)

    def web_root(self, app):
        kids = {"Step A": [N("button", "Next"), N("button", "Send")], "Step B": [N("button", "Done")],
                "Step C": [N("button", "Go")]}[self.title]
        return N("document", self.title, children=kids)


def make(tmp_path, steps, risk="navigate"):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True), pages.mkdir()
    for pid, p in PAGES.items():
        (pages / f"{pid}.yaml").write_text(yaml.safe_dump({"page": {
            "id": pid, "identification": {"title_matches": p["title_matches"]}, "elements": p["elements"]}}))
    f = flows / "teach.yaml"
    f.write_text(yaml.safe_dump({"workflow": {
        "id": "teach", "app": "Teach", "version": 1, "browser": {"application": "chrome", "account": "x"},
        "permissions": {"allow": ["click", "read_page", "ask_admin"], "max_element_risk": risk},
        "destinations": [SITE], "steps": steps}}))
    return f, pages


def run(tmp_path, monkeypatch, steps, risk="navigate", ctx=None):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    f, _ = make(tmp_path, steps, risk)
    d = Desk()
    r = Runner(f, d, tmp_path)
    r.approvals.approve_flow("teach", r.digest)
    r.approvals.approve_destination("teach", SITE)
    r.ctx.update(ctx or {})
    try:
        r.run()
    finally:
        r.audit_lines = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()]
    return r, d


def learned(*do, then="again"):
    return {"do": [{"id": f"learned_page_a_{i}", **s} for i, s in enumerate(do, 1)], "then": then}


def test_learned_case_clicks_then_reclassifies(tmp_path, monkeypatch):
    steps = [{"id": "where", "action": "classify_page", "timeout_seconds": 0,
              "on_match": {"page_a": learned({"action": "click", "target": "page_a.next"}),
                           "page_b": "continue", "unknown": "stop_and_report"}},
             {"id": "finish", "action": "click", "target": "page_b.done"}]
    r, d = run(tmp_path, monkeypatch, steps)
    assert ("click", "Next") in d.calls and ("click", "Done") in d.calls
    assert r.ctx["page"] == "page_b" and r.audit_lines[-1]["kind"] == "flow_end"
    assert any(e.get("step") == "learned_page_a_1" and e.get("action") == "click" for e in r.audit_lines)


def test_learned_end_finishes_the_job(tmp_path, monkeypatch):
    each = {"id": "each", "action": "for_each_item", "task_title": ["t"], "steps": [
        {"id": "where", "action": "classify_page", "timeout_seconds": 0,
         "on_match": {"page_a": learned({"action": "click", "target": "page_a.next"}, then="end"),
                      "unknown": "stop_and_report"}},
        {"id": "never", "action": "click", "target": "page_b.done"}]}
    r, d = run(tmp_path, monkeypatch, [each], ctx={"items": [{"t": "Job 1"}]})
    assert ("click", "Done") not in d.calls and ("click", "Next") in d.calls
    assert r.tasks == [{"n": 1, "title": "Job 1", "status": "done"}]
    assert r.audit_lines[-1]["kind"] == "flow_end"


def test_learned_end_outside_for_each_ends_the_list(tmp_path, monkeypatch):
    steps = [{"id": "where", "action": "classify_page", "timeout_seconds": 0,
              "on_match": {"page_a": learned({"action": "click", "target": "page_a.next"}, then="end")}},
             {"id": "never", "action": "click", "target": "page_b.done"}]
    r, d = run(tmp_path, monkeypatch, steps)
    assert ("click", "Done") not in d.calls and r.audit_lines[-1]["kind"] == "flow_end"


@pytest.mark.parametrize("bad, why", [
    ({"action": "navigate", "value": SITE}, "learned steps: navigate not allowed"),
    ({"action": "classify_page", "on_match": {}}, "learned steps: classify_page not allowed"),
])
def test_learned_do_rejects_navigate(tmp_path, bad, why):
    f, _ = make(tmp_path, [{"id": "where", "action": "classify_page", "on_match": {"page_a": learned(bad)}}])
    with pytest.raises(Stop, match=why):
        Runner(f, Desk(), tmp_path)


@pytest.mark.parametrize("case, why", [
    ({"do": [{"action": "click", "target": "page_a.next"}], "then": "again"}, "learned steps: a step without an id"),
    ({"do": [{"id": "where", "action": "click", "target": "page_a.next"}], "then": "again"}, "duplicate step id: where"),
    ({"do": [], "then": "again"}, "learned steps: page_a has no steps"),
    ({"do": [{"id": "x", "action": "click", "target": "page_a.next"}], "then": "later"}, "learned steps: then must be"),
    ({"unknown": True, "do": [{"id": "x", "action": "hand_over"}], "then": "end"},
     "learned steps: unknown cannot be taught"),
])
def test_learned_case_shape_checked_at_load(tmp_path, case, why):
    case = dict(case)
    key = "unknown" if case.pop("unknown", False) else "page_a"
    f, _ = make(tmp_path, [{"id": "where", "action": "classify_page", "on_match": {key: case}}])
    with pytest.raises(Stop, match=why):
        Runner(f, Desk(), tmp_path)


def test_learned_pages_are_bound_by_approval(tmp_path):
    # page_c is referenced only by a learned step's target
    f, pages = make(tmp_path, [{"id": "where", "action": "classify_page", "on_match": {
        "page_a": learned({"action": "click", "target": "page_c.go"}), "page_b": "continue"}}])
    r = Runner(f, Desk(), tmp_path)
    assert "page_c" in r.pages
    r.approvals.approve_flow("teach", r.digest)
    (pages / "page_c.yaml").write_text((pages / "page_c.yaml").read_text().replace("Go", "Go!"))
    assert not r.approvals.flow_ok("teach", Runner(f, Desk(), tmp_path).digest)


def test_too_many_learned_pages_in_a_row(tmp_path, monkeypatch):
    # A -> (Next) B -> (learned: Done does nothing) ... B again: a loop the bound stops
    steps = [{"id": "where", "action": "classify_page", "timeout_seconds": 0, "on_match": {
        "page_b": {"do": [{"id": "learned_page_b_1", "action": "click", "target": "page_b.done"}], "then": "again"},
        "page_a": learned({"action": "click", "target": "page_a.next"})}}]
    with pytest.raises(Stop, match="too many learned pages in a row"):
        run(tmp_path, monkeypatch, steps)
    r_clicks = [c for c in FakeDesktop.current.calls if c == ("click", "Done")]
    assert len(r_clicks) == 9   # 1 learned A + 9 learned B = 10 cases; the 11th stops before acting


def test_learned_click_on_a_submit_element_is_refused(tmp_path, monkeypatch):
    steps = [{"id": "where", "action": "classify_page", "timeout_seconds": 0,
              "on_match": {"page_a": learned({"action": "click", "target": "page_a.send"})}}]
    with pytest.raises(Stop, match=r"denied click \(risk submit\)"):
        run(tmp_path, monkeypatch, steps, risk="modify")
    assert ("click", "Send") not in FakeDesktop.current.calls


def test_learned_case_on_an_undeclared_origin_is_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(Desk, "current_url", lambda self, app: "https://elsewhere.example/a")
    steps = [{"id": "where", "action": "classify_page", "timeout_seconds": 0,
              "on_match": {"page_a": learned({"action": "click", "target": "page_a.next"})}}]
    with pytest.raises(Stop, match="denied read_page"):
        run(tmp_path, monkeypatch, steps)
    assert not any(isinstance(c, tuple) and c[0] == "click" for c in FakeDesktop.current.calls)
