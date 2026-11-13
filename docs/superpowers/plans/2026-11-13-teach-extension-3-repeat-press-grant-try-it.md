# Teach extension, plan 3: repeat, first-run press grant, Try it, refill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The acceptance lesson works: the admin teaches Review → Approve & promote on **one** Shortlisted profile, ticks Repeat, approves, and **Run** approves and promotes every remaining shortlisted profile, asking one Touch ID before its first press. Build steps 4 and 5 of the spec.

**Architecture:** Submit-level clicks on the admin's own apps (`localhost`, `127.0.0.1`) become real click steps. The policy check allows them only with a per-app press grant, which is tied to the flow digest and asked once by the engine before the first press. A new learned step `repeat` re-finds the list on every round and runs its sub-steps on the first item that still holds the target. The lesson page offers it with a cap. **Try it** builds the lesson into a private copy under `<home>/try/`, then runs that copy once with a one-run approval, stopping before any change-making press. A test-only script refills Shortlisted through JobLens's own API.

**Tech Stack:** Python 3 (`.venv`), pytest, PyYAML; the panel (`govaios/audit/web.py`, server-rendered HTML); the engine (`govaios/engine.py`).

**Spec:** `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (Goals 4, 10; "Pressing Approve & promote"; rules 1, 4, 5; Build order 4–5).

## Global Constraints

- Own apps are hosts `localhost` and `127.0.0.1` (any port except the panel's 8765, as `recorder.OWN`/`PANEL_PORT`). One constant: `policy.OWN_HOSTS = ("localhost", "127.0.0.1")`; `recorder.OWN` is replaced by it.
- **Submit-level presses happen only on own-app pages, and only with that app's press grant for its current digest.** On any other origin a submit click is denied, as today. A **payment** click is denied on every site, always (never asked).
- **The three Touch IDs stay separate** (rule 4): Try it, Approve, press grant. The prompt names which one it is: `"Try <app> once"`, the existing approve text, `"Let '<app>' press <names> on <site>?"`.
- Every press and every repeat round is in the audit log. Nothing is removed from it.
- Dev mode: item labels are logged unmasked (spec rule 1).
- No new dependency; no JavaScript framework; the extension is not changed in this plan.
- Branch `feat/teach-extension-plan3`; never `main`. Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Keep `docs/research/research_notes/GOV AIOS agent governance related work/site_terms_benchmarks.md` out of commits.

## Rulings made while planning (to report to the admin)

- **The repeat is offered on the lesson page, not in the side panel.** Why: the extension's Done already opens the lesson page, where steps are deleted and approved. Cost if wrong: the side panel later gains the same offer, reading `/ext/state`.
- **Only the shrinking repeat ("until none are left, at most N") is built.** A round whose item is still first on the list afterwards stops the run (`"<label> is still on the list after its round"`), so it never loops on one item. The "first N" form for lists that don't shrink is parked in `docs/backlog.md`. Why: it is the acceptance test, and spec rule 1 forbids index-based rounds.
- **No automatic hand-over card when every page of the lesson is on the admin's own apps** (the card the admin met on 2026-11-13). Outside-site lessons keep it.
- **Items are `row` or `article` containers** (`roles.yaml`), the nearest one holding exactly one match of the target.
- **Try it runs a private copy** of the built lesson (`<home>/try/flows/try_<app id>.yaml` plus its pages, workflow id `try_<app id>`, `try: true`). The approval for that copy is revoked when the run ends, so the Touch ID covers one run of the exact draft.

## Review Focus

1. **A revoked or edited app keeps pressing.** Expected: the grant is checked against the run's digest on every submit press, so an edited app asks again. Test in Task 1: `test_press_grant_is_tied_to_the_digest`.
2. **A submit button on an outside page of a mixed app.** Expected: denied even with a grant. Test in Task 1: `test_submit_click_outside_own_apps_is_denied_even_with_grant`.
3. **The list empties mid-run, or shows an empty-state message.** Expected: the repeat ends cleanly with `none_left`, and the flow goes on. Test in Task 3: `test_repeat_ends_when_none_left`.
4. **Approve fails on one profile** (the pop-up stays open, or the row is still there). Expected: the run stops, naming that profile, with the rounds already done. Test in Task 3: `test_repeat_stops_on_a_row_that_did_not_go`.
5. **Try it on a lesson whose step is rated `navigate` but named "Approve…".** Expected: Try still stops before it (the second safety net). Test in Task 5: `test_try_stops_before_a_change_named_button_rated_navigate`.

---

### Task 1: Press grant in policy, approvals and engine

**Files:**
- Modify: `govaios/policy.py` (`OWN_HOSTS`, `decide`)
- Modify: `govaios/approvals.py` (`presses` map)
- Modify: `govaios/engine.py` (`gate` gains `granted`, `do_click` submit path, `_press_grant`, `submit_buttons`)
- Modify: `govaios/recorder.py` (use `policy.OWN_HOSTS`)
- Test: `tests/test_policy.py`, `tests/test_approvals.py`, `tests/test_press_grant.py` (new)

**Interfaces:**
- Produces: `policy.OWN_HOSTS`; `policy.own(url) -> bool` (scheme `http`/`https`, hostname in OWN_HOSTS, port ≠ 8765); `decide(request, flow, approvals)` reads `request.get("granted", False)`.
- Produces: `Approvals.press_ok(flow_id, digest) -> bool`, `Approvals.grant_presses(flow_id, digest)`; `snapshot()` gains `"presses"`; `revoke_flow` and `revoke_all` also drop presses.
- Produces: the question names the app by `workflow.app` (Studio apps carry it), else its id; the site is `origin(url)`.
- Produces: `Runner.submit_buttons() -> list[str]`: the sorted, de-duplicated names (`name`, or `name_matches` without `^`/`$`) of every page element with risk `submit` that a `click` step targets anywhere in the flow (top-level steps, `steps`, `on_match` do-lists, `repeat` steps).
- Audit: kind `press_grant`, fields `decision`, `approver="admin"`, `channel="touch_id"`, `auth`, `flow_hash`, `reason` = the names joined with `", "`.

- [ ] **Step 1: Failing tests, policy.** In `tests/test_policy.py`:
  - `test_payment_click_is_denied_never_asked`: a click with risk `payment` and max `payment` → `"deny"`.
  - `test_submit_click_on_own_app_needs_grant`: max `submit`, destination `http://localhost:8100/discover` (declared, approved): `granted=False` → `"deny"`; `granted=True` → `"allow"`.
  - `test_submit_click_outside_own_apps_is_denied_even_with_grant`: destination `https://boards.greenhouse.io/x`, `granted=True` → `"deny"`.
  - `test_own_url`: `own("http://127.0.0.1:8100/")` is True; `own("http://127.0.0.1:8765/")`, `own("https://localhost.evil.com/")`, `own("file:///x")` are False.
