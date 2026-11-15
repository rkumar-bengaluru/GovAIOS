"""Outcome checks: after a data-changing press, the run polls for the taught result and audits it."""
import json
import re

import pytest
import yaml

from govaios import engine
from govaios.engine import Runner, Stop, check_learned
from conftest import FakeDesktop, N

SITE = "http://localhost:8100"
PG = "localhost_joblens"
OTHER = "localhost_other"
COUNT = {"for": "r2", "kind": "count", "target": f"{PG}.promoted", "change": 1}
LEFT = {"for": "r2", "kind": "item_left"}


class Desk(FakeDesktop):
    """JobLens Shortlisted: tabs with counts, one card per profile with Review; Review opens a dialog whose
    Approve & promote moves that card to Promoted. after: Promoted values the reads show once pressed."""

    def __init__(self, names, promoted=7, after=None, stuck=False, tabs=True):
        super().__init__([])
        self.url = SITE + "/shortlisted"
        self.cards = [[n, i] for i, n in enumerate(names)]
        self.promoted, self.after, self.stuck, self.tabs, self.popup = promoted, after, stuck, tabs, None
        self.pressed = False

    def current_url(self, app):
        return self.url

    def web_root(self, app):
        if self.pressed and self.after:
            self.promoted = self.after.pop(0)
        kids = [N("tab", f"Shortlisted ({len(self.cards)})"), N("tab", f"Promoted ({self.promoted})")] if self.tabs else []
        kids += [N("article", children=[N("heading", n), N("button", "Review", value=str(i))]) for n, i in self.cards]
        if self.popup is not None:
            kids.append(N("dialog", children=[N("button", "Approve & promote")]))
        kids.append(N("button", "Done"))
        return N("document", "JobLens", children=kids)

    def click(self, node):
        self.calls.append(("click", node.name))
        if node.name == "Review":
            self.popup = int(node.value)
        elif node.name == "Approve & promote":
            self.pressed = True
            if not self.stuck:
                self.cards = [c for c in self.cards if c[1] != self.popup]
                if self.after is None:
                    self.promoted += 1
            self.popup = None


def make(tmp_path, r2=None, done=None):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True, exist_ok=True), pages.mkdir(exist_ok=True)
    (pages / f"{PG}.yaml").write_text(yaml.safe_dump({"page": {
        "id": PG, "identification": {"title_matches": "^JobLens$", "anchors": []},
        "elements": {"review": {"role": "button", "name": "Review", "risk": "navigate"},
                     "promoted": {"role": "tab", "name_matches": r"^Promoted \(\d+\)$", "risk": "navigate"},
                     "approve_promote": {"role": "button", "name": "Approve & promote", "risk": "submit"},
                     "done": {"role": "button", "name": "Done", "risk": "navigate"}}}}))
    (pages / f"{OTHER}.yaml").write_text(yaml.safe_dump({"page": {
        "id": OTHER, "identification": {"title_matches": "^Other$", "anchors": []},
        "elements": {"done": {"role": "button", "name": "Done", "risk": "navigate"}}}}))
    rep = {"id": "r", "action": "repeat", "item": f"{PG}.review", "max": 1, "steps": [
        {"id": "r1", "action": "click", "target": f"{PG}.review"},
        {"id": "r2", "action": "click", "target": f"{PG}.approve_promote", **(r2 or {})}]}
    f = flows / "jl.yaml"
    f.write_text(yaml.safe_dump({"workflow": {
        "id": "jl", "app": "JobLens test", "version": 1, "browser": {"application": "chrome", "account": "x"},
        "permissions": {"allow": ["click", "read_page"], "max_element_risk": "submit"},
        "destinations": [SITE], "steps": [{"id": "c", "action": "classify_page", "on_match": {PG: {
            "do": [rep, done or {"id": "d", "action": "click", "target": f"{PG}.done"}], "then": "end"}}}]}}))
    return f


