import os
import subprocess
import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent
PRELUDE = "from govaios.netguard import block_all_network\nblock_all_network()\n"


def run_py(code):
    # The block is permanent for a process, so every case gets its own interpreter.
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, env=env)


def test_inet_connect_blocked():
    r = run_py(PRELUDE + "import socket\nsocket.create_connection(('127.0.0.1', 9))\n")
    assert r.returncode != 0
    assert "network blocked" in r.stderr


def test_urllib_blocked():
    r = run_py(PRELUDE + "import urllib.request\nurllib.request.urlopen('https://example.com')\n")
    assert r.returncode != 0
    assert "network blocked" in r.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: AF_UNIX sockets")
def test_unix_socket_allowed():
    r = run_py(PRELUDE + "import socket\ns = socket.socket(socket.AF_UNIX)\ns.close()\nprint('ok')\n")
    assert r.returncode == 0
    assert "ok" in r.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="macOS: osascript")
def test_osascript_dialog_unaffected():
    code = PRELUDE + "import subprocess, sys\nsys.exit(subprocess.run(['osascript', '-e', 'return 1'], capture_output=True).returncode)\n"
    assert run_py(code).returncode == 0


def test_block_all_network_twice_still_blocks():
    code = (
        PRELUDE
        + "block_all_network()\n"
        + "import socket\n"
        + "for call in (lambda: socket.create_connection(('127.0.0.1', 9)), lambda: socket.getaddrinfo('localhost', 80)):\n"
        + "    try:\n        call()\n    except PermissionError as e:\n        assert 'network blocked' in str(e)\n    else:\n        raise SystemExit('not blocked')\n"
    )
    r = run_py(code)
    assert r.returncode == 0, r.stderr


def test_dns_lookup_blocked():
    r = run_py(PRELUDE + "import socket\nsocket.gethostbyname('example.com')\n")
    assert r.returncode != 0
    assert "network blocked" in r.stderr
