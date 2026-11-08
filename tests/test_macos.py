"""MacDesktop input guards with every pyobjc call mocked: no real input, focus, AX or app launch."""
import signal
import subprocess
import types

import pytest

from govaios.desktop import Node
from govaios.desktop import macos
from govaios.runstate import Stop

CHROME, OTHER = 100, 200


class Running:
    def __init__(self):
        self.activated = 0

    def processIdentifier(self):
        return CHROME

    def activateWithOptions_(self, opts):
        self.activated += 1


class AX:
    """Fake accessibility state: which pid/window has focus, what is under the click point."""

    def __init__(self):
        self.focus_pid, self.window, self.hit_pid = CHROME, "win1", CHROME
        self.hit_window = "win1"
        self.hit_parent = None
        self.focus_err = self.hit_err = 0

    def copy_attr(self, el, name, _):
        if (el, name) == ("sys", "AXFocusedApplication"):
            return self.focus_err, "focused_app"
        if (el, name) == ("focused_app", "AXFocusedWindow"):
            return 0, self.window
        if (el, name) == ("hit", "AXWindow"):
            return 0, self.hit_window
        if (el, name) == ("hit", "AXParent") and self.hit_parent:
            return 0, self.hit_parent
        return -25212, None

    def get_pid(self, el, _):
        return 0, {"focused_app": self.focus_pid, "hit": self.hit_pid}[el]

    def at_position(self, el, x, y, _):
        return self.hit_err, "hit"


@pytest.fixture
def env(monkeypatch):
    ax, posted = AX(), []
    fake_q = types.SimpleNamespace(
        CGEventCreateKeyboardEvent=lambda src, code, down: ("key", code, down),
        CGEventCreateMouseEvent=lambda src, t, pt, b: ("mouse", t),
        CGEventSetFlags=lambda ev, f: None,
        CGEventKeyboardSetUnicodeString=lambda ev, n, ch: None,
        CGEventPost=lambda tap, ev: posted.append(("hid", ev)),
        CGEventPostToPid=lambda pid, ev: posted.append((pid, ev)),
        kCGEventMouseMoved=5, kCGEventLeftMouseDown=1, kCGEventLeftMouseUp=2, kCGMouseButtonLeft=0, kCGHIDEventTap=0)
    monkeypatch.setattr(macos, "Q", fake_q)
    monkeypatch.setattr(macos, "AXIsProcessTrusted", lambda: True)
    monkeypatch.setattr(macos, "AXUIElementCreateSystemWide", lambda: "sys")
    monkeypatch.setattr(macos, "AXUIElementCopyAttributeValue", ax.copy_attr)
    monkeypatch.setattr(macos, "AXUIElementGetPid", ax.get_pid)
    monkeypatch.setattr(macos, "AXUIElementCopyElementAtPosition", ax.at_position)
    monkeypatch.setattr(macos, "CFEqual", lambda a, b: a == b)
    monkeypatch.setattr(macos.time, "sleep", lambda s: None)
    calls = []
    monkeypatch.setattr(macos, "subprocess", types.SimpleNamespace(
        Popen=lambda *a, **k: calls.append(("popen", a[0])), run=lambda *a, **k: calls.append(("run", a[0])),
        DEVNULL=None))
    d = macos.MacDesktop()
    app = Running()
    d._app = lambda name: app
    d._bounds = lambda node: (10, 10, 100, 20)
    d.activate("chrome")
    return types.SimpleNamespace(d=d, ax=ax, posted=posted, app=app, calls=calls)


def test_other_app_focused_refuses_keys(env):
    env.ax.focus_pid = OTHER
    with pytest.raises(RuntimeError, match="not frontmost"):
        env.d.press("enter")
    with pytest.raises(RuntimeError):
        env.d.type_text("x")
    assert env.posted == []


def test_target_focused_posts_keys_to_pid(env):
    env.d.press("enter")
    env.d.type_text("ab")
    assert env.posted and all(dest == CHROME for dest, _ in env.posted)


