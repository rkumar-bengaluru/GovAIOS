"""Localhost-only web UI over the signed audit log: cookie session after a Touch ID login; the only write is revocation."""
import hmac
import json
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from govaios import auth
from govaios.approvals import Approvals
from govaios.audit.log import AuditLog
from govaios.audit.verify import verify

COLS = ["kind", "flow", "step", "action", "target", "decision", "approver", "channel", "outcome", "reason",
        "response_code", "listing_id", "auth", "command", "file_hash"]
CSS = ("body{font:14px system-ui;margin:2em}table{border-collapse:collapse}td,th{border:1px solid #bbb;"
       "padding:3px 8px;text-align:left}.ok{background:#d8f5d8;padding:6px}.fail{background:#f8d0d0;padding:6px}")


def _entries(log: AuditLog):
    """Every line in file order as (entry dict or None, raw text); unparsable lines are kept, not dropped."""
    try:
        lines = log.path.read_bytes().split(b"\n")
    except OSError:
        return []
    if lines and not lines[-1]:
        lines.pop()
    out = []
    for raw in lines:
        try:
            e = json.loads(raw)
        except (ValueError, RecursionError):
            e = None
        out.append((e if isinstance(e, dict) else None, raw.decode("utf-8", "replace")[:200]))
    return out


def _seq(e):
    s = e.get("seq")
    return s if type(s) is int else None


def _runs(entries):
    """Entries from each flow_start (valid int seq) through its flow_end or stop. Returns (runs, anomaly count)."""
    runs, cur, odd = [], None, 0
    for e, _ in entries:
        if e is None:
            odd += 1
        elif e.get("kind") == "flow_start" and _seq(e) is not None:
            cur = [e]
            runs.append(cur)
        elif cur is not None:
            cur.append(e)
            if e.get("kind") in ("flow_end", "stop"):
                cur = None
        elif (e.get("kind") in ("action", "request") and e.get("flow") not in (None, "claude_code")
              and not (e.get("kind") == "request" and e.get("action") == "deliver")):
            odd += 1   # a flow step outside a run; hook, stop, login, revoke, dump and deliver entries are normal here
    return runs, odd


def _td(v):
    return f"<td>{escape('' if v is None else str(v))}</td>"


def _page(body):
    return f"<!doctype html><meta charset=utf-8><title>GOV-AIOS audit</title><style>{CSS}</style>{body}"


LOGIN_TTL, SESSION_TTL = 60, 3600


