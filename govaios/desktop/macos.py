"""macOS adapter: NSAccessibility for perception, CGEvent for real mouse/keyboard."""
import os
import signal
import subprocess
import time

import Quartz as Q
from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
from ApplicationServices import (
    AXIsProcessTrusted, AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
    AXUIElementCopyElementAtPosition, AXUIElementCopyMultipleAttributeValues, AXUIElementCreateSystemWide,
    AXUIElementGetPid, AXUIElementSetAttributeValue, AXValueGetValue, kAXValueCGPointType, kAXValueCGSizeType,
)
from CoreFoundation import CFEqual

from . import Node, ROLES, native_to_neutral
from .. import auth
from ..runstate import Stop

BUNDLES = {"chrome": ("com.google.Chrome", "Google Chrome")}
# Fixed human pace (spec 5.8): reliability and fair site load, never bot-detection evasion (no jitter).
# shortcut: fixed values, not the admin's learned pace; replaced by bootstrap-learned pace in plan 4.
PACE = {"char": 0.12, "key": 0.15, "pointer": 0.25, "after_action": 1.0}
KEYCODES = {"l": 37, "[": 33, "return": 36, "left": 123}
FLAGS = {"cmd": Q.kCGEventFlagMaskCommand, "alt": Q.kCGEventFlagMaskAlternate,
         "ctrl": Q.kCGEventFlagMaskControl, "shift": Q.kCGEventFlagMaskShift}
ATTRS = ["AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXValue", "AXDOMIdentifier", "AXDOMClassList", "AXChildren"]
NEUTRAL = native_to_neutral("macos")
MAX_NODES = 40000


def _attr(el, name):
    err, v = AXUIElementCopyAttributeValue(el, name, None)
    return v if err == 0 else None


def _s(v):
    return str(v).replace("\n", " ").strip() if isinstance(v, str) else ""


