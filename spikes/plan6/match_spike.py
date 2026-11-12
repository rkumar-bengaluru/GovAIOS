"""Teach-extension matching spike, option A (plan 1 of 2): the extension reports each mouse-down from the page; GOV-AIOS
reads the element under the pointer at once, before the page reacts. Do those become steps a run finds again?

Run (admin, from Terminal, which has Accessibility), from the repo root:
  .venv/bin/python spikes/plan6/match_spike.py
with spikes/plan6/extension loaded (reload it in chrome://extensions after an update, then reload the JobLens tab).
Pass 1: Discover -> Shortlisted -> Review (first profile), with NORMAL quick clicks. Approve & promote is NEVER pressed:
its spec is read from a snapshot. Pass 2: reload each page, the script re-finds each recorded step.
It only reads: no click, key or text is posted. Prints roles, names, specs and timings, never field values.
Spike only: reaches into private helpers (macos._attr/_s, desk._hit/_ax_app/_window/_target, studio._walk). No timeout.
"""
import json
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import Quartz as Q
from ApplicationServices import AXIsProcessTrusted

from govaios import capture, studio
from govaios.desktop.macos import MacDesktop, _attr, _s
from govaios.engine import find_all
from govaios.policy import origin

SITE, APP, PORT = "http://localhost:8100", "chrome", 8799
WANT = ("Discover", "Shortlisted", "Review")
APPROVE = "Approve & promote"
CLICKABLE = ("link", "button", "tab", "radio")
CONTAINERS = ("row", "article", "group", "region")
COUNT = re.compile(r"^(.*\S) \(\d+\)$")   # "Shortlisted (4)": the count changes, so it is never part of the step
fails, downs, ups, lock = [], [], [], threading.Lock()
desk = None


def fail(what):
    print(f"  FAIL {what}")
    fails.append(what)


def enter(prompt):
    print(f"\n{prompt}\n  (click Terminal, then press Enter)")
    sys.stdin.readline()


def web_areas():
    out = []

    def walk(el, depth):
        if el is None or depth == 0:
            return
        if _s(_attr(el, "AXRole")) == "AXWebArea":
            u = _attr(el, "AXURL")
            out.append((el, _s(_attr(el, "AXTitle")), str(u.absoluteString()) if u is not None else ""))
            return
        for c in _attr(el, "AXChildren") or []:
            walk(c, depth - 1)
    walk(desk._window, 30)
    return out


def check_root(root, where):
    areas = web_areas()
    for _, t, u in areas:
        print(f"  web area: title={t!r} url={u}")
    if root is None:
        return fail(f"{where}: no page snapshot")
    picked = next(((t, u) for el, t, u in areas if desk.same(el, root.handle)), None)
    if picked is None:
        return fail(f"{where}: picked root is not a web area of the window")
    t, u = picked
    if u.startswith("chrome-extension://") or "GOV-AIOS Teach" in t:
        return fail(f"{where}: side panel read")
    if origin(u) != SITE or "JobLens" not in t:
        return fail(f"{where}: picked {t!r} at {u}")
    print(f"  ok: picked the JobLens page ({t!r})")


def spec_of(root, node):
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


def on_down(ev, recv):
    """At once, in the server thread: the element under the pointer, then a snapshot, before the page reacts."""
    rec = {"dom": ev, "recv": recv}
    try:
        hit = desk._hit((ev["x"], ev["y"]))
        rec["hit"] = time.time()
        root = desk.web_root(APP) if hit is not None else None
        rec["snap"] = time.time()
        n = next((m for m in root.walk() if desk.same(m.handle, hit)), None) if root else None
        up = {id(c): p for p in root.walk() for c in p.children} if root else {}
        while n is not None and n.role not in CLICKABLE:
            n = up.get(id(n))
        if n is not None:
            rec["role"], rec["name"], rec["spec"] = n.role, n.name, spec_of(root, n)
    except Exception as e:   # spike: show it, keep going
        rec["error"] = f"{type(e).__name__}: {e}"[:200]
    with lock:
        downs.append(rec)
    ms = lambda k: f"{(rec[k] - ev['t'] / 1000) * 1000:.0f}ms" if k in rec else "-"
    print(f"  down: page says {ev['tag']}/{ev['role'] or '-'} {ev['name']!r}; GOV-AIOS read "
          f"{rec.get('role')} {rec.get('name')!r} spec={rec.get('spec')} (arrived {ms('recv')}, hit {ms('hit')}, "
          f"snapshot {ms('snap')} after the press){' ' + rec['error'] if 'error' in rec else ''}")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        recv = time.time()
        try:
            ev = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)))
        except ValueError:
            ev = {}
        self.send_response(204)
        self.end_headers()
        if ev.get("kind") == "down" and origin(desk.current_url(APP) or "") == SITE:
            on_down(ev, recv)
        elif ev.get("kind") == "up":
            with lock:
                ups.append(ev["t"] / 1000)

    def log_message(self, *a):
        pass


