"""Run bookkeeping, emergency stop, resume and the guard: exe paths, kill and sleep faked; no real signals to foreign pids."""
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from govaios import auth, guard, runstate
from govaios.audit.log import AuditLog

APP = runstate.APP_EXE
A, B = 99901, 99902   # fake pids: only ever passed to the fake kill


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    (h / "runs").mkdir(parents=True)
    return h


@pytest.fixture
def exe(monkeypatch):
    paths = {}
    monkeypatch.setattr(runstate, "_exe_path", lambda pid: paths.get(pid))
    return paths


def entries(home):
    return [json.loads(l) for l in (home / "audit.jsonl").read_text().splitlines()]


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: /sbin/launchd via libproc")
def test_is_govaios_reads_real_exe_path():
    assert runstate._exe_path(1) == "/sbin/launchd"   # read-only lookup, no signal
    assert runstate._exe_path(os.getpid()).startswith("/")
    assert runstate.is_govaios(os.getpid()) is False
    assert runstate._exe_path(99999999) is None   # above pid_max: never alive


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: SIGKILL")
def test_stop_terms_then_kills(home, exe):
    exe.update({A: APP, B: APP})
    for p in (A, B):
        (home / "runs" / str(p)).write_text("")
    sent = []

    def kill(pid, sig):
        sent.append((pid, sig))
        if pid == A:
            exe.pop(A)   # A exits on SIGTERM; B ignores it
    slept = []
    out = runstate.emergency_stop(home, AuditLog(home), kill=kill, sleep=slept.append)
    assert out == [(A, "stopped"), (B, "killed")]
    assert sent == [(A, signal.SIGTERM), (B, signal.SIGTERM), (B, signal.SIGKILL)] and slept == [3]
    assert runstate.stopped(home)
    e = entries(home)
    assert [(x["kind"], x["outcome"]) for x in e] == [("emergency_stop", "stopped"), ("emergency_stop", "killed")]
    assert all(x["reason"] == "runs stopped; new Claude tool calls denied; running Claude commands not stopped" for x in e)


def test_stop_skips_non_govaios_pid(home, exe):
    exe[A] = "/usr/bin/something-else"   # pid reused by another program
    (home / "runs" / str(A)).write_text("")
    sent = []
    assert runstate.emergency_stop(home, AuditLog(home), kill=lambda *a: sent.append(a), sleep=lambda s: None) == []
    assert sent == [] and runstate.stopped(home)
    assert [x["kind"] for x in entries(home)] == ["emergency_stop"]   # the press itself is still audited


def test_register_run_collects_stale_entries(home, exe):
    exe[A] = "/bin/zsh"   # live, not gov-aios; B is dead (no exe path)
    for p in (A, B):
        (home / "runs" / str(p)).write_text("")
    path = runstate.register_run(home)
    assert path == home / "runs" / str(os.getpid())
    assert sorted(os.listdir(home / "runs")) == [str(os.getpid())]
    runstate.unregister_run(home)
    assert os.listdir(home / "runs") == []


def test_live_runs(home, exe):
    exe.update({A: APP, B: "/bin/zsh"})
    for p in (A, B, 99903):
        (home / "runs" / str(p)).write_text("")
    (home / "runs" / "junk").write_text("")
    assert runstate.live_runs(home) == [A]


def test_reused_guard_pid_is_not_alive(home, exe):
    assert runstate.guard_alive(home) is False   # no guard.pid
    (home / "guard.pid").write_text(str(A))
    exe[A] = "/bin/zsh"
    assert runstate.guard_alive(home) is False
    exe[A] = APP
    assert runstate.guard_alive(home) is True
    (home / "guard.pid").write_text("garbage")
    assert runstate.guard_alive(home) is False


def test_resume_needs_proof(home, monkeypatch):
    (home / "STOPPED").write_text("")
    seen = []
    monkeypatch.setattr(auth, "prove", lambda reason, h: (seen.append(reason), (False, "failed"))[1])
    assert runstate.resume(home, AuditLog(home)) is False
    assert runstate.stopped(home) and seen == ["resume gov-aios"]
    monkeypatch.setattr(auth, "prove", lambda reason, h: (True, "biometric"))
    assert runstate.resume(home, AuditLog(home)) is True
    assert not runstate.stopped(home)
    e = entries(home)
    assert [(x["kind"], x["auth"]) for x in e] == [("resume", "failed"), ("resume", "biometric")]


def test_guard_writes_pid_only_after_registration(home, monkeypatch, capsys):
    monkeypatch.setattr(guard, "_register", lambda on_press: -9878)
    monkeypatch.setattr(guard, "_run_loop", lambda: pytest.fail("loop must not start"))
    assert guard.main(home) == 1
    assert not (home / "guard.pid").exists()
    assert "-9878" in capsys.readouterr().err


def test_guard_press_runs_emergency_stop(home, monkeypatch):
    calls = []
    monkeypatch.setattr(runstate, "emergency_stop", lambda h, audit: calls.append(h))
    guard._on_press(home)
    assert calls == [home]


CHILD = """
import sys
from pathlib import Path
from govaios import guard
guard._register = lambda on_press: 0   # no real Carbon hotkey
sys.exit(guard.main(Path(sys.argv[1])))
"""


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: SIGTERM guard; Windows guard in Task 9")
def test_guard_exits_on_sigterm_and_removes_pid(home):
    """Row 53: SIGTERM must reach Python while the guard sits in the NSApplication run loop."""
    with subprocess.Popen([sys.executable, "-c", CHILD, str(home)], stderr=subprocess.PIPE, text=True) as p:
        try:
            for _ in range(100):
                if (home / "guard.pid").exists():
                    break
                time.sleep(0.1)
            assert (home / "guard.pid").read_text() == str(p.pid)
            time.sleep(0.5)   # let it settle into the run loop
            p.send_signal(signal.SIGTERM)
            assert p.wait(3) == 0, p.stderr.read()
            assert not (home / "guard.pid").exists()
        finally:
            if p.poll() is None:
                p.kill()


def test_register_run_keeps_entry_created_during_scan(home, monkeypatch):
    """Fix 1: a run that registers while another run's GC scans is never deleted."""
    (home / "runs" / str(A)).write_text("")   # dead entry the scan visits

    def is_govaios(pid):
        (home / "runs" / str(B)).write_text("")   # run B registers mid-scan
        return pid == B
    monkeypatch.setattr(runstate, "is_govaios", is_govaios)
    runstate.register_run(home)
    assert sorted(os.listdir(home / "runs")) == sorted([str(B), str(os.getpid())])


@pytest.mark.skipif(sys.platform == "win32", reason="Windows: covered by Task 6")
def test_stop_never_signals_self_and_clears_handled_entries(home, exe):
    me = os.getpid()
    exe.update({A: APP, B: APP, me: APP})
    for p in (A, B, me):
        (home / "runs" / str(p)).write_text("")
    sent = []

    def kill(pid, sig):
        sent.append((pid, sig))
        if pid == A:
            exe.pop(A)
    out = runstate.emergency_stop(home, AuditLog(home), kill=kill, sleep=lambda s: None)
    assert out == [(A, "stopped"), (B, "killed")] and all(p != me for p, _ in sent)
    assert os.listdir(home / "runs") == [str(me)]   # a reused A or B is never signalled by a later press
