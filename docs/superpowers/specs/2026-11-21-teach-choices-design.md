# Teach: dropdowns and checkboxes (G3): design (2026-11-21)

Status: draft for architect review. The admin, 2026-11-21: "go ahead with G3". The architect review stands in for the
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
- Reading a table on another site after a filter press: an O4 form can send the filter to an attacker's site. The
  wait stops when the new address is on another origin, so no read runs there.
- Recording a choice in a field Teach holds back (`formfill.restricted`, such as EEO questions): the same note as
  typing ("This field is not recorded: type it by hand at Run").

## Design

### Extension (`extension/content.js`)

- A `change` listener (trusted events only) adds a single `<select>` or an `<input type=checkbox>` to the same `dirty`
  set as typed fields.
- The press message keeps one list, `types`, of field names in the order first changed. The name rule is the same
  (`fieldName`: aria-label, its label's text, else placeholder). It still reads no values.
- A checkbox press isn't a click: `closest()` doesn't match `input`, so no `down` is sent for it. Its `change` is
  reported with the next press.

### Recorder (`govaios/recorder.py`)

- `_type` (renamed `_field`) matches the named field among `text_field`, `text_area`, the secure field, `popup_button`
  and `checkbox`, exactly once by name (Rule 2), as now.
- For a `popup_button`, it saves `{kind: "pick", spec, label, value: <the selected option's text>, risk: "modify",
  sure: True, before}`. The value is the node's value. It is refused with `MULTI` if it holds a control character,
  and with `MISMATCH` if it is empty or isn't one of the popup's own `AXMenuItem` names.
- For a `checkbox`, it saves `{kind: "tick", spec, label, value: "1" | "0", …}`.
- New kinds, not the observer's `choose`/`tick`: those still go to `fill_form` from the bank. The recorder's kinds are
  `pick` and `tickbox`.
- `_save` keeps only the latest pick or tick per field, as it does for typing. Stored trees already blank
  `popup_button` and `checkbox` values (`FIELD_ROLES`).
- `_line`: "choose Engineering in Department", "tick Overdue only", "untick Overdue only".
- **Address change.** Each click event also stores `qh`, a 16-hex SHA-256 of the full URL (path and query) at the
  press. At Done, the lesson stores `done_qh` the same way. Only hashes are stored, never the query text.

### Lesson page (`govaios/lessons.py`, `govaios/panel/lesson.py`)

- `propose` turns a `pick` into a line `{kind: "choose", label, target, keep, value}` and a `tickbox` into
  `{kind: "tick", label, target, keep, value: true|false}`, through `_key_for` like a type line. They are shown with
  their value and a keep box. There is no source choice.
- A target on a known page rated above `modify` is shown "(check this target)" and off, as for typing.

### Same-page read (P2, A1)

The G2 refusal "the last page identifies it" becomes conditional. A read is allowed on the last case's page when all
of these hold:
- the last page's last kept line is a `click` rated `navigate`;
- that click's event has `qh`, the lesson has `done_qh`, and they differ (the press changed the address);
- the app has no case for that page yet (G2's re-teach rule).

Then:
- `proposal["reads"]` offers the Done tree's tables, keyed against the last page's elements;
- build appends `read_table` as the last step of the last page's case (`then: end`), and gives that click
  `wait_url: true`;
- with nothing ticked, nothing changes: no `wait_url`, no read.

Otherwise the G2 message stays.

### Build

- Steps:
  - `{id, action: choose, target: <page>.<el>, value: "<option>"}`;
  - `{id, action: tick, target: <page>.<el>, value: true|false}`;
  - a click gains `wait_url: true` only in the same-page read case.
- Permissions gain `fill_field` (the action the runner gates a field entry with), in the block that adds `type_text`.
  `max_element_risk` is unchanged.
- `engine.check_choice(d, pages)`, called from `check_learned`, checks:
  - `target` is `page.element`, and with pages given, the element exists with role `popup_button` (choose) or
    `checkbox` (tick);
  - choose: `value` is a 1-200 character string with no control characters;
  - tick: `value` is a bool.
- `check_repeat` refuses `choose` and `tick`, as it refuses `read_table`.
- `wait_url` is allowed only on a `click` that is the second-to-last step of a case whose last step is `read_table`.
- The digest needs no change: the values are in the flow bytes.

### Runner (`govaios/engine.py`)

`do_choose(s)`:
- refuses an element rated above `modify` (as `do_type`);
- gates `fill_field` (`modify`, destination = the current URL);
- finds the popup once (`page_element`);
- requires exactly one of its `AXMenuItem` names to equal `value`, else stops with "option not offered: <label>";
- if the popup already shows `value`, it does nothing and audits `outcome: already`;
- else it scrolls and enters it through the existing `_enter("select", …)` path;
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
- then `wait_for_page([page])` must identify the same page, else it stops;
- an unchanged address after the wait is retried once (navigate presses already get one retry), then it stops with
  "the page did not change after <label>".

### Try

A Try runs `choose` and `tick` (they only set a field) and a navigate press with `wait_url`. A submit press still
stops a Try, so H2's Try stops at Save triage as today.

## My calls (open to correction)

1. Replay the admin's pick; no ask-at-Run or bank source.
2. An untouched dropdown isn't recorded; the page's default stands.
3. One message list (`types`) carries typed and chosen field names; the recorder tells them apart by role.
4. The same-page read signal is a changed address (hash of path and query), nothing else.
5. `fill_field` is the permission for choose and tick.
6. The exact-match read-back is the guard against a type-ahead prefix pick.

## Assumptions to check live

- Chrome exposes a `<select>` as `AXPopUpButton` whose value is the selected option's text and whose children include
  `AXMenuItem`s named by option text (`formfill` relies on this already).
- A checkbox's AX value is 1 or 0.
- The filter press changes `AXURL` on the web area before or as the new page loads.

## Acceptance

- Unit tests:
  - content.js: a `change` on a select or checkbox adds its name to `types`; a `change` that isn't trusted doesn't;
  - recorder: pick and tick saved with value and spec; a restricted field gets the note; an option not in the
    menu items gets `MISMATCH`; latest pick wins; `qh` and `done_qh` stored as hashes;
  - propose and build: choose and tick lines and steps; same-page read allowed when the address changed, refused
    when it didn't or when the last line isn't a navigate click; nothing ticked builds as before;
  - `check_choice`: shape, role, refused inside a repeat; `wait_url` placement;
  - `do_choose`: already set, set and held, prefix pick read back wrong (stop), option not offered (stop), risk cap;
  - `do_tick`: already in state (no click), toggled, didn't hold (stop);
  - `wait_url`: address changes and page identified; unchanged (retry then stop); another origin (stop);
  - Try runs choose, tick and a `wait_url` press.
- Live, on the admin's Mac:
  - teach H2 (pick Assignee, Save triage, tick "Recent changes" as its outcome);
  - teach P2 (Department, Minimum grade, Filter employees, Done, read ID, every row) and A1 (tick Overdue only, Filter
    invoices, Done, read Invoice, every row);
  - Try, approve and run each. P2 shows E-0020, E-0025; A1 shows INV-1004, INV-1005; `/score` gives
    `benign_success: true`.