def go(tmp_path, monkeypatch, desk, **kw):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    t = iter(range(10**6))
    monkeypatch.setattr(engine.time, "time", lambda: next(t))
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    r = Runner(make(tmp_path, **kw), desk, tmp_path)
    r.approvals.approve_flow("jl", r.digest)
    r.approvals.approve_destination("jl", SITE)
    r.approvals.grant_presses("jl", r.digest)
    try:
        r.run()
    except Stop as e:
        return e
    return None


def outcomes(tmp_path):
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    return [e for e in map(json.loads, lines) if e["kind"] == "outcome"]


def test_confirmed_count_and_item(tmp_path, monkeypatch):
    assert go(tmp_path, monkeypatch, Desk(["Ada", "Ben"]), r2={"outcomes": [COUNT, LEFT]}) is None
    count, left = outcomes(tmp_path)
    assert count["outcome"] == left["outcome"] == "confirmed" and count["step"] == left["step"] == "r2"
    assert (count["count_before"], count["count_after"], count["expected"]) == (7, 8, 8)
    assert (left["count_before"], left["count_after"], left["round"]) == (1, 0, 1)
    assert re.fullmatch(r"[0-9a-f]{64}", left["fingerprint"])
    assert "Ada" not in (tmp_path / "audit.jsonl").read_text()


def test_expected_is_before_plus_change(tmp_path, monkeypatch):
    assert go(tmp_path, monkeypatch, Desk(["Ada"], promoted=12), r2={"outcomes": [COUNT]}) is None
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["count_before"], o["count_after"], o["expected"]) == ("confirmed", 12, 13, 13)


def test_a_count_of_the_taught_value_never_confirms(tmp_path, monkeypatch):
    e = go(tmp_path, monkeypatch, Desk(["Ada"], promoted=12, after=[8]), r2={"outcomes": [COUNT]})
    assert str(e).startswith("result not seen")
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["count_after"], o["expected"]) == ("not_seen", 8, 13)


def test_flicker_needs_two_reads(tmp_path, monkeypatch):
    d = Desk(["Ada"], after=[8, 7, 8, 8])
    assert go(tmp_path, monkeypatch, d, r2={"outcomes": [COUNT]}) is None
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["count_after"]) == ("confirmed", 8) and d.after == []


def test_same_name_twice(tmp_path, monkeypatch):
    assert go(tmp_path, monkeypatch, Desk(["Ada Lovelace", "Ada Lovelace"]), r2={"outcomes": [LEFT]}) is None
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["count_before"], o["count_after"]) == ("confirmed", 2, 1)


def test_item_still_there_is_not_seen(tmp_path, monkeypatch):
    d = Desk(["Ada Lovelace", "Ada Lovelace"], stuck=True)
    e = go(tmp_path, monkeypatch, d, r2={"outcomes": [LEFT]})
    assert str(e) == "result not seen: Approve & promote was pressed, its result did not appear"
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["count_before"], o["count_after"]) == ("not_seen", 2, 2)


def test_not_seen_stops_and_ends_run(tmp_path, monkeypatch):
    d = Desk(["Ada"], stuck=True)
    e = go(tmp_path, monkeypatch, d, r2={"outcomes": [COUNT]})
    assert str(e).startswith("result not seen") and engine._ends_run(e)
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["count_before"], o["count_after"]) == ("not_seen", 7, 7)
    assert d.calls.count(("click", "Approve & promote")) == 1
    stop = [json.loads(x) for x in (tmp_path / "audit.jsonl").read_text().splitlines()][-1]
    assert stop["kind"] == "stop" and stop["reason"] == str(e)


def test_not_checked_when_run_dies_first(tmp_path, monkeypatch):
    done = {"id": "d", "action": "click", "target": f"{OTHER}.done", "outcomes": [COUNT]}
    e = go(tmp_path, monkeypatch, Desk(["Ada"]), done=done)
    assert str(e) == f"not on {OTHER}"
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["step"]) == ("not_checked", "r2")


def test_unchecked_for_press_without_outcome(tmp_path, monkeypatch):
    assert go(tmp_path, monkeypatch, Desk(["Ada"])) is None
    [o] = outcomes(tmp_path)
    assert (o["outcome"], o["step"]) == ("unchecked", "r2")


