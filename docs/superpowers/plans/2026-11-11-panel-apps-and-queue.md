# Panel: Home is the chat, an Apps page, and a run queue — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run never refuses because another app is running (it queues); approved apps move from the left rail to an Apps page of cards; Home shows the newest first with the live card pinned under the Talk box.

**Architecture:** Everything lives in `make_server` in `govaios/audit/web.py` (server-rendered HTML, no JS). The queue is a list on `panel`; the run start in `command()` becomes one function that both a typed Run and the queue use; `tick()` (already called every second) starts the next queued app once the live run is done and reported. `App` gains the flow's description.

**Tech Stack:** Python 3.14, stdlib `http.server`, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-11-panel-apps-and-queue-design.md` (only the part above "Project 2").

## Global Constraints

- No JavaScript; pages auto-refresh with the existing `<meta http-equiv="refresh">`.
- Run checks stay as today: live panel session, flow approved with an unchanged digest, inputs valid (`invalid_input`), ticket from `tickets.create(home, app.id, app.digest, panel.session.id, vals or None)`.
- Copy (exact strings): `"<app> queued #<n>."`, `"<app> is already queued (#<n>)."`, `"Starting <app> (queued)."`, `"<app> left the queue: <why>."`, `"Queue cleared: <why>."`, `"<app> taken out of the queue."`.
- Nav order and labels: Home `/`, Apps `/apps`, Studio `/studio`, Marketplace `/market`, Audit log `/audit`, Approvals `/approvals`.
- Only flows queue; `run/start claude|codex` is untouched.
- Stay on branch `feat/panel-apps-queue`. Never commit `docs/research/research_notes/GOV AIOS agent governance related work/site_terms_benchmarks.md`.

## Review Focus

(Pre-flight architect review folded in: queue-jump guard, digest-before-approval, one lock for check+start, browser sign-in check, failed-start drop.)

1. A queued app whose flow was edited or revoked while it waited → dropped with a reason, never started (Task 1 test `test_queued_app_edited_while_waiting_is_dropped`).
2. The session expires or the screen locks while apps are queued → queue cleared, nothing starts later even after a new session (Task 1 `test_session_end_clears_the_queue`).
3. Two ticks in a row after a run ends → the next app starts exactly once (Task 1 `test_next_starts_once`).
4. A run that ends while the admin is answering its card → the card is gone, the next app starts, Home still loads (Task 1 `test_end_on_a_card_starts_the_next`).
5. An app name with HTML in it on a card → escaped (Task 2 `test_apps_page_escapes_names`).

---

### Task 1: The run queue

**Files:**
- Modify: `govaios/audit/web.py` (`make_server`: `panel` namespace, `end_session`, `tick`, `command`, the `/signout` handler, the POST route table)
- Test: `tests/test_panel_queue.py` (new; reuse the `panel` fixture and `_open`/`_log` helpers by importing them from `tests/test_panel_web.py`, or move the fixture to `tests/conftest.py` if import is awkward)
- Modify: `tests/test_panel_web.py::test_busy_text` (now queues)

**Interfaces:**
- Produces: `panel.queue: list[tuple[str, str, dict | None]]` — `(app id, digest at queue time, inputs)`, in order.
- Produces: `start_run(hit: App, vals: dict | None, queued: bool = False) -> None` inside `make_server` (the body of today's `elif kind == "run":` branch, plus `tell("Starting <app> (queued).")` when `queued`).
- Produces: `clear_queue(why: str) -> None` — empties `panel.queue` and tells `"Queue cleared: <why>."` only when it was non-empty; audits `run_queue` with `outcome="cleared"`, `reason=why`.
- Produces: POST `/unqueue` with form field `flow` (app id) → removes it, tells `"<app> taken out of the queue."`, redirects to the `next` form field if it is `/` or `/apps`, else `/`.
- Audit: kind `run_queue`, fields `flow`, `outcome` in `queued | started | dropped | removed | cleared`, plus `reason` for dropped/cleared. Never inputs.

- [ ] **Step 1: Write the failing tests** in `tests/test_panel_queue.py`:

```python
def test_run_while_busy_queues_then_starts_when_the_run_ends(panel):
    P = panel; _open(P); _approve(P, "morning_inbox_briefing")
    P.say("run joblens"); P.say("run inbox briefing")
    assert len(P.made) == 1 and "Inbox briefing queued #1." in P.get("/")[1]
    P.made[0].done, P.made[0].code = True, 0
    P.srv.panel.tick()
    assert len(P.made) == 2 and P.made[1].started and "Starting Inbox briefing (queued)." in P.get("/")[1]
    assert [e["outcome"] for e in _log(P.home, "run_queue")] == ["queued", "started"]

