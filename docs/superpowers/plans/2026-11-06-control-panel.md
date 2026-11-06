# Control panel (typed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bin/gov-aios panel flows` opens a Touch-ID-gated local page where the admin sets up an authenticator once, opens a 30-minute session with a 6-digit code, types "run joblens", watches the run, and hears "Rupak, the JobLens flow is complete, thank you."

**Architecture:** New package `govaios/panel/` holds pure parts (`totp.py`, `session.py`, `tickets.py`, `apps.py`) and the run launcher (`launch.py`, a Python port of the shim's two launches). The audit page server (`govaios/audit/web.py`) grows into the panel server: Talk page, audit pages under `/audit`, approvals, setup. The panel never runs flows itself: it writes a one-use run ticket and launches the signed app, whose `run` consumes the ticket instead of asking Touch ID.

**Tech Stack:** Python 3.14 standard library, PyObjC (existing), PyYAML, `segno` (new, pure Python, QR only), pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-control-panel-design.md`

## Global Constraints

- Panel serves `127.0.0.1` only, under `UI_PROFILE`; `sandbox.apply` stays first in `main()`. Runs keep `RUN_PROFILE`, delivery keeps `DELIVER_PROFILE`.
- Page CSP stays `default-src 'none'; style-src 'unsafe-inline'`: no JavaScript. Live progress uses `<meta http-equiv="refresh" content="2">` while a run is live.
- The page never approves: approving an app goes through `auth.approve` (native dialog + Touch ID) in the server process.
- Terminal `run` without a ticket keeps `auth.prove` (Touch ID) exactly as today.
- TOTP: RFC 6238, HMAC-SHA1, 6 digits, 30 s step, accept steps −1/0/+1, refuse a step already used, 5 wrong codes in a row → code entry locked 15 minutes; constant-time compare.
- Session: exactly 30 minutes from the accepted code, monotonic clock, never extended. Ends on: expiry, any screen lock, STOPPED, Reset authenticator, End session, server stop. When it ends, its run is stopped (SIGTERM to the app pid) and a not-yet-started `deliver` launch is not started.
- Run ticket: 32 random bytes hex, file `<home>/tickets/<hex>` mode 0600, created `O_CREAT|O_EXCL|O_NOFOLLOW`, content JSON `{"flow": id, "digest": hex, "expires": unix_ts}`, valid 60 s, deleted on consume; env var `GOVAIOS_RUN_TICKET`.
- Audit: new kinds `totp_setup`, `totp_reset`, `session_open`, `session_end`; new field `session` (random session id). Never the code or the secret. Panel run start: `request`, `action="run_start"`, `approver="admin"`, `channel="totp_session"`, `auth="ticket"`, `session=<id>`.
- Spoken text exactly: `"{name}, the {app} flow is complete, thank you."` / `"{name}, the {app} flow stopped: {reason}."`; name default `"Rupak"`; speech via `/usr/bin/say`.
- Refusal texts exactly: draft → `"{app} is a draft. Get it approved first."`; busy → `"{app} is still running."`; no match → `"I don't know that app. Approved apps: {names}."`; ambiguous → `"Which app: {names}?"`; no session → `"Enter the 6-digit code from your authenticator."`.
- No job or mail content in the page, the audit log or stdout. All 477 existing tests keep passing (update only those this plan names).

## Review Focus

1. A forged POST from another local page (no cookie, wrong `Origin`, bad CSRF) must never open a session or start a run. Test in Task 5.
2. A screen lock followed by an unlock between two page requests must still end the session (the ticker sees it). Test in Task 6.
3. Moving the wall clock back must not extend a session; ticket expiry is wall-clock (crosses processes) and is also capped at 60 s from creation. Test in Task 2.
4. A code typed while a session is open must not reset its 30 minutes. Test in Task 2.
5. Hotkey stop during a panel run: the run ends, the page shows "stopped", the session ends. Test in Task 6.

---

### Task 1: TOTP and the authenticator secret

**Files:**
- Create: `govaios/panel/__init__.py` (empty), `govaios/panel/totp.py`
- Modify: `govaios/audit/log.py` (`KINDS`, `FIELDS`), `pyproject.toml` (add `segno`), `packaging/gov-aios.spec` (`hiddenimports` add `"segno"`)
- Test: `tests/test_totp.py`

**Interfaces:**
- Produces:
  - `new_secret() -> bytes` (20 random bytes)
  - `otpauth_uri(secret: bytes, account: str = "Admin") -> str` → `otpauth://totp/GOV-AIOS:Admin?secret=<base32 no padding>&issuer=GOV-AIOS`
  - `qr_svg(uri: str) -> str` (inline `<svg>` via `segno.make(uri).svg_inline(scale=4)`)
  - `code_at(secret: bytes, t: float) -> str` (6 digits, zero-padded)
  - `class Verifier(path: Path, clock=time.time)`: `.verify(code: str) -> str` returns `"ok"`, `"bad_code"`, `"replay"`, `"locked_out"`, `"no_secret"`; state (last used step, failure count, lockout until) persisted in `path` beside the secret.
  - `class SecretStore(home: Path)`: `.load() -> bytes | None`, `.save(secret: bytes)`, `.delete()`; file `<home>/totp.key` mode 0600, created with `O_CREAT|O_EXCL|O_NOFOLLOW` (save replaces atomically via a temp file in the same directory). `# shortcut: file 0600 like audit_key.pem, not the Keychain; move with the Secure Enclave work.`
  - Audit `KINDS` += `totp_setup`, `totp_reset`, `session_open`, `session_end`; `FIELDS` += `session`.

- [ ] **Step 1: Failing tests** in `tests/test_totp.py`:
  - `test_rfc6238_vectors` — secret `b"12345678901234567890"`, 6-digit codes: t=59 → `"287082"`, t=1111111109 → `"081804"`, t=1111111111 → `"050471"`, t=1234567890 → `"005924"`, t=2000000000 → `"279037"`, t=20000000000 → `"353130"`.
  - `test_window_plus_minus_one` — codes for t−30 and t+30 verify `"ok"` at t; t−60 → `"bad_code"`.
  - `test_replay_refused` — same code twice → second `"replay"`; also a code from an earlier step than the last used → `"replay"`.
  - `test_lockout_after_five` — 5 wrong → 6th call (even with a right code) `"locked_out"`; after 15 min (fake clock) a right code → `"ok"`; a success resets the failure count.
  - `test_no_secret` → `"no_secret"`.
  - `test_secret_store_mode_and_no_follow` — saved file mode `0o600`; a symlink at `totp.key` → `load()` raises or returns None, never reads the target.
  - `test_otpauth_uri_and_qr` — URI exact for a fixed secret; `qr_svg` starts with `<svg`.
  - `test_audit_accepts_new_kinds` — each new kind appends with `session="ab"*8`.
- [ ] **Step 2:** `.venv/bin/pip install segno` then run → FAIL (module missing).
- [ ] **Step 3:** implement.
- [ ] **Step 4:** `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5:** commit `feat(panel): TOTP verifier and authenticator secret store`.

### Task 2: session and run tickets

**Files:**
- Create: `govaios/panel/session.py`, `govaios/panel/tickets.py`
- Test: `tests/test_panel_session.py`

**Interfaces:**
- Produces:
  - `SESSION_S = 30 * 60`
  - `class Session(clock=time.monotonic)`: `.open() -> str` (new random id; raises `RuntimeError` if one is open), `.active() -> bool`, `.remaining() -> float`, `.id -> str | None`, `.end(reason: str) -> str | None` (returns the ended id, None if none was open). Expiry is `opened_at + SESSION_S` on the monotonic clock.
  - `tickets.create(home: Path, flow_id: str, digest: str, now=time.time) -> str` (hex token; JSON per Global Constraints)
  - `tickets.consume(home: Path, token: str, flow_id: str, digest: str, now=time.time) -> bool` — true only if: token is 64 hex chars; the file is a regular file opened `O_NOFOLLOW`; JSON valid; flow and digest match; `now <= expires` and `expires - now <= 60`. The file is unlinked before returning, whatever the result.

- [ ] **Step 1: Failing tests:**
  - `test_session_lasts_exactly_30_min` — fake monotonic clock: active at 29:59, not at 30:00.
  - `test_session_not_extended` — `open()` while active raises; `remaining()` unchanged.
  - `test_wall_clock_back_does_not_extend` — Session ignores `time.time` (only the injected monotonic clock is read).
  - `test_end_returns_id_once` — first `end("ended")` returns the id, second returns None.
  - `test_ticket_once` — create then consume → True; consume again → False.
  - `test_ticket_rejections` (parametrized): expired; `expires` more than 60 s ahead (forged); other flow; other digest; non-hex token (`"../x"`); symlink at the ticket path; missing file → all False, and no file left behind.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** full suite → pass.
- [ ] **Step 5:** commit `feat(panel): 30-minute session and one-use run tickets`.

### Task 3: apps, command matching, run start by ticket

**Files:**
- Create: `govaios/panel/apps.py`
- Modify: `govaios/engine.py` (`Runner.__init__` gains `ticket: str | None = None`; `_run` start; new module function `approval_question(flow: dict, deliver: dict | None) -> str` used by `approve_flow`), `govaios/cli.py` (`_run` passes `os.environ.get("GOVAIOS_RUN_TICKET")`)
- Test: `tests/test_panel_apps.py`, `tests/test_engine_audit.py`

**Interfaces:**
- Consumes: `tickets.consume` (Task 2).
- Produces:
  - `@dataclass App: id: str, name: str, path: Path, digest: str, approved: bool`
  - `list_apps(flows_dir: Path, home: Path) -> list[App]` — every `*.yaml` in `flows_dir`, pages from `flows_dir.parent / "pages"`, digest via `read_bound`, `approved = Approvals(home/"approvals.json").flow_ok(id, digest)`, `name = workflow.get("app") or workflow["name"]`; a file that fails to load is skipped. Sorted: approved first, then by name.
  - `match(text: str, apps: list[App]) -> tuple[str, App | list[App] | None]` → `("run", app)`, `("draft", app)`, `("ambiguous", [apps])`, `("unknown", None)`. Normalise: lowercase, split on non-alphanumerics, drop words `run, the, app, flow, now, please, start`; compare the remaining words joined by space with each app's name and id (id with `_` → space), lowercased.
  - `engine.approval_question(flow, deliver) -> str` — the exact text `approve_flow` builds today.
  - Runner with `ticket`: in `_run`, when the flow is approved, `tickets.consume(home, ticket, id, digest)` replaces `auth.prove`; audit `request` `action="run_start"`, `decision`, `approver="admin"`, `channel="totp_session"`, `auth="ticket"`; failure → `Stop("run ticket not valid")`, no prompt. A ticket for a flow not approved → `Stop("run ticket not valid")` (no approval dialog from a panel run).

- [ ] **Step 1: Failing tests:**
  - `test_match_phrases` — apps JobLens (approved, id `himalayas_job_vetting`), Inbox briefing (draft, id `morning_inbox_briefing`): `"Run the JobLens app now"` → run JobLens; `"run himalayas job vetting"` → run JobLens; `"run inbox briefing"` → draft; `"run mail"` → unknown; with a second approved app named `JobLens Two`, `"run joblens"` still → JobLens (exact match), `""` → unknown.
  - `test_list_apps_approved_and_draft` — temp flows/pages copy; approve one digest → approved; edit its file → draft.
  - `test_ticket_run_skips_touch_id` — Runner with a valid ticket: `auth.prove` never called (fail if called); audit has the `run_start` entry with `channel="totp_session"`.
  - `test_bad_ticket_stops_without_prompt` — invalid ticket → `Stop("run ticket not valid")`, `auth.prove` and `auth.approve` never called.
  - `test_terminal_run_still_proves` — no ticket → `auth.prove` called once (existing behaviour).
  - `test_approval_question_unchanged` — `approval_question` output equals the string the existing approval test captures.
  - `test_cli_run_passes_ticket_env` — `GOVAIOS_RUN_TICKET=abc` reaches `Runner(..., ticket="abc")`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** full suite → pass.
- [ ] **Step 5:** commit `feat(panel): app list, command matching, run start by ticket`.

### Task 4: run launcher (Python port of the shim)

**Files:**
- Create: `govaios/panel/launch.py`
- Test: `tests/test_panel_launch.py`

**Interfaces:**
- Produces: `class RunLaunch(flow_path: Path, ticket: str, app: str = "/Applications/gov-aios.app", open_cmd: str = "open")`:
  - `.start()` — starts a thread doing: launch 1 `open -W -n -a <app> --stdout <f> --stderr <f> --env GOVAIOS_EXIT_FILE=.. --env GOVAIOS_PID_FILE=.. --env GOVAIOS_NEXT_FILE=.. --env GOVAIOS_RUN_TICKET=<ticket> --args run <flow>`; if its exit code is 0 and the next file holds exactly `deliver` and `stop()` was not called, launch 2 with `--args deliver <flow>` (no ticket, no next file).
  - `.lines() -> list[str]` — stdout+stderr lines so far, both launches, in order received.
  - `.done -> bool`, `.code -> int | None` (last launch's code; 70 if the exit file is empty), `.summary -> str | None` (the `deliver joblens: ...` line if any), `.stopped_reason -> str | None`.
  - `.stop(reason: str)` — sets the reason, SIGTERMs the pid in the current launch's pid file (waiting up to 2 s for it to appear), and prevents launch 2.
  - Temp files via `tempfile.mkstemp` in a private temp dir, removed when done.

- [ ] **Step 1: Failing tests** with a fake `open` script (bash, first on `PATH` via `open_cmd` path) that parses the same flags as `tests/test_shim.py`'s fake and writes `$FAKE_CODE` / `deliver` as configured; `FAKE_SLEEP` makes launch 1 sleep and write its own pid to the pid file:
  - `test_run_then_deliver` — next file `deliver` → 2 launches; argv of launch 1 contains `GOVAIOS_RUN_TICKET=t1`, launch 2 does not.
  - `test_failed_run_no_deliver` — code 1 → one launch, `code == 1`.
  - `test_stop_kills_and_skips_deliver` — `FAKE_SLEEP=5`, `stop("session ended")` → the fake receives SIGTERM, only one launch, `stopped_reason == "session ended"`, `done` within 3 s.
  - `test_summary_captured` — fake deliver prints `deliver joblens: delivered 2, duplicate 3, retry 0, failed 0, skipped 0` → `.summary` equals it.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** full suite → pass.
- [ ] **Step 5:** commit `feat(panel): run launcher with stop`.

### Task 5: panel server — pages, setup, session open, commands

**Files:**
- Modify: `govaios/audit/web.py` (becomes the panel server; `make_server(home, port=0, now=time.time, flows_dir=None, launcher=RunLaunch, speak=_say, name="Rupak")`)
- Test: `tests/test_audit_web.py` (move existing page tests to the new paths), new `tests/test_panel_web.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces routes (all behind the existing Host check, lock check, cookie session; every POST also needs the CSRF field and an absent-or-matching `Origin`):
  - `GET /` Talk: session ring text (`No session` / `Session open: N min left`), conversation lines (server-side list, newest last), the run's step lines while live, a form `POST /say` (field `text`), Approved and Drafts lists (each draft with an `Approve…` form `POST /approve` field `flow`), `End session` form when open. `<meta refresh 2>` only while a run is live.
  - `GET /audit`, `/audit/log`, `/audit/run/<seq>` — today's `/`, `/log`, `/run/<seq>` pages, same content; runs table gains column `started by`: `Panel, session code` when the run's `run_start` entry has `channel="totp_session"`, else `Terminal, Touch ID`.
  - `GET /approvals` (as today, plus an Authenticator row: `Set up` link or `Reset authenticator` form `POST /totp/reset`), `POST /revoke` unchanged.
  - `GET /totp/setup` — only when no secret: makes a pending secret (held in memory), shows `qr_svg` and the base32 key; `POST /totp/setup` field `code`: verify against the pending secret, then `auth.approve("Set up the authenticator for GOV-AIOS?", "set up authenticator", home)`; only on yes `SecretStore.save` + audit `totp_setup`.
  - `POST /totp/reset` — `auth.prove("reset the authenticator", home)`; yes → delete secret, end session (`reset`), audit `totp_reset`.
  - `POST /say` — no session: text that is all 6 digits → `Verifier.verify`; `"ok"` → `Session.open()`, audit `session_open` decision allow + `session`; else audit `session_open` decision deny + `reason` (`bad_code`/`replay`/`locked_out`/`no_secret`) and the line `"That code did not work."` (or `"Too many wrong codes. Try again in 15 minutes."`). Any other text without a session → the no-session line. With a session: `apps.match`; `run` → if a run is live the busy line, else `tickets.create` + `launcher(...).start()`; `draft`/`unknown`/`ambiguous` → the exact Global Constraints texts. Admin lines are shown as `Admin -> <text>` (escaped).
  - `POST /approve` field `flow` → the draft's `approval_question` via `auth.approve`; yes → `approve_flow` + audit `flow_approval` like the CLI; no → nothing written.
  - `POST /end` → end session (`ended`).

- [ ] **Step 1: Failing tests** in `tests/test_panel_web.py` (real server on port 0 in a thread, as `test_audit_web.py` does; fake `auth`, fake launcher class recording calls, fake `speak`):
  - `test_forged_requests_never_run` — POST `/say` with: no cookie; wrong `Origin`; bad CSRF → 403 and the fake launcher never constructed, no `session_open` entry.
  - `test_code_opens_session_then_run` — set up a secret in the store; POST a valid code → `session_open` allow; POST `run joblens` → launcher constructed with the JobLens flow path and a ticket whose file exists.
  - `test_no_session_asks_for_code` and `test_wrong_code_audited_without_code` (the audit entry has no field containing the code).
  - `test_draft_refused_text`, `test_unknown_and_ambiguous_texts`, `test_busy_text`.
  - `test_setup_requires_code_then_touch_id` — wrong code → nothing saved; right code + approve False → nothing saved; right code + approve True → saved, `totp_setup` entry.
  - `test_approve_draft_uses_native_dialog` — approve False → `approvals.json` unchanged; True → draft becomes approved.
  - `test_audit_pages_moved` — `/audit` lists runs with `started by`; old `/` audit content no longer at `/`.
  - `test_page_has_no_script_and_csp_unchanged`.
  - `test_no_content_in_page` — a run line containing `ZQXMARKER` in a job field never appears (only step lines from the launcher are shown, which carry none; assert the page renders launcher lines escaped).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement; keep the existing helpers (`_entries`, `_runs`, `banner`, `guarded`, `SEC`).
- [ ] **Step 4:** full suite → pass (moved paths updated in `tests/test_audit_web.py`).
- [ ] **Step 5:** commit `feat(panel): talk page, authenticator setup, session, typed commands`.

### Task 6: run lifecycle — ticker, session end stops the run, spoken result

**Files:**
- Modify: `govaios/audit/web.py`
- Test: `tests/test_panel_web.py`

**Interfaces:**
- Consumes: `Session`, `RunLaunch.stop/done/code/summary/stopped_reason`, `auth.screen_locked`, `runstate.stopped`.
- Produces: a daemon ticker thread started by `make_server`, every 1 s:
  - if a session is open and (`not session.active()` → reason `expired`; `auth.screen_locked()` → `screen_lock`; `runstate.stopped(home)` → `emergency_stop`): end it, audit `session_end` with `session` and `reason`, and `run.stop("session ended")` if a run is live.
  - when a live run becomes `done`: add the result line (`"<app> finished: <summary>"` or `"<app> stopped: <reason>"`) and call `speak(text)` with the exact Global Constraints sentence (reason = `stopped_reason` or `"exit <code>"`).
  - `End session`, `Reset authenticator` and server shutdown also stop a live run (`"session ended"`).
  - The browser-session expiry shutdown waits until no run is live.
  - `_say(text)`: `subprocess.run(["/usr/bin/say", text], timeout=60)`, errors ignored.

- [ ] **Step 1: Failing tests** (inject a fake clock into `Session`, a fake `screen_locked`, and call the ticker's `tick()` directly rather than sleeping):
  - `test_expiry_stops_run` — open session, start a fake run, advance 30 min, `tick()` → `session_end` reason `expired`, fake run's `stop("session ended")` called.
  - `test_lock_then_unlock_between_requests_ends_session` — `screen_locked` True for one tick then False → session ended (`screen_lock`).
  - `test_stopped_flag_ends_session` — STOPPED file → `emergency_stop`.
  - `test_done_run_speaks_complete` — fake run done with code 0 and summary → `speak("Rupak, the JobLens flow is complete, thank you.")` and the result line.
  - `test_stopped_run_speaks_reason` — stopped with "session ended" → `speak("Rupak, the JobLens flow stopped: session ended.")`.
  - `test_server_waits_for_live_run` — browser-session expiry with a live run → server keeps serving; after the run is done → it stops.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** full suite → pass.
- [ ] **Step 5:** commit `feat(panel): session end stops its run; spoken result`.

### Task 7: `panel` command, alias, JobLens display name

**Files:**
- Modify: `govaios/cli.py` (`panel [flows_dir] [--port]`; `audit-ui` same handler; `PROFILES["panel"] = sandbox.UI_PROFILE`), `flows/himalayas_job_vetting.yaml` (`app: JobLens` after `name:`), `tests/test_cli.py` (`SUBCOMMANDS` gets `"panel"` right after `"audit-ui"`, profile map `panel → UI_PROFILE`), `tests/test_delivery.py` (`test_real_flows_load` also checks `app`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `make_server(..., flows_dir=...)`.
- Produces: `bin/gov-aios panel flows` (shim already makes the path absolute) and `bin/gov-aios audit-ui` (no flows dir → Talk shows `"No apps folder given. Start with: bin/gov-aios panel flows"`).

- [ ] **Step 1: Failing tests:** `test_panel_deny_and_allow` (mirror of `test_audit_ui_deny_and_allow`, with a flows dir passed through to `make_server`), `test_audit_ui_alias_same_handler`, the sandbox table rows; `test_real_flows_load` asserts Himalayas `workflow["app"] == "JobLens"`; morning digest still `a1dca44ed9e272377fe86987aca8bece3a1dcd7c4ef797e6ed40d4e8386ff4ae`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement.
- [ ] **Step 4:** full suite → pass.
- [ ] **Step 5:** commit `feat(cli): panel command; JobLens display name`.

### Task 8: live test (admin)

- [ ] **Step 1 (controller):** `GOVAIOS_SIGN_ID="GOV-AIOS Dev" packaging/build.sh`; signer check as before.
- [ ] **Step 2 (admin):** `sudo packaging/install.sh --no-claude`; `bin/gov-aios panel flows` → Touch ID → open the printed link (do not paste it).
- [ ] **Step 3 (admin):** Approvals → Set up authenticator: scan the QR on the phone, enter a code, Touch ID.
- [ ] **Step 4 (admin):** Talk: JobLens shows under Drafts (its file changed: `app:`) → `Approve…` → dialog + Touch ID → it moves to Approved.
- [ ] **Step 5 (admin):** type a code → `Session open: 30 min left`; type `run joblens` → no Touch ID; steps update every 2 s; window closes; result line and the spoken sentence.
- [ ] **Step 6 (admin):** type `run inbox briefing` → the draft text. Lock the screen → after unlock the session is ended.
- [ ] **Step 7 (admin):** terminal `bin/gov-aios run flows/himalayas_job_vetting.yaml` while a session is open → still asks Touch ID. `bin/gov-aios verify-audit` → OK.
