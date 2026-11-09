"""Studio: a Web Sandbox capture becomes a draft page schema (its start link kept in a header comment).

The draft page is the reusable unit: any bigger flow uses it by its page id, and that flow's approval binds the
page's bytes (approvals.read_bound). It is written as a Draft (never approved).
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


def _ident(n):
    return ("dom_id", _id(n)) if _id(n) else ("name", n.get("name") or "")


def _spec(nodes, n, **extra):
    """The locator for capture-tree node n: its stable id, else its name; `index` (its rank among the nodes with
    the same role and ident) when that attribute alone matches more than once."""
    ident = _ident(n)
    s = {"role": n["role"], ident[0]: ident[1], **extra}
    if sum(1 for m in nodes if m["role"] == n["role"] and (m.get(ident[0]) or "") == ident[1]) > 1:
        same = [m for m in nodes if m["role"] == n["role"] and _ident(m) == ident]
        s["index"] = next(i for i, m in enumerate(same) if m is n)   # by identity: equal sibling dicts are distinct
    return s


def element_spec(tree, node):
    """draft_page's locator for one node of a capture tree, or None unless it finds exactly that node."""
    from . import engine   # engine imports studio
    if not (_id(node) or node.get("name")):
        return None   # nothing stable to find it by
    spec = _spec(list(_walk(tree)), node)
    root, made = _as_nodes(tree)
    found = engine.find_all(root, spec, {"elements": {}})
    return spec if len(found) == 1 and found[0] is made[id(node)] else None


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

    def spec_for(n, **extra):
        return _spec(nodes, n, **extra)

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
    _add_items(tree, nodes, elements, add)
    title = tree.get("name") or ""
    ident = {"title_matches": f"^{re.escape(title)}$" if title else "."}
    anchors = [a for a in anchors if a and "fields" not in elements[a]][:2] or [
        k for k in elements if "fields" not in elements[k]][:1]
    if anchors:
        ident["anchors"] = anchors
    return {"page": {"id": page_id, "identification": ident, "elements": elements}}


def _repeats(nodes):
    """(parent, items): 3+ sibling nodes with the same shape (role and the roles inside) that each hold a named
    link: job cards, table rows, result items. Largest first, at most 3 groups."""
    out = []
    for p in nodes:
        groups = {}
        for c in p.get("children", []):
            inside = list(_walk(c))
            if any(d["role"] == "link" and d.get("name") for d in inside[1:]):
                groups.setdefault((c["role"], frozenset(d["role"] for d in inside[1:])), []).append(c)
        best = max(groups.values(), key=len, default=[])
        if len(best) >= 3:
            out.append((p, best))
    return sorted(out, key=lambda g: -len(g[1]))[:3]


def _as_nodes(tree):
    """The Node tree for a capture tree, and {id(dict): its Node}."""
    from .desktop import Node
    made = {}

    def node(d):
        n = Node(d["role"], d.get("name", ""), d.get("value", ""), d.get("dom_id", ""), tuple(d.get("dom_class", [])),
                 [node(c) for c in d.get("children", [])])
        made[id(d)] = n
        return n
    return node(tree), made


def _add_items(tree, nodes, elements, add):
    """A repeated-item element for each group, only when its spec finds exactly that group's items."""
    from . import engine   # engine imports studio
    root, made = _as_nodes(tree)
    for n, (parent, items) in enumerate(_repeats(nodes), 1):
        same = [m for m in nodes if m["role"] == parent["role"] and _id(m) == _id(parent)
                and (_id(parent) or (m.get("name") or "") == (parent.get("name") or ""))]
        cont = {"role": parent["role"], **({"dom_id": _id(parent)} if _id(parent) else {"name": parent.get("name") or ""}),
                "risk": "read"}
        if len(same) > 1:
            cont["index"] = next(i for i, m in enumerate(same) if m is parent)
        fields = {"link": {"role": "link", "index": 0, "risk": "navigate"}}
        if all(any(d["role"] == "text" and (d.get("value") or d.get("name")) for d in _walk(c)) for c in items):
            fields["label"] = {"role": "text", "index": 0, "risk": "read"}
        trial = dict(elements)
        ck = f"list_{n}"
        trial[ck] = cont
        if ck in elements:
            continue
        spec = {"role": items[0]["role"], "has": {"role": "link"}, "within": ck, "direct": True, "risk": "read",
                "fields": fields}
        found = engine.find_all(root, spec, {"elements": trial})
        if [id(x) for x in found] != [id(made[id(c)]) for c in items]:
            continue   # the spec would also catch other nodes (or miss some): not offered
        add(ck, cont)
        add(f"items_{n}", spec)


