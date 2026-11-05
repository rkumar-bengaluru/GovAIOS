from govaios import identity
from govaios.cli import main


def test_check_keys():
    assert set(identity.check()) == {"bundle_id", "frozen", "accessibility", "screen_recording"}


def test_not_frozen_under_pytest():
    assert identity.check()["frozen"] is False


def test_exit_file_written(tmp_path, monkeypatch):
    f = tmp_path / "x"
    f.write_text("")   # the shim's mktemp file
    monkeypatch.setenv("GOVAIOS_EXIT_FILE", str(f))
    assert main(["selftest", "lines", "1", "--dev"]) == 0   # doctor now needs guard, settings and review fakes
    assert f.read_text().strip() == "0"
