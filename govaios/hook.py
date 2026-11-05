"""Claude Code PreToolUse hook and the managed settings that wire it (rows 13-16, 31, 32).

Never returns "ask" to Claude Code: an ask verdict is resolved by GOV-AIOS's own dialog plus Touch ID.
Exit 2 with one stderr line blocks the call whatever stdout says.
"""
import json
import os
from pathlib import Path

from . import executor, runstate
from .approvals import Approvals
from .audit.log import AuditLog, url_for_audit
from .policy import _inside, decide_tool, origin
from .redact import redact_command

MANAGED_SETTINGS = Path("/Library/Application Support/ClaudeCode/managed-settings.json")
HOOK_COMMAND = "/Applications/gov-aios.app/Contents/MacOS/gov-aios hook"
DENY_RULE_IDX = (0, 1, 2, 3, 6)   # realpathed data home, GOV-AIOS, ClaudeCode, app, LaunchAgents; ~/.claude is the hook's (row 16)
ID = "claude_code"


class Block(Exception):
    """A one-line reason to exit 2."""


def _hosts(ds):
    return {d.lower() for d in ds}


def _check(home: Path, managed: Path):
    if not runstate.guard_alive(home):
        raise Block("gov-aios guard is not running")
    if runstate.stopped(home):
        raise Block("gov-aios is stopped (emergency stop); run `gov-aios resume`")
    if runstate.live_runs(home):
        raise Block("a gov-aios flow run is in progress")
    try:
        pol, digest = executor.load(home)
    except FileNotFoundError:
        raise Block("no Claude Code executor policy: run `gov-aios claude-settings`") from None
    approvals = Approvals(home / "approvals.json")
    if not approvals.flow_ok(ID, digest):
        raise Block("Claude Code executor policy not approved: run `gov-aios claude-settings`")
    try:
        domains = json.loads(managed.read_text())["sandbox"]["network"]["allowedDomains"]
    except (OSError, ValueError, KeyError, TypeError):
        raise Block("managed settings missing or unreadable") from None
    if not isinstance(domains, list) or not all(isinstance(d, str) for d in domains):
        raise Block("managed settings allowedDomains is not a list of host names")
    if _hosts(domains) != _hosts(pol.get("destinations", [])):
        raise Block("managed settings out of date: run `gov-aios claude-settings` and reinstall (admin, sudo)")
    return pol, digest, approvals


def _decide(payload, home: Path, managed: Path):
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_name"), str):
        raise Block("unparsable hook input")
    tool, inp = payload["tool_name"], payload.get("tool_input") or {}
    if executor.category(tool) is None:
        raise Block(f"unknown tool: {tool[:80]!r}")
    pol, digest, approvals = _check(home, managed)
    req = executor.build_request(tool, inp, home, payload.get("cwd") or "")
    raw_cmd = req["command"] if isinstance(req.get("command"), str) else None
    cmd = redact_command(raw_cmd) if raw_cmd is not None else None
    url = req.get("url") if isinstance(req.get("url"), str) else None
    target = req.get("path") or (url_for_audit(url) if url else None)
    verdict = decide_tool(req, pol, approvals, executor.protected_paths(home))
    how, reason, remember = None, None, None
    if verdict == "ask" and cmd != raw_cmd:   # redaction could hide code from the admin: never offer it
        verdict, reason = "deny", "denied by GOV-AIOS policy: command contains secret-like values; not offered for approval"
    if verdict == "ask":
        from . import auth   # lazy: pyobjc import only when a prompt is needed
        q = f"Claude Code wants to use {tool}" + (f" on {target}" if target else "") + "."
        q += f"\nCommand: {cmd}" if cmd else ""
        ok, how = auth.approve(q + "\nApprove?", f"Claude Code: {tool}", home)
        verdict = "allow" if ok else "deny"
        if ok and req["category"] == "fetch" and not approvals.destination_ok(ID, origin(url).lower()):
            remember = origin(url).lower()
        reason = "approved by admin" if ok else (
            "denied by GOV-AIOS policy: approval busy" if how == "busy" else "denied by GOV-AIOS policy: admin did not approve")
    reason = reason or ("allowed by GOV-AIOS policy" if verdict == "allow" else f"denied by GOV-AIOS policy: {tool}")
    asked = how is not None
    AuditLog(home).append("request", flow=ID, flow_hash=digest, executor=ID, action=tool, target=target,
                          command=cmd, decision=verdict, approver="admin" if asked else "policy",
                          channel="touch_id" if asked else None, auth=how)
    if remember:   # only once the approval is on record
        approvals.approve_destination(ID, remember)
    return verdict, reason


def main(stdin, stdout, stderr, home: Path, managed: Path = MANAGED_SETTINGS) -> int:
    try:
        try:
            payload = json.loads(stdin.read())
        except ValueError:
            raise Block("unparsable hook input") from None
        verdict, reason = _decide(payload, Path(home), Path(managed))
    except Block as e:
        print(f"gov-aios: {e}", file=stderr)
        return 2
    except Exception as e:   # type only: messages can carry tool input
        print(f"gov-aios: hook error {type(e).__name__}", file=stderr)
        return 2
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": verdict,
                                             "permissionDecisionReason": reason}}), file=stdout)
    return 0


def managed_settings(pol, home: Path) -> dict:
    """Row 14 (amended): Read/Edit deny rules only, `//` absolute paths, host-name allowedDomains."""
    prot = executor.protected_paths(home)
    deny = [f"{k}(/{prot[i]}/**)" for i in DENY_RULE_IDX for k in ("Read", "Edit")] + ["Edit(~/.claude.json)"]
    return {
        "allowManagedHooksOnly": True,
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": HOOK_COMMAND, "timeout": 300, "onFailure": "block"}]}]},
        "permissions": {"disableBypassPermissionsMode": "disable", "deny": deny},
        "sandbox": {
            "enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
            "enableWeakerNestedSandbox": False, "enableWeakerNetworkIsolation": False, "allowAppleEvents": False,
            "filesystem": {"denyRead": list(dict.fromkeys(prot))},
            "network": {"allowManagedDomainsOnly": True, "allowedDomains": list(pol["destinations"]),
                        "allowAllUnixSockets": False, "allowLocalBinding": False},
        },
    }


def bad_destination(d) -> bool:
    """Row 31: destinations are bare host names (no scheme, slash, port or upper case)."""
    return not (isinstance(d, str) and d and all(c.islower() or c.isdigit() or c in ".-" for c in d) and d.isascii())


def bad_root(root, home: Path) -> bool:
    """Row 16: a project root that equals, contains or sits inside a protected path (sandbox writes are allowed in roots)."""
    forms = {os.path.realpath(root), os.path.abspath(root)}
    return any(_inside(p, r, True) or _inside(r, p, True) for r in forms for p in executor.protected_paths(home))