def write_draft(flows_dir, pages_dir, tree, url, browser, capture_name):
    """Write the draft page (exclusive, never overwriting). Returns the page id."""
    for d in (flows_dir, pages_dir):
        if d.is_symlink():
            raise OSError("apps folder is a symlink")
    host = _slug(urlsplit(url).hostname or "site", 24)
    base = f"{host}_{_slug(tree.get('name') or 'page', 30)}".strip("_")[:56]
    for i in range(1, 100):
        pid = base if i == 1 else f"{base}_{i}"
        if not (pages_dir / f"{pid}.yaml").exists():
            break
    else:
        raise OSError("no free draft name")
    page = draft_page(tree, pid)
    u = urlsplit(url)
    head = (f"# Draft from the Web Sandbox capture {capture_name} ({date.today().isoformat()}). Review before use:\n"
            f"# Start link: {u.scheme}://{(u.hostname or '').lower()}{f':{u.port}' if u.port else ''}{u.path or '/'}\n"   # no userinfo, query or fragment: they can hold secrets
            "# every button is rated submit until lowered; names are as the page showed them.\n")
    if not _create(pages_dir / f"{pid}.yaml", (head + yaml.safe_dump(page, sort_keys=False, allow_unicode=True)).encode()):
        raise OSError("draft page exists")
    return pid


# ---------- composing a bigger flow from draft pages ----------

MAX_STEPS = 20
CLICKABLE = ("read", "navigate", "modify")   # submit-rated elements stay the admin's: never composed into a click


def find_browser(flows_dir, ok=lambda wf: True):
    """The browser block (application, profile, account) of the first flow in the folder that has a full one and
    passes ok(workflow): the panel has no other source for it. None if there is none."""
    for f in sorted(Path(flows_dir).glob("*.yaml")):
        try:
            wf = yaml.safe_load(f.read_text())["workflow"]
            b = wf["browser"]
            if b["application"] and b["profile_directory"] and b["account"] and ok(wf):
                return dict(b)
        except Exception:
            continue
    return None


def catalogue(flows_dir, pages_dir, browser=...):
    """Draft pages (with a Start link header, or an old Check app) ready to compose with. {page id: info}. The browser block is
    copied from an existing flow, as new_automation does."""
    browser = find_browser(flows_dir) if browser is ... else browser   # an explicit None: no browser to copy
    out = {}
    for f in sorted(Path(pages_dir).glob("*.yaml")):
        try:
            text = f.read_text()
            m = re.search(r"^# Start link: (\S+)$", text, re.M)
            if m:
                url = m[1]
            else:   # a draft from before Check apps went: its start link is in its Check app
                chk = yaml.safe_load((Path(flows_dir) / f"check_{f.stem}.yaml").read_text())["workflow"]
                url = next(x["value"] for x in chk["steps"] if x["id"] == "open_page")
            page = yaml.safe_load(text)["page"]
        except Exception:   # not a Studio draft page, or unreadable: not offered
            continue
        pid = f.stem
        out[pid] = {"url": url, "browser": browser, "title": pid,
                    "elements": {k: (s.get("role"), s.get("name") or s.get("dom_id") or k, s.get("risk"))
                                 for k, s in page["elements"].items() if "fields" not in s},
                    "items": {k: dict(s["fields"]) for k, s in page["elements"].items()
                              if isinstance(s.get("fields"), dict) and "link" in s["fields"]}}
    return out


