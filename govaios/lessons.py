"""Studio lessons: what the admin did in Chrome, saved, then turned into a PROPOSED change (page files, steps per
page, bank ops) for the admin to review. Nothing here writes flows, pages or the bank.

Dev mode: lessons are NOT masked (values as typed; secure fields are already blank from the observer).
shortcut: unmasked, add masking before this leaves dev. Files are 0600 under <data home>/lessons/, last KEEP per flow.
"""
import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from . import capture, engine, studio
from .formfill import FIELD_ROLES, Field, new_key, normalize, restricted

DIR = "lessons"
KEEP = 30
_NAME = re.compile(r"[0-9-]{22}-[a-z0-9_]{1,64}\.json")
_CODE = re.compile(r"\d{4,8}")


def save(home, flow_id, flow_digest, step_id, pages) -> str:
    """Write one lesson (Observer.pages, Node trees); returns its file name. Never follows a link."""
    if not re.fullmatch(r"[a-z0-9_]{1,64}", flow_id or ""):
        raise ValueError("bad flow id")
    d = Path(home) / DIR
    if d.is_symlink():
        raise OSError("lessons/ is a symlink")
    d.mkdir(mode=0o700, exist_ok=True)

    def url(u):
        s = urlsplit(u)
        return f"{s.scheme}://{s.netloc}{s.path}" if s.scheme else u   # never the query: it can hold tokens
    doc = {"flow": flow_id, "digest": flow_digest, "step": step_id, "at": datetime.now().isoformat(timespec="seconds"),
           "pages": [{"url": url(p["url"]), "title": p["title"], "tree": capture.tree(p["tree"]),
                      "events": p["events"]} for p in pages]}
    name = f"{datetime.now():%Y%m%d-%H%M%S-%f}-{flow_id}.json"
    fd = os.open(d / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=1).encode())
    for old in sorted(p for p in d.iterdir() if p.name.endswith(f"-{flow_id}.json"))[:-KEEP]:
        old.unlink()
    return name


def load(home, name) -> dict:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("bad lesson name")
    d = Path(home) / DIR
    if d.is_symlink():
        raise OSError("lessons/ is a symlink")
    with os.fdopen(os.open(d / name, os.O_RDONLY | os.O_NOFOLLOW), "rb") as f:
        return json.loads(f.read())


def _risk(role):
    if role == "button":
        return "submit"
    if role == "link":
        return "navigate"
    if role in FIELD_ROLES or role == "text_area":
        return "modify"
    if role in ("heading", "text"):
        return "read"
    return "submit"   # any other clickable (a div with a click handler) may submit: conservative, as draft_page


def _known(pages_dir):
    """[(page id, page dict)] for every readable page file."""
    out = []
    for f in sorted(Path(pages_dir).glob("*.yaml")):
        try:
            out.append((f.stem, yaml.safe_load(f.read_text())["page"]))
        except Exception:   # unreadable or not a page: never matched
            continue
    return out


def _key_for(page, root, spec, label):
    """(key, sure): the element key in page that locates spec's node (adding it, risk by role, when none does);
    sure is False when spec does not find exactly one node in the stored tree."""
    els = page["elements"]
    want = [id(n) for n in engine.find_all(root, spec, {"elements": {}})]   # Node is a dataclass: compare identity
    sure = len(want) == 1
    for k, s in els.items():
        if "fields" in s:
            continue
        if {a: b for a, b in s.items() if a != "risk"} == spec:
            return k, sure
        if sure and [id(n) for n in engine.find_all(root, s, page)] == want:
            return k, sure
    base = studio._slug(label) or spec["role"]
    k, i = base, 2
    while k in els:
        k, i = f"{base}_{i}", i + 1
    els[k] = {**spec, "risk": _risk(spec["role"])}
    return k, sure


def _new_id(lp, taken):
    host = studio._slug(urlsplit(lp["url"]).hostname or "site", 24)
    base = f"{host}_{studio._slug(lp['tree'].get('name') or lp.get('title') or 'page', 30)}".strip("_")[:56]
    for i in range(1, 100):
        pid = base if i == 1 else f"{base}_{i}"
        if pid not in taken:
            return pid
    raise OSError("no free page name")


def _keep(value):
    return "drop" if len(value) > 200 or _CODE.fullmatch(value) else "bank"


