"""Studio lessons: saved recordings become a proposed change (pages, steps, bank ops); nothing is written."""
import copy
import os

import pytest
import yaml

from govaios import lessons
from govaios.desktop import Node
from govaios.formfill import Bank, Entry

URL = "https://jobs.acme.example/apply?token=secret"


def tree(*kids, title="Apply | Acme"):
    return Node("document", title, children=[Node("heading", "Apply for Engineer"), *kids])


def ev(kind, role, name, value="", secure=False, submit=None):
    return {"kind": kind, "spec": {"role": role, "name": name}, "label": name, "value": value, "secure": secure,
            "submit": role == "button" if submit is None else submit}


def lesson(tmp_path, *pages):
    name = lessons.save(tmp_path, "job_apply", "d" * 64, "classify", list(pages))
    return lessons.load(tmp_path, name)


def page(t, events, url=URL):
    return {"url": url, "title": t.name, "tree": t, "events": events}


def kinds(p):
    return [s["kind"] for s in p["steps"]]


def test_save_is_private_unqueried_and_pruned(tmp_path):
    for _ in range(lessons.KEEP + 2):
        name = lessons.save(tmp_path, "job_apply", "d", "s", [page(tree(), [])])
    files = list((tmp_path / "lessons").iterdir())
    assert len(files) == lessons.KEEP
    assert os.stat(tmp_path / "lessons" / name).st_mode & 0o777 == 0o600
    doc = lessons.load(tmp_path, name)
    assert doc["pages"][0]["url"] == "https://jobs.acme.example/apply"
    assert doc["pages"][0]["tree"]["children"][0] == {"role": "heading", "name": "Apply for Engineer"}


def test_fill_events_collapse_to_one_fill_form_step(tmp_path):
    t = tree(Node("text_field", "Email"), Node("text_field", "Phone"), Node("checkbox", "Remote"),
             Node("native:AXSecureTextField", "Password"))
    les = lesson(tmp_path, page(t, [ev("fill", "text_field", "Email", "a@x"), ev("fill", "text_field", "Phone", "99"),
                                    ev("tick", "checkbox", "Remote", "1"),
                                    ev("fill", "native:AXSecureTextField", "Password", secure=True)]))
    out = lessons.propose(les, tmp_path / "pages", Bank())
    [p] = out["pages"]
    assert kinds(p) == ["fill_form", "hand_fill", "hand_over"]
    assert p["steps"][1]["label"] == "Password"
    assert [o["label"] for o in out["bank"]] == ["Email", "Phone"]   # no op for the tick or the secure field


def test_submit_click_becomes_hand_over(tmp_path):
    t = tree(Node("link", "Jobs"), Node("button", "Submit"), Node("button", "Send"))
    les = lesson(tmp_path, page(t, [ev("click", "link", "Jobs"), ev("click", "button", "Submit"),
                                    ev("click", "button", "Send")]))
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert kinds(p) == ["click", "hand_over", "hand_over"]   # it ends the page: no final one added
    assert [st["keep"] for st in p["steps"]] == [True, True, False]   # after the hand over: dead, shown off
    pid = p["id"]
    assert p["new"] and pid == "jobs_acme_example_apply_acme"
    assert p["steps"][0]["target"] == f"{pid}.link_jobs"
    els = p["yaml"]["page"]["elements"]
    assert els["link_jobs"]["risk"] == "navigate" and els["button_submit"]["risk"] == "submit"
    assert set(els) == {"heading_apply_for_engineer", "link_jobs", "button_submit", "button_send"}
    assert p["added"] == []
    assert set(p["yaml"]["page"]["identification"]["anchors"]) <= set(els)


def test_file_chooser_click_dropped_and_unknown_click_kept(tmp_path):
    t = tree(Node("button", "Choose File No file chosen"))
    unknown = {"kind": "click", "spec": None, "label": "", "value": "", "secure": False, "submit": False}
    les = lesson(tmp_path, page(t, [ev("click", "button", "Choose File No file chosen"),
                                    ev("attach", "button", "Choose File No file chosen"), unknown]))
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert kinds(p) == ["attach_file", "click", "hand_over"]
    assert p["steps"][1] == {"kind": "click", "label": "not sure what this was", "target": None, "keep": False}


