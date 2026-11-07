"""The launch helper: a real forked child, a fake `open` and a fake `say`."""
import os
import time

import pytest

from govaios.panel.helper import start_helper
from test_panel_launch import FAKE_OPEN

pytestmark = pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")

TICKET = "ab" * 32
FAKE_SAY = '#!/bin/bash\nprintf "%s\\n" "$@" > "$SAID"\n'


@pytest.fixture
def h(tmp_path, monkeypatch):
    fake, say = tmp_path / "open", tmp_path / "say"
    fake.write_text(FAKE_OPEN)
    say.write_text(FAKE_SAY)
    fake.chmod(0o755), say.chmod(0o755)
    monkeypatch.setenv("CALLS", str(tmp_path / "calls"))
    monkeypatch.setenv("SAID", str(tmp_path / "said"))
    flows, home = tmp_path / "flows", tmp_path / "home"
    flows.mkdir()
    (home / "tickets").mkdir(parents=True)
    (home / "tickets" / TICKET).write_text("{}")
    (flows / "flow.yaml").write_text("x")
    helper = start_helper(flows, home, open_cmd=str(fake), say_cmd=str(say))
    helper.tmp = tmp_path
    yield helper
    helper.close()
    assert helper.exited   # no leaked child


def wait(cond, s=8):
    end = time.time() + s
    while not cond() and time.time() < end:
        time.sleep(0.02)
    return cond()


def calls(h):
    p = h.tmp / "calls"
    return p.read_text().splitlines() if p.exists() else []


def test_helper_runs_with_fake_open(h):
    r = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    assert r.ticket == TICKET and not r.done
    r.start()
    assert wait(lambda: r.done)
    assert r.code == 0 and r.stopped_reason is None and r.lines() == ["out-run", "out-deliver"]
    assert f"GOVAIOS_RUN_TICKET={TICKET}" in calls(h)[0]


def test_helper_refuses_flow_outside_dir(h):
    flows = h.tmp / "flows"
    (h.tmp / "x.yaml").write_text("x")
    (flows / "link.yaml").symlink_to(h.tmp / "x.yaml")
    (flows / "notes.txt").write_text("x")
    for p in (flows / ".." / "x.yaml", flows / "link.yaml", flows / "notes.txt", flows):
        r = h.run(p, TICKET)
        r.start()
        assert wait(lambda: r.done) and r.code == 70 and r.error == "refused", p
    assert calls(h) == []


def test_helper_refuses_bad_ticket(h):
    for t in ("AB" * 32, "ab" * 31, TICKET + "\n", "cd" * 32, 5):   # last two: no such ticket file, not a str
        r = h.run(h.tmp / "flows" / "flow.yaml", t)
        r.start()
        assert wait(lambda: r.done) and r.code == 70 and r.error == "refused", t
    assert calls(h) == []


@pytest.fixture
def slow(monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "5")


def test_helper_refuses_second_live_run(slow, h):
    a = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    a.start()
    assert wait(lambda: any("--args" in x for x in calls(h)))
    b = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    b.start()
    assert wait(lambda: b.done) and b.error == "refused" and not a.done
    a.stop("x")
    assert wait(lambda: a.done) and a.stopped_reason == "x"


def test_helper_stop(slow, h):
    r = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    r.start()
    assert wait(lambda: any("--args" in x for x in calls(h)))
    time.sleep(0.3)   # the fake has written its pid
    r.stop("session ended")
    assert wait(lambda: r.done)
    assert r.stopped_reason == "session ended" and "term" in calls(h)


def test_helper_exits_and_stops_run_on_pipe_close(slow, h):
    r = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    r.start()
    assert wait(lambda: any("--args" in x for x in calls(h)))
    time.sleep(0.3)
    h.close()
    assert h.exited and "term" in calls(h)


def test_helper_say_uses_double_dash(h):
    h.say("-v Zarvox " + "x" * 400)
    said = h.tmp / "said"
    assert wait(said.exists)
    assert wait(lambda: said.read_text().splitlines() == ["--", ("-v Zarvox " + "x" * 400)[:300]])


