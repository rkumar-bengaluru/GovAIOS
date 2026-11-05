import shutil
from pathlib import Path

import pytest
import yaml

from govaios.approvals import flow_hash, pages_used

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
