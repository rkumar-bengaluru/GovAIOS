"""Studio observer spike: can we see the admin's clicks, typing and tab close on Chrome with only Accessibility?

Run (admin, from Terminal, which has Accessibility):
  .venv/bin/python spikes/plan5/observe_spike.py
Bring Chrome to the front; its focused window's AXWebArea becomes the "teach tab". Then, within 60 s: click a
link, a button, a dropdown option, type in a field, click elsewhere, then close the tab. Ctrl-C quits.
Prints role, name and value LENGTH only, never values. No GUI is driven; it only reads.
"""
import sys
import time

import Quartz as Q
from ApplicationServices import (
    AXUIElementCopyAttributeValue, AXUIElementCopyElementAtPosition, AXUIElementCreateApplication,
    AXUIElementCreateSystemWide, AXUIElementGetPid, AXUIElementSetAttributeValue,
)
from CoreFoundation import CFEqual

SECONDS, TICK = 60, 0.03


def attr(el, name):
    err, v = AXUIElementCopyAttributeValue(el, name, None)
    return v if err == 0 else None


def describe(el):
    if el is None:
        return "role=None"
    name = attr(el, "AXTitle") or attr(el, "AXDescription") or ""
    v = attr(el, "AXValue")
    return f"role={attr(el, 'AXRole')} name={str(name)[:40]!r} value_len={len(str(v)) if v is not None else '-'}"


def front_chrome_pid():
    err, app = AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), "AXFocusedApplication", None)
    if err != 0 or app is None:
        return None
    err, pid = AXUIElementGetPid(app, None)
    return pid if err == 0 and attr(app, "AXTitle") == "Google Chrome" else None


def find(el, role, depth=30):
    if el is None or depth == 0:
        return None
    if attr(el, "AXRole") == role:
        return el
    for c in attr(el, "AXChildren") or []:
        hit = find(c, role, depth - 1)
        if hit is not None:
            return hit
    return None


def main():
    print("Waiting for Chrome to be frontmost (Ctrl-C to quit)...")
    while (pid := front_chrome_pid()) is None:
        time.sleep(0.3)
    app = AXUIElementCreateApplication(pid)
    AXUIElementSetAttributeValue(app, "AXManualAccessibility", True)   # Chrome builds web tree on demand
    time.sleep(0.5)
    tab = find(attr(app, "AXFocusedWindow"), "AXWebArea")
    if tab is None:
        print("no AXWebArea in the focused window; abort")
        return 1
    print(f"teach tab taken (pid {pid}). For {SECONDS} s: click a link, a button, a dropdown option; type in a field;")
    print("click elsewhere; then close the tab. Lines: CLICK x,y -> element | FOCUS-LEAVE -> element | tab gone")
    was_down, focused, gone = False, None, False
    end = time.time() + SECONDS
    while time.time() < end:
        down = Q.CGEventSourceButtonState(Q.kCGEventSourceStateCombinedSessionState, Q.kCGMouseButtonLeft)
        if down and not was_down:
            p = Q.CGEventGetLocation(Q.CGEventCreate(None))
            err, hit = AXUIElementCopyElementAtPosition(app, p.x, p.y, None)
            print(f"CLICK {p.x:.0f},{p.y:.0f} -> {describe(hit) if err == 0 else f'ax error {err}'}")
        was_down = down
        cur = attr(app, "AXFocusedUIElement")
        if focused is not None and (cur is None or not CFEqual(cur, focused)):
            print(f"FOCUS-LEAVE -> {describe(focused)}")   # value read now: length of what was typed
        if cur is None or focused is None or not CFEqual(cur, focused):
            focused = cur
        if not gone and attr(tab, "AXRole") is None:
            gone = True
            print("tab gone")
        time.sleep(TICK)
    print("done")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