def test_ax_error_reading_focus_refuses(env):
    env.ax.focus_err = -25204
    with pytest.raises(RuntimeError):
        env.d.press("enter")
    assert env.posted == []


def test_no_target_refuses(env):
    env.d._target = None
    with pytest.raises(RuntimeError):
        env.d.press("enter")


def test_pinned_window_must_keep_focus(env):
    env.d.pin_window(env.d.focused_window_id("chrome"))
    env.d.type_text("a")
    env.ax.window = "win2"
    with pytest.raises(RuntimeError, match="verified window"):
        env.d.type_text("b")
    env.ax.window = None   # AX could not read the window: fail closed
    with pytest.raises(RuntimeError):
        env.d.press("enter")
    assert len(env.posted) == 2


def test_pin_refused_when_window_no_longer_focused(env):
    tok = env.d.focused_window_id("chrome")
    env.ax.window = "win2"
    with pytest.raises(RuntimeError):
        env.d.pin_window(tok)


def test_focused_window_id_requires_target_focus(env):
    env.ax.focus_pid = OTHER
    with pytest.raises(RuntimeError):
        env.d.focused_window_id("chrome")


def test_click_point_owned_by_other_app_refuses(env):
    env.ax.hit_pid = OTHER
    with pytest.raises(RuntimeError, match="click point"):
        env.d.click(Node("link", "SECRET", handle="hit"))
    env.ax.hit_pid, env.ax.hit_err = CHROME, -25200
    with pytest.raises(RuntimeError):
        env.d.click(Node("link", "SECRET", handle="hit"))
    assert env.posted == []


def test_click_in_target_posts_mouse(env):
    env.d.click(Node("link", "SECRET", handle="hit"))
    assert len(env.posted) == 3


def test_activate_waits_for_ax_focus(env):
    env.ax.focus_pid = OTHER
    with pytest.raises(RuntimeError, match="front"):
        env.d.activate("chrome")
    env.ax.focus_pid = CHROME
    env.d.activate("chrome")


def test_errors_carry_no_page_content(env, monkeypatch):
    d = macos.MacDesktop()
    d._app, d._target = env.d._app, "chrome"
    monkeypatch.setattr(macos, "_attr", lambda el, name: None)
    with pytest.raises(RuntimeError) as e:
        d._bounds(Node("link", "SECRET-NAME"))
    assert "SECRET" not in str(e.value)
    env.d._bounds = lambda node: (10, 10, 0, 0)
    with pytest.raises(RuntimeError) as e:
        env.d.click(Node("link", "SECRET-NAME"))
    assert "SECRET" not in str(e.value)


CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class Proc:
    def __init__(self, code=0, hang=False):
        self.code, self.hang, self.killed, self.reaped, self.pid = code, hang, False, False, 4242

    def wait(self, timeout=None):
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired("chrome", timeout)
        self.reaped = self.killed
        return self.code

    def kill(self):
        self.killed = True


def _handoff(env, monkeypatch, proc):
    argv = []
    monkeypatch.setattr(macos.subprocess, "Popen", lambda a, **k: argv.append(a) or proc)
    monkeypatch.setattr(macos.os, "killpg", lambda pid, sig: proc.kill() if pid == proc.pid and sig == signal.SIGKILL else None)
    monkeypatch.setattr(macos.subprocess, "TimeoutExpired", subprocess.TimeoutExpired, raising=False)
    return argv


def test_launch_hands_profile_to_running_chrome(env, monkeypatch):
    argv = _handoff(env, monkeypatch, Proc(0))
    env.d.launch_application("chrome", "Profile 2")
    assert argv == [[CHROME_BIN, "--profile-directory=Profile 2"]] and env.app.activated


def test_launch_handoff_timeout_kills_and_stops(env, monkeypatch):
    proc = Proc(hang=True)
    _handoff(env, monkeypatch, proc)
    with pytest.raises(Stop, match="^chrome handoff failed$"):
        env.d.launch_application("chrome", "Profile 2")
    assert proc.killed and proc.reaped


