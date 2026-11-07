"""Job-application form filling: answer bank and label matching. Pure; no OS automation."""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml

RESTRICTED = {
    "sensitive": r"password|passcode|\bssn\b|social security|national id|aadhaar|\bpan\b|passport|bank|card number|iban|routing|sort code",
    "demographic": r"gender|\brace\b|ethnic|veteran|disab|pronoun|sexual orientation|hispanic|latino",
    "consent": r"^i (certify|agree|acknowledge|consent|confirm|understand)|terms|privacy policy",
}
_KEY = re.compile(r"[a-z0-9_]{1,40}")


class BankError(ValueError):
    """Message holds field names or line numbers only, never answer text."""


@dataclass(frozen=True)
class Entry:
    key: str
    labels: tuple[str, ...]
    answer: str


@dataclass(frozen=True)
class Bank:
    entries: tuple[Entry, ...] = ()
    cv_file: str | None = None


def normalize(label: str) -> str:
    s = label.lower().rstrip("*✱ \t\r\n")
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s).split())


def ok_value(value: str, kind: str) -> bool:
    return not any(ord(c) < 32 and not (c == "\n" and kind == "textarea") or ord(c) == 127 for c in value)


def _check_dir(path: Path) -> None:
    try:
        if stat.S_ISLNK(os.lstat(path.parent).st_mode):
            raise BankError("apply/ is a symlink")
    except FileNotFoundError:
        pass


