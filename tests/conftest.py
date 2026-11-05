import os

import pytest

from govaios import sandbox


@pytest.fixture(autouse=True)
def govaios_home(tmp_path, monkeypatch):
    home = tmp_path / "govaios-home"
    monkeypatch.setenv("GOVAIOS_HOME", str(home))
    yield home
    # The audit log is UF_APPEND; clear flags under this test's tmp_path only (some tests use it as Runner home).
    for root, dirs, files in os.walk(tmp_path):
        for n in dirs + files:
            os.chflags(os.path.join(root, n), 0, follow_symlinks=False)


@pytest.fixture(autouse=True)
def sandbox_calls(monkeypatch):
    """sandbox_init cannot be undone: never in the pytest process (row 28). Child-process tests use the real one."""
    calls = []
    monkeypatch.setattr(sandbox, "apply", calls.append)
    return calls
