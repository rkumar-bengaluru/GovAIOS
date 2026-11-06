"""App list and spoken-command matching for the control panel."""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from govaios.approvals import Approvals, read_bound

_FILLER = {"run", "the", "app", "flow", "now", "please", "start"}


@dataclass
class App:
    id: str
    name: str
    path: Path
    digest: str
    approved: bool


def list_apps(flows_dir: Path, home: Path) -> list[App]:
    flows_dir = Path(flows_dir)
    approvals = Approvals(Path(home) / "approvals.json")
    out = []
    for p in sorted(flows_dir.glob("*.yaml")):
        try:
            digest, raw = read_bound(p, flows_dir.parent / "pages")
            wf = yaml.safe_load(raw[p])["workflow"]
            out.append(App(wf["id"], wf.get("app") or wf["name"], p, digest, approvals.flow_ok(wf["id"], digest)))
        except Exception:   # unloadable file: not an app
            continue
    return sorted(out, key=lambda a: (not a.approved, a.name.lower()))


def _words(text: str) -> str:
    return " ".join(w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in _FILLER)


def match(text: str, apps: list[App]):
    want = _words(text)
    if not want:
        return "unknown", None
    hits = [a for a in apps if want in (_words(a.name), _words(a.id.replace("_", " ")))]
    if len(hits) > 1:
        return "ambiguous", hits
    if not hits:
        return "unknown", None
    return ("run" if hits[0].approved else "draft"), hits[0]
