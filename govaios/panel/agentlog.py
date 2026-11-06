"""panel.log for the login agent: steps and errors only, never content. Rotated at a cap; repeats throttled."""
import json
import os
import time
from pathlib import Path
from typing import TextIO

CAP = 1_000_000


def _append(p: Path) -> TextIO:
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)   # a file made earlier with looser bits
    return os.fdopen(fd, "a", buffering=1)


def open_log(home: Path, cap: int = CAP) -> TextIO:
    """Rotate once, at startup, then hold the log. Nothing else rotates it while the process runs."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = home / "panel.log"
    try:
        if p.stat().st_size > cap:
            os.replace(p, home / "panel.log.1")
            os.chmod(home / "panel.log.1", 0o600)
    except FileNotFoundError:
        pass
    return _append(p)


def once(home: Path, line: str, now=time.time, every: float = 60, cap: int = CAP) -> bool:
    """Append line to panel.log unless the same line went in less than `every` seconds ago, or the log is at the cap."""
    home = Path(home)
    last = home / "panel.log.last"
    try:
        d = json.loads(last.read_text())
        if d["line"] == line and 0 <= now() - d["ts"] < every:
            return False
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        if (home / "panel.log").stat().st_size >= cap:
            return False   # rotation happens at startup only; a running panel never grows the file past the cap
    except FileNotFoundError:
        pass
    with _append(home / "panel.log") as f:   # same inode the process holds; never rotates
        f.write(line + "\n")
    tmp = home / "panel.log.last.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"line": line, "ts": now()}, f)
    os.replace(tmp, last)
    return True