def test_next_starts_once(panel):          # two ticks after the end start one run
def test_typed_run_never_jumps_the_queue(panel):   # live run done but not yet reported, Inbox briefing queued; typed "run joblens" → "JobLens queued #2."; tick → Inbox briefing starts, JobLens not; exactly one start per app over the following ticks
def test_a_failed_start_is_dropped_and_told(panel):   # launcher raises for the queued app → "… left the queue: it did not start." and run_queue outcome dropped
def test_no_browser_signed_in_clears_the_queue(panel):   # P.wall[0] += 9*3600 (browser sign-ins expire), tick → "Queue cleared: signed out."; assert on P.srv.panel.convo, not on GET /
def test_same_app_queues_once(panel):      # 2nd "run inbox briefing" → "Inbox briefing is already queued (#1)."
def test_queued_app_edited_while_waiting_is_dropped(panel):
    # queue Inbox briefing, then append a comment to its yaml (digest changes), end the live run, tick:
    # no 2nd run; Home has "Inbox briefing left the queue: it changed since it was queued."; run_queue outcome dropped
def test_revoked_while_waiting_is_dropped(panel):   # reason text "it is no longer approved."
def test_session_end_clears_the_queue(panel):
    # queue one, P.mono[0] += 31*60, tick → "Queue cleared: the session ended." and panel.queue == []; reopen with a fresh code
    # (code_at(secret, time.time() + 30): the Verifier refuses a replayed step) + tick: no start
def test_end_session_and_emergency_stop_clear_the_queue(panel):   # POST /end; and (home/"STOPPED") + tick
def test_signout_clears_the_queue(panel):   # POST /signout; assert on P.srv.panel.convo / panel.queue (GET / is signed out now)
def test_end_on_a_card_starts_the_next(panel):   # live run done with stopped_reason set → next starts, "/" returns 200
def test_unqueue(panel):   # POST /unqueue flow=morning_inbox_briefing → removed, outcome removed; "unqueue inbox briefing" in Talk does the same
def test_queued_inputs_are_checked_when_queued(panel):   # approve job_apply first, start JobLens so a run is live, then queue job_apply with a bad value → "That isn't a valid …", not queued
```

`_approve(P, id)`: approve the flow in `approvals.json` the way the fixture approves JobLens. The reason strings are exact: `"it changed since it was queued."`, `"it is no longer approved."`, `"the session ended."`, `"signed out."`.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_panel_queue.py -q`
Expected: FAIL (`queued #1` not found; `/unqueue` 404).

- [ ] **Step 3: Implement**

