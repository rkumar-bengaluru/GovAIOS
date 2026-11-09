"""job_apply flow (app JobLens): each Ready JobLens job -> Himalayas Apply -> Greenhouse or Lever form, filled and CV
attached, never submitted; one panel task per job."""
import itertools
import json
import threading
import time
import types

import pytest
import yaml

from govaios import engine
from govaios.approvals import Approvals, pages_used, read_bound
from govaios.engine import REPO, Runner
from govaios.panel.apps import list_apps, match
from govaios.policy import decide
from conftest import ACCT, FakeDesktop, N, google_home

FLOW = REPO / "flows" / "job_apply.yaml"
JOB = "https://himalayas.app/companies/acme-test/jobs/staff-engineer"
GH = "https://job-boards.greenhouse.io/acmetest/jobs/1234567"
LV = "https://jobs.lever.co/acmetest/0000-1111/apply"
DESTS = ["https://www.google.com", "http://localhost:8100", "https://himalayas.app", "https://job-boards.greenhouse.io", "https://jobs.lever.co"]
NEW_PAGES = ("joblens_applications", "joblens_job", "himalayas_job_apply", "himalayas_apply_prompt", "himalayas_job_logged_out", "greenhouse_application", "lever_application")
CV = "Resume-Test.pdf"
SECRET = "SECRET-NOTICE"   # an answer value: must never reach the audit log or output


def submit_elements():
    for pid in NEW_PAGES:
        page = yaml.safe_load((REPO / "pages" / f"{pid}.yaml").read_text())["page"]
        for el, spec in page["elements"].items():
            if spec["risk"] == "submit":
                yield pid, el


def test_flow_loads_and_binds_pages():
    digest, raw = read_bound(FLOW, REPO / "pages")
    wf = yaml.safe_load(raw[FLOW])["workflow"]
    assert pages_used(wf) == {"google_home", "joblens_applications", "joblens_job", "himalayas_job_apply", "himalayas_apply_prompt", "himalayas_logged_out", "himalayas_job_logged_out",
                              "greenhouse_application", "lever_application"}
    assert (wf["id"], wf["app"], wf["permissions"]["max_element_risk"], wf["destinations"]) == \
        ("job_apply", "JobLens", "modify", DESTS)
    assert "close_window" not in json.dumps(wf["steps"]) and "inputs" not in wf


@pytest.mark.parametrize("pid,el", list(submit_elements()))
def test_submit_buttons_denied(pid, el, tmp_path):
    wf = yaml.safe_load(FLOW.read_text())["workflow"]
    risk = yaml.safe_load((REPO / "pages" / f"{pid}.yaml").read_text())["page"]["elements"][el]["risk"]
    assert decide({"action": "click", "risk": risk}, wf, Approvals(tmp_path / "a.json")) == "deny"


def test_submit_elements_are_the_expected_ones():
    assert set(submit_elements()) == {
        ("himalayas_job_apply", "save_link"), ("himalayas_job_apply", "save_button"),
        ("himalayas_job_apply", "job_expired"), ("himalayas_apply_prompt", "ai_cover_letter"),
        ("himalayas_apply_prompt", "ai_resume"), ("greenhouse_application", "submit"),
        ("greenhouse_application", "autofill"), ("lever_application", "submit"), ("lever_application", "linkedin"),
        ("joblens_job", "mark_submitted")}


def test_other_host_denied(tmp_path):
    wf = yaml.safe_load(FLOW.read_text())["workflow"]
    assert decide({"action": "read_page", "risk": "read", "destination": "https://apply.workable.com/x"},
                  wf, Approvals(tmp_path / "a.json")) == "deny"


def test_list_apps_shows_job_apply(tmp_path):
    apps = list_apps(REPO / "flows", tmp_path)
    by_id = {a.id: a.name for a in apps}
    assert by_id["job_apply"] == "JobLens" and by_id["web_sandbox"] == "Web Sandbox"
    assert by_id["himalayas_job_vetting"] == "SyncJobLens" and "morning_inbox_briefing" in by_id
    assert match("run joblens", apps)[1].id == "job_apply"
    assert match("syncjoblens", apps)[1].id == "himalayas_job_vetting"


