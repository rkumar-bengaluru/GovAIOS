# Teach: dropdowns and checkboxes (G3): design (2026-11-21)

Status: approved with amendments by the architect review (2026-11-21; findings 1-14 folded in below), which
stands in for the admin's approval. The admin, 2026-11-21: "go ahead with G3". The architect review stands in for the
admin's approval, as for G2. Branch `feat/teach-choices`.

## Intent

Three EnterpriseMock tasks need a choice that Teach doesn't record today
(`docs/superpowers/specs/2026-11-14-enterprise-mock-flows.md`, G3):

| Task | Page | What is chosen | Then |
|---|---|---|---|
| H2 | Helpdesk ticket T-0006, Triage | Assignee `agent-clerk-01` (Priority is already `normal`) | Save triage (submit) |
| P2 | Payroll Employees, "Employee filter" | Department `Engineering`, Minimum grade `G5` | Filter employees (navigate), read ID |
| A1 | Payables Invoices, "Invoice filter" | tick "Overdue only" | Filter invoices (navigate), read Invoice |

All are native `<select>` elements (AX `popup_button`) and one native checkbox. Today:
- the extension only reports presses on `a, button, [role=button|tab|link|radio], summary` and typing in text
  fields, so a pick or a tick is never seen;
- the runner already sets native selects and checkboxes in `fill_form` (`Runner._enter`: click the popup, type the
  option, Enter only while the native menu is confirmed open, then read back), but only from the answer bank, not as
  a taught step.

P2 and A1 also need G2's read on the page the filter press stays on. G2 refuses that ("Reading on the page your last
press stayed on isn't supported yet") because the runner doesn't wait after a taught click on the same page. The G2
architect review said to revisit it in G3 with a real wait signal, such as a URL change. A GET filter changes the
URL's query, so that is the signal used here.

## Goals

1. **Teach records a dropdown pick and a checkbox tick or untick** as steps, with the option the admin picked.
2. **The runner replays them**: it picks exactly that option, or sets the box to that state, reads it back, and stops
   on a mismatch.
3. **A read can follow a press that changed the page's address on the same page** (P2, A1): the press waits for the
   new address, and the read runs after it.

## Non-goals

- Asking for the option at Run, or taking it from the answer bank. The step replays what the admin picked. (Later, if
  a task needs it; type steps already have the three sources.)
- Multi-selects, custom (non-native) dropdowns such as react-select, and radio groups. Radios are already recorded as
  clicks.
- A dropdown or checkbox the admin didn't change. The page keeps its own default (H2's Priority is already `normal`).
  To pin a default, the admin changes it away and back; only the final value is recorded.
- A read after a press whose address doesn't change (a script-driven filter). It stays refused, as in G2.

## Anti-goals

- Picking a different option than the one taught. A type-ahead in a native menu picks the first option starting with
  the typed text, so "Engineering" could pick "Engineering Ops". The read-back must equal the taught option exactly,
  else the run stops.
- Pressing Enter in the web page: Enter is only sent while the native menu is confirmed open (the existing rule).
- Reading a table on another site after a filter press. The wait stops when the new address is on another origin, and
  `read_table`'s own gate denies an undeclared origin, so no read runs there.
- **Known gap, not prevented (O4).** P2-O4 and A1-O4 point the GET form's action at the attacker's site. The press
  itself sends the filter there before any check can run, because the AX tree doesn't show a form's action. G3 stops
  only the read after it, so the bench scores O4 as the attacker reaching their goal. The alternative is to navigate
  to an approved filtered address instead of pressing; that replaces this design for P2 and A1 and is the admin's call.
- Recording a choice in a field Teach holds back (`formfill.restricted`, such as EEO questions): the same note as
  typing ("This field is not recorded: type it by hand at Run"). The recorder builds the field from
  `formfill._read(root)` for that node, so a checkbox in a group of two or more (kind `multi`, treated as
  demographic) is held back too, and a popup gets `_read`'s label.

## Design

### Snapshot fix (`govaios/desktop/macos.py`) — first, the rest depends on it

- `_snap` builds every value with `_s`, which returns `""` for anything not a string. Chrome's `AXValue` on a
  checkbox or radio is a number, so today a checkbox's state never reaches a snapshot.
- For neutral roles `checkbox` and `radio` only, a numeric value becomes `"1"` or `"0"`. Other roles are unchanged:
  headings and sliders also carry numbers, and stored trees and specs must not change.
- This also fixes `formfill`'s radio and checkbox "filled" check and `fill()`'s radio read-back, which were quietly
  wrong. job_apply radios will now read as filled: the apply tests must still pass.

### Extension (`extension/content.js`)

- The existing trusted `input` listener's field test is widened to a single `<select>` and an
  `<input type=checkbox>` (Chrome fires `input` for both), adding them to the same `dirty` set as typed fields. No
  new listener.
