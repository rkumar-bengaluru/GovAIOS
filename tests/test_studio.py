"""Studio drafts: a capture becomes a draft page schema and a start link; bigger flows link pages by id."""
import yaml

from govaios import engine, studio
from govaios.approvals import read_bound
from govaios.desktop import Node
from govaios.panel.apps import list_apps

BROWSER = {"application": "chrome", "profile_directory": "Profile 2", "account": "a@example.com"}
TREE = {"role": "document", "name": "Careers | Acme", "children": [
    {"role": "heading", "name": "Open roles"},
    {"role": "text_field", "name": "Search", "dom_id": ":r5:"},          # React id: changes every load
    {"role": "text_field", "name": "Email", "dom_id": "email"},
    {"role": "button", "name": "Apply"}, {"role": "button", "name": "Apply"},   # the same name twice
    {"role": "button", "name": "x" * 200},                                # too long to be a useful anchor
    {"role": "link", "name": "Home", "value": "SECRET-VALUE"},
    {"role": "text", "value": "SECRET-VALUE"}]}


def node(d):
    return Node(d["role"], d.get("name", ""), d.get("value", ""), d.get("dom_id", ""), (),
                [node(c) for c in d.get("children", [])])


def test_draft_page_identifies_its_own_capture_and_each_element_is_unique():
    page = studio.draft_page(TREE, "acme_careers")["page"]
    root = node(TREE)
    assert engine.identify(page, root)
    assert {k: len(engine.find_all(root, s, page)) for k, s in page["elements"].items()} == \
        {k: 1 for k in page["elements"]}
    el = page["elements"]
    assert el["search"] == {"role": "text_field", "name": "Search", "risk": "modify"}   # name, not the volatile id
    assert el["email"] == {"role": "text_field", "dom_id": "email", "risk": "modify"}
    assert (el["button_apply"]["index"], el["button_apply_2"]["index"]) == (0, 1)
    assert all(s["risk"] == "submit" for s in el.values() if s["role"] == "button")
    assert "SECRET-VALUE" not in yaml.safe_dump(page) and len(el) == 6


def test_write_draft_no_longer_writes_check_app(tmp_path):
    flows, pages = tmp_path / "flows", tmp_path / "pages"
    flows.mkdir(), pages.mkdir()
    a = studio.write_draft(flows, pages, TREE, "https://acme.example/jobs?token=SECRET", BROWSER, "cap1.json")
    assert a == "acme_example_careers_acme" and not list(flows.glob("check_*"))
    text = (pages / f"{a}.yaml").read_text()
    assert "# Start link: https://acme.example/jobs\n" in text and "SECRET" not in text   # the query never kept


def test_write_draft_never_overwrites(tmp_path):
    flows, pages = tmp_path / "flows", tmp_path / "pages"
    flows.mkdir(), pages.mkdir()
    a = studio.write_draft(flows, pages, TREE, "https://acme.example/jobs", BROWSER, "cap1.json")
    b = studio.write_draft(flows, pages, TREE, "https://acme.example/jobs", BROWSER, "cap2.json")
    assert (a, b) == ("acme_example_careers_acme", "acme_example_careers_acme_2")
    assert "cap1.json" in (pages / f"{a}.yaml").read_text()
    assert list_apps(flows, tmp_path) == []


def test_a_bigger_flow_links_draft_pages_by_id(tmp_path):
    """The reusable unit is the page: a flow that names it binds it, and any later edit to it needs re-approval."""
    flows, pages = tmp_path / "flows", tmp_path / "pages"
    flows.mkdir(), pages.mkdir()
    (pages / "google_home.yaml").write_text("page: {id: google_home, identification: {title_matches: x}, elements: {}}")
    pid = studio.write_draft(flows, pages, TREE, "https://acme.example/jobs", BROWSER, "cap.json")
    big = flows / "acme_apply.yaml"
    big.write_text(yaml.safe_dump({"workflow": {"id": "acme_apply", "version": 1, "steps": [
        {"id": "on_jobs", "action": "classify_page", "on_match": {pid: "continue", "unknown": "stop_and_report"}},
        {"id": "apply", "action": "click", "target": f"{pid}.button_apply"}]}}))
    before = read_bound(big, pages)[0]
    (pages / f"{pid}.yaml").write_text((pages / f"{pid}.yaml").read_text().replace("risk: submit", "risk: navigate", 1))
    assert read_bound(big, pages)[0] != before


