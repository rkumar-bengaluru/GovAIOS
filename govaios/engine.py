"""OS-agnostic flow engine: page identification, element location, step execution.
Every OS side effect goes through the desktop adapter, and every action is
decided by policy.decide() first."""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from .approvals import Approvals, flow_hash, pages_used
from .policy import decide, origin

REPO = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent


class Stop(Exception):
    """Flow stopped: unexpected state, denial, or admin needed (Rule 2)."""


# ---------- element location (neutral roles only) ----------

def matches(node, spec):
    if spec.get("role") and node.role != spec["role"]:
        return False
    if "name" in spec and node.name != spec["name"]:
        return False
    if "name_matches" in spec and not re.search(spec["name_matches"], node.name):
        return False
    if "dom_id" in spec and node.dom_id != spec["dom_id"]:
        return False
    if "dom_class" in spec and spec["dom_class"] not in node.dom_class:
        return False
    if node.name in spec.get("exclude_names", []):
        return False
    return True


def find_all(root, spec, page):
    scope = root
    if "within" in spec:
        found = find_all(root, page["elements"][spec["within"]], page)
        if not found:
            return []
        scope = found[0]
    hits = [n for n in scope.walk() if n is not scope and matches(n, spec)]
    if "index" in spec:
        return hits[spec["index"]:spec["index"] + 1]
    return hits


def field_value(node, spec):
    v = node.text() if spec.get("text") else (node.name or node.text())
    for suffix in spec.get("strip_suffix", []):
        v = v.removesuffix(suffix)
    return v.strip()


def identify(page, root):
    """Document title (not window title: its format differs per OS and browser) + anchors."""
    ident = page["identification"]
    if not re.search(ident.get("title_matches", ""), root.name):
        return False
    for anchor in ident.get("anchors", []):
        if not find_all(root, page["elements"][anchor], page):
            return False
    for anchor in ident.get("absent", []):
        if find_all(root, page["elements"][anchor], page):
            return False
    return True


# ---------- executor ----------

