"""Delivery of a flow's saved job files to a local service (block check, payload, once-only tracking)."""
import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from . import runstate
from .runstate import Stop

TARGETS = {"joblens": {"url": "http://127.0.0.1:8100/api/discover/listings", "label": "joblens (local)"}}


def _bad_char(c):
    return ord(c) < 32 or ord(c) == 127


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
        scheme = urlsplit(url).scheme
    except ValueError:  # malformed host, e.g. "http://[x"
        scheme = ""
    if scheme in ("http", "https") and not any(c.isspace() or _bad_char(c) for c in url):
        p["url"] = url
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


def send(url, payload, timeout=20):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    except (OSError, ValueError):  # refused, timeout, DNS
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
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        return f.read(MAX_BYTES + 1) if stat.S_ISREG(os.fstat(f.fileno()).st_mode) else None


def deliver_batch(home, flow, block, audit, post=send):
    home = Path(home)
    d, tracker = home / block["from"], Deliveries(home / "deliveries.json")
    counts = dict.fromkeys(("delivered", "duplicate", "retry", "failed", "skipped", "left"), 0)
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
                code, body = post(TARGETS[block["to"]]["url"], payload)
                outcome, lid, reason = classify(code, body)
        else:
            outcome, reason = local
        counts["skipped" if outcome == "skipped_too_short" else outcome] += 1
        tracker.record(h, outcome, lid)
        audit.append("delivery", flow=flow["id"], target=block["to"], file_hash=h, response_code=code,
                     listing_id=lid, outcome=outcome, reason=reason)
        if outcome == "retry":
            counts["left"] = len(todo) - i - 1
            break
    return counts