def test_existing_flow_digests_unchanged():
    # the vetting flow changed only its app name (JobLens -> SyncJobLens, 2026-11-08): re-approved once
    raw = read_bound(REPO / "flows" / "himalayas_job_vetting.yaml", REPO / "pages")[1]
    text = raw[REPO / "flows" / "himalayas_job_vetting.yaml"].decode()
    assert "  app: SyncJobLens\n" in text and yaml.safe_load(text)["workflow"]["version"] == 3
    assert read_bound(REPO / "flows" / "morning_inbox_briefing.yaml", REPO / "pages")[0] == \
        "f949509d8a962723981d11a16c1aae944a42dc4f73d7441d8eee3d6ff31abc8b"


# ---------- end to end on fake trees ----------

def _page(pid):
    return yaml.safe_load((REPO / "pages" / f"{pid}.yaml").read_text())["page"]


# every submit-rated element of every page the flow uses: the fake desktop refuses to click any of them
SUBMIT_SPECS = [spec for pid in sorted(pages_used(yaml.safe_load(FLOW.read_text())["workflow"]))
                for spec in _page(pid)["elements"].values() if spec["risk"] == "submit"]


def test_submit_guard_covers_himalayas_and_forms():
    names = {s.get("name") or s.get("dom_id") for s in SUBMIT_SPECS}
    assert {"Save", "Job expired?", "Submit application", "Autofill my application", "btn-submit",
            "Apply with LinkedIn"} <= names


def job_page(logged_in=True):
    kind = "button" if logged_in else "link"   # Save / Apply now are links when logged out
    apply = lambda: [N("heading", "Apply now"), N("button", "Job expired?"), N(kind, "Apply now")]  # noqa: E731
    # as the live page: the Apply block appears twice inside main
    return N("document", "Acme Test hiring Staff Engineer | Himalayas", children=[
        N("banner", children=[] if logged_in else [N("link", "Log in")]),
        N("main", children=[N("heading", "Staff Engineer"), N("link", "Acme Test"), N(kind, "Save"),
                            N("article", children=[N("text", "A job.")]), *apply(),
                            N("navigation", "Breadcrumbs"), *apply()])])


def test_apply_button_is_the_first_of_the_repeated_blocks():
    root, page = job_page(), _page("himalayas_job_apply")
    first = next(n for n in root.walk() if n.role == "button" and n.name == "Apply now")
    assert [id(n) for n in engine.find_all(root, page["elements"]["apply_button"], page)] == [id(first)]


@pytest.mark.parametrize("logged_in,want", [(True, "himalayas_job_apply"), (False, "himalayas_job_logged_out")])
def test_job_page_classified_by_login_state(logged_in, want):
    each = next(s for s in yaml.safe_load(FLOW.read_text())["workflow"]["steps"] if s["id"] == "each_job")
    guard = next(s for s in each["steps"] if s["id"] == "authentication_guard")
    hits = [p for p in guard["on_match"] if p != "unknown" and engine.identify(_page(p), job_page(logged_in))]
    assert hits == [want]
    assert guard["on_match"][want] == ("continue" if logged_in else "stop_and_request_user")


def greenhouse(d):
    v = d.values
    combo_kids = [N("combo_box", "Will you require visa sponsorship?*", value="", dom_id="question_1000000002")]
    if v.get("sel"):
        combo_kids.append(N("text", v["sel"]))
    if d.open_list:   # react-select: the option list appears as a new list inside the form once opened
        combo_kids.append(N("list", children=[N("group", "Yes", children=[N("text", "Yes")]),
                                              N("group", "No", children=[N("text", "No")])]))
    tf = lambda i, label: N("text_field", label, value=v.get(i, ""), dom_id=i)   # noqa: E731
    return N("document", "Job Application for Staff Engineer at Acme Test", children=[
        N("button", "Autofill my application"),
        N("group", dom_id="application-form", children=[
            tf("first_name", "First Name*"), tf("last_name", "Last Name*"), tf("email", "Email*"),
            N("group", "Resume/CV", children=[
                N("button", "Attach"),
                N("button", f"Attach: {v.get('cv', 'No file chosen')}", dom_id="resume")]),
            tf("question_1000000001", "Notice period*"),
            N("group", children=combo_kids),
            N("combo_box", "Gender", value="", dom_id="gender"),   # demographic: never auto-filled
            N("button", "Submit application")])])