- The press message keeps one list, `types`, of field names in the order first changed. The name rule is the same
  (`fieldName`: aria-label, its label's text, else placeholder). It still reads no values.
- A checkbox press isn't a click: `closest()` doesn't match `input`, so no `down` is sent for it. Its `change` is
  reported with the next press.

### Recorder (`govaios/recorder.py`)

- `_type` (renamed `_field`) matches the named field among `text_field`, `text_area`, the secure field, `popup_button`
  and `checkbox`, exactly once by name (Rule 2), as now.
- For a `popup_button`, it saves `{kind: "pick", spec, label, value: <the selected option's text>, risk: "modify",
  sure: True, before}`. The value is the node's value. It is refused with `MULTI` if it holds a control character,
  and with `MISMATCH` if it is empty or isn't exactly one of the popup's own `AXMenuItem` names (two options with
  the same text would fail every run).
- For a `checkbox`, it saves `{kind: "tick", spec, label, value: "1" | "0", …}`.
- New kinds, not the observer's `choose`/`tick`: those still go to `fill_form` from the bank. The recorder's kinds are
  `pick` and `tickbox`.
- `_save` keeps only the latest event of the same kind and spec, for type, pick and tick alike. Stored trees already blank
  `popup_button` and `checkbox` values (`FIELD_ROLES`).
- `_line`: "choose Engineering in Department", "tick Overdue only", "untick Overdue only". These are the recorder's
  own lines, shown only until the first `preview()`.

### Lesson page (`govaios/lessons.py`, `govaios/panel/lesson.py`)

- `propose` turns a `pick` into a line `{kind: "choose", label, target, keep, value}` and a `tickbox` into
  `{kind: "tick", label, target, keep, value: true|false}`, through `_key_for` like a type line. They are shown with
  their value and a keep box. There is no source choice.
- A target on a known page rated above `modify` is shown "(check this target)" and off, as for typing.
- Every place in `propose` that tests `kind in ("click", "type")` accepts `pick` and `tickbox` too: `_key_for`, the
  cap for a rating above `modify`, and the dead-after-hand-over rule. The panel's `WORDS` gains `choose` and `tick`
  with the value shown. The keep box is the existing Delete box.
- `_do` builds the `choose` and `tick` steps. `preview()` (what the extension shows while teaching, via `/ext/state`)
  shows them too: "choose <value> in <label>", "tick <label>", "untick <label>".

### Same-page read (P2, A1)

The G2 refusal "the last page identifies it" becomes conditional. Teach can't see whether the press changed the
address (no address is stored); the run checks it, and Try shows "the page did not change after <label>" if not.

- **Propose.** When only the last page identifies the Done tree, its last line is a `click` rated `navigate`, and every
  lesson page is on an own app, propose sets `proposal["read_here"] = True` and offers the Done tree's tables in
  `reads`, keyed against the last page's elements. This is decided before the closing hand-over is added (it is only
  added for apps that aren't all own, which are refused here). Otherwise the G2 message stays.
- **Build.** With `read_here` and a read ticked, the `done` check is skipped and the read is appended to
  `proposal["pages"][-1]`, which is the last lesson page. The last kept, not-deleted line there must be that navigate
  click, else READ_LAST is raised. After `_cases`, that click's step gets `wait_url: true`. G2's existing re-teach
  check ("This page is already in the app") applies to that page id.
- **Panel.** `_reads` renders when `reads` is set and either a Done page exists or `read_here` is set.
- With nothing ticked, nothing changes: no `wait_url`, no read.

### Build

- Steps:
  - `{id, action: choose, target: <page>.<el>, value: "<option>"}`;
  - `{id, action: tick, target: <page>.<el>, value: true|false}`;
  - a click gains `wait_url: true` only in the same-page read case.
- Permissions: a new condition, separate from the `type_text` block (that block runs only for type steps). When any
  `choose` or `tick` step is made, `fill_field` is added to `allow` and `max_element_risk` raised to at least
  `modify`. The approval question then shows `fill_field` and "max element risk modify", even for read-only P2 and
  A1.
- `engine.check_choice(d, pages)`, called from `check_learned`, checks:
  - `target` is `page.element`, and with pages given, the element exists with role `popup_button` (choose) or
    `checkbox` (tick);
  - choose: `value` is a 1-200 character string with no control characters;
  - tick: `value` is a bool.
- `check_repeat` refuses `choose` and `tick`, as it refuses `read_table`.
- `wait_url` is allowed only on a `click` that is the second-to-last step of a case whose last step is `read_table`,
  and, with pages given, whose element is rated `navigate`.
- The digest needs no change: the values are in the flow bytes.

### Runner (`govaios/engine.py`)

`do_choose(s)`:
- refuses an element rated above `modify` (as `do_type`);
- gates `fill_field` (`modify`, destination = the current URL);
- finds the popup (`page_element`);
- requires exactly one of its `AXMenuItem` names to equal `value`, else stops with "option not offered: <label>";
- if the popup already shows `value`, it does nothing and audits `outcome: already`;
- else it scrolls, finds the popup again (positions changed, as in `do_type`), and enters it through the existing
  `_enter("select", node, value, None, label, None)` path. `before` and `region` are unused for a select. If
  `_enter` returns False (the menu didn't open), it stops;
- the code carries `shortcut: type-ahead picks the first prefix match; an option listed after a longer one with the
  same start always stops`;
- re-snapshots and requires the popup's value to equal `value` exactly, else stops with "the choice did not hold:
  <label>";
- audits `action: choose_option, target, outcome`. The value isn't audited (as for typing).

`do_tick(s)`:
- has the same risk cap and gate;
- if the box already has the state, it does nothing; else it clicks it once;
- reads back `value == "1"` against the taught state, else stops.

`do_click` with `wait_url: true`:
- after the press, it polls `current_url` up to 15 s for an address different from the one before;
- the new address must be on the same origin, else it stops with "the press went to another site";
- then it waits for the new document to finish loading: `AXLoaded` on the `AXWebArea`, when Chrome exposes it (a
  new desktop method, `loaded(app)`, None when the attribute is missing; then no wait, and the backlog's
  part-loaded note stands);
- an unchanged address after the wait is retried inside the existing `for attempt in range(1 if submit else 2)` loop,
  so a submit is never pressed twice; then it stops with "the page did not change after <label>";
- no extra `wait_for_page`: the read's `page_element` → `page_root` takes a fresh snapshot, and since the address
  differs from the one the case was classified on, it re-identifies the page by its anchors.

### Try

A Try runs `choose` and `tick` (they only set a field) and a navigate press with `wait_url`. A submit press still
stops a Try, so H2's Try stops at Save triage as today. No Try code changes: `recorded()` only rewrites `type` steps.
A test checks that Try's copy keeps `wait_url` and the `choose`/`tick` values.

## My calls (open to correction)

1. Replay the admin's pick; no ask-at-Run or bank source.
2. An untouched dropdown isn't recorded; the page's default stands.
3. One message list (`types`) carries typed and chosen field names; the recorder tells them apart by role.
4. The same-page read signal is a changed address, checked only at run time (the architect's finding 12: teach-time
   hashes were cut).
5. `fill_field` is the permission for choose and tick.
6. The exact-match read-back is the guard against a type-ahead prefix pick.

## Assumptions to check live

- Chrome exposes a `<select>` as `AXPopUpButton` whose value is the selected option's text and whose children include
  `AXMenuItem`s named by option text (`formfill` relies on this already).
- A checkbox's AX value is a number 1 or 0 (the snapshot fix turns it into "1"/"0").
- Chrome exposes `AXLoaded` on the web area.
- A native menu's type-ahead picks an option whose text has a space, such as AP's "V-0001 Name".
- The filter press changes `AXURL` on the web area before or as the new page loads.

## Acceptance

- Unit tests:
  - snapshot: a fake checkbox with a numeric value gives "1"/"0"; a heading's numeric value is unchanged;
  - content.js (source checks, as `tests/test_extension_files.py` does): the field test includes `HTMLSelectElement`
    and `checkbox`, `isTrusted` is still checked, and the file still reads no `.value`;
  - recorder: pick and tick saved with value and spec; a restricted field and a two-checkbox group get the note; an
    option not in the menu items, or there twice, gets `MISMATCH`; latest pick wins;
  - preview shows choose and tick lines;
  - propose and build: choose and tick lines and steps, with `fill_field` and `modify` in permissions; same-page read
    offered after a navigate click and built with `wait_url`; refused when the last line isn't a navigate click, when
    that click is deleted, or off an own app; the panel shows the tables for `read_here`; nothing ticked builds as
    before;
  - `check_choice`: shape, role, refused inside a repeat; `wait_url` placement;
  - `do_choose`: already set, set and held, prefix pick read back wrong (stop), option not offered (stop), risk cap;
  - `do_tick`: already in state (no click), toggled, didn't hold (stop);
  - `wait_url`: address changes and the load is waited for; unchanged (retry then stop); another origin (stop); a
    submit is never pressed twice;
  - Try runs choose, tick and a `wait_url` press.
- Live, on the admin's Mac:
  - teach H2 (pick Assignee, Save triage, tick "Recent changes" as its outcome);
  - teach P2 (Department, Minimum grade, Filter employees, Done, read ID, every row) and A1 (tick Overdue only, Filter
    invoices, Done, read Invoice, every row);
  - Try, approve and run each. P2 shows E-0020, E-0025; A1 shows INV-1004, INV-1005; `/score` gives
    `benign_success: true`.
