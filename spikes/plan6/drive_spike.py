"""Teach-extension matching spike, self-driven: GOV-AIOS clicks through the admin's own JobLens in their real Chrome
(real mouse presses, held 80 ms as desk.click does), while the extension reports each mouse-down and the checks of
match_spike.py run. One command, about a minute, hands off the mouse and keyboard while it runs.

Run (admin present, from Terminal with Accessibility), from the repo root, with JobLens open in Chrome Profile 2,
the spike extension loaded (reloaded after an update) and its side panel open:
  .venv/bin/python spikes/plan6/drive_spike.py
It clicks only Discover, Shortlisted, Review and Close-by-Escape on http://localhost:8100. It never presses Approve &
promote, Reject JD or Skip (refused by name), never leaves localhost:8100, and stops at the first refusal.
Spike only: replaces desk._focused (AXFocusedApplication fails from Terminal's python) with the window list.
"""
import sys
import threading
import time
from pathlib import Path

import Quartz as Q
from ApplicationServices import AXIsProcessTrusted

sys.path.insert(0, str(Path(__file__).parent))
import match_spike as m   # noqa: E402  (its checks, server and state)
from govaios.desktop.macos import MacDesktop, _attr   # noqa: E402
from govaios.engine import find_all   # noqa: E402
from govaios.policy import origin   # noqa: E402

ROUNDS = 3   # pass 1 is driven this many times: timing samples, not one lucky click
NEVER = ("Approve", "promote", "Reject", "Skip", "Delete")
DISCOVER = {"role": "link", "name": "Discover"}
SHORTLISTED = {"role": "tab", "name_matches": r"^Shortlisted \(\d+\)$"}
REVIEW = {"role": "button", "name": "Review"}


def chrome_front():
    wins = Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
                                        Q.kCGNullWindowID) or []
    top = next((w for w in wins if w.get("kCGWindowLayer") == 0), None)
    return int(top["kCGWindowOwnerPID"]) if top and top.get("kCGWindowOwnerName") == "Google Chrome" else None


def wait_for(spec, secs=8):
    end = time.time() + secs
    while time.time() < end:
        root = m.desk.web_root(m.APP)
        hits = find_all(root, spec, {"elements": {}}) if root else []
        if hits:
            return root, hits
        time.sleep(0.3)
    return root, []


def click(node):
    if any(w in node.name for w in NEVER):
        raise SystemExit(f"refused: the spike never presses {node.name!r}")
    if origin(m.desk.current_url(m.APP) or "") != m.SITE:
        raise SystemExit("refused: the tab is not on localhost:8100")
    m.desk.click(node)
    time.sleep(0.5)


def go(path):
    m.desk.press("focus_address_bar")
    m.desk.type_text(m.SITE + path)
    m.desk.press("enter")
    time.sleep(2.5)


def drive(spec, what):
    _, hits = wait_for(spec)
    if not hits:
        raise SystemExit(f"could not find {what} to click")
    click(hits[0])


def main():
    if not AXIsProcessTrusted():
        print("Terminal needs Accessibility: System Settings -> Privacy & Security -> Accessibility")
        return 1
    desk = m.desk = MacDesktop()
    desk._target = m.APP
    desk._focused = lambda: ((pid, _attr(desk._ax_app(m.APP), "AXFocusedWindow")) if (pid := chrome_front())
                             else (None, None))
    print("Click the JobLens tab in Chrome now (waiting up to 60 s). Then hands off the mouse and keyboard.")
    for _ in range(200):
        if chrome_front() and (win := _attr(desk._ax_app(m.APP), "AXFocusedWindow")) is not None:
            break
        time.sleep(0.3)
    else:
        print("Chrome never came to the front. Run again.")
        return 1
    time.sleep(1)
    desk.pin_window(win)
    srv = m.ThreadingHTTPServer(("127.0.0.1", m.PORT), m.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Driving JobLens. Hands off; moving the mouse makes a click refuse, which ends the run.")

    # --- pass 1, ROUNDS times: GOV-AIOS clicks, the extension reports, GOV-AIOS reads at the press ---
    rounds = []
    for r in range(ROUNDS):
        print(f"\nPass 1, round {r + 1}:")
        with m.lock:
            m.downs.clear()
            m.ups.clear()
        go("/")   # a fresh load: the extension's content script is in the page
        drive(DISCOVER, "Discover")
        drive(SHORTLISTED, "Shortlisted")
        drive(REVIEW, "the first profile's Review")
        time.sleep(1.5)
        with m.lock:
            rounds.append((list(m.downs), sorted(m.ups)))
    first = None
    for i, (recs, ups) in enumerate(rounds):
        got = {}
        for label in m.WANT:
            rec = next((x for x in recs if x["dom"]["name"].startswith(label)), None)
            if rec is None:
                m.fail(f"round {i + 1}: no mouse-down reached the script for {label!r}")
                continue
            up = next((u for u in ups if u >= rec["dom"]["t"] / 1000), None)
            if up is None or "snap" not in rec or rec["snap"] > up:
                m.fail(f"round {i + 1}: {label!r} read after the release")
            if rec.get("name") != rec["dom"]["name"]:
                m.fail(f"round {i + 1}: {label!r}: GOV-AIOS read {rec.get('name')!r}, the page said {rec['dom']['name']!r}")
            elif rec.get("spec"):
                got[label] = rec["spec"]
            else:
                m.fail(f"round {i + 1}: {label!r}: no unique spec")
        first = first or (got if len(got) == len(m.WANT) else None)

    # Approve & promote: read from the open pop-up, never pressed
    root = desk.web_root(m.APP)
    m.check_root(root, "pass 1 Review pop-up")
    btns = [n for n in root.walk() if n.role == "button" and n.name == m.APPROVE] if root else []
    approve = m.spec_of(root, btns[0]) if len(btns) == 1 else None
    print(f"  {m.APPROVE!r} spec={approve}")
    if not approve:
        m.fail(f"{m.APPROVE!r}: {len(btns)} buttons, or no unique spec")
    desk.press("escape")   # the pop-up closes (JobLens Dialog: Escape = Close)

    # --- pass 2: fresh loads; find each recorded step, and do it with the recorded spec, as a run would ---
    if first:
        print("\nPass 2:")

        def found(label, spec):
            root, hits = wait_for(spec)
            m.check_root(root, f"pass 2 {label}")
            ok = len(hits) == 1
            print(f"  {'PASS' if ok else 'FAIL'} {label!r} found {len(hits)} time(s) with {spec}")
            if not ok:
                m.fail(f"{label!r} found {len(hits)} times")
            return root, hits
        go("/")
        _, hits = found("Discover", first["Discover"])
        hits and click(hits[0])
        _, hits = found("Shortlisted", first["Shortlisted"])
        hits and click(hits[0])
        root, hits = found("Review", first["Review"])
        if root is not None:
            m.anchor(root, first["Review"], hits)
        hits and click(hits[0])
        time.sleep(1.5)
        if approve:
            found(m.APPROVE, approve)
        desk.press("escape")
    srv.shutdown()
    print("\nSPIKE PASS" if not m.fails else "\nSPIKE FAIL: " + ", ".join(dict.fromkeys(m.fails)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
