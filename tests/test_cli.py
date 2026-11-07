import os
import json
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
    assert e.value.code == 1
    assert capsys.readouterr().err.count("com.govaios.cli") == 1   # printed once, not again by the re-raise


def test_run_dev_blocks_network(tmp_path):
    driver = textwrap.dedent("""
        import socket
        from govaios import auth, cli, engine
        from govaios import powers, runstate
        auth.screen_locked = lambda: False   # dev runs every preflight check; never depend on the real screen or guard
        runstate.guard_alive = lambda home: True
        powers.fresh = lambda home, now=None: True
        def run(self):
            socket.create_connection(("127.0.0.1", 9))
        engine.Runner.__init__ = lambda self, *a, **k: None
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


def _doctor_env(monkeypatch, tmp_path, root_owned=True, domains=None):
    import json
    from govaios import auth, hook, runstate
    from govaios.executor import DESTINATIONS, POLICY_PATH, default_policy
    from govaios.home import data_home
    pol = data_home() / POLICY_PATH
    pol.parent.mkdir(parents=True, exist_ok=True)
    pol.write_text(default_policy(tmp_path))
    managed = tmp_path / "managed-settings.json"   # never the real /Library file
    managed.write_text(json.dumps({"sandbox": {"network": {"allowedDomains": DESTINATIONS if domains is None else domains}}}))
    managed.chmod(0o644)
    real_stat = type(managed).stat
    monkeypatch.setattr(identity, "check", lambda: OK)
    monkeypatch.setattr(hook, "MANAGED_SETTINGS", managed)
    monkeypatch.setattr(runstate, "guard_alive", lambda home: True)
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    monkeypatch.setattr("govaios.powers.fresh", lambda home, now=None: True)
    if root_owned:
        import os
        monkeypatch.setattr(type(managed), "stat", lambda self, **k: os.stat_result(
            (*real_stat(self, **k)[:4], 0, *real_stat(self, **k)[5:])) if self == managed else real_stat(self, **k))


def test_doctor_fields(monkeypatch, tmp_path):
    _doctor_env(monkeypatch, tmp_path)
    assert main(["doctor", "--dev"]) == 0


def test_doctor_reports_new_checks(monkeypatch, tmp_path, capsys, govaios_home):
    import json
    _doctor_env(monkeypatch, tmp_path, root_owned=False)   # owned by the test user, not root
    assert main(["doctor"]) == 1
    assert "managed_settings: False" in capsys.readouterr().out.splitlines()
    _doctor_env(monkeypatch, tmp_path)
    monkeypatch.setattr("govaios.powers.fresh", lambda home, now=None: False)
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    for k in ("guard: True", "managed_settings: True", "powers_review: missing", "screen_locked: False"):
        assert k in out.splitlines(), out
    govaios_home.mkdir(parents=True, exist_ok=True)
    (govaios_home / "powers_review.json").write_text(json.dumps({"ts": "2026-11-01T00:00:00+00:00", "kept": []}))
    monkeypatch.setattr("govaios.powers.fresh", lambda home, now=None: True)
    assert main(["doctor"]) == 0
    assert "powers_review: 2026-11-01" in capsys.readouterr().out.splitlines()
    from govaios import auth, runstate
    monkeypatch.setattr(runstate, "guard_alive", lambda home: False)
    assert main(["doctor"]) == 1
    monkeypatch.setattr(runstate, "guard_alive", lambda home: True)
    monkeypatch.setattr(auth, "screen_locked", lambda: True)
    assert main(["doctor"]) == 1


def test_doctor_wrong_bundle(monkeypatch):
    monkeypatch.setattr(identity, "check", lambda: {**OK, "bundle_id": "org.python.python"})
    assert main(["doctor"]) == 1


def test_selftest_requires_dev(tmp_path, monkeypatch):
    f = tmp_path / "exit"
    f.write_text("")   # the shim's mktemp file
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
        deliver = None   # a flow without a deliver block

        def __init__(self, path, d, home, executor, ticket=None):
            seen["executor"] = executor
            seen["ticket"] = ticket

        def run(self):
            if exc:
                raise exc

    monkeypatch.setattr(engine, "Runner", R)
    monkeypatch.setattr(desktop, "get_desktop", lambda: None)
    monkeypatch.setattr("govaios.netguard.block_all_network", lambda: None)
    _checks(monkeypatch)
    monkeypatch.setattr(identity, "check", lambda: {**OK, "bundle_id": "com.govaios.cli" if packaged else "x"})
    return seen


def _checks(monkeypatch, guard=True, stopped=False, locked=False, fresh=True, ident=None):
    from govaios import auth, powers, runstate
    monkeypatch.setattr(identity, "check", lambda: {**OK, **(ident or {})})
    monkeypatch.setattr(runstate, "guard_alive", lambda home: guard)
    monkeypatch.setattr(runstate, "stopped", lambda home: stopped)
    monkeypatch.setattr(auth, "screen_locked", lambda: locked)
    monkeypatch.setattr(powers, "fresh", lambda home, now=None: fresh)


BAD_IDENT = {"bundle_id": "x", "frozen": False, "accessibility": False, "screen_recording": False}


@pytest.mark.parametrize("dev", [False, True])   # row 28: no dev exemptions
def test_preflight_order(monkeypatch, govaios_home, dev):
    from govaios.cli import preflight
    want = [("guard", dict(guard=False, stopped=True, locked=True, fresh=False, ident=BAD_IDENT)),
            ("STOPPED", dict(stopped=True, locked=True, fresh=False, ident=BAD_IDENT)),
            ("locked", dict(locked=True, fresh=False, ident=BAD_IDENT)),
            ("powers review", dict(fresh=False, ident=BAD_IDENT))]
    for word, bad in want:
        _checks(monkeypatch, **bad)
        with pytest.raises(SystemExit) as e:
            preflight(govaios_home, dev=dev)
        assert word in str(e.value) and "\n" not in str(e.value)
    _checks(monkeypatch, ident=BAD_IDENT)
    if dev:
        preflight(govaios_home, dev=True)   # identity is the one dev difference
    else:
        with pytest.raises(SystemExit) as e:
            preflight(govaios_home, dev=False)
        assert "bundle_id" in str(e.value) and "\n" not in str(e.value)
    _checks(monkeypatch)
    preflight(govaios_home, dev=dev)


@pytest.mark.parametrize("key", ["bundle_id", "frozen", "accessibility", "screen_recording"])
def test_preflight_identity_names_failing_check(monkeypatch, govaios_home, key):
    from govaios.cli import preflight
    _checks(monkeypatch, ident={key: BAD_IDENT[key]})
    with pytest.raises(SystemExit) as e:
        preflight(govaios_home, dev=False)
    assert str(e.value).endswith(key)


def test_run_refuses_failed_identity_before_runner(monkeypatch, capsys):
    from govaios import auth
    seen = _fake_run(monkeypatch, None, packaged=True)
    calls = iter([OK, {**OK, "accessibility": False}])   # require_app passes; doctor's checks then fail
    monkeypatch.setattr(identity, "check", lambda: next(calls))
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    with pytest.raises(SystemExit):
        main(["run", "x.yaml"])
    assert "executor" not in seen and "accessibility" in capsys.readouterr().err


def test_run_preflight_refusal(monkeypatch, capsys, govaios_home):
    seen = _fake_run(monkeypatch, None, packaged=True)
    _checks(monkeypatch, guard=False)
    with pytest.raises(SystemExit):
        main(["run", "x.yaml"])
    assert "executor" not in seen and "guard" in capsys.readouterr().err
    assert not any((govaios_home / "runs").iterdir())


@pytest.mark.parametrize("exc", [None, RuntimeError("x")])
def test_run_registers_and_unregisters(monkeypatch, govaios_home, exc):
    import os
    from govaios import engine
    _fake_run(monkeypatch, None)
    during = []

    class R:
        deliver = None

        def __init__(self, *a, **k):
            pass

        def run(self):
            during.append((govaios_home / "runs" / str(os.getpid())).exists())
            if exc:
                raise exc
    monkeypatch.setattr(engine, "Runner", R)
    assert main(["run", "x.yaml", "--dev"]) == (1 if exc else 0)
    assert during == [True] and not (govaios_home / "runs" / str(os.getpid())).exists()


def test_dev_requires_tmp_home(monkeypatch, tmp_path):
    import os
    import pwd
    seen = _fake_run(monkeypatch, None)
    f = tmp_path / "exit"
    monkeypatch.setenv("GOVAIOS_EXIT_FILE", str(f))
    real = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, "Library/Application Support/GOV-AIOS")
    for env in (None, real, real.upper(), real + "/sub"):
        if env is None:
            monkeypatch.delenv("GOVAIOS_HOME")
        else:
            monkeypatch.setenv("GOVAIOS_HOME", env)
        f.write_text("")   # the shim's mktemp file
        with pytest.raises(SystemExit):
            main(["run", "x.yaml", "--dev"])
        assert f.read_text() == "1" and "executor" not in seen


def test_dump_needs_proof(monkeypatch, capsys, govaios_home):
    from govaios import auth, desktop
    _fake_run(monkeypatch, None)
    reads, reasons = [], []

    class D:
        def _app(self, name):
            return True

        def web_root(self, name):
            reads.append(name)

    monkeypatch.setattr(desktop, "get_desktop", lambda: D())
    answer = [(False, "failed")]
    monkeypatch.setattr(auth, "prove", lambda reason, home: (reasons.append(reason), answer[0])[1])
    assert main(["dump", "--dev"]) == 1
    assert reads == [] and reasons == ["print the open Chrome page"]
    from govaios.audit.log import AuditLog
    log = lambda: [json.loads(x) for x in AuditLog(govaios_home).path.read_text().splitlines()]  # noqa: E731
    (e,) = log()
    assert (e["kind"], e["action"], e["decision"], e["approver"], e["channel"], e["auth"]) == \
        ("request", "dump", "deny", "admin", "touch_id", "failed")
    answer[0] = (True, "biometric")
    D._app = lambda self, name: False   # proven, then "chrome is not running": the proof is still on record
    with pytest.raises(SystemExit):
        main(["dump", "--dev"])
    e = log()[-1]
    assert (e["action"], e["decision"], e["auth"]) == ("dump", "allow", "biometric")
    assert set(e) <= {"seq", "ts", "kind", "action", "decision", "approver", "channel", "auth", "prev", "hash", "sig"}
    reasons.clear()
    _checks(monkeypatch, locked=True)
    with pytest.raises(SystemExit):
        main(["dump", "--dev"])
    assert reasons == []   # preflight refuses before the proof


def _subcommands():
    """Every subparser name, read from main()'s own usage line."""
    import contextlib
    import io
    import re
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
        main(["-h"])
    return re.search(r"\{([a-z,-]+)\}", buf.getvalue())[1].split(",")


SUBCOMMANDS = ["doctor", "selftest", "run", "deliver", "verify-audit", "audit-ui", "panel", "dump", "guard", "resume", "hook",
               "claude-settings", "review-powers"]
ARGV = {"selftest": ["selftest", "lines", "1"], "run": ["run", "x.yaml"], "deliver": ["deliver", "x.yaml"],
        "claude-settings": ["claude-settings", "--root", "/x"],
        "review-powers": ["review-powers", "Zoom"]}


def test_sandbox_table_covers_every_subcommand():
    assert _subcommands() == SUBCOMMANDS


@pytest.mark.parametrize("cmd", SUBCOMMANDS)
def test_sandbox_applied_per_subcommand(monkeypatch, sandbox_calls, cmd):
    """The Global Constraints table: doctor none, audit-ui UI_PROFILE, every other subcommand RUN_PROFILE."""
    from govaios import cli, sandbox
    profile = {"doctor": None, "audit-ui": "UI_PROFILE", "panel": "UI_PROFILE", "deliver": "DELIVER_PROFILE"}.get(cmd, "RUN_PROFILE")
    order = []
    monkeypatch.setattr(sandbox, "apply", lambda p: order.append(("apply", p)))
    monkeypatch.setattr(cli, "_" + cmd.replace("-", "_"), lambda args: order.append(("handler", None)) or 0)
    assert main(ARGV.get(cmd, [cmd])) == 0
    assert order == ([("apply", getattr(sandbox, profile))] if profile else []) + [("handler", None)]


def test_sandbox_refusal_runs_nothing(monkeypatch, capsys):
    from govaios import cli, sandbox

    def refuse(p):
        raise RuntimeError("sandbox refused")
    monkeypatch.setattr(sandbox, "apply", refuse)
    monkeypatch.setattr(cli, "_hook", lambda args: pytest.fail("handler ran"))
    assert main(["hook"]) == 1
    assert capsys.readouterr().err.count("\n") == 1


def test_review_powers_subcommand(monkeypatch, govaios_home):
    from govaios import powers
    seen = []
    monkeypatch.setattr(powers, "review", lambda home, kept, audit: seen.append((home, kept)) or False)
    assert main(["review-powers", "Zoom", "1Password"]) == 1
    monkeypatch.setattr(powers, "review", lambda home, kept, audit: seen.append((home, kept)) or True)
    assert main(["review-powers", "Zoom"]) == 0
    assert seen == [(govaios_home, ["Zoom", "1Password"]), (govaios_home, ["Zoom"])]


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
    import hashlib

    from govaios.approvals import Approvals
    from govaios.executor import POLICY_PATH, default_policy
    root = tmp_path / "proj"
    root.mkdir()
    digest = hashlib.sha256(default_policy(str(root.resolve())).encode()).hexdigest()
    _settings(monkeypatch, (False, "failed"))
    assert main(["claude-settings", "--root", str(root)]) == 1
    assert capsys.readouterr().out == ""
    assert not (govaios_home / POLICY_PATH).exists()   # written only once approved
    assert not Approvals(govaios_home / "approvals.json").flow_ok("claude_code", digest)


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
    want = "destinations must be a list of strings" if dest == 7 else "bare host names"   # 7: refused by load (M-10)
    assert asked == [] and out.out == "" and want in out.err


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


def test_audit_ui_no_prove_at_start_prints_panel_address(monkeypatch, capsys, govaios_home):
    from govaios import auth
    from govaios.audit import web
    from govaios.audit.log import AuditLog
    monkeypatch.setattr(auth, "prove", lambda *a, **k: pytest.fail("sign-in happens on the page"))

    class Srv:
        server_address = ("127.0.0.1", 1234)
        serve_forever = server_close = lambda self: None
    monkeypatch.setattr(web, "make_server", lambda home, port, flows_dir=None, helper=None: Srv())
    assert main(["audit-ui"]) == 0
    out = capsys.readouterr().out
    assert "Control panel: http://127.0.0.1:1234/\n" in out and "login" not in out
    p = AuditLog(govaios_home).path
    assert not p.exists() or '"ui_login"' not in p.read_text()


class FakeHelper:
    last = None

    def __init__(self):
        self.closed = False
        FakeHelper.last = self

    run = say = staticmethod(lambda *a, **k: None)

    def close(self):
        self.closed = True


@pytest.mark.parametrize("argv", [["panel", "FLOWS"], ["audit-ui", "FLOWS"], ["audit-ui"], ["panel"]])
def test_cli_panel_starts_helper_before_sandbox(monkeypatch, tmp_path, govaios_home, argv):
    from govaios import cli, sandbox
    argv = [str(tmp_path) if a == "FLOWS" else a for a in argv]
    order = []
    monkeypatch.setattr("govaios.panel.helper.start_helper",
                        lambda flows, home: order.append(("helper", flows, home)) or FakeHelper())
    monkeypatch.setattr(sandbox, "apply", lambda p: order.append(("apply", p)))
    monkeypatch.setattr(cli, "_audit_ui", lambda args: order.append(("handler", args.helper)) or 0)
    assert main(argv) == 0
    if len(argv) == 2:
        assert order == [("helper", tmp_path.resolve(), govaios_home), ("apply", sandbox.UI_PROFILE),
                         ("handler", FakeHelper.last)] and FakeHelper.last.closed
    else:
        assert order == [("apply", sandbox.UI_PROFILE), ("handler", None)]


def test_panel_starts_without_prove(monkeypatch, capsys, govaios_home, tmp_path):
    from govaios import auth
    from govaios.audit import web
    monkeypatch.setattr(auth, "prove", lambda *a, **k: pytest.fail("sign-in happens on the page"))
    seen = []

    class Srv:
        server_address = ("127.0.0.1", 1234)
        serve_forever = server_close = lambda self: None
    monkeypatch.setattr(web, "make_server", lambda home, port, flows_dir=None, helper=None:
                        seen.append((port, flows_dir, helper)) or Srv())
    monkeypatch.setattr("govaios.panel.helper.start_helper", lambda flows, home: FakeHelper())
    assert main(["panel", str(tmp_path), "--port", "7"]) == 0
    assert seen == [(7, tmp_path.resolve(), FakeHelper.last)] and FakeHelper.last.closed
    assert "Control panel: http://127.0.0.1:1234/" in capsys.readouterr().out


def test_panel_sigterm_ends_session_and_stops_run(monkeypatch, govaios_home):
    """The shim's trap sends SIGTERM: the panel must still end the session and stop its run, once."""
    import json
    import signal
    from govaios import auth
    from govaios.audit import web
    from govaios.audit.log import AuditLog
    real = web.make_server
    stops, got = [], {}

    class Run:
        done, ticket = False, "0" * 64
        stop = lambda self, why: stops.append(why)

    def make(home, port, flows_dir=None, helper=None):
        srv = real(home, 0, flows_dir=flows_dir, tick_s=None)
        srv.panel.session.open()
        srv.panel.run = Run()

        def serve():
            got["h"] = signal.getsignal(signal.SIGTERM)
            got["h"](signal.SIGTERM, None)   # what the shim's kill -TERM delivers
        srv.serve_forever = serve
        return srv
    monkeypatch.setattr(web, "make_server", make)
    before = signal.getsignal(signal.SIGTERM)
    assert main(["panel"]) == 0
    assert got["h"] is not before and signal.getsignal(signal.SIGTERM) is before   # restored
    ends = [json.loads(l) for l in AuditLog(govaios_home).path.read_text().splitlines()]
    assert [e["reason"] for e in ends if e["kind"] == "session_end"] == ["server_stop"]
    assert stops == ["session ended"]


def test_audit_ui_alias_same_handler(monkeypatch):
    from govaios import cli, sandbox
    monkeypatch.setattr(sandbox, "apply", lambda p: None)
    monkeypatch.setattr(cli, "_audit_ui", lambda args: 0 if args.flows_dir is None else 1)
    assert main(["audit-ui"]) == 0 and main(["panel"]) == 0


def test_doctor_reports_drift_and_mode(monkeypatch, tmp_path, capsys):
    """M-3: row 32's drift check (the hook's comparison) and a group/other-writable managed file."""
    _doctor_env(monkeypatch, tmp_path)
    assert main(["doctor"]) == 0
    assert "managed_settings_current: True" in capsys.readouterr().out.splitlines()
    _doctor_env(monkeypatch, tmp_path, domains=["github.com"])
    assert main(["doctor"]) == 1
    assert "managed_settings_current: False" in capsys.readouterr().out.splitlines()
    _doctor_env(monkeypatch, tmp_path)
    from govaios import hook
    hook.MANAGED_SETTINGS.chmod(0o664)
    assert main(["doctor"]) == 1
    assert "managed_settings: False" in capsys.readouterr().out.splitlines()


def test_dump_is_a_registered_run(monkeypatch, govaios_home):
    """M-12: registered before preflight, unregistered afterwards (a stop finds it)."""
    import os
    from govaios import auth, cli
    _fake_run(monkeypatch, None)
    me = govaios_home / "runs" / str(os.getpid())
    seen = []
    monkeypatch.setattr(cli, "preflight", lambda home, dev: seen.append(("preflight", me.exists())))
    monkeypatch.setattr(auth, "prove", lambda reason, home: (False, "failed"))
    assert main(["dump", "--dev"]) == 1
    assert seen == [("preflight", True)] and not me.exists()


@pytest.mark.parametrize("var", ["GOVAIOS_PID_FILE", "GOVAIOS_EXIT_FILE"])
def test_shim_files_never_follow_links_or_truncate(monkeypatch, tmp_path, var):
    """M-6: only an existing empty regular file (the shim's mktemp) is written."""
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "link"
    link.symlink_to(victim)
    for target in (link, victim, tmp_path / "missing"):
        monkeypatch.setenv(var, str(target))
        assert main(["selftest", "lines", "1", "--dev"]) == 0
    assert victim.read_text() == "keep" and not (tmp_path / "missing").exists()
    empty = tmp_path / "empty"
    empty.write_text("")
    monkeypatch.setenv(var, str(empty))
    assert main(["selftest", "lines", "1", "--dev"]) == 0
    assert empty.read_text() != ""


@pytest.mark.parametrize("deliver,exc,want", [({"to": "joblens"}, None, "deliver"), (None, None, ""),
                                              ({"to": "joblens"}, "stop", "")])
def test_run_writes_next_file_only_for_deliver_flows(monkeypatch, tmp_path, deliver, exc, want):
    from govaios import engine
    _fake_run(monkeypatch, None)

    class R:
        def __init__(self, *a, **k):
            self.deliver = deliver

        def run(self):
            if exc:
                raise engine.Stop("x")
    monkeypatch.setattr(engine, "Runner", R)
    f = tmp_path / "next"
    f.write_text("")   # the shim's mktemp file
    monkeypatch.setenv("GOVAIOS_NEXT_FILE", str(f))
    assert main(["run", "x.yaml", "--dev"]) == (1 if exc else 0)
    assert f.read_text() == want


def test_deliver_is_a_registered_run_and_preflighted(monkeypatch, capsys, govaios_home):
    from govaios import delivery
    _checks(monkeypatch, stopped=True, ident={"bundle_id": "x"})
    monkeypatch.setattr(delivery, "run_delivery", lambda *a: pytest.fail("delivery ran"))
    with pytest.raises(SystemExit) as e:
        main(["deliver", "x.yaml", "--dev"])
    assert e.value.code == 1 and "STOPPED" in capsys.readouterr().err
    assert not any((govaios_home / "runs").iterdir())


def test_deliver_refused_when_screen_locked(monkeypatch, capsys, govaios_home):
    from govaios import delivery
    _checks(monkeypatch, locked=True)
    monkeypatch.setattr(delivery, "run_delivery", lambda *a: pytest.fail("delivery ran"))
    with pytest.raises(SystemExit) as e:
        main(["deliver", "x.yaml", "--dev"])
    assert e.value.code == 1 and "screen is locked" in capsys.readouterr().err
    assert not any((govaios_home / "runs").iterdir())


def test_cli_run_passes_ticket_env(monkeypatch):
    seen = _fake_run(monkeypatch, None)
    monkeypatch.setenv("GOVAIOS_RUN_TICKET", "abc")
    main(["run", "x.yaml", "--dev"])
    assert seen["ticket"] == "abc"


def test_cli_empty_ticket_env_is_no_ticket(monkeypatch):
    seen = _fake_run(monkeypatch, None)
    monkeypatch.setenv("GOVAIOS_RUN_TICKET", "")
    main(["run", "x.yaml", "--dev"])
    assert seen["ticket"] is None


def _agent_env(monkeypatch, govaios_home, port=0):
    from govaios import cli, sandbox
    monkeypatch.setattr(cli, "AGENT_PORT", port)
    monkeypatch.setattr(os, "dup2", lambda a, b: None)   # never repoint pytest's own fds
    monkeypatch.setattr(sandbox, "apply", lambda p: None)
    monkeypatch.setattr("govaios.panel.helper.start_helper", lambda flows, home: FakeHelper())


def test_agent_args(monkeypatch, govaios_home):
    from govaios import cli, sandbox
    from govaios.audit import web
    order, seen = [], []

    class Srv:
        server_address = ("127.0.0.1", 8765)
        serve_forever = server_close = lambda self: None
    monkeypatch.setattr("govaios.panel.helper.start_helper",
                        lambda flows, home: order.append(("helper", flows)) or FakeHelper())
    monkeypatch.setattr(sandbox, "apply", lambda p: order.append(("apply", p)))
    monkeypatch.setattr(os, "dup2", lambda a, b: order.append(("dup2", b)))
    monkeypatch.setattr(web, "make_server", lambda home, port, flows_dir=None, helper=None:
                        seen.append((home, port, flows_dir)) or Srv())
    assert cli.AGENT_PORT == 8765
    assert main(["panel", "--agent"]) == 0
    flows = (govaios_home / "apps" / "flows").resolve()
    assert order == [("helper", flows), ("dup2", 1), ("dup2", 2), ("apply", sandbox.UI_PROFILE)]
    assert seen == [(govaios_home, 8765, flows)]
    assert "Control panel: http://127.0.0.1:8765/" in (govaios_home / "panel.log").read_text()


def test_agent_missing_apps_dir(monkeypatch, govaios_home, ui):
    import threading
    from govaios.audit import web
    _agent_env(monkeypatch, govaios_home)
    real, got = web.make_server, {}

    def make(home, port, flows_dir=None, helper=None):
        srv = real(home, 0, flows_dir=flows_dir, tick_s=None)

        def serve():   # a signed-in browser opens Talk while the panel is up
            t = threading.Thread(target=srv.__class__.serve_forever, args=(srv,), daemon=True)
            t.start()
            sid = ui.signin(srv)
            got["talk"] = ui.raw(srv.server_address[1], "GET", "/", f"s={sid}")[:2]
            got["audit"] = ui.raw(srv.server_address[1], "GET", "/audit", f"s={sid}")[:2]
            srv.shutdown()
        srv.serve_forever = serve
        return srv
    monkeypatch.setattr(web, "make_server", make)
    assert not (govaios_home / "apps").exists()
    assert main(["panel", "--agent"]) == 0
    # Talk lists no apps (and no "no folder given" note: the folder was given); the existing no-apps line is on /audit
    assert got["talk"][0] == 200 and "<h2>Approved</h2><ul></ul><h2>Drafts</h2><ul></ul>" in got["talk"][1]
    assert "No apps folder given" not in got["talk"][1]
    assert got["audit"][0] == 200 and "No apps yet." in got["audit"][1]


def test_agent_port_busy_exits_1_and_logs_once(monkeypatch, govaios_home):
    import socket
    _agent_env(monkeypatch, govaios_home)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        monkeypatch.setattr("govaios.cli.AGENT_PORT", port)
        assert main(["panel", "--agent"]) == 1
        assert main(["panel", "--agent"]) == 1
    log = (govaios_home / "panel.log").read_text()
    assert log == f"panel: port {port} is in use\n"


def test_agent_no_ui_login_at_start(monkeypatch, govaios_home):
    from govaios import auth
    from govaios.audit import web
    from govaios.audit.log import AuditLog
    _agent_env(monkeypatch, govaios_home)
    monkeypatch.setattr(auth, "prove", lambda *a, **k: pytest.fail("sign-in happens on the page"))
    real = web.make_server

    def make(home, port, flows_dir=None, helper=None):
        srv = real(home, 0, flows_dir=flows_dir, tick_s=None)
        srv.serve_forever = lambda: None
        return srv
    monkeypatch.setattr(web, "make_server", make)
    assert main(["panel", "--agent"]) == 0
    p = AuditLog(govaios_home).path
    assert not p.exists() or "ui_login" not in p.read_text()