def make_server(home: Path, port: int = 0, now=time.time):
    """Returns (server, login code). The caller has already proven presence."""
    log = AuditLog(home)
    approvals_path = Path(home) / "approvals.json"
    code = secrets.token_urlsafe(32)
    state = {"code_ts": now(), "code_used": False, "sessions": {}}  # sid -> (created, csrf)

    def banner():
        try:
            r = verify(log.path, log.pub_path)
        except (OSError, ValueError) as e:
            return f"<p class=fail>FAIL: {escape(str(e))}</p>"
        if r.ok:
            return f"<p class=ok>OK {r.entries} entries</p>"
        return f"<p class=fail>FAIL line {r.line}: {escape(str(r.problem))}</p>"

    def index():
        runs, orphans = _runs(_entries(log))
        note = f"<p class=fail>{orphans} entries outside any run</p>" if orphans else ""
        rows = "".join(
            f"<tr><td><a href='/run/{int(r[0]['seq'])}'>{int(r[0]['seq'])}</a></td>{_td(r[0].get('flow'))}"
            f"{_td(r[0].get('ts'))}{_td(sum(1 for e in r if e.get('kind') == 'action'))}"
            f"{_td(r[-1].get('outcome') or r[-1].get('kind'))}</tr>" for r in runs)
        table = (f"<table><tr><th>run</th><th>flow</th><th>time</th><th>steps</th><th>outcome</th></tr>{rows}</table>"
                 if runs else "<p>No runs yet.</p>")
        return _page(f"<h1>Runs</h1>{banner()}{note}{table}<p><a href='/log'>Full log</a> <a href='/approvals'>Approvals</a></p>")

    def run(seq):
        for r in _runs(_entries(log))[0]:
            if r[0]["seq"] == seq:
                head = "".join(f"<th>{c}</th>" for c in COLS)
                rows = "".join("<tr>" + "".join(_td(e.get(c)) for c in COLS) + "</tr>" for e in r)
                return _page(f"<h1>Run {int(seq)}</h1>{banner()}<table><tr>{head}</tr>{rows}</table>"
                             f"<p><a href='/'>Runs</a></p>")
        return None

    def fulllog():
        head = "".join(f"<th>{c}</th>" for c in ["seq", "ts", *COLS])
        rows = "".join(
            "<tr>" + "".join(_td(e.get(c)) for c in ["seq", "ts", *COLS]) + "</tr>" if e is not None
            else f"<tr><td colspan={len(COLS) + 2} class=fail>unparsed: {escape(raw)}</td></tr>" for e, raw in _entries(log))
        return _page(f"<h1>Full log</h1>{banner()}<table><tr>{head}</tr>{rows}</table>"
                     f"<p><a href='/'>Runs</a></p>")

    def approvals(csrf):
        bad = "<p class=fail>approvals.json unreadable</p>"
        try:
            d = json.loads(approvals_path.read_text())
        except FileNotFoundError:
            d = {}
        except (OSError, ValueError):
            d = None
        if not isinstance(d, dict):
            d = None
        flows, dests = (d or {}).get("flows", {}), (d or {}).get("destinations", {})
        if not (isinstance(d, dict) and isinstance(flows, dict) and isinstance(dests, dict)
                and all(isinstance(v, list) for v in dests.values())):
            return _page(f"<h1>Approvals</h1>{bad}<p><a href='/'>Runs</a></p>")
        def form(kind, flow="", dest="", label="Revoke"):
            return (f"<form method=post action=/revoke><input type=hidden name=csrf value='{escape(csrf)}'>"
                    f"<input type=hidden name=kind value={kind}><input type=hidden name=flow value='{escape(flow)}'>"
                    f"<input type=hidden name=destination value='{escape(dest)}'><button>{label}</button></form>")
        fr = "".join(f"<tr>{_td(k)}{_td(v)}<td>{form('flow', str(k), label='Revoke flow')}</td></tr>" for k, v in flows.items())
        dr = "".join(f"<tr>{_td(k)}{_td(d)}<td>{form('destination', str(k), str(d), label='Revoke site')}</td></tr>"
                     for k, v in dests.items() for d in v)
        return _page(f"<h1>Approvals</h1><h2>Flows</h2><table><tr><th>flow</th><th>hash</th><th></th></tr>{fr}</table>"
                     f"<h2>Destinations</h2><table><tr><th>flow</th><th>destination</th><th></th></tr>{dr}</table>"
                     f"{form('all', label='Revoke all')}"
                     f"<p><a href='/'>Runs</a></p>")

    # same-origin, not no-referrer: under no-referrer Chrome sends `Origin: null` on our own form POSTs (revoke 403)
    SEC = (("Cache-Control", "no-store"), ("Referrer-Policy", "same-origin"), ("X-Content-Type-Options", "nosniff"),
           ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"))
    code_lock = threading.Lock()

    def guarded(fn):
        """Host and lock checks run first on every method and path; a locked screen ends the server."""
        def wrapper(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_address[1]}":
                return self._send(403)
            if auth.screen_locked():
                state["sessions"].clear()
                threading.Thread(target=self.server.shutdown, daemon=True).start()  # not from the handler thread
                return self._send(403)
            return fn(self)
        return wrapper

    class H(BaseHTTPRequestHandler):
        timeout = 10  # a short body must not hold a thread forever

        def _send(self, status, body=""):
            data = body.encode() if body else f"{status}".encode()
            self.send_response(status)
            for k, v in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(data))), *SEC):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def send_error(self, code, message=None, explain=None):  # parse-level errors keep the headers too
            self._send(code)

        def log_message(self, *a):  # default logging would print the login code
            pass

        def _session(self):
            """(created, csrf) of a live session, else None. Expiry ends the server."""
            if any(now() - c > SESSION_TTL for c, _ in state["sessions"].values()):
                state["sessions"].clear()
                threading.Thread(target=self.server.shutdown, daemon=True).start()  # not from the handler thread
                return None
            try:
                sid = SimpleCookie(self.headers.get("Cookie", ""))["s"].value
            except (KeyError, ValueError):
                return None
            for k, v in state["sessions"].items():
                if hmac.compare_digest(k.encode(), sid.encode()):
                    return v
            return None

        @guarded
        def do_GET(self):
            u = urlsplit(self.path)
            if u.path == "/login":
                c = parse_qs(u.query).get("c", [""])[0]
                with code_lock:  # check-and-set: two concurrent requests cannot both log in
                    fresh = not state["code_used"] and now() - state["code_ts"] < LOGIN_TTL
                    if not (hmac.compare_digest(c.encode(), code.encode()) and fresh):
                        return self._send(403)
                    state["code_used"] = True
                sid = secrets.token_urlsafe(32)
                state["sessions"][sid] = (now(), secrets.token_urlsafe(32))
                self.send_response(303)
                for k, v in (("Set-Cookie", f"s={sid}; HttpOnly; SameSite=Strict; Path=/"), ("Location", "/"),
                             ("Content-Length", "0"), *SEC):
                    self.send_header(k, v)
                return self.end_headers()
            sess = self._session()
            if not sess:
                return self._send(403)
            try:
                m = re.fullmatch(r"/run/([0-9]{1,9})", u.path)
                page = (index() if u.path == "/" else approvals(sess[1]) if u.path == "/approvals"
                        else fulllog() if u.path == "/log" else run(int(m[1])) if m else None)
            except Exception:  # tampered data must not leak a traceback; body stays fixed
                return self._send(500, "internal error")
            self._send(200, page) if page else self._send(404)

        @guarded
        def do_POST(self):
            if urlsplit(self.path).path != "/revoke":
                return self._send(405)
            sess = self._session()
            origin = self.headers.get("Origin")  # absent is fine (row 37); a wrong one is not
            if not sess or (origin is not None and origin != f"http://127.0.0.1:{self.server.server_address[1]}"):
                return self._send(403)
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if not 0 <= n <= 65536:
                return self._send(400)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace")).items()}
            if not hmac.compare_digest(f.get("csrf", "").encode(), sess[1].encode()):
                return self._send(403)
            kind, flow, dest = f.get("kind"), f.get("flow", ""), f.get("destination", "")
            ap = Approvals(approvals_path)
            if kind == "flow" and flow:
                fields, apply = {"flow": flow}, lambda: ap.revoke_flow(flow)
            elif kind == "destination" and flow and dest:
                fields, apply = {"flow": flow, "destination": dest}, lambda: ap.revoke_destination(flow, dest)
            elif kind == "all":
                fields, apply = {"reason": "all"}, ap.revoke_all
            else:
                return self._send(400)
            try:
                log.append("revoke", **fields)   # audit first, then apply
            except Exception:
                return self._send(500, "internal error")
            try:
                apply()
            except Exception:   # the log must not be left saying "revoked" while the approval stands
                try:
                    log.append("revoke", outcome="error", **fields)
                except Exception:
                    pass   # already answering 500; nothing more can be recorded
                return self._send(500, "internal error")
            self.send_response(303)
            for k, v in (("Location", "/approvals"), ("Content-Length", "0"), *SEC):
                self.send_header(k, v)
            self.end_headers()

        @guarded
        def _no(self):
            self._send(405)

        do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _no

    return ThreadingHTTPServer(("127.0.0.1", port), H), code
