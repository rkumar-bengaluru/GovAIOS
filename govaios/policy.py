"""Pure policy decisions (no screen or OS access, so unit-testable)."""
import re
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
CLAUDE_IDX = 4  # position of ~/.claude in executor.protected_paths()
# a `.claude` path segment or `.mcp.json` in casefolded command or pattern text: Claude Code config at any depth
_CONFIG_TEXT = re.compile(r"(?:^|[\s/'\"=])\.claude(?:$|[\s/'\"])|\.mcp\.json")


def _inside(p, d, fold=False):
    if fold:
        p, d = p.casefold(), d.casefold()    # APFS is case-insensitive: protection must be too
    return p == d or p.startswith(d.rstrip("/") + "/")


def _memory_md(p, claude):
    """~/.claude/projects/<name>/memory/**/*.md (row 16 carve-out); p is already a realpath."""
    p, claude = p.casefold(), claude.casefold()
    parts = p[len(claude) + 1:].split("/") if p.startswith(claude + "/") else []
    return len(parts) >= 4 and parts[0] == "projects" and parts[2] == "memory" and p.endswith(".md")


def _nested_config(path, roots):
    """A realpath under a root with a `.claude` component, or ending in `.mcp.json`, at any depth (casefolded):
    a session started in that subfolder would load it."""
    p = path.casefold()
    for r in roots:
        r = r.casefold().rstrip("/")
        if p.startswith(r + "/"):
            parts = p[len(r) + 1:].split("/")
            if ".claude" in parts or parts[-1] == ".mcp.json":
                return True
    return False


def _fetch_host(url):
    """Host of a plain https URL, or None. Strict, so every URL parser agrees on the host."""
    if not url or "\\" in url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        return None
    try:
        u = urlsplit(url)
        host = u.netloc.lower()
        if u.scheme != "https" or not host or (u.hostname or "").lower() != host:
            return None                                       # userinfo or port
    except ValueError:
        return None
    return host


def decide_tool(request, policy, approvals, protected, config=()):
    """Return 'allow', 'deny' or 'ask' for one Claude tool call. Pure: paths arrive realpathed.
    `config`: project Claude Code config paths, denied for every tool and in any command (no carve-out, no ask)."""
    cat, tool, path = request.get("category"), request.get("tool"), request.get("path")
    if path is not None and (any(_inside(path, q, True) for q in config)
                             or _nested_config(path, policy.get("project_roots", []))):
        return "deny"
    if cat == "shell":
        low = (request.get("command") or "").casefold()
        if any(q.casefold() in low for q in config) or _CONFIG_TEXT.search(low):
            return "deny"
    if _CONFIG_TEXT.search((request.get("pattern") or "").casefold()):   # Glob pattern, Grep file filter
        return "deny"
    memory = False
    if path is not None:
        memory = tool in ("Read", "Edit", "Write") and _memory_md(path, protected[CLAUDE_IDX])
        if not memory and any(_inside(path, q, True) for q in protected):
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
        pat = request.get("pattern") or ""
        if tool == "Glob" and (pat.startswith(("/", "~")) or ".." in pat.split("/")
                              or any(b in pat for b in ("{/", ",/", "{~", ",~"))):
            return "deny"
        if memory or any(_inside(path, r) for r in policy.get("project_roots", [])):
            return "allow"
        return "ask" if cat == "read" else "deny"
    if cat == "shell":
        cmd = request.get("command")
        if cmd is None:
            return "deny"
        low = cmd.casefold()
        touchy = any("~" in a or ".." in a.split("/") for a in low.split()) or any(q.casefold() in low for q in protected)
        if not touchy and not _META.intersection(cmd) and any(
                cmd == c or cmd.startswith(c + " ") for c in policy.get("allow_commands", [])):
            return "allow"
        return "ask"
    if cat == "fetch":
        host = _fetch_host(request.get("url"))
        if host is None or host not in {d.lower() for d in policy.get("destinations", [])}:
            return "deny"
        return "allow" if approvals.destination_ok("claude_code", f"https://{host}") else "ask"
    return "deny"
