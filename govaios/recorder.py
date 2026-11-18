"""Teach recorder: each press the extension reports is read in the AX tree at once, before the page reacts, and
saved to the open lesson as a click step. The fields typed in before the press come with it by name only: each value
is read from the tree and saved as a type step. Stored trees still have every field's value blanked.
Ported from spikes/plan6/match_spike.py (on_down, spec_of), which passed on JobLens."""
import re
from datetime import datetime
from urllib.parse import urlsplit

from . import capture, lessons, studio, terms
from .policy import OWN_HOSTS, PANEL_PORT
from .applyfiles import TEACH_OPEN, TEACH_OUT, remove, write_json
from .engine import find_all
from .formfill import FIELD_ROLES, Field, restricted

FLOW = "teach_new"
CLICKABLE = ("link", "button", "tab", "radio")
COUNT = re.compile(r"^(.*\S) \(\d+\)$")   # "Shortlisted (4)": the count changes, so it is never part of the step
OWN, PANEL_PORT = OWN_HOSTS, PANEL_PORT   # one source: policy
MISMATCH = "Run could not find this. Do it again, or skip it."
OUTSIDE = "This site's terms are not marked allowed in Studio: recording paused."
UNSAVED = "Could not save this step. Do it again."
MISSED = "Missed that press. Do it again."
SECRET = "Password fields are never recorded: you type them at Run."
MULTI = "Multi-line text is not supported yet: type it by hand at Run."
SECURE = "native:AXSecureTextField"
TYPED = ("text_field", "text_area", SECURE)


def _plain(name):
    """A name as the page's own text has it: icon-font glyphs (CSS ::before, Unicode private use) dropped."""
    return re.sub(r"\s+", " ", re.sub("[\ue000-\uf8ff]", "", name or "")).strip()


def _key(url):
    s = urlsplit(url or "")
    return f"{s.scheme}://{s.netloc}{s.path}"


def _title(root):
    h = next((n.name for n in root.walk() if n.role == "heading" and n.name), "")
    return f"{root.name} · {h}" if h else root.name


def _blank(root):
    """The snapshot in capture.tree form with every field's value dropped: a lesson never stores what was typed."""
    t = capture.tree(root)
    for d in studio._walk(t):
        if d["role"] in FIELD_ROLES or d["role"] in TYPED:
            d.pop("value", None)
    return t


def _line(title, ev):
    if ev["kind"] == "type":
        return f"{title}: type into {ev['label']}"
    return f"{title}: {'click' if ev['risk'] == 'navigate' else 'you press'} {ev['label']}"


def _spec(root, node):
    t = capture.tree(root)
    ds = list(studio._walk(t))
    spec = studio.element_spec(t, ds[next(i for i, m in enumerate(root.walk()) if m is node)])
    m = COUNT.match(node.name)
    if spec and m and "name" in spec:   # the count-free form, if it still finds exactly this node
        alt = {k: v for k, v in spec.items() if k not in ("name", "index")}
        alt["name_matches"] = f"^{re.escape(m.group(1))} \\(\\d+\\)$"
        hits = find_all(root, alt, {"elements": {}})
        if len(hits) == 1 and hits[0] is node:
            return alt
    return spec


