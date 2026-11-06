# Delivery and the first app (JobLens) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bin/gov-aios run flows/himalayas_job_vetting.yaml` collects today's Himalayas matches (as today, no network) and then, in a second sandboxed launch, sends each saved job once to JobLens.

**Architecture:** A new `govaios/delivery.py` holds the target table, the flow's `deliver:` block check, payload building, the HTTP sender, the once-only tracking file and the batch loop. A new `gov-aios deliver <flow>` subcommand runs it under a new `DELIVER_PROFILE` sandbox (TCP to `localhost:8100` only). The run process writes `deliver` to a shim file after `flow_end`; the shim then launches the app a second time.

**Tech Stack:** Python 3 standard library (`urllib.request`, `http.server` in tests), PyYAML, pytest, bash shim.

**Spec:** `docs/superpowers/specs/2026-11-06-joblens-delivery-design.md`

## Global Constraints

- No new dependency; HTTP with `urllib.request` only.
- `DELIVER_PROFILE = _BASE + ' (allow network-outbound (remote ip "localhost:8100"))' + " " + _DNS_FIX` (verbatim, in `govaios/sandbox.py`); `sandbox.apply` stays the first call in `main()` (ruling 19).
- The `run` subcommand keeps `RUN_PROFILE` and `block_all_network()`; nothing in `run` gains network.
- Target table lives in code only: `TARGETS = {"joblens": {"url": "http://127.0.0.1:8100/api/discover/listings", "label": "joblens (local)"}}`. No flow field may hold an address, port or URL.
- Flows without `deliver:` (the morning brief) behave exactly as today; morning digest stays `a1dca44ed9e272377fe86987aca8bece3a1dcd7c4ef797e6ed40d4e8386ff4ae`.
- Audit entries never contain title, company, description or URL of a job.
- Never print job content to stdout/stderr (summary counts only).
- The browser key `application:` keeps its name.
- All 364 existing tests keep passing (update only the ones this plan names).

## Review Focus

1. JobLens down (Docker stopped): connection refused → `retry`, message `JobLens not reachable at 127.0.0.1:8100 (is it running?)`, exit 1; the run itself still exited 0 before delivery. Test in Task 2.
2. Emergency stop during delivery: SIGTERM raises `Stop`; no further request; the file in flight is not recorded (stays pending; a resend gets a 200 duplicate). Test in Task 2.
3. A corrupt or hand-edited job file: `failed` with reason `bad_json`, the batch continues. Test in Task 2.
4. A description of exactly 50,000 characters is sent intact; 50,001 is `failed` locally. Test in Task 1.
5. A symlink or non-regular file in `jd_selected/` is ignored, never followed. Test in Task 2.

---

### Task 1: delivery core — block check, payload, tracking, audit vocabulary

**Files:**
- Create: `govaios/delivery.py`
- Modify: `govaios/audit/log.py` (`KINDS`, `FIELDS`)
- Test: `tests/test_delivery.py`

**Interfaces:**
- Produces:
  - `TARGETS: dict[str, dict]` (value in Global Constraints)
  - `check_block(flow: dict) -> dict | None` — `None` when the flow has no `deliver` key; raises `ValueError(<field name>)` when the block is bad.
  - `build_payload(rec: dict, source: str) -> tuple[dict | None, str | None, str | None]` — `(payload, None, None)` to send, or `(None, outcome, reason)` with outcome `"failed"` / `"skipped_too_short"`.
  - `class Deliveries(path: Path)`: `done(file_hash: str) -> bool`, `record(file_hash: str, outcome: str, listing_id: int | None) -> None`.
  - Audit: kind `"delivery"`; fields `"file_hash"`, `"response_code"`, `"listing_id"` added to `FIELDS`.

`check_block` rules (each failure raises `ValueError` with the key name):
- `deliver` must be a dict with exactly the keys `to`, `from`, `source`.
- `to` in `TARGETS`.
- `from` equals the `directory` of some `write_json` step in `flow["steps"]` (walk nested `steps`).
- `source` a str, 1–50 chars after strip, no character with `ord < 32` or `== 127`.
- `"deliver"` in `flow["permissions"]["allow"]` (else `ValueError("permissions.allow")`).

