"""Studio lessons: what the admin did in Chrome, saved, then turned into a PROPOSED change (page files, steps per
page, bank ops) for the admin to review. Only apply() writes, and only the panel calls it, after Touch ID.

Dev mode: lessons are NOT masked (values as typed; secure fields are already blank from the observer).
shortcut: unmasked, add masking before this leaves dev. Files are 0600 under <data home>/lessons/, last KEEP per flow.
"""
import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .observer import NO_FILE
from .policy import RISK_ORDER, origin
from . import capture, engine, formfill, studio
from .approvals import pages_used, read_bound
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
    tmp = d / (name + ".tmp")   # never a half-written lesson under its real name
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(doc, ensure_ascii=False, indent=1).encode())
        os.replace(tmp, d / name)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
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


def _key_for(page, root, spec, label, exact=False):
    """(key, sure): the element key in page that locates spec's node (adding it, risk by role, when none does);
    sure is False when spec does not find exactly one node in the stored tree. exact: only a key with this spec."""
    els = page["elements"]
    want = [id(n) for n in engine.find_all(root, spec, {"elements": {}})]   # Node is a dataclass: compare identity
    sure = len(want) == 1
    for k, s in els.items():
        if "fields" in s:
            continue
        if {a: b for a, b in s.items() if a != "risk"} == spec:
            return k, sure
        if sure and not exact and [id(n) for n in engine.find_all(root, s, page)] == want:
            return k, sure
    base = studio._slug(label) or spec["role"]
    k, i = base, 2
    while k in els:
        k, i = f"{base}_{i}", i + 1
    els[k] = {**spec, "risk": _risk(spec["role"])}
    return k, sure


def _file_input(spec):
    """The attach check's locator: as observed, but by its name's part before "No file chosen" (the file's name
    replaces it once attached); None when nothing else locates it."""
    if not spec or "name" not in spec:
        return dict(spec) if spec else None   # a stable dom_id
    head = spec["name"].split(NO_FILE)[0]
    if not head.strip() or "index" in spec:
        return None
    return {"role": spec["role"], "name_matches": "^" + re.escape(head)}


def _attach(look, page, root, evs, i, new):
    """(target key, check key, sure) for an attach event, as job_apply's attach step: target opens the file chooser
    (the click just before, or the file input itself), check is the file input. (None, None, False): not replayable."""
    ev = evs[i]
    chk = _file_input(ev.get("spec"))
    if chk is None:
        return None, None, False
    prev = evs[i - 1].get("spec") if i and evs[i - 1]["kind"] == "click" else None
    kc, sure = _key_for(look, root, chk, ev.get("label") or "", exact=True)
    kt, st = (_key_for(look, root, prev, evs[i - 1].get("label") or "") if prev and prev != ev.get("spec")
              else (kc, sure))
    for k, risk in ((kc, "read"), (kt, "modify")):   # the target last: when it is the input too, it is clicked
        if new or k not in page["elements"]:   # a draft's own rating (buttons submit) is lowered; a known page's kept
            look["elements"][k]["risk"] = risk
        elif RISK_ORDER.index(page["elements"][k]["risk"]) > RISK_ORDER.index("modify"):
            sure = False   # the engine would refuse it at run time
    return kt, kc, sure and st


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
            chk = None
            if kind == "attach":
                k, chk, sure = _attach(look, page, root, evs, i, new)
            else:
                k, sure = _key_for(look, root, spec, label) if kind == "click" and spec else (None, False)
            target = f"{pid}.{k}" if k else None
            line, keep = None, sure and not (kind == "click" and any(s["kind"] == "hand_over" for s in steps))
            text = label + ("" if sure else " (check this target)")   # off until the admin checks it
            if kind == "click" and not k:
                line = {"kind": "click", "label": "not sure what this was", "target": None, "keep": False}
            elif kind == "click" and look["elements"][k].get("risk") == "submit":
                line = {"kind": "hand_over", "label": text, "target": target, "keep": keep}   # replayed as hand over
            elif kind == "click":
                line = {"kind": "click", "label": text, "target": target,
                        "keep": keep}   # a click after the hand over is dead: replay stops there
            elif kind == "attach":
                line = {"kind": "attach_file", "label": label if chk is None else text, "target": target,
                        "check": f"{pid}.{chk}" if chk else None, "keep": keep}
            if line:
                steps.append(line)
                for key in dict.fromkeys(x for x in (k, chk) if x):
                    if not new and key not in page["elements"]:
                        added.append(key)
                    page["elements"][key] = look["elements"][key]
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


SANDBOX = (None, "web_sandbox")   # a lesson with no flow: its pages go to Studio, nothing else changes
_DO = {"click": "click", "fill_form": "fill_form", "attach_file": "attach_file", "hand_over": "hand_over"}


def _ids(steps):
    out = []
    for s in steps:
        out.append(s.get("id"))
        out += _ids(s.get("steps", []))
        for v in s.get("on_match", {}).values():
            if isinstance(v, dict) and isinstance(v.get("do"), list):
                out += [d.get("id") for d in v["do"] if isinstance(d, dict)]
    return out


def _find(steps, sid):
    for s in steps:
        if s.get("id") == sid:
            return s
        hit = _find(s.get("steps", []), sid)
        if hit:
            return hit
    return None


def _do(line, page):
    """The flow step for one kept line, or None (hand_fill: fill_form leaves it for the admin)."""
    kind = line["kind"]
    if kind == "attach_file":   # the engine's CV attach, as job_apply's attach step
        return ({"action": "attach_file", "target": line["target"], "check": line["check"]}
                if line.get("target") and line.get("check") else None)
    if kind == "click":
        return {"action": "click", "target": line["target"]} if line.get("target") else None
    return {"action": _DO[kind]} if kind in _DO else None


