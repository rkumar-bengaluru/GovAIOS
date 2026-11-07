# Windows, dev mode: governance first, then the morning brief — design

Date: 2026-11-07. Branch: `feat/windows-dev`. Builds on `2026-11-05-governance-layer-design.md` (goal 7: "OS-neutral design: macOS first, Windows behind the same interfaces") and `2026-11-05-admin-auth-isolation-design.md`.

## 1. Intent

GOV-AIOS has only ever run on macOS. The admin wants it to run on Windows too, **without breaking the Mac**. The core idea is the governance layer (presence proof, emergency stop, audit, refusals), so that comes to Windows first; the first real flow on top of it is the **morning inbox briefing** (`flows/morning_inbox_briefing.yaml`), in dev mode.

## 2. Goals, non-goals, anti-goals

Goals
- `govaios` imports and its unit tests run on Windows.
- The governance layer works on Windows in dev mode: stop hotkey guard, recorded emergency stop, resume, approval dialog + Windows Hello, screen-lock refusal, powers review, signed audit log with file locking.
- `gov-aios-dev run flows/morning_inbox_briefing.yaml --dev` on Windows: Chrome, the flow's profile, account check, Gmail, top 5 messages, printed sender/subject report, every step governed exactly as on Mac.
- A Windows `dump --dev` (read-only page tree print), needed to capture and check page schemas.

Non-goals (this cycle)
- OS-level network lockdown on Windows (AppContainer / firewall). The in-process block (`netguard`) is the only network layer for now (admin decision).
- The packaged/signed Windows app, an installer, auto-start of the guard at logon.
- The Claude Code executor (hook, managed settings), the panel / audit-ui, delivery, JobLens, the Himalayas flow, TTS. They must still **import** on Windows (the engine imports delivery); they need not work.
- Private-file ACL hardening beyond what the user profile already gives (see 5.4).

Anti-goals (a failure even if it works)
- **Any change in Mac behaviour.** Same calls, same strings, same refusals, same audit entries, same test results. Mac code paths are moved behind the OS layer, not rewritten.
- A Windows path that is less strict than Mac in a way that is not labeled. Every relaxation is dev-only and printed (`DEV MODE: insecure, not for real use`, plus the Windows-specific notice in 5.5).
- An emergency stop that ends a run without a `stop` audit entry (the naive Windows port does exactly this: `os.kill(pid, SIGTERM)` is TerminateProcess).
- A prompt (dialog or Hello) left on screen after a stop, cancel or timeout.

## 3. Admin decisions (as said)

- "make this windows compatible, so far it has been tested in mac os"
- "do in a way it does not break in mac"
- Workflow: "you make changes to a branch once done you will ask me to test that branch in mac with the commands you want me to execute. if that works i will ask you to merge."
- "start with morning email brief example in dev mode"
- "let the governance layer work first, that is the core idea then the brief"
- "in-process block is fine for now, lockdown later"
- Windows Hello: the admin was not sure it is set up on this PC; agreed approach: Hello with a PIN (Settings → Accounts → Sign-in options); no Hello means deny, as on Mac.
- Hello prompt that cannot be closed by code after a stop: accepted as a labeled dev-mode gap, not a blocker (proposed, not objected to).
- "for email brief during setup in control panel we will setup the profile to choose" — later; for now "local copy is fine, panel later".

## 4. Constraints

- **Mac is verified by the admin on a real Mac** before each merge (section 7). Claude works on Windows and cannot run Mac tests itself, so every stage ends with a Mac check request.
- Python **3.14** (`requires-python >=3.14` stays). This Windows machine has up to 3.13; 3.14 is installed here for development (admin agreed at the start of the work). If a Windows library (pywinrt, comtypes) has no 3.14 build, the builder calls the OS API through ctypes / COM interop instead and says so in the stage report (my call).
- pyobjc dependencies become `; sys_platform == "darwin"`. Windows-only dependencies get `; sys_platform == "win32"`. Mac installs resolve to exactly today's set.
- Windows-only modules are imported only on `win32`, Mac-only modules only on `darwin`, the same way `desktop/__init__.py:get_desktop` already does.
- No new network use anywhere. Windows Hello and UIA are local OS APIs.
- Everything on Windows is dev for now (there is no packaged Windows app): every Windows command requires `GOVAIOS_HOME` set to a directory outside the would-be real data home (5.5).

## 5. Design

### 5.1 OS layer

A small per-OS layer (builder picks the shape; e.g. `govaios/osapi/{__init__,posix,windows}.py`) that holds the primitives today called directly:

