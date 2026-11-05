import json
from datetime import datetime, timedelta, timezone

from govaios import auth, powers


class Audit:
    def __init__(self):
        self.entries = []

    def append(self, kind, **f):
        self.entries.append((kind, f))


def _write(home, ts):
    home.mkdir(parents=True, exist_ok=True)
    (home / "powers_review.json").write_text(json.dumps({"ts": ts, "kept": []}))


def test_powers_fresh(govaios_home):
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert not powers.fresh(govaios_home, now)
    _write(govaios_home, (now - timedelta(days=29)).isoformat())
    assert powers.fresh(govaios_home, now)
    _write(govaios_home, (now - timedelta(days=31)).isoformat())
    assert not powers.fresh(govaios_home, now)
    _write(govaios_home, (now + timedelta(days=1)).isoformat())   # a future stamp would never expire
    assert not powers.fresh(govaios_home, now)
    _write(govaios_home, "2026-11-01T00:00:00")   # naive
    assert not powers.fresh(govaios_home, now)
    (govaios_home / "powers_review.json").write_text("{nope")
    assert not powers.fresh(govaios_home, now)


def test_review_records_kept_apps(monkeypatch, govaios_home):
    opened, asked = [], []
    monkeypatch.setattr(powers.subprocess, "run", lambda cmd, **k: opened.append(cmd))
    monkeypatch.setattr(auth, "approve", lambda q, r, h: (asked.append(q), (False, "failed"))[1])
    a = Audit()
    assert not powers.review(govaios_home, ["Zoom"], a)
    assert not (govaios_home / "powers_review.json").exists()
    assert a.entries[-1][0] == "powers_review" and a.entries[-1][1]["auth"] == "failed"
    assert [c[-1].rsplit("?", 1)[1] for c in opened] == ["Privacy_Accessibility", "Privacy_ListenEvent",
                                                         "Privacy_ScreenCapture"]
    assert all(c[-1].startswith("x-apple.systempreferences:com.apple.preference.security?") for c in opened)

    monkeypatch.setattr(auth, "approve", lambda q, r, h: (asked.append(q), (True, "biometric"))[1])
    assert powers.review(govaios_home, ["Zoom", "1Password"], a)
    rec = json.loads((govaios_home / "powers_review.json").read_text())
    assert rec["kept"] == ["Zoom", "1Password"] and powers.fresh(govaios_home)
    assert "Only gov-aios and the apps you keep hold these; no terminal or AI agent does" in asked[-1]
    assert "Zoom" in asked[-1] and "1Password" in asked[-1]
    kind, f = a.entries[-1]
    assert kind == "powers_review" and f["auth"] == "biometric" and f["decision"] == "allow" and "1Password" in f["target"]


def test_review_audited_before_file(monkeypatch, govaios_home):
    """M-14: a failed audit append leaves no fresh review behind."""
    monkeypatch.setattr(powers.subprocess, "run", lambda cmd, **k: None)
    monkeypatch.setattr(auth, "approve", lambda q, r, h: (True, "biometric"))

    class Broken:
        def append(self, kind, **f):
            raise OSError("disk full")
    try:
        powers.review(govaios_home, [], Broken())
    except OSError:
        pass
    assert not (govaios_home / "powers_review.json").exists()