def main():
    global desk
    if not AXIsProcessTrusted():
        print("Terminal needs Accessibility: System Settings -> Privacy & Security -> Accessibility")
        return 1
    print(f"Accessibility: yes; Input Monitoring: {'yes' if Q.CGPreflightListenEventAccess() else 'no'} (not needed)")
    if not sys.stdin.isatty():
        print("Run this from Terminal: it needs Enter presses.")
        return 0
    desk = MacDesktop()
    desk._target = APP
    enter(f"In chrome://extensions press the reload icon on 'GOV-AIOS Teach (spike)', then open {SITE}/ in Chrome\n"
          "Profile 2, press Cmd-R there, and open the side panel. After Enter, click the JobLens page within 60 s.")
    print("Now click the JobLens page in Chrome (waiting up to 60 s)...")
    win = None
    for _ in range(200):   # AXFocusedApplication fails from Terminal's python: the window list says who is in front
        wins = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
                                            Q.kCGNullWindowID) or []
        top = next((w for w in wins if w.get("kCGWindowLayer") == 0), None)
        if top and top.get("kCGWindowOwnerName") == "Google Chrome":
            win = _attr(desk._ax_app(APP), "AXFocusedWindow")
            if win is not None:
                break
        time.sleep(0.3)
    if win is None:
        print("Chrome never came to the front. Run again.")
        return 1
    desk._window = win
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"Pinned Chrome's window; listening for the extension on 127.0.0.1:{PORT}.")

    # --- pass 1: record ---
    enter("Pass 1: in Chrome click Discover, Shortlisted, then Review on the FIRST profile, with NORMAL quick clicks.\n"
          "Each click should print a 'down:' line here. Do NOT press Approve & promote.\n"
          "Leave the Review pop-up open when you come back here.")
    with lock:
        recs = list(downs)
        ups_now = sorted(ups)
    if not recs:
        fail("no mouse-down reached the script (reload the extension and the JobLens tab)")
    checks = []
    for label in WANT:
        rec = next((r for r in recs if r["dom"]["name"].startswith(label)), None)
        if rec is None:
            fail(f"no mouse-down on {label!r}")
            continue
        up = next((u for u in ups_now if u >= rec["dom"]["t"] / 1000), None)
        before = "snap" in rec and up is not None and rec["snap"] <= up
        print(f"  {label!r}: page name {rec['dom']['name']!r}, GOV-AIOS name {rec.get('name')!r}, "
              f"snapshot {'BEFORE' if before else 'AFTER (or no release seen)'} the release")
        if rec.get("name") != rec["dom"]["name"]:
            fail(f"{label!r}: GOV-AIOS read {rec.get('name')!r}, the page said {rec['dom']['name']!r}")
        elif not rec.get("spec"):
            fail(f"{label!r}: no unique spec")
        else:
            checks.append((label, rec["spec"]))
    print("\nThe Review pop-up now (Approve & promote is read, not pressed):")
    root = desk.web_root(APP)
    check_root(root, "pass 1 Review pop-up")
    btns = [n for n in root.walk() if n.role == "button" and n.name == APPROVE] if root else []
    spec = spec_of(root, btns[0]) if len(btns) == 1 else None
    if spec:
        print(f"  {APPROVE!r} spec={spec}")
        checks.append((APPROVE, spec))
    else:
        fail(f"{APPROVE!r}: {len(btns)} buttons, or no unique spec")

    # --- pass 2: find again, by walk order ---
    for label, spec in checks:
        if label == APPROVE:
            enter("Pass 2: in Chrome press Cmd-R, open Shortlisted, then click Review on the first profile (the same one)\n"
                  "and leave the pop-up open.")
        elif label == "Review":
            enter("Pass 2: in Chrome press Cmd-R (the pop-up closes), then click Shortlisted. Do not click Review.")
        else:
            enter(f"Pass 2: in Chrome open the page where you clicked {label!r}, press Cmd-R and wait for it to load.")
        root = desk.web_root(APP)
        check_root(root, f"pass 2 {label}")
        hits = find_all(root, spec, {"elements": {}}) if root else []
        if len(hits) == 1 and (spec.get("name") in (None, hits[0].name)):
            print(f"  PASS {label!r} found again ({hits[0].name!r})")
        else:
            fail(f"{label!r} found {len(hits)} times")
        if label == "Review" and root is not None:
            anchor(root, spec, hits)
    srv.shutdown()
    print("\nSPIKE PASS" if not fails else "\nSPIKE FAIL: " + ", ".join(fails))
    return 0


def anchor(root, spec, hits):
    """Each card's Review is told apart by its card, and the recorded step hits the first card."""
    reviews = [n for n in root.walk() if n.role == spec["role"] and n.name == "Review"]
    up = {id(c): p for p in root.walk() for c in p.children}

    def card(n):
        p = up.get(id(n))
        while p is not None and p.role not in CONTAINERS:
            p = up.get(id(p))
        return p
    cards = [card(r) for r in reviews]
    print(f"  anchor: {len(reviews)} Review buttons; containers: {[c.role if c else None for c in cards]}")
    inside = lambda c, x: any(n is x for n in c.walk())
    if not reviews or not all(cards) or len({id(c) for c in cards}) != len(cards):
        return fail("anchor: Reviews do not each have their own container")
    if sum(1 for r in reviews if inside(cards[0], r)) != 1:
        return fail("anchor: the first container holds more than one Review")
    if len(hits) != 1 or not inside(cards[0], hits[0]):
        return fail("anchor: the recorded Review is not the first card's")
    print("  PASS anchor")


if __name__ == "__main__":
    sys.exit(main())
