"""The Teach recorder: each press is read at once, checked, and saved to the open lesson as it goes."""
from govaios import applyfiles, lessons
from govaios.desktop import Node
from govaios.recorder import Recorder

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
                 "secure": False, "submit": False, "risk": "navigate", "sure": True}
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
    assert out(tmp_path)["note"] == "Outside sites come later: recording paused."
    assert lessons.load(tmp_path, r.name)["pages"] == []


def test_the_panels_own_pages_are_outside(tmp_path):
    for url in ("http://127.0.0.1:8765/", "http://localhost:8765/studio"):
        desk = Desk(url, {url: [home_tree()]})
        desk.hit = "discover"
        r = rec(tmp_path, desk)
        r.handle(down("Discover", url))
        assert r.paused and out(tmp_path)["note"] == "Outside sites come later: recording paused."
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
