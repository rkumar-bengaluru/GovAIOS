"""Sandbox tests run in child processes: sandbox_init cannot be undone, so never apply it to pytest itself."""
import socket
import subprocess
import sys
import threading
import urllib.request

from govaios import sandbox


def child(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)


def test_run_profile_blocks_tcp_and_dns():
    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    r = child(f"""
import socket
from govaios import sandbox
sandbox.apply(sandbox.RUN_PROFILE)
def ok(f):
    try:
        f()
        return "open"
    except Exception:
        return "blocked"
print("tcp", ok(lambda: socket.create_connection(("127.0.0.1", {port}), timeout=3)))
print("dns", ok(lambda: socket.getaddrinfo("example.com", 80)))
a, b = socket.socketpair(); a.sendall(b"x")
print("pair", b.recv(1) == b"x")
""")
    srv.close()
    assert r.stdout.split("\n")[:3] == ["tcp blocked", "dns blocked", "pair True"], r.stderr


def test_ui_profile_serves_localhost():
    p = subprocess.Popen([sys.executable, "-c", """
import http.server, socket
from govaios import sandbox
sandbox.apply(sandbox.UI_PROFILE)
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
s = http.server.HTTPServer(("127.0.0.1", 0), H)
print(s.server_address[1], flush=True)
s.handle_request()
try:
    socket.create_connection(("127.0.0.1", s.server_address[1]), timeout=2)
    print("outbound open")
except Exception:
    print("outbound blocked")
"""], stdout=subprocess.PIPE, text=True)
    try:
        port = int(p.stdout.readline())
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).status == 200
        assert p.stdout.readline().strip() == "outbound blocked"
    finally:
        p.kill()
        p.wait()
        p.stdout.close()


def test_bad_profile_raises():
    r = child("""
from govaios import sandbox
try:
    sandbox.apply("(version 1) (bogus)")
except RuntimeError as e:
    print("RuntimeError", e)
""")
    assert "RuntimeError sandbox refused" in r.stdout, r.stderr
