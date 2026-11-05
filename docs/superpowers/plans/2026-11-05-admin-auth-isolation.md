# Admin Authentication and Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every grant of power needs proof that the admin is present (Touch ID), a hotkey stops everything, runs have no network at the OS level, and Claude Code can act only through GOV-AIOS's policy engine inside a sandbox it cannot loosen.

**Architecture:** Still one app process per CLI call (the plan-1 shim), plus one resident `gov-aios guard` (LaunchAgent) that owns the emergency-stop hotkey. Claude Code runs the installed app binary as its `PreToolUse` hook, which decides in-process. Processes share state only through locked files in the data home. The app is installed root-owned at `/Applications/gov-aios.app` and named by root-owned Claude Code managed settings.

**Tech Stack:** Python 3.14, pyobjc (adds `pyobjc-framework-LocalAuthentication`), Carbon `RegisterEventHotKey` and libsystem_sandbox `sandbox_init` through `ctypes`, PyYAML, `cryptography`, pytest, PyInstaller, stdlib `http.server`, `launchctl`.

**Spec:** `docs/superpowers/specs/2026-11-05-admin-auth-isolation-design.md` (the **design**), with every decision in `docs/superpowers/decisions/2026-11-05-admin-auth-isolation.md` (the **log**, "row N"). Parent spec: `docs/superpowers/specs/2026-11-05-governance-layer-design.md`. Read the design and the log rows a task cites before starting it.

## Global Constraints

- Plan-1 global constraints still hold (`docs/superpowers/plans/2026-11-05-governance-foundation.md`), except where this list replaces them.
- Installed app: `/Applications/gov-aios.app`, root:wheel. `dist/` is build output only. Shim, hook and guard use the installed copy (row 18).
- Managed settings: `/Library/Application Support/ClaudeCode/managed-settings.json`, root:wheel 0644 (row 14).
- Hook command: `/Applications/gov-aios.app/Contents/MacOS/gov-aios hook` (row 14).
- Guard LaunchAgent: label `com.govaios.guard`, `~/Library/LaunchAgents/com.govaios.guard.plist`, `KeepAlive` and `RunAtLoad` true (row 10).
- Hotkey: `ctrl+option+cmd+.` (row 10).
- Sandbox profile per subcommand, applied once in `main()` right after argument parsing (rows 22, 28):

  | Subcommand | Profile |
  | :--- | :--- |
  | `doctor` | none |
  | `audit-ui` | `UI_PROFILE` |
  | `run`, `dump`, `hook`, `guard`, `resume`, `review-powers`, `claude-settings`, `verify-audit`, `selftest` | `RUN_PROFILE` |
