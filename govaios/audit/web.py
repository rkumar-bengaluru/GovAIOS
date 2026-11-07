"""Localhost-only control panel: cookie session after a Touch ID login; Talk page (TOTP session, typed commands),
the signed audit log under /audit, approvals with revocation and the authenticator."""
import base64
import hmac
import json
import math
import re
import secrets
import subprocess
import sys
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
from govaios.auth import shown_digest
from govaios.audit.verify import verify
from govaios.panel import settings, tickets, totp
from govaios.panel.apps import list_apps, match
from govaios.panel.launch import RunLaunch
from govaios.panel.session import SESSION_S, Session

COLS = ["kind", "flow", "step", "action", "target", "decision", "approver", "channel", "outcome", "reason",
        "response_code", "listing_id", "auth", "command", "file_hash"]
# the journey-v2 mockup in one stylesheet: system fonts, no images, no script (CSP allows inline style only)
CSS = """
:root{color-scheme:light dark;--bg:#E8ECF2;--paper:#F5F7FA;--card:#fff;--ink:#14213D;--steel:#2B3A55;
--muted:#56627A;--line:#D9DEE7;--amber:#F2A93B;--amber-soft:#FDF1DC;--ok:#3E8E7E;--ok-soft:#E3F1EE;
--stop:#C8473A;--stop-soft:#FBE9E7;--rail:#14213D;--rail-fg:#DCE3EE;--rail-mute:#A9B4C6;--me:#14213D;
--focus:#14213D;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0B1222;--paper:#101A2D;--card:#17223A;--ink:#E6EBF3;
--steel:#BAC4D6;--muted:#9AA6BB;--line:#2C3A55;--amber-soft:#3A2E15;--ok:#5FB8A5;--ok-soft:#15302B;
--stop:#F07A6C;--stop-soft:#3A1C19;--rail:#070D1A;--me:#2B3A55;--focus:#F2A93B}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--sans)}
a{color:inherit}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
.rail :focus-visible{outline-color:var(--amber)}
.app{display:grid;grid-template-columns:260px minmax(0,1fr);min-height:100vh}
.rail{background:var(--rail);color:var(--rail-fg);padding:18px 14px}
.brand{display:flex;align-items:center;gap:10px;margin:0 6px 18px;font-weight:700;font-size:17px;color:#fff}
.rail>a{display:block;padding:8px 10px;border-radius:8px;text-decoration:none;color:#fff}
.rail>a:hover,.rail>a[aria-current]{background:rgba(255,255,255,.08)}
.rail h2{font-size:13px;font-weight:500;color:var(--rail-mute);margin:18px 6px 6px}
.rail ul{list-style:none;margin:0;padding:0}
.rail li{padding:9px 10px;border-radius:8px;margin-bottom:4px;font-weight:700;color:#fff}
.rail li::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;
background:var(--ok);vertical-align:1px}
.rail li.ok{background:rgba(62,142,126,.18)}
.rail li.draft{border:1px dashed #4A5A78}
.rail li.draft::before{background:#8B97AD}
.rail .m{display:block;font-size:13px;font-weight:400;color:var(--rail-mute)}
.rail form{margin-top:6px}
.rail button{background:transparent;color:#fff;border:1px solid #4A5A78}
main{min-width:0;padding:20px 22px 40px;background:var(--paper)}
h1{font-size:26px;line-height:1.15;font-weight:800;margin:0 0 14px;letter-spacing:-.01em}
h2{font-size:17px;margin:22px 0 8px}
.top{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;margin:-20px -22px 18px;
padding:14px 22px;background:var(--card);border-bottom:1px solid var(--line)}
.who{display:flex;align-items:center;gap:12px}
.who h1{font-size:17px;margin:0}.who .s{font-size:14px;color:var(--steel)}
.ring{flex:none;width:46px;height:46px;border-radius:50%;display:grid;place-items:center;
background:conic-gradient(var(--ok) var(--p,0%),var(--line) 0)}
.ring b{width:34px;height:34px;border-radius:50%;background:var(--me);color:#fff;display:grid;place-items:center;font-size:14px}
button{font:inherit;font-weight:700;border-radius:10px;padding:9px 14px;cursor:pointer;
background:var(--card);color:var(--steel);border:1px solid var(--line)}
button.go{background:var(--me);color:#fff;border-color:var(--me)}
button.stop{color:var(--stop);border:2px solid var(--stop)}
input{font:inherit;color:var(--ink);background:var(--card);padding:10px 14px;border:1px solid var(--line);border-radius:10px;min-width:0}
.vh{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.talk{list-style:none;margin:0;padding:0}
.talk li{max-width:640px;width:fit-content;margin:0 0 12px;padding:10px 14px;border-radius:12px;
background:var(--card);border:1px solid var(--line);overflow-wrap:anywhere}
.talk li.admin{margin-left:auto;background:var(--me);color:#fff;border-color:var(--me)}
.talk li.ask{background:var(--amber-soft);border-color:var(--amber)}
.talk li.done{background:var(--ok-soft);border-color:var(--ok)}
.talk li.no{background:var(--stop-soft);border-color:var(--stop)}
.run{max-width:640px;padding:10px 14px;border:1px dashed var(--muted);border-radius:12px;margin:0 0 12px}
.run h2{margin:0;font-size:13px;font-weight:500;color:var(--muted)}
.run ul{list-style:none;padding:0;margin:6px 0 0;font-size:15px}
.run li{padding:4px 0 4px 26px;position:relative;color:var(--ink);overflow-wrap:anywhere}
.run li::before{content:"";position:absolute;left:4px;top:11px;width:10px;height:10px;border-radius:50%;
background:var(--ok);border:2px solid var(--ok)}
.run li:last-child{font-weight:700}
.run li:last-child::before{background:var(--amber);border-color:var(--amber)}
.cmd{display:flex;gap:10px;margin:18px 0 0;padding:14px;background:var(--card);border:1px solid var(--line);border-radius:12px}
.cmd input{flex:1}
.note{background:var(--card);border-left:4px solid var(--amber);padding:10px 14px}
p.ok,p.fail{display:inline-block;padding:8px 12px;border-radius:8px;border:1px solid}
p.ok{background:var(--ok-soft);border-color:var(--ok)}
.fail{background:var(--stop-soft);border-color:var(--stop)}
table{display:block;max-width:100%;overflow-x:auto;border-collapse:collapse;font-size:14px;
background:var(--card);border:1px solid var(--line);border-radius:8px}
th{color:var(--steel);font-weight:700}
td,th{padding:8px;text-align:left;vertical-align:top;border-top:1px solid var(--line)}
td button{padding:6px 10px;font-size:14px}
form{margin:10px 0}
td form{margin:0}
.card{max-width:640px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px}
.card label{display:block;font-weight:700;margin-bottom:6px}
.word{font:700 28px var(--mono);letter-spacing:.2em}
.qr{display:inline-block;background:#fff;padding:10px;border-radius:8px;border:1px solid var(--line)}
.qr svg{display:block;max-width:100%;height:auto}
code{font-family:var(--mono);background:var(--paper);padding:4px 8px;border-radius:6px;letter-spacing:.08em;overflow-wrap:anywhere}
@media (max-width:820px){.app{grid-template-columns:minmax(0,1fr);min-height:0}.rail{order:1}main{padding:16px 16px 32px}
.top{margin:-16px -16px 16px;padding:12px 16px}}
"""
BRAND = ("<div class=brand><svg width=30 height=30 viewBox='0 0 30 30' aria-hidden=true>"
         "<path d='M15 2 26 6v8c0 7-4.6 11.6-11 14C8.6 25.6 4 21 4 14V6z' fill='#F2A93B'/>"
         "<path d='m10 15 3.5 3.5L20.5 11' stroke='#14213D' stroke-width='2.6' fill=none stroke-linecap=round "
         "stroke-linejoin=round /></svg>GOV-AIOS</div>")


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


