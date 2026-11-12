"""Studio lessons: saved recordings become a proposed change (pages, steps, bank ops); nothing is written."""
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
