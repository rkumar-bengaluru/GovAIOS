"""Studio drafts: a capture becomes a draft page schema and a read-only Check app; bigger flows link pages by id."""
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


def test_check_app_is_read_only_and_drops_the_query():
    f = studio.draft_check_flow("acme_careers", "https://acme.example/jobs?token=SECRET", BROWSER, "Careers | Acme")["workflow"]
    assert f["permissions"] == {"allow": ["launch_application", "navigate", "read_page"], "max_element_risk": "read"}
    assert f["destinations"] == ["https://www.google.com", "https://acme.example"]
    assert f["steps"][4]["value"] == "https://acme.example/jobs" and f["app"] == "Check Careers Acme"


def test_write_draft_never_overwrites_and_check_app_binds_the_page(tmp_path):
    flows, pages = tmp_path / "flows", tmp_path / "pages"
    flows.mkdir(), pages.mkdir()
    (pages / "google_home.yaml").write_text("page: {id: google_home, identification: {title_matches: x}, elements: {}}")
    a = studio.write_draft(flows, pages, TREE, "https://acme.example/jobs", BROWSER, "cap1.json")
    b = studio.write_draft(flows, pages, TREE, "https://acme.example/jobs", BROWSER, "cap2.json")
    assert (a, b) == ("acme_example_careers_acme", "acme_example_careers_acme_2")
    assert "cap1.json" in (pages / f"{a}.yaml").read_text()
    digest, raw = read_bound(flows / f"check_{a}.yaml", pages)
    assert pages / f"{a}.yaml" in raw   # approving the Check app binds the draft page's exact bytes
    assert [x.approved for x in list_apps(flows, tmp_path)] == [False, False]


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
