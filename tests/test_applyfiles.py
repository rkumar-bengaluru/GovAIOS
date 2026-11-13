import os
import stat

import pytest

from govaios import applyfiles as af


def test_write_read_remove_modes(tmp_path):
    af.write_json(tmp_path, af.ASK, {"run": "r", "fields": []})
    af.write_json(tmp_path, af.ASK, {"run": "r2", "fields": []})   # replaces the older file
    assert stat.S_IMODE(os.stat(tmp_path / af.ASK).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(tmp_path / af.APPLY_DIR).st_mode) == 0o700
    assert af.read_json(tmp_path, af.ASK)["run"] == "r2"
    af.remove(tmp_path, af.ASK, af.REPLY)
    assert af.read_json(tmp_path, af.ASK) is None


def test_refuses_symlinked_dir_and_file(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / af.APPLY_DIR).symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        af.write_json(tmp_path, af.ASK, {})
    assert af.read_json(tmp_path, af.ASK) is None
    (tmp_path / af.APPLY_DIR).unlink()
    af.write_json(tmp_path, af.ASK, {"a": 1})
    (tmp_path / af.REPLY).symlink_to(tmp_path / af.ASK)
    assert af.read_json(tmp_path, af.REPLY) is None
    af.write_json(tmp_path, af.REPLY, {"b": 2})   # replaces the link, not the target
    assert af.read_json(tmp_path, af.ASK) == {"a": 1}


def test_read_json_rejects_large_or_bad(tmp_path):
    af.write_json(tmp_path, af.ASK, {})
    p = tmp_path / af.ASK
    p.write_text("{" + " " * af.MAX + "}")
    assert af.read_json(tmp_path, af.ASK) is None
    p.write_text("nope")
    assert af.read_json(tmp_path, af.ASK) is None
    p.write_text("[1]")
    assert af.read_json(tmp_path, af.ASK) is None


def test_append_line_appends_0600_and_refuses_symlink(tmp_path):
    af.append_line(tmp_path, af.TEACH_IN, {"a": 1})
    af.append_line(tmp_path, af.TEACH_IN, {"b": 2})
    assert (tmp_path / af.TEACH_IN).read_text() == '{"a": 1}\n{"b": 2}\n'
    assert stat.S_IMODE(os.stat(tmp_path / af.TEACH_IN).st_mode) == 0o600
    (tmp_path / af.TEACH_IN).unlink()
    (tmp_path / "t").write_text("x")
    (tmp_path / af.TEACH_IN).symlink_to(tmp_path / "t")
    with pytest.raises(OSError):
        af.append_line(tmp_path, af.TEACH_IN, {"c": 3})
