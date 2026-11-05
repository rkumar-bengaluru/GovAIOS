"""Row 22 probe: sandbox_init with the plan-2 profiles, then check what still works.

Usage (always in a throwaway process: sandbox_init cannot be undone):
  python probe_sandbox.py run            # RUN_PROFILE: network checks + no-prompt API checks
  python probe_sandbox.py ui --drive     # UI_PROFILE; unsandboxed parent fetches the served URL
  python probe_sandbox.py run --tcc      # + AX / CGEvent / activate / osascript / LAContext (signed app, admin)
  python probe_sandbox.py run --exec     # apply via /usr/bin/sandbox-exec -p instead (fallback)
  ... --original                         # row 22's first strings, without the mDNSResponder deny (row 39)
Prints one line per check: PASS/FAIL <name> <detail>. Never prints window titles or page content.
"""
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time

_BASE = ('(version 1) (allow default) (deny network*) (allow network* (remote unix-socket)) '
         '(deny mach-lookup (global-name "com.apple.dnssd.service"))')
_UI_BIND = ' (allow network-bind network-inbound (local ip "localhost:*"))'
# Row 39: libinfo reaches mDNSResponder over this Unix socket, which the unix-socket allow lets through.
DNS_FIX = '(deny network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))'
# Final strings, verbatim from amended row 22 (DNS_FIX last, so it overrides the unix-socket allow).
RUN_PROFILE = _BASE + " " + DNS_FIX
UI_PROFILE = _BASE + _UI_BIND + " " + DNS_FIX
# Row 22's first strings (--original), kept to reproduce row 39.
ORIGINAL = {"run": _BASE, "ui": _BASE + _UI_BIND}

# Working ctypes binding (Task 5/6 copy this).
_lib = ctypes.CDLL("/usr/lib/libsandbox.1.dylib")
_lib.sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
_lib.sandbox_init.restype = ctypes.c_int
_lib.sandbox_free_error.argtypes = [ctypes.c_char_p]


def sandbox_init(profile: str) -> None:
    err = ctypes.c_char_p()
    if _lib.sandbox_init(profile.encode(), 0, ctypes.byref(err)) != 0:
        msg = err.value.decode() if err.value else "unknown"
        _lib.sandbox_free_error(err)
        raise OSError(f"sandbox_init failed: {msg}")


def report(ok: bool, name: str, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name} {detail}".rstrip(), flush=True)


def expect_fail(name, fn):
    try:
        fn()
        report(False, name, "unexpectedly succeeded")
    except Exception as e:
        report(True, name, f"blocked: {type(e).__name__}: {e}")


def expect_ok(name, fn):
    try:
        report(True, name, str(fn() or ""))
    except Exception as e:
        report(False, name, f"{type(e).__name__}: {e}")


def net_checks(profile_name):
    expect_fail("tcp 1.1.1.1:443", lambda: socket.create_connection(("1.1.1.1", 443), timeout=3).close())
    import random
    fresh = f"p{random.randint(0, 10**9)}.10.0.0.1.nip.io"  # wildcard DNS: exists, never cached
    expect_fail("dns example.com", lambda: socket.getaddrinfo("example.com", 443))
    expect_fail("dns uncached <rand>.10.0.0.1.nip.io", lambda: socket.getaddrinfo(fresh, 443))
    expect_fail("child curl https://example.com",
                lambda: subprocess.run(["/usr/bin/curl", "-sS", "-m", "5", "-o", "/dev/null", "https://example.com"],
                                       check=True, capture_output=True))

    def pair():
        a, b = socket.socketpair()
        a.sendall(b"x")
        assert b.recv(1) == b"x"
        return "socketpair ok"
    expect_ok("unix socketpair", pair)

    def unix_path():
        path = f"/tmp/govaios-probe-{os.getpid()}.sock"
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(path)
        srv.listen(1)
        try:
            c = socket.socket(socket.AF_UNIX)
            c.connect(path)
            s, _ = srv.accept()
            c.sendall(b"y")
            assert s.recv(1) == b"y"
            return "named unix socket ok"
        finally:
            os.unlink(path)
    expect_ok("unix named socket", unix_path)

    if profile_name == "run":
        expect_fail("bind 127.0.0.1:0", lambda: socket.create_server(("127.0.0.1", 0)).close())


def ui_checks():
    """Serve one request on 127.0.0.1:0; the client is an unsandboxed process (stands in for the browser)."""
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"govaios-probe-ok")

        def log_message(self, *a):
            pass

    try:
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    except Exception as e:
        report(False, "http.server bind 127.0.0.1:0", f"{type(e).__name__}: {e}")
        return
    port = srv.server_address[1]
    report(True, "http.server bind 127.0.0.1:0", f"port {port}")
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    # The client must live outside our sandbox: ask the parent (run_child) or the admin's browser.
    print(f"URL http://127.0.0.1:{port}/", flush=True)
    t.join(30)
    report(not t.is_alive(), "http.server served a request", "" if not t.is_alive() else "no request within 30 s")
    expect_fail("outbound from sandbox to localhost (expected blocked)",
                lambda: socket.create_connection(("127.0.0.1", port), timeout=2).close())


