"""A click refused because something covers its target asks the admin to close it, instead of stopping."""
import pytest
import yaml

from govaios import engine
from govaios.desktop.macos import InputRefused
from govaios.engine import Runner, Stop
from conftest import FakeDesktop, N

SITE = "https://automationexercise.com"
COVERED = "input refused: click point is not on the target element (hit AXGroup is unrelated to target AXLink)"


class Desk(FakeDesktop):
    def __init__(self, covered, err=COVERED):
        super().__init__([])
        self.covered, self.err, self.url = covered, err, SITE + "/"

    def current_url(self, app):
        return self.url

    def click(self, node):
        if self.covered:
            self.covered -= 1
            raise InputRefused(self.err)
        self.calls.append(("click", node.name))

    def link_url(self, node):
        return getattr(self, "href", None)

    def web_root(self, app):
        return N("document", "Home", children=[N("link", "Products")])


def go(tmp_path, monkeypatch, desk, choices, run_id="r1", on_card=lambda: None, step_id="go"):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "approve", lambda q, r, h: (True, "biometric"))
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True), pages.mkdir()
    (pages / "home.yaml").write_text(yaml.safe_dump({"page": {
        "id": "home", "identification": {"title_matches": "^Home$", "anchors": []},
        "elements": {"products": {"role": "link", "name": "Products", "risk": "navigate"}}}}))
    (flows / "ae.yaml").write_text(yaml.safe_dump({"workflow": {
        "id": "ae", "app": "Practice", "version": 1, "browser": {"application": "chrome", "account": "x"},
        "permissions": {"allow": ["click", "read_page", "ask_admin"], "max_element_risk": "navigate"},
        "destinations": [SITE], "steps": [{"id": step_id, "action": "click", "target": "home.products"}]}}))
    r = Runner(flows / "ae.yaml", desk, tmp_path)
    seen = []
    r.card = lambda kind, label, tick=None: (seen.append((kind, label)), on_card(), choices.pop(0) if run_id else None)[2]
    r.approvals.approve_flow("ae", r.digest)
    r.approvals.approve_destination("ae", SITE)
    try:
        r.run()
    except Stop as e:
        return seen, str(e)
    return seen, None


def test_close_it_and_continue_clicks(tmp_path, monkeypatch):
    d = Desk(covered=1)
    seen, err = go(tmp_path, monkeypatch, d, ["continue"])
    assert seen == [("covered", "Products")] and err is None and ("click", "Products") in d.calls


def test_end_stops_the_run(tmp_path, monkeypatch):
    seen, err = go(tmp_path, monkeypatch, Desk(covered=1), ["end"])
    assert seen == [("covered", "Products")] and err == "ended by admin"


def test_still_covered_after_three_asks_stops(tmp_path, monkeypatch):
    seen, err = go(tmp_path, monkeypatch, Desk(covered=9), ["continue"] * 3)
    assert len(seen) == 3 and err == COVERED


@pytest.mark.parametrize("err", ["input refused: click point is not in the target app",
                                 "input refused: click point is not on the target element (hit AXStaticText contains target AXLink)"])
def test_other_refusals_never_ask(tmp_path, monkeypatch, err):
    seen, got = go(tmp_path, monkeypatch, Desk(covered=1, err=err), [])
    assert seen == [] and got == err


def test_a_cli_run_stops_as_before(tmp_path, monkeypatch):
    seen, err = go(tmp_path, monkeypatch, Desk(covered=1), [], run_id=None)
    assert err == COVERED


def test_closing_a_full_page_ad_that_finished_the_click_carries_on(tmp_path, monkeypatch):
    d = Desk(covered=1)
    went_on = lambda: setattr(d, "url", SITE + "/products#google_vignette")   # closing the ad finished the click
    seen, err = go(tmp_path, monkeypatch, d, ["continue"], on_card=went_on)
    assert err is None and ("click", "Products") not in d.calls   # never clicked again on the next page
    assert "\"outcome\":\"done_by_cover\"" in (tmp_path / "audit.jsonl").read_text()


@pytest.mark.parametrize("href, opened", [(SITE + "/products", True), (SITE + "/#top", False),
                                          ("javascript:void(0)", False), ("https://ads.example/x", False)])
def test_a_learned_link_on_an_outside_site_is_opened_not_clicked(tmp_path, monkeypatch, href, opened):
    d = Desk(covered=0)
    d.href = href
    typed = []
    monkeypatch.setattr(Runner, "_go", lambda self, url: typed.append(url))
    seen, err = go(tmp_path, monkeypatch, d, [], step_id="learned_home_1")
    assert err is None and typed == ([href] if opened else []) and (("click", "Products") in d.calls) != opened


def test_a_hand_written_click_is_still_a_click(tmp_path, monkeypatch):
    d = Desk(covered=0)
    d.href = SITE + "/products"
    seen, err = go(tmp_path, monkeypatch, d, [])
    assert err is None and ("click", "Products") in d.calls