def test_helper_child_dies_ends_runs(slow, h):
    r = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    r.start()
    assert wait(lambda: any("--args" in x for x in calls(h)))
    os.kill(h.pid, 9)
    assert wait(lambda: r.done) and r.code == 70


def test_helper_ignores_garbage_then_runs(h):
    with h._lock:
        h._w.write('not json\n[1, 2]\n"str"\n{"op": "nope", "id": 1}\n{"op": "run", "id": "1"}\n')
        h._w.flush()
    for m in ({"op": "stop", "id": 99, "reason": "x"}, {"op": "stop", "id": 1, "reason": 5}, {"op": "say", "text": 5}):
        h._send(m)
    r = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    r.start()
    assert wait(lambda: r.done) and r.code == 0 and r.stopped_reason is None


def test_helper_child_ignores_sigterm(slow, h):
    import signal
    r = h.run(h.tmp / "flows" / "flow.yaml", TICKET)
    r.start()
    assert wait(lambda: any("--args" in x for x in calls(h)))
    time.sleep(0.3)
    os.kill(h.pid, signal.SIGTERM)
    time.sleep(0.3)
    assert os.waitpid(h.pid, os.WNOHANG) == (0, 0) and not r.done   # still alive, run still live
    h.close()
    assert h.exited and "term" in calls(h)   # the pipe still ends it, stopping the app


@pytest.fixture
def adm(tmp_path, monkeypatch):
    """A helper whose administrator dialog is faked: argv runs as this user, into a temp ClaudeCode folder."""
    import subprocess
    flows, home, ms = tmp_path / "flows", tmp_path / "home", tmp_path / "ClaudeCode"
    flows.mkdir()
    (home / "executors").mkdir(parents=True)
    answer = tmp_path / "answer"   # "cancel": the admin cancels the dialog

    def elevate(argv, prompt):
        (tmp_path / "prompt").write_text(prompt)
        return 2 if answer.exists() else subprocess.run(argv).returncode
    helper = start_helper(flows, home, elevate=elevate, ms_dir=str(ms), owner=f"{os.getuid()}:{os.getgid()}")
    helper.home, helper.ms, helper.tmp, helper.answer = home, ms, tmp_path, answer
    yield helper
    helper.close()
    assert helper.exited


def _stage(h, data=b'{"hooks": {}}\n'):
    import hashlib
    (h.home / "executors" / "managed-settings.json").write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_claude_install_copies_only_the_approved_bytes(adm):
    d = _stage(adm)
    assert adm.claude("install", d) == 0
    dst = adm.ms / "managed-settings.json"
    assert dst.read_bytes() == b'{"hooks": {}}\n' and oct(dst.stat().st_mode & 0o777) == "0o644"
    assert "install the Claude Code managed settings" in (adm.tmp / "prompt").read_text()
    assert [p.name for p in adm.ms.iterdir()] == ["managed-settings.json"]   # no temp file left


def test_claude_install_refuses_swapped_file(adm):
    d = _stage(adm)
    _stage(adm, b'{"hooks": {}, "evil": 1}\n')   # changed after approval
    assert adm.claude("install", d) == 3
    assert not (adm.ms / "managed-settings.json").exists() and list(adm.ms.iterdir()) == []


def test_claude_remove_and_cancel(adm):
    assert adm.claude("install", _stage(adm)) == 0
    adm.answer.write_text("cancel")
    assert adm.claude("remove") == 2 and (adm.ms / "managed-settings.json").exists()
    adm.answer.unlink()
    assert adm.claude("remove") == 0 and not (adm.ms / "managed-settings.json").exists()


@pytest.mark.parametrize("action,digest", [("install", "x"), ("install", ""), ("wipe", "ab" * 32), (None, "")])
def test_claude_bad_requests_refused(adm, action, digest):
    assert adm.claude(action, digest) == 70 and not (adm.tmp / "prompt").exists()