- [ ] **Step 2: Failing tests, approvals.** `test_press_grant_is_tied_to_the_digest`: `grant_presses("a", "d1")`; `press_ok("a","d1")` is True and `press_ok("a","d2")` is False; after `revoke_flow("a")`, `press_ok("a","d1")` is False.
- [ ] **Step 3: Failing tests, engine** (`tests/test_press_grant.py`, a FakeDesktop on `http://localhost:8100` with a page whose element `approve` is `{role: button, name: "Approve & promote", risk: submit}`; flow max `submit`, a click step on it):
  - `test_first_submit_press_asks_once_then_presses`: two runs. The first asks exactly `"Let 'JobLens test' press Approve & promote on http://localhost:8100?"` and clicks. The second run asks nothing and clicks. One `press_grant` audit entry with `decision="allow"`.
  - `test_refused_grant_stops_before_the_press`: the ask returns False → Stop `"press grant refused"`, no click call, a `press_grant` entry with `decision="deny"`.
  - `test_edited_flow_asks_again`: grant for the old digest, the flow file changed and re-approved → asks again.
- [ ] **Step 4: Run them.** `.venv/bin/python -m pytest -q tests/test_policy.py tests/test_approvals.py tests/test_press_grant.py`. Expected: the new tests FAIL.
- [ ] **Step 5: Implement.**
  - `decide`: before the ceiling check, a click with risk `payment` → `"deny"`. A click with risk `submit` → `"deny"` unless `own(destination)` and `request.get("granted")`. The ceiling check and destination checks then run as today.
  - Engine `do_click`: when `spec["risk"] == "submit"`, take `url = current_url`. If `own(url)` and not `approvals.press_ok(fid, self.digest)`, call `_press_grant(url)`, which asks through `self.ask(question, reason)` as other Touch IDs do, audits, and grants on yes. Then call `gate("click", "submit", target=ref, destination=url, granted=approvals.press_ok(...))`.
- [ ] **Step 6: Run the whole suite.** `.venv/bin/python -m pytest -q`. Expected: all pass.
- [ ] **Step 7: Commit** `feat(policy): submit presses on own apps need a per-version press grant; payment clicks are never pressed`.