# ---------- composing a bigger flow from draft pages ----------
import json  # noqa: E402

import pytest  # noqa: E402
from conftest import ACCT, FakeDesktop, N, google_home  # noqa: E402

JOBS = {"role": "document", "name": "Jobs | Acme", "children": [
    {"role": "heading", "name": "Open roles"}, {"role": "link", "name": "Staff Engineer"},
    {"role": "button", "name": "Delete account"}]}
FORM = {"role": "document", "name": "Apply | Acme", "children": [
    {"role": "heading", "name": "Your application"}, {"role": "text_field", "name": "Email", "dom_id": "email"},
    {"role": "button", "name": "Submit application"}]}


def studio_dirs(tmp_path):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True), pages.mkdir()
    for p in ("google_home",):
        (pages / f"{p}.yaml").write_bytes((engine.REPO / "pages" / f"{p}.yaml").read_bytes())
    b = {**BROWSER, "account": ACCT}
    (flows / "job_apply.yaml").write_text(yaml.safe_dump({"workflow": {"id": "job_apply", "browser": b, "steps": []}}))
    jobs = studio.write_draft(flows, pages, JOBS, "https://acme.example/jobs", b, "c1.json")
    form = studio.write_draft(flows, pages, FORM, "https://apply.acme.example/form", b, "c2.json")
    return flows, pages, jobs, form


def test_catalogue_lists_draft_pages_directly(tmp_path):
    flows, pages, jobs, form = studio_dirs(tmp_path)
    cat = studio.catalogue(flows, pages)
    assert set(cat) == {jobs, form} and cat[jobs]["url"] == "https://acme.example/jobs"
    assert cat[jobs]["elements"]["link_staff_engineer"] == ("link", "Staff Engineer", "navigate")


def test_compose_builds_a_flow_over_two_sites(tmp_path):
    flows, pages, jobs, form = studio_dirs(tmp_path)
    f = studio.compose("Acme apply", [f"open:{jobs}", f"click:{jobs}.link_staff_engineer", f"open:{form}",
                                      f"fill:{form}", "review"], studio.catalogue(flows, pages))["workflow"]
    assert (f["id"], f["app"]) == ("studio_acme_apply", "Acme apply")
    assert f["destinations"] == ["https://www.google.com", "https://acme.example", "https://apply.acme.example"]
    assert f["permissions"] == {"allow": ["ask_admin", "click", "fill_field", "launch_application", "navigate",
                                          "read_page"], "max_element_risk": "navigate"}
    assert [s["action"] for s in f["steps"]][4:] == ["navigate", "classify_page", "click", "classify_page",
                                                    "fill_form", "hand_over"]


@pytest.mark.parametrize("steps, why", [
    ([], "between 1 and"),
    (["review"], "step 1 must open a page"),
    (["open:nope"], "no draft page 'nope'"),
    (["open:JOBS", "click:JOBS.button_delete_account"], "rated submit: that click stays yours"),
    (["open:JOBS", "fill:FORM"], "open FORM first"),
    (["open:JOBS", "click:JOBS.nothing"], "has no element 'nothing'"),
    (["open:JOBS", "rm -rf"], "unknown step"),
])
def test_compose_refuses(tmp_path, steps, why):
    flows, pages, jobs, form = studio_dirs(tmp_path)
    steps = [s.replace("JOBS", jobs).replace("FORM", form) for s in steps]
    with pytest.raises(ValueError, match=why.replace("JOBS", jobs).replace("FORM", form)):
        studio.compose("Acme", steps, studio.catalogue(flows, pages))


