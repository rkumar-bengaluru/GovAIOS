import http.client
import os
import re
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from govaios import sandbox
from govaios.desktop import Node


@pytest.fixture(autouse=True)
def govaios_home(tmp_path, monkeypatch):
    home = tmp_path / "govaios-home"
    monkeypatch.setenv("GOVAIOS_HOME", str(home))
    yield home
    # The audit log is UF_APPEND; clear flags under this test's tmp_path only (some tests use it as Runner home).
    for root, dirs, files in os.walk(tmp_path):
        for n in dirs + files:
            os.chflags(os.path.join(root, n), 0, follow_symlinks=False)


@pytest.fixture(autouse=True)
def sandbox_calls(monkeypatch):
    """sandbox_init cannot be undone: never in the pytest process (row 28). Child-process tests use the real one."""
    calls = []
    monkeypatch.setattr(sandbox, "apply", calls.append)
    return calls


def _no_touch_id(*a, **k):
    raise AssertionError("real Touch ID called in a test")


@pytest.fixture(autouse=True)
def no_real_touch_id(request, monkeypatch):
    """No test can open a real Touch ID sheet; tests that need prove/approve monkeypatch over this.
    test_auth is exempt: it tests prove/approve themselves, with LocalAuthentication and the dialog faked."""
    if request.module.__name__ != "test_auth":
        from govaios import auth
        monkeypatch.setattr(auth, "prove", _no_touch_id)
        monkeypatch.setattr(auth, "approve", _no_touch_id)


WORD = re.compile(r"sign in to the GOV-AIOS panel, code ([ABCDEFGHJKLMNPQRSTUVWXYZ]{4})$")   # in the Touch ID reason only


def _raw(port, method, path, cookie="", body=None, headers=None):
    """One request with a raw Cookie header: (status, body, response)."""
    c = http.client.HTTPConnection("127.0.0.1", port)
    h = {**({"Cookie": cookie} if cookie else {}), **(headers or {})}
    if body is not None:
        h["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, body=urlencode(body) if body is not None else None, headers=h)
    r = c.getresponse()
    return r.status, r.read().decode(), r


def _signed_out(port, cookie=""):
    """GET / signed out: (page body, pre token from the form, pre cookie value)."""
    s, body, r = _raw(port, "GET", "/", cookie)
    pre = re.search(r"name=pre value='([^']+)'", body)[1]
    return body, pre, SimpleCookie(r.getheader("Set-Cookie"))["pre"].value


def _signin_post(port, cookie_pre, field_pre, headers=None):
    return _raw(port, "POST", "/signin", f"pre={cookie_pre}", {"pre": field_pre}, headers)


def _code_post(port, t, word, field_t=None, headers=None):
    """POST /signin/code with the t cookie from a Touch ID-approved /signin and the typed word."""
    return _raw(port, "POST", "/signin/code", f"t={t}" if t else "", {"t": t if field_t is None else field_t, "word": word}, headers)


def _t(r):
    """The t cookie a Touch ID-approved /signin set, else None."""
    c = r.getheader("Set-Cookie")
    return SimpleCookie(c)["t"].value if c and c.startswith("t=") else None


def _s(r):
    """The s cookie a finished sign-in set, else None."""
    c = SimpleCookie(r.getheader("Set-Cookie") or "")
    return c["s"].value if "s" in c else None


@pytest.fixture
def ui(monkeypatch):
    """Panel page helpers. ui.signin(srv): GET /, then POST /signin with its pre pair while Touch ID is faked
    as approved (only for that one POST), then POST /signin/code with the word from that prompt; returns the s cookie."""
    from govaios import auth

    def signin(srv):
        port = srv.server_address[1]
        _, pre, ck = _signed_out(port)
        seen = []
        with monkeypatch.context() as m:
            m.setattr(auth, "prove", lambda r, h, **k: (seen.append(r), (True, "biometric"))[1])
            r = _signin_post(port, ck, pre)[2]
        return _s(_code_post(port, _t(r), WORD.search(seen[0])[1])[2])
    return SimpleNamespace(raw=_raw, signed_out=_signed_out, signin_post=_signin_post, signin=signin, WORD=WORD,
                           code_post=_code_post, t=_t, s=_s)


ACCT = "test@example.invalid"


def N(role, name="", **kw):
    return Node(role, name, **kw)


def google_home():
    return N("document", "Google", children=[
        N("link", "Gmail"), N("popup_button", f"Google Account: Tester ({ACCT})")])


def matches():
    card = N("article", children=[N("link", "SECRET-TITLE"), N("link", "SECRET-CO Verified"),
                                  N("link", "View job"), N("time", children=[N("text", "2d ago")])])
    return N("document", "Your matches | Himalayas", children=[
        N("heading", "Your matches"), N("banner"),
        N("group", dom_id="job-search-results", children=[card])])


def detail():
    return N("document", "SECRET-CO hiring SECRET-TITLE | Himalayas", children=[
        N("main", children=[N("heading", "SECRET-TITLE"), N("link", "SECRET-CO"),
                            N("article", children=[N("text", "SECRET-DESCRIPTION")])]),
        N("heading", "Apply now")])


class FakeDesktop:
    """Canned trees; records instead of sending input. Never touches the OS."""

    def __init__(self, answers):
        self.answers, self.calls, self.url, self.typed = list(answers), [], "about:blank", ""
        FakeDesktop.current = self

    def activate(self, app):
        self.calls.append("activate")

    def focused_window_id(self, app):
        return "win1"

    def pin_window(self, token):
        self.calls.append(("pin", token))

    def launch_application(self, app, profile=None):
        self.calls.append("launch")

    def press(self, key):
        self.calls.append(key)
        if key == "enter":
            self.url = self.typed
        elif key == "browser_back":
            self.url = "https://himalayas.app/jobs/matches"

    def type_text(self, t):
        self.typed = t

    def scroll_into_view(self, node):
        self.calls.append("scroll")

    # Form input primitives: record the target, never the text or path.
    def type_into(self, node, text):
        self.calls.append(("type_into", getattr(node, "dom_id", None) or node.name))

    def focused_is(self, node):
        return True

    def raise_pinned(self):
        self.calls.append("raise_pinned")

    def menu_open(self):
        return False

    def choose_file(self, path):
        self.calls.append(("choose_file",))

    def click(self, node):
        self.calls.append("click")
        self.url = "https://himalayas.app/jobs/secret-title"

    def current_url(self, app):
        return self.url + ("?utm=x" if "himalayas" in self.url else "")

    def window_title(self, app):
        return "x"

    def web_root(self, app):
        if "google.com" in self.url:
            return google_home()
        return detail() if "/jobs/secret" in self.url else matches()
