"""macOS adapter: NSAccessibility for perception, CGEvent for real mouse/keyboard."""
import subprocess
import time

import Quartz as Q
from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps
from ApplicationServices import (
    AXIsProcessTrusted, AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
    AXUIElementCopyMultipleAttributeValues, AXUIElementSetAttributeValue,
    AXValueGetValue, kAXValueCGPointType, kAXValueCGSizeType,
)

from . import Node, ROLES, native_to_neutral

BUNDLES = {"chrome": ("com.google.Chrome", "Google Chrome")}
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
            raise PermissionError("Grant Accessibility to this terminal: System Settings > Privacy & Security > Accessibility")
        self.keys = {k: v["macos"] for k, v in ROLES["keys"].items()}

    # --- application and window ---
    def _app(self, app):
        bundle, _ = BUNDLES[app]
        running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(bundle)
        return running[0] if running else None

    def launch_application(self, app, profile_directory=None):
        """With a profile, Chrome opens (or focuses) a window in that profile even if already running."""
        args = ["--args", f"--profile-directory={profile_directory}"] if profile_directory else []
        if profile_directory or not self._app(app):
            subprocess.run(["open", "-a", BUNDLES[app][1], *args], check=True)
            time.sleep(3)
        self.activate(app)

    def activate(self, app):
        self._app(app).activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.5)

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

    def ask_admin(self, question, timeout_s=60):
        """Native dialog; anything but an explicit Approve (incl. timeout) is a deny."""
        q = question.replace("\\", "\\\\").replace('"', '\\"')
        script = (f'display dialog "{q}" with title "GOV-AIOS approval" '
                  f'buttons {{"Deny", "Approve"}} default button "Deny" giving up after {timeout_s}')
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        return "button returned:Approve" in r.stdout and "gave up:true" not in r.stdout

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
            raise RuntimeError(f"element has no bounds: {node.role} {node.name!r}")
        _, p = AXValueGetValue(pos, kAXValueCGPointType, None)
        _, s = AXValueGetValue(size, kAXValueCGSizeType, None)
        return p.x, p.y, s.width, s.height

    def click(self, node):
        # wait for layout to settle (ads, hydration) so the click hits the element, max ~3s
        x, y, w, h = self._bounds(node)
        for _ in range(10):
            time.sleep(0.3)
            b = self._bounds(node)
            if b == (x, y, w, h):
                break
            x, y, w, h = b
        if w <= 0 or h <= 0:
            raise RuntimeError(f"element not visible: {node.name!r}")
        pt = (x + min(w / 2, 20), y + h / 2)   # near the left edge: link text, not trailing whitespace
        for t in (Q.kCGEventMouseMoved, Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
            ev = Q.CGEventCreateMouseEvent(None, t, pt, Q.kCGMouseButtonLeft)
            Q.CGEventSetFlags(ev, 0)   # else a prior cmd shortcut leaks in: cmd+click = background tab
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.05)

    def scroll_into_view(self, node):
        # AXScrollToVisible is an accessibility action, not input; it only scrolls.
        from ApplicationServices import AXUIElementPerformAction
        AXUIElementPerformAction(node.handle, "AXScrollToVisible")
        time.sleep(0.4)

    def press(self, logical_key):
        *mods, key = self.keys[logical_key]
        flags = 0
        for m in mods:
            flags |= FLAGS[m]
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, KEYCODES[key], down)
            Q.CGEventSetFlags(ev, flags)
            Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.03)

    def type_text(self, text):
        for ch in text:
            for down in (True, False):
                ev = Q.CGEventCreateKeyboardEvent(None, 0, down)
                Q.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
                Q.CGEventSetFlags(ev, 0)
                Q.CGEventPost(Q.kCGHIDEventTap, ev)
            time.sleep(0.01)
