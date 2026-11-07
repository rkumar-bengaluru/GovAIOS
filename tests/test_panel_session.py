import sys
import json
import os
import time

import pytest

from govaios.panel import tickets
from govaios.panel.session import SESSION_S, Session

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows: panel/audit-ui not supported this cycle (os.O_NOFOLLOW)")


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def test_session_lasts_exactly_30_min():
    c = Clock()
    s = Session(c)
    s.open()
    c.t += SESSION_S - 1
    assert s.active()
    c.t += 1
    assert not s.active()


def test_session_not_extended():
    c = Clock()
    s = Session(c)
    s.open()
    c.t += 100
    r = s.remaining()
    with pytest.raises(RuntimeError):
        s.open()
    assert s.remaining() == r


def test_wall_clock_back_does_not_extend(monkeypatch):
    c = Clock()
    s = Session(c)
    s.open()
    c.t += 600
    r = s.remaining()
    monkeypatch.setattr(time, "time", lambda: 0.0)
    assert s.remaining() == r


def test_end_returns_id_once():
    s = Session(Clock())
    sid = s.open()
    assert s.end("ended") == sid
    assert s.end("ended") is None
    assert s.id is None and not s.active()


def test_ticket_once(tmp_path):
    t = tickets.create(tmp_path, "f", "d", "s1", now=lambda: 100.0)
    assert (tmp_path / "tickets").stat().st_mode & 0o777 == 0o700
    assert (tmp_path / "tickets" / t).stat().st_mode & 0o777 == 0o600
    assert tickets.consume(tmp_path, t, "f", "d", now=lambda: 101.0) == "s1"
    assert tickets.consume(tmp_path, t, "f", "d", now=lambda: 101.0) is None


@pytest.mark.parametrize("case", ["expired", "forged", "flow", "digest", "nothex", "symlink", "missing"])
def test_ticket_rejections(tmp_path, case):
    t = tickets.create(tmp_path, "f", "d", "s1", now=lambda: 100.0)
    p = tmp_path / "tickets" / t
    flow, dig, now = "f", "d", 101.0
    if case == "expired":
        now = 161.0
    elif case == "forged":
        p.write_text(json.dumps({"flow": "f", "digest": "d", "session": "s1", "expires": 100 + 3600}))
    elif case == "flow":
        flow = "g"
    elif case == "digest":
        dig = "e"
    elif case == "nothex":
        p.unlink()  # the real ticket is not the one presented
        t = "../x"
    elif case == "symlink":
        target = tmp_path / "real"
        target.write_text(p.read_text())
        p.unlink()
        os.symlink(target, p)
    elif case == "missing":
        p.unlink()
    assert tickets.consume(tmp_path, t, flow, dig, now=lambda: now) is None
    assert not p.exists() and not p.is_symlink()


def test_ticket_race_only_one_wins(tmp_path, monkeypatch):
    t = tickets.create(tmp_path, "f", "d", "s1", now=lambda: 100.0)
    real_open, results = os.open, []

    def racing_open(path, *a, **k):
        if ".used-" in str(path) and not results:
            results.append(tickets.consume(tmp_path, t, "f", "d", now=lambda: 101.0))  # rival
        return real_open(path, *a, **k)

    monkeypatch.setattr(tickets.os, "open", racing_open)
    assert tickets.consume(tmp_path, t, "f", "d", now=lambda: 101.0) == "s1"
    assert results == [None]


@pytest.mark.parametrize("kind", ["fifo", "dir"])
def test_ticket_non_regular(tmp_path, kind):
    (tmp_path / "tickets").mkdir()
    t = "a" * 64
    p = tmp_path / "tickets" / t
    os.mkfifo(p) if kind == "fifo" else p.mkdir()
    assert tickets.consume(tmp_path, t, "f", "d") is None
    assert not p.exists()


@pytest.mark.parametrize("delta,ok", [(0, True), (60, True), (60.01, False), (-0.01, False)])
def test_ticket_boundaries(tmp_path, delta, ok):
    t = tickets.create(tmp_path, "f", "d", "s1", now=lambda: 100.0)
    (tmp_path / "tickets" / t).write_text(json.dumps({"flow": "f", "digest": "d", "session": "s1", "expires": 100.0 + delta}))
    assert (tickets.consume(tmp_path, t, "f", "d", now=lambda: 100.0) is not None) is ok


def test_ticket_expires_equals_now(tmp_path):
    t = tickets.create(tmp_path, "f", "d", "s1", now=lambda: 100.0)
    assert tickets.consume(tmp_path, t, "f", "d", now=lambda: 160.0) == "s1"


def test_open_after_end():
    s = Session(Clock())
    s.open()
    s.end("x")
    assert s.open()


@pytest.mark.parametrize("sid", [None, "", 5])
def test_ticket_bad_session_refused(tmp_path, sid):
    t = tickets.create(tmp_path, "f", "d", "s1", now=lambda: 100.0)
    body = {"flow": "f", "digest": "d", "expires": 160.0}
    if sid is not None:
        body["session"] = sid
    (tmp_path / "tickets" / t).write_text(json.dumps(body))
    assert tickets.consume(tmp_path, t, "f", "d", now=lambda: 101.0) is None