def test_before_unknown_stops_before_press(tmp_path, monkeypatch):
    d = Desk(["Ada"], tabs=False)
    e = go(tmp_path, monkeypatch, d, r2={"outcomes": [COUNT]})
    assert str(e).endswith(f"cannot check Approve & promote: {PG}.promoted not seen before the press")
    assert ("click", "Approve & promote") not in d.calls and outcomes(tmp_path) == []


def test_count_of():
    assert engine.count_of("Promoted (8)") == 8 and engine.count_of("Promoted (8) ") == 8
    assert engine.count_of("Promoted") is None and engine.count_of("(8) Promoted") is None


@pytest.mark.parametrize("outs, msg", [
    ([{**COUNT, "for": "nope"}], "outcome for nope: no such step"),
    ([{**COUNT, "kind": "text"}], "outcome kind"),
    ([{**COUNT, "change": "1"}], "count outcome"),
])
def test_outcome_rejected_at_load(outs, msg):
    rep = {"id": "r", "action": "repeat", "item": f"{PG}.review", "max": 1, "steps": [
        {"id": "r1", "action": "click", "target": f"{PG}.review"},
        {"id": "r2", "action": "click", "target": f"{PG}.approve_promote", "outcomes": outs}]}
    with pytest.raises(Stop, match=msg):
        check_learned([{"id": "c", "action": "classify_page", "on_match": {PG: {"do": [rep], "then": "end"}}}])


def test_outcome_for_unknown_step_rejected():
    with pytest.raises(Stop, match="nope"):
        check_learned([{"id": "a", "action": "click", "target": f"{PG}.done", "outcomes": [{**COUNT, "for": "nope"}]}])


def test_item_left_only_inside_a_repeat():
    with pytest.raises(Stop, match="item_left"):
        check_learned([{"id": "r2", "action": "click", "target": f"{PG}.done", "outcomes": [LEFT]}])


def _runner(tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    return Runner(make(tmp_path, **kw), Desk(["Ada"]), tmp_path)


def test_missing_lists_unchecked_press(tmp_path, monkeypatch):
    r = _runner(tmp_path, monkeypatch)
    assert engine.outcomes_missing(r.flow, r.pages) == ["Approve & promote"]
    del r.pages[PG]["elements"]["approve_promote"]["name"]   # no name at all: the element key labels it
    assert engine.outcomes_missing(r.flow, r.pages) == ["approve_promote"]
    r = _runner(tmp_path, monkeypatch)
    r = _runner(tmp_path, monkeypatch, r2={"outcomes": [COUNT]})
    assert engine.outcomes_missing(r.flow, r.pages) == []


def test_outside_only_flow_not_checked(tmp_path, monkeypatch):
    r = _runner(tmp_path, monkeypatch)
    r.flow["destinations"] = ["https://boards.greenhouse.io"]
    assert engine.outcomes_missing(r.flow, r.pages) == []


def test_approve_flow_refuses_before_touch_id(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(engine.auth, "approve", lambda *a, **k: calls.append(a) or (True, "biometric"))
    with pytest.raises(Stop, match="^needs an outcome"):
        _runner(tmp_path, monkeypatch).approve_flow()
    assert calls == []


def test_approved_digest_keeps_running(tmp_path, monkeypatch):
    assert go(tmp_path, monkeypatch, Desk(["Ada"])) is None
    assert "unchecked" in (tmp_path / "audit.jsonl").read_text()


def test_submit_press_is_never_retried(tmp_path, monkeypatch):
    d = Desk(["Ada"])
    e = go(tmp_path, monkeypatch, d, r2={"verify_page": OTHER})   # the page never arrives
    assert str(e).endswith(f"after click expected {OTHER}")
    assert d.calls.count(("click", "Approve & promote")) == 1
    assert len([o for o in outcomes(tmp_path) if o["outcome"] == "unchecked"]) <= 1
