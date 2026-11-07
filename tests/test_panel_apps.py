import shutil

from govaios.approvals import Approvals
from govaios.engine import REPO
from govaios.panel.apps import App, list_apps, match
from pathlib import Path


def _apps():
    return [App("himalayas_job_vetting", "JobLens", Path("a"), "d1", True),
            App("morning_inbox_briefing", "Inbox briefing", Path("b"), "d2", False)]


def test_match_phrases():
    a = _apps()
    assert match("Run the JobLens app now", a) == ("run", a[0])
    assert match("run himalayas job vetting", a) == ("run", a[0])
    assert match("run inbox briefing", a) == ("draft", a[1])
    assert match("run mail", a) == ("unknown", None)
    assert match("", a) == ("unknown", None)
    two = a + [App("joblens_two", "JobLens Two", Path("c"), "d3", True)]
    assert match("run joblens", two) == ("run", a[0])
    assert match("run two", two)[0] == "unknown"


def test_match_ambiguous():
    a = [App("x1", "Mail", Path("a"), "d", True), App("x2", "mail", Path("b"), "d", False)]
    kind, hits = match("mail", a)
    assert kind == "ambiguous" and hits == a


def test_list_apps_approved_and_draft(tmp_path):
    shutil.copytree(REPO / "flows", tmp_path / "flows")
    shutil.copytree(REPO / "pages", tmp_path / "pages")
    (tmp_path / "flows" / "broken.yaml").write_text("workflow: [")
    home = tmp_path / "home"
    home.mkdir()
    apps = list_apps(tmp_path / "flows", home)
    assert len(apps) == 3 and not any(a.approved for a in apps)
    one = apps[0]
    Approvals(home / "approvals.json").approve_flow(one.id, one.digest)
    apps = list_apps(tmp_path / "flows", home)
    assert apps[0].id == one.id and apps[0].approved and not apps[1].approved
    one.path.write_text(one.path.read_text() + "\n# edit\n")
    assert not any(a.approved for a in list_apps(tmp_path / "flows", home))