def lever(d):
    v = d.values
    radios = [N("radio", o, value="1" if v.get("radio") == o else "0") for o in ("Yes", "No")]
    return N("document", "Acme Test - Staff Engineer", children=[
        N("button", "Apply with LinkedIn"),
        N("group", dom_id="application-form", children=[
            N("group", children=[
                N("link", "ATTACH RESUME/CV"),
                N("button", f"Resume/CV ✱ ATTACH RESUME/CV: {v.get('cv', 'No file chosen')}",
                  dom_id="resume-upload-input")]),
            N("text_field", "Full name✱", value=v.get("Full name✱", "")),
            N("text_field", "Email✱", value=v.get("Email✱", "")),
            N("group", children=[N("group", children=[N("text", "Notice period?")]),
                                 N("text_field", "", value=v.get("q1", ""))]),   # employer question, unnamed
            N("group", children=[N("group", children=[N("text", "Are you authorised to work in Testland?")]),
                                 N("group", children=radios)]),
            N("button", "SUBMIT APPLICATION", dom_id="btn-submit")])])


JL = "http://localhost:8100/"
JOBS = [("Acme Test", "Staff Engineer", "Ready"), ("Old Corp", "Engineer", "Submitted"), ("Beta Test", "Lead", "Ready")]


def joblens_list():
    row = lambda c, t, st: N("row", children=[   # noqa: E731
        N("cell", children=[N("text", c)]), N("cell", children=[N("link", t)]),
        N("cell", children=[N("text", "Himalayas")]), N("cell", children=[N("text", st)])])
    head = N("row", children=[N("cell", children=[N("text", h)]) for h in ("Client", "Role", "Source", "Status")])
    return N("document", "JobLens", children=[N("heading", "Applications"), N("link", "+ New Application"),
                                              N("table", children=[head, *(row(*j) for j in JOBS)])])


def joblens_job(title):
    return N("document", "JobLens", children=[N("heading", title), N("group", "Apply", children=[
        N("button", "Apply"), N("text", "Judge score: 80"), N("button", "Mark submitted (v1)")])])


