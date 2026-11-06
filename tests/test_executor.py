import os
from types import SimpleNamespace

import pytest
import yaml

from govaios.approvals import Approvals
from govaios import executor
from govaios.executor import (ALLOW_COMMANDS, DESTINATIONS, build_request, category, default_policy,
                              load, protected_paths)
from govaios.policy import decide_tool


@pytest.fixture
def env(tmp_path, govaios_home, monkeypatch):
    govaios_home.mkdir()
    user = tmp_path / "user"
    root = tmp_path / "proj"
    mem = user / ".claude/projects/p/memory"
    mem.mkdir(parents=True)
    root.mkdir()
    monkeypatch.setattr(executor.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(user)))
    pol = yaml.safe_load(default_policy(root))
    pol["tools"] += ["mcp__x__y"]
    return dict(user=user, root=root, mem=mem, pol=pol, appr=Approvals(tmp_path / "approvals.json"),
                prot=protected_paths(govaios_home), home=govaios_home)


def run(env, tool, **inp):
    return decide_tool(build_request(tool, inp, env["home"], env["root"]), env["pol"], env["appr"], env["prot"])


def test_table(env):
    r, o = str(env["root"]), str(env["root"].parent / "elsewhere")
    assert run(env, "Read", file_path=r + "/a") == "allow"
    assert run(env, "Read", file_path=o) == "ask"
    assert run(env, "Write", file_path=o) == "deny"
    assert run(env, "Write", file_path=str(env["home"] / "x")) == "deny"
    assert run(env, "Nope") == "deny"
    assert run(env, "mcp__x__y") == "ask"
    assert run(env, "mcp__x__z") == "deny"
    assert run(env, "TodoWrite") == "allow"
    assert run(env, "Bash", command="git status") == "allow"
    assert run(env, "Bash", command="git status; rm -rf ~") == "ask"
    assert run(env, "Bash", command="rm -rf build") == "ask"
    assert run(env, "Bash", command="git statusx") == "ask"
    assert run(env, "WebSearch") == "deny"
    assert run(env, "Read") == "deny"
    assert run(env, "Bash") == "deny"


def test_webfetch(env):
    assert run(env, "WebFetch", url="https://evil.com/x") == "deny"
    assert run(env, "WebFetch", url="http://github.com/x") == "deny"
    assert run(env, "WebFetch", url="https://GitHub.com/x") == "ask"
    env["appr"].approve_destination("claude_code", "https://github.com")
    assert run(env, "WebFetch", url="https://github.com/x") == "allow"


def test_symlink_into_data_home_denied(env):
    link = env["root"] / "link"
    link.symlink_to(env["home"])
    assert run(env, "Read", file_path=str(link)) == "deny"
    assert run(env, "Read", file_path=f"{env['root']}/../govaios-home") == "deny"


def test_memory_carve_out(env):
    m, u = env["mem"], env["user"]
    (m / "a.md").write_text("x")
    for t in ("Read", "Edit", "Write"):
        assert run(env, t, file_path=str(m / "a.md")) == "allow"
    assert run(env, "Read", file_path=str(m / "a.txt")) == "deny"
    assert run(env, "Read", file_path=str(u / ".claude/settings.json")) == "deny"
    assert run(env, "Read", file_path=str(u / ".claude.json")) == "deny"
    (m / "evil.md").symlink_to(u / ".claude/settings.json")
    assert run(env, "Read", file_path=str(m / "evil.md")) == "deny"
    (env["root"] / "ok.md").write_text("x")
    (m / "ok.md").symlink_to(env["root"] / "ok.md")
    assert run(env, "Read", file_path=str(m / "ok.md")) == "allow"  # realpath is inside the root


def test_unknown_tool_category_is_none():
    assert category("NewTool") is None and category("mcp__a__b") == "external"


def test_default_policy_round_trips(tmp_path):
    p = yaml.safe_load(default_policy(tmp_path))
    assert p["project_roots"] == [str(tmp_path)]
    assert p["allow_commands"] == ALLOW_COMMANDS == ["git status", "git diff", "git log", "git show", "ls", ".venv/bin/pytest"]
    assert p["destinations"] == DESTINATIONS == ["github.com", "pypi.org", "files.pythonhosted.org"]
    assert not {"LSP", "Monitor", "WebSearch"} & set(p["tools"]) and "Read" in p["tools"]


def test_load_hashes_bytes(tmp_path):
    (tmp_path / "executors").mkdir()
    (tmp_path / "executors/claude_code.yaml").write_text(default_policy(tmp_path))
    pol, digest = load(tmp_path)
    import hashlib
    assert pol["project_roots"] == [str(tmp_path)]
    assert digest == hashlib.sha256((tmp_path / "executors/claude_code.yaml").read_bytes()).hexdigest()