- Presence proof: 60 s overall; anything but success is deny; a new `LAContext` per prompt; `touchIDAuthenticationAllowableReuseDuration` 0; biometrics when available, else device-owner, else deny (rows 4, 6).
- `auth` values: `biometric`, `device_owner`, `failed`, `none`. Channel value for Touch ID proofs: `touch_id` (rows 7, 35).
- Audit `KINDS` add `emergency_stop`, `revoke`, `ui_login`, `powers_review`, `resume`; `FIELDS` add `auth`, `command` (row 25).
- Data-home files: `STOPPED`, `guard.pid`, `runs/<pid>`, `ask.lock`, `approvals.lock`, `powers_review.json`, `executors/claude_code.yaml`.
- Protected paths (always deny, after `realpath`): the data home, `/Library/Application Support/GOV-AIOS`, `/Library/Application Support/ClaudeCode`, `/Applications/gov-aios.app`, `~/.claude`, `~/Library/LaunchAgents` (row 16).
- Shell metacharacters that force `ask`: `;` `&` `|` `$` `` ` `` `<` `>` `(` `)` newline (row 16).
- Powers review max age: 30 days. Audit UI session: 1 hour; login code: single use, 60 s (rows 19, 24).
- `--dev` is never an exemption: it refuses unless `GOVAIOS_HOME` is set and differs from the real data home, then runs every check (row 28).
- Tests never run real Touch ID, dialogs, hotkeys, `launchctl`, `sudo`, `sandbox_init` in the pytest process, or real input. Every pyobjc, `ctypes` and `subprocess` call is mocked, as in `tests/test_macos.py`. A real `sandbox_init` is tested only in a child process.
- Root installs, TCC grants and approval dialogs are the admin's: the plan stops and asks at each (row 1).
- No production code relies on a **[spike]** fact until Task 1 confirms it. A failed check goes back to the architect, who updates the row before the dependent task starts.

## Review Focus

- The Touch ID sheet never calls back (lid closed mid-prompt, biometric lockout, sheet dismissed by the system). `approve`/`prove` must return deny when 60 s pass, never hang (Task 3 test `test_no_reply_is_deny_after_timeout`).
- Claude passes a path that is a symlink into the data home, or `..` segments out of a project root. Decide on the `realpath`, so it is denied (Task 7 test `test_symlink_into_data_home_denied`).
- Two Claude sessions, or a Claude session and a run, ask at the same moment. Only one dialog is on screen at a time; the second tries `ask.lock` for 2 s, then is denied with reason `busy` (row 36; Task 3 test `test_second_prompt_denied_when_busy`).
- `guard.pid` is stale: the guard crashed and the pid was reused by another process. Treat as no guard (Task 5 test `test_reused_guard_pid_is_not_alive`).
- The admin presses the hotkey while an approval dialog is open. That prompt resolves as deny within 1 s (Task 5 test `test_stop_cancels_pending_prompt`).

---

## File Structure

```
govaios/auth.py            Create: screen_locked, prove, approve (channel interface), dialog
govaios/runstate.py        Create: STOPPED, guard.pid, runs/ bookkeeping; emergency_stop, resume
govaios/guard.py           Create: hotkey registration and run loop (gov-aios guard)
govaios/sandbox.py         Create: sandbox_init profiles, apply()
govaios/executor.py        Create: executor policy load/default/approve, categories, protected paths
govaios/redact.py          Create: redact_command
govaios/hook.py            Create: PreToolUse hook main
govaios/powers.py          Create: review-powers record and freshness check
govaios/policy.py          Modify: add decide_tool
govaios/approvals.py       Modify: locked read-modify-write, revoke_*
govaios/home.py            Modify: frozen home from pwd
govaios/engine.py          Modify: start proof, lock checks, auth on asks, revocation stop, SIGTERM
govaios/desktop/macos.py   Modify: drop ask_admin; lock check in _require_focus; Chrome via open -n
govaios/netguard.py        Modify: shortcut comment -> row 22
govaios/audit/log.py       Modify: KINDS, FIELDS
govaios/audit/web.py       Modify: login, cookie session, Host check, POST /revoke
govaios/cli.py             Modify: preflight, new subcommands, sandbox at entry
packaging/install.sh       Create: sudo install (app, managed settings, LaunchAgent)
packaging/uninstall.sh     Create: reverse of install; never touches data home or audit
packaging/com.govaios.guard.plist  Create: LaunchAgent template
packaging/gov-aios.spec, pyproject.toml, bin/gov-aios, packaging/README.md: Modify
spikes/plan2/              Create (Task 1 only): throwaway probes, kept for reference
tests/test_auth.py, test_runstate.py, test_sandbox.py, test_executor.py, test_redact.py,
tests/test_hook.py, test_powers.py: Create;  test_approvals.py, test_engine_audit.py,
tests/test_audit_web.py, test_cli.py, test_macos.py: Modify
```

---

### Task 1: Spike: confirm every platform fact

Throwaway probes in `spikes/plan2/` (no tests, no production code). Each result becomes a new row in the log (Source `spike`, Basis = what was observed), and any row it contradicts goes back to the architect before the task that depends on it. Probes needing the screen, Touch ID or root are run by the admin; the controller says exactly what to run and what to look for.

**Files:** Create `spikes/plan2/README.md` (one line per probe: command, expected, observed), the probe scripts it lists. Modify the log.

- [ ] **Step 1:** `probe_auth.py` (rows 4, 6): `LAContext` with reason "approve: test run"; record for each of Touch ID present / lid closed with external display / after 5 failed touches: `canEvaluatePolicy` for both policies, which sheet appears, the reason text shown, and what happens if the sheet is left for 60 s then `invalidate()` is called (reply arrives with an error, or never).
- [ ] **Step 2:** `probe_lock.py` (row 8): print `CGSessionCopyCurrentDictionary()` every second for 30 s while the admin locks and unlocks the screen and switches user; confirm the `CGSSessionScreenIsLocked` and `kCGSessionOnConsoleKey` behaviour.
- [ ] **Step 3:** `probe_hotkey.py` (row 10): register `ctrl+option+cmd+.` with `RegisterEventHotKey` via `ctypes` on an accessory-app run loop, from a binary with no Accessibility or Input Monitoring grant; confirm it fires with Chrome frontmost, with Terminal frontmost, and while a password field has focus (secure input). Keep the working `ctypes` code: Task 5 copies it.
- [ ] **Step 4:** `probe_sandbox.py` (row 22): call `sandbox_init` with the run profile from row 22 via `ctypes`, then check: `socket.create_connection(("1.1.1.1", 443))` fails; DNS for `example.com` fails; a Unix socket pair works; `AXIsProcessTrusted`, an AX read of Chrome's window title, `CGEventPostToPid` of a harmless shift key, `NSRunningApplication.activateWithOptions_`, an `osascript` dialog and an `LAContext` prompt all still work. Repeat with the UI profile: an `http.server` on `127.0.0.1:0` serves a request from the browser. Build it as a minimal signed app (copy of the gov-aios spec) so TCC behaves as in production. If `sandbox_init` with a custom profile fails, repeat through `/usr/bin/sandbox-exec -p` (the fallback).
- [ ] **Step 5:** `probe_chrome.py` (row 23): with Chrome running in another profile, `open -n -a "Google Chrome" --args --profile-directory="Profile 2"`; confirm a Profile 2 window opens in the same Chrome (one Chrome process tree, no second dock icon) and it loads a page during a sandboxed probe.
- [ ] **Step 6:** `probe_hook.sh` and a project-level `.claude/settings.local.json` in a scratch directory (rows 13, 14, 27; no root needed): a `PreToolUse` command hook that logs its stdin and timing. Confirm: matcher `*` fires for Bash, Read, an MCP tool and a subagent's tool call; the hook process is not inside Claude Code's sandbox (it can read a path in `sandbox.filesystem.denyRead`); exit 2 blocks; a crash and a timeout block when `onFailure: "block"` is set; Claude's sandboxed Bash can or cannot run `open /Applications/…app` (row 29). Then time 20 runs of `dist/gov-aios.app/Contents/MacOS/gov-aios selftest lines 1 --dev`; median must be under 1 s (row 13).
- [ ] **Step 7:** Check managed-settings key names against the Claude Code settings docs for the installed version (`claude --version`): every key in row 14. Record the exact JSON that Task 8 will emit.
- [ ] **Step 8 (admin):** `sudo ditto dist/gov-aios.app /Applications/gov-aios.app && sudo chown -R root:wheel /Applications/gov-aios.app`, then run its `doctor` through `open -W`. Record whether Accessibility and Screen Recording still read True or need a fresh grant (row 18). Leave it installed for later tasks only if the admin agrees.
- [ ] **Step 9:** Append one log row per probe (rows 38+). If any expectation failed, stop and send it to the architect; continue only after the affected row is updated.
- [ ] **Step 10:** Commit: `git commit -m "Plan 2 spike: confirm platform facts"`.

### Task 2: Leftovers and revocations that stick

Rows 2, 21.

**Files:** Modify `govaios/home.py`, `govaios/approvals.py`, `govaios/engine.py`; Test `tests/test_approvals.py`, `tests/test_engine_audit.py`, new `tests/test_home.py`.

**Interfaces:**
- Produces: `Approvals(path)` with `flow_ok(flow_id, digest) -> bool`, `approve_flow(flow_id, digest)`, `destination_ok(flow_id, org) -> bool`, `approve_destination(flow_id, org)`, `revoke_flow(flow_id)`, `revoke_destination(flow_id, org)`, `revoke_all()`, `snapshot() -> dict` (a fresh read, for the UI). Every read re-reads the file; every write is read-modify-write under `fcntl.flock` on `approvals.lock` beside the file, saved by a temp file in the same directory plus `os.replace`.
- Produces: `Runner.gate` raises `Stop("revoked")` when `flow_ok(self.flow["id"], self.digest)` is false; the `stop` entry carries reason `revoked`.

- [ ] **Step 1: Write the failing tests:**
  - `test_revocation_survives_other_writer`: instances `a` and `b` on one file; `a.approve_flow("f", "h")`, `b.revoke_flow("f")`, `a.approve_destination("f", "https://y")`; then `Approvals(path).flow_ok("f", "h") is False` and `destination_ok("f", "https://y")` is True.
  - `test_revoke_destination_and_all`: after `revoke_destination("f", "https://x")`, `destination_ok` is False and other destinations stay; after `revoke_all()`, `snapshot() == {"flows": {}, "destinations": {}}`.
  - `test_write_is_atomic`: monkeypatch `os.replace` to raise; the previous file content is unchanged and no temp file remains.
  - `test_revoked_flow_stops_at_next_gate` (engine): run the Task-5-of-plan-1 fixture flow with a FakeDesktop whose `click` calls `Approvals(home / "approvals.json").revoke_flow(flow_id)`; the run raises `Stop`, the last audit entry is `stop` with `reason == "revoked"`, and no further `click` is recorded.
  - `test_frozen_home_ignores_HOME` (`tests/test_home.py`): with `sys.frozen = True` and `HOME=/tmp/elsewhere`, `data_home()` is under `pwd.getpwuid(os.getuid()).pw_dir`; monkeypatch `Path.mkdir` so nothing is created.
  - Change `test_flow_parsed_from_hashed_bytes` to patch `read_bytes` instead of `read_text`.
- [ ] **Step 2:** Run `pytest tests/test_approvals.py tests/test_engine_audit.py tests/test_home.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the interfaces above; `data_home()` uses `Path(pwd.getpwuid(os.getuid()).pw_dir)` when frozen.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Approvals: locked writes and revocation; frozen home from pwd"`.