def test_launch_missing_binary_stops(env, monkeypatch):
    def boom(a, **k):
        raise FileNotFoundError(a[0])
    monkeypatch.setattr(macos.subprocess, "Popen", boom)
    with pytest.raises(Stop, match="^chrome handoff failed$"):
        env.d.launch_application("chrome", "Profile 2")


def test_launch_handoff_nonzero_exit_stops(env, monkeypatch):
    _handoff(env, monkeypatch, Proc(1))
    with pytest.raises(Stop, match="^chrome handoff failed$"):
        env.d.launch_application("chrome", "Profile 2")


def test_launch_profile_refuses_when_chrome_not_running(env):
    env.d._app = lambda name: None
    with pytest.raises(Stop, match="^start Chrome, then run the flow again$"):
        env.d.launch_application("chrome", "Profile 2")
    assert env.calls == []


def test_permission_error_names_the_app(monkeypatch):
    monkeypatch.setattr(macos, "AXIsProcessTrusted", lambda: False)
    with pytest.raises(PermissionError, match="gov-aios.app"):
        macos.MacDesktop()


def test_click_rechecks_before_button_down(env, monkeypatch):
    def move_then_steal(tap, ev):   # a dialog takes the point right after the pointer moves
        env.posted.append(("hid", ev))
        env.ax.hit_pid = OTHER
    monkeypatch.setattr(macos.Q, "CGEventPost", move_then_steal)
    with pytest.raises(RuntimeError, match="click point"):
        env.d.click(Node("link", "SECRET", handle="hit"))
    assert [ev[1] for _, ev in env.posted] == [5]   # mouse moved only; no down/up


def test_click_point_in_other_window_of_target_refuses(env):
    env.d.pin_window(env.d.focused_window_id("chrome"))
    env.ax.hit_window = "win2"   # e.g. another Chrome window overlapping the element
    with pytest.raises(RuntimeError, match="verified window"):
        env.d.click(Node("link", "SECRET", handle="hit"))
    env.ax.hit_window = "win1"
    env.d.click(Node("link", "SECRET", handle="hit"))
    assert len(env.posted) == 3


def test_locked_screen_refuses_input(env, monkeypatch):
    monkeypatch.setattr(macos.auth, "screen_locked", lambda: True)
    with pytest.raises(Stop, match="^screen_locked$"):   # row 9: audited as screen_locked, not RuntimeError
        env.d.press("enter")
    assert env.posted == []


def test_launch_handoff_stop_during_wait_kills_child(env, monkeypatch):
    """M-11: the run's SIGTERM Stop during the wait must not leave the handoff child (own session) alive."""
    class StoppedProc(Proc):
        def wait(self, timeout=None):
            if not self.killed:
                raise Stop("emergency stop")
            return super().wait(timeout)
    proc = StoppedProc()
    _handoff(env, monkeypatch, proc)
    with pytest.raises(Stop, match="^emergency stop$"):
        env.d.launch_application("chrome", "Profile 2")
    assert proc.killed


def test_input_refused_is_a_readable_stop():
    from govaios.desktop.macos import InputRefused
    from govaios.runstate import Stop
    e = InputRefused("input refused: target app is not frontmost")
    assert isinstance(e, Stop) and isinstance(e, RuntimeError)   # prints as STOPPED: <fixed text>, not ERROR: RuntimeError


def test_click_refuses_when_something_else_is_under_the_point(env):
    """An ad that slid over the job link after layout settled: same app and window, wrong element."""
    with pytest.raises(RuntimeError, match="not on the target element") as e:
        env.d.click(Node("link", "SECRET", handle="job_link"))
    assert "SECRET" not in str(e.value) and "target" in str(e.value).split("(")[1]   # roles only, never names
    assert env.d.last_refusal["relation"] and env.d.last_refusal["target"]   # kept for the 0600 dev capture only
    assert env.posted == []   # not even the pointer move
    env.ax.hit_parent = "job_link"   # the hit is the link's text, inside the link
    env.d.click(Node("link", "SECRET", handle="job_link"))
    assert len(env.posted) == 3


