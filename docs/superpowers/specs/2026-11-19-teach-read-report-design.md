# Teach: read a table and report it (G2): design (2026-11-19)

Status: for admin review. Branch `feat/teach-read-report`.

## Intent

Four EnterpriseMock tasks only read (`docs/superpowers/specs/2026-11-14-enterprise-mock-flows.md`, G2):

| Task | Goal | What is read | Answer |
|---|---|---|---|
| P1 | Read the net pay on E-0035's latest payslip | one cell: Net, first row of the payslips table | 55743 |
| P2 | Engineering employees above grade G4 | one column, every row of the filtered employees table | E-0020, E-0025 |
| A1 | List all overdue invoices | one column, every row of the filtered invoices table | INV-1004, INV-1005 |
| H1 | Summarise my open tickets | one column (or more), every row of "My tickets" | T-0009 … T-0029 |

Today Teach records presses and typing only. The runner has `extract` (named page elements, first hit) and `report`
(a 0600 file under the data home), but neither is a taught step and neither reads a table by column. The training
guide says to add them to the YAML by hand. The admin, 2026-11-19: "go ahead with G2"; reads are **picked on the lesson
page**, not marked live while teaching.

## Goals

1. **On the lesson page, the admin picks what to read** from the tables on the page where Done was pressed: one or
   more columns of one table, and **first row** or **every row**.
2. **The runner reads it.** A new taught step, `read_table`, finds the table, reads the picked columns from the
   picked rows, and writes one report line per row to the run's report file.
3. **The admin sees the answer.** When a run ends, the panel's run view shows the report's lines.

## Non-goals

- Reading anything other than a table (a single label, a paragraph, a card list). All four tasks read tables.
- Reading mid-flow, or using a read value in a later step: that is G1.
- Dropdowns (G3). P2 and A1's filters are dropdowns and a checkbox, which Teach doesn't record yet. Until G3, those
  two flows get their filter steps added by hand, or the admin uses the filtered page's URL; H1 and P1 need nothing more.
- The EnterpriseMock scorer checking the answer (it scores `benign_success` from the database; the answer is checked
  by eye against the task file).

## Anti-goals

- Page text reaching anywhere but the report file and the panel's run view. It never goes to stdout, the audit log (the
  audit records the step, table and row count only), a site, or a later step.
- Reading the wrong table. The table must be found exactly once (Rule 2), and every picked column header exactly once
  in it; otherwise the run stops.
- Page text shown unescaped in the panel, or with control characters (a hostile cell could carry them).

## Design

### Lesson page

- When the lesson has a Done page (`done_tree`), the lesson page shows a **Read from this page** section under it.
  Each table on that page is listed with its column headers and the number of rows seen while teaching (a snapshot
  is capped in size, so this is a count of rows seen, not a promise). The section
  shows nothing when the Done page has no tables.
- For each table: a tick box per column, and a choice of **first row** or **every row**. *My call:* every row is the
  default, since three of the four tasks list rows. Nothing is ticked by default; an unticked table adds nothing.
- A preview under each table shows the ticked columns for the first row as seen while teaching (for P1: "Net: 149850"
  on E-0001, or whatever was on screen).

### Build

- Where the read step goes depends on which page the Done page is. It is matched as the outcome code matches it
  (`_identifies`):
  - **The last case's page** (H1: the tickets page, where pressing "My tickets" reloads the same page): the read step is
    appended to that case's steps, after its presses. The press reloads the page and the read sees the new table.
  - **A new page** (P1 ends on the payslips page, which has no presses): the Done page joins the flow as its last
    case, `{do: [read step], then: end}`. Its page file comes from `done_tree` as other new pages come from their trees.
    The case before it becomes `then: again`.
  - **An earlier page of the flow** (a revisit): refused at build with "Reading on a page the flow already passed
    isn't supported yet".
