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
    "Bash": "shell", "Monitor": "shell", "WebFetch": "fetch", "WebSearch": "search",
    "TodoWrite": "internal", "ToolSearch": "internal", "AskUserQuestion": "internal",
    "EnterPlanMode": "internal", "ExitPlanMode": "internal",
    "Agent": "delegate", "Task": "delegate", "Skill": "delegate",
}
POLICY_PATH = "executors/claude_code.yaml"
ALLOW_COMMANDS = ["git status", "git diff", "git log", "git show", "ls", ".venv/bin/pytest"]
DESTINATIONS = ["github.com", "pypi.org", "files.pythonhosted.org"]


def category(tool):
    return "external" if tool.startswith("mcp__") else CATEGORIES.get(tool)


def protected_paths(home=None):
    """Always-deny paths (row 16), realpathed. `home` is the user's home (passwd db, not $HOME)."""
    home = Path(home) if home else Path(pwd.getpwuid(os.getuid()).pw_dir)
    raw = [data_home(), "/Library/Application Support/GOV-AIOS", "/Library/Application Support/ClaudeCode",
           "/Applications/gov-aios.app", home / ".claude", home / ".claude.json", home / "Library/LaunchAgents"]
    return tuple(os.path.realpath(p) for p in raw)


def default_policy(root):
    tools = [t for t in CATEGORIES if t not in ("LSP", "Monitor", "WebSearch")]
    return yaml.safe_dump({"project_roots": [str(root)], "allow_commands": ALLOW_COMMANDS,
                           "destinations": DESTINATIONS, "tools": tools}, sort_keys=False)


def load(home):
    raw = (Path(home) / POLICY_PATH).read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def build_request(tool_name, tool_input, home):
    req = {"tool": tool_name, "category": category(tool_name)}
    for k in ("file_path", "path", "notebook_path"):
        if tool_input.get(k):
            req["path"] = os.path.realpath(tool_input[k])
            break
    for k in ("command", "url"):
        if k in tool_input:
            req[k] = tool_input[k]
    return req
