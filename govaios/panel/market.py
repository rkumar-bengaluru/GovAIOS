"""Marketplace: the templates shipped with GOV-AIOS, and setting one up as a Draft app in the apps folder."""
import json
import os
import pwd
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Template:
    id: str          # the workflow id of the shipped flow
    title: str
    does: str
    needs: tuple
    limits: str


CATALOG = (
    Template("morning_inbox_briefing", "Morning Gmail Briefing",
             "Reads your Gmail inbox and gives you a short summary of the newest mail.",
             ("Google account", "Chrome"), "Reads mail.google.com only. Never sends, replies or deletes."),
    Template("himalayas_job_vetting", "Sync Himalayas to JobLens",
             "Vets your Himalayas job matches and sends the good ones to JobLens on this Mac.",
             ("Google account", "Chrome", "JobLens"), "Reads himalayas.app only. Never applies for or saves a job."),
)
PROFILE_DIR = re.compile(r"Default|Profile [0-9]{1,3}")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63}){1,4}")


def local_state() -> Path:
    """Chrome's profile list. Home from the passwd database, like data_home: HOME is not trusted."""
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / "Library/Application Support/Google/Chrome/Local State"


def chrome_profiles(path: Path) -> list[tuple[str, str, str]]:
    """(profile directory, profile name, Google account) for each profile signed in to Google; [] if unreadable."""
    try:
        cache = json.loads(Path(path).read_text())["profile"]["info_cache"]
        out = [(d, str(v.get("name") or d)[:80], v.get("user_name") or "") for d, v in cache.items()]
    except Exception:
        return []
    return sorted((d, n, a) for d, n, a in out if PROFILE_DIR.fullmatch(d) and EMAIL.fullmatch(a))


def installed_ids(flows_dir: Path) -> dict[str, str]:
    """workflow id -> app name, for every loadable flow in the apps folder."""
    out = {}
    for p in sorted(Path(flows_dir).glob("*.yaml")) if flows_dir else ():
        try:
            wf = yaml.safe_load(p.read_text())["workflow"]
            out[wf["id"]] = wf.get("app") or wf["name"]
        except Exception:
            continue
    return out


def _create(path: Path, data: bytes) -> bool:
    """Exclusive, no-follow create (0600). False if anything is already there; a partial write is removed."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    except BaseException:
        path.unlink()
        raise
    return True


def setup(t: Template, profile_dir: str, account: str, flows_dir: Path, src: Path) -> Path:
    """Write the template's flow into the apps folder for this Chrome profile and account, and any of its pages
    the folder lacks. Never overwrites. The new app is a Draft until the admin approves it. ValueError if refused."""
    if not PROFILE_DIR.fullmatch(profile_dir) or not EMAIL.fullmatch(account):
        raise ValueError("bad profile or account")
    flows_dir = Path(flows_dir)
    target = flows_dir / f"{t.id}.yaml"
    if t.id in installed_ids(flows_dir) or target.exists() or target.is_symlink():
        raise ValueError("already installed")
    text = (Path(src) / "flows" / f"{t.id}.yaml").read_text()
    text, n1 = re.subn(r'(?m)^(\s+profile_directory: )"[^"\n]*"', lambda m: f'{m[1]}"{profile_dir}"', text, count=1)
    text, n2 = re.subn(r"(?m)^(\s+account: )\S+", lambda m: m[1] + account, text, count=1)
    b = yaml.safe_load(text)["workflow"]["browser"]
    if (n1, n2) != (1, 1) or (b["profile_directory"], b["account"]) != (profile_dir, account):
        raise ValueError("template has no browser profile or account")
    pages = flows_dir.parent / "pages"
    for d in (flows_dir, pages):
        if d.is_symlink():
            raise ValueError("apps folder is a symlink")
        d.mkdir(mode=0o700, parents=True, exist_ok=True)
    for p in sorted((Path(src) / "pages").glob("*.yaml")):
        q = pages / p.name
        if not (q.exists() or q.is_symlink()):
            _create(q, p.read_bytes())   # a page made meanwhile is kept; the flow digest binds whatever is there
    if not _create(target, text.encode()):
        raise ValueError("already installed")
    return target
