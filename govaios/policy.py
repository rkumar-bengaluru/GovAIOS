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


_META = set(";&|$`<>()\n")


def _inside(p, d):
    return p == d or p.startswith(d.rstrip("/") + "/")


def _memory_md(p, claude):
    """~/.claude/projects/<name>/memory/**/*.md (row 16 carve-out); p is already a realpath."""
    parts = p[len(claude) + 1:].split("/") if p.startswith(claude + "/") else []
    return len(parts) >= 4 and parts[0] == "projects" and parts[2] == "memory" and p.endswith(".md")


def decide_tool(request, policy, approvals, protected):
    """Return 'allow', 'deny' or 'ask' for one Claude tool call. Pure: paths arrive realpathed."""
    cat, tool, path = request.get("category"), request.get("tool"), request.get("path")
    memory = False
    if path is not None:
        memory = request["tool"] in ("Read", "Edit", "Write") and any(
            _memory_md(path, q) for q in protected if q.endswith("/.claude"))
        if not memory and any(_inside(path, q) for q in protected):
            return "deny"
    if cat is None or tool not in policy.get("tools", []):
        return "deny"                                     # Rule 9
    if cat in ("internal", "delegate", "search"):
        return "allow"
    if cat == "external":
        return "ask"
    if cat in ("read", "write"):
        if path is None:
            return "deny"
        if memory or any(_inside(path, r) for r in policy.get("project_roots", [])):
            return "allow"
        return "ask" if cat == "read" else "deny"
    if cat == "shell":
        cmd = request.get("command")
        if cmd is None:
            return "deny"
        if not _META.intersection(cmd) and any(
                cmd == c or cmd.startswith(c + " ") for c in policy.get("allow_commands", [])):
            return "allow"
        return "ask"
    if cat == "fetch":
        u = urlsplit(request.get("url") or "")
        host = (u.hostname or "").lower()
        if u.scheme != "https" or host not in {d.lower() for d in policy.get("destinations", [])}:
            return "deny"
        return "allow" if approvals.destination_ok("claude_code", f"https://{host}") else "ask"
    return "deny"
