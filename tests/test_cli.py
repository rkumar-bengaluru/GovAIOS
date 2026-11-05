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
    assert data_home() == tmp_path / "Library/Application Support/GOV-AIOS"


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
