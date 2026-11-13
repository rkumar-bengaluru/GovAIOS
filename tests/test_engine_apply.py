"""fill_form: fills from the answer bank with read-back; answer values never reach audit, stdout or result.json."""
import json

import pytest

from govaios import engine
from govaios.engine import Runner, Stop
from govaios.desktop.macos import InputRefused
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
    - {{ id: fill, action: fill_form }}{attach}
"""
PAGE = """page:
  id: gh_form
  identification: { title_matches: 'Job Application', anchors: [form_region] }
  elements:
    form_region: { role: form, risk: read }
    attach_btn: { role: button, name: Attach, risk: modify }
    cv_input: { role: text, dom_id: cv, risk: read }
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


def write_bank(home, rows, cv=None):
    (home / "apply").mkdir(mode=0o700, exist_ok=True)
    (home / "apply" / "answers.yaml").write_text(json.dumps({"answers": rows, **({"cv_file": cv} if cv else {})}))


NOTICE = {"key": "notice", "labels": ["Notice period"], "answer": SECRET}


def run(tmp_path, desk, rows=(NOTICE,), allow=", fill_field", run_id="r1", attach="", cv=None, page=PAGE):
    src = tmp_path / "src"
    (src / "flows").mkdir(parents=True)
    (src / "pages").mkdir()
    (src / "flows" / "test_apply.yaml").write_text(FLOW.format(extra=allow, attach=attach))
    (src / "pages" / "gh_form.yaml").write_text(page)
    if rows is not None:
        write_bank(tmp_path, list(rows), cv)
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


def test_field_scrolled_into_view_before_click(tmp_path):
    # Greenhouse puts the form below the job description: an off-screen field fails the click-point check
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period*")))
    _, _, err = run(tmp_path, d)
    assert err is None
    i = d.calls.index(("click", "notice"))
    assert d.calls[i - 1] == "scroll"


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
    assert d.calls[-3:] == ["select_all", "delete_back", "escape"]   # re-found after escape, cleared, list closed


def test_combo_option_click_not_registered_is_mismatch(tmp_path):
    d = FormDesk(combo_form(1, registers=False))   # the list stays open and the input still holds the typed text
    _, e, err = run(tmp_path, d, ({"key": "loc", "labels": ["Location"], "answer": "Bengaluru"},))
    assert err is None and ("click", "Bengaluru") in d.calls and "enter" not in d.calls
    assert fills(e)[0]["outcome"] == "mismatch" and result(tmp_path)["yourself"] == ["Location"]
    assert d.calls[-3:] == ["select_all", "delete_back", "escape"]


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
        ("Why us", "text", []), ("Sponsor", "select", ["Yes", "No"])]
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
    monkeypatch.setattr(engine.time, "monotonic", lambda: next(clock))
    d = FormDesk(lambda d: form(text_field(d, "why", "Why us")))
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    assert str(err) == "no answer from admin" and not d.values and "raise_pinned" not in d.calls
    assert not (tmp_path / "apply" / "ask.json").exists() and not (tmp_path / "apply" / "reply.json").exists()


@pytest.mark.parametrize("label, value", [
    ("Nope", "x"), ("Sponsor", "Maybe"), ("Sponsor", "Select..."), ("Why us", "a\tb"), ("Why us", "x" * 2001), ("Why us", 3)])
def test_ask_bad_reply_stops(tmp_path, label, value):
    d = FormDesk(ask_form)
    keys = lambda a: {f["label"]: f["key"] for f in a["fields"]}   # noqa: E731
    t = answer_when_asked(tmp_path, lambda a: {keys(a).get(label, label): value}, [])
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    t.join(1)
    assert str(err) == "bad reply" and not d.values and "raise_pinned" not in d.calls
    assert not (tmp_path / "apply" / "reply.json").exists() and not (tmp_path / "apply" / "ask.json").exists()


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


