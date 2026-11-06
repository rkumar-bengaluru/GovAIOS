import http.client
import os
import re
from http.cookies import SimpleCookie
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from govaios import sandbox


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


WORD = re.compile(r"<b class=word>([ABCDEFGHJKLMNPQRSTUVWXYZ]{4})</b>")


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
    """GET / signed out: (page body, pre token from the form, pre cookie value, shown code word)."""
    s, body, r = _raw(port, "GET", "/", cookie)
    pre = re.search(r"name=pre value='([^']+)'", body)[1]
    return body, pre, SimpleCookie(r.getheader("Set-Cookie"))["pre"].value, WORD.search(body)[1]


def _signin_post(port, cookie_pre, field_pre, headers=None):
    return _raw(port, "POST", "/signin", f"pre={cookie_pre}", {"pre": field_pre}, headers)


@pytest.fixture
def ui(monkeypatch):
    """Panel page helpers. ui.signin(srv): GET /, then POST /signin with its pre pair while Touch ID is faked
    as approved (only for that one POST); returns the s cookie."""
    from govaios import auth

    def signin(srv):
        port = srv.server_address[1]
        _, pre, ck, _ = _signed_out(port)
        with monkeypatch.context() as m:
            m.setattr(auth, "prove", lambda r, h, **k: (True, "biometric"))
            r = _signin_post(port, ck, pre)[2]
        return SimpleCookie(r.getheader("Set-Cookie"))["s"].value
    return SimpleNamespace(raw=_raw, signed_out=_signed_out, signin_post=_signin_post, signin=signin, WORD=WORD)
