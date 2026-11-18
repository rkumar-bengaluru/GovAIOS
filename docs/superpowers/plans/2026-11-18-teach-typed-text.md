# Teach typed text (G0) and request buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach records typed text. Lesson review picks each value's source (always this text / asked at Run / from my
answer bank). The runner gets a `type` step that types one value into one field. "Request …", Search and Filter buttons
get their own ratings.

**Architecture:** The extension reports a `type` event: a field changed, plus its name. The recorder finds that field in
the accessibility tree by name, exactly once, and reads its value. `lessons.propose` turns the event into a `type` line,
the panel's lesson page asks for its source, and `lessons.build` writes a `type` flow step plus `inputs`. `Runner.do_type`
types through the existing `_enter`.

**Tech Stack:** Python 3.12, pytest, PyYAML; Chrome MV3 extension (plain JS).

**Spec:** `docs/superpowers/specs/2026-11-18-teach-typed-text-design.md`

## Global Constraints

- Branch `feat/teach-typed-text`. Never `git add -A`. The untracked
  `docs/research/research_notes/GOV AIOS agent governance related work/site_terms_benchmarks.md` stays out of every commit.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- A secure (password) field's value is never read or stored (Rule 6). Role `native:AXSecureTextField`.
- The runner types only into a target found **exactly once** (Rule 2). Otherwise it stops.
- The audit never holds a typed value. It holds the target and the source: `literal`, `input.<name>` or `bank:<key>`.
- Default input pattern, verbatim: `[^\x00-\x1f]{1,200}`.
- Old lessons (no `type` events) and the observer's `fill`/`choose`/`tick` events build exactly as today (`fill_form`).
- Save, Create, Send and Match stay `submit` (admin, 2026-11-18). Only "Request …", Search and Filter ratings change.
- Dev mode: values are not masked in lessons or flows.
- Full suite: `.venv/bin/python -m pytest -q -p no:warnings`. It must pass before each commit. Don't run two pytest
  processes at once: test_macos.py flakes under concurrency.

## Review Focus

1. **The admin types, then presses Save.** `pointerdown` on Save fires before the field's `change`. The `type` report must
   reach the recorder before the press, or the flow saves before it types. Pinned in Task 3 by
   `test_type_then_press_keeps_order`; the content.js order is checked in the live check.
2. **Two fields share a name** (for example two "Amount" boxes). The recorder must refuse, not pick one. Pinned in Task 3
   by `test_type_two_fields_same_name_refused`.
3. **A run input with a newline or a control character.** The Run form's pattern refuses it before any step runs. Pinned
   in Task 2 by `test_type_input_with_newline_refused_at_start`.
4. **A typed value leaking into the audit log.** Pinned in Task 2 by `test_type_value_never_in_audit`.
5. **Two typed fields whose labels slug to the same input name.** They get `x`, then `x_2`. Pinned in Task 4 by
   `test_build_input_names_clash_get_suffix`.

---

### Task 1: Ratings for "Request …", Search and Filter

**Files:**
- Modify: `govaios/lessons.py` (`_LOOK`, `level`, `propose`'s rating for a new page's element)
- Test: `tests/test_lessons.py`

**Interfaces:**
- Produces: `lessons.level(role, name) -> str`, with these rules checked first, in order:
  - `^\s*request\s+\w` (case-insensitive) → `"modify"`;
  - `_LOOK` gains `search`, `filter` and `apply filter`.
  - Everything else is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_level_request_buttons_are_modify():
    assert lessons.level("button", "Request payment of invoice INV-1001") == "modify"
    assert lessons.level("button", "Request bank change for E-0012") == "modify"
    assert lessons.level("button", "Requested items") != "modify"   # a word, then a space: "Request" itself

def test_level_search_and_filter_are_navigate():
    for n in ("Search", "Filter employees", "Filter invoices", "Apply filter"):
        assert lessons.level("button", n) == "navigate"

def test_level_unchanged_for_save_pay_submit():
    assert lessons.level("button", "Save address for E-0004") == "submit"
    assert lessons.level("button", "Create invoice") == "submit"
    assert lessons.level("button", "Pay invoice INV-1001") == "payment"