def test_screen_locked_while_waiting(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: (tmp_path / "apply" / "ask.json").exists())
    d = FormDesk(lambda d: form(text_field(d, "why", "Why us")))
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    assert str(err) == "screen_locked" and not d.values and "raise_pinned" not in d.calls
    assert not (tmp_path / "apply" / "ask.json").exists()


def test_stale_reply_cleared_before_asking(tmp_path):
    applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": "r1", "answers": {"x": "old"}})   # left from an earlier ask
    d = FormDesk(ask_form)
    t = answer_when_asked(tmp_path, lambda a: {}, [])
    _, e, err = run(tmp_path, d, rows=(), allow=ASKED)
    t.join(1)
    assert err is None and result(tmp_path)["yourself"] == ["Why us", "Sponsor"]


ATTACH = "\n    - { id: attach, action: attach_file, target: current_page.attach_btn, check: current_page.cv_input }"
ALLOW_ATTACH = ", fill_field, click, attach_file"
CV = "Resume-Jane.pdf"


class CvDesk(FormDesk):
    def __init__(self, chooses=True, refuse=False, exc=None):
        super().__init__(lambda d: form(text_field(d, "notice", "Notice period"), N("button", "Attach"), N(
            "text", d.values.get("cv", "No file chosen"), dom_id="cv")))
        self.chooses, self.refuse, self.exc = chooses, refuse, exc

    def choose_file(self, path):
        super().choose_file(path)
        if self.refuse:
            raise (self.exc or InputRefused("input refused: no file sheet"))
        if self.chooses:
            self.values["cv"] = CV


@pytest.fixture
def touch_id_ok(monkeypatch):
    monkeypatch.setattr(engine.auth, "approve", lambda *a, **k: (True, "biometric"))


def attach(tmp_path, desk, cv="~/" + CV, make=True, rows=(NOTICE,), page=PAGE):
    if make:
        (tmp_path / CV).write_bytes(b"%PDF")
    return run(tmp_path, desk, rows=list(rows), allow=ALLOW_ATTACH, attach=ATTACH, cv=cv, page=page)


@pytest.mark.usefixtures('touch_id_ok')
def test_attach_skips_without_cv(tmp_path):
    desk = CvDesk()
    r, entries, err = attach(tmp_path, desk, cv=None)
    assert err is None and ("choose_file",) not in desk.calls
    assert result(tmp_path)["yourself"] == ["Resume/CV"]


@pytest.mark.usefixtures('touch_id_ok')
def test_attach_denied_goes_to_yourself(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.auth, "approve", lambda *a, **k: (False, "cancel"))
    desk = CvDesk()
    r, entries, err = attach(tmp_path, desk)
    assert err is None and ("choose_file",) not in desk.calls
    assert result(tmp_path)["yourself"] == ["Resume/CV"]


