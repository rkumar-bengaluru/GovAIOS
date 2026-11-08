import json
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pathlib import Path

from govaios import delivery
from govaios.approvals import flow_hash
from govaios.engine import Runner
from govaios.runstate import Stop

from govaios.audit.log import AuditLog
from govaios.delivery import Deliveries, build_payload, check_block

DESC = "d" * 300


def flow(deliver=None, allow=("deliver",), directory="jd_selected"):
    f = {"permissions": {"allow": list(allow)},
         "steps": [{"action": "for_each_item", "steps": [{"action": "write_json", "directory": directory}]}]}
    if deliver is not None:
        f["deliver"] = deliver
    return f


GOOD = {"to": "joblens", "from": "jd_selected", "source": "Himalayas"}


def test_check_block_none_without_deliver():
    assert check_block(flow()) is None


def test_check_block_accepts_himalayas_shape():
    assert check_block(flow(GOOD)) == GOOD


@pytest.mark.parametrize("block,allow,field", [
    ({**GOOD, "to": "other"}, ("deliver",), "to"),
    ({**GOOD, "url": "x"}, ("deliver",), "deliver"),
    ({**GOOD, "from": "elsewhere"}, ("deliver",), "from"),
    ({**GOOD, "source": ""}, ("deliver",), "source"),
    ({**GOOD, "source": "x" * 51}, ("deliver",), "source"),
    ({**GOOD, "source": "a\nb"}, ("deliver",), "source"),
    (GOOD, (), "permissions.allow"),
])
def test_check_block_refuses(block, allow, field):
    with pytest.raises(ValueError) as e:
        check_block(flow(block, allow))
    assert str(e.value) == field


def rec(**kw):
    return {"job_title": "Senior Dev", "company": "Acme", "description": DESC,
            "url": "https://himalayas.app/x", **kw}


def test_payload_maps_fields():
    p = build_payload(rec(job_title="  Senior\n  Dev "), "Himalayas")
    assert p == ({"title": "Senior Dev", "company": "Acme", "jd_text": DESC,
                  "url": "https://himalayas.app/x", "source": "Himalayas"}, None, None)


@pytest.mark.parametrize("posted, captured, want", [
    ("just now", "2026-11-06T09:00:00", "2026-11-06"),
    ("today", "2026-11-06T09:00:00", "2026-11-06"),
    ("5 minutes ago", "2026-11-06T09:00:00", "2026-11-06"),
    ("56 mins ago", "2026-11-06T15:13:03", "2026-11-06"),
    ("1 min ago", "2026-11-06T00:00:30", "2026-11-05"),
    ("3 hrs ago", "2026-11-06T02:00:00", "2026-11-05"),
    ("1 hr ago", "2026-11-06T09:00:00", "2026-11-06"),
    ("30 secs ago", "2026-11-06T09:00:00", "2026-11-06"),
    ("5m ago", "2026-11-06T09:00:00", None),   # too terse to trust
    ("9 hours ago", "2026-11-06T14:17:42", "2026-11-06"),
    ("13 hours ago", "2026-11-06T09:00:00", "2026-11-05"),   # crosses midnight
    ("1 hour ago", "2026-11-06T00:30:00", "2026-11-05"),
    ("an hour ago", "2026-11-06T09:00:00", "2026-11-06"),
    ("yesterday", "2026-11-06T09:00:00", "2026-11-05"),
    ("1 day ago", "2026-11-06T09:00:00", "2026-11-05"),
    ("3 days ago", "2026-11-01T09:00:00", "2026-10-29"),
    ("Posted 2 days ago", "2026-11-06T09:00:00", "2026-11-04"),
    ("3 weeks ago", "2026-11-06T09:00:00", None),
    ("a month ago", "2026-11-06T09:00:00", None),
    ("Nov 3", "2026-11-06T09:00:00", None),
    ("99999999999 days ago", "2026-11-06T09:00:00", None),
    (None, "2026-11-06T09:00:00", None),
    ("9 hours ago", None, None),
    ("9 hours ago", "garbage", None),
    ("2 days ago", "2999-01-03T09:00:00", None),   # never after today (Asia/Kolkata)
])
def test_payload_posted_on(posted, captured, want):
    r = rec()
    r["list_item"] = {"title": "t", "posted": posted}
    r["captured_at"] = captured
    p = build_payload(r, "S")[0]
    assert p.get("posted_on") == want