def _site(url):
    """https://host[:port] for a new destination, by the engine's rule for typed sites (engine destination_inputs)."""
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise ValueError("a page's address is not valid") from None
    if u.scheme != "https" or u.username or u.password or not u.hostname:
        raise ValueError(f"only https sites can be added, not {u.scheme}://{u.hostname or ''}"[:200])
    return f"https://{u.hostname.lower()}" + (f":{port}" if port not in (None, 443) else "")


def build(lesson, proposal, deleted, keeps, raw, flow_path, pages_dir) -> dict:
    """The approved change in memory, checked before Touch ID: {"pages": {path: bytes}, "new": {paths},
    "flow": (path, bytes) | None, "digest": the digest the written files must have, "ops": bank ops, "counts": str}.
    raw: read_bound's {path: bytes} from the digest check: the flow is built from those bytes, never re-read.
    deleted: {(page index, line index)}; keeps: {bank line index: keep}. ValueError when it cannot be written."""
    pages_dir = Path(pages_dir)
    pages, fresh = {}, set()
    for p, lp in zip(proposal["pages"], lesson["pages"]):
        if p["new"] or p["added"]:   # a known page gaining nothing is not rewritten
            path = pages_dir / f"{p['id']}.yaml"
            if p["new"] and os.path.lexists(path):
                raise ValueError(f"page {p['id']} exists now; teach it again")
            if p["new"]:
                fresh.add(path)
                head = studio.draft_head(f"lesson for {lesson.get('flow') or 'Studio'}", lp["url"]).encode()
            else:   # a known page keeps its header comments (a draft's Start link)
                lines = (raw[path] if raw and path in raw else path.read_bytes()).splitlines(keepends=True)
                head = b"".join(lines[:next((i for i, x in enumerate(lines) if not x.startswith(b"#")), len(lines))])
            pages[path] = head + yaml.safe_dump(p["yaml"], sort_keys=False, allow_unicode=True).encode()
    new = sum(1 for p in proposal["pages"] if p["new"])
    if lesson.get("flow") in SANDBOX:
        return {"pages": pages, "new": fresh, "flow": None, "digest": None, "ops": [],
                "counts": f"pages {len(pages)} ({new} new), steps 0, bank 0"}
    flow_path = Path(flow_path)
    doc = yaml.safe_load(raw[flow_path])
    wf = doc["workflow"]
    step = _find(wf["steps"], lesson.get("step"))
    if step is None or step.get("action") != "classify_page":
        raise ValueError("the step this lesson belongs to is gone; teach it again")
    on, ids, last, n = step.setdefault("on_match", {}), set(_ids(wf["steps"])), len(proposal["pages"]) - 1, 0
    for i, p in enumerate(proposal["pages"]):
        if p["id"] in on:   # the flow already handles this page: its own case stays
            continue
        do = []
        for j, line in enumerate(p["steps"]):
            s = _do(line, p) if line["keep"] and (i, j) not in deleted else None
            if s:
                k = len(do) + 1
                while f"learned_{p['id']}_{k}" in ids:
                    k += 1
                ids.add(f"learned_{p['id']}_{k}")
                do.append({"id": f"learned_{p['id']}_{k}", **s})
        if do:
            on[p["id"]] = {"do": do, "then": "end" if i == last else "again"}
            n += len(do)
    if "unknown" in on:
        on["unknown"] = on.pop("unknown")   # stays the last case, as written by hand
    dests = wf.setdefault("destinations", [])
    for lp in lesson["pages"]:
        if origin(lp["url"]) not in dests and (site := _site(lp["url"])) not in dests:
            dests.append(site)
    try:
        engine.check_learned(wf["steps"])
    except engine.Stop as e:
        raise ValueError(str(e)) from None
    data = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode()
    if yaml.safe_load(data) != doc:
        raise ValueError("the new flow does not read back the same")
    h = hashlib.sha256(data)   # read_bound's digest, over the bytes approved here: what the files must hold after
    for pid in sorted(pages_used(doc["workflow"])):
        pp = pages_dir / f"{pid}.yaml"
        try:   # a page bound only now (a known page's new case) is read here, before Touch ID
            h.update(pages[pp] if pp in pages else raw[pp] if pp in raw else pp.read_bytes())
        except FileNotFoundError:
            raise ValueError(f"page {pid} is missing") from None
    ops = [{**o, "keep": keeps.get(i, o["keep"])} for i, o in enumerate(proposal["bank"])]
    kept = sum(1 for o in ops if o["keep"] == "bank")
    return {"pages": pages, "new": fresh, "flow": (flow_path, data), "digest": h.hexdigest(), "ops": ops,
            "counts": f"pages {len(pages)} ({new} new), steps {n}, bank {kept}"}


def _put(path, data, new=False):
    """A fresh temp file beside path, then os.replace (a crash leaves the old file whole); new: os.link instead,
    which fails if a file appeared there meanwhile."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        if new:
            os.link(tmp, path)
            os.unlink(tmp)
        else:
            os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply(plan, pages_dir, bank_path) -> str | None:
    """Write what build() made: pages, then the flow, then the bank ops. Returns the new flow digest, read back
    from the files as written (None for a sandbox lesson)."""
    for path, data in plan["pages"].items():
        _put(path, data, path in plan["new"])
    if plan["flow"] is None:
        return None
    _put(*plan["flow"])
    formfill.apply_ops(Path(bank_path), plan["ops"])
    digest = read_bound(plan["flow"][0], pages_dir)[0]
    if digest != plan["digest"]:   # a bound file changed during the Touch ID wait: not what was approved
        raise ValueError("files changed while you approved")
    return digest
