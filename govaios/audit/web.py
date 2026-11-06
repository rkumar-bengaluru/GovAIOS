"""Localhost-only control panel: cookie session after a Touch ID login; Talk page (TOTP session, typed commands),
the signed audit log under /audit, approvals with revocation and the authenticator."""
import base64
import hmac
import json
import math
import re
import secrets
import subprocess
import threading
import time
from collections import deque
from http.cookies import SimpleCookie
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from govaios import auth, runstate
from govaios.approvals import Approvals
from govaios.audit.log import AuditLog
from govaios.audit.verify import verify
from govaios.panel import tickets, totp
from govaios.panel.apps import list_apps, match
from govaios.panel.launch import RunLaunch
from govaios.panel.session import Session

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


def _page(body, head=""):
    return f"<!doctype html><meta charset=utf-8>{head}<title>GOV-AIOS</title><style>{CSS}</style>{body}"


def _started_by(run):
    panel = any(e.get("kind") == "request" and e.get("action") == "run_start" and e.get("channel") == "totp_session"
                for e in run)
    return "Panel, session code" if panel else "Terminal, Touch ID"


def _say(text):
    try:
        subprocess.run(["/usr/bin/say", text], timeout=60)
    except Exception:
        pass   # a missing voice must not break the panel


NO_SESSION = "Enter the 6-digit code from your authenticator."


LOGIN_TTL, SESSION_TTL = 60, 3600


