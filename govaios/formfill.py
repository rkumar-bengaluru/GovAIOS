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