def test_payload_posted_on_without_list_item():
    assert "posted_on" not in build_payload(rec(), "S")[0]


def test_payload_jd_limits():
    assert build_payload(rec(description="d" * 299), "S") == (None, "skipped_too_short", "jd_text")
    assert build_payload(rec(description="d" * 300), "S")[0]["jd_text"] == "d" * 300
    assert len(build_payload(rec(description="d" * 50000), "S")[0]["jd_text"]) == 50000
    assert build_payload(rec(description="d" * 50001), "S") == (None, "failed", "jd_text")


def test_payload_title_without_letters_fails():
    assert build_payload(rec(job_title="--- !!"), "S") == (None, "failed", "title")


def test_payload_bad_types_fail():
    assert build_payload(rec(company=5), "S") == (None, "failed", "company")


@pytest.mark.parametrize("url", ["javascript:x", None, "https://a b", "x" * 5, "http://[x", "https:///x"])
def test_payload_drops_bad_url(url):
    assert "url" not in build_payload(rec(url=url), "S")[0]


def test_payload_every_cc_char_is_control():
    p = build_payload(rec(job_title="Senior\x85Eng\x80ineer", description="a\x85b\n\tc" + DESC), "S")[0]
    assert p["title"] == "Senior Eng ineer" and p["jd_text"] == "ab\n\tc" + DESC


def test_payload_empty_company_left_out():
    assert "company" not in build_payload(rec(company="  "), "S")[0]


def test_deliveries_once(tmp_path):
    p = tmp_path / "deliveries.json"
    d = Deliveries(p)
    d.record("h", "delivered", 5)
    d.record("h2", "retry", None)
    d2 = Deliveries(p)
    assert d2.done("h") and not d2.done("h2") and not d2.done("h3")


def test_audit_accepts_delivery_entry(govaios_home):
    AuditLog(govaios_home).append("delivery", flow="f", target="joblens", file_hash="ab" * 32,
                                  response_code=202, listing_id=1, outcome="delivered")


@pytest.mark.parametrize("code,body,want", [
    (202, {"id": 5}, ("delivered", 5, None)),
    (200, {"id": 6, "duplicate": True}, ("duplicate", 6, None)),
    (202, {"id": "x"}, ("delivered", None, None)),
    (400, {"error": {"message": "title: too long"}}, ("failed", None, "title")),
    (400, {"error": {"message": "<b>x</b>: y"}}, ("failed", None, "bad_request")),
    (400, None, ("failed", None, "bad_request")),
    (409, None, ("retry", None, "conflict")),
    (429, None, ("retry", None, "intake_cap")),
    (None, None, ("retry", None, "unreachable")),
    (503, None, ("retry", None, "server_error")),
    (404, None, ("failed", None, "http_404")),
])
def test_classify_table(code, body, want):
    assert delivery.classify(code, body) == want


class Fake:
    def __init__(self, answers, on_answer=None):
        self.answers, self.bodies = list(answers), []
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                outer.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                code, body = outer.answers.pop(0)
                if on_answer:
                    on_answer()
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data) + (100 if body == "short" else 0)))
                self.end_headers()
                self.wfile.write(data)
                self.close_connection = True

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/x" % self.srv.server_port

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def fake(monkeypatch):
    made = []

    def make(answers, on_answer=None):
        f = Fake(answers, on_answer)
        made.append(f)
        monkeypatch.setitem(delivery.TARGETS["joblens"], "url", f.url)
        return f

    yield make
    for f in made:
        f.close()


FLOW = {"id": "f1"}


def job(home, name, at="2026-01-01", title="Engineer", flow="f1", **kw):
    d = home / "jd_selected"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"flow": flow, "captured_at": at, "job_title": title, "description": DESC, **kw}
    (d / name).write_text(json.dumps(rec))
    return d / name


def batch(home):
    return delivery.deliver_batch(home, FLOW, GOOD, AuditLog(home))


def test_batch_sends_once(govaios_home, fake):
    f = fake([(202, {"id": 1}), (200, {"id": 2, "duplicate": True})])
    job(govaios_home, "a.json", at="1")
    job(govaios_home, "b.json", at="2")
    c = batch(govaios_home)
    assert c["delivered"] == 1 and c["duplicate"] == 1
    batch(govaios_home)
    assert len(f.bodies) == 2