def propose(lesson, pages_dir, bank) -> dict:
    """The change a lesson proposes. Pure: reads pages_dir, never writes."""
    known = _known(pages_dir)
    taken = {f.stem for f in Path(pages_dir).glob("*.yaml")}   # unreadable files too: never overwritten
    out_pages, ops, keys = [], [], {e.key for e in bank.entries}
    for lp in lesson["pages"]:
        root = studio._as_nodes(lp["tree"])[0]
        hit = next(((pid, p) for pid, p in known if _identifies(p, root)), None)
        if hit:
            pid, page, new = hit[0], copy.deepcopy(hit[1]), False
        else:
            pid = _new_id(lp, taken)
            taken.add(pid)
            page, new = studio.draft_page(lp["tree"], pid)["page"], True
        look = copy.deepcopy(page)   # elements are looked up here, and copied to page only when a step uses them
        if new:
            anchors = page["identification"].get("anchors", [])
            page["elements"] = {k: v for k, v in page["elements"].items() if k in anchors}
        steps, added = [], []
        evs = lp["events"]
        for i, ev in enumerate(evs):
            kind, label, spec = ev["kind"], ev.get("label") or "", ev.get("spec")
            if kind == "click" and i + 1 < len(evs) and evs[i + 1]["kind"] == "attach":
                continue   # the file chooser's own button: the attach covers it
            k, sure = _key_for(look, root, spec, label) if kind in ("click", "attach") and spec else (None, False)
            target = f"{pid}.{k}" if k else None
            line, keep = None, sure and not (kind == "click" and any(s["kind"] == "hand_over" for s in steps))
            text = label + ("" if sure else " (check this target)")   # off until the admin checks it
            if kind == "click" and not k:
                line = {"kind": "click", "label": "not sure what this was", "target": None, "keep": False}
            elif kind == "click" and look["elements"][k].get("risk") == "submit":
                line = {"kind": "hand_over", "label": text, "target": target, "keep": keep}   # replayed as hand over
            elif kind in ("click", "attach"):
                line = {"kind": "click" if kind == "click" else "attach_file", "label": text, "target": target,
                        "keep": keep}   # a click after the hand over is dead: replay stops there
            if line:
                steps.append(line)
                if k:
                    if not new and k not in page["elements"]:
                        added.append(k)
                    page["elements"][k] = look["elements"][k]
            elif kind in ("click", "attach"):
                continue
            elif kind in ("fill", "choose", "tick") and ev.get("secure"):
                steps.append({"kind": "hand_fill", "label": label, "target": None, "keep": True})
            elif kind in ("fill", "choose", "tick"):
                if not any(s["kind"] == "fill_form" for s in steps):
                    steps.append({"kind": "fill_form", "label": "Fill the form from the bank", "target": None,
                                  "keep": True})
                if kind != "tick" and (op := _bank_op(label, ev.get("value") or "", bank, keys, ops)):
                    ops.append(op)
        out_pages.append({"id": pid, "new": new, "yaml": {"page": page}, "steps": steps,
                          "added": added})
    if out_pages and not any(s["kind"] == "hand_over" and s["keep"] for s in out_pages[-1]["steps"]):
        out_pages[-1]["steps"].append({"kind": "hand_over", "label": "You check and submit", "target": None,
                                       "keep": True})
    return {"pages": out_pages, "bank": ops}


def _identifies(page, root):
    try:
        return engine.identify(page, root)
    except Exception:   # a hand-edited page with a bad anchor never matches
        return False


def _bank_op(label, value, bank, keys, ops):
    nl = normalize(label)
    if not value or not nl or any(normalize(o["label"]) == nl and o["value"] == value for o in ops):
        return None
    base = {"label": label, "value": value, "keep": _keep(value),
            "sensitive": restricted(Field("", label, "text", (), False)) is not None}
    known = next((e for e in bank.entries if nl in {normalize(x) for x in e.labels}), None)
    if known:
        return None if known.answer == value else {"op": "change", "key": known.key, **base}
    same = [e for e in bank.entries if e.answer == value]
    if len(same) == 1:   # "Yes" answers many keys: only a unique answer says which key this label belongs to
        return {"op": "label", "key": same[0].key, **base}
    key = new_key(label, keys)
    keys.add(key)
    return {"op": "add", "key": key, **base}
