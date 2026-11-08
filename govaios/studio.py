"""Studio, first piece: a Web Sandbox capture becomes a draft page schema and a read-only "Check" app.

The draft page is the reusable unit: any bigger flow uses it by its page id, and that flow's approval binds the
page's bytes (approvals.read_bound). The Check app only opens the page and identifies it, so the admin can confirm
the draft against the live site before linking it into a bigger flow. Both are written as Drafts (never approved).
Page text is untrusted: it only ever becomes quoted YAML strings (safe_dump) and slugged ids, never code.
Risks are conservative: every button is submit until the admin or Claude lowers it.
"""
import re
from datetime import date
from pathlib import Path
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


# ---------- composing a bigger flow from draft pages ----------

MAX_STEPS = 20
CLICKABLE = ("read", "navigate", "modify")   # submit-rated elements stay the admin's: never composed into a click


def catalogue(flows_dir, pages_dir):
    """Draft pages ready to compose with: each has its Check app (the start URL and browser). {page id: info}."""
    out = {}
    for f in sorted(Path(flows_dir).glob("check_*.yaml")):
        try:
            wf = yaml.safe_load(f.read_text())["workflow"]
            pid = wf["id"].removeprefix("check_")
            url = next(s["value"] for s in wf["steps"] if s["id"] == "open_page")
            page = yaml.safe_load((Path(pages_dir) / f"{pid}.yaml").read_text())["page"]
        except Exception:   # unreadable or not a Check app: not offered
            continue
        out[pid] = {"url": url, "browser": wf["browser"], "title": wf.get("app", pid).removeprefix("Check "),
                    "elements": {k: (s.get("role"), s.get("name") or s.get("dom_id") or k, s.get("risk"))
                                 for k, s in page["elements"].items()}}
    return out


def compose(app, steps, cat):
    """A draft flow from steps over draft pages, or ValueError naming what is wrong. Steps:
    open:<page>  (the first opens its URL; later ones wait for a page a click led to)
    click:<page>.<element>  (on the page last opened; never a submit-rated element)
    fill:<page>  (fill its form from the answer bank, fix cards on failures)
    review  (hand over: the admin checks and submits in Chrome, then Next)"""
    name = " ".join(str(app).split())[:40]
    fid = "studio_" + _slug(name, 40)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", name) or fid == "studio_":
        raise ValueError("give the app a name (letters, digits, spaces)")
    steps = [s for s in steps if s]
    if not steps or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"between 1 and {MAX_STEPS} steps")
    out, here, allow, risks, origins, browser = [], None, {"launch_application", "navigate", "read_page"}, [], [], None
    for i, s in enumerate(steps, 1):
        kind, _, arg = s.partition(":")
        pid, _, el = arg.partition(".")
        if kind in ("open", "click", "fill") and pid not in cat:
            raise ValueError(f"step {i}: no draft page {pid!r}")
        if kind == "open":
            info = cat[pid]
            if i == 1:
                browser = info["browser"]
                out.append({"id": "open_start", "action": "navigate", "value": info["url"]})
            if (o := _origin(info["url"])) not in origins:
                origins.append(o)
            out.append({"id": f"s{i}_on_{pid}"[:64], "action": "classify_page",
                        "on_match": {pid: "continue", "unknown": "stop_and_report"}})
            here = pid
        elif i == 1:
            raise ValueError("step 1 must open a page")
        elif kind in ("click", "fill") and pid != here:
            raise ValueError(f"step {i}: open {pid} first (the run is on {here})")
        elif kind == "click":
            spec = cat[pid]["elements"].get(el)
            if spec is None:
                raise ValueError(f"step {i}: {pid} has no element {el!r}")
            if spec[2] not in CLICKABLE:
                raise ValueError(f"step {i}: {el} is rated {spec[2]}: that click stays yours")
            out.append({"id": f"s{i}_click_{el}"[:64], "action": "click", "target": f"{pid}.{el}"})
            allow.add("click")
            risks.append(spec[2])
        elif kind == "fill":
            out.append({"id": f"s{i}_fill"[:64], "action": "fill_form"})
            allow |= {"fill_field", "ask_admin"}
        elif kind == "review":
            out.append({"id": f"s{i}_review", "action": "hand_over"})
            allow.add("ask_admin")
        else:
            raise ValueError(f"step {i}: unknown step {s!r}")
    order = ["read", "navigate", "modify"]
    return {"workflow": {
        "id": fid, "app": name, "name": f"{name} (composed in Studio from draft pages)", "version": 1,
        "site_terms": {"reviewed": date.today().isoformat(),
                       "basis": "Composed in Studio from Web Sandbox drafts: the admin checked each site's terms"},
        "browser": dict(browser),
        "permissions": {"allow": sorted(allow), "max_element_risk": max(risks or ["navigate"], key=order.index)},
        "destinations": ["https://www.google.com", *origins],
        "steps": [
            {"id": "launch_chrome", "action": "launch_application"},
            {"id": "open_google", "action": "navigate", "value": "https://www.google.com"},
            {"id": "on_google", "action": "classify_page", "on_match": {"google_home": "continue", "unknown": "stop_and_report"}},
            {"id": "verify_account", "action": "verify_account", "target": "google_home.account_button"},
            *out]}}


def _origin(url):
    u = urlsplit(url)
    return f"{u.scheme}://{u.netloc}"


def write_composed(flows_dir, flow):
    """Save a composed flow as a Draft app (exclusive: an existing app of that name is never replaced)."""
    if Path(flows_dir).is_symlink():
        raise OSError("apps folder is a symlink")
    text = (f"# Composed in Studio {date.today().isoformat()}. A Draft: it runs only after you approve it.\n"
            + yaml.safe_dump(flow, sort_keys=False, allow_unicode=True))
    if not _create(Path(flows_dir) / f"{flow['workflow']['id']}.yaml", text.encode()):
        raise OSError("an app with that name exists")
    return flow["workflow"]["id"]
