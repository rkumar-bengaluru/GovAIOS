"""OpenAI Codex under GOV-AIOS: the requirements.toml that wires it, and its PreToolUse hook (`gov-aios codex-hook`).

Codex sends Bash (shell), apply_patch (file edits; the patch is in tool_input.command) and mcp__* (plugins) to the
hook. Same decisions as Claude Code's hook: allow, deny, or GOV-AIOS's own dialog plus Touch ID. Codex's docs say a
hook that errors or times out can let the call run, so the hook always answers, and the dialog (about 60 s) ends
well inside the hook timeout. Allow = exit 0 and no output; deny = exit 2 with the reason on stderr.
"""
import json
import os
import re
import shlex
from pathlib import Path

import yaml

from . import executor, runstate
from .approvals import Approvals
from .audit.log import AuditLog
from .policy import decide_tool
from .redact import redact_command

ID = "codex"
POLICY_PATH = "executors/codex.yaml"
APP_DIR = "/Applications/gov-aios.app/Contents/MacOS"
HOOK_COMMAND = f"{APP_DIR}/gov-aios codex-hook"
HOOK_TIMEOUT_S = 120   # > the dialog's 60 s plus Touch ID: an answer always comes before Codex gives up
MATCHER = "^(Bash|apply_patch|mcp__.*)$"
TOOLS = ["Bash", "Write"]   # apply_patch is checked as one Write per file it touches
_SID = re.compile(r"[A-Za-z0-9-]{1,64}")
_PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", re.M)


class Block(Exception):
    """A one-line reason to exit 2."""


def default_policy(*roots):
    return yaml.safe_dump({"project_roots": [str(r) for r in roots], "allow_commands": executor.ALLOW_COMMANDS,
                           "destinations": executor.DESTINATIONS, "tools": TOOLS}, sort_keys=False)


def _q(s):
    return json.dumps(str(s))   # a TOML basic string is a JSON string for these characters


def protected(home):
    """Claude Code's protected paths plus Codex's own config and managed requirements."""
    from .agents import user_home
    extra = [user_home() / ".codex", Path("/etc/codex")]
    return executor.protected_paths(home) + tuple(dict.fromkeys([os.path.realpath(p) for p in extra] + [str(p) for p in extra]))


def project_config(roots):
    raw = [os.path.join(r, ".codex") for r in roots]
    return executor.project_config(roots) + tuple(dict.fromkeys([os.path.realpath(p) for p in raw] + raw))


def requirements(pol, home) -> str:
    """The /etc/codex/requirements.toml for this policy. Plugins and MCP servers stay allowed (the admin's choice);
    each plugin call still goes through the hook."""
    from .agents import user_home
    deny = [str(home), "/Library/Application Support/GOV-AIOS", str(user_home() / "Library/LaunchAgents")]
    return "\n".join([
        "# Written by GOV-AIOS from the Codex policy you approved. Change it from the GOV-AIOS panel.",
        "allow_managed_hooks_only = true",
        'allowed_sandbox_modes = ["read-only", "workspace-write"]',
        'allowed_approval_policies = ["on-request"]',
        'allowed_web_search_modes = ["disabled"]',
        "",
        "[features]",
        "hooks = true",
        "",
        "[hooks]",
        f"managed_dir = {_q(APP_DIR)}",
        "",
        "[[hooks.PreToolUse]]",
        f"matcher = {_q(MATCHER)}",
        "",
        "[[hooks.PreToolUse.hooks]]",
        'type = "command"',
        f"command = {_q(HOOK_COMMAND)}",
        f"timeout = {HOOK_TIMEOUT_S}",
        "",
        "[permissions.filesystem]",
        "deny_read = [" + ", ".join(_q(os.path.realpath(d)) for d in dict.fromkeys(deny)) + "]",
        "",
    ])


def _command_text(c):
    """Codex may send a shell command as a string or as argv (often [shell, "-lc", script])."""
    if isinstance(c, str):
        return c
    if isinstance(c, list) and all(isinstance(x, str) for x in c) and c:
        if len(c) == 3 and c[1] in ("-c", "-lc") and os.path.basename(c[0]) in ("bash", "sh", "zsh"):
            return c[2]
        return shlex.join(c)
    return None


def patch_paths(patch, cwd):
    """Absolute paths an apply_patch touches; None if it names none or a relative path without a cwd."""
    if not isinstance(patch, str):
        return None
    out = []
    for p in _PATCH_PATH.findall(patch):
        p = p.strip()
        if not p.startswith("/"):
            if not (isinstance(cwd, str) and cwd.startswith("/")):
                return None
            p = os.path.join(cwd, p)
        out.append(os.path.realpath(p))
    return out or None


