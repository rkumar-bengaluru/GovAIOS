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


# ---------- Task 5: teach this page (an unknown page in a JobLens panel run) ----------

import test_job_apply_flow as ja
from test_job_apply_flow import env, fast_clock  # noqa: F401  (fixtures)
from govaios import applyfiles, terms

ODD = "https://apply.example.invalid/x"   # Acme's job link: a site the flow doesn't know
LOOK = {"down": False, "pt": (0, 0), "hit": None, "focus": None, "url": ODD, "title": "Somewhere else", "tab": True,
        "web": "w1"}


class TeachDesk(ja.ApplyDesk):
    def __init__(self, samples=(), forever=None):
        super().__init__(ja.GH, links={"Staff Engineer": ODD})
        self.samples, self.forever = list(samples), forever

    def web_root(self, app):
        if self.url == ODD:
            return N("document", "Somewhere else", children=[N("button", "Apply Now", handle="b1")])
        return super().web_root(app)

    def observe_sample(self, app):
        return dict(self.forever) if self.forever else self.samples.pop(0)   # none left: raises, as a closed window


def answer_cards(tmp_path, choose, seen):
    """ja.answer_cards, but a None choice leaves the card unanswered (the teaching card ends by itself)."""
    import threading
    import time
    done = threading.Event()

    def go():
        while not done.is_set():
            ask = applyfiles.read_json(tmp_path, applyfiles.ASK)
            if ask and "card" in ask and applyfiles.read_json(tmp_path, applyfiles.REPLY) is None:
                seen.append(ask["card"])
                c = choose(ask["card"])
                if c is not None:
                    applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": ask["run"], "card": c})
                while applyfiles.read_json(tmp_path, applyfiles.ASK) == ask and not done.is_set():
                    time.sleep(0.002)
            time.sleep(0.002)
    threading.Thread(target=go, daemon=True).start()
    return done


def teach_run(tmp_path, monkeypatch, desk, answers, allow_teach=True, run_id="r1"):
    """job_apply with `teach` allowed (a copy); answers: card kind -> reply (a callable gets the card); the teaching
    card is left to end by itself unless answered."""
    wf = yaml.safe_load(ja.FLOW.read_text())
    allow = wf["workflow"]["permissions"]["allow"]
    allow[:] = [a for a in allow if a != "teach"] + (["teach"] if allow_teach else [])
    flow = tmp_path / "job_apply.yaml"
    flow.write_text(yaml.safe_dump(wf))
    monkeypatch.setattr(ja, "FLOW", flow)
    monkeypatch.setattr(ja, "answer_cards", answer_cards)
    answers = {"teaching": None, **answers}
    live = []
    write = engine.write_json
    monkeypatch.setattr(engine, "write_json", lambda h, n, o: (live.append(o) if n == applyfiles.LESSON_LIVE else None,
                                                               write(h, n, o))[1])
    seen = []
    choose = lambda c: (lambda a: a(c) if callable(a) else a)(answers.get(c["kind"], "next"))  # noqa: E731
    e, tasks, err = ja.run_apply(tmp_path, desk, choose=choose, seen=seen, run_id=run_id)
    return e, tasks, err, seen, live


def lessons_written(tmp_path):
    d = tmp_path / "lessons"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


@pytest.mark.usefixtures("env", "fast_clock")
def test_unknown_page_offers_teach_and_skip_keeps_old_stop(tmp_path, monkeypatch):
    e, tasks, err, seen, _ = teach_run(tmp_path, monkeypatch, TeachDesk(), {"new_page": "skip"})
    assert err is None and [(t["status"], t.get("reason")) for t in tasks] == [("stopped", "unexpected page"), ("done", None)]
    assert [c["kind"] for c in seen] == ["new_page", "stopped", "review"]
    assert seen[0]["label"] == "A page this flow does not know" and not lessons_written(tmp_path)