| Primitive | Mac (unchanged behaviour) | Windows |
|---|---|---|
| exclusive file lock (blocking and non-blocking) | `fcntl.flock` | `LockFileEx` at fixed offset 0, truly blocking; `LOCKFILE_FAIL_IMMEDIATELY` failure raised as `BlockingIOError` (not `msvcrt.locking`: R4) |
| directory fsync after creating files | `os.open(dir, O_RDONLY)` + `fsync` | no-op (R5) |
| user home from the account database | `pwd.getpwuid(os.getuid()).pw_dir` | profile folder from the shell API (`SHGetKnownFolderPath`), not `%USERPROFILE%` |
| user display name (panel settings) | `pw_gecos` | `GetUserNameExW` display name, falling back to the user name |
| default data home | `~/Library/Application Support/GOV-AIOS` | `%LOCALAPPDATA%\GOV-AIOS` (Known Folder) |
| append-only guard on the audit log | `chflags UF_APPEND`, re-armed after each append | 5.4 |
| executable path of a pid | `proc_pidpath` (libproc) | `QueryFullProcessImageNameW` |
| "this pid is ours" | exe == `/Applications/gov-aios.app/...` | 5.5 |
| open flags `O_NOFOLLOW`, `O_NONBLOCK` | as today | not available: open without them, then refuse if the path is a reparse point (`lstat`, `FILE_ATTRIBUTE_REPARSE_POINT`) or not a regular file |
| terminate / force-kill a pid | `SIGTERM` then `SIGKILL` | 5.2 stop channel, then `TerminateProcess` |

`runstate.py` must stop loading `libproc.dylib` at import time on non-Mac (today it does so at module load, which breaks every import on Windows). Same for top-level `fcntl`/`pwd`/`Quartz`/`LocalAuthentication` imports in `approvals`, `auth`, `audit/log`, `delivery`, `executor`, `home`, `identity`, `panel/settings`.

### 5.2 Emergency stop on Windows

Same contract as Mac (rows 10-12, 28, 30): the press writes `STOPPED` first, every live run ends as a **recorded** stop, a run still alive after `KILL_AFTER_S` (3 s) is force-killed, the press is always audited, `resume` needs a presence proof.

- **Guard:** `gov-aios-dev guard` (started by hand in a terminal in dev; no auto-start this cycle). Registers the global hotkey with `RegisterHotKey` (user32, `MOD_NOREPEAT`); a second guard fails to register and exits 1, as on Mac. Message loop wakes at least every 0.2 s (e.g. `MsgWaitForMultipleObjects`) so Ctrl-C / close end it cleanly and `guard.pid` is removed.
- **Hotkey (my call):** ctrl+alt+win+period. If Windows refuses that combo, the builder picks the nearest free one (e.g. ctrl+alt+shift+period), and the doc/README states the Windows combo.
- **Telling a run to stop:** Windows cannot deliver SIGTERM to a Python handler, so the run watches for the stop itself. Requirement: a run notices a new stop within 1 s, even while sleeping or waiting for a page, and raises `runstate.Stop("emergency stop")` through the same path the Mac SIGTERM handler uses, so the `stop` entry and cleanup are identical. Mechanism: see R2 (the earlier "within 1 s even while sleeping" needs an interruptible sleep on Windows). Blocking OS calls in the run (UIA, Hello, the dialog) must stay cancellable as they are on Mac (`auth` already polls `runstate.stopped` every 0.2 s).
- **Force kill:** after the grace period, `TerminateProcess` on a pid that is still ours.

### 5.3 Presence proof on Windows (`auth`)

Same contract as Mac: anything but an explicit success is a deny, never raised; one prompt at a time (`ask.lock`, `busy`); 60 s deadline; a stop that starts while a prompt waits cancels it within 0.2 s; prompts never left on screen. `auth` values stay `biometric | device_owner | failed | none | busy`.

