"""Capture on stop: the page as it was when a web run stopped, for the admin's debugging.

Dev mode: NOT masked (names and values as on the page). shortcut: unmasked, add spec §5.3 masking before
this leaves dev or feeds Studio. Files are 0600 under <data home>/captures/, never printed; only the last KEEP stay (a run can save several: one per read-back mismatch, then the stop).
"""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

DIR = "captures"
KEEP = 30


def tree(n):
    d = {"role": n.role}
    for k in ("name", "value", "dom_id"):
        if getattr(n, k):
            d[k] = getattr(n, k)
    if n.dom_class:
        d["dom_class"] = list(n.dom_class)
    if n.children:
        d["children"] = [tree(c) for c in n.children]
    return d


def save(home: Path, flow_id: str, step, reason: str, url: str, title: str, root, refusal) -> tuple[str, str]:
    """Write one capture; returns (file name, sha256). Never follows a link."""
    d = Path(home) / DIR
    if d.is_symlink():
        raise OSError("captures/ is a symlink")
    d.mkdir(mode=0o700, exist_ok=True)
    u = urlsplit(url)
    doc = {"flow": flow_id, "step": step, "reason": reason, "at": datetime.now().isoformat(timespec="seconds"),
           "url": f"{u.scheme}://{u.netloc}{u.path}" if u.scheme else url, "title": title,
           "refusal": refusal, "tree": tree(root) if root is not None else None}
    data = json.dumps(doc, ensure_ascii=False, indent=1).encode()
    name = f"{datetime.now():%Y%m%d-%H%M%S-%f}-{flow_id}.json"
    fd = os.open(d / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    for old in sorted(p for p in d.iterdir() if p.suffix == ".json")[:-KEEP]:
        old.unlink()
    return name, hashlib.sha256(data).hexdigest()
