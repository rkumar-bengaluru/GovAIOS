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
from urllib.parse import urlsplit

from . import auth, capture, runstate, studio, terms
from .agents import user_home
from .applyfiles import ASK, BANK, CARDS, LESSON_LIVE, REPLY, RESULT, SANDBOX, TASKS, TEACH_IN, read_json, remove, write_json
from .formfill import (ASKABLE, cv_path, FIELD_ROLES, BankError, answer_for, load_bank, locate, normalize, ok_value,
                       read_form, restricted)
from .audit.log import AuditLog, url_for_audit
from .delivery import TARGETS, check_block
from .approvals import Approvals, pages_used, read_bound
from .policy import RISK_ORDER, decide, origin, own
from .runstate import Stop

REPO = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent.parent


NO_DEST = object()
LEARNED_ACTIONS = ("click", "fill_form", "attach_file", "hand_over", "repeat")   # what a taught page may do (Studio lessons)
ITEM_ROLES = ("row", "article")   # what a repeat round works on: one list item
MAX_LEARNED = 10   # learned pages run within one classify_page call
FORM_PASSES = 3
ASK_TIMEOUT_S = 900
TEACH_IDLE_S = 1800   # the teaching card ends after 30 min with no new event
LIVE_LINES = 50


# A stop inside one JobLens task that ends the whole run, not just that job: safety and the admin's own choices.
RUN_STOPS = ("emergency stop", "screen_locked", "revoked", "no answer from admin", "bad reply", "ended by admin",
             "the browser has no window in front", "Try it stops here")
TRY_STOP = ("Try it stops here: the real run will press {}. Close the pop-up, or press Run: it starts from your "
            "start page.")
def _ends_run(e):
    m = str(e)
    return m.startswith(RUN_STOPS) or m.startswith("input refused") and "not on the target element" not in m


class TeachEnded(Stop):
    """A lesson's own outcome (cancelled, discarded, learned, skipped, terms refused): the job ends, the run goes on."""


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
    if "has" in spec and not any(d is not node and matches(d, spec["has"]) for d in node.walk()):
        return False   # e.g. a repeated card that holds a link (a header row of the same role holds none)
    if "has_text" in spec and not any(d.role == "text" and (d.value or d.name) == spec["has_text"]
                                      for d in node.walk()):
        return False   # e.g. a JobLens row whose Status cell shows "Ready"
    return True


def find_all(root, spec, page):
    scope = root
    if "within" in spec:
        found = find_all(root, page["elements"][spec["within"]], page)
        if not found:
            return []
        scope = found[0]
    pool = scope.children if spec.get("direct") else (n for n in scope.walk() if n is not scope)
    hits = [n for n in pool if matches(n, spec)]   # direct: only the scope's own children (cards holding cards)
    if "index" in spec:
        return hits[spec["index"]:spec["index"] + 1]
    return hits


def item_spec(spec):
    """The item's own target spec: the row is the container, so the taught index and within do not apply."""
    return {k: v for k, v in spec.items() if k not in ("index", "within")}


def item_candidates(root, spec, page):
    """List items (innermost) holding exactly one match of item_spec(spec), in walk order."""
    spec = item_spec(spec)
    held = [n for n in root.walk() if n.role in ITEM_ROLES and len(find_all(n, spec, page)) == 1]
    return [n for n in held if not any(m is not n and any(x is m for x in n.walk()) for m in held)]


def item_target(item, spec, page):
    return find_all(item, item_spec(spec), page)[0]


def item_label(item, target):
    """The item's first name other than the target's: for audit and messages only, never its identity."""
    return next((n.name for n in item.walk() if n is not target and n.name), "")[:200]


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


def check_learned(steps, pages=None):
    """A learned page case {do: [steps], then: again|end}: only the allowed actions, each with its own id."""
    ids = []

    def walk(steps):
        for s in steps:
            ids.append(s.get("id"))
            walk(s.get("steps", []))
            for page, v in s.get("on_match", {}).items():
                if not (isinstance(v, dict) and "do" in v):
                    continue
                if page == "unknown":   # its steps would run on a page the engine never identified
                    raise Stop("learned steps: unknown cannot be taught")
                if not isinstance(v["do"], list) or not v["do"]:
                    raise Stop(f"learned steps: {page} has no steps")
                if v.get("then") not in ("again", "end"):
                    raise Stop("learned steps: then must be again or end")
                for d in v["do"]:
                    if not isinstance(d, dict) or not d.get("id"):
                        raise Stop("learned steps: a step without an id")
                    if d.get("action") not in LEARNED_ACTIONS:
                        raise Stop(f"learned steps: {d.get('action')} not allowed")
                    ids.append(d["id"])
                    learned.add(d["id"])
                    if d["action"] == "repeat":
                        check_repeat(d, pages)
                        for x in d["steps"]:
                            ids.append(x["id"])
                            learned.add(x["id"])

    learned = set()
    walk(steps)
    for i in sorted(learned):
        if ids.count(i) > 1:
            raise Stop(f"duplicate step id: {i}")


