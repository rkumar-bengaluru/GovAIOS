"""The type step: one value (literal, run input or bank answer) into one text field, never logged."""
import json

import pytest
import yaml

from govaios import engine
from govaios.engine import Runner, Stop, check_learned
from conftest import FakeDesktop, N

SITE = "http://localhost:8100"
PG = "localhost_form"


class Desk(FakeDesktop):
    """One page of text fields by name; select_all + delete_back clears the focused one."""

    def __init__(self, fields=(("Home address", "text_field", ""),)):
        super().__init__([])
        self.url = SITE + "/form"
        self.fields = [list(f) for f in fields]
        self.selected = None

    def current_url(self, app):
        return self.url

    def web_root(self, app):
        return N("document", "Form", children=[N(role, name, value=v) for name, role, v in self.fields])

    def _field(self, node):
        return next(f for f in self.fields if f[0] == node.name)

    def click(self, node):
        self.calls.append(("click", node.name))
        self.focus = node.name

    def press(self, key):
        self.calls.append(key)
        f = next(f for f in self.fields if f[0] == self.focus)
        if key == "select_all":
            self.selected = f[0]
        elif key == "delete_back" and self.selected == f[0]:
            f[2] = ""

    def type_into(self, node, text):
        self.calls.append(("type_into", node.name, text))
        self._field(node)[2] += text


def make(tmp_path, step, inputs=None, role="text_field", risk=None):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True, exist_ok=True), pages.mkdir(exist_ok=True)
    el = {"role": role, "name": "Home address", **({"risk": risk} if risk else {})}
    (pages / f"{PG}.yaml").write_text(yaml.safe_dump({"page": {
        "id": PG, "identification": {"title_matches": "^Form$", "anchors": []}, "elements": {"address": el}}}))
    f = flows / "tf.yaml"
    f.write_text(yaml.safe_dump({"workflow": {
        "id": "tf", "version": 1, "browser": {"application": "chrome", "account": "x"},
        "permissions": {"allow": ["type_text"], "max_element_risk": "modify"},
        **({"inputs": inputs} if inputs else {}),
        "destinations": [SITE], "steps": [{"id": "t", "action": "type", "target": f"{PG}.address", **step}]}}))
    return f


def go(tmp_path, monkeypatch, desk, step, inputs=None, given=None, **kw):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    r = Runner(make(tmp_path, step, inputs, **kw), desk, tmp_path, inputs=given)
    r.approvals.approve_flow("tf", r.digest)
    try:
        r.run()
    except Stop as e:
        return e
    return None


def typed(desk):
    return [c[1:] for c in desk.calls if c[0] == "type_into"]


def write_bank(home, rows):
    (home / "apply").mkdir(mode=0o700, exist_ok=True)
    (home / "apply" / "answers.yaml").write_text(json.dumps({"answers": rows}))


ADDR = {"address": {"pattern": "[^\x00-\x1f]{1,200}"}}


def test_type_literal_into_the_one_field(tmp_path, monkeypatch):
    d = Desk()
    assert go(tmp_path, monkeypatch, d, {"value": "9 Willow Terrace"}) is None
    assert typed(d) == [("Home address", "9 Willow Terrace")]


def test_type_from_input(tmp_path, monkeypatch):
    d = Desk()
    assert go(tmp_path, monkeypatch, d, {"value_from": "input.address"}, ADDR, {"address": "1 Elm Rd"}) is None
    assert typed(d) == [("Home address", "1 Elm Rd")]


def test_type_from_bank(tmp_path, monkeypatch):
    write_bank(tmp_path, [{"key": "city", "labels": ["City"], "answer": "Pune"}])
    d = Desk()
    assert go(tmp_path, monkeypatch, d, {"bank": "city"}) is None
    assert typed(d) == [("Home address", "Pune")]


def test_type_bank_key_missing_stops(tmp_path, monkeypatch):
    write_bank(tmp_path, [{"key": "town", "labels": ["Town"], "answer": "Pune"}])
    d = Desk()
    assert str(go(tmp_path, monkeypatch, d, {"bank": "city"})) == "answer bank has no city"
    assert typed(d) == []


def test_type_target_missing_stops(tmp_path, monkeypatch):
    d = Desk(fields=(("Other", "text_field", ""),))
    assert isinstance(go(tmp_path, monkeypatch, d, {"value": "x"}), Stop)
    assert typed(d) == []


def test_type_target_twice_stops(tmp_path, monkeypatch):
    d = Desk(fields=(("Home address", "text_field", ""), ("Home address", "text_field", "")))
    assert "expected 1 element, found 2" in str(go(tmp_path, monkeypatch, d, {"value": "x"}))
    assert typed(d) == []