### Task 3: Presence proof module

Rows 4–8, 35.

**Files:** Create `govaios/auth.py`, `tests/test_auth.py`; Modify `govaios/audit/log.py`, `pyproject.toml` (add `pyobjc-framework-LocalAuthentication`), `packaging/gov-aios.spec` (hidden import `LocalAuthentication`).

**Interfaces:**
- Produces:
  - `screen_locked() -> bool`: reads the session through the seam `_cg_session_dict() -> dict | None` (the only place that calls `CGSessionCopyCurrentDictionary()`; tests patch the seam, never Quartz); true if it is missing, `CGSSessionScreenIsLocked` is true, or `kCGSessionOnConsoleKey` is false (key names as confirmed in Task 1).
  - `prove(reason: str, home: Path, channel: str = "touch_id") -> tuple[bool, str]`: no dialog; returns `(ok, auth)`.
  - `approve(question: str, reason: str, home: Path, channel: str = "touch_id") -> tuple[bool, str]`: dialog with the full question, then on Approve a fresh `LAContext` with `reason`.
  - Both: if `screen_locked()` → `(False, "none")` with no prompt; try a non-blocking `flock` on `home / "ask.lock"` for up to 2 s, else return `(False, "none")` with deny reason `busy` and no prompt (row 36); hold it for the whole prompt; one 60 s deadline covers the dialog and the Touch ID reply; any channel other than `touch_id` raises `ValueError`.
  - `dialog(question: str, timeout_s: int) -> bool`: the osascript dialog moved from `MacDesktop.ask_admin` (same text escaping, Deny default, `giving up after`).
  - Module-level seams for tests: `_la_evaluate(reason: str, deadline: float) -> str` returning `biometric`, `device_owner` or `failed`, and `_now()`.
- Produces: audit `KINDS` and `FIELDS` as in Global Constraints.

