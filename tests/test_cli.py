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
        cli.main(["run", "x.yaml", "--dev"])
    """)
    (tmp_path / "x.yaml").write_text("")
    r = subprocess.run([sys.executable, "-c", driver], cwd=tmp_path, capture_output=True, text=True,
                       env={"PATH": "/usr/bin", "GOVAIOS_HOME": str(tmp_path / "h"), "PYTHONPATH": str(__import__("os").getcwd())})
    assert r.returncode != 0
    assert "network blocked" in r.stderr and "DEV MODE" in r.stderr


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