def load_bank(path: Path, user_home: Path) -> Bank:
    _check_dir(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return Bank()
    except OSError:
        raise BankError("answer bank cannot be opened") from None
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise BankError("answer bank is not a regular file")
        try:
            data = yaml.safe_load(f.read().decode("utf-8"))
        except UnicodeDecodeError:
            raise BankError("answer bank is not UTF-8") from None
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            raise BankError(f"YAML error at line {mark.line + 1}" if mark else "YAML error") from None
    if data is None:
        return Bank()
    if not isinstance(data, dict):
        raise BankError("answer bank must be a mapping")
    cv = data.get("cv_file")
    if cv is not None and not isinstance(cv, str):
        raise BankError("cv_file must be a string")
    rows = data.get("answers", [])
    if not isinstance(rows, list) or len(rows) > 300:
        raise BankError("answers must be a list of at most 300 entries")
    entries, seen = [], set()
    for i, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            raise BankError(f"entry {i}: not a mapping")
        key, labels, ans = r.get("key"), r.get("labels"), r.get("answer")
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise BankError(f"entry {i}: bad key")
        if key in seen:
            raise BankError(f"entry {i}: duplicate key")
        seen.add(key)
        if (not isinstance(labels, list) or not 1 <= len(labels) <= 20
                or not all(isinstance(x, str) and len(x) <= 300 for x in labels)):
            raise BankError(f"entry {key}: bad labels")
        if not isinstance(ans, str) or len(ans) > 2000 or not ok_value(ans, "textarea"):
            raise BankError(f"entry {key}: bad answer")
        entries.append(Entry(key, tuple(labels), ans))
    return Bank(tuple(entries), cv)


def cv_path(bank: Bank, user_home: Path) -> Path | None:
    if not bank.cv_file:
        return None
    raw = bank.cv_file
    p = Path(user_home, raw[2:]) if raw.startswith("~/") else Path(raw)
    try:
        if not stat.S_ISREG(os.lstat(p).st_mode) or p.suffix.lower() not in (".pdf", ".doc", ".docx"):
            return None
        return p if Path(os.path.realpath(p)).is_relative_to(os.path.realpath(user_home)) else None
    except OSError:
        return None


def add_answer(path: Path, label: str, answer: str) -> str:
    if not ok_value(answer, "textarea") or len(answer) > 2000:
        raise BankError("answer refused")
    _check_dir(path)
    bank = load_bank(path, path.parent)
    if len(label) > 300 or len(bank.entries) >= 300:
        raise BankError("label too long or bank full")
    base = normalize(label).replace(" ", "_")[:40] or "answer"
    key, n = base, 1
    taken = {e.key for e in bank.entries}
    while key in taken:
        n += 1
        key = f"{base[:40 - len(str(n)) - 1]}_{n}"
    doc = {"answers": [{"key": e.key, "labels": list(e.labels), "answer": e.answer} for e in bank.entries]
           + [{"key": key, "labels": [label], "answer": answer}]}
    if bank.cv_file:
        doc["cv_file"] = bank.cv_file
    path.parent.mkdir(mode=0o700, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(doc, f, allow_unicode=True)
    os.replace(tmp, path)
    return key


FIELD_ROLES = {"text_field", "text_area", "combo_box", "popup_button", "radio", "checkbox"}
_KINDS = {"text_field": "text", "text_area": "textarea", "combo_box": "combo", "popup_button": "select",
          "native:AXSecureTextField": "other"}
ASKABLE = {"text", "textarea", "combo", "select", "radio"}


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    kind: str
    options: tuple[str, ...]
    filled: bool


def _is_field(n) -> bool:
    return n.role in FIELD_ROLES or n.role == "native:AXSecureTextField"


def _question(start, parents) -> str:
    """Text of the nearest previous sibling (no fields inside) of `start` or up to 3 ancestors."""
    n = start
    for _ in range(4):
        p = parents.get(id(n))
        if p is None:
            return ""
        i = next(i for i, c in enumerate(p.children) if c is n)  # identity: Node == is structural
        for sib in reversed(p.children[:i]):
            kids = list(sib.walk())
            if any(_is_field(k) for k in kids):
                break  # never look past a field-bearing sibling
            if any(k.role == "text" for k in kids):
                return sib.text().rstrip("*✱ \t\r\n")
        n = p
    return ""


def _read(region):
    parents = {id(c): n for n in region.walk() for c in n.children}
    out, seen, counts, done = [], set(), {}, set()

    def add(node, label, kind, options, filled, use_id=True):
        nl = normalize(label)
        if use_id and node.dom_id:
            key = "#" + node.dom_id
        else:
            key = f"label:{nl}:{counts.get(nl, 0)}"
        counts[nl] = counts.get(nl, 0) + 1
        out.append((Field(key, label, kind, options, filled), node))

    def group_of(node):
        a = parents.get(id(node))
        while a is not None:
            if sum(1 for d in a.walk() if d.role == node.role) >= 2:
                return a
            a = parents.get(id(a))
        return None

    for n in region.walk():
        if id(n) in done or not _is_field(n):
            continue
        label = n.name.rstrip("*✱ \t\r\n")
        if n.role in ("radio", "checkbox"):
            g = group_of(n)
            if g is not None:
                members = [d for d in g.walk() if d.role == n.role]
                done.update(id(m) for m in members)
                label = _question(g, parents)
                add(g, label, "radio" if n.role == "radio" else "multi", tuple(m.name for m in members),
                    any(m.value == "1" for m in members), use_id=False)
                continue
        label = label or _question(n, parents)
        kind = _KINDS.get(n.role, n.role)  # lone radio/checkbox keep their role as kind
        opts = tuple(d.name for d in n.walk() if d.role == "native:AXMenuItem") if kind == "select" else ()
        if kind in ("radio", "checkbox"):
            filled = n.value == "1"
        elif kind == "select":
            filled = bool(n.value) and n.value != (opts[0] if opts else None)
        else:
            filled = bool(n.value)
        add(n, label, kind, opts, filled)
    return out


def read_form(region) -> list[Field]:
    return [f for f, _ in _read(region)]


def locate(region, f: Field):
    return next((n for g, n in _read(region) if g.key == f.key), None)


def restricted(f: Field) -> str | None:
    if f.kind == "other":
        return "secure"
    if f.kind == "multi":
        return "demographic"
    s = normalize(f.label)
    return next((name for name, pat in RESTRICTED.items() if re.search(pat, s)), None)


def answer_for(f: Field, bank: Bank, fields: list[Field]) -> tuple[str, str] | None:
    nl = normalize(f.label)
    if not nl or restricted(f) or f.filled or f.kind not in ASKABLE:
        return None
    if sum(1 for g in fields if normalize(g.label) == nl) != 1:
        return None
    hits = [e for e in bank.entries if nl in {normalize(x) for x in e.labels}]
    if len(hits) != 1 or not ok_value(hits[0].answer, f.kind):
        return None
    e = hits[0]
    if f.kind in ("select", "radio"):
        m = [o for o in f.options if normalize(o) == normalize(e.answer)]
        return (m[0], f"bank:{e.key}") if len(m) == 1 and ok_value(m[0], f.kind) else None
    return e.answer, f"bank:{e.key}"