def _check(home: Path, managed: Path):
    from .agents import CODEX
    if not runstate.guard_alive(home):
        raise Block("gov-aios guard is not running")
    if runstate.stopped(home):
        raise Block("gov-aios is stopped (emergency stop); clear it in the GOV-AIOS panel")
    if runstate.live_runs(home):
        raise Block("a gov-aios flow run is in progress")
    try:
        pol, digest = executor.load(home, POLICY_PATH)
    except FileNotFoundError:
        raise Block("no Codex policy: set up Codex in the GOV-AIOS panel") from None
    approvals = Approvals(home / "approvals.json")
    if not approvals.flow_ok(ID, digest):
        raise Block("Codex policy not approved: set up Codex in the GOV-AIOS panel")
    try:
        same = CODEX.same(Path(managed).read_bytes(), pol, home)
    except OSError:
        same = False
    if not same:
        raise Block("Codex requirements out of date: set up Codex again in the GOV-AIOS panel")
    return pol, digest, approvals


def decide(payload, home: Path, managed: Path):
    """(verdict, reason) for one Codex tool call; every call is audited."""
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_name"), str):
        raise Block("unparsable hook input")
    tool, inp, cwd = payload["tool_name"], payload.get("tool_input") or {}, payload.get("cwd")
    if not isinstance(inp, dict):
        raise Block("unparsable hook input")
    pol, digest, approvals = _check(home, managed)
    prot, config = protected(home), project_config(pol.get("project_roots", []))
    raw_cmd, target, remember = None, None, None
    if tool == "Bash":
        raw_cmd = _command_text(inp.get("command"))
        verdict = "deny" if raw_cmd is None else decide_tool(
            {"tool": "Bash", "category": "shell", "command": raw_cmd}, pol, approvals, prot, config)
    elif tool == "apply_patch":
        paths = patch_paths(inp.get("command"), cwd)
        target = ", ".join(paths)[:500] if paths else None
        vs = [decide_tool({"tool": "Write", "category": "write", "path": p}, pol, approvals, prot, config)
              for p in paths or []]
        verdict = "deny" if not vs or "deny" in vs else "ask" if "ask" in vs else "allow"
    elif tool.startswith("mcp__"):
        target = tool[:200]
        verdict = "allow" if approvals.destination_ok(ID, f"mcp:{tool}") else "ask"
    else:
        raise Block(f"unknown tool: {tool[:80]!r}")
    cmd = redact_command(raw_cmd) if raw_cmd is not None else None
    how, reason = None, None
    if verdict == "ask" and cmd != raw_cmd:   # redaction could hide code from the admin: never offer it
        verdict, reason = "deny", "denied by GOV-AIOS policy: command contains secret-like values; not offered for approval"
    if verdict == "ask":
        from . import auth   # lazy: pyobjc import only when a prompt is needed
        q = f"OpenAI Codex wants to use {tool}" + (f" on {target}" if target else "") + "."
        q += f"\nCommand: {cmd}" if cmd else ""
        if tool.startswith("mcp__"):
            q += "\nApproving also allows later calls to this plugin tool (revoke under Approvals)."
        ok, how = auth.approve(q + "\nApprove?", f"Codex: {tool[:60]}", home)
        verdict = "allow" if ok else "deny"
        remember = f"mcp:{tool}" if ok and tool.startswith("mcp__") else None
        reason = "approved by admin" if ok else (
            "denied by GOV-AIOS policy: approval busy" if how == "busy" else "denied by GOV-AIOS policy: admin did not approve")
    reason = reason or ("allowed by GOV-AIOS policy" if verdict == "allow" else f"denied by GOV-AIOS policy: {tool[:60]}")
    sid = payload.get("session_id")
    AuditLog(home).append("request", flow=ID, flow_hash=digest, executor=ID, action=tool[:200], target=target,
                          command=cmd, decision=verdict, approver="admin" if how is not None else "policy",
                          channel="touch_id" if how is not None else None, auth=how, reason=reason,
                          session=sid if isinstance(sid, str) and _SID.fullmatch(sid) else None,
                          folder=os.path.realpath(cwd) if isinstance(cwd, str) and cwd.startswith("/") else None)
    if remember:   # only once the approval is on record
        approvals.approve_destination(ID, remember)
    return verdict, reason


def main(stdin, stdout, stderr, home: Path, managed: Path = Path("/etc/codex/requirements.toml")) -> int:
    try:
        try:
            payload = json.loads(stdin.read())
        except ValueError:
            raise Block("unparsable hook input") from None
        verdict, reason = decide(payload, Path(home), Path(managed))
    except Block as e:
        print(f"gov-aios: {e}", file=stderr)
        return 2
    except Exception as e:   # type only: messages can carry tool input
        print(f"gov-aios: hook error {type(e).__name__}", file=stderr)
        return 2
    if verdict != "allow":
        print(f"gov-aios: {reason}", file=stderr)
        return 2
    return 0
