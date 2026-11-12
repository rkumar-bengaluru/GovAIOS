import time

from govaios.approvals import Approvals
from govaios.panel.apps import list_apps
from govaios.panel.totp import code_at
from test_panel_web import _log, _open, _secret, panel  # noqa: F401  (fixture)

INBOX = "morning_inbox_briefing"


def _approve(P, fid):
    a = next(a for a in list_apps(P.flows, P.home) if a.id == fid)
    Approvals(P.home / "approvals.json").approve_flow(a.id, a.digest)


def _convo(P):
    return "\n".join(P.srv.panel.convo)


def _outcomes(P):
    return [e["outcome"] for e in _log(P.home, "run_queue")]


def _busy_with_inbox_queued(P):
    _open(P); _approve(P, INBOX)
    P.say("run joblens"); P.say("run inbox briefing")
    assert len(P.made) == 1 and P.srv.panel.queue[0][0] == INBOX


def test_run_while_busy_queues_then_starts_when_the_run_ends(panel):
    P = panel; _open(P); _approve(P, "morning_inbox_briefing")
    P.say("run joblens"); P.say("run inbox briefing")
    assert len(P.made) == 1 and "Inbox briefing queued #1." in P.get("/")[1]
    P.made[0].done, P.made[0].code = True, 0
    P.srv.panel.tick()
    assert len(P.made) == 2 and P.made[1].started and "Starting Inbox briefing (queued)." in P.get("/")[1]
    assert [e["outcome"] for e in _log(P.home, "run_queue")] == ["queued", "started"]
    assert all("inputs" not in e for e in _log(P.home, "run_queue"))


