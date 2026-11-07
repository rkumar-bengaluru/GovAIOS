import sys
import pytest
import json
import os
import stat

from govaios.panel import agentlog


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: POSIX file mode 0600")
def test_log_rotates_at_cap(tmp_path):
    (tmp_path / "panel.log").write_text("x" * 50)
    f = agentlog.open_log(tmp_path, cap=10)
    f.write("new\n")
    f.close()
    assert (tmp_path / "panel.log.1").read_text() == "x" * 50
    assert (tmp_path / "panel.log").read_text() == "new\n"
    assert stat.S_IMODE(os.stat(tmp_path / "panel.log").st_mode) == 0o600


def test_once_throttles_same_line_60s(tmp_path):
    t = [100.0]
    assert agentlog.once(tmp_path, "boom", now=lambda: t[0])
    t[0] = 130
    assert not agentlog.once(tmp_path, "boom", now=lambda: t[0])
    assert agentlog.once(tmp_path, "other", now=lambda: t[0])
    t[0] = 200
    assert agentlog.once(tmp_path, "other", now=lambda: t[0])
    assert (tmp_path / "panel.log").read_text() == "boom\nother\nother\n"
    assert json.loads((tmp_path / "panel.log.last").read_text())["line"] == "other"


def test_once_corrupt_or_missing_last_writes(tmp_path):
    assert agentlog.once(tmp_path, "a")   # no .last
    (tmp_path / "panel.log.last").write_text("not json")
    assert agentlog.once(tmp_path, "a")
    assert (tmp_path / "panel.log").read_text() == "a\na\n"


def test_once_same_line_after_61s(tmp_path):
    assert agentlog.once(tmp_path, "x", now=lambda: 0)
    assert agentlog.once(tmp_path, "x", now=lambda: 61)


def test_once_does_not_rotate_live_log(tmp_path):
    (tmp_path / "panel.log").write_text("x" * 50)
    live = agentlog.open_log(tmp_path, cap=1000)   # the process holds it
    assert agentlog.once(tmp_path, "err")
    live.write("more\n")
    live.close()
    assert not (tmp_path / "panel.log.1").exists()
    assert (tmp_path / "panel.log").read_text() == "x" * 50 + "err\nmore\n"


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: POSIX file mode 0600")
def test_permissions_tightened(tmp_path):
    for n in ("panel.log", "panel.log.last"):
        (tmp_path / n).write_text("")
        os.chmod(tmp_path / n, 0o644)
    agentlog.open_log(tmp_path).close()
    assert agentlog.once(tmp_path, "z", now=lambda: 0)
    for n in ("panel.log", "panel.log.last"):
        assert stat.S_IMODE(os.stat(tmp_path / n).st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: POSIX file mode 0600")
def test_rotated_file_is_0600(tmp_path):
    (tmp_path / "panel.log").write_text("x" * 50)
    os.chmod(tmp_path / "panel.log", 0o644)
    agentlog.open_log(tmp_path, cap=10).close()
    assert stat.S_IMODE(os.stat(tmp_path / "panel.log.1").st_mode) == 0o600


def test_append_at_cap_is_dropped(tmp_path):
    (tmp_path / "panel.log").write_text("x" * 20)
    assert not agentlog.once(tmp_path, "more", cap=20)
    assert (tmp_path / "panel.log").stat().st_size == 20
    assert agentlog.once(tmp_path, "more", cap=21)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows: panel not supported this cycle (os.O_NOFOLLOW)")
def test_handle_error_one_line_no_traceback(tmp_path):
    from govaios.audit.web import make_server
    srv = make_server(tmp_path, tick_s=None)
    try:
        try:
            raise ConnectionResetError("secret-peer")
        except ConnectionResetError:
            srv.handle_error(None, ("203.0.113.9", 5555))
        text = (tmp_path / "panel.log").read_text()
        assert text == "panel: request error (ConnectionResetError)\n"
    finally:
        srv.server_close()
