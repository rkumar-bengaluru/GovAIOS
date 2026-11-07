"""fill_form: fills from the answer bank with read-back; answer values never reach audit, stdout or result.json."""
import json

import pytest

from govaios import engine
from govaios.engine import Runner, Stop
from conftest import FakeDesktop, N

URL = "https://job-boards.greenhouse.io/acme/jobs/1"
SECRET = "SECRET-ANSWER"

FLOW = """workflow:
  id: test_apply
  version: 1
  browser: {{ application: chrome, account: x }}
  permissions:
    allow: [read_page{extra}]
    max_element_risk: modify
  destinations: ["https://job-boards.greenhouse.io"]
  steps:
    - {{ id: on_form, action: classify_page, on_match: {{ gh_form: continue, unknown: stop_and_report }} }}
    - {{ id: fill, action: fill_form }}
"""
PAGE = """page:
  id: gh_form
  identification: { title_matches: 'Job Application', anchors: [form_region] }
  elements:
    form_region: { role: form, risk: read }
"""


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine, "user_home", lambda: tmp_path)


class FormDesk(FakeDesktop):
    """build(desk) returns a fresh tree each snapshot (new handles); typing sets the value in the next tree.
    Input on a node from an older snapshot fails (a stale handle)."""

    def __init__(self, build, menu=False, keep=lambda t: t):
        super().__init__([])
        self.build, self.menu, self.keep = build, menu, keep
        self.values, self.gen, self.url = {}, 0, URL

    def web_root(self, app):
        self.gen += 1
        root = self.build(self)
        for n in root.walk():
            n.handle = self.gen
        return root

    def _fresh(self, node):
        assert node.handle == self.gen, "input on a stale node"

    def type_into(self, node, text):
        self._fresh(node)
        super().type_into(node, text)
        self.values[node.dom_id or node.name] = self.keep(text)

    def click(self, node):
        self._fresh(node)
        self.calls.append(("click", node.dom_id or node.name))
        self.values.setdefault("clicked", []).append(node.name)

    def focused_is(self, node):   # a handle from an older snapshot is not the focused element
        return node.handle == self.gen

    def menu_open(self):
        return self.menu

    def press(self, key):
        self.calls.append(key)
        if key == "enter" and self.menu:
            self.values["sel"] = self.typed


def form(*fields, title="Job Application for Engineer at Acme"):
    return N("document", title, children=[N("form", children=list(fields))])


def text_field(d, dom_id, label):
    return N("text_field", label, value=d.values.get(dom_id, ""), dom_id=dom_id)


def write_bank(home, rows):
    (home / "apply").mkdir(mode=0o700, exist_ok=True)
    (home / "apply" / "answers.yaml").write_text(json.dumps({"answers": rows}))


NOTICE = {"key": "notice", "labels": ["Notice period"], "answer": SECRET}


def run(tmp_path, desk, rows=(NOTICE,), allow=", fill_field", run_id="r1"):
    src = tmp_path / "src"
    (src / "flows").mkdir(parents=True)
    (src / "pages").mkdir()
    (src / "flows" / "test_apply.yaml").write_text(FLOW.format(extra=allow))
    (src / "pages" / "gh_form.yaml").write_text(PAGE)
    if rows is not None:
        write_bank(tmp_path, list(rows))
    r = Runner(src / "flows" / "test_apply.yaml", desk, tmp_path)
    r.approvals.approve_flow(r.flow["id"], r.digest)
    r.approvals.approve_destination(r.flow["id"], "https://job-boards.greenhouse.io")
    r.run_id = run_id
    try:
        r.run()
        err = None
    except Stop as e:
        err = e
    entries = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    return r, entries, err


def result(tmp_path):
    return json.loads((tmp_path / "apply" / "result.json").read_text())


def fills(entries):
    return [x for x in entries if x.get("action") == "fill_field" and x["kind"] == "action"]


def test_fills_bank_matches_and_audits_no_values(tmp_path, capsys):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period*")))
    r, e, err = run(tmp_path, d)
    assert err is None
    assert d.values["notice"] == SECRET
    [f] = fills(e)
    assert f["source"] == "bank:notice" and f["outcome"] == "done" and f["target"] == "Notice period"
    assert result(tmp_path) == {"run": "r1", "filled": 1, "total": 1, "yourself": [], "check": []}
    out = capsys.readouterr()
    assert "apply: filled 1 of 1" in out.out
    for blob in ((tmp_path / "audit.jsonl").read_text(), out.out, out.err,
                 (tmp_path / "apply" / "result.json").read_text()):
        assert SECRET not in blob