### Task 2: Lessons on own apps press their buttons

**Files:**
- Modify: `govaios/lessons.py` (`propose`, `build`, `preview`)
- Modify: `govaios/panel/lesson.py` (words for a press)
- Test: `tests/test_lessons.py`

**Interfaces:**
- Consumes: `policy.own(url)` (Task 1).
- Produces: a proposal line `{"kind": "click", ..., "press": True}` for a submit-rated click on an own-app page. `_do` turns it into `{"action": "click", "target": ...}` as for any click.

- [ ] **Step 1: Failing tests.**
  - `test_own_app_submit_click_is_a_press`: a JobLens lesson (pages on `http://localhost:8100/discover`) clicking Review, then `Approve & promote` (risk `submit`). Expected: the second line has kind `click` and `press: True`, with no hand-over line anywhere. The built flow's case `do` ends with a click on the approve element, and `wf["permissions"]["max_element_risk"] == "submit"`.
  - `test_outside_submit_click_stays_hand_over`: the same lesson on `https://acme.example/jobs`. Expected: a `hand_over` line, plus the automatic closing hand-over, as today.
  - `test_payment_click_on_own_app_stays_hand_over`: `Pay now` on localhost gives a `hand_over` line.
  - `test_build_never_lowers_max_element_risk`: a flow already at `submit`, with a lesson of navigate clicks only, stays at `submit`.
  - Lesson page: a `press` line reads `Press: Approve & promote (asks Touch ID before the first run's press)`.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - In `propose`, the "higher rating" branch: `submit` on `own(lp["url"])` gives the click line with `press: True`. `payment`, or `submit` elsewhere, gives `hand_over` as today.
  - The closing hand-over is appended only if some lesson page is not `own`.
  - `build` raises `max_element_risk` to `submit` when any kept line in the built cases has `press`, and never lowers it.
  - `preview` shows `press <label>` for these lines.
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(lessons): a submit-level click on your own app is taught as a press, not a hand-over`.

### Task 3: The `repeat` step in the engine

**Files:**
- Modify: `govaios/engine.py` (`LEARNED_ACTIONS`, `check_learned`, `do_repeat`, `do_click` round target)
- Test: `tests/test_repeat.py` (new; a FakeDesktop list page whose rows each hold a `cell` with a profile name and a `button` "Review". Clicking Review opens a pop-up with "Approve & promote". Clicking that removes the row, and a flag can make it fail to remove.)

**Interfaces:**
- Flow syntax (inside a learned `do` list):
  ```yaml
  - id: learned_localhost_joblens_2
    action: repeat
    item: localhost_joblens.review        # the round's first click target; an item holds exactly one
    max: 10                               # cap on successful rounds, 1..100
    steps:
    - {id: learned_localhost_joblens_3, action: click, target: localhost_joblens.review}
    - {id: learned_localhost_joblens_4, action: click, target: localhost_joblens.approve_promote}
  ```
- Produces: `engine.ITEM_ROLES = ("row", "article")`; `Runner.do_repeat(s)`; `engine.item_label(item, target) -> str` (the first non-empty `name` in `item.walk()` other than the target's, cut to 200).
- Audit: kind `repeat`, one entry per round with `target=<item label>` and `outcome="done"`, then one closing entry: `outcome="none_left"` or `"cap"`, with `reason="<k> done"`. On failure: `outcome="error"`, `target=<label>`.

- [ ] **Step 1: Failing tests.**
  - `test_repeat_does_every_row_until_none_left`: 3 rows → 3 rounds in row order (re-found each time), audit labels `["Ada", "Ben", "Cy"]`, a closing `none_left` entry, and the flow's next step runs.
  - `test_repeat_ends_when_none_left`: 0 rows plus a text "No profiles" → no click, `none_left` with `"0 done"`.
  - `test_repeat_cap_stops_at_max`: 5 rows, `max: 2` → 2 rounds, `cap`.
  - `test_repeat_stops_on_a_row_that_did_not_go`: the second row's approve leaves it in place → Stop `"repeat stopped on Ben after 1 done: Ben is still on the list after its round"`.
  - `test_repeat_shape_checked_at_load`: `max: 0`, `max: 101`, a nested repeat, an empty `steps`, or a first step that does not click `item` each raise `Stop` from `check_learned`, with a message naming the problem.
  - `test_repeat_round_click_is_the_item_s_own_button`: the round's first click lands on the first row's Review even though the page element carries `index: 1`.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement `do_repeat`** by rule 1. Each round:
  1. Run the page check for `item`'s page, the same way `page_element` does.
  2. The candidates are the `ITEM_ROLES` nodes (innermost first) holding exactly one match of the item's spec without `index`, in walk order.
  3. None → `none_left`.
  4. Otherwise take the first one. If its label equals the previous round's, stop with the error above.
  5. Set `ctx["round"] = (page_id, el_id, label)`, run `self.steps(s["steps"])`, then pop `ctx["round"]`.
  6. A `Stop` inside becomes `Stop(f"repeat stopped on {label} after {k} done: {e}")`, after the error audit.

  In `do_click`, when `ctx["round"]` is set and the target is its element, the node is that item's own match, re-found by label in a fresh snapshot, both before and after `scroll_into_view`. `check_learned` accepts `repeat` in `do` lists and validates its shape. Its sub-steps' ids count toward the duplicate check.
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(engine): repeat a taught round on every list item until none are left`.

