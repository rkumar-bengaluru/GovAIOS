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


# --- panel agent, apps seeding ---
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PK = ROOT / "packaging"
END_LINE = "Control panel: http://127.0.0.1:8765/  (sign in with Touch ID on the page)"


def test_panel_plist_shape():
    p = plistlib.loads((PK / "com.govaios.panel.plist").read_bytes())
    assert p["Label"] == "com.govaios.panel"
    assert p["ProgramArguments"] == ["/Applications/gov-aios.app/Contents/MacOS/gov-aios", "panel", "--agent"]
    assert p["RunAtLoad"] is True
    assert p["KeepAlive"] == {"SuccessfulExit": False}
    assert p["ThrottleInterval"] == 30
    assert "StandardOutPath" not in p and "StandardErrorPath" not in p


def seed(src, dest):
    return subprocess.run(["/bin/bash", str(PK / "seed-apps.sh"), str(src), str(dest)],
                          capture_output=True, text=True, timeout=30)


def repo(tmp_path, pages=True):
    r = tmp_path / "repo"
    (r / "flows").mkdir(parents=True)
    (r / "flows/x.yaml").write_text("new")
    (r / "flows/y.yaml").write_text("same")
    if pages:
        (r / "pages").mkdir()
        (r / "pages/p.yaml").write_text("pnew")
    return r


def test_seed_apps_never_overwrites(tmp_path):
    r = repo(tmp_path)
    dest = tmp_path / "apps"
    (dest / "flows").mkdir(parents=True)
    (dest / "flows/x.yaml").write_text("edited")
    (dest / "flows/y.yaml").write_text("same")
    (dest / "pages").mkdir()
    (dest / "pages/p.yaml").write_text("pedited")
    p = seed(r, dest)
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["not updated: flows/x.yaml", "not updated: pages/p.yaml"]
    assert (dest / "flows/x.yaml").read_bytes() == b"edited"
    assert (dest / "pages/p.yaml").read_bytes() == b"pedited"
    assert (dest / "flows").stat().st_mode & 0o777 == 0o700


def test_seed_apps_copies_missing_and_tolerates_no_pages(tmp_path):
    r = repo(tmp_path, pages=False)
    dest = tmp_path / "apps"
    p = seed(r, dest)
    assert p.returncode == 0 and p.stdout == ""
    assert (dest / "flows/x.yaml").read_text() == "new"
    assert (dest / "pages").is_dir() and (dest / "pages").stat().st_mode & 0o777 == 0o700
    assert seed(r, dest).stdout == ""  # second run: identical, silent


def test_seed_apps_refuses_symlinks(tmp_path):
    r = repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = tmp_path / "apps"
    os.symlink(elsewhere, link)
    assert seed(r, link).returncode == 1 and list(elsewhere.iterdir()) == []
    dest = tmp_path / "apps2"
    dest.mkdir()
    os.symlink(elsewhere, dest / "flows")
    assert seed(r, dest).returncode == 1 and list(elsewhere.iterdir()) == []
    # a symlinked entry is not written through
    dest3 = tmp_path / "apps3"
    (dest3 / "flows").mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.write_text("keep")
    os.symlink(victim, dest3 / "flows/x.yaml")
    p = seed(r, dest3)
    assert "not updated: flows/x.yaml" in p.stdout and victim.read_text() == "keep"


def test_install_mentions_address():
    s = (PK / "install.sh").read_text()
    assert s.rstrip().splitlines()[-1] == f'echo "{END_LINE}"'
    assert 'bootout "gui/$UID_N/com.govaios.panel"' in s
    assert "lsof -nP -iTCP:8765 -sTCP:LISTEN" in s
    assert 'sudo -u "$SUDO_USER" /usr/bin/install -m 0644 packaging/com.govaios.panel.plist' in s
    assert s.index("port 8765 is in use") < s.index('boot panel "$PANEL_PLIST"')


def test_uninstall_removes_panel_agent():
    s = (PK / "uninstall.sh").read_text()
    assert 'launchctl bootout "gui/$UID_N/com.govaios.panel"' in s
    assert 'sudo -u "$SUDO_USER" rm -f "$UHOME/Library/LaunchAgents/com.govaios.panel.plist"' in s
    for line in s.splitlines():
        if line.lstrip().startswith("#") or "rm " not in line:
            continue
        assert "apps" not in line and "Application Support/GOV-AIOS" not in line and "$DATA" not in line


def test_install_seeds_before_swap():
    s = (PK / "install.sh").read_text()
    seed_i = s.index("packaging/seed-apps.sh")
    assert s.index("packaging/handback.py") < s.index("umask 077; /bin/mkdir -p") < seed_i < s.index("launchctl bootout")
    assert seed_i < s.index('rm -rf "/Applications/gov-aios.app"')
    assert s.index("codesign --verify --strict \"-R=$REQ\"") < seed_i
    assert 'boot guard "$PLIST"' in s


def test_seed_creates_missing_parents_0700(tmp_path):
    dest = tmp_path / "a/b/apps"
    assert seed(repo(tmp_path), dest).returncode == 0
    for d in (tmp_path / "a", tmp_path / "a/b", dest, dest / "flows", dest / "pages"):
        assert d.stat().st_mode & 0o777 == 0o700, d


def test_seed_existing_0755_apps_ends_0700(tmp_path):
    dest = tmp_path / "apps"
    dest.mkdir(mode=0o755)
    os.chmod(dest, 0o755)
    assert seed(repo(tmp_path), dest).returncode == 0
    assert dest.stat().st_mode & 0o777 == 0o700


def test_seed_dangling_symlink_not_written_through(tmp_path):
    dest = tmp_path / "apps"
    (dest / "flows").mkdir(parents=True)
    target = tmp_path / "nowhere"
    os.symlink(target, dest / "flows/x.yaml")
    p = seed(repo(tmp_path), dest)
    assert p.returncode == 0 and "not updated: flows/x.yaml" in p.stdout
    assert not target.exists() and os.readlink(dest / "flows/x.yaml") == str(target)
    assert (dest / "flows/y.yaml").read_text() == "same"  # the rest still copied


def test_seed_odd_names(tmp_path):
    r = repo(tmp_path)
    (r / "flows/-dash.yaml").write_text("d")
    (r / "flows/with space.yaml").write_text("s")
    dest = tmp_path / "apps"
    assert seed(r, dest).returncode == 0
    assert (dest / "flows/-dash.yaml").read_text() == "d"
    assert (dest / "flows/with space.yaml").read_text() == "s"
    assert (dest / "flows/x.yaml").stat().st_mode & 0o777 == 0o600


def test_seed_failed_write_leaves_no_partial_file(tmp_path):
    r = repo(tmp_path, pages=False)
    dest = tmp_path / "apps"
    # file-size limit 0 with SIGXFSZ ignored: the write fails with EFBIG after the create
    p = subprocess.run(["/bin/bash", "-c", "trap '' XFSZ; ulimit -f 0; exec /bin/bash \"$0\" \"$1\" \"$2\"",
                        str(PK / "seed-apps.sh"), str(r), str(dest)], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0
    assert "not updated: flows/x.yaml" in p.stdout.splitlines()
    assert not (dest / "flows/x.yaml").exists()