def test_next_starts_once(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.made[0].done, P.made[0].code = True, 0
    P.srv.panel.tick(); P.srv.panel.tick()
    assert len(P.made) == 2 and P.srv.panel.queue == []


def test_typed_run_never_jumps_the_queue(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.made[0].done, P.made[0].code = True, 0   # done, not yet reported
    P.say("run joblens")
    assert "JobLens queued #2." in _convo(P) and len(P.made) == 1
    P.srv.panel.tick()
    assert len(P.made) == 2 and P.made[1].flow_path.stem == INBOX
    P.srv.panel.tick()
    assert len(P.made) == 2
    P.made[1].done, P.made[1].code = True, 0
    P.srv.panel.tick(); P.srv.panel.tick()
    assert [m.flow_path.stem for m in P.made] == ["himalayas_job_vetting", INBOX, "himalayas_job_vetting"]


def test_a_failed_start_is_dropped_and_told(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.made[0].done, P.made[0].code = True, 0
    real = P.launcher.start
    P.launcher.start = lambda self: (_ for _ in ()).throw(RuntimeError("no"))
    try:
        P.srv.panel.tick()
    finally:
        P.launcher.start = real
    assert "Inbox briefing left the queue: it did not start." in _convo(P)
    assert _outcomes(P)[-1] == "dropped" and _log(P.home, "run_queue")[-1]["reason"] == "it did not start."
    assert P.srv.panel.queue == []


def test_no_browser_signed_in_clears_the_queue(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.made[0].done, P.made[0].code = True, 0
    P.wall[0] += 9 * 3600
    P.srv.panel.tick()
    assert "Queue cleared: signed out." in _convo(P) and len(P.made) == 1 and P.srv.panel.queue == []
    assert _outcomes(P)[-1] == "cleared" and _log(P.home, "run_queue")[-1]["reason"] == "signed out."


def test_same_app_queues_once(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.say("run inbox briefing")
    assert "Inbox briefing is already queued (#1)." in _convo(P) and len(P.srv.panel.queue) == 1
    assert _outcomes(P) == ["queued"]


def test_queued_app_edited_while_waiting_is_dropped(panel):
    P = panel; _busy_with_inbox_queued(P)
    f = P.flows / f"{INBOX}.yaml"
    f.write_text(f.read_text() + "# edited\n")
    P.made[0].done, P.made[0].code = True, 0
    P.srv.panel.tick()
    assert len(P.made) == 1
    assert "Inbox briefing left the queue: it changed since it was queued." in P.get("/")[1]
    assert _outcomes(P)[-1] == "dropped"


def test_revoked_while_waiting_is_dropped(panel):
    P = panel; _busy_with_inbox_queued(P)
    Approvals(P.home / "approvals.json").revoke_flow(INBOX)
    P.made[0].done, P.made[0].code = True, 0
    P.srv.panel.tick()
    assert len(P.made) == 1 and "Inbox briefing left the queue: it is no longer approved." in _convo(P)
    assert _log(P.home, "run_queue")[-1]["reason"] == "it is no longer approved."


def test_session_end_clears_the_queue(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.mono[0] += 31 * 60
    P.srv.panel.tick()
    assert "Queue cleared: the session ended." in _convo(P) and P.srv.panel.queue == []
    P.say(code_at(_secret(P), time.time() + 30))   # the Verifier refuses a replayed step
    assert P.srv.panel.session.active()
    P.srv.panel.tick()
    assert len(P.made) == 1


def test_end_session_and_emergency_stop_clear_the_queue(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.post("/end")
    assert "Queue cleared: the session ended." in _convo(P) and P.srv.panel.queue == []
    P.srv.panel.convo.clear()
    P.say(code_at(_secret(P), time.time() + 30))
    P.say("run inbox briefing")   # the stopped JobLens run is not reported yet: it queues
    assert P.srv.panel.queue
    (P.home / "STOPPED").write_text("")
    P.srv.panel.tick()
    assert "Queue cleared: emergency stop." in _convo(P) and P.srv.panel.queue == [] and len(P.made) == 1


def test_signout_clears_the_queue(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.post("/signout")
    assert "Queue cleared: signed out." in _convo(P) and P.srv.panel.queue == []


def test_end_on_a_card_starts_the_next(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.made[0].done, P.made[0].stopped_reason = True, "ended by the admin"
    P.srv.panel.tick()
    assert len(P.made) == 2 and P.made[1].started and P.get("/")[0] == 200


def test_unqueue(panel):
    P = panel; _busy_with_inbox_queued(P)
    assert P.post("/unqueue", flow=INBOX, next="/apps")[2].getheader("Location") == "/apps"
    assert P.srv.panel.queue == [] and "Inbox briefing taken out of the queue." in _convo(P)
    assert _outcomes(P) == ["queued", "removed"]
    assert P.post("/unqueue", flow=INBOX, next="https://evil")[2].getheader("Location") == "/"
    P.say("run inbox briefing"); P.srv.panel.convo.clear()
    P.say("unqueue inbox briefing")
    assert P.srv.panel.queue == [] and "Inbox briefing taken out of the queue." in _convo(P)
    assert _outcomes(P) == ["queued", "removed", "queued", "removed"]


def test_queued_inputs_are_checked_when_queued(panel):
    P = panel; _approve(P, "job_apply"); _open(P)
    P.say("run joblens")
    P.say("/job-apply not a link")
    assert "That isn't a valid Himalayas job link." in _convo(P) and P.srv.panel.queue == []
    good = "https://himalayas.app/companies/acme/jobs/dev"
    P.say(f"/job-apply {good}?ref=x")
    assert P.srv.panel.queue == [("job_apply", P.srv.panel.queue[0][1], {"job_url": good})]


def test_home_keeps_refreshing_while_apps_are_queued(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.made[0].done, P.made[0].code = True, 0
    assert '<meta http-equiv="refresh" content="2">' in P.get("/")[1]


def test_queue_lines_are_not_steps_of_a_run():
    from govaios.audit.web import _runs
    ent = [({"kind": k, **x}, None) for k, x in [("flow_start", {"seq": 1, "flow": "a"}), ("run_queue", {"flow": "a"}), ("flow_end", {"flow": "a"})]]
    assert [e["kind"] for e in _runs(ent)[0][0]] == ["flow_start", "flow_end"]


def test_the_queue_is_cleared_and_audited_as_the_session_ends(panel):
    P = panel; _busy_with_inbox_queued(P)
    P.post("/end")
    es = _log(P.home)
    cleared = next(i for i, e in enumerate(es) if e["kind"] == "run_queue" and e["outcome"] == "cleared")
    # cleared inside end_session's lock, before session_end: an audit failure can never leave a queue behind
    assert cleared < next(i for i, e in enumerate(es) if e["kind"] == "session_end") and P.srv.panel.queue == []


def test_queue_is_empty_even_if_the_session_end_audit_fails(panel, monkeypatch):
    from govaios.audit.log import AuditLog
    P = panel; _busy_with_inbox_queued(P)
    real = AuditLog.append

    def append(self, kind, *a, **k):
        if kind == "session_end":
            raise OSError("disk")
        return real(self, kind, *a, **k)
    monkeypatch.setattr(AuditLog, "append", append)
    P.mono[0] += 31 * 60
    try:
        P.srv.panel.tick()
    except OSError:
        pass
    assert P.srv.panel.queue == []
    monkeypatch.setattr(AuditLog, "append", real)
    P.say(code_at(_secret(P), time.time() + 30))
    P.srv.panel.tick()
    assert len(P.made) == 1
