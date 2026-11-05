import os

import pytest
import yaml

from govaios.approvals import Approvals
from govaios.executor import (ALLOW_COMMANDS, DESTINATIONS, build_request, category, default_policy,
                              load, protected_paths)
from govaios.policy import decide_tool


@pytest.fixture
def env(tmp_path, govaios_home):
    govaios_home.mkdir()
    user = tmp_path / "user"
    root = tmp_path / "proj"
    mem = user / ".claude/projects/p/memory"
    mem.mkdir(parents=True)
    root.mkdir()
    pol = yaml.safe_load(default_policy(root))
    pol["tools"] += ["mcp__x__y"]
    return dict(user=user, root=root, mem=mem, pol=pol, appr=Approvals(tmp_path / "approvals.json"),
                prot=protected_paths(user), home=govaios_home)


def run(env, tool, **inp):
    return decide_tool(build_request(tool, inp, env["home"]), env["pol"], env["appr"], env["prot"])


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
