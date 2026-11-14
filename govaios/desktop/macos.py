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
    AXUIElementGetPid, AXUIElementPerformAction, AXUIElementSetAttributeValue, AXValueGetValue, kAXValueCGPointType, kAXValueCGSizeType,
)
from CoreFoundation import CFEqual

from . import Node, ROLES, native_to_neutral
from .. import auth
from ..runstate import Stop

BUNDLES = {"chrome": ("com.google.Chrome", "Google Chrome")}
# Fixed human pace (spec 5.8): reliability and fair site load, never bot-detection evasion (no jitter).
# shortcut: fixed values, not the admin's learned pace; replaced by bootstrap-learned pace in plan 4.
PACE = {"char": 0.12, "key": 0.15, "pointer": 0.25, "after_action": 1.0}
KEYCODES = {"l": 37, "[": 33, "return": 36, "left": 123, "w": 13, "t": 17, "a": 0, "g": 5, "backspace": 51, "escape": 53}
FLAGS = {"cmd": Q.kCGEventFlagMaskCommand, "alt": Q.kCGEventFlagMaskAlternate,
         "ctrl": Q.kCGEventFlagMaskControl, "shift": Q.kCGEventFlagMaskShift}
ATTRS = ["AXRole", "AXSubrole", "AXTitle", "AXDescription", "AXValue", "AXDOMIdentifier", "AXDOMClassList", "AXChildren"]
NEUTRAL = native_to_neutral("macos")
MAX_NODES = 40000


def _attr(el, name):
    err, v = AXUIElementCopyAttributeValue(el, name, None)
    return v if err == 0 else None


def _within(el, target, depth=40):
    """True if el is target or a descendant of it (AXParent chain); no target means no."""
    for _ in range(depth):
        if el is None or target is None:
            return False
        if CFEqual(el, target):
            return True
        el = _attr(el, "AXParent")
    return False


def _chain(el, depth=8):
    """el and its AXParent chain (innermost first): role, subrole, title, description, value, dom id."""
    out = []
    for _ in range(depth):
        if el is None:
            break
        out.append({k: _s(_attr(el, a)) for k, a in (("role", "AXRole"), ("subrole", "AXSubrole"),
                    ("title", "AXTitle"), ("desc", "AXDescription"), ("value", "AXValue"), ("dom_id", "AXDOMIdentifier"))})
        pos, size = _attr(el, "AXPosition"), _attr(el, "AXSize")
        if pos is not None and size is not None:   # x, y, w, h on screen
            p, s = AXValueGetValue(pos, kAXValueCGPointType, None)[1], AXValueGetValue(size, kAXValueCGSizeType, None)[1]
            out[-1]["frame"] = [p.x, p.y, s.width, s.height]
        el = _attr(el, "AXParent")
    return out


def _s(v):
    return str(v).replace("\n", " ").strip() if isinstance(v, str) else ""



class InputRefused(Stop, RuntimeError):
    """A safety refusal with fixed text (never page content), so the run prints and audits it as a stop."""