### Task 4: Offer the repeat on the lesson page

**Files:**
- Modify: `govaios/lessons.py` (`repeatable(proposal, lesson) -> dict[int, int]`, `_cases`/`build` gain `repeats`)
- Modify: `govaios/panel/lesson.py` (`page`, `edits`)
- Modify: `govaios/audit/web.py` (`approve_lesson` passes `repeats`; `lesson_ctx` unchanged)
- Test: `tests/test_lessons.py`, `tests/test_panel_web.py`

**Interfaces:**
- Consumes: the `repeat` syntax and `ITEM_ROLES` (Task 3).
- Produces: `lessons.repeatable(proposal, lesson) -> {page index: line index}`. A page is repeatable at the first kept click line whose element carries `index` and sits in an `ITEM_ROLES` container of the page's stored tree. The repeat runs from that line to the end of the page's kept lines.
- Produces: `lesson_ui.edits(proposal, form)` returns `(deleted, keeps, repeats)`, where `repeats = {page index: cap}` comes from the form fields `rep:<i>=1` and `cap:<i>=<1..100>`. A bad cap raises `ValueError`. `build(..., repeats=None)` and `_cases(..., repeats=None)` wrap those lines into one `repeat` step with id `learned_<page>_r<k>`.

- [ ] **Step 1: Failing tests.**
  - `test_repeatable_finds_the_review_row`: the JobLens tree (two `row`s, each with Review). Lines are Shortlisted, Review (index 0), Approve & promote, so `repeatable` gives `{0: 1}`.
  - `test_build_wraps_the_round_in_repeat`: with `repeats={0: 10}`, the case is `do: [click shortlisted, repeat{item: …review, max: 10, steps: [click review, click approve_promote]}]`, and `engine.check_learned` accepts it.
  - `test_lesson_page_offers_repeat`: the page contains `Repeat from “Review” for every item on this list, until none are left, at most` and an `<input name='cap:0' type=number min=1 max=100 value=10>`.
  - `test_approve_with_repeat_writes_it`: posting `rep:0=1, cap:0=5` gives a flow with a `repeat` step whose `max` is 5. `cap:0=0` refuses with `Not approved:` and writes nothing.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Proposal digests are unchanged; the repeat choice is a form edit like Delete. Existing callers of `edits` take the third value.
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(lessons): offer Repeat on a list page, with a cap`.

### Task 5: Try it

**Files:**
- Modify: `govaios/audit/web.py` (`POST /lesson/try`; revoke the try approval when a `try_` run ends)
- Modify: `govaios/panel/lesson.py` (a **Try it** button and its line)
- Modify: `govaios/engine.py` (try mode in `do_click`)
- Test: `tests/test_panel_web.py`, `tests/test_try.py` (new)

**Interfaces:**
- Consumes: `lessons.build` with `repeats` (Task 4). `start_run(app, vals)`. `list_apps(flows_dir, home)`. `Approvals.approve_flow/revoke_flow`.
- Produces: `POST /lesson/try` (form: `name`, `p`, plus the same edit fields as approve). Then:
  1. Same checks as `approve_lesson`, up to `build`.
  2. Write the built flow, re-id'd `try_<app id>` with `try: true` in its workflow, to `<home>/try/flows/try_<app id>.yaml`, and the needed pages to `<home>/try/pages/`. The directories are 0700, and each Try replaces the previous try tree.
  3. Touch ID `"Try <app name> once"`.
  4. `approve_flow("try_<id>", digest)`, then `start_run` on that app.
  5. Audit kind `lesson`, `outcome="try"`.

  When the panel sees any `try_` run end, it calls `revoke_flow` on it. The real app's flow, pages, bank and approvals are untouched.
- Engine: when `self.flow.get("try") is True`, `do_click` stops before any click whose element risk is `submit`/`payment`, **or** whose name matches `lessons._CHANGE`/`_PAY`, with `Stop(f"Try it stops here: the real run will press {name}.")`. That message counts as a normal end in the run's card, not a failure.
- Lesson page: the line `Try it runs the steps once on the real pages and stops before any button that changes something.` above the **Try it** button.

- [ ] **Step 1: Failing tests.**
  - `test_try_stops_before_a_change_named_button_rated_navigate` (engine): a try flow clicking `Approve & promote` rated `navigate` → Stop with the exact message above, and no click call.
  - `test_try_stops_before_submit` (engine): the same with risk `submit`, and no press grant asked.
  - `test_try_runs_a_copy_and_leaves_the_app_alone` (panel): POST `/lesson/try` asks exactly `"Try Approve shortlisted once"`, starts a run whose flow path is under `<home>/try/flows/`, and leaves the real flow file bytes, the approvals for the real app and the lesson file unchanged.
  - `test_try_approval_is_revoked_after_the_run` (panel): after the fake run ends, `try_studio_approve_shortlisted` is not in approvals.
  - `test_try_refused_touch_id_starts_nothing`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse `approve_lesson`'s checks by moving them into one helper both handlers call. Do not copy them.
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(teach): Try it runs the lesson once on a private copy and stops before any change`.