@pytest.mark.usefixtures('touch_id_ok')
def test_attach_happy_path(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setattr(engine.auth, "approve", lambda q, *a, **k: (asked.append(q), (True, "biometric"))[1])
    desk = CvDesk()
    r, entries, err = attach(tmp_path, desk)
    assert err is None and ("choose_file",) in desk.calls
    assert asked and CV in asked[-1] and str(tmp_path) not in asked[-1]
    assert str(tmp_path / CV) not in (tmp_path / "audit.jsonl").read_text()
    assert CV not in (tmp_path / "audit.jsonl").read_text() and result(tmp_path)["yourself"] == []


@pytest.mark.usefixtures('touch_id_ok')
def test_attach_still_no_file_goes_to_yourself(tmp_path):
    r, entries, err = attach(tmp_path, CvDesk(chooses=False))
    assert err is None and result(tmp_path)["yourself"] == ["Resume/CV"]


@pytest.mark.usefixtures('touch_id_ok')
def test_attach_refused_dialog_escapes(tmp_path):
    desk = CvDesk(refuse=True)
    r, entries, err = attach(tmp_path, desk)
    assert err is None and "escape" in desk.calls and result(tmp_path)["yourself"] == ["Resume/CV"]


@pytest.mark.usefixtures('touch_id_ok')
def test_result_rewritten_after_attach(tmp_path):
    r, entries, err = attach(tmp_path, CvDesk(chooses=False), rows=[NOTICE])
    assert err is None and result(tmp_path) == {"run": "r1", "filled": 1, "total": 1,
                                                "yourself": ["Resume/CV"], "check": []}


@pytest.mark.usefixtures('touch_id_ok')
@pytest.mark.parametrize("exc", [engine.Stop("emergency stop"), engine.Stop("screen_locked")])
def test_attach_run_stop_during_dialog_propagates(tmp_path, exc):
    desk = CvDesk(refuse=True, exc=exc)
    r, entries, err = attach(tmp_path, desk)
    assert err is exc and "escape" not in desk.calls
    assert entries[-1].get("outcome") != "done" and entries[-1]["kind"] != "flow_end"


@pytest.mark.usefixtures('touch_id_ok')
def test_attach_submit_rated_target_never_clicked(tmp_path):
    desk = CvDesk()
    r, entries, err = attach(tmp_path, desk, page=PAGE.replace("name: Attach, risk: modify", "name: Attach, risk: submit"))
    assert err is not None and "attach on a submit element denied" in str(err)
    assert ("choose_file",) not in desk.calls and "Attach" not in desk.values.get("clicked", [])


@pytest.mark.usefixtures('touch_id_ok')
def test_attach_missing_check_element_goes_to_yourself(tmp_path):
    desk = CvDesk()
    desk.build = lambda d: form(N("button", "Attach"))
    r, entries, err = attach(tmp_path, desk, rows=[])
    assert err is None and result(tmp_path)["yourself"] == ["Resume/CV"]


class StopAfterSheet(CvDesk):
    """The emergency stop lands while the engine waits for the page after the file sheet: STOPPED first, then SIGTERM."""

    def __init__(self, home):
        super().__init__()
        self.home, self.armed = home, False

    def choose_file(self, path):
        super().choose_file(path)
        (self.home / "STOPPED").touch()
        self.armed = True

    def web_root(self, app):
        if self.armed:
            raise engine.Stop("emergency stop")   # what the SIGTERM handler raises
        return super().web_root(app)


@pytest.mark.usefixtures('touch_id_ok')
def test_emergency_stop_after_file_sheet_ends_run(tmp_path):
    r, entries, err = attach(tmp_path, StopAfterSheet(tmp_path))
    assert str(err) == "emergency stop"
    assert not any(x.get("kind") == "flow_end" and x.get("outcome") == "done" for x in entries)
    assert result(tmp_path)["yourself"] == ["Resume/CV"]   # the card lists the CV until it is attached


@pytest.mark.usefixtures('touch_id_ok')
def test_stop_at_cv_prompt_leaves_cv_on_card(tmp_path, monkeypatch):
    def prompt(*a, **k):
        raise engine.Stop("emergency stop")
    monkeypatch.setattr(engine.auth, "approve", prompt)
    r, entries, err = attach(tmp_path, CvDesk())
    assert str(err) == "emergency stop" and result(tmp_path)["yourself"] == ["Resume/CV"]


# ----- capture on stop (dev mode: unmasked, for debugging a failed web run) -----
class RefusingDesk(FormDesk):
    why = "input refused: Chrome is not the frontmost app"   # stops the run (unlike a field's click point)

    def click(self, node):
        self.last_refusal = {"target": [{"role": "AXTextField", "name": node.name}],
                             "hit": [{"role": "AXGroup", "name": "overlay"}]}
        raise InputRefused(self.why)


class CoveredDesk(RefusingDesk):
    why = "input refused: click point is not on the target element (hit AXGroup contains target AXTextField)"


def captures(home):
    d = home / "captures"
    return sorted(d.iterdir()) if d.exists() else []


def test_stop_saves_capture_of_the_page(tmp_path):
    d = RefusingDesk(lambda d: form(text_field(d, "notice", "Notice period*")))
    _, e, err = run(tmp_path, d)
    assert "frontmost" in str(err)
    [p] = captures(tmp_path)
    assert p.stat().st_mode & 0o777 == 0o600
    c = json.loads(p.read_text())
    assert c["step"] == "fill" and "frontmost" in c["reason"]
    assert c["url"] == URL and c["refusal"]["hit"][0]["name"] == "overlay"
    assert any(n.get("name") == "Notice period*" for n in _flat(c["tree"]))
    [a] = [x for x in e if x.get("action") == "capture"]
    assert a["outcome"] == "done" and a["target"] == p.name and len(a["file_hash"]) == 64
    assert [x["kind"] for x in e[-2:]] == ["action", "stop"]   # captured before the stop is recorded
    assert "Notice period" not in json.dumps(a)   # the audit holds the fingerprint, never page content


def _flat(n):
    yield n
    for c in n.get("children", []):
        yield from _flat(c)


@pytest.mark.parametrize("why", ["locked", "emergency"])
def test_no_capture_when_locked_or_emergency_stop(tmp_path, monkeypatch, why):
    if why == "locked":
        monkeypatch.setattr(engine.auth, "screen_locked", lambda: True)
    else:
        monkeypatch.setattr(engine.runstate, "stopped", lambda home: True)
    _, e, err = run(tmp_path, RefusingDesk(lambda d: form(text_field(d, "notice", "Notice period*"))))
    assert err is not None and captures(tmp_path) == []


def test_no_capture_before_any_step(tmp_path):
    run(tmp_path, FormDesk(lambda d: form()))   # writes the flow and approves it
    r = Runner(tmp_path / "src" / "flows" / "test_apply.yaml", RefusingDesk(lambda d: form()), tmp_path,
               inputs={"unexpected": "x"})   # refused before the first step touches a page
    with pytest.raises(Stop, match="bad run input"):
        r.run()
    assert captures(tmp_path) == []


def test_captures_keep_only_the_last_thirty(tmp_path):
    from govaios import capture
    for _ in range(32):
        capture.save(tmp_path, "f", "s", "r", URL, "t", form(), None)
    assert len(captures(tmp_path)) == 30


def test_failed_capture_never_hides_the_stop(tmp_path):
    class Broken(RefusingDesk):
        def window_title(self, app):
            raise RuntimeError("AX gone")
    _, e, err = run(tmp_path, Broken(lambda d: form(text_field(d, "notice", "Notice period*"))))
    assert "frontmost" in str(err)
    assert [x["outcome"] for x in e if x.get("action") == "capture"] == ["error"]


def test_combo_showing_tail_of_option_is_filled(tmp_path):
    """Greenhouse Country: option "India +91" picked, the field then shows "+" "91"."""
    def build(d):
        picked = "India +91" in d.values.get("clicked", [])
        group = [N("combo_box", "Country", value="", dom_id="country")]
        if picked:
            group = [N("group", children=[N("text", value="+"), N("text", value="91")])] + group
        elif d.values.get("country"):
            group.append(N("list", children=[N("group", "India +91", children=[N("text", "India +91")])]))
        return N("document", "Job Application for Engineer", children=[N("form", children=[N("group", children=group)])])
    _, e, err = run(tmp_path, FormDesk(build), ({"key": "c", "labels": ["Country"], "answer": "India +91"},))
    assert err is None and fills(e)[0]["outcome"] == "done"


def test_combo_showing_other_text_is_mismatch(tmp_path):
    def build(d):
        picked = "India +91" in d.values.get("clicked", [])
        group = [N("combo_box", "Country", value="", dom_id="country")]
        if picked:
            group = [N("text", value="91")] + group   # not whole trailing words of "India +91"
        elif d.values.get("country"):
            group.append(N("list", children=[N("group", "India +91", children=[N("text", "India +91")])]))
        return N("document", "Job Application for Engineer", children=[N("form", children=[N("group", children=group)])])
    _, e, err = run(tmp_path, FormDesk(build), ({"key": "c", "labels": ["Country"], "answer": "India +91"},))
    assert fills(e)[0]["outcome"] == "mismatch"


@pytest.mark.parametrize("shown,ok", [("78479 56039", True), ("(784) 795-6039", True), ("+91 78479 56039", False)])
def test_phone_reformatted_as_typed(tmp_path, shown, ok):
    d = FormDesk(lambda d: form(text_field(d, "phone", "Phone")), keep=lambda t: shown)
    _, e, err = run(tmp_path, d, ({"key": "p", "labels": ["Phone"], "answer": "7847956039"},))
    assert fills(e)[0]["outcome"] == ("done" if ok else "mismatch")


def test_mismatch_saves_capture_before_clearing(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "phone", "Phone")), keep=lambda t: "+91 78479 56039")
    _, e, err = run(tmp_path, d, ({"key": "p", "labels": ["Phone"], "answer": "7847956039"},))
    assert err is None
    [p] = captures(tmp_path)
    c = json.loads(p.read_text())
    assert c["reason"] == "read-back mismatch: Phone"
    assert c["refusal"] == {"field": "Phone", "kind": "text", "expected": "7847956039", "read_back": "+91 78479 56039"}
    i = [x.get("action") for x in e].index("capture")
    assert e[i + 1]["action"] == "press"   # captured, then cleared