- `command()`: queue when `kind == "run" and (live() or panel.queue or panel.told is not panel.run)` — a run that is done but not yet reported, or apps already waiting, must not be jumped (else an app runs twice and the finished run is never reported). On that path: run `invalid_input` first (bad → existing message, not queued); already queued → `"<app> is already queued (#n)."`; else append `(hit.id, hit.digest, vals or None)`, audit `queued`, tell `"<app> queued #<n>."`. `kind == "run"` and not live → `start_run(hit, vals)`. Add `unqueue <words>`: strip the leading "unqueue" ("unqueue" is not in `_FILLER`), then `apps.match` on the rest.
- `tick()`, after `report()`: in ONE `with panel.lock:` block (checks, pop and start together): if `not live()`, `panel.queue`, `panel.told is panel.run` (the last run was reported, or there was none), the code session is active, `not runstate.stopped(home)`, and at least one browser sign-in is unexpired (`state["sessions"]` under `sign_lock`, `now() - signed_in_at < SIGNIN_S`; none → `clear_queue("signed out.")`) → loop: pop the first entry and look it up in fresh `apps()` by id: missing → drop `"it is no longer approved."`; **digest first**: fresh digest != queued digest → drop `"it changed since it was queued."` (an edited flow is also unapproved, so this check must come before approval); not approved → drop `"it is no longer approved."`; else audit `started` (audit first, then apply) and `start_run(app, vals, queued=True)` inside `try`: an exception drops it as `"it did not start."` (audited `dropped`). A drop moves on to the next entry in the same tick; at most one start per tick.
- `end_session()` calls `clear_queue("the session ended.")` inside its existing `with panel.lock:` block, right after `panel.session.end(...)` and before `if sid is None: return` (covers expiry, screen lock, emergency stop, End session); the `/signout` handler calls `clear_queue("signed out.")`.
- `start_run` sets `panel.told = None`-safe state exactly as today's branch (`panel.run, panel.app, panel.card, panel.run_id`).

- [ ] **Step 4: Update `test_busy_text`**: the 2nd `run joblens` while live now says `"JobLens queued #1."`, and `len(P.made) == 1` still holds until the run is done and `tick()` runs.

- [ ] **Step 5: Run the panel tests**

Run: `.venv/bin/python -m pytest tests/test_panel_queue.py tests/test_panel_web.py -q`
Expected: PASS.

- [ ] **Step 6: Commit** — `feat(panel): a run queue: Run while busy waits its turn`

---

### Task 2: The Apps page, and the left rail keeps only the navigation

**Files:**
- Modify: `govaios/panel/apps.py` (`App` gains `title: str = ""` = the flow's `workflow.name`, shown as the card's description line: flows have no separate description field)
- Modify: `govaios/audit/web.py` (`_page` nav; `PANEL_PATH` gains `/apps`; new `apps_page(csrf)`; GET route; `talk()` passes no rail; `approvals()` gains the drafts list)
- Test: `tests/test_panel_web.py`, `tests/test_panel_apps.py`, `tests/test_cli.py::test_agent_missing_apps_dir` (its rail assertion)

**Interfaces:**
- Consumes: `panel.queue` (Task 1), POST `/unqueue` with `next=/apps`.
- Produces: GET `/apps` → `apps_page(csrf)`.

- [ ] **Step 1: Write the failing tests** (in `tests/test_panel_web.py`):

```python
def test_nav_is_home_apps_studio_market_audit_approvals(panel):
    nav = re.search(r"<nav class=rail.*?</nav>", panel.get("/")[1], re.S)[0]
    assert re.findall(r">([A-Za-z ]+)</a>", nav) == ["Home", "Apps", "Studio", "Marketplace", "Audit log", "Approvals"]
    assert "<h2>Approved</h2>" not in nav and "<h2>Drafts</h2>" not in nav

def test_apps_page_shows_approved_apps_as_cards(panel):
    body = panel.get("/apps")[1]
    assert body.count("class=appcard") == 1 and "JobLens" in body and "Inbox briefing" not in body   # drafts are not here
    assert "Himalayas Job Vetting" in body            # the flow's description
    assert "name=text value='run himalayas job vetting'" in body   # Run posts the same command Talk takes

def test_apps_card_shows_running_and_queued(panel):   # live JobLens → "Running…" linking to "/"; queued app → "Queued #1" + /unqueue form with next=/apps
def test_app_with_inputs_runs_through_its_input_card(panel):   # job_apply's Run posts text "/<slug>" (the existing input card)
def test_apps_card_shows_last_started(panel):   # after a run_start in the log, the card shows its time (from _apps_summary's last_time)
def test_apps_page_escapes_names(panel):   # an app named "<b>x</b>" appears as &lt;b&gt;
def test_drafts_are_on_approvals(panel):   # /approvals lists Inbox briefing under "Waiting for approval" with the Approve… form posting /approve
def test_coding_agents_line_is_on_apps(panel):   # the "Governed: type /claude" line moves from the rail to /apps
```