- [ ] **Step 1: Write the failing tests** (all with `_la_evaluate`, `dialog`, the Quartz session call and `_now` mocked):
  - `test_locked_screen_denies_without_prompt`: session dict says locked; `approve(...) == (False, "none")`; `dialog` and `_la_evaluate` never called. Same for a missing dict and for `kCGSessionOnConsoleKey` false.
  - `test_dialog_deny_skips_touch_id`: dialog returns False → `(False, "none")`; `_la_evaluate` not called.
  - `test_approve_then_biometric`: `(True, "biometric")`; with `device_owner` → `(True, "device_owner")`; with `failed` → `(False, "failed")`.
  - `test_prove_has_no_dialog`: `prove` calls `_la_evaluate` with the given reason and never `dialog`.
  - `test_no_reply_is_deny_after_timeout`: a fake LAContext whose `evaluatePolicy` never calls its reply block; with `_now` advanced past 60 s, `_la_evaluate` returns `failed` and `invalidate` was called.
  - `test_policy_choice`: `canEvaluatePolicy` true for biometrics → biometric policy with `localizedFallbackTitle == ""`; false for biometrics, true for device owner → device-owner policy; both false → `failed` without evaluating.
  - `test_second_prompt_denied_when_busy`: hold `ask.lock` in the test; `approve` returns `(False, "none")` after about 2 s (clock seam), reports reason `busy`, and `dialog` was never called. Release the lock: the next `approve` prompts.
  - `test_unknown_channel_rejected`: `approve(..., channel="phone")` raises `ValueError`.
  - `test_audit_accepts_new_kinds_and_fields`: `AuditLog.append("resume", auth="biometric")` and `append("request", command="git status")` succeed; an unknown field still raises.
- [ ] **Step 2:** Run `pytest tests/test_auth.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement. `_la_evaluate` creates a new `LAContext`, sets `touchIDAuthenticationAllowableReuseDuration = 0`, picks the policy per row 6, calls `evaluatePolicy_localizedReason_reply_`, waits on a `threading.Event` until the deadline, then `invalidate()`s and returns `failed`. Use the exact pattern Task 1 Step 1 confirmed.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Add presence proof (Touch ID channel) and lock check"`.

### Task 4: Engine and adapter use the proof

Rows 5, 9, 28 (start proof), 29.

**Files:** Modify `govaios/engine.py`, `govaios/desktop/macos.py`; Test `tests/test_engine_audit.py`, `tests/test_macos.py`.

**Interfaces:**
- Consumes: `auth.approve`, `auth.prove`, `auth.screen_locked` (Task 3).
- Produces: `Runner.ask(question: str, reason: str) -> tuple[bool, str]` (calls `auth.approve`, then re-activates the app as today). `Runner.run()` start proof: if the flow is approved, `auth.prove(f"run {flow_id}", home)` audited as kind `request`, `action="run_start"`, `approver="admin"`, `channel="touch_id"`, `auth`; denied → `Stop("start not proven")`. If not approved, the flow-approval prompt is the only start proof. Every `ask` entry (`flow_approval`, `request`) records `channel="touch_id"` and `auth`. `MacDesktop.ask_admin` is removed (its dialog lives in `auth.dialog`).
- Produces: before each step `Runner.steps` raises `Stop("screen_locked")` if `auth.screen_locked()`; `MacDesktop._require_focus` raises `RuntimeError("input refused: screen locked")` first.

- [ ] **Step 1: Write the failing tests** (`auth.approve`, `auth.prove` and `auth.screen_locked` monkeypatched in `govaios.engine` / `govaios.auth`; the FakeDesktop loses `ask_admin`):
  - `test_approved_flow_start_needs_proof`: flow pre-approved; `prove` returns `(False, "failed")` → `Stop`, no `launch_application` call; the audit holds `request` `run_start` `decision="deny"`, `auth="failed"`.
  - `test_unapproved_flow_one_prompt`: flow not approved; `approve` returns `(True, "biometric")`; `prove` never called; the `flow_approval` entry has `auth="biometric"`, `channel="touch_id"`.
  - `test_first_contact_records_auth`: the destination ask entry has `auth` and `channel="touch_id"`.
  - `test_lock_mid_run_stops`: `screen_locked` turns True after the first step; the run stops with `reason == "screen_locked"` and no later step's action is recorded.
  - `test_locked_screen_refuses_input` (`test_macos.py`): a locked session makes `press` raise `RuntimeError` matching `screen locked`, with nothing posted.
- [ ] **Step 2:** Run `pytest tests/test_engine_audit.py tests/test_macos.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement the interfaces above. Question texts stay as today; reasons are short: `approve flow <id>`, `<id>: <action> <origin>`.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Engine: Touch ID start proof, authenticated asks, lock stops runs"`.

### Task 5: Guard, emergency stop and resume

Rows 10–12, 29 (`resume` proof), 30.

**Files:** Create `govaios/runstate.py`, `govaios/guard.py`, `tests/test_runstate.py`, `packaging/com.govaios.guard.plist`; Modify `govaios/auth.py` (cancel on stop), `govaios/engine.py` (SIGTERM), `govaios/cli.py` (`guard`, `resume`).

**Interfaces:**
- Produces in `runstate.py` (all take `home: Path`):
  - `is_govaios(pid: int) -> bool`: the process's executable path (`proc_pidpath` via `ctypes`) is `/Applications/gov-aios.app/Contents/MacOS/gov-aios`; seam `_exe_path(pid)` for tests.
  - `guard_alive(home) -> bool`: `guard.pid` exists, the pid is alive and `is_govaios`.
  - `stopped(home) -> bool`; `register_run(home) -> Path` (first removes every `runs/` entry whose pid is not alive or not `is_govaios`, then writes `runs/<os.getpid()>`), `unregister_run(home)`.
  - `emergency_stop(home, audit: AuditLog, kill=os.kill, sleep=time.sleep) -> list[tuple[int, str]]`: writes `STOPPED`, SIGTERMs each live `is_govaios` pid in `runs/`, SIGKILLs any still alive after 3 s, appends kind `emergency_stop` with `outcome` per run (`stopped` or `killed`) and `reason="claude commands already running are not stopped"`; returns the list.
  - `resume(home, audit) -> bool`: `auth.prove("resume gov-aios", home)`; on success removes `STOPPED`; audits kind `resume` with `auth` either way.