class ApplyDesk(FakeDesktop):
    def __init__(self, form_url, prompt=False, links=None):
        super().__init__([])
        self.form_url, self.values, self.open_list = form_url, {}, False
        self.prompt, self.prompt_open = prompt, False   # Himalayas' "I'm ready to apply" popup
        self.links = links or {}   # job title -> where its JobLens Apply leads (default: the Himalayas job)
        self.job = None

    def web_root(self, app):
        if "google.com" in self.url:
            return google_home()
        if self.url == JL:
            return joblens_list()
        if self.url.startswith(JL + "jobs/"):
            return joblens_job(self.job)
        if self.url == "chrome://newtab/":
            return N("document", "New Tab", children=[N("text", "New Tab")])
        if "himalayas.app" in self.url:
            root = job_page()
            if self.prompt_open:   # as live: over the job page, the button with a text child of the same name
                root.children.append(N("dialog", children=[
                    N("heading", "Don't let your application get lost in the pile"), N("button", "Close"),
                    N("button", "Generate cover letter with AI"), N("button", "Generate resume with AI"),
                    N("button", "I\u2019m ready to apply", children=[N("text", "I\u2019m ready to apply")])]))
            return root
        if "greenhouse" in self.url:
            return greenhouse(self)
        if "lever" in self.url:
            return lever(self)
        return N("document", "Somewhere else", children=[N("heading", "Apply here")])

    def current_url(self, app):
        return self.url

    def press(self, key):
        assert key != "enter" or self.calls[-1:] == ["focus_address_bar"], "Enter in a web page"
        self.calls.append(key)
        if key == "enter":
            self.url = self.typed
        elif key == "new_tab":
            self.url = "chrome://newtab/"
            self.values, self.open_list = {}, False   # a fresh form for the next job

    def type_into(self, node, text):
        super().type_into(node, text)
        if node.role == "combo_box":
            self.open_list = True
        else:
            self.values[node.dom_id or node.name or "q1"] = text

    def link_url(self, node):   # JobLens's title links carry their address (AXURL), as live
        if self.url == JL and node.role == "link":
            self.job = node.name
            return getattr(self, "link_base", JL) + f"jobs/{node.name.lower().replace(' ', '-')}"
        return None

    def click(self, node):
        assert not any(engine.matches(node, spec) for spec in SUBMIT_SPECS), f"clicked {node.name}"
        self.calls.append(("click", node.dom_id or node.name))
        if self.url == JL and node.role == "link":
            self.job, self.url = node.name, JL + f"jobs/{node.name.lower().replace(' ', '-')}"
        elif self.url.startswith(JL + "jobs/") and node.name == "Apply":
            self.url = self.links.get(self.job, JOB)   # JobLens opens the job link (a new tab, live)
        elif node.name == "Apply now":
            self.prompt_open = self.prompt
            if not self.prompt:
                self.url = self.form_url
        elif node.name == "I\u2019m ready to apply" and node.role == "button":
            self.url, self.prompt_open = self.form_url, False
        elif node.role == "radio":
            self.values["radio"] = node.name
        elif self.open_list and node.role == "group" and node.name in ("Yes", "No"):
            self.values["sel"], self.open_list = node.name, False

    def choose_file(self, path):
        super().choose_file(path)
        self.values["cv"] = CV


BANK = [
    {"key": "first", "labels": ["First Name"], "answer": "Testa"},
    {"key": "last", "labels": ["Last Name"], "answer": "Example"},
    {"key": "full", "labels": ["Full name"], "answer": "Testa Example"},
    {"key": "email", "labels": ["Email"], "answer": "testa@example.invalid"},
    {"key": "notice", "labels": ["Notice period", "Notice period?"], "answer": SECRET},
    {"key": "visa", "labels": ["Will you require visa sponsorship?"], "answer": "No"},
    {"key": "auth", "labels": ["Are you authorised to work in Testland?"], "answer": "Yes"},
]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    monkeypatch.setattr(engine.auth, "approve", lambda *a, **k: (True, "biometric"))   # the CV prompt
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine, "user_home", lambda: tmp_path)
    (tmp_path / "apply").mkdir(mode=0o700)
    (tmp_path / "apply" / "answers.yaml").write_text(json.dumps({"answers": BANK, "cv_file": "~/" + CV}))
    (tmp_path / CV).write_bytes(b"%PDF")


def answer_cards(tmp_path, choose, seen):
    """The panel's side: answer every card the run shows (choose(card) -> reply) until the run ends."""
    from govaios import applyfiles
    done = threading.Event()

    def go():
        while not done.is_set():
            ask = applyfiles.read_json(tmp_path, applyfiles.ASK)
            if ask and "card" in ask and applyfiles.read_json(tmp_path, applyfiles.REPLY) is None:
                seen.append(ask["card"])
                applyfiles.write_json(tmp_path, applyfiles.REPLY, {"run": ask["run"], "card": choose(ask["card"])})
                while applyfiles.read_json(tmp_path, applyfiles.ASK) == ask and not done.is_set():
                    time.sleep(0.002)
            time.sleep(0.002)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return done


