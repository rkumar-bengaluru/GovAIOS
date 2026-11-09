"""Remembered approvals: approved flows (by hash) and approved destinations."""
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path

import yaml


def pages_used(flow):
    """Every page id a flow's steps reference, recursing into nested steps."""
    ids = set()

    def walk(steps):
        for s in steps:
            t = s.get("target", "").split(".")[0]
            if t and t not in ("current_item", "current_page"):
                ids.add(t)
            ids.update(s[k] for k in ("page", "verify_page") if k in s)
            ids.update(k for k in s.get("on_match", {}) if k != "unknown")
            walk(s.get("steps", []))
            for v in s.get("on_match", {}).values():   # a learned page's steps: their targets are bound too
                # the shape is checked by engine.check_learned at Runner init; this only has to not crash first
                if isinstance(v, dict) and isinstance(v.get("do"), list):
                    walk(v["do"])

    walk(flow["steps"])
    return ids


def read_bound(flow_path, pages_dir):
    """Read the flow and the page schemas it uses once: (digest, {path: bytes}).
    Callers parse these same bytes, so the approval binds to exactly what runs (Rule 11)."""
    flow_path = Path(flow_path)
    raw = {flow_path: flow_path.read_bytes()}
    h = hashlib.sha256(raw[flow_path])
    for pid in sorted(pages_used(yaml.safe_load(raw[flow_path])["workflow"])):
        p = Path(pages_dir) / f"{pid}.yaml"
        try:
            raw[p] = p.read_bytes()
        except FileNotFoundError:
            raise KeyError(pid) from None
        h.update(raw[p])
    return h.hexdigest(), raw


def flow_hash(flow_path, pages_dir):
    """Approval covers the flow and only the page schemas it uses (Rule 11)."""
    return read_bound(flow_path, pages_dir)[0]


class Approvals:
    """approved-flows and approved-destinations lists, persisted locally.
    Every read re-reads the file; every write is read-modify-write under a file lock."""

    def __init__(self, path):
        self.path = Path(path)

    def snapshot(self):
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            data = {}
        return {"flows": data.get("flows", {}), "destinations": data.get("destinations", {})}

    def flow_ok(self, flow_id, digest):
        return self.snapshot()["flows"].get(flow_id) == digest

    def destination_ok(self, flow_id, org):
        return org in self.snapshot()["destinations"].get(flow_id, [])

    def approve_flow(self, flow_id, digest):
        self._update(lambda d: d["flows"].__setitem__(flow_id, digest))

    def approve_destination(self, flow_id, org):
        self._update(lambda d: d["destinations"].setdefault(flow_id, []).append(org))

    def revoke_flow(self, flow_id):
        self._update(lambda d: d["flows"].pop(flow_id, None))

    def revoke_destination(self, flow_id, org):
        self._update(lambda d: d["destinations"].get(flow_id, []).remove(org) if self._has(d, flow_id, org) else None)

    def revoke_all(self):
        self._update(lambda d: (d["flows"].clear(), d["destinations"].clear()))

    @staticmethod
    def _has(d, flow_id, org):
        return org in d["destinations"].get(flow_id, [])

    def _update(self, mutate):
        with open(self.path.with_name("approvals.lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.snapshot()
            mutate(data)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".approvals.")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp, self.path)
            except BaseException:
                os.unlink(tmp)
                raise
