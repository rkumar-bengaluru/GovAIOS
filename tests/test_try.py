"""Try it: a try flow runs the steps and stops before any button that changes something."""
import yaml

import test_press_grant as pg
import test_repeat as rp
from govaios import engine
from govaios.engine import Runner, Stop

STOP = ("Try it stops here: the real run will press {}. Close the pop-up, or press Run: it starts from your "
        "start page.")


def _try_flow(f, risk):
    d = yaml.safe_load(f.read_text())
    d["workflow"]["try"] = True
    f.write_text(yaml.safe_dump(d))
    p = f.parent.parent / "pages" / "disc.yaml"
    pd = yaml.safe_load(p.read_text())
    pd["page"]["elements"]["approve"]["risk"] = risk
    p.write_text(yaml.safe_dump(pd))


def test_try_stops_before_a_change_named_button_rated_navigate(tmp_path, monkeypatch):
    _try_flow(pg.make(tmp_path), "navigate")
    d, asked, why = pg.go(tmp_path, monkeypatch, [], keep=True)
    assert why == STOP.format("Approve & promote") and asked == []
    assert not any(c[0] == "click" for c in d.calls if isinstance(c, tuple))


def test_try_stops_before_submit(tmp_path, monkeypatch):
    _try_flow(pg.make(tmp_path), "submit")
    d, asked, why = pg.go(tmp_path, monkeypatch, [], keep=True)   # no answers: a press grant prompt would fail
    assert why == STOP.format("Approve & promote") and asked == [] and pg.grants(tmp_path) == []
    assert not any(c[0] == "click" for c in d.calls if isinstance(c, tuple))


def test_try_stop_inside_a_repeat_is_not_wrapped(tmp_path, monkeypatch):
    real = rp.make

    def make(tmp_path, rep, within=False):
        f = real(tmp_path, rep, within)
        d = yaml.safe_load(f.read_text())
        d["workflow"]["try"] = True
        f.write_text(yaml.safe_dump(d))
        return f
    monkeypatch.setattr(rp, "make", make)
    d, why = rp.go(tmp_path, monkeypatch, ["Ada"])
    assert why == STOP.format("Approve & promote") and d.calls.count(("click", "Review")) == 1
    assert ("click", "Approve & promote") not in d.calls