def test_no_result_file_without_run_id(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")))
    _, _, err = run(tmp_path, d, run_id=None)
    assert err is None and not (tmp_path / "apply" / "result.json").exists()


def test_existing_value_untouched(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")))
    d.values["notice"] = "admin typed"
    _, e, err = run(tmp_path, d)
    assert err is None and d.values["notice"] == "admin typed"
    assert not [c for c in d.calls if c[0] in ("type_into", "click")] and not fills(e)
    assert result(tmp_path)["check"] == ["Notice period"]


def test_refinds_field_after_rerender(tmp_path):
    def build(d):   # React re-render: structure and handles change every snapshot
        f = text_field(d, "notice", "Notice period")
        return form(*[N("group")] * (d.gen % 3), N("group", children=[f]))
    d = FormDesk(build)
    _, e, err = run(tmp_path, d)
    assert err is None and d.values["notice"] == SECRET
    assert result(tmp_path)["filled"] == 1


def test_conditional_field_second_pass(tmp_path):
    def build(d):
        fs = [text_field(d, "notice", "Notice period")]
        if d.values.get("notice"):
            fs.append(text_field(d, "why", "Why this notice"))
        return form(*fs)
    d = FormDesk(build)
    rows = (NOTICE, {"key": "why", "labels": ["Why this notice"], "answer": "SECRET-TWO"})
    _, e, err = run(tmp_path, d, rows)
    assert err is None and d.values["why"] == "SECRET-TWO"
    assert result(tmp_path) == {"run": "r1", "filled": 2, "total": 2, "yourself": [], "check": []}


def test_mismatch_clears_and_goes_to_yourself(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")), keep=lambda t: t[:5])
    _, e, err = run(tmp_path, d)
    assert err is None
    assert d.calls[-2:] == ["select_all", "delete_back"]
    assert fills(e)[0]["outcome"] == "mismatch"
    assert result(tmp_path)["yourself"] == ["Notice period"] and result(tmp_path)["filled"] == 0


def combo_form(n_options, registers=True, portal=False):
    def build(d):
        picked = registers and "Bengaluru" in d.values.get("clicked", [])
        group = [N("text", "Location"), N("combo_box", "Location", value=d.values.get("loc", "") if not picked else "",
                                         dom_id="loc")]
        if picked:
            group.append(N("text", "Bengaluru"))
        elif d.values.get("loc"):
            group.append(N("list", children=[N("group", "Bengaluru", children=[N("text", "Bengaluru")]) for _ in range(n_options)]
                           + [N("group", "Bengaluru North")]))
        nav = N("list", children=[N("text", "Bengaluru")])   # was there before typing: never a candidate
        top = [N("form", children=[N("group", children=group)])]
        if portal:   # a page-level node appears on typing, shifting the nav list's path so it looks new
            return N("document", "Job Application for Engineer",
                     children=top + [N("group")] * bool(d.values.get("loc")) + [nav])
        return N("document", "Job Application for Engineer", children=[nav] + top)
    return build


def test_combo_clicks_single_new_option_never_enter(tmp_path):
    d = FormDesk(combo_form(1))
    _, e, err = run(tmp_path, d, ({"key": "loc", "labels": ["Location"], "answer": "Bengaluru"},))
    assert err is None
    assert ("click", "Bengaluru") in d.calls and "enter" not in d.calls and "escape" not in d.calls
    assert fills(e)[0]["outcome"] == "done" and result(tmp_path)["filled"] == 1


@pytest.mark.parametrize("n", [0, 2])
def test_combo_no_or_many_options_escape(tmp_path, n):
    d = FormDesk(combo_form(n))
    _, e, err = run(tmp_path, d, ({"key": "loc", "labels": ["Location"], "answer": "Bengaluru"},))
    assert err is None
    assert "escape" in d.calls and "enter" not in d.calls and ("click", "Bengaluru") not in d.calls
    assert fills(e)[0]["outcome"] == "mismatch" and result(tmp_path)["yourself"] == ["Location"]
    assert d.calls[-2:] == ["select_all", "delete_back"]   # field re-found after escape (new handles), then cleared


def test_combo_option_click_not_registered_is_mismatch(tmp_path):
    d = FormDesk(combo_form(1, registers=False))   # the list stays open and the input still holds the typed text
    _, e, err = run(tmp_path, d, ({"key": "loc", "labels": ["Location"], "answer": "Bengaluru"},))
    assert err is None and ("click", "Bengaluru") in d.calls and "enter" not in d.calls
    assert fills(e)[0]["outcome"] == "mismatch" and result(tmp_path)["yourself"] == ["Location"]
    assert d.calls[-2:] == ["select_all", "delete_back"]


def test_combo_list_outside_form_never_a_candidate(tmp_path):
    d = FormDesk(combo_form(0, portal=True))
    _, e, err = run(tmp_path, d, ({"key": "loc", "labels": ["Location"], "answer": "Bengaluru"},))
    assert err is None and ("click", "Bengaluru") not in d.calls and "escape" in d.calls
    assert fills(e)[0]["outcome"] == "mismatch"


def select_form(d):
    opts = [N("native:AXMenuItem", o) for o in ("Select...", "Yes", "No")]
    return form(N("text", "Authorised to work"),
                N("popup_button", "", value=d.values.get("sel", "Select..."), dom_id="sel", children=opts))


@pytest.mark.parametrize("menu", [False, True])
def test_select_without_menu_escapes(tmp_path, menu):
    d = FormDesk(select_form, menu=menu)
    _, e, err = run(tmp_path, d, ({"key": "auth", "labels": ["Authorised to work"], "answer": "yes"},))
    assert err is None
    if menu:
        assert d.calls[-1] == "enter" and d.values["sel"] == "Yes" and fills(e)[0]["outcome"] == "done"
    else:
        assert "escape" in d.calls and "enter" not in d.calls and fills(e)[0]["outcome"] == "mismatch"
        assert result(tmp_path)["yourself"] == ["Authorised to work"]


def test_select_menu_closed_before_enter_escapes(tmp_path):
    d = FormDesk(select_form)
    states = iter([True, False])   # open on click, closed by the time Enter would go
    d.menu_open = lambda: next(states)
    _, e, err = run(tmp_path, d, ({"key": "auth", "labels": ["Authorised to work"], "answer": "yes"},))
    assert err is None and "enter" not in d.calls and "escape" in d.calls
    assert fills(e)[0]["outcome"] == "mismatch"


def test_fill_refuses_control_characters(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")))
    r, _, err = run(tmp_path, d, rows=(), run_id=None)   # a CLI run: the unmatched field isn't asked
    [f] = engine.read_form(r._form()[1])
    assert err is None and r.fill(f, "a\nb", "admin") is False
    assert not [c for c in d.calls if c[0] in ("type_into", "click")] and "notice" not in d.values


def test_radio_clicks_named_option(tmp_path):
    def build(d):
        picked = d.values.get("clicked", [])
        return form(N("text", "Relocate?"), N("group", children=[
            N("radio", o, value="1" if o in picked else "0") for o in ("Yes", "No")]))
    d = FormDesk(build)
    _, e, err = run(tmp_path, d, ({"key": "reloc", "labels": ["Relocate?"], "answer": "No"},))
    assert err is None and d.values["clicked"] == ["No"] and fills(e)[0]["outcome"] == "done"


def test_left_form_page_stops(tmp_path):
    def build(d):
        title = "Thanks | Acme" if d.values.get("notice") else "Job Application for Engineer"
        return form(text_field(d, "notice", "Notice period"), text_field(d, "why", "Why"), title=title)
    d = FormDesk(build)
    rows = (NOTICE, {"key": "why", "labels": ["Why"], "answer": "x"})
    _, e, err = run(tmp_path, d, rows)
    assert str(err) == "left the form page" and "why" not in d.values


def test_restricted_never_filled(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "g", "Gender"), N("text_field", "Password", dom_id="pw")))
    rows = ({"key": "g", "labels": ["Gender"], "answer": SECRET}, {"key": "pw", "labels": ["Password"], "answer": "p"})
    _, e, err = run(tmp_path, d, rows)
    assert err is None and not d.values and not fills(e)
    assert result(tmp_path)["yourself"] == ["Gender", "Password"]


def test_bank_error_stops_without_values(tmp_path, capsys):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")))
    (tmp_path / "apply").mkdir(mode=0o700)
    (tmp_path / "apply" / "answers.yaml").write_text(f"answers:\n  - key: notice\n    answer: {SECRET}\n  bad: [\n")
    _, e, err = run(tmp_path, d, rows=None)
    assert str(err).startswith("answer bank: YAML error at line") and SECRET not in str(err)
    out = capsys.readouterr()
    assert SECRET not in (tmp_path / "audit.jsonl").read_text() + out.out + out.err
    assert not d.values and not (tmp_path / "apply" / "result.json").exists()


def test_fill_denied_when_not_permitted(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")))
    _, e, err = run(tmp_path, d, allow="")
    assert str(err).startswith("denied fill_field") and not d.values


# ----- Task 8: asking the admin -----
import threading  # noqa: E402

from govaios import applyfiles  # noqa: E402

ASKED = ", fill_field, ask_admin"


def ask_form(d):
    opts = [N("native:AXMenuItem", o) for o in ("Select...", "Yes", "No")]
    return form(text_field(d, "why", "Why us"), N("text", "Sponsor"),
                N("popup_button", "", value=d.values.get("sel", "Select..."), dom_id="sel", children=opts))


def answer_when_asked(tmp_path, answers, seen):
    def go():
        for _ in range(2000):
            ask = applyfiles.read_json(tmp_path, applyfiles.ASK)
            if ask:
                seen.append(ask)
                applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": "other", "answers": {}})   # another run's
                applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": ask["run"], "answers": answers(ask)})
                return
            threading.Event().wait(0.005)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def test_ask_round_trip(tmp_path, capsys):
    d = FormDesk(ask_form)
    seen = []
    t = answer_when_asked(tmp_path, lambda a: {f["key"]: SECRET if f["kind"] == "text" else "" for f in a["fields"]}, seen)
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    t.join(1)
    assert err is None and d.values["why"] == SECRET
    [ask] = seen
    assert ask["run"] == "r1" and [(f["label"], f["kind"], f["options"]) for f in ask["fields"]] == [
        ("Why us", "text", []), ("Sponsor", "select", ["Select...", "Yes", "No"])]
    [f] = fills(e)
    assert f["source"] == "admin" and f["outcome"] == "done"
    assert d.calls.index("raise_pinned") < d.calls.index(("type_into", "why"))
    assert result(tmp_path) == {"run": "r1", "filled": 1, "total": 2, "yourself": ["Sponsor"], "check": []}
    assert not (tmp_path / "apply" / "ask.json").exists() and not (tmp_path / "apply" / "reply.json").exists()
    out = capsys.readouterr()
    assert SECRET not in (tmp_path / "audit.jsonl").read_text() + out.out + out.err + json.dumps(result(tmp_path))
    assert any(x.get("action") == "ask_admin" and x["decision"] == "allow" for x in e)


def test_ask_timeout_stops_and_cleans(tmp_path, monkeypatch):
    clock = iter(range(0, 10**6, 60))
    monkeypatch.setattr(engine.time, "time", lambda: next(clock))
    d = FormDesk(lambda d: form(text_field(d, "why", "Why us")))
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    assert str(err) == "no answer from admin" and not d.values and "raise_pinned" not in d.calls
    assert not (tmp_path / "apply" / "ask.json").exists() and not (tmp_path / "apply" / "reply.json").exists()


@pytest.mark.parametrize("label, value", [
    ("Nope", "x"), ("Sponsor", "Maybe"), ("Why us", "a\tb"), ("Why us", "x" * 2001), ("Why us", 3)])
def test_ask_bad_reply_stops(tmp_path, label, value):
    d = FormDesk(ask_form)
    keys = lambda a: {f["label"]: f["key"] for f in a["fields"]}   # noqa: E731
    t = answer_when_asked(tmp_path, lambda a: {keys(a).get(label, label): value}, [])
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    t.join(1)
    assert str(err) == "bad reply" and not d.values and "raise_pinned" not in d.calls
    assert not (tmp_path / "apply" / "reply.json").exists()


def test_cli_run_never_asks(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "why", "Why us")))
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED, run_id=None)
    assert err is None and not d.values and "raise_pinned" not in d.calls
    assert not any(x.get("action") == "ask_admin" for x in e)
    assert not (tmp_path / "apply" / "ask.json").exists()


def test_emergency_stop_while_waiting(tmp_path, monkeypatch):
    def sleep(s):
        assert (tmp_path / "apply" / "ask.json").exists()
        (tmp_path / "STOPPED").touch()
    monkeypatch.setattr(engine.time, "sleep", sleep)
    d = FormDesk(lambda d: form(text_field(d, "why", "Why us")))
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    assert str(err) == "emergency stop" and not d.values
    assert not (tmp_path / "apply" / "ask.json").exists()
