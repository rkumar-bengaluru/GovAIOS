# Governance Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `spikes/ax-flows` runner into the `gov-aios` package and
signed app (`com.govaios.cli`) that alone holds the macOS permissions,
with a policy engine, a signed tamper-evident audit trail, a standalone
verifier, a read-only local audit web UI, and no network during runs.

**Architecture:** One Python package, `govaios/`, frozen by PyInstaller
into `gov-aios.app`. macOS starts the app (never Terminal), so the app's
signed identity holds Accessibility and Screen Recording. A shell shim,
`bin/gov-aios`, starts the app with `open -W` and forwards its stdout and
stderr to the caller's terminal. Every governed event is appended to a
hash-chained JSONL log signed with ECDSA P-256, the curve the Secure
Enclave supports, so the later hardware key is a drop-in swap.

**Tech Stack:** Python 3.14, pyobjc (ApplicationServices, Quartz, Cocoa),
PyYAML, `cryptography`, pytest, PyInstaller (dev dependency), the stdlib
`http.server` for the UI, and macOS `codesign`.

**Spec:** `docs/superpowers/specs/2026-11-05-governance-layer-design.md`
(this plan covers build-order step 1 of §7.3 plus §9.1 day 1 and the
run-stage network rule of §9.2). Later plans: (2) admin authentication
and isolation, (3) terms gate and challenge handling, (4) bootstrap,
observation, `redact_for_cloud()`, drafting, and simulation and live
rehearsal. Revoking approvals from the web UI (spec 5.9) needs admin
authentication, so it moves to plan 2; this plan's UI is read-only.

## Global Constraints

- Binary name `gov-aios`; bundle identifier `com.govaios.cli` (spec 9.1).
- Permissions must belong to `com.govaios.cli`, not Terminal: the app is always started by macOS (`open`), never as a child of a terminal (spec 9.1, builder note).
- Signing identity: `GOVAIOS_SIGN_ID` environment variable, default `-` (ad-hoc, spec 9.1 day 1). A stable self-signed certificate is recommended for dev builds, because an ad-hoc signature changes on every rebuild (spec 9.1, builder note).
- Python in a terminal is dev-only: it requires `--dev` and is never shipped (spec 9.1).
- Data home: `$GOVAIOS_HOME`, default `~/Library/Application Support/GOV-AIOS/`. Holds `audit.jsonl`, `audit_key.pem`, `audit_pubkey.pem`, `approvals.json`.
- The audit never contains content: elements are recorded by page and schema element id, URLs by origin and path only (no query or fragment) (spec 7.4, 5.7).
- During `run`, all network from the GOV-AIOS process is blocked (spec 9.2.5). Unix sockets and the operated app's own traffic are unaffected.
- Approval binds to the flow file plus only the page schemas it uses (spec 7.6).
- Nothing is ever written inside the app bundle, which the signature seals: every output, including `write_json` directories, goes under the data home.
- Silence, timeout, or anything but an explicit approve means deny (spec 5.3).
- No website APIs (spec 9.3).
- Tests never touch the real data home: `tests/conftest.py` sets `GOVAIOS_HOME` to a fresh `tmp_path` for every test (autouse). This home holds no credentials, keys or approvals from the real one, so even if a guard is bypassed, nothing real can leak.
- PyInstaller must use `--onedir` inside the `.app` (`EXE` + `COLLECT` + `BUNDLE`), never `--onefile`, so `sys._MEIPASS` is the stable `Contents/Frameworks` directory. `hiddenimports=['objc', 'AppKit', 'Foundation', 'ApplicationServices', 'Quartz', 'yaml', 'cryptography']`.

## Review Focus

- A crash mid-write leaves a partial last line in `audit.jsonl`. The verifier must report "truncated tail at line N", distinct from tampering, and appending must refuse until the admin resolves it (Task 3 and Task 4 tests).
- `audit_key.pem` is missing while `audit.jsonl` exists. Never silently create a new key, which would fork the chain; refuse to append (Task 3 test).
- Two `gov-aios` processes append at once: `seq` and `prev_hash` must stay consistent, so appends take an exclusive file lock (Task 3 test).
- The web UI gets a request with no token or a wrong token, a path outside its routes, or a POST. Respond 403, 404 and 405, and never modify or delete anything (Task 7 test).
- A flow references a page id that has no schema. Fail at load with that id named, before hashing or approval (Task 2 test).

