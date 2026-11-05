import os

import pytest


@pytest.fixture(autouse=True)
def govaios_home(tmp_path, monkeypatch):
    home = tmp_path / "govaios-home"
    monkeypatch.setenv("GOVAIOS_HOME", str(home))
    yield home
    # The audit log is UF_APPEND; clear it so tmp_path can be deleted (only this test's home).
    if home.exists():
        for root, dirs, files in os.walk(home):
            for n in dirs + files:
                os.chflags(os.path.join(root, n), 0)
