"""Studio, first piece: a Web Sandbox capture becomes a draft page schema and a read-only "Check" app.

The draft page is the reusable unit: any bigger flow uses it by its page id, and that flow's approval binds the
page's bytes (approvals.read_bound). The Check app only opens the page and identifies it, so the admin can confirm
the draft against the live site before linking it into a bigger flow. Both are written as Drafts (never approved).
Page text is untrusted: it only ever becomes quoted YAML strings (safe_dump) and slugged ids, never code.
Risks are conservative: every button is submit until the admin or Claude lowers it.
"""
import re
from datetime import date
from urllib.parse import urlsplit

import yaml

from .formfill import FIELD_ROLES
from .panel.market import _create

MAX_LINKS = 40
MAX_ELEMENTS = 200


def _slug(text, n=40):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:n].strip("_")


# ids a framework makes up per page load (React useId, react-select, Radix, Headless UI): never stable anchors
_VOLATILE = re.compile(r"^:|\u00ab|^react-select-\d|^radix-|^headlessui-|^mui-\d|^[0-9a-f]{8}-[0-9a-f]{4}-")


def _id(n):
    d = n.get("dom_id") or ""
    return d if d and not _VOLATILE.search(d) else ""


def _walk(n):
    yield n
    for c in n.get("children", []):
        yield from _walk(c)


def draft_page(tree, page_id):
    """Page schema dict for a capture tree (capture.tree form): identification + headings, fields, buttons, links.
    An element whose spec matches more than once gets its index, so each resolves to exactly one node."""
    nodes = list(_walk(tree))
    elements = {}

    def add(base, spec):
        if len(elements) >= MAX_ELEMENTS:
            return None
        key = _slug(base) or spec["role"]
        k, i = key, 2
        while k in elements:
            k, i = f"{key}_{i}", i + 1
        elements[k] = spec
        return k

    seen = {}

    def spec_for(n, **extra):
        ident = ("dom_id", _id(n)) if _id(n) else ("name", n.get("name") or "")
        sig = (n["role"], ident)
        seen[sig] = seen.get(sig, -1) + 1
        s = {"role": n["role"], ident[0]: ident[1], **extra}
        total = sum(1 for m in nodes if m["role"] == n["role"] and (m.get(ident[0]) or "") == ident[1])
        if total > 1:
            s["index"] = seen[sig]
        return s

    headings = [n for n in nodes if n["role"] == "heading" and n.get("name")][:5]
    anchors = [add("heading " + n["name"], spec_for(n, risk="read")) for n in headings]
    for n in nodes:
        if n["role"] in FIELD_ROLES and (_id(n) or n.get("name")):
            add(n.get("name") or _id(n), spec_for(n, risk="modify"))
    for n in nodes:
        if n["role"] == "button" and n.get("name") and len(n["name"]) <= 120:
            add("button " + n["name"], spec_for(n, risk="submit"))
    for n in [n for n in nodes if n["role"] == "link" and n.get("name") and len(n["name"]) <= 120][:MAX_LINKS]:
        add("link " + n["name"], spec_for(n, risk="navigate"))
    title = tree.get("name") or ""
    ident = {"title_matches": f"^{re.escape(title)}$" if title else "."}
    anchors = [a for a in anchors if a][:2] or list(elements)[:1]
    if anchors:
        ident["anchors"] = anchors
    return {"page": {"id": page_id, "identification": ident, "elements": elements}}


def draft_check_flow(page_id, url, browser, title):
    """A read-only app that opens the captured page and identifies it with the draft page."""
    u = urlsplit(url)
    site = f"{u.scheme}://{u.netloc}"
    name = " ".join(re.sub(r"[^A-Za-z0-9 ]+", " ", title).split())[:40] or page_id
    return {"workflow": {
        "id": f"check_{page_id}", "app": f"Check {name}",
        "name": f"Check the draft page {page_id}: open it and identify it",
        "version": 1,
        "site_terms": {"reviewed": date.today().isoformat(),
                       "basis": "Drafted from the Web Sandbox: the admin checked this site's terms before capturing it"},
        "browser": dict(browser),
        "permissions": {"allow": ["launch_application", "navigate", "read_page"], "max_element_risk": "read"},
        "destinations": ["https://www.google.com", site],
        "steps": [
            {"id": "launch_chrome", "action": "launch_application"},
            {"id": "open_google", "action": "navigate", "value": "https://www.google.com"},
            {"id": "on_google", "action": "classify_page", "on_match": {"google_home": "continue", "unknown": "stop_and_report"}},
            {"id": "verify_account", "action": "verify_account", "target": "google_home.account_button"},
            {"id": "open_page", "action": "navigate", "value": site + (u.path or "/")},   # never the query: it can hold tokens
            {"id": "on_page", "action": "classify_page", "on_match": {page_id: "continue", "unknown": "stop_and_report"}},
        ]}}


def write_draft(flows_dir, pages_dir, tree, url, browser, capture_name):
    """Write the draft page and its Check app (exclusive, never overwriting). Returns the page id."""
    for d in (flows_dir, pages_dir):
        if d.is_symlink():
            raise OSError("apps folder is a symlink")
    host = _slug(urlsplit(url).hostname or "site", 24)
    base = f"{host}_{_slug(tree.get('name') or 'page', 30)}".strip("_")[:56]
    for i in range(1, 100):
        pid = base if i == 1 else f"{base}_{i}"
        if not (pages_dir / f"{pid}.yaml").exists() and not (flows_dir / f"check_{pid}.yaml").exists():
            break
    else:
        raise OSError("no free draft name")
    page = draft_page(tree, pid)
    head = (f"# Draft from the Web Sandbox capture {capture_name} ({date.today().isoformat()}). Review before use:\n"
            "# every button is rated submit until lowered; names are as the page showed them.\n")
    if not _create(pages_dir / f"{pid}.yaml", (head + yaml.safe_dump(page, sort_keys=False, allow_unicode=True)).encode()):
        raise OSError("draft page exists")
    flow = draft_check_flow(pid, url, browser, tree.get("name") or "")
    if not _create(flows_dir / f"check_{pid}.yaml", yaml.safe_dump(flow, sort_keys=False, allow_unicode=True).encode()):
        (pages_dir / f"{pid}.yaml").unlink()
        raise OSError("draft flow exists")
    return pid
