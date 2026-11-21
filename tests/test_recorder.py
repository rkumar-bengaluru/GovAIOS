"""The Teach recorder: each press is read at once, checked, and saved to the open lesson as it goes."""
from govaios import applyfiles, lessons
from govaios.desktop import Node
from govaios import terms
from govaios.recorder import HELD, MISMATCH, OUTSIDE, Recorder

HOME, DISCOVER = "http://localhost:8100/", "http://localhost:8100/discover"


def home_tree():
    return Node("document", "JobLens", children=[Node("heading", "Applications"),
                                                 Node("link", "Discover", handle="discover")])


def discover_tree(*kids):
    return Node("document", "JobLens", children=[Node("heading", "Discover"), *kids])


class Desk:
    """trees: url -> list of trees, one per web_root call (the last repeats)."""
    def __init__(self, url, trees):
        self.url, self.trees, self.calls = url, trees, 0

    def element_at(self, x, y):
        return self.hit

    def web_root(self, app):
        ts = self.trees[self.url]
        self.calls += 1
        return ts.pop(0) if len(ts) > 1 else ts[0]

    def current_url(self, app):
        return self.url

    def same(self, a, b):
        return a == b


def down(name, url=HOME, role="link"):
    return {"run": "r1", "kind": "down", "x": 10, "y": 20, "name": name, "role": role, "tag": "a", "url": url, "t": 1}


def rec(tmp_path, desk, lesson=None):
    return Recorder(desk, "chrome", tmp_path, "r1", lesson)


def out(tmp_path):
    return applyfiles.read_json(tmp_path, applyfiles.TEACH_OUT)