def check_repeat(d, pages=None):
    """pages: the flow's page schemas (Runner); without them only the item's form is checked."""
    item = d.get("item")
    if not (isinstance(item, str) and re.fullmatch(r"[^.]+\.[^.]+", item)) or item.startswith(("current_item.", "current_page.")):
        raise Stop("learned steps: a repeat's item must be page.element")
    if pages is not None and item.split(".")[1] not in pages.get(item.split(".")[0], {}).get("elements", {}):
        raise Stop(f"learned steps: repeat item {item} is not an element of its page")
    m = d.get("max")
    if type(m) is not int or not 1 <= m <= 100:
        raise Stop("learned steps: repeat max must be 1 to 100")
    if not isinstance(d.get("steps"), list) or not d["steps"]:
        raise Stop("learned steps: repeat has no steps")
    for x in d["steps"]:
        if not isinstance(x, dict) or not x.get("id"):
            raise Stop("learned steps: a step without an id")
        if x.get("action") == "repeat":
            raise Stop("learned steps: a repeat cannot hold a repeat")
        if x.get("action") not in LEARNED_ACTIONS:
            raise Stop(f"learned steps: {x.get('action')} not allowed")
    if d["steps"][0].get("action") != "click" or d["steps"][0].get("target") != d.get("item"):
        raise Stop("learned steps: a repeat's first step must click its item")


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


def _shown(region, n):
    """Text shown beside a combo's input (its pick or placeholder), not counting an open list's options."""
    parent = next((p for p in region.walk() if any(c is n for c in p.children)), n)
    in_list = {id(x) for l in parent.walk() if l.role == "list" for x in l.walk()}
    return [d.value or d.name for d in parent.walk() if d.role == "text" and id(d) not in in_list]


def _shows_tail(value, texts):
    """The field shows value's trailing whole words (Greenhouse Country: "India +91" shows "+" "91")."""
    words = value.split()
    return bool({" ".join(words[i:]) for i in range(len(words))} & {"".join(texts), " ".join(texts)} - {""})


def _same_phone(value, got):
    """A phone number the page reformatted as typed: same digits, other spacing or punctuation."""
    digits = re.sub(r"\D", "", value)
    return bool(re.fullmatch(r"\+?[\d\s().-]{7,}", value)) and digits == re.sub(r"\D", "", got)


def _option(group, value):
    return next((n for n in group.walk() if n.role == "radio" and n.name == value), None)


