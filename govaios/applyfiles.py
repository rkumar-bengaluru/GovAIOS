"""Job-apply hand-off files in the data home's apply/ dir (bank, ask, reply, result). Values are never logged."""
import json
import os
import stat
from pathlib import Path

APPLY_DIR = "apply"
BANK = "apply/answers.yaml"
ASK = "apply/ask.json"
REPLY = "apply/reply.json"
RESULT = "apply/result.json"
TASKS = "apply/tasks.json"       # JobLens: one task per job, its status and counts (labels only, never values)
SANDBOX = "apply/sandbox.json"   # web sandbox: the pages captured so far
# a card the run shows on the panel, and the only replies each kind accepts
CARDS = {"fix": ("continue", "skip"), "review": ("next", "end"), "stopped": ("next", "end"), "sandbox": ("capture", "done")}
MAX = 64 * 1024


def _dir(home):
    d = Path(home) / APPLY_DIR
    if d.is_symlink():
        raise OSError("apply dir is a symlink")
    d.mkdir(mode=0o700, exist_ok=True)
    if not stat.S_ISDIR(os.lstat(d).st_mode):
        raise OSError("apply dir is not a directory")
    os.chmod(d, 0o700)
    return d


def write_json(home, name, obj):
    p = _dir(home).parent / name
    p.unlink(missing_ok=True)   # also drops a planted symlink rather than following it
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)


def read_json(home, name):
    try:
        if (Path(home) / APPLY_DIR).is_symlink():
            return None
        fd = os.open(Path(home) / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX:
            return None
        try:
            obj = json.loads(f.read(MAX + 1))
        except ValueError:
            return None
    return obj if isinstance(obj, dict) else None


def remove(home, *names):
    for n in names:
        (Path(home) / n).unlink(missing_ok=True)
