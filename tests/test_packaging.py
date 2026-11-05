import importlib.util
import getpass
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("handback", Path(__file__).parent.parent / "packaging/handback.py")
handback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handback)

ME = getpass.getuser()


def run(home):
    # "root" is replaced by the current uid; chown to self works unprivileged
    return handback.main(str(home), ME, owner_uid=os.getuid())


def make(tmp_path):
    d = tmp_path / "Library/Application Support/GOV-AIOS"
    d.mkdir(parents=True)
    return d


def test_missing_data_home_ok(tmp_path):
    (tmp_path / "Library/Application Support").mkdir(parents=True)
    assert run(tmp_path) == 0


def test_dir_and_file_handled(tmp_path):
    d = make(tmp_path)
    (d / "sub").mkdir()
    (d / "sub/f").write_text("x")
    assert run(tmp_path) == 0


def test_hard_link_left_over(tmp_path, capsys):
    d = make(tmp_path)
    (d / "a").write_text("x")
    os.link(d / "a", d / "b")
    assert run(tmp_path) == 1
    assert "./a" in capsys.readouterr().err


def test_symlink_entry_left_over(tmp_path):
    d = make(tmp_path)
    os.symlink("/etc/hosts", d / "l")
    assert run(tmp_path) == 1


def test_symlinked_components_refused(tmp_path):
    real = tmp_path / "real"
    (real / "Application Support/GOV-AIOS").mkdir(parents=True)
    h = tmp_path / "h1"
    h.mkdir()
    os.symlink(real, h / "Library")
    assert run(h) == 1
    h2 = tmp_path / "h2"
    (h2 / "Library").mkdir(parents=True)
    os.symlink(real / "Application Support", h2 / "Library/Application Support")
    assert run(h2) == 1
    h3 = tmp_path / "h3"
    (h3 / "Library/Application Support").mkdir(parents=True)
    os.symlink(real / "Application Support/GOV-AIOS", h3 / "Library/Application Support/GOV-AIOS")
    assert run(h3) == 1
