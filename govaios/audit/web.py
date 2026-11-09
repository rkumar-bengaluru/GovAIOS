"""Localhost-only control panel: cookie session after a Touch ID login; Talk page (TOTP session, typed commands),
the signed audit log under /audit, approvals with revocation and the authenticator."""
import base64
import hashlib
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

import yaml

from govaios import agents, applyfiles, auth, lessons, runstate, studio, terms
import os
from govaios.formfill import BankError, add_answer, load_bank, ok_value, read_bank, stage_text
from govaios.approvals import Approvals, pages_used, read_bound
from govaios.audit.log import AuditLog
from govaios.auth import shown_digest
from govaios.audit.verify import verify
from govaios.panel import lesson as lesson_ui, market, settings, tickets, totp
from govaios.panel.apps import list_apps, match
from govaios.panel.launch import RunLaunch
from govaios.panel.session import SESSION_S, Session

COLS = ["kind", "flow", "step", "action", "target", "decision", "approver", "channel", "outcome", "reason",
        "response_code", "listing_id", "auth", "command", "file_hash", "source"]
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
button.go,a.go{background:var(--me);color:#fff;border-color:var(--me)}
a.go{display:inline-block;font-weight:700;border-radius:10px;padding:9px 14px;text-decoration:none;border:1px solid var(--me)}
button.stop{color:var(--stop);border:2px solid var(--stop)}
input,textarea{font:inherit;color:var(--ink);background:var(--card);padding:10px 14px;border:1px solid var(--line);border-radius:10px;min-width:0}
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
.appcard{max-width:640px;padding:14px 16px;background:var(--card);border:1px solid var(--line);border-radius:12px;margin:0 0 12px}
.appcard h2{margin:0 0 4px;font-size:16px;font-weight:600}
.appcard .m{margin:0 0 10px}
.appcard form{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.appcard input{flex:1;min-width:220px}
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
.otp{font:700 28px var(--mono);letter-spacing:1ch;width:12ch;box-sizing:border-box;padding:10px 0 10px .3ch;
border:0;border-radius:0;caret-color:var(--me);background:repeating-linear-gradient(90deg,transparent 0 2px,var(--card) 2px calc(1.6ch - 2px),transparent calc(1.6ch - 2px) 2ch) 0 2px/11.6ch calc(100% - 4px) no-repeat,repeating-linear-gradient(90deg,var(--line) 0 1.6ch,transparent 1.6ch 2ch) 0 0/11.6ch 100% no-repeat;
box-shadow:none;outline-offset:4px}
.otp:focus{background:repeating-linear-gradient(90deg,transparent 0 2px,var(--card) 2px calc(1.6ch - 2px),transparent calc(1.6ch - 2px) 2ch) 0 2px/11.6ch calc(100% - 4px) no-repeat,repeating-linear-gradient(90deg,var(--me) 0 1.6ch,transparent 1.6ch 2ch) 0 0/11.6ch 100% no-repeat}
.otpbox{display:flex;flex-wrap:wrap;gap:14px;align-items:center;margin:0 0 16px}
.qr{display:inline-block;background:#fff;padding:10px;border-radius:8px;border:1px solid var(--line)}
.qr svg{display:block;max-width:100%;height:auto}
.tpl{max-width:640px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:0 0 12px}
.tpl h2{margin:0 0 4px}.tpl p{margin:4px 0}.tpl .m{color:var(--steel);font-size:14px}
.tpl .need{display:inline-block;font-size:13px;padding:2px 8px;margin:6px 6px 0 0;border:1px solid var(--line);border-radius:999px}
.tpl .state{font-weight:700;color:var(--ok)}
.pick label{display:flex;gap:10px;align-items:baseline;font-weight:400;padding:8px 0;border-top:1px solid var(--line)}
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


PANEL_KINDS = ("ui_login", "session_open", "session_end", "setting", "claude_start", "apply_answer", "apply_fix", "apply_card", "bank_updated")


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
        elif (e.get("kind") in ("action", "request") and e.get("flow") not in (None, "claude_code", "codex")
              and not (e.get("kind") == "request" and e.get("action") == "deliver")):
            odd += 1   # a flow step outside a run; hook, stop, login, revoke, dump and deliver entries are normal here
    return runs, odd


def _decided_by(e):
    """Who made a Claude Code decision, in words: the admin's own presence proof, or GOV-AIOS's rules alone."""
    if e.get("approver") == "admin":
        how = {"biometric": "Touch ID", "password": "Mac password"}.get(e.get("auth"), e.get("auth") or "no proof")
        return f"You, {how}" if e.get("decision") == "allow" else f"You declined ({how})"
    return "GOV-AIOS policy"


def _td(v):
    return f"<td>{escape('' if v is None else str(v))}</td>"


def _page(body, head="", rail="", here=None):
    nav = "".join(f"<a href='{h}'{' aria-current=page' if h == here else ''}>{t}</a>"
                  for h, t in (("/", "Talk"), ("/market", "Marketplace"), ("/studio", "Studio"), ("/audit", "Audit log"), ("/approvals", "Approvals")))
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


PANEL_PATH = re.compile(r"/audit(/.*)?|/approvals|/totp/setup|/market(/.*)?|/apply/bank|/apply/task/[0-9]{1,2}|/studio|/claude|/codex|/lesson/[^/]{1,200}")
DOES = {"claude_code": "Every command Claude Code runs is checked by GOV-AIOS first and written to the audit log.",
        "codex": "Shell commands, file edits and plugin calls are checked by GOV-AIOS first and written to the audit "
                 "log. Plugins stay on; each new plugin tool asks you once."}
RULES = {"claude_code": "Rules: every command is checked first and every action is logged (always on).",
         "codex": "Rules: shell commands, file edits and plugin calls are checked first and logged; Codex's sandbox "
                  "stays on and web search is off (always on)."}
APP_ID = re.compile(r"[a-z0-9_]{1,64}")


def _say(text):
    try:
        subprocess.run(["/usr/bin/say", text], timeout=60)
    except Exception:
        pass   # a missing voice must not break the panel


def _notify(text):
    """A macOS notification; the text is an argument to the script, never part of it."""
    try:
        subprocess.run(["/usr/bin/osascript", "-e", "on run argv", "-e",
                        'display notification (item 1 of argv) with title "GOV-AIOS"', "-e", "end run", text], timeout=10)
    except Exception:
        pass   # a refused notification must not break the panel


NO_SESSION = "Enter the 6-digit code from your authenticator."


SIGNIN_S, SIGNIN_PAUSE_S, SIGNIN_PAUSE_MAX_S, PRE_S = 8 * 3600, 10, 300, 120
WORD_ABC = "ABCDEFGHJKLMNPQRSTUVWXYZ"
NOTES = {"busy": "Another sign-in is waiting for Touch ID.", "no": "Touch ID did not sign you in.",
         "code": "That code did not match the Touch ID prompt. Sign in again."}


def make_server(home: Path, port: int = 0, now=time.time, flows_dir=None, launcher=None, speak=None,
                name=None, session=None, tick_s=1.0, helper=None, chrome_state=None, templates=None, managed=None,
                admin=None, starter=None):
    """Returns the server; server.panel holds the run session, current run and conversation.
    Browsers sign in on the page with Touch ID (POST /signin); the server never shuts itself down. tick_s=None starts no ticker (tests call server.panel.tick()).
    helper: the launch helper forked before the sandbox; it runs and speaks unless launcher/speak are passed.
    managed: {agent id: the root-owned file it reads}; admin(action, digest, agent id) -> int runs the Mac-password
    step (helper.claude); starter(folder, agent id) -> int opens Terminal there (helper.claude_start)."""
    launcher = launcher or (helper.run if helper else RunLaunch)
    speak = speak or (helper.say if helper else _say)
    admin = admin or getattr(helper, "claude", None)
    starter = starter or getattr(helper, "claude_start", None)
    managed = {a.id: Path((managed or {}).get(a.id, a.managed)) for a in agents.AGENTS.values()}
    home = Path(home)
    log = AuditLog(home)
    approvals_path = home / "approvals.json"
    store = totp.SecretStore(home)
    panel = SimpleNamespace(session=session or Session(), run=None, app=None, convo=deque(maxlen=50),
                            speak=speak, name=name or settings.name(home), pending=None, lock=threading.RLock(),
                            told=None, voice=None, card=None, run_id=None, fix_spoken=None, notify=_notify)

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
                why = r.stopped_reason or getattr(r, "reason", None) or f"exit {r.code}"
                cap = getattr(r, "capture", None)
                tell(f"{app} stopped: {why}" + (f" Saved page: captures/{cap}" if cap else ""))
                text = f"{panel.name}, the {app} flow stopped: {why}."
            panel.voice = threading.Thread(target=panel.speak, args=(text,), daemon=True)
            panel.voice.start()
            try:   # after the finish message: a killed run leaves its hand-off behind
                applyfiles.remove(home, applyfiles.ASK, applyfiles.REPLY)
            except OSError:
                pass

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
        cc = ""
        rows_a = []
        for ag in agents.AGENTS.values():
            checks, ok = cc_checks(ag), cc_roots(ag) is not None
            if checks or ok:
                rows_a.append(f"<tr><td><a href='/audit/app/{ag.id}'>{ag.title}</a></td>"
                              f"{_td('Governed' if ok else 'Not governed')}{_td(len(checks))}"
                              f"{_td(sum(1 for e in checks if e.get('decision') != 'allow'))}"
                              f"{_td(checks[-1].get('ts') if checks else None)}</tr>")
        if rows_a:
            cc = ("<h2>Coding agents</h2><table><tr><th>agent</th><th>state</th><th>checks</th><th>refused</th>"
                  f"<th>last check</th></tr>{''.join(rows_a)}</table>")
        body = (f"<h1>Audit log</h1>{banner()}{note}<h2>Apps</h2>"
                + (table(rows[""]) if rows[""] else "<p>No apps yet.</p>") + cc
                + (f"<h2>Removed apps</h2>{table(rows['Removed'])}" if rows["Removed"] else "")
                + "<p><a href='/audit/log'>Full log</a></p>")
        return _page(body, here="/audit")

    def cc_checks(ag):
        """The agent's hook decisions (one `request` per tool call it saw)."""
        return [e for e, _ in _entries(log) if e and e.get("kind") == "request" and e.get("executor") == ag.id]

    def cc_sessions(ag):
        """Sessions in the order they began: [(key, checks)]; key "earlier" holds checks logged before sessions
        were recorded."""
        by = {}
        for e in cc_checks(ag):
            by.setdefault(e.get("session") or "earlier", []).append(e)
        return list(by.items())

    NOTE = {"claude_code": "Calls Claude Code's own managed rules refuse first never reach GOV-AIOS and are not listed.",
            "codex": "Codex sends shell commands, file edits and plugin calls to GOV-AIOS; its other built-in tools "
                     "are not checked."}

    def cc_page(ag):
        rows = "".join(
            f"<tr><td><a href='/audit/{ag.slash}/{escape(k)}'>{'Earlier' if k == 'earlier' else f'Session {i}'}</a></td>"
            f"{_td(es[0].get('ts'))}{_td(agents.tilde(es[0].get('folder') or '') or chr(8212))}{_td(len(es))}"
            f"{_td(sum(1 for e in es if e.get('decision') != 'allow'))}"
            f"{_td(sum(1 for e in es if e.get('approver') == 'admin'))}{_td(es[-1].get('ts'))}</tr>"
            for i, (k, es) in reversed(list(enumerate(cc_sessions(ag), 1))))
        table = ("<table><tr><th>session</th><th>started</th><th>folder</th><th>checks</th><th>refused</th>"
                 f"<th>asked you</th><th>last check</th></tr>{rows}</table>" if rows
                 else f"<p>No sessions yet. Type /{ag.slash} in Talk, or start it in a new Terminal session.</p>")
        return _page(f"<h1>{ag.title}</h1>{banner()}<p class=m>Sessions newest first. {NOTE[ag.id]}</p>{table}"
                     f"<p><a href='/audit'>Apps</a> | <a href='/audit/log'>Full log</a></p>", here="/audit")

    def cc_session_page(ag, key):
        es = dict(cc_sessions(ag)).get(key)
        if es is None:
            return None
        cols = ("ts", "action", "command", "target", "decision")
        rows = "".join("<tr>" + "".join(_td(e.get(c)) for c in cols) + _td(_decided_by(e)) + _td(e.get("reason"))
                       + "</tr>" for e in es)
        heads = ("time", "tool", "command", "target", "decision", "decided by", "why")
        title = "Earlier checks" if key == "earlier" else f"{ag.title} session"
        where = agents.tilde(es[0].get("folder") or "")
        return _page(f"<h1>{title}</h1>{banner()}<p class=m>{escape(where)}</p>"
                     f"<table><tr>{''.join(f'<th>{c}</th>' for c in heads)}</tr>{rows}</table>"
                     f"<p><a href='/audit/app/{ag.id}'>{ag.title} sessions</a> | <a href='/audit/log'>Full log</a></p>",
                     here="/audit")

    def cc_roots(ag):
        ok, roots = agents.governed(home, managed[ag.id], ag)
        return roots if ok else None

    def claude_start(ag, text):
        """Open Terminal in the folder and run the agent there (governed only, inside its approved folders)."""
        roots = cc_roots(ag)
        if roots is None:
            tell(f"{ag.title} is not governed yet. Set it up in Marketplace first.")
            return
        if starter is None:
            tell(f"Starting {ag.title} needs the installed panel.")
            return
        folder, cands = agents.pick(text, roots)
        if folder is None:
            tell(f"Which folder: {', '.join(agents.tilde(c) for c in cands[:8])}?" if cands else
                 f"That folder is not inside the approved ones: {', '.join(agents.tilde(r) for r in roots)}.")
            return
        log.append("claude_start", flow=ag.id, executor=ag.id, target=folder, approver="admin")   # first
        code = starter(folder, ag.id)
        log.append("claude_start", flow=ag.id, executor=ag.id, target=folder, outcome=str(code))
        if code == 0:
            panel.card = None
        tell(f"Starting {ag.title} in {agents.tilde(folder)}. It opens in Terminal." if code == 0
             else f"{ag.title} did not start.")

    def start_post(ag):
        def post(f):
            if not panel.session.active():
                tell(NO_SESSION)
            else:
                claude_start(ag, f.get("folder", ""))
            return "/"
        return post

    def slug(name):
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def slashes():
        out = [f"/{ag.slash}" for ag in agents.AGENTS.values() if cc_roots(ag) is not None]
        return out + [f"/{slug(a.name)}" for a in apps() if a.approved] + ["/help"]

    def by_slash(name):
        return next((ag for ag in agents.AGENTS.values() if ag.slash == name), None)

    def flow_inputs(path):
        try:
            return yaml.safe_load(Path(path).read_text())["workflow"].get("inputs") or {}
        except Exception:
            return {}

    def show_card(name):
        ag = by_slash(name)
        with panel.lock:
            if ag is not None:
                panel.card = ("agent", ag.id) if cc_roots(ag) is not None else None
            else:
                hit = next((a for a in apps() if slug(a.name) == name or a.id == name), None)
                panel.card = ("app", hit.id) if hit else None
        if ag is not None and panel.card is None:
            tell(f"{ag.title} is not governed yet. Set it up in Marketplace first.")
        elif ag is None and hit is None:
            tell(f"No command /{name}. Commands: {', '.join(slashes())}.")

    def card(csrf):
        c = panel.card
        if c is None:
            return ""
        if c[0] == "agent":
            ag = agents.AGENTS[c[1]]
            return (f"<section class=appcard><h2>{ag.title}</h2><p class=m>Opens Terminal in the folder and runs "
                    f"{ag.title} there, governed. Suggestions show as you type.</p>{cc_form(csrf, ag)}</section>")
        a = next((a for a in apps() if a.id == c[1]), None)
        if a is None:
            return ""
        try:
            b = yaml.safe_load(a.path.read_text())["workflow"].get("browser") or {}
        except Exception:
            b = {}
        uses = (f"<p class=m>Chrome profile {escape(str(b.get('profile_directory')))}, "
                f"account {escape(str(b.get('account')))}</p>" if b.get("account") else "")
        ins = flow_inputs(a.path)
        if ins:   # one field per input; the server check is the authority, the pattern only helps the browser
            fields = "".join(f"<label>{escape(str(d.get('label', k)))} <input name='{escape('in:' + k)}' required "
                             f"pattern='{escape(re.sub(r"(?<!\\)-(?=\])", r"\\-", str(d['pattern'])) + '/?([?#].*)?')}'></label>" for k, d in ins.items())
            act = (f"<form method=post action=/say>{hidden(csrf)}<input type=hidden name=text value='/{escape(slug(a.name))}'>"
                   f"{fields}<button class=go>Run {escape(a.name)}</button></form>" if a.approved
                   else "<p class=m>Draft: approve it first.</p>")
            return (f"<section class=appcard><h2>{escape(a.name)}</h2>{uses}{act}"
                    f"<p class=m><a href='/apply/bank'>My answer bank</a></p></section>")
        act = (f"<form method=post action=/say>{hidden(csrf)}<input type=hidden name=text value='run {escape(a.name)}'>"
               f"<button class=go>Run {escape(a.name)}</button></form>" if a.approved
               else "<p class=m>Draft: approve it first.</p>")
        return f"<section class=appcard><h2>{escape(a.name)}</h2>{uses}{act}</section>"

    def cc_form(csrf, ag):
        roots = cc_roots(ag)
        if roots is None:
            return ""
        sugg = [agents.tilde(x) for x in agents.suggest(roots)]
        last = next((e.get("target") for e, _ in reversed(_entries(log))
                     if e and e.get("kind") == "claude_start" and e.get("flow") == ag.id and e.get("outcome") == "0"),
                    None)
        value = agents.tilde(last) if last else (sugg[1] if len(sugg) > 1 else sugg[0] if sugg else "")
        opts = "".join(f"<option value='{escape(x)}'>" for x in sugg)
        return (f"<form method=post action=/{ag.slash}/start>{hidden(csrf)}<label class=vh for=ccf>Folder</label>"
                f"<input id=ccf name=folder list=ccdirs value='{escape(value)}' autocomplete=off required>"
                f"<datalist id=ccdirs>{opts}</datalist><button class=go>Start {ag.title}</button></form>")

    def app_page(app_id):
        if app_id in agents.AGENTS:
            return cc_page(agents.AGENTS[app_id])
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
        cc_li = "".join(f"<li class=ok>{ag.title}<span class=m>Governed: type /{ag.slash}</span></li>"
                        for ag in agents.AGENTS.values() if cc_roots(ag) is not None)
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
                         f"<input type=hidden name=flow value='{escape(a.id)}'><button>Approve…</button></form>"
                         f"{delete_form(csrf, 'flow', a.id, '/') if DELETABLE.fullmatch(a.id) else ''}</li>"
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
        # no session yet: the authenticator code gets its own 6-box field (the command box still takes it too)
        otp = (f"<form class=otpbox method=post action=/say>{hidden(csrf)}<label for=otp>Authenticator code</label>"
               f"<input class=otp id=otp name=text inputmode=numeric pattern='[0-9]{{6}}' maxlength=6 "
               f"autocomplete=one-time-code required autofocus><button class=go>Open session</button></form>"
               if not s.active() and store.load() is not None else "")
        cmds = "".join(f"<option value='{escape(x)}'>" for x in slashes())
        ans = answer_card(csrf) or task_card(csrf)   # the admin is answering: no reload wipes it, no box steals focus
        return _page(f"{who}{nodir}<ul class=talk>{talked}</ul>{card(csrf)}{steps}{ans}{tasks_card()}{result_card()}{otp}"
                     f"<form class=cmd method=post action=/say>{hidden(csrf)}<label class=vh for=cmd>Type a command"
                     f"</label><input id=cmd name=text list=cmds autocomplete=off{'' if otp or ans else ' autofocus'} "
                     f"placeholder='Type / for commands'><datalist id=cmds>{cmds}</datalist>"
                     f"<button class=go>Send</button></form>",
                     '<meta http-equiv="refresh" content="2">' if live() and (not ans or teaching()) else "",
                     f"<h2>Approved</h2><ul>{ok}{cc_li}</ul><h2>Drafts</h2><ul>{drafts}</ul>", "/")

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
                     f"<input class=otp id=code name=code inputmode=numeric pattern='[0-9]{{6}}' maxlength=6 "
                     f"autocomplete=one-time-code required> <button class=go>Confirm</button>"
                     f"</form></section>")

    def asked():
        """The live run's question as (digest, fields), fields capped; None when there is none for this run.
        Labels and options come from the employer's page: untrusted, escaped wherever they are shown."""
        a = applyfiles.read_json(home, applyfiles.ASK)
        if not live() or not a or a.get("run") != panel.run_id or not isinstance(a.get("fields"), list):
            return None
        fs = [f for f in a["fields"][:50] if isinstance(f, dict) and isinstance(f.get("key"), str)
              and isinstance(f.get("label"), str) and isinstance(f.get("kind"), str)
              and isinstance(f.get("options"), list) and all(isinstance(o, str) for o in f["options"])]
        return hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()[:16], fs

    def answer_card(csrf):
        q = asked()
        if q is None or applyfiles.read_json(home, applyfiles.REPLY) is not None:
            return ""
        rows = []
        for f in q[1]:
            n, lab = escape("a:" + f["key"][:200]), escape(f["label"][:300])   # a longer key never matches: fill yourself
            if f["kind"] in ("select", "radio"):
                ctl = "".join(f"<label><input type=radio name='{n}' value='{escape(o)}'> {escape(o[:200])}</label>"
                              for o in f["options"][:50])
            elif f["kind"] == "textarea":
                ctl = f"<textarea name='{n}' maxlength=2000 aria-label='{lab}'></textarea>"
            else:
                ctl = f"<input name='{n}' maxlength=2000 autocomplete=off aria-label='{lab}'>"
            rows.append(f"<fieldset><legend>{lab}</legend>{ctl}"
                        f"<label><input type=checkbox name='{escape('save:' + f['key'][:200])}' value=1> Save to my bank</label>"
                        f"</fieldset>")
        return (f"<section class=appcard><h2>JobLens needs your answers</h2>"
                f"<p class=m>Leave one empty to fill it in Chrome yourself.</p>"
                f"<form method=post action=/apply/answer>{hidden(csrf)}<input type=hidden name=ask value='{q[0]}'>"
                f"{''.join(rows)}<button class=go>Send answers</button></form></section>")

    # The run's cards (applyfiles.CARDS): what each says and its buttons. Labels come from the page: untrusted.
    CARD_TEXT = {
        "fix": ("Fill this field in Chrome", "It couldn't fill <b>{label}</b>. Fill it in Chrome yourself, then "
                "press Continue. Skip leaves it on the list to fill before you submit.",
                (("continue", "Continue"), ("skip", "Skip")),
                "{name}, I couldn't fill {label}. Please fill it in Chrome, then press Continue."),
        "review": ("Ready for you to submit", "The form is filled. Check it in Chrome and press Submit there yourself. "
                   "Then press Next job, or End to stop here.", (("next", "Next job"), ("end", "End")),
                   "{name}, {job} is ready. Please check it and submit it in Chrome."),
        "stopped": ("This job stopped", "It stopped: <b>{label}</b>. The page is saved for debugging. You can finish it "
                    "in Chrome yourself. Press Next job to go on, or End.", (("next", "Next job"), ("end", "End")),
                    "{name}, {job} stopped: {label}."),
        "sandbox": ("Web sandbox", "Go to the page you want in Chrome, then press Capture this page. Done ends the "
                    "sandbox.", (("capture", "Capture this page"), ("teach", "Teach this page"), ("done", "Done")), None),
        "new_page": ("This page is new", "{app} can't go on: this page is new. Teach it?",
                     (("teach", "Teach this page"), ("skip", "Next job")),
                     "{name}, {app} can't go on: this page is new. Teach it?"),
        "terms": ("Check this site's terms", "Before I learn <b>{label}</b>, check that its terms allow a personal "
                  "agent. Open the site, find its terms, then record what they say.", (("cancel", "Cancel"),),
                  "{name}, please check the terms of {label}."),
        "teaching": ("Teaching", "Do the page in Chrome. Close the tab when you're done.",
                     (("done", "Done"), ("cancel", "Cancel lesson")), None),
        "lesson": ("What I learned", "Review what I learned, then approve it with Touch ID or discard it.", (),
                   "{name}, the lesson is ready. Please review what I learned."),
    }
    TOLD = {"continue": "Carrying on.", "skip": "Skipped: fill it before you submit.", "next": "On to the next job.",
            "end": "Ending the run.", "capture": "Capturing this page.", "done": "Sandbox done.",
            "teach": "Teaching: do the page in Chrome, then close the tab.", "checked": "Terms recorded.",
            ("new_page", "skip"): "On to the next job.", ("teaching", "done"): "Lesson done: see what I learned.",
            ("teaching", "cancel"): "Lesson cancelled.", ("terms", "cancel"): "Terms not checked: the lesson stops."}

    def card_asked():
        """The live run's card as (digest, card); None when there is none for this run."""
        a = applyfiles.read_json(home, applyfiles.ASK)
        c = a.get("card") if live() and a and a.get("run") == panel.run_id else None
        if not isinstance(c, dict) or not isinstance(c.get("kind"), str) or c.get("kind") not in CARD_TEXT or not all(
                isinstance(c.get(k), str) for k in ("label", "job")) or type(c.get("item")) is not int:
            return None
        return hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()[:16], c

    def task_card(csrf, item=None):
        """The waiting card, on Talk or on its own task's page (item). Speaks once per card."""
        q = card_asked()
        if q is None or applyfiles.read_json(home, applyfiles.REPLY) is not None or item not in (None, q[1]["item"]):
            return ""
        c = q[1]
        title, text, buttons, say = CARD_TEXT[c["kind"]]
        app = panel.app.name if panel.app else "The app"
        if say and panel.fix_spoken != q[0]:   # once per card, on its own thread (say blocks)
            panel.fix_spoken = q[0]
            words = say.format(name=panel.name, label=c["label"][:120], job=c["job"][:120] or "the job", app=app)
            threading.Thread(target=panel.speak, daemon=True, args=(words,)).start()
            if c["kind"] == "new_page":
                threading.Thread(target=panel.notify, daemon=True, args=(words,)).start()
        job = (f"<p class=m><a href='/apply/task/{c['item']}'>Job {c['item']}: {escape(c['job'][:200])}</a></p>"
               if c["job"] else "")
        cap = c.get("capture")
        if isinstance(cap, str) and re.fullmatch(r"[0-9-]{22}-[a-z0-9_]{1,64}\.json", cap):
            job += f"<p class=m>Saved page: <code>captures/{cap}</code></p>"
        btns = " ".join(f"<button{' class=go' if i == 0 else ''} name=choice value={v}>{t}</button>"
                        for i, (v, t) in enumerate(buttons))
        extra = {"sandbox": sandbox_pages, "teaching": live_lines, "terms": lambda: terms_form(csrf, q),
                 "lesson": lambda: lesson_link(c["label"])}.get(c["kind"], str)()
        form = (f"<form method=post action=/apply/card>{hidden(csrf)}<input type=hidden name=ask value='{q[0]}'>"
                f"{btns}</form>" if buttons else "")
        return (f"<section class=appcard><h2>{title}</h2>{job}"
                f"<p>{text.format(label=escape(c['label'][:300]), app=escape(app))}</p>{extra}{form}</section>")

    def live_lines():
        """The teaching card's lines: labels and lengths only, as the engine writes them."""
        lv = applyfiles.read_json(home, applyfiles.LESSON_LIVE)
        if not lv or lv.get("run") != panel.run_id or not isinstance(lv.get("lines"), list):
            return "<p class=m>Nothing seen yet.</p>"
        return "<ul>" + "".join(f"<li>{escape(x[:200])}</li>" for x in lv["lines"][-50:] if isinstance(x, str)) + "</ul>"

    def terms_form(csrf, q):
        site = q[1]["label"]
        link = (f"<p><a href='{escape(site)}' target=_blank rel=noopener>Open {escape(site[:200])}</a></p>"
                if urlsplit(site).scheme in ("http", "https") else "")
        radios = "".join(f"<label><input type=radio name=verdict value={v} required> {t}</label>" for v, t in
                         (("allowed", "Allowed"), ("forbidden", "Forbidden"), ("unclear", "Unclear")))
        return (f"{link}<form method=post action=/terms>{hidden(csrf)}<input type=hidden name=ask value='{q[0]}'>"
                f"<fieldset><legend>The terms say a personal agent is</legend>{radios}</fieldset>"
                f"<label>Terms link <input name=link type=url maxlength=500 required placeholder='https://'></label>"
                f"<label>The clause it rests on <textarea name=clause maxlength=2000></textarea></label>"
                f"<button class=go>Record</button></form>")

    def lesson_link(name):
        ok = re.fullmatch(r"[0-9-]{22}-[a-z0-9_]{1,64}\.json", name)
        return f"<p><a class=go href='/lesson/{name}'>See what I learned</a></p>" if ok else ""

    def teaching():
        q = card_asked()
        return q is not None and q[1]["kind"] == "teaching"

    def reply_card(q, choice):
        """Write reply.json for this card (audited first) and say what happens next. Caller holds panel.lock."""
        audited("apply_card", {"outcome": choice, "item": q[1]["item"]},
                lambda: applyfiles.write_json(home, applyfiles.REPLY, {"run": panel.run_id, "card": choice}))
        told = TOLD.get((q[1]["kind"], choice), TOLD.get(choice))
        if told:
            tell(told)

    def apply_card(f):
        """Write reply.json once for this card, with one of its own choices. Nothing from the page is echoed."""
        with panel.lock:
            q = card_asked() if panel.session.active() else None
            # a lesson is answered only by its own page (approve needs Touch ID); terms only after they are recorded
            if q is None or f.get("ask") != q[0] or applyfiles.read_json(home, applyfiles.REPLY) is not None \
                    or f.get("choice") not in applyfiles.CARDS[q[1]["kind"]] or q[1]["kind"] == "lesson" \
                    or f.get("choice") == "checked":
                tell("That card is no longer waiting.")
                return "/"
            reply_card(q, f["choice"])
        return "/" if q[1]["kind"] == "sandbox" or not q[1]["item"] else f"/apply/task/{q[1]['item']}"

    TASK_WORDS = {"waiting": "Not started", "working": "Working", "needs_you": "Needs you", "review": "Ready to submit",
                  "done": "Done", "stopped": "Stopped"}

    def tasks():
        """This (or the last) panel run's JobLens tasks, shape-checked; [] when there are none."""
        t = applyfiles.read_json(home, applyfiles.TASKS)
        if not t or panel.run_id is None or t.get("run") != panel.run_id or not isinstance(t.get("tasks"), list):
            return []
        return [x for x in t["tasks"][:50] if isinstance(x, dict) and type(x.get("n")) is int
                and isinstance(x.get("title"), str) and isinstance(x.get("status"), str) and x["status"] in TASK_WORDS]

    def tasks_card():
        ts = tasks()
        if not ts:
            return ""
        rows = "".join(f"<li><a href='/apply/task/{t['n']}'>{t['n']}. {escape(t['title'][:200])}</a> \u00b7 "
                       f"{TASK_WORDS[t['status']]}</li>" for t in ts)
        return f"<section class=appcard><h2>JobLens jobs</h2><ul>{rows}</ul></section>"

    def task_page(n, csrf):
        t = next((x for x in tasks() if x["n"] == n), None)
        if t is None:
            return None
        lst = lambda k: "<ul>" + "".join(f"<li>{escape(str(x)[:300])}</li>" for x in (t.get(k) or [])[:50]) + "</ul>" \
            if isinstance(t.get(k), list) and t.get(k) else ""   # noqa: E731
        num = lambda k: t.get(k) if type(t.get(k)) is int else 0   # noqa: E731
        runs = [r for r in _runs(_entries(log))[0] if r[0].get("flow") == "job_apply"]
        lines = [e for e in (runs[-1] if runs else []) if e.get("item") == n]
        cols = ["step", "action", "target", "decision", "outcome", "reason"]
        rows = "".join("<tr>" + _td((e.get("ts") or "")[11:19]) + "".join(_td(e.get(c)) for c in cols) + "</tr>"
                       for e in lines[-300:])
        why = f"<p>Stopped: {escape(str(t.get('reason'))[:300])}</p>" if t.get("reason") else ""
        return _page(f"<h1>Job {n}: {escape(t['title'][:200])}</h1><p>{TASK_WORDS[t['status']]}. Filled {num('filled')} "
                     f"of {num('total')} fields.</p>{why}{task_card(csrf, n)}"
                     + (f"<p>Fill in Chrome yourself:</p>{lst('yourself')}" if lst("yourself") else "")
                     + (f"<p>Check:</p>{lst('check')}" if lst("check") else "")
                     + f"<h2>Log</h2><table><tr><th>time</th>{''.join(f'<th>{c}</th>' for c in cols)}</tr>{rows}</table>"
                     + "<p><a href='/'>Talk</a></p>",
                     f'<meta http-equiv="refresh" content="{2 if teaching() else 3}">'
                     if live() and (teaching() or not task_card(csrf, n)) else "", here="/")

    def sandbox_pages():
        sb = applyfiles.read_json(home, applyfiles.SANDBOX)
        if not sb or sb.get("run") != panel.run_id or not isinstance(sb.get("pages"), list):
            return ""
        num = lambda p, k: p.get(k) if type(p.get(k)) is int else 0   # noqa: E731
        rows = "".join(
            f"<li>{escape(str(p.get('title') or p.get('url') or '')[:200])}: "
            + (f"{num(p, 'fields')} fields, {num(p, 'buttons')} buttons, {num(p, 'links')} links "
               f"<code>{escape(str(p.get('file'))[:80])}</code>"
               + (f" \u00b7 draft page <code>{escape(p['draft'][:80])}</code>, app <i>Check</i> in Drafts"
                  if isinstance(p.get("draft"), str) else "") if p.get("file") else escape(str(p.get("note") or "not captured")[:80]))
            + "</li>" for p in sb["pages"][:50] if isinstance(p, dict))
        return f"<p>Captured so far:</p><ul>{rows}</ul>" if rows else ""

    def result_card():
        r = applyfiles.read_json(home, applyfiles.RESULT)
        if live() or panel.run is None or not r or r.get("run") != panel.run_id or tasks():
            return ""   # a JobLens run shows its jobs' tasks instead
        labels = lambda k: "<ul>" + "".join(f"<li>{escape(str(x)[:300])}</li>" for x in (r.get(k) or [])[:50]) + "</ul>" \
            if isinstance(r.get(k), list) and r.get(k) else ""
        you, chk = labels("yourself"), labels("check")
        num = lambda k: r.get(k) if type(r.get(k)) is int else 0   # a garbled count must not break the Talk page
        done = panel.run.code == 0 and panel.run.stopped_reason is None
        return (f"<section class=appcard><h2>JobLens</h2><p>Filled {num('filled')} of {num('total')} fields. "
                + ("Review the form in Chrome and press Submit yourself." if done
                   else "The run stopped. Check the form in Chrome.") + "</p>"
                + (f"<p>Fill in Chrome yourself:</p>{you}" if you else "")
                + (f"<p>Check:</p>{chk}" if chk else "")
                + "<p class=m><a href='/apply/bank'>My answer bank</a></p></section>")

    def apply_answer(f):
        """Check every answer, then write reply.json once for this ask. Values are never logged or echoed."""
        with panel.lock:
            q = asked() if panel.session.active() else None
            if q is None or f.get("ask") != q[0] or applyfiles.read_json(home, applyfiles.REPLY) is not None:
                tell("That question is no longer waiting for an answer.")
                return "/"
            answers = {}
            for fd in q[1]:
                v = f.get("a:" + fd["key"], "")
                if fd["kind"] == "textarea":
                    v = v.replace("\r\n", "\n")   # browsers send a textarea's newlines as CRLF
                if len(v) > 2000 or not ok_value(v, fd["kind"]) or (
                        v and fd["kind"] in ("select", "radio") and v not in fd["options"]):
                    tell(f"That answer can't be used: {fd['label'][:300]}.")
                    return "/"
                answers[fd["key"]] = v
            n = sum(1 for v in answers.values() if v)
            audited("apply_answer", {"outcome": str(n)},   # the reply first: the live run is waiting on it
                    lambda: applyfiles.write_json(home, applyfiles.REPLY, {"run": panel.run_id, "answers": answers}))
            tell(f"Sent {n} answer{'' if n == 1 else 's'} to Job Apply.")
            for fd in q[1]:
                v = answers[fd["key"]]
                if v and f.get("save:" + fd["key"]):
                    try:   # the reply is sent: nothing here may turn into a 500
                        audited("bank_updated", {"field": fd["key"][:200]},
                                lambda fd=fd, v=v: add_answer(home / applyfiles.BANK, fd["label"], v))
                    except Exception:
                        tell("That answer couldn't be saved to your bank.")
        return "/"

    rejected = {}   # the last refused bank edit, shown once: {"msg": fixed BankError text, "text": the admin's own YAML}

    def bank_page(csrf):
        bad = rejected.pop("msg", None), rejected.pop("text", None)
        try:
            text = bad[1] if bad[1] is not None else (read_bank(home / applyfiles.BANK) or b"").decode()
        except (OSError, BankError, UnicodeDecodeError):
            text = ""
        return _page(f"<section class=appcard><h1>My answer bank</h1><p class=m>YAML. Your own answers, used to fill "
                     f"job forms; they are never sent anywhere else.</p>"
                     f"{f'<p class=fail>{escape(bad[0])}</p>' if bad[0] else ''}"
                     f"<form method=post action=/apply/bank>{hidden(csrf)}"
                     f"<textarea name=text rows=24 cols=80 spellcheck=false aria-label='Answer bank YAML'>{escape(text)}</textarea>"
                     f"<button class=go>Save</button></form></section>")

    def bank_post(f):
        """Validate the posted YAML with load_bank on a temp file, then replace the bank. Contents are never logged."""
        text = f.get("text", "").replace("\r\n", "\n")
        path = home / applyfiles.BANK
        if len(text.encode()) > 60000:
            rejected.update(msg="answer bank too large")
            return "/apply/bank"
        with panel.lock:   # apply_answer's bank saves hold it too: one temp name, one writer
            tmp = None
            try:
                tmp = stage_text(path, text)
                cv = load_bank(tmp, agents.user_home()).cv_file
                if cv:   # a file not there yet is fine; one that would resolve outside home is not
                    uh = os.path.realpath(agents.user_home())
                    if not Path(os.path.realpath(Path(uh, cv[2:]) if cv.startswith("~/") else cv)).is_relative_to(uh):
                        raise BankError("cv_file must be inside your home folder")
                audited("bank_updated", {"field": "all"}, lambda: os.replace(tmp, path))
            except BankError as e:
                rejected.update(msg=str(e), text=text)
                if tmp and os.path.lexists(tmp):
                    os.unlink(tmp)
                return "/apply/bank"
            except BaseException:
                if tmp and os.path.lexists(tmp):
                    os.unlink(tmp)
                raise
        tell("Saved your answer bank.")
        return "/apply/bank"

    def say(f):
        later = []   # an expired session's run stop, run once the lock is released
        try:
            with panel.lock:   # check-and-act: one session open, one run start at a time
                return command(f, later)
        finally:
            for fn in later:
                fn()

    def invalid_input(hit, vals):
        """Strip and check the run-time inputs in place; the label of the first bad or missing one, else None."""
        for k, d in flow_inputs(hit.path).items():
            v = vals.get(k, "")
            if str(d["pattern"]).startswith("https://"):   # links only today: drop ?query, #fragment and one trailing "/"
                v = re.split(r"[?#]", v, maxsplit=1)[0].removesuffix("/")
            if not re.fullmatch(str(d["pattern"]), v):
                return d.get("label", k)
            vals[k] = v
        return None

    def command(f, later):
        text = " ".join(f.get("text", "").split())[:200]
        if not text:
            return "/"
        code = re.fullmatch(r"[0-9]{6}", text) is not None
        # never a code: any run of 6 digits, spaces allowed between them, is masked
        panel.convo.append("Admin -> " + re.sub(r"[0-9](?: ?[0-9]){5}", "••••••", text))
        vals = {}   # input values typed for an app that takes them
        sl = re.fullmatch(r"/([A-Za-z0-9_-]{0,64})(?: (.+))?", text)
        if sl:   # a slash command: alone it shows the app's card; with words it runs like "run <app> <words>"
            name, rest = sl[1].lower(), sl[2]
            if name in ("", "help"):
                tell("Commands: " + ", ".join(slashes()) + ". Type one to see what it needs.")
                return "/"
            app = next((a for a in apps() if slug(a.name) == name or a.id == name), None)
            ins = flow_inputs(app.path) if app and not by_slash(name) else {}
            form = {k: " ".join(f["in:" + k].split()) for k in ins if "in:" + k in f}   # declared keys only
            if rest is None and not form:
                show_card(name)
                return "/"
            if ins:
                vals = form or ({next(iter(ins)): rest} if len(ins) == 1 and rest is not None else {})
                text = f"run {name.replace('-', ' ')}"
            else:
                text = f"run {name} {rest}" if by_slash(name) else f"run {name.replace('-', ' ')}"   # apps without inputs take no words yet
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
        cm = re.fullmatch(r"(?:run|start|open) (claude(?: code)?|codex)(?: in)?(?: (.+))?", text, re.I)
        if cm:
            claude_start(agents.CODEX if cm[1].lower() == "codex" else agents.CLAUDE, cm[2] or "")
            return "/"
        kind, hit = match(text, al := apps())
        if kind == "run" and live():
            tell(f"{panel.app.name} is still running.")
        elif kind == "run" and (bad := invalid_input(hit, vals)):
            tell(f"That isn't a valid {bad}.")
        elif kind == "run":
            t = tickets.create(home, hit.id, hit.digest, panel.session.id, vals or None)
            r = launcher(hit.path, t, vals or None)
            r.start()
            panel.run, panel.app, panel.card, panel.run_id = r, hit, None, tickets.run_id(t)
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

    def _src():
        if templates is not None:
            return Path(templates)
        from govaios.engine import REPO   # the flows and pages shipped inside the app
        return REPO

    def _tpl(tid):
        return next((t for t in market.CATALOG if t.id == tid), None)

    def market_page():
        have = market.installed_ids(flows_dir)
        cards = []
        for t in market.CATALOG:
            act = (f"<p class=state>Installed as {escape(have[t.id])}</p>" if t.id in have
                   else f"<p><a class=go href='/market/setup/{t.id}'>Set up</a></p>" if flows_dir else "")
            needs = "".join(f"<span class=need>{escape(n)}</span>" for n in t.needs)
            cards.append(f"<section class=tpl><h2>{escape(t.title)}</h2><p>{escape(t.does)}</p>"
                         f"<p class=m>{escape(t.limits)}</p><div>{needs}</div>{act}</section>")
        for ag in agents.AGENTS.values():
            where = agents.found(ag)
            act = ("<p class=state>Governed</p>" if cc_roots(ag) is not None
                   else f"<p><a class=go href='/{ag.slash}'>Set up</a></p>")
            cards.append(f"<section class=tpl><h2>{ag.title}, governed</h2><p>{DOES[ag.id]}</p>"
                         f"<p class=m>{'Found at ' + escape(where) if where else 'Not found in the usual places on this Mac.'}"
                         f"</p><div><span class=need>{ag.title}</span><span class=need>Your Mac password</span>"
                         f"<span class=need>Touch ID</span></div>{act}</section>")
        nodir = "" if flows_dir else "<p class=note>No apps folder given, so nothing can be set up here.</p>"
        return _page(f"<h1>Marketplace</h1><p>Templates that ship with GOV-AIOS. Setting one up makes a draft app; "
                     f"it runs only after you approve it with Touch ID.</p>{nodir}{''.join(cards)}", here="/market")

    STEPS = 12   # step rows on the compose form
    DELETABLE = re.compile(r"(studio|check)_[a-z0-9_]{1,70}")   # flow ids Delete may remove (the file is <id>.yaml)
    PAGE_ID = re.compile(r"[a-z0-9_]{1,80}")

    def delete_form(csrf, kind, name, back):
        return (f"<form method=post action=/apps/delete>{hidden(csrf)}<input type=hidden name=kind value={kind}>"
                f"<input type=hidden name=name value='{escape(name)}'><input type=hidden name=back value='{back}'>"
                f"<button class=stop>Delete</button></form>")

    def approved_browser():
        ok = {a.id for a in apps() if a.approved}
        return flows_dir and studio.find_browser(flows_dir, lambda wf: wf["id"] in ok)

    def studio_page(csrf):
        """Draft pages from the Web Sandbox, and composing a bigger app from them (saved as a Draft)."""
        cat = studio.catalogue(flows_dir, flows_dir.parent / "pages", approved_browser()) if flows_dir else {}
        rows = "".join(
            f"<li><b>{escape(pid)}</b> \u00b7 <code>{escape(info['url'][:120])}</code>"
            f"{delete_form(csrf, 'page', pid, '/studio')}</li>" for pid, info in cat.items())
        mine = "".join(f"<li><b>{escape(a.name)}</b> \u00b7 {'approved' if a.approved else 'in Drafts'}"
                       f"{delete_form(csrf, 'flow', a.id, '/studio')}</li>" for a in apps() if DELETABLE.fullmatch(a.id))
        b = approved_browser() or {}
        runs = (f"Runs in {escape(str(b['profile_directory']))} as {escape(str(b['account']))}." if b
                else "No approved app has a browser profile to copy yet.")
        new = (f"<section class=appcard><h2>New automation</h2><p class=m>{runs} An empty app that opens a site and waits on its "
               f"start page: when it runs, choose Teach on that page and show it the steps. Saved as a Draft.</p>"
               f"<form method=post action=/studio/new>{hidden(csrf)}<label>App name <input name=app maxlength=40 required>"
               f"</label><label>Starting link <input name=url type=url required placeholder='https://...'></label>"
               f"<button class=go>Save as a Draft app</button></form></section>" if flows_dir else "")
        opts = ["<option value=''>\u2014</option>"]
        for pid, info in cat.items():
            opts.append(f"<option value='open:{escape(pid)}'>Open {escape(pid)}</option>")
            opts.append(f"<option value='fill:{escape(pid)}'>Fill the form on {escape(pid)}</option>")
            for el in info.get("items", {}):
                opts.append(f"<option value='each:{escape(pid)}.{escape(el)}'>For each item in {escape(el)} on "
                            f"{escape(pid)}</option>")
            for el, (role, label, risk) in info["elements"].items():
                if role in ("button", "link") and risk in studio.CLICKABLE:
                    opts.append(f"<option value='click:{escape(pid)}.{escape(el)}'>Click {escape(str(label)[:60])} "
                                f"on {escape(pid)}</option>")
        opts.append("<option value=click_item>Click the item (inside a for each)</option>")
        opts.append("<option value=end_each>End of for each</option>")
        opts.append("<option value=review>Hand over: you check and submit in Chrome</option>")
        sel = "".join(f"<label>Step {i}<select name=s{i}>{''.join(opts)}</select></label>" for i in range(1, STEPS + 1))
        form = (f"<section class=appcard><h2>Compose an app</h2><p class=m>Steps run in order. Step 1 opens a page; "
                f"later Opens wait for the page a click led to. For each runs the steps up to End of for each once per "
                f"item (up to 10), each its own task and tab. Buttons rated submit are never offered: those clicks "
                f"stay yours.</p><form method=post action=/studio/compose>{hidden(csrf)}<label>App name <input name=app "
                f"maxlength=40 required></label>{sel}<button class=go>Save as a Draft app</button></form></section>"
                if cat else "<p class=note>No draft pages yet. Capture pages with the Web Sandbox first.</p>")
        return _page(f"<h1>Studio</h1><p>Pages you captured in the Web Sandbox become draft pages. "
                     f"Compose them into an app here, or start a new automation.</p>"
                     f"{new}<h2>Studio apps</h2><ul>{mine}</ul><h2>Draft pages</h2><ul>{rows}</ul>{form}", here="/studio")

    def studio_compose(f):
        if not flows_dir:
            return None
        cat = studio.catalogue(flows_dir, flows_dir.parent / "pages")
        try:
            flow = studio.compose(f.get("app", ""), [f.get(f"s{i}", "") for i in range(1, STEPS + 1)], cat)
            fid = studio.write_composed(flows_dir, flow)
        except (ValueError, OSError) as e:
            tell(f"Studio: {e}.")
            return "/studio"
        log.append("setting", field="studio_compose", flow=fid)
        tell(f"{flow['workflow']['app']} is saved as a draft app. Approve it to let it run.")
        return "/"

    def studio_new(f):
        if not flows_dir:
            return None
        try:
            path = studio.new_automation(flows_dir, f.get("app", ""), f.get("url", ""), approved_browser())
        except (ValueError, OSError) as e:
            tell(f"Studio: {e}.")
            return "/studio"
        log.append("setting", field="studio_new", flow=path.stem)
        tell(f"{f.get('app', '').strip()[:40]} is saved as a draft app. Approve it to let it run.")
        return "/"

    def apps_delete(f):
        """Delete a Studio app (studio_*, check_*) or a draft page no flow uses; its approval goes first."""
        kind, name, back = f.get("kind"), f.get("name", ""), f.get("back")
        back = back if back in ("/", "/studio") else "/"
        if not flows_dir:
            return None
        pages = flows_dir.parent / "pages"
        if kind == "flow" and DELETABLE.fullmatch(name):
            path = flows_dir / f"{name}.yaml"
            try:   # approvals are keyed by the workflow id inside the file
                wid = yaml.safe_load(path.read_text())["workflow"]["id"]
            except Exception:
                wid = name
            apply = lambda: (Approvals(approvals_path).revoke_flow(wid), path.unlink())   # noqa: E731
        elif kind == "page" and PAGE_ID.fullmatch(name):
            path = pages / f"{name}.yaml"
            try:   # any flow, approved or not; one that cannot be read might use it: refuse
                used = set().union(*(pages_used(yaml.safe_load(p.read_text())["workflow"]) for p in flows_dir.glob("*.yaml")))
            except Exception:
                used = {name}
            if name in used:
                tell(f"Studio: {name} is used by an app, so it stays.")
                return back
            try:   # drafts only: the Web Sandbox header
                draft = path.read_text().startswith("# Draft from the Web Sandbox")
            except OSError:
                draft = False
            if not draft:
                tell("Studio: only draft pages can be deleted.")
                return back
            apply = path.unlink
        else:
            tell("Studio: only Studio apps and unused draft pages can be deleted.")
            return back
        if path.is_symlink() or not path.is_file():
            tell("Studio: nothing to delete there.")
            return back
        audited("setting", {"field": "delete", "target": path.name}, apply)
        tell(f"{path.name} is deleted.")
        return back

    def market_setup_page(csrf, tid):
        t = _tpl(tid)
        if t is None or not flows_dir:
            return None
        if t.id in market.installed_ids(flows_dir):
            return market_page()
        profiles = market.chrome_profiles(chrome_state or market.local_state())
        if profiles:
            pick = "".join(f"<label><input type=radio name=profile value='{escape(d)}' required{' checked' if i == 0 else ''}>"
                           f"<span><b>{escape(n)}</b> <span class=m>{escape(a)}</span></span></label>"
                           for i, (d, n, a) in enumerate(profiles))
            ask = (f"<p>Which Chrome profile should it use? The app checks this Google account before it opens any site.</p>"
                   f"<div class=pick>{pick}</div>")
        else:
            ask = ("<p class=note>Chrome's profile list could not be read. Type the profile folder and the Google "
                   "account signed in to it.</p><label for=profile>Chrome profile folder</label>"
                   "<input id=profile name=profile placeholder='Profile 1' required>"
                   "<label for=account>Google account</label><input id=account name=account type=email required>")
        return _page(f"<section class=card><h1>Set up {escape(t.title)}</h1><p>{escape(t.does)}</p>"
                     f"<form method=post action=/market/setup>{hidden(csrf)}<input type=hidden name=template value='{t.id}'>"
                     f"{ask}<p><button class=go>Set up as draft</button> <a href='/market'>Cancel</a></p></form></section>",
                     here="/market")

    def market_setup(f):
        t = _tpl(f.get("template", ""))
        if t is None or not flows_dir:
            return None
        profile = f.get("profile", "")
        profiles = market.chrome_profiles(chrome_state or market.local_state())
        if profiles:   # the account comes from Chrome, never from the form
            account = next((a for d, _, a in profiles if d == profile), None)
            if account is None:
                return None
        else:
            account = f.get("account", "").strip()
        try:
            market.setup(t, profile, account, flows_dir, _src())
        except ValueError:
            return None
        log.append("setting", field="app_setup", flow=t.id)   # no account or profile in the log
        tell(f"{t.title} is set up as a draft. Approve it to let it run.")
        return "/"

    def agent_page(ag, csrf):
        roots = cc_roots(ag)
        if roots is not None:
            body = (f"<p class=state>Governed. {ag.title} may work in: {escape(', '.join(roots))}</p>"
                    f"<p>Turning it off removes the settings (Touch ID, then your Mac password). {ag.title} then runs "
                    f"without GOV-AIOS checks from its next session.</p>"
                    f"<form method=post action=/{ag.slash}/off>{hidden(csrf)}<button>Turn off…</button></form>")
        else:
            try:
                pol = agents.load(home, ag)[0]
            except Exception:
                pol = None
            ask = (f"<p>{ag.title} may work in the folders of your existing policy: "
                   f"{escape(', '.join(pol.get('project_roots', [])))}</p>" if pol else
                   f"<label for=folders>Which folders may {ag.title} work in? One per line. Anything outside is "
                   "refused and logged.</label><textarea id=folders name=folders rows=3 required>~/Documents/2026"
                   "</textarea>")
            body = (f"<ul><li>{RULES[ag.id]}</li><li>You approve the policy with Touch ID.</li><li>macOS asks for your "
                    f"Mac password to write the settings.</li></ul>"
                    f"<form method=post action=/{ag.slash}/setup>{hidden(csrf)}{ask}"
                    "<p><button class=go>Approve and install…</button> <a href='/market'>Cancel</a></p></form>"
                    "<p class=m>Sessions already open stay ungoverned until they restart.</p>")
        where = agents.found(ag)
        found = f"Found at {escape(where)}." if where else "Not found in the usual places on this Mac."
        return _page(f"<section class=card><h1>{ag.title}, governed</h1><p class=m>{found}</p>{body}</section>",
                     here="/market")

    def _folders(text):
        uh = agents.user_home()
        out = [str(uh / l.strip()[2:]) if l.strip().startswith("~/") else l.strip() for l in text.splitlines() if l.strip()]
        if not 0 < len(out) <= 10 or not all(r.startswith("/") and Path(r).is_dir() for r in out):
            raise ValueError("each folder must be an existing folder, written in full or starting with ~/")
        return out

    def setup_post_for(ag):
        def post(f):
            if admin is None:
                tell(f"{ag.title} setup needs the installed panel.")
                return "/"
            try:
                roots = [] if (home / ag.policy).exists() else _folders(f.get("folders", ""))
                path, raw, pol, digest = agents.draft(home, roots, ag)
            except ValueError as e:   # our own messages
                tell(f"{ag.title} was not set up: {e}.")
                return "/"
            q = agents.question(path, raw, ag)
            ok, how = auth.approve(q, ag.reason, home)
            log.append("flow_approval", flow=ag.id, flow_hash=digest, executor=ag.id,
                       decision="allow" if ok else "deny", approver="admin", channel="touch_id", auth=how,
                       shown=shown_digest(q, None if how == "none" else ag.reason))
            if not ok:
                tell(f"{ag.title} was not set up: the policy was not approved.")
                return "/"
            try:
                agents.commit(home, path, raw, digest, ag)
            except (OSError, ValueError):
                tell(f"{ag.title} was not set up: the policy changed while it was being approved. Try again.")
                return "/"
            code = admin("install", agents.stage(home, pol, ag), ag.id)
            log.append("setting", field=ag.id, action="install", outcome=str(code))
            if code == 0 and cc_roots(ag) is not None:
                tell(f"{ag.title} is governed. Sessions already open stay ungoverned until they restart.")
            elif code == 2:
                tell(f"{ag.title} was not set up: the Mac password was cancelled. The policy stays approved; "
                     "press Approve and install again to finish.")
            else:
                tell(f"{ag.title} was not set up: writing the settings failed.")
            return "/"
        return post

    def off_post_for(ag):
        def post(f):
            if admin is None:
                tell(f"Turning {ag.title} off needs the installed panel.")
                return "/"
            ok, how = auth.prove(f"turn off {ag.title} governance", home)
            log.append("setting", field=ag.id, action="remove", decision="allow" if ok else "deny",
                       approver="admin", channel="touch_id", auth=how)
            if not ok:
                return f"/{ag.slash}"
            code = admin("remove", "", ag.id)
            log.append("setting", field=ag.id, action="remove", outcome=str(code))
            tell(f"{ag.title} governance is off. New sessions run without GOV-AIOS checks." if code == 0
                 else f"{ag.title} governance is still on: the Mac password was cancelled." if code == 2
                 else f"{ag.title} governance is still on: removing the settings failed.")
            return "/"
        return post

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

    def terms_post(f):
        """Record the admin's verdict for the terms card's site (terms.record checks it), then reply checked."""
        with panel.lock:
            q = card_asked() if panel.session.active() else None
            if q is None or q[1]["kind"] != "terms" or f.get("ask") != q[0] \
                    or applyfiles.read_json(home, applyfiles.REPLY) is not None:
                tell("That card is no longer waiting.")
                return "/"
            site, verdict = q[1]["label"], f.get("verdict", "")
            try:
                audited("setting", {"field": "terms", "target": site[:200], "outcome": verdict[:20]},
                        lambda: terms.record(home, site, verdict, f.get("link", "").strip(),
                                             f.get("clause", "").replace("\r\n", "\n")))
            except ValueError as e:   # terms.record's own fixed messages
                tell(f"Terms not recorded: {e}.")
                return "/"
            reply_card(q, "checked")
        return "/"

    LESSON = re.compile(r"/lesson/([0-9-]{22}-[a-z0-9_]{1,64}\.json)")
    lesson_lock = threading.Lock()   # one lesson approval (and its Touch ID) at a time

    def lesson_ctx(name):
        """(lesson, proposal, app or None, the stuck step's case ids, {known page gaining elements: names of the
        other apps that use it}). ValueError/OSError for a bad or missing one."""
        if not flows_dir:
            raise ValueError("no apps folder")
        lesson = lessons.load(home, name)
        proposal = lessons.propose(lesson, flows_dir.parent / "pages",
                                   load_bank(home / applyfiles.BANK, agents.user_home()))
        app = next((a for a in apps() if a.id == lesson.get("flow")), None)
        cases = set()
        if app is not None and lesson.get("flow") not in lessons.SANDBOX:
            st = lessons._find(yaml.safe_load(app.path.read_bytes())["workflow"]["steps"], lesson.get("step"))
            cases = set((st or {}).get("on_match", {}))
        grown, others = {p["id"] for p in proposal["pages"] if p["added"]}, {}
        for a in apps() if grown else ():
            if a.id != lesson.get("flow"):
                for pid in grown & pages_used(yaml.safe_load(a.path.read_bytes())["workflow"]):
                    others.setdefault(pid, []).append(a.name)
        return lesson, proposal, app, cases, others

    def lesson_page(name, csrf):
        try:
            lesson, proposal, _, cases, others = lesson_ctx(name)
        except BankError as e:
            return _page(f"<h1>What I learned</h1><p class=fail>Your answer bank has an error: {escape(str(e))}. "
                         f"<a href='/apply/bank'>Fix it</a> first.</p>", here="/")
        except (ValueError, OSError, KeyError, TypeError):
            return None
        return _page(lesson_ui.page(name, lesson, proposal, cases, others, hidden(csrf)), here="/")

    def lesson_reply(name, choice):
        """Answer the engine's lesson card for this lesson, if it is still waiting."""
        with panel.lock:
            q = card_asked()
            if q is not None and q[1]["kind"] == "lesson" and q[1]["label"] == name \
                    and applyfiles.read_json(home, applyfiles.REPLY) is None:
                applyfiles.write_json(home, applyfiles.REPLY, {"run": panel.run_id, "card": choice})

    def lesson_approve(f):
        if not lesson_lock.acquire(blocking=False):
            tell("Another lesson is being approved.")
            return "/"
        try:
            return approve_lesson(f)
        finally:
            lesson_lock.release()

    def approve_lesson(f):
        """The only place a lesson changes a flow, page files or the bank: checked, then Touch ID, then written."""
        name = f.get("name", "")
        if not LESSON.fullmatch(f"/lesson/{name}"):
            return None
        back = f"/lesson/{name}"
        try:
            lesson, proposal, app, _, _ = lesson_ctx(name)
            deleted, keeps = lesson_ui.edits(proposal, f)
        except (ValueError, OSError, KeyError, TypeError):
            return None
        fid, sandbox, pages_dir = lesson.get("flow"), lesson.get("flow") in lessons.SANDBOX, flows_dir.parent / "pages"
        raw = None
        if not sandbox:
            try:   # these bytes are what is built on and approved: the flow is never read again
                d, raw = read_bound(app.path, pages_dir) if app is not None else (None, None)
            except (OSError, KeyError, ValueError, yaml.YAMLError):
                d = None
            if d is None or d != lesson.get("digest"):
                tell(f"{app.name if app else fid} changed since this lesson; teach it again")
                return back
            if not Approvals(approvals_path).flow_ok(app.id, d):   # revoked: a lesson never re-approves it
                tell(f"Approve {app.name} first, then add what it learned.")
                return back
        if f.get("p") != lesson_ui.digest(proposal):
            tell("This lesson changed since you opened it. Look at it again.")
            return back
        try:
            plan = lessons.build(lesson, proposal, deleted, keeps, raw, None if sandbox else app.path, pages_dir)
        except (ValueError, KeyError, TypeError) as e:
            tell(f"Not approved: {str(e)[:200]}.")
            return back
        ok, how = auth.prove(f"Add what GOV-AIOS learned to {app.name if app else 'Studio'}", home)
        who = {"flow": fid, "target": name, "approver": "admin", "channel": "touch_id", "auth": how}
        if not ok:
            log.append("lesson", decision="deny", **who)
            tell("Touch ID is busy. Try again." if how in ("busy", "none") else "Not approved: nothing was written.")
            return back
        try:
            with panel.lock:   # bank_post and saved answers write the bank under it too
                digest = lessons.apply(plan, pages_dir, home / applyfiles.BANK)
                if not sandbox:   # only once every file is written: never approved with a mismatched digest
                    Approvals(approvals_path).approve_flow(app.id, digest)
        except Exception as e:
            log.append("lesson", decision="allow", outcome="error", reason=type(e).__name__, **who)
            tell("Writing what I learned failed, so nothing was approved. Teach the page again.")
            return back
        log.append("lesson", decision="allow", outcome="approved", flow_hash=digest, reason=plan["counts"], **who)
        lesson_reply(name, "approved")
        tell(f"Learned: {app.name} uses it from the next run." if not sandbox else "Saved the pages to Studio.")
        return "/"

    def lesson_discard(f):
        name = f.get("name", "")
        if not LESSON.fullmatch(f"/lesson/{name}"):
            return None
        try:
            fid = lessons.load(home, name).get("flow")
        except (ValueError, OSError):
            return None
        audited("lesson", {"flow": fid if isinstance(fid, str) else None, "target": name, "outcome": "discarded"},
                lambda: lesson_reply(name, "discarded"))
        tell("Lesson discarded.")
        return "/"

    POSTS = {"/terms": terms_post, "/lesson/approve": lesson_approve, "/lesson/discard": lesson_discard,
             "/apply/answer": apply_answer, "/apply/card": apply_card, "/apply/bank": bank_post, "/say": say, "/approve": approve, "/end": end, "/totp/setup": setup_post, "/totp/reset": reset,
             "/revoke": revoke, "/name": set_name, "/market/setup": market_setup, "/studio/compose": studio_compose, "/studio/new": studio_new,
             "/apps/delete": apps_delete}
    for _ag in agents.AGENTS.values():
        POSTS.update({f"/{_ag.slash}/setup": setup_post_for(_ag), f"/{_ag.slash}/off": off_post_for(_ag),
                      f"/{_ag.slash}/start": start_post(_ag)})

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
                    with sign_lock:   # the same lock /signin/code counts under
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
            ok = hmac.compare_digest("".join(f.get("word", "").split()).upper().encode(), word.encode())
            with sign_lock:
                if not ok:
                    refused()
                else:
                    state["n"] = 0
            locked = ok and auth.screen_locked()   # locked since the sheet: that lock signs this browser out too
            log.append("ui_login", decision="allow" if ok and not locked else "deny", approver="admin",
                       channel="touch_id", auth="screen_lock" if locked else how if ok else "wrong_code",
                       shown=shown_digest(None, reason))   # audit first, then the cookie
            if not ok:
                return self._redirect("/?m=code", clear)
            if locked:
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
                mk = re.fullmatch(r"/market/setup/([a-z0-9_]{1,64})", u.path)
                cs = re.fullmatch(r"/audit/(claude|codex)/([A-Za-z0-9-]{1,64})", u.path)
                tk = re.fullmatch(r"/apply/task/([0-9]{1,2})", u.path)
                ls = LESSON.fullmatch(u.path)
                ap = by_slash(u.path[1:])
                page = (talk(sess[1]) if u.path == "/" else index() if u.path == "/audit"
                        else approvals(sess[1]) if u.path == "/approvals" else fulllog() if u.path == "/audit/log"
                        else setup(sess[1], u.query == "bad=1") if u.path == "/totp/setup"
                        else bank_page(sess[1]) if u.path == "/apply/bank"
                        else task_page(int(tk[1]), sess[1]) if tk
                        else lesson_page(ls[1], sess[1]) if ls
                        else market_page() if u.path == "/market" else studio_page(sess[1]) if u.path == "/studio" else agent_page(ap, sess[1]) if ap
                        else market_setup_page(sess[1], mk[1]) if mk
                        else cc_session_page(by_slash(cs[1]), cs[2]) if cs else run(int(m[1])) if m else app_page(a[1]) if a and APP_ID.fullmatch(a[1]) else None)
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
            if not 0 <= n <= (262144 if path == "/apply/bank" else 65536):   # the bank's 60000 chars may encode 3x
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
