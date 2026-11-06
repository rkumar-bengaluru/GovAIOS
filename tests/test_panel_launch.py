import time

import pytest

from govaios.panel.launch import RunLaunch

FAKE_OPEN = r'''#!/bin/bash
echo "$*" >> "$CALLS"
while [ $# -gt 0 ]; do
  case "$1" in
    --stdout) so=$2; shift 2;;
    --stderr) shift 2;;
    --env) export "$2"; shift 2;;
    --args) shift; break;;
    *) shift;;
  esac
done
if [ -n "${FAKE_SLEEP:-}" ] && [ "$1" = run ]; then
  echo $$ > "$GOVAIOS_PID_FILE"
  trap 'echo term >> "$CALLS"; exit 143' TERM
  sleep "$FAKE_SLEEP" & wait $!
fi
echo "${FAKE_CODE-0}" > "$GOVAIOS_EXIT_FILE"
echo "out-$1" > "$so"
[ -n "${FAKE_LINE:-}" ] && [ "$1" = deliver ] && echo "$FAKE_LINE" >> "$so"
if [ "$1" = run ] && [ "${FAKE_NEXT:-1}" = 1 ] && [ -n "${GOVAIOS_NEXT_FILE:-}" ]; then
  printf deliver > "$GOVAIOS_NEXT_FILE"
fi
'''


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = tmp_path / "open"
    fake.write_text(FAKE_OPEN)
    fake.chmod(0o755)
    calls = tmp_path / "calls"
    monkeypatch.setenv("CALLS", str(calls))
    flow = tmp_path / "flow.yaml"
    flow.write_text("x")
    return fake, flow, calls


def run(env, wait=10):
    fake, flow, calls = env
    r = RunLaunch(flow, "t1", app="/app", open_cmd=str(fake))
    r.start()
    end = time.time() + wait
    while not r.done and time.time() < end:
        time.sleep(0.02)
    return r, (calls.read_text().splitlines() if calls.exists() else [])


def test_run_then_deliver(env):
    r, calls = run(env)
    assert r.done and r.code == 0
    assert len(calls) == 2
    assert "GOVAIOS_RUN_TICKET=t1" in calls[0] and "GOVAIOS_RUN_TICKET" not in calls[1]
    assert r.lines() == ["out-run", "out-deliver"]


def test_failed_run_no_deliver(env, monkeypatch):
    monkeypatch.setenv("FAKE_CODE", "1")
    r, calls = run(env)
    assert r.code == 1 and len(calls) == 1


def test_empty_exit_file_is_70(env, monkeypatch):
    monkeypatch.setenv("FAKE_CODE", "")
    r, _ = run(env)
    assert r.code == 70


def test_stop_kills_and_skips_deliver(env, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "5")
    fake, flow, calls = env
    r = RunLaunch(flow, "t1", app="/app", open_cmd=str(fake))
    r.start()
    time.sleep(0.5)
    t0 = time.time()
    r.stop("session ended")
    while not r.done and time.time() - t0 < 3:
        time.sleep(0.02)
    assert r.done and r.stopped_reason == "session ended"
    lines = calls.read_text().splitlines()
    assert "term" in lines and sum("--args" in x for x in lines) == 1


def test_summary_captured(env, monkeypatch):
    s = "deliver joblens: delivered 2, duplicate 3, retry 0, failed 0, skipped 0"
    monkeypatch.setenv("FAKE_LINE", s)
    r, _ = run(env)
    assert r.summary == s
