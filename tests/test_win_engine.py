import sys

import pytest

from govaios.engine import Stop
from test_engine_audit import _no_prompts, run

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only: panel tickets are not supported there")


def test_ticket_run_fails_closed_on_windows(tmp_path, monkeypatch):
    """Panel tickets are a non-goal on Windows: a run with a ticket stops at the start gate, no flow step runs."""
    _no_prompts(monkeypatch)
    r, e, err = run(tmp_path, [True] * 10, preapprove=True, ticket="0" * 64)
    assert isinstance(err, Stop)
    assert any(x["kind"] == "stop" for x in e)
    assert [x["decision"] for x in e if x.get("action") == "run_start"] == ["deny"]
    assert not any(x["kind"] == "action" for x in e)
    assert "launch" not in r.d.calls
