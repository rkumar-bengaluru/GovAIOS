"""Delivery of a flow's saved job files to a local service (block check, payload, once-only tracking)."""
import fcntl
import hashlib
import http.client
import json
import os
import re
import signal
import stat
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import runstate
from .runstate import Stop

TARGETS = {"joblens": {"url": "http://127.0.0.1:8100/api/discover/listings", "label": "joblens (local)"}}


def _bad_char(c):
    return unicodedata.category(c) == "Cc"   # as JobLens: C0, DEL and C1 (e.g. U+0085)


def _dirs(steps):
    for s in steps:
        if s.get("action") == "write_json":
            yield s.get("directory")
        yield from _dirs(s.get("steps", []))


def check_block(flow):
    if "deliver" not in flow:
        return None
    b = flow["deliver"]
    if not isinstance(b, dict) or set(b) != {"to", "from", "source"}:
        raise ValueError("deliver")
    if b["to"] not in TARGETS:
        raise ValueError("to")
    if b["from"] not in set(_dirs(flow["steps"])):
        raise ValueError("from")
    s = b["source"]
    if not isinstance(s, str) or not 1 <= len(s.strip()) <= 50 or any(map(_bad_char, s)):
        raise ValueError("source")
    if "deliver" not in flow.get("permissions", {}).get("allow", []):
        raise ValueError("permissions.allow")
    return b


def _line(v):
    return " ".join("".join(" " if _bad_char(c) else c for c in v).split())


_IST = timezone(timedelta(hours=5, minutes=30))   # no DST; avoids tz data in the frozen app
_AGO = re.compile(r"(?:posted\s+)?(?:(\d+|an?)\s+(minute|hour|day)s?\s+ago|(just now|today|yesterday))")


def _posted_on(posted, captured_at):
    """Himalayas shows relative ages ("9 hours ago"): the date counted back from capture, or None when vague."""
    if not isinstance(posted, str) or not isinstance(captured_at, str):
        return None
    m = _AGO.fullmatch(posted.strip().lower())
    try:
        at = datetime.fromisoformat(captured_at)
    except ValueError:
        return None
    if not m:
        return None
    n, unit, word = m.groups()
    if word:
        d = at.date() - timedelta(days=word == "yesterday")
    else:
        k = 1 if n in ("a", "an") else int(n)
        try:
            d = (at - timedelta(**{unit + "s": k})).date()
        except OverflowError:   # absurd age from the page
            return None
    if d > datetime.now(_IST).date():   # JobLens refuses a date after its today (Asia/Kolkata)
        return None
    return d.isoformat()


def build_payload(rec, source):
    def fail(field):
        return None, "failed", field

    raw = {k: rec.get(k) for k in ("job_title", "company", "description", "url")}
    for k, f in (("job_title", "title"), ("company", "company"), ("description", "jd_text"), ("url", "url")):
        if raw[k] is not None and not isinstance(raw[k], str):
            return fail(f)
    title = _line(raw["job_title"] or "")
    if not re.search(r"[^\W_]", title) or len(title) > 500:
        return fail("title")
    p = {"title": title, "source": source}
    company = _line(raw["company"] or "")
    if len(company) > 500:
        return fail("company")
    if company:
        p["company"] = company
    jd = (raw["description"] or "").replace("\r\n", "\n").replace("\r", "\n")
    jd = "".join(c for c in jd if c in "\n\t" or not _bad_char(c)).strip()
    if len(jd) < 300:
        return None, "skipped_too_short", "jd_text"
    if len(jd) > 50000:
        return fail("jd_text")
    p["jd_text"] = jd
    url = (raw["url"] or "").strip()
    if len(url) > 2000:
        return fail("url")
    try:
        parts = urlsplit(url)
    except ValueError:  # malformed host, e.g. "http://[x"
        parts = None
    if parts and parts.scheme in ("http", "https") and parts.netloc and not any(c.isspace() or _bad_char(c) for c in url):
        p["url"] = url
    li = rec.get("list_item")
    posted = _posted_on(li.get("posted") if isinstance(li, dict) else None, rec.get("captured_at"))
    if posted:
        p["posted_on"] = posted
    return p, None, None


class Deliveries:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self):
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}

    def done(self, file_hash):
        e = self._load().get(file_hash)
        return e is not None and e["outcome"] != "retry"

    def record(self, file_hash, outcome, listing_id):
        with open(self.path.with_name("deliveries.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._load()
            data[file_hash] = {"outcome": outcome, "listing_id": listing_id}
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".deliveries.")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, self.path)
            except BaseException:
                os.unlink(tmp)
                raise


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a):
        return None   # a 3xx surfaces as HTTPError -> failed/http_3xx


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)   # no env/system proxies


def send(url, payload, timeout=20):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    try:
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                code, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, raw = e.code, e.read()
    except (OSError, ValueError, http.client.HTTPException):  # refused, timeout, DNS, truncated body
        return None, None
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    return code, body if isinstance(body, dict) else None


def classify(code, body):
    body = body or {}
    lid = body.get("id")
    lid = lid if isinstance(lid, int) and not isinstance(lid, bool) else None
    if code == 202:
        return "delivered", lid, None
    if code == 200:
        return "duplicate", lid, None
    if code == 400:
        err = body.get("error")
        msg = err.get("message") if isinstance(err, dict) else None
        head = msg.split(":")[0] if isinstance(msg, str) and ":" in msg else None
        return "failed", None, head if head and re.fullmatch(r"[a-z_]{1,30}", head) else "bad_request"
    if code == 409:
        return "retry", None, "conflict"
    if code == 429:
        return "retry", None, "intake_cap"
    if code is None:
        return "retry", None, "unreachable"
    if code >= 500:
        return "retry", None, "server_error"
    return "failed", None, "http_%d" % code