def compose(app, steps, cat):
    """A draft flow from steps over draft pages, or ValueError naming what is wrong. Steps:
    open:<page>  (the first opens its URL; later ones wait for a page a click led to)
    click:<page>.<element>  (on the page last opened; never a submit-rated element)
    fill:<page>  (fill its form from the answer bank, fix cards on failures)
    review  (hand over: the admin checks and submits in Chrome, then Next)
    each:<page>.<items>  (for each repeated item on the page last opened, up to 10: one panel task per item,
                          each in its own tab; the steps up to end_each run per item)
    click_item  (inside each: click the item's link)
    end_each"""
    name = " ".join(str(app).split())[:40]
    fid = "studio_" + _slug(name, 40)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", name) or fid == "studio_":
        raise ValueError("give the app a name (letters, digits, spaces)")
    steps = [s for s in steps if s]
    if not steps or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"between 1 and {MAX_STEPS} steps")
    out, here, allow, risks, origins, browser = [], None, {"launch_application", "navigate", "read_page"}, [], [], None
    top, loop = out, None
    for i, s in enumerate(steps, 1):
        kind, _, arg = s.partition(":")
        pid, _, el = arg.partition(".")
        if kind in ("open", "click", "fill", "each") and pid not in cat:
            raise ValueError(f"step {i}: no draft page {pid!r}")
        if kind in ("click_item", "end_each", "review") and arg:
            raise ValueError(f"step {i}: unknown step {s!r}")
        if kind == "open":
            info = cat[pid]
            if i == 1:
                if not info["browser"]:
                    raise ValueError("no app with a browser profile to copy: set one up first")
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
        elif kind == "each":
            if loop is not None:
                raise ValueError(f"step {i}: end the first for each before another")
            if pid != here:
                raise ValueError(f"step {i}: open {pid} first (the run is on {here})")
            if el not in cat[pid]["items"]:
                raise ValueError(f"step {i}: {pid} has no repeated items {el!r}")
            inner = [{"id": f"s{i}_tab", "action": "new_tab"},   # each item in its own tab, its form kept as left
                     {"id": f"s{i}_list", "action": "navigate", "value": cat[pid]["url"]},
                     {"id": f"s{i}_on_list", "action": "classify_page",
                      "on_match": {pid: "continue", "unknown": "stop_and_report"}}]
            out.append({"id": f"s{i}_pick", "action": "select_items", "target": f"{pid}.{el}", "count": 10,
                        "none": "no items on the page"})
            out.append({"id": f"s{i}_each", "action": "for_each_item", "task_title": ["link"], "steps": inner})
            out, loop = inner, pid
        elif kind == "click_item":
            if loop is None or here != loop:
                raise ValueError(f"step {i}: click the item only inside a for each, on its list page")
            out.append({"id": f"s{i}_click_item", "action": "click", "target": "current_item.link"})
            allow.add("click")
            risks.append("navigate")
            here = None   # until the next Open says where the click led
        elif kind == "end_each":
            if loop is None:
                raise ValueError(f"step {i}: no for each to end")
            out, loop, here = top, None, None
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


def new_automation(flows_dir, name, url, browser):
    """An empty Draft app that opens `url` and stops on its (unknown) start page, where `teach` lets the admin
    teach it. Written exclusively. ValueError for a bad name, link or missing browser block."""
    from . import lessons   # imports studio
    name = " ".join(str(name).split())[:40]
    fid = "studio_" + _slug(name, 40)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", name) or fid == "studio_":
        raise ValueError("give the app a name (letters, digits, spaces)")
    if not browser:
        raise ValueError("no approved app with a browser profile to copy: set one up first")
    try:
        u = urlsplit(url.strip())
        local = u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1") and not (u.username or u.password)
        site = f"http://{u.hostname}" + (f":{u.port}" if u.port else "") if local else lessons._site(url.strip())
    except ValueError as e:
        raise ValueError(f"the starting link must be https (or http://localhost): {e}"[:200]) from None
    flow = {"workflow": {
        "id": fid, "app": name, "name": f"{name} (new automation from Studio: teach it from its start page)",
        "version": 1,
        "site_terms": {"reviewed": date.today().isoformat(),
                       "basis": "Started in Studio: the admin checks the site's terms before teaching it"},
        "browser": dict(browser),
        "permissions": {"allow": ["launch_application", "navigate", "read_page", "click", "fill_field", "ask_admin",
                                  "attach_file", "teach"], "max_element_risk": "modify"},
        "destinations": ["https://www.google.com", site],
        "steps": [
            {"id": "launch_chrome", "action": "launch_application"},
            {"id": "open_google", "action": "navigate", "value": "https://www.google.com"},
            {"id": "on_google", "action": "classify_page", "on_match": {"google_home": "continue", "unknown": "stop_and_report"}},
            {"id": "verify_account", "action": "verify_account", "target": "google_home.account_button"},
            {"id": "open_start", "action": "navigate", "value": site + (u.path or "/")},
            {"id": "on_start", "action": "classify_page", "on_match": {"unknown": "stop_and_report"}},
        ]}}
    if Path(flows_dir).is_symlink():
        raise OSError("apps folder is a symlink")
    path = Path(flows_dir) / f"{fid}.yaml"
    text = (f"# Started in Studio {date.today().isoformat()}. A Draft: it runs only after you approve it.\n"
            + yaml.safe_dump(flow, sort_keys=False, allow_unicode=True))
    if not _create(path, text.encode()):
        raise OSError("an app with that name exists")
    return path
