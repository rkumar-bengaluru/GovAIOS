"""Run bookkeeping, emergency stop and resume (rows 10-12, 29, 30).

Data-home files: STOPPED (persisted stop flag), guard.pid, runs/<pid> (one per live run).
A pid counts only if its executable is the installed app, so a reused pid is never trusted or signalled.
No import of auth at module level: auth imports this module (resume imports auth inside).
Stop lives here (not in engine) so auth can let a run's emergency-stop Stop pass without an import cycle.
"""
import ctypes
import os
import signal
import time
from pathlib import Path

APP_EXE = "/Applications/gov-aios.app/Contents/MacOS/gov-aios"
STOP_REASON = "runs stopped; new Claude tool calls denied; running Claude commands not stopped"   # row 30, verbatim
KILL_AFTER_S = 3

class Stop(Exception):
    """Flow stopped: unexpected state, denial, or admin needed (Rule 2). Re-exported as engine.Stop."""


_libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
_libproc.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
_libproc.proc_pidpath.restype = ctypes.c_int
_PATH_MAX = 4 * 1024   # PROC_PIDPATHINFO_MAXSIZE


def _exe_path(pid: int) -> str | None:
    """Executable path of a live pid, None if it is gone (no /bin/ps: setuid exec is denied in the sandbox, row 49)."""
    buf = ctypes.create_string_buffer(_PATH_MAX)
    n = _libproc.proc_pidpath(pid, buf, _PATH_MAX)
    return buf.value.decode(errors="replace") if n > 0 else None


def is_govaios(pid: int) -> bool:
    return _exe_path(pid) == APP_EXE


def _pid_in(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def guard_alive(home: Path) -> bool:
    # shortcut: a dead guard's pid reused by another gov-aios process (e.g. a run) passes; plan-mandated check.
    pid = _pid_in(Path(home) / "guard.pid")
    return pid is not None and is_govaios(pid)


def stopped(home: Path) -> bool:
    return (Path(home) / "STOPPED").exists()


def live_runs(home: Path) -> list[int]:
    runs = Path(home) / "runs"
    pids = sorted(int(n) for n in os.listdir(runs) if n.isdigit()) if runs.is_dir() else []
    return [p for p in pids if is_govaios(p)]


def register_run(home: Path) -> Path:
    runs = Path(home) / "runs"
    runs.mkdir(parents=True, exist_ok=True, mode=0o700)
    for n in os.listdir(runs):   # one decision per entry: a run registering meanwhile is never removed
        if not (n.isdigit() and is_govaios(int(n))):
            (runs / n).unlink(missing_ok=True)
    me = runs / str(os.getpid())
    me.write_text("")
    return me


def unregister_run(home: Path) -> None:
    (Path(home) / "runs" / str(os.getpid())).unlink(missing_ok=True)


def _send(kill, pid, sig):
    try:
        kill(pid, sig)
    except ProcessLookupError:
        pass


def emergency_stop(home: Path, audit, kill=os.kill, sleep=time.sleep) -> list[tuple[int, str]]:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    (home / "STOPPED").touch()   # first: from here on no run starts and the hook denies
    pids = [p for p in live_runs(home) if p != os.getpid()]   # never signal ourselves
    for p in pids:
        _send(kill, p, signal.SIGTERM)
    if pids:
        sleep(KILL_AFTER_S)
    out = []
    for p in pids:
        if is_govaios(p):   # still there (and still ours) after the grace period
            _send(kill, p, signal.SIGKILL)
            out.append((p, "killed"))
        else:
            out.append((p, "stopped"))
        (home / "runs" / str(p)).unlink(missing_ok=True)   # handled: a later press never signals a reused pid
    for p, outcome in out:
        audit.append("emergency_stop", target=str(p), outcome=outcome, reason=STOP_REASON)
    if not out:
        audit.append("emergency_stop", reason=STOP_REASON)   # the press itself is always on record
    return out


def resume(home: Path, audit) -> bool:
    from . import auth
    ok, how = auth.prove("resume gov-aios", home)
    if ok:
        (Path(home) / "STOPPED").unlink(missing_ok=True)
    audit.append("resume", decision="allow" if ok else "deny", approver="admin", channel="touch_id", auth=how)
    return ok
