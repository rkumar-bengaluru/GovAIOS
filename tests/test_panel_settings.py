import json
import os
import stat

import pytest

from govaios.panel import settings


def test_default_name():
    assert settings.default_name("Rupak Kumar,,,") == "Rupak"
    assert settings.default_name("") == "Admin"
    assert settings.default_name("  ") == "Admin"


def test_set_name_file_mode_and_symlink(tmp_path):
    settings.set_name(tmp_path, " Asha ")
    p = tmp_path / "panel.json"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and settings.name(tmp_path) == "Asha"
    p.write_text(json.dumps({"name": "Asha", "other": 1}))
    settings.set_name(tmp_path, "Ben")
    assert json.loads(p.read_text()) == {"name": "Ben", "other": 1}
    p.unlink()
    (tmp_path / "target").write_text("{}")
    os.symlink(tmp_path / "target", p)
    settings.set_name(tmp_path, "Cy")   # replaces the link; the target is untouched
    assert (tmp_path / "target").read_text() == "{}" and not p.is_symlink()


@pytest.mark.parametrize("bad", ["", "  ", "x" * 41, "\x07", "a\nb", "a\u0085b", "a\u2028b", "a\u2029b"])
def test_set_name_rejects(tmp_path, bad):
    with pytest.raises(ValueError):
        settings.set_name(tmp_path, bad)
    assert not (tmp_path / "panel.json").exists()


def test_name_falls_back_on_bad_file(tmp_path):
    (tmp_path / "panel.json").write_text(json.dumps({"name": "x" * 41}))
    assert settings.name(tmp_path)
    (tmp_path / "panel.json").write_text("not json")
    assert settings.name(tmp_path)