@pytest.mark.usefixtures("env", "fast_clock")
def test_teach_records_lesson_and_stops_task(tmp_path, monkeypatch):
    def terms_ok(card):
        assert card["label"] == "https://apply.example.invalid"
        terms.record(tmp_path, ODD, "allowed", "https://example.invalid/terms", "personal use is fine")
        return "checked"
    desk = TeachDesk([LOOK, {**LOOK, "down": True, "hit": "b1"}])   # then the samples run out: the tab is gone
    e, tasks, err, seen, live = teach_run(tmp_path, monkeypatch, desk,
                                          {"new_page": "teach", "terms": terms_ok, "lesson": "approved"})
    assert err is None and e[-1]["kind"] == "flow_end"
    assert tasks[0]["status"] == "stopped" and tasks[0]["reason"].startswith("page learned")
    assert tasks[1]["status"] == "done"   # the next job ran
    assert [c["kind"] for c in seen] == ["new_page", "terms", "teaching", "lesson", "stopped", "review"]
    [name] = lessons_written(tmp_path)
    assert seen[3]["label"] == name
    lesson = json.loads((tmp_path / "lessons" / name).read_text())
    assert [ev["kind"] for p in lesson["pages"] for ev in p["events"]] == ["click"]
    [rec] = [x for x in e if x["kind"] == "lesson"]
    assert (rec["outcome"], rec["target"], rec["item"]) == ("recorded", name, 1)
    # first contact with the new site went through Touch ID
    assert any(x.get("action") == "read_page" and x.get("approver") == "admin" and "example.invalid" in x["destination"]
               for x in e)
    assert live == [{"run": "r1", "lines": ["clicked Apply Now"]}]
    assert not (tmp_path / applyfiles.LESSON_LIVE).exists()


def test_fill_line_shows_length_never_the_value():
    assert engine._lesson_line({"kind": "fill", "label": "Email", "value": "a@example.invalid", "secure": False}) \
        == "Email ← 17 chars"
    assert engine._lesson_line({"kind": "fill", "label": "Password", "value": "", "secure": True}) == "Password ← hidden"


@pytest.mark.usefixtures("env", "fast_clock")
def test_forbidden_terms_never_reads_the_page(tmp_path, monkeypatch):
    def terms_no(card):
        terms.record(tmp_path, ODD, "forbidden", "https://example.invalid/terms", "no bots")
        return "checked"
    desk = TeachDesk([LOOK])
    e, tasks, err, seen, live = teach_run(tmp_path, monkeypatch, desk, {"new_page": "teach", "terms": terms_no})
    assert tasks[0]["reason"] == "site terms do not allow a personal agent" and tasks[1]["status"] == "done"
    assert not any(x.get("action") == "read_page" and "example.invalid" in (x.get("destination") or "") for x in e)
    assert desk.samples == [LOOK] and not lessons_written(tmp_path) and not live


@pytest.mark.usefixtures("env", "fast_clock")
def test_cancel_writes_no_lesson(tmp_path, monkeypatch):
    terms.record(tmp_path, ODD, "allowed", "https://example.invalid/terms", "ok")   # checked before: no terms card
    desk = TeachDesk(forever={**LOOK, "down": True, "hit": "b1"})   # never ends by itself
    e, tasks, err, seen, _ = teach_run(tmp_path, monkeypatch, desk, {"new_page": "teach", "teaching": "cancel"})
    assert tasks[0]["reason"] == "lesson cancelled" and [c["kind"] for c in seen][:2] == ["new_page", "teaching"]
    assert not lessons_written(tmp_path) and not any(x["kind"] == "lesson" for x in e)
    assert not (tmp_path / applyfiles.LESSON_LIVE).exists()


@pytest.mark.usefixtures("env", "fast_clock")
def test_flow_without_teach_permission_stops_as_before(tmp_path, monkeypatch):
    e, tasks, err, seen, _ = teach_run(tmp_path, monkeypatch, TeachDesk(), {}, allow_teach=False)
    assert tasks[0]["reason"] == "unexpected page" and [c["kind"] for c in seen] == ["stopped", "review"]


@pytest.mark.usefixtures("env", "fast_clock")
def test_cli_run_never_teaches(tmp_path, monkeypatch):
    e, tasks, err, seen, _ = teach_run(tmp_path, monkeypatch, TeachDesk(), {}, run_id=None)
    assert seen == [] and not lessons_written(tmp_path)
    assert [x["reason"] for x in e if x.get("action") == "task_stop"][0] == "unexpected page"


def test_teach_needs_the_pinned_window(tmp_path):
    r = Runner.__new__(Runner)
    with pytest.raises(Stop, match="teach needs the pinned browser window"):
        r.teach("x")


