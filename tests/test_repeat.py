"""A learned repeat: every list item still holding the target gets the taught round, until none are left."""
import json

import pytest
import yaml

from govaios import engine
from govaios.engine import Runner, Stop, check_learned
from conftest import FakeDesktop, N

SITE = "http://localhost:8100"
PG = "localhost_joblens"


class Desk(FakeDesktop):
    """A list of rows (cell name + Review); Review opens a pop-up whose Approve removes that row."""

    def __init__(self, names, stuck=(), box="row", swap=False, slow=False, estop=False):
        super().__init__([])
        self.url = SITE + "/shortlisted"
        self.rows = [[n, i] for i, n in enumerate(names)]   # [label, row id]
        self.stuck, self.popup, self.reviews, self.order = set(stuck), None, 0, []
        self.box, self.swap, self.slow, self.estop, self.leaving = box, swap, slow, estop, None

    def scroll_into_view(self, node):
        super().scroll_into_view(node)
        if self.swap:   # the list reorders between the round's two looks at it
            self.rows.reverse()

    def current_url(self, app):
        return self.url

    def web_root(self, app):
        if self.leaving:   # slow: the row leaves on a later snapshot, as JobLens answers
            self.leaving[1] -= 1
            if self.leaving[1] <= 0:
                self.rows, self.leaving = [r for r in self.rows if r[1] != self.leaving[0]], None
        kids = [N(self.box, children=[N("cell", n), N("button", "Review", value=str(i))]) for n, i in self.rows]
        if not self.rows:
            kids.append(N("text", "No profiles"))
        if self.popup is not None:
            kids.append(N("dialog", children=[N("button", "Approve & promote")]))
        kids.append(N("button", "Done"))
        return N("document", "JobLens", children=[N("table", children=kids)])

    def click(self, node):
        self.calls.append(("click", node.name))
        if node.name == "Review":
            self.reviews += 1
            self.popup = int(node.value)
            self.order.append(next(n for n, i in self.rows if i == self.popup))
        elif node.name == "Approve & promote":
            if self.estop:
                raise Stop("emergency stop")
            if self.slow:
                self.leaving = [self.popup, 2]
            elif self.popup not in self.stuck:
                self.rows = [r for r in self.rows if r[1] != self.popup]
            self.popup = None


def repeat_step(**kw):
    return {"id": "r", "action": "repeat", "item": f"{PG}.review", "max": 10, "steps": [
        {"id": "r1", "action": "click", "target": f"{PG}.review"},
        {"id": "r2", "action": "click", "target": f"{PG}.approve_promote"}], **kw}


def make(tmp_path, rep, within=False):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True, exist_ok=True), pages.mkdir(exist_ok=True)
    (pages / f"{PG}.yaml").write_text(yaml.safe_dump({"page": {
        "id": PG, "identification": {"title_matches": "^JobLens$", "anchors": []},
        "elements": {"review": {"role": "button", "name": "Review", "risk": "navigate", "index": 1,
                                **({"within": "table"} if within else {})},
                     "table": {"role": "table", "risk": "read"},
                     "approve_promote": {"role": "button", "name": "Approve & promote", "risk": "submit"},
                     "done": {"role": "button", "name": "Done", "risk": "navigate"}}}}))
    f = flows / "jl.yaml"
    f.write_text(yaml.safe_dump({"workflow": {
        "id": "jl", "app": "JobLens test", "version": 1, "browser": {"application": "chrome", "account": "x"},
        "permissions": {"allow": ["click", "read_page"], "max_element_risk": "submit"},
        "destinations": [SITE], "steps": [{"id": "c", "action": "classify_page", "on_match": {PG: {
            "do": [rep, {"id": "d", "action": "click", "target": f"{PG}.done"}], "then": "end"}}}]}}))
    return f


def go(tmp_path, monkeypatch, names, stuck=(), desk=None, within=False, **kw):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    t = iter(range(0, 10**6, 5))
    monkeypatch.setattr(engine.time, "time", lambda: next(t))   # the after-round wait runs out quickly
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    d = Desk(names, stuck, **(desk or {}))
    r = Runner(make(tmp_path, repeat_step(**kw), within), d, tmp_path)
    r.approvals.approve_flow("jl", r.digest)
    r.approvals.approve_destination("jl", SITE)
    r.approvals.grant_presses("jl", r.digest)   # Task 1's press grant: not what these tests are about
    try:
        r.run()
    except Stop as e:
        return d, str(e)
    return d, None


def repeats(tmp_path):
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    return [(e.get("round"), e["outcome"], e.get("reason")) for e in map(json.loads, lines) if e["kind"] == "repeat"]


