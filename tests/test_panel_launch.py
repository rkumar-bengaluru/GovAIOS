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
  trap 'echo term >> "$CALLS"; exit 143' TERM
  [ -n "${FAKE_PID_DELAY:-}" ] && { sleep "$FAKE_PID_DELAY" & wait $!; }
  echo $$ > "$GOVAIOS_PID_FILE"
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
    assert lines.count("term") == 1 and sum("--args" in x for x in lines) == 1   # one SIGTERM, not two


def test_summary_captured(env, monkeypatch):
    s = "deliver joblens: delivered 2, duplicate 3, retry 0, failed 0, skipped 0"
    monkeypatch.setenv("FAKE_LINE", s)
    r, _ = run(env)
    assert r.summary == s


def test_stop_before_launch_prevents_any_launch(env):
    fake, flow, calls = env
    r = RunLaunch(flow, "t1", app="/app", open_cmd=str(fake))
    r.stop("early")
    r.start()
    end = time.time() + 3
    while not r.done and time.time() < end:
        time.sleep(0.02)
    assert r.done and r.stopped_reason == "early" and not calls.exists()


def test_missing_open_cmd(env):
    _, flow, _ = env
    r = RunLaunch(flow, "t1", app="/app", open_cmd="/nonexistent/open")
    r.start()
    end = time.time() + 3
    while not r.done and time.time() < end:
        time.sleep(0.02)
    assert r.done and r.code == 70 and r.lines() == ["launch failed: FileNotFoundError"]


def test_stop_after_finish_is_not_a_stop(env):
    r, _ = run(env)
    r.stop("session ended")
    assert r.code == 0 and r.stopped_reason is None


def test_late_pid_still_gets_sigterm(env, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "8")
    monkeypatch.setenv("FAKE_PID_DELAY", "2.5")   # a cold start slower than stop's 2 s wait
    fake, flow, calls = env
    r = RunLaunch(flow, "t1", app="/app", open_cmd=str(fake))
    r.start()
    end = time.time() + 3
    while not calls.exists() and time.time() < end:
        time.sleep(0.02)
    time.sleep(0.1)
    r.stop("session ended")
    end = time.time() + 5
    while not r.done and time.time() < end:
        time.sleep(0.02)
    assert r.done and r.stopped_reason == "session ended"
    lines = calls.read_text().splitlines()
    assert "term" in lines and sum("--args" in x for x in lines) == 1


def test_runlaunch_passes_input_env(env):
    fake, flow, calls = env
    inputs = {"job_url": "https://himalayas.app/companies/a/jobs/b"}
    r = RunLaunch(flow, "t1", app="/app", open_cmd=str(fake), inputs=inputs)
    r.start()
    end = time.time() + 10
    while not r.done and time.time() < end:
        time.sleep(0.02)
    c = calls.read_text().splitlines()
    assert 'GOVAIOS_RUN_INPUT={"job_url": "https://himalayas.app/companies/a/jobs/b"}' in c[0]
    assert "GOVAIOS_RUN_INPUT" not in c[1]


def test_runlaunch_inputs_is_third_positional(env):
    fake, flow, calls = env
    r = RunLaunch(flow, "t1", {"job_url": "u"}, open_cmd=str(fake))   # launcher(path, ticket, inputs) shape
    r.start()
    end = time.time() + 10
    while not r.done and time.time() < end:
        time.sleep(0.02)
    c = calls.read_text().splitlines()[0]
    assert 'GOVAIOS_RUN_INPUT={"job_url": "u"}' in c and "-a /Applications/gov-aios.app" in c


@pytest.mark.parametrize("line, want", [("capture saved: captures/20261108-201918-912751-job_apply.json",
                                         "20261108-201918-912751-job_apply.json"),
                                        ("capture saved: captures/../../x.json", None)])
def test_last_capture_name_kept(env, monkeypatch, line, want):
    monkeypatch.setenv("FAKE_LINE", line)
    r, _ = run(env)
    assert r.capture == want