PANEL_KINDS = ("ui_login", "session_open", "session_end", "setting")


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
            if e.get("kind") in PANEL_KINDS or str(e.get("kind")).startswith("totp_") or e.get("flow") not in (None, cur[0].get("flow")):
                continue   # the panel's own entries and other flows' entries are never steps of this run
            cur.append(e)
            if e.get("kind") in ("flow_end", "stop"):
                cur = None
        elif (e.get("kind") in ("action", "request") and e.get("flow") not in (None, "claude_code")
              and not (e.get("kind") == "request" and e.get("action") == "deliver")):
            odd += 1   # a flow step outside a run; hook, stop, login, revoke, dump and deliver entries are normal here
    return runs, odd


def _td(v):
    return f"<td>{escape('' if v is None else str(v))}</td>"


def _page(body, head="", rail="", here=None):
    nav = "".join(f"<a href='{h}'{' aria-current=page' if h == here else ''}>{t}</a>"
                  for h, t in (("/", "Talk"), ("/audit", "Audit log"), ("/approvals", "Approvals")))
    return (f"<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width,"
            f"initial-scale=1'>{head}<title>GOV-AIOS</title><style>{CSS}</style><div class=app>"
            f"<nav class=rail aria-label='GOV-AIOS'>{BRAND}{nav}{rail}</nav><main>{body}</main></div>")


