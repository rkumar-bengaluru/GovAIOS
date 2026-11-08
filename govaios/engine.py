"""OS-agnostic flow engine: page identification, element location, step execution.
Every OS side effect goes through the desktop adapter, and every action is
decided by policy.decide() first."""
import hashlib
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import auth, runstate
from .agents import user_home
from .applyfiles import ASK, BANK, REPLY, RESULT, read_json, remove, write_json
from .formfill import (ASKABLE, cv_path, FIELD_ROLES, BankError, answer_for, load_bank, locate, normalize, ok_value,
                       read_form, restricted)
from .audit.log import AuditLog, url_for_audit
from .delivery import TARGETS, check_block
from .approvals import Approvals, pages_used, read_bound
from .policy import RISK_ORDER, decide, origin
from .runstate import Stop

REPO = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent


NO_DEST = object()
FORM_PASSES = 3
ASK_TIMEOUT_S = 900


class Denied(Stop):
    """The admin (or policy) refused an action; the run may carry on without it."""


def _emergency_stop(signum, frame):
    raise Stop("emergency stop")


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


def approval_question(f, deliver):
    return (f"First run of flow '{f['id']}' (v{f['version']}). It may: {', '.join(f['permissions']['allow'])}; "
            f"max element risk {f['permissions']['max_element_risk']}; destinations "
            f"{', '.join(f['destinations'])}"
            f"{'; delivers to: ' + TARGETS[deliver['to']]['label'] if deliver else ''}. Approve this flow?")


def _lists(root):
    """`list` nodes by their path of child indexes from the root (handles change between snapshots)."""
    out = {}

    def walk(n, path):
        if n.role == "list":
            out[path] = n
        for i, c in enumerate(n.children):
            walk(c, path + (i,))
    walk(root, ())
    return out


def _new_lists(before, root, region):
    """`list` nodes inside the form region whose path wasn't in `before` (an open dropdown)."""
    inside = {id(n) for n in region.walk()}
    return [l for p, l in _lists(root).items() if p not in before and id(l) in inside]


def _named(n, value):
    """Outermost descendants whose name or text equals value (an option, not also its own text child)."""
    for c in n.children:
        if c.name == value or c.text() == value:
            yield c
        else:
            yield from _named(c, value)


def _option(group, value):
    return next((n for n in group.walk() if n.role == "radio" and n.name == value), None)


# ---------- executor ----------

