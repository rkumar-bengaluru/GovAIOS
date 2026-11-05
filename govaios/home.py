import os
import pwd
import sys
from pathlib import Path


def data_home():
    # The packaged app ignores GOVAIOS_HOME: an environment variable must not redirect its audit/approvals.
    env = None if getattr(sys, "frozen", False) else os.environ.get("GOVAIOS_HOME")
    # Frozen: HOME is attacker-controlled, so take the home from the passwd database.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir) if getattr(sys, "frozen", False) else Path.home()
    p = Path(env or home / "Library/Application Support/GOV-AIOS")
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p
