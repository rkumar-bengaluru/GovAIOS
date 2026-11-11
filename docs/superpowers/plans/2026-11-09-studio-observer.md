# Studio Observer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a flow meets a new page, the admin teaches it by doing it in Chrome. GOV-AIOS records it, shows "What I learned", and one Touch ID adds the page, its steps and the bank answers to the flow.

**Architecture:**
- The **engine** runs the lesson. It already holds Chrome's accessibility tree and the pinned window. A new `observer.py` turns desktop samples into events, and a lesson file is written under `lessons/`.
- The **panel** reviews the lesson. After Touch ID, `lessons.py` writes the page files, the flow case and the bank changes into the apps folder, then approves the new flow digest.
- At the learned page, the flow's `classify_page` step runs the learned steps on its next run.

**Tech Stack:** Python 3.14, pyobjc (ApplicationServices, Quartz), PyYAML, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-09-studio-observer-design.md`

## Global Constraints

- macOS + Chrome + the accessibility tree only. No website APIs, no keyboard recording, no new macOS permission.
- The observer reads only, and only the teach tab of the pinned window. It never clicks or types.
- Nothing changes a flow, a page file or the bank before the admin's Touch ID on the What I learned page. If Touch ID is denied, nothing is written.
- A submit click in a lesson is recorded and shown, but replayed as `hand_over`.
- Keep defaults: **Keep in bank** for short values. **Don't keep** for values over 200 characters, for one-time codes (`^\d{4,8}$`) and for secure fields (password: the step is *fill yourself*).
- A bank entry with `learned: true` may fill a `formfill.RESTRICTED` field. Others stay on the "yourself" list.
- Terms verdict per registrable domain, kept 90 days, values `allowed` / `forbidden` / `unclear` (`unclear` = forbidden). Exempt: `localhost`, `127.0.0.1`, and origins already in the flow's approved `destinations`.
- Lessons are kept unmasked (dev mode) under `lessons/`, 0600, last 30. A lesson ends on tab close, **Done**, **Cancel**, or after 30 minutes idle.
- A learned page case runs at most 10 learned pages per `classify_page` step (bounded, Rule 10).
- Panel copy follows the spec's wording: "JobLens can't go on: this page is new. Teach it?", "Teaching: do the page in Chrome. Close the tab when you're done.", "What I learned".

## Review Focus

1. **The admin switches to another tab mid-lesson** (to copy something from email or JobLens). Expected: nothing on the other tab is recorded, and the lesson continues when they come back. Test in Task 3: `test_events_on_another_tab_are_ignored`.
2. **Two identical buttons on a page** ("Next" at the top and the bottom). Expected: the step resolves to the one clicked (`index`), or is shown as *not sure what this was*. Never the wrong one. Test in Task 3: `test_duplicate_buttons_resolve_by_index`.
3. **The lesson reaches a page the flow already knows** (it moves back to a Greenhouse form). Expected: the existing page id is reused and no duplicate page file is written. Test in Task 6: `test_known_page_reuses_its_id`.
4. **Touch ID denied, or the flow file changed on disk since the lesson started.** Expected: nothing is written, and the panel says why. Test in Task 9: `test_approve_refused_writes_nothing` and `test_flow_changed_since_lesson_refused`.
5. **The admin types a cover letter or an emailed code.** Expected: it defaults to Don't keep, is never added to the bank silently, and the step stays a fix card. Test in Task 6: `test_long_text_and_codes_default_dont_keep`.

---

### Task 1: Spike: can we see the admin's clicks without a new permission?

Throwaway, run by the admin. It decides how the observer polls in Task 2.

**Files:**
- Create: `spikes/plan5/observe_spike.py`

- [ ] **Step 1: Write the spike.**
  - It polls every 30 ms for 60 s:
    - `Quartz.CGEventSourceButtonState(kCGEventSourceStateCombinedSessionState, kCGMouseButtonLeft)`;
    - `Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))`;
    - `AXUIElementCopyElementAtPosition` at each mouse-down;
    - Chrome's `AXFocusedUIElement`, and its `AXValue` when focus leaves it.
  - It prints one line per event: role, name, value length only.
  - It prints `tab gone` when the AXWebArea taken at start stops answering `AXRole`.
- [ ] **Step 2: The admin runs it from the signed app.** Command: `/Applications/gov-aios.app/Contents/MacOS/gov-aios python spikes/plan5/observe_spike.py`, or the closest packaged entry. They click a link, a button and a dropdown option, type in a field, then close the tab.
  - Expected: every click is printed with the right role and name, no permission prompt appears, and `tab gone` is printed on close.
- [ ] **Step 3: Record the result in the spec** under "The observer": which events were seen, and whether tab close is detectable. If tab close isn't detectable, the **Done** button is the only end signal. If clicks aren't detectable, clicks fall back to page-change inference with "you clicked X?" confirmation.
- [ ] **Step 4: Commit:** `git add spikes/plan5 docs/superpowers/specs/2026-11-09-studio-observer-design.md && git commit -m "spike(studio): observer polling on Chrome"`

### Task 2: Desktop observation primitives

**Files:**
- Modify: `govaios/desktop/macos.py`
- Modify: `tests/conftest.py` (`FakeDesktop`)
- Test: `tests/test_macos.py`

**Interfaces:**
- Produces, on `MacDesktop` and `FakeDesktop`:
  - `observe_sample(app) -> dict`, returning `{"down": bool, "pt": (x, y), "hit": handle|None, "focus": handle|None, "url": str, "title": str, "tab": bool}`;
  - `same(a, b) -> bool`;
  - `teach_tab(app) -> handle` (the current AXWebArea).
- `hit` is `None` unless the point is in the target pid and the pinned window.
- `tab` is False once the `teach_tab` handle no longer answers `AXRole`.
- `FakeDesktop` takes `samples=[...]` and pops one per call.

- [ ] **Step 1: Write the failing tests:**
  - `test_observe_sample_hit_outside_pinned_window_is_none`: mock `AXUIElementCopyElementAtPosition` to return an element whose `AXWindow` ≠ `_window`; assert `observe_sample("chrome")["hit"] is None`.
  - `test_observe_sample_reports_tab_gone`: the teach tab handle's `_attr(h, "AXRole")` returns None; assert `["tab"] is False`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_macos.py -k observe -v`. Expected: FAIL (no attribute `observe_sample`).
