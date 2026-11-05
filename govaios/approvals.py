"""Remembered approvals: approved flows (by hash) and approved destinations."""
import hashlib
import json
from pathlib import Path

import yaml


def pages_used(flow):
    """Every page id a flow's steps reference, recursing into nested steps."""
    ids = set()

    def walk(steps):
        for s in steps:
            t = s.get("target", "").split(".")[0]
            if t and t != "current_item":
                ids.add(t)
            ids.update(s[k] for k in ("page", "verify_page") if k in s)
            ids.update(k for k in s.get("on_match", {}) if k != "unknown")
            walk(s.get("steps", []))

    walk(flow["steps"])
    return ids


def flow_hash(flow_path, pages_dir):
    """Approval covers the flow and only the page schemas it uses (Rule 11)."""
    flow = yaml.safe_load(Path(flow_path).read_text())["workflow"]
    h = hashlib.sha256(Path(flow_path).read_bytes())
    for pid in sorted(pages_used(flow)):
        try:
            h.update((Path(pages_dir) / f"{pid}.yaml").read_bytes())
        except FileNotFoundError:
            raise KeyError(pid) from None
    return h.hexdigest()


class Approvals:
    """approved-flows and approved-destinations lists, persisted locally."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            self.data = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.data = {"flows": {}, "destinations": {}}

    def flow_ok(self, flow_id, digest):
        return self.data["flows"].get(flow_id) == digest

    def approve_flow(self, flow_id, digest):
        self.data["flows"][flow_id] = digest
        self._save()

    def destination_ok(self, flow_id, org):
        return org in self.data["destinations"].get(flow_id, [])

    def approve_destination(self, flow_id, org):
        self.data["destinations"].setdefault(flow_id, []).append(org)
        self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.data, indent=2))
