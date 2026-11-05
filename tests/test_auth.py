"""Presence proof with every dialog, LocalAuthentication and Quartz call mocked: no real prompt or sheet."""
import fcntl
import itertools
import types

import pytest

from govaios import auth
from govaios.audit.log import AuditError, AuditLog

UNLOCKED = {auth.Quartz.kCGSessionOnConsoleKey: True}


class Calls:
    def __init__(self, dialog=True, la="biometric"):
        self.dialog_ret, self.la_ret = dialog, la
        self.dialog, self.la = [], []

    def fake_dialog(self, question, timeout_s):
        self.dialog.append((question, timeout_s))
        return self.dialog_ret

    def fake_la(self, reason, deadline):
        self.la.append((reason, deadline))
        return self.la_ret


@pytest.fixture
def calls(monkeypatch):
    c = Calls()
    monkeypatch.setattr(auth, "dialog", c.fake_dialog)
    monkeypatch.setattr(auth, "_la_evaluate", c.fake_la)
    monkeypatch.setattr(auth, "_cg_session_dict", lambda: UNLOCKED)
    return c


@pytest.fixture
def home(tmp_path):
    return tmp_path


@pytest.mark.parametrize("session", [
    {"CGSSessionScreenIsLocked": True, auth.Quartz.kCGSessionOnConsoleKey: True},
    None,
    {auth.Quartz.kCGSessionOnConsoleKey: False},
    {},
])
def test_locked_screen_denies_without_prompt(calls, home, monkeypatch, session):
    monkeypatch.setattr(auth, "_cg_session_dict", lambda: session)
    assert auth.approve("q?", "approve: f a", home) == (False, "none")
    assert auth.prove("resume", home) == (False, "none")
    assert calls.dialog == [] and calls.la == []


def test_unlocked_session_is_not_locked(monkeypatch):
    monkeypatch.setattr(auth, "_cg_session_dict", lambda: UNLOCKED)
    assert auth.screen_locked() is False


def test_dialog_deny_skips_touch_id(calls, home):
    calls.dialog_ret = False
    assert auth.approve("Allow x?", "approve: f a", home) == (False, "none")
    assert calls.dialog[0][0] == "Allow x?" and calls.la == []


@pytest.mark.parametrize("la,expected", [
    ("biometric", (True, "biometric")),
    ("device_owner", (True, "device_owner")),
    ("failed", (False, "failed")),
])
def test_approve_then_biometric(calls, home, la, expected):
    calls.la_ret = la
    assert auth.approve("q?", "approve: f a", home) == expected
    assert calls.la[0][0] == "approve: f a"


def test_one_deadline_covers_dialog_and_touch_id(calls, home, monkeypatch):
    monkeypatch.setattr(auth, "_now", lambda: 1000.0)
    auth.approve("q?", "r", home)
    assert calls.dialog[0][1] == 60 and calls.la[0][1] == 1060.0


def test_prove_has_no_dialog(calls, home):
    assert auth.prove("resume", home) == (True, "biometric")
    assert calls.dialog == [] and calls.la[0][0] == "resume"


class FakeLA:
    """Stands in for the LocalAuthentication module; records what the context was asked."""
    LAPolicyDeviceOwnerAuthenticationWithBiometrics = 1
    LAPolicyDeviceOwnerAuthentication = 2

    def __init__(self, can=(1, 2), reply=None):
        self.can, self.reply = can, reply   # reply: None = never answers, else (success, error)
        self.ctxs = []
        self.answer_on_invalidate = True
        la = self

        class Ctx:
            @classmethod
            def alloc(cls):
                return cls()

            def init(self):
                self.reuse = self.fallback = self.policy = None
                self.invalidated = False
                la.ctxs.append(self)
                return self

            def setTouchIDAuthenticationAllowableReuseDuration_(self, v):
                self.reuse = v

            def setLocalizedFallbackTitle_(self, v):
                self.fallback = v

            def canEvaluatePolicy_error_(self, p, _):
                return p in la.can, None

            def evaluatePolicy_localizedReason_reply_(self, p, reason, block):
                self.policy, self.reason, self.block = p, reason, block
                if la.reply is not None:
                    block(*la.reply)

            def invalidate(self):
                self.invalidated = True
                if la.reply is None and la.answer_on_invalidate:   # row 51: reply arrives at once with -9
                    self.block(False, types.SimpleNamespace(code=lambda: -9))

        self.LAContext = Ctx