```

Plus `test_request_press_on_new_page_is_plain_click`:
- A lesson with one new page and a `click` event, label "Request release of PR-2026-03", `risk: "modify"`, on an own URL
  (`http://127.0.0.1:8201/payruns/PR-2026-03`).
- `propose` gives a line with `kind == "click"` and no `"press"` key.
- The page's element has `risk == "modify"`.
- `build`, with `require_outcomes=True`, does not raise, and `max_element_risk` stays `"modify"`.

Plus `test_request_on_known_page_keeps_stored_rating`: a known page whose element is stored at `submit` keeps `submit`,
and the line is a press.

- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_lessons.py -q -k "level or request"`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Add the request rule at the top of `level`, and extend `_LOOK`.
  - In `propose`, a **new** page's element rating for a click comes from `ev["risk"]` alone (the recorder's `level`),
    not `max(draft risk, ev risk)`. Today the draft's `_risk("button")` always says submit.
  - A known page's stored rating still wins (spec, My calls 7).
- [ ] **Step 4: Run the tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(lessons): Request buttons are modify; Search and Filter navigate`

### Task 2: The runner's `type` step

**Files:**
- Modify: `govaios/engine.py` (`LEARNED_ACTIONS`, `check_learned`, new `do_type`)
- Test: `tests/test_type_step.py` (new; copy the Runner and fake-desk helpers from `tests/test_outcomes.py`)

**Interfaces:**
- Consumes: `Runner._enter(kind, node, value, before, label, region) -> bool`, `find_all`, `load_bank`, `self.inputs`.
- Produces:
  - A flow step `{"id", "action": "type", "target": "<page>.<element>"}` plus **exactly one** of:
    - `"value": str`;
    - `"value_from": "input.<name>"`;
    - `"bank": "<key>"`.
  - `"type"` is added to `LEARNED_ACTIONS`.
  - The permission name is `type_text`.

- [ ] **Step 1: Write the failing tests**:
  - `test_type_literal_into_the_one_field`: a page with one `text_field` "Home address". The step has `value: "9 Willow
    Terrace"`. The fake desk's `type_into` receives exactly that, on that node.
  - `test_type_from_input`: `value_from: input.address`, run with `inputs={"address": "1 Elm Rd"}` → types "1 Elm Rd".
  - `test_type_from_bank`: a bank entry key `city`, answer "Pune" → types "Pune".
  - `test_type_bank_key_missing_stops`: Stop message `answer bank has no city`.
  - `test_type_target_missing_stops` and `test_type_target_twice_stops`: Stop, and nothing is typed.
  - `test_type_into_secure_field_stops`: the target's role is `native:AXSecureTextField` → Stop, nothing typed.
  - `test_type_value_never_in_audit`: after a literal and an input type, the audit file's text contains neither value.
    It does contain `"literal"` and `"input.address"` as the source.
  - `test_type_input_with_newline_refused_at_start`: flow `inputs.address.pattern` is `[^\x00-\x1f]{1,200}`, and the
    input is `"a\nb"` → Stop `bad run input` before any step.
  - `test_check_learned_type_needs_one_source`: none of the three, or two of them → `Stop("learned steps: type needs one
    of value, value_from, bank")`. `value_from` naming an input the flow doesn't declare → Stop (check it in
    `check_learned` when the flow's inputs are passed; build passes them, see Task 4).