def test_repeat_does_every_row_until_none_left(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben", "Cy"])
    assert why is None and d.order == ["Ada", "Ben", "Cy"] and d.rows == []
    assert repeats(tmp_path) == [(1, "done", None), (2, "done", None), (3, "done", None),
                                 (None, "none_left", "3 done")]
    assert d.calls[-1] == ("click", "Done")


def test_repeat_ends_when_none_left(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, [])
    assert why is None and d.reviews == 0
    assert repeats(tmp_path) == [(None, "none_left", "0 done")]


def test_repeat_cap_stops_at_max(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["A", "B", "C", "D", "E"], max=2)
    assert why is None and d.order == ["A", "B"]
    assert repeats(tmp_path)[-1] == (None, "cap", "2 done") and len(repeats(tmp_path)) == 3


def test_repeat_stops_on_a_row_that_did_not_go(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben", "Cy"], stuck={1})
    assert why == "repeat stopped on round 2 after 1 done: round 2: the item is still on the list after its round"
    assert repeats(tmp_path) == [(1, "done", None), (2, "error", None)]
    assert d.order == ["Ada", "Ben"]


@pytest.mark.parametrize("kw, msg", [
    ({"max": 0}, "max"), ({"max": 101}, "max"), ({"max": True}, "max"),
    ({"steps": []}, "no steps"),
    ({"steps": [{"id": "x", "action": "click", "target": f"{PG}.review"}, repeat_step(id="inner")]}, "cannot hold"),
    ({"steps": [{"id": "x", "action": "click", "target": f"{PG}.approve_promote"}]}, "first step"),
    ({"item": None}, "item must be page.element"),
    ({"item": "current_item.review", "steps": [{"id": "x", "action": "click", "target": "current_item.review"}]},
     "item must be page.element"),
])
def test_repeat_shape_checked_at_load(kw, msg):
    flow = [{"id": "c", "action": "classify_page", "on_match": {PG: {"do": [repeat_step(**kw)], "then": "end"}}}]
    with pytest.raises(Stop, match=msg):
        check_learned(flow)


def test_repeat_sub_step_ids_count_as_duplicates():
    rep = repeat_step()
    flow = [{"id": "c", "action": "classify_page", "on_match": {PG: {
        "do": [rep, {"id": "r1", "action": "click", "target": f"{PG}.done"}], "then": "end"}}}]
    with pytest.raises(Stop, match="duplicate step id: r1"):
        check_learned(flow)


def test_repeat_round_click_is_the_item_s_own_button(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben"], max=1)
    assert why is None and d.order == ["Ada"] and [n for n, _ in d.rows] == ["Ben"]


def test_repeat_with_duplicate_names_does_each_row(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ada", "Ada"])
    assert why is None and d.rows == []
    assert repeats(tmp_path) == [(1, "done", None), (2, "done", None), (3, "done", None), (None, "none_left", "3 done")]


def test_repeat_duplicate_name_that_did_not_go_stops(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ada"], stuck={0})
    assert why == "repeat stopped on round 1 after 0 done: round 1: the item is still on the list after its round"


def test_repeat_clicks_the_item_once_per_round(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben", "Cy"])
    assert d.reviews == 3 and d.calls.count(("click", "Review")) == 3


def test_item_label_skips_the_target():
    btn = N("button", "Review")
    assert engine.item_label(N("row", children=[btn, N("cell", ""), N("cell", "x" * 300)]), btn) == "x" * 200


def test_repeat_item_must_be_an_element_of_its_page(tmp_path):
    rep = repeat_step(item=f"{PG}.nope", steps=[{"id": "x", "action": "click", "target": f"{PG}.nope"}])
    with pytest.raises(Stop, match=f"repeat item {PG}.nope is not an element of its page"):
        Runner(make(tmp_path, rep), Desk([]), tmp_path)


def test_repeat_item_spec_with_within_still_finds_each_row(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben"], within=True)
    assert why is None and d.order == ["Ada", "Ben"] and repeats(tmp_path)[-1] == (None, "none_left", "2 done")


def test_repeat_items_outside_rows_never_end_as_none_left(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben"], desk={"box": "group"})
    assert why == "repeat: 2 Review found but none inside a row or card" and d.reviews == 0
    assert repeats(tmp_path) == [(1, "error", None)]


def test_repeat_list_that_changed_during_the_round_stops(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben"], desk={"swap": True})
    assert why == "repeat stopped on round 1 after 0 done: the list changed during the round" and d.reviews == 0


def test_repeat_row_that_leaves_on_a_later_poll_is_done(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada", "Ben"], desk={"slow": True})
    assert why is None and d.rows == []
    assert repeats(tmp_path) == [(1, "done", None), (2, "done", None), (None, "none_left", "2 done")]


def test_repeat_run_stop_inside_a_round_is_not_wrapped(tmp_path, monkeypatch):
    d, why = go(tmp_path, monkeypatch, ["Ada"], desk={"estop": True})
    assert why == "emergency stop" and repeats(tmp_path) == [(1, "error", None)]


def test_later_lesson_never_reuses_a_repeat_sub_step_id():
    from govaios import lessons
    rep = repeat_step(id="learned_p_1", item="p.review", steps=[
        {"id": "learned_p_2", "action": "click", "target": "p.review"},
        {"id": "learned_p_3", "action": "click", "target": "p.ok"}])
    flow = [{"id": "c", "action": "classify_page", "on_match": {"p": {"do": [rep], "then": "end"}}}]
    ids = set(lessons._ids(flow))
    assert {"learned_p_2", "learned_p_3"} <= ids
    line = {"kind": "click", "target": "p.ok", "keep": True}
    new = lessons._cases({"pages": [{"id": "p", "steps": [line] * 4}]}, set(), set(ids), {})["p"]["do"]
    assert not {s["id"] for s in new} & ids


def test_item_label_prefers_a_cell_over_the_rows_whole_text():
    btn = N("button", "Review")
    row = N("row", "Ada Lovelace " + "long " * 80, children=[btn, N("cell", "Ada")])
    assert engine.item_label(row, btn) == "Ada"


def test_repeat_audit_has_no_item_text(tmp_path, monkeypatch):
    go(tmp_path, monkeypatch, ["Ada Lovelace", "Alan Turing"])
    text = (tmp_path / "audit.jsonl").read_text()
    assert "Ada" not in text and "Turing" not in text and '"fingerprint"' in text
