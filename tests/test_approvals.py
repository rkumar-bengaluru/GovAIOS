import os
import shutil
from pathlib import Path

import pytest
import yaml

from govaios.approvals import Approvals, flow_hash, pages_used

ROOT = Path(__file__).parent.parent
HIM = "flows/himalayas_job_vetting.yaml"


def test_pages_used_himalayas():
    flow = yaml.safe_load((ROOT / HIM).read_text())["workflow"]
    assert pages_used(flow) == {"google_home", "himalayas_matches", "himalayas_logged_out", "himalayas_job_detail"}


@pytest.fixture
def tree(tmp_path):
    shutil.copytree(ROOT / "flows", tmp_path / "flows")
    shutil.copytree(ROOT / "pages", tmp_path / "pages")
    return tmp_path


def test_unrelated_page_edit_keeps_hash(tree):
    before = flow_hash(tree / HIM, tree / "pages")
    with open(tree / "pages/gmail_inbox.yaml", "a") as f:
        f.write("\n# edit\n")
    assert flow_hash(tree / HIM, tree / "pages") == before


def test_used_page_edit_changes_hash(tree):
    before = flow_hash(tree / HIM, tree / "pages")
    with open(tree / "pages/himalayas_matches.yaml", "a") as f:
        f.write("\n# edit\n")
    assert flow_hash(tree / HIM, tree / "pages") != before


def test_missing_page_rejected(tree):
    flow = tree / "flows/bad.yaml"
    flow.write_text("workflow:\n  id: bad\n  steps:\n    - {id: a, action: click, verify_page: nope}\n")
    with pytest.raises(KeyError, match="nope"):
        flow_hash(flow, tree / "pages")


def test_revocation_survives_other_writer(tmp_path):
    p = tmp_path / "approvals.json"
    a, b = Approvals(p), Approvals(p)
    a.approve_flow("f", "h")
    b.revoke_flow("f")
    a.approve_destination("f", "https://y")
    assert Approvals(p).flow_ok("f", "h") is False
    assert Approvals(p).destination_ok("f", "https://y") is True


def test_revoke_destination_and_all(tmp_path):
    a = Approvals(tmp_path / "approvals.json")
    a.approve_destination("f", "https://x")
    a.approve_destination("f", "https://y")
    a.revoke_destination("f", "https://x")
    assert not a.destination_ok("f", "https://x") and a.destination_ok("f", "https://y")
    a.approve_flow("f", "h")
    a.revoke_all()
    assert a.snapshot() == {"flows": {}, "destinations": {}, "presses": {}}


def test_write_is_atomic(tmp_path, monkeypatch):
    p = tmp_path / "approvals.json"
    a = Approvals(p)
    a.approve_flow("f", "h")
    before = p.read_text()
    monkeypatch.setattr(os, "replace", lambda *x: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        a.approve_flow("g", "h2")
    assert p.read_text() == before
    assert sorted(x.name for x in tmp_path.iterdir()) == ["approvals.json", "approvals.lock"]


def test_pages_used_skips_current_page():
    flow = {"steps": [{"target": "current_page.next"}, {"target": "current_item.title"}, {"target": "p.x"}]}
    assert pages_used(flow) == {"p"}


def test_press_grant_is_tied_to_the_digest(tmp_path):
    a = Approvals(tmp_path / "approvals.json")
    a.grant_presses("a", "d1")
    assert a.press_ok("a", "d1") and not a.press_ok("a", "d2")
    a.revoke_flow("a")
    assert not a.press_ok("a", "d1")
