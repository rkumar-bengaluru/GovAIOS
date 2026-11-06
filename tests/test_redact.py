import pytest

from govaios.redact import redact_command

CASES = [
    ("curl -H 'Authorization: Bearer abc123' x", "abc123"),
    ("mysql -p secret db", "secret"),
    ("API_KEY=xyz make", "xyz"),
    ("git clone https://u:pw@host/r", "u:pw"),
    ("echo sk-ant-123456789012345678901234", "sk-ant-1234"),
    ("echo ghp_abcdefghijklmnopqrstu", "ghp_abcdef"),
    ("echo github_pat_abcdefghijklmnop", "github_pat_abc"),
    ("echo AKIAABCDEFGHIJKLMNOP", "AKIAABCD"),
    ("echo xoxb-123456-abcdef", "xoxb-123456"),
    ("cmd --password hunter2", "hunter2"),
    ("cmd --token=tok999", "tok999"),
    ("echo '-----BEGIN RSA PRIVATE KEY-----\nMIIBOg\n-----END RSA PRIVATE KEY-----'", "MIIBOg"),
]


@pytest.mark.parametrize("cmd,secret", CASES)
def test_redact(cmd, secret):
    out = redact_command(cmd)
    assert "[REDACTED]" in out and secret not in out


def test_clean_unchanged():
    assert redact_command("git status") == "git status"