---

## File Structure

```
pyproject.toml                    deps, pytest config, console entry
govaios/__init__.py
govaios/home.py                   data-home path resolution
govaios/roles.yaml                (moved from spike)
govaios/desktop/__init__.py       (moved) Node, ROLES, get_desktop
govaios/desktop/macos.py          (moved) macOS adapter
govaios/policy.py                 (from spike governance.py) RISK_ORDER, origin, decide
govaios/approvals.py              (from spike governance.py) Approvals, pages_used, flow_hash
govaios/engine.py                 (moved) Runner, Stop, locator, now audits every event
govaios/audit/__init__.py
govaios/audit/log.py              AuditLog: signed hash chain, redaction helpers
govaios/audit/verify.py           standalone verifier (stdlib + cryptography only)
govaios/audit/web.py              read-only localhost UI
govaios/netguard.py               block_all_network()
govaios/identity.py               bundle and permission checks
govaios/cli.py                    gov-aios run | verify-audit | audit-ui | doctor
flows/, pages/                    (moved from spike)
packaging/gov-aios.spec           PyInstaller spec
packaging/build.sh                build + codesign
bin/gov-aios                      shim: open -W the app, forward stdio
tests/                            pytest
spikes/ax-flows/README.md         kept; points to govaios/
```

---

### Task 1: Package skeleton from the spike

**Files:**
- Create: `pyproject.toml`, `govaios/__init__.py`, `govaios/home.py`, `tests/conftest.py` (the autouse `GOVAIOS_HOME` fixture from Global Constraints), `tests/test_policy.py`, `.gitignore` (root; same ignores as the spike plus `build/`, `dist/`, `.venv/`)
- Move (`git mv`): `spikes/ax-flows/{roles.yaml,desktop/,engine.py,flows/,pages/}` → `govaios/roles.yaml`, `govaios/desktop/`, `govaios/engine.py`, `flows/`, `pages/`
- Split: `spikes/ax-flows/governance.py` → `govaios/policy.py` (`RISK_ORDER`, `origin`, `decide`) and `govaios/approvals.py` (`Approvals`, `flow_hash`)
- Delete: `spikes/ax-flows/{run.py,dump.py,test_governance.py,.gitignore}` (dump becomes `gov-aios dump` in Task 8)
- Modify: `spikes/ax-flows/README.md` (prepend one line: "Code moved to `govaios/`; this file keeps the spike's findings.")

**Interfaces:**
- Produces: `govaios.home.data_home() -> pathlib.Path` (returns `$GOVAIOS_HOME`, or `~/Library/Application Support/GOV-AIOS`; creates it with mode 0700). `govaios.policy.decide(request: dict, flow: dict, approvals) -> str` and `origin(url: str) -> str`, unchanged from the spike. `govaios.engine` imports become package-relative, and `HERE`-based paths become `REPO = Path(__file__).parent.parent` for `pages/`.

- [ ] **Step 1:** Write `tests/test_policy.py` by converting each assert in the spike's `test_governance.py` into its own pytest test, keeping the same names in behaviour: `test_unlisted_action_denied`, `test_submit_click_denied`, `test_navigate_click_allowed`, `test_write_file_not_subject_to_click_ceiling`, `test_first_contact_asks`, `test_destination_remembered`, `test_undeclared_destination_denied`, `test_lookalike_domain_denied`, `test_payment_always_asks`. Use pytest's `tmp_path` for the approvals file.
- [ ] **Step 2:** Run `python -m pytest tests/test_policy.py -v`. Expected: FAIL (`ModuleNotFoundError: govaios`).
- [ ] **Step 3:** Do the moves and the split, and write `pyproject.toml`:
  - `requires-python = ">=3.14"`;
  - dependencies `pyobjc-framework-ApplicationServices`, `pyobjc-framework-Quartz`, `pyobjc-framework-Cocoa`, `pyyaml`, `cryptography`;
  - optional `dev = ["pytest", "pyinstaller"]`;
  - `[project.scripts] gov-aios-dev = "govaios.cli:main"`.

  Then fix the imports.
