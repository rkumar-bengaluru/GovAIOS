"""Studio observer: read-only desktop samples taken while the admin teaches a page become lesson events.

Pure (no OS calls): the caller samples the desktop and passes a snapshot function. A sample is
{"down", "pt", "hit", "focus", "url", "title", "tab", "web"}: hit/focus/web are opaque OS handles, compared only
through `same`; web is the front tab's web area (the teach tab is the first one seen); tab False = the teach tab
is gone. Values are read only from fields the admin left; a secure field's value is never read.
"""
from . import capture
from .formfill import FIELD_ROLES
from .studio import _walk, element_spec

SECURE = "native:AXSecureTextField"
TEXT = ("text_field", "text_area", SECURE)
STATE = {"checkbox": "tick", "radio": "tick", "combo_box": "choose", "popup_button": "choose"}
NO_FILE = "No file chosen"   # Chrome's file input until a file is chosen (engine.do_attach_file checks it too)


class _Snap:
    """One snapshot: its Node tree, plus the capture-tree form element_spec needs (same walk order)."""

    def __init__(self, root, same):
        self.root, self.same = root, same
        self.nodes = list(root.walk())
        self.up = {id(c): p for p in self.nodes for c in p.children}
        self._dicts = None

    def find(self, h):
        return next((n for n in self.nodes if n.handle is not None and self.same(n.handle, h)), None) \
            if h is not None else None

    def spec(self, n):
        if self._dicts is None:
            t = capture.tree(self.root)
            self._dicts = (t, list(_walk(t)))
        t, ds = self._dicts
        return element_spec(t, ds[next(i for i, m in enumerate(self.nodes) if m is n)])


def _value(n):
    return "" if n.role == SECURE else n.value   # never read a secure field's value


def _event(kind, snap, n, value="", submit=False):
    return {"kind": kind, "spec": snap.spec(n), "label": n.name, "value": value, "secure": n.role == SECURE,
            "submit": submit}


class Observer:
    """feed() each sample; .pages holds {"url", "title", "tree", "events"} per page seen on the teach tab."""

    def __init__(self, desk, app, same):   # desk, app: the plan's interface; snapshots come through feed()
        self.same = same
        self.pages, self.ended = [], False
        self._web = self._focus = self._field = None
        self._down = False
        self._state, self._seen = [], None   # (handle, role, value, name, node) of choosable, tickable and file
        # nodes at the last look, and that look's snapshot

    def _is(self, a, b):
        return a is b or (a is not None and b is not None and self.same(a, b))

    def feed(self, sample, snapshot):
        """Returns the events this sample completed (also appended to their page)."""
        if self.ended:
            return []
        was_down, self._down = self._down, bool(sample.get("down"))
        out = []
        if not sample.get("tab"):
            self.ended = True
            self._blur(out)   # the last field's last-seen value
            return out
        web = sample.get("web")
        if web is None:
            return []   # can't tell which tab this is
        if self._web is None:
            self._web = web
        elif not self.same(web, self._web):
            return []   # another tab: not the lesson
        snap = None
        page = self.pages[-1] if self.pages else None
        if page is None or (sample.get("url"), sample.get("title")) != (page["url"], page["title"]):
            # a field left by navigating belongs to the old page, with its value as of the last look. shortcut: a
            # value typed then submitted by Enter (no click or focus change between) is missed; poll the focus if it bites
            self._blur(out)
            snap = _Snap(snapshot(), self.same)
            self.pages.append({"url": sample.get("url"), "title": sample.get("title"), "tree": snap.root, "events": []})
            self._state, self._seen = self._states(snap), snap
        focus, hit = sample.get("focus"), sample.get("hit")
        click = self._down and not was_down and hit is not None
        moved = snap is not None or not self._is(focus, self._focus)   # a new page: look at the focus afresh
        if click or moved:
            snap = snap or _Snap(snapshot(), self.same)
            self._diff(snap, out)
            if self._field:   # the field's value as of now
                n = snap.find(self._field["handle"])
                if n:
                    self._field["ev"] = _event("fill", snap, n, _value(n))
                    self._field["now"] = _value(n)
            if moved:
                self._focus = focus
                self._blur(out)
                n = snap.find(focus)
                if n and n.role in TEXT:
                    v = _value(n)
                    self._field = {"handle": focus, "start": v, "now": v, "ev": _event("fill", snap, n, v)}
            if click:
                self._flush(out)   # typed before this click (e.g. Next), even if focus hasn't left yet
                self._click(snap, hit, out)
        return out

    def _emit(self, out, ev):
        out.append(ev)
        self.pages[-1]["events"].append(ev)

    def _flush(self, out):
        """The focused field's fill, once per change (a secure field can't be compared: one hand-fill)."""
        f = self._field
        if f and (f["now"] != f["start"] or (f["ev"]["secure"] and not f.get("sent"))):
            self._emit(out, f["ev"])
            f["start"], f["sent"] = f["now"], True

    def _blur(self, out):
        self._flush(out)
        self._field = None

    def _states(self, snap):
        return [(n.handle, n.role, n.value, n.name, n) for n in snap.nodes
                if n.handle is not None and (n.role in STATE or NO_FILE in n.name)]

    def _diff(self, snap, out):
        """Ticks, choices and attached files since the last look (state nodes matched by handle)."""
        old, prev, self._state, self._seen = self._state, self._seen, self._states(snap), snap
        for h, role, value, name, o in old:
            n = snap.find(h)
            if n is None:
                continue
            if NO_FILE in name and NO_FILE not in n.name:   # located as it was: its name now holds the file name
                self._emit(out, _event("attach", prev, o))
            elif role in STATE and n.value != value and not (role == "radio" and n.value in ("", "0")):
                self._emit(out, _event(STATE[role], snap, n, n.value))   # a radio counts once: when picked

    def _click(self, snap, hit, out):
        n = snap.find(hit)
        if n is None or n is snap.root:
            return   # outside the page (browser toolbar) or its background
        t = n
        while t is not None and t.role not in ("link", "button") and t.role not in FIELD_ROLES and t.role not in TEXT:
            t = snap.up.get(id(t))
        t = t or n
        if t.role in FIELD_ROLES or t.role in TEXT:
            return   # fields become fill/choose/tick events, not clicks
        self._emit(out, _event("click", snap, t, submit=t.role == "button"))   # draft_page rates buttons submit
