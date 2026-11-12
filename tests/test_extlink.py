import os

import pytest

from govaios.panel import extlink
from govaios.panel.totp import SecretStore, code_at

S = b"12345678901234567890"
T = 1_000_000_020
A = "chrome-extension://" + "a" * 32
B = "chrome-extension://" + "b" * 32


@pytest.fixture
def home(tmp_path):
    SecretStore(tmp_path).save(S)
    return tmp_path


def pair(home, t=T, origin=A):
    return extlink.pair(home, code_at(S, t), origin, clock=lambda: t)


def test_pair_then_check(home):
    t = pair(home)
    assert t and extlink.check(home, t, A)
    assert not extlink.check(home, t, B)
    assert not extlink.check(home, "x" + t, A)
    assert not extlink.check(home, None, A) and not extlink.check(home, t, None)
    assert t not in (home / "extension.json").read_text()
    assert (home / "extension.json").stat().st_mode & 0o777 == 0o600


def test_code_is_single_use(home):
    t = pair(home)
    assert pair(home) is None
    assert extlink.check(home, t, A)


def test_bad_origin_refused(home):
    assert pair(home, origin="https://evil.example") is None
    assert pair(home, origin=A + "\n") is None
    assert not (home / "extension.json").exists()


def test_repair_replaces(home):
    old = pair(home)
    new = pair(home, T + 30, B)
    assert new and not extlink.check(home, old, A)
    assert extlink.check(home, new, B)


def test_disconnect(home):
    t = pair(home)
    assert extlink.connected(home)
    extlink.disconnect(home)
    assert not extlink.check(home, t, A) and not extlink.connected(home)


def test_symlink_refused(home, tmp_path_factory):
    target = tmp_path_factory.mktemp("x") / "t.json"
    target.write_text("{}")
    os.symlink(target, home / "extension.json")
    assert not extlink.check(home, "t", A)
    assert pair(home) is None
    assert target.read_text() == "{}"