- [ ] **Step 4:** Run `python -m venv .venv && .venv/bin/pip install -e '.[dev]' && .venv/bin/python -m pytest -v`. Expected: 9 passed.
- [ ] **Step 5:** Commit: `git commit -m "Move spike into govaios package"`.

### Task 1b: Early packaging smoke test

Packaging pyobjc with PyInstaller is brittle, so the app identity is proven
before anything else depends on it.

**Files:**
- Create: `govaios/identity.py`, `govaios/cli.py` (the `doctor` subcommand only), `packaging/gov-aios.spec`, `packaging/build.sh`, `bin/gov-aios`
- Test: `tests/test_identity.py`

**Interfaces:**
- Consumes: `govaios.home.data_home()` (Task 1).
- Produces:
  - `identity.check() -> dict` with keys `bundle_id` (`NSBundle.mainBundle().bundleIdentifier()` or `None`), `frozen` (`getattr(sys, "frozen", False)`), `accessibility` (`AXIsProcessTrusted()`), and `screen_recording` (`Quartz.CGPreflightScreenCaptureAccess()`).
  - `cli.main(argv: list[str] | None = None) -> int`, with `doctor` printing one `key: value` line per check field and returning 1 if any is false.
  - At exit, `cli.main` writes its return code to the path in env `GOVAIOS_EXIT_FILE` if that is set.
  - `dist/gov-aios.app`:
    - `CFBundleIdentifier = com.govaios.cli`, executable `gov-aios`, `LSUIElement = true`, and `NSAppleEventsUsageDescription` (for the approval dialogs via `osascript`);
    - built `--onedir` with the Global Constraints' `hiddenimports`, and datas `govaios/roles.yaml`, `flows/` and `pages/`;
    - signed with `codesign --force --deep --options runtime --sign "${GOVAIOS_SIGN_ID:--}" --identifier com.govaios.cli`.
  - `bin/gov-aios <args>` (bash, `set -euo pipefail`) works the same from Terminal, VS Code, scripts, and with no TTY:
    1. Create per-invocation temp files with `mktemp`: `out`, `err`, `exitf`. They are removed by a `trap` on EXIT, so concurrent invocations never share a file.
    2. Convert arguments that name existing files to absolute paths, because `open` starts the app with working directory `/`.
    3. Run `open -W -n -a "$REPO/dist/gov-aios.app" --stdout "$out" --stderr "$err" --env GOVAIOS_EXIT_FILE="$exitf" --env GOVAIOS_HOME="${GOVAIOS_HOME:-}" --args "$@"` in the background.
    4. Stream `out` and `err` with `tail -f` to the caller's stdout and stderr until `open` returns.
    5. Exit with the code in `exitf`, or 70 if it is empty.
  - In the frozen app, `REPO` in `engine.py` resolves to `Path(sys._MEIPASS)`, where the datas place `pages/` and `flows/`.

- [ ] **Step 1: Write the failing tests:**
  - `test_check_keys`: `set(identity.check()) == {"bundle_id", "frozen", "accessibility", "screen_recording"}`.
  - `test_not_frozen_under_pytest`: `identity.check()["frozen"] is False`.
  - `test_exit_file_written`: with `GOVAIOS_EXIT_FILE=tmp_path/'x'` and `identity.check` monkeypatched to all true, `main(["doctor"])` returns 0 and the file contains `0`.
