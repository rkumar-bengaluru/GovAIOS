# Teach: dropdowns and checkboxes (G3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach records a native dropdown pick and a checkbox tick as taught steps the runner replays exactly, and a
G2 read can follow a navigate press that changed the address on the same page (P2, A1).

**Architecture:** The extension reports changed selects and checkboxes by name in the existing `types` list. The
recorder reads their values from the AX tree as new events, `pick` and `tickbox`. `lessons.propose`/`build` turn
those into `choose`/`tick` steps. The runner sets a field through the existing `Runner._enter("select")` path, or
with one click, then reads it back exactly. A `wait_url` click waits for a new same-origin address and the page load
before a same-page `read_table`.

**Tech Stack:** Python 3 (pytest, PyYAML), PyObjC AX on macOS, Chrome MV3 content script.

**Spec:** `docs/superpowers/specs/2026-11-21-teach-choices-design.md` (architect amendments folded in).

## Global Constraints

- Full suite: `.venv/bin/python -m pytest -q -p no:warnings`. It must pass at the end of every task.
- Never work on main. Branch `feat/teach-choices`. Never `git add -A`; add files by name. Never add
  `docs/research/research_notes/GOV AIOS agent governance related work/site_terms_benchmarks.md`.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Recorder event kinds are `pick` (dropdown) and `tickbox` (checkbox), never the observer's `choose`/`tick`.
- Proposal line kinds and flow step actions are `choose` (`value`: option text, str) and `tick` (`value`: bool).
- The runner's permission for both is `fill_field`, gated at `modify` with destination = the current URL. Flows that
  have them get `fill_field` in `allow` and `max_element_risk` at least `modify`.
- The audit never records a chosen value, as with typing.
- Exact stop texts:
  - `option not offered: <label>`;
  - `the choice did not hold: <label>`;
  - `the press went to another site`;
  - `the page did not change after <label>`;
  - `could not open the menu: <label>`.
- Teaching line texts: `choose <value> in <label>`, `tick <label>`, `untick <label>`.
- The snapshot fix touches only the neutral roles `checkbox` and `radio`.

## Review Focus

1. A select already showing the taught option: no click, no keys, audit `outcome: already` (Task 3 test).
2. A type-ahead prefix pick ("Engineering" picks "Engineering Ops"): stops with `the choice did not hold` (Task 3
   test).
3. A box already in the taught state is never clicked. A box already ticked when the taught state is untick is
   clicked once (Task 3 tests).
4. The admin deletes the filter click on the lesson page: build refuses the same-page read with READ_LAST, never puts
   `wait_url` elsewhere (Task 5 test).
5. A navigate press that lands on another origin (an O4 form): stop before any read (Task 3 test).

---

### Task 1: Snapshot values for checkboxes, page-loaded probe, extension reports selects and checkboxes

**Files:**
- Modify: `govaios/desktop/macos.py` (`_snap`; add `loaded`)
- Modify: `extension/content.js` (the `onInput` field test)
- Modify: `tests/conftest.py` (`FakeDesktop.loaded`)
- Test: `tests/test_macos.py`, `tests/test_extension_files.py`

**Interfaces:**
- Produces: `MacDesktop.loaded(app) -> bool | None`. True or False from `AXLoaded` on the focused window's
  `AXWebArea`; None when there's no web area or the attribute is missing. `FakeDesktop.loaded(app)` returns None.
- Produces: snapshot `Node.value` for neutral `checkbox`/`radio` is `"1"` or `"0"` when AXValue is a number.

- [ ] **Step 1: Failing tests** in `tests/test_macos.py`, using the existing `_snap_tree` helper (extend it to carry
  a value per element if needed):
  - `test_snap_checkbox_number_value`: an `AXCheckBox` with AXValue `1` → `.value == "1"`; with `0` → `"0"`;
  - `test_snap_radio_number_value`: an `AXRadioButton` (not under a tab group) with AXValue `1` → `"1"`;
  - `test_snap_heading_number_value_unchanged`: an `AXHeading` with AXValue `2` → `.value == ""`;
  - `test_loaded_reads_web_area`: True, False, and None when the attribute is missing.
- [ ] **Step 2: Failing tests** in `tests/test_extension_files.py`:
  - `test_content_js_reports_selects_and_checkboxes`: the source contains `HTMLSelectElement` and `"checkbox"`, and
    the `onInput` handler still starts with the `isTrusted` check;
  - the existing no-`.value` test still passes.
