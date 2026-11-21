"""Taught choose and tick steps, and a click that waits for a new address before a same-page read_table."""
import json

import pytest
import yaml

from govaios import engine
from govaios.engine import Runner, Stop, check_learned
from conftest import FakeDesktop, N

SITE = "http://localhost:8100"
PG = "localhost_tickets"
OPTS = ["Any", "Engineering", "Engineering Ops", "Sales"]


def cell(x):
    return N("cell", children=[N("text", x)])


class Desk(FakeDesktop):
    """One page: a Department popup, an Overdue only box, a Filter button and a table that follows the address."""

    def __init__(self, dept="Any", overdue="0", opts=OPTS, opens=True, picks=None, holds=True,
                 goes=SITE + "/tickets?overdue=1", loads=()):
        super().__init__([])
        self.dept, self.overdue, self.opts, self.opens, self.picks, self.holds = dept, overdue, opts, opens, picks, holds
        self.goes, self.loads, self.menu, self.url = goes, list(loads), False, SITE + "/tickets"

    def current_url(self, app):
        return self.url

    def loaded(self, app):
        return self.loads.pop(0) if self.loads else None

    def menu_open(self):
        return self.menu

    def click(self, node):
        self.calls.append(("click", node.name))
        if node.name == "Department":
            self.menu = self.opens
        elif node.name == "Overdue only" and self.holds:
            self.overdue = "0" if self.overdue == "1" else "1"
        elif node.name == "Filter" and self.goes:
            self.url = self.goes

    def press(self, key):
        self.calls.append(key)
        if key == "enter" and self.menu:
            self.dept = self.picks or self.typed
        if key in ("enter", "escape"):
            self.menu = False

    def web_root(self, app):
        rows = [["T-0009"]] if "overdue=1" in self.url else [["T-0001"], ["T-0009"]]
        return N("document", "Tickets", children=[
            N("popup_button", "Department", value=self.dept,
              children=[N("native:AXMenuItem", o) for o in self.opts]),
            N("checkbox", "Overdue only", value=self.overdue),
            N("button", "Filter"),
            N("table", children=[N("row", children=[cell("Ticket")])]
              + [N("row", children=[cell(c) for c in r]) for r in rows])])


def choose(v="Engineering"):
    return {"id": "ch", "action": "choose", "target": f"{PG}.dept", "value": v}


def tick(v=True):
    return {"id": "tk", "action": "tick", "target": f"{PG}.overdue", "value": v}


def press(**kw):
    return {"id": "f", "action": "click", "target": f"{PG}.filter", "wait_url": True, **kw}


def read():
    return {"id": "r", "action": "read_table", "target": f"{PG}.tickets", "columns": ["Ticket"], "rows": "all"}


def make(tmp_path, do, try_=False, risk=None, max_risk="modify"):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True, exist_ok=True), pages.mkdir(exist_ok=True)
    els = {"dept": {"role": "popup_button", "name": "Department", "risk": "modify"},
           "overdue": {"role": "checkbox", "name": "Overdue only", "risk": "modify"},
           "filter": {"role": "button", "name": "Filter", "risk": "navigate"},
           "tickets": {"role": "table", "has_text": "Ticket", "risk": "read"}}
    for k, v in (risk or {}).items():
        els[k]["risk"] = v
    (pages / f"{PG}.yaml").write_text(yaml.safe_dump({"page": {
        "id": PG, "identification": {"title_matches": "^Tickets$", "anchors": []}, "elements": els}}))
    f = flows / "tf.yaml"
    f.write_text(yaml.safe_dump({"workflow": {
        "id": "tf", "version": 1, "browser": {"application": "chrome", "account": "x"},
        **({"try": True} if try_ else {}),
        "permissions": {"allow": ["read_page", "fill_field", "click", "extract_visible_text", "report"],
                        "max_element_risk": max_risk},
        "destinations": [SITE], "steps": [{"id": "c", "action": "classify_page",
                                           "on_match": {PG: {"do": do, "then": "end"}}}]}}))
    return f


