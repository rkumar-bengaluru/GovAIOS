"""Claude Code executor: tool categories, protected paths, policy file, request building."""
import hashlib
import os
import sys
from pathlib import Path

import yaml

from govaios.home import data_home

WIN = sys.platform == "win32"
if WIN:
    from govaios.win import files as winfiles
else:
    import pwd

CATEGORIES = {
    "Read": "read", "Glob": "read", "Grep": "read", "LSP": "read",
    "Edit": "write", "Write": "write", "NotebookEdit": "write",
    "Bash": "shell", "Monitor": "shell", "PowerShell": "shell", "WebFetch": "fetch", "WebSearch": "search",
    "TaskStop": "internal", "TodoWrite": "internal", "ToolSearch": "internal", "AskUserQuestion": "internal",
    "EnterPlanMode": "internal", "ExitPlanMode": "internal",
    "Agent": "delegate", "Task": "delegate", "Skill": "delegate",
}
POLICY_PATH = "executors/claude_code.yaml"
ALLOW_COMMANDS = ["git status", "git diff", "git log", "git show", "ls", ".venv/bin/pytest"]
DESTINATIONS = ["github.com", "pypi.org", "files.pythonhosted.org"]


def category(tool):
    return "external" if tool.startswith("mcp__") else CATEGORIES.get(tool)


DEFAULT_TOOLS = ["Read", "Glob", "Grep", "Edit", "Write", "NotebookEdit", "Bash", "WebFetch", "TodoWrite",
                 "ToolSearch", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "Agent", "Skill"]  # row 33


def protected_paths(home):
    """Always-deny paths (row 16), realpathed. `home` is the GOV-AIOS data home; `~` comes from passwd.
    Order is fixed: policy.CLAUDE_IDX points at ~/.claude."""
    user = winfiles.user_home() if WIN else Path(pwd.getpwuid(os.getuid()).pw_dir)
    raw = [home, "/Library/Application Support/GOV-AIOS", "/Library/Application Support/ClaudeCode",
           "/Applications/gov-aios.app", user / ".claude", user / ".claude.json", user / "Library/LaunchAgents"]
    # realpathed forms first (CLAUDE_IDX), then the as-given forms, for textual matching in commands
    return tuple(os.path.realpath(p) for p in raw) + tuple(str(p) for p in raw)


def project_config(roots):
    """Each project root's Claude Code config (`.claude`, `.mcp.json`): deny for every tool, no carve-out.
    Project settings and MCP servers run code outside the hook and the sandbox (final review C-1)."""
    raw = [os.path.join(r, n) for r in roots for n in (".claude", ".mcp.json")]
    return tuple(dict.fromkeys([os.path.realpath(p) for p in raw] + raw))


def default_policy(*roots):
    return yaml.safe_dump({"project_roots": [str(r) for r in roots], "allow_commands": ALLOW_COMMANDS,
                           "destinations": DESTINATIONS, "tools": DEFAULT_TOOLS}, sort_keys=False)


def load(home):
    raw = (Path(home) / POLICY_PATH).read_bytes()
    pol = yaml.safe_load(raw)
    if not isinstance(pol, dict):
        raise ValueError("executor policy is not a mapping")
    for k in ("tools", "allow_commands", "destinations", "project_roots"):   # a scalar would match as a substring
        if not (isinstance(pol.get(k, []), list) and all(isinstance(v, str) for v in pol.get(k, []))):
            raise ValueError(f"executor policy {k} must be a list of strings")
    pol["project_roots"] = [os.path.realpath(r) for r in pol.get("project_roots", [])]  # requests are realpathed
    return pol, hashlib.sha256(raw).hexdigest()


def build_request(tool_name, tool_input, home, cwd):
    """Paths are realpathed only if absolute; `~` and relative paths leave path None (decide_tool denies)."""
    cat = category(tool_name)
    req = {"tool": tool_name, "category": cat}
    given = next((tool_input[k] for k in ("file_path", "path", "notebook_path") if tool_input.get(k)), None)
    if given is None and tool_name in ("Glob", "Grep"):
        given = str(cwd)
    if isinstance(given, str) and given.startswith("/"):
        req["path"] = os.path.realpath(given)
    for k in ("command", "url"):
        if k in tool_input:
            req[k] = tool_input[k]
    if tool_name == "Glob":
        req["pattern"] = tool_input.get("pattern", "")
    elif tool_name == "Grep" and isinstance(tool_input.get("glob"), str):
        req["pattern"] = tool_input["glob"]   # Grep's file filter; its `pattern` is content, not paths
    return req