`build_payload` rules (applied after trimming; reasons are field names, never content):
- `title` ← `rec["job_title"]`: replace control chars (`ord < 32` or `127`) with a space, collapse whitespace runs to one space, strip. Empty or no letter/digit → `failed`/`"title"`; > 500 → `failed`/`"title"`.
- `company` ← same cleanup; empty → left out; > 500 → `failed`/`"company"`.
- `jd_text` ← `rec["description"]`: `\r\n`/`\r` → `\n`, remove control chars other than `\n` and `\t`, strip. < 300 → `skipped_too_short`/`"jd_text"`; > 50,000 → `failed`/`"jd_text"`.
- `url` ← strip; kept only if scheme is `http`/`https` and it has no whitespace or control chars; > 2000 → `failed`/`"url"`; otherwise dropped.
- `source` ← the argument.
- A non-str, non-None value for any of these → `failed`/`<that field>`.
- The payload has only the keys `title`, `source`, and those of `company`, `jd_text`, `url` that are present.

`Deliveries`: JSON file `{file_hash: {"outcome": str, "listing_id": int|None}}`; `done` is true for every outcome except `"retry"`; `record` is read-modify-write under `fcntl.flock` on `deliveries.lock` beside it, atomic via `tempfile.mkstemp` + `os.replace` (same pattern as `Approvals._update`).

- [ ] **Step 1: Write the failing tests** in `tests/test_delivery.py`:
  - `test_check_block_none_without_deliver` — the morning-brief-shaped flow → `None`.
  - `test_check_block_accepts_himalayas_shape` — `{to: joblens, from: jd_selected, source: Himalayas}` with a `write_json` step `directory: jd_selected` nested in `for_each_item` → returns the block.
  - `test_check_block_refuses` (parametrized): `to: other` → `"to"`; extra key `url:` → `"deliver"`; `from: elsewhere` → `"from"`; `source: ""` / `"x"*51` / `"a\nb"` → `"source"`; `deliver` missing from allow → `"permissions.allow"`.
  - `test_payload_maps_fields` — exact dict equality: `{"title": "Senior Dev", "company": "Acme", "jd_text": <desc>, "url": "https://himalayas.app/x", "source": "Himalayas"}` from `job_title: "  Senior\n  Dev "`.
  - `test_payload_jd_limits` — 299 chars → `(None, "skipped_too_short", "jd_text")`; 300 → sent; 50,000 → sent with `len == 50000`; 50,001 → `(None, "failed", "jd_text")`.
  - `test_payload_title_without_letters_fails` — `"--- !!"` → `failed`/`title`.
  - `test_payload_drops_bad_url` — `"javascript:x"` and `None` → no `url` key.
  - `test_payload_empty_company_left_out`.
  - `test_deliveries_once` — `record(h, "delivered", 5)` → `done(h)`; `record(h2, "retry", None)` → not `done(h2)`; new instance on the same path sees both.
  - `test_audit_accepts_delivery_entry` — `AuditLog(home).append("delivery", flow="f", target="joblens", file_hash="ab"*32, response_code=202, listing_id=1, outcome="delivered")` succeeds.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_delivery.py -q` → FAIL (module missing).
- [ ] **Step 3:** Implement the interfaces above in `govaios/delivery.py`; add the kind and fields to `govaios/audit/log.py`.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5:** Commit `feat(delivery): deliver block check, JobLens payload, once-only tracking`.

### Task 2: sender and batch

**Files:**
- Modify: `govaios/delivery.py`
- Test: `tests/test_delivery.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `send(url: str, payload: dict, timeout: float = 20) -> tuple[int | None, dict | None]` — POST JSON (`Content-Type: application/json`); `HTTPError` → its code and parsed body (or `None`); connection errors and timeouts → `(None, None)`.
  - `classify(code: int | None, body: dict | None) -> tuple[str, int | None, str | None]` → `(outcome, listing_id, reason)`:
    `202` → `delivered`, `body["id"]`; `200` → `duplicate`, `body["id"]`; `400` → `failed`, the text before `":"` in `body["error"]["message"]` if it matches `[a-z_]{1,30}`, else `"bad_request"`; `409` → `retry`/`"conflict"`; `429` → `retry`/`"intake_cap"`; `None` → `retry`/`"unreachable"`; `>= 500` → `retry`/`"server_error"`; any other → `failed`/`"http_<code>"`. `listing_id` only if it is an `int`, else `None`.
  - `deliver_batch(home: Path, flow: dict, block: dict, audit, post=send) -> dict[str, int]` — counts with keys `delivered, duplicate, retry, failed, skipped`, plus `left` (files not attempted after a stop of the batch).