def test_batch_changed_file_sent_again(govaios_home, fake):
    f = fake([(202, {"id": 1}), (202, {"id": 2})])
    p = job(govaios_home, "a.json")
    batch(govaios_home)
    job(govaios_home, "a.json", title="Other Engineer")
    batch(govaios_home)
    assert len(f.bodies) == 2


def test_409_stops_batch_rest_pending(govaios_home, fake):
    f = fake([(202, {"id": 1}), (409, {})])
    for i in "abc":
        job(govaios_home, i + ".json", at=i)
    c = batch(govaios_home)
    assert len(f.bodies) == 2 and c["retry"] == 1 and c["left"] == 1
    f.answers = [(202, {"id": 2}), (202, {"id": 3})]
    batch(govaios_home)
    assert len(f.bodies) == 4


def test_unreachable_is_retry(govaios_home, monkeypatch):
    monkeypatch.setitem(delivery.TARGETS["joblens"], "url", "http://127.0.0.1:1/x")
    job(govaios_home, "a.json")
    assert batch(govaios_home)["retry"] == 1
    assert not Deliveries(govaios_home / "deliveries.json")._load() or all(
        not Deliveries(govaios_home / "deliveries.json").done(h) for h in Deliveries(govaios_home / "deliveries.json")._load())


def test_order_oldest_captured_first(govaios_home, fake):
    f = fake([(202, {"id": 1}), (202, {"id": 2})])
    job(govaios_home, "a.json", at="2026-02", title="Newer Role")
    job(govaios_home, "b.json", at="2026-01", title="Older Role")
    batch(govaios_home)
    assert [b["title"] for b in f.bodies] == ["Older Role", "Newer Role"]


def test_other_flow_files_ignored(govaios_home, fake):
    f = fake([])
    job(govaios_home, "a.json", flow="other")
    c = batch(govaios_home)
    assert not f.bodies and not any(c.values())


def test_corrupt_json_failed_and_batch_continues(govaios_home, fake):
    f = fake([(202, {"id": 1})])
    (govaios_home / "jd_selected").mkdir(parents=True)
    (govaios_home / "jd_selected" / "a.json").write_text("{nope")
    job(govaios_home, "b.json")
    c = batch(govaios_home)
    assert c["failed"] == 1 and c["delivered"] == 1 and len(f.bodies) == 1


def test_symlink_not_followed(govaios_home, fake, tmp_path):
    f = fake([])
    out = job(tmp_path, "real.json")
    d = govaios_home / "jd_selected"
    d.mkdir(parents=True)
    os.symlink(out, d / "link.json")
    batch(govaios_home)
    assert not f.bodies


def test_stop_flag_stops_before_next_file(govaios_home, fake):
    f = fake([(202, {"id": 1}), (202, {"id": 2})], on_answer=lambda: (govaios_home / "STOPPED").write_text(""))
    job(govaios_home, "a.json", at="1")
    job(govaios_home, "b.json", at="2")
    with pytest.raises(Stop):
        batch(govaios_home)
    assert len(f.bodies) == 1
    assert len(Deliveries(govaios_home / "deliveries.json")._load()) == 1


def test_audit_has_no_content(govaios_home, fake):
    fake([(202, {"id": 1})])
    job(govaios_home, "a.json", job_title="ZQXMARKER", company="ZQXMARKER", url="https://ZQXMARKER.example/x",
        description="ZQXMARKER " * 40)
    batch(govaios_home)
    assert "ZQXMARKER" not in (govaios_home / "audit.jsonl").read_text()


def test_truncated_response_is_retry(govaios_home, fake):
    fake([(200, "short")])
    job(govaios_home, "a.json")
    assert batch(govaios_home)["retry"] == 1


def test_fifo_not_opened_blocking(govaios_home, fake):
    f = fake([(202, {"id": 1})])
    job(govaios_home, "a.json")
    os.mkfifo(govaios_home / "jd_selected" / "x.json")
    assert batch(govaios_home)["delivered"] == 1 and len(f.bodies) == 1


def test_truncated_error_body_is_retry(govaios_home, fake):
    fake([(503, "short")])
    job(govaios_home, "a.json")
    assert batch(govaios_home)["retry"] == 1