- Produces in `guard.py`: `main(home) -> int` registers the hotkey (code from Task 1 Step 3), writes `guard.pid` only after registration succeeds, calls `emergency_stop` on each press; registration failure → message on stderr, exit 1.
- Produces: `auth.approve` / `prove` return `(False, "none")` within 1 s once `runstate.stopped(home)` becomes true while waiting (poll every 0.2 s; kill the osascript child).
- Produces: in `Runner.run`, a SIGTERM handler that raises `Stop("emergency stop")`.
- CLI: `gov-aios guard`, `gov-aios resume`.

- [ ] **Step 1: Write the failing tests** (`_exe_path`, `kill`, `sleep` faked):
  - `test_stop_terms_then_kills`: two run files; pid A dies after SIGTERM, pid B does not; result `[(A, "stopped"), (B, "killed")]`; `STOPPED` exists; one `emergency_stop` entry per run.
  - `test_stop_skips_non_govaios_pid`: a `runs/` pid whose exe is not gov-aios is never signalled (pid reuse).
  - `test_register_run_collects_stale_entries`: `runs/` holds a dead pid and a live non-gov-aios pid; after `register_run` only `runs/<own pid>` remains.
  - `test_reused_guard_pid_is_not_alive`: `guard.pid` names a live pid with another exe → `guard_alive` is False; missing file → False.
  - `test_resume_needs_proof`: `prove` fails → `STOPPED` remains, `resume` entry `auth="failed"`; succeeds → removed.
  - `test_stop_cancels_pending_prompt` (`test_auth.py`): `dialog` blocks until killed; writing `STOPPED` from another thread makes `approve` return `(False, "none")` within 1 s.
  - `test_sigterm_stops_run` (`test_engine_audit.py`): send `SIGTERM` to the test process from a FakeDesktop action; the run's last entry is `stop` with reason `emergency stop`.
  - `test_guard_writes_pid_only_after_registration`: registration seam fails → exit 1, no `guard.pid`.
- [ ] **Step 2:** Run `pytest tests/test_runstate.py tests/test_auth.py tests/test_engine_audit.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement. The LaunchAgent plist runs `/Applications/gov-aios.app/Contents/MacOS/gov-aios guard` with `KeepAlive` and `RunAtLoad`.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Add guard with emergency-stop hotkey, resume, run bookkeeping"`.

### Task 6: OS-level network block; Chrome via LaunchServices

Rows 22, 23.

**Files:** Create `govaios/sandbox.py`, `tests/test_sandbox.py`; Modify `govaios/desktop/macos.py`, `govaios/netguard.py`, `tests/test_macos.py`.

