"""Governance layer (spike): pure policy decisions plus the remembered approvals.
No screen or OS access here, so it is unit-testable (test_governance.py)."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

RISK_ORDER = ["read", "navigate", "modify", "submit", "payment"]


def origin(url):
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def flow_hash(flow_path, page_paths):
    """Approval covers the flow and every page schema it relies on (Rule 11)."""
    h = hashlib.sha256()
    for p in [flow_path, *sorted(page_paths)]:
        h.update(Path(p).read_bytes())
    return h.hexdigest()


def decide(request, flow, approvals):
    """Return 'allow', 'deny' or 'ask' for one action request.
    request: {action, risk, destination?}; flow: parsed flow yaml; approvals: Approvals."""
    perms = flow["permissions"]
    if request["action"] not in perms["allow"]:
        return "deny"                                     # Rule 9: unlisted = denied
    if request["action"] == "click" and \
            RISK_ORDER.index(request["risk"]) > RISK_ORDER.index(perms["max_element_risk"]):
        return "deny"                                     # README §7: element risk ceiling
    if request["risk"] == "payment":
        return "ask"                                      # Rule 4: always, never remembered
    dest = request.get("destination")
    if dest:
        if origin(dest) not in {origin(d) for d in flow.get("destinations", [])}:
            return "deny"                                 # undeclared destination
        if not approvals.destination_ok(flow["id"], origin(dest)):
            return "ask"                                  # Rule 11: first contact
    return "allow"


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