def run_apply(tmp_path, desk, choose=lambda c: "next", seen=None, run_id="r1"):
    wf = yaml.safe_load(FLOW.read_text())
    if FLOW == REPO / "flows" / "job_apply.yaml":   # the shipped file: these tests are about stopping; test_teach.py teaches
        wf["workflow"]["permissions"]["allow"].remove("teach")
    wf["workflow"]["browser"]["account"] = ACCT   # the fake Google page's account; the shipped file is untouched
    src = tmp_path / "src"
    (src / "flows").mkdir(parents=True)
    (src / "pages").mkdir()
    (src / "flows" / "job_apply.yaml").write_text(yaml.safe_dump(wf))
    for p in (REPO / "pages").glob("*.yaml"):
        (src / "pages" / p.name).write_bytes(p.read_bytes())
    r = Runner(src / "flows" / "job_apply.yaml", desk, tmp_path)
    r.approvals.approve_flow(r.flow["id"], r.digest)
    for o in DESTS:
        r.approvals.approve_destination(r.flow["id"], o)
    r.run_id = run_id
    done = answer_cards(tmp_path, choose, seen if seen is not None else [])
    err = None
    try:
        r.run()
    except engine.Stop as e:
        err = e
    finally:
        done.set()
    entries = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    tasks = (json.loads((tmp_path / "apply" / "tasks.json").read_text())["tasks"]
             if (tmp_path / "apply" / "tasks.json").exists() else None)
    return entries, tasks, err


@pytest.fixture
def fast_clock(monkeypatch):
    """Page waits time out at once (a page that never comes)."""
    c = itertools.count(0, 30)
    monkeypatch.setattr(engine, "time", types.SimpleNamespace(sleep=lambda s: None, time=lambda: next(c),
                                                             monotonic=time.monotonic))


@pytest.mark.usefixtures("env")
def test_end_to_end_fake_greenhouse(tmp_path, monkeypatch, capsys):
    d = ApplyDesk(GH)
    seen = []
    e, tasks, err = run_apply(tmp_path, d, seen=seen)
    assert err is None and e[-1]["kind"] == "flow_end"
    assert {k: d.values[k] for k in ("first_name", "last_name", "email", "question_1000000001", "sel", "cv")} == \
        {"first_name": "Testa", "last_name": "Example", "email": "testa@example.invalid",
         "question_1000000001": SECRET, "sel": "No", "cv": CV}
    # the two Ready jobs, never the Submitted one; each its own task, reviewed by the admin
    assert [(t["n"], t["title"], t["status"], t["filled"], t["total"], t["yourself"]) for t in tasks] == [
        (1, "Acme Test \u2014 Staff Engineer", "done", 5, 6, ["Gender"]),
        (2, "Beta Test \u2014 Lead", "done", 5, 6, ["Gender"])]
    assert [(c["kind"], c["job"], c["item"]) for c in seen] == [
        ("review", "Acme Test \u2014 Staff Engineer", 1), ("review", "Beta Test \u2014 Lead", 2)]
    clicks = [c[1] for c in d.calls if isinstance(c, tuple) and c[0] == "click"]
    assert "Engineer" not in clicks and clicks.count("Apply") == 2
    assert "Staff Engineer" not in clicks and "Lead" not in clicks   # opened by address: no click on the title
    assert d.calls.count("new_tab") == 2   # each job in its own tab
    assert {x.get("item") for x in e if x.get("step") == "fill"} == {1, 2}
    assert not any(x.get("decision") == "deny" for x in e)
    out = capsys.readouterr()
    for blob in ((tmp_path / "audit.jsonl").read_text(), out.out, out.err, json.dumps(tasks)):
        assert SECRET not in blob and str(tmp_path / CV) not in blob


@pytest.mark.usefixtures("env")
def test_a_link_to_another_site_is_clicked_not_typed(tmp_path, monkeypatch):
    d = ApplyDesk(GH)
    d.link_base = "https://elsewhere.example/"   # open_link never types an address on another site
    e, tasks, err = run_apply(tmp_path, d)
    clicks = [c[1] for c in d.calls if isinstance(c, tuple) and c[0] == "click"]
    assert "Staff Engineer" in clicks and "elsewhere" not in d.typed