def test_known_page_reuses_its_id(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    known = {"page": {"id": "acme_apply", "identification": {"title_matches": "^Apply", "anchors": ["head"]},
                      "elements": {"head": {"role": "heading", "name": "Apply for Engineer", "risk": "read"},
                                   "next": {"role": "button", "name_matches": "^Next$", "risk": "navigate"}}}}
    (pages / "acme_apply.yaml").write_text(yaml.safe_dump(known))
    (pages / "jobs_acme_example_other.yaml").write_text("not: a page")
    t1 = tree(Node("button", "Next"))
    t2 = tree(Node("link", "Help"), title="Other")
    les = lesson(tmp_path, page(t1, [ev("click", "button", "Next")]), page(t2, [ev("click", "link", "Help")]))
    out = lessons.propose(les, pages, Bank())
    a, b = out["pages"]
    assert (a["id"], a["new"]) == ("acme_apply", False)
    assert a["steps"] == [{"kind": "click", "label": "Next", "target": "acme_apply.next", "keep": True}]  # admin lowered it
    assert a["yaml"]["page"]["elements"] == known["page"]["elements"]
    assert a["added"] == []
    assert b["new"] and b["id"] == "jobs_acme_example_other_2"   # never an existing file's name
    assert kinds(b) == ["click", "hand_over"]
    assert (pages / "acme_apply.yaml").read_text() == yaml.safe_dump(known)   # pure: nothing written


def test_bank_ops_add_label_change(tmp_path):
    bank = Bank((Entry("email", ("Email",), "a@x"), Entry("city", ("City",), "Bengaluru"),
                 Entry("notice", ("Notice period",), "30 days")))
    t = tree(Node("text_field", "Work email"), Node("text_field", "City"), Node("text_field", "Notice period"),
             Node("text_field", "LinkedIn"), Node("text_field", "Email"))
    les = lesson(tmp_path, page(t, [ev("fill", "text_field", "Work email", "a@x"),
                                    ev("fill", "text_field", "City", "Pune"),
                                    ev("choose", "combo_box", "Notice period", "30 days"),
                                    ev("fill", "text_field", "LinkedIn", "in/rk"),
                                    ev("fill", "text_field", "Email", "a@x")]))
    ops = lessons.propose(les, tmp_path / "pages", bank)["bank"]
    assert [(o["op"], o["key"], o["value"]) for o in ops] == [
        ("label", "email", "a@x"), ("change", "city", "Pune"), ("add", "linkedin", "in/rk")]
    assert all(o["keep"] == "bank" and o["sensitive"] is False for o in ops)


def test_long_text_and_codes_default_dont_keep(tmp_path):
    t = tree(Node("text_area", "Why us"), Node("text_field", "Code"))
    les = lesson(tmp_path, page(t, [ev("fill", "text_area", "Why us", "x" * 201),
                                    ev("fill", "text_field", "Code", "482913")]))
    ops = lessons.propose(les, tmp_path / "pages", Bank())["bank"]
    assert [o["keep"] for o in ops] == ["drop", "drop"]


def test_restricted_field_is_marked_sensitive(tmp_path):
    t = tree(Node("combo_box", "Gender"))
    les = lesson(tmp_path, page(t, [ev("choose", "combo_box", "Gender", "Male")]))
    [op] = lessons.propose(les, tmp_path / "pages", Bank())["bank"]
    assert op["sensitive"] is True and op["op"] == "add" and op["key"] == "gender"


def test_lesson_name_validated(tmp_path):
    with pytest.raises(ValueError):
        lessons.load(tmp_path, "../x.json")
    with pytest.raises(ValueError):
        lessons.save(tmp_path, "../x", "d", "s", [])


def known_page(tmp_path, elements, anchors=("head",)):
    pages = tmp_path / "pages"
    pages.mkdir()
    els = {"head": {"role": "heading", "name": "Apply for Engineer", "risk": "read"}, **elements}
    (pages / "acme.yaml").write_text(yaml.safe_dump({"page": {
        "id": "acme", "identification": {"title_matches": "^Apply", "anchors": list(anchors)}, "elements": els}}))
    return pages


def test_known_page_gaining_an_element_lists_it(tmp_path):
    pages = known_page(tmp_path, {})
    les = lesson(tmp_path, page(tree(Node("link", "Jobs")), [ev("click", "link", "Jobs")]))
    [p] = lessons.propose(les, pages, Bank())["pages"]
    assert (p["new"], p["added"]) == (False, ["jobs"])
    assert p["yaml"]["page"]["elements"]["jobs"] == {"role": "link", "name": "Jobs", "risk": "navigate"}


def test_known_page_lower_rating_never_drops_the_recorders_submit(tmp_path):
    pages = known_page(tmp_path, {"send": {"role": "button", "name": "Send", "risk": "navigate"}})
    e = {**ev("click", "button", "Send"), "risk": "submit", "sure": True}
    [p] = lessons.propose(lesson(tmp_path, page(tree(Node("button", "Send")), [e])), pages, Bank())["pages"]
    assert p["steps"][0]["kind"] == "hand_over"
    assert p["yaml"]["page"]["elements"]["send"]["risk"] == "navigate"   # the page file's rating is not rewritten


def test_look_alike_nodes_compare_by_identity(tmp_path):
    pages = known_page(tmp_path, {
        "side": {"role": "group", "dom_id": "side", "risk": "read"},
        "side_next": {"role": "link", "name": "More", "within": "side", "risk": "navigate"}})
    t = tree(Node("group", dom_id="side", children=[Node("link", "More")]),
             Node("group", dom_id="main", children=[Node("link", "More")]))
    e = ev("click", "link", "More")
    e["spec"] = {"role": "link", "name": "More", "index": 1}   # the second one
    [p] = lessons.propose(lesson(tmp_path, page(t, [e])), pages, Bank())["pages"]
    assert p["steps"][0]["target"] == "acme.more" and p["added"] == ["more"]


def test_unresolved_target_is_proposed_but_off(tmp_path):
    les = lesson(tmp_path, page(tree(Node("link", "Jobs")), [ev("click", "link", "Careers")]))   # not in the tree
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert p["steps"][0] == {"kind": "click", "label": "Careers (check this target)",
                             "target": f"{p['id']}.careers", "keep": False}
    assert "careers" in p["yaml"]["page"]["elements"]


def test_clicks_after_hand_over_are_kept_off(tmp_path):
    t = tree(Node("button", "Submit"), Node("link", "Back"))
    les = lesson(tmp_path, page(t, [ev("click", "button", "Submit"), ev("click", "link", "Back")]))
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert [(st["kind"], st["keep"]) for st in p["steps"]] == [("hand_over", True), ("click", False)]


def test_shared_answer_does_not_pick_a_key(tmp_path):
    bank = Bank((Entry("visa", ("Need a visa?",), "Yes"), Entry("remote", ("Remote ok?",), "Yes")))
    les = lesson(tmp_path, page(tree(), [ev("choose", "combo_box", "Willing to relocate?", "Yes"),
                                         ev("choose", "combo_box", "Remote ok?", "Yes")]))
    ops = lessons.propose(les, tmp_path / "pages", bank)["bank"]
    assert [(o["op"], o["key"]) for o in ops] == [("add", "willing_to_relocate")]


def test_failed_write_leaves_no_lesson(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(lessons.json, "dumps", boom)
    with pytest.raises(OSError):
        lessons.save(tmp_path, "job_apply", "d", "s", [page(tree(), [])])
    assert list((tmp_path / "lessons").iterdir()) == []


def test_attach_replays_with_the_chooser_button_and_the_file_input(tmp_path):
    t = tree(Node("button", "Attach"), Node("button", "Attach: No file chosen", dom_id="resume"))
    att = ev("attach", "button", "Attach: No file chosen")
    att["spec"] = {"role": "button", "dom_id": "resume"}
    les = lesson(tmp_path, page(t, [ev("click", "button", "Attach"), att]))
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    pid, els = p["id"], p["yaml"]["page"]["elements"]
    [line] = [s for s in p["steps"] if s["kind"] == "attach_file"]
    assert not line["keep"] and "'Attach'" in line["label"]   # a separate button: the admin checks it first
    assert line["target"] == f"{pid}.button_attach" and line["check"].startswith(pid + ".")
    chk = line["check"].split(".")[1]
    assert els["button_attach"]["risk"] == "modify" and els[chk] == {"role": "button", "dom_id": "resume", "risk": "read"}
    assert lessons._do(line, p) == {"action": "attach_file", "target": line["target"], "check": line["check"]}


def test_a_submit_button_before_an_attach_is_never_kept_as_the_chooser(tmp_path):
    t = tree(Node("button", "Submit application"), Node("button", "Attach: No file chosen", dom_id="resume"))
    att = ev("attach", "button", "Attach: No file chosen")
    att["spec"] = {"role": "button", "dom_id": "resume"}
    les = lesson(tmp_path, page(t, [ev("click", "button", "Submit application"), att]))
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    [line] = [s for s in p["steps"] if s["kind"] == "attach_file"]
    assert not line["keep"] and "'Submit application'" in line["label"]


def test_attach_on_chromes_own_file_input_checks_its_name_prefix(tmp_path):
    t = tree(Node("button", "Choose File No file chosen"))
    les = lesson(tmp_path, page(t, [ev("click", "button", "Choose File No file chosen"),
                                    ev("attach", "button", "Choose File No file chosen")]))
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    [line] = [s for s in p["steps"] if s["kind"] == "attach_file"]
    k = line["target"].split(".")[1]
    assert line["keep"] and line["check"] == line["target"]
    assert p["yaml"]["page"]["elements"][k] == {"role": "button", "name_matches": "^Choose\\ File\\ ", "risk": "modify"}


def test_attach_without_a_usable_input_is_not_replayed(tmp_path):
    from govaios.panel import lesson as lesson_ui
    t = tree(Node("button", "No file chosen"))
    les = lesson(tmp_path, page(t, [ev("attach", "button", "No file chosen")]))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    [p] = prop["pages"]
    assert p["steps"][0]["kind"] == "attach_file" and not p["steps"][0]["keep"]
    assert lessons._do(p["steps"][0], p) is None
    assert "Attach your CV: No file chosen (not replayed)" in lesson_ui.page("n", les, prop, set(), {}, "")


def test_level():
    assert lessons.level("tab", "Shortlisted (2)") == "navigate"
    assert lessons.level("button", "Review") == "navigate"
    assert lessons.level("button", "Approve & promote") == "submit"
    assert lessons.level("button", "Pay now") == "payment"
    assert lessons.level("button", "Frobnicate") == "submit"
    assert lessons.level("button", "Review and submit") == "submit"
    assert lessons.level("link", "Pay now") == "navigate"


def test_write_rewrites_one_lesson_in_place(tmp_path):
    name = lessons.new_name("teach_new")
    lessons.write(tmp_path, name, {"flow": "teach_new", "pages": []})
    lessons.write(tmp_path, name, {"flow": "teach_new", "pages": [1]})
    assert lessons.load(tmp_path, name)["pages"] == [1]
    assert [p.name for p in (tmp_path / "lessons").iterdir()] == [name]
    assert os.stat(tmp_path / "lessons" / name).st_mode & 0o777 == 0o600


def test_leftover_tmp_does_not_block_a_write(tmp_path):
    name = lessons.new_name("teach_new")
    (tmp_path / "lessons").mkdir()
    (tmp_path / "lessons" / (name + ".tmp")).write_text("half")
    lessons.write(tmp_path, name, {"flow": "teach_new", "pages": []})
    assert lessons.load(tmp_path, name)["pages"] == []


def joblens(tmp_path):
    """An extension lesson on JobLens (the recorder's doc), bound to a new_automation app; returns (lesson, app path)."""
    import shutil
    from govaios import capture, studio
    from govaios.approvals import read_bound
    from govaios.engine import REPO
    shutil.copytree(REPO / "pages", tmp_path / "pages")
    (tmp_path / "flows").mkdir()
    app = studio.new_automation(tmp_path / "flows", "Approve shortlisted", "http://localhost:8100/",
                                {"profile_directory": "Default", "account": "a@x.example"})
    home = Node("document", "JobLens", children=[Node("heading", "Applications"), Node("link", "Discover")])
    disc = Node("document", "JobLens", children=[
        Node("heading", "Discover"), Node("tab", "Shortlisted (2)"),
        *[Node("row", "", children=[Node("cell", c), Node("button", "Review")]) for c in ("Acme", "Globex")]])

    def click(spec, label, risk="navigate"):
        return {"kind": "click", "spec": spec, "label": label, "value": "", "secure": False, "submit": risk != "navigate",
                "risk": risk, "sure": True}
    name = lessons.new_name("teach_new")
    lessons.write(tmp_path, name, {"flow": "teach_new", "digest": None, "step": None, "at": "2026-11-12T10:00:00",
                                   "new_app": True, "pages": [
        {"url": "http://localhost:8100/", "title": "JobLens · Applications", "tree": capture.tree(home),
         "events": [click({"role": "link", "name": "Discover"}, "Discover")]},
        {"url": "http://localhost:8100/discover", "title": "JobLens · Discover", "tree": capture.tree(disc),
         "events": [click({"role": "tab", "name_matches": "^Shortlisted \\(\\d+\\)$"}, "Shortlisted"),
                    click({"role": "button", "name": "Review", "index": 0}, "Review"),
                    # pressed in a pop-up: not in the page's first snapshot, so only the recorder's reading is sure
                    click({"role": "button", "name": "Approve & promote"}, "Approve & promote", "submit")]}]})
    lessons.bind(tmp_path, name, "studio_approve_shortlisted", read_bound(app, tmp_path / "pages")[0], "on_start")
    return lessons.load(tmp_path, name), app


def test_joblens_lesson_builds_two_cases(tmp_path):
    from govaios import studio
    from govaios.approvals import read_bound
    les, app = joblens(tmp_path)
    assert (les["flow"], les["step"], les["new_app"]) == ("studio_approve_shortlisted", "on_start", True)
    d, raw = read_bound(app, tmp_path / "pages")
    assert les["digest"] == d
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    plan = lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml",
                         require_outcomes=False)
    on = next(s for s in yaml.safe_load(plan["flow"][1])["workflow"]["steps"] if s["id"] == "on_start")["on_match"]
    new = prop["pages"][1]["id"]
    assert list(on) == ["joblens_applications", new, "unknown"]
    assert on["joblens_applications"] == {"do": [{"id": "learned_joblens_applications_1", "action": "click",
                                                  "target": "joblens_applications.discover"}], "then": "again"}
    assert [s["action"] for s in on[new]["do"]] == ["click", "click", "click"] and on[new]["then"] == "end"
    assert [s.get("target") for s in on[new]["do"]] == [f"{new}.shortlisted", f"{new}.button_review", f"{new}.approve_promote"]
    pg = prop["pages"][1]["yaml"]["page"]
    assert [pg["elements"][a] for a in pg["identification"]["anchors"]][0]["name"] == "Discover"
    assert not lessons._identifies(pg, studio._as_nodes(les["pages"][0]["tree"])[0])   # never the home page


def test_preview_lines_and_yaml(tmp_path):
    les, _ = joblens(tmp_path)
    lines, text = lessons.preview(les, tmp_path / "pages", Bank())
    assert lines == ["JobLens · Applications: click Discover", "JobLens · Discover: click Shortlisted",
                     "JobLens · Discover: click Review", "JobLens · Discover: press Approve & promote"]
    cases = yaml.safe_load(text)
    assert list(cases) == ["joblens_applications", "localhost_joblens"] and cases["localhost_joblens"]["then"] == "end"


def _approve_lesson(tmp_path, url, label="Approve & promote", risk="submit"):
    t = tree(Node("button", "Review"), Node("button", label))
    ev2 = {**ev("click", "button", label), "risk": risk, "sure": True}
    return lesson(tmp_path, page(t, [{**ev("click", "button", "Review"), "risk": "navigate", "sure": True}, ev2], url))


def test_own_app_submit_click_is_a_press(tmp_path):
    les, app = joblens(tmp_path)
    from govaios.approvals import read_bound
    d, raw = read_bound(app, tmp_path / "pages")
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    steps = prop["pages"][1]["steps"]
    assert steps[2]["kind"] == "click" and steps[2]["press"] is True
    assert all(s["kind"] != "hand_over" for p in prop["pages"] for s in p["steps"])
    plan = lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml", require_outcomes=False)
    wf = yaml.safe_load(plan["flow"][1])["workflow"]
    on = next(s for s in wf["steps"] if s["id"] == "on_start")["on_match"]
    do = on[prop["pages"][1]["id"]]["do"]
    assert do[-1]["action"] == "click" and do[-1]["target"].endswith(".approve_promote")
    assert wf["permissions"]["max_element_risk"] == "submit"


def test_outside_submit_click_stays_hand_over(tmp_path):
    les = _approve_lesson(tmp_path, "https://acme.example/jobs")
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert kinds(p) == ["click", "hand_over"] and "press" not in p["steps"][1]


def test_payment_click_on_own_app_stays_hand_over(tmp_path):
    les = _approve_lesson(tmp_path, "http://localhost:8100/pay", "Pay now", "payment")
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert kinds(p) == ["click", "hand_over"] and "press" not in p["steps"][1]


def test_build_never_lowers_max_element_risk(tmp_path):
    les, app = joblens(tmp_path)
    from govaios.approvals import read_bound
    doc = yaml.safe_load(app.read_bytes())
    doc["workflow"]["permissions"]["max_element_risk"] = "submit"
    app.write_text(yaml.safe_dump(doc, sort_keys=False))
    _, raw = read_bound(app, tmp_path / "pages")
    for lp in les["pages"]:
        lp["events"] = [e for e in lp["events"] if e.get("risk") == "navigate"]
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    plan = lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml")
    assert yaml.safe_load(plan["flow"][1])["workflow"]["permissions"]["max_element_risk"] == "submit"


def test_mixed_lesson_presses_own_page_and_hands_over_outside_page(tmp_path):
    def pg(url, title):
        t = tree(Node("button", "Review"), Node("button", "Approve & promote"), title=title)
        return page(t, [{**ev("click", "button", "Review"), "risk": "navigate", "sure": True},
                        {**ev("click", "button", "Approve & promote"), "risk": "submit", "sure": True}], url)
    les = lesson(tmp_path, pg("http://localhost:8100/discover", "Own"), pg("https://acme.example/jobs", "Jobs | Acme"))
    a, b = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert kinds(a) == ["click", "click"] and a["steps"][1]["press"] is True
    assert kinds(b) == ["click", "hand_over"] and "press" not in b["steps"][1]
    assert b["steps"][-1]["keep"]   # the closing hand-over is there (the outside page's own submit)


def test_panel_port_submit_click_stays_hand_over(tmp_path):
    les = _approve_lesson(tmp_path, "http://127.0.0.1:8765/discover")
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert kinds(p) == ["click", "hand_over"] and "press" not in p["steps"][1]


def test_deleted_press_leaves_max_element_risk_alone(tmp_path):
    les, app = joblens(tmp_path)
    from govaios.approvals import read_bound
    _, raw = read_bound(app, tmp_path / "pages")
    before = yaml.safe_load(raw[app])["workflow"]["permissions"]["max_element_risk"]
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    j = next(j for j, s in enumerate(prop["pages"][1]["steps"]) if s.get("press"))
    plan = lessons.build(les, prop, {(1, j)}, {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml")
    after = yaml.safe_load(plan["flow"][1])["workflow"]["permissions"]["max_element_risk"]
    assert after == before and before != "submit"


def test_repeatable_finds_the_review_row(tmp_path):
    les, _ = joblens(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert lessons.repeatable(prop, les) == {1: 1}   # Shortlisted, Review (0), Approve & promote


def test_build_wraps_the_round_in_repeat(tmp_path):
    from govaios.approvals import read_bound
    les, app = joblens(tmp_path)
    _, raw = read_bound(app, tmp_path / "pages")
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    plan = lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml", {1: 10}, require_outcomes=False)
    on = next(s for s in yaml.safe_load(plan["flow"][1])["workflow"]["steps"] if s["id"] == "on_start")["on_match"]
    new = prop["pages"][1]["id"]
    review = f"{new}.button_review"
    assert on[new]["do"] == [
        {"id": f"learned_{new}_1", "action": "click", "target": f"{new}.shortlisted"},
        {"id": f"learned_{new}_r1", "action": "repeat", "item": review, "max": 10, "steps": [
            {"id": f"learned_{new}_2", "action": "click", "target": review},
            {"id": f"learned_{new}_3", "action": "click", "target": f"{new}.approve_promote"}]}]
    from govaios import engine
    engine.check_learned(yaml.safe_load(plan["flow"][1])["workflow"]["steps"])
    with pytest.raises(ValueError):   # a page with no list
        lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml", {0: 10})
    with pytest.raises(ValueError):   # the first repeated line deleted
        lessons.build(les, prop, {(1, 1)}, {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml", {1: 10})


def test_repeat_refusals_and_same_bytes(tmp_path):
    from govaios.approvals import read_bound
    les, app = joblens(tmp_path)
    _, raw = read_bound(app, tmp_path / "pages")
    prop = lessons.propose(les, tmp_path / "pages", Bank())

    def build(prop=prop, **kw):
        return lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml", **kw, require_outcomes=False)
    a, b = build(repeats={1: 10}), build(repeats={1: 10})   # tick, untick, tick: same flow, same digest
    assert build(repeats={1: 10})["flow"] == a["flow"] and a["flow"] == b["flow"] and a["digest"] == b["digest"]
    assert build()["flow"] != a["flow"]
    hand = copy.deepcopy(prop)
    hand["pages"][1]["steps"].append({"kind": "hand_over", "label": "You check", "target": "x.y", "keep": True})
    with pytest.raises(ValueError, match="hand-over"):
        build(hand, repeats={1: 10})
    assert build(hand)   # without the repeat it is fine
    on = next(s for s in yaml.safe_load(a["flow"][1])["workflow"]["steps"] if s["id"] == "on_start")["on_match"]
    assert prop["pages"][1]["id"] in on
    raw2 = {**raw, app: a["flow"][1]}   # the flow now handles that page
    with pytest.raises(ValueError, match="already in the app"):
        lessons.build(les, prop, set(), {}, raw2, app, tmp_path / "pages", tmp_path / "answers.yaml", {1: 10})


def test_closing_hand_over_follows_the_repeat(tmp_path):
    from govaios.approvals import read_bound
    les, app = joblens(tmp_path)
    _, raw = read_bound(app, tmp_path / "pages")
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    prop["pages"][1]["steps"].append({"kind": "hand_over", "label": "You check and submit", "target": None, "keep": True})
    plan = lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml", {1: 10}, require_outcomes=False)
    on = next(s for s in yaml.safe_load(plan["flow"][1])["workflow"]["steps"] if s["id"] == "on_start")["on_match"]
    do = on[prop["pages"][1]["id"]]["do"]
    assert [d["action"] for d in do] == ["click", "repeat", "hand_over"]
    assert [d["action"] for d in do[1]["steps"]] == ["click", "click"]


def test_known_page_storing_navigate_is_raised_to_submit_when_the_recorder_reads_submit(tmp_path):
    les, app = joblens(tmp_path)
    pages = tmp_path / "pages"
    p = lessons.propose(les, pages, Bank())["pages"][1]
    page = p["yaml"]["page"]
    page["elements"]["approve_promote"]["risk"] = "navigate"
    (pages / f"{p['id']}.yaml").write_text(yaml.safe_dump({"page": page}))
    p2 = lessons.propose(les, pages, Bank())["pages"][1]
    assert not p2["new"]
    press = next(s for s in p2["steps"] if s.get("press"))
    assert press["target"] == f"{p2['id']}.approve_promote"
    assert p2["yaml"]["page"]["elements"]["approve_promote"]["risk"] == "submit"
    assert "approve_promote" in p2["added"]   # shown as "Adds to this page", and the page is rewritten


# ---------- outcomes: proposed per press, ticked by the admin, written by build ----------

def _discover(promoted, names, inbox=3):
    from govaios import capture
    return capture.tree(Node("document", "JobLens", children=[
        Node("heading", "Discover"), Node("tab", f"Shortlisted ({len(names)})"), Node("tab", f"Promoted ({promoted})"),
        Node("link", f"Inbox ({inbox})"),
        *[Node("row", "", children=[Node("cell", c), Node("button", "Review")]) for c in names]]))


def joblens_outcomes(tmp_path, inbox_after=3):
    """joblens() with each click's "before" tree and a Done tree: Promoted 7 -> 8, Acme left the list."""
    from govaios import capture
    les, app = joblens(tmp_path)
    home = capture.tree(Node("document", "JobLens", children=[Node("heading", "Applications"), Node("link", "Discover")]))
    les["pages"][0]["events"][0]["before"] = home
    for e in les["pages"][1]["events"]:
        e["before"] = _discover(7, ["Acme", "Globex"])
    les["done_tree"], les["done_url"] = _discover(8, ["Globex"], inbox_after), "http://localhost:8100/discover"
    return les, app


def _press(prop):
    return next((i, j) for i, p in enumerate(prop["pages"]) for j, s in enumerate(p["steps"]) if s.get("press"))


def test_propose_count_and_item_left(tmp_path):
    les, _ = joblens_outcomes(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    i, j = _press(prop)
    outs = prop["pages"][i]["steps"][j]["outcomes"]
    [c] = [o for o in outs if o["kind"] == "count" and o["label"] == "Promoted"]
    assert (c["role"], c["before"], c["after"], c["change"], c["at"], c["page"]) == \
        ("tab", 7, 8, 1, [1, 2], prop["pages"][1]["id"])
    assert {"kind": "item_left", "at": [1, 2], "page": prop["pages"][1]["id"]} in outs
    assert all(s.get("outcomes") is None for p in prop["pages"] for s in p["steps"] if not s.get("press"))


def test_propose_hr_after_later_click(tmp_path):
    from govaios import capture

    def hr(n):
        return capture.tree(tree(Node("button", "Schedule"), Node("tab", f"Scheduled ({n})"), title="HR"))
    les = lesson(tmp_path, page(tree(Node("button", "Schedule"), Node("tab", "Scheduled (3)"), title="HR"), [
        {**ev("click", "button", "Schedule"), "risk": "submit", "sure": True, "before": hr(3)},
        {"kind": "click", "spec": {"role": "tab", "name_matches": "^Scheduled \\(\\d+\\)$"}, "label": "Scheduled",
         "risk": "navigate", "sure": True, "before": hr(3)}], "http://localhost:8100/hr"))
    les["done_tree"] = hr(4)
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert p["steps"][0]["press"] and p["steps"][1]["kind"] == "click"
    assert p["steps"][0]["outcomes"] == [{"kind": "count", "role": "tab", "label": "Scheduled", "before": 3,
                                          "after": 4, "change": 1, "at": [0, 1], "page": p["id"],
                                          "adds": None}]


def test_old_lesson_without_trees_proposes_no_outcome(tmp_path):
    les, _ = joblens(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    i, j = _press(prop)
    assert prop["pages"][i]["steps"][j]["outcomes"] == []


def _plan(tmp_path, les, app, prop, deleted=(), **kw):
    from govaios.approvals import read_bound
    _, raw = read_bound(app, tmp_path / "pages")
    return lessons.build(les, prop, set(deleted), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml", **kw)


def _tick(prop, want):
    i, j = _press(prop)
    return {(i, j): [k for k, o in enumerate(prop["pages"][i]["steps"][j]["outcomes"]) if want(o)]}


def test_spurious_counts_are_proposed_unticked(tmp_path):
    les, app = joblens_outcomes(tmp_path, inbox_after=4)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    i, j = _press(prop)
    assert any(o.get("label") == "Inbox" and o["change"] == 1 for o in prop["pages"][i]["steps"][j]["outcomes"])
    plan = _plan(tmp_path, les, app, prop, outcomes=_tick(prop, lambda o: o.get("label") == "Promoted"))
    assert b"inbox" not in plan["flow"][1].lower()
    assert all(b"Inbox" not in b for b in plan["pages"].values())


def test_edits_reads_outcome_ticks():
    from govaios.panel import lesson as lesson_ui
    prop = {"pages": [{"steps": [{}, {}, {"outcomes": [{"kind": "item_left", "at": [0, 2], "page": "p"}]}]}],
            "bank": []}
    assert lesson_ui.edits(prop, {"out:0:2:0": "1"})[3] == {(0, 2): [0]}
    for bad in ("out:9:9:9", "out:0:2:1", "out:0:1:0"):
        with pytest.raises(ValueError):
            lesson_ui.edits(prop, {bad: "1"})


def test_lesson_page_shows_unticked_proposals(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, _ = joblens_outcomes(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    html = lesson_ui.page("n", les, prop, set(), {}, "")
    assert "<input type=checkbox name='out:1:2:0' value=1>" in html
    assert "Promoted 7 → 8 (+1), checked after: Approve &amp; promote" in html
    assert "this round&#x27;s item left the list, checked after: Approve &amp; promote" in html


def test_build_writes_outcomes_and_element(tmp_path):
    from govaios import engine
    les, app = joblens_outcomes(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    new = prop["pages"][1]["id"]
    plan = _plan(tmp_path, les, app, prop, outcomes=_tick(prop, lambda o: o.get("label") == "Promoted"))
    wf = yaml.safe_load(plan["flow"][1])["workflow"]
    on = next(s for s in wf["steps"] if s["id"] == "on_start")["on_match"]
    press = on[new]["do"][-1]
    assert press["outcomes"] == [{"for": press["id"], "kind": "count", "target": f"{new}.promoted_count", "change": 1}]
    pg = yaml.safe_load(plan["pages"][tmp_path / "pages" / f"{new}.yaml"])["page"]
    assert pg["elements"]["promoted_count"] == {"role": "tab", "name_matches": "^Promoted \\(\\d+\\)$", "risk": "navigate"}
    engine.check_learned(wf["steps"], {new: pg})
    # with the Repeat ticked, the item_left proposal goes on the press inside the round
    plan = _plan(tmp_path, les, app, prop, repeats={1: 10}, outcomes=_tick(prop, lambda o: True))
    wf = yaml.safe_load(plan["flow"][1])["workflow"]
    press = next(s for s in wf["steps"] if s["id"] == "on_start")["on_match"][new]["do"][1]["steps"][-1]
    assert [o["kind"] for o in press["outcomes"]].count("item_left") == 1 and press["outcomes"][0]["for"] == press["id"]
    pg = yaml.safe_load(plan["pages"][tmp_path / "pages" / f"{new}.yaml"])["page"]
    engine.check_learned(wf["steps"], {new: pg})


def test_build_refuses_press_without_outcome(tmp_path):
    les, app = joblens_outcomes(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    with pytest.raises(ValueError, match="^needs an outcome: Approve & promote$"):
        _plan(tmp_path, les, app, prop)
    assert _plan(tmp_path, les, app, prop, require_outcomes=False)   # Try it never presses
    with pytest.raises(ValueError, match="the step an outcome is checked after was removed"):
        _plan(tmp_path, les, app, prop, deleted=[_press(prop)], outcomes=_tick(prop, lambda o: True))


def test_two_presses_first_reads_only_up_to_the_second(tmp_path):
    from govaios import capture

    def hr(a, b):
        return capture.tree(tree(Node("button", "Schedule"), Node("button", "Approve"), Node("tab", f"Scheduled ({a})"),
                                 Node("tab", f"Approved ({b})"), title="HR"))
    les = lesson(tmp_path, page(tree(Node("button", "Schedule"), Node("button", "Approve"), title="HR"), [
        {**ev("click", "button", "Schedule"), "risk": "submit", "sure": True, "before": hr(3, 1)},
        {**ev("click", "button", "Approve"), "risk": "submit", "sure": True, "before": hr(4, 1)}],
        "http://localhost:8100/hr"))
    les["done_tree"] = hr(4, 2)   # only the second press changed Approved
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert [(o["label"], o["at"]) for o in p["steps"][0]["outcomes"]] == [("Scheduled", [0, 0])]
    assert [(o["label"], o["at"]) for o in p["steps"][1]["outcomes"]] == [("Approved", [0, 1])]


def test_build_refuses_when_only_the_at_line_is_deleted(tmp_path):
    les, app = joblens_outcomes(tmp_path)
    tab = dict(les["pages"][1]["events"][0])   # after the press, a click on the Shortlisted tab, then Done
    les["pages"][1]["events"].append(tab)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    i, j = _press(prop)
    ticks = _tick(prop, lambda o: o.get("label") == "Promoted")
    assert prop["pages"][i]["steps"][j]["outcomes"][ticks[(i, j)][0]]["at"] == [1, 3]
    assert _plan(tmp_path, les, app, prop, outcomes=ticks)
    with pytest.raises(ValueError, match="the step an outcome is checked after was removed"):
        _plan(tmp_path, les, app, prop, deleted=[(1, 3)], outcomes=ticks)


# ---------- ratings for "Request ...", Search and Filter ----------

def test_level_request_buttons_are_modify():
    assert lessons.level("button", "Request payment of invoice INV-1001") == "modify"
    assert lessons.level("button", "Request bank change for E-0012") == "modify"
    assert lessons.level("button", "Requested items") != "modify"


def test_level_search_and_filter_are_navigate():
    for n in ("Search", "Filter employees", "Filter invoices", "Apply filter", "Apply filters"):
        assert lessons.level("button", n) == "navigate"


def test_level_unchanged_for_save_pay_submit():
    assert lessons.level("button", "Save address for E-0004") == "submit"
    assert lessons.level("button", "Create invoice") == "submit"
    assert lessons.level("button", "Pay invoice INV-1001") == "payment"
    assert lessons.level("button", "Review and submit") == "submit"
    assert lessons.level("button", "Apply") == "submit"


def _request_lesson(tmp_path, label):
    les, app = joblens(tmp_path)
    les["pages"][1]["url"] = "http://localhost:8100/payruns/PR-2026-03"
    les["pages"][1]["events"][-1] = {"kind": "click", "spec": {"role": "button", "name": label}, "label": label,
                                     "value": "", "secure": False, "submit": True, "risk": "modify", "sure": True}
    return les, app


def test_request_press_on_new_page_is_plain_click(tmp_path):
    from govaios.approvals import read_bound
    les, app = _request_lesson(tmp_path, "Request release of PR-2026-03")
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    p = prop["pages"][1]
    assert p["new"] and p["steps"][-1]["kind"] == "click" and "press" not in p["steps"][-1]
    assert p["yaml"]["page"]["elements"]["request_release_of_pr_2026_03"]["risk"] == "modify"
    _, raw = read_bound(app, tmp_path / "pages")
    plan = lessons.build(les, prop, set(), {}, raw, app, tmp_path / "pages", tmp_path / "answers.yaml",
                         require_outcomes=True)
    assert yaml.safe_load(plan["flow"][1])["workflow"]["permissions"]["max_element_risk"] == "modify"


def test_request_on_known_page_keeps_stored_rating(tmp_path):
    les, _ = _request_lesson(tmp_path, "Request release of PR-2026-03")
    pages = tmp_path / "pages"
    p = lessons.propose(les, pages, Bank())["pages"][1]
    page = p["yaml"]["page"]
    page["elements"]["request_release_of_pr_2026_03"]["risk"] = "submit"
    (pages / f"{p['id']}.yaml").write_text(yaml.safe_dump({"page": page}))
    p2 = lessons.propose(les, pages, Bank())["pages"][1]
    assert not p2["new"]
    press = p2["steps"][-1]
    assert press.get("press") is True and press["label"].endswith(" (kept at submit: known page)")
    assert p2["yaml"]["page"]["elements"]["request_release_of_pr_2026_03"]["risk"] == "submit"


# --- typed text (teach-typed-text Task 4)

def _typed(tmp_path, *fields):
    """The JobLens lesson with fields (label, value) typed on Discover before the press; (lesson, app)."""
    les, app = joblens(tmp_path)
    evs = les["pages"][1]["events"]
    for label, value in fields:
        les["pages"][1]["tree"]["children"].append({"role": "text_field", "name": label})
        evs.insert(len(evs) - 1, {"kind": "type", "spec": {"role": "text_field", "name": label}, "label": label,
                                  "value": value, "secure": False, "risk": "modify", "sure": True, "before": None})
    return les, app


def _type_lines(prop):
    return [(i, j, s) for i, p in enumerate(prop["pages"]) for j, s in enumerate(p["steps"]) if s["kind"] == "type"]


def _typed_flow(tmp_path, bank=Bank(), fields=(("Home address", "9 Willow Terrace"),), src=None):
    les, app = _typed(tmp_path, *fields)
    prop = lessons.propose(les, tmp_path / "pages", bank)
    lines = _type_lines(prop)
    sources = {(i, j): (src, s["label"]) for i, j, s in lines} if src else None
    plan = _plan(tmp_path, les, app, prop, require_outcomes=False, sources=sources)
    wf = yaml.safe_load(plan["flow"][1])["workflow"]
    steps = [d for c in next(s for s in wf["steps"] if s["id"] == "on_start")["on_match"].values()
             if isinstance(c, dict) for d in c["do"] if d["action"] == "type"]
    return prop, plan, wf, steps


def test_propose_type_line_defaults_to_input(tmp_path):
    les, _ = _typed(tmp_path, ("Home address", "9 Willow Terrace"))
    [(_, _, s)] = _type_lines(lessons.propose(les, tmp_path / "pages", Bank()))
    assert (s["source"], s["input"], s["value"], s["bank_key"], s["keep"]) == \
        ("input", "home_address", "9 Willow Terrace", None, True)
    assert s["bank_op"]["op"] == "add" and s["bank_op"]["key"]


def _city(tmp_path, typed):
    from govaios.panel import lesson as lesson_ui
    les, _ = _typed(tmp_path, ("City", typed))
    prop = lessons.propose(les, tmp_path / "pages", Bank((Entry("city", ("City",), "Bengaluru <B>"),)))
    [(i, j, s)] = _type_lines(prop)
    return prop, s, lesson_ui.page("n", les, prop, set(), {}, ""), f"name='src:{i}:{j}'"


def test_propose_type_line_bank_when_label_known(tmp_path):
    prop, s, html, src = _city(tmp_path, "Bengaluru <B>")
    assert (s["source"], s["bank_key"], s["bank_value"], s["bank_op"]) == ("bank", "city", "Bengaluru <B>", None)
    assert prop["bank"] == []
    assert f"<input type=radio {src} value=bank checked> From the bank: <code>city</code> = “Bengaluru &lt;B&gt;”" in html


def test_propose_type_line_input_when_bank_answer_differs(tmp_path):
    _, s, html, src = _city(tmp_path, "Pune")   # Run would type the bank's answer, not what the page shows
    assert (s["source"], s["bank_key"], s["bank_op"]) == ("input", "city", None)   # a change op is never offered
    assert f"<input type=radio {src} value=input checked>" in html
    assert f"<input type=radio {src} value=bank> From the bank: <code>city</code> = “Bengaluru &lt;B&gt;”" in html


def test_propose_skips_a_secure_type_event(tmp_path):
    les, _ = _typed(tmp_path, ("Home address", "9 Willow Terrace"))
    next(e for e in les["pages"][1]["events"] if e["kind"] == "type")["secure"] = True
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert _type_lines(prop) == [] and "9 Willow Terrace" not in str(prop)


def test_input_name_slug():
    assert [lessons._input_name(x) for x in ("Home address", "", "2nd line", "Ünïcode?!", "x" * 50)] == \
        ["home_address", "text", "t_2nd_line", "n_code", "x" * 40]


def test_build_type_literal(tmp_path):
    _, plan, wf, [s] = _typed_flow(tmp_path, src="literal")
    assert {k: v for k, v in s.items() if k != "id"} == {"action": "type", "target": s["target"],
                                                       "value": "9 Willow Terrace"}
    assert "inputs" not in wf and "type_text" in wf["permissions"]["allow"]


def test_build_type_input(tmp_path):
    _, plan, wf, [s] = _typed_flow(tmp_path)
    assert set(s) == {"id", "action", "target", "value_from"} and s["value_from"] == "input.home_address"
    assert wf["inputs"]["home_address"] == {"label": "Home address (on JobLens · Discover)",
                                            "pattern": "[^\\x00-\\x1f]{1,200}"}
    assert "type_text" in wf["permissions"]["allow"]
    page = yaml.safe_load(next(b for b in plan["pages"].values() if b"home_address" in b))["page"]
    assert page["elements"]["home_address"]["risk"] == "modify"


def test_build_type_bank(tmp_path):
    prop, plan, wf, [s] = _typed_flow(tmp_path, src="bank")
    [(_, _, line)] = _type_lines(prop)
    assert set(s) == {"id", "action", "target", "bank"} and s["bank"] == line["bank_op"]["key"]
    assert {**line["bank_op"], "keep": "bank"} in plan["ops"] and "type_text" in wf["permissions"]["allow"]


def test_build_type_raises_max_element_risk_to_modify(tmp_path):
    from govaios.approvals import read_bound
    les, app = _typed(tmp_path, ("Home address", "9 Willow Terrace"))
    doc = yaml.safe_load(app.read_text())
    doc["workflow"]["permissions"]["max_element_risk"] = "navigate"
    app.write_text(yaml.safe_dump(doc, sort_keys=False))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    press = _press(prop)
    plan = lessons.build(les, prop, {press}, {}, read_bound(app, tmp_path / "pages")[1], app, tmp_path / "pages",
                         tmp_path / "answers.yaml", require_outcomes=False)
    assert yaml.safe_load(plan["flow"][1])["workflow"]["permissions"]["max_element_risk"] == "modify"


def test_build_input_names_clash_get_suffix(tmp_path):
    _, _, wf, steps = _typed_flow(tmp_path, fields=(("Amount", "1"), ("Amount", "2")))
    assert [s["value_from"] for s in steps] == ["input.amount", "input.amount_2"]
    assert list(wf["inputs"]) == ["amount", "amount_2"]


def test_build_input_name_clashes_with_an_existing_input(tmp_path):
    from govaios.approvals import read_bound
    les, app = _typed(tmp_path, ("Home address", "9 Willow Terrace"))
    doc = yaml.safe_load(app.read_text())
    doc["workflow"]["inputs"] = {"home_address": {"label": "Old", "pattern": "x"}}
    app.write_text(yaml.safe_dump(doc, sort_keys=False))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    plan = lessons.build(les, prop, set(), {}, read_bound(app, tmp_path / "pages")[1], app, tmp_path / "pages",
                         tmp_path / "answers.yaml", require_outcomes=False)
    assert list(yaml.safe_load(plan["flow"][1])["workflow"]["inputs"]) == ["home_address", "home_address_2"]


# --- taught choices (teach-choices Task 4)

def _chose(tmp_path, dept="Engineering", tick="1"):
    """The JobLens lesson with Department picked, Overdue only ticked and Filter clicked before the press."""
    les, app = joblens(tmp_path)
    p = les["pages"][1]
    p["tree"]["children"] += [{"role": "popup_button", "name": "Department"},
                              {"role": "checkbox", "name": "Overdue only"}, {"role": "button", "name": "Filter"}]
    p["events"][-1:-1] = [
        {"kind": "pick", "spec": {"role": "popup_button", "name": "Department"}, "label": "Department", "value": dept,
         "secure": False, "risk": "modify", "sure": True, "before": None},
        {"kind": "tickbox", "spec": {"role": "checkbox", "name": "Overdue only"}, "label": "Overdue only",
         "value": tick, "secure": False, "risk": "modify", "sure": True, "before": None},
        {"kind": "click", "spec": {"role": "button", "name": "Filter"}, "label": "Filter", "value": "",
         "secure": False, "submit": False, "risk": "navigate", "sure": True}]
    return les, app


def _choice_lines(prop):
    return [(i, j, s) for i, p in enumerate(prop["pages"]) for j, s in enumerate(p["steps"])
            if s["kind"] in ("choose", "tick")]


def test_propose_pick_and_tickbox_lines(tmp_path):
    les, _ = _chose(tmp_path)
    p = lessons.propose(les, tmp_path / "pages", Bank())["pages"][1]
    pid = p["id"]
    assert [(s["kind"], s["label"], s["target"], s["keep"], s.get("value")) for s in p["steps"][2:5]] == [
        ("choose", "Department", f"{pid}.department", True, "Engineering"),
        ("tick", "Overdue only", f"{pid}.overdue_only", True, True),
        ("click", "Filter", f"{pid}.button_filter", True, None)]
    assert p["yaml"]["page"]["elements"]["department"] == {"role": "popup_button", "name": "Department",
                                                           "risk": "modify"}


def test_propose_choice_on_known_page_above_modify_is_unsure(tmp_path):
    les, _ = _chose(tmp_path)
    pages = tmp_path / "pages"
    p = lessons.propose(les, pages, Bank())["pages"][1]
    page = p["yaml"]["page"]
    page["elements"]["department"]["risk"] = "submit"
    (pages / f"{p['id']}.yaml").write_text(yaml.safe_dump({"page": page}))
    p2 = lessons.propose(les, pages, Bank())["pages"][1]
    assert not p2["new"]
    [s] = [s for s in p2["steps"] if s["kind"] == "choose"]
    assert (s["label"], s["keep"]) == ("Department (check this target)", False)


def test_propose_choice_after_hand_over_is_dead(tmp_path):
    t = tree(Node("button", "Submit"), Node("popup_button", "Department"))
    pick = {**ev("pick", "popup_button", "Department", "Engineering"), "risk": "modify", "sure": True}
    les = lesson(tmp_path, page(t, [ev("click", "button", "Submit"), pick]))
    [p] = lessons.propose(les, tmp_path / "pages", Bank())["pages"]
    assert [(s["kind"], s["keep"]) for s in p["steps"]] == [("hand_over", True), ("choose", False)]


def _chose_flow(tmp_path, **kw):
    les, app = _chose(tmp_path, **kw)
    doc = yaml.safe_load(app.read_text())
    doc["workflow"]["permissions"] = {"allow": [a for a in doc["workflow"]["permissions"]["allow"]
                                                if a != "fill_field"], "max_element_risk": "navigate"}
    app.write_text(yaml.safe_dump(doc, sort_keys=False))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    return les, app, prop


def test_build_choose_and_tick_steps(tmp_path):
    les, app, prop = _chose_flow(tmp_path)
    plan = _plan(tmp_path, les, app, prop, {_press(prop)}, require_outcomes=False)
    wf = yaml.safe_load(plan["flow"][1])["workflow"]
    pid = prop["pages"][1]["id"]
    do = [{k: v for k, v in d.items() if k != "id"} for d in
          next(s for s in wf["steps"] if s["id"] == "on_start")["on_match"][pid]["do"]]
    assert {"action": "choose", "target": f"{pid}.department", "value": "Engineering"} in do
    assert {"action": "tick", "target": f"{pid}.overdue_only", "value": True} in do
    perms = wf["permissions"]
    assert "fill_field" in perms["allow"] and "type_text" not in perms["allow"]
    assert perms["max_element_risk"] == "modify"


def test_preview_shows_choose_and_tick(tmp_path):
    les, _ = _chose(tmp_path)
    lines, text = lessons.preview(les, tmp_path / "pages", Bank())
    assert lines[3:6] == ["JobLens · Discover: choose Engineering in Department",
                          "JobLens · Discover: tick Overdue only", "JobLens · Discover: click Filter"]
    do = yaml.safe_load(text)["localhost_joblens"]["do"]
    assert [(d["action"], d.get("value")) for d in do][2:4] == [("choose", "Engineering"), ("tick", True)]
    les2, _ = _chose(tmp_path / "b", tick="0")
    assert "JobLens · Discover: untick Overdue only" in lessons.preview(les2, tmp_path / "b" / "pages", Bank())[0]


def test_lesson_page_shows_choice_lines(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, app, prop = _chose_flow(tmp_path, dept="R&D <x>")
    [(i, j, s), (ti, tj, _)] = _choice_lines(prop)
    html = lesson_ui.page("n", les, prop, set(), {}, "")
    assert f"Choose: Department “R&amp;D &lt;x&gt;” <label><input type=checkbox name='del:{i}:{j}' value=1> Delete" in html
    assert f"Tick: Overdue only (on) <label><input type=checkbox name='del:{ti}:{tj}' value=1> Delete" in html
    plan = _plan(tmp_path, les, app, prop, {_press(prop), (i, j), (ti, tj)}, require_outcomes=False)
    wf = yaml.safe_load(plan["flow"][1])["workflow"]
    assert b"choose" not in plan["flow"][1] and b"tick" not in plan["flow"][1]
    assert wf["permissions"]["max_element_risk"] == "navigate"   # no choice step: no fill_field


OLD_HASH = "e6d0f21fb22953570305418d0d088d351d46a7709a90956dbf51255caa7e8523"


def _pin_date(monkeypatch):
    """The drafts write today's date into the bytes: pinned to the day OLD_HASH was taken."""
    import datetime
    from govaios import studio

    class Day(datetime.date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 18)
    monkeypatch.setattr(studio, "date", Day)


def _hash(plan):
    import hashlib
    h = hashlib.sha256(plan["flow"][1])
    for p in sorted(plan["pages"]):
        h.update(plan["pages"][p])
    return h.hexdigest()


def test_build_old_lesson_unchanged(tmp_path, monkeypatch):
    _pin_date(monkeypatch)
    les, app = joblens(tmp_path)
    plan = _plan(tmp_path, les, app, lessons.propose(les, tmp_path / "pages", Bank()), require_outcomes=False)
    # the bytes this lesson built before typed text (commit 189578f); a change to the shipped pages changes it too
    assert _hash(plan) == OLD_HASH
    assert plan["tried"] == {}


def test_build_tried_holds_recorded_values(tmp_path):
    _, plan, _, [s] = _typed_flow(tmp_path)
    assert plan["tried"] == {s["id"]: "9 Willow Terrace"}


def test_lesson_page_shows_source_choices(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, _ = _typed(tmp_path, ("Home <b>address", "9 <Willow> & Terrace"))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    i, j, s = _type_lines(prop)[0]
    s["bank_op"] = None
    html = lesson_ui.page("n", les, prop, set(), {}, "")
    assert f"<input type=radio name='src:{i}:{j}' value=input checked>" in html
    assert f"<input type=radio name='src:{i}:{j}' value=literal>" in html
    assert f"name='lab:{i}:{j}'" in html and f"value=bank" not in html
    assert "9 &lt;Willow&gt; &amp; Terrace" in html and "<Willow>" not in html


def test_edits_reads_sources():
    from govaios.panel import lesson as lesson_ui
    line = {"kind": "type", "label": "Home address", "source": "input", "bank_key": None, "bank_op": None}
    prop = {"pages": [{"steps": [line, {"kind": "click"}]}], "bank": []}
    assert lesson_ui.edits(prop, {"src:0:0": "literal"})[4] == {(0, 0): ("literal", "Home address")}
    assert lesson_ui.edits(prop, {"lab:0:0": "New address"})[4] == {(0, 0): ("input", "New address")}
    assert lesson_ui.edits(prop, {})[4] == {}
    for bad in ({"src:0:0": "bank"}, {"src:0:0": "other"}, {"src:0:1": "input"}, {"lab:0:0": "x" * 61},
                {"lab:0:0": "a\nb"}, {"src:1:0": "input"}):
        with pytest.raises(ValueError):
            lesson_ui.edits(prop, bad)
    line["bank_key"] = "city"
    assert lesson_ui.edits(prop, {"src:0:0": "bank"})[4] == {(0, 0): ("bank", "Home address")}


# ---------- reads: the Done page's tables ----------

def _cell(x):
    return Node("cell", "", children=[Node("text", x)])


def _table(head, rows):
    return Node("table", "", children=[Node("row", "", children=[_cell(h) for h in head])]
                + [Node("row", "", children=[_cell(c) for c in r]) for r in rows])


def _tickets(*tables):
    from govaios import capture
    return capture.tree(Node("document", "JobLens · My tickets", children=[Node("heading", "My tickets"), *tables]))


def _reading(tmp_path, done=None):
    """joblens() with Done pressed on a tickets page holding one table."""
    les, app = joblens(tmp_path)
    les["done_tree"] = done or _tickets(_table(["Ticket", "Subject", ""],
                                               [["T-0009", "VPN down", ""], ["T-0012", "Printer", ""]]))
    les["done_url"] = "http://localhost:8100/tickets"
    return les, app


READ = {"table": 0, "columns": [0, 1], "rows": "all"}


def _on(plan):
    return next(s for s in yaml.safe_load(plan["flow"][1])["workflow"]["steps"] if s["id"] == "on_start")["on_match"]


def test_propose_offers_the_done_pages_tables(tmp_path):
    les, _ = _reading(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    d = prop["pages"][-1]
    assert (d["done"], d["new"], d["steps"], len(prop["pages"])) == (True, True, [], 3)
    assert prop["reads"] == [{"key": "ticket_table", "spec": {"role": "table", "has_text": "Ticket"},
                              "headers": ["Ticket", "Subject", ""], "rows": 2, "preview": ["T-0009", "VPN down", ""]}]
    assert prop["read_refused"] is None


def test_build_without_reads_is_unchanged(tmp_path, monkeypatch):
    _pin_date(monkeypatch)
    les, app = _reading(tmp_path)
    plan = _plan(tmp_path, les, app, lessons.propose(les, tmp_path / "pages", Bank()), require_outcomes=False)
    assert _hash(plan) == OLD_HASH
    assert len(plan["new"]) == 1 and _on(plan)["localhost_joblens"]["then"] == "end"


def test_build_adds_the_done_page_and_its_read(tmp_path):
    les, app = _reading(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    pid = prop["pages"][-1]["id"]
    before = yaml.safe_load(_plan(tmp_path, les, app, prop, require_outcomes=False)["flow"][1])["workflow"]
    plan = _plan(tmp_path, les, app, prop, require_outcomes=False, reads=READ)
    path = tmp_path / "pages" / f"{pid}.yaml"
    assert path in plan["new"]
    assert yaml.safe_load(plan["pages"][path])["page"]["elements"]["ticket_table"] == \
        {"role": "table", "has_text": "Ticket", "risk": "read"}
    on = _on(plan)
    assert on[pid] == {"do": [{"id": f"learned_{pid}_1", "action": "read_table", "target": f"{pid}.ticket_table",
                               "columns": ["Ticket", "Subject"], "rows": "all"}], "then": "end"}
    assert on["localhost_joblens"]["then"] == "again" and list(on)[-1] == "unknown"
    wf = yaml.safe_load(plan["flow"][1])["workflow"]
    assert {"extract_visible_text", "report"} <= set(wf["permissions"]["allow"])
    assert wf["permissions"]["max_element_risk"] == before["permissions"]["max_element_risk"]
    assert not {"extract_visible_text", "report"} & set(before["permissions"]["allow"])
    assert wf["destinations"].count("http://localhost:8100") == 1


def _refused(tmp_path, done, text):
    les, app = _reading(tmp_path, done)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert (prop["read_refused"], prop["reads"]) == (text, [])
    assert not any(p.get("done") for p in prop["pages"])
    with pytest.raises(ValueError, match=text.replace(".", r"\.")):
        _plan(tmp_path, les, app, prop, require_outcomes=False, reads=READ)


def test_read_on_the_last_page_refused(tmp_path):
    les, _ = joblens(tmp_path)
    _refused(tmp_path / "x", les["pages"][1]["tree"], "Reading on the page your last press stayed on isn't supported yet")


def test_read_on_an_earlier_page_refused(tmp_path):
    les, _ = joblens(tmp_path)
    _refused(tmp_path / "x", les["pages"][0]["tree"], "Reading on a page the flow already passed isn't supported yet")


def test_read_on_two_pages_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(lessons, "_identifies", lambda p, r: True)
    _refused(tmp_path, None, "The page Done was pressed on looks like more than one page of this lesson; reads not added")


def _with_case(tmp_path, app, page, then):
    """A hand-written case for page (its file written too), then the lesson proposed again: the page is known now."""
    pid = page["id"]
    (tmp_path / "pages" / f"{pid}.yaml").write_text(yaml.safe_dump(page["yaml"], sort_keys=False))
    doc = yaml.safe_load(app.read_text())
    step = next(s for s in doc["workflow"]["steps"] if s["id"] == "on_start")
    step["on_match"] = {pid: {"do": [{"id": "hand_written", "action": "hand_over"}], "then": then},
                        **step["on_match"]}
    app.write_text(yaml.safe_dump(doc, sort_keys=False))
    return pid


def test_read_on_a_page_the_app_handles_refused(tmp_path):
    from govaios.approvals import read_bound
    les, app = _reading(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    pid = _with_case(tmp_path, app, prop["pages"][-1], "end")
    les["digest"] = read_bound(app, tmp_path / "pages")[0]
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert (prop["pages"][-1]["id"], prop["pages"][-1]["new"]) == (pid, False)
    with pytest.raises(ValueError, match="^This page is already in the app; reads not added$"):
        _plan(tmp_path, les, app, prop, require_outcomes=False, reads=READ)


def test_read_after_a_page_that_ends_the_app_refused(tmp_path):
    les, app = _reading(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    _with_case(tmp_path, app, prop["pages"][1], "end")
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    with pytest.raises(ValueError, match="^The page before this one ends the app; reads not added$"):
        _plan(tmp_path, les, app, prop, require_outcomes=False, reads=READ)


def test_read_on_a_known_page_adds_its_table(tmp_path):
    from govaios import studio
    les, app = _reading(tmp_path)
    (tmp_path / "pages" / "helpdesk_tickets.yaml").write_text(
        yaml.safe_dump(studio.draft_page(les["done_tree"], "helpdesk_tickets"), sort_keys=False))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert (prop["pages"][-1]["new"], prop["pages"][-1]["id"]) == (False, "helpdesk_tickets")
    plan = _plan(tmp_path, les, app, prop, require_outcomes=False, reads=READ)
    path = tmp_path / "pages" / "helpdesk_tickets.yaml"
    assert path in plan["pages"] and path not in plan["new"]
    assert "ticket_table" in yaml.safe_load(plan["pages"][path])["page"]["elements"]


def test_read_on_a_known_page_holding_the_table_rewrites_nothing(tmp_path):
    from govaios import studio
    les, app = _reading(tmp_path)
    doc = studio.draft_page(les["done_tree"], "helpdesk_tickets")
    doc["page"]["elements"]["tickets"] = {"role": "table", "has_text": "Ticket", "risk": "read"}
    (tmp_path / "pages" / "helpdesk_tickets.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert prop["reads"][0]["key"] == "tickets"
    plan = _plan(tmp_path, les, app, prop, require_outcomes=False, reads=READ)
    assert tmp_path / "pages" / "helpdesk_tickets.yaml" not in plan["pages"]
    assert _on(plan)["helpdesk_tickets"]["do"][0]["target"] == "helpdesk_tickets.tickets"


def test_table_spec_skips_a_header_another_table_shows(tmp_path):
    les, _ = _reading(tmp_path, _tickets(_table(["Net", "Gross"], [["1", "2"]]), _table(["Amount"], [["Net"]]),
                                         _table(["Amount"], [["3"]])))
    reads = lessons.propose(les, tmp_path / "pages", Bank())["reads"]
    assert [r["spec"]["has_text"] for r in reads] == ["Gross"]   # both Amount tables share their only header


def test_build_refuses_a_header_shown_twice(tmp_path):
    les, app = _reading(tmp_path, _tickets(_table(["Net", "Net", "Gross"], [["1", "2", "3"]])))
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    with pytest.raises(ValueError, match="^column Net appears twice in this table$"):
        _plan(tmp_path, les, app, prop, require_outcomes=False, reads={"table": 0, "columns": [0], "rows": "first"})


def test_sandbox_lesson_offers_no_reads(tmp_path):
    les, _ = _reading(tmp_path)
    les["flow"] = None
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert prop["reads"] == [] and prop["read_refused"] is None and not any(p.get("done") for p in prop["pages"])


def test_preview_ignores_the_done_page(tmp_path):
    les, _ = _reading(tmp_path)
    _, text = lessons.preview(les, tmp_path / "pages", Bank())
    assert list(yaml.safe_load(text)) == ["joblens_applications", "localhost_joblens"]
    assert yaml.safe_load(text)["localhost_joblens"]["then"] == "end"


def test_read_with_no_presses(tmp_path):
    les, app = _reading(tmp_path)
    les["pages"] = []
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert [r["key"] for r in prop["reads"]] == ["ticket_table"] and len(prop["pages"]) == 1
    pid = prop["pages"][0]["id"]
    on = _on(_plan(tmp_path, les, app, prop, require_outcomes=False, reads=READ))
    assert [k for k in on if k.startswith("learned") or k == pid] == [pid] and on[pid]["then"] == "end"


def test_done_page_after_a_typed_field(tmp_path):
    les, _ = _typed(tmp_path, ("Home address", "9 Willow Terrace"))
    les["done_tree"], les["done_url"] = _tickets(_table(["Ticket"], [["T-1"]])), "http://localhost:8100/tickets"
    prop = lessons.propose(les, tmp_path / "pages", Bank())   # the type line once hid the known pages' list
    assert prop["pages"][-1]["done"] and [r["key"] for r in prop["reads"]] == ["ticket_table"]


# ---------- reads: the lesson page's form ----------

def _read_prop():
    t = {"key": "k", "spec": {}, "headers": ["Ticket", "Subject", ""], "rows": 2, "preview": ["a", "b", ""]}
    return {"pages": [{"steps": [{}]}, {"id": "d", "done": True, "steps": []}], "bank": [], "reads": [t, dict(t)],
            "read_refused": None}


def test_edits_reads_one_table():
    from govaios.panel import lesson as lesson_ui
    got = lesson_ui.edits(_read_prop(), {"read:0:1": "1", "read:0:0": "1", "rows:0": "first"})
    assert len(got) == 6 and got[5] == {"table": 0, "columns": [0, 1], "rows": "first"}
    assert lesson_ui.edits(_read_prop(), {"read:1:0": "1"})[5] == {"table": 1, "columns": [0], "rows": "all"}
    assert lesson_ui.edits(_read_prop(), {})[5] is None


def test_edits_rows_alone_is_no_read():
    from govaios.panel import lesson as lesson_ui
    assert lesson_ui.edits(_read_prop(), {"rows:0": "all", "rows:1": "all"})[5] is None


def test_edits_refuses_two_tables():
    from govaios.panel import lesson as lesson_ui
    with pytest.raises(lesson_ui.BadCap, match="^Read columns from one table only$"):
        lesson_ui.edits(_read_prop(), {"read:0:0": "1", "read:1:0": "1"})
    prop = _read_prop()
    prop["reads"][0]["headers"] = [f"h{i}" for i in range(11)]
    assert len(lesson_ui.edits(prop, {f"read:0:{i}": "1" for i in range(10)})[5]["columns"]) == 10
    with pytest.raises(lesson_ui.BadCap, match="^Read at most 10 columns$"):
        lesson_ui.edits(prop, {f"read:0:{i}": "1" for i in range(11)})


def test_edits_refuses_an_empty_header():
    from govaios.panel import lesson as lesson_ui
    prop = _read_prop()
    prop["reads"][1]["headers"] = ["a\tb", "x" * 201, "x" * 200]
    for bad in ({"read:0:2": "1"}, {"read:0:3": "1"}, {"read:2:0": "1"}, {"rows:0": "some"}, {"rows:2": "all"},
                {"read:0:0": "on"}, {"read:1:0": "1"}, {"read:1:1": "1"}):
        with pytest.raises(ValueError, match="^unknown field$"):
            lesson_ui.edits(prop, bad)
    assert lesson_ui.edits(prop, {"read:1:2": "1"})[5]["columns"] == [2]
    prop["read_refused"], prop["reads"] = "no", []
    with pytest.raises(ValueError, match="^unknown field$"):
        lesson_ui.edits(prop, {"read:0:0": "1"})


def test_edits_skips_the_done_page():
    from govaios.panel import lesson as lesson_ui
    assert lesson_ui.edits(_read_prop(), {"rep:0": "1", "cap:0": "3"})[2] == {0: 3}
    for bad in ({"rep:1": "1", "cap:1": "3"}, {"cap:1": "3"}, {"del:1:0": "1"}):
        with pytest.raises(ValueError):
            lesson_ui.edits(_read_prop(), bad)


def test_lesson_page_offers_reads(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, _ = _reading(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    prop["reads"][0]["headers"][1] = "<b>x</b>"
    prop["reads"][0]["preview"][1] = "<b>y</b>"
    html = lesson_ui.page("n", les, prop, set(), {}, "")
    assert "<h2>Read from this page</h2>" in html and "Table 1: 2 rows seen" in html
    assert "<input type=checkbox name='read:0:0' value=1>" in html and "read:0:2" not in html
    assert "<input type=radio name='rows:0' value=all checked>" in html and "name='rows:0' value=first>" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "&lt;b&gt;y&lt;/b&gt;" in html and "<b>x" not in html
    assert html.count("<section class=appcard><h2><code>") == len(prop["pages"]) - 1
    assert f"<code>{prop['pages'][-1]['id']}</code> · new" not in html
    assert "The last page gets no steps" not in html
    assert "approving again" not in html


def test_lesson_page_hides_an_untickable_header(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, _ = _reading(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    prop["reads"][0]["headers"] = ["a\tb", "x" * 201, "Subject"]
    html = lesson_ui.page("n", les, prop, set(), {}, "")
    assert "read:0:0" not in html and "read:0:1" not in html and "name='read:0:2'" in html


def test_lesson_page_shows_why_reads_are_refused(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, _ = _reading(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    prop["read_refused"], prop["reads"] = "Can't <read> here", []
    html = lesson_ui.page("n", les, prop, set(), {}, "")
    assert "Can&#x27;t &lt;read&gt; here" in html and "read:" not in html
    prop["read_refused"], prop = None, lessons.propose(les, tmp_path / "pages", Bank())
    html = lesson_ui.page("n", les, prop, {prop["pages"][-1]["id"]}, {}, "")
    assert "This page is already in the app; reads not added" in html and "read:" not in html


def test_lesson_page_hides_reads_for_studio(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, _ = _reading(tmp_path)
    les["flow"] = None
    html = lesson_ui.page("n", les, lessons.propose(les, tmp_path / "pages", Bank()), set(), {}, "")
    assert "Read from this page" not in html


def test_lesson_page_warns_other_apps_only_for_a_new_table_key(tmp_path):
    from govaios import studio
    from govaios.panel import lesson as lesson_ui
    les, _ = _reading(tmp_path)
    doc = studio.draft_page(les["done_tree"], "helpdesk_tickets")
    path = tmp_path / "pages" / "helpdesk_tickets.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    others = {"helpdesk_tickets": ["Desk <app>"]}
    html = lesson_ui.page("n", les, lessons.propose(les, tmp_path / "pages", Bank()), set(), others, "")
    assert "approving again: Desk &lt;app&gt;" in html
    doc["page"]["elements"]["tickets"] = {"role": "table", "has_text": "Ticket", "risk": "read"}
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    html = lesson_ui.page("n", les, lessons.propose(les, tmp_path / "pages", Bank()), set(), others, "")
    assert "approving again" not in html and "name='read:0:0'" in html


# ---------- same-page read after a navigate press (teach-choices Task 5) ----------

def _filtered(tmp_path, last=None, url=None):
    """_chose's Discover page with only pick, tick, click "Filter employees" (navigate); Done pressed on the same
    page reloaded, now holding a table "ID". last: an event added after the click."""
    from govaios import capture
    les, app = _chose(tmp_path)
    p = les["pages"][1]
    p["events"] = p["events"][2:-1]
    p["events"][-1].update(spec={"role": "button", "name": "Filter employees"}, label="Filter employees")
    p["tree"]["children"][-1]["name"] = "Filter employees"
    if last:
        p["events"].append(last)
    if url:
        for lp in les["pages"]:
            lp["url"] = url + lp["url"].split("8100", 1)[1]
    done = copy.deepcopy(p["tree"])
    done["children"].append(capture.tree(_table(["ID", "Name"], [["E-1", "Ann"]])))
    les["done_tree"], les["done_url"] = done, "http://localhost:8100/discover?dept=Engineering"
    return les, app


HERE = {"table": 0, "columns": [0, 1], "rows": "all"}


def test_read_here_offered_after_navigate_click(tmp_path):
    les, _ = _filtered(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert (prop["read_here"], prop["read_refused"]) == (True, None)
    assert len(prop["pages"]) == 2 and not any(p.get("done") for p in prop["pages"])
    assert [(r["key"], r["headers"], r["preview"]) for r in prop["reads"]] == [("id_table", ["ID", "Name"], ["E-1", "Ann"])]
    assert prop["pages"][1]["steps"][-1]["label"] == "Filter employees"   # no closing hand-over: an own app


def test_read_here_refused_when_last_line_not_navigate(tmp_path):
    typed = {"kind": "type", "spec": {"role": "text_field", "name": "Note"}, "label": "Note", "value": "x",
             "secure": False, "risk": "modify", "sure": True}
    for k, les in enumerate([_filtered(tmp_path / "a", typed)[0], _filtered(tmp_path / "b")[0]]):
        if k:   # the filter press rated submit: a press, not a navigate click
            les["pages"][1]["events"][-1].update(risk="submit", submit=True)
        les["pages"][1]["tree"]["children"].append({"role": "text_field", "name": "Note"})
        prop = lessons.propose(les, tmp_path / "ab"[k] / "pages", Bank())
        assert (prop["read_here"], prop["read_refused"], prop["reads"]) == (False, lessons.READ_LAST, [])


def test_read_here_refused_off_own_app(tmp_path):
    les, _ = _filtered(tmp_path, url="https://hr.acme.example")
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert (prop["read_here"], prop["read_refused"], prop["reads"]) == (False, lessons.READ_LAST, [])
    assert prop["pages"][1]["steps"][-1]["kind"] == "hand_over"


def test_build_read_here_adds_wait_url_and_read(tmp_path):
    les, app = _filtered(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    pid = prop["pages"][1]["id"]
    plan = _plan(tmp_path, les, app, prop, reads=HERE)
    case = _on(plan)[pid]
    assert case["then"] == "end"
    assert [{k: v for k, v in d.items() if k != "id"} for d in case["do"]][-2:] == [
        {"action": "click", "target": f"{pid}.button_filter_employees", "wait_url": True},
        {"action": "read_table", "target": f"{pid}.id_table", "columns": ["ID", "Name"], "rows": "all"}]
    assert {p.stem for p in plan["pages"]} <= {p["id"] for p in prop["pages"]}   # no extra page file
    assert yaml.safe_load(plan["pages"][tmp_path / "pages" / f"{pid}.yaml"])["page"]["elements"]["id_table"] == \
        {"role": "table", "has_text": "ID", "risk": "read"}
    assert prop["pages"][1]["steps"][-1]["kind"] == "click"   # never the caller's proposal


def test_build_read_here_filter_click_deleted_refused(tmp_path):
    les, app = _filtered(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    j = len(prop["pages"][1]["steps"]) - 1
    with pytest.raises(ValueError, match=f"^{lessons.READ_LAST}$"):
        _plan(tmp_path, les, app, prop, {(1, j)}, reads=HERE)


def test_build_read_here_nothing_ticked_unchanged(tmp_path):
    les, app = _filtered(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    plain = {**prop, "read_here": False, "reads": [], "read_refused": lessons.READ_LAST}
    a, b = _plan(tmp_path, les, app, prop), _plan(tmp_path, les, app, plain)
    assert (a["flow"], a["pages"], a["digest"]) == (b["flow"], b["pages"], b["digest"])
    assert b"wait_url" not in a["flow"][1] and b"read_table" not in a["flow"][1]


def test_build_read_here_page_already_in_app_refused(tmp_path):
    les, app = _filtered(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    pid = _with_case(tmp_path, app, prop["pages"][1], "end")
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    assert (prop["read_here"], prop["pages"][1]["id"], prop["pages"][1]["new"]) == (True, pid, False)
    with pytest.raises(ValueError, match="^This page is already in the app; reads not added$"):
        _plan(tmp_path, les, app, prop, reads=HERE)


def test_lesson_page_offers_read_here_tables(tmp_path):
    from govaios.panel import lesson as lesson_ui
    les, _ = _filtered(tmp_path)
    prop = lessons.propose(les, tmp_path / "pages", Bank())
    html = lesson_ui.page("n", les, prop, set(), {}, "")
    assert "<h2>Read from this page</h2>" in html and "Table 1: 1 rows seen" in html
    assert "name='read:0:0'" in html and "name='read:0:1'" in html
    assert lesson_ui.edits(prop, {"read:0:0": "1"})[5] == {"table": 0, "columns": [0], "rows": "all"}
    html = lesson_ui.page("n", les, prop, {prop["pages"][1]["id"]}, {}, "")
    assert "This page is already in the app; reads not added" in html and "read:" not in html