def test_no_reply_is_deny_after_timeout(monkeypatch):
    la = FakeLA(reply=None)
    monkeypatch.setattr(auth, "LA", la)
    monkeypatch.setattr(auth, "_now", lambda: 2000.0)
    assert auth._la_evaluate("r", deadline=1060.0) == "failed"
    assert la.ctxs[0].invalidated and la.ctxs[0].reuse == 0


def test_no_reply_even_after_invalidate_is_bounded(monkeypatch):
    la = FakeLA(reply=None)
    la.answer_on_invalidate = False
    monkeypatch.setattr(auth, "LA", la)
    monkeypatch.setattr(auth, "_now", lambda: 2000.0)
    assert auth._la_evaluate("r", deadline=1060.0) == "failed"   # returns after the bounded 2 s wait


def test_policy_choice(monkeypatch):
    monkeypatch.setattr(auth, "_now", lambda: 0.0)
    la = FakeLA(can=(1, 2), reply=(True, None))
    monkeypatch.setattr(auth, "LA", la)
    assert auth._la_evaluate("r", 60.0) == "biometric"
    assert la.ctxs[0].policy == 1 and la.ctxs[0].fallback == "" and la.ctxs[0].reason == "r"

    la = FakeLA(can=(2,), reply=(True, None))
    monkeypatch.setattr(auth, "LA", la)
    assert auth._la_evaluate("r", 60.0) == "device_owner"
    assert la.ctxs[0].policy == 2

    la = FakeLA(can=(), reply=(True, None))
    monkeypatch.setattr(auth, "LA", la)
    assert auth._la_evaluate("r", 60.0) == "failed"
    assert la.ctxs[0].policy is None


def test_non_ok_reply_is_failed(monkeypatch):
    monkeypatch.setattr(auth, "_now", lambda: 0.0)
    err = types.SimpleNamespace(code=lambda: -2)
    monkeypatch.setattr(auth, "LA", FakeLA(reply=(False, err)))
    assert auth._la_evaluate("r", 60.0) == "failed"


def test_new_context_per_prompt(monkeypatch):
    monkeypatch.setattr(auth, "_now", lambda: 0.0)
    la = FakeLA(reply=(True, None))
    monkeypatch.setattr(auth, "LA", la)
    auth._la_evaluate("r", 60.0)
    auth._la_evaluate("r", 60.0)
    assert len(la.ctxs) == 2 and la.ctxs[0] is not la.ctxs[1]


def test_second_prompt_denied_when_busy(calls, home, monkeypatch):
    clock = itertools.count(0, 0.5)
    monkeypatch.setattr(auth, "_now", lambda: next(clock))
    with open(home / "ask.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert auth.approve("q?", "r", home) == (False, "busy")
        assert calls.dialog == [] and calls.la == []
    assert auth.approve("q?", "r", home) == (True, "biometric")
    assert len(calls.dialog) == 1


def test_unknown_channel_rejected(calls, home):
    with pytest.raises(ValueError):
        auth.approve("q?", "r", home, channel="phone")
    with pytest.raises(ValueError):
        auth.prove("r", home, channel="phone")


def test_dialog_escapes_and_defaults_to_deny(monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen["script"] = cmd[2]
        return types.SimpleNamespace(stdout="button returned:Approve, gave up:false\n")

    monkeypatch.setattr(auth.subprocess, "run", run)
    assert auth.dialog('say "hi" \\ now', 60) is True
    s = seen["script"]
    assert 'say \\"hi\\" \\\\ now' in s and 'default button "Deny"' in s and "giving up after 60" in s

    monkeypatch.setattr(auth.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(stdout="button returned:, gave up:true\n"))
    assert auth.dialog("q", 60) is False


def test_audit_accepts_new_kinds_and_fields(home):
    log = AuditLog(home)
    log.append("resume", auth="biometric")
    log.append("request", command="git status")
    for k in ("emergency_stop", "revoke", "ui_login", "powers_review"):
        log.append(k)
    with pytest.raises(AuditError):
        log.append("request", bogus="x")
