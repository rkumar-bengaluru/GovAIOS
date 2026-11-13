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


def test_attach_file_always_asks(appr):
    f = {**FLOW, "permissions": {**FLOW["permissions"], "allow": ["attach_file"]}}
    req = {"action": "attach_file", "risk": "modify"}
    assert decide(req, f, appr) == "ask"
    appr.approve_destination("f", "https://himalayas.app")
    assert decide(req, f, appr) == "ask"
    assert decide(req, FLOW, appr) == "deny"   # not allow-listed: deny wins


SUB = {"id": "f", "permissions": {"allow": ["click"], "max_element_risk": "submit"},
       "destinations": ["http://localhost:8100"]}


def _click(risk, dest=None, **k):
    return {"action": "click", "risk": risk, **({"destination": dest} if dest else {}), **k}


def test_payment_click_is_denied_never_asked(appr):
    flow = {**SUB, "permissions": {"allow": ["click"], "max_element_risk": "payment"}}
    assert decide(_click("payment"), flow, appr) == "deny"


def test_submit_click_on_own_app_needs_grant(appr):
    appr.approve_destination("f", "http://localhost:8100")
    d = "http://localhost:8100/discover"
    assert decide(_click("submit", d, granted=False), SUB, appr) == "deny"
    assert decide(_click("submit", d, granted=True), SUB, appr) == "allow"


def test_submit_click_outside_own_apps_is_denied_even_with_grant(appr):
    flow = {**SUB, "destinations": ["https://boards.greenhouse.io"]}
    assert decide(_click("submit", "https://boards.greenhouse.io/x", granted=True), flow, appr) == "deny"


def test_own_url():
    from govaios.policy import own
    assert own("http://127.0.0.1:8100/")
    assert not any(own(u) for u in ("http://127.0.0.1:8765/", "https://localhost.evil.com/", "file:///x"))