class MacDesktop:
    platform = "macos"

    def __init__(self):
        if not AXIsProcessTrusted():
            raise PermissionError("Grant Accessibility to gov-aios.app: System Settings > Privacy & Security > Accessibility")
        self.keys = {k: v["macos"] for k, v in ROLES["keys"].items()}
        self._target = None   # app key that input may go to; set by launch/activate
        self._window = None   # pinned window token (pin_window); input refused if another window has focus

    def _target_pid(self):
        running = self._app(self._target) if self._target else None
        if running is None:
            raise RuntimeError("input refused: target app is not running")
        return running.processIdentifier()

    def _focused(self):
        """(pid, focused window) of the app holding keyboard focus, read live over AX IPC
        (NSWorkspace.frontmostApplication is cached without a run loop). Any AX error -> (None, None)."""
        err, app_el = AXUIElementCopyAttributeValue(AXUIElementCreateSystemWide(), "AXFocusedApplication", None)
        if err != 0 or app_el is None:
            return None, None
        err, pid = AXUIElementGetPid(app_el, None)
        return (pid if err == 0 else None), _attr(app_el, "AXFocusedWindow")

    def _require_focus(self):
        """Synthetic input goes to whatever has focus: refuse unless it is the flow's app (and pinned window)."""
        if auth.screen_locked():
            raise Stop("screen_locked")   # row 9: recorded as screen_locked, not as a RuntimeError
        pid = self._target_pid()
        fpid, win = self._focused()
        if fpid is None or fpid != pid:
            raise RuntimeError("input refused: target app is not frontmost")
        if self._window is not None and (win is None or not CFEqual(win, self._window)):
            raise RuntimeError("input refused: focused window is not the verified window")
        return pid

    def focused_window_id(self, app):
        """Opaque token for the target app's focused window (the AXUIElement; compared with CFEqual)."""
        running = self._app(app)
        fpid, win = self._focused()
        if running is None or fpid != running.processIdentifier() or win is None:
            raise RuntimeError("no focused window in the target app")
        return win

    def pin_window(self, token):
        """From now on input goes only to this window; it must still have focus right now."""
        self._window = token
        self._require_focus()

    # --- application and window ---
    def _app(self, app):
        bundle, _ = BUNDLES[app]
        running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle)
        return running[0] if running else None

    def launch_application(self, app, profile_directory=None):
        """With a profile, Chrome must already be running; its own binary hands the profile to it (row 23)."""
        if profile_directory and not self._app(app):
            raise Stop("start Chrome, then run the flow again")   # never launch: a child would inherit our sandbox and TCC identity
        if profile_directory:
            exe = f"/Applications/{BUNDLES[app][1]}.app/Contents/MacOS/{BUNDLES[app][1]}"
            try:
                proc = subprocess.Popen([exe, f"--profile-directory={profile_directory}"],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError:   # binary missing or not executable
                raise Stop("chrome handoff failed") from None
            try:
                code = proc.wait(timeout=10)
            except BaseException as e:   # timeout (it became a browser of its own) or the run's own stop
                try:
                    os.killpg(proc.pid, signal.SIGKILL)   # own session: the run's SIGKILL would miss it
                except ProcessLookupError:
                    proc.kill()
                proc.wait()
                if isinstance(e, subprocess.TimeoutExpired):
                    raise Stop("chrome handoff failed") from None
                raise
            if code != 0:
                raise Stop("chrome handoff failed")
        elif not self._app(app):
            subprocess.run(["open", "-a", BUNDLES[app][1]], check=True)
            time.sleep(3)
        self.activate(app)   # brings Chrome's key window (the profile window just opened) to the front
        time.sleep(PACE["after_action"])

    def activate(self, app):
        self._target = app
        pid = self._target_pid()
        self._app(app).activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        for _ in range(20):   # activation is async; wait until it really has focus (same check as input)
            time.sleep(0.25)
            if self._focused()[0] == pid:
                return
        raise RuntimeError("could not bring the target app to the front")

    def _ax_app(self, app):
        ax = AXUIElementCreateApplication(self._app(app).processIdentifier())
        # Chrome builds its web tree only when it thinks an assistive tech is present.
        AXUIElementSetAttributeValue(ax, "AXEnhancedUserInterface", True)
        AXUIElementSetAttributeValue(ax, "AXManualAccessibility", True)
        return ax

    def window_title(self, app):
        win = _attr(self._ax_app(app), "AXFocusedWindow")
        return _s(_attr(win, "AXTitle")) if win is not None else ""

    def current_url(self, app):
        win = _attr(self._ax_app(app), "AXFocusedWindow")
        doc = self._find(win, "AXWebArea", 30) if win is not None else None
        url = _attr(doc, "AXURL") if doc is not None else None
        return str(url.absoluteString()) if url is not None else ""

    # --- perception ---
    def web_root(self, app):
        """Snapshot of the focused window's top web document, or None if not built yet."""
        win = _attr(self._ax_app(app), "AXFocusedWindow")
        if win is None:
            return None
        doc = self._find(win, "AXWebArea", 30)
        if doc is None:
            return None
        self._count = 0
        return self._snap(doc)

    def _find(self, el, role, depth):
        if _s(_attr(el, "AXRole")) == role:
            return el
        if depth == 0:
            return None
        for c in _attr(el, "AXChildren") or []:
            hit = self._find(c, role, depth - 1)
            if hit is not None:
                return hit
        return None

    def _snap(self, el):
        self._count += 1
        err, vals = AXUIElementCopyMultipleAttributeValues(el, ATTRS, 0, None)
        if err != 0:
            return Node(role="native:?", handle=el)
        role, sub, title, desc, value, dom_id, classes, kids = vals
        role, sub = _s(role), _s(sub)
        neutral = NEUTRAL.get(f"{role}/{sub}") or NEUTRAL.get(role) or f"native:{role}"
        node = Node(role=neutral, name=_s(title) or _s(desc), value=_s(value), dom_id=_s(dom_id),
                    dom_class=tuple(c for c in classes if isinstance(c, str)) if hasattr(classes, '__iter__') and not isinstance(classes, str) else (), handle=el)
        if neutral == "document" and self._count > 1:
            node.role = "embedded_document"   # iframes (ads); not descended into
            return node
        if isinstance(kids, (list, tuple)) or hasattr(kids, "count"):
            for k in kids:
                if self._count >= MAX_NODES:
                    break
                node.children.append(self._snap(k))
        return node

    # --- input: real OS events ---
    def _bounds(self, node):
        pos, size = _attr(node.handle, "AXPosition"), _attr(node.handle, "AXSize")
        if pos is None or size is None:
            raise RuntimeError(f"element has no bounds: {node.role}")   # never the name: page content
        _, p = AXValueGetValue(pos, kAXValueCGPointType, None)
        _, s = AXValueGetValue(size, kAXValueCGSizeType, None)
        return p.x, p.y, s.width, s.height

    def click(self, node):
        self._require_focus()
        # wait for layout to settle (ads, hydration) so the click hits the element, max ~3s
        x, y, w, h = self._bounds(node)
        for _ in range(10):
            time.sleep(0.3)
            b = self._bounds(node)
            if b == (x, y, w, h):
                break
            x, y, w, h = b
        if w <= 0 or h <= 0:
            raise RuntimeError("element not visible")
        pt = (x + min(w / 2, 20), y + h / 2)   # near the left edge: link text, not trailing whitespace
        for t in (Q.kCGEventMouseMoved, Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
            if t != Q.kCGEventLeftMouseUp:   # re-check after the pointer pause; never strand a pressed button
                self._require_point(pt)
            ev = Q.CGEventCreateMouseEvent(None, t, pt, Q.kCGMouseButtonLeft)
            Q.CGEventSetFlags(ev, 0)   # else a prior cmd shortcut leaks in: cmd+click = background tab
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(PACE["pointer"] if t == Q.kCGEventMouseMoved else 0.08)
        time.sleep(PACE["after_action"])

    def _require_point(self, pt):
        """Focus check, plus: the element under the point belongs to the target pid (not a dialog or other app)."""
        pid = self._require_focus()
        err, hit = AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(), pt[0], pt[1], None)
        hit_pid = AXUIElementGetPid(hit, None) if err == 0 and hit is not None else (1, None)
        if hit_pid[0] != 0 or hit_pid[1] != pid:
            raise RuntimeError("input refused: click point is not in the target app")
        if self._window is not None and not CFEqual(_attr(hit, "AXWindow"), self._window):
            raise RuntimeError("input refused: click point is not in the verified window")

    def scroll_into_view(self, node):
        # AXScrollToVisible is an accessibility action, not input; it only scrolls.
        from ApplicationServices import AXUIElementPerformAction
        AXUIElementPerformAction(node.handle, "AXScrollToVisible")
        time.sleep(PACE["after_action"])

    def press(self, logical_key):
        pid = self._require_focus()
        *mods, key = self.keys[logical_key]
        flags = 0
        for m in mods:
            flags |= FLAGS[m]
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, KEYCODES[key], down)
            Q.CGEventSetFlags(ev, flags)
            Q.CGEventPostToPid(pid, ev)   # delivered to the target process, never to whatever has focus
            time.sleep(0.05)
        time.sleep(PACE["key"])

    def type_text(self, text):
        for ch in text:
            pid = self._require_focus()   # per character: focus can move mid-word
            for down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(None, 0, down)
                Q.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
                Q.CGEventSetFlags(ev, 0)
                Q.CGEventPostToPid(pid, ev)
            time.sleep(PACE["char"])
        time.sleep(PACE["after_action"])