MAX_BYTES = 1_000_000


def _read(path):
    """Bytes of a regular, non-symlink file (None otherwise); at most MAX_BYTES + 1."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)  # NONBLOCK: a FIFO must not hang open
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read(MAX_BYTES + 1) if stat.S_ISREG(os.fstat(f.fileno()).st_mode) else None


def deliver_batch(home, flow, block, audit, post=send):
    home = Path(home)
    d, tracker = home / block["from"], Deliveries(home / "deliveries.json")
    if not d.resolve().is_relative_to(home.resolve()):   # as engine do_write_json
        raise Stop("deliver directory outside the data home")
    counts = dict.fromkeys(("delivered", "duplicate", "retry", "failed", "skipped", "left", "unreachable"), 0)
    todo = []
    for name in (sorted(os.listdir(d)) if d.is_dir() else []):
        data = _read(d / name) if name.endswith(".json") else None
        if data is None:
            continue
        h = hashlib.sha256(data).hexdigest()
        if tracker.done(h):
            continue
        if len(data) > MAX_BYTES:
            rec = None
            local = ("failed", "size")
        else:
            try:
                rec = json.loads(data)
            except ValueError:
                rec = None
            local = None if isinstance(rec, dict) else ("failed", "bad_json")
        if rec is not None and rec.get("flow") != flow["id"]:
            continue
        todo.append((str((rec or {}).get("captured_at") or ""), name, h, rec, local))
    todo.sort(key=lambda t: t[:2])
    for i, (_, _, h, rec, local) in enumerate(todo):
        if runstate.stopped(home):
            raise Stop("emergency stop")
        code = lid = None
        if local is None:
            payload, outcome, reason = build_payload(rec, block["source"])
            if payload is not None:
                try:
                    code, body = post(TARGETS[block["to"]]["url"], payload)
                except Stop:   # JobLens may have stored it: audit, but leave the file pending (a resend is a 200)
                    audit.append("delivery", flow=flow["id"], target=block["to"], file_hash=h, response_code=None,
                                 listing_id=None, outcome="stopped", reason="emergency stop")
                    raise
                outcome, lid, reason = classify(code, body)
        else:
            outcome, reason = local
        counts["skipped" if outcome == "skipped_too_short" else outcome] += 1
        audit.append("delivery", flow=flow["id"], target=block["to"], file_hash=h, response_code=code,
                     listing_id=lid, outcome=outcome, reason=reason)
        tracker.record(h, outcome, lid)
        if outcome == "retry":
            counts["unreachable"] += reason == "unreachable"
            counts["left"] = len(todo) - i - 1
            break
    return counts


def last_run_finished(home, flow_id):
    state = None
    try:
        lines = (Path(home) / "audit.jsonl").read_text().splitlines()
    except FileNotFoundError:
        return False
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("flow") == flow_id:
            state = {"flow_start": "open", "flow_end": "done", "stop": "stopped"}.get(e.get("kind"), state)
    return state == "done"


def run_delivery(flow_path, home, audit):
    """Spec 4.3: trusts nothing from the shim; every check is made here."""
    import yaml

    from . import auth
    from .approvals import Approvals, read_bound

    flow_path, home = Path(flow_path), Path(home)
    try:
        digest, raw = read_bound(flow_path, flow_path.parent.parent / "pages")
    except KeyError as e:
        raise Stop(f"unknown page: {e.args[0]}") from None
    flow = yaml.safe_load(raw[flow_path])["workflow"]
    try:
        block = check_block(flow)
    except ValueError as e:
        raise Stop(f"bad deliver block: {e}") from None
    if block is None:
        raise Stop("flow has no deliver block")
    fid, approvals = flow["id"], Approvals(home / "approvals.json")
    if not approvals.flow_ok(fid, digest):
        raise Stop("flow not approved for its current file")
    if [p for p in runstate.live_runs(home) if p != os.getpid()]:
        raise Stop("another gov-aios run is live")
    if not last_run_finished(home, fid):
        raise Stop("last run did not finish")
    if not approvals.destination_ok(fid, block["to"]):
        ok, how = auth.approve(f"Flow '{fid}' wants to deliver its saved jobs to JobLens (local, 127.0.0.1:8100) "
                               f"for the first time. Approve?", f"{fid}: deliver to {block['to']}", home)
        audit.append("request", action="deliver", destination=block["to"], decision="allow" if ok else "deny",
                     approver="admin", channel="touch_id", auth=how, flow=fid)
        if not ok:
            print("approval busy" if how == "busy" else "not approved; nothing sent", file=sys.stderr)
            return 1
        approvals.approve_destination(fid, block["to"])

    def on_term(signum, frame):
        raise Stop("emergency stop")
    prev = signal.signal(signal.SIGTERM, on_term)
    try:
        c = deliver_batch(home, flow, block, audit)
    finally:
        signal.signal(signal.SIGTERM, prev)
    print(f"deliver {block['to']}: delivered {c['delivered']}, duplicate {c['duplicate']}, retry {c['retry']}, "
          f"failed {c['failed']}, skipped {c['skipped']}")
    if c["unreachable"]:
        print("JobLens not reachable at 127.0.0.1:8100 (is it running?)", file=sys.stderr)
    if c["left"]:
        print(f"{c['left']} file{'' if c['left'] == 1 else 's'} left for the next delivery")
    return 1 if c["retry"] or c["failed"] else 0
