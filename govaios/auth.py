"""Presence proof: the one place that proves the admin is at the Mac before any grant of power.

Anything but an explicit success is a deny, returned and never raised (only an unknown channel raises).
A proof takes at most the 60 s deadline plus about 3 s (2 s lock wait, 2 s post-invalidate wait, 1 s osascript slack) (rows 4-8, 35, 36).
auth values: biometric, device_owner, failed, none, busy.
"""
import fcntl
import os
import subprocess
import threading
import time
from pathlib import Path

import LocalAuthentication as LA
import Quartz

TIMEOUT_S = 60
LOCK_WAIT_S = 2
CHANNELS = {"touch_id"}   # row 35: a paired-phone channel slots in here later


def _now() -> float:
    return time.monotonic()


def _cg_session_dict():
    return Quartz.CGSessionCopyCurrentDictionary()


def screen_locked() -> bool:
    """Row 8 / 52: missing dict, locked flag set, or not on console -> locked (fail closed)."""
    try:
        d = _cg_session_dict()
    except Exception:
        return True
    if d is None:
        return True
    # `!= True` (not `is not True`) so an NSNumber 1 from the bridge still counts as on-console.
    return bool(d.get("CGSSessionScreenIsLocked")) or d.get(Quartz.kCGSessionOnConsoleKey) != True  # noqa: E712


def dialog(question: str, timeout_s: int) -> bool:
    """Native dialog; anything but an explicit Approve (incl. timeout) is a deny."""
    q = question.replace("\\", "\\\\").replace('"', '\\"')
    script = (f'display dialog "{q}" with title "GOV-AIOS approval" '
              f'buttons {{"Deny", "Approve"}} default button "Deny" giving up after {timeout_s}')
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout_s + 1)
    except (subprocess.TimeoutExpired, OSError, ValueError):   # ValueError: NUL byte in the question
        return False
    return "button returned:Approve" in r.stdout and "gave up:true" not in r.stdout


def _la_evaluate(reason: str, deadline: float) -> str:
    """One Touch ID (or device-owner) prompt on a fresh LAContext; 'failed' unless the reply is ok in time."""
    try:
        return _la_prompt(reason, deadline)
    except Exception:   # any pyobjc error is a failed proof, never a raise
        return "failed"


def _la_prompt(reason: str, deadline: float) -> str:
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

    ctx.evaluatePolicy_localizedReason_reply_(policy, reason, reply)
    if not done.wait(max(0.0, deadline - _now())):
        ctx.invalidate()   # row 51: the reply then arrives at once with -9; still bounded below
        done.wait(2)
        return "failed"
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
        if question is not None and not dialog(question, max(1, int(deadline - _now()))):
            return False, "none"
        if _now() >= deadline:
            return False, "none"
        auth = _la_evaluate(reason, deadline)
        return auth in ("biometric", "device_owner"), auth


def prove(reason: str, home: Path, channel: str = "touch_id") -> tuple[bool, str]:
    """Presence proof with no dialog (resume, audit-ui, dump, powers review)."""
    return _gate(None, reason, home, channel)


def approve(question: str, reason: str, home: Path, channel: str = "touch_id") -> tuple[bool, str]:
    """Dialog with the full question, then on Approve a Touch ID proof with the short reason."""
    return _gate(question, reason, home, channel)
