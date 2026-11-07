import importlib
import os
import subprocess
import sys

import pytest

from govaios.sandbox import RUN_PROFILE, apply as real_apply   # before conftest's autouse patch of sandbox.apply

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

MODULES = ["govaios.cli", "govaios.engine", "govaios.auth", "govaios.guard", "govaios.hook", "govaios.powers",
           "govaios.runstate", "govaios.delivery", "govaios.audit.log", "govaios.audit.web", "govaios.panel.settings"]


@pytest.mark.parametrize("m", MODULES)
def test_imports_on_windows(m):
    importlib.import_module(m)


def test_default_data_home_is_localappdata(monkeypatch, tmp_path):
    from govaios import home
    from govaios.win import files
    monkeypatch.delenv("GOVAIOS_HOME")
    monkeypatch.setattr(files, "local_appdata", lambda: tmp_path)
    assert home.data_home() == tmp_path / "GOV-AIOS"
    assert (tmp_path / "GOV-AIOS").is_dir()


def test_govaios_home_still_overrides(monkeypatch, tmp_path):
    from govaios import home
    monkeypatch.setenv("GOVAIOS_HOME", str(tmp_path / "h"))
    assert home.data_home() == tmp_path / "h"


def test_audit_append_and_verify_on_windows(tmp_path):
    from govaios.audit.log import AuditLog
    from govaios.audit.verify import main as verify_main
    log = AuditLog(tmp_path)
    log.append("resume", decision="allow")
    log.append("resume", decision="deny")
    assert verify_main([str(log.path), str(log.pub_path)]) == 0


def test_netguard_blocks_everything_on_windows():   # in a subprocess: block_all_network is one-way
    code = ("from govaios.netguard import block_all_network as b; b()\n"
            "import socket\ntry: socket.socket()\nexcept PermissionError: print('blocked')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=os.getcwd(), env={**os.environ, "PYTHONUTF8": "1"})
    assert out.stdout.strip() == "blocked", out.stderr


def test_sandbox_apply_is_notice_on_windows(capsys):
    real_apply(RUN_PROFILE)
    assert "DEV: no OS network lockdown on Windows; in-process block only" in capsys.readouterr().err