def make_server(home: Path, port: int = 0, now=time.time, flows_dir=None, launcher=None, speak=None,
                name="Rupak", session=None, tick_s=1.0, helper=None):
    """Returns (server, login code); server.panel holds the run session, current run and conversation.
    The caller has already proven presence. tick_s=None starts no ticker (tests call server.panel.tick()).
    helper: the launch helper forked before the sandbox; it runs and speaks unless launcher/speak are passed."""
    launcher = launcher or (helper.run if helper else RunLaunch)
    speak = speak or (helper.say if helper else _say)
    home = Path(home)
    log = AuditLog(home)
    approvals_path = home / "approvals.json"
    store = totp.SecretStore(home)
    panel = SimpleNamespace(session=session or Session(), run=None, app=None, convo=deque(maxlen=50),
                            speak=speak, name=name, pending=None, lock=threading.RLock(),
                            told=None, voice=None)

    def tell(line):
        panel.convo.append(f"GOV-AIOS -> {line}")

    def live():
        return panel.run is not None and not panel.run.done

    def end_session(reason, later=None):
        """End the run session (stopping its run), then audit; None when none was open.
        Ending and taking the run share panel.lock with say()'s run start, so a run cannot start unseen;
        run.stop may block (direct RunLaunch: up to 2 s; via the helper it returns at once): it runs after the lock,
        or goes on `later` when the caller holds the lock."""
        with panel.lock:
            sid = panel.session.end(reason)
            run = panel.run if sid is not None and live() else None
        if sid is None:
            return None
        try:
            log.append("session_end", session=sid, reason=reason)
        finally:   # a failed audit line must not leave the run going
            if run is not None:
                stop = lambda: stop_run(run)
                stop() if later is None else later.append(stop)
        return sid
    panel.end_session = end_session

    def stop_run(run):
        """Spend the run's ticket first: an app that starts after stop's wait then refuses to run."""
        try:
            (home / "tickets" / run.ticket).unlink(missing_ok=True)
        finally:
            run.stop("session ended")

    def report():
        """Once per run, when it is done: the result line, then speech on its own thread (say blocks)."""
        with panel.lock:
            r = panel.run
            if r is None or not r.done or panel.told is r:
                return
            panel.told, app = r, panel.app.name
            if r.code == 0 and r.stopped_reason is None:
                tell(f"{app} finished: {(r.summary or 'done').split(': ', 1)[-1]}")
                text = f"{panel.name}, the {app} flow is complete, thank you."
            else:
                why = r.stopped_reason or f"exit {r.code}"
                tell(f"{app} stopped: {why}")
                text = f"{panel.name}, the {app} flow stopped: {why}."
            panel.voice = threading.Thread(target=panel.speak, args=(text,), daemon=True)
            panel.voice.start()

    def close():
        """Shut the server down, but never while its run is live or its result is still being spoken."""
        state["closing"] = True
        report()   # a finished, unreported run gets its line and speech before any shutdown
        with panel.lock:
            busy = live() or (panel.voice is not None and panel.voice.is_alive()) or state["down"]
            state["down"] = state["down"] or not busy
        if not busy:
            threading.Thread(target=server.shutdown, daemon=True).start()   # never from a handler thread

    def tick():
        s = panel.session
        if s.id is not None:
            reason = ("expired" if not s.active() else "screen_lock" if auth.screen_locked()
                      else "emergency_stop" if runstate.stopped(home) else None)
            if reason:
                end_session(reason)   # Session.end hands the id out once: a racing request cannot end it twice
        report()
        if state["closing"]:
            close()
    panel.tick = tick

    def apps():
        return list_apps(flows_dir, home) if flows_dir else []

    def audited(kind, fields, apply):
        log.append(kind, **fields)   # audit first, then apply
        try:
            apply()
        except Exception:   # the log must not be left saying it happened when it did not
            try:
                log.append(kind, outcome="error", **fields)
            except Exception:
                pass   # already answering 500; nothing more can be recorded
            raise
    code = secrets.token_urlsafe(32)
    state = {"code_ts": now(), "code_used": False, "sessions": {}, "closing": False, "down": False}  # sid -> (created, csrf)

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
            f"<tr><td><a href='/audit/run/{int(r[0]['seq'])}'>{int(r[0]['seq'])}</a></td>{_td(r[0].get('flow'))}"
            f"{_td(r[0].get('ts'))}{_td(sum(1 for e in r if e.get('kind') == 'action'))}"
            f"{_td(r[-1].get('outcome') or r[-1].get('kind'))}{_td(_started_by(r))}</tr>" for r in runs)
        table = (f"<table><tr><th>run</th><th>flow</th><th>time</th><th>steps</th><th>outcome</th><th>started by</th></tr>"
                 f"{rows}</table>" if runs else "<p>No runs yet.</p>")
        return _page(f"<h1>Runs</h1>{banner()}{note}{table}<p><a href='/audit/log'>Full log</a> "
                     f"<a href='/approvals'>Approvals</a> <a href='/'>Talk</a></p>")

    def run(seq):
        for r in _runs(_entries(log))[0]:
            if r[0]["seq"] == seq:
                head = "".join(f"<th>{c}</th>" for c in COLS)
                rows = "".join("<tr>" + "".join(_td(e.get(c)) for c in COLS) + "</tr>" for e in r)
                return _page(f"<h1>Run {int(seq)}</h1>{banner()}<table><tr>{head}</tr>{rows}</table>"
                             f"<p><a href='/audit'>Runs</a> <a href='/'>Talk</a></p>")
        return None

    def fulllog():
        head = "".join(f"<th>{c}</th>" for c in ["seq", "ts", *COLS])
        rows = "".join(
            "<tr>" + "".join(_td(e.get(c)) for c in ["seq", "ts", *COLS]) + "</tr>" if e is not None
            else f"<tr><td colspan={len(COLS) + 2} class=fail>unparsed: {escape(raw)}</td></tr>" for e, raw in _entries(log))
        return _page(f"<h1>Full log</h1>{banner()}<table><tr>{head}</tr>{rows}</table>"
                     f"<p><a href='/audit'>Runs</a> <a href='/'>Talk</a></p>")

    def hidden(csrf):
        return f"<input type=hidden name=csrf value='{escape(csrf)}'>"

    def approvals(csrf):
        authn = "<h2>Authenticator</h2>" + (
            "<p><a href='/totp/setup'>Set up</a></p>" if store.load() is None else
            f"<form method=post action=/totp/reset>{hidden(csrf)}<button>Reset authenticator</button></form>")
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
            return _page(f"<h1>Approvals</h1>{bad}{authn}<p><a href='/audit'>Runs</a> <a href='/'>Talk</a></p>")
        def form(kind, flow="", dest="", label="Revoke"):
            return (f"<form method=post action=/revoke><input type=hidden name=csrf value='{escape(csrf)}'>"
                    f"<input type=hidden name=kind value={kind}><input type=hidden name=flow value='{escape(flow)}'>"
                    f"<input type=hidden name=destination value='{escape(dest)}'><button>{label}</button></form>")
        fr = "".join(f"<tr>{_td(k)}{_td(v)}<td>{form('flow', str(k), label='Revoke flow')}</td></tr>" for k, v in flows.items())
        dr = "".join(f"<tr>{_td(k)}{_td(d)}<td>{form('destination', str(k), str(d), label='Revoke site')}</td></tr>"
                     for k, v in dests.items() for d in v)
        return _page(f"<h1>Approvals</h1><h2>Flows</h2><table><tr><th>flow</th><th>hash</th><th></th></tr>{fr}</table>"
                     f"<h2>Destinations</h2><table><tr><th>flow</th><th>destination</th><th></th></tr>{dr}</table>"
                     f"{form('all', label='Revoke all')}{authn}"
                     f"<p><a href='/audit'>Runs</a> <a href='/'>Talk</a></p>")

    def talk(csrf):
        report()   # the page refresh stops once the run is done: show its result on that same load
        s, run, al = panel.session, panel.run, apps()
        with panel.lock:
            convo = list(panel.convo)
        ring = f"Session open: {math.ceil(s.remaining() / 60)} min left" if s.active() else "No session"
        lines = lambda xs: "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in xs) + "</ul>"
        drafts = "".join(f"<li>{escape(a.name)}<form method=post action=/approve>{hidden(csrf)}"
                         f"<input type=hidden name=flow value='{escape(a.id)}'><button>Approve…</button></form></li>"
                         for a in al if not a.approved)
        end = f"<form method=post action=/end>{hidden(csrf)}<button>End session</button></form>" if s.active() else ""
        steps = f"<h2>{escape(panel.app.name)}</h2>{lines(run.lines())}" if live() else ""
        nodir = "" if flows_dir else "<p>No apps folder given. Start with: bin/gov-aios panel flows</p>"
        return _page(f"<h1>{escape(panel.name)}</h1><p>{ring}</p>{nodir}{end}{lines(convo)}{steps}"
                     f"<form method=post action=/say>{hidden(csrf)}<input name=text autocomplete=off autofocus>"
                     f"<button>Send</button></form><h2>Approved</h2>{lines(a.name for a in al if a.approved)}"
                     f"<h2>Drafts</h2><ul>{drafts}</ul><p><a href='/audit'>Audit log</a> <a href='/approvals'>Approvals</a></p>",
                     '<meta http-equiv="refresh" content="2">' if live() else "")

    def setup(csrf, bad):
        if store.load() is not None:
            return None
        with panel.lock:
            panel.pending = panel.pending or totp.new_secret()   # held in memory only until confirmed
            secret = panel.pending
        key = base64.b32encode(secret).decode().rstrip("=")
        return _page(f"<h1>Set up the authenticator</h1>{'<p class=fail>That code did not work.</p>' if bad else ''}"
                     f"{totp.qr_svg(totp.otpauth_uri(secret))}<p>Key: <code>{key}</code></p>"
                     f"<form method=post action=/totp/setup>{hidden(csrf)}<input name=code inputmode=numeric "
                     f"autocomplete=off><button>Confirm</button></form><p><a href='/approvals'>Approvals</a></p>")

    def say(f):
        later = []   # an expired session's run stop, run once the lock is released
        try:
            with panel.lock:   # check-and-act: one session open, one run start at a time
                return command(f, later)
        finally:
            for fn in later:
                fn()

    def command(f, later):
        text = " ".join(f.get("text", "").split())[:200]
        if not text:
            return "/"
        code = re.fullmatch(r"[0-9]{6}", text) is not None
        # never a code: any run of 6 digits, spaces allowed between them, is masked
        panel.convo.append("Admin -> " + re.sub(r"[0-9](?: ?[0-9]){5}", "••••••", text))
        if not panel.session.active():
            if panel.session.id:
                end_session("expired", later)
            if not code:
                tell(NO_SESSION)
                return "/"
            if runstate.stopped(home):
                log.append("session_open", decision="deny", reason="emergency_stop")
                tell("Emergency stop is on. Clear it first.")
                return "/"
            r = totp.Verifier(home / "totp.state").verify(text)
            if r != "ok":
                log.append("session_open", decision="deny", reason=r)
                tell("Too many wrong codes. Try again in 15 minutes." if r == "locked_out" else "That code did not work.")
                return "/"
            sid = panel.session.open()
            try:
                log.append("session_open", decision="allow", session=sid)
            except Exception:
                panel.session.end("error")   # an unrecorded session must not stay open
                raise
            tell("Session open for 30 minutes.")
            return "/"
        kind, hit = match(text, al := apps())
        if kind == "run" and live():
            tell(f"{panel.app.name} is still running.")
        elif kind == "run":
            r = launcher(hit.path, tickets.create(home, hit.id, hit.digest, panel.session.id))
            r.start()
            panel.run, panel.app = r, hit
            tell(f"Starting {hit.name}.")
        elif kind == "draft":
            tell(f"{hit.name} is a draft. Get it approved first.")
        elif kind == "ambiguous":
            tell(f"Which app: {', '.join(a.name for a in hit)}?")
        else:
            tell(f"I don't know that app. Approved apps: {', '.join(a.name for a in al if a.approved) or 'none'}.")
        return "/"

    def approve(f):
        from govaios import identity
        from govaios.engine import Runner, Stop
        hit = next((a for a in apps() if a.id == f.get("flow") and not a.approved), None)
        if hit is None:
            return None
        try:   # the CLI's own path: native dialog + Touch ID, flow_approval audited, then approvals.json
            # the executor the panel's runs use: cli.py's rule, packaged and never --dev from the panel
            packaged = identity.check()["bundle_id"] == "com.govaios.cli"
            Runner(hit.path, None, home, "gov_runner" if packaged else "gov_runner_dev").approve_flow()
            tell(f"{hit.name} is approved.")
        except Stop:
            tell(f"{hit.name} was not approved.")
        return "/"

    def setup_post(f):
        with panel.lock:   # take-and-clear: two concurrent POSTs cannot both reach the dialog
            secret, panel.pending = panel.pending, None
        if secret is None or store.load() is not None:
            return None
        step = totp.matches(secret, f.get("code", ""), time.time())
        if step is not None:
            ok, how = auth.approve("Set up the authenticator for GOV-AIOS?", "set up authenticator", home)
            if ok:
                def save():
                    store.save(secret)
                    totp.mark_used(home, step)
                audited("totp_setup", {"decision": "allow", "approver": "admin", "channel": "touch_id", "auth": how},
                        save)
                return "/approvals"
        with panel.lock:   # not set up: the shown QR stays valid unless a newer one was made
            panel.pending = panel.pending or secret
        return "/totp/setup?bad=1" if step is None else "/approvals"

    def reset(f):
        ok, how = auth.prove("reset the authenticator", home)
        if ok:
            end_session("reset")
            audited("totp_reset", {"decision": "allow", "approver": "admin", "channel": "touch_id", "auth": how},
                    store.delete)
        return "/approvals"

    def end(f):
        end_session("ended")
        return "/"

    def revoke(f):
        kind, flow, dest = f.get("kind"), f.get("flow", ""), f.get("destination", "")
        ap = Approvals(approvals_path)
        if kind == "flow" and flow:
            fields, apply = {"flow": flow}, lambda: ap.revoke_flow(flow)
        elif kind == "destination" and flow and dest:
            fields, apply = {"flow": flow, "destination": dest}, lambda: ap.revoke_destination(flow, dest)
        elif kind == "all":
            fields, apply = {"reason": "all"}, ap.revoke_all
        else:
            return None
        audited("revoke", fields, apply)
        return "/approvals"

    POSTS = {"/say": say, "/approve": approve, "/end": end, "/totp/setup": setup_post, "/totp/reset": reset,
             "/revoke": revoke}

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
                try:
                    end_session("screen_lock")
                except Exception:
                    pass   # the session is already ended; only its audit line failed
                close()   # the stopped run still finishes and reports first
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
                close()   # a live run keeps the server up until it is done
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
                m = re.fullmatch(r"/audit/run/([0-9]{1,9})", u.path)
                page = (talk(sess[1]) if u.path == "/" else index() if u.path == "/audit"
                        else approvals(sess[1]) if u.path == "/approvals" else fulllog() if u.path == "/audit/log"
                        else setup(sess[1], u.query == "bad=1") if u.path == "/totp/setup"
                        else run(int(m[1])) if m else None)
            except Exception:  # tampered data must not leak a traceback; body stays fixed
                return self._send(500, "internal error")
            self._send(200, page) if page else self._send(404)

        @guarded
        def do_POST(self):
            act = POSTS.get(urlsplit(self.path).path)
            if act is None:
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
            try:
                loc = act(f)
            except Exception:   # body stays fixed; nothing about the failure reaches the page
                return self._send(500, "internal error")
            if loc is None:
                return self._send(400)
            self.send_response(303)
            for k, v in (("Location", loc), ("Content-Length", "0"), *SEC):
                self.send_header(k, v)
            self.end_headers()

        @guarded
        def _no(self):
            self._send(405)

        do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _no

    halt = threading.Event()

    class Server(ThreadingHTTPServer):
        def server_close(self):
            halt.set()
            try:
                # a run whose session already ended still must not outlive us; never stop it twice
                # (end_session stops it, even when it raises): a 2nd SIGTERM can cut the app's own stop entry
                if end_session("server_stop") is None and live():
                    stop_run(panel.run)
            finally:
                super().server_close()

    def ticker():
        while not halt.wait(tick_s):
            try:
                tick()
            except Exception:
                pass   # one bad tick (an audit write, a lock probe) must not end the watch

    server = Server(("127.0.0.1", port), H)
    server.panel = panel
    if tick_s is not None:
        threading.Thread(target=ticker, daemon=True).start()
    return server, code