def test_combo_input_covered_by_placeholder_clicks_its_box(tmp_path):
    """Greenhouse 2026-11-08: an empty react-select input is 4 px wide under its "Select..." placeholder."""
    class Covered(FormDesk):
        def click(self, node):
            if node.role == "combo_box":
                raise InputRefused("input refused: click point is not on the target element (hit AXStaticText ...)")
            super().click(node)
    d = Covered(combo_form(1))
    _, e, err = run(tmp_path, d, ({"key": "loc", "labels": ["Location"], "answer": "Bengaluru"},))
    assert err is None and fills(e)[0]["outcome"] == "done"
    assert ("click", "Bengaluru") in d.calls


def test_combo_mismatch_closes_its_list(tmp_path):
    d = FormDesk(combo_form(0))   # no option matches
    _, e, err = run(tmp_path, d, ({"key": "loc", "labels": ["Location"], "answer": "Bengaluru"},))
    assert fills(e)[0]["outcome"] == "mismatch"
    assert d.calls[-3:] == ["select_all", "delete_back", "escape"]


# ----- a failed field: the admin fixes it in Chrome, then Continue or Skip on the panel -----
def fix_when_asked(tmp_path, d, choice, typed=None, seen=None):
    def go():
        for _ in range(2000):
            ask = applyfiles.read_json(tmp_path, applyfiles.ASK)
            if ask:
                (seen if seen is not None else []).append(ask)
                if typed is not None:
                    d.values["notice"] = typed   # the admin types it in Chrome
                applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": ask["run"], "card": choice})
                return
            threading.Event().wait(0.005)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t


