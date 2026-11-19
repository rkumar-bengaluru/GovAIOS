# Teach: read a table and report it (G2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the lesson page the admin picks columns of one table on the Done page, plus first row or every row. The
runner gets a `read_table` step that writes one report line per row. The panel shows the report when the run ends,
and also after a Try.

**Architecture:**
- `engine.do_read_table` finds the table exactly once and matches each picked column to exactly one header text. It
  writes lines through a report-file helper it shares with `do_report`, and prints only the file's name.
- `lessons.propose` adds the Done page through `pages_of(lesson)` and offers its tables as `proposal["reads"]`.
  `lessons.build(reads=…)` keeps that page, and its `read_table` case, only when a read is ticked.
- The panel's lesson page posts indices only. The Talk page finds the report through a `report saved:` stdout line
  that it reads with a strict regex.

**Tech Stack:** Python 3.12, pytest, PyYAML.

**Spec:** `docs/superpowers/specs/2026-11-19-teach-read-report-design.md` (amended after the architect review; binding).

## Global Constraints

- Work on branch `feat/teach-read-report`; never switch branches.
- Never `git add -A`. Add explicit paths only. The untracked
  `docs/research/research_notes/GOV AIOS agent governance related work/site_terms_benchmarks.md` stays out of every
  commit.
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Full suite: `.venv/bin/python -m pytest -q -p no:warnings`. About 1443 tests pass on main, and the suite must pass
  before each commit. Don't run two pytest processes at once: test_macos.py flakes under concurrency.
- Page text goes only to the report file and the panel's run view. It never goes to stdout, the audit log, `tell()`,
  speech, a notification, a site or a later step.
- Rule 2: the table is found exactly once, and each picked column matches exactly one header text. Otherwise the run
  stops.
- Caps: 200 rows, 200 characters per value, 10 columns, one table. The panel shows at most 200 lines.
- Report name: `reports/<flow id>-<UTC %Y%m%dT%H%M%SZ>.txt`, mode 0600, in a 0700 `reports/` directory.
- Stdout line, verbatim: `report saved: reports/<flow id>-<stamp>.txt`.
- Panel pattern, verbatim: `re.fullmatch(r"report saved: reports/[a-z0-9_]{1,64}-\d{8}T\d{6}Z\.txt", ln)`.
- With nothing ticked, the built flow and page bytes are exactly as before this plan.

## Review Focus

1. **Every lesson form posts `rows:<t>=all`**, because the radio is checked by default. `edits` must treat a `rows`
   field with no ticks as "no read", not as an unknown field (which turns Approve into a 404). This is pinned in
   Task 3 by `test_edits_rows_alone_is_no_read`.
2. **A table with two headers of the same text**, where the admin ticks one of them. At run time it would always
   stop "found more than once", so build refuses it first. This is pinned in Task 2 by
   `test_build_refuses_a_header_shown_twice`.
3. **A header text that is also a data cell of another table.** That header must not become the spec. The next
   header that finds exactly this table is used instead, and a table with no such header isn't offered. This is
   pinned in Task 2 by `test_table_spec_skips_a_header_another_table_shows`.
4. **A column with an empty header** (an Actions column). It gets no tick box, and `edits` refuses its index. This is
   pinned in Task 3 by `test_edits_refuses_an_empty_header`.
5. **`reports/`, or the report file, is a symlink.** The panel shows nothing and doesn't follow it. This is pinned in
   Task 4 by `test_report_card_refuses_symlinks`.

---

### Task 1: Engine: the `read_table` step

**Files:**
- Modify: `govaios/engine.py`:
  - `LEARNED_ACTIONS` (line 32);
  - `check_learned` (line 203);
  - `check_repeat` (line 256);
  - `do_report` (line 1180);
  - new `table_rows`, `check_read`, `Runner._report_file`, `Runner.do_read_table`.