def api_checks():
    """No-prompt pyobjc calls the subcommands make; must still be callable inside the sandbox."""
    import AppKit
    import ApplicationServices as AS
    import LocalAuthentication as LA

    expect_ok("AXIsProcessTrusted callable", lambda: f"returned {bool(AS.AXIsProcessTrusted())}")
    expect_ok("NSWorkspace.runningApplications",
              lambda: f"{len(AppKit.NSWorkspace.sharedWorkspace().runningApplications())} apps")
    for name, pol in (("biometrics", LA.LAPolicyDeviceOwnerAuthenticationWithBiometrics),
                      ("device_owner", LA.LAPolicyDeviceOwnerAuthentication)):
        ok, err = LA.LAContext.alloc().init().canEvaluatePolicy_error_(pol, None)
        report(bool(ok), f"LAContext canEvaluate {name}", f"error={err.code() if err else None}")


def tcc_checks():
    import AppKit
    import ApplicationServices as AS
    import Quartz

    report(bool(AS.AXIsProcessTrusted()), "AXIsProcessTrusted", str(bool(AS.AXIsProcessTrusted())))

    chrome = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.google.Chrome")
    if not chrome:
        report(False, "chrome running", "start Chrome first")
    else:
        pid = chrome[0].processIdentifier()
        app = AS.AXUIElementCreateApplication(pid)
        err, wins = AS.AXUIElementCopyAttributeValue(app, "AXWindows", None)
        if err or not wins:
            report(False, "AX read Chrome windows", f"AXError {err}")
        else:
            err2, title = AS.AXUIElementCopyAttributeValue(wins[0], "AXTitle", None)
            # Privacy: report only that a title was read, never the title.
            report(err2 == 0 and title is not None, "AX read Chrome window title",
                   f"windows={len(wins)} title_len={len(title) if title else 0}")
        for down in (True, False):  # left shift (56): harmless
            Quartz.CGEventPostToPid(pid, Quartz.CGEventCreateKeyboardEvent(None, 56, down))
        print("INFO CGEventPostToPid shift posted (effect unverified)", flush=True)

    finder = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.apple.finder")
    ok = bool(finder) and finder[0].activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
    report(bool(ok), "NSRunningApplication activate Finder", str(bool(ok)))

    r = subprocess.run(["/usr/bin/osascript", "-e",
                        'display dialog "GOV-AIOS sandbox probe: click OK" buttons {"OK"} '
                        'default button "OK" giving up after 30'],
                       capture_output=True, text=True)
    out = (r.stdout or r.stderr).strip()
    report(r.returncode == 0 and "gave up:true" not in out, "osascript dialog", out)

    import LocalAuthentication as LA
    ctx = LA.LAContext.alloc().init()
    can, err = ctx.canEvaluatePolicy_error_(LA.LAPolicyDeviceOwnerAuthentication, None)
    report(bool(can), "LAContext canEvaluate device-owner", str(err))
    done = threading.Event()
    res = {}

    def reply(success, error):
        res["ok"], res["err"] = bool(success), error
        done.set()
    ctx.evaluatePolicy_localizedReason_reply_(LA.LAPolicyDeviceOwnerAuthentication, "approve: sandbox probe", reply)
    done.wait(60)
    report(res.get("ok", False), "LAContext prompt", str(res) if res else "no reply in 60 s")


def drive(argv):
    """Unsandboxed parent: run the probe in a child and play the browser for any URL it prints."""
    import urllib.request
    child = subprocess.Popen([sys.executable, __file__, *[a for a in argv if a != "--drive"]],
                             stdout=subprocess.PIPE, text=True)
    for line in child.stdout:
        print(line, end="", flush=True)
        if line.startswith("URL "):
            body = urllib.request.urlopen(line.split()[1], timeout=5).read()
            print(f"parent GET -> {body!r}", flush=True)
    return child.wait()


def main(argv):
    if "--drive" in argv:
        return drive(argv)
    profile_name = argv[0] if argv and argv[0] in ("run", "ui") else "run"
    profile = UI_PROFILE if profile_name == "ui" else RUN_PROFILE
    if "--original" in argv:
        profile = ORIGINAL[profile_name]
    if "--exec" in argv and os.environ.get("GOVAIOS_PROBE_EXECED") != "1":
        os.environ["GOVAIOS_PROBE_EXECED"] = "1"
        os.execv("/usr/bin/sandbox-exec", ["sandbox-exec", "-p", profile, sys.executable, *sys.argv])
    if os.environ.get("GOVAIOS_PROBE_EXECED") == "1":
        report(True, "sandbox-exec -p applied", profile_name)
    else:
        try:
            sandbox_init(profile)
            report(True, "sandbox_init accepted", profile_name)
        except OSError as e:
            report(False, "sandbox_init accepted", str(e))
            return 1
    if profile_name == "ui":
        ui_checks()
    net_checks(profile_name)
    api_checks()
    if "--tcc" in argv:
        tcc_checks()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