def test_type_into_secure_field_stops(tmp_path, monkeypatch):
    d = Desk(fields=(("Home address", "native:AXSecureTextField", ""),))
    e = go(tmp_path, monkeypatch, d, {"value": "x"}, role="native:AXSecureTextField")
    assert "password" in str(e) and typed(d) == []


def test_type_replaces_a_prefilled_field(tmp_path, monkeypatch):
    d = Desk(fields=(("Home address", "text_field", "Old Street"),))
    assert go(tmp_path, monkeypatch, d, {"value": "9 Willow Terrace"}) is None
    assert d.fields[0][2] == "9 Willow Terrace"
    assert d.calls.index("select_all") < d.calls.index("delete_back") < d.calls.index(typed_call(d))


def typed_call(d):
    return next(c for c in d.calls if c[0] == "type_into")


def test_type_value_that_does_not_hold_stops(tmp_path, monkeypatch):
    d = Desk(fields=(("Home address", "text_field", "Old Street"),))
    d.press = lambda key: d.calls.append(key)   # the clear does nothing
    assert str(go(tmp_path, monkeypatch, d, {"value": "9 Willow"})) == "typed value did not hold: Home address"


def test_type_value_never_in_audit(tmp_path, monkeypatch):
    d = Desk(fields=(("Home address", "text_field", ""), ("Town", "text_field", "")))
    make(tmp_path, {})   # page file, then a second element and step for the input
    flow = tmp_path / "apps" / "flows" / "tf.yaml"
    page = tmp_path / "apps" / "pages" / f"{PG}.yaml"
    p = yaml.safe_load(page.read_text())
    p["page"]["elements"]["town"] = {"role": "text_field", "name": "Town"}
    page.write_text(yaml.safe_dump(p))
    w = yaml.safe_load(flow.read_text())
    w["workflow"]["inputs"] = ADDR
    w["workflow"]["steps"] = [{"id": "t1", "action": "type", "target": f"{PG}.address", "value": "SECRET-LITERAL"},
                              {"id": "t2", "action": "type", "target": f"{PG}.town", "value_from": "input.address"}]
    flow.write_text(yaml.safe_dump(w))
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    r = Runner(flow, d, tmp_path, inputs={"address": "SECRET-INPUT"})
    r.approvals.approve_flow("tf", r.digest)
    r.run()
    text = (tmp_path / "audit.jsonl").read_text()
    assert "SECRET-LITERAL" not in text and "SECRET-INPUT" not in text
    srcs = [e["source"] for e in map(json.loads, text.splitlines()) if e.get("action") == "type_text" and "source" in e]
    assert srcs == ["literal", "input.address"]


def test_type_input_with_newline_refused_at_start(tmp_path, monkeypatch):
    d = Desk()
    e = go(tmp_path, monkeypatch, d, {"value_from": "input.address"}, ADDR, {"address": "a\nb"})
    assert str(e) == "bad run input" and typed(d) == [] and d.calls == []


def test_type_literal_with_newline_refused(tmp_path, monkeypatch):
    d = Desk()
    assert "control character" in str(go(tmp_path, monkeypatch, d, {"value": "a\nb"})) and typed(d) == []
    with pytest.raises(Stop, match="control character"):
        check_learned([{"id": "c", "action": "classify_page", "on_match": {PG: {"do": [
            {"id": "t", "action": "type", "target": f"{PG}.address", "value": "a\nb"}], "then": "end"}}}])


def test_type_above_modify_refused(tmp_path, monkeypatch):
    d = Desk()
    assert "denied" in str(go(tmp_path, monkeypatch, d, {"value": "x"}, risk="submit")) and typed(d) == []


def learned(*steps):
    return [{"id": "c", "action": "classify_page", "on_match": {PG: {"do": list(steps), "then": "end"}}}]


def test_check_learned_type_needs_one_source():
    t = {"id": "t", "action": "type", "target": f"{PG}.address"}
    msg = "learned steps: type needs one of value, value_from, bank"
    for src in ({}, {"value": "x", "bank": "city"}, {"value_from": "input.a", "bank": "city"}):
        with pytest.raises(Stop) as e:
            check_learned(learned({**t, **src}))
        assert str(e.value) == msg
    check_learned(learned({**t, "value_from": "input.nope"}))   # inputs not passed: names unchecked
    with pytest.raises(Stop, match="not an input"):
        check_learned(learned({**t, "value_from": "input.nope"}), None, {"address": {}})
    check_learned(learned({**t, "value_from": "input.address"}), None, {"address": {}})
    rep = {"id": "r", "action": "repeat", "item": f"{PG}.row", "max": 2, "steps": [
        {"id": "r1", "action": "click", "target": f"{PG}.row"}, {**t, "id": "r2"}]}
    with pytest.raises(Stop, match="type needs one of"):   # inside a repeat too
        check_learned(learned(rep))