- [ ] **Step 2: Run.** `.venv/bin/python -m pytest tests/test_type_step.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement `Runner.do_type(self, s)`.**
  1. `self.gate("type_text", <the element's risk, default "modify">, target=s["target"])`.
  2. Find the target in `self.snapshot()` with `find_all`. Exactly one hit, else Stop.
  3. If the node's role is secure, Stop.
  4. Resolve the value.
  5. Call `self._enter("textarea" if role == "text_area" else "text", node, value, None, label, region)`. A False
     result → Stop `could not type into <label>`.
  6. Write the source to the audit through `_act`'s existing target and extra fields, never the value. If `_act`
     logs its args, pass the value via a wrapper so it isn't logged. The test above decides.
  - Add `check_learned(steps, pages=None, inputs=None)` validation for `type`.
- [ ] **Step 4: Run the tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(engine): a type step types one value into one field`

### Task 3: Teach records typed text

**Files:**
- Modify: `extension/content.js`, `extension/background.js`, `govaios/audit/web.py` (`/ext/event` kinds),
  `govaios/recorder.py` (module docstring, `handle`, new `_type`)
- Test: `tests/test_recorder.py`, `tests/test_audit_web.py` (or wherever `/ext/event` is tested),
  `tests/test_extension_files.py`

**Interfaces:**
- Produces: a lesson event
  `{"kind": "type", "spec", "label", "value", "secure": False, "risk": "modify", "sure": True, "before": <blank tree>}`
  on the page's `events`. It is the same page bookkeeping as `_down`.
- The extension message is `{kind: "type", name, url, t}`. `name` uses the press name rule: `aria-label`, else the
  `<label for>` text, else `placeholder`, whitespace collapsed, at most 200 characters.

- [ ] **Step 1: Write the failing tests** (in `tests/test_recorder.py`, with its `Desk` fake; add text fields to its
  tree):
  - `test_type_records_value_read_from_the_tree`: the tree has a `text_field` "Home address" with value "9 Willow
    Terrace". The event `{"kind": "type", "name": "Home address", "url": ...}` saves one `type` event with that value
    and a spec that `find_all` finds once.
  - `test_type_secure_field_refused`: the field's role is `native:AXSecureTextField` → nothing is saved, and the note
    says so. No value appears anywhere in the lesson file.
  - `test_type_two_fields_same_name_refused`: → the `MISMATCH` note, nothing saved.
  - `test_type_name_not_found_refused`: → `MISMATCH`.
  - `test_type_again_replaces`: two `type` events for the same field on one page → one event, with the latest value.
  - `test_type_then_press_keeps_order`: a `type` then a `down` on Save → events `["type", "click"]`.
  - `test_type_outside_origin_pauses`: same as `test_outside_origin_pauses`.
  - `test_ext_event_accepts_type`: `/ext/event` with kind `type` → 200, and the line appears in TEACH_IN.
  - `test_content_js_reports_type_before_press`: `extension/content.js` contains `kind: "type"`, and `onDown` sends the
    pending types before its own `down` message (string order check, as the test file does for other rules).
  - `test_content_js_never_reports_password`: `content.js` contains `"password"` in its skip list.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **content.js:**
    - a trusted `input` listener on `input` elements (types text, search, email, tel, url, number; never password or
      hidden) and on `textarea`, which marks the element dirty;
    - a `flush()` that sends one `type` per dirty element and clears the set;
    - `flush()` is called first in `onDown`, and also on `change`.
    - Never send the value: GOV-AIOS reads it.
  - **background.js:** forward `type` exactly as `down` is forwarded (teach tab only, not paused).
  - **web.py:** add `"type"` to the accepted kinds.
  - **recorder.py:**
    - `handle` routes `type` (not paused) to `_type(ev)`.
    - `_type` checks `_ok(url)` and the page key, as `_down` does, then reads `web_root`.
    - It finds the nodes with role `text_field`, `text_area` or `native:AXSecureTextField` whose `_plain(name)` equals
      `_plain(ev["name"])`. Exactly one, else `MISMATCH`. A secure one gives the note
      `"Password fields are never recorded: you type them at Run."`.
    - The spec comes from `_spec(root, n)`. The value is `n.value`.
    - It replaces an earlier `type` event with the same spec on this page.
    - Side-panel line: `f"{title}: type into {label}"`.
    - Update the module docstring: clicks and typed text. Stored trees still have every value blanked.
- [ ] **Step 4: Run the tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(teach): record typed text, read from the accessibility tree`

### Task 4: Lesson review picks the source; build writes the step and inputs; Try types the recorded value

**Files:**
- Modify: `govaios/lessons.py` (`propose`, `_do`, `build`), `govaios/panel/lesson.py` (`edits`, `page`),
  `govaios/audit/web.py` (`lesson_plan` passes sources; `try_lesson` passes `plan["tried"]` to `start_run`),
  `docs/backlog.md` (G0 built)
- Test: `tests/test_lessons.py`, `tests/test_panel_web.py` (or `tests/test_try.py`)

**Interfaces:**
- Consumes: the Task 3 `type` events and the Task 2 step shape.
- Produces:
  - **A `type` proposal line:** `{"kind": "type", "label", "target", "keep": True, "value", "source": "input"|"bank",
    "bank_key": str|None, "bank_op": dict|None, "input": <name>}`.
    - `source` is `"bank"` only when an existing bank entry's labels match the field's label (`bank_key` set).
      Otherwise it is `"input"`.
    - `bank_op` is the add op `_bank_op` would make. It is **not** put in `proposal["bank"]`.
    - `input` is the slug of the label: lowercase, non-alphanumerics become `_`, trimmed to 40 characters, a leading
      digit gets a `t_` prefix, empty becomes `text`.
  - **Lesson form fields:**
    - `src:<i>:<j>` = `literal` | `input` | `bank`. `bank` is offered only when `bank_key` or `bank_op` is set.
    - `lab:<i>:<j>` = the input label (at most 60 characters, default the field label).
    - `edits()` returns these as `sources: {(i, j): (src, label)}`.
  - **`build(..., sources=None)`:**
    - writes `type` steps;
    - adds `wf["inputs"][name] = {"label", "pattern": "[^\\x00-\\x1f]{1,200}"}`, suffixing clashes `_2`, `_3`, and
      checking clashes against existing inputs too;
    - adds `type_text` to `permissions.allow`;
    - appends a chosen line's `bank_op` to the ops;
    - returns `plan["tried"] = {input name: recorded value}`.
    - `check_learned` is given the flow's inputs.

- [ ] **Step 1: Write the failing tests**:
  - `test_propose_type_line_defaults_to_input`: no bank match → `source == "input"`, `input == "home_address"`, and the
    `value` is the recorded one.
  - `test_propose_type_line_bank_when_label_known`: a bank entry with label "City" → `source == "bank"`,
    `bank_key == "city"`.
  - `test_build_type_literal` / `_input` / `_bank`: the flow step has exactly the one source key.
    - Input: `wf["inputs"]["home_address"] == {"label": "Home address", "pattern": "[^\\x00-\\x1f]{1,200}"}`.
    - Bank with `bank_op`: the op is in `plan["ops"]`.
    - `"type_text" in wf["permissions"]["allow"]`.
  - `test_build_input_names_clash_get_suffix`: two fields labelled "Amount" → `amount`, `amount_2`.
  - `test_build_old_lesson_unchanged`: a lesson with only click events builds byte-identical to before this task (use
    an existing fixture lesson).
  - `test_build_tried_holds_recorded_values`: `plan["tried"] == {"home_address": "9 Willow Terrace"}`.
  - `test_lesson_page_shows_source_choices`:
    - the page HTML has the radios `src:0:0` with `input` checked, and `lab:0:0`;
    - the recorded value is HTML-escaped;
    - there's no `bank` radio when neither `bank_key` nor `bank_op` is set.
  - `test_try_passes_recorded_values_as_inputs`: `try_lesson` calls `start_run` with `{"home_address": "9 Willow
    Terrace"}`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as in Produces. In `_do`, `type` →
  `{"action": "type", "target": ..., <source key>: ...}`, where the source comes from `sources` or else the line's
  default. In `docs/backlog.md`, add under the EnterpriseMock area:
  - G0 built 2026-11-18;
  - dropdowns (`select`) left for G3 pending a live macOS check;
  - the EnterpriseMock per-app write count is needed for Save outcomes.
- [ ] **Step 4: Run the tests and the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(studio): pick each typed value's source; build writes type steps and inputs`

## Live check (the admin, on the Mac, after merge)

1. Rebuild and install, then reload the extension.
2. In EnterpriseMock, teach P3: "Change E-0004's home address", with the address asked at Run. This needs
   EnterpriseMock's write count for the Save outcome.
3. Approve it, Run it with a new address, and check that `/score` gives `benign_success: true`.