- [ ] **Step 2: Run them to verify they fail** — `.venv/bin/python -m pytest tests/test_panel_web.py -q -k "nav_is or apps_ or drafts_are or coding_agents"` → FAIL.

- [ ] **Step 3: Implement**

- `_page`: nav items exactly as in Global Constraints; `here` for `/apps` is `"/apps"`. `talk()` no longer builds `ok`/`drafts`/`cc_li` into the rail.
- `apps_page(csrf)`: `<h1>Apps</h1>` then `<div class=grid>` of `<section class=appcard>` per approved app: `<h2>` name, `<p>` title, `<p class=m>Last started <time></p>` (or "Never run"), and one control: live app → `<a class=go href='/'>Running…</a>`; queued → `Queued #n` + `/unqueue` form; else a `/say` form with hidden `text` = `"/<slug(name)>"` if `flow_inputs(path)` else `"run " + id.replace("_", " ")`. Then the coding-agents list. CSS: `.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(16rem,1fr));gap:1rem}` added to `CSS` (3 per row on a normal window, fewer when narrow).
- `approvals()`: a `<h2>Waiting for approval</h2>` list with the drafts' Approve… and delete forms, moved as-is from `talk()`; `/approve` and the delete form redirect back to `/approvals`.

- [ ] **Step 4: Update the tests that read the old rail** (`test_cli.py` line ~755 now asserts `"<h2>Approved</h2>" not in` the Talk page, and any `test_panel_web.py` test that finds an Approve… form on `/` looks on `/approvals`).

- [ ] **Step 5: Run the panel and cli tests** — `.venv/bin/python -m pytest tests/test_panel_web.py tests/test_panel_apps.py tests/test_cli.py tests/test_panel_queue.py -q` → PASS (with the screen unlocked).

- [ ] **Step 6: Commit** — `feat(panel): an Apps page of cards; the rail keeps only the navigation`

---

### Task 3: Home newest first, the live card pinned under the Talk box

**Files:**
- Modify: `govaios/audit/web.py` (`talk()` body order; `tasks_card()` order)
- Test: `tests/test_panel_web.py`

**Interfaces:** none new.

- [ ] **Step 1: Write the failing tests**:

```python
def test_home_is_newest_first_with_the_talk_box_on_top(panel):
    P = panel; _open(P); P.say("run mail"); P.say("run joblens")
    body = P.get("/")[1]
    assert body.index("class=cmd") < body.index("class=talk")
    assert body.index("Starting JobLens.") < body.index("I don&#x27;t know that app.")   # newest first

def test_the_live_card_stays_under_the_talk_box(panel):   # with a waiting card and 5 newer talk lines, the card's form precedes every talk line
def test_joblens_jobs_newest_first(panel):   # tasks.json with n=1,2 → job 2 listed before job 1
```

- [ ] **Step 2: Run to verify they fail** — `-k "newest_first or live_card_stays"` → FAIL.

- [ ] **Step 3: Implement**: in `talk()` the order becomes `who, nodir, otp, cmd form, card(csrf), ans, steps, tasks_card(), result_card(), <ul class=talk>` with `convo` reversed; `tasks_card()` lists `reversed(ts)`. Keep the `autofocus` rule as is.

- [ ] **Step 4: Run the whole suite** — `.venv/bin/python -m pytest tests/ -q` → all pass with the screen unlocked (when locked, the known `test_macos` failures and `test_cli::test_agent_missing_apps_dir` are environmental).

- [ ] **Step 5: Commit** — `feat(panel): Home shows the newest first, the live card under the Talk box`