- Modify: `govaios/desktop/macos.py`: a `capped` property on `MacDesktop`, next to `web_root` (line 193).
- Test: `tests/test_read_table.py` (new). Copy the `Desk(FakeDesktop)`, `make` and `go` shape from
  `tests/test_type_step.py`.

**Interfaces:**
- Consumes:
  - `Runner.page_element(ref)`, which stops with `"<ref>: expected 1 element, found N"`;
  - `Runner.gate`, `Runner._act`, `Runner._audit`, `Runner._append_report`;
  - `CONTROL`.
- Produces:
  - **Flow step:**
    `{"id", "action": "read_table", "target": "<page>.<table key>", "columns": [<header>, …], "rows": "first"|"all"}`.
  - **`LEARNED_ACTIONS`** gains `"read_table"`.
  - **`table_rows(table: Node) -> tuple[list[str], list[list[str]]]`**, a module function:
    - the rows are `[n for n in table.walk() if n.role == "row"]`. The first one is the header row, and the rest are
      the data rows;
    - a cell is each child of a row, whatever its role, and its text is `(c.text() or c.name).strip()`;
    - with no rows, it returns `([], [])`.
    - Task 2 uses it too.
  - **`check_read(d: dict, pages: dict | None = None) -> None`**. It raises `Stop`.
  - **`Runner._report_file(self) -> Path`**:
    - on first use, it creates `home/"reports"` (mode 0o700) and sets `self.report_path`;
    - it returns `self.report_path`.
  - **`MacDesktop.capped -> bool`**: `getattr(self, "_count", 0) >= MAX_NODES` (the last snapshot hit the node cap).
    The Runner reads `getattr(self.d, "capped", False)`.
  - **Permissions:** `extract_visible_text` and `report`, both at risk `read`.

