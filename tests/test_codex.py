"""OpenAI Codex: the generated requirements.toml and the codex-hook decisions."""
import io
import json
import os
import tomllib

import pytest

from govaios import auth, codex, executor, runstate
from govaios.approvals import Approvals

GUARD = 4242


@pytest.fixture
def env(tmp_path, govaios_home, monkeypatch):
    home = govaios_home
    (home / "executors").mkdir(parents=True)
    root = tmp_path / "proj"
    root.mkdir()
    (home / codex.POLICY_PATH).write_text(codex.default_policy(os.path.realpath(root)))
    pol, digest = executor.load(home, codex.POLICY_PATH)
    Approvals(home / "approvals.json").approve_flow("codex", digest)
    (home / "guard.pid").write_text(str(GUARD))
    monkeypatch.setattr(runstate, "is_govaios", lambda pid: pid == GUARD)
    managed = tmp_path / "requirements.toml"
    managed.write_text(codex.requirements(pol, home))
    asks = []

    def approve(question, reason, h):
        asks.append(question)
        return d["answer"]
    monkeypatch.setattr(auth, "approve", approve)
    d = dict(home=home, root=os.path.realpath(root), managed=managed, asks=asks, answer=(True, "biometric"), pol=pol)
    return d


def call(env, tool, inp, **extra):
    out, err = io.StringIO(), io.StringIO()
    payload = {"tool_name": tool, "tool_input": inp, "cwd": env["root"], "session_id": "019a-s1",
               "hook_event_name": "PreToolUse", "turn_id": "t", "tool_use_id": "u", **extra}
    code = codex.main(io.StringIO(json.dumps(payload)), out, err, env["home"], env["managed"])
    return code, out.getvalue(), err.getvalue()


def entries(env):
    return [json.loads(l) for l in (env["home"] / "audit.jsonl").read_text().splitlines()]


def test_requirements_lock_hooks_sandbox_and_search(env):
    r = tomllib.loads(codex.requirements(env["pol"], env["home"]))
    assert r["allow_managed_hooks_only"] is True and r["features"]["hooks"] is True
    assert "danger-full-access" not in r["allowed_sandbox_modes"] and r["allowed_approval_policies"] == ["on-request"]
    assert r["allowed_web_search_modes"] == ["disabled"]
    assert r["hooks"]["managed_dir"] == codex.APP_DIR
    (group,) = r["hooks"]["PreToolUse"]
    (h,) = group["hooks"]
    assert group["matcher"] == "^(Bash|apply_patch|mcp__.*)$"
    assert h == {"type": "command", "command": codex.HOOK_COMMAND, "timeout": codex.HOOK_TIMEOUT_S}
    assert codex.HOOK_TIMEOUT_S > auth.TIMEOUT_S + 30   # the dialog always ends before Codex gives up on the hook
    assert os.path.realpath(env["home"]) in r["permissions"]["filesystem"]["deny_read"]
    assert "mcp_servers" not in r   # plugins stay allowed (admin's choice); each call is checked


@pytest.mark.parametrize("command", ["git status", ["bash", "-lc", "git status"], ["git", "status"]])
def test_allowed_shell_runs_silently(env, command):
    code, out, err = call(env, "Bash", {"command": command})
    assert (code, out, err) == (0, "", "") and env["asks"] == []
    (e,) = entries(env)
    assert (e["executor"], e["action"], e["command"], e["decision"], e["approver"]) == \
        ("codex", "Bash", "git status", "allow", "policy")
    assert (e["session"], e["folder"]) == ("019a-s1", env["root"])


@pytest.mark.parametrize("answer,code", [((True, "biometric"), 0), ((False, "failed"), 2)])
def test_other_shell_asks_with_touch_id(env, answer, code):
    env["answer"] = answer
    c, out, err = call(env, "Bash", {"command": "make --version"})
    assert c == code and out == "" and len(env["asks"]) == 1 and "make --version" in env["asks"][0]
    assert (err == "") == (code == 0)
    assert entries(env)[-1]["approver"] == "admin"


def _patch(*paths):
    return "*** Begin Patch\n" + "".join(f"*** Update File: {p}\n@@\n-a\n+b\n" for p in paths) + "*** End Patch\n"


def test_patch_inside_folder_allowed(env):
    code, _, _ = call(env, "apply_patch", {"command": _patch("src/a.py", f"{env['root']}/b.py")})
    assert code == 0 and env["asks"] == []
    assert entries(env)[-1]["target"] == f"{env['root']}/src/a.py, {env['root']}/b.py"


@pytest.mark.parametrize("patch", [_patch("/etc/hosts"), _patch("ok.py", "../outside.py"), _patch(".codex/config.toml"),
                                   "*** Begin Patch\n*** End Patch\n", 7])
def test_patch_outside_or_into_config_denied(env, patch):
    code, out, err = call(env, "apply_patch", {"command": patch})
    assert code == 2 and out == "" and err.startswith("gov-aios: ") and env["asks"] == []


def test_patch_with_move_checks_destination(env):
    p = "*** Begin Patch\n*** Update File: a.py\n*** Move to: /tmp/elsewhere.py\n@@\n-a\n+b\n*** End Patch\n"
    assert call(env, "apply_patch", {"command": p})[0] == 2


def test_plugin_tool_asks_once_then_remembered(env):
    assert call(env, "mcp__node_repl__js", {"code": "1+1"})[0] == 0
    assert len(env["asks"]) == 1 and "revoke under Approvals" in env["asks"][0]
    assert call(env, "mcp__node_repl__js", {"code": "2+2"})[0] == 0
    assert len(env["asks"]) == 1   # remembered for this tool only
    env["answer"] = (False, "failed")
    assert call(env, "mcp__computer-use__click", {})[0] == 2
    assert not Approvals(env["home"] / "approvals.json").destination_ok("codex", "mcp:mcp__computer-use__click")


def test_unknown_tool_and_garbage_blocked(env):
    assert call(env, "web_search", {"q": "x"})[0] == 2
    out, err = io.StringIO(), io.StringIO()
    assert codex.main(io.StringIO("not json"), out, err, env["home"], env["managed"]) == 2


def test_out_of_date_requirements_block_everything(env):
    env["managed"].write_text(env["managed"].read_text().replace("timeout = 120", "timeout = 1"))
    code, _, err = call(env, "Bash", {"command": "git status"})
    assert code == 2 and "out of date" in err


def test_not_approved_or_guard_down_blocks(env, monkeypatch):
    Approvals(env["home"] / "approvals.json").revoke_flow("codex")
    assert "not approved" in call(env, "Bash", {"command": "git status"})[2]
    monkeypatch.setattr(runstate, "is_govaios", lambda pid: False)
    assert "guard is not running" in call(env, "Bash", {"command": "git status"})[2]


def test_secret_in_command_never_offered(env):
    code, _, err = call(env, "Bash", {"command": "curl -H 'Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz123456' x"})
    assert code == 2 and env["asks"] == [] and "secret-like" in err
