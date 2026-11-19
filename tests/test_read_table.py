"""The read_table step: picked columns of one table into the run's report, never to stdout or the audit."""
import re

import pytest
import yaml

from govaios import engine
from govaios.engine import Runner, Stop, check_learned
from conftest import FakeDesktop, N

SITE = "http://localhost:8100"
PG = "localhost_tickets"
MORE = "(more rows not read)"


def cell(x):
    return N("cell", children=[N("text", x)])


def table(head, rows):
    return N("table", children=[N("row", children=[cell(h) for h in head])]
             + [N("row", children=[cell(c) for c in r]) for r in rows])


class Desk(FakeDesktop):
    def __init__(self, tables, capped=False):
        super().__init__([])
        self.tables, self.capped = tables, capped

    def current_url(self, app):
        return SITE + "/tickets"

    def web_root(self, app):
        return N("document", "Tickets", children=list(self.tables))


def make(tmp_path, step, try_=False, has="Ticket"):
    flows, pages = tmp_path / "apps" / "flows", tmp_path / "apps" / "pages"
    flows.mkdir(parents=True, exist_ok=True), pages.mkdir(exist_ok=True)
    (pages / f"{PG}.yaml").write_text(yaml.safe_dump({"page": {
        "id": PG, "identification": {"title_matches": "^Tickets$", "anchors": []},
        "elements": {"tickets": {"role": "table", "has_text": has, "risk": "read"}}}}))
    f = flows / "tf.yaml"
    f.write_text(yaml.safe_dump({"workflow": {
        "id": "tf", "version": 1, "browser": {"application": "chrome", "account": "x"},
        **({"try": True} if try_ else {}),
        "permissions": {"allow": ["read_page", "extract_visible_text", "report"], "max_element_risk": "read"},
        "destinations": [SITE], "steps": [{"id": "c", "action": "classify_page", "on_match": {PG: {"do": [
            {"id": "r", "action": "read_table", "target": f"{PG}.tickets", **step}], "then": "end"}}}]}}))
    return f