- [ ] **Step 1: Write the failing tests** in `tests/test_read_table.py`.

  **Fixture:**
  - `SITE = "http://localhost:8100"`, `PG = "localhost_tickets"`.
  - The page's identification is `{"title_matches": "^Tickets$", "anchors": []}`, and its element is
    `tickets: {role: table, has_text: Ticket, risk: read}`.
  - The flow `tf` has:
    - permissions `allow: [read_page, extract_visible_text, report]` and `max_element_risk: read`;
    - one step `{"id": "c", "action": "classify_page", "on_match": {PG: {"do": [{"id": "r", "action": "read_table",
      "target": f"{PG}.tickets", **step}], "then": "end"}}}`.
  - The `Desk` serves `N("document", "Tickets", children=[table, …])`. A cell is `N("cell", children=[N("text", x)])`.
  - `report(tmp_path)` returns the text of the only file in `tmp_path / "reports"`.

  **Tests:**
  - `test_read_first_row`:
    - the headers are Net and Gross, and the rows are `["55743", "70000"]` and `["1", "2"]`;
    - the step is `columns: ["Net"], rows: first`;
    - the report text is `"Net: 55743\n"`, and the file's mode is `0o600`;
    - `capsys` stdout contains a line that fullmatches the Global Constraints pattern, and doesn't contain `"55743"`.
  - `test_read_every_row`: columns `["Ticket", "Subject"]`, rows `all`. The report lines are
    `["Ticket: T-0009 | Subject: VPN down", "Ticket: T-0012 | Subject: Printer"]`.
  - `test_read_table_twice_stops`: two tables, both with a "Ticket" header.
    - The stop is `f"{PG}.tickets: expected 1 element, found 2"`.
    - `tmp_path / "reports"` doesn't exist.
  - `test_read_column_missing_stops`: the stop is `"column Net not found"`.
  - `test_read_column_twice_stops`: the header row is Ticket, Net, Net, and the step's columns are `["Net"]`. The stop
    is `"column Net found more than once"`.
  - `test_read_short_row_missing`: a data row with only `T-1` gives `"Ticket: T-1 | Subject: (missing)"`.
  - `test_read_no_rows`: a header row only gives the report `"(no rows)\n"`.
  - `test_read_201_rows`: 201 data rows with `rows: all`.
    - The report has 201 lines. The first 200 are rows, and the last one is `"(more rows not read)"`.
  - `test_read_capped_snapshot_says_more`: `desk.capped = True` and 2 rows give 2 row lines, then
    `"(more rows not read)"`.
  - `test_read_cleans_values`:
    - the cell `"a\x07b | Ticket: T-9999"` gives `"Ticket: ab / Ticket: T-9999"`;
    - a 250-character cell gives a value of exactly 200 characters.
  - `test_read_audit_has_no_values`:
    - `audit.jsonl` contains no cell text;
    - the one entry with `action == "read_table"` has `target == f"{PG}.tickets"`, `columns == ["Ticket"]`,
      `rows == 2` and `outcome == "done"`.
  - `test_read_in_a_try_runs_in_full`: the flow has `try: True`. The run ends without a Stop, and the report is
    written.
  - `test_check_read_shape`. Each of these gives `Stop` through `check_learned(flow_steps)`:
    - the target `"tickets"` (no dot): `"learned steps: read_table target must be page.element"`;
    - the columns `[]`, eleven names, `["a", "a"]`, `[""]`, `["x" * 201]`, `["a\nb"]` or `"Net"` (not a list):
      `"learned steps: read_table columns must be 1 to 10 unique names of 1 to 200 characters"`;
    - the rows `"some"`: `"learned steps: read_table rows must be first or all"`.
  - `test_check_read_target_must_be_a_table`: `check_learned(steps, pages)` with the element's role `button` gives
    `Stop("learned steps: read_table target localhost_tickets.tickets is not a table of its page")`.
  - `test_check_read_must_be_last`: a `click` after the read in the same `do` gives
    `Stop("learned steps: read_table must be the last step of its page")`.
  - `test_repeat_cannot_hold_a_read`: a `repeat` whose second step is a `read_table` gives
    `Stop("learned steps: a repeat cannot hold a read_table")`.
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_read_table.py -q`. Expected: FAIL (`read_table`
  not allowed / no `do_read_table`).
- [ ] **Step 3: Implement.**
  - **`check_learned`:** for each top-level case step `d` with action `read_table`:
    - call `check_read(d, pages)`;
    - then, if `d is not v["do"][-1]`, raise the "last step" Stop.
  - **`check_read`:** checks the target form, and with `pages`, that the element exists with `role: table`. Then the
    columns (control characters per `CONTROL`), then the rows.
  - **`check_repeat`:** refuses `read_table` before its `LEARNED_ACTIONS` check.
  - **`do_report`:** move its mkdir and naming into `_report_file()`. `do_report` keeps its own `report_items`
    counter and its own print, unchanged.
  - **`do_read_table(s)`**, in this order:
    1. `ref = self.ref(s["target"])`, then
       `self.gate("extract_visible_text", "read", target=ref, destination=self.d.current_url(self.app))`, then
       `self.gate("report", "read")`.
    2. `table, _ = self.page_element(ref)`, then `headers, data = table_rows(table)`.
    3. Each column matches exactly one header index; otherwise it stops, using the messages above.
    4. The rows read are `data[:1]` for `first`, else `data[:200]`.
       - For `all`, when `len(data) > 200` or `getattr(self.d, "capped", False)`, the line `"(more rows not read)"`
         is added.
    5. Each value is `CONTROL.sub("", v).replace("|", "/")[:200]`, or `"(missing)"` when the row is too short.
    6. A line is `" | ".join(f"{col}: {val}")`, and no rows gives `["(no rows)"]`.
    7. `self._act("report", self._append_report, "\n".join(lines) + "\n", target=ref)`.
    8. `print(f"report saved: reports/{path.name}", flush=True)`.
    9. `self._audit("action", action="read_table", target=ref, columns=s["columns"], rows=<data rows read>,
       outcome="done")`.
  - No Try special case: a read is read-only.
- [ ] **Step 4: Run the tests, then the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add govaios/engine.py govaios/desktop/macos.py tests/test_read_table.py
  git commit -m "feat(engine): a read_table step reads picked columns into the run's report"
  ```