class Runner:
    def __init__(self, flow_path, desktop, home, executor="gov_runner_dev", ticket=None, inputs=None):
        self.home = Path(home)
        self.ticket = ticket   # panel run: a one-use ticket stands in for the Touch ID start proof
        self.inputs = inputs   # validated in _run, not here: the panel builds a Runner only to approve the flow
        self.run_id = None
        if ticket is not None:
            from .panel import tickets
            self.run_id = tickets.run_id(ticket)
        self.executor = executor   # "gov_runner" only when cli runs inside com.govaios.cli
        self.flow_path = Path(flow_path)
        self.pages_dir = self.flow_path.parent.parent / "pages"   # flows/ and pages/ are siblings
        try:
            self.digest, raw = read_bound(self.flow_path, self.pages_dir)   # approval binds to these bytes
        except KeyError as e:
            raise Stop(f"unknown page: {e.args[0]}") from None
        self.flow = yaml.safe_load(raw[self.flow_path])["workflow"]
        if not re.fullmatch(r"[a-z0-9_]+", str(self.flow.get("id"))):   # it becomes part of a report filename
            raise Stop("invalid flow id")
        try:
            self.deliver = check_block(self.flow)
        except ValueError as e:
            raise Stop(f"bad deliver block: {e}") from None
        self.d = desktop
        self.launched = False
        self.shown = None   # digest of the last approval text shown (set by ask)
        self.report_path = None
        self.app = self.flow["browser"]["application"]
        self.approvals = Approvals(self.home / "approvals.json")
        self.audit = AuditLog(self.home)
        self.step = None
        self.pages = {}
        for pid in sorted(pages_used(self.flow)):
            self.pages[pid] = yaml.safe_load(raw[self.pages_dir / f"{pid}.yaml"])["page"]
        self.ctx = {}

    def _audit(self, kind, **f):
        """One signed entry; console shows only kind, step and decision (no content)."""
        self.audit.append(kind, flow=self.flow["id"], flow_version=self.flow["version"],
                          executor=self.executor, step=self.step, **f)
        print(f"[{datetime.now():%H:%M:%S}] {kind} {self.step or ''} {f.get('decision') or ''}".rstrip(), flush=True)

    def _act(self, name, fn, *args, target=None):
        """Every OS side effect, audited as done/error (arguments such as typed text are never logged)."""
        try:
            out = fn(*args)
        except Exception:
            self._audit("action", action=name, target=target, outcome="error")
            raise
        self._audit("action", action=name, target=target, outcome="done")
        return out

    def ask(self, question, reason):
        """Authenticated admin prompt; afterwards (any answer) the flow's app is brought back before any further input."""
        ok, how = auth.approve(question, reason, self.home)
        # audited with the answer: what exactly was shown ("none": the Touch ID prompt never appeared)
        self.shown = auth.shown_digest(question, None if how == "none" else reason)
        if self.launched:
            self._act("activate", self.d.activate, self.app)
        return ok, how

    # governance gate for every side effect
    def gate(self, action, risk, target=None, destination=NO_DEST, question=None):
        if runstate.stopped(self.home):   # row 28: backs up the guard's SIGTERM
            raise Stop("emergency stop")
        if not self.approvals.flow_ok(self.flow["id"], self.digest):   # revoked since approve_flow
            raise Stop("revoked")
        if destination is not NO_DEST and not destination:   # blank/None URL: fail closed
            self._audit("request", action=action, risk=risk, target=target, decision="deny",
                        approver="policy", channel=None, reason="no url")
            raise Stop(f"denied {action}: no url")
        if destination is NO_DEST:
            destination = None
        dest = url_for_audit(destination) if destination else None
        verdict = decide({"action": action, "risk": risk, "destination": destination}, self.flow, self.approvals)
        asked, how, remember = verdict == "ask", None, False
        if asked:
            q = f"Flow '{self.flow['id']}' wants to {action}"
            q += f" and reach {origin(destination)} for the first time." if destination else "."
            ok, how = self.ask(question or q + " Approve?", f"{self.flow['id']}: {action} {origin(destination) if destination else ''}".strip())
            verdict, remember = ("allow", bool(destination)) if ok else ("deny", False)
        self._audit("request", action=action, risk=risk, target=target, destination=dest, decision=verdict,
                    approver="admin" if asked else "policy", channel="touch_id" if asked else None, auth=how,
                    shown=self.shown if asked else None)
        if remember:   # only once the approval is on record
            self.approvals.approve_destination(self.flow["id"], origin(destination))
        if verdict != "allow":
            raise Denied(f"denied {action}: approval busy" if how == "busy" else f"denied {action} (risk {risk}) {dest or ''}")

    def approve_flow(self):
        digest = self.digest
        if self.approvals.flow_ok(self.flow["id"], digest):
            return
        f = self.flow
        ok, how = self.ask(approval_question(f, self.deliver), f"approve flow {f['id']}")
        self._audit("flow_approval", flow_hash=digest, decision="allow" if ok else "deny",
                    approver="admin", channel="touch_id", auth=how, shown=self.shown)
        if not ok:
            raise Stop("flow approval busy" if how == "busy" else "admin did not approve the flow")
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
                self._audit("verify", outcome=page or "no_match")
                return page, root
            time.sleep(1)

    def page_element(self, ref):
        """Element by schema ref, only after its page is identified (never on an unknown page)."""
        page_id = ref.split(".")[0]
        page, root = self.wait_for_page([page_id], 10)
        if not page:
            raise Stop(f"not on {page_id}")
        return self.element(ref, root)

    def element(self, ref, root):
        page_id, el_id = ref.split(".")
        page = self.pages[page_id]
        hits = find_all(root, page["elements"][el_id], page)
        if len(hits) != 1:
            raise Stop(f"{ref}: expected 1 element, found {len(hits)}")
        return hits[0], page["elements"][el_id]

    # ----- step actions -----
    def run(self):
        prev = signal.signal(signal.SIGTERM, _emergency_stop)   # the guard's stop (row 11): end as a recorded stop
        try:
            self._run()
        finally:
            signal.signal(signal.SIGTERM, prev)

    def _run(self):
        self.step = None
        self._audit("flow_start", flow_hash=self.digest)
        try:
            decl, given = self.flow.get("inputs") or {}, self.inputs or {}
            if set(given) != set(decl) or not all(
                    isinstance(v, str) and re.fullmatch(decl[k]["pattern"], v) for k, v in given.items()):
                raise Stop("bad run input")
            approved = self.approvals.flow_ok(self.flow["id"], self.digest)
            if self.ticket is not None:   # panel run: never a prompt; the ticket is the start proof
                from .panel import tickets
                sid = tickets.consume(self.home, self.ticket, self.flow["id"], self.digest, self.inputs)   # always: a refused ticket is spent too
                sid = approved and sid
                if approved:
                    extra = {"session": sid} if sid else {}
                    self._audit("request", action="run_start", decision="allow" if sid else "deny",
                                approver="admin", channel="totp_session", auth="ticket", **extra)
                if not sid:
                    raise Stop("run ticket not valid")
            elif approved:   # approved flow: Touch ID is the start proof
                ok, how = auth.prove(f"run {self.flow['id']}", self.home)
                self._audit("request", action="run_start", decision="allow" if ok else "deny",
                            approver="admin", channel="touch_id", auth=how)
                if not ok:
                    raise Stop("start not proven")
            else:
                self.approve_flow()
            self.steps(self.flow["steps"])
        except Exception as e:   # fail closed: any failure is a recorded stop
            self._audit("stop", reason=str(e) if isinstance(e, Stop) else type(e).__name__)
            raise
        self.step = None
        self._audit("flow_end", outcome="done")

    def steps(self, steps):
        for s in steps:
            if auth.screen_locked():
                raise Stop("screen_locked")
            if runstate.stopped(self.home):   # row 28: backs up the guard's SIGTERM
                raise Stop("emergency stop")
            self.step = s["id"]
            getattr(self, "do_" + s["action"])(s)

    def do_launch_application(self, s):
        self.gate("launch_application", "navigate")
        self._act("launch_application", self.d.launch_application, self.app, self.flow["browser"].get("profile_directory"))
        self.launched = True

    def do_verify_account(self, s):
        """Profile display names can repeat; the signed-in account shown on the page is the proof.
        The window it was read from is pinned: later input is refused in any other window."""
        window = self.d.focused_window_id(self.app)
        node, _ = self.page_element(s["target"])
        want = self.flow["browser"]["account"]
        if f"({want})" not in node.name:
            raise Stop("wrong browser profile: account on page does not match the flow")
        self.d.pin_window(window)   # refuses if focus left that window during the check

    def do_navigate(self, s):
        value = self.inputs[s["value_from"].removeprefix("input.")] if "value_from" in s else s["value"]
        self.gate("navigate", "navigate", destination=value)
        self._act("press", self.d.press, "focus_address_bar")
        self._act("type_text", self.d.type_text, value)
        self._act("press", self.d.press, "enter")
        time.sleep(2)

    def do_classify_page(self, s):
        cases = s["on_match"]
        candidates = [p for p in cases if p != "unknown"]
        for attempt in range(3):                         # bounded resumes (Rule 10)
            page, root = self.wait_for_page(candidates, s.get("timeout_seconds", 20))
            what = cases.get(page or "unknown", "stop_and_report")
            if what == "continue":
                url = self.d.current_url(self.app)
                self.gate("read_page", "read", destination=url)      # landed origin must be declared
                self.ctx["page"] = page
                return
            if isinstance(what, dict):                   # an interstitial (a popup): click past it once, look again
                candidates.remove(page)
                self.do_click({"id": self.step, "target": f"{page}.{what['click']}"})
                continue
            if what == "stop_and_report":
                raise Stop("unexpected page")
            # stop_and_request_user (Rule 6)
            ok, how = self.ask(f"GOV-AIOS stopped at '{page}'. Complete it yourself in Chrome, "
                               f"then click Approve to continue.", f"{self.flow['id']}: resume {page or 'unknown page'}")
            self._audit("request", action="resume", risk="read", target=page, decision="allow" if ok else "deny",
                        approver="admin", channel="touch_id", auth=how)
            if not ok:
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

    def ref(self, target):
        """Audit ref for a target; `current_page.<el>` names the page the run classified."""
        return f"{self.ctx['page']}.{target.split('.', 1)[1]}" if target.startswith("current_page.") else target

    def do_click(self, s):
        tgt = self.ref(s["target"])
        if tgt.startswith("current_item."):
            node, spec = self._current_item_node(tgt.split(".", 1)[1])
        else:
            node, spec = self.page_element(tgt)
        if tgt.startswith("current_item."):
            ref = "{}.{}[{}].{}".format(*self.ctx["item_spec"], self.ctx["n"], tgt.split(".", 1)[1])
        else:
            ref = tgt
        self.gate("click", spec["risk"], target=ref)
        before = self.d.current_url(self.app)
        for attempt in range(2):                         # one bounded retry (Rule 10)
            self._act("scroll_into_view", self.d.scroll_into_view, node, target=ref)
            node, spec = (self._current_item_node(tgt.split(".", 1)[1]) if tgt.startswith("current_item.")
                          else self.page_element(tgt))   # positions changed after scrolling
            self._act("click", self.d.click, node, target=ref)
            if "verify_page" not in s:
                return
            page, _ = self.wait_for_page([s["verify_page"]], s.get("timeout_seconds", 15))
            if page:
                self.gate("read_page", "read", destination=self.d.current_url(self.app))
                return
            if self.d.current_url(self.app) != before:
                break                                    # went somewhere unexpected: never retry
        raise Stop(f"after click expected {s['verify_page']}")

    def do_extract(self, s):
        self.gate("extract_visible_text", "read", target=s["page"], destination=self.d.current_url(self.app))
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
        out = (self.home / s["directory"]).resolve()   # never inside the sealed app bundle
        if not out.is_relative_to(self.home.resolve()):
            raise Stop("output directory outside the data home")
        out.mkdir(parents=True, exist_ok=True)
        rec = {**self.ctx["record"], "list_item": self.ctx["item"],
               "captured_at": datetime.now().isoformat(timespec="seconds"),
               "flow": self.flow["id"], "flow_version": self.flow["version"]}
        slug = re.sub(r"[^a-z0-9]+", "-", (rec.get("job_title") or rec.get("title") or "item").lower()).strip("-")[:60]
        path = out / f"{datetime.now():%Y%m%d}-{slug}-{hashlib.sha256((rec.get('url') or '').encode()).hexdigest()[:8]}.json"
        self._act("write_file", path.write_text, json.dumps(rec, indent=2, ensure_ascii=False))

    def do_report(self, s):
        """Page content goes to a 0600 file under the data home, never to stdout/stderr."""
        self.gate("report", "read")
        rec = self.ctx.get("record", {})
        line = f"#{self.ctx.get('n')}: " + " | ".join(str(rec.get(f) or "")[:80] for f in s["fields"]) + "\n"
        if self.report_path is None:
            (self.home / "reports").mkdir(mode=0o700, exist_ok=True)
            self.report_path = self.home / "reports" / f"{self.flow['id']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.txt"
            self.report_items = 0
        self._act("report", self._append_report, line)
        self.report_items += 1
        print(f"report: {self.report_items} items -> {self.report_path}", flush=True)

    def _append_report(self, line):
        fd = os.open(self.report_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(line)

    def do_close_window(self, s):
        """Close the flow's window only (press checks it is the verified window); the admin's other windows stay."""
        self.gate("close_window", "navigate")
        self._act("press", self.d.press, "close_window")

    def do_browser_back(self, s):
        self.gate("navigate", "navigate")
        self._act("press", self.d.press, "browser_back")
        time.sleep(2)

    # ----- job-application form -----
    def _form(self):
        page = self.ctx["page"]
        root = self.snapshot()
        if not identify(self.pages[page], root):
            raise Stop("left the form page")
        return root, self.element(f"{page}.form_region", root)[0]

    def _node(self, region, f, value):
        n = locate(region, f)
        if n is not None and f.kind == "radio":
            n = _option(n, value)
        return n if n is not None and n.role in FIELD_ROLES else None

    def fill(self, f, value, source):
        """One bank/admin answer into one field, re-found by key in a fresh snapshot, then read back.
        Never logs the value; Enter only inside a confirmed-open native menu."""
        root, region = self._form()
        node, label = self._node(region, f, value), f.label[:80]
        ok = node is not None and ok_value(value, f.kind)
        if ok:
            self.gate("fill_field", "modify", target=label, destination=self.d.current_url(self.app))
            # the form can sit below the fold (Greenhouse: under the job description); click() checks the point
            self._act("scroll_into_view", self.d.scroll_into_view, node, target=label)
            before = set(_lists(root))
            ok = self._enter(f.kind, node, value, before, label)
            root, region = self._form()   # re-found after entry or escape: the old handle may be stale
            node = n = self._node(region, f, value)
            if not ok or n is None:
                ok = False
            elif f.kind == "radio":
                ok = n.value == "1"
            elif f.kind == "select":
                ok = value in (n.value, n.name)
            elif f.kind == "combo":   # picked only once the dropdown closed; text in a still-open list doesn't count
                parent = next((p for p in region.walk() if any(c is n for c in p.children)), n)
                in_list = {id(x) for l in parent.walk() if l.role == "list" for x in l.walk()}
                ok = not _new_lists(before, root, region) and (n.value == value or any(
                    d.role == "text" and (d.value or d.name) == value and id(d) not in in_list for d in parent.walk()))
            else:
                ok = n.value == value
        if not ok and node is not None and f.kind in ("text", "textarea", "combo") and self.d.focused_is(node):
            self._act("press", self.d.press, "select_all", target=label)
            self._act("press", self.d.press, "delete_back", target=label)
        self._audit("action", action="fill_field", target=label, source=source, outcome="done" if ok else "mismatch")
        if not ok:
            self.ctx["apply"]["yourself"].append(f.label)
        return ok

    def _enter(self, kind, node, value, before, label):
        if kind in ("text", "textarea"):
            self._act("click", self.d.click, node, target=label)
            if not self.d.focused_is(node):
                return False
            self._act("type_into", self.d.type_into, node, value, target=label)
        elif kind == "combo":
            self._act("click", self.d.click, node, target=label)
            self._act("type_into", self.d.type_into, node, value, target=label)
            new = _new_lists(before, *self._form())
            cands = list({id(c): c for l in new for c in _named(l, value)}.values())
            if len(cands) != 1:
                self._act("press", self.d.press, "escape", target=label)
                return False
            self._act("click", self.d.click, cands[0], target=label)
        elif kind == "select":
            self._act("click", self.d.click, node, target=label)
            if not self.d.menu_open():
                self._act("press", self.d.press, "escape", target=label)
                return False
            self._act("type_text", self.d.type_text, value, target=label)
            if not self.d.menu_open():   # checked again right before Enter: never Enter in the web page
                self._act("press", self.d.press, "escape", target=label)
                return False
            self._act("press", self.d.press, "enter", target=label)   # inside the native menu, confirmed open
        else:   # radio: node is the option named value
            self._act("click", self.d.click, node, target=label)
        return True

    def do_fill_form(self, s):
        try:
            bank = load_bank(self.home / BANK, user_home())
        except BankError as e:
            raise Stop(f"answer bank: {e}") from None
        a = self.ctx["apply"] = {"bank": bank, "filled": 0, "total": 0, "yourself": [], "check": [], "pending": []}
        done = set()
        for _ in range(FORM_PASSES):   # a fill can reveal conditional fields
            fields = read_form(self._form()[1])
            new = [f for f in fields if f.key not in done]
            if not new:
                break
            for f in new:
                done.add(f.key)
                a["total"] += 1
                hit = answer_for(f, bank, fields)
                if f.filled:
                    a["check"].append(f.label)
                elif hit:
                    a["filled"] += self.fill(f, *hit)
                elif restricted(f) or not normalize(f.label) or f.kind not in ASKABLE:
                    a["yourself"].append(f.label)
                else:
                    a["pending"].append(f)
        self.ask_pending()
        self.write_result()

    def do_attach_file(self, s):
        """Attach the admin's CV through the native file dialog, Touch ID every time. The path is never logged."""
        from .desktop.macos import InputRefused   # lazy: pyobjc only on the real desktop
        a, ref = self.ctx["apply"], self.ref(s["target"])
        a["yourself"].append("Resume/CV")   # until attached: a stop from here on leaves it on the result card
        self.write_result()
        p = cv_path(a["bank"], user_home())
        if p is not None:
            _, spec = self.page_element(ref)
            if RISK_ORDER.index(spec["risk"]) > RISK_ORDER.index(self.flow["permissions"]["max_element_risk"]):
                raise Stop(f"{ref}: risk {spec['risk']} above the flow's ceiling")   # never click it
            try:
                self.gate("attach_file", spec["risk"], target=ref,
                          question=f"Attach your CV ({p.name}) to this application?")
            except Denied:
                p = None
        if p is not None:
            node, _ = self.page_element(ref)   # re-located after the prompt, as do_click does
            self._act("scroll_into_view", self.d.scroll_into_view, node, target=ref)
            node, _ = self.page_element(ref)
            self._act("click", self.d.click, node, target=ref)
            try:
                self._act("choose_file", self.d.choose_file, str(p), target=ref)
            except InputRefused:   # fixed text, no path; any other Stop ends the run
                self._act("press", self.d.press, "escape", target=ref)
                p = None
        if p is not None:
            try:
                chk, _ = self.element(self.ref(s["check"]), self.wait_for_page([ref.split(".")[0]], 10)[1])
                if "No file chosen" in chk.name:
                    p = None
            except Stop:   # the check element is missing or ambiguous
                if runstate.stopped(self.home):   # an emergency stop (STOPPED is touched before SIGTERM)
                    raise
                p = None
        if p is not None:
            a["yourself"].remove("Resume/CV")
        self.write_result()

    def ask_pending(self):
        """Hand the unmatched fields to the admin via the panel (ask.json/reply.json), then type the answers in.
        A CLI run (no ticket) never asks. Values are never logged."""
        a = self.ctx["apply"]
        pend, a["pending"] = a["pending"], []
        if not pend or self.run_id is None:
            a["yourself"] += [f.label for f in pend]
            return
        self.gate("ask_admin", "read")
        # a select's first option is its placeholder (formfill's rule): never offered, never accepted
        offered = {f.key: list(f.options[1:] if f.kind == "select" else f.options if f.kind == "radio" else ())
                   for f in pend}
        asked = {f.key: f for f in pend}
        try:
            remove(self.home, REPLY)   # a late reply to an earlier ask in this run must not answer this one
            write_json(self.home, ASK, {"run": self.run_id, "fields": [
                {"key": f.key, "label": f.label, "kind": f.kind, "options": offered[f.key]} for f in pend]})
            deadline = time.monotonic() + ASK_TIMEOUT_S
            while True:
                reply = read_json(self.home, REPLY)   # None mid-write or garbled: not yet
                if reply and reply.get("run") == self.run_id:
                    break
                if runstate.stopped(self.home):
                    raise Stop("emergency stop")
                if auth.screen_locked():
                    raise Stop("screen_locked")
                if time.monotonic() > deadline:
                    raise Stop("no answer from admin")
                time.sleep(1)
        finally:
            remove(self.home, ASK, REPLY)
        answers = reply.get("answers")
        if not isinstance(answers, dict) or not all(
                k in asked and isinstance(v, str) and len(v) <= 2000 and ok_value(v, asked[k].kind)
                and (not v or asked[k].kind not in ("select", "radio") or v in offered[k])
                for k, v in answers.items()):
            raise Stop("bad reply")
        self._act("raise_pinned", self.d.raise_pinned)
        for f in pend:
            v = answers.get(f.key, "")
            if v:
                a["filled"] += self.fill(f, v, "admin")
            else:
                a["yourself"].append(f.label)

    def write_result(self):
        """Counts and labels only, never values."""
        a = self.ctx["apply"]
        if self.run_id is not None:
            write_json(self.home, RESULT, {"run": self.run_id, "filled": a["filled"], "total": a["total"],
                                           "yourself": a["yourself"], "check": a["check"]})
        print(f"apply: filled {a['filled']} of {a['total']}", flush=True)