def go(tmp_path, monkeypatch, desk, step, try_=False, has="Ticket"):
    monkeypatch.setattr(engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(engine.auth, "screen_locked", lambda: False)
    monkeypatch.setattr(engine.auth, "prove", lambda *a, **k: (True, "biometric"))
    r = Runner(make(tmp_path, step, try_, has), desk, tmp_path)
    r.approvals.approve_flow("tf", r.digest)
    r.approvals.approve_destination("tf", SITE)
    try:
        r.run()
    except Stop as e:
        return e
    return None


def report(tmp_path):
    (f,) = (tmp_path / "reports").iterdir()
    return f.read_text()


TWO = ["Ticket", "Subject"]
ROWS = [["T-0009", "VPN down"], ["T-0012", "Printer"]]


def test_read_first_row(tmp_path, monkeypatch, capsys):
    d = Desk([table(["Net", "Gross"], [["55743", "70000"], ["1", "2"]])])
    assert go(tmp_path, monkeypatch, d, {"columns": ["Net"], "rows": "first"}, has="Net") is None
    assert report(tmp_path) == "Net: 55743\n"
    (f,) = (tmp_path / "reports").iterdir()
    assert f.stat().st_mode & 0o777 == 0o600
    out = capsys.readouterr().out
    assert any(re.fullmatch(r"report saved: reports/[a-z0-9_]{1,68}-\d{8}T\d{6}Z\.txt", ln) for ln in out.splitlines())
    assert "55743" not in out


def test_read_every_row(tmp_path, monkeypatch):
    d = Desk([table(TWO, ROWS)])
    assert go(tmp_path, monkeypatch, d, {"columns": TWO, "rows": "all"}) is None
    assert report(tmp_path).splitlines() == ["Ticket: T-0009 | Subject: VPN down", "Ticket: T-0012 | Subject: Printer"]


def test_read_table_twice_stops(tmp_path, monkeypatch):
    d = Desk([table(TWO, ROWS), table(TWO, ROWS)])
    e = go(tmp_path, monkeypatch, d, {"columns": ["Ticket"], "rows": "all"})
    assert str(e) == f"{PG}.tickets: expected 1 element, found 2"
    assert not (tmp_path / "reports").exists()


def test_read_column_missing_stops(tmp_path, monkeypatch):
    e = go(tmp_path, monkeypatch, Desk([table(TWO, ROWS)]), {"columns": ["Net"], "rows": "all"})
    assert "column Net not found" in str(e)
    assert not (tmp_path / "reports").exists()


def test_read_column_twice_stops(tmp_path, monkeypatch):
    d = Desk([table(["Ticket", "Net", "Net"], [["a", "b", "c"]])])
    assert "column Net found more than once" in str(go(tmp_path, monkeypatch, d, {"columns": ["Net"], "rows": "all"}))


def test_read_short_row_missing(tmp_path, monkeypatch):
    d = Desk([table(TWO, [["T-1"]])])
    assert go(tmp_path, monkeypatch, d, {"columns": TWO, "rows": "all"}) is None
    assert report(tmp_path) == "Ticket: T-1 | Subject: (missing)\n"


def test_read_no_rows(tmp_path, monkeypatch):
    assert go(tmp_path, monkeypatch, Desk([table(TWO, [])]), {"columns": TWO, "rows": "all"}) is None
    assert report(tmp_path) == "(no rows)\n"


def test_read_no_rows_capped(tmp_path, monkeypatch):
    assert go(tmp_path, monkeypatch, Desk([table(TWO, [])], capped=True), {"columns": TWO, "rows": "all"}) is None
    assert report(tmp_path).splitlines() == ["(no rows)", MORE]


def test_read_201_rows(tmp_path, monkeypatch):
    d = Desk([table(TWO, [[f"T-{i}", "s"] for i in range(201)])])
    assert go(tmp_path, monkeypatch, d, {"columns": TWO, "rows": "all"}) is None
    lines = report(tmp_path).splitlines()
    assert len(lines) == 201 and lines[0].startswith("Ticket: T-0") and lines[-1] == MORE


def test_read_capped_snapshot_says_more(tmp_path, monkeypatch):
    d = Desk([table(TWO, ROWS)], capped=True)
    assert go(tmp_path, monkeypatch, d, {"columns": TWO, "rows": "all"}) is None
    lines = report(tmp_path).splitlines()
    assert len(lines) == 3 and lines[-1] == MORE


def test_read_cleans_values(tmp_path, monkeypatch):
    d = Desk([table(TWO, [["a\x07b\x7f | Ticket: T-9999", "y" * 250]])])
    assert go(tmp_path, monkeypatch, d, {"columns": TWO, "rows": "all"}) is None
    (line,) = report(tmp_path).splitlines()
    t, s = line.split(" | Subject: ")
    assert t == "Ticket: ab / Ticket: T-9999" and len(s) == 200


def test_read_audit_has_no_values(tmp_path, monkeypatch):
    d = Desk([table(TWO, ROWS)])
    assert go(tmp_path, monkeypatch, d, {"columns": ["Ticket"], "rows": "all"}) is None
    raw = (tmp_path / "audit.jsonl").read_text()
    assert "T-0009" not in raw and "VPN" not in raw
    import json
    es = [json.loads(ln) for ln in raw.splitlines()]
    (e,) = [x for x in es if x.get("action") == "read_table"]
    assert (e["target"], e["columns"], e["rows"], e["outcome"]) == (f"{PG}.tickets", "Ticket", 2, "done")


def test_read_in_a_try_runs_in_full(tmp_path, monkeypatch):
    d = Desk([table(TWO, ROWS)])
    assert go(tmp_path, monkeypatch, d, {"columns": ["Ticket"], "rows": "first"}, try_=True) is None
    assert report(tmp_path) == "Ticket: T-0009\n"


def steps(*do, **step):
    return [{"id": "c", "action": "classify_page", "on_match": {PG: {"do": list(do), "then": "end"}}}]


def rd(**kw):
    return {"id": "r", "action": "read_table", "target": f"{PG}.tickets", "columns": ["Ticket"], "rows": "all", **kw}


@pytest.mark.parametrize("kw,msg", [
    ({"target": "tickets"}, "learned steps: read_table target must be page.element"),
    ({"target": "current_page.tickets"}, "learned steps: read_table target must be page.element"),
    ({"target": "current_item.tickets"}, "learned steps: read_table target must be page.element"),
    *[({"columns": c}, "learned steps: read_table columns must be 1 to 10 unique names of 1 to 200 characters")
      for c in ([], [str(i) for i in range(11)], ["a", "a"], [""], ["x" * 201], ["a\nb"], "Net")],
    ({"rows": "some"}, "learned steps: read_table rows must be first or all"),
])
def test_check_read_shape(kw, msg):
    with pytest.raises(Stop) as e:
        check_learned(steps(rd(**kw)))
    assert str(e.value) == msg


def test_check_read_target_must_be_a_table():
    pages = {PG: {"elements": {"tickets": {"role": "button"}}}}
    with pytest.raises(Stop) as e:
        check_learned(steps(rd()), pages)
    assert str(e.value) == f"learned steps: read_table target {PG}.tickets is not a table of its page"


def test_check_read_must_be_last():
    with pytest.raises(Stop) as e:
        check_learned(steps(rd(), {"id": "k", "action": "click", "target": f"{PG}.tickets"}))
    assert str(e.value) == "learned steps: read_table must be the last step of its page"


def test_repeat_cannot_hold_a_read():
    rep = {"id": "p", "action": "repeat", "item": f"{PG}.row", "max": 3,
           "steps": [{"id": "k", "action": "click", "target": f"{PG}.row"}, rd(id="r2")]}
    with pytest.raises(Stop) as e:
        check_learned(steps(rep))
    assert str(e.value) == "learned steps: a repeat cannot hold a read_table"
