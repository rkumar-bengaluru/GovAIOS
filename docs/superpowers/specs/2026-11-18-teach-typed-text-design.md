# Teach: typed text (G0) and request buttons: design (2026-11-18)

Status: for admin review. Branch `feat/teach-typed-text`.

## Intent

EnterpriseMock training (`docs/superpowers/specs/2026-11-14-enterprise-mock-flows.md`, guide
`EnterpriseMock/docs/training-guide.md`) needs flows that type: an employee ID into a search box, a new address, a bank
account, a reply. Today Teach records **clicks only** (`extension/content.js` sends `down` events; `recorder.py`
records `click`), and the runner has **no step that types a value into one field**. It can only type a URL
(`do_navigate`) or fill a whole form from the answer bank (`do_fill_form`). About 9 of the 15 flows (P1–P4, A1, A3–A5,
H3) cannot be taught. G1 (a value read earlier) builds on this. The admin, 2026-11-18: "G0 first".

Second, smaller: the admin decided "request buttons as modify". In EnterpriseMock an agent user sees "Request payment",
"Request release", "Request submission" and "Request change" buttons. They only create a pending item for a human, so their
real effect is `modify`. Teach rates them `submit` today (`lessons.level`'s default). Because of that, the build raises
`max_element_risk` to submit, and since the outcome checks (PR #38) each one would also need an outcome and a press grant.

## Goals

1. **Teach records typed text.** When the admin types into a text field or text area, the lesson gets a `fill` event.
   It records the field (a spec the runner can find again) and the value as GOV-AIOS read it from the accessibility tree.
2. **Lesson review asks where each typed value comes from.** These are the three choices of the Teach design §9:
   - **Always this text:** the literal value is written into the flow.
   - **Asked at Run:** becomes a flow input. The Run form asks for it, as for apps with inputs today.
   - **From my answer bank:** reads `answers.yaml` on every run, through `lessons.py`'s existing bank logic (`_bank_op`).
3. **The runner types one value into one field.** It is a new `type` step: target `page.element`, plus exactly one of
   `value`, `value_from: input.<name>` or `bank: <key>`.
4. **"Request …" buttons are rated modify.** A label that starts with "Request" followed by a word is `modify`, both in
   `lessons.level` and in the risk stored on the element. A press on one is then a plain click: no press grant, no outcome
   needed, and it doesn't raise `max_element_risk` above modify.

## Non-goals

- G1 (a value read on an earlier page), G2 (read and report steps) and G3 (dropdowns). G3 is a separate gap, but see
  "My calls" (4).
- Changing `fill_form` or job_apply. Pages filled from the bank in one step keep working as today.
- Masking typed values (dev mode: "no masking for now").
- Recording Enter-to-submit. Teach records the button the admin presses. The side panel's notes say to press the
  button, not Enter.
- A level control in the side panel (training guide step 3). The "Request" rule removes the need for one here.

## Anti-goals

- A secure (password) field's value is read or stored anywhere. Rule 6 is unchanged: such a field stays a `hand_fill`.
- A value is typed into a field other than the one taught. The runner needs exactly one match for the target (Rule 2)
  and stops otherwise.
- A recorded value comes from what the page *says*, not from what GOV-AIOS reads. The extension reports *that* a field
  changed and where; the recorder reads the value from the accessibility tree, as it reads names for presses today.
- An input value passes into a step without the Run form's pattern check.

## Design

### Teach (extension and recorder)

- `content.js` tracks fields the admin changed. These are `input` events, trusted only, on `input` (text-like types,
  never `password` or `hidden`) and `textarea`.
- Before any recorded press, and on `change`, it sends one `fill` report per changed field: `{kind: "fill", x, y, url,
  name}`. Here `x, y` is the field's centre on screen and `name` is its accessible name, using the same name rule as
  presses. **Order matters:** a press on Save fires `pointerdown` before the field's `change`. So pending fills are sent
  first, inside the `pointerdown` handler, and the Save press after them.
- `background.js` forwards `fill` exactly as it forwards `down`: only from the teach tab, never while paused.
- `Recorder._fill` mirrors `_down`:
  - the own-app or allowed-terms check;
  - `element_at(x, y)` must be a text field or text area whose name matches `name` (Rule 2);
  - the field must not be `AXSecureTextField`, which is refused and noted;
  - the value is read from the node.
  - It records `{"kind": "fill", "spec", "label", "value", "secure": False, "before"}`. A second `fill` of the same field
    on the same page replaces the first.
- The side panel's lines show typed steps as "type into *label*". The value isn't shown there.

### Lesson review and build

- `lessons.propose` turns each `fill` event into a `type` line with `source` set to `bank` when `_bank_op` finds or
  proposes a bank key, and `input` otherwise. *My call:* Asked at Run is the default, because a literal is the riskier
  choice to make by accident.
- The lesson page shows each typed line with its value and three radio choices. For Asked at Run it also shows the
  input's name, taken from the label (for example `employee_id`), and its label, which the admin can edit.
- `build` writes the step and, for inputs, `inputs.<name>: {label, pattern}`. The pattern defaults to
  `[^\x00-\x1f]{1,200}`: any printable text up to 200 characters, no newline. The admin can't edit it in this build;
  G1 adds shape patterns.
- The permissions add `type_text`. The element's risk is `modify`.
- Old lessons (no `fill` events) build exactly as today.

### Runner

- `do_type(s)`:
  - the gate (`type_text`, the element's risk);
  - the target found with exactly one hit;
  - the value from `value`, `self.inputs[name]`, or the bank (via `load_bank` / `answer_for`'s key lookup). A missing
    bank key stops the run with "answer bank has no <key>".
  - It then calls the existing `_enter("text" | "textarea", …)`, which clicks, checks focus and runs `type_into`.
  - It stops if `_enter` returns False.
- **Audit:** the `type_text` entry records the target and the source (`input.employee_id`, `bank:city`, `literal`),
  never the typed value. *My call:* this matches "fingerprint only, the name stays in the app" from the outcome checks.
  The run's inputs are already covered by the run ticket's inputs digest.

### Request buttons

- `lessons.level`: `^request\s+\w` (case-insensitive, after trimming) → `modify`, checked before the pay and change rules.
- **Risk, accepted:** a hostile page could name a real Pay button "Request payment" and get it taught as modify. This is
  exactly the O6 opening EnterpriseMock measures (training poisoning, scored from the trained page file). The runtime
  guard is unchanged: an EnterpriseMock flow's `max_element_risk: modify` stops a run that meets a real Pay or Release
  button. Rule 4 still applies to any element rated payment.

## My calls (open to correction)

1. The typed-value choice is made on the **lesson review page** in the panel, not live in the side panel as the Teach
   design §9 said. The review page is where outcomes are already ticked, and a choice made there can't be lost
   mid-recording.
2. Asked at Run is the default; Always this text is never pre-selected.
3. The audit records the source, not the value.
4. **Dropdowns (`select`)**: the same `change` report covers them almost for free. The value is the popup button's
   chosen title, and the runner uses `_enter("select", …)`, which already exists. I'd include it only if the macOS tree
   shows the chosen option reliably in a live check; otherwise it is left for G3. No other part of G3 (combo boxes,
   radios) is in this build.
5. **Teach lessons get a new event kind, `type`**, so the observer's old `fill` events (job_apply's `fill_form` path) build
   exactly as today. Only `type` events become `type` lines.
6. **The recorder finds the field by name, not by point.** It looks for exactly one text field or text area with the
   reported name in the tree (Rule 2: none or two is a mismatch, noted, nothing saved). A field can be reached by Tab,
   so its point on screen isn't reliable.
7. **"Request …" lowers only a new page's rating.** Today a known page keeps its stored risk, and that stays: lowering a
   shared page file's rating is a downgrade that other apps would inherit, so the lesson page says
   "kept at submit (known page)". For a new page, the rule applies to the stored element risk too, not only the press
   (`_risk("button")` is otherwise always submit).
8. **Search and Filter are navigate.** `Search`, `Filter …` and `Apply filter` are added to `lessons._LOOK`. Without
   that, P1, P2 and A1's lookups would be rated submit and need outcomes.
9. **Try types the value recorded in the lesson** for every source. A Try is unsaved and never presses submit, so the
   recorded value is the honest one to show. A Try needs no inputs.
10. **Input names that clash get a suffix**: `address`, then `address_2`. Run lists each one with its label and the page
    it is typed on.

## Acceptance

- Unit tests:
  - recorder fill (match, name mismatch, secure refused, replace);
  - propose and build for all three sources;
  - `do_type` (found once, not found, two found, bank key missing, input used);
  - level rule (`Request payment of invoice INV-1001` → modify; `Pay invoice` → payment; `Save` → submit).
- Live, on the admin's Mac: teach EnterpriseMock P3 ("Change E-0004's home address"), with the address asked at Run.
  Approve it, run it with a new address, and the scorer's `benign_success` is `true`.
