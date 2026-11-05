"""Read-only, localhost-only web UI over the signed audit log. GET only; fixed routes."""
import json
import re
import secrets
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from govaios.audit.log import AuditLog
from govaios.audit.verify import verify

COLS = ["kind", "step", "action", "target", "decision", "approver", "channel", "outcome", "reason"]
CSS = ("body{font:14px system-ui;margin:2em}table{border-collapse:collapse}td,th{border:1px solid #bbb;"
       "padding:3px 8px;text-align:left}.ok{background:#d8f5d8;padding:6px}.fail{background:#f8d0d0;padding:6px}")


def _entries(log: AuditLog):
    try:
        lines = log.path.read_bytes().split(b"\n")
    except OSError:
        return []
    out = []
    for raw in lines:
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def _runs(entries):
    """Entries from each flow_start through its flow_end or stop."""
    runs, cur = [], None
    for e in entries:
        if e.get("kind") == "flow_start":
            cur = [e]
            runs.append(cur)
        elif cur is not None:
            cur.append(e)
            if e.get("kind") in ("flow_end", "stop"):
                cur = None
    return runs


def _td(v):
    return f"<td>{escape('' if v is None else str(v))}</td>"


def _page(body):
    return f"<!doctype html><meta charset=utf-8><title>GOV-AIOS audit</title><style>{CSS}</style>{body}"


def make_server(home: Path, port: int = 0):
    log = AuditLog(home)
    approvals_path = Path(home) / "approvals.json"
    token = secrets.token_urlsafe(32)

    def banner():
        try:
            r = verify(log.path, log.pub_path)
        except (OSError, ValueError) as e:
            return f"<p class=fail>FAIL: {escape(str(e))}</p>"
        if r.ok:
            return f"<p class=ok>OK {r.entries} entries</p>"
        return f"<p class=fail>FAIL line {r.line}: {escape(str(r.problem))}</p>"

    def index(q):
        runs = _runs(_entries(log))
        rows = "".join(
            f"<tr><td><a href='/run/{r[0]['seq']}?t={q}'>{r[0]['seq']}</a></td>{_td(r[0].get('flow'))}"
            f"{_td(r[0].get('ts'))}{_td(sum(1 for e in r if e.get('kind') == 'action'))}"
            f"{_td(r[-1].get('outcome') or r[-1].get('kind'))}</tr>" for r in runs)
        table = (f"<table><tr><th>run</th><th>flow</th><th>time</th><th>steps</th><th>outcome</th></tr>{rows}</table>"
                 if runs else "<p>No runs yet.</p>")
        return _page(f"<h1>Runs</h1>{banner()}{table}<p><a href='/approvals?t={q}'>Approvals</a></p>")

    def run(seq, q):
        for r in _runs(_entries(log)):
            if r[0]["seq"] == seq:
                head = "".join(f"<th>{c}</th>" for c in COLS)
                rows = "".join("<tr>" + "".join(_td(e.get(c)) for c in COLS) + "</tr>" for e in r)
                return _page(f"<h1>Run {seq}</h1>{banner()}<table><tr>{head}</tr>{rows}</table>"
                             f"<p><a href='/?t={q}'>Runs</a></p>")
        return None

    def approvals(q):
        try:
            d = json.loads(approvals_path.read_text())
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        flows = "".join(f"<tr>{_td(k)}{_td(v)}</tr>" for k, v in (d.get("flows") or {}).items())
        dests = "".join(f"<tr>{_td(k)}{_td(', '.join(map(str, v)) if isinstance(v, list) else v)}</tr>"
                        for k, v in (d.get("destinations") or {}).items())
        return _page(f"<h1>Approvals</h1><h2>Flows</h2><table><tr><th>flow</th><th>hash</th></tr>{flows}</table>"
                     f"<h2>Destinations</h2><table><tr><th>flow</th><th>destinations</th></tr>{dests}</table>"
                     f"<p><a href='/?t={q}'>Runs</a></p>")

    class H(BaseHTTPRequestHandler):
        def _send(self, status, body=""):
            data = body.encode() if body else f"{status}".encode()
            self.send_response(status)
            for k, v in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(data))),
                         ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"),
                         ("X-Content-Type-Options", "nosniff"),
                         ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def send_error(self, code, message=None, explain=None):  # parse-level errors keep the headers too
            self._send(code)

        def log_message(self, *a):  # default logging would print the token
            pass

        def do_GET(self):
            u = urlsplit(self.path)
            # shortcut: URL token, not Touch ID; replaced by admin authentication in plan 2.
            t = parse_qs(u.query).get("t", [""])[0]
            if not secrets.compare_digest(t.encode(), token.encode()):
                return self._send(403)
            if u.path == "/":
                return self._send(200, index(token))
            if u.path == "/approvals":
                return self._send(200, approvals(token))
            m = re.fullmatch(r"/run/([0-9]{1,9})", u.path)
            page = run(int(m[1]), token) if m else None
            self._send(200, page) if page else self._send(404)

        def _no(self):
            self._send(405)

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _no

    return ThreadingHTTPServer(("127.0.0.1", port), H), token
