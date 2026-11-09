"""Studio observer: scripted desktop samples become lesson events (no OS: handles are plain strings)."""
from govaios.desktop import Node
from govaios.observer import Observer

URL, TITLE = "https://jobs.example/apply", "Apply | Acme"


def same(a, b):
    return a == b


def page(*kids):
    return Node("document", TITLE, handle="root", children=list(kids))


def s(down=False, hit=None, focus=None, url=URL, title=TITLE, web="w1", tab=True):
    return {"down": down, "pt": (0, 0), "hit": hit, "focus": focus, "url": url, "title": title, "tab": tab, "web": web}


def click(o, hit, snap, **kw):
    return o.feed(s(down=True, hit=hit, **kw), snap) + o.feed(s(**kw), snap)


def test_click_on_link_becomes_click_event():
    tree = page(Node("link", "Apply Now", handle="l", children=[Node("text", "Apply Now", handle="t")]))
    o = Observer(None, None, same)
    o.feed(s(), lambda: tree)
    [ev] = click(o, "t", lambda: tree)   # the hit is the text inside the link
    assert ev["kind"] == "click" and ev["spec"] == {"role": "link", "name": "Apply Now"}
    assert (ev["label"], ev["value"], ev["submit"]) == ("Apply Now", "", False)
    assert o.pages[0]["events"] == [ev]


def field_tree(value, role="text_field"):
    return page(Node(role, "Email", value, handle="f"), Node("button", "Next", handle="b"))


def test_fill_records_value_on_blur():
    o = Observer(None, None, same)
    o.feed(s(), lambda: field_tree(""))
    assert o.feed(s(focus="f"), lambda: field_tree("")) == []
    evs = o.feed(s(focus="b"), lambda: field_tree("rupak@x"))
    assert [(e["kind"], e["value"], e["secure"], e["spec"]) for e in evs] == \
        [("fill", "rupak@x", False, {"role": "text_field", "name": "Email"})]
    assert o.feed(s(focus="f"), lambda: field_tree("rupak@x")) + o.feed(s(), lambda: field_tree("rupak@x")) == []


def test_secure_field_value_never_read():
    o = Observer(None, None, same)
    tree = field_tree("hunter2", role="native:AXSecureTextField")
    o.feed(s(focus="f"), lambda: tree)
    [ev] = o.feed(s(focus=None), lambda: tree)
    assert ev["kind"] == "fill" and ev["value"] == "" and ev["secure"] is True


def test_url_change_starts_new_page():
    o = Observer(None, None, same)
    o.feed(s(focus="f"), lambda: field_tree(""))
    o.feed(s(down=True, hit="b", focus="f"), lambda: field_tree("rupak@x"))   # Next pressed, focus not moved yet
    o.feed(s(url=URL + "/2", title="Step 2"), lambda: page())
    assert len(o.pages) == 2
    assert [(e["kind"], e["value"]) for e in o.pages[0]["events"]] == [("fill", "rupak@x"), ("click", "")]
    assert o.pages[1]["events"] == []
    assert o.pages[1]["url"] == URL + "/2"


def test_events_on_another_tab_are_ignored():
    tree = page(Node("button", "Next", handle="b"))
    o = Observer(None, None, same)
    o.feed(s(), lambda: tree)
    assert click(o, "b", lambda: tree, web="w2", url="https://other.example", title="Other") == []
    assert len(o.pages) == 1 and o.pages[0]["events"] == []
    o.feed(s(tab=False), lambda: tree)
    assert o.ended and o.feed(s(down=True, hit="b"), lambda: tree) == []


def test_duplicate_buttons_resolve_by_index():
    tree = page(Node("button", "Next", handle="b1"), Node("button", "Next", handle="b2"))
    o = Observer(None, None, same)
    o.feed(s(), lambda: tree)
    [ev] = click(o, "b2", lambda: tree)
    assert ev["spec"] == {"role": "button", "name": "Next", "index": 1} and ev["submit"] is True
    # a stable id on the first "Next": the name-and-index locator would find it, not the clicked one
    tree = page(Node("button", "Next", dom_id="go", handle="b1"), Node("button", "Next", handle="b2"))
    o = Observer(None, None, same)
    o.feed(s(), lambda: tree)
    [ev] = click(o, "b2", lambda: tree)
    assert ev["spec"] is None and ev["label"] == "Next"


def test_choice_tick_and_attach_seen_on_next_look():
    def tree(country, agree, file):
        return page(Node("popup_button", "Country", country, handle="c"), Node("checkbox", "I agree", agree, handle="k"),
                    Node("button", f"Resume: {file}", handle="r"), Node("link", "Help", handle="h"))
    o = Observer(None, None, same)
    o.feed(s(), lambda: tree("Choose", "0", "No file chosen"))
    evs = click(o, "h", lambda: tree("India", "1", "cv.pdf"))
    assert [(e["kind"], e["value"]) for e in evs] == [("choose", "India"), ("tick", "1"), ("attach", ""), ("click", "")]
    assert evs[2]["spec"] == {"role": "button", "name": "Resume: No file chosen"}   # as it was before the file