def test_sigterm_during_post_audited_as_stopped_and_resent(govaios_home, fake):
    import signal

    kill = [signal.SIGTERM]   # only the first request is interrupted
    f = fake([(202, {"id": 1}), (200, {"id": 1})], on_answer=lambda: kill and os.kill(os.getpid(), kill.pop()))

    def on_term(signum, frame):
        raise Stop("emergency stop")
    prev = signal.signal(signal.SIGTERM, on_term)
    try:
        job(govaios_home, "a.json")
        with pytest.raises(Stop):
            batch(govaios_home)
    finally:
        signal.signal(signal.SIGTERM, prev)
    entries = [json.loads(x) for x in (govaios_home / "audit.jsonl").read_text().splitlines()]
    (e,) = [x for x in entries if x["kind"] == "delivery"]
    assert (e["outcome"], e["reason"], e["response_code"], e["listing_id"]) == ("stopped", "emergency stop", None, None)
    assert not Deliveries(govaios_home / "deliveries.json")._load()
    assert batch(govaios_home)["duplicate"] == 1 and len(f.bodies) == 2


def test_send_ignores_proxy_env(fake, monkeypatch):
    target, proxy = fake([(202, {"id": 1})]), Fake([(502, {})])
    try:
        for k in ("http_proxy", "HTTP_PROXY"):
            monkeypatch.setenv(k, "http://127.0.0.1:%d" % proxy.srv.server_port)
        for k in ("no_proxy", "NO_PROXY"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setattr(urllib.request, "_opener", None)   # urlopen's cached opener read proxies when first built
        assert delivery.send(target.url, {"a": 1}) == (202, {"id": 1})
        assert len(target.bodies) == 1 and not proxy.bodies
    finally:
        proxy.close()


def test_from_outside_home_refused(govaios_home, fake):
    f = fake([(202, {"id": 1})])
    d = govaios_home.parent / "x" / "jd_selected"
    d.mkdir(parents=True)
    (d / "a.json").write_text(json.dumps({"flow": "f1", "captured_at": "1", "job_title": "Engineer", "description": DESC}))
    with pytest.raises(Stop) as e:
        delivery.deliver_batch(govaios_home, FLOW, {**GOOD, "from": "../x/jd_selected"}, AuditLog(govaios_home))
    assert str(e.value) == "deliver directory outside the data home" and not f.bodies


def _log(home, *entries):
    a = AuditLog(home)
    for kind, fl in entries:
        a.append(kind, flow=fl)


@pytest.mark.parametrize("entries,want", [
    ([("flow_start", "f1"), ("flow_end", "f1")], True),
    ([("flow_start", "f1"), ("stop", "f1")], False),
    ([("flow_start", "f1")], False),
    ([("flow_start", "f1"), ("flow_end", "other")], False),
    ([("flow_start", "f1"), ("flow_end", "f1"), ("flow_start", "f1"), ("stop", "f1")], False),
    ([("flow_start", "f1"), ("stop", "f1"), ("flow_start", "f1"), ("flow_end", "f1")], True),
    ([], False),
])
def test_last_run_finished(govaios_home, entries, want):
    _log(govaios_home, *entries)
    with open(govaios_home / "audit.jsonl", "a") if entries else open(os.devnull, "a") as f:
        f.write("not json\n")
    assert delivery.last_run_finished(govaios_home, "f1") is want


FLOW_YAML = """workflow:
  id: f1
  permissions: {allow: [deliver]}
  steps: [{action: write_json, directory: jd_selected}]
"""
BLOCK_YAML = "  deliver: {to: joblens, from: jd_selected, source: Himalayas}\n"


@pytest.fixture
def setup(govaios_home, tmp_path, monkeypatch):
    from govaios import auth, runstate
    from govaios.approvals import Approvals, flow_hash

    def make(block=True, approved=True, last="flow_end", live=(), dest=True):
        (tmp_path / "flows").mkdir(exist_ok=True)
        p = tmp_path / "flows" / "f1.yaml"
        p.write_text(FLOW_YAML + (block if isinstance(block, str) else BLOCK_YAML if block else ""))
        govaios_home.mkdir(parents=True, exist_ok=True)
        ap = Approvals(govaios_home / "approvals.json")
        if approved:
            ap.approve_flow("f1", flow_hash(p, tmp_path / "pages"))
        if dest:
            ap.approve_destination("f1", "joblens")
        _log(govaios_home, ("flow_start", "f1"), (last, "f1"))
        monkeypatch.setattr(runstate, "live_runs", lambda home: [os.getpid(), *live])
        monkeypatch.setattr(auth, "approve", lambda *a: pytest.fail("asked"))
        return p
    return make


@pytest.mark.parametrize("kw,msg", [
    (dict(approved=False), "flow not approved for its current file"),
    (dict(block=False), "flow has no deliver block"),
    (dict(last="stop"), "last run did not finish"),
    (dict(live=(1,)), "another gov-aios run is live"),
    (dict(block="  deliver: {to: other, from: jd_selected, source: Himalayas}\n"), "bad deliver block: to"),
])
def test_run_delivery_refusals(govaios_home, setup, kw, msg):
    p = setup(**kw)
    with pytest.raises(Stop) as e:
        delivery.run_delivery(p, govaios_home, AuditLog(govaios_home))
    assert str(e.value) == msg


def _requests(home):
    return [e for e in map(json.loads, (home / "audit.jsonl").read_text().splitlines()) if e["kind"] == "request"]


@pytest.mark.parametrize("answer", [(True, "biometric"), (False, "cancelled"), (False, "busy")])
def test_first_contact_asks_once(govaios_home, setup, fake, monkeypatch, capsys, answer):
    from govaios import auth
    f = fake([(202, {"id": 1})])
    p = setup(dest=False)
    job(govaios_home, "a.json")
    asked = []
    monkeypatch.setattr(auth, "approve", lambda q, r, h: (asked.append((q, r)), answer)[1])
    code = delivery.run_delivery(p, govaios_home, AuditLog(govaios_home))
    assert asked == [("Flow 'f1' wants to deliver its saved jobs to JobLens (local, 127.0.0.1:8100) for the first "
                      "time. Approve?", "f1: deliver to joblens")]
    (r,) = _requests(govaios_home)
    assert (r["action"], r["destination"], r["decision"], r["approver"], r["channel"], r["auth"]) == \
        ("deliver", "joblens", "allow" if answer[0] else "deny", "admin", "touch_id", answer[1])
    if not answer[0]:
        assert code == 1 and not f.bodies
        assert capsys.readouterr().err.strip() == ("approval busy" if answer[1] == "busy" else "not approved; nothing sent")
        return
    assert code == 0 and len(f.bodies) == 1
    asked.clear()
    assert delivery.run_delivery(p, govaios_home, AuditLog(govaios_home)) == 0 and asked == []


def test_summary_and_exit_code(govaios_home, setup, capsys):
    p = setup()
    job(govaios_home, "a.json", description="short", job_title="ZQXMARKER")
    assert delivery.run_delivery(p, govaios_home, AuditLog(govaios_home)) == 0
    out = capsys.readouterr()
    assert out.out == "deliver joblens: delivered 0, duplicate 0, retry 0, failed 0, skipped 1\n" and not out.err
    (govaios_home / "jd_selected" / "b.json").write_text("{nope")
    assert delivery.run_delivery(p, govaios_home, AuditLog(govaios_home)) == 1
    out = capsys.readouterr()
    assert "failed 1" in out.out and "ZQXMARKER" not in out.out + out.err


def test_unreachable_message(govaios_home, setup, monkeypatch, capsys):
    monkeypatch.setitem(delivery.TARGETS["joblens"], "url", "http://127.0.0.1:1/x")
    p = setup()
    job(govaios_home, "a.json", at="1")
    job(govaios_home, "b.json", at="2")
    assert delivery.run_delivery(p, govaios_home, AuditLog(govaios_home)) == 1
    out = capsys.readouterr()
    assert out.err == "JobLens not reachable at 127.0.0.1:8100 (is it running?)\n"
    assert out.out.splitlines()[1:] == ["1 file left for the next delivery"]


# ---------- real flows ----------

REPO = Path(__file__).resolve().parent.parent


def test_real_flows_load(tmp_path):
    him = Runner(REPO / "flows" / "himalayas_job_vetting.yaml", None, tmp_path)
    assert him.deliver == {"to": "joblens", "from": "jd_selected", "source": "Himalayas"}
    assert him.flow["app"] == "SyncJobLens"
    morning = Runner(REPO / "flows" / "morning_inbox_briefing.yaml", None, tmp_path)
    assert morning.deliver is None


def test_morning_digest_unchanged():
    assert flow_hash(REPO / "flows" / "morning_inbox_briefing.yaml", REPO / "pages") == \
        "a1dca44ed9e272377fe86987aca8bece3a1dcd7c4ef797e6ed40d4e8386ff4ae"