def runner(tmp_path, monkeypatch, desk, do, **kw):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    r = Runner(make(tmp_path, do, **kw), desk, tmp_path)
    r.approvals.approve_flow("tf", r.digest)
    r.approvals.approve_destination("tf", SITE)
    return r


def go(tmp_path, monkeypatch, desk, do, **kw):
    try:
        runner(tmp_path, monkeypatch, desk, do, **kw).run()
    except Stop as e:
        return e
    return None


def audits(tmp_path, action):
    es = [json.loads(ln) for ln in (tmp_path / "audit.jsonl").read_text().splitlines()]
    return [e for e in es if e.get("action") == action and "decision" not in e]


def clicks(d):
    return [c for c in d.calls if isinstance(c, tuple) and c[0] == "click"]


def test_choose_already_set_does_nothing(tmp_path, monkeypatch):
    d = Desk(dept="Engineering")
    assert go(tmp_path, monkeypatch, d, [choose()]) is None
    assert clicks(d) == [] and "enter" not in d.calls and d.typed == ""
    (e,) = audits(tmp_path, "choose_option")
    assert e["outcome"] == "already" and "value" not in e and "Engineering" not in json.dumps(e)


def test_choose_sets_and_holds(tmp_path, monkeypatch):
    d = Desk()
    assert go(tmp_path, monkeypatch, d, [choose()]) is None
    assert d.dept == "Engineering" and clicks(d) == [("click", "Department")] and d.calls.count("enter") == 1
    (e,) = audits(tmp_path, "choose_option")
    assert e["outcome"] == "done"
    assert "Engineering" not in (tmp_path / "audit.jsonl").read_text()


def test_choose_prefix_pick_stops(tmp_path, monkeypatch):
    e = go(tmp_path, monkeypatch, Desk(picks="Engineering Ops"), [choose()])
    assert str(e) == "the choice did not hold: Department"


@pytest.mark.parametrize("opts", [["Any", "Sales"], ["Any", "Engineering", "Engineering"]])
def test_choose_option_not_offered_stops(tmp_path, monkeypatch, opts):
    d = Desk(opts=opts)
    assert str(go(tmp_path, monkeypatch, d, [choose()])) == "option not offered: Department"
    assert clicks(d) == []


def test_choose_menu_not_open_stops(tmp_path, monkeypatch):
    d = Desk(opens=False)
    assert str(go(tmp_path, monkeypatch, d, [choose()])) == "could not open the menu: Department"
    assert "enter" not in d.calls


def test_choose_over_modify_denied(tmp_path, monkeypatch):
    d = Desk()
    e = go(tmp_path, monkeypatch, d, [choose()], risk={"dept": "submit"}, max_risk="submit")
    assert "denied" in str(e) and clicks(d) == []


def test_tick_already_in_state_no_click(tmp_path, monkeypatch):
    d = Desk(overdue="1")
    assert go(tmp_path, monkeypatch, d, [tick()]) is None
    assert clicks(d) == []


def test_tick_untick_clicks_once(tmp_path, monkeypatch):
    d = Desk(overdue="1")
    assert go(tmp_path, monkeypatch, d, [tick(False)]) is None
    assert clicks(d) == [("click", "Overdue only")] and d.overdue == "0"


def test_tick_did_not_hold_stops(tmp_path, monkeypatch):
    e = go(tmp_path, monkeypatch, Desk(holds=False), [tick()])
    assert str(e) == "the choice did not hold: Overdue only"


def test_wait_url_waits_then_read_runs(tmp_path, monkeypatch):
    d = Desk(loads=[False, True])
    assert go(tmp_path, monkeypatch, d, [press(), read()]) is None
    assert d.loads == [] and clicks(d) == [("click", "Filter")]
    (f,) = (tmp_path / "reports").iterdir()
    assert f.read_text() == "Ticket: T-0009\n"


