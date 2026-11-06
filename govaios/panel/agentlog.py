"""panel.log for the login agent: steps and errors only, never content. Rotated at a cap; repeats throttled."""
import json
import os
import time
from pathlib import Path
from typing import TextIO


def open_log(home: Path, cap: int = 1_000_000) -> TextIO:
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = home / "panel.log"
    try:
        if p.stat().st_size > cap:
            os.replace(p, home / "panel.log.1")
    except FileNotFoundError:
        pass
    return os.fdopen(os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a", buffering=1)


def once(home: Path, line: str, now=time.time, every: float = 60) -> bool:
    """Append line to panel.log unless the same line went in less than `every` seconds ago."""
    home = Path(home)
    last = home / "panel.log.last"
    try:
        d = json.loads(last.read_text())
        if d["line"] == line and 0 <= now() - d["ts"] < every:
            return False
    except (OSError, ValueError, KeyError, TypeError):
        pass
    with open_log(home) as f:
        f.write(line + "\n")
    tmp = home / "panel.log.last.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"line": line, "ts": now()}, f)
    os.replace(tmp, last)
    return True
