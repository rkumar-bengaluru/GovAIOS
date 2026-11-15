# Outcome checks and proof packets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every own-app press that changes data carries a taught outcome that each run checks after the press, and a
panel run can be exported as a signed proof packet that a standalone verifier checks.

**Architecture:**
- **Audit:** run entries gain a per-run chain (`run`, `run_seq`, `run_prev`).
- **Teaching:** the recorder keeps one blanked tree per press plus a Done tree. `lessons.propose` diffs them into
  outcome proposals. The lesson page lets the admin tick them, and `lessons.build` writes `outcomes` onto flow steps.
- **Running:** the engine reads "before" values, presses, polls for the outcome, and audits
  `confirmed`/`not_seen`/`not_checked`/`unchecked`.
- **Packets:** a new `govaios/audit/packet.py` builds packets, and `verify.py` gains a packet mode.

**Tech Stack:** Python 3, pytest, PyYAML, `cryptography` (ECDSA P-256), the existing FakeDesktop/`N` test doubles in
`tests/conftest.py`.

**Spec:** `docs/superpowers/specs/2026-11-14-outcome-checks-design.md` (read it first; "Settled n" below refers to its
section).

## Global Constraints

- The audit stores metadata only: no item text, names or field values. New fields go into `FIELDS` and new kinds into
  `KINDS` in `govaios/audit/log.py`. Field values are `str`, `int` or `None`.
- `govaios/audit/verify.py` imports only stdlib and `cryptography`.
- Outcome kinds in this build: `count` and `item_left` only.
- Polling: about every 1 s, for up to **15 s**. An outcome holds when it holds on **two consecutive reads**.
- Expected count = "before" + the taught `change`, never a number seen while teaching.
- Audit `outcome` values: `confirmed`, `not_seen`, `not_checked`, `unchecked`.
- The stop text starts with `result not seen`, and `result not seen` is in `RUN_STOPS`.
- Fingerprint = SHA-256 hex of `f"{run}\n{round}\n{norm(identity)}"`, where `norm` = NFC, strip, collapse whitespace,
  casefold. The verifier module documents it.
- The rule "a press needs an outcome" covers `click` steps whose target element has `risk: submit`, in flows with an
  own destination (`localhost` / `127.0.0.1`, `policy.OWN_HOSTS`).
- Packet export: panel session plus CSRF, no Touch ID. Each export writes a signed `packet_export` entry.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never `git add -A`. Never commit
  `docs/research/research_notes/…/site_terms_benchmarks.md`.
- Test command: `.venv/bin/python -m pytest -q`. The whole suite passes at the end of each task (1324+ tests).

## Review Focus

1. **Two profiles with the same name in Shortlisted:** item_left must count by identity (2 → 1), not by presence. Test
   in Task 3.
2. **A flicker:** the count reads 8, then 7, then 8, 8. Confirm only on two consecutive matching reads. Test in Task 3.
3. **A run started when Promoted was already 12** (taught at 7): expect 13, not 8. Test in Task 3.
4. **A Repeat's stop and audit lines no longer carry the profile name.** A JobLens fixture run's audit file must not
   contain the name string. Test in Task 2.
5. **A queued second run of the same app after `not_seen`:** the queue is cleared before it can start. Test in Task 8.

---

### Task 1: Per-run audit chain

**Files:**
- Modify: `govaios/audit/log.py:22-28` (KINDS, FIELDS)
- Modify: `govaios/engine.py:316-321` (`Runner._audit`)
- Test: `tests/test_engine_audit.py`

