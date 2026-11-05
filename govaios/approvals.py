"""Remembered approvals: approved flows (by hash) and approved destinations."""
import hashlib
import json
from pathlib import Path


def flow_hash(flow_path, page_paths):
    """Approval covers the flow and every page schema it relies on (Rule 11)."""
    h = hashlib.sha256()
    for p in [flow_path, *sorted(page_paths)]:
        h.update(Path(p).read_bytes())
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