- [ ] **Step 3: Implement the three methods in `macos.py`.** Reuse `_attr`, `CFEqual`, `self._window` and `_target_pid`. Use the Task 1 calls, no event tap.
- [ ] **Step 4: Run the tests again.** Expected: PASS. Then run the full suite: `.venv/bin/python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit:** `feat(desktop): read-only observation sample for lessons`

### Task 3: Observer: samples to events

**Files:**
- Create: `govaios/observer.py`
- Modify: `govaios/studio.py`: expose `element_spec`
- Test: `tests/test_observer.py`

**Interfaces:**
- Consumes: Task 2 samples; `Node` trees from `web_root`.
- Produces:
  - `studio.element_spec(tree: Node, node: Node) -> dict | None`: the same rules as `draft_page`'s `spec_for` (stable id, else name; `index` for duplicates). Returns `None` unless `find_all(tree, spec, ...)` resolves to exactly `node`.
  - `class Observer(desk, app, same)`:
    - `feed(sample: dict, snapshot: Callable[[], Node]) -> list[dict]` returns the new events;
    - `.pages: list[dict]`, each `{"url", "title", "tree": Node, "events": [...]}`.
  - Event dict: `{"kind": "click"|"fill"|"choose"|"tick"|"attach", "spec": dict|None, "label": str, "value": str, "secure": bool, "submit": bool}`.
- Rules:
  - A new page starts when url or title changes on the teach tab.
  - A click is a `down` False→True transition with a `hit`.
  - A fill is recorded when focus leaves a text field, with its value from a fresh snapshot.
  - A choice is a combo or select whose shown value changed. A tick is a checkbox or radio state change.
  - `submit` is True when the clicked element's draft risk is `submit`.
  - Samples whose `tab` handle isn't the teach tab are ignored.

- [ ] **Step 1: Write the failing tests** with scripted samples and small `Node` trees:
  - `test_click_on_link_becomes_click_event`: the spec equals `{"role": "link", "name": "Apply Now"}`.
  - `test_fill_records_value_on_blur`: the value is `"rupak@x"`, `secure` False.
  - `test_secure_field_value_never_read`: role `native:AXSecureTextField` gives `value == ""` and `secure is True`.
  - `test_url_change_starts_new_page`: `len(o.pages) == 2`.
  - `test_events_on_another_tab_are_ignored` (Review Focus 1).
  - `test_duplicate_buttons_resolve_by_index` (Review Focus 2): the second "Next" gets `index: 1`. An unresolvable one gets `spec is None`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_observer.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `studio.element_spec` and `observer.Observer`.** Refactor `draft_page`'s inner `spec_for` into `element_spec` so both share it.
- [ ] **Step 4: Run** `tests/test_observer.py` and `tests/test_studio.py`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(studio): observer turns samples into lesson events`