@pytest.mark.usefixtures("env")
def test_end_to_end_fake_lever(tmp_path, monkeypatch, capsys):
    d = ApplyDesk(LV)
    e, tasks, err = run_apply(tmp_path, d)
    assert err is None and e[-1]["kind"] == "flow_end"
    assert {k: d.values[k] for k in ("Full name\u2731", "Email\u2731", "q1", "radio", "cv")} == \
        {"Full name\u2731": "Testa Example", "Email\u2731": "testa@example.invalid", "q1": SECRET, "radio": "Yes", "cv": CV}
    assert [(t["filled"], t["total"], t["yourself"]) for t in tasks] == [(4, 4, []), (4, 4, [])]


@pytest.mark.usefixtures("env")
def test_ready_to_apply_popup_is_clicked_through(tmp_path):
    d = ApplyDesk(GH, prompt=True)
    e, tasks, err = run_apply(tmp_path, d)
    assert err is None and e[-1]["kind"] == "flow_end"
    clicks = [c[1] for c in d.calls if isinstance(c, tuple) and c[0] == "click"]
    assert clicks.count("I\u2019m ready to apply") == 2 and clicks.index("Apply now") < clicks.index("I\u2019m ready to apply")
    assert tasks[0]["filled"] == 5 and d.values["cv"] == CV


@pytest.mark.usefixtures("env", "fast_clock")
def test_a_job_that_stops_ends_only_its_task(tmp_path):
    """Acme's link leads to a site the flow doesn't know: that task stops (captured), the admin picks Next job."""
    d = ApplyDesk(GH, links={"Staff Engineer": "https://apply.example.invalid/x"})
    seen = []
    e, tasks, err = run_apply(tmp_path, d, seen=seen)
    assert err is None and e[-1]["kind"] == "flow_end"
    assert [(t["status"], t.get("reason")) for t in tasks] == [("stopped", "unexpected page"), ("done", None)]
    assert [(c["kind"], c["label"], c["item"]) for c in seen] == [("stopped", "unexpected page", 1), ("review", "", 2)]
    [st] = [x for x in e if x.get("action") == "task_stop"]
    assert st["item"] == 1 and st["reason"] == "unexpected page"
    # the undeclared site is never read for a capture
    assert [x["outcome"] for x in e if x.get("action") == "capture" and x.get("item") == 1] == ["not_declared"]
    assert not (tmp_path / "captures").exists()
    assert not any(x["kind"] == "stop" for x in e)


@pytest.mark.usefixtures("env", "fast_clock")
def test_end_on_a_stopped_task_ends_the_run(tmp_path):
    d = ApplyDesk(GH, links={"Staff Engineer": "https://apply.example.invalid/x"})
    e, tasks, err = run_apply(tmp_path, d, choose=lambda c: "end")
    assert str(err) == "ended by admin" and e[-1]["kind"] == "stop"
    assert [t["status"] for t in tasks] == ["stopped", "waiting"]


@pytest.mark.usefixtures("env")
def test_end_at_review_ends_the_run(tmp_path):
    d = ApplyDesk(GH)
    e, tasks, err = run_apply(tmp_path, d, choose=lambda c: "end")
    assert str(err) == "ended by admin"
    assert [t["status"] for t in tasks] == ["done", "waiting"]
    assert d.calls.count("new_tab") == 1


@pytest.mark.usefixtures("env")
def test_emergency_stop_inside_a_task_ends_the_run(tmp_path):
    d = ApplyDesk(GH)
    (tmp_path / "STOPPED").touch()   # pressed while the first job runs: before any of its steps
    orig = d.press
    d.press = lambda k: (orig(k), (tmp_path / "STOPPED").touch() if k == "new_tab" else None)[0]
    (tmp_path / "STOPPED").unlink()
    e, tasks, err = run_apply(tmp_path, d)
    assert str(err) == "emergency stop" and [t["status"] for t in tasks] == ["stopped", "waiting"]
    [ts] = [x for x in e if x.get("action") == "task_stop"]   # in job 1's log, and the run ended
    assert (ts["item"], ts["outcome"], ts["reason"]) == (1, "run_stopped", "emergency stop") and e[-1]["kind"] == "stop"


@pytest.mark.usefixtures("env")
def test_cli_run_fills_every_job_in_its_own_tab_without_cards(tmp_path):
    d = ApplyDesk(GH)
    e, tasks, err = run_apply(tmp_path, d, run_id=None)
    assert err is None and tasks is None and d.calls.count("new_tab") == 2
    assert not any(x.get("action") == "ask_admin" for x in e)


