import os
import subprocess
from pathlib import Path

FAKE_OPEN = r'''#!/bin/bash
while [ $# -gt 0 ]; do
  case "$1" in
    --stdout) so=$2; shift 2;;
    --stderr) shift 2;;
    --env) export "$2"; shift 2;;
    --args) shift; break;;
    *) shift;;
  esac
done
echo "$*" >> "$CALLS"
echo "${FAKE_CODE:-0}" > "$GOVAIOS_EXIT_FILE"
echo "out-$1" > "$so"
if [ "$1" = run ] && [ "${FAKE_NEXT:-0}" = 1 ] && [ -n "${GOVAIOS_NEXT_FILE:-}" ]; then
  printf deliver > "$GOVAIOS_NEXT_FILE"
fi
'''


def shim(tmp_path, *args, **env):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "open").write_text(FAKE_OPEN)
    (bindir / "open").chmod(0o755)
    app = tmp_path / "app"
    app.mkdir()
    flow = tmp_path / "flow.yaml"
    flow.write_text("x")
    calls = tmp_path / "calls"
    e = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", GOVAIOS_APP=str(app),
             CALLS=str(calls), **env)
    root = Path(__file__).resolve().parent.parent
    args = [str(flow) if a == "FLOW" else a for a in args]
    p = subprocess.run(["/bin/bash", str(root / "bin/gov-aios"), *args],
                       env=e, capture_output=True, text=True, timeout=30)
    return p, (calls.read_text().splitlines() if calls.exists() else []), str(flow)


def test_shim_launches_once_without_next(tmp_path):
    p, calls, flow = shim(tmp_path, "run", "FLOW", FAKE_NEXT="0")
    assert p.returncode == 0 and calls == [f"run {flow}"]


def test_shim_launches_deliver_after_run(tmp_path):
    p, calls, flow = shim(tmp_path, "run", "FLOW", FAKE_NEXT="1")
    assert p.returncode == 0
    assert calls == [f"run {flow}", f"deliver {flow}"]
    assert "out-run" in p.stdout and "out-deliver" in p.stdout


def test_shim_no_deliver_after_failed_run(tmp_path):
    p, calls, flow = shim(tmp_path, "run", "FLOW", FAKE_NEXT="1", FAKE_CODE="1")
    assert p.returncode == 1 and calls == [f"run {flow}"]


def test_shim_next_ignored_for_other_subcommands(tmp_path):
    p, calls, _ = shim(tmp_path, "doctor", FAKE_NEXT="1")
    assert p.returncode == 0 and calls == ["doctor"]


def test_shim_forwards_flags_before_flow(tmp_path):
    p, calls, flow = shim(tmp_path, "run", "--dev", "FLOW", FAKE_NEXT="1")
    assert calls == [f"run --dev {flow}", f"deliver --dev {flow}"]


def test_shim_forwards_flags_after_flow(tmp_path):
    p, calls, flow = shim(tmp_path, "run", "FLOW", "--dev", FAKE_NEXT="1")
    assert calls == [f"run {flow} --dev", f"deliver {flow} --dev"]
