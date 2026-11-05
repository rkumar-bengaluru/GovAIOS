"""Pure policy decisions (no screen or OS access, so unit-testable)."""
from urllib.parse import urlsplit

RISK_ORDER = ["read", "navigate", "modify", "submit", "payment"]


def origin(url):
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


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
