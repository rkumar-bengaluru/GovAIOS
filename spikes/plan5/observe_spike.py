"""Studio observer spike: can we see the admin's clicks, typing and tab close on Chrome with only Accessibility?

Run (admin, from Terminal, which has Accessibility):
  .venv/bin/python spikes/plan5/observe_spike.py
Bring Chrome to the front; its focused window's AXWebArea becomes the "teach tab". Then, within 60 s: click a
link, a button, a dropdown option, type in a field, click elsewhere, then close the tab. Ctrl-C quits.
Only "Google Chrome" is matched (not Beta/Canary). Prints role, name and value LENGTH only, never values. No GUI is driven; it only reads.
"""
import sys
import time

import Quartz as Q
from ApplicationServices import (
    AXIsProcessTrusted, AXUIElementCopyAttributeValue, AXUIElementCopyElementAtPosition, AXUIElementCreateApplication,
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


_seen = [None]


def front_chrome_pid():
    # the top normal-layer on-screen window's owner (NSWorkspace.frontmostApplication is cached without a run loop)
    wins = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
                                        Q.kCGNullWindowID) or []
    top = next((w for w in wins if w.get("kCGWindowLayer") == 0), None)
    err, app = AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), "AXFocusedApplication", None)
    now = (top.get("kCGWindowOwnerName") if top else None, err,
           attr(app, "AXTitle") if err == 0 and app is not None else None)
    if now != _seen[0]:   # spike diagnostics: what is front, by the window list and by AX
        print(f"front app: {now[0]!r}; AX focused app err={now[1]} title={now[2]!r}")
        _seen[0] = now
    return int(top["kCGWindowOwnerPID"]) if top and now[0] == "Google Chrome" else None


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
    if not AXIsProcessTrusted():
        print("Terminal needs Accessibility: System Settings -> Privacy & Security -> Accessibility")
        return 1
    im = bool(Q.CGPreflightListenEventAccess())
    print(f"Accessibility granted: yes; Input Monitoring granted: {'yes' if im else 'no'}")
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
    print("click elsewhere; switch to another tab and back; THEN close the tab.")
    print("Lines: CLICK x,y -> element | FOCUS-LEAVE -> element | teach tab hidden/in front | tab unreachable/back")
    sysw = AXUIElementCreateSystemWide()
    st, btn = Q.kCGEventSourceStateCombinedSessionState, Q.kCGMouseButtonLeft
    was_down, focused, unreachable, hidden = False, None, False, False
    last_count = Q.CGEventSourceCounterForEventType(st, Q.kCGEventLeftMouseDown)
    clicks = fast = typed = backs = 0
    end = time.time() + SECONDS
    next_view = 0.0
    while time.time() < end:
        down = Q.CGEventSourceButtonState(st, btn)
        count = Q.CGEventSourceCounterForEventType(st, Q.kCGEventLeftMouseDown)
        edge = down and not was_down
        quick = not edge and count > last_count   # tap-to-click: down+up inside one tick
        if edge or quick:
            clicks += 1
            fast += quick
            p = Q.CGEventGetLocation(Q.CGEventCreate(None))
            err, hit = AXUIElementCopyElementAtPosition(sysw, p.x, p.y, None)
            if err != 0:
                what = f"ax error {err}"
            else:
                herr, hpid = AXUIElementGetPid(hit, None)
                what = describe(hit) + ("" if herr == 0 and hpid == pid else " [other app]")
            print(f"{'CLICK (fast, position approx)' if quick else 'CLICK'} {p.x:.0f},{p.y:.0f} -> {what}")
        was_down, last_count = down, count
        cur = attr(app, "AXFocusedUIElement")
        if focused is not None and (cur is None or not CFEqual(cur, focused)):
            d = describe(focused)   # value read now: length of what was typed
            print(f"FOCUS-LEAVE -> {d}")
            typed += "value_len=-" not in d and "value_len=0" not in d
        if focused is None or cur is None or not CFEqual(cur, focused):
            focused = cur
        reach = attr(tab, "AXRole") is not None
        if reach == unreachable:   # state flipped
            print("tab back" if reach else "tab unreachable")
            backs += reach
            unreachable = not reach
        if time.time() >= next_view:   # tree walk is costly: twice a second
            next_view = time.time() + 0.5
            front = find(attr(app, "AXFocusedWindow"), "AXWebArea") if reach else None
            now_hidden = reach and (front is None or not CFEqual(front, tab))
            if now_hidden != hidden:
                print("teach tab hidden (another tab in front)" if now_hidden else "teach tab in front")
                hidden = now_hidden
        time.sleep(TICK)
    yn = lambda b: "yes" if b else "no"
    print(f"done. clicks seen {clicks} (fast {fast}); typing seen {yn(typed)}; "
          f"tab switch looked like close {yn(backs)}; tab close detected {yn(unreachable)}; "
          f"Input Monitoring granted {yn(im)}")
    if not im:
        print("no new permission proven (Input Monitoring is off and this still worked)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