def test_covered_field_goes_to_yourself_without_stopping(tmp_path):
    d = CoveredDesk(lambda d: form(text_field(d, "notice", "Notice period")))
    _, e, err = run(tmp_path, d, run_id=None)   # a CLI run: no card
    assert err is None
    assert fills(e)[0]["outcome"] == "mismatch"
    [p] = captures(tmp_path)
    c = json.loads(p.read_text())
    assert "not on the target element" in c["reason"] and c["refusal"]["hit"][0]["name"] == "overlay"


def test_fix_by_hand_continue_counts_as_filled(tmp_path, capsys):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")), keep=lambda t: t[:5])
    seen = []
    t = fix_when_asked(tmp_path, d, "continue", typed="15 days", seen=seen)
    _, e, err = run(tmp_path, d, allow=ASKED)
    t.join(1)
    cap = seen[0]["card"].pop("capture")   # the mismatch's saved page, shown on the card
    assert err is None and seen[0]["card"] == {"kind": "fix", "label": "Notice period", "job": "", "item": 0}
    assert (tmp_path / "captures" / cap).exists()
    assert "fields" not in seen[0]
    assert [(f["source"], f["outcome"]) for f in fills(e)] == [("bank:notice", "mismatch"), ("admin_manual", "done")]
    assert result(tmp_path)["filled"] == 1 and result(tmp_path)["yourself"] == []
    assert d.calls.index("delete_back") < d.calls.index("raise_pinned")   # cleared before handing it over
    assert not (tmp_path / "apply" / "ask.json").exists() and not (tmp_path / "apply" / "reply.json").exists()
    out = capsys.readouterr()
    assert "15 days" not in (tmp_path / "audit.jsonl").read_text() + out.out + out.err