def _lesson_line(e):
    """One live line for the panel: the element's label and what was done, never the value (a fill: its length)."""
    label = (e.get("label") or "a field")[:80]
    if e["kind"] == "fill":
        return f"{label} \u2190 hidden" if e.get("secure") else f"{label} \u2190 {len(e.get('value') or '')} chars"
    return {"click": f"clicked {label}", "tick": f"ticked {label}", "choose": f"chose an option in {label}",
            "attach": f"attached a file to {label}"}.get(e["kind"], f"{e['kind']} {label}")


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
        self.file_destinations = list(self.flow.get("destinations", []))   # before a typed site joins: terms-exempt
        self.pages = {}
        for pid in sorted(pages_used(self.flow)):
            self.pages[pid] = yaml.safe_load(raw[self.pages_dir / f"{pid}.yaml"])["page"]
        check_learned(self.flow["steps"], self.pages)
        self.ctx = {}

    def _audit(self, kind, **f):
        """One signed entry; console shows only kind, step and decision (no content)."""
        if self.ctx.get("task"):   # JobLens: which job's task this line belongs to
            f.setdefault("item", self.ctx["task"])
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
    def gate(self, action, risk, target=None, destination=NO_DEST, question=None, keep=True, granted=False):
        """keep=False: a first-contact approval holds for this call only, never remembered (teach)."""
        if runstate.stopped(self.home):   # row 28: backs up the guard's SIGTERM
            raise Stop("emergency stop")
        now = self.approvals.snapshot()["flows"].get(self.flow["id"])
        if now is None or now not in (self.digest, getattr(self, "superseded", None)):   # revoked since approve_flow
            raise Stop("revoked")
        if destination is not NO_DEST and not destination:   # blank/None URL: fail closed
            self._audit("request", action=action, risk=risk, target=target, decision="deny",
                        approver="policy", channel=None, reason="no url")
            raise Stop(f"denied {action}: no url")
        if destination is NO_DEST:
            destination = None
        dest = url_for_audit(destination) if destination else None
        verdict = decide({"action": action, "risk": risk, "destination": destination, "granted": granted}, self.flow, self.approvals)
        asked, how, remember = verdict == "ask", None, False
        if asked:
            q = f"Flow '{self.flow['id']}' wants to {action}"
            q += f" and reach {origin(destination)} for the first time." if destination else "."
            ok, how = self.ask(question or q + " Approve?", f"{self.flow['id']}: {action} {origin(destination) if destination else ''}".strip())
            verdict, remember = ("allow", bool(destination)) if ok else ("deny", False)
        self._audit("request", action=action, risk=risk, target=target, destination=dest, decision=verdict,
                    approver="admin" if asked else "policy", channel="touch_id" if asked else None, auth=how,
                    shown=self.shown if asked else None)
        if remember and keep:   # only once the approval is on record
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
        try:
            url = self.d.current_url(self.app) or ""
        except Exception:
            url = ""
        host = urlsplit(url).hostname or ""
        if host and origin(url) not in {origin(d) for d in self.flow.get("destinations", [])}:
            raise Stop(f"Chrome went to {host[:100]}, a site this flow does not know")
        raise Stop("cannot read the page: a Chrome prompt (location, notifications) may be covering it")

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
        return self.element(ref, self.page_root(ref.split(".")[0]))

    def page_root(self, page_id):
        """A fresh snapshot, only once it is identified as page_id."""
        on = self.ctx.get("learned_on")
        if on and on[0] == page_id and self.d.current_url(self.app) == on[1]:
            # a taught pop-up hides the page's anchors: within its own case, the same URL and title is the same page
            root = self.snapshot()
            if root is not None and re.search(self.pages[page_id]["identification"].get("title_matches", ""), root.name):
                self._audit("verify", outcome=page_id)
                return root
        page, root = self.wait_for_page([page_id], 10)
        if not page:
            raise Stop(f"not on {page_id}")
        return root

    def items(self, ref):
        """(root, page, ref's spec, the list items holding ref's element) on a fresh, identified snapshot."""
        page_id, el_id = ref.split(".")
        page, root = self.pages[page_id], self.page_root(page_id)
        spec = page["elements"][el_id]
        return root, page, spec, item_candidates(root, spec, page)

    def round_element(self, ref, label):
        """The round's click target: ref's element inside the first list item (never the taught index)."""
        _, page, spec, cands = self.items(ref)
        node = item_target(cands[0], spec, page) if cands else None
        if node is None or item_label(cands[0], node) != label:
            raise Stop("the list changed during the round")
        return node, spec

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
            for k in self.flow.get("destination_inputs", []):   # web sandbox: the site the admin typed (Touch ID on
                try:
                    u = urlsplit(given[k])
                    port = u.port
                except ValueError:
                    raise Stop("bad destination input") from None
                if k not in decl or u.scheme != "https" or u.username or u.password or not u.hostname:
                    raise Stop("bad destination input")   # first contact asks for Touch ID, as any destination
                site = f"https://{u.hostname.lower()}" + (f":{port}" if port not in (None, 443) else "")
                self.flow["destinations"] = [*self.flow["destinations"], site]
                self.inputs = {**given, k: site + given[k][len(f"{u.scheme}://{u.netloc}"):]}   # navigate there too
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
            self._capture(str(e) if isinstance(e, Stop) else type(e).__name__)
            self._audit("stop",reason=str(e) if isinstance(e, Stop) else type(e).__name__)
            raise
        self.step = None
        self._audit("flow_end", outcome="done")

    def _capture(self, reason, root=None, extra=None):
        """Save the page as it is at the stop, for debugging. Never on a locked screen or an emergency stop,
        never before a step ran; a failed capture is audited and never replaces the original stop."""
        if self.step is None or runstate.stopped(self.home) or auth.screen_locked():
            return None
        try:
            url = self.d.current_url(self.app) or ""
        except Exception:
            url = ""
        if origin(url) not in {origin(d) for d in self.flow.get("destinations", [])}:
            self._audit("action", action="capture", outcome="not_declared")   # never read a site the flow may not reach
            return None
        try:
            name, digest = capture.save(
                self.home, self.flow["id"], self.step, reason, self.d.current_url(self.app),
                self.d.window_title(self.app), root if root is not None else self.d.web_root(self.app),
                extra if extra is not None else getattr(self.d, "last_refusal", None))
        except Exception:
            self._audit("action", action="capture", outcome="error")
            return None
        self._audit("action", action="capture", target=name, file_hash=digest, outcome="done")
        print(f"capture saved: {capture.DIR}/{name}", flush=True)
        self.last_capture = name
        return name

    def steps(self, steps):
        skip = None   # a classify_page {skip_to: <id>}: jump forward to that step of this same list, never back
        for i, s in enumerate(steps):
            if skip is not None:
                if s["id"] != skip:
                    continue
                skip = None
            if auth.screen_locked():
                raise Stop("screen_locked")
            if runstate.stopped(self.home):   # row 28: backs up the guard's SIGTERM
                raise Stop("emergency stop")
            self.step = s["id"]
            out = getattr(self, "do_" + s["action"])(s)
            if out == ("end",):   # a learned page ended this list (the job is done)
                return
            if isinstance(out, tuple) and out[0] == "skip_to":
                if not any(x["id"] == out[1] for x in steps[i + 1:]):
                    raise Stop(f"skip_to {out[1]}: no such later step")
                skip = out[1]

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
        self.pinned = True   # teach observes only this window

    def do_record_lesson(self, s):
        """Teach app: record the extension's presses (TEACH_IN, appended by the panel) into a lesson. Never launches,
        navigates or types: Chrome must already be in front, and its window is pinned."""
        from .recorder import Recorder   # recorder imports engine
        self.d.activate(self.app)   # `open -a` put this run in front: give focus back to Chrome, no input posted
        self.d.pin_window(self.d.focused_window_id(self.app))   # Stop if Chrome has no window in front
        self.pinned = True
        self.gate("teach", "read")
        lesson = self.inputs["lesson"]
        rec = Recorder(self.d, self.app, self.home, self.run_id, None if lesson == "new" else lesson)
        pos, last, check = 0, time.monotonic(), 0
        while not (rec.done or rec.cancelled):
            now = time.monotonic()
            if now >= check:
                if runstate.stopped(self.home):
                    raise Stop("emergency stop")
                if auth.screen_locked():
                    raise Stop("screen_locked")
                check = now + 0.5
            try:
                fd = os.open(self.home / TEACH_IN, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            except FileNotFoundError:
                data = b""
            else:
                with os.fdopen(fd, "rb") as f:
                    f.seek(pos)
                    data = f.read()
            data = data[:data.rfind(b"\n") + 1]   # a partial last line waits for its newline
            pos += len(data)
            for line in data.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if isinstance(ev, dict) and ev.get("run") == self.run_id:
                    rec.handle(ev)
                    last = now
            if rec.paused:
                last = now   # idle time counts only while recording
            elif now - last > TEACH_IDLE_S:
                break   # what was recorded so far is kept
            time.sleep(0.01)
        self._audit("lesson", outcome="cancelled" if rec.cancelled else "recorded", target=rec.name)

    def do_navigate(self, s):
        value = self.inputs[s["value_from"].removeprefix("input.")] if "value_from" in s else s["value"]
        self._go(value)

    def _go(self, url):
        self.gate("navigate", "navigate", destination=url)
        self._act("press", self.d.press, "focus_address_bar")
        self._act("type_text", self.d.type_text, url)
        self._act("press", self.d.press, "enter")
        time.sleep(2)

    def do_classify_page(self, s):
        cases = s["on_match"]
        candidates = [p for p in cases if p != "unknown"]
        attempts = learned = 0
        while attempts < 3:                              # bounded resumes (Rule 10)
            page, root = self.wait_for_page(candidates, s.get("timeout_seconds", 20))
            what = cases.get(page or "unknown", "stop_and_report")
            if isinstance(what, dict) and "do" in what:  # a page the admin taught: its steps, then look again or end
                learned += 1
                if learned > MAX_LEARNED:
                    raise Stop("too many learned pages in a row")
                self.gate("read_page", "read", destination=self.d.current_url(self.app))
                self.ctx["page"] = page
                self.ctx["learned_on"] = (page, self.d.current_url(self.app))
                try:
                    self.steps(what["do"])               # each step through its own gate (click: risk ceiling)
                finally:
                    self.ctx.pop("learned_on", None)
                self.step = s["id"]
                if what["then"] == "end":
                    return ("end",)
                continue
            attempts += 1
            if what == "continue":
                url = self.d.current_url(self.app)
                self.gate("read_page", "read", destination=url)      # landed origin must be declared
                self.ctx["page"] = page
                return
            if isinstance(what, dict) and "skip_to" in what:   # already further on (a job link straight to its form)
                return ("skip_to", what["skip_to"])
            if isinstance(what, dict):                   # an interstitial (a popup): click past it once, look again
                candidates.remove(page)
                self.do_click({"id": self.step, "target": f"{page}.{what['click']}"})
                continue
            if what == "stop_and_report":
                if page is None and self.run_id is not None and decide(
                        {"action": "teach", "risk": "read", "destination": None}, self.flow, self.approvals) == "allow":
                    self.teach(self.step)   # always raises Stop
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
            raise Stop(s.get("none", "no items found"))
        # remember identity, not handles: the tree is rebuilt after each navigation
        self.ctx["items"] = [self._fields(it, spec, page_id) for it in items]
        # two rows can show the same fields (same client and role): the k-th of them stays the k-th
        self.ctx["item_occ"] = [self.ctx["items"][:i].count(f) for i, f in enumerate(self.ctx["items"])]
        self.ctx["item_spec"] = (page_id, el_id)

    def _fields(self, item_node, spec, page_id):
        out = {}
        for k, fs in spec["fields"].items():
            hits = [item_node] if fs.get("self") else find_all(item_node, fs, self.pages[page_id])
            out[k] = field_value(hits[0], fs) if hits else None
        return out

    def do_for_each_item(self, s):
        """With task_title (JobLens): each item is the admin's task on the panel. A stop inside one ends only that
        task (captured, then the admin picks Next job or End); safety stops still end the run (RUN_STOPS)."""
        tasks = "task_title" in s
        if tasks:
            self.tasks = [{"n": i, "title": " \u2014 ".join(str(it.get(k) or "") for k in s["task_title"])[:200],
                           "status": "waiting"} for i, it in enumerate(self.ctx["items"], 1)]
            self._write_tasks()
        for i, item in enumerate(self.ctx["items"], 1):
            self.ctx["item"], self.ctx["n"] = item, i
            if not tasks:
                self.steps(s["steps"])
                continue
            self.ctx["task"] = i
            self._task("working")
            try:
                self.steps(s["steps"])
                self._task("done")
            except Exception as e:
                reason = str(e) if isinstance(e, Stop) else type(e).__name__
                if self._current_task()["status"] != "done":
                    self._task("stopped", reason=reason[:200])
                if not isinstance(e, Stop) or _ends_run(e):   # an engine or AX error: fail closed, end the run
                    try:   # in this job's own log too (the run's stop line carries no job number)
                        self._audit("action", action="task_stop", reason=reason, outcome="run_stopped")
                    except Exception:
                        pass
                    raise
                self._capture(reason)
                self._audit("action", action="task_stop", reason=reason, outcome="error")
                if self.card("stopped", reason) == "end":
                    raise Stop("ended by admin") from None
            finally:
                self.ctx["task"] = None

    def _current_task(self):
        n = self.ctx.get("task")
        return self.tasks[n - 1] if n and getattr(self, "tasks", None) else None

    def _task(self, status, **extra):
        t = self._current_task()
        if t is not None:
            t.update(status=status, **extra)
            self._write_tasks()

    def _write_tasks(self):
        if self.run_id is not None:   # labels and counts only, never values
            write_json(self.home, TASKS, {"run": self.run_id, "tasks": self.tasks})

    def do_hand_over(self, s):
        """JobLens: the form is filled; the admin checks it and submits in Chrome, then Next job (or End)."""
        self._task("review")
        choice = self.card("review", "")
        self._task("done")
        if choice == "end":
            raise Stop("ended by admin")

    def do_new_tab(self, s):
        """Each JobLens job in its own tab: the earlier job's form stays as the admin left it."""
        self.gate("navigate", "navigate")
        self._act("press", self.d.press, "new_tab")
        time.sleep(1)

    def do_capture_pages(self, s):
        """Web sandbox: the admin browses in Chrome; each Capture saves the page they are on (read only).
        A CLI run captures the current page once."""
        pages = []
        while True:
            choice = self.card("sandbox", f"{len(pages)} captured")
            if choice == "done":
                return
            if choice == "teach":
                try:
                    self.teach(self.step, offered=True)
                except (TeachEnded, Denied):   # the lesson ends, not the sandbox; safety stops go on
                    pass
                continue
            url = self.d.current_url(self.app)
            try:
                self.gate("read_page", "read", destination=url)
            except Denied:   # another site than the one opened: never read
                pages.append({"title": "", "url": url_for_audit(url) if url else "", "file": None,
                              "note": "another site: not captured"})
            else:
                root = self.snapshot()
                if origin(self.d.current_url(self.app) or "") != origin(url):   # moved on while it was read
                    pages.append({"title": "", "url": url_for_audit(url), "file": None,
                                  "note": "page changed while capturing: not captured"})
                    if self.run_id is not None:
                        write_json(self.home, SANDBOX, {"run": self.run_id, "pages": pages[-50:]})
                    if choice is None:
                        return
                    continue
                name = self._capture("sandbox", root, {"sandbox": True})
                draft = None
                if name and "write_draft" in self.flow["permissions"]["allow"]:   # a draft page + its Check app
                    self.gate("write_draft", "modify", target=name)
                    try:
                        draft = self._act("write_draft", studio.write_draft, self.flow_path.parent, self.pages_dir,
                                          capture.tree(root), url, self.flow["browser"], name, target=name)
                    except OSError:
                        draft = None   # audited as an error; the capture itself is kept
                pages.append({"title": root.name[:200], "url": url_for_audit(url), "file": name, "draft": draft,
                              "fields": sum(n.role in FIELD_ROLES for n in root.walk()),
                              "buttons": sum(n.role == "button" for n in root.walk()),
                              "links": sum(n.role == "link" for n in root.walk())})
            if self.run_id is not None:
                write_json(self.home, SANDBOX, {"run": self.run_id, "pages": pages[-50:]})
            if choice is None:
                return

    def _current_item_node(self, field):
        page_id, el_id = self.ctx["item_spec"]
        page, root = self.wait_for_page([page_id], 15)
        if not page:
            raise Stop(f"not back on {page_id}")
        spec = self.pages[page_id]["elements"][el_id]
        same = [it for it in find_all(root, spec, self.pages[page_id]) if self._fields(it, spec, page_id) == self.ctx["item"]]
        k = self.ctx.get("item_occ", [0] * self.ctx["n"])[self.ctx["n"] - 1]
        if k < len(same):
            fs = spec["fields"][field]
            return (same[k] if fs.get("self") else find_all(same[k], fs, self.pages[page_id])[0]), fs
        raise Stop("selected item no longer on the page")   # identity check

    def ref(self, target):
        """Audit ref for a target; `current_page.<el>` names the page the run classified."""
        return f"{self.ctx['page']}.{target.split('.', 1)[1]}" if target.startswith("current_page.") else target

    def submit_buttons(self):
        """Sorted names of the submit-risk elements any click step targets, nested steps and learned cases included."""
        names = set()

        def spec_of(t):
            page, _, el = t.partition(".")
            pages = self.pages.values() if page == "current_page" else [self.pages.get(page, {"elements": {}})]
            return [p["elements"][el] for p in pages if el in p.get("elements", {})]

        def walk(steps):
            for s in steps:
                if s.get("action") == "click":
                    for e in spec_of(s.get("target", "")):
                        if e.get("risk") == "submit":
                            names.add(e.get("name") or e.get("name_matches", "").strip("^$"))
                walk(s.get("steps", []))
                for page, v in s.get("on_match", {}).items():
                    if isinstance(v, dict) and isinstance(v.get("do"), list):
                        walk(v["do"])
                    elif isinstance(v, dict) and "click" in v:   # an interstitial's click
                        walk([{"action": "click", "target": f"{page}.{v['click']}"}])

        walk(self.flow["steps"])
        return sorted(names)

    def _press_grant(self, url, spec):
        """One Touch ID lets this version of the app press its own submit buttons."""
        names = ", ".join(self.submit_buttons()) or spec.get("name") or spec.get("name_matches", "").strip("^$")
        ok, how = self.ask(f"Let '{self.flow.get('app') or self.flow['id']}' press {names} on {origin(url)}?",
                           f"{self.flow['id']}: press {names}")
        self._audit("press_grant", flow_hash=self.digest, decision="allow" if ok else "deny",
                    approver="admin", channel="touch_id", auth=how, reason=names)
        if not ok:
            raise Stop("press grant busy" if how == "busy" else "press grant refused")
        if not self.approvals.flow_ok(self.flow["id"], self.digest):   # revoked while the prompt was up
            raise Stop("revoked")
        self.approvals.grant_presses(self.flow["id"], self.digest)

    def do_repeat(self, s):
        """A taught round on the first list item still holding s["item"], until none are left or s["max"] rounds."""
        k, label = 0, None
        try:
            while k < s["max"]:
                label = None   # set once this round has an item
                root, page, spec, cands = self.items(s["item"])
                if not cands:
                    if n := len(find_all(root, item_spec(spec), page)):   # never a silent "none left"
                        raise Stop(f"repeat: {n} {spec.get('name') or s['item']} found but none inside a row or card")
                    break
                c, label = len(cands), item_label(cands[0], item_target(cands[0], spec, page))
                self.ctx["round"] = (s["item"], label)
                try:
                    self.steps(s["steps"])   # steps[0] clicks the item (do_click finds it in the first candidate)
                finally:
                    self.ctx.pop("round", None)
                    self.step = s["id"]
                deadline = time.time() + 10   # the item leaves once the app answers: wait as page checks wait
                while len(self.items(s["item"])[3]) >= c:
                    if time.time() > deadline:
                        raise Stop(f"{label} is still on the list after its round")
                    time.sleep(1)
                k += 1
                self._audit("repeat", target=label, outcome="done")
        except Stop as e:
            self._audit("repeat", target=label, outcome="error")
            if _ends_run(e) or label is None:   # a run stop keeps the message the run checks; no round yet: as is
                raise
            raise Stop(f"repeat stopped on {label} after {k} done: {e}") from e
        self._audit("repeat", outcome="cap" if k == s["max"] else "none_left", reason=f"{k} done")

    def do_click(self, s):
        tgt = self.ref(s["target"])
        rnd = self.ctx.get("round")
        is_round = rnd is not None and tgt == rnd[0]

        def locate():
            if tgt.startswith("current_item."):
                return self._current_item_node(tgt.split(".", 1)[1])
            return self.round_element(tgt, rnd[1]) if is_round else self.page_element(tgt)

        node, spec = locate()
        if tgt.startswith("current_item."):
            ref = "{}.{}[{}].{}".format(*self.ctx["item_spec"], self.ctx["n"], tgt.split(".", 1)[1])
        else:
            ref = tgt
        if self.flow.get("try") is True:   # before the press grant and the gate: a Try never asks to press
            from .lessons import _CHANGE, _PAY   # lessons imports engine
            names = (getattr(node, "name", "") or "", spec.get("name") or "", spec.get("name_matches") or "")
            if spec["risk"] in ("submit", "payment") or any(_CHANGE.search(n) or _PAY.search(n) for n in names):
                raise Stop(TRY_STOP.format(names[0] or names[1] or ref))
        if spec["risk"] == "submit":
            url = self.d.current_url(self.app)
            fid = self.flow["id"]
            # ask only if policy would allow the press with a grant: never prompt for a press that is denied anyway
            if own(url) and not self.approvals.press_ok(fid, self.digest) and decide(
                    {"action": "click", "risk": "submit", "destination": url, "granted": True},
                    self.flow, self.approvals) != "deny":
                self._press_grant(url, spec)
            self.gate("click", "submit", target=ref, destination=url,
                      granted=self.approvals.press_ok(fid, self.digest))
        else:
            self.gate("click", spec["risk"], target=ref)
        before = self.d.current_url(self.app)
        # open_link: go to the link's own address instead of clicking it (JobLens's two-line titles defeat the
        # click-point check); same site only, so it never reaches a destination the click could not
        url = self.d.link_url(node) if s.get("open_link") else None
        if url and origin(url) != origin(before):
            url = None
        for attempt in range(2):                         # one bounded retry (Rule 10)
            if url:
                self._go(url)
            else:
                self._act("scroll_into_view", self.d.scroll_into_view, node, target=ref)
                node, spec = locate()   # positions changed after scrolling
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
        if "form_region" not in self.pages[page]["elements"]:   # a Studio draft page: the whole page is the form
            return root, root
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
        shown0 = _shown(region, node) if node is not None and f.kind == "combo" else []
        refused = False   # a refused click was captured already, with what was under the point
        ok = node is not None and ok_value(value, f.kind)
        if ok:
            self.gate("fill_field", "modify", target=label, destination=self.d.current_url(self.app))
            # the form can sit below the fold (Greenhouse: under the job description); click() checks the point
            self._act("scroll_into_view", self.d.scroll_into_view, node, target=label)
            before = set(_lists(root))
            try:
                ok = self._enter(f.kind, node, value, before, label, region)
            except Exception as e:   # only "something else under the point" is this field's problem; the rest stop
                if "not on the target element" not in str(e):
                    raise
                self._capture(str(e))
                ok, refused = False, True
            root, region = self._form()   # re-found after entry or escape: the old handle may be stale
            node = n = self._node(region, f, value)
            if not ok or n is None:
                ok = False
            elif f.kind == "radio":
                ok = n.value == "1"
            elif f.kind == "select":
                ok = value in (n.value, n.name)
            elif f.kind == "combo":   # picked only once the dropdown closed; text in a still-open list doesn't count
                shown = _shown(region, n)
                ok = not _new_lists(before, root, region) and (n.value == value or value in shown
                                                                 or _shows_tail(value, shown))
            else:
                ok = n.value == value or _same_phone(value, n.value)
        if not ok and node is not None and not refused:   # before clearing: what the page actually held
            self._capture(f"read-back mismatch: {label}", root, {"field": label, "kind": f.kind, "expected": value,
                                                                  "read_back": node.value})
        if not ok and node is not None and f.kind in ("text", "textarea", "combo") and self.d.focused_is(node):
            self._act("press", self.d.press, "select_all", target=label)
            self._act("press", self.d.press, "delete_back", target=label)
            if f.kind == "combo":   # deleting reopens the full list; left open it can cover the next field
                self._act("press", self.d.press, "escape", target=label)
        self._audit("action", action="fill_field", target=label, source=source, outcome="done" if ok else "mismatch")
        if not ok and self.fix_by_hand(f, shown0):
            self._audit("action", action="fill_field", target=label, source="admin_manual", outcome="done")
            ok = True
        if not ok:
            self.ctx["apply"]["yourself"].append(f.label)
        return ok

    def card(self, kind, label, tick=None):
        """Panel run only: show a card (applyfiles.CARDS) and wait for the admin's choice, then bring the pinned
        window back. None when there is no panel or the flow may not ask (a CLI run carries on without it)."""
        if self.run_id is None or decide({"action": "ask_admin", "risk": "read", "destination": None},
                                         self.flow, self.approvals) != "allow":
            return None
        self.gate("ask_admin", "read")
        task = self._current_task()
        cap, self.last_capture = getattr(self, "last_capture", None), None   # the page saved for this card, if any
        reply = self._ask({"card": {"kind": kind, "label": label[:300], "capture": cap if kind != "sandbox" else None,
                                    "job": task["title"] if task else "", "item": self.ctx.get("task") or 0}}, tick,
                          TEACH_IDLE_S if kind in ("lesson", "terms") else ASK_TIMEOUT_S)   # reading terms or a lesson takes time
        choice = reply.get("card")
        if choice not in CARDS[kind]:
            raise Stop("bad reply")
        self._act("raise_pinned", self.d.raise_pinned)
        return choice

    def teach(self, step_id, offered=False):
        """Studio: the admin does an unknown page in Chrome while the read-only observer records it as a lesson.
        Always ends this job with a Stop; a lesson is used only once approved, from the next run."""
        if not getattr(self, "pinned", False):
            raise Stop("teach needs the pinned browser window")
        before = self.flow["destinations"]
        try:
            self._teach(step_id, offered)
        finally:
            self.flow["destinations"] = before   # a taught site is allowed for the lesson only

    def _teach(self, step_id, offered):
        from . import lessons, observer   # lessons imports engine
        if not offered and self.card("new_page", "A page this flow does not know") != "teach":
            raise TeachEnded("unexpected page")
        url = self.d.current_url(self.app) or ""
        site = origin(url)
        declared = {origin(d) for d in self.file_destinations}
        if terms.verdict(self.home, url, declared) != "allowed" and (
                self.card("terms", site) != "checked" or terms.verdict(self.home, url, declared) != "allowed"):
            raise TeachEnded("site terms do not allow a personal agent")
        before = self.flow["destinations"]
        if site not in {origin(d) for d in before}:   # in memory, this run only; Touch ID each time, never remembered:
            self.flow["destinations"] = [*before, site]   # the lesson's own approval is where a site joins the flow
        self.gate("read_page", "read", destination=url, keep=False)   # refused: never read (or captured)
        allowed = {origin(d) for d in self.flow["destinations"]}
        tab = self.d.teach_tab(self.app)
        obs = observer.Observer(self.d, self.app, self.d.same)
        lines, last = [], [time.monotonic()]

        class Left(Exception):
            pass

        def snap():
            root = self.d.web_root(self.app)
            url = self.d.current_url(self.app) or ""   # after the read: a navigation in between is never stored
            if origin(url) not in allowed:
                raise Left(url)
            return root

        def tick():
            left = []
            try:
                sample = self.d.observe_sample(self.app)
                # never snapshot a site not approved for this lesson: end it as if the tab closed. Other tabs are
                # not the lesson (the observer ignores them). shortcut: fails closed on any other site; ask terms +
                # Touch ID there when lessons span sites
                if sample.get("tab") and self.d.same(sample.get("web"), tab) and \
                        origin(sample.get("url") or "") not in allowed:
                    raise Left(sample.get("url") or "")
                evs = obs.feed(sample, snap)
            except Left as e:
                left = [f"left {(urlsplit(str(e)).hostname or 'the site')[:100]}: lesson ended"]
                evs = obs.feed({"tab": False}, snap)
            except Exception:   # the window closed mid-look: the teach tab is gone
                evs = obs.feed({"tab": False}, snap)
            if evs or left:
                lines.extend([*(_lesson_line(e) for e in evs), *left])
                del lines[:-LIVE_LINES]
                write_json(self.home, LESSON_LIVE, {"run": self.run_id, "lines": lines})
                last[0] = time.monotonic()
            if obs.ended or time.monotonic() - last[0] > TEACH_IDLE_S:
                return {"run": self.run_id, "card": "done"}   # what was recorded so far is kept
            return None
        try:
            choice = self.card("teaching", "Do this page in Chrome", tick)
        finally:
            remove(self.home, LESSON_LIVE)
        if choice != "done" or not any(p["events"] for p in obs.pages):
            raise TeachEnded("lesson cancelled")
        name = lessons.save(self.home, self.flow["id"], self.digest, step_id, obs.pages)
        self._audit("lesson", outcome="recorded", target=name)
        if self.card("lesson", name) == "approved":
            # the panel approved the flow as the lesson rewrote it: this run keeps the flow it started with
            self.superseded = self.approvals.snapshot()["flows"].get(self.flow["id"])
            raise TeachEnded("page learned: it is used from the next run")
        raise TeachEnded("lesson discarded")

    def fix_by_hand(self, f, shown0):
        """Panel run only: the admin fills the failed field in Chrome, then Continue (or Skip). Re-read after."""
        self._task("needs_you")
        choice = self.card("fix", f.label)
        self._task("working")
        if choice in (None, "skip"):
            return False
        region = self._form()[1]
        now = next((x for x in read_form(region) if x.key == f.key), None)
        n = self._node(region, f, "")
        # a react-select keeps its pick in text beside an empty input: filled once that text changed
        return now is not None and (now.filled or f.kind == "combo" and n is not None and
                                    _shown(region, n) not in ([], shown0))

    def _enter(self, kind, node, value, before, label, region):
        if kind in ("text", "textarea"):
            self._act("click", self.d.click, node, target=label)
            if not self.d.focused_is(node):
                return False
            self._act("type_into", self.d.type_into, node, value, target=label)
        elif kind == "combo":
            from .desktop.macos import InputRefused   # lazy: pyobjc only on the real desktop
            try:
                self._act("click", self.d.click, node, target=label)
            except InputRefused as e:   # an empty react-select input is 4 px wide under its placeholder: click its box
                box = next((p for p in region.walk() if any(c is node for c in p.children)), None)
                if box is None or "not on the target element" not in str(e):
                    raise
                self._act("click", self.d.click, box, target=label)
            self._act("type_into", self.d.type_into, node, value, target=label)
            new = _new_lists(before, *self._form())
            cands = list({id(c): c for l in new for c in _named(l, value)}.values())
            if len(cands) != 1:   # the open list shows which options there were, before Escape closes it
                self._capture(f"{len(cands)} options named as the answer: {label}", None,
                              {"field": label, "expected": value})
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

    def _new_apply(self):
        try:
            bank = load_bank(self.home / BANK, user_home())
        except BankError as e:
            raise Stop(f"answer bank: {e}") from None
        self.ctx["apply"] = {"bank": bank, "filled": 0, "total": 0, "yourself": [], "check": [], "pending": []}
        return self.ctx["apply"]

    def do_fill_form(self, s):
        a = self._new_apply()
        done = set()
        for _ in range(FORM_PASSES):   # a fill can reveal conditional fields
            fields = read_form(self._form()[1])
            new = [f for f in fields if f.key not in done]
            if not new:
                break
            for f in new:
                done.add(f.key)
                a["total"] += 1
                hit = answer_for(f, a["bank"], fields)
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
        a, ref = self.ctx.get("apply") or self._new_apply(), self.ref(s["target"])   # a learned attach: no fill before
        a["yourself"].append("Resume/CV")   # until attached: a stop from here on leaves it on the result card
        self.write_result()
        p = cv_path(a["bank"], user_home())
        if p is not None:
            _, spec = self.page_element(ref)
            if spec["risk"] in ("submit", "payment"):
                raise Stop(f"{ref}: attach on a {spec['risk']} element denied")
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
        reply = self._ask({"fields": [
            {"key": f.key, "label": f.label, "kind": f.kind, "options": offered[f.key]} for f in pend]})
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

    def _ask(self, body, tick=None, timeout=ASK_TIMEOUT_S):
        """Write ask.json for the panel and wait for this run's reply.json (emergency stop, lock and timeout end it).
        tick (the teaching card): called every 0.2 s, its reply dict ends the wait; it keeps its own idle timeout."""
        try:
            remove(self.home, REPLY)   # a late reply to an earlier ask in this run must not answer this one
            self.asks = getattr(self, "asks", 0) + 1   # each ask unique: a stale reply never answers the next one
            write_json(self.home, ASK, {"run": self.run_id, "seq": self.asks, **body})
            deadline = time.monotonic() + timeout
            while True:
                reply = read_json(self.home, REPLY)   # None mid-write or garbled: not yet
                if reply and reply.get("run") == self.run_id:
                    break
                if runstate.stopped(self.home):
                    raise Stop("emergency stop")
                if auth.screen_locked():
                    raise Stop("screen_locked")
                if tick is not None:
                    reply = tick()
                    if reply is not None:
                        break
                elif time.monotonic() > deadline:
                    raise Stop("no answer from admin")
                time.sleep(0.2 if tick is not None else 1)
        finally:
            remove(self.home, ASK, REPLY)
        return reply

    def write_result(self):
        """Counts and labels only, never values."""
        a = self.ctx["apply"]
        if self.run_id is not None:
            write_json(self.home, RESULT, {"run": self.run_id, "filled": a["filled"], "total": a["total"],
                                           "yourself": a["yourself"], "check": a["check"]})
        t = self._current_task()
        if t is not None:   # JobLens: the counts on this job's task
            t.update(filled=a["filled"], total=a["total"], yourself=list(a["yourself"]), check=list(a["check"]))
            self._write_tasks()
        print(f"apply: filled {a['filled']} of {a['total']}", flush=True)
