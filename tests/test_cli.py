import subprocess
import sys
import textwrap

import pytest

from govaios import identity
from govaios.cli import main

OK = {"bundle_id": "com.govaios.cli", "frozen": True, "accessibility": True, "screen_recording": True}


def test_run_refused_outside_app(capsys):
    with pytest.raises(SystemExit) as e:
        main(["run", "flows/himalayas_job_vetting.yaml"])
    assert "com.govaios.cli" in str(e.value)


def test_run_dev_blocks_network(tmp_path):
    driver = textwrap.dedent("""
        import socket
        from govaios import cli, engine
        def run(self):
            socket.create_connection(("127.0.0.1", 9))
        engine.Runner.__init__ = lambda self, *a: None
        engine.Runner.run = run
        import govaios.desktop as d
        d.get_desktop = lambda: object()
        raise SystemExit(cli.main(["run", "x.yaml", "--dev"]))
    """)
    (tmp_path / "x.yaml").write_text("")
    r = subprocess.run([sys.executable, "-c", driver], cwd=tmp_path, capture_output=True, text=True,
                       env={"PATH": "/usr/bin", "GOVAIOS_HOME": str(tmp_path / "h"), "PYTHONPATH": str(__import__("os").getcwd())})
    assert r.returncode != 0
    # netguard raises PermissionError; run reports only the type (no message: it may carry content)
    assert "ERROR: PermissionError" in r.stderr and "DEV MODE" in r.stderr


def test_doctor_fields(monkeypatch):
    monkeypatch.setattr(identity, "check", lambda: OK)
    assert main(["doctor", "--dev"]) == 0


def test_doctor_wrong_bundle(monkeypatch):
    monkeypatch.setattr(identity, "check", lambda: {**OK, "bundle_id": "org.python.python"})
    assert main(["doctor"]) == 1


def test_selftest_requires_dev(tmp_path, monkeypatch):
    f = tmp_path / "exit"
    monkeypatch.setenv("GOVAIOS_EXIT_FILE", str(f))
    with pytest.raises(SystemExit):
        main(["selftest", "lines", "1"])
    assert f.read_text() == "1"
    assert main(["selftest", "lines", "1", "--dev"]) == 0


def test_verify_audit_exit():
    from govaios.audit.log import AuditLog
    from govaios.home import data_home
    AuditLog(data_home()).append("flow_start", flow="t")
    assert main(["verify-audit"]) == 0


def test_frozen_app_ignores_govaios_home(tmp_path, monkeypatch):
    from govaios.home import data_home
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GOVAIOS_HOME", str(tmp_path / "elsewhere"))
    assert data_home() == tmp_path / "elsewhere"          # unpackaged (tests, --dev): honoured
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    import os
    import pwd
    from pathlib import Path
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: None)   # the passwd home is the real one
    assert data_home() == Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library/Application Support/GOV-AIOS"


def _fake_run(monkeypatch, exc, packaged=False):
    from govaios import desktop, engine
    seen = {}

    class R:
        def __init__(self, path, d, home, executor):
            seen["executor"] = executor

        def run(self):
            if exc:
                raise exc

    monkeypatch.setattr(engine, "Runner", R)
    monkeypatch.setattr(desktop, "get_desktop", lambda: None)
    monkeypatch.setattr("govaios.netguard.block_all_network", lambda: None)
    monkeypatch.setattr(identity, "check", lambda: {**OK, "bundle_id": "com.govaios.cli" if packaged else "x"})
    return seen


def test_run_unexpected_error_prints_type_only(monkeypatch, capsys):
    _fake_run(monkeypatch, ValueError("SECRET page text"))
    assert main(["run", "x.yaml", "--dev"]) == 1
    out = capsys.readouterr()
    assert "ERROR: ValueError" in out.err and "SECRET" not in out.out + out.err