def _snap_tree(env, monkeypatch, tree):
    """tree: {el: (role, sub, kids)}; fake CopyMultipleAttributeValues."""
    monkeypatch.setattr(macos, "AXUIElementCopyMultipleAttributeValues",
                        lambda el, attrs, o, n: (0, (tree[el][0], tree[el][1], "t", None, None, None, [], tree[el][2])))
    env.d._count = 0
    return env.d._snap("root")


def test_radio_outside_tab_list_is_radio(env, monkeypatch):
    n = _snap_tree(env, monkeypatch, {"root": ("AXGroup", None, ["r"]), "r": ("AXRadioButton", None, [])})
    assert n.children[0].role == "radio"


def test_radio_in_tab_list_is_tab(env, monkeypatch):
    n = _snap_tree(env, monkeypatch, {"root": ("AXTabGroup", None, ["r"]), "r": ("AXRadioButton", None, [])})
    assert n.children[0].role == "tab"


def test_text_area_role(env, monkeypatch):
    assert _snap_tree(env, monkeypatch, {"root": ("AXTextArea", None, [])}).role == "text_area"


def test_new_keys_have_codes():
    from govaios.desktop import ROLES
    for combo in ROLES["keys"].values():
        assert all(k in macos.KEYCODES or k in macos.FLAGS for k in combo["macos"])
    assert (macos.KEYCODES["a"], macos.KEYCODES["g"], macos.KEYCODES["backspace"], macos.KEYCODES["escape"]) == (0, 5, 51, 53)


# --- form input primitives ---
class FormAX:
    """Focused element + AXParent/AXRole tree for the field, sheet and menu checks."""

    def __init__(self):
        self.focused = "field"
        self.parents = {"field": "page", "page": "win1", "item": "menu1", "menu1": "win1",
                        "sfield": "sheet1", "sheet1": "win1"}
        self.roles = {"menu1": "AXMenu", "sheet1": "AXSheet"}
        self.on_post = None


@pytest.fixture
def form(env, monkeypatch):
    fx = FormAX()
    orig = macos.AXUIElementCopyAttributeValue

    def copy_attr(el, name, _):
        if el == "chrome_ax" and name == "AXFocusedUIElement":
            return 0, fx.focused
        if name == "AXParent" and el in fx.parents:
            return 0, fx.parents[el]
        if name == "AXRole" and el in fx.roles:
            return 0, fx.roles[el]
        return orig(el, name, _)
    monkeypatch.setattr(macos, "AXUIElementCopyAttributeValue", copy_attr)
    monkeypatch.setattr(macos, "AXUIElementCreateApplication", lambda pid: "chrome_ax")
    performed = []
    monkeypatch.setattr(macos, "AXUIElementPerformAction", lambda el, a: performed.append((el, a)))
    monkeypatch.setattr(macos.Q, "CGEventPostToPid", lambda pid, ev: (env.posted.append((pid, ev)),
                                                                      fx.on_post and fx.on_post(ev)))
    env.fx, env.performed = fx, performed
    env.d.pin_window("win1")
    return env


def test_type_into_refuses_when_focus_moves(form):
    def move(ev):
        if len([e for _, e in form.posted if e[2]]) == 2 and not ev[2]:
            form.fx.focused = "other"
    form.fx.on_post = move
    with pytest.raises(macos.InputRefused, match="focus left the field"):
        form.d.type_into(Node("textbox", handle="field"), "abcd")
    assert len(form.posted) == 4   # 2 chars, key down + up each


def test_focused_is(form):
    assert form.d.focused_is(Node("textbox", handle="field"))
    assert not form.d.focused_is(Node("textbox", handle="x"))


def test_choose_file_refuses_without_sheet(form):
    with pytest.raises(macos.InputRefused, match="no file dialog"):
        form.d.choose_file("/secret/cv.pdf")
    assert form.posted == []


def test_choose_file_types_path_in_sheet_and_leaves_window_pinned(form):
    form.fx.focused = "sfield"
    def closes_on_enter(ev):   # return key code 36 down closes the sheet
        if ev[1] == 36 and ev[2]:
            form.fx.focused = "field"
    form.fx.on_post = closes_on_enter
    form.d.choose_file("/a")
    keys = [e[1] for _, e in form.posted if e[2]]
    assert keys == [5, 0, 0, 36]   # cmd-shift-g, "/", "a" (unicode events use code 0), enter
    assert form.d._window == "win1"