class Recorder:
    def __init__(self, desk, app, home, run_id, lesson=None):
        self.desk, self.app, self.home, self.run = desk, app, home, run_id
        self.paused = self.done = self.cancelled = False
        self.note, self.at = "", None   # at: (key, title) of the page recording paused on (None: resume anywhere)
        if lesson:
            self.name, self.doc = lesson, lessons.load(home, lesson)
        else:
            self.name = lessons.new_name(FLOW)
            self.doc = {"flow": FLOW, "digest": None, "step": None, "at": datetime.now().isoformat(timespec="seconds"),
                        "new_app": True, "pages": []}
            lessons.write(home, self.name, self.doc)
        self.lines = [_line(p["title"], e) for p in self.doc["pages"] for e in p["events"]]
        write_json(home, TEACH_OPEN, {"lesson": self.name})
        self._out()

    def handle(self, ev):
        kind = ev.get("kind")
        if self.done or self.cancelled:
            return
        if kind == "cancel":
            self.cancelled = True
            remove(self.home, f"{lessons.DIR}/{self.name}", TEACH_OPEN)
        elif kind == "done":
            url, root = self.desk.current_url(self.app), None
            if self._ok(url):
                root = self.desk.web_root(self.app)
            if root is not None:   # the page Done was pressed on is what a run must end on
                self.doc["done_tree"], self.doc["done_url"] = _blank(root), _key(url)
                try:
                    lessons.write(self.home, self.name, self.doc)
                except OSError:
                    self.note = UNSAVED
            self.done = True   # TEACH_OPEN stays: the panel binds the lesson, then removes it
        elif kind == "pause":
            key, root = _key(self.desk.current_url(self.app)), self.desk.web_root(self.app)
            self.paused, self.note, self.at = True, "", (key, _title(root) if root else key)
        elif kind == "resume":
            if self.at and _key(self.desk.current_url(self.app)) != self.at[0]:
                self.note = f"Go back to {self.at[1]} to resume."
            else:
                self.paused, self.note, self.at = False, "", None
        elif kind == "down" and not self.paused:
            root, kept = None, ""
            for name in ev.get("types") or []:   # typed before the press, so saved before it
                root = self._type(ev, name, root)
                kept = self.note or kept
            self._down(ev, root)
            self.note = self.note or kept   # a refused field's note outlives the press saved after it
        self._out()

    def _ok(self, url):
        s = urlsplit(url)
        own = s.scheme == "http" and s.hostname in OWN and s.port != PANEL_PORT   # never the panel's own pages
        return own or (s.scheme == "https" and terms.verdict(self.home, url, ()) == "allowed")

    def _type(self, ev, name, root):
        """Saves the value the tree holds for the one field named `name`; returns the snapshot, read once per press."""
        url = self.desk.current_url(self.app)
        if not self._ok(url):
            self.paused, self.note, self.at = True, OUTSIDE, None
            return root
        if _key(ev.get("url")) != _key(url):
            self.note = MISSED
            return root
        root = self.desk.web_root(self.app) if root is None else root
        hits = [n for n in root.walk() if n.role in TYPED and _plain(n.name) == _plain(name)] if root else []
        if not _plain(name) or len(hits) != 1:   # rule 2: exactly the field the page reported
            self.note = MISMATCH
            return root
        n = hits[0]
        if n.role == SECURE or restricted(Field("", n.name, "text", (), False)):
            self.note = SECRET
            return root
        if any(ord(c) < 32 or ord(c) == 127 for c in n.value or ""):
            self.note = MULTI
            return root
        spec = _spec(root, n)
        if spec is None or [id(h) for h in find_all(root, spec, {"elements": {}})] != [id(n)]:   # a run finds it once
            self.note = MISMATCH
            return root
        self._save(root, url, {"kind": "type", "spec": spec, "label": n.name, "value": n.value or "", "secure": False,
                               "risk": "modify", "sure": True, "before": _blank(root)})
        return root

    def _down(self, ev, root=None):
        url = self.desk.current_url(self.app)
        if not self._ok(url):
            self.paused, self.note, self.at = True, OUTSIDE, None
            return
        if _key(ev.get("url")) != _key(url) or ev.get("x") is None or ev.get("y") is None:
            self.note = MISSED   # pressed on another page than the one read, or no point
            return
        hit = self.desk.element_at(ev["x"], ev["y"])
        if hit is None:
            return
        root = self.desk.web_root(self.app) if root is None else root   # one snapshot per press
        if root is None:
            return
        n = next((m for m in root.walk() if self.desk.same(m.handle, hit)), None)
        up = {id(c): p for p in root.walk() for c in p.children}
        while n is not None and n.role not in CLICKABLE:
            n = up.get(id(n))
        if n is None:
            return   # empty space
        if _plain(n.name) != _plain(ev.get("name")):   # rule 2: what GOV-AIOS reads must be what the page reported
            self.note = MISMATCH
            return
        spec = _spec(root, n)
        if spec is None:   # rule 2: no step a run could find again, so none is saved
            self.note = MISMATCH
            return
        sure = [id(h) for h in find_all(root, spec, {"elements": {}})] == [id(n)]
        risk = lessons.level(n.role, n.name)
        self._save(root, url, {"kind": "click", "spec": spec, "label": n.name, "value": "", "secure": False,
                               "submit": risk != "navigate", "risk": risk, "sure": sure, "before": _blank(root)})

    def _save(self, root, url, e):
        """Adds the step to its page; a field typed again keeps only its latest value, at its latest place."""
        key = _key(url)
        pages, before = self.doc["pages"], list(self.doc["pages"])
        page = next((p for p in pages if p["url"] == key), None)
        if page is None:   # a page's tree and title are its first snapshot's
            page = {"url": key, "title": _title(root), "tree": _blank(root), "events": []}
            pages.append(page)
        elif page is not pages[-1]:   # back on an earlier page: a run does each page once, so this visit's clicks win
            pages.remove(page)
            page = {**page, "events": []}
            pages.append(page)
        events = page["events"]
        page["events"] = [x for x in events if e["kind"] != "type" or x["kind"] != "type" or x["spec"] != e["spec"]] + [e]
        try:
            lessons.write(self.home, self.name, self.doc)
        except OSError:   # undo in memory too, so what is shown is what is on disk
            page["events"] = events
            self.doc["pages"] = before
            self.note = UNSAVED
            return
        self.lines = [_line(p["title"], x) for p in self.doc["pages"] for x in p["events"]]
        self.note = ""

    def _out(self):
        write_json(self.home, TEACH_OUT, {"run": self.run, "lesson": self.name, "paused": self.paused,
                                          "note": self.note, "lines": self.lines})
