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
                                          "after": 4, "change": 1, "at": [0, 1], "page": p["id"]}]


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