- [ ] **Step 2:** Run `pytest tests/test_identity.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `identity.check`, the `doctor` subcommand, the spec, `build.sh` (`pyinstaller --clean --noconfirm packaging/gov-aios.spec`, then `codesign`, then `codesign --verify --strict --verbose=2 dist/gov-aios.app`), and the shim, then `chmod +x bin/gov-aios`.
- [ ] **Step 4:** Run `pytest tests/test_identity.py -v`. Expected: 3 passed.
- [ ] **Step 5:** Run `packaging/build.sh && codesign -dv dist/gov-aios.app 2>&1 | grep Identifier`. Expected: `Identifier=com.govaios.cli`.
- [ ] **Step 6:** Run `bin/gov-aios doctor; echo "exit=$?"`, then `bin/gov-aios doctor < /dev/null | cat; echo "exit=$?"` (no TTY). Expected both times: `bundle_id: com.govaios.cli`, `frozen: True`. `accessibility` may be False before the admin grants it, in which case the exit is 1. No `ModuleNotFoundError` from objc, AppKit or Quartz.
- [ ] **Step 7:** Run two shims at once: `bin/gov-aios doctor > /tmp/a & bin/gov-aios doctor > /tmp/b; wait`. Expected: both files have the full `doctor` output and neither has the other's lines.
- [ ] **Step 8:** Commit: `git commit -m "Prove gov-aios.app identity with early packaging smoke test"`.

### Task 2: Approval binds to the pages a flow uses

**Files:**
- Modify: `govaios/approvals.py`, `govaios/engine.py` (`Runner.approve_flow`, `Runner.__init__`)
- Test: `tests/test_approvals.py`

**Interfaces:**
- Produces:
  - `pages_used(flow: dict) -> set[str]`: every page id referenced anywhere in the steps, recursing into nested `steps`. It covers `target` (the part before the dot, skipping `current_item`), `page`, `verify_page`, and the keys of `on_match` (skipping `unknown`).
  - `flow_hash(flow_path: Path, pages_dir: Path) -> str`: the SHA-256 of the flow file bytes followed by the bytes of `pages_dir/<id>.yaml` for each id in sorted `pages_used`. It raises `KeyError(<page id>)` if a page file is missing.
  - `Runner` only loads the pages it uses, and raises `Stop("unknown page: <id>")` at construction.

- [ ] **Step 1: Write the failing tests:**
  - `test_pages_used_himalayas`: loading `flows/himalayas_job_vetting.yaml` gives `{"google_home", "himalayas_matches", "himalayas_logged_out", "himalayas_job_detail"}`.
  - `test_unrelated_page_edit_keeps_hash`: copy `flows/` and `pages/` into `tmp_path`, hash the Himalayas flow, append a comment to `gmail_inbox.yaml`, and the hash is unchanged.
  - `test_used_page_edit_changes_hash`: the same, but editing `himalayas_matches.yaml` changes the hash.
  - `test_missing_page_rejected`: a flow whose step has `verify_page: nope` makes `flow_hash` raise `KeyError("nope")`.
- [ ] **Step 2:** Run `pytest tests/test_approvals.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the interfaces above, and switch `Runner.approve_flow` to `flow_hash(self.flow_path, REPO / "pages")`.
- [ ] **Step 4:** Run `pytest -v`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Bind flow approval to the pages it uses"`.

### Task 3: Signed hash-chained audit log

**Files:**
- Create: `govaios/audit/__init__.py`, `govaios/audit/log.py`
- Test: `tests/test_audit_log.py`

**Interfaces:**
- Produces:
  - `class AuditLog(home: Path)`. On first use with neither file present it creates the ECDSA P-256 key `home/audit_key.pem` (mode 0600) and `home/audit_pubkey.pem`.
  - `AuditLog.append(kind: str, **fields) -> dict` returns the written entry.
  - `url_for_audit(url: str) -> str` returns origin + path, with the query and fragment dropped.
  - `AuditError(Exception)`.
  - Entry JSON keys: `seq` (int, from 1), `ts` (ISO-8601 UTC with seconds), `kind`, then the caller's fields, then `prev` (the previous entry's `hash`, or 64 zeros for seq 1), `hash`, `sig` (base64 DER).
  - The hash is SHA-256 hex of the canonical JSON (`sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`) of the entry without `hash` and `sig`. The sig is ECDSA-SHA256 over the `hash` string's UTF-8 bytes.
  - `kind` is one of `flow_start`, `flow_approval`, `request`, `action`, `verify`, `stop`, `flow_end`.
  - The allowed caller fields are `flow`, `flow_version`, `flow_hash`, `executor`, `step`, `action`, `risk`, `target`, `destination`, `decision`, `approver`, `channel`, `outcome`, `reason`. Anything else raises `AuditError`, so content cannot be logged by accident.