### Task 4: Terms verdicts

**Files:**
- Create: `govaios/terms.py`
- Test: `tests/test_terms.py`

**Interfaces:**
- Produces:
  - `TERMS = "terms.json"`;
  - `domain(url) -> str`: the last two host labels, or three when the second-to-last is ≤ 3 chars and the last is 2 chars (`co.uk`, `co.in`). Use the comment `# shortcut: no public-suffix list, add one when a site is misjudged`;
  - `verdict(home, url, declared: list[str]) -> str | None`:
    - `"allowed"` for localhost, 127.0.0.1 or an origin in `declared`;
    - the stored value if it is under 90 days old;
    - else `None`;
  - `record(home, url, value, link, clause) -> None`: validates `value` in the three verdicts, `link` https, and `clause` ≤ 2000 chars, then writes 0600.

- [ ] **Step 1: Write the failing tests:**
  - `test_domain_groups_company_subdomains`: `domain("https://fa-ewji-saasfaprod1.fa.ocs.oraclecloud.com/x") == "oraclecloud.com"` and `domain("https://a.co.uk") == "a.co.uk"`.
  - `test_verdict_expires_after_90_days`.
  - `test_localhost_and_declared_need_no_check`.
  - `test_unclear_is_not_allowed`: `verdict(...) == "unclear"`. The callers treat anything but `"allowed"` as refused.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use `applyfiles.write_json` / `read_json`, or the same 0600 atomic write.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(terms): per-domain terms verdicts`

### Task 5: Engine: Teach this page

**Files:**
- Modify: `govaios/engine.py` (`do_classify_page`, `_ask`, new `teach`)
- Modify: `govaios/applyfiles.py` (`CARDS`, new `LESSON_LIVE = "apply/lesson.json"`)
- Modify: `govaios/audit/log.py` (`KINDS` += `"lesson"`)
- Test: `tests/test_teach.py`

**Interfaces:**
- Consumes: `Observer` (Task 3), `terms.verdict` (Task 4), `lessons.save` (Task 6: write Task 6 first, or stub it with its signature).
- Produces:
  - `CARDS` gains:
    - `"new_page": ("teach", "skip")`
    - `"terms": ("checked", "cancel")`
    - `"teaching": ("done", "cancel")`
    - `"lesson": ("approved", "discarded")`
  - `Runner._ask(body, tick=None)`: when `tick` is given, it is called every 0.2 s and may return a reply dict to end the wait.
  - `Runner.teach(step_id) -> NoReturn`, which always raises `Stop`:
    1. card `new_page`. On `skip`, `Stop("unexpected page")` as today.
    2. If `terms.verdict` isn't `"allowed"`: card `terms` (the panel shows the terms form, Task 8), then re-read. Still not allowed: `Stop("site terms do not allow a personal agent")`.
    3. Append the origin to `self.flow["destinations"]` in memory, then `gate("read_page", "read", destination=url)`, which asks Touch ID on first contact.
    4. Card `teaching`, with `tick` feeding `Observer`. Write `LESSON_LIVE` (`{"run", "lines": [str]}`, ≤ 50 lines) after each new event. End on `tab` False, `done`, `cancel` or 30 min idle.
    5. On `cancel`: `Stop("lesson cancelled")`. Otherwise `name = lessons.save(...)`, audit `lesson` with `outcome="recorded"` and `target=name`, then card `lesson` with `label=name`.
    6. `approved`: `Stop("page learned: it is used from the next run")`. `discarded`: `Stop("lesson discarded")`.
  - `do_classify_page`: on an unknown page, when `decide({"action": "teach", ...}) == "allow"` and `self.run_id` is set, call `self.teach(self.step)`. Otherwise the existing stop.

- [ ] **Step 1: Write the failing tests** with `FakeDesktop(samples=...)` and the `answer_cards` responder from `tests/test_job_apply_flow.py`:
  - `test_unknown_page_offers_teach_and_skip_keeps_old_stop`: the reason is `"unexpected page"`.
  - `test_teach_records_lesson_and_stops_task`: a lesson file exists, the task reason starts with `"page learned"`, and the next job runs.
  - `test_forbidden_terms_never_reads_the_page`: no `read_page` request audited for that origin, and no lesson file.
  - `test_cancel_writes_no_lesson`.
  - `test_flow_without_teach_permission_stops_as_before`.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_teach.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** as in the Interfaces block. `_ask`'s timeout stays `ASK_TIMEOUT_S` for every card except `teaching`, which uses the 30 min idle rule.
- [ ] **Step 4: Run** `tests/test_teach.py`, `tests/test_job_apply_flow.py` and `tests/test_web_sandbox.py`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(engine): teach this page - record a lesson from an unknown page`

