# Teach: read a table and report it (G2): design (2026-11-19)

Status: approved by the admin after architect review (2026-11-19). Branch `feat/teach-read-report`.

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

Amended after the architect review (2026-11-19, approve with amendments; findings 1-13 are folded in below).

### Which page a read is on

- Reads are offered only on the **Done page** (`done_tree`, `done_url`), and only when the Done page is a **new page**:
  one that no page in the lesson identifies. A page is identified by its exact title and first two headings
  (`studio.draft_page`).
  - H1: "My tickets" changes the title to "My tickets · Larkspur Helpdesk", so the Done page is new.
  - P1: the payslips page has no presses, so it is new.
- Every other case is refused at build, with the read not added. Lesson pages are matched as the
  outcome code does (`_identifies`), but its "else the last page" fallback is not used:
  - **the last page identifies it:** "Reading on the page your last press stayed on isn't supported yet". The runner
    doesn't wait or take a new snapshot after a taught click on the same page, so the read could see the old table;
  - **an earlier page identifies it:** "Reading on a page the flow already passed isn't supported yet";
  - **more than one page identifies it:** refused (Rule 2);
  - **the app already has a case for that page id** (a re-teach): "This page is already in the app; reads not added".
    Without this, `_cases` would drop the read silently.
- The read relies on the runner telling the Done page apart from the page before it. After the previous case's last
  press, `then: again` waits for and classifies the next page; if the old page still shows, that page's case runs
  again, bounded by `MAX_LEARNED`.

### One page list

- One helper, `pages_of(lesson)`, used by both `propose` and `build`: `lesson["pages"]` plus, when the Done page is new,
  `{url: done_url, title, tree: done_tree, events: []}`.
  - The known-page lookup runs on it too. If a known page file identifies the Done page, the table key is added to that
    page, which is rewritten, and its other apps are warned, as for count outcomes.
  - `build` writes the Done page's file only when a read is ticked. With nothing ticked, the build is exactly as today.

### Lesson page

- `propose` computes `proposal["reads"]`: one entry per table offered on the Done page. Each entry holds the table's
  spec, header texts, rows seen and a preview of the first row. Because it is in the proposal, the existing
  proposal digest binds what the admin saw.
- The page shows a **Read from this page** section listing those tables. For each table there is a tick box per
  column, and a choice of **every row** (the default) or **first row**. No column is ticked by default.
- The form posts indices only: `read:<t>:<c>` and `rows:<t>`. Header text never comes from the browser.
- `lesson_ui.edits` validates the indices. Ticks in more than one table are refused with a plain message.
- The section is hidden for Studio (sandbox) lessons.
- The preview shows real cell text. Lessons already store page trees with their text (only field values are blanked).
  "Rows seen" is a count of what the capped snapshot held, not a promise.

### The table's spec

- EnterpriseMock tables have no id or name, so `element_spec` can't find them.
- The spec is `{role: table, has_text: <header>}`. Each of the table's header texts is tried in turn, and the first one
  that finds exactly this table in `done_tree` is used. With none, the table isn't offered. There is no `index`: it is
  positional and would move silently to another table.
- The header check at run time is the real guard. A `has_text` can match a data cell; the header row can't be faked
  that way.

### Build

- The step: `{id, action: read_table, target: <page>.<table>, columns: [<header>, …], rows: first | all}`, the last
  (only) step of the Done page's case, `then: end`. The case before it becomes `then: again`.
- Permissions gain `extract_visible_text` and `report`, in the same block that adds `type_text`. `max_element_risk`
  isn't raised.
- `engine.check_read(d, pages)` is called from `check_learned` for top-level case steps. It checks:
  - `target` is `page.element`, and with pages given, the element exists with `role: table`;
  - `columns` is a non-empty list of at most 10 unique strings, each 1-200 characters, with no control characters;
  - `rows` is `first` or `all`;
  - the step is the last one in its case.
- `check_repeat` refuses `read_table`.
- The digest needs no change: the columns are in the flow bytes and the table is in the page bytes.

### Runner

`do_read_table(s)`:
- gates `extract_visible_text` (`read`, destination = the current URL) and `report`;
- finds the table exactly once (Rule 2), else stops;
- takes the header row: the table's first `row` child. Its cells' text is read whatever role they have. Each picked
  column must match exactly one header text, else it stops with "column Net not found";
- reads the data rows: every row after the header (`first`: only the first one).
  - A row too short for a column gets `(missing)` for that cell.
  - Past 200 rows, or when the snapshot hit its node cap, the report adds "(more rows not read)".
  - No rows writes `(no rows)`;
- for each value: the cell's text, with control characters removed, `|` replaced by `/`, and at most 200 characters;
- writes one line per row, `Net: 55743` or `Ticket: T-0009 | Subject: …`, through a report-file helper shared with
  `do_report`. The file is 0600 at `reports/<flow id>-<UTC stamp>.txt`;
- prints `report saved: reports/<flow id>-<stamp>.txt`. That is the file's name, never its content;
- writes the audit entry: step, table, columns and number of rows read, never a value.

### Try

A Try runs `read_table` in full, since a read is read-only, and the panel shows its report. Try is the admin's chance
to see the answer before Approve. H1 and P1 press only navigate links, so a Try reaches the read.

### Panel

- The panel takes a report only from a line matching
  `re.fullmatch(r"report saved: reports/[a-z0-9_]{1,64}-\d{8}T\d{6}Z\.txt", ln)` whose flow id is the running app's.
  This is the same pattern as captures.
- It opens the file with `O_NOFOLLOW` under `home/"reports"`, and refuses if `reports/` is a symlink.
- When the run ends, it shows at most 200 lines, escaped. Report text never goes to speech, `tell()` or a notification.

## My calls (open to correction)

1. Reads are offered only on a new Done page; the other cases are refused at build (above).
2. Every row is the default; no column is pre-ticked.
3. The header row is the table's first row.
4. Report lines are `Header: value` joined by ` | `, one per row.
5. Caps: 200 rows, 200 characters per value, 10 columns, one table.
6. P2 and A1 still need G3, or hand-added filter steps. Build can't detect a Done table that a run won't reach
   filtered.
7. Tables are found by role plus a header text that finds exactly that table.
8. The lesson page preview shows real cell text, which lessons already store.
9. The panel shows the report once the run ends, not live.

## Assumptions to check live

- The header row comes first, and its text is readable. If not, the run stops with "column … not found".
- Chrome may add a header group under the table, so header texts appear twice. That's harmless for the spec and the
  header row; the H1 dump confirms it.

## Acceptance

- Unit tests:
  - the lesson page offers a new Done page's tables, and hides them for Studio lessons;
  - nothing ticked builds exactly as today;
  - build adds the Done page's file and its case, and refuses each of the four non-new cases;
  - ticks in two tables are refused;
  - `check_read`: shape, last step, refused inside a repeat;
  - `do_read_table`: first row, every row, table found twice (stop), column missing (stop), column twice (stop), short
    row `(missing)`, no rows, 201 rows, control characters and `|`, audit without values;
  - Try reaches the read and shows the report;
  - the panel shows a finished run's report escaped, and ignores a line not matching the pattern or another app's id.
- Live, on the admin's Mac: teach H1 (My tickets, read Ticket, every row) and P1 (read Net, first row). Try, approve
  and run each. The panel shows the task file's answer, and the scorer's `benign_success` is `true`.