- [ ] **Step 3: Implement.**
  - `_snap`: for `neutral in ("checkbox", "radio")` and a value that is an int or bool, use `str(int(value))`; else
    `_s(value)`.
  - `loaded(app)`: find the focused window's `AXWebArea` the way `current_url` does, read `AXLoaded`, return
    `bool(v)` or None.
  - content.js: the `onInput` test also accepts `el instanceof HTMLSelectElement && !el.multiple` and
    `el instanceof HTMLInputElement && el.type === "checkbox"`. Update the file's header comment, and read no
    `.value`.
- [ ] **Step 4: Run** the suite. job_apply and formfill tests must still pass: radios now read as filled. If one
  fails, it was relying on the bug. Fix the test's expectation only when the new reading is the correct one, and
  write why in the report.
- [ ] **Step 5: Commit** `fix(desktop): checkbox and radio values reach the snapshot; extension reports selects and checkboxes`.

### Task 2: Recorder saves pick and tickbox events

**Files:**
- Modify: `govaios/recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Consumes: Task 1's `"1"`/`"0"` checkbox values.
- Produces: lesson events
  - `{"kind": "pick", "spec", "label", "value": <option text>, "secure": False, "risk": "modify", "sure": True, "before"}`;
  - `{"kind": "tickbox", ..., "value": "1" | "0"}`.
- Produces: `_line` for `pick`: `<title>: choose <value> in <label>`; for `tickbox`: `<title>: tick <label>` or
  `<title>: untick <label>`.

- [ ] **Step 1: Failing tests** in `tests/test_recorder.py`, in the style of `test_type_records_value_read_from_the_tree`:
  - `test_pick_records_selected_option`: a `popup_button` "Department" with value "Engineering" and
    `native:AXMenuItem` children "All departments", "Engineering", "Sales". `save("Department")` gives the pick event
    with value "Engineering". Its spec finds the popup once. The stored `before` tree has no "Engineering" value on
    the popup. The line is `... : choose Engineering in Department`;
  - `test_pick_option_not_in_menu_refused` (value "Ops" with no such item) and `test_pick_option_twice_refused`
    (two items "Engineering") give no pick event, note `MISMATCH`;
  - `test_pick_empty_value_refused`: note `MISMATCH`;
  - `test_tickbox_records_state`: a lone `checkbox` "Overdue only" with value "1" gives a tickbox event with value
    "1" and the line `tick Overdue only`; with "0", the line `untick Overdue only`;
  - `test_tickbox_in_a_group_held`: two checkboxes in one group give no event and note `HELD`;
  - `test_pick_restricted_label_held`: a popup labelled "Gender" gives note `HELD`;
  - `test_latest_pick_wins`: two presses picking different values in the same popup keep one pick event, the latest.
- [ ] **Step 2: Implement.**
  - Rename `_type` to `_field`; keep the one-snapshot-per-press behaviour.
  - Matching roles are `TYPED + ("popup_button", "checkbox")`, exactly one by `_plain(name)`.
  - For popup and checkbox, build the `Field` for the restricted check from `formfill._read(root)` for that node.
    Hold it back (HELD) when its kind is `multi` or `restricted()` says so.
  - Popup: the value must be non-empty, hold no control character (`MULTI` else), and equal exactly one
    `native:AXMenuItem` name under the node (`MISMATCH` else).
  - Checkbox: the value is `"1"` if `n.value == "1"` else `"0"`.
  - `_save`'s replace rule: drop an earlier event with the same `kind` and `spec`, for kinds `type`, `pick` and
    `tickbox`.
- [ ] **Step 3: Run** the suite.
- [ ] **Step 4: Commit** `feat(recorder): record dropdown picks and checkbox ticks`.

### Task 3: Runner choose, tick and wait_url steps

**Files:**
- Modify: `govaios/engine.py`
- Create: `tests/test_choice_step.py`

**Interfaces:**
- Consumes: `Desktop.loaded(app)` (Task 1); `Runner._enter`; `Runner.page_element`; `menu_open`.
- Produces:
  - `engine.check_choice(d, pages=None)`;
  - `LEARNED_ACTIONS` gains `"choose"` and `"tick"`;
  - `Runner.do_choose(s)` and `Runner.do_tick(s)`;
  - `do_click` honours `s.get("wait_url")`.

- [ ] **Step 1: Failing tests** in `tests/test_choice_step.py`. Build the harness the way `tests/test_read_table.py`
  does: a page YAML with elements `dept` `{role: popup_button, name: Department, risk: modify}`, `overdue`
  `{role: checkbox, name: Overdue only, risk: modify}` and `filter` `{role: button, name: Filter, risk: navigate}`;
  a flow with permissions `allow: [read_page, fill_field, click, extract_visible_text, report]` and
  `max_element_risk: modify`; a `Desk(FakeDesktop)` whose `web_root` returns the current state and whose `click` and
  `press` change it. Tests:
  - `test_choose_already_set_does_nothing`: no click and no keys; the audit has `action: choose_option`,
    `outcome: already`, and no value;
  - `test_choose_sets_and_holds`: menu open, type-ahead sets value "Engineering", Enter. No stop, and the audit
    outcome is `done`;
  - `test_choose_prefix_pick_stops`: after Enter the value is "Engineering Ops" → Stop `the choice did not hold: Department`;
  - `test_choose_option_not_offered_stops` (no item, or two equal items) → `option not offered: Department`;
  - `test_choose_menu_not_open_stops` → `could not open the menu: Department`, with no Enter pressed;
  - `test_choose_over_modify_denied`: element risk `submit` → Stop containing `denied`;
  - `test_tick_already_in_state_no_click`;
  - `test_tick_untick_clicks_once`: value "1" with taught False → one click, then the value reads "0";
  - `test_tick_did_not_hold_stops` → `the choice did not hold: Overdue only`;
  - `test_wait_url_waits_then_read_runs`: the click changes the URL query and `loaded` goes False then True; the
    following `read_table` reads the new table;
  - `test_wait_url_unchanged_retries_then_stops`: two clicks, then `the page did not change after Filter`;
  - `test_wait_url_other_origin_stops`: → `the press went to another site`, and no report file;
  - `test_wait_url_submit_pressed_once`: a submit-rated click with `wait_url` is clicked once;
  - `test_check_choice_shape`, parametrized: a choose value that is empty, 201 characters, or holds `\n`; a tick value
    "yes"; a target that isn't `page.element`; with pages, a target role that isn't `popup_button`/`checkbox`;
  - `test_repeat_cannot_hold_a_choice`, for choose and tick;
  - `test_wait_url_placement`: `wait_url` on a click that isn't second-to-last before a `read_table` → Stop; with
    pages, on a click whose element isn't `navigate` → Stop;
  - `test_try_runs_choose_tick_and_wait_url`: a Try copy (`try: true`) runs all three.
- [ ] **Step 2: Implement** in `engine.py`.
  - `check_choice` is called from `check_learned` for `choose`/`tick`, next to `check_type`.
  - `check_repeat` refuses `choose` and `tick` as it does `read_table`.
  - The `wait_url` check sits in `check_learned`'s case walk.
  - `do_choose`/`do_tick` follow the spec's Runner section. The risk cap is copied from `do_type`. The gate is
    `self.gate("fill_field", "modify", target=ref, destination=self.d.current_url(self.app))`. Options are the
    `native:AXMenuItem` names under the node. For entry, re-find after `scroll_into_view`, then call
    `self._enter("select", node, value, None, label, None)`. Read back from a fresh `page_element`. The shortcut
    comment is the spec's text.
  - `do_click` `wait_url`: inside the existing attempt loop, after the press:
    - poll `current_url` (0.25 s steps, 15 s) until it differs from `before`;
    - `origin()` differs → Stop;
    - then poll `loaded` up to 15 s while it returns False (None means no wait);
    - return on success; an unchanged address goes to the next attempt; after the loop, the Stop.
- [ ] **Step 3: Run** the suite.
- [ ] **Step 4: Commit** `feat(engine): taught choose and tick steps; a click can wait for a new address`.

### Task 4: Lessons and lesson page: choose and tick lines and steps

**Files:**
- Modify: `govaios/lessons.py` (`propose`, `_do`, `preview`, `build` permissions)
- Modify: `govaios/panel/lesson.py` (`WORDS`, line rendering with the value)
- Test: `tests/test_lessons.py`, `tests/test_panel_web.py` or the existing lesson-page test file

**Interfaces:**
- Consumes: Task 2 events; Task 3 step shapes and `check_choice` (build's check runs it).
- Produces:
  - proposal lines `{"kind": "choose", "label", "target", "keep", "value": str}` and
    `{"kind": "tick", ..., "value": bool}`;
  - `_do` steps `{"action": "choose", "target", "value"}` / `{"action": "tick", "target", "value"}`.

- [ ] **Step 1: Failing tests:**
  - `test_propose_pick_and_tickbox_lines`: a lesson with pick "Engineering" in Department, a tickbox "1" on Overdue
    only, then a click "Filter". The lines are choose/tick/click, with values and targets, all kept;
  - `test_propose_choice_on_known_page_above_modify_is_unsure`: a known page rating the popup `submit` gives a line
    with "(check this target)" and keep False;
  - `test_propose_choice_after_hand_over_is_dead`, mirroring the type rule;
  - `test_build_choose_and_tick_steps`: the steps are in the flow; `fill_field` is in `allow`; `max_element_risk` is
    `modify` when it was `navigate`; no `type_text` is added;
  - `test_build_without_choices_unchanged`: the existing G0/G2 golden-hash tests still pass;
  - `test_preview_shows_choose_and_tick`: lines `... choose Engineering in Department`, `... tick Overdue only`; the
    YAML has the steps;
  - lesson page: `test_lesson_page_shows_choice_lines`: the value is shown escaped, and the Delete box works.
- [ ] **Step 2: Implement:**
  - every `kind in ("click", "type")` test in `propose` accepts `pick`/`tickbox` (`_key_for`, the cap above
    `modify`, the dead-after-hand-over rule);
  - new line branches;
  - `_do` branches;
  - `preview` kinds and texts;
  - in `build`, a separate permissions condition `if any(s["action"] in ("choose", "tick") for s in made.values())`.
  The observer's `choose`/`tick` events keep their `fill_form` branch unchanged.
- [ ] **Step 3: Run** the suite.
- [ ] **Step 4: Commit** `feat(lessons): choose and tick lines and steps from taught picks`.

### Task 5: Same-page read after a navigate press (P2, A1)

**Files:**
- Modify: `govaios/lessons.py` (`propose` read decision, `build` read path)
- Modify: `govaios/panel/lesson.py` (`_reads`, the "already in the app" check against that page)
- Modify: `docs/backlog.md` (G3 entry: the O4 gap; type-ahead with a space; `AXLoaded` live check)
- Test: `tests/test_lessons.py`, the panel lesson tests, `tests/test_try.py`

**Interfaces:**
- Consumes: Task 3's `wait_url`; G2's `_tables`, `READ_LAST`, `build(reads=...)`.
- Produces: `proposal["read_here"]: bool`.

- [ ] **Step 1: Failing tests:**
  - `test_read_here_offered_after_navigate_click`: the lesson's last page has pick, pick, click "Filter employees"
    (navigate). The Done tree has the same title and headings, and a table "ID". Expect `read_here` True,
    `read_refused` None, and `reads` offering the table;
  - `test_read_here_refused_when_last_line_not_navigate` (last event a type, or a submit click) → READ_LAST;
  - `test_read_here_refused_off_own_app` → READ_LAST;
  - `test_build_read_here_adds_wait_url_and_read`: the last case's `do` ends `[..., click {wait_url: true}, read_table]`
    with `then: end`, and no extra page file;
  - `test_build_read_here_filter_click_deleted_refused` → `ValueError(READ_LAST)`;
  - `test_build_read_here_nothing_ticked_unchanged`: no `wait_url`, the same bytes as without `read_here`;
  - `test_build_read_here_page_already_in_app_refused`, reusing G2's message;
  - panel: `test_lesson_page_offers_read_here_tables`;
  - `test_try_keeps_wait_url_and_choices`: Try's private copy still has `wait_url` and the choose/tick values.
- [ ] **Step 2: Implement** per the spec's "Same-page read" section. Decide `read_here` before the closing
  hand-over is appended.
- [ ] **Step 3: Backlog.** Add the G3 entry to `docs/backlog.md`, one line each:
  - O4 sends the filter at the press; not prevented;
  - type-ahead with an option containing a space, untested live;
  - `AXLoaded` presence, untested live;
  - an untouched dropdown isn't recorded.
- [ ] **Step 4: Run** the suite.
- [ ] **Step 5: Commit** `feat(lessons): read on the page a navigate press reloaded; the press waits for the new address`.
