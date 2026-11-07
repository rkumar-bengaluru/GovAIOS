"""OS desktop adapters. Every adapter exposes the operations in roles.yaml
and returns trees of Node with neutral roles, so the engine is OS-agnostic."""
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROLES = yaml.safe_load((Path(__file__).parent.parent / "roles.yaml").read_text())


@dataclass
class Node:
    role: str                 # neutral role (roles.yaml), or "native:<role>" if unmapped
    name: str = ""
    value: str = ""
    dom_id: str = ""
    dom_class: tuple = ()     # web element classes (macOS AXDOMClassList, Windows UIA ClassName)
    children: list = field(default_factory=list)
    handle: object = None     # OS element, used only by the adapter

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def text(self):
        """All visible text under this node, in reading order."""
        parts = [n.value or n.name for n in self.walk() if n.role == "text"]
        return " ".join(p for p in parts if p).strip()


def native_to_neutral(platform):
    # a macOS value with a space is documentation only (e.g. radio), never a native role
    return {v[platform]: k for k, v in ROLES["roles"].items() if " " not in v[platform]}


def get_desktop():
    if sys.platform == "darwin":
        from .macos import MacDesktop
        return MacDesktop()
    # shortcut: Windows adapter (UIA + SendInput, see roles.yaml) not written yet; add desktop/windows.py when Windows support starts.
    raise NotImplementedError(f"no desktop adapter for {sys.platform}")
