"""Claude Code, governed: the policy, its approval text and the managed settings, shared by the CLI's
`claude-settings` and the panel's Claude Code setup."""
import hashlib
import json
import os
import pwd
from pathlib import Path

from . import executor
from .approvals import Approvals
from .hook import ID, bad_destination, bad_root, managed_settings

REASON = "approve Claude Code executor policy"
STAGED = "executors/managed-settings.json"   # under the data home; the root step copies it if its digest matches
PLACES = (".local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")


def user_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)   # HOME is not trusted (like data_home)


def found() -> str | None:
    """Where Claude Code is installed, from the usual places; None if not found."""
    return next((str(p) for p in (user_home() / q for q in PLACES) if os.access(p, os.X_OK)), None)


def draft(home: Path, roots) -> tuple[Path, bytes, dict, str]:
    """(policy path, its bytes, the policy, digest). The existing policy if there is one (its folders win), else a
    new one for `roots`, not written until approved. ValueError with our own message if refused."""
    path = Path(home) / executor.POLICY_PATH
    if any(bad_root(r, home) for r in roots):
        raise ValueError("a project root equals, contains or sits inside a protected path")
    raw = path.read_bytes() if path.exists() else executor.default_policy(*(os.path.realpath(r) for r in roots)).encode()
    try:
        pol, digest = executor.parse(raw)
    except ValueError as e:   # our own message: field names only
        raise ValueError(f"{path}: {e}") from None
    if not pol.get("project_roots") or any(bad_root(r, home) for r in pol["project_roots"]):
        raise ValueError(f"{path} needs project_roots, none inside or above a protected path")
    dests = pol.get("destinations")
    if not isinstance(dests, list) or any(bad_destination(d) for d in dests):
        raise ValueError(f"{path} destinations must be bare host names (e.g. github.com)")
    return path, raw, pol, digest


def question(path: Path, raw: bytes) -> str:
    return f"Approve this Claude Code executor policy ({path})?\n\n" + raw.decode(errors="replace")


def commit(home: Path, path: Path, raw: bytes, digest: str) -> None:
    """After approval: write the approved bytes if the policy is new, then record the approval."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("policy changed while it was being approved; try again")
    Approvals(Path(home) / "approvals.json").approve_flow(ID, digest)


def settings_bytes(pol, home: Path) -> bytes:
    return json.dumps(managed_settings(pol, home), indent=2).encode() + b"\n"


def stage(home: Path, pol) -> str:
    """Write the managed settings for the root step to copy; returns their sha256."""
    data = settings_bytes(pol, home)
    p = Path(home) / STAGED
    tmp = p.with_name(p.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, p)
    return hashlib.sha256(data).hexdigest()


def root_owned(path: Path) -> bool:
    try:
        st = Path(path).stat()   # follows a link: who can change the content is what counts
    except OSError:
        return False
    return st.st_uid == 0 and st.st_mode & 0o022 == 0


def governed(home: Path, managed: Path) -> tuple[bool, list]:
    """(governed, the policy's folders): an approved policy and root-owned managed settings that match it."""
    try:
        pol, digest = executor.load(home)
    except Exception:
        return False, []
    try:   # the whole file, not just the hook's allowedDomains check (drift)
        same = json.loads(Path(managed).read_text()) == managed_settings(pol, home)
    except (OSError, ValueError):
        same = False
    ok = Approvals(Path(home) / "approvals.json").flow_ok(ID, digest) and root_owned(managed) and same
    return ok, pol.get("project_roots", [])
