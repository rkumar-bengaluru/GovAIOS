"""Teach-extension matching spike (plan 1 of 2): with the GOV-AIOS side panel open, do the admin's clicks on JobLens
become steps a run finds again after a fresh load?

Run (admin, from Terminal, which has Accessibility and Input Monitoring), from the repo root:
  .venv/bin/python spikes/plan6/match_spike.py
and follow the prompts. Pass 1: Discover -> Shortlisted -> Review (first profile). Approve & promote is NEVER pressed:
its spec is read from a snapshot. Pass 2: reload each page, the script re-finds each recorded step.
It only reads: no click, key or text is posted. Prints roles, names and specs, never typed values.
Spike only: reaches into private helpers (macos._attr/_s, studio._walk, desk._target). No timeout.
"""
import select
import sys

import Quartz as Q
from ApplicationServices import AXIsProcessTrusted

from govaios import capture, studio
from govaios.desktop.macos import MacDesktop, _attr, _s
from govaios.engine import find_all
from govaios.observer import Observer
from govaios.policy import origin

SITE, APP, TICK = "http://localhost:8100", "chrome", 0.03
WANT = ("Discover", "Shortlisted", "Review")
APPROVE = "Approve & promote"
CONTAINERS = ("row", "article", "group", "region")
fails = []


def fail(what):
    print(f"  FAIL {what}")
    fails.append(what)


def enter(prompt):
    print(f"\n{prompt}\n  (click Terminal, then press Enter)")
    sys.stdin.readline()


def web_areas(desk):
    out = []

    def walk(el, depth):
        if el is None or depth == 0:
            return
        if _s(_attr(el, "AXRole")) == "AXWebArea":
            u = _attr(el, "AXURL")
            out.append((el, _s(_attr(el, "AXTitle")), str(u.absoluteString()) if u is not None else ""))
            return   # not into the page's own frames
        for c in _attr(el, "AXChildren") or []:
            walk(c, depth - 1)
    walk(desk._window, 30)
    return out


def check_root(desk, root, where):
    """Review Focus 1: web_root read the JobLens page, not the side panel."""
    areas = web_areas(desk)
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
    return studio.element_spec(t, ds[next(i for i, m in enumerate(root.walk()) if m is node)])


def main():
    if not AXIsProcessTrusted():
        print("Terminal needs Accessibility: System Settings -> Privacy & Security -> Accessibility")
        return 1
    print(f"Accessibility: yes; Input Monitoring: {'yes' if Q.CGPreflightListenEventAccess() else 'no'}")
    if not sys.stdin.isatty():
        print("Run this from Terminal: it needs Enter presses.")
        return 0
    desk = MacDesktop()
    desk._target = APP
    enter(f"Open {SITE}/ in Chrome Profile 2 with the GOV-AIOS Teach side panel open and 4 profiles in Shortlisted.\n"
          "After Enter, click the JobLens page within 60 s.")
    win = None
    for _ in range(12):   # focused_window_id waits ~5 s each try
        try:
            win = desk.focused_window_id(APP)
            break
        except Exception:
            pass
    if win is None:
        print("Chrome never came to the front. Run again.")
        return 1
    desk.pin_window(win)
    tab = desk.teach_tab(APP)
    print(f"Pinned Chrome's window; teach tab via {desk.teach_tab_source}.")

    # --- pass 1: record ---
    obs = Observer(desk, APP, desk.same)

    class Left(Exception):
        pass

    def snap():
        root = desk.web_root(APP)
        if origin(desk.current_url(APP) or "") != SITE:
            raise Left()
        return root
    print("\nPass 1: in Chrome click Discover, Shortlisted, then Review on the FIRST profile.\n"
          "Do NOT press Approve & promote. When the Review page has loaded, click Terminal and press Enter.")
    try:
        while not select.select([sys.stdin], [], [], TICK)[0]:
            sample = desk.observe_sample(APP)
            if sample.get("tab") and desk.same(sample.get("web"), tab) and origin(sample.get("url") or "") != SITE:
                raise Left()
            for ev in obs.feed(sample, snap):
                print(f"  event {ev['kind']}: role={ev['spec'] and ev['spec'].get('role')} label={ev['label']!r} "
                      f"spec={ev['spec']} submit={ev['submit']}")
        sys.stdin.readline()
    except Left:
        print("  the tab left localhost:8100: pass 1 ended")
    except KeyboardInterrupt:
        print("  stopped")
    print("\nPages seen:")
    for p in obs.pages:
        print(f"  {p['url']}  title={p['title']!r}  events={len(p['events'])}")
    clicks = [e for p in obs.pages for e in p["events"] if e["kind"] == "click"]
    checks = []
    for label in WANT:
        ev = next((e for e in clicks if e["label"] == label), None)
        if ev is None or not ev["spec"]:
            fail(f"no click recorded for {label!r}" if ev is None else f"{label!r} has no unique spec")
        else:
            checks.append((label, ev["spec"]))
    print("\nThe Review page now (Approve & promote is read, not pressed):")
    root = desk.web_root(APP)
    check_root(desk, root, "pass 1 Review page")
    btns = [n for n in root.walk() if n.role == "button" and n.name == APPROVE] if root else []
    spec = spec_of(root, btns[0]) if len(btns) == 1 else None
    if spec:
        print(f"  {APPROVE!r} spec={spec}")
        checks.append((APPROVE, spec))
    else:
        fail(f"{APPROVE!r}: {len(btns)} buttons, or no unique spec")

    # --- pass 2: find again, by walk order ---
    for label, spec in checks:
        page = "the first profile's Review page (same profile as pass 1)" if label == APPROVE \
            else f"the page where you clicked {label!r}"
        enter(f"Pass 2: in Chrome open {page}, press Cmd-R and wait for it to load.")
        root = desk.web_root(APP)
        check_root(desk, root, f"pass 2 {label}")
        hits = find_all(root, spec, {"elements": {}}) if root else []
        if len(hits) == 1 and hits[0].name == label:
            print(f"  PASS {label!r} found again")
        else:
            fail(f"{label!r} found {len(hits)} times" + (f" ({hits[0].name!r})" if len(hits) == 1 else ""))
        if label == "Review" and root is not None:
            anchor(root, spec, hits)
    print("\nSPIKE PASS" if not fails else "\nSPIKE FAIL: " + ", ".join(fails))
    return 0


def anchor(root, spec, hits):
    """Review Focus 3: each card's Review is told apart by its card, and the recorded step hits the first card."""
    reviews = [n for n in root.walk() if n.role == spec["role"] and n.name == "Review"]
    up = {id(c): p for p in root.walk() for c in p.children}

    def card(n):
        p = up.get(id(n))
        while p is not None and p.role not in CONTAINERS:
            p = up.get(id(p))
        return p
    cards = [card(r) for r in reviews]
    print(f"  anchor: {len(reviews)} Review buttons (expected 4); containers: {[c.role if c else None for c in cards]}")
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