### Task 6: The refill script, backlog, and the result line

**Files:**
- Create: `scripts/refill_shortlisted.py`
- Modify: `docs/backlog.md` (the "first N" repeat; side-panel repeat offer)
- Test: `tests/test_refill.py`

**Interfaces:**
- `scripts/refill_shortlisted.py [--n 4]` (n in 1..10):
  1. POST `n` test listings to `http://127.0.0.1:8100/api/discover/listings`, the endpoint `delivery.TARGETS["joblens"]` already names. Use `delivery.send`. Never any other host.
  2. Each listing is `{"title": "GOV-AIOS test profile <stamp>-<i>", "source": "GOV-AIOS test", "company": "Test Co", "url": "http://localhost/test/<stamp>-<i>", "jd_text": <a fixed ≥ MIN_JD_CHARS test description>}`. `<stamp>` is the UTC time `YYYYmmddHHMMSS`, so JobLens never sees a duplicate.
  3. Poll `GET /api/discover/listings/<id>` every 2 s, up to 120 s.
  4. Print one line per listing: `<id> <status>`. Then print `shortlisted: <n>` from `GET /api/discover/listings/counts`.
  5. Exit 0 if every listing has a status, 1 if JobLens is unreachable.
- [ ] **Step 1: Failing test** (`tests/test_refill.py`, with `send` and the GETs stubbed): `test_refill_posts_unique_test_listings_to_joblens_only` checks for 4 POSTs, all to `127.0.0.1:8100`, with distinct titles and urls and `source == "GOV-AIOS test"`, and the printed lines. `test_refill_unreachable_exits_1`.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use stdlib only (`urllib`), as `delivery.send` does.
- [ ] **Step 4: Run the whole suite.** Expected: all pass.
- [ ] **Step 5: Commit** `feat(scripts): refill JobLens Shortlisted with test profiles`.

### Task 7: The admin's acceptance run and the verdict

**Files:**
- Modify: `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (append "Plan 3 result (date)")

- [ ] **Step 1: The admin runs it.**
  1. Rebuild and install.
  2. Run `.venv/bin/python scripts/refill_shortlisted.py --n 4`.
  3. In Chrome: Teach on `http://localhost:8100/`, then Discover → Shortlisted → Review (first profile) → Approve & promote, then Done, naming it `Approve shortlisted`.
  4. On the lesson page: tick **Repeat**, optionally press **Try it** (it stops at Approve & promote), then **Approve**.
  5. **Run**: one press-grant Touch ID, then every remaining shortlisted profile is approved.
  6. Run again: no grant asked.

  Paste the result.
- [ ] **Step 2: Record it in the spec:** the verdict, the audit's `repeat` and `press_grant` entries (labels, counts), and anything that failed.
- [ ] **Step 3: Commit** `docs(spec): teach extension plan 3 result`.