**Interfaces:**
- Produces:
  - kinds `outcome` and `packet_export`
  - fields `run`, `run_seq`, `run_prev`, `fingerprint`, `round`, `count_before`, `count_after`, `expected`,
    `chain_count`, `chain_head`
  - `Runner._run_seq: int` and `Runner._run_prev: str` (64 zeros at start)
  - every entry a Runner with `run_id` writes carries `run`, `run_seq` and `run_prev`; a Runner without `run_id` (CLI)
    writes none of them.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_entries_chain_by_run_prev(tmp_path, monkeypatch):
    r = make_runner(tmp_path, monkeypatch, run_id="run-abc")   # use this file's existing runner helper, give it run_id
    r.run()
    es = [json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    mine = [e for e in es if e.get("run") == "run-abc"]
    assert mine[0]["kind"] == "flow_start" and mine[0]["run_seq"] == 1 and mine[0]["run_prev"] == "0" * 64
    assert [e["run_seq"] for e in mine] == list(range(1, len(mine) + 1))
    assert all(b["run_prev"] == a["hash"] for a, b in zip(mine, mine[1:]))

def test_cli_run_has_no_run_fields(tmp_path, monkeypatch):
    r = make_runner(tmp_path, monkeypatch, run_id=None)
    r.run()
    assert not any("run" in json.loads(l) for l in (tmp_path / "audit.jsonl").read_text().splitlines())
```

- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/test_engine_audit.py -q -k "run_prev or run_fields"`.
  Expected: FAIL (KeyError `run_seq` / AuditError "audit field(s) not allowed").
- [ ] **Step 3: Implement.** Add the kinds and fields. In `Runner._audit`, when `self.run_id` is set:
  - pass `run=self.run_id`, `run_seq=self._run_seq + 1`, `run_prev=self._run_prev`;
  - after `append` returns, set `self._run_seq` and `self._run_prev = entry["hash"]`.

  Initialise both in `__init__`. If `append` raises, leave both unchanged (spec Settled 1, known edge).
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(audit): run entries carry run, run_seq and run_prev`.

### Task 2: No item text in run entries; fingerprints

**Files:**
- Create: `govaios/fingerprint.py`
- Modify: `govaios/engine.py:858-892` (`do_repeat`)
- Test: `tests/test_repeat.py`, `tests/test_fingerprint.py`

**Interfaces:**
- Produces: `fingerprint.of(run: str, round_no: int, identity: str) -> str` (64 hex chars) and
  `fingerprint.norm(s: str) -> str`.
- Changes in `do_repeat`:
  - `repeat` entries log `round=<1-based round>` and `fingerprint=of(run_id or "", round, label)`, never
    `target=label`;
  - the stop texts become `f"repeat stopped on round {k + 1} after {k} done: {e}"` and
    `f"round {k + 1}: the item is still on the list after its round"`.
  - `item_label` stays, for identity only.

- [ ] **Step 1: Write the failing tests**

```python
def test_norm_and_of():
    assert fingerprint.norm("  Ada  LOVELACE ") == "ada lovelace"
    assert fingerprint.of("r1", 1, "Ada Lovelace") == fingerprint.of("r1", 1, " ada  lovelace")
    assert fingerprint.of("r1", 1, "Ada") != fingerprint.of("r2", 1, "Ada") != fingerprint.of("r1", 2, "Ada")

def test_repeat_audit_has_no_item_text(tmp_path, monkeypatch):
    # this file's existing two-profile Repeat fixture, with profile names "Ada Lovelace" and "Alan Turing"
    run_repeat_fixture(tmp_path, monkeypatch, names=["Ada Lovelace", "Alan Turing"])
    text = (tmp_path / "audit.jsonl").read_text()
    assert "Ada" not in text and "Turing" not in text
    assert '"fingerprint"' in text
```

- [ ] **Step 2: Run them.** Expected: FAIL (module missing; name in audit).
- [ ] **Step 3: Implement** `govaios/fingerprint.py` (stdlib `hashlib`, `unicodedata`), and the `do_repeat` changes
  above. Update existing `test_repeat.py` assertions that expected the label in stop texts.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** `fix(engine): repeat entries carry a fingerprint, never the item's text`.

### Task 3: The engine checks outcomes

**Files:**
- Modify: `govaios/engine.py` (constants at :36-44, `page_root` :415, `steps`/step dispatch, `do_click` press branch
  :933-946, `do_repeat` wait :877-881, `_run` except :499-502)
- Test: Create `tests/test_outcomes.py`

**Interfaces:**
- Consumes: Task 1 fields; `fingerprint.of`.
- Flow schema (written by Task 6, also by hand): any step may carry
  `outcomes: [{"for": <press step id>, "kind": "count", "target": "<page>.<element>", "change": <int>} |
  {"for": <press step id>, "kind": "item_left"}]`. These are checked after that step.
  - `item_left` is valid only on a step inside a `repeat`'s `steps`.
  - `check_learned` rejects an outcome whose `for` is not a step id of the flow.
- Produces:
  - `OUTCOME_POLL_S = 15` and `RESULT_NOT_SEEN = "result not seen"`, added to `RUN_STOPS`
  - `Runner.counts: dict[str, int]`: last-seen value per count target
  - `Runner._pending: dict[press_id, dict]`
  - `count_of(name: str) -> int | None`: the trailing `(N)` of a name, at module level

**Behaviour to implement:**
1. **Remember counts.** Whenever `page_root(page_id)` returns a root, for every count outcome in the flow whose target
   page is `page_id`, read the element. If exactly one is found and `count_of` parses, store it in
   `self.counts[target]`.
2. **Before the press** (the `do_click` `submit` branch, before the gate), for each outcome whose `for` is this step's id:
   - **count:** `before = self.counts.get(target)`. If it's `None`, raise
     `Stop(f"cannot check {name}: {target} not seen before the press")`, which is safe because nothing is pressed yet.
   - **item_left:** before = the round's identity count. In `do_repeat`, count candidates whose `item_label` equals this
     round's label; store it in `self.ctx["round"]`.

   Store everything in `self._pending[step_id]`. If the press step has **no** outcome anywhere in the flow, audit
   `outcome` with `outcome="unchecked"` right after the press action.
3. **After a step that carries `outcomes`**, call `self._check_outcomes(step)`. It polls with `current_page([target
   page])` every 1 s up to `OUTCOME_POLL_S`:
   - **count** holds when the value equals `before + change`;
   - **item_left** holds when the identity count is below its before value;
   - all of a step's outcomes must hold on two consecutive reads.

   On success, audit one `outcome` entry per outcome: `outcome="confirmed"`, `step=<for>`, `count_before`,
   `count_after`, `expected` (count only), plus `fingerprint` and `round` (item_left only). On timeout, audit
   `outcome="not_seen"` with the last values seen (`count_after` = last value or None), then
   `raise Stop(f"{RESULT_NOT_SEEN}: {button} was pressed, its result did not appear")`. Here `button` is the press
   element's `name` or `name_matches` from the page file, never page text.
4. **In `_run`'s except**, before the `stop` entry: every press still in `self._pending` gets an `outcome` entry with
   `outcome="not_checked"`.
5. **In `do_repeat`**, skip the 10 s "still on the list" wait when the round's steps carry an `item_left` outcome.

- [ ] **Step 1: Write the failing tests** in `tests/test_outcomes.py`. Use a FakeDesktop whose `web_root` returns trees
  from a list you advance on each `click`, and the JobLens-shaped page:
  - tabs `Shortlisted (2)` and `Promoted (7)`;
  - one card per profile, each with a `Review` button;
  - a Review dialog with `Approve & promote`.

  Tests:
  - `test_confirmed_count_and_item`: after the press the tree shows `Promoted (8)` and one fewer card. The audit has
    `outcome` entries with `outcome == "confirmed"`, `count_before == 7`, `count_after == 8`, and a `fingerprint` of
    64 hex chars.
  - `test_expected_is_before_plus_change`: start at `Promoted (12)` → confirmed at 13. A tree showing 8 never confirms.
  - `test_flicker_needs_two_reads`: the after reads go 8, 7, 8, 8. Confirmed, and exactly one `outcome` entry per
    outcome.
  - `test_same_name_twice`: two cards both named "Ada Lovelace". After the press one remains → item_left confirmed.
  - `test_not_seen_stops_and_ends_run`: Promoted stays 7. `Stop` message starts with `"result not seen"`,
    `engine._ends_run(stop)` is True, the audit has `outcome == "not_seen"` with `count_after == 7`, and there was
    exactly one press click.
  - `test_not_checked_when_run_dies_first`: the outcome is on a later step whose page never appears →
    `outcome == "not_checked"`.
  - `test_unchecked_for_press_without_outcome`: the old-app flow (no `outcomes`) → one `outcome == "unchecked"` entry.
  - `test_before_unknown_stops_before_press`: the count element is never on any page read → Stop, and no click was
    made.
  - `test_outcome_for_unknown_step_rejected`: `check_learned` raises `Stop` for `for: "nope"`.

  Patch `engine.time.sleep` and `engine.time.time` so polling ends without waiting.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the behaviour above.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(engine): check each press's taught outcome after it, by polling`.

### Task 4: Approval needs outcomes

**Files:**
- Modify: `govaios/engine.py` (new `outcomes_missing`; `Runner.approve_flow` :369)
- Test: `tests/test_outcomes.py`, `tests/test_press_grant.py` (its fixture press flow gains an outcome or is
  pre-approved)

**Interfaces:**
- Produces: `outcomes_missing(wf: dict, pages: dict[str, dict]) -> list[str]`, a module-level function. It returns the
  press labels (the element's `name` or `name_matches`) of every `click` step, at any depth including repeats and
  `on_match` cases, whose target element has `risk == "submit"`, where no step's `outcomes` has `for` equal to that
  step id, in flows with an own destination. Empty means OK.
- `approve_flow`: when the digest is not yet approved and `outcomes_missing` is non-empty, raise
  `Stop("needs an outcome before approval: re-teach " + ", ".join(labels))` **before** asking Touch ID. An already
  approved digest is never checked.

- [ ] **Step 1: Write the failing tests:**
  - `test_missing_lists_unchecked_press`: the flow with a submit click and no outcome returns `["Approve & promote"]`.
    With an outcome `for` that step, it returns `[]`.
  - `test_outside_only_flow_not_checked`: destinations `["https://boards.greenhouse.io"]` returns `[]`.
  - `test_approve_flow_refuses_before_touch_id`: a monkeypatched `auth.approve` records calls. `approve_flow()` raises
    `Stop` starting with `"needs an outcome"`, and no approve call was made.
  - `test_approved_digest_keeps_running`: pre-approve the digest. `run()` presses and logs `unchecked`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** Expected: PASS. Fix fixtures that relied on approving submit flows without
  outcomes by pre-approving the digest.
- [ ] **Step 5: Commit** `feat(engine): a press needs an outcome before its app is approved`.

### Task 5: Recorder keeps a tree per press and at Done

**Files:**
- Modify: `govaios/recorder.py:82-152`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Produces:
  - each click event in a lesson gains `"before": <_blank(root) tree>`, the snapshot already read at the press, with no
    extra read;
  - on `kind == "done"`, if the current page is own or allowed (same test as `_down`) and `web_root` returns a root,
    `self.doc["done_tree"] = _blank(root)` and `"done_url": _key(url)`, written with `lessons.write` before
    `self.done = True`. An `OSError` there only sets `self.note = UNSAVED`.
- Old lessons without these keys stay readable. Consumers treat a missing key as "no tree".

- [ ] **Step 1: Write the failing tests:**
  - `test_each_press_keeps_its_tree`: two presses on one page; their `before` trees differ (the second shows
    `Promoted (8)`).
  - `test_done_keeps_a_tree`: after `handle({"kind": "done"})` the lesson file has `done_tree` and `done_url`.
  - `test_trees_have_no_values`: a text field with value `"secret"`; `"secret"` is not in the lesson file.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(recorder): keep each press's tree and a tree at Done`.

### Task 6: Studio proposes outcomes; the admin ticks them; build writes them

**Files:**
- Modify: `govaios/lessons.py` (`propose` :196, `_cases` :364, `build` :407)
- Modify: `govaios/panel/lesson.py` (`edits` :24, `page` :62)
- Modify: `govaios/audit/web.py:1724-1760` (`lesson_plan` passes outcome choices to `build`)
- Test: `tests/test_lessons.py`, `tests/test_teach.py` (or the panel lesson tests that already post the lesson form)

**Interfaces:**
- Consumes: Task 5's `before`, `done_tree` and `done_url`; Task 3's flow `outcomes` schema; Task 4's
  `outcomes_missing`.
- `propose` adds `line["outcomes"]` (a list, possibly empty) to every `press: True` line. Each proposal is:
  - **count:** `{"kind": "count", "role": str, "label": <prefix, e.g. "Promoted">, "before": int, "after": int,
    "change": after - before, "at": [page index, line index], "page": <page id of the after tree>}`;
  - **item_left:** `{"kind": "item_left", "at": [...], "page": ...}`, only when the press line is inside the page's
    repeatable range (`repeatable`).

  How it is computed:
  - **After trees,** in order: the `before` trees of the events that follow the press, up to and including the next
    press's tree, then `done_tree`. The tree of event e is the "after" of the event just before e. The done tree is the
    "after" of the last event. `at` names that preceding line.
  - **Count:** nodes whose name matches `recorder.COUNT` in both the press's `before` tree and an after tree, same role
    and prefix, number changed. The first after tree showing the change wins per (role, prefix).
  - **item_left:** in the first after tree on the repeat's page, the clicked item's `item_label` identity count dropped.
- `lesson_ui.edits` returns a 4th value `outcomes: {(page, line): [k, ...]}` from form keys `out:<p>:<l>:<k>`, value
  `"1"`. Indices are validated as `del:` keys are.
- The page shows each proposal as an **unchecked** checkbox `out:p:l:k` labelled, for example,
  `Promoted 7 → 8 (+1), checked after: <line label>` or `this round's item left the list, checked after: <line label>`.
  All text is escaped.
- `build(…, outcomes=None)`: for each ticked proposal,
  - **count:** add the page element `f"{slug(label)}_count"` = `{"role": role, "name_matches": f"^{re.escape(label)}
    \\(\\d+\\)$", "risk": "navigate"}` to the after page, then append `{"for": <press id>, "kind": "count", "target":
    f"{page}.{key}", "change": change}` to the `outcomes` of the flow step built from line `at`;
  - **item_left:** append `{"for": <press id>, "kind": "item_left"}`.

  Use `_cases`'s ids to map lines to step ids. If the `at` line or the press is deleted, raise
  `ValueError("the step an outcome is checked after was removed")`. After building, raise
  `ValueError("needs an outcome: " + ", ".join(outcomes_missing(...)))` when presses lack one; the lesson page shows
  that message, as other `ValueError`s are shown. `build` takes `require_outcomes: bool = True`. Try it
  (`try_lesson`) passes `False`: a Try never presses (spec Settled 5).

- [ ] **Step 1: Write the failing tests:**
  - `test_propose_count_and_item_left`: the lesson fixture is JobLens Shortlisted → Review → Approve & promote, as a
    repeat, then Done with `Promoted (8)` and one fewer card. The press line has a count proposal (`label == "Promoted"`,
    `before == 7`, `after == 8`, `change == 1`) and an `item_left` proposal.
  - `test_propose_hr_after_later_click`: Schedule press, then a click on the `Scheduled (3)` tab, then Done shows
    `Scheduled (4)`. The count proposal's `at` is the Scheduled click's line, and there is no `item_left`.
  - `test_spurious_counts_are_proposed_unticked`: an unrelated `Inbox (3)` → `(4)` change is proposed. Building without
    ticking it writes no outcome for it.
  - `test_edits_reads_outcome_ticks`: `{"out:0:2:0": "1"}` → `{(0, 2): [0]}`. `"out:9:9:9"` raises ValueError.
  - `test_build_writes_outcomes_and_element`: ticked count proposal → the flow step carries `outcomes` with `for` =
    the press id, the page file gains `promoted_count` with that `name_matches`, and `engine.check_learned` passes.
  - `test_build_refuses_press_without_outcome`: nothing ticked → ValueError starting with `"needs an outcome"`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** The lesson page's proposal digest (`lesson_ui.digest`) already covers the new keys.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(studio): propose each press's outcome; the admin ticks it; build writes it`.

### Task 7: Proof packet and verifier packet mode

**Files:**
- Create: `govaios/audit/packet.py`
- Modify: `govaios/audit/verify.py` (add `verify_packet`, `--packet` in `main`)
- Test: Create `tests/test_packet.py`

**Interfaces:**
- Produces:
  - `packet.build(entries: list[dict], run_id: str, export_entry: dict, pubkey_pem: str) -> dict`, returning
    `{"format": "govaios-proof-1", "run": run_id, "entries": [...], "context": [...], "export": export_entry,
    "pubkey": pubkey_pem, "note": <str>}`.
    - `entries`: those with `run == run_id` **and** an int `run_seq`, in log order.
    - `context`: the last `flow_approval` with `decision == "allow"`, the last `lesson` with `outcome == "approved"`,
      and the last `press_grant` with `decision == "allow"`, each whose `flow_hash` equals the run's `flow_start`
      `flow_hash`, excluding any already in `entries`.
    - `note`: `"Fingerprints are commitments: anyone who can guess the item's name can confirm it."`
  - `verify.verify_packet(p: dict) -> PacketResult(ok: bool, complete: bool, notes: list[str], problem: str | None)`.
    It checks:
    - each entry's hash (canonical JSON without `hash`/`sig`, as `verify` does) and its signature with `p["pubkey"]`;
    - `run_prev` from 64 zeros, `run_seq` 1…n, a single `run`, `flow_start` first;
    - each context entry's hash and signature, and `flow_hash` == `flow_start`'s;
    - the export entry's hash and signature, and `target == p["run"]`.

    It does **not** check `prev`. `complete` is True iff the last entry is `flow_end` or `stop`. `notes` gets
    `"no outcome check"` if any `outcome` entry is `unchecked`, and `"count changed; item not matched"` if a confirmed
    press has only `count` outcomes.
  - CLI: `verify.py --packet <file>` prints `OK packet complete|incomplete (no end entry)` plus notes, or
    `FAIL: <problem>`.
  - The fingerprint rule is documented in `verify.py`'s docstring.

- [ ] **Step 1: Write the failing tests.** Write real entries with `AuditLog(tmp_path).append(...)`: a run of 4
  entries with run fields, two interleaved `request` entries with `executor="claude_code"`, and a context
  `flow_approval`. Tests:
  - `test_packet_has_only_run_entries_and_context`: no `claude_code` entry in `entries` or `context`.
  - `test_packet_verifies`: `ok`, `complete` and no problem.
  - `test_tampered_entry_fails`: change `count_after` → `problem == "bad hash"`.
  - `test_dropped_entry_fails`: delete the middle entry → `problem` mentions `run_prev`.
  - `test_incomplete_without_end`: drop the last entry → `ok` and `not complete`.
  - `test_notes`: an `unchecked` outcome → `"no outcome check" in notes`.
  - `test_cli`: `verify.main(["--packet", str(path)])` returns 0 and prints `OK packet complete`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Keep `verify.py` stdlib + `cryptography` only.
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(audit): proof packets and verify.py --packet`.

### Task 8: Panel export, and `not_seen` clears the queue

**Files:**
- Modify: `govaios/audit/web.py` (`PANEL_KINDS` :171; `run(seq)` page :714; POST routing; `report()` :360)
- Test: `tests/test_audit_web.py`, `tests/test_panel_queue.py`

**Interfaces:**
- Consumes: `packet.build`, `verify.verify_packet`.
- `packet_export` is added to `PANEL_KINDS`.
- **The run page** (`/audit/run/<seq>`) shows a form, `POST /audit/run/<seq>/packet` with `hidden(csrf)` and the
  button **"Export proof packet"**, only when the run's `flow_start` has a `run` field. The page also lists the run's
  `outcome` entries.
- **The POST handler**, with session and CSRF as other panel POSTs:
  1. compute `chain_count` and `chain_head` from the log's last entry;
  2. `log.append("packet_export", target=<run id>, chain_count=…, chain_head=…)`;
  3. `packet.build(...)` with that returned entry;
  4. respond `200` with `Content-Type: application/json` and
     `Content-Disposition: attachment; filename="govaios-proof-<seq>.json"`.

  GET on that path is 404.
- **`report()`:** when the run's stop reason starts with `"result not seen"`, call
  `clear_queue("a press's result was not seen; check the app before running again.")` (`panel.lock` is an RLock).

- [ ] **Step 1: Write the failing tests:**
  - `test_export_needs_session_and_csrf`: no cookie → redirect or 403; a bad CSRF → 403; GET → 404.
  - `test_export_returns_packet_and_audits`: the body parses, `verify_packet` is ok, and the log's last entry before
    the response is `packet_export` with `target` equal to the run id.
  - `test_run_page_shows_export_only_for_panel_runs`: a CLI run (no `run` field) has no button.
  - `test_not_seen_clears_queue` (in `test_panel_queue.py`'s style): a queued app plus a finished run whose
    `stopped_reason` is `"result not seen: Approve & promote was pressed, its result did not appear"` → after
    `report()` the queue is empty and a `run_queue` entry with `outcome == "cleared"` is logged.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the whole suite.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(panel): export a run's proof packet; a result not seen clears the queue`.

### Task 9: Docs and the paper

**Files:**
- Modify: `docs/paper/gov-aios-paper-v1.md` (new §4.9 after §4.8; rows in §10's table; one line in §9)
- Modify: `docs/backlog.md` (the "Outcome check per step" entry: mark built, list the cuts from the spec's
  Non-goals as open items)

- [ ] **Step 1: Write §4.9 "Outcome-checked steps and proof packets"**, about 250 words, in the paper's style:
  - **The requirement:** enterprises need proof of results, not only of actions.
  - **The mechanism:** the outcome is taught and confirmed by the admin, checked after each data-changing press by
    polling, and recorded as a signed `outcome` entry.
  - **The proof packet:** a per-run chain (`run_prev`), plus context entries for who approved, checked standalone.
  - **The fingerprint:** a commitment, not hiding.
  - **Failure handling:** a result not seen ends the run and clears the queue.
- [ ] **Step 2: Add the four Limitations rows** from the spec verbatim, and the §9 line contrasting WebArena's
  end-of-task evaluators and Playwright's `expect` with per-step signed checks.
- [ ] **Step 3: Update the backlog entry.**
- [ ] **Step 4: Commit** `docs: outcome checks in the paper and backlog`.