- **Dialog:** a native Windows message box with Deny (default) and Approve, auto-deny on timeout, title "GOV-AIOS approval", full question text. It must be killable on cancel/deadline/exception, as the Mac `osascript` child is (builder's choice: a child process, or a dialog thread closed by handle).
- **Windows Hello:** `UserConsentVerifier` (WinRT). Hello does not say which factor was used, so Windows always reports `device_owner` (R10). Unavailable / not set up → `failed`. Known risk: from a console process the Hello prompt can open behind other windows; the builder makes it come to the front (the WinRT interop that takes a window handle) or documents the limitation.
- **Hello not set up:** `failed`, so the approval is a deny (no password prompt, no plain-dialog fallback: admin agreed). `doctor` on Windows reports whether Hello is available.
- **Known dev gap (admin accepted):** if Windows offers no reliable way to close a pending Hello prompt on stop / cancel / deadline, the prompt may stay on screen. The run still ends as a recorded stop and any later answer to that prompt is discarded as a deny. This is printed (`DEV: a Windows Hello prompt may stay open after a stop; its answer is ignored`) and listed in section 10. This relaxes anti-goal 4 for Hello only; the dialog must still close.
- **Screen locked:** fail closed (any error → locked), from the session's lock state (`WTSQuerySessionInformation` / `WTSSessionInfoEx`) and whether the session is on the console.
- **Channel name** stays `touch_id` in audit entries and code (it is the presence channel id, not a claim about hardware); my call, to keep audit format identical across OSes.

### 5.4 Audit log and private files on Windows

- Same hash chain, ECDSA signature, key file, `audit.lock` serialisation; locking via 5.1.
- **Append-only (my call):** Windows has no user append-only flag. After each append, set the file's ACL so the owner has append but not overwrite/truncate/delete (deny `FILE_WRITE_DATA`, `DELETE`; allow `FILE_APPEND_DATA`), re-armed after each append like Mac. Same strength as Mac's user-clearable `UF_APPEND`: an accident guard; tamper evidence is the signature chain. If the builder finds this makes the log unwritable for the next append, the fallback is: skip the guard on Windows, print it in `doctor`, and add it to the lockdown stage.
- `mkdir(mode=0o700)` and `0o600` files: on Windows these bits do nothing. In dev the data home is under the user's profile (private by default ACL). Explicit ACL hardening is deferred to the lockdown stage (my call).
- The test fixture that clears file flags (`tests/conftest.py`) must clear the Windows equivalent instead, so tmp dirs can be removed.

### 5.5 Identity and dev mode on Windows

- `identity.check()` on Windows: `bundle_id` None, `frozen` False, `accessibility` True (no per-app UIA permission exists), `screen_recording` True (none exists). So `require_app` always takes the dev path on Windows: `--dev` required for `run`, `dump`; `GOVAIOS_HOME` required and outside `%LOCALAPPDATA%\GOV-AIOS`.
- **Every Windows command** (including `guard`, `resume`, `review-powers`, `verify-audit`, `doctor`) refuses without such a `GOVAIOS_HOME` (my call: nothing on Windows touches a real data home until a packaged app exists).
- **"Ours" in Windows dev:** a pid is ours if its executable image is the same Python interpreter image as the current process (from `QueryFullProcessImageNameW` of our own pid, not `sys.executable`: a venv `python.exe` on Windows is a launcher that starts the base interpreter). Weaker than Mac (any script on that interpreter passes); acceptable only because it is dev, the pid files live in the private dev home, and it is labeled.
- **Network:** `sandbox.apply` on Windows does not apply anything; it prints once `DEV: no OS network lockdown on Windows; in-process block only` and returns. `netguard.block_all_network()` is the only layer; it must work on Windows (Windows Python has no `socket.AF_UNIX` attribute today, so the allowlist must not reference it there — on Windows nothing is allowed).
- **Powers review (my call):** no Settings panes are opened (Windows has no per-app list for these powers). The statement becomes an honest dev notice (R10): "DEV on Windows: any program running as you can drive this desktop; I accept this for development", approved with the dialog + Hello, recorded and expiring after 30 days exactly as on Mac.
- `doctor` runs on Windows and reports the same keys; Windows-only lines (no OS lockdown, dev only) are added, Mac lines unchanged.

### 5.6 Windows desktop adapter (`desktop/windows.py`)

Implements the same interface as `MacDesktop` (`launch_application`, `activate`, `focused_window_id`, `pin_window`, `window_title`, `current_url`, `web_root`, `click`, `press`, `type_text`, `scroll_into_view`, `_app`) using the `windows:` column of `roles.yaml`: UI Automation for perception, `SendInput` for real input. Library choice (comtypes + UIAutomationCore, or a thin wrapper) is the builder's.

Safety checks keep their Mac meaning:
- Input only when Chrome's verified window is the foreground window (`GetForegroundWindow` + owning pid), checked before every click and every key/character.
- Click point check: the element under the point (`ElementFromPoint`) is the target or inside it, in the pinned window; else `InputRefused` with the same fixed texts.
- Keys: Mac posts to the target pid; Windows `SendInput` goes to the foreground window, so the foreground check immediately before each `SendInput` is the guard. Residual race acknowledged in a code comment.
- Text: `KEYEVENTF_UNICODE`, per character, fixed pace `PACE`.
- Launch: as Mac, Chrome must already be running; the profile is handed over via `chrome.exe --profile-directory=<dir>` (exe found in the standard install locations), never a fresh browser of ours.
- Web tree: Chrome builds its UIA web tree when a UIA client asks; the adapter waits for it like Mac waits for `AXWebArea`. If it doesn't appear, that is the first thing the spike (stage C) must show.
- `dom_id` from `AutomationId`; `dom_class` from Chrome's UIA exposure if present. Unmapped roles become `native:<ControlType>`, as on Mac.

### 5.7 The flow file on Windows

`flows/morning_inbox_briefing.yaml` is shared and unchanged. On Windows, dev runs use a **local copy in the dev data home** in the seeded apps layout `%GOVAIOS_HOME%\apps\flows\morning_inbox_briefing.yaml` with the repo's pages copied to `%GOVAIOS_HOME%\apps\pages\` (the engine looks for `pages/` next to the flow's folder: R1) with this PC's Chrome `profile_directory` and `account`; it is approved on Windows like any flow (its own hash). The admin edits that copy by hand for now. Choosing the profile during setup in the control panel is a later stage (section 10).