def test_run_executor_label(monkeypatch):
    seen = _fake_run(monkeypatch, None)
    main(["run", "x.yaml", "--dev"])
    assert seen["executor"] == "gov_runner_dev"
    seen = _fake_run(monkeypatch, None, packaged=True)
    main(["run", "x.yaml"])
    assert seen["executor"] == "gov_runner"


def test_resume_exit_follows_proof(monkeypatch, govaios_home):
    from govaios import auth
    (govaios_home / "STOPPED").parent.mkdir(parents=True, exist_ok=True)
    (govaios_home / "STOPPED").touch()
    monkeypatch.setattr(auth, "prove", lambda reason, home: (False, "failed"))
    assert main(["resume"]) == 1 and (govaios_home / "STOPPED").exists()
    monkeypatch.setattr(auth, "prove", lambda reason, home: (True, "biometric"))
    assert main(["resume"]) == 0 and not (govaios_home / "STOPPED").exists()


def test_guard_subcommand_calls_guard(monkeypatch, govaios_home):
    from govaios import guard
    seen = []
    monkeypatch.setattr(guard, "main", lambda home: seen.append(home) or 0)
    assert main(["guard"]) == 0 and seen == [govaios_home]


def test_guard_plist():
    import plistlib
    from govaios.engine import REPO
    p = plistlib.loads((REPO / "packaging" / "com.govaios.guard.plist").read_bytes())
    assert p == {"Label": "com.govaios.guard", "KeepAlive": True, "RunAtLoad": True,
                 "ProgramArguments": ["/Applications/gov-aios.app/Contents/MacOS/gov-aios", "guard"]}


def _settings(monkeypatch, answer):
    from govaios import auth
    asked = []
    monkeypatch.setattr(auth, "approve", lambda q, r, h: (asked.append(q), answer)[1])
    return asked


ROW14_KEYS = {"allowManagedHooksOnly", "hooks", "permissions", "sandbox"}
ROW14_SANDBOX = {"enabled", "failIfUnavailable", "allowUnsandboxedCommands", "enableWeakerNestedSandbox",
                 "enableWeakerNetworkIsolation", "allowAppleEvents", "filesystem", "network"}
ROW14_NETWORK = {"allowManagedDomainsOnly", "allowedDomains", "allowAllUnixSockets", "allowLocalBinding"}


def test_claude_settings_output(monkeypatch, capsys, tmp_path, govaios_home):
    import json

    from govaios.approvals import Approvals
    from govaios.executor import DESTINATIONS, POLICY_PATH, load
    root = tmp_path / "proj"
    root.mkdir()
    asked = _settings(monkeypatch, (True, "biometric"))
    assert main(["claude-settings", "--root", str(root)]) == 0
    s = json.loads(capsys.readouterr().out)
    assert ROW14_SANDBOX <= set(s["sandbox"]) and ROW14_NETWORK <= set(s["sandbox"]["network"])
    assert set(s["permissions"]) == {"disableBypassPermissionsMode", "deny"} and "denyRead" in s["sandbox"]["filesystem"]
    assert ROW14_KEYS <= set(s) and s["sandbox"]["network"]["allowedDomains"] == DESTINATIONS
    pol, digest = load(govaios_home)
    assert Approvals(govaios_home / "approvals.json").flow_ok("claude_code", digest)
    assert asked == [asked[0]] and (govaios_home / POLICY_PATH).read_text() in asked[0]
    assert pol["project_roots"] == [str(root.resolve())]


def test_claude_settings_not_approved(monkeypatch, capsys, tmp_path, govaios_home):
    from govaios.approvals import Approvals
    from govaios.executor import load
    root = tmp_path / "proj"
    root.mkdir()
    _settings(monkeypatch, (False, "failed"))
    assert main(["claude-settings", "--root", str(root)]) == 1
    assert capsys.readouterr().out == ""
    assert not Approvals(govaios_home / "approvals.json").flow_ok("claude_code", load(govaios_home)[1])