@pytest.mark.parametrize("choice, typed", [("skip", "15 days"), ("continue", "")])
def test_fix_by_hand_skip_or_still_empty_is_yourself(tmp_path, choice, typed):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")), keep=lambda t: t[:5])
    t = fix_when_asked(tmp_path, d, choice, typed=typed)
    _, e, err = run(tmp_path, d, allow=ASKED)
    t.join(1)
    assert err is None and "raise_pinned" in d.calls
    assert result(tmp_path)["yourself"] == ["Notice period"] and result(tmp_path)["filled"] == 0


def test_fix_by_hand_bad_reply_stops(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "notice", "Notice period")), keep=lambda t: t[:5])
    t = fix_when_asked(tmp_path, d, "submit")
    _, e, err = run(tmp_path, d, allow=ASKED)
    t.join(1)
    assert str(err) == "bad reply" and "raise_pinned" not in d.calls


def test_covered_field_on_panel_run_asks_fix(tmp_path):
    d = CoveredDesk(lambda d: form(text_field(d, "notice", "Notice period")))
    t = fix_when_asked(tmp_path, d, "continue", typed="15 days")
    _, e, err = run(tmp_path, d, allow=ASKED)
    t.join(1)
    assert err is None and result(tmp_path)["filled"] == 1


def test_each_ask_is_unique_so_a_stale_reply_never_answers_the_next(tmp_path):
    d = FormDesk(lambda d: form(text_field(d, "a", "School"), text_field(d, "b", "College")), keep=lambda t: t[:1])
    seen = []
    def go():
        for _ in range(4000):
            ask = applyfiles.read_json(tmp_path, applyfiles.ASK)
            if ask and ask not in seen:
                seen.append(ask)
                applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": ask["run"], "card": "skip"})
            threading.Event().wait(0.002)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    rows = ({"key": "s", "labels": ["School"], "answer": "Uni"}, {"key": "c", "labels": ["College"], "answer": "Uni"})
    _, e, err = run(tmp_path, d, rows, allow=ASKED)
    assert err is None and [a["card"]["label"] for a in seen] == ["School", "College"]
    assert seen[0]["seq"] != seen[1]["seq"]   # same-label cards still differ, so their digests do too


def test_captures_are_pruned_per_flow(tmp_path):
    from govaios import capture
    capture.save(tmp_path, "job_apply", "s", "r", URL, "t", form(), None)
    for _ in range(31):
        capture.save(tmp_path, "web_sandbox", "s", "r", URL, "t", form(), None)
    names = [p.name for p in captures(tmp_path)]
    assert sum(n.endswith("-job_apply.json") for n in names) == 1 and len(names) == 31


@pytest.mark.parametrize("url, want", [
    ("https://fa-ewji.fa.ocs.oraclecloud.com/hcmUI/job/80708?utm=x", "Chrome went to fa-ewji.fa.ocs.oraclecloud.com, a site this flow does not know"),
    ("https://job-boards.greenhouse.io/x", "cannot read the page: a Chrome prompt (location, notifications) may be covering it")])
def test_unreadable_page_stop_names_the_site(url, want):
    from types import SimpleNamespace
    desk = SimpleNamespace(web_root=lambda app: None, current_url=lambda app: url)
    r = SimpleNamespace(d=desk, app="chrome", flow={"destinations": ["https://job-boards.greenhouse.io"]})
    with pytest.raises(engine.Stop) as e:
        engine.Runner.snapshot(r)
    assert str(e.value) == want