### Task 6: Lessons: from events to a proposed change

**Files:**
- Create: `govaios/lessons.py`
- Test: `tests/test_lessons.py`

**Interfaces:**
- Produces:
  - `DIR = "lessons"`, `KEEP = 30`.
  - `save(home, flow_id, flow_digest, step_id, pages: list[dict]) -> str`: name `<YYYYmmdd-HHMMSS-ffffff>-<flow_id>.json`, 0600, prunes to KEEP. Trees are stored with `capture.tree`.
  - `load(home, name) -> dict`: validates `name` against `^[0-9-]{22}-[a-z0-9_]{1,64}\.json$`.
  - `propose(lesson, pages_dir, bank) -> dict`:
    ```
    {"pages": [{"id", "new": bool, "yaml": dict, "steps": [line]}],
     "bank": [{"op": "add"|"label"|"change", "key", "label", "value", "keep": "bank"|"job"|"drop", "sensitive": bool}]}
    ```
    where each `line` is `{"kind", "label", "target", "keep": bool}`.
  - Page id: an existing page file whose `identify` matches the lesson page's tree is reused (`new: False`). Otherwise `studio._slug`-based like `write_draft`, with the YAML trimmed to the used elements plus identification.
  - Steps per page:
    - clicks become `click` lines, except submit-rated ones, which become one `hand_over` line;
    - any fill, choose or tick on a page becomes a single `fill_form` line;
    - an `attach` becomes `attach_file`;
    - the last page ends with `hand_over` if it has none.
  - Bank ops:
    - a value equal to a bank answer: `label` op (only if the label is new);
    - a known label with a different answer: `change`;
    - otherwise `add`.
    - `sensitive` is `formfill.restricted(...) is not None`.
    - `keep` defaults follow the Global Constraints.

- [ ] **Step 1: Write the failing tests:**
  - `test_fill_events_collapse_to_one_fill_form_step`.
  - `test_submit_click_becomes_hand_over`.
  - `test_known_page_reuses_its_id` (Review Focus 3).
  - `test_bank_ops_add_label_change`: one of each, from a three-entry bank.
  - `test_long_text_and_codes_default_dont_keep` (Review Focus 5): a 201-char value and `"482913"` both have `keep == "drop"`.
  - `test_restricted_field_is_marked_sensitive`: label "Gender".
  - `test_lesson_name_validated`: `load(home, "../x.json")` raises `ValueError`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(studio): lessons propose pages, steps and bank changes`

### Task 7: Engine: run a learned page

**Files:**
- Modify: `govaios/engine.py` (`do_classify_page`, `steps`)
- Modify: `govaios/approvals.py`, only if `pages_used` misses pages referenced inside `do:`
- Test: `tests/test_teach.py`

**Interfaces:**
- Produces the flow YAML form `on_match: { <page>: { do: [<steps>], then: again|end } }`:
  - the allowed `do` actions are `click`, `fill_form`, `attach_file` and `hand_over`. Any other action stops at load with `Stop("learned steps: <action> not allowed")`;
  - `then: again` classifies the same step again;
  - `then: end` returns `("end",)`, and `steps()` stops the current list there (the job is done);
  - at most 10 learned cases run per `classify_page` call. The 11th gives `Stop("too many learned pages in a row")`.
  - `pages_used` must include every page referenced in `do` targets, so approval binds them.

- [ ] **Step 1: Write the failing tests:**
  - `test_learned_case_clicks_then_reclassifies`: page A → `do: [click A.next]`, `then: again` → page B `continue`.
  - `test_learned_end_finishes_the_job`: steps after the classify step never run, and the task is `done`.
  - `test_learned_do_rejects_navigate`.
  - `test_learned_pages_are_bound_by_approval`: editing a page used only inside `do` makes `flow_ok` False.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them, then the full suite.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(engine): learned page cases in classify_page`

