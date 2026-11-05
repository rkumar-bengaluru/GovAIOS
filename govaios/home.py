import os
from pathlib import Path


def data_home():
    p = Path(os.environ.get("GOVAIOS_HOME") or Path.home() / "Library/Application Support/GOV-AIOS")
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p