def _tone(line):
    """Bubble style for one conversation line: who said it, and whether it asks, succeeds or refuses."""
    if line.startswith("Admin -> "):
        return "admin"
    if line.endswith(NO_SESSION):
        return "ask"
    if " finished: " in line or line.endswith((" is approved.", "Session open for 30 minutes.")):
        return "done"
    refused = (" stopped: ", " is a draft.", "did not work.", "Too many wrong codes", "Emergency stop is on",
               " was not approved.", "know that app")
    return "no" if any(r in line for r in refused) else ""


def _started_by(run):
    ch = next((e.get("channel") for e in run if e.get("kind") == "request" and e.get("action") == "run_start"), None)
    return {"totp_session": "Panel", "touch_id": "Terminal"}.get(ch, "\u2014")   # older runs carry no run_start


def _outcome(r):
    return r[-1].get("outcome") or r[-1].get("kind")


def _apps_summary(runs, apps):
    """One row per app: the folder's apps first (Approved/Draft), then apps seen only in the log (Removed)."""
    out = [{"id": a.id, "name": a.name, "state": "Approved" if a.approved else "Draft", "runs": 0,
            "last_time": None, "last_outcome": None, "last_started_by": "\u2014"} for a in apps]
    by = {d["id"]: d for d in out}
    for r in runs:   # log order, so the last one wins
        f = r[0].get("flow")
        if not isinstance(f, str):
            continue
        if f not in by:
            by[f] = {"id": f, "name": f, "state": "Removed", "runs": 0}
            out.append(by[f])
        d = by[f]
        d.update(runs=d["runs"] + 1, last_time=r[0].get("ts"), last_outcome=_outcome(r), last_started_by=_started_by(r))
    return out


PANEL_PATH = re.compile(r"/audit(/.*)?|/approvals|/totp/setup")
APP_ID = re.compile(r"[a-z0-9_]{1,64}")


def _say(text):
    try:
        subprocess.run(["/usr/bin/say", text], timeout=60)
    except Exception:
        pass   # a missing voice must not break the panel


NO_SESSION = "Enter the 6-digit code from your authenticator."


SIGNIN_S, SIGNIN_PAUSE_S, SIGNIN_PAUSE_MAX_S, PRE_S = 8 * 3600, 10, 300, 120
WORD_ABC = "ABCDEFGHJKLMNPQRSTUVWXYZ"
NOTES = {"busy": "Another sign-in is waiting for Touch ID.", "no": "Touch ID did not sign you in.",
         "code": "That code did not match the Touch ID prompt. Sign in again."}