def test_choose_file_stops_when_sheet_closes(form):
    form.fx.focused = "sfield"
    def closes_on_enter(ev):
        if ev[1] == 36 and ev[2]:
            form.fx.focused = "field"
    form.fx.on_post = closes_on_enter
    form.d.choose_file("/a")
    assert [e[1] for _, e in form.posted if e[2]].count(36) == 1


def test_choose_file_presses_enter_again_if_sheet_stays(form):
    form.fx.focused = "sfield"
    form.d.choose_file("/a")
    assert [e[1] for _, e in form.posted if e[2]].count(36) == 2


def test_choose_file_refuses_when_sheet_closes_mid_path(form):
    form.fx.focused = "sfield"
    def close(ev):
        form.fx.focused = "field"
    form.fx.on_post = close
    with pytest.raises(macos.InputRefused) as e:
        form.d.choose_file("/secret")
    assert "secret" not in str(e.value)


def test_choose_file_sheet_of_another_window_refused(form):
    form.fx.focused = "sfield"
    form.fx.parents["sheet1"] = "win2"
    with pytest.raises(macos.InputRefused):
        form.d.choose_file("/a")


def test_menu_open(form):
    assert not form.d.menu_open()
    form.fx.focused = "item"
    assert form.d.menu_open()
    form.fx.focused = "menu1"
    assert form.d.menu_open()


def test_raise_pinned(form):
    form.d.raise_pinned()
    assert ("win1", "AXRaise") in form.performed and form.app.activated >= 2


def test_choose_file_refuses_when_app_leaves_front_mid_path(form):
    form.fx.focused = "sfield"
    def leave(ev):
        if len(form.posted) >= 6:   # go_to_folder (2 events) + 2 chars
            form.ax.focus_pid = OTHER
    form.fx.on_post = leave
    with pytest.raises(macos.InputRefused, match="not frontmost"):
        form.d.choose_file("/abcdef")
    n = len(form.posted)
    assert n == 6


def test_raise_pinned_without_pinned_window_refused(form):
    form.d._window = None
    with pytest.raises(macos.InputRefused, match="no pinned window"):
        form.d.raise_pinned()
    assert form.performed == []


def test_click_rechecks_after_the_page_moves(env, monkeypatch):
    """Greenhouse 2026-11-08: a scroll still moving put the neighbour's label under the point; settle again."""
    tries = []
    def hit_parent_after_first(el, x, y, _):
        tries.append((x, y))
        env.ax.hit_parent = "job_link" if len(tries) > 1 else None   # second look: the field is under the point
        return 0, "hit"
    monkeypatch.setattr(macos, "AXUIElementCopyElementAtPosition", hit_parent_after_first)
    env.d.click(Node("text_field", "SECRET", handle="job_link"))
    assert len(env.posted) == 3


def test_click_refuses_when_the_point_never_settles(env):
    with pytest.raises(RuntimeError, match="not on the target element"):
        env.d.click(Node("text_field", "SECRET", handle="job_link"))
    assert env.posted == []


def test_click_uses_centre_when_left_edge_is_covered(env, monkeypatch):
    """Greenhouse 2026-11-08: "Locate me" sat over the Location option's left edge; its centre was clear."""
    def covered_left(el, x, y, _):
        env.ax.hit_parent = "job_link" if x > 30 else None   # bounds (10, 10, 100, 20): left x=30, centre x=60
        return 0, "hit"
    monkeypatch.setattr(macos, "AXUIElementCopyElementAtPosition", covered_left)
    pts = []
    monkeypatch.setattr(macos.Q, "CGEventCreateMouseEvent", lambda src, t, pt, b: pts.append(pt) or ("mouse", t))
    env.d.click(Node("text", "SECRET", handle="job_link"))
    assert pts == [(60, 20)] * 3
