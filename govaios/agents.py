"""Coding agents under GOV-AIOS (Claude Code, OpenAI Codex): the policy, its approval text, the root-owned file
that wires the agent to GOV-AIOS, and starting a session. Shared by the CLI, the panel and the launch helper."""
import hashlib
import json
import os
import pwd
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import executor
from .approvals import Approvals


@dataclass(frozen=True)
class Agent:
    id: str            # approval and audit id
    title: str         # what the panel calls it
    slash: str         # Talk command: /claude, /codex
    policy: str        # executor policy, under the data home
    staged: str        # the wired file as staged under the data home for the root step
    managed: Path      # the root-owned file the agent reads
    places: tuple      # where its command usually is (relative: under the user's home)
    default_policy: Callable   # (*roots) -> policy text
    settings: Callable         # (pol, home) -> bytes of the managed file
    same: Callable             # (installed bytes, pol, home) -> bool

    @property
    def reason(self):
        return f"approve {self.title} executor policy"


def _claude_same(data, pol, home):
    from .hook import managed_settings
    return json.loads(data) == managed_settings(pol, home)   # a CLI-installed file may differ in spacing only


def _claude_settings(pol, home):
    from .hook import managed_settings
    return json.dumps(managed_settings(pol, home), indent=2).encode() + b"\n"


def _codex_settings(pol, home):
    from .codex import requirements
    return requirements(pol, home).encode()


def _codex_default(*roots):
    from .codex import default_policy
    return default_policy(*roots)


CLAUDE = Agent("claude_code", "Claude Code", "claude", executor.POLICY_PATH, "executors/managed-settings.json",
               Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
               (".local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"),
               executor.default_policy, _claude_settings, _claude_same)
CODEX = Agent("codex", "OpenAI Codex", "codex", "executors/codex.yaml", "executors/codex-requirements.toml",
              Path("/etc/codex/requirements.toml"),
              ("/opt/homebrew/bin/codex", "/usr/local/bin/codex", ".local/bin/codex"),
              _codex_default, _codex_settings, lambda data, pol, home: data == _codex_settings(pol, home))
AGENTS = {a.id: a for a in (CLAUDE, CODEX)}


def user_home() -> Path:
    return Path(pwd.getpwuid(os.getuid()).pw_dir)   # HOME is not trusted (like data_home)


def found(a: Agent) -> str | None:
    """Where the agent's command is installed, from the usual places; None if not found."""
    return next((str(p) for p in (user_home() / q for q in a.places) if os.access(p, os.X_OK)), None)


def draft(home: Path, roots, a: Agent = CLAUDE) -> tuple[Path, bytes, dict, str]:
    """(policy path, its bytes, the policy, digest). The existing policy if there is one (its folders win), else a
    new one for `roots`, not written until approved. ValueError with our own message if refused."""
    from .hook import bad_destination, bad_root
    path = Path(home) / a.policy
    if any(bad_root(r, home) for r in roots):
        raise ValueError("a project root equals, contains or sits inside a protected path")
    raw = path.read_bytes() if path.exists() else a.default_policy(*(os.path.realpath(r) for r in roots)).encode()
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


def question(path: Path, raw: bytes, a: Agent = CLAUDE) -> str:
    return f"Approve this {a.title} executor policy ({path})?\n\n" + raw.decode(errors="replace")


def commit(home: Path, path: Path, raw: bytes, digest: str, a: Agent = CLAUDE) -> None:
    """After approval: write the approved bytes if the policy is new, then record the approval."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("policy changed while it was being approved; try again")
    Approvals(Path(home) / "approvals.json").approve_flow(a.id, digest)


def stage(home: Path, pol, a: Agent = CLAUDE) -> str:
    """Write the managed file for the root step to copy; returns its sha256."""
    data = a.settings(pol, home)
    p = Path(home) / a.staged
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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


def load(home: Path, a: Agent = CLAUDE):
    return executor.load(home, a.policy)


def governed(home: Path, managed: Path, a: Agent = CLAUDE) -> tuple[bool, list]:
    """(governed, the policy's folders): an approved policy and a root-owned managed file that matches it."""
    try:
        pol, digest = load(home, a)
    except Exception:
        return False, []
    try:
        same = a.same(Path(managed).read_bytes(), pol, home)
    except (OSError, ValueError):
        same = False
    ok = Approvals(Path(home) / "approvals.json").flow_ok(a.id, digest) and root_owned(managed) and same
    return ok, pol.get("project_roots", [])


def tilde(p: str) -> str:
    uh = str(user_home())
    return "~" + p[len(uh):] if p == uh or p.startswith(uh + "/") else p


def suggest(roots, limit=60) -> list[str]:
    """Folders to offer for a new session: each approved folder and the folders directly inside it."""
    out = []
    for r in roots:
        out.append(r)
        try:
            out += sorted(e.path for e in os.scandir(r) if e.is_dir(follow_symlinks=False) and not e.name.startswith("."))
        except OSError:
            pass
    return list(dict.fromkeys(out))[:limit]


def inside(folder: str, roots) -> str | None:
    """The real folder if it is an existing folder in or under an approved one, else None."""
    real = os.path.realpath(folder)
    ok = os.path.isdir(real) and any(real == r or real.startswith(r.rstrip("/") + "/") for r in roots)
    return real if ok else None


def pick(text: str, roots) -> tuple[str | None, list[str]]:
    """What the admin typed -> (folder, []), or (None, candidates). `~/` is the user's home; a bare name matches
    the suggested folders by name (case ignored)."""
    if not text.strip():
        return None, suggest(roots)
    t = text.strip().rstrip("/*").rstrip("/") or text.strip()
    if t.startswith("~/") or t == "~":
        t = str(user_home()) + t[1:]
    if t.startswith("/"):
        hit = inside(t, roots)
        return (hit, []) if hit else (None, [])
    names = [s for s in suggest(roots) if os.path.basename(s).lower() == t.lower()]
    return (names[0], []) if len(names) == 1 else (None, names)


def launch_file(home: Path, folder: str, command: str, a: Agent = CLAUDE) -> Path:
    """A one-use Terminal .command that opens `folder` and runs the agent there (no Apple Events needed)."""
    import secrets
    import shlex
    d = Path(home) / "executors" / "launch"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = d / f"{a.slash}-{secrets.token_hex(8)}.command"
    body = f'#!/bin/sh\nrm -f -- "$0"\ncd -- {shlex.quote(folder)} || exit 1\nexec {shlex.quote(command)}\n'
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    return p