**Interfaces:**
- Produces: `sandbox.RUN_PROFILE`, `sandbox.UI_PROFILE` (strings exactly as row 22, adjusted only by Task 1 findings); `sandbox.apply(profile: str) -> None` calls `sandbox_init` via `ctypes` (flags 0) and raises `RuntimeError("sandbox refused")` on a non-zero return, freeing the error buffer.
- Produces: `MacDesktop.launch_application(app, profile_directory=None)` always uses `subprocess.run(["open", "-n", "-a", "Google Chrome", "--args", f"--profile-directory={profile_directory}"], check=True)` when a profile is given (plain `open -a` otherwise); no direct execution of the Chrome binary remains anywhere.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_profile_blocks_tcp_and_dns` (child process via `subprocess.run([sys.executable, "-c", ...])`): after `sandbox.apply(RUN_PROFILE)`, connecting to a TCP listener the parent opened on `127.0.0.1` fails, `socket.getaddrinfo("localhost", 80)` fails, and a `socket.socketpair()` round trip works. Child prints one result per check; the parent asserts all three.
  - `test_ui_profile_serves_localhost`: child applies `UI_PROFILE`, serves one request on `127.0.0.1:0`; the parent fetches it with `urllib` and gets 200; an outbound connect from the child still fails.
  - `test_bad_profile_raises`: child applies `"(version 1) (bogus)"`; `RuntimeError` named in its output.
  - `test_launch_uses_open_n_when_chrome_running` and `..._when_not_running` (`test_macos.py`): both record exactly `["open", "-n", "-a", "Google Chrome", "--args", "--profile-directory=Profile 2"]`; no `Popen` is recorded. Replace the two plan-1 launch tests.
- [ ] **Step 2:** Run `pytest tests/test_sandbox.py tests/test_macos.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; point netguard's shortcut comment at row 22 (it stays as a second layer).
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "OS-level network block via sandbox_init; Chrome launched by LaunchServices"`.

### Task 7: Claude tool policy, executor policy and redaction

Rows 16, 17, 31, 33.

**Files:** Create `govaios/executor.py`, `govaios/redact.py`, `tests/test_executor.py`, `tests/test_redact.py`; Modify `govaios/policy.py`, `tests/test_policy.py`.

**Interfaces:**
- Produces in `policy.py`: `decide_tool(request: dict, policy: dict, approvals, protected: tuple[str, ...]) -> str` returning `allow`, `deny` or `ask`. Pure: no filesystem access. `request` keys: `tool`, `category` (from `executor.category`), optional `path` (already `realpath`ed), `command`, `url`. Rules in the design §4.4 table, protected paths first, then unlisted tool, then per category. A path is "inside roots" when it equals a root or starts with root + `/`. `external` is always `ask`; `internal` and `delegate` are `allow` when listed.
- Produces in `executor.py`:
  - `CATEGORIES: dict[str, str]`: Read, Glob, Grep, LSP → `read`; Edit, Write, NotebookEdit → `write`; Bash, Monitor → `shell`; WebFetch → `fetch`; WebSearch → `search`; TodoWrite, ToolSearch, AskUserQuestion, EnterPlanMode, ExitPlanMode → `internal`; Agent, Task, Skill → `delegate`. `category(tool: str) -> str | None`: `mcp__*` → `external`; unknown → `None`.
  - `protected_paths(home: Path) -> tuple[str, ...]`: the Global Constraints list, `realpath`ed.
  - `POLICY_PATH = "executors/claude_code.yaml"` (under the data home); `default_policy(root: Path) -> str` (YAML text: `project_roots: [<root>]`, `allow_commands` and `destinations` per row 31, `tools` = every non-external key of `CATEGORIES` except LSP, Monitor, WebSearch).
  - `load(home) -> tuple[dict, str]`: parsed policy and its sha256 of the exact bytes (one read, as `read_bound`).
  - `build_request(tool_name: str, tool_input: dict, home: Path) -> dict`: resolves `file_path`/`path`/`notebook_path` with `os.path.realpath`, copies `command` and `url`, sets `category`.
- Produces in `redact.py`: `redact_command(cmd: str) -> str` per row 17, replacing each secret with `[REDACTED]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_decide_tool` table (parametrized): Read inside root → allow; Read outside → ask; Write outside → deny; Write inside protected (data home) → deny; unlisted tool → deny; `mcp__x__y` listed → ask; listed `TodoWrite` → allow; Bash `git status` → allow; Bash `git status; rm -rf ~` → ask; Bash `rm -rf build` (no listed prefix) → ask; Bash `git statusx` → ask (prefix must end at a word boundary); WebFetch undeclared host → deny; declared, not yet approved → ask; approved → allow; WebSearch not listed → deny.
  - `test_symlink_into_data_home_denied`: a symlink in the project root pointing into the tmp data home; `build_request("Read", {"file_path": link}, home)` then `decide_tool` → deny. Same for `root/../<data home>`.
  - `test_unknown_tool_category_is_none`: `category("NewTool") is None`.
  - `test_default_policy_round_trips`: `default_policy(root)` parses; `project_roots == [str(root)]`; `allow_commands` and `destinations` exactly as row 31.
  - `test_redact` (parametrized, one per row 17 pattern): `curl -H 'Authorization: Bearer abc'`, `mysql -p secret`, `API_KEY=xyz make`, `git clone https://u:pw@host/r`, `echo sk-ant-123456789012345678901234`, `ghp_…`, `github_pat_…`, `AKIA…`, `xoxb-…`, a PEM block; each output contains `[REDACTED]` and none of the secret. `git status` is unchanged.
- [ ] **Step 2:** Run `pytest tests/test_executor.py tests/test_redact.py tests/test_policy.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the interfaces above.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Add Claude tool policy, executor policy file, command redaction"`.

### Task 8: The Claude Code hook and managed settings

Rows 13–15, 31, 32.

**Files:** Create `govaios/hook.py`, `tests/test_hook.py`; Modify `govaios/cli.py`.

**Interfaces:**
- Consumes: `runstate.guard_alive`, `runstate.stopped`, live pids in `runs/` (Task 5); `auth.approve` (Task 3); `executor.load`, `build_request`, `category`, `protected_paths` and `policy.decide_tool` (Task 7); `redact_command`; `Approvals`.
- Produces: `hook.main(stdin: TextIO, stdout: TextIO, stderr: TextIO, home: Path, managed: Path = MANAGED_SETTINGS) -> int`. Exit 2 with one stderr line for: unparsable JSON, `category` None, guard not alive, `STOPPED`, a live run in `runs/`, the executor policy missing or its hash not approved (`Approvals.flow_ok("claude_code", digest)`), managed settings missing or `sandbox.network.allowedDomains` not equal as a set to the policy's `destinations`, or any exception. Otherwise decides; `ask` goes to `auth.approve(question, reason, home)` with the question naming the tool, the target and the redacted command; prints `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"|"deny", "permissionDecisionReason": ...}}`; exit 0. An approved WebFetch first contact calls `approve_destination("claude_code", origin)`. One audit `request` entry per call: `flow="claude_code"`, `flow_hash`, `executor="claude_code"`, `action` = tool, `target`, `command` (redacted), `decision`, `approver`, `channel`, `auth`.
- Produces: `gov-aios hook` (reads stdin) and `gov-aios claude-settings --root DIR`: writes `default_policy(DIR)` to the data home if no policy exists, shows the whole file through `auth.approve`, records `approve_flow("claude_code", digest)`, and prints the managed-settings JSON exactly as recorded in Task 1 Step 7, with `allowedDomains` = the policy's `destinations` and `denyRead` = the data home.

