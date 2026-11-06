import os
import pwd
import sys
from pathlib import Path

from govaios.home import data_home


def test_frozen_home_ignores_HOME(monkeypatch):
    monkeypatch.delenv("GOVAIOS_HOME", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("HOME", "/tmp/elsewhere")
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: None)
    assert data_home() == Path(pwd.getpwuid(os.getuid()).pw_dir) / "Library/Application Support/GOV-AIOS"
