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


def test_symlink_to_dir_not_followed(tmp_path):
    d = make(tmp_path)
    target = tmp_path / "target"
    target.mkdir()
    (target / "f").write_text("x")
    os.link(target / "f", target / "g")  # would be reported if the walk followed the link
    os.symlink(target, d / "l")
    assert run(tmp_path) == 1  # the symlink itself is left over
    assert sorted(os.listdir(target)) == ["f", "g"]


def test_fifo_reported_not_opened(tmp_path, capsys):
    import signal
    d = make(tmp_path)
    os.mkfifo(d / "p")
    signal.alarm(5)  # a blocking open would hang here
    try:
        assert run(tmp_path) == 1
    finally:
        signal.alarm(0)
    assert "./p" in capsys.readouterr().err


def test_unreadable_subdir_reported(tmp_path, capsys):
    d = make(tmp_path)
    (d / "sub").mkdir()
    (d / "sub").chmod(0)
    try:
        assert run(tmp_path) == 1
        assert "./sub" in capsys.readouterr().err
    finally:
        (d / "sub").chmod(0o700)


def test_walk_leaks_no_fds(tmp_path):
    d = make(tmp_path)
    for i in range(20):
        (d / f"d{i}").mkdir()
    before = len(os.listdir("/dev/fd"))
    assert run(tmp_path) == 0
    assert len(os.listdir("/dev/fd")) == before


def test_uninstall_hardened_like_install():
    """M-7: static checks only (the script is never run by tests)."""
    from pathlib import Path
    s = (Path(__file__).parent.parent / "packaging" / "uninstall.sh").read_text()
    assert s.startswith("#!/bin/bash\n") and "set -euo pipefail" in s
    assert "export PATH=/usr/bin:/bin:/usr/sbin:/sbin" in s and "dscl" not in s
    assert "/usr/bin/python3 -I -c 'import pwd" in s
    assert 'sudo -u "$SUDO_USER" rm -f "$UHOME/Library/LaunchAgents/com.govaios.guard.plist"' in s
    assert "\nrm -f \"$UHOME" not in s