- [ ] **Step 1: Write the failing tests:**
  - `test_first_entry_links_to_zero`: `append("flow_start", flow="f")` gives `seq == 1` and `prev == "0"*64`.
  - `test_chain_links`: the second entry's `prev` equals the first entry's `hash`.
  - `test_unknown_field_rejected`: `append("action", body="secret")` raises `AuditError`.
  - `test_url_for_audit`: `url_for_audit("https://mail.google.com/mail/u/0/?q=x#inbox/123") == "https://mail.google.com/mail/u/0/"`.
  - `test_missing_key_with_existing_log_refuses`: append once, delete `audit_key.pem`, construct a new `AuditLog` and append; it raises `AuditError` with message containing "audit key missing".
  - `test_truncated_tail_refuses_append`: append twice, write `'{"seq": 3, "ts'` with no newline to the file, then append; it raises `AuditError` containing "truncated".
  - `test_concurrent_appends_stay_chained`: two `multiprocessing` processes each append 50 entries to the same home; the file has 100 lines, `seq` runs 1..100, and every `prev` matches.
  - `test_file_is_append_only_flag`: after the first append, `os.stat(path).st_flags & stat.UF_APPEND` is non-zero.
- [ ] **Step 2:** Run `pytest tests/test_audit_log.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `AuditLog` in `govaios/audit/log.py`:
  - Under `fcntl.flock(LOCK_EX)` on `home/audit.lock`, read the last line, refuse if it doesn't end in a newline, compute the entry, write it, then `flush` and `os.fsync`.
  - Set `UF_APPEND` with `os.chflags` once at file creation.
  - Mark the key with `# shortcut: key on disk (0600), not Secure Enclave; move to Secure Enclave in the deployment plan.`
- [ ] **Step 4:** Run `pytest tests/test_audit_log.py -v`. Expected: 8 passed. Note for test cleanup: clearing `UF_APPEND` (`os.chflags(path, 0)`) must happen before `tmp_path` deletion; add a fixture that does this.
- [ ] **Step 5:** Commit: `git commit -m "Add signed hash-chained audit log"`.

### Task 4: Standalone audit verifier

**Files:**
- Create: `govaios/audit/verify.py` (imports only the stdlib and `cryptography`, never other `govaios` modules, so it can be copied out and run alone)
- Test: `tests/test_audit_verify.py`

**Interfaces:**
- Consumes: the entry format from Task 3.
- Produces:
  - `verify(log_path: Path, pubkey_path: Path) -> VerifyResult`.
  - `@dataclass VerifyResult: ok: bool; entries: int; problem: str | None; line: int | None`. `problem` is one of `"truncated tail"`, `"bad hash"`, `"bad signature"`, `"broken chain"`, `"seq gap"`, `None`.
  - `main(argv) -> int` prints `OK <n> entries` or `FAIL line <n>: <problem>`, and returns 0 or 1.
  - Runnable as `python verify.py audit.jsonl audit_pubkey.pem`.

- [ ] **Step 1: Write the failing tests**, each building a log with `AuditLog` in `tmp_path`, clearing `UF_APPEND`, and tampering:
  - `test_clean_log_ok`: 3 entries give `ok` and `entries == 3`.
  - `test_edited_field_bad_hash`: change entry 2's `outcome` and the result is `("bad hash", 2)`.
  - `test_rehashed_edit_bad_signature`: change entry 2 and recompute its `hash` and the result is `("bad signature", 2)`.
  - `test_deleted_middle_entry`: removing line 2 gives `("broken chain", 2)`.
  - `test_truncated_tail_reported`: a partial last line gives `("truncated tail", 4)`.
  - `test_cli_exit_codes`: `main([...])` returns 0 for clean and 1 for tampered.