`deliver_batch` behaviour:
- Directory `home / block["from"]`; candidates are names ending `.json`, opened with `os.open(..., O_RDONLY | O_NOFOLLOW)` and kept only if `fstat` says regular; read at most 1,000,000 bytes (more → `failed`/`"size"`). Symlinks and non-regular entries are skipped, never read.
- `file_hash` = SHA-256 hex of the bytes; skip if `Deliveries(home / "deliveries.json").done(hash)`.
- Parse JSON: not a dict → `failed`/`"bad_json"`; `rec.get("flow") != flow["id"]` → skipped silently (not counted, not recorded).
- Order: `(str(rec.get("captured_at") or ""), name)` ascending.
- Before each file: `runstate.stopped(home)` → `raise Stop("emergency stop")`.
- Local outcome (`build_payload` → failed/skipped): record, audit with `response_code=None`, no request.
- Otherwise `classify(*post(TARGETS[block["to"]]["url"], payload))`; record, then audit; on `retry` stop the loop, `left` = remaining files.
- Audit per file: `audit.append("delivery", flow=..., target=block["to"], file_hash=..., response_code=..., listing_id=..., outcome=..., reason=...)`.
- `skipped_too_short` counts as `skipped`.

- [ ] **Step 1: Write the failing tests** (fake JobLens: `http.server.ThreadingHTTPServer` on `("127.0.0.1", 0)` in a thread, answering from a scripted list of `(code, body)` and recording request bodies; point `TARGETS["joblens"]["url"]` at it with `monkeypatch.setitem`):
  - `test_classify_table` — every row above, including 400 `"title: too long"` → `("failed", None, "title")` and 400 `"<b>x</b>: y"` → reason `"bad_request"`.
  - `test_batch_sends_once` — 2 files, answers `[202 {"id": 1}, 200 {"id": 2, "duplicate": true}]` → counts `delivered 1, duplicate 1`; second call sends 0 requests.
  - `test_batch_changed_file_sent_again` — edit a delivered file's bytes → one new request.
  - `test_409_stops_batch_rest_pending` — 3 files, answers `[202, 409]` → 2 requests, `retry 1, left 1`; next call with `[202, 202]` sends the 2 pending.
  - `test_unreachable_is_retry` — URL to a closed port → `retry 1`, nothing recorded as done.
  - `test_order_oldest_captured_first`.
  - `test_other_flow_files_ignored`, `test_corrupt_json_failed_and_batch_continues`, `test_symlink_not_followed` (symlink to a valid job file outside the directory → 0 requests).
  - `test_stop_flag_stops_before_next_file` — `STOPPED` created by the fake server after the first answer → `Stop` raised, 1 request, second file not recorded.
  - `test_audit_has_no_content` — job file with title/company/description/url containing `ZQXMARKER`; after a batch `"ZQXMARKER" not in audit.jsonl text`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement `send`, `classify`, `deliver_batch`.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5:** Commit `feat(delivery): JobLens sender and once-only batch`.

### Task 3: engine — deliver block at load, approval text, unique job filenames

**Files:**
- Modify: `govaios/engine.py` (`Runner.__init__`, `approve_flow`, `do_write_json`)
- Test: `tests/test_engine_audit.py`

**Interfaces:**
- Consumes: `delivery.check_block`, `delivery.TARGETS`.
- Produces: `Runner.deliver: dict | None` (the checked block), used by Task 4.

Changes:
- `__init__`: `self.deliver = check_block(self.flow)`; `ValueError` → `raise Stop(f"bad deliver block: {e}")`.
- `approve_flow` question: when `self.deliver`, insert `; delivers to: {TARGETS[to]['label']}` after the destinations list (before `. Approve this flow?`).
- `do_write_json` filename: `f"{datetime.now():%Y%m%d}-{slug}-{hashlib.sha256((rec.get('url') or '').encode()).hexdigest()[:8]}.json"`.

- [ ] **Step 1: Write the failing tests:**
  - `test_write_json_name_has_url_hash` — written name matches `r"\d{8}-[a-z0-9-]+-[0-9a-f]{8}\.json"`, and two jobs with the same title but different URLs give two files.
  - `test_bad_deliver_block_stops_at_load` — flow fixture with `deliver: {to: other, ...}` → `Stop` from `Runner(...)` with message starting `bad deliver block`.
  - `test_approval_dialog_names_delivery` — flow with a valid block: the captured approval question contains `delivers to: joblens (local)`; a flow without one does not contain `delivers`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5:** Commit `feat(engine): deliver block checked at load; unique job filenames`.

### Task 4: `deliver` subcommand, sandbox profile, run → next-file

