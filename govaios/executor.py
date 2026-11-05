"""Claude Code executor: tool categories, protected paths, policy file, request building."""
import hashlib
import os
import pwd
from pathlib import Path

import yaml

from govaios.home import data_home

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
    user = Path(pwd.getpwuid(os.getuid()).pw_dir)
    raw = [home, "/Library/Application Support/GOV-AIOS", "/Library/Application Support/ClaudeCode",
           "/Applications/gov-aios.app", user / ".claude", user / ".claude.json", user / "Library/LaunchAgents"]
    return tuple(os.path.realpath(p) for p in raw)


def default_policy(root):
    return yaml.safe_dump({"project_roots": [str(root)], "allow_commands": ALLOW_COMMANDS,
                           "destinations": DESTINATIONS, "tools": DEFAULT_TOOLS}, sort_keys=False)


def load(home):
    raw = (Path(home) / POLICY_PATH).read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


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
    return req
