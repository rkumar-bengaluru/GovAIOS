"""Secret redaction for audited shell commands (decision row 17)."""
import re

R = "[REDACTED]"
_PEM = (r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)", R)
_RULES = [
    (re.compile(_PEM[0], re.S), R),
    (re.compile(r"(?i)(authorization:\s*)[^'\"\n]+"), r"\1" + R),
    (re.compile(r"(?i)\b(bearer\s+)[\w.~+/=-]+"), r"\1" + R),
    (re.compile(r"(://)[^/\s@]+@"), r"\1" + R + "@"),
    (re.compile(r"(--(?:password|token)(?:=|\s+))\S+"), r"\1" + R),
    (re.compile(r"(?i)\b(\w*(?:pass(?:word)?|secret|token|api[_-]?key|auth|credential)\w*=)\S+"), r"\1" + R),
    (re.compile(r"\bsk-[\w-]{10,}|\bgh[pousr]_\w{10,}|\bgithub_pat_\w{10,}|\bAKIA[0-9A-Z]{12,}|\bxox[bp]-[\w-]{6,}"), R),
]
_MYSQL_P = re.compile(r"(\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^;&|\n]*?\s-p)\s*(?!-)\S+")


def redact_command(cmd: str) -> str:
    cmd = _MYSQL_P.sub(r"\1 " + R, cmd)
    for rx, rep in _RULES:
        cmd = rx.sub(rep, cmd)
    return cmd
