"""Panel settings in <data home>/panel.json (0600, no-follow, atomic). Only the owner's name so far."""
import json
import os
import pwd
import unicodedata
from pathlib import Path

from govaios.panel.totp import _read_nofollow, _replace

MAX = 40


def default_name(gecos: str) -> str:
    return (gecos.split(",")[0].split() or ["Admin"])[0]


def _load(home: Path) -> dict:
    try:
        d = json.loads(_read_nofollow(Path(home) / "panel.json") or b"")
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def name(home: Path) -> str:
    v = _load(home).get("name")
    if isinstance(v, str) and 0 < len(v) <= MAX:
        return v
    return default_name(pwd.getpwuid(os.getuid()).pw_gecos)


def check(value: str) -> str:
    value = value.strip()
    if not 0 < len(value) <= MAX or any(unicodedata.category(c)[0] == "C" or unicodedata.category(c) in ("Zl", "Zp") for c in value):
        raise ValueError("name must be 1-40 characters, no control characters")
    return value


def set_name(home: Path, value: str) -> None:
    _replace(Path(home) / "panel.json", json.dumps({**_load(home), "name": check(value)}).encode())