**Files:**
- Modify: `govaios/sandbox.py` (add `DELIVER_PROFILE`), `govaios/cli.py`, `govaios/delivery.py`, `govaios/audit/web.py` (`_runs` anomaly rule)
- Test: `tests/test_cli.py`, `tests/test_sandbox.py`, `tests/test_delivery.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `PROFILES["deliver"] = sandbox.DELIVER_PROFILE`.
  - `delivery.last_run_finished(home: Path, flow_id: str) -> bool` — scan `audit.jsonl` lines (skip unparsable); for entries with `flow == flow_id`: `flow_start` → open, `flow_end` → done, `stop` → stopped; true only if the final state is done.
  - `delivery.run_delivery(flow_path: Path, home: Path, audit) -> int` — the checks of spec §4.3 then `deliver_batch`; prints the summary; returns the exit code.
  - `cli._deliver(args)` and parser `deliver <flow> [--dev]`.
  - `_run` writes `deliver` to `GOVAIOS_NEXT_FILE` via `_write_shim_file` only after `Runner.run()` returned and `runner.deliver` is set.

`run_delivery` order (each refusal `raise Stop(<text>)`):
1. `read_bound(flow_path, flow_path.parent.parent / "pages")`; parse `["workflow"]`; `check_block` (None → `"flow has no deliver block"`; `ValueError` → `"bad deliver block: <e>"`).
2. `Approvals(home / "approvals.json").flow_ok(id, digest)` else `"flow not approved for its current file"`.
3. `[p for p in live_runs(home) if p != os.getpid()]` non-empty → `"another gov-aios run is live"`.
4. `last_run_finished` false → `"last run did not finish"`.
5. First contact: `destination_ok(id, block["to"])` false → `auth.approve(f"Flow '{id}' wants to deliver its saved jobs to JobLens (local, 127.0.0.1:8100) for the first time. Approve?", f"{id}: deliver to {block['to']}", home)`; audit `request`, `action="deliver"`, `destination=block["to"]`, decision, `approver="admin"`, `channel="touch_id"`, `auth=how`; not ok → print `not approved; nothing sent` (or `approval busy`) to stderr, return 1; ok → `approve_destination(id, block["to"])`.
6. SIGTERM handler raising `Stop("emergency stop")` around `deliver_batch` (restore the previous handler after).
7. Print `deliver joblens: delivered N, duplicate N, retry N, failed N, skipped N`; when any `retry` had reason `unreachable`, also print `JobLens not reachable at 127.0.0.1:8100 (is it running?)` to stderr; when `left > 0` print `N files left for the next delivery`. Return 1 if `retry` or `failed` > 0, else 0.

`_deliver(args)`: like `_run` — `identity.require_app(args.dev)`, `register_run` before `preflight(home, dev=not packaged)`, `unregister_run` in `finally`, `Stop` → `STOPPED: <msg>` on stderr and 1, other exceptions → `ERROR: <TypeName>` and 1. It does **not** call `block_all_network()`.

`audit/web.py` `_runs`: an `action == "deliver"` request outside a run is normal (not an anomaly).

- [ ] **Step 1: Write the failing tests:**
  - `tests/test_sandbox.py::test_deliver_profile_allows_only_8100` — child process applies `DELIVER_PROFILE`; classify connects by errno as the spike does (connected/`ECONNREFUSED` = allowed, `EPERM`/`EACCES` = denied): `127.0.0.1:8100` allowed; a listening server on a free port denied; `127.0.0.1:8000` denied; `1.1.1.1:443` denied; DNS blocked (reuse `_DNS`); socketpair works.
  - `tests/test_cli.py`: add `"deliver"` to `SUBCOMMANDS`, `ARGV["deliver"] = ["deliver", "x.yaml"]`, and the expected profile map gets `"deliver": "DELIVER_PROFILE"`.
  - `test_run_writes_next_file_only_for_deliver_flows` — fake `Runner` with `deliver` set / `None`, empty `GOVAIOS_NEXT_FILE` → contains `deliver` / stays empty; a `Stop` from `run()` leaves it empty.
  - `test_deliver_is_a_registered_run_and_preflighted` — STOPPED in the home → exit 1, `STOPPED`-style refusal on stderr, runs dir empty after.
  - `tests/test_delivery.py`: `test_last_run_finished` (start+end → True; start+stop → False; start only → False; other flow's end does not count; latest run wins), `test_run_delivery_refusals` (parametrized: flow not approved, no block, last run stopped, other live run via monkeypatched `live_runs`), `test_first_contact_asks_once` (fake `auth.approve` True → asked once, second call not asked; False → exit 1, 0 requests), `test_summary_and_exit_code` (skipped-only → 0; one failed → 1).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5:** Commit `feat(cli): deliver subcommand under DELIVER_PROFILE; run signals delivery`.

### Task 5: shim — second launch

**Files:**
- Modify: `bin/gov-aios`
- Test: `tests/test_shim.py` (new)

**Interfaces:**
- Consumes: `GOVAIOS_NEXT_FILE` written by Task 4.

Changes:
- `APP=${GOVAIOS_APP:-/Applications/gov-aios.app}` (test hook; comment says so).
- `nextf=$(mktemp)` with the other temp files, removed by `cleanup`.
- Move the launch + stream + read-exit block into a function `launch <args...>` that resets offsets and truncates `$out $err $exitf $pidf` before starting; pass `--env GOVAIOS_NEXT_FILE="$nextf"` only on the first launch.
- After the first launch: if its code is 0, the first argument was `run`, and `$(cat "$nextf")` is exactly `deliver`, call `launch deliver <the same absolute flow path>`; the shim's exit code is the second launch's. Otherwise exit with the first code.

- [ ] **Step 1: Write the failing tests** — a fake `open` (bash script on `PATH` in `tmp_path`) that parses `--stdout/--stderr/--env K=V/--args`, appends its `--args` line to `$CALLS`, writes `$FAKE_CODE` to the exit file, prints `out-<subcommand>` to the stdout file, and for `run` writes `deliver` to `GOVAIOS_NEXT_FILE` when `FAKE_NEXT=1`. `GOVAIOS_APP` points at an empty dir in `tmp_path`.
  - `test_shim_launches_once_without_next` — `FAKE_NEXT=0` → one call, exit 0.
  - `test_shim_launches_deliver_after_run` — `FAKE_NEXT=1` → calls `run <abs>` then `deliver <abs>`; stdout has both `out-run` and `out-deliver`.
  - `test_shim_no_deliver_after_failed_run` — `FAKE_NEXT=1, FAKE_CODE=1` → one call, exit 1.
  - `test_shim_next_ignored_for_other_subcommands` — `doctor` with `FAKE_NEXT=1` → one call.
- [ ] **Step 2:** `.venv/bin/python -m pytest tests/test_shim.py -q` → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5:** Commit `feat(shim): launch deliver after a run that asks for it`.

### Task 6: the JobLens app — Himalayas flow

**Files:**
- Modify: `flows/himalayas_job_vetting.yaml`
- Test: `tests/test_delivery.py`

Changes (only inside `workflow:`): `name: "Himalayas Job Vetting → JobLens"`, `version: 2`, `deliver` appended to `permissions.allow`, and after `destinations:` the line `deliver: { to: joblens, from: jd_selected, source: Himalayas }`. `steps:` unchanged.

- [ ] **Step 1: Write the failing tests:**
  - `test_real_flows_load` — `Runner(<repo>/flows/<f>, None, tmp_home)` for both flows; Himalayas `runner.deliver == {"to": "joblens", "from": "jd_selected", "source": "Himalayas"}`; morning `runner.deliver is None`.
  - `test_morning_digest_unchanged` — `flow_hash("flows/morning_inbox_briefing.yaml", "pages") == "a1dca44ed9e272377fe86987aca8bece3a1dcd7c4ef797e6ed40d4e8386ff4ae"`.
- [ ] **Step 2:** run → FAIL (no deliver block yet).
- [ ] **Step 3:** edit the flow.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5:** Commit `feat(flows): Himalayas flow delivers to JobLens`.

### Task 7: live test (admin)

No code. The controller rebuilds and hands the admin these steps; results go in the ledger.

- [ ] **Step 1 (controller):** `GOVAIOS_SIGN_ID="GOV-AIOS Dev" packaging/build.sh`, then `codesign --verify --strict -R='identifier "com.govaios.cli" and certificate leaf[subject.CN] = "GOV-AIOS Dev"' dist/gov-aios.app` → valid.
- [ ] **Step 2 (admin):** `sudo packaging/install.sh`; `bin/gov-aios doctor` → all checks true.
- [ ] **Step 3 (admin):** JobLens running (`127.0.0.1:8100`). `bin/gov-aios run flows/himalayas_job_vetting.yaml` → flow approval dialog showing `delivers to: joblens (local)` + Touch ID; 5 jobs collected; then the JobLens first-contact dialog + Touch ID; summary line with `delivered` ≥ 1, exit 0. Jobs appear in JobLens.
- [ ] **Step 4 (admin):** run it again → one Touch ID only; summary shows the repeat jobs as `duplicate` (or not resent).
- [ ] **Step 5 (admin):** stop JobLens's container, `bin/gov-aios deliver flows/himalayas_job_vetting.yaml` → `JobLens not reachable ...`, exit 1; start it again, rerun → pending files sent.
- [ ] **Step 6 (admin):** `bin/gov-aios audit-ui` → `delivery` entries with codes, no job text; `bin/gov-aios verify-audit` → OK. The morning brief flow is not run (unchanged).