### 5.8 Page schemas

`pages/google_home.yaml`, `google_sign_in.yaml`, `gmail_inbox.yaml`, `gmail_message.yaml` are shared by both OSes and must keep matching on Mac. Order of preference when Windows trees differ:
1. normalise in the Windows adapter (map to the same neutral role/name the Mac produces);
2. widen the schema so both match (e.g. `gmail_message.body`'s `dom_class: a3s` if Chrome on Windows doesn't expose classes);
3. never a per-OS fork of a page file without asking the admin.
Any schema change is verified on Mac with a real run of the morning brief (section 7).

## 6. Stages (one branch, Mac check after each)

- **A. Importable, Mac unchanged.** OS layer, conditional imports and dependencies, Windows unit tests, Mac-only tests marked to skip on Windows. Done when: full suite passes on Mac unchanged; Windows suite passes with Mac-only tests skipped.
- **B. Governance on Windows.** 5.2-5.5. Done when, on Windows: `guard` registers the hotkey; `review-powers` shows the dialog + Hello and records; the hotkey writes STOPPED and audits; a test run (fake desktop) is stopped as a recorded stop within 1 s and force-killed if it ignores it; `resume` needs Hello; `verify-audit` passes; screen lock refuses.
- **C. Spike, then adapter.** First a throwaway `dump --dev` of Chrome on google.com, Gmail inbox and a message, compared against the page files; findings reported to the admin before the adapter is finished. Then 5.6-5.7.
- **D. Morning brief.** The full flow (local copy, 5.7), dev mode, on Windows, from approval to report, plus a hotkey stop mid-run.

## 7. Mac verification (admin, on the Mac, after each stage)

Claude sends the exact commands per stage. Baseline set:

```
git fetch && git checkout feat/windows-dev && git pull
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q                       # all of main's tests pass, plus the new ones (R18)
packaging/build.sh && sudo packaging/install.sh --no-claude   # stages A, B
bin/gov-aios doctor
bin/gov-aios run flows/morning_inbox_briefing.yaml            # stages C, D (and any page-file change)
```

Merge only after the admin says so.

**Windows hands-on check (admin, on this PC, end of stages B and D).** Claude cannot press the hotkey, pass Hello or lock the screen, so Claude sends a short Windows script per stage (start guard, review powers, press hotkey, resume, lock test, and for D the brief run) and the admin sends back the output. Before stage B the admin confirms a Windows Hello PIN is set up.

## 8. Architect review amendments (2026-11-07, binding; they override earlier text where it conflicts)

