"""Plan 4 spike, part 1 (throwaway): can a run-sandboxed child live under a deliver-sandboxed parent?

Usage: .venv/bin/python spikes/plan4/probe_sandbox_nesting.py
Top level (no sandbox) starts `parent`; parent applies DELIVER_PROFILE and starts a fresh `child`
(a new interpreter, not a fork); child applies RUN_PROFILE on top. Network checks are TCP connect
then close, never a request. EPERM = sandbox denied; ECONNREFUSED/connected = allowed through.
"""
import errno
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from govaios.sandbox import RUN_PROFILE, _BASE, _DNS_FIX, apply  # noqa: E402

DELIVER_PROFILE = _BASE + ' (allow network-outbound (remote ip "localhost:8100"))' + " " + _DNS_FIX
results = []


def report(ok, name, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} [{sys.argv[1] if len(sys.argv) > 1 else 'top'}] {name} {detail}".rstrip(), flush=True)


def connect(host, port, family=socket.AF_INET):
    """'allowed' (connected or refused by the peer), 'denied' (EPERM/EACCES from the sandbox) or 'other:<err>'."""
    s = socket.socket(family, socket.SOCK_STREAM)
    s.settimeout(3)
    try:
        s.connect((host, port))
        return "allowed"
    except OSError as e:
        if e.errno in (errno.ECONNREFUSED,):
            return "allowed"
        if e.errno in (errno.EPERM, errno.EACCES):
            return "denied"
        return f"other:{errno.errorcode.get(e.errno, e.errno)}"
    finally:
        s.close()


def dns_fails():
    try:
        socket.getaddrinfo("example.com", 443)
        return False
    except OSError:
        return True


def socketpair_ok():
    a, b = socket.socketpair()
    a.sendall(b"x")
    ok = b.recv(1) == b"x"
    a.close(), b.close()
    return ok


def parent():
    try:
        apply(DELIVER_PROFILE)
        report(True, "sandbox_init DELIVER_PROFILE")
    except RuntimeError as e:
        report(False, "sandbox_init DELIVER_PROFILE", str(e))
        return 1
    report(connect("127.0.0.1", 8100) == "allowed", "parent -> 127.0.0.1:8100 allowed", connect("127.0.0.1", 8100))
    report(connect("127.0.0.1", 8000) == "denied", "parent -> 127.0.0.1:8000 denied", connect("127.0.0.1", 8000))
    report(connect("1.1.1.1", 443) == "denied", "parent -> 1.1.1.1:443 denied", connect("1.1.1.1", 443))
    report(dns_fails(), "parent DNS lookup fails")
    report(socketpair_ok(), "parent socketpair works")
    child = subprocess.Popen([sys.executable, __file__, "child"])
    time.sleep(4)   # child runs its checks, then waits for SIGTERM
    child.send_signal(signal.SIGTERM)
    rc = child.wait(10)
    report(rc == 42, "child got SIGTERM from parent (exit 42)", f"rc={rc}")
    return 0


def child():
    def term(*_):
        print("INFO [child] SIGTERM received", flush=True)
        os._exit(42)
    signal.signal(signal.SIGTERM, term)
    report(connect("127.0.0.1", 8100) == "allowed", "child (before own sandbox) inherits :8100 allowed",
           connect("127.0.0.1", 8100))
    try:
        apply(RUN_PROFILE)
        report(True, "sandbox_init RUN_PROFILE on top (nesting accepted)")
    except RuntimeError as e:
        report(False, "sandbox_init RUN_PROFILE on top (nesting accepted)", str(e))
    report(connect("127.0.0.1", 8100) == "denied", "child -> 127.0.0.1:8100 denied", connect("127.0.0.1", 8100))
    report(connect("127.0.0.1", 8000) == "denied", "child -> 127.0.0.1:8000 denied", connect("127.0.0.1", 8000))
    report(connect("::1", 8100, socket.AF_INET6) == "denied", "child -> [::1]:8100 denied",
           connect("::1", 8100, socket.AF_INET6))
    report(dns_fails(), "child DNS lookup fails")
    report(socketpair_ok(), "child socketpair works")
    ok = all(results)
    print(f"INFO [child] checks {'all PASS' if ok else 'had FAIL'}; waiting for SIGTERM", flush=True)
    time.sleep(30)
    return 1


def top():
    report(connect("127.0.0.1", 8000) == "allowed", "control: unsandboxed -> 127.0.0.1:8000 allowed")
    rc = subprocess.run([sys.executable, __file__, "parent"]).returncode
    print(f"done: parent rc={rc}")
    return rc


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "top"
    sys.exit({"top": top, "parent": parent, "child": child}[mode]())