def test_default_tools_match_row_33(tmp_path):
    assert yaml.safe_load(default_policy(tmp_path))["tools"] == [
        "Read", "Glob", "Grep", "Edit", "Write", "NotebookEdit", "Bash", "WebFetch", "TodoWrite", "ToolSearch",
        "AskUserQuestion", "EnterPlanMode", "ExitPlanMode", "Agent", "Skill"]
    assert category("TaskStop") == "internal" and category("PowerShell") == "shell"


@pytest.mark.parametrize("url,want", [
    ("https://evil.com\\@github.com/x", "deny"), ("https://github.com:8443/x", "deny"),
    ("https://u@github.com/x", "deny"), ("https://GITHUB.com/x", "ask"), ("http://github.com/x", "deny"),
    ("https://[::1/x", "deny"), ("https://github.com/a b", "deny"), ("https://github.com/\t", "deny"),
    ("", "deny")])
def test_webfetch_parser_differential(env, url, want):
    assert run(env, "WebFetch", url=url) == want


def test_tilde_and_relative_paths_deny(env):
    for p in ("~/.claude/settings.json", "relative/x", "./x"):
        assert run(env, "Read", file_path=p) == "deny"
        assert run(env, "Write", file_path=p) == "deny"
    assert run(env, "Glob", pattern="*.py") == "allow"       # cwd (inside root) fills the missing path
    assert run(env, "Grep", pattern="x") == "allow"


def test_case_insensitive_protected(env):
    u = env["user"]
    for p in (".CLAUDE/settings.json", ".Claude.json", ".claude/Projects/p/MEMORY/a.txt"):
        assert run(env, "Read", file_path=str(u / p)) == "deny"
    assert run(env, "Read", file_path=str(env["home"]).upper() + "/x") == "deny"


def test_glob_pattern_escape(env):
    r = str(env["root"])
    for pat in (str(env["user"] / ".claude/**"), "~/.claude/*", "../*", "a/../../*"):
        assert run(env, "Glob", path=r, pattern=pat) == "deny"
    assert run(env, "Glob", path=r, pattern="**/*.py") == "allow"


def test_shell_args_touching_protected_paths_ask(env):
    u, h = env["user"], env["home"]
    for c in ("git diff --no-index ~/.claude.json /dev/null", f"ls {h}", "git log ../other",
              "ls ~", f"git diff --output={u}/.claude.json"):
        assert run(env, "Bash", command=c) == "ask", c
    for c in (f"ls {u}/.CLAUDE", "ls $HOME/.claude"):   # a `.claude` segment anywhere is denied, not asked (I-N1)
        assert run(env, "Bash", command=c) == "deny", c
    assert run(env, "Bash", command="git status") == "allow"


def test_shell_protected_paths_with_spaces_and_given_form(env, tmp_path):
    u, h = env["user"], env["home"]
    for c in ('ls "/Library/Application Support/GOV-AIOS"', 'ls "/Library/Application Support/ClaudeCode"',
              f'ls "{u}/Library/Application Support/GOV-AIOS"'):
        assert run(env, "Bash", command=c) == "ask", c
    given = tmp_path / "link"
    given.symlink_to(h)
    prot = protected_paths(given)
    pol = {"tools": ["Bash"], "project_roots": [], "allow_commands": ["ls"]}
    req = {"tool": "Bash", "category": "shell", "command": f"ls {given}"}
    assert decide_tool(req, pol, env["appr"], prot) == "ask"
    spaced = tmp_path / "Application Support/GOV-AIOS"
    spaced.mkdir(parents=True)
    req["command"] = f'ls "{spaced}"'
    assert decide_tool(req, pol, env["appr"], protected_paths(spaced)) == "ask"
    assert run(env, "Bash", command="git status") == "allow"


def test_glob_brace_escape(env):
    for pat in ("{/etc,x}/*", "{x,/etc}/*", "{~,x}/*", "a/{b,~}"):
        assert run(env, "Glob", path=str(env["root"]), pattern=pat) == "deny"
    assert run(env, "Glob", path=str(env["root"]), pattern="{a,b}/*.py") == "allow"


def test_load_realpaths_roots(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    (tmp_path / "executors").mkdir()
    (tmp_path / "executors/claude_code.yaml").write_text(default_policy(link))
    pol, _ = load(tmp_path)
    assert pol["project_roots"] == [os.path.realpath(real)]


@pytest.mark.parametrize("field,value", [("tools", "Bash"), ("allow_commands", "git status"), ("destinations", "github.com"),
                                         ("project_roots", "/tmp"), ("tools", ["Bash", 7]), ("tools", None)])
def test_load_rejects_non_list_fields(tmp_path, field, value):
    """M-10: a scalar would turn `in` into a substring test or iterate by character."""
    import yaml
    from govaios.executor import POLICY_PATH, default_policy, load
    pol = yaml.safe_load(default_policy(tmp_path))
    pol[field] = value
    (tmp_path / "executors").mkdir()
    (tmp_path / POLICY_PATH).write_text(yaml.safe_dump(pol))
    with pytest.raises(ValueError):
        load(tmp_path)