@pytest.mark.parametrize("app", ["", "   ", "<script>", "../x"])
def test_compose_needs_a_plain_name(tmp_path, app):
    flows, pages, jobs, form = studio_dirs(tmp_path)
    with pytest.raises(ValueError, match="give the app a name"):
        studio.compose(app, [f"open:{jobs}"], studio.catalogue(flows, pages))


class AcmeDesk(FakeDesktop):
    def __init__(self):
        super().__init__([])
        self.values = {}

    def current_url(self, app):
        return self.url

    def press(self, key):
        self.calls.append(key)
        if key == "enter":
            self.url = self.typed

    def click(self, node):
        assert node.name != "Submit application" and node.name != "Delete account"
        self.calls.append(("click", node.name))
        if node.name == "Staff Engineer":
            self.url = "https://apply.acme.example/form"

    def type_into(self, node, text):
        self.values[node.dom_id] = text


def _acme_root(d):
    if "google.com" in d.url:
        return google_home()
    if d.url == "https://acme.example/jobs":
        return node(JOBS)
    t = json.loads(json.dumps(FORM))
    t["children"][1]["value"] = d.values.get("email", "")
    return node(t)


def test_composed_app_runs_end_to_end(tmp_path, monkeypatch):
    flows, pages, jobs, form = studio_dirs(tmp_path)
    flow = studio.compose("Acme apply", [f"open:{jobs}", f"click:{jobs}.link_staff_engineer", f"open:{form}",
                                         f"fill:{form}", "review"], studio.catalogue(flows, pages))
    studio.write_composed(flows, flow)
    for k in ("sleep",):
        monkeypatch.setattr(engine.time, k, lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    monkeypatch.setattr(engine, "user_home", lambda: tmp_path)
    (tmp_path / "apply").mkdir(mode=0o700)
    (tmp_path / "apply" / "answers.yaml").write_text(json.dumps({"answers": [
        {"key": "email", "labels": ["Email"], "answer": "a@example.invalid"}]}))
    d = AcmeDesk()
    d.web_root = lambda app: _acme_root(d)
    r = engine.Runner(flows / "studio_acme_apply.yaml", d, tmp_path)
    r.approvals.approve_flow(r.flow["id"], r.digest)
    for o in r.flow["destinations"]:
        r.approvals.approve_destination(r.flow["id"], o)
    r.run()   # a Terminal run: the hand-over card is skipped
    assert d.values == {"email": "a@example.invalid"} and ("click", "Staff Engineer") in d.calls
    e = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert e[-1]["kind"] == "flow_end" and not any(x.get("decision") == "deny" for x in e)


def test_write_composed_never_replaces_an_app(tmp_path):
    flows, pages, jobs, form = studio_dirs(tmp_path)
    flow = studio.compose("Acme", [f"open:{jobs}"], studio.catalogue(flows, pages))
    studio.write_composed(flows, flow)
    with pytest.raises(OSError, match="exists"):
        studio.write_composed(flows, flow)


# ---------- repeated items (for each) ----------
def card(title, company):
    return {"role": "group", "children": [{"role": "group", "children": [{"role": "link", "name": title}]},
                                          {"role": "text", "value": company}]}


LIST = {"role": "document", "name": "Roles | Acme", "children": [
    {"role": "heading", "name": "Roles"},
    {"role": "navigation", "children": [{"role": "link", "name": "Home"}, {"role": "link", "name": "About"}]},
    {"role": "group", "dom_id": "results", "children": [
        {"role": "heading", "name": "4 roles"}, card("Lead", "Acme"), card("Dev", "Acme"), card("QA", "Beta"),
        card("Ops", "Beta")]}]}
TABLE = {"role": "document", "name": "Applications", "children": [{"role": "heading", "name": "Applications"}, {
    "role": "table", "children": [
        {"role": "row", "children": [{"role": "cell", "children": [{"role": "text", "value": h}]} for h in ("Client", "Role")]},
        *({"role": "row", "children": [{"role": "cell", "children": [{"role": "text", "value": c}]},
                                       {"role": "cell", "children": [{"role": "link", "name": r}]}]}
          for c, r in (("Acme", "Lead"), ("Beta", "Dev"), ("Gamma", "QA")))]}]}


@pytest.mark.parametrize("tree, want", [(LIST, ["Lead", "Dev", "QA", "Ops"]), (TABLE, ["Lead", "Dev", "QA"])])
def test_repeated_items_detected_exactly(tree, want):
    page = studio.draft_page(tree, "p")["page"]
    items = page["elements"]["items_1"]
    assert items["direct"] and items["has"] == {"role": "link"} and items["fields"]["link"]["risk"] == "navigate"
    found = engine.find_all(node(tree), items, page)
    assert [engine.find_all(f, items["fields"]["link"], page)[0].name for f in found] == want   # no header, no nav
    assert "items_1" not in page["identification"]["anchors"]


def test_two_similar_cards_are_not_a_list():
    t = {"role": "document", "name": "x", "children": [card("A", "a"), card("B", "b")]}
    assert not any(k.startswith("items_") for k in studio.draft_page(t, "p")["page"]["elements"])


def each_dirs(tmp_path):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True), pages.mkdir()
    (pages / "google_home.yaml").write_bytes((engine.REPO / "pages" / "google_home.yaml").read_bytes())
    b = {**BROWSER, "account": ACCT}
    (flows / "job_apply.yaml").write_text(yaml.safe_dump({"workflow": {"id": "job_apply", "browser": b, "steps": []}}))
    lst = studio.write_draft(flows, pages, LIST, "https://acme.example/roles", b, "c1.json")
    form = studio.write_draft(flows, pages, FORM, "https://apply.acme.example/form", b, "c2.json")
    return flows, pages, lst, form