### Task 8: Bank: learned answers

**Files:**
- Modify: `govaios/formfill.py` (`load_bank`, `add_answer`, `answer_for`, new `apply_ops`)
- Test: `tests/test_formfill.py`

**Interfaces:**
- Produces:
  - `Bank` entries gain `learned: bool` (default False).
  - `apply_ops(path, ops: list[dict]) -> None`: applies `add` / `label` / `change` ops with `keep == "bank"`, with `learned: true` on each entry it touches. It writes `answers.yaml.bak-<YYYYmmdd-HHMMSS>` first, then replaces atomically (`stage_text` + `os.replace`). The limits are those of `add_answer`.
  - `answer_for` returns a hit for a `RESTRICTED` field only when the matched entry has `learned` True.

- [ ] **Step 1: Write the failing tests:**
  - `test_learned_answer_fills_restricted_field`;
  - `test_unlearned_answer_still_left_for_admin`;
  - `test_apply_ops_backs_up_first`;
  - `test_apply_ops_skips_job_and_drop`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/test_formfill.py` and `tests/test_job_apply_flow.py`. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(bank): learned answers, applied with a backup`

### Task 9: Panel: teach cards, terms form, What I learned, approve

**Files:**
- Modify: `govaios/audit/web.py` (`CARD_TEXT`, `task_card`, new `lesson_page`, `lesson_post`, `terms_post`; `POSTS`; `PANEL_PATH`)
- Modify: `govaios/lessons.py`: add `apply(lesson, proposal, edits, apps_dir, bank_path) -> str`, which returns the new flow digest
- Test: `tests/test_panel_web.py`

**Interfaces:**
- Consumes: `lessons.load` / `propose` (Task 6), `formfill.apply_ops` (Task 8), `terms.record` (Task 4), `approvals.read_bound` / `Approvals.approve_flow`, `auth.prove`.
- Produces:
  - **Cards:**
    - `new_page`: the spec's text, buttons **Teach this page** / **Next job** (= `skip`). It is spoken once, like every card, and also posts a macOS notification with the same text (`osascript -e 'display notification …'`, with the text passed as an argument, never interpolated). Test: `test_new_page_card_notifies_once`;
    - `terms`: a link to the site, plus a form `POST /terms` with verdict radio, terms link and clause, then replies `checked`;
    - `teaching`: the live lines from `LESSON_LIVE`, buttons **Done** / **Cancel lesson**, refreshing every 2 s;
    - `lesson`: a link to `/lesson/<name>`.
  - **`GET /lesson/<name>`:** one section per page:
    - its id, *new* or *known*;
    - its step lines, each with a delete checkbox;
    - bank lines with a keep select (`bank` / `job` / `drop`) and the *sensitive* tag.
    - Buttons **Approve with Touch ID** / **Discard**.
  - **`POST /lesson/approve`:**
    1. Check the flow digest on disk equals `lesson["flow_digest"]`, else refuse: "JobLens changed since this lesson; teach it again".
    2. `auth.prove("Add what GOV-AIOS learned to <app>")`. Denied: write nothing.
    3. `lessons.apply` writes the page YAMLs, the flow's step case (`then: again` for all but the last page, `end` for the last) and destinations (each new origin), then calls `formfill.apply_ops`.
    4. `approve_flow(id, new_digest)`, audit `lesson` with `outcome="approved"`, `flow_hash` and counts.
    5. Reply `approved` to the engine card.
  - **`POST /lesson/discard`:** audit, then reply `discarded`.
  - A lesson whose flow is `None` (sandbox) writes only the page YAMLs into `apps/pages/`.