CLICK_TRIES = 6

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
            raise InputRefused("input refused: target app is not running")
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
            front = NSRunningApplication.runningApplicationWithProcessIdentifier_(fpid) if fpid else None
            name = str(front.localizedName() or "")[:40] if front is not None else "none"
            raise InputRefused(f"input refused: target app is not frontmost ({name} is)")   # app name only: says who took it
        if self._window is not None and (win is None or not CFEqual(win, self._window)):
            raise InputRefused("input refused: focused window is not the verified window")
        return pid

    def focused_window_id(self, app):
        """Opaque token for the target app's focused window (the AXUIElement; compared with CFEqual)."""
        running = self._app(app)
        fpid, win = self._focused()
        for _ in range(10):   # Chrome just launched or reopened: its window can take a moment to take focus
            if running is not None and fpid == running.processIdentifier() and win is not None:
                return win
            time.sleep(0.5)
            running, (fpid, win) = self._app(app), self._focused()
        raise Stop("the browser has no window in front: click its window, then run again")

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

    def _snap(self, el, parent_role=None):
        self._count += 1
        err, vals = AXUIElementCopyMultipleAttributeValues(el, ATTRS, 0, None)
        if err != 0:
            return Node(role="native:?", handle=el)
        role, sub, title, desc, value, dom_id, classes, kids = vals
        role, sub = _s(role), _s(sub)
        neutral = NEUTRAL.get(f"{role}/{sub}") or NEUTRAL.get(role) or f"native:{role}"
        if neutral == "tab" and parent_role != "AXTabGroup":
            neutral = "radio"   # Chrome's role=tab and plain radios are both AXRadioButton
        if "AXSecureTextField" in (role, sub):   # Chrome: the role; AppKit: AXTextField + this subrole
            neutral, value = "native:AXSecureTextField", ""   # a password never reaches a snapshot (lessons store trees)
        node = Node(role=neutral, name=_s(title) or _s(desc), value=_s(value), dom_id=_s(dom_id),
                    dom_class=tuple(c for c in classes if isinstance(c, str)) if hasattr(classes, '__iter__') and not isinstance(classes, str) else (), handle=el)
        if neutral == "document" and self._count > 1:
            node.role = "embedded_document"   # iframes (ads); not descended into
            return node
        if role == "AXColumn":
            return node   # Chrome lists each table cell under its row AND its column: the rows already hold them all
        if isinstance(kids, (list, tuple)) or hasattr(kids, "count"):
            for k in kids:
                if self._count >= MAX_NODES:
                    break
                node.children.append(self._snap(k, role))
        return node

    # --- input: real OS events ---
    def _bounds(self, node):
        pos, size = _attr(node.handle, "AXPosition"), _attr(node.handle, "AXSize")
        if pos is None or size is None:
            raise RuntimeError(f"element has no bounds: {node.role}")   # never the name: page content
        _, p = AXValueGetValue(pos, kAXValueCGPointType, None)
        _, s = AXValueGetValue(size, kAXValueCGSizeType, None)
        return p.x, p.y, s.width, s.height

    def _settled_points(self, node):
        # wait for layout to settle (ads, hydration, smooth scroll) so the click hits the element, max ~3s
        x, y, w, h = self._bounds(node)
        for _ in range(10):
            time.sleep(0.3)
            b = self._bounds(node)
            if b == (x, y, w, h):
                break
            x, y, w, h = b
        if w <= 0 or h <= 0:
            raise RuntimeError("element not visible")
        # last: the first line's left spot, for a link that wraps (its box centre falls between the lines)
        return (x + min(w / 2, 20), y + h / 2), (x + w / 2, y + h / 2), (x + min(w / 2, 20), y + min(h / 2, 9))

    def link_url(self, node):
        """The link's own address (AXURL), or None."""
        u = _attr(node.handle, "AXURL") if node.handle is not None else None
        return str(u.absoluteString()) if hasattr(u, "absoluteString") else (str(u) if u else None)

    def click(self, node):
        self._require_focus()
        # 6 tries (~5 s): Chrome answers a hit on a fresh or just-hovered wrapped link with its cell for a few
        # seconds before its text (JobLens EVERSANA, 2026-11-09); the check stays strict, it just waits
        for attempt in range(CLICK_TRIES):
            last = attempt == CLICK_TRIES - 1
            pt = None
            # left spot first (link text, not trailing whitespace), then the centre, then the first line: a page button can sit over
            # an option's left edge (Greenhouse "Locate me" under the Location list)
            pts = self._settled_points(node)
            for i, p in enumerate(pts):
                final = last and i == len(pts) - 1
                if self._point_ok(p, node, final):
                    self._mouse(Q.kCGEventMouseMoved, p)
                    time.sleep(PACE["pointer"])
                    # re-check after the pointer pause, before the button goes down (nothing pressed yet: safe to
                    # retry); a hover restyle can move a wrapped link's line break, so a failed spot tries the next
                    if self._point_ok(p, node, final):
                        pt = p
                        break
            if pt is not None:
                break
            time.sleep(0.5)   # a page still scrolling or loading: Chrome's AX bounds can lag the layout ~1 s
        self._mouse(Q.kCGEventLeftMouseDown, pt)
        time.sleep(0.08)
        self._mouse(Q.kCGEventLeftMouseUp, pt)   # never strand a pressed button
        time.sleep(PACE["after_action"])

    def _point_ok(self, pt, node, final):
        """True if the point is on the target; False to retry when a neighbour is under it (a scroll still moving).
        Any other refusal (another app or window), or the final try, raises."""
        try:
            self._require_point(pt, node.handle)
            return True
        except InputRefused as e:
            if final or "not on the target element" not in str(e):
                raise
            return False

    def _mouse(self, kind, pt):
        ev = Q.CGEventCreateMouseEvent(None, kind, pt, Q.kCGMouseButtonLeft)
        Q.CGEventSetFlags(ev, 0)   # else a prior cmd shortcut leaks in: cmd+click = background tab
        Q.CGEventPost(Q.kCGHIDEventTap, ev)

    def _require_point(self, pt, target):
        """Focus check, plus: the element under the point is the target element or inside it
        (not a dialog, another app, or an ad that moved over the link)."""
        pid = self._require_focus()
        err, hit = AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(), pt[0], pt[1], None)
        hit_pid = AXUIElementGetPid(hit, None) if err == 0 and hit is not None else (1, None)
        if hit_pid[0] != 0 or hit_pid[1] != pid:
            raise InputRefused("input refused: click point is not in the target app")
        if self._window is not None and not CFEqual(_attr(hit, "AXWindow"), self._window):
            raise InputRefused("input refused: click point is not in the verified window")
        if not _within(hit, target):
            # roles only (never names or values): tells a stale target from an overlay from a coarse hit
            rel = "contains" if _within(target, hit) else "is unrelated to"
            # dev capture only (engine writes it 0600 on stop, never logged): the full picture, names included
            self.last_refusal = {"point": list(pt), "relation": rel, "hit": _chain(hit), "target": _chain(target)}
            raise InputRefused(f"input refused: click point is not on the target element (hit {_s(_attr(hit, 'AXRole'))}"
                               f" {rel} target {_s(_attr(target, 'AXRole')) or 'gone'})")

    def scroll_into_view(self, node):
        # AXScrollToVisible is an accessibility action, not input; it only scrolls.
        AXUIElementPerformAction(node.handle, "AXScrollToVisible")
        time.sleep(PACE["after_action"])

    def _key(self, pid, logical_key):
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

    def _char(self, pid, ch):
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, 0, down)
            Q.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
            Q.CGEventSetFlags(ev, 0)
            Q.CGEventPostToPid(pid, ev)
        time.sleep(PACE["char"])

    def press(self, logical_key):
        self._key(self._require_focus(), logical_key)

    def type_text(self, text):
        for ch in text:
            self._char(self._require_focus(), ch)   # per character: focus can move mid-word
        time.sleep(PACE["after_action"])

    # --- observation (Studio lessons): read only, never posts input ---
    def same(self, a, b):
        return a is b or (a is not None and b is not None and bool(CFEqual(a, b)))

    def _win(self, app):
        return self._window if self._window is not None else _attr(self._ax_app(app), "AXFocusedWindow")

    def _selected_tab(self, el, depth=12):
        """The selected tab button in the window's tab strip (AXTabGroup > AXRadioButton, AXValue 1);
        page content (AXWebArea) is not searched, so a site's own tab list never counts."""
        if el is None or depth == 0:
            return None
        role = _s(_attr(el, "AXRole"))
        if role == "AXWebArea":
            return None
        kids = _attr(el, "AXChildren") or []
        if role == "AXTabGroup":
            return next((k for k in kids if _s(_attr(k, "AXRole")) == "AXRadioButton" and _attr(k, "AXValue") == 1), None)
        for k in kids:
            hit = self._selected_tab(k, depth - 1)
            if hit is not None:
                return hit
        return None

    def _tab_id(self, app):
        win = self._win(app)
        tab = self._selected_tab(win)
        self._tab_source = "tab_strip"
        if tab is None and win is not None:
            # shortcut: no tab strip found (e.g. a tabless app window), so the web area stands in; it changes per document
            tab, self._tab_source = self._find(win, "AXWebArea", 30), "web_area"
        return tab

    def teach_tab(self, app):
        """The tab the admin teaches in: Chrome's selected tab of the pinned window (stable across navigation).
        Call it before observe_sample. teach_tab_source says which path found it: "tab_strip" or "web_area"."""
        self._teach = self._tab_id(app)
        self.teach_tab_source = self._tab_source
        return self._teach

    def element_at(self, x: float, y: float):
        return self._hit((x, y))

    def _hit(self, pt):
        """Element under pt if it is in the target app and the pinned window, else None (never raises)."""
        err, hit = AXUIElementCopyElementAtPosition(AXUIElementCreateSystemWide(), pt[0], pt[1], None)
        if err != 0 or hit is None:
            return None
        perr, pid = AXUIElementGetPid(hit, None)
        if perr != 0 or pid != self._target_pid():
            return None
        if self._window is None or not self.same(_attr(hit, "AXWindow"), self._window):
            return None
        return hit

    def observe_sample(self, app):
        """One look at mouse, focus, url, title and tabs (teach_tab first). Polls button state and the down
        counter, so a tap inside one poll still shows down once; no event tap, no input posted. hit/focus/web are
        None unless the pinned window has focus (devtools, a popup or another window are not the lesson);
        Chrome gone -> tab False, never raises."""
        st = Q.kCGEventSourceStateCombinedSessionState
        count = Q.CGEventSourceCounterForEventType(st, Q.kCGEventLeftMouseDown)
        tapped = getattr(self, "_downs", None) is not None and count > self._downs
        self._downs = count
        p = Q.CGEventGetLocation(Q.CGEventCreate(None))
        pt = (p.x, p.y)
        down = bool(Q.CGEventSourceButtonState(st, Q.kCGMouseButtonLeft)) or tapped
        if self._app(app) is None or (self._target and self._app(self._target) is None):   # Chrome quit
            return {"down": down, "pt": pt, "hit": None, "focus": None, "url": "", "title": "", "tab": False, "web": None}
        teach = getattr(self, "_teach", None)
        win = _attr(self._ax_app(app), "AXFocusedWindow")
        mine = self._window is not None and self.same(win, self._window)
        return {"down": down, "pt": pt, "hit": self._hit(pt) if mine else None, "focus": self._focus_el() if mine else None,
                "url": self.current_url(app), "title": self.window_title(app),
                "tab": teach is not None and _attr(teach, "AXRole") is not None,
                "web": self._tab_id(app) if mine else None}

    def _focus_el(self):
        return _attr(AXUIElementCreateApplication(self._target_pid()), "AXFocusedUIElement")

    def focused_is(self, node):
        el = self._focus_el()
        return el is not None and bool(CFEqual(el, node.handle))

    def type_into(self, node, text):
        """type_text, but the field itself (not just the window) must keep focus before every character."""
        for ch in text:
            pid = self._require_focus()
            if not self.focused_is(node):
                raise InputRefused("input refused: focus left the field")
            self._char(pid, ch)
        time.sleep(PACE["after_action"])

    def _ancestor(self, role, el=None):
        """First element with AXRole `role` on the AXParent chain from the focused element (bounded)."""
        el = self._focus_el() if el is None else el
        for _ in range(40):
            if el is None:
                return None
            if _attr(el, "AXRole") == role:
                return el
            el = _attr(el, "AXParent")
        return None

    def menu_open(self):
        return self._ancestor("AXMenu") is not None

    def _in_pinned_sheet(self):
        sheet = self._ancestor("AXSheet")
        return sheet is not None and _within(_attr(sheet, "AXParent"), self._window)

    def raise_pinned(self):
        if self._window is None:
            raise InputRefused("input refused: no pinned window")
        AXUIElementPerformAction(self._window, "AXRaise")
        pid = self._target_pid()
        self._app(self._target).activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        for _ in range(8):
            time.sleep(0.25)
            if self._focused()[0] == pid:
                break
        self._require_focus()

    def choose_file(self, path):
        """Drive the native open sheet: Go to Folder, the path, Enter. The sheet (child of the pinned window)
        replaces the window check here; self._window stays as it is. The path is never put in a message."""
        pid = self._target_pid()
        for _ in range(20):
            if self._in_pinned_sheet():
                break
            time.sleep(0.25)
        else:
            raise InputRefused("input refused: no file dialog")

        def guard():
            if auth.screen_locked():
                raise Stop("screen_locked")
            if self._focused()[0] != pid:
                raise InputRefused("input refused: target app is not frontmost")
            if not self._in_pinned_sheet():
                raise InputRefused("input refused: file dialog is not focused")
        guard()
        self._key(pid, "go_to_folder")
        for ch in path:
            guard()
            self._char(pid, ch)
        guard()
        self._key(pid, "enter")
        time.sleep(1)
        if self._in_pinned_sheet():   # still open: the Go to Folder field needed a second Enter
            guard()
            self._key(pid, "enter")