@pytest.mark.parametrize("steps, why", [
    (["open:L", "click_item"], "only inside a for each"),
    (["open:L", "end_each"], "no for each to end"),
    (["open:L", "each:L.items_1", "each:L.items_1"], "end the first for each"),
    (["open:L", "each:L.nothing"], "no repeated items 'nothing'"),
    (["open:F", "each:L.items_1"], "open L first"),
    (["open:L", "click_item:x"], "unknown step"),
])
def test_compose_each_refuses(tmp_path, steps, why):
    flows, pages, lst, form = each_dirs(tmp_path)
    steps = [s.replace("L", lst).replace("F", form) if s.startswith(("open", "each")) else s for s in steps]
    with pytest.raises(ValueError, match=why.replace("L", lst)):
        studio.compose("Acme", steps, studio.catalogue(flows, pages))


class EachDesk(AcmeDesk):
    def __init__(self):
        super().__init__()
        self.clicked, self.filled = [], []

    def press(self, key):
        super().press(key)
        if key == "new_tab":
            self.url, self.values = "chrome://newtab/", {}

    def click(self, node):
        self.calls.append(("click", node.name))
        if node.role == "link" and self.url == "https://acme.example/roles":
            self.clicked.append(node.name)
            self.url = "https://apply.acme.example/form"

    def type_into(self, node, text):
        super().type_into(node, text)
        self.filled.append(self.clicked[-1])


