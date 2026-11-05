"""run: .venv/bin/python test_governance.py"""
import tempfile
from pathlib import Path

from governance import Approvals, decide

FLOW = {"id": "f", "permissions": {"allow": ["navigate", "click"], "max_element_risk": "navigate"},
        "destinations": ["https://himalayas.app"]}

with tempfile.TemporaryDirectory() as d:
    a = Approvals(Path(d) / "approvals.json")
    assert decide({"action": "delete", "risk": "read"}, FLOW, a) == "deny"           # not allowed
    assert decide({"action": "click", "risk": "submit"}, FLOW, a) == "deny"          # Save job / Apply
    assert decide({"action": "click", "risk": "navigate"}, FLOW, a) == "allow"
    w = {**FLOW, "permissions": {**FLOW["permissions"], "allow": ["write_file"]}}
    assert decide({"action": "write_file", "risk": "modify"}, w, a) == "allow"       # ceiling is for clicks
    nav = {"action": "navigate", "risk": "navigate", "destination": "https://himalayas.app/jobs/matches"}
    assert decide(nav, FLOW, a) == "ask"                                              # first contact
    a.approve_destination("f", "https://himalayas.app")
    assert decide(nav, FLOW, Approvals(Path(d) / "approvals.json")) == "allow"        # remembered
    assert decide({**nav, "destination": "https://evil.example/x"}, FLOW, a) == "deny"  # undeclared
    assert decide({**nav, "destination": "https://himalayas.app.evil.example/"}, FLOW, a) == "deny"
    pay = {"permissions": {"allow": ["click"], "max_element_risk": "payment"}, "id": "p"}
    assert decide({"action": "click", "risk": "payment"}, pay, a) == "ask"           # Rule 4
print("governance tests passed")