@pytest.mark.usefixtures("env")
def test_no_ready_job_stops_with_a_clear_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__(__name__), "JOBS", [("Old Corp", "Engineer", "Submitted")])
    e, tasks, err = run_apply(tmp_path, ApplyDesk(GH))
    assert str(err) == "no Ready jobs in JobLens"


def test_job_apply_in_marketplace_and_set_up_as_draft(tmp_path):
    from govaios.panel import market
    t = next(t for t in market.CATALOG if t.id == "job_apply")
    out = market.setup(t, "Profile 5", "x.y@example.com", tmp_path / "apps/flows", REPO)
    b = yaml.safe_load(out.read_text())["workflow"]["browser"]
    assert (b["profile_directory"], b["account"]) == ("Profile 5", "x.y@example.com")
    assert [a.name for a in list_apps(tmp_path / "apps/flows", tmp_path)] == ["JobLens"]


@pytest.mark.usefixtures("env")
def test_an_engine_error_inside_a_job_ends_the_run(tmp_path):
    """Not a Stop (an AX or engine bug): fail closed, never carry on to the next job."""
    d = ApplyDesk(GH)
    d.scroll_into_view = lambda node: (_ for _ in ()).throw(AttributeError("AX gone"))
    with pytest.raises(AttributeError):
        run_apply(tmp_path, d)
    tasks = json.loads((tmp_path / "apply" / "tasks.json").read_text())["tasks"]
    assert [t["status"] for t in tasks] == ["stopped", "waiting"] and tasks[0]["reason"] == "AttributeError"
    e = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert e[-1]["kind"] == "stop" and [x["outcome"] for x in e if x.get("action") == "task_stop"] == ["run_stopped"]


@pytest.mark.usefixtures("env")
def test_job_linking_straight_to_its_form_skips_himalayas(tmp_path):
    d = ApplyDesk(GH, links={"Lead": GH})   # Beta's link is the Greenhouse form itself
    e, tasks, err = run_apply(tmp_path, d)
    assert err is None and [(t["status"], t["filled"]) for t in tasks] == [("done", 5), ("done", 5)]
    beta = [x for x in e if x.get("item") == 2]
    assert not any(x.get("step") == "apply" for x in beta)   # no Himalayas Apply now for that job
    assert any(x.get("step") == "on_form" and x.get("kind") == "verify" for x in beta)


def test_skip_to_must_be_a_later_step(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    r = Runner.__new__(Runner)
    r.home, r.step, r.ctx = tmp_path, None, {}
    r.do_x = lambda s: ("skip_to", "a")   # back to itself: never a loop
    with pytest.raises(engine.Stop, match="no such later step"):
        r.steps([{"id": "a", "action": "x"}, {"id": "b", "action": "x"}])


@pytest.mark.usefixtures("env")
def test_two_jobs_with_the_same_client_and_role_are_both_done(tmp_path, monkeypatch):
    monkeypatch.setattr(__import__(__name__), "JOBS", [("Acme Test", "Lead", "Ready"), ("Acme Test", "Lead", "Ready")])
    d = ApplyDesk(GH)
    rows, root_of = [], d.web_root
    def web_root(app):
        d.last = root_of(app)
        return d.last
    orig = d.link_url
    def link_url(node):
        if d.url == JL and node.role == "link":   # which of the two equal rows was opened (0 is the header)
            table = next(n for n in d.last.walk() if n.role == "table")
            rows.append(next(i for i, r in enumerate(table.children) if any(x is node for x in r.walk())))
        return orig(node)
    d.web_root, d.link_url = web_root, link_url
    e, tasks, err = run_apply(tmp_path, d)
    assert err is None and [t["status"] for t in tasks] == ["done", "done"] and rows == [1, 2]


def test_shipped_joblens_flow_allows_teach():
    assert "teach" in yaml.safe_load(FLOW.read_text())["workflow"]["permissions"]["allow"]