def test_composed_for_each_runs_once_per_item(tmp_path, monkeypatch):
    flows, pages, lst, form = each_dirs(tmp_path)
    flow = studio.compose("Acme roles", [f"open:{lst}", f"each:{lst}.items_1", "click_item", f"open:{form}",
                                         f"fill:{form}", "review", "end_each"], studio.catalogue(flows, pages))
    studio.write_composed(flows, flow)
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    monkeypatch.setattr(engine, "user_home", lambda: tmp_path)
    (tmp_path / "apply").mkdir(mode=0o700)
    (tmp_path / "apply" / "answers.yaml").write_text(json.dumps({"answers": [
        {"key": "email", "labels": ["Email"], "answer": "a@example.invalid"}]}))
    d = EachDesk()

    def root(app):
        if d.url == "https://acme.example/roles":
            return node(LIST)
        return _acme_root(d)
    d.web_root = root
    r = engine.Runner(flows / "studio_acme_roles.yaml", d, tmp_path)
    r.approvals.approve_flow(r.flow["id"], r.digest)
    for o in r.flow["destinations"]:
        r.approvals.approve_destination(r.flow["id"], o)
    r.run()
    assert d.clicked == ["Lead", "Dev", "QA", "Ops"] and d.filled == d.clicked and d.calls.count("new_tab") == 4
    e = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert e[-1]["kind"] == "flow_end" and {x.get("item") for x in e if (x.get("step") or "").endswith("_fill")} == {1, 2, 3, 4}


# ---------- Task 10: New automation ----------
import test_job_apply_flow as ja  # noqa: E402
from test_job_apply_flow import env, fast_clock  # noqa: E402,F401  (fixtures)


def test_new_automation_flow_shape_and_refusals(tmp_path):
    p = studio.new_automation(tmp_path, "My Site", "https://Acme.example:443/start?token=SECRET#x", BROWSER)
    f = yaml.safe_load(p.read_text())["workflow"]
    assert p.name == "studio_my_site.yaml" and f["browser"] == BROWSER and "SECRET" not in p.read_text()
    assert f["destinations"] == ["https://www.google.com", "https://acme.example"]
    assert f["permissions"] == {"allow": ["launch_application", "navigate", "read_page", "click", "fill_field",
                                          "ask_admin", "attach_file", "teach"], "max_element_risk": "modify"}
    assert f["steps"][4:] == [{"id": "open_start", "action": "navigate", "value": "https://acme.example/start"},
                              {"id": "on_start", "action": "classify_page", "on_match": {"unknown": "stop_and_report"}}]
    with pytest.raises(OSError, match="exists"):
        studio.new_automation(tmp_path, "My Site", "https://acme.example", BROWSER)
    assert studio.new_automation(tmp_path, "Local", "http://localhost:8100/x", BROWSER)
    for bad in ("http://acme.example", "ftp://x", "https://u:p@acme.example", "javascript:1", ""):
        with pytest.raises(ValueError):
            studio.new_automation(tmp_path, "Bad", bad, BROWSER)
    with pytest.raises(ValueError, match="browser"):
        studio.new_automation(tmp_path, "Bad", "https://acme.example", None)
    with pytest.raises(ValueError, match="name"):
        studio.new_automation(tmp_path, "../x/", "https://acme.example", BROWSER)


@pytest.mark.usefixtures("env", "fast_clock")
def test_new_automation_is_teachable_from_its_start_page(tmp_path):
    src = tmp_path / "src"
    (src / "flows").mkdir(parents=True), (src / "pages").mkdir()
    for pg in (engine.REPO / "pages").glob("*.yaml"):
        (src / "pages" / pg.name).write_bytes(pg.read_bytes())
    path = studio.new_automation(src / "flows", "Acme", "https://acme.example/start", {**BROWSER, "account": ACCT})
    r = engine.Runner(path, ja.ApplyDesk(ja.GH), tmp_path)   # an empty page: nothing identifies it
    r.approvals.approve_flow(r.flow["id"], r.digest)
    for o in ("https://www.google.com", "https://acme.example"):
        r.approvals.approve_destination(r.flow["id"], o)
    r.run_id, seen = "r1", []
    done = ja.answer_cards(tmp_path, lambda c: "skip", seen)
    try:
        with pytest.raises(engine.Stop, match="unexpected page"):
            r.run()
    finally:
        done.set()
    assert seen[0]["kind"] == "new_page"