- [ ] **Step 1: Write the failing tests** (fake guard/run state via files plus `is_govaios` seam; `auth.approve` mocked; managed settings written to `tmp_path`):
  - `test_allow_inside_root`: Read inside the root → exit 0, `permissionDecision == "allow"`, one audit `request` entry with `executor == "claude_code"`.
  - `test_ask_resolved_by_govaios`: Bash `make` → `approve` called once; its result maps to allow or deny; output never contains `"ask"`.
  - `test_exit2_cases` (parametrized): bad JSON; unknown tool; no guard; `STOPPED`; live run; policy changed after approval; managed domains `{github.com}` vs policy `{github.com, pypi.org}`, and the reverse. Each: exit 2, one stderr line, nothing on stdout.
  - `test_command_redacted_in_audit`: Bash `API_KEY=xyz make` → the audit entry's `command` holds `[REDACTED]`, not `xyz`.
  - `test_no_content_in_audit`: Write with `content: "SECRET"` and Edit with `new_string: "SECRET"`; `SECRET` appears nowhere in `audit.jsonl`.
  - `test_claude_settings_output` (`test_cli.py`): with `approve` mocked True, the printed JSON has the row 14 keys (as recorded in Task 1) and `allowedDomains` equal to the default destinations; the policy hash is approved; with `approve` False, nothing is printed and exit 1.
- [ ] **Step 2:** Run `pytest tests/test_hook.py tests/test_cli.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the interfaces above.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Add Claude Code PreToolUse hook and managed-settings generator"`.

### Task 9: Audit UI login and revocation

Rows 19–21.

**Files:** Modify `govaios/audit/web.py`, `govaios/cli.py`, `tests/test_audit_web.py`.

**Interfaces:**
- Consumes: `auth.prove`, `auth.screen_locked`; `Approvals.snapshot`, `revoke_flow`, `revoke_destination`, `revoke_all` (Task 2).
- Produces: `make_server(home: Path, port: int = 0, now=time.time) -> tuple[server, code]` (the caller has already proven presence); `gov-aios audit-ui` (already under `UI_PROFILE`, Task 10) calls `auth.prove("open the audit log", home)` first (deny → exit 1, audited `ui_login` with `auth`), and prints `http://127.0.0.1:<port>/login?c=<code>`. `GET /login?c=` with a valid unused code under 60 s old sets cookie `s=<session>; HttpOnly; SameSite=Strict; Path=/` and returns 303 to `/`. All other routes need the cookie. Every request needs `Host == 127.0.0.1:<port>`, else 403. After 1 hour, or when `screen_locked()` is true at a request, the response is 403 and the server shuts down. `POST /revoke` with form fields `csrf`, `kind` (`flow`, `destination`, `all`), `flow`, `destination`; needs the session's CSRF token (and the Host check above); an `Origin` header, when present, must equal `http://127.0.0.1:<port>`, but its absence is not a rejection (row 37); then 303 to `/approvals`; audited kind `revoke` with `flow`, `destination`, or `reason="all"`. Any other POST → 405. Plan-1 headers stay.

- [ ] **Step 1: Write the failing tests** (replace the plan-1 token tests):
  - `test_login_code_single_use_and_expiry`: first `/login?c=` → 303 with the cookie flags above; second use → 403; a fresh server with `now` advanced 61 s → 403.
  - `test_pages_need_cookie`: `/`, `/log`, `/approvals` without the cookie → 403; with it → 200; `?t=` is no longer accepted.
  - `test_host_header_checked`: `Host: evil.example` with a valid cookie → 403.
  - `test_session_expires_and_lock_ends_server`: `now` + 3601 s → 403; `screen_locked` True → 403 and `server.shutdown` called.
  - `test_revoke_flow`: valid POST → 303, `Approvals.flow_ok` false, one `revoke` entry.
  - `test_revoke_rejects_bad_csrf_or_origin`: wrong token, missing token, `Origin: http://evil` each → 403 and nothing changes; a valid token with no `Origin` header → 303 (row 37).
  - `test_revoke_all`: empties both lists; entry has `reason == "all"`.
  - `test_values_still_escaped`: a flow id containing `<script>` renders escaped on the Approvals page, including in the hidden form field.
- [ ] **Step 2:** Run `pytest tests/test_audit_web.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement; no JavaScript, inline CSS, as plan 1.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Audit UI: Touch ID login, cookie session, revocation"`.

### Task 10: Run preflight, powers review, doctor, dump proof, --dev

Rows 24, 25, 28, 29.

**Files:** Create `govaios/powers.py`, `tests/test_powers.py`; Modify `govaios/cli.py`, `govaios/identity.py`, `tests/test_cli.py`.

**Interfaces:**
- Produces in `powers.py`: `review(home, kept: list[str], audit) -> bool` (opens the three panes with `open x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility` / `?Privacy_ListenEvent` / `?Privacy_ScreenCapture`, then `auth.approve` with the row 24 statement and the kept names; on success writes `powers_review.json` `{"ts": <UTC ISO>, "kept": [...]}`; audits `powers_review` with `auth`); `fresh(home, now=None) -> bool` (file exists, parses, under 30 days old).
- Produces in `cli.py`: `preflight(home: Path, dev: bool) -> None` raising `SystemExit` with a one-line reason, checks in row 28's order (the sandbox, row 28's first item, is already applied at entry, below): `runstate.guard_alive`, not `runstate.stopped`, not `auth.screen_locked()`, `powers.fresh`. `_run` calls `preflight`, `register_run`, then `Runner.run()` (which does the proof, Task 4), and `unregister_run` in `finally`. `--dev` refuses unless `GOVAIOS_HOME` is set and resolves to a path other than the frozen default data home. `dump` calls `preflight` and `auth.prove("read the current Chrome page", home)` before reading. New subcommand `review-powers KEPT...`. `doctor` adds `guard`, `managed_settings` (present and owned by uid 0), `powers_review` (date or `missing`), `screen_locked`, and exits 1 if any fails.
- `main()` applies the sandbox once, right after argument parsing and before any other work: `UI_PROFILE` for `audit-ui`, nothing for `doctor`, `RUN_PROFILE` for every other subcommand (row 22). A refusal exits 1 before anything runs. In tests `sandbox.apply` is monkeypatched; `test_sandbox_applied_per_subcommand` asserts the profile chosen for `run`, `hook`, `audit-ui` and `doctor`.