@pytest.mark.parametrize("pick", [lambda h: h, lambda h: h.parent, lambda h: "/", lambda h: h / "sub",
                                  lambda h: str(h.parent).upper()])
def test_claude_settings_refuses_protected_root(monkeypatch, capsys, govaios_home, pick):
    govaios_home.mkdir(parents=True, exist_ok=True)
    asked = _settings(monkeypatch, (True, "biometric"))
    assert main(["claude-settings", "--root", str(pick(govaios_home))]) == 1
    out = capsys.readouterr()
    assert asked == [] and out.out == "" and out.err.count("\n") == 1


def test_claude_settings_refuses_hand_edited_root(monkeypatch, capsys, tmp_path, govaios_home):
    from govaios.executor import POLICY_PATH, default_policy
    (govaios_home / "executors").mkdir(parents=True)
    (govaios_home / POLICY_PATH).write_text(default_policy(tmp_path))   # tmp_path holds the data home
    root = tmp_path / "proj"
    root.mkdir()
    asked = _settings(monkeypatch, (True, "biometric"))
    assert main(["claude-settings", "--root", str(root)]) == 1
    assert asked == [] and capsys.readouterr().out == ""


@pytest.mark.parametrize("dest", ["https://github.com", "github.com/x", "github.com:443", "GitHub.com", "", 7])
def test_claude_settings_refuses_non_host_destination(monkeypatch, capsys, tmp_path, govaios_home, dest):
    import yaml

    from govaios.executor import POLICY_PATH, default_policy
    root = tmp_path / "proj"
    root.mkdir()
    pol = yaml.safe_load(default_policy(root))
    pol["destinations"].append(dest)
    (govaios_home / "executors").mkdir(parents=True)
    (govaios_home / POLICY_PATH).write_text(yaml.safe_dump(pol))
    asked = _settings(monkeypatch, (True, "biometric"))
    assert main(["claude-settings", "--root", str(root)]) == 1
    out = capsys.readouterr()
    assert asked == [] and out.out == "" and "bare host names" in out.err


def test_claude_settings_notes_existing_policy(monkeypatch, capsys, tmp_path, govaios_home):
    from govaios.executor import POLICY_PATH, default_policy, load
    root, other = tmp_path / "proj", tmp_path / "other"
    root.mkdir()
    other.mkdir()
    (govaios_home / "executors").mkdir(parents=True)
    (govaios_home / POLICY_PATH).write_text(default_policy(root))
    _settings(monkeypatch, (True, "biometric"))
    assert main(["claude-settings", "--root", str(other)]) == 0
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "project_roots are used" in err
    assert load(govaios_home)[0]["project_roots"] == [str(root.resolve())]


def test_cli_hook_passes_exit2(monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("{nope"))
    assert main(["hook"]) == 2


def test_audit_ui_deny_and_allow(monkeypatch, capsys, govaios_home):
    import json
    from govaios import auth
    from govaios.audit import web
    from govaios.audit.log import AuditLog
    monkeypatch.setattr(web, "make_server", lambda *a, **k: pytest.fail("must not bind"))
    monkeypatch.setattr(auth, "prove", lambda reason, home: (False, "failed"))
    assert main(["audit-ui"]) == 1
    e = json.loads(AuditLog(govaios_home).path.read_text().splitlines()[-1])
    assert e["kind"] == "ui_login" and e["channel"] == "touch_id" and e["auth"] == "failed"

    class Srv:
        server_address = ("127.0.0.1", 1234)
        serve_forever = server_close = lambda self: None
    monkeypatch.setattr(web, "make_server", lambda home, port: (Srv(), "CODE"))
    monkeypatch.setattr(auth, "prove", lambda reason, home: (True, "biometric"))
    assert main(["audit-ui"]) == 0
    assert "http://127.0.0.1:1234/login?c=CODE" in capsys.readouterr().out
