"""Delivery of a flow's saved job files to a local service (block check, payload, once-only tracking)."""
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

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
