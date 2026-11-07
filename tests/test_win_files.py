import os
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@pytest.fixture
def files():
    from govaios.win import files as f
    return f


def test_flock_nonblocking_busy_from_other_process(files, tmp_path):
    lock = tmp_path / "x.lock"
    code = (
        "import sys, time\n"
        "from govaios.win import files\n"
        f"f = open(r'{lock}', 'a')\n"
        "files.flock_ex(f)\n"
        "print('held', flush=True)\n"
        "time.sleep(2)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                             cwd=os.getcwd(), env={**os.environ, "PYTHONUTF8": "1"})
    try:
        assert child.stdout.readline().strip() == "held"
        with open(lock, "a") as f:
            with pytest.raises(BlockingIOError):
                files.flock_ex(f, blocking=False)
    finally:
        child.kill()
        child.wait()


def test_flock_ignores_file_position(files, tmp_path):
    p = tmp_path / "x.lock"
    p.write_text("abc")
    with open(p, "a") as a, open(p, "a") as b:
        files.flock_ex(a)
        with pytest.raises(BlockingIOError):
            files.flock_ex(b, blocking=False)
        files.funlock(a)
        files.flock_ex(b, blocking=False)
        files.funlock(b)


def test_flock_accepts_fd_and_funlock_unlocked_is_quiet(files, tmp_path):
    fd = os.open(tmp_path / "y.lock", os.O_RDWR | os.O_CREAT | os.O_BINARY)
    try:
        files.funlock(fd)
        files.flock_ex(fd, blocking=False)
        files.funlock(fd)
    finally:
        os.close(fd)


def test_open_nofollow_refuses_junction(files, tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    with pytest.raises(OSError):
        files.open_nofollow(link, os.O_RDONLY)


def test_open_nofollow_opens_regular_file(files, tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"hi")
    fd = files.open_nofollow(p, os.O_RDONLY)
    try:
        assert os.read(fd, 2) == b"hi"
    finally:
        os.close(fd)


def test_user_folders(files):
    assert files.user_home().is_dir()
    assert files.local_appdata().is_dir()
    assert files.display_name()