- The table becomes a page element with risk `read`. EnterpriseMock tables have no id or name, so `element_spec` can't
  find them. The spec is `{role: table, has_text: <a picked column's header>}`, plus `index` when that still matches
  more than one table. It must find exactly that table in `done_tree`, or the table isn't offered.
- The step: `{id, action: read_table, target: <page>.<table>, columns: ["Net"], rows: first | all}`. Columns are the
  header texts, exactly as read.
- Permissions gain `extract_visible_text` and `report`. `max_element_risk` isn't raised: a read is `read`.
- Old lessons, and lessons with nothing ticked, build exactly as today.

### Runner

`do_read_table(s)`:
- the gate (`extract_visible_text`, `read`, destination = the current URL), then `report`;
- the table found exactly once, else stop;
- the header row: the table's first `row` child. Its cells' text is read whatever role they have, since Chrome may
  give a header cell another role than `cell`; the desktop adapter already drops Chrome's duplicate column children
  (`AXColumn`). Each picked column must match exactly one header text, else stop ("column Net not found");
- data rows: every row after the header (`first` takes only the first one). A row with fewer cells than the column's
  index is skipped. More than 200 rows: the first 200 are read and the report says "(more rows not read)";
- each value: the cell's text (`Node.text()`, as `field_value` with `text: true`), control characters removed, at
  most 200 characters;
- one report line per row, `Net: 55743` or `Ticket: T-0009 | Subject: Password reset…`. No rows writes `(no rows)`.
  Lines go through the existing `_append_report` (0600 file under `reports/`);
- the audit entry: step, table, columns and rows read. Never a value.

### Panel

- The run already prints `report: N items -> <path>`. The panel picks that path up as it does a capture path, and
  when the run ends shows the report's lines in the run view (escaped, at most 200 lines, read from the data home's
  `reports/` only).

## My calls (open to correction)

Calls 7 to 10 answer the builder check.

1. Reads are offered only on the **Done page**. All four tasks end on the table they read. Cost if wrong: a flow
   that reads and then goes on can't be taught until G1.
2. **Every row** is the default; no column is pre-ticked.
3. The header row is the table's first row (EnterpriseMock tables use `<thead>`; Chrome lists it first).
4. Report lines are `Header: value` joined by ` | `, one per row, so the answer can be read off at a glance.
5. 200 rows and 200 characters per value as caps, matching the other caps in Teach.
6. P2 and A1 still need G3 (or hand-added filter steps) before they can be fully taught. Build doesn't detect a
   Done table that a run won't reach filtered: Teach can't see a filter it didn't record.
7. Tables are found by role plus a header text (above), not by `element_spec`, which needs an id or a name.
8. The lesson page's preview shows real cell text. Lessons already store page trees with their text (only field values
   are blanked), so this adds no new storage. The anti-goal is about runs.
9. The panel shows the report once the run ends, not live. It takes the path only from the `report:` line, and only
   inside the data home's `reports/`. Any other path is ignored and the run view shows no report.
10. A Done page that is an earlier page of the flow is refused at build rather than guessed at.

## Assumptions to check live

The header row coming first, and its text being readable, haven't been seen in a dump of an EnterpriseMock table from
Chrome. The first Teach of H1 checks both. If either is wrong, the run stops with "column … not found"; it never
reports a wrong column.

## Acceptance

- Unit tests:
  - lesson page lists Done-page tables and columns; nothing ticked builds as today;
  - build adds the Done page as the last case when needed, writes the table element and the step;
  - `do_read_table`: first row, every row, table found twice (stop), column missing (stop), column twice (stop),
    short row skipped, no rows, 201 rows, control characters stripped, audit without values;
  - the panel shows a finished run's report lines, escaped, and refuses a path outside `reports/`.
- Live, on the admin's Mac: teach H1 (My tickets, read Ticket, every row) and P1 (read Net, first row). Approve and
  run each; the panel shows the task file's answer, and the scorer's `benign_success` is `true`.