@pytest.mark.usefixtures("env", "fast_clock")
def test_idle_teaching_ends_and_an_empty_lesson_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "TEACH_IDLE_S", -1)   # idle at once: no event ever came
    terms.record(tmp_path, ODD, "allowed", "https://example.invalid/terms", "ok")
    e, tasks, err, seen, live = teach_run(tmp_path, monkeypatch, TeachDesk(forever=LOOK), {"new_page": "teach"})
    assert tasks[0]["reason"] == "lesson cancelled" and tasks[1]["status"] == "done"
    assert not lessons_written(tmp_path) and not live


@pytest.mark.usefixtures("env", "fast_clock")
def test_denied_touch_id_never_reads_or_captures_the_site(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.auth, "approve", lambda *a, **k: (False, "biometric"))
    terms.record(tmp_path, ODD, "allowed", "https://example.invalid/terms", "ok")
    desk = TeachDesk([LOOK])
    e, tasks, err, seen, live = teach_run(tmp_path, monkeypatch, desk, {"new_page": "teach"})
    assert tasks[0]["reason"].startswith("denied read_page") and tasks[1]["status"] == "done"
    assert not any(x.get("action") == "capture" and x.get("outcome") == "done" and x.get("item") == 1 for x in e)
    assert not (tmp_path / "captures").exists() and desk.samples == [LOOK] and not lessons_written(tmp_path)


@pytest.mark.usefixtures("env", "fast_clock")
def test_teach_approval_is_not_remembered(tmp_path, monkeypatch):
    terms.record(tmp_path, ODD, "allowed", "https://example.invalid/terms", "ok")
    desk = TeachDesk([LOOK, {**LOOK, "down": True, "hit": "b1"}])
    e, tasks, err, seen, _ = teach_run(tmp_path, monkeypatch, desk, {"new_page": "teach", "lesson": "approved"})
    assert tasks[0]["reason"].startswith("page learned")
    from govaios.approvals import Approvals
    assert not Approvals(tmp_path / "approvals.json").destination_ok("job_apply", "https://apply.example.invalid")


@pytest.mark.usefixtures("env", "fast_clock")
def test_leaving_the_site_ends_the_lesson_without_reading_the_other_site(tmp_path, monkeypatch):
    terms.record(tmp_path, ODD, "allowed", "https://example.invalid/terms", "ok")
    other = {**LOOK, "url": "https://elsewhere.example.org/p", "title": "Elsewhere"}
    desk = TeachDesk([LOOK, {**LOOK, "down": True, "hit": "b1"}, other, {**other, "down": True, "hit": "b1"}])
    e, tasks, err, seen, live = teach_run(tmp_path, monkeypatch, desk, {"new_page": "teach", "lesson": "approved"})
    assert tasks[0]["reason"].startswith("page learned")
    [name] = lessons_written(tmp_path)
    lesson = json.loads((tmp_path / "lessons" / name).read_text())
    assert [p["title"] for p in lesson["pages"]] == ["Somewhere else"]
    assert live[-1]["lines"] == ["clicked Apply Now", "left elsewhere.example.org: lesson ended"]
    assert len(desk.samples) == 1   # stopped at the first look at the other site


@pytest.mark.parametrize("after, job2", [(None, "done"), ("revoke", "revoked"), ("other", "revoked")])
@pytest.mark.usefixtures("env", "fast_clock")
def test_approving_a_lesson_keeps_the_run_and_a_real_revoke_still_stops(tmp_path, monkeypatch, after, job2):
    from govaios.approvals import Approvals
    terms.record(tmp_path, ODD, "allowed", "https://example.invalid/terms", "ok")
    ap = Approvals(tmp_path / "approvals.json")

    def approved(card):   # the panel's approve_lesson: approvals.json now holds the new flow's digest
        ap.approve_flow("job_apply", "n" * 64)
        return "approved"

    def stopped(card):   # job 1's stop card, after the lesson: the admin revokes, or approves yet another version
        if after == "revoke":
            ap.revoke_flow("job_apply")
        elif after == "other":
            ap.approve_flow("job_apply", "o" * 64)
        return "next"
    desk = TeachDesk([LOOK, {**LOOK, "down": True, "hit": "b1"}])
    e, tasks, err, seen, _ = teach_run(tmp_path, monkeypatch, desk,
                                       {"new_page": "teach", "lesson": approved, "stopped": stopped})
    assert tasks[0]["reason"].startswith("page learned")
    if job2 == "done":
        assert err is None and tasks[1]["status"] == "done"
    else:
        assert str(err) == "revoked"