def test_wait_url_unchanged_retries_then_stops(tmp_path, monkeypatch):
    d = Desk(goes=None)
    assert str(go(tmp_path, monkeypatch, d, [press(), read()])) == "the page did not change after Filter"
    assert clicks(d) == [("click", "Filter")] * 2


def test_wait_url_other_origin_stops(tmp_path, monkeypatch):
    d = Desk(goes="https://elsewhere.example/tickets")
    assert str(go(tmp_path, monkeypatch, d, [press(), read()])) == "the press went to another site"
    assert not (tmp_path / "reports").exists()


def test_wait_url_submit_pressed_once(tmp_path, monkeypatch):
    d = Desk(goes=None)
    r = runner(tmp_path, monkeypatch, d, [tick()], risk={"filter": "submit"}, max_risk="submit")
    r.approvals.grant_presses("tf", r.digest)
    with pytest.raises(Stop) as e:
        r.do_click(press())
    assert str(e.value) == "the page did not change after Filter"
    assert clicks(d) == [("click", "Filter")]


def case(*do):
    return [{"id": "c", "action": "classify_page", "on_match": {PG: {"do": list(do), "then": "end"}}}]


PAGES = {PG: {"elements": {"dept": {"role": "popup_button", "risk": "modify"},
                           "overdue": {"role": "checkbox", "risk": "modify"},
                           "filter": {"role": "button", "risk": "navigate"},
                           "tickets": {"role": "table", "risk": "read"}}}}


CV = "learned steps: choose value must be 1 to 200 characters with no control character"


@pytest.mark.parametrize("step,pages,msg", [
    (choose(""), None, CV), (choose("x" * 201), None, CV), (choose("a\nb"), None, CV),
    (tick("yes"), None, "learned steps: tick value must be true or false"),
    ({**choose(), "target": "dept"}, None, "learned steps: choose target must be page.element"),
    ({**tick(), "target": "current_item.overdue"}, None, "learned steps: tick target must be page.element"),
    ({**choose(), "target": f"{PG}.overdue"}, PAGES,
     f"learned steps: choose target {PG}.overdue is not a popup_button of its page"),
    ({**tick(), "target": f"{PG}.dept"}, PAGES, f"learned steps: tick target {PG}.dept is not a checkbox of its page"),
])
def test_check_choice_shape(step, pages, msg):
    with pytest.raises(Stop) as e:
        check_learned(case(step), pages)
    assert str(e.value) == msg


def test_check_choice_accepts_good_steps():
    check_learned(case(choose(), tick(), {**tick(False), "id": "t2"}, press(), read()), PAGES)


@pytest.mark.parametrize("step", [choose(), tick()])
def test_repeat_cannot_hold_a_choice(step):
    rep = {"id": "p", "action": "repeat", "item": f"{PG}.row", "max": 3,
           "steps": [{"id": "k", "action": "click", "target": f"{PG}.row"}, step]}
    with pytest.raises(Stop) as e:
        check_learned(case(rep))
    assert str(e.value) == f"learned steps: a repeat cannot hold a {step['action']}"


@pytest.mark.parametrize("do,pages", [
    ([press()], None), ([press(), tick()], None), ([press(), tick(), read()], None),
    ([{**tick(), "wait_url": True}, read()], None),
    ([press(target=f"{PG}.dept"), read()], PAGES),
])
def test_wait_url_placement(do, pages):
    with pytest.raises(Stop) as e:
        check_learned(case(*do), pages)
    assert "wait_url" in str(e.value)


def test_try_runs_choose_tick_and_wait_url(tmp_path, monkeypatch):
    d = Desk()
    assert go(tmp_path, monkeypatch, d, [choose(), tick(), press(), read()], try_=True) is None
    assert (d.dept, d.overdue) == ("Engineering", "1")
    (f,) = (tmp_path / "reports").iterdir()
    assert f.read_text() == "Ticket: T-0009\n"
