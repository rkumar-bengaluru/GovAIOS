import pytest

from govaios.approvals import Approvals
from govaios.policy import decide

FLOW = {"id": "f", "permissions": {"allow": ["navigate", "click"], "max_element_risk": "navigate"},
        "destinations": ["https://himalayas.app"]}
NAV = {"action": "navigate", "risk": "navigate", "destination": "https://himalayas.app/jobs/matches"}


@pytest.fixture
def appr(tmp_path):
    return Approvals(tmp_path / "approvals.json")


def test_unlisted_action_denied(appr):
    assert decide({"action": "delete", "risk": "read"}, FLOW, appr) == "deny"


def test_submit_click_denied(appr):
    assert decide({"action": "click", "risk": "submit"}, FLOW, appr) == "deny"


def test_navigate_click_allowed(appr):
    assert decide({"action": "click", "risk": "navigate"}, FLOW, appr) == "allow"


def test_write_file_not_subject_to_click_ceiling(appr):
    w = {**FLOW, "permissions": {**FLOW["permissions"], "allow": ["write_file"]}}
    assert decide({"action": "write_file", "risk": "modify"}, w, appr) == "allow"


def test_first_contact_asks(appr):
    assert decide(NAV, FLOW, appr) == "ask"


def test_destination_remembered(appr, tmp_path):
    appr.approve_destination("f", "https://himalayas.app")
    assert decide(NAV, FLOW, Approvals(tmp_path / "approvals.json")) == "allow"


def test_undeclared_destination_denied(appr):
    assert decide({**NAV, "destination": "https://evil.example/x"}, FLOW, appr) == "deny"


def test_lookalike_domain_denied(appr):
    assert decide({**NAV, "destination": "https://himalayas.app.evil.example/"}, FLOW, appr) == "deny"


def test_payment_always_asks(appr):
    pay = {"permissions": {"allow": ["click"], "max_element_risk": "payment"}, "id": "p"}
    assert decide({"action": "click", "risk": "payment"}, pay, appr) == "ask"
