import json
import os
import stat

from govaios.panel import agentlog


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
