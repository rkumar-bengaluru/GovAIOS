from govaios import identity
from govaios.cli import main


def test_check_keys():
    assert set(identity.check()) == {"bundle_id", "frozen", "accessibility", "screen_recording"}


def test_not_frozen_under_pytest():
    assert identity.check()["frozen"] is False


def test_exit_file_written(tmp_path, monkeypatch):
    f = tmp_path / "x"
    monkeypatch.setenv("GOVAIOS_EXIT_FILE", str(f))
    monkeypatch.setattr(
        identity, "check",
        lambda: {"bundle_id": "com.govaios.cli", "frozen": True, "accessibility": True, "screen_recording": True},
    )
    assert main(["doctor"]) == 0
    assert f.read_text().strip() == "0"