class Runner:
    def __init__(self, flow_path, desktop, approvals_path=REPO / "approvals.json"):
        self.flow_path = Path(flow_path)
        self.flow = yaml.safe_load(self.flow_path.read_text())["workflow"]
        self.d = desktop
        self.app = self.flow["browser"]["application"]
        self.approvals = Approvals(approvals_path)
        self.pages = {}
        for pid in sorted(pages_used(self.flow)):
            try:
                self.pages[pid] = yaml.safe_load((REPO / "pages" / f"{pid}.yaml").read_text())["page"]
            except FileNotFoundError:
                raise Stop(f"unknown page: {pid}") from None
        self.ctx = {}

    def log(self, msg):
        print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

    # governance gate for every side effect
    def gate(self, action, risk, destination=None):
        req = {"action": action, "risk": risk, "destination": destination}
        verdict = decide(req, self.flow, self.approvals)
        if verdict == "ask":
            q = f"Flow '{self.flow['id']}' wants to {action}"
            q += f" and reach {origin(destination)} for the first time." if destination else "."
            if not self.d.ask_admin(q + " Approve?", timeout_s=180):
                raise Stop(f"admin denied {action} {destination or ''}")
            if destination:
                self.approvals.approve_destination(self.flow["id"], origin(destination))
            verdict = "allow"
        if verdict != "allow":
            raise Stop(f"policy denied {action} (risk {risk}) {destination or ''}")
        self.log(f"allow {action} risk={risk} {destination or ''}")

    def approve_flow(self):
        digest = flow_hash(self.flow_path, REPO / "pages")
        if self.approvals.flow_ok(self.flow["id"], digest):
            return
        f = self.flow
        q = (f"First run of flow '{f['id']}' (v{f['version']}). It may: {', '.join(f['permissions']['allow'])}; "
             f"max element risk {f['permissions']['max_element_risk']}; destinations "
             f"{', '.join(f['destinations'])}. Approve this flow?")
        if not self.d.ask_admin(q, timeout_s=180):
            raise Stop("admin did not approve the flow")
        self.approvals.approve_flow(f["id"], digest)

    def snapshot(self):
        for _ in range(10):
            root = self.d.web_root(self.app)
            if root is not None and root.children:
                return root
            time.sleep(1)
        raise Stop("web tree not available (renderer accessibility)")

    def current_page(self, candidates):
        root = self.snapshot()
        hits = [c for c in candidates if identify(self.pages[c], root)]
        if len(hits) > 1:
            raise Stop(f"ambiguous page: {hits}")   # Rule 2: never guess
        return (hits[0] if hits else None), root

    def wait_for_page(self, candidates, timeout):
        deadline = time.time() + timeout
        while True:
            page, root = self.current_page(candidates)
            if page or time.time() > deadline:
                return page, root
            time.sleep(1)

    def element(self, ref, root):
        page_id, el_id = ref.split(".")
        page = self.pages[page_id]
        hits = find_all(root, page["elements"][el_id], page)
        if len(hits) != 1:
            raise Stop(f"{ref}: expected 1 element, found {len(hits)}")
        return hits[0], page["elements"][el_id]

    # ----- step actions -----
    def run(self):
        self.approve_flow()
        self.steps(self.flow["steps"])
        self.log("flow complete")

    def steps(self, steps):
        for s in steps:
            self.log(f"step {s['id']}")
            getattr(self, "do_" + s["action"])(s)

    def do_launch_application(self, s):
        self.gate("launch_application", "navigate")
        self.d.launch_application(self.app, self.flow["browser"].get("profile_directory"))

    def do_verify_account(self, s):
        """Profile display names can repeat; the signed-in account shown on the page is the proof."""
        node, _ = self.element(s["target"], self.snapshot())
        want = self.flow["browser"]["account"]
        if f"({want})" not in node.name:
            raise Stop(f"wrong browser profile: expected {want}, page shows {node.name!r}")
        self.log(f"account verified: {want}")

    def do_navigate(self, s):
        self.gate("navigate", "navigate", s["value"])
        self.d.press("focus_address_bar")
        self.d.type_text(s["value"])
        self.d.press("enter")
        time.sleep(2)

    def do_classify_page(self, s):
        cases = s["on_match"]
        candidates = [p for p in cases if p != "unknown"]
        for attempt in range(3):                         # bounded resumes (Rule 10)
            page, root = self.wait_for_page(candidates, s.get("timeout_seconds", 20))
            what = cases.get(page or "unknown", "stop_and_report")
            if what == "continue":
                url = self.d.current_url(self.app)
                self.gate("read_page", "read", url)      # landed origin must be declared
                self.ctx["page"] = page
                return
            if what == "stop_and_report":
                raise Stop(f"unexpected page (title {self.d.window_title(self.app)!r})")
            self.log(f"{page}: admin action needed")    # stop_and_request_user (Rule 6)
            if not self.d.ask_admin(f"GOV-AIOS stopped at '{page}'. Complete it yourself in Chrome, "
                                    f"then click Approve to continue.", timeout_s=300):
                raise Stop(f"stopped at {page}; admin did not resume")
        raise Stop("still not on the expected page after admin action")

    def do_select_items(self, s):
        page_id, el_id = s["target"].split(".")
        page, root = self.wait_for_page([page_id], 10)
        if not page:
            raise Stop(f"not on {page_id}")
        spec = self.pages[page_id]["elements"][el_id]
        items = find_all(root, spec, self.pages[page_id])[: s["count"]]
        if not items:
            raise Stop("no items found")
        # remember identity, not handles: the tree is rebuilt after each navigation
        self.ctx["items"] = [self._fields(it, spec, page_id) for it in items]
        self.ctx["item_spec"] = (page_id, el_id)
        self.log(f"selected {len(items)}: " + "; ".join(i.get("title", "?") for i in self.ctx["items"]))

    def _fields(self, item_node, spec, page_id):
        out = {}
        for k, fs in spec["fields"].items():
            hits = [item_node] if fs.get("self") else find_all(item_node, fs, self.pages[page_id])
            out[k] = field_value(hits[0], fs) if hits else None
        return out

    def do_for_each_item(self, s):
        for i, item in enumerate(self.ctx["items"], 1):
            self.ctx["item"], self.ctx["n"] = item, i
            self.steps(s["steps"])

    def _current_item_node(self, field):
        page_id, el_id = self.ctx["item_spec"]
        page, root = self.wait_for_page([page_id], 15)
        if not page:
            raise Stop(f"not back on {page_id}")
        spec = self.pages[page_id]["elements"][el_id]
        for it in find_all(root, spec, self.pages[page_id]):
            if self._fields(it, spec, page_id) == self.ctx["item"]:
                fs = spec["fields"][field]
                return (it if fs.get("self") else find_all(it, fs, self.pages[page_id])[0]), fs
        raise Stop("selected item no longer on the page")   # identity check

    def do_click(self, s):
        tgt = s["target"]
        if tgt.startswith("current_item."):
            node, spec = self._current_item_node(tgt.split(".", 1)[1])
        else:
            node, spec = self.element(tgt, self.snapshot())
        self.gate("click", spec["risk"])
        before = self.d.current_url(self.app)
        for attempt in range(2):                         # one bounded retry (Rule 10)
            self.d.scroll_into_view(node)
            node, spec = (self._current_item_node(tgt.split(".", 1)[1]) if tgt.startswith("current_item.")
                          else self.element(tgt, self.snapshot()))   # positions changed after scrolling
            self.d.click(node)
            if "verify_page" not in s:
                return
            page, _ = self.wait_for_page([s["verify_page"]], s.get("timeout_seconds", 15))
            if page:
                self.gate("read_page", "read", self.d.current_url(self.app))
                return
            if self.d.current_url(self.app) != before:
                break                                    # went somewhere unexpected: never retry
            self.log("click had no effect, retrying once")
        raise Stop(f"after click expected {s['verify_page']}")

    def do_extract(self, s):
        self.gate("extract_visible_text", "read")
        page = self.pages[s["page"]]
        root = self.snapshot()
        rec = {}
        for f in s["fields"]:
            hits = find_all(root, page["elements"][f], page)
            rec[f] = field_value(hits[0], page["elements"][f]) if hits else None
        rec["url"] = self.d.current_url(self.app)
        missing = [f for f in s.get("required", []) if not rec.get(f)]
        if missing:
            raise Stop(f"could not extract {missing}")
        self.ctx["record"] = rec

    def do_write_json(self, s):
        self.gate("write_file", "modify")
        out = REPO / s["directory"]
        out.mkdir(exist_ok=True)
        rec = {**self.ctx["record"], "list_item": self.ctx["item"],
               "captured_at": datetime.now().isoformat(timespec="seconds"),
               "flow": self.flow["id"], "flow_version": self.flow["version"]}
        slug = re.sub(r"[^a-z0-9]+", "-", (rec.get("job_title") or rec.get("title") or "item").lower()).strip("-")[:60]
        path = out / f"{datetime.now():%Y%m%d}-{slug}.json"
        path.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
        self.log(f"wrote {path.relative_to(REPO)}")

    def do_report(self, s):
        rec = self.ctx.get("record", {})
        print(f"  #{self.ctx.get('n')}: " + " | ".join(str(rec.get(f) or "")[:80] for f in s["fields"]))

    def do_browser_back(self, s):
        self.gate("navigate", "navigate")
        self.d.press("browser_back")
        time.sleep(2)