- [ ] **Step 1: Write the failing tests:**
  - `test_preflight_order`: with every check failing, the error names the guard; fix that and it names `STOPPED`; then locked; then powers review.
  - `test_run_registers_and_unregisters`: `runs/<pid>` exists during `Runner.run` (FakeRunner) and is gone after, including when it raises.
  - `test_dev_requires_tmp_home`: `run --dev` with `GOVAIOS_HOME` unset → exit 1; set to the real default → exit 1.
  - `test_dump_needs_proof`: `prove` False → exit 1 and no `web_root` call.
  - `test_powers_fresh`: missing → False; 29 days → True; 31 days → False; corrupt JSON → False.
  - `test_review_records_kept_apps`: `approve` True → file written, audit `powers_review`; False → nothing written.
  - `test_doctor_reports_new_checks`: output has `guard:`, `managed_settings:`, `powers_review:`, `screen_locked:` lines; a non-root-owned managed settings file → exit 1.
- [ ] **Step 2:** Run `pytest tests/test_cli.py tests/test_powers.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the interfaces above.
- [ ] **Step 4:** Run `pytest -W error`. Expected: all pass.
- [ ] **Step 5:** Commit: `git commit -m "Run preflight, powers review, doctor checks, proof for dump"`.

### Task 11: Install, recovery docs, attended end-to-end

Rows 18, 26, 34.

**Files:** Create `packaging/install.sh`, `packaging/uninstall.sh`; Modify `bin/gov-aios` (use `/Applications/gov-aios.app`; if absent, exit 1 with "not installed: run packaging/install.sh"), `packaging/README.md`.

- [ ] **Step 1:** `install.sh` (refuses unless run as root via sudo, and `dist/gov-aios.app` passes `codesign --verify --strict`): `ditto` the app to `/Applications/gov-aios.app`, `chown -R root:wheel`; write the managed settings from `gov-aios claude-settings` output given as a file argument (root:wheel 0644); install the LaunchAgent plist for `$SUDO_USER`; never run `gov-aios` as root, and create nothing in the data home; if the data home exists, `find <data home> -user 0 -exec chown -h "$SUDO_USER" {} +` hands back any root-owned file there (only those: a blanket `chown -R` would hit the `UF_APPEND` audit log needlessly), and the script ends by asserting no root-owned file remains; and `launchctl bootstrap gui/<uid>`; print the System Settings steps (grant Accessibility and Screen Recording to `/Applications/gov-aios.app`). Optional `--no-claude` skips the managed settings so the app and guard can be installed and checked before Claude Code is governed. `uninstall.sh`: `launchctl bootout`, remove the plist, the managed settings and the app; never the data home or audit.
- [ ] **Step 2:** `packaging/README.md` adds: install and uninstall; rebuild flow (build, then `sudo packaging/install.sh --no-claude` again; re-grant if Task 1 Step 8 showed it is needed); recovery: guard not running (`launchctl kickstart -k gui/$UID/com.govaios.guard`), after an emergency stop (`gov-aios resume`), hook locking Claude Code out (`sudo rm "/Library/Application Support/ClaudeCode/managed-settings.json"`).
- [ ] **Step 3:** Run `bash -n packaging/install.sh packaging/uninstall.sh && GOVAIOS_SIGN_ID="GOV-AIOS Dev" packaging/build.sh && pytest -W error`. Expected: no syntax errors; build OK; all pass. Commit: `git commit -m "Install/uninstall scripts and recovery docs"`.
- [ ] **Step 4 (admin):** `sudo packaging/install.sh --no-claude`; grant Accessibility and Screen Recording to the installed app; `bin/gov-aios review-powers <kept apps>` (dialog + Touch ID); `bin/gov-aios doctor`. Expected: every line OK except `managed_settings`.
- [ ] **Step 5 (admin attended):** `bin/gov-aios run flows/himalayas_job_vetting.yaml`. Expected: exactly one prompt, Touch ID only (the run-start proof; the flow is already approved); the run completes; then a second run where the admin presses `ctrl+option+cmd+.` mid-run: the run stops, `emergency_stop` and `stop` entries are written, a third run refuses with `STOPPED`, `gov-aios resume` (Touch ID) clears it. Lock the screen during a fourth run: it stops with `screen_locked`. `bin/gov-aios audit-ui`: Touch ID, login link works once, revoke the flow, a fifth run asks for flow approval again. `bin/gov-aios verify-audit`: OK.
- [ ] **Step 6:** Ledger the results, then hand over: the next step governs this Claude session, so the controller stops here (row 34).
- [ ] **Step 7 (admin, new Claude Code session afterwards):** `bin/gov-aios claude-settings --root <repo> > /tmp/ms.json` (review the policy, Touch ID), `sudo packaging/install.sh /tmp/ms.json`, start a new Claude Code session in the repo and check: `git status` runs without a prompt; `cat ~/Library/Application\ Support/GOV-AIOS/audit.jsonl` is denied; a Bash `make` shows the GOV-AIOS dialog + Touch ID; a Write outside the repo is denied; pressing the hotkey makes the next tool call fail; `gov-aios resume` restores it; the audit UI shows `claude_code` entries with redacted commands. If the hook locks the session out, use the recovery step from `packaging/README.md`.