- **R1 Flow copy layout.** Local copy lives in `GOVAIOS_HOME\apps\flows`, pages in `GOVAIOS_HOME\apps\pages` (as `packaging/seed-apps.sh` lays out). Each stage check confirms the copied pages equal the repo's.
- **R2 Stop latency.** Windows-only: in the run process, install an interruptible sleep (wait on a stop event with timeout) without changing engine call sites (tests patch `engine.time.sleep`, `macos.time.sleep`). A watcher thread polls `STOPPED` every ≤0.1 s and fires once, via `_thread.interrupt_main(signal.SIGTERM)` and the sleep's event. If no SIGTERM handler is installed (`SIG_DFL`: preflight, `dump`, `deliver`), it `os._exit(1)`s, matching Mac's default SIGTERM death. Requirement: stop-to-`stop`-entry well under `KILL_AFTER_S`, with a subprocess test measuring it against a sleeping fake desktop. Long single C calls (UIA) are bounded by the force-kill, as on Mac.
- **R3 Mac code stays put.** Mac code keeps its modules, names and bodies. Windows dispatch is an early `if sys.platform == "win32"` branch or late rebinding; Mac lines get import guards only. Tests' monkeypatch targets (`auth.LA`, `auth._cg_session_dict`, `auth.subprocess.Popen`, `runstate._exe_path`, `executor.pwd.getpwuid`, `macos.*` …) keep working unchanged. Review gate: `git diff main -- govaios` shows no edits inside Mac function bodies beyond import guards and dispatch.
- **R4 Locks.** As in the 5.1 table. A busy non-blocking lock is `BlockingIOError` so `auth` returns `busy`, never raises.
- **R5 Audit on Windows.** Directory fsync is a no-op. Append-only: ACL set once at creation, appends through an OS-layer append-only open (`CreateFileW` with `FILE_APPEND_DATA` only); deny-delete must also cover the parent's delete-child right. If any of this fails in the first try (including `FlushFileBuffers` on that handle), take the fallback: no guard on Windows, shown in `doctor`.
- **R6 Dev-home check.** Windows-only check: create the dir, `realpath`, `normcase`, `commonpath` against the real home. `policy._inside` is unchanged (the Mac hook uses it).
- **R7 "Ours" and guard liveness.** Run files store the process creation time; signalling/termination opens one handle, verifies image + creation time, and terminates on that handle. Guard liveness on Windows is a named mutex (per home) held by the guard, plus a console-close handler. `STOPPED` is authoritative; any named event is only an accelerator.
- **R8 Windows emergency_stop.** A separate Windows function (no `os.kill`, no `SIGKILL`), chosen by the guard; the Mac function and its tests are untouched.
- **R9 No asyncio for WinRT.** netguard blocks asyncio's socketpair on Windows. Hello uses a completion handler + `threading.Event`. Test: `prove` works after `block_all_network()`.
- **R10 Labeled presence relaxations (dev).** Printed and in section 9: any same-user process (including an AI agent on the PC) can press Approve in the dialog (Hello is still required after it); Hello PIN is always accepted; a lingering Hello prompt can coexist with a new one; powers review is a dev notice. Hello's message names the flow id / action, so a prompt can't be borrowed for something else.
- **R11 Dialog.** TaskDialog (Deny/Approve buttons) in a child process inside a Job object with kill-on-close, so it dies with the run.
- **R12 current_url.** From the Chrome Document element's Value (the real URL), refused unless http(s); not the address bar text. `roles.yaml` windows column updated.
- **R13 Input.** Per-monitor-v2 DPI awareness declared at adapter start. Bringing Chrome to the front uses a stated mechanism; failure is `InputRefused`.
- **R14 Encoding.** Windows runs use UTF-8 mode (`PYTHONUTF8=1` / `-X utf8`); documented in the Windows run commands.
- **R15 Line endings.** `.gitattributes` with `eol=lf` for `flows/`, `pages/`, `*.sh`, `bin/*` (and `*.py`, `*.yaml`), since this PC has `core.autocrlf=true` and a CRLF would change approval hashes on Mac.
- **R16 Hello spike first.** Stage B starts with a throwaway Hello spike from a console on 3.14 (wheels, front, cancel, after netguard). The UIA spike stays at the start of C (admin's order: governance first). If the Hello spike forces ctypes-only WinRT, the estimate is reported before building.
- **R17 Fake-desktop stop test** is a test harness, not a production CLI flag.
- **R18 Mac check wording.** All of main's tests pass, plus the new ones; Mac-relevant test files change only by skip markers.
- **R19 PyInstaller.** Windows-only imports stay inside functions in `osapi/windows.py` / `desktop/windows.py`, and both are excluded in `gov-aios.spec`, so the Mac bundle is unchanged.
- **R20 Data-home rule.** "Every Windows command needs a dev `GOVAIOS_HOME`" is enforced once in `cli.main` before `args.fn`.

## 9. Left to the builder

- Shape and naming of the OS layer; library choices for UIA, WinRT and dialogs.
- The stop channel mechanism, within 5.2's requirements.
- How Windows tests fake WinRT/UIA, mirroring how Mac tests fake pyobjc.
- Windows entries in README / packaging README for dev setup.

## 10. Later stages (not this cycle)

Choosing the Chrome profile and account during app setup in the control panel (replaces the hand-edited local flow copy); closing a pending Windows Hello prompt on stop, if a way is found; OS-level network lockdown (AppContainer or install-time firewall rules); packaged, signed Windows app and installer (Program Files, Task Scheduler guard, ACL-hardened data home); Claude Code executor on Windows (managed settings path, Windows path rules, case-insensitive matching); panel; delivery; Himalayas flow.