- [ ] **Step 1: Write the failing tests** with the existing `cc` fixture:
  - `test_teaching_card_shows_live_lines`;
  - `test_lesson_page_lists_pages_steps_and_bank`;
  - `test_approve_writes_flow_pages_bank_and_approves` (the digest is approved, and the bank `.bak` exists);
  - `test_approve_refused_writes_nothing` (Review Focus 4): `auth.prove` returns `(False, "denied")`; the flow, pages and bank bytes are unchanged;
  - `test_flow_changed_since_lesson_refused` (Review Focus 4);
  - `test_terms_post_validates_and_records`;
  - `test_lesson_name_traversal_refused`: `GET /lesson/..%2Fx` returns 404.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Write files with exclusive temp files, then `os.replace`, so a crash leaves the old flow.
- [ ] **Step 4: Run** `tests/test_panel_web.py`, then the full suite. Expected: PASS.
- [ ] **Step 5: Commit:** `feat(panel): What I learned - review and approve a lesson with Touch ID`

### Task 10: Studio New automation, Delete, no more Check apps

**Files:**
- Modify: `govaios/studio.py` (new `new_automation`; `write_draft` stops writing the Check app)
- Modify: `govaios/audit/web.py` (Studio form `POST /studio/new`; Delete on Drafts: `POST /apps/delete`)
- Test: `tests/test_studio.py`, `tests/test_panel_web.py`

**Interfaces:**
- Produces:
  - `studio.new_automation(flows_dir, name, url, browser) -> Path`: writes `studio_<slug>.yaml` exclusively, with these steps:
    - launch, Google, `verify_account`;
    - navigate `url`;
    - `classify_page` `{unknown: stop_and_report}`; `teach` makes the unknown start page teachable.
  - Its permissions:
    - `allow`: `[launch_application, navigate, read_page, click, fill_field, ask_admin, attach_file, teach]`;
    - `max_element_risk: modify`;
    - `destinations`: Google plus `url`'s origin, which must be https or localhost.
  - `POST /apps/delete`: only for files named `studio_*.yaml` or `check_*.yaml` in `apps/flows`, or a draft page no approved flow uses. It revokes the approval if there is one, deletes the file, and audits a `setting` entry with `field=delete`.

- [ ] **Step 1: Write the failing tests:**
  - `test_new_automation_is_teachable_from_its_start_page`: run it with a fake desktop on an empty page. The `new_page` card appears;
  - `test_write_draft_no_longer_writes_check_app`;
  - `test_delete_only_studio_and_check_apps`: deleting `job_apply.yaml` is refused;
  - `test_delete_draft_page_used_by_approved_flow_refused`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Update the existing tests that expected a Check app.
- [ ] **Step 4: Run the full suite.** Expected: PASS.
- [ ] **Step 5: Commit:** `feat(studio): new automation, delete drafts, drop Check apps`

### Task 11: Turn it on and live test plan

**Files:**
- Modify: `flows/job_apply.yaml` (`allow` += `teach`), `flows/web_sandbox.yaml` (`allow` += `teach`; the card offers Teach)
- Modify: `docs/joblens-integration-test.md` (new section D: Teach), `docs/backlog.md`
- Test: `tests/test_job_apply_flow.py`

- [ ] **Step 1: Write the failing test** `test_shipped_joblens_flow_allows_teach`: load `flows/job_apply.yaml` and assert `"teach"` is in `allow`.
- [ ] **Step 2: Run it.** Expected: FAIL.
- [ ] **Step 3: Edit both flows.** Write section D, the live test:
  1. Run `/joblens` with eClerx Ready. At Oracle, choose Teach this page.
  2. Terms: record your verdict.
  3. Touch ID.
  4. Do the page, then close the tab.
  5. Review, approve with Touch ID.
  6. Run again. Expected: it gets past the page you taught.

  Add the copy commands for the apps folder and the re-approval of JobLens and Web Sandbox.
- [ ] **Step 4: Run the full suite.** Expected: all pass.
- [ ] **Step 5: Commit:** `feat: JobLens and Web Sandbox can teach; live test plan D`
