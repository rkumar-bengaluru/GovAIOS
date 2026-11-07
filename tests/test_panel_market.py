import json
import os

import pytest
import yaml

from govaios.engine import REPO
from govaios.panel import market

T = {t.id: t for t in market.CATALOG}


def test_catalog_templates_ship_with_the_app():
    for t in market.CATALOG:
        wf = yaml.safe_load((REPO / "flows" / f"{t.id}.yaml").read_text())["workflow"]
        assert wf["id"] == t.id and "profile_directory" in wf["browser"] and "account" in wf["browser"]


def test_chrome_profiles_only_signed_in_and_unreadable_is_empty(tmp_path):
    p = tmp_path / "Local State"
    assert market.chrome_profiles(p) == []
    p.write_text("{not json")
    assert market.chrome_profiles(p) == []
    p.write_text(json.dumps({"profile": {"info_cache": {
        "Profile 2": {"name": "Home", "user_name": "a@example.com"},
        "Default": {"name": "Plain", "user_name": ""},
        "../evil": {"name": "x", "user_name": "b@example.com"}}}}))
    assert market.chrome_profiles(p) == [("Profile 2", "Home", "a@example.com")]


def test_setup_writes_draft_flow_and_missing_pages_only(tmp_path):
    flows, pages = tmp_path / "apps/flows", tmp_path / "apps/pages"
    pages.mkdir(parents=True)
    (pages / "gmail_inbox.yaml").write_text("mine")   # never overwritten
    out = market.setup(T["morning_inbox_briefing"], "Profile 5", "x.y@example.com", flows, REPO)
    b = yaml.safe_load(out.read_text())["workflow"]["browser"]
    assert (b["profile_directory"], b["account"]) == ("Profile 5", "x.y@example.com")
    assert (pages / "gmail_inbox.yaml").read_text() == "mine" and (pages / "google_home.yaml").exists()
    assert oct(out.stat().st_mode & 0o777) == "0o600" and oct(flows.stat().st_mode & 0o777) == "0o700"
    with pytest.raises(ValueError):
        market.setup(T["morning_inbox_briefing"], "Profile 5", "x.y@example.com", flows, REPO)


@pytest.mark.parametrize("profile,account", [("Profile 1\nx", "a@example.com"), ("../x", "a@example.com"),
                                             ("Profile 1", "a@example.com\n  name: x"), ("Profile 1", "nobody")])
def test_setup_refuses_bad_values(tmp_path, profile, account):
    with pytest.raises(ValueError):
        market.setup(T["morning_inbox_briefing"], profile, account, tmp_path / "apps/flows", REPO)
    assert not (tmp_path / "apps/flows/morning_inbox_briefing.yaml").exists()


def test_setup_refuses_symlinked_target(tmp_path):
    flows = tmp_path / "apps/flows"
    flows.mkdir(parents=True)
    os.symlink(tmp_path / "elsewhere", flows / "himalayas_job_vetting.yaml")
    with pytest.raises(ValueError):
        market.setup(T["himalayas_job_vetting"], "Profile 1", "a@example.com", flows, REPO)
    assert not (tmp_path / "elsewhere").exists()