def make_server(home: Path, port: int = 0, now=time.time, flows_dir=None, launcher=None, speak=None,
                name=None, session=None, tick_s=1.0, helper=None):
    """Returns the server; server.panel holds the run session, current run and conversation.
    Browsers sign in on the page with Touch ID (POST /signin); the server never shuts itself down. tick_s=None starts no ticker (tests call server.panel.tick()).
    helper: the launch helper forked before the sandbox; it runs and speaks unless launcher/speak are passed."""
    launcher = launcher or (helper.run if helper else RunLaunch)
    speak = speak or (helper.say if helper else _say)
    home = Path(home)
    log = AuditLog(home)
    approvals_path = home / "approvals.json"
    store = totp.SecretStore(home)
    panel = SimpleNamespace(session=session or Session(), run=None, app=None, convo=deque(maxlen=50),
                            speak=speak, name=name or settings.name(home), pending=None, lock=threading.RLock(),
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

    def signout_all():
        with sign_lock:
            state["sessions"].clear()
            state["typed"].clear()   # a Touch ID sign-in still waiting for its typed code ends too

    def tick():
        locked = auth.screen_locked()
        if locked:
            signout_all()
        s = panel.session
        if s.id is not None:
            reason = ("expired" if not s.active() else "screen_lock" if locked
                      else "emergency_stop" if runstate.stopped(home) else None)
            if reason:
                end_session(reason)   # Session.end hands the id out once: a racing request cannot end it twice
        report()
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
    # sessions: sid -> (signed in at, csrf); pre: token -> (issued at, code word); typed: token -> (Touch ID ok at, code word);
    # until: end of the panel-wide pause; n: consecutive refusals (Touch ID or a wrong typed code)
    state = {"sessions": {}, "pre": {}, "typed": {}, "until": float("-inf"), "n": 0}
    sign_lock, prompt = threading.Lock(), threading.Lock()   # prompt: one Touch ID sign-in sheet at a time

    def refused():
        """One more refusal: the panel-wide pause doubles (10 s up to 300 s). A fresh pre token never resets it."""
        state["n"] += 1
        state["until"] = now() + min(SIGNIN_PAUSE_S * 2 ** (state["n"] - 1), SIGNIN_PAUSE_MAX_S)

    def signed_out(pre, m):
        """The code word is never on the page: only the Touch ID prompt shows it (NIST 800-63B-4: a typed code, not a compared one)."""
        note = NOTES.get(m, "")
        left = state["until"] - now()
        if left > 0:
            note = f"{note} Sign-in paused. Try again in {math.ceil(left)} s.".strip()
        return _page(f"<section class=card><h1>Locked</h1>{f'<p class=fail>{note}</p>' if note else ''}"
                     f"<p>The Touch ID prompt shows a 4-letter code. Remember it: you type it here next.</p>"
                     f"<form method=post action=/signin><input type=hidden name=pre value='{pre}'>"
                     f"<button class=go>Sign in with Touch ID</button></form></section>")

    def type_code(t):
        return _page(f"<section class=card><h1>Locked</h1>"
                     f"<p>Type the 4-letter code the Touch ID prompt showed.</p>"
                     f"<form method=post action=/signin/code><input type=hidden name=t value='{t}'>"
                     f"<input name=word maxlength=4 autocomplete=off autocapitalize=characters spellcheck=false autofocus "
                     f"aria-label='Code from the Touch ID prompt'>"
                     f"<button class=go>Finish signing in</button></form></section>")

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
        rows = {"Removed": [], "": []}
        for d in _apps_summary(runs, apps()):
            if not flows_dir and d["state"] == "Removed":
                d["state"] = "\u2014"   # without an apps folder nothing can be called removed
            link = f"<a href='/audit/app/{escape(d['id'])}'>{escape(d['name'])}</a>" if APP_ID.fullmatch(d["id"]) \
                else escape(d["name"])
            rows["Removed" if d["state"] == "Removed" else ""].append(
                f"<tr><td>{link}</td>{_td(d['state'])}{_td(d['runs'])}{_td(d['last_time'])}"
                f"{_td(d['last_outcome'])}{_td(d['last_started_by'])}</tr>")
        head = "<tr><th>app</th><th>state</th><th>runs</th><th>last run</th><th>outcome</th><th>started by</th></tr>"
        table = lambda rs: f"<table>{head}{''.join(rs)}</table>"
        body = (f"<h1>Audit log</h1>{banner()}{note}<h2>Apps</h2>"
                + (table(rows[""]) if rows[""] else "<p>No apps yet.</p>")
                + (f"<h2>Removed apps</h2>{table(rows['Removed'])}" if rows["Removed"] else "")
                + "<p><a href='/audit/log'>Full log</a></p>")
        return _page(body, here="/audit")

    def app_page(app_id):
        runs = [r for r in _runs(_entries(log))[0] if r[0].get("flow") == app_id]
        known = {a.id: a.name for a in apps()}
        if not runs and app_id not in known:
            return None
        rows = "".join(
            f"<tr><td><a href='/audit/run/{int(r[0]['seq'])}'>{int(r[0]['seq'])}</a></td>{_td(r[0].get('ts'))}"
            f"{_td(_outcome(r))}{_td(_started_by(r))}"
            f"{_td('delivered %d, duplicate %d' % tuple(sum(1 for e in r if e.get('kind') == 'delivery' and e.get('outcome') == o) for o in ('delivered', 'duplicate')))}</tr>"
            for r in reversed(runs))
        table = (f"<table><tr><th>run</th><th>time</th><th>outcome</th><th>started by</th><th>delivery</th></tr>{rows}</table>"
                 if runs else "<p>No runs yet.</p>")
        return _page(f"<h1>{escape(known.get(app_id, app_id))}</h1>{banner()}{table}"
                     f"<p><a href='/audit'>Apps</a> | <a href='/audit/log'>Full log</a></p>", here="/audit")

    def run(seq):
        for r in _runs(_entries(log))[0]:
            if r[0]["seq"] == seq:
                head = "".join(f"<th>{c}</th>" for c in COLS)
                rows = "".join("<tr>" + "".join(_td(e.get(c)) for c in COLS) + "</tr>" for e in r)
                return _page(f"<h1>Run {int(seq)}</h1>{banner()}<table><tr>{head}</tr>{rows}</table>"
                             f"<p><a href='/audit'>Apps</a></p>", here="/audit")
        return None

    def fulllog():
        head = "".join(f"<th>{c}</th>" for c in ["seq", "ts", *COLS])
        rows = "".join(
            "<tr>" + "".join(_td(e.get(c)) for c in ["seq", "ts", *COLS]) + "</tr>" if e is not None
            else f"<tr><td colspan={len(COLS) + 2} class=fail>unparsed: {escape(raw)}</td></tr>" for e, raw in _entries(log))
        return _page(f"<h1>Full log</h1>{banner()}<table><tr>{head}</tr>{rows}</table>"
                     f"<p><a href='/audit'>Apps</a></p>", here="/audit")

    def hidden(csrf):
        return f"<input type=hidden name=csrf value='{escape(csrf)}'>"

    def approvals(csrf):
        authn = "<h2>Authenticator</h2>" + (
            "<p><a href='/totp/setup'>Set up</a></p>" if store.load() is None else
            f"<form method=post action=/totp/reset>{hidden(csrf)}<button class=stop>Reset authenticator</button></form>")
        authn = (f"<h2>Your name</h2><form method=post action=/name>{hidden(csrf)}<label for=nm>Your name</label> "
                 f"<input id=nm name=name maxlength=40 value='{escape(panel.name)}'> <button>Save</button></form>") + authn
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
            return _page(f"<h1>Approvals</h1>{bad}{authn}", here="/approvals")
        def form(kind, flow="", dest="", label="Revoke", cls=""):
            return (f"<form method=post action=/revoke><input type=hidden name=csrf value='{escape(csrf)}'>"
                    f"<input type=hidden name=kind value={kind}><input type=hidden name=flow value='{escape(flow)}'>"
                    f"<input type=hidden name=destination value='{escape(dest)}'><button{cls}>{label}</button></form>")
        fr = "".join(f"<tr>{_td(k)}{_td(v)}<td>{form('flow', str(k), label='Revoke flow')}</td></tr>" for k, v in flows.items())
        dr = "".join(f"<tr>{_td(k)}{_td(d)}<td>{form('destination', str(k), str(d), label='Revoke site')}</td></tr>"
                     for k, v in dests.items() for d in v)
        return _page(f"<h1>Approvals</h1><h2>Flows</h2><table><tr><th>flow</th><th>hash</th><th></th></tr>{fr}</table>"
                     f"<h2>Destinations</h2><table><tr><th>flow</th><th>destination</th><th></th></tr>{dr}</table>"
                     f"{form('all', label='Revoke all', cls=' class=stop')}{authn}", here="/approvals")

    def talk(csrf):
        report()   # the page refresh stops once the run is done: show its result on that same load
        s, run, al = panel.session, panel.run, apps()
        with panel.lock:
            convo = list(panel.convo)
        ring = f"Session open: {math.ceil(s.remaining() / 60)} min left" if s.active() else "No session"
        pct = round(100 * s.remaining() / SESSION_S) if s.active() else 0
        lines = lambda xs: "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in xs) + "</ul>"
        talked = "".join(f"<li class='{_tone(x)}'>{escape(x)}</li>" for x in convo)
        ok = "".join(f"<li class=ok>{escape(a.name)}<span class=m>Can run</span></li>" for a in al if a.approved)
        drafts = "".join(f"<li class=draft>{escape(a.name)}<span class=m>Needs approval</span>"
                         f"<form method=post action=/approve>{hidden(csrf)}"
                         f"<input type=hidden name=flow value='{escape(a.id)}'><button>Approve…</button></form></li>"
                         for a in al if not a.approved)
        end = (f"<form method=post action=/end>{hidden(csrf)}<button class=stop>End session</button></form>"
               if s.active() else "")
        steps = (f"<section class=run><h2>{escape(panel.app.name)}</h2>{lines(run.lines())}</section>"
                 if live() else "")
        nodir = "" if flows_dir else "<p class=note>No apps folder given. Start with: bin/gov-aios panel flows</p>"
        who = (f"<header class=top><div class=who><div class=ring style='--p:{pct}%' aria-hidden=true>"
               f"<b>{escape(panel.name[:1])}</b></div><div><h1>{escape(panel.name)}</h1>"
               f"<div class=s>{ring}</div></div></div>{end}<form method=post action=/signout>{hidden(csrf)}"
               f"<button>Sign out</button></form></header>")
        return _page(f"{who}{nodir}<ul class=talk>{talked}</ul>{steps}"
                     f"<form class=cmd method=post action=/say>{hidden(csrf)}<label class=vh for=cmd>Type a command"
                     f"</label><input id=cmd name=text autocomplete=off autofocus placeholder='Type: run joblens'>"
                     f"<button class=go>Send</button></form>",
                     '<meta http-equiv="refresh" content="2">' if live() else "",
                     f"<h2>Approved</h2><ul>{ok}</ul><h2>Drafts</h2><ul>{drafts}</ul>", "/")

    def setup(csrf, bad):
        if store.load() is not None:
            return None
        with panel.lock:
            panel.pending = panel.pending or totp.new_secret()   # held in memory only until confirmed
            secret = panel.pending
        key = base64.b32encode(secret).decode().rstrip("=")
        return _page(f"<section class=card><h1>Set up the authenticator</h1>"
                     f"{'<p class=fail>That code did not work.</p>' if bad else ''}"
                     f"<div class=qr role=img aria-label='QR code for your authenticator app'>"
                     f"{totp.qr_svg(totp.otpauth_uri(secret))}</div><p>Key: <code>{key}</code></p>"
                     f"<form method=post action=/totp/setup>{hidden(csrf)}<label for=code>6-digit code</label>"
                     f"<input id=code name=code inputmode=numeric autocomplete=off> <button class=go>Confirm</button>"
                     f"</form></section>")

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

    def set_name(f):
        try:
            v = settings.check(f.get("name", ""))
        except ValueError:
            return None
        audited("setting", {"field": "name"}, lambda: (settings.set_name(home, v), setattr(panel, "name", v)))
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
             "/revoke": revoke, "/name": set_name}

    # same-origin, not no-referrer: under no-referrer Chrome sends `Origin: null` on our own form POSTs (revoke 403)
    SEC = (("Cache-Control", "no-store"), ("Referrer-Policy", "same-origin"), ("X-Content-Type-Options", "nosniff"),
           ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'"))
    def guarded(fn):
        """Host and lock checks run first on every method and path; a locked screen signs every browser out."""
        def wrapper(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_address[1]}":
                return self._send(403)
            if auth.screen_locked():
                signout_all()
                try:
                    end_session("screen_lock")
                except Exception:
                    pass   # the session is already ended; only its audit line failed
                return self._send(403)
            return fn(self)
        return wrapper

    class H(BaseHTTPRequestHandler):
        timeout = 10  # a short body must not hold a thread forever

        def _send(self, status, body="", extra=()):
            data = body.encode() if body else f"{status}".encode()
            self.send_response(status)
            for k, v in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(data))), *SEC, *extra):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def send_error(self, code, message=None, explain=None):  # parse-level errors keep the headers too
            self._send(code)

        def log_message(self, *a):  # default logging would print request paths and their tokens
            pass

        def _cookie(self, name):
            try:
                return SimpleCookie(self.headers.get("Cookie", ""))[name].value
            except (KeyError, ValueError):
                return None

        def _redirect(self, loc, extra=()):
            self.send_response(303)
            for k, v in (("Location", loc), ("Content-Length", "0"), *SEC, *extra):
                self.send_header(k, v)
            self.end_headers()

        def _session(self):
            """(signed in at, csrf, sid) of this browser's live sign-in, else None. A sign-in lasts SIGNIN_S."""
            sid = self._cookie("s")
            with sign_lock:
                for k, (c, _) in list(state["sessions"].items()):
                    if now() - c >= SIGNIN_S:
                        del state["sessions"][k]
                for k, v in state["sessions"].items():
                    if sid is not None and hmac.compare_digest(k.encode(), sid.encode()):
                        return (*v, k)
            return None

        def _signed_out(self, query):
            """The Locked page. Only GET / makes a pre-login token (cookie + form field) and code word;
            a browser that still holds a valid one gets the same pair back."""
            ck, m = self._cookie("pre"), parse_qs(query).get("m", [""])[0]
            tc = self._cookie("t")
            with sign_lock:
                typed = state["typed"]
                for k in [k for k, (t, *_) in typed.items() if now() - t >= PRE_S]:
                    typed.pop(k)
                if tc is not None and any(hmac.compare_digest(k.encode(), tc.encode()) for k in typed):
                    return self._send(200, type_code(tc))
                pres = state["pre"]
                for k in [k for k, (t, _) in pres.items() if now() - t >= PRE_S]:
                    pres.pop(k)
                hit = next((k for k in pres if ck is not None and hmac.compare_digest(k.encode(), ck.encode())), None)
                if hit is not None:
                    return self._send(200, signed_out(hit, m))
                pre, word = secrets.token_urlsafe(32), "".join(secrets.choice(WORD_ABC) for _ in range(4))
                for k in list(pres)[:max(0, len(pres) - 63)]:
                    pres.pop(k)   # at most 64 kept: a page loaded in a loop cannot grow it
                pres[pre] = (now(), word)
            self._send(200, signed_out(pre, m),
                       (("Set-Cookie", f"pre={pre}; HttpOnly; SameSite=Strict; Path=/; Max-Age={PRE_S}"),))

        def _signin(self, f):
            """POST /signin: the pre pair must match a token this server issued; one Touch ID prompt at a time,
            paused after a refusal. The prompt alone shows the code word; POST /signin/code finishes the sign-in."""
            ck, field = self._cookie("pre"), f.get("pre", "")
            if ck is None or not hmac.compare_digest(ck.encode(), field.encode()):
                return self._redirect("/")   # a bad Host/Origin was already 403; this is a stale or missing pair
            with sign_lock:   # spent by this one attempt
                hit = next((k for k in state["pre"] if hmac.compare_digest(k.encode(), ck.encode())), None)
                issued, word = state["pre"].pop(hit) if hit is not None else (None, None)
            if issued is None or now() - issued >= PRE_S:
                return self._redirect("/")   # stale, unknown or evicted (the pair matched): a fresh Locked page
            if not prompt.acquire(blocking=False):
                return self._redirect("/?m=busy")
            try:
                if now() < state["until"]:
                    return self._redirect("/")   # the Locked page tells how long
                reason = f"sign in to the GOV-AIOS panel, code {word}"
                ok, how = auth.prove(reason, home)
                if not ok and how in ("busy", "none"):
                    return self._redirect("/?m=busy")   # no sheet was shown: nothing refused, no pause
                if not ok:
                    refused()
                    log.append("ui_login", decision="deny", approver="admin", channel="touch_id", auth=how,
                               shown=shown_digest(None, reason))
            finally:
                prompt.release()
            if not ok:
                return self._redirect("/?m=no")
            if auth.screen_locked():   # locked while the sheet was up: that lock signs this browser out too
                return self._redirect("/")
            t = secrets.token_urlsafe(32)
            with sign_lock:
                for k in list(state["typed"])[:max(0, len(state["typed"]) - 7)]:
                    state["typed"].pop(k)   # at most 8 waiting for their typed code
                state["typed"][t] = (now(), word, how)
            self._redirect("/", (("Set-Cookie", f"t={t}; HttpOnly; SameSite=Strict; Path=/; Max-Age={PRE_S}"),))

        def _signin_code(self, f):
            """POST /signin/code: the code word from the Touch ID prompt, typed. One try per prompt; a wrong one
            counts as a refusal (the same pause) and is audited."""
            ck, field = self._cookie("t"), f.get("t", "")
            clear = (("Set-Cookie", "t=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"),)
            if ck is None or not hmac.compare_digest(ck.encode(), field.encode()):
                return self._redirect("/", clear)
            with sign_lock:   # spent by this one try
                hit = next((k for k in state["typed"] if hmac.compare_digest(k.encode(), ck.encode())), None)
                at, word, how = state["typed"].pop(hit) if hit is not None else (None, None, None)
            if at is None or now() - at >= PRE_S:
                return self._redirect("/", clear)
            reason = f"sign in to the GOV-AIOS panel, code {word}"
            ok = hmac.compare_digest(f.get("word", "").strip().upper().encode(), word.encode())
            with sign_lock:
                if not ok:
                    refused()
                else:
                    state["n"] = 0
            log.append("ui_login", decision="allow" if ok else "deny", approver="admin", channel="touch_id",
                       auth=how if ok else "wrong_code", shown=shown_digest(None, reason))   # audit first, then the cookie
            if not ok:
                return self._redirect("/?m=code", clear)
            if auth.screen_locked():   # locked since the sheet: that lock signs this browser out too
                return self._redirect("/", clear)
            sid = secrets.token_urlsafe(32)
            with sign_lock:
                state["sessions"][sid] = (now(), secrets.token_urlsafe(32))
            self._redirect("/", (("Set-Cookie", f"s={sid}; HttpOnly; SameSite=Strict; Path=/"), *clear))

        @guarded
        def do_GET(self):
            u = urlsplit(self.path)
            sess = self._session()
            if not sess:
                if u.path == "/":
                    return self._signed_out(u.query)
                # a panel page (bookmark, expired sign-in) goes to the Locked page; no cookie is set here
                return self._redirect("/") if PANEL_PATH.fullmatch(u.path) else self._send(404)
            try:
                m = re.fullmatch(r"/audit/run/([0-9]{1,9})", u.path)
                a = re.fullmatch(r"/audit/app/([^/]{1,200})", u.path)
                page = (talk(sess[1]) if u.path == "/" else index() if u.path == "/audit"
                        else approvals(sess[1]) if u.path == "/approvals" else fulllog() if u.path == "/audit/log"
                        else setup(sess[1], u.query == "bad=1") if u.path == "/totp/setup"
                        else run(int(m[1])) if m else app_page(a[1]) if a and APP_ID.fullmatch(a[1]) else None)
            except Exception:  # tampered data must not leak a traceback; body stays fixed
                return self._send(500, "internal error")
            self._send(200, page) if page else self._send(404)

        @guarded
        def do_POST(self):
            path = urlsplit(self.path).path
            act = POSTS.get(path)
            if act is None and path not in ("/signin", "/signin/code", "/signout"):
                return self._send(405)
            sess = self._session()
            origin = self.headers.get("Origin")  # absent is fine (row 37); a wrong one is not
            if origin is not None and origin != f"http://127.0.0.1:{self.server.server_address[1]}":
                return self._send(403)
            if not sess and path not in ("/signin", "/signin/code"):
                return self._send(403)
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = -1
            if not 0 <= n <= 65536:
                return self._send(400)
            f = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace")).items()}
            if path in ("/signin", "/signin/code"):
                try:
                    return self._signin(f) if path == "/signin" else self._signin_code(f)
                except Exception:   # body stays fixed; nothing about the failure reaches the page
                    return self._send(500, "internal error")
            if not hmac.compare_digest(f.get("csrf", "").encode(), sess[1].encode()):
                return self._send(403)
            if path == "/signout":   # this browser only; the code session stays open
                with sign_lock:
                    state["sessions"].pop(sess[2], None)
                return self._redirect("/")
            try:
                loc = act(f)
            except Exception:   # body stays fixed; nothing about the failure reaches the page
                return self._send(500, "internal error")
            if loc is None:
                return self._send(400)
            self._redirect(loc)

        @guarded
        def _no(self):
            self._send(405)

        do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _no

    halt = threading.Event()

    class Server(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            # the default prints a traceback and the peer's address; only the class name goes to panel.log
            from govaios.panel import agentlog
            agentlog.once(home, f"panel: request error ({type(sys.exc_info()[1]).__name__})")

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
    return server
