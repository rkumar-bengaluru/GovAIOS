import os
import stat

import pytest

from govaios.audit.log import AuditLog
from govaios.panel.totp import SecretStore, Verifier, code_at, new_secret, otpauth_uri, qr_svg

S = b"12345678901234567890"


def test_rfc6238_vectors():
    for t, c in [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                 (1234567890, "005924"), (2000000000, "279037"), (20000000000, "353130")]:
        assert code_at(S, t) == c


def mk(tmp_path, now):
    clock = {"t": now}
    return Verifier(tmp_path / "totp.state", lambda: clock["t"]), clock


def test_window_plus_minus_one(tmp_path):
    t = 1_000_000_020
    for off, want in [(-30, "ok"), (30, "ok"), (-60, "bad_code")]:
        v, _ = mk(tmp_path, t)
        v.path.unlink(missing_ok=True)
        SecretStore(tmp_path).save(S)
        assert v.verify(code_at(S, t + off)) == want


def test_replay_refused(tmp_path):
    SecretStore(tmp_path).save(S)
    v, c = mk(tmp_path, 1_000_000_020)
    assert v.verify(code_at(S, c["t"])) == "ok"
    assert v.verify(code_at(S, c["t"])) == "replay"
    assert v.verify(code_at(S, c["t"] - 30)) == "replay"


def test_lockout_after_five(tmp_path):
    SecretStore(tmp_path).save(S)
    v, c = mk(tmp_path, 1_000_000_020)
    for _ in range(5):
        assert v.verify("000000") == "bad_code"
    assert v.verify(code_at(S, c["t"])) == "locked_out"
    c["t"] += 15 * 60
    assert v.verify(code_at(S, c["t"])) == "ok"
    for _ in range(3):
        v.verify("000000")
    c["t"] += 30
    assert v.verify(code_at(S, c["t"])) == "ok"  # success reset the count
    assert Verifier(v.path, lambda: c["t"]).verify("000000") == "bad_code"  # state persisted


def test_no_secret(tmp_path):
    assert Verifier(tmp_path / "totp.state").verify("123456") == "no_secret"


def test_secret_store_mode_and_no_follow(tmp_path):
    st = SecretStore(tmp_path)
    st.save(S)
    st.save(S)  # replace
    assert stat.S_IMODE(os.stat(tmp_path / "totp.key").st_mode) == 0o600
    assert st.load() == S
    st.delete()
    assert st.load() is None
    target = tmp_path / "target"
    target.write_bytes(b"x" * 20)
    os.symlink(target, tmp_path / "totp.key")
    try:
        assert st.load() is None
    except OSError:
        pass


def test_otpauth_uri_and_qr():
    assert otpauth_uri(S) == ("otpauth://totp/GOV-AIOS:Admin?secret="
                              "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ&issuer=GOV-AIOS")
    assert qr_svg("otpauth://x").startswith("<svg")
    assert len(new_secret()) == 20


@pytest.mark.parametrize("kind", ["totp_setup", "totp_reset", "session_open", "session_end"])
def test_audit_accepts_new_kinds(tmp_path, kind):
    assert AuditLog(tmp_path).append(kind, session="ab" * 8)["kind"] == kind
