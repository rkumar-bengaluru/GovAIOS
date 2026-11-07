"""job_apply flow: Himalayas Apply -> Greenhouse or Lever form, filled and CV attached, never submitted."""
import json

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
DESTS = ["https://www.google.com", "https://himalayas.app", "https://job-boards.greenhouse.io", "https://jobs.lever.co"]
NEW_PAGES = ("himalayas_job_apply", "himalayas_job_logged_out", "greenhouse_application", "lever_application")
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
    assert pages_used(wf) == {"google_home", "himalayas_job_apply", "himalayas_logged_out", "himalayas_job_logged_out",
                              "greenhouse_application", "lever_application"}
    assert (wf["id"], wf["app"], wf["permissions"]["max_element_risk"], wf["destinations"]) == \
        ("job_apply", "Job Apply", "modify", DESTS)
    assert "close_window" not in json.dumps(wf["steps"])


@pytest.mark.parametrize("pid,el", list(submit_elements()))
def test_submit_buttons_denied(pid, el, tmp_path):
    wf = yaml.safe_load(FLOW.read_text())["workflow"]
    risk = yaml.safe_load((REPO / "pages" / f"{pid}.yaml").read_text())["page"]["elements"][el]["risk"]
    assert decide({"action": "click", "risk": risk}, wf, Approvals(tmp_path / "a.json")) == "deny"


def test_submit_elements_are_the_expected_ones():
    assert set(submit_elements()) == {
        ("himalayas_job_apply", "save_link"), ("himalayas_job_apply", "save_button"),
        ("himalayas_job_apply", "job_expired"), ("greenhouse_application", "submit"),
        ("greenhouse_application", "autofill"), ("lever_application", "submit"), ("lever_application", "linkedin")}


def test_other_host_denied(tmp_path):
    wf = yaml.safe_load(FLOW.read_text())["workflow"]
    assert decide({"action": "read_page", "risk": "read", "destination": "https://apply.workable.com/x"},
                  wf, Approvals(tmp_path / "a.json")) == "deny"


def test_list_apps_shows_job_apply(tmp_path):
    apps = list_apps(REPO / "flows", tmp_path)
    by_id = {a.id: a.name for a in apps}
    assert by_id["job_apply"] == "Job Apply"
    assert by_id["himalayas_job_vetting"] == "JobLens" and "morning_inbox_briefing" in by_id
    assert match("run joblens", apps)[1].id == "himalayas_job_vetting"


def test_existing_flow_digests_unchanged():
    # recorded from main (flows/ and pages/ identical to this branch's base)
    assert read_bound(REPO / "flows" / "himalayas_job_vetting.yaml", REPO / "pages")[0] == \
        "d902703645bbd8f381a7d912789624171e77cae3c52c77eb62addaea9008e546"
    assert read_bound(REPO / "flows" / "morning_inbox_briefing.yaml", REPO / "pages")[0] == \
        "a1dca44ed9e272377fe86987aca8bece3a1dcd7c4ef797e6ed40d4e8386ff4ae"


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
    guard = next(s for s in yaml.safe_load(FLOW.read_text())["workflow"]["steps"] if s["id"] == "authentication_guard")
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


class ApplyDesk(FakeDesktop):
    def __init__(self, form_url):
        super().__init__([])
        self.form_url, self.values, self.open_list = form_url, {}, False

    def web_root(self, app):
        if "google.com" in self.url:
            return google_home()
        if "himalayas.app" in self.url:
            return job_page()
        return greenhouse(self) if "greenhouse" in self.url else lever(self)

    def current_url(self, app):
        return self.url

    def press(self, key):
        assert key != "enter" or self.calls[-1:] == ["focus_address_bar"], "Enter in a web page"
        self.calls.append(key)
        if key == "enter":
            self.url = self.typed

    def type_into(self, node, text):
        super().type_into(node, text)
        if node.role == "combo_box":
            self.open_list = True
        else:
            self.values[node.dom_id or node.name or "q1"] = text

    def click(self, node):
        assert not any(engine.matches(node, spec) for spec in SUBMIT_SPECS), f"clicked {node.name}"
        self.calls.append(("click", node.dom_id or node.name))
        if node.name == "Apply now":
            self.url = self.form_url
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


def run_apply(tmp_path, desk):
    wf = yaml.safe_load(FLOW.read_text())
    wf["workflow"]["browser"]["account"] = ACCT   # the fake Google page's account; the shipped file is untouched
    src = tmp_path / "src"
    (src / "flows").mkdir(parents=True)
    (src / "pages").mkdir()
    (src / "flows" / "job_apply.yaml").write_text(yaml.safe_dump(wf))
    for p in (REPO / "pages").glob("*.yaml"):
        (src / "pages" / p.name).write_bytes(p.read_bytes())
    r = Runner(src / "flows" / "job_apply.yaml", desk, tmp_path, inputs={"job_url": JOB})
    r.approvals.approve_flow(r.flow["id"], r.digest)
    for o in DESTS:
        r.approvals.approve_destination(r.flow["id"], o)
    r.run_id = "r1"
    r.run()
    entries = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    return entries, json.loads((tmp_path / "apply" / "result.json").read_text())


@pytest.mark.usefixtures("env")
def test_end_to_end_fake_greenhouse(tmp_path, monkeypatch, capsys):
    d = ApplyDesk(GH)
    e, res = run_apply(tmp_path, d)
    assert e[-1]["kind"] == "flow_end"
    assert {k: d.values[k] for k in ("first_name", "last_name", "email", "question_1000000001", "sel", "cv")} == \
        {"first_name": "Testa", "last_name": "Example", "email": "testa@example.invalid",
         "question_1000000001": SECRET, "sel": "No", "cv": CV}
    assert res == {"run": "r1", "filled": 5, "total": 6, "yourself": ["Gender"], "check": []}
    assert not any(x.get("decision") == "deny" for x in e)
    out = capsys.readouterr()
    for blob in ((tmp_path / "audit.jsonl").read_text(), out.out, out.err):
        assert SECRET not in blob and str(tmp_path / CV) not in blob


@pytest.mark.usefixtures("env")
def test_end_to_end_fake_lever(tmp_path, monkeypatch, capsys):
    d = ApplyDesk(LV)
    e, res = run_apply(tmp_path, d)
    assert e[-1]["kind"] == "flow_end"
    assert {k: d.values[k] for k in ("Full name✱", "Email✱", "q1", "radio", "cv")} == \
        {"Full name✱": "Testa Example", "Email✱": "testa@example.invalid", "q1": SECRET, "radio": "Yes", "cv": CV}
    assert res == {"run": "r1", "filled": 4, "total": 4, "yourself": [], "check": []}
    out = capsys.readouterr()
    for blob in ((tmp_path / "audit.jsonl").read_text(), out.out, out.err):
        assert SECRET not in blob and str(tmp_path / CV) not in blob


def test_job_apply_in_marketplace_and_set_up_as_draft(tmp_path):
    from govaios.panel import market
    t = next(t for t in market.CATALOG if t.id == "job_apply")
    out = market.setup(t, "Profile 5", "x.y@example.com", tmp_path / "apps/flows", REPO)
    b = yaml.safe_load(out.read_text())["workflow"]["browser"]
    assert (b["profile_directory"], b["account"]) == ("Profile 5", "x.y@example.com")
    assert [a.name for a in list_apps(tmp_path / "apps/flows", tmp_path)] == ["Job Apply"]