### Task 2: Lessons: offer the Done page's tables; build the read

**Files:**
- Modify: `govaios/lessons.py`:
  - `propose` (line 197);
  - `_outcomes` (`done_pid`, line 334);
  - `_do` (line 422);
  - `preview` (line 513);
  - `build` (line 535);
  - new `pages_of`, `_tables` and `_table_key`.
- Test: `tests/test_lessons.py`. Reuse `joblens(tmp_path)`, `_plan(...)` and the hash in
  `test_build_old_lesson_unchanged`.

**Interfaces:**
- Consumes: `engine.table_rows`, `engine.find_all`, `engine.check_learned` (which now runs `check_read`), and
  `_identifies`.
- Produces:
  - **`pages_of(lesson) -> list[dict]`:**
    - It returns `lesson["pages"]` plus, when the lesson has both `done_tree` and `done_url`,
      `{"url": done_url, "title": done_tree.get("name") or "", "tree": done_tree, "events": []}`.
    - `propose` iterates it, then keeps the Done entry only when the Done page is new and the lesson isn't a
      `SANDBOX` one.
    - `build` zips `proposal["pages"]` with it.
    - This is how the spec's "plus, when the Done page is new" is placed: newness needs the lesson pages' drafted
      or known YAML, which only `propose` has.
  - **A kept Done page in `proposal["pages"]`:** it is always the last entry, with `"done": True` and `"steps": []`.
    `"new"` and `"added"` work as for any page, so a known page from `pages_dir` is found the same way.
  - **`proposal["reads"]`:** a list with one entry per offered table:
    `{"key": str, "spec": {"role": "table", "has_text": str}, "headers": [str], "rows": int, "preview": [str]}`.
    - `rows` is the number of data rows in the snapshot.
    - `preview` is the first data row's cells, each cut to 200 characters (`[]` with no rows).
    - The list is empty when nothing is offered.
  - **`proposal["read_refused"]`:** `str | None`, one of:
    - `"Reading on the page your last press stayed on isn't supported yet"`;
    - `"Reading on a page the flow already passed isn't supported yet"`;
    - `"The page Done was pressed on looks like more than one page of this lesson; reads not added"`.
    - When it is set, `reads` is `[]` and the Done page isn't kept.
  - **`build(..., sources=None, reads=None)`:** `reads` is `None` or
    `{"table": int, "columns": [int, …], "rows": "first"|"all"}` (from Task 3's `edits`).
  - **The proposal line a read adds** (made inside `build` only):
    `{"kind": "read_table", "label": "Read <cols>", "target": "<pid>.<key>", "columns": [str], "rows": str,
    "keep": True}`. `_do` maps it to the Task 1 step.
  - **`_table_key(els, spec) -> str`:** works like `_count_key`. It reuses an equal `{**spec, "risk": "read"}` entry,
    or else adds `<slug(has_text)>_table`, then `_2` and so on.

- [ ] **Step 1: Write the failing tests.**

  **Fixture:** `_reading(tmp_path, done=None)` returns `(les, app)`:
  - it starts from `joblens(tmp_path)`;
  - `les["done_tree"]` is
    `capture.tree(N("document", "JobLens · My tickets", heading "My tickets", table))`;
  - the table's header row is Ticket, Subject and an empty cell, with two data rows `T-0009 VPN down` and
    `T-0012 Printer`;
  - `les["done_url"]` is `"http://localhost:8100/tickets"`;
  - `done` replaces the tree.

  **Tests:**
  - `test_propose_offers_the_done_pages_tables`:
    - `prop["pages"][-1]` has `done` True, `new` True and `steps == []`;
    - `prop["reads"] == [{"key": "ticket_table", "spec": {"role": "table", "has_text": "Ticket"},
      "headers": ["Ticket", "Subject", ""], "rows": 2, "preview": ["T-0009", "VPN down", ""]}]`;
    - `prop["read_refused"] is None`.
  - `test_build_without_reads_is_unchanged`: `_reading` built with `reads=None` gives the hash in
    `test_build_old_lesson_unchanged`. No new page file is written, and the Discover case is still `then: end`.
  - `test_build_adds_the_done_page_and_its_read`: `reads={"table": 0, "columns": [0, 1], "rows": "all"}`.
    - The Done page's YAML is in `plan["pages"]` and `plan["new"]`, and its elements hold
      `ticket_table: {role: table, has_text: Ticket, risk: read}`.
    - `on[<done id>] == {"do": [{"id": f"learned_{pid}_1", "action": "read_table", "target": f"{pid}.ticket_table",
      "columns": ["Ticket", "Subject"], "rows": "all"}], "then": "end"}`.
    - The Discover case is now `then: again`.
    - `"extract_visible_text"` and `"report"` are in `permissions.allow`.
    - `max_element_risk` is unchanged.
    - `"http://localhost:8100"` is still one destination.
  - `test_read_on_the_last_page_refused`: with `done=` the Discover tree:
    - `prop["read_refused"] == "Reading on the page your last press stayed on isn't supported yet"`;
    - `prop["reads"] == []`;
    - `build(reads={...})` raises `ValueError` with that text.
  - `test_read_on_an_earlier_page_refused`: with `done=` the Applications tree, the result is
    `"Reading on a page the flow already passed isn't supported yet"`, the same way.
  - `test_read_on_two_pages_refused`: monkeypatch `lessons._identifies` to `lambda p, r: True`. The result is the
    "more than one page" text, the same way.
  - `test_read_on_a_page_the_app_handles_refused`:
    1. Add the Done page's id to the app's `on_start.on_match` as a hand-written case, then re-bind the lesson's
       digest.
    2. `build(reads=...)` raises
       `ValueError("This page is already in the app; reads not added")`.
  - `test_read_on_a_known_page_adds_its_table`:
    1. Write `studio.draft_page(les["done_tree"], "helpdesk_tickets")` into `pages/` first.
    2. `prop["pages"][-1]` has `new` False and `id == "helpdesk_tickets"`.
    3. After the build, `"ticket_table"` is in that page's `added`, and the page is rewritten in `plan["pages"]`.
  - `test_table_spec_skips_a_header_another_table_shows`:
    - table A's headers are Net and Gross, and table B has a data cell "Net";
    - A's spec is `has_text: "Gross"`;
    - a table whose every header also appears in another table isn't in `reads`.
  - `test_build_refuses_a_header_shown_twice`:
    - the headers are Net, Net and Gross;
    - `reads={"table": 0, "columns": [0], "rows": "first"}` raises
      `ValueError("column Net appears twice in this table")`.
  - `test_sandbox_lesson_offers_no_reads`: with `les["flow"] = None`, `prop["reads"] == []` and no page has `done`.
  - `test_preview_ignores_the_done_page`: `preview(_reading(...))`'s YAML still has Discover's case at `then: end`.
- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_lessons.py -q -k "read or done_page or sandbox_lesson_offers or preview_ignores"`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **`propose`:**
    - Loop over `pages_of(lesson)` instead of `lesson["pages"]`.
    - With `n = len(lesson["pages"])`, take `hits = [k for k in range(n) if _identifies(out_pages[k]["yaml"]["page"], droot)]`.
      An empty `hits` means new.
    - When the Done page isn't new, or the lesson is a sandbox one: pop the Done entry from `out_pages` and
      `marks`, and set `read_refused` (`None` for a sandbox lesson).
    - The closing `hand_over` goes on `out_pages[n - 1]`, not `out_pages[-1]`.
    - Return `{"pages", "bank", "reads", "read_refused"}`.
  - **`_tables(root, page) -> list[dict]`:** the `reads` entries.
    - For each `table` node (in walk order), try its non-empty headers in order. Keep the first one where
      `engine.find_all(root, {"role": "table", "has_text": h}, page)` is exactly `[that node]` (compare by identity).
    - Keys come from `_table_key` on a copy of the Done page's elements, so two tables never share a key.
  - **`_outcomes`:** compute `done_pid` over `out_pages[:len(lesson["pages"])]`, so count outcomes are attributed
    exactly as today.
  - **`build`:**
    - Right after the deep copy:
      - with `reads` None, drop any page with `done` from `proposal["pages"]`;
      - otherwise, raise `ValueError(read_refused)` if `read_refused` is set, and `ValueError("No page to read on")`
        if the last page isn't `done`.
      - Then check that each picked column index points at a non-empty header that appears once in `headers`.
      - Add `{**spec, "risk": "read"}` under `key` to the page's elements. On a known page, add `key` to `added`.
      - Append the `read_table` line.
    - After `on` is known, raise the "already in the app" error when the Done page's id is in `on`.
    - Zip `proposal["pages"]` with `pages_of(lesson)` for the page files and for `destinations`.
    - Add `extract_visible_text` and `report` to `allow` when a `read_table` step was made. Do this in the block
      that adds `type_text`, and leave `max_element_risk` alone.
  - **`preview`:** drop any page with `done` before `_cases`.
- [ ] **Step 4: Run the tests, then the full suite.** Expected: PASS. `test_build_old_lesson_unchanged` must keep its
  hash.
- [ ] **Step 5: Commit.**
  ```bash
  git add govaios/lessons.py tests/test_lessons.py
  git commit -m "feat(lessons): offer the Done page's tables; build a read_table case when one is ticked"
  ```

### Task 3: Lesson page "Read from this page", and Try reads

**Files:**
- Modify: `govaios/panel/lesson.py`:
  - `edits` (line 25);
  - `page` (line 106): skip the `done` page in the section loop; the "last page gets no steps" note uses the last
    non-`done` page;
  - `BadCap`'s docstring;
  - new `_reads(proposal, flow_cases)`.
- Modify: `govaios/audit/web.py`:
  - `lesson_ctx` (line 1680): a known Done page with offered tables joins `grown`, so its other apps are listed;
  - `lesson_plan` (line 1742): unpack and pass `reads`.
- Test: `tests/test_lessons.py` (the `edits` and page tests, beside `test_edits_reads_sources`) and
  `tests/test_panel_web.py` (Try, beside `test_try_types_recorded_values`).

**Interfaces:**
- Consumes: Task 2's `proposal["reads"]`, `proposal["read_refused"]`, the `done` page and `build(..., reads=)`.
- Produces:
  - **Form fields:** `read:<t>:<c>` = `1`, and `rows:<t>` = `first` | `all`.
  - **`edits(proposal, form)`** returns a 6-tuple:
    `(deleted, keeps, repeats, outcomes, sources, reads)`.
    - `reads` is `None` or `{"table": t, "columns": sorted [c], "rows": form.get(f"rows:{t}", "all")}`.
    - A valid `rows:<t>` with no ticks is accepted and ignored.
    - Ticks in two tables raise `BadCap("Read columns from one table only")`. `BadCap` now means any form choice the
      admin can fix, and web.py already tells it as `Not approved: <e>.`.
    - An index out of range, an empty header, or a `rows` value other than `first` or `all` raises
      `ValueError("unknown field")`.
    - Read the tables as `proposal.get("reads") or []`: the proposals that existing tests build by hand have no
      such key.

- [ ] **Step 1: Write the failing tests.**
  - `test_edits_reads_one_table`: a proposal with `reads` of 2 tables (`headers` `["Ticket", "Subject", ""]`).
    - `edits(prop, {"read:0:1": "1", "read:0:0": "1", "rows:0": "first"})[5] == {"table": 0, "columns": [0, 1],
      "rows": "first"}`.
  - `test_edits_rows_alone_is_no_read`: `edits(prop, {"rows:0": "all", "rows:1": "all"})[5] is None`.
  - `test_edits_refuses_two_tables`: `{"read:0:0": "1", "read:1:0": "1"}` raises `BadCap`, with the message above.
  - `test_edits_refuses_an_empty_header`: each of these raises `ValueError`:
    `{"read:0:2": "1"}`, `{"read:0:3": "1"}`, `{"read:2:0": "1"}` and `{"rows:0": "some"}`.
  - `test_lesson_page_offers_reads` (on `_reading` from Task 2):
    - the HTML has `<h2>Read from this page</h2>`;
    - it has `name='read:0:0' value=1`, unchecked, and has no `read:0:2`;
    - it has `<input type=radio name='rows:0' value=all checked>` and `value=first`;
    - a header or preview of `<b>x</b>` shows as `&lt;b&gt;x&lt;/b&gt;`;
    - the Done page gets no step section of its own.
  - `test_lesson_page_shows_why_reads_are_refused`: `prop["read_refused"]` set gives that text, escaped, and no
    `read:` field.
  - `test_lesson_page_hides_reads_for_studio`: a sandbox lesson's page has no "Read from this page".
  - `test_try_reads_the_table` (test_panel_web.py):
    1. `_open` and `_done`, then set the lesson's `done_tree` and `done_url` to the tickets page, as `_typed_lesson`
       edits a lesson.
    2. Post `/lesson/try` with `p`, `read:0:0=1` and `rows:0=all`.
    3. Check the Try copy:
       - its step list (`_try_steps`) has one `read_table` with `columns == ["Ticket"]`;
       - `"report" in wf["permissions"]["allow"]`;
       - `panel.made[-1].started`;
       - `Runner(panel.made[-1].flow_path, None, panel.home)` loads it, so `check_read` passes with the pages.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - **`_reads`:** renders the section after the page sections, and only when the lesson isn't `SANDBOX`.
    - If `read_refused` is set, show it as a note.
    - Else, if the Done page's id is in `flow_cases`, show the note "This page is already in the app; reads not
      added".
    - Else, for each table `t`, show a fieldset whose legend is `Table {t+1}: {rows} rows seen`. Inside it:
      - one checkbox per non-empty header, with the escaped header and a `“preview”` cell;
      - the two `rows:` radios, "Every row" (checked) and "First row".
    - If nothing is offered, show nothing.
  - **`web.py`:**
    - `lesson_plan` unpacks the 6-tuple and passes `reads=reads` to `lessons.build`.
    - `try_lesson` needs no change: it builds through `lesson_plan`, and its `recorded()` leaves `read_table` alone.
- [ ] **Step 4: Run the tests, then the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add govaios/panel/lesson.py govaios/audit/web.py tests/test_lessons.py tests/test_panel_web.py
  git commit -m "feat(studio): pick a table's columns to read on the lesson page; Try runs the read"
  ```

### Task 4: The panel shows the finished run's report

**Files:**
- Modify: `govaios/audit/web.py`:
  - new module-level `REPORT_LINE` and `report_lines(home, name)`;
  - new `report_card()` inside `make_server`, rendered in `talk()` right after `result_card()` (line 846).
- Modify: `docs/backlog.md`: G2 built 2026-11-19. P2 and A1 still need G3's dropdowns, or hand-added filter steps.
- Test: `tests/test_panel_web.py`. Reuse `_running`, `_tick`, `_tells` and `P.spoken`.

**Interfaces:**
- Consumes: Task 1's stdout line, through `panel.run.lines()`. That works for both `RunLaunch` and `HelperRun`: the
  helper forwards every line, but no extra attributes. So neither `launch.py` nor `helper.py` changes.
- Produces:
  - **`REPORT_LINE`:** `re.compile(r"report saved: reports/([a-z0-9_]{1,64})-\d{8}T\d{6}Z\.txt")`, used with
    `fullmatch`.
  - **`report_lines(home: Path, name: str) -> list[str] | None`:**
    - `None` if `home/"reports"` is a symlink, or the open fails;
    - it opens the file with `os.open(..., O_RDONLY | O_NOFOLLOW)` and reads at most 1 MiB;
    - it decodes with `errors="replace"`, removes `[\x00-\x1f\x7f]` from each line, and returns the first 200 lines.
  - **`report_card()`:**
    - it returns `""` while `live()`, or when `panel.run` is None;
    - otherwise, it takes the last line of `panel.run.lines()` that fullmatches `REPORT_LINE`, with group 1 ==
      `panel.app.id`;
    - it renders `<section class=appcard><h2>{escape(app name)}: report</h2><ul><li>…</li></ul></section>`, each
      line escaped.
    - Its text is never passed to `tell`, `panel.speak` or `panel.notify`.

- [ ] **Step 1: Write the failing tests.**
  - `test_finished_run_shows_its_report_escaped`:
    1. `r = _running(P)`, `aid = P.srv.panel.app.id`.
    2. Write `P.home/"reports"/f"{aid}-20261119T101500Z.txt"` with 250 lines of `"Ticket: <b>T-0009</b>\x07"`.
    3. Append the matching `report saved:` line to `r._lines`, then set `r.done, r.code = True, 0` and call `_tick(P)`.
    4. Check the body of `P.get("/")`:
       - it contains `"Ticket: &lt;b&gt;T-0009&lt;/b&gt;"` exactly 200 times;
       - it contains no `"<b>T-0009"` and no `"\x07"`.
    5. `T-0009` is in no `_tells(P)` line and in no `P.spoken` entry.
  - `test_report_card_ignores_other_lines`: each of these shows no report card, with the file present:
    - `"report saved: reports/../x-20261119T101500Z.txt"`;
    - `"report saved: reports/other_app-20261119T101500Z.txt"` (another app's id);
    - `"report saved: /abs/path.txt"`;
    - a `report saved: reports/…` line with text after it.
  - `test_report_card_refuses_symlinks`: the card shows nothing in either case:
    - `reports/` is a symlink to a directory that holds the file;
    - the report file is a symlink.
  - `test_no_report_card_while_running`: `r.done = False` with the line present gives no report card.
  - `test_try_report_shows_after_the_try`: set up as in `test_try_approval_is_revoked_after_the_run`, with the line
    for `TRY_ID` and its file. After `_tick`, the card shows the lines. The Try approval is still revoked.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** as in Produces. Update `docs/backlog.md`.
- [ ] **Step 4: Run the tests, then the full suite.** Expected: PASS.
- [ ] **Step 5: Commit.**
  ```bash
  git add govaios/audit/web.py docs/backlog.md tests/test_panel_web.py
  git commit -m "feat(panel): show a finished run's report, escaped, on the Talk page"
  ```

## Live check (the admin, on the Mac, after merge)

1. Rebuild and install, then reload the extension.
2. In EnterpriseMock, teach H1:
   - press "My tickets", then Done;
   - on the lesson page, tick Ticket and keep "Every row";
   - Try it. The Talk page shows T-0009 … T-0029.
3. Approve H1 and Run it. Check that `/score` gives `benign_success: true`.
4. Teach P1 the same way: open E-0035's payslips, then Done; tick Net and choose "First row". Try it, approve it and
   run it. The report shows `Net: 55743`.
5. Check the H1 accessibility dump: is the header row the table's first `row`, and do its texts appear twice (a
   header group)?
