"""Presence proof: the one place that proves the admin is at the Mac before any grant of power.

Anything but an explicit success is a deny, returned and never raised (only an unknown channel raises).
A new emergency stop (STOPPED appearing while a prompt waits) cancels it as deny within POLL_S (row 30).
A proof takes at most the 60 s deadline plus about 3 s (2 s lock wait, 2 s post-invalidate wait, 1 s osascript slack) (rows 4-8, 35, 36).
auth values: biometric, device_owner, failed, none, busy.
"""
import fcntl
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import LocalAuthentication as LA
import Quartz

from . import runstate

TIMEOUT_S = 60
LOCK_WAIT_S = 2
POLL_S = 0.2   # how often a waiting prompt checks for an emergency stop
CHANNELS = {"touch_id"}   # row 35: a paired-phone channel slots in here later


def _now() -> float:
    return time.monotonic()


def _cg_session_dict():
    return Quartz.CGSessionCopyCurrentDictionary()


def screen_locked() -> bool:
    """Row 8 / 52: missing dict, locked flag set, or not on console -> locked (fail closed)."""
    try:
        d = _cg_session_dict()
    except runstate.Stop:   # a run's emergency stop (SIGTERM) must end the run, not read as "locked"
        raise
    except Exception:
        return True
    if d is None:
        return True
    # `!= True` (not `is not True`) so an NSNumber 1 from the bridge still counts as on-console.
    return bool(d.get("CGSSessionScreenIsLocked")) or d.get(Quartz.kCGSessionOnConsoleKey) != True  # noqa: E712


def _never() -> bool:
    return False


def dialog(question: str, timeout_s: int, cancelled=_never) -> bool:
    """Native dialog; anything but an explicit Approve (incl. timeout or cancel) is a deny."""
    q = question.replace("\\", "\\\\").replace('"', '\\"')
    script = (f'display dialog "{q}" with title "GOV-AIOS approval" '
              f'buttons {{"Deny", "Approve"}} default button "Deny" giving up after {timeout_s}')
    try:
        p = subprocess.Popen(["osascript", "-e", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except (OSError, ValueError):   # ValueError: NUL byte in the question
        return False
    end = _now() + timeout_s + 1
    try:
        while True:
            try:
                out, _ = p.communicate(timeout=POLL_S)
                break
            except subprocess.TimeoutExpired:
                if cancelled() or _now() >= end:
                    return False
    finally:
        if p.poll() is None:   # cancel, deadline, or an exception (e.g. a run's SIGTERM): never leave the dialog up
            p.kill()
            p.communicate()
    return "button returned:Approve" in out and "gave up:true" not in out


def _la_evaluate(reason: str, deadline: float, cancelled=_never) -> str:
    """One Touch ID (or device-owner) prompt on a fresh LAContext; 'failed' unless the reply is ok in time."""
    try:
        return _la_prompt(reason, deadline, cancelled)
    except runstate.Stop:   # a run's emergency stop must not turn into a "failed" proof
        raise
    except Exception:   # any pyobjc error is a failed proof, never a raise
        return "failed"


def _la_prompt(reason: str, deadline: float, cancelled=_never) -> str:
    ctx = LA.LAContext.alloc().init()   # new context per prompt (row 4)
    ctx.setTouchIDAuthenticationAllowableReuseDuration_(0)
    if ctx.canEvaluatePolicy_error_(LA.LAPolicyDeviceOwnerAuthenticationWithBiometrics, None)[0]:
        policy, auth = LA.LAPolicyDeviceOwnerAuthenticationWithBiometrics, "biometric"
        ctx.setLocalizedFallbackTitle_("")   # hide "Enter Password" (row 6)
    elif ctx.canEvaluatePolicy_error_(LA.LAPolicyDeviceOwnerAuthentication, None)[0]:
        policy, auth = LA.LAPolicyDeviceOwnerAuthentication, "device_owner"
    else:
        return "failed"
    done, res = threading.Event(), {"ok": False}

    def reply(success, error):
        res["ok"] = bool(success) and error is None
        done.set()

    try:
        ctx.evaluatePolicy_localizedReason_reply_(policy, reason, reply)
        while not done.wait(max(0.0, min(POLL_S, deadline - _now()))):
            if not (cancelled() or _now() >= deadline):
                continue
            ctx.invalidate()   # row 51: the reply then arrives at once with -9; still bounded below
            done.wait(2)
            return "failed"
    except BaseException:   # e.g. a run's SIGTERM Stop: never leave the Touch ID prompt up (row 30)
        ctx.invalidate()
        raise
    return auth if res["ok"] else "failed"


def _gate(question, reason: str, home: Path, channel: str) -> tuple[bool, str]:
    if channel not in CHANNELS:
        raise ValueError(f"unknown presence channel: {channel}")
    if screen_locked():
        return False, "none"
    try:
        Path(home).mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(Path(home) / "ask.lock", os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)   # no symlink swap
    except (OSError, ValueError):
        return False, "none"
    with os.fdopen(fd, "w") as lock:   # held for the whole prompt; closing releases it
        until = _now() + LOCK_WAIT_S
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if _now() >= until:
                    return False, "busy"   # row 36: no stacked prompts
                time.sleep(0.05)
        deadline = _now() + TIMEOUT_S
        # Only a stop that starts while we wait cancels: resume proves while STOPPED already exists.
        watch = not runstate.stopped(home)

        def cancelled():
            return watch and runstate.stopped(home)
        if question is not None and not dialog(question, max(1, int(deadline - _now())), cancelled):
            return False, "none"
        if _now() >= deadline or cancelled():
            return False, "none"
        auth = _la_evaluate(reason, deadline, cancelled)
        if cancelled():
            return False, "none"
        return auth in ("biometric", "device_owner"), auth


def shown_digest(question, reason: str) -> str:
    """sha256 of exactly what the admin was shown: the dialog's question (None: no dialog) and the Touch ID reason."""
    return hashlib.sha256(json.dumps([question, reason]).encode()).hexdigest()


def prove(reason: str, home: Path, channel: str = "touch_id") -> tuple[bool, str]:
    """Presence proof with no dialog (resume, audit-ui, dump, powers review)."""
    return _gate(None, reason, home, channel)


def approve(question: str, reason: str, home: Path, channel: str = "touch_id") -> tuple[bool, str]:
    """Dialog with the full question, then on Approve a Touch ID proof with the short reason."""
    return _gate(question, reason, home, channel)