- [ ] **Step 2:** Run `pytest tests/test_audit_verify.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `verify` and `main`. Check order for each line: parse (an unterminated last line is a truncated tail), then seq, then prev, then hash, then signature.
- [ ] **Step 4:** Run `pytest tests/test_audit_verify.py -v`. Expected: 6 passed.
- [ ] **Step 5:** Commit: `git commit -m "Add standalone audit verifier"`.

### Task 5: Engine audits every governed event

**Files:**
- Modify: `govaios/engine.py`
- Test: `tests/test_engine_audit.py`

**Interfaces:**
- Consumes: `AuditLog`, `url_for_audit` (Task 3); `flow_hash` (Task 2).
- Produces: `Runner(flow_path: Path, desktop, home: Path)`, with approvals at `home/approvals.json` and `self.audit = AuditLog(home)`. `Runner.gate(action: str, risk: str, target: str | None = None, destination: str | None = None)`. Every call writes one `request` entry with these fields:
  - `decision`: the final `allow` or `deny`;
  - `approver`: `"admin"` if asked, else `"policy"`;
  - `channel`: `"desktop_dialog"` if asked, else `None`;
  - `destination = url_for_audit(dest)`;
  - `executor = "gov_runner"`;
  - `target` as an element ref, for example `himalayas_matches.job_cards[2].title` (the 1-based item index in brackets).

  Further entries:
  - each OS side effect writes an `action` entry (`outcome`: `"done"` or `"error"`);
  - each page verification writes `verify` (`outcome`: the page id or `"no_match"`);
  - `Stop` writes `stop` with `reason`;
  - the run starts with `flow_start` and ends with `flow_end`;
  - a first-run approval writes `flow_approval` (`decision`, `approver`, `channel`, `flow_hash`).

  `do_write_json` writes to `home / <directory>`, never next to the code.

- [ ] **Step 1: Write the failing tests**, using a `FakeDesktop` defined in the test file. It holds a canned `Node` tree for `himalayas_matches` and `himalayas_job_detail`, built from the shapes in `pages/*.yaml`, records clicks and keys instead of sending them, and its `ask_admin` returns a scripted list of answers.
  - `test_run_writes_start_and_end`: run the Himalayas flow with `count: 1` against the fake, admin approves everything. The first kind is `flow_start`, a `flow_approval` follows, the last kind is `flow_end`, and `verify(...)` from Task 4 is `ok`.
  - `test_click_target_is_element_ref`: some `request` entry has `target == "himalayas_matches.job_cards[1].title"`.
  - `test_no_content_in_audit`: the fake's job description text is `"SECRET-DESCRIPTION"` and its title is `"SECRET-TITLE"`; neither string appears anywhere in `audit.jsonl`.
  - `test_denied_flow_approval_logged`: the admin denies the first dialog, so `Stop` is raised, and the last two kinds are `flow_approval` (`decision: "deny"`) and `stop`.
  - `test_write_json_under_home`: after the run, `tmp_path/'jd_selected'` holds 1 file, and nothing was written under `REPO`.
  - `test_destination_url_redacted`: the `request` entry for `open_matches` has `destination == "https://himalayas.app/jobs/matches"` even when the fake's current URL has `?utm=x`.
- [ ] **Step 2:** Run `pytest tests/test_engine_audit.py -v`. Expected: FAIL.
- [ ] **Step 3:** Thread `target` refs through `gate()` calls in each `do_*` method, wrap every adapter call in an `action` entry, and wrap `run()` in `flow_start`/`flow_end` and `stop`. Remove `Runner.log`'s duplicate of the audit: keep console printing, but print only kind, step and decision.
- [ ] **Step 4:** Run `pytest -v`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Audit every governed event in the engine"`.

### Task 6: No network during runs

**Files:**
- Create: `govaios/netguard.py`
- Test: `tests/test_netguard.py`

**Interfaces:**
- Produces: `block_all_network() -> None`. After it is called, creating or connecting any `AF_INET` or `AF_INET6` socket in this process raises `PermissionError("network blocked during run")`. `AF_UNIX` is unaffected. The call is idempotent and cannot be undone in-process (there is no `unblock`). `getaddrinfo` also raises.

- [ ] **Step 1: Write the failing tests.** Run each in a subprocess (`subprocess.run([sys.executable, "-c", ...])`), because the block is permanent:
  - `test_inet_connect_blocked`: `socket.create_connection(("127.0.0.1", 9))` fails with "network blocked".
  - `test_urllib_blocked`: `urllib.request.urlopen("https://example.com")` fails with "network blocked".
  - `test_unix_socket_allowed`: `socket.socket(socket.AF_UNIX)` succeeds.
  - `test_osascript_dialog_unaffected`: `subprocess.run(["osascript", "-e", "return 1"])` returns 0.
- [ ] **Step 2:** Run `pytest tests/test_netguard.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement by wrapping `socket.socket.__init__` and `socket.getaddrinfo`. Mark it `# shortcut: in-process guard only; a C extension can bypass it. Runs under test use a credential-free GOVAIOS_HOME, so a bypass leaks nothing. The OS-level egress block (sandbox profile) comes with plan 2.`
- [ ] **Step 4:** Run `pytest tests/test_netguard.py -v`. Expected: 4 passed.
- [ ] **Step 5:** Commit: `git commit -m "Block network during flow runs"`.

### Task 7: Read-only audit web UI

**Files:**
- Create: `govaios/audit/web.py`
- Test: `tests/test_audit_web.py`

**Interfaces:**
- Consumes: `verify` (Task 4); the entry format (Task 3).
- Produces: `make_server(home: Path, port: int = 0) -> tuple[http.server.ThreadingHTTPServer, str]`, which binds `127.0.0.1` only and returns the server and a random token from `secrets.token_urlsafe(32)`. Routes, GET only, each requiring `?t=<token>`:
  - `/` lists runs (the entries from each `flow_start` to its `flow_end` or `stop`) with flow, time, steps and final outcome, and shows a verification banner (`OK <n> entries`, or a red `FAIL line <n>: <problem>`);
  - `/run/<seq>` lists that run's entries in a table (kind, step, action, target, decision, approver, channel, outcome, reason);
  - `/approvals` lists the approved flows and destinations from `approvals.json`.

  A missing or wrong token gives 403, an unknown path 404, and any other method 405. Every response carries `Cache-Control: no-store` and `Referrer-Policy: no-referrer`, because the token in the URL ends up in browser history. All values are HTML-escaped. Day-1 auth is marked `# shortcut: URL token, not Touch ID; replaced by admin authentication in plan 2.`

- [ ] **Step 1: Write the failing tests**, starting the server on a thread with port 0:
  - `test_requires_token`: GET `/` without a token gives 403.
  - `test_index_lists_run`: with a home holding one run from `AuditLog`, GET `/?t=..` gives 200 and the body contains the flow id and `OK`.
  - `test_tampered_log_banner`: after editing an entry, the body contains `FAIL line`.
  - `test_post_rejected`: POST `/` gives 405, and `audit.jsonl` bytes are unchanged.
  - `test_unknown_path_404`: GET `/../audit_key.pem?t=..` gives 404.
  - `test_escapes_html`: an entry with `reason="<script>x</script>"` is rendered escaped.
  - `test_binds_localhost_only`: `server.server_address[0] == "127.0.0.1"`.
  - `test_no_store_headers`: every response, including the 403, has `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
- [ ] **Step 2:** Run `pytest tests/test_audit_web.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement using a `BaseHTTPRequestHandler` subclass and server-rendered HTML with inline CSS, with no JavaScript and no external assets.
- [ ] **Step 4:** Run `pytest tests/test_audit_web.py -v`. Expected: 8 passed.
- [ ] **Step 5:** Commit: `git commit -m "Add read-only local audit web UI"`.

### Task 8: CLI and identity checks

**Files:**
- Modify: `govaios/identity.py`, `govaios/cli.py` (both from Task 1b)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Runner` (Task 5), `block_all_network` (Task 6), `verify.main` (Task 4), `make_server` (Task 7), `get_desktop` (Task 1), `identity.check` and `cli.main`'s exit file (Task 1b).
- Produces:
  - `identity.require_app(dev: bool) -> None` raises `SystemExit` with the message `gov-aios must run as com.govaios.cli (use bin/gov-aios); --dev allows Python for development only` unless `bundle_id == "com.govaios.cli"` or `dev`. With `dev` it prints a `DEV MODE: insecure, not for real use` warning to stderr.
  - `cli.main(argv: list[str] | None = None) -> int` with subcommands:
    - `run <flow.yaml> [--dev]`: `require_app`, then `block_all_network()`, then `Runner(...).run()`; exit 1 with `STOPPED: <reason>` on `Stop`;
    - `verify-audit`: runs `verify.main` on the home's files;
    - `audit-ui [--port N]`: prints `http://127.0.0.1:<port>/?t=<token>` and serves; network is not blocked here, as it's a separate command bound to localhost;
    - `doctor`: prints `identity.check()` and exits 1 if anything is false;
    - `dump [url]`: the spike's `dump.py` behaviour.

    `run`, `dump` and `doctor` require the app unless `--dev`.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_refused_outside_app`: `main(["run", "flows/himalayas_job_vetting.yaml"])` under pytest (not frozen, no bundle id) raises `SystemExit` whose message contains `com.govaios.cli`.
  - `test_run_dev_blocks_network`: monkeypatch `Runner.run` to try `socket.create_connection(("127.0.0.1", 9))`; run in a subprocess with `--dev`; it exits non-zero and stderr contains `network blocked` and `DEV MODE`.
  - `test_doctor_fields`: monkeypatch `identity.check` to return all true, and `main(["doctor","--dev"]) == 0`.
  - `test_verify_audit_exit`: with a clean log in `GOVAIOS_HOME=tmp_path`, `main(["verify-audit"]) == 0`.
- [ ] **Step 2:** Run `pytest tests/test_cli.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement with `argparse`. Data home comes from `govaios.home.data_home()`.
- [ ] **Step 4:** Run `pytest -v`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Add gov-aios CLI with identity checks"`.

### Task 9: Attended end-to-end verification and docs

**Files:**
- Create: `packaging/README.md`
- Modify: `README.md` (add a "Run gov-aios" section under Part I "Build order", 6 lines: build, grant permissions, doctor, run, audit-ui, verify)

**Interfaces:**
- Consumes: the app and shim (Task 1b), and the full CLI (Task 8).

- [ ] **Step 1:** Run `packaging/build.sh && bin/gov-aios doctor; echo "exit=$?"`. Expected: `bundle_id: com.govaios.cli`, `frozen: True`.
- [ ] **Step 2 (admin):** Ask the admin to add `dist/gov-aios.app` under System Settings › Privacy & Security › Accessibility and Screen Recording. Do not toggle these yourself. Then run `bin/gov-aios doctor`. Expected: all `True`, exit 0. Then run `.venv/bin/python -m govaios.cli doctor --dev` from Terminal and confirm its `accessibility` reflects Terminal's own grant, not the app's. This proves the permission belongs to `com.govaios.cli`.
- [ ] **Step 3 (admin attended):** Run `bin/gov-aios run flows/himalayas_job_vetting.yaml`. Expected:
  1. one flow-approval dialog (new home, new hash);
  2. destination dialogs for google.com and himalayas.app;
  3. 5 files written to `~/Library/Application Support/GOV-AIOS/jd_selected/`;
  4. `bin/gov-aios verify-audit` prints `OK <n> entries`.

  Then run `bin/gov-aios audit-ui`, open the printed URL, and confirm the run is listed with the green OK banner.
- [ ] **Step 4:** Write `packaging/README.md`, covering:
  - the build;
  - `--onedir` and why `--onefile` breaks `_MEIPASS`;
  - the signing identity (`GOVAIOS_SIGN_ID`): how to create a stable self-signed "GOV-AIOS Dev" code-signing certificate in Keychain Access, and why ad-hoc signing loses the permissions on every rebuild;
  - granting permissions;
  - the shim's temp-file stdio;
  - "never grant Terminal or Python these permissions for GOV-AIOS".

  Then write the README section.
- [ ] **Step 5:** Commit: `git commit -m "Verify gov-aios end to end and document packaging"`.