def test_down_records_a_click_step(tmp_path):
    desk = Desk(HOME, {HOME: [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover"))
    doc = lessons.load(tmp_path, r.name)
    assert doc["flow"] == "teach_new" and doc["new_app"] is True
    (p,) = doc["pages"]
    assert p["url"] == HOME and p["title"] == "JobLens · Applications"
    (e,) = p["events"]
    assert e == {"kind": "click", "spec": {"role": "link", "name": "Discover"}, "label": "Discover", "value": "",
                 "secure": False, "submit": False, "risk": "navigate", "sure": True,
                 "before": p["tree"]}
    o = out(tmp_path)
    assert o == {"run": "r1", "lesson": r.name, "paused": False, "note": "",
                 "lines": ["JobLens · Applications: click Discover"]}
    assert applyfiles.read_json(tmp_path, applyfiles.TEACH_OPEN) == {"lesson": r.name}


def test_counted_name_saved_without_count(tmp_path):
    desk = Desk(DISCOVER, {DISCOVER: [discover_tree(Node("tab", "Shortlisted (2)", handle="t"))]})
    desk.hit = "t"
    r = rec(tmp_path, desk)
    r.handle(down("Shortlisted (2)", DISCOVER, "tab"))
    (e,) = lessons.load(tmp_path, r.name)["pages"][0]["events"]
    assert e["spec"] == {"role": "tab", "name_matches": "^Shortlisted \\(\\d+\\)$"}
    assert e["risk"] == "navigate" and e["sure"] is True


def test_spec_checked_against_its_own_snapshot(tmp_path):
    def rows(second):
        return discover_tree(Node("row", children=[Node("text", "Ana"), Node("button", "Review", handle="b1")]),
                             Node("row", children=[Node("button", second, handle="b2")]))
    later = discover_tree(Node("row", children=[Node("button", "Close", handle="b1")]))
    desk = Desk(DISCOVER, {DISCOVER: [rows("Review"), later]})
    desk.hit = "b1"
    r = rec(tmp_path, desk)
    r.handle(down("Review", DISCOVER, "button"))
    (e,) = lessons.load(tmp_path, r.name)["pages"][0]["events"]
    assert e["spec"] == {"role": "button", "name": "Review", "index": 0} and e["sure"] is True
    assert e["risk"] == "navigate" and e["submit"] is False


def test_icon_glyph_in_the_tree_name_still_matches(tmp_path):
    tree = Node("document", "Shop", children=[Node("link", "\uf07a Add to cart", handle="add")])
    desk = Desk(HOME, {HOME: [tree]})
    desk.hit = "add"
    r = rec(tmp_path, desk)
    r.handle(down("Add to cart"))   # the page's innerText has no glyph: it comes from CSS ::before
    (e,) = lessons.load(tmp_path, r.name)["pages"][0]["events"]
    assert e["spec"] == {"role": "link", "name": "\uf07a Add to cart"} and out(tmp_path)["note"] == ""


def test_name_mismatch_not_saved(tmp_path):
    desk = Desk(DISCOVER, {DISCOVER: [discover_tree(Node("button", "Skip", handle="s"))]})
    desk.hit = "s"
    r = rec(tmp_path, desk)
    r.handle(down("Review", DISCOVER, "button"))
    assert lessons.load(tmp_path, r.name)["pages"] == []
    assert out(tmp_path)["note"] == "Run could not find this. Do it again, or skip it."


def test_empty_space_dropped_without_note(tmp_path):
    desk = Desk(DISCOVER, {DISCOVER: [discover_tree(Node("text", "blank", handle="x"))]})
    desk.hit = "x"
    r = rec(tmp_path, desk)
    r.handle(down("", DISCOVER))
    assert lessons.load(tmp_path, r.name)["pages"] == [] and out(tmp_path)["note"] == ""


def test_other_page_down_dropped(tmp_path):
    desk = Desk(HOME, {HOME: [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover", DISCOVER))
    assert lessons.load(tmp_path, r.name)["pages"] == [] and out(tmp_path)["lines"] == []


def test_outside_origin_pauses(tmp_path):
    desk = Desk("https://example.com/", {"https://example.com/": [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover", "https://example.com/"))
    assert r.paused and out(tmp_path)["paused"] is True
    assert out(tmp_path)["note"] == OUTSIDE
    assert lessons.load(tmp_path, r.name)["pages"] == []


def test_a_site_marked_allowed_records(tmp_path):
    site = "https://automationexercise.com/"
    terms.record(tmp_path, site, "allowed", site, "Full-Fledged practice website for Automation Engineers")
    desk = Desk(site, {site: [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover", site))
    assert not r.paused and [p["url"] for p in lessons.load(tmp_path, r.name)["pages"]] == [site]


def test_forbidden_unclear_or_plain_http_sites_pause(tmp_path):
    for value, url in (("forbidden", "https://jiomart.com/"), ("unclear", "https://gymshark.com/"),
                       ("allowed", "http://books.toscrape.com/")):
        terms.record(tmp_path, url.replace("http:", "https:"), value, "https://x.example/terms", "")
        desk = Desk(url, {url: [home_tree()]})
        desk.hit = "discover"
        r = rec(tmp_path, desk)
        r.handle(down("Discover", url))
        assert r.paused and out(tmp_path)["note"] == OUTSIDE
        assert lessons.load(tmp_path, r.name)["pages"] == []


def test_the_panels_own_pages_are_outside(tmp_path):
    for url in ("http://127.0.0.1:8765/", "http://localhost:8765/studio"):
        desk = Desk(url, {url: [home_tree()]})
        desk.hit = "discover"
        r = rec(tmp_path, desk)
        r.handle(down("Discover", url))
        assert r.paused and out(tmp_path)["note"] == OUTSIDE
        assert lessons.load(tmp_path, r.name)["pages"] == []


def test_new_path_starts_a_page(tmp_path):
    desk = Desk(HOME, {HOME: [home_tree()], DISCOVER: [discover_tree(Node("tab", "Shortlisted (2)", handle="t"))]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover"))
    desk.url, desk.hit = DISCOVER, "t"
    r.handle(down("Shortlisted (2)", DISCOVER, "tab"))
    pages = lessons.load(tmp_path, r.name)["pages"]
    assert [p["url"] for p in pages] == [HOME, DISCOVER]
    assert pages[0]["tree"]["children"][0]["name"] == "Applications"
    assert pages[1]["tree"]["children"][0]["name"] == "Discover"
    assert out(tmp_path)["lines"] == ["JobLens · Applications: click Discover",
                                      "JobLens · Discover: click Shortlisted (2)"]


def test_back_on_an_earlier_page_keeps_only_the_last_visit(tmp_path):
    """Discover -> Applications -> Discover (the 2026-11-13 lesson): the run must end on Discover, Shortlisted kept."""
    disc = discover_tree(Node("link", "Applications", handle="apps"), Node("tab", "Shortlisted (2)", handle="t"))
    desk = Desk(DISCOVER, {HOME: [home_tree()], DISCOVER: [disc]})
    r = rec(tmp_path, desk)
    desk.hit = "apps"
    r.handle(down("Applications", DISCOVER))
    desk.url, desk.hit = HOME, "discover"
    r.handle(down("Discover"))
    desk.url, desk.hit = DISCOVER, "t"
    r.handle(down("Shortlisted (2)", DISCOVER, "tab"))
    pages = lessons.load(tmp_path, r.name)["pages"]
    assert [p["url"] for p in pages] == [HOME, DISCOVER]
    assert [e["label"] for e in pages[1]["events"]] == ["Shortlisted (2)"]
    assert out(tmp_path)["lines"] == ["JobLens · Applications: click Discover",
                                      "JobLens · Discover: click Shortlisted (2)"]


def test_pause_drops_downs(tmp_path):
    desk = Desk(HOME, {HOME: [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle({"kind": "pause"})
    r.handle(down("Discover"))
    assert r.paused
    r.handle({"kind": "resume"})
    r.handle(down("Discover"))
    assert not r.paused
    assert len(lessons.load(tmp_path, r.name)["pages"][0]["events"]) == 1


def test_resume_elsewhere_refused(tmp_path):
    desk = Desk(DISCOVER, {DISCOVER: [discover_tree()], HOME: [home_tree()]})
    r = rec(tmp_path, desk)
    r.handle({"kind": "pause"})
    desk.url = HOME
    r.handle({"kind": "resume"})
    assert r.paused and out(tmp_path)["note"] == "Go back to JobLens · Discover to resume."


def test_submit_step_is_you_press(tmp_path):
    desk = Desk(DISCOVER, {DISCOVER: [discover_tree(Node("button", "Approve & promote", handle="a"))]})
    desk.hit = "a"
    r = rec(tmp_path, desk)
    r.handle(down("Approve & promote", DISCOVER, "button"))
    (e,) = lessons.load(tmp_path, r.name)["pages"][0]["events"]
    assert e["risk"] == "submit" and e["submit"] is True
    assert out(tmp_path)["lines"] == ["JobLens · Discover: you press Approve & promote"]


def test_resume_appends_to_open_lesson(tmp_path):
    desk = Desk(HOME, {HOME: [home_tree()], DISCOVER: [discover_tree(Node("tab", "Shortlisted (2)", handle="t"))]})
    desk.hit = "discover"
    first = rec(tmp_path, desk)
    first.handle(down("Discover"))
    desk.url, desk.hit = DISCOVER, "t"
    again = rec(tmp_path, desk, first.name)
    assert again.name == first.name
    again.handle(down("Shortlisted (2)", DISCOVER, "tab"))
    assert [p["url"] for p in lessons.load(tmp_path, first.name)["pages"]] == [HOME, DISCOVER]
    assert len(out(tmp_path)["lines"]) == 2


def test_done_keeps_lesson_and_open(tmp_path):
    r = rec(tmp_path, Desk(HOME, {HOME: [home_tree()]}))
    r.handle({"kind": "done"})
    assert r.done and (tmp_path / lessons.DIR / r.name).exists()
    assert applyfiles.read_json(tmp_path, applyfiles.TEACH_OPEN) == {"lesson": r.name}


def test_cancel_deletes_lesson(tmp_path):
    desk = Desk(HOME, {HOME: [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover"))
    r.handle({"kind": "cancel"})
    assert r.cancelled
    assert not (tmp_path / lessons.DIR / r.name).exists()
    assert applyfiles.read_json(tmp_path, applyfiles.TEACH_OPEN) is None



def test_nameless_button_not_saved(tmp_path):
    desk = Desk(DISCOVER, {DISCOVER: [discover_tree(Node("button", "", handle="n"))]})
    desk.hit = "n"
    r = rec(tmp_path, desk)
    r.handle(down("", DISCOVER, "button"))
    assert lessons.load(tmp_path, r.name)["pages"] == []
    assert out(tmp_path)["note"] == "Run could not find this. Do it again, or skip it."


def test_failed_write_keeps_memory_and_disk_in_step(tmp_path, monkeypatch):
    desk = Desk(HOME, {HOME: [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)

    def boom(*a):
        raise OSError("disk full")
    monkeypatch.setattr(lessons, "write", boom)
    r.handle(down("Discover"))
    assert r.doc["pages"] == [] and r.lines == []
    assert out(tmp_path) == {"run": "r1", "lesson": r.name, "paused": False,
                             "note": "Could not save this step. Do it again.", "lines": []}
    monkeypatch.undo()
    r.handle(down("Discover"))
    assert len(lessons.load(tmp_path, r.name)["pages"][0]["events"]) == 1


def test_stored_tree_holds_no_field_values(tmp_path):
    t = home_tree()
    t.children.append(Node("text_field", "Email", value="me@x.com"))
    desk = Desk(HOME, {HOME: [t]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover"))
    text = (tmp_path / lessons.DIR / r.name).read_text()
    assert "Email" in text and "me@x.com" not in text


def test_each_press_keeps_its_tree(tmp_path):
    first = discover_tree(Node("tab", "Promoted", handle="t"))
    second = discover_tree(Node("tab", "Promoted (8)", handle="t"))
    desk = Desk(DISCOVER, {DISCOVER: [first, second]})
    desk.hit = "t"
    r = rec(tmp_path, desk)
    r.handle(down("Promoted", DISCOVER, "tab"))
    r.handle(down("Promoted (8)", DISCOVER, "tab"))
    a, b = lessons.load(tmp_path, r.name)["pages"][0]["events"]
    assert a["before"] != b["before"] and "Promoted (8)" in str(b["before"]) and desk.calls == 2


def test_done_keeps_a_tree(tmp_path):
    r = rec(tmp_path, Desk(HOME, {HOME: [home_tree()]}))
    r.handle({"kind": "done"})
    doc = lessons.load(tmp_path, r.name)
    assert "Applications" in str(doc["done_tree"]) and doc["done_url"] == HOME and r.done


def test_done_on_an_outside_page_keeps_no_tree(tmp_path):
    r = rec(tmp_path, Desk("http://localhost:8100/x", {"http://localhost:8100/x": [home_tree()]}))
    r.desk.url = "https://example.org/"
    r.handle({"kind": "done"})
    assert r.done and "done_tree" not in lessons.load(tmp_path, r.name)


def test_trees_have_no_values(tmp_path):
    t = home_tree()
    t.children.append(Node("text_field", "Email", value="secret"))
    desk = Desk(HOME, {HOME: [t]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle(down("Discover"))
    r.handle({"kind": "done"})
    assert "secret" not in (tmp_path / lessons.DIR / r.name).read_text()


FORM = "http://localhost:8100/form"


def form_tree(*kids):
    return Node("document", "JobLens", children=[Node("heading", "Profile"), *kids, Node("button", "Save", handle="save")])


def save(*types, url=FORM):
    return {**down("Save", url, "button"), "types": list(types)}


def test_type_records_value_read_from_the_tree(tmp_path):
    from govaios.engine import find_all
    tree = form_tree(Node("text_field", "Home address", value="9 Willow Terrace"))
    desk = Desk(FORM, {FORM: [tree]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("Home address"))
    t, _ = lessons.load(tmp_path, r.name)["pages"][0]["events"]
    assert t == {"kind": "type", "spec": t["spec"], "label": "Home address", "value": "9 Willow Terrace",
                 "secure": False, "risk": "modify", "sure": True, "before": t["before"]}
    assert len(find_all(tree, t["spec"], {"elements": {}})) == 1
    assert "9 Willow Terrace" not in str(t["before"]) and desk.calls == 1   # one snapshot for the types and the press
    assert out(tmp_path)["lines"][0] == "JobLens · Profile: type into Home address"


def test_type_secure_field_refused(tmp_path):
    desk = Desk(FORM, {FORM: [form_tree(Node("native:AXSecureTextField", "Password", value="hunter2"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("Password"))
    assert [e["kind"] for e in lessons.load(tmp_path, r.name)["pages"][0]["events"]] == ["click"]
    assert out(tmp_path)["note"] == "Password fields are never recorded: you type them at Run."
    assert "hunter2" not in (tmp_path / lessons.DIR / r.name).read_text()


def test_type_restricted_label_refused(tmp_path):
    desk = Desk(FORM, {FORM: [form_tree(Node("text_field", "Passport number", value="Z1234567"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("Passport number"))
    assert "Z1234567" not in (tmp_path / lessons.DIR / r.name).read_text()
    assert out(tmp_path)["note"] == "This field is not recorded: type it by hand at Run."


def test_type_multi_line_refused(tmp_path):
    desk = Desk(FORM, {FORM: [form_tree(Node("text_area", "Cover note", value="Hi\nthere"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("Cover note"))
    assert [e["kind"] for e in lessons.load(tmp_path, r.name)["pages"][0]["events"]] == ["click"]
    assert out(tmp_path)["note"] == "Multi-line text is not supported yet: type it by hand at Run."


def test_type_two_fields_same_name_refused(tmp_path):
    desk = Desk(FORM, {FORM: [form_tree(Node("text_field", "Name", value="a"), Node("text_field", "Name", value="b"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("Name"))
    assert [e["kind"] for e in lessons.load(tmp_path, r.name)["pages"][0]["events"]] == ["click"]
    assert out(tmp_path)["note"] == MISMATCH


def test_type_name_not_found_refused(tmp_path):
    desk = Desk(FORM, {FORM: [form_tree(Node("text_field", "Name", value="a"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("City"))
    r.handle(save(""))   # a nameless field is never matched
    assert [e["kind"] for e in lessons.load(tmp_path, r.name)["pages"][0]["events"]] == ["click", "click"]
    assert out(tmp_path)["note"] == MISMATCH


def test_type_again_replaces(tmp_path):
    first = form_tree(Node("text_field", "City", value="Pune"))
    second = form_tree(Node("text_field", "City", value="Delhi"))
    desk = Desk(FORM, {FORM: [first, second]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("City"))
    r.handle(save("City"))
    evs = lessons.load(tmp_path, r.name)["pages"][0]["events"]
    assert [e["kind"] for e in evs] == ["click", "type", "click"]   # the latest typing moves to its latest place
    assert evs[1]["value"] == "Delhi" and len(r.lines) == 3


def test_type_then_press_keeps_order(tmp_path):
    desk = Desk(FORM, {FORM: [form_tree(Node("text_field", "City", value="Pune"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("City"))
    assert [e["kind"] for e in lessons.load(tmp_path, r.name)["pages"][0]["events"]] == ["type", "click"]
    assert out(tmp_path)["note"] == ""


def test_type_outside_origin_pauses(tmp_path):
    site = "https://example.com/"
    desk = Desk(site, {site: [form_tree(Node("text_field", "City", value="Pune"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("City", url=site))
    assert r.paused and out(tmp_path)["note"] == OUTSIDE
    assert lessons.load(tmp_path, r.name)["pages"] == []


def test_down_on_another_page_says_missed(tmp_path):
    desk = Desk(HOME, {HOME: [home_tree()]})
    desk.hit = "discover"
    r = rec(tmp_path, desk)
    r.handle({**down("Discover"), "x": None})
    assert out(tmp_path)["note"] == "Missed that press. Do it again."


def popup(name, value, *items):
    return Node("popup_button", name, value=value, children=[Node("native:AXMenuItem", i) for i in items])


def press(tmp_path, *kids, names=("Department",)):
    desk = Desk(FORM, {FORM: [form_tree(*kids)]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save(*names))
    return r, [e for e in lessons.load(tmp_path, r.name)["pages"][0]["events"] if e["kind"] != "click"]


def test_pick_records_selected_option(tmp_path):
    from govaios.engine import find_all
    tree = form_tree(popup("Department", "Engineering", "All departments", "Engineering", "Sales"))
    desk = Desk(FORM, {FORM: [tree]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("Department"))
    (p,) = [e for e in lessons.load(tmp_path, r.name)["pages"][0]["events"] if e["kind"] == "pick"]
    assert p == {"kind": "pick", "spec": p["spec"], "label": "Department", "value": "Engineering", "secure": False,
                 "risk": "modify", "sure": True, "before": p["before"]}
    assert len(find_all(tree, p["spec"], {"elements": {}})) == 1
    assert "Engineering" not in str([n for n in p["before"]["children"] if n["role"] == "popup_button"][0].get("value"))
    assert out(tmp_path)["lines"][0] == "JobLens · Profile: choose Engineering in Department"


def test_pick_option_not_in_menu_refused(tmp_path):
    r, evs = press(tmp_path, popup("Department", "Ops", "All departments", "Engineering"))
    assert evs == [] and out(tmp_path)["note"] == MISMATCH


def test_pick_option_twice_refused(tmp_path):
    r, evs = press(tmp_path, popup("Department", "Engineering", "Engineering", "Engineering"))
    assert evs == [] and out(tmp_path)["note"] == MISMATCH


def test_pick_empty_value_refused(tmp_path):
    r, evs = press(tmp_path, popup("Department", "", "Engineering"))
    assert evs == [] and out(tmp_path)["note"] == MISMATCH


def test_tickbox_records_state(tmp_path):
    r, (e,) = press(tmp_path, Node("checkbox", "Overdue only", value="1"), names=("Overdue only",))
    assert e["kind"] == "tickbox" and e["value"] == "1" and e["risk"] == "modify"
    assert out(tmp_path)["lines"][0] == "JobLens · Profile: tick Overdue only"
    r, (e,) = press(tmp_path, Node("checkbox", "Overdue only", value="0"), names=("Overdue only",))
    assert e["value"] == "0" and out(tmp_path)["lines"][0] == "JobLens · Profile: untick Overdue only"


def test_tickbox_in_a_group_held(tmp_path):
    grp = Node("group", "Tags", children=[Node("checkbox", "Red", value="1"), Node("checkbox", "Blue", value="0")])
    r, evs = press(tmp_path, grp, names=("Red",))
    assert evs == [] and out(tmp_path)["note"] == HELD


def test_pick_restricted_label_held(tmp_path):
    r, evs = press(tmp_path, popup("Gender", "Female", "Female", "Male"), names=("Gender",))
    assert evs == [] and out(tmp_path)["note"] == HELD


def test_latest_pick_wins(tmp_path):
    desk = Desk(FORM, {FORM: [form_tree(popup("Department", "Sales", "Engineering", "Sales"))]})
    desk.hit = "save"
    r = rec(tmp_path, desk)
    r.handle(save("Department"))
    desk.trees[FORM] = [form_tree(popup("Department", "Engineering", "Engineering", "Sales"))]
    r.handle(save("Department"))
    picks = [e for e in lessons.load(tmp_path, r.name)["pages"][0]["events"] if e["kind"] == "pick"]
    assert [p["value"] for p in picks] == ["Engineering"]
