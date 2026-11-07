# Windows dev mode, stages A+B (importable, governance) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GOV-AIOS imports and tests green on Windows, and its governance layer (guard hotkey, recorded emergency stop, resume, dialog + Windows Hello, screen-lock refusal, powers review, audit) works there in dev mode, with macOS behaviour unchanged.

**Architecture:** Mac code stays in its modules under its names (R3). A new Windows-only package `govaios/win/` holds ctypes/WinRT primitives; existing modules get import guards and an early `if WIN:` dispatch to it. Stages C (UIA spike, Windows desktop adapter) and D (morning brief) get their own plan after the UIA spike, because the adapter's details depend on what Chrome's UIA tree shows.

**Tech Stack:** Python 3.14, ctypes (kernel32, user32, advapi32, wtsapi32, comctl32, shell32, secur32), WinRT for Windows Hello (library fixed by the Task 5 spike), pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-windows-dev-governance-design.md` (section 8, R1-R20, overrides earlier text).

## Global Constraints

- macOS behaviour must not change: same calls, strings, refusals, audit entries; all of main's tests pass on Mac, plus the new ones (R18).
- Mac code keeps its modules, names and bodies; only import guards and early Windows dispatch are added (R3). Monkeypatch targets used by tests (`auth.LA`, `auth._cg_session_dict`, `auth.subprocess.Popen`, `auth.threading.Event`, `runstate._exe_path`, `executor.pwd.getpwuid`, `macos.*`, `engine.time.sleep`) keep working.
- `WIN = sys.platform == "win32"` is the only platform test in new code; Mac branches are `darwin`/else exactly as today.
- `requires-python = ">=3.14"` stays. pyobjc deps get `; sys_platform == "darwin"`; Windows deps get `; sys_platform == "win32"`.
- Windows-only imports (`ctypes.windll`, WinRT) happen inside functions in `govaios/win/*`; `govaios/win` is excluded from the Mac PyInstaller bundle (R19).
- No new network use. Windows Hello must not use asyncio (R9).
- Every Windows command needs `GOVAIOS_HOME` set outside `%LOCALAPPDATA%\GOV-AIOS` (R20), message verbatim: `--dev needs GOVAIOS_HOME set to a directory outside the real data home`.
- Windows requires UTF-8 mode (R14). Refusal verbatim: `refused: on Windows run with PYTHONUTF8=1 (UTF-8 mode)`.
- Fixed Windows texts, verbatim:
  - sandbox: `DEV: no OS network lockdown on Windows; in-process block only`
  - relaxations (R10), printed by `doctor` and once before any prompt: `DEV on Windows: any program running as you can press Approve; a Windows Hello PIN is accepted; a Hello prompt may stay open after a stop (its answer is ignored)`
  - powers review statement: `DEV on Windows: any program running as you can drive this desktop; I accept this for development`
- Windows `auth` results: `device_owner` (Hello verified), `failed`, `none`, `busy`. Never `biometric`. Audit `channel` stays `touch_id`.
- Audit log on Windows: no append-only guard this cycle (R5 fallback); `doctor` prints `audit_append_only: False`.
- Line endings: flows/pages/sh/py/yaml committed LF (R15).
- Windows tests that start a Python child: a venv `python.exe` on Windows is a launcher that starts the base interpreter as its own child, so `Popen.pid` is not the interpreter's pid. Children print `os.getpid()` and tests use that pid; `tests/winutil.py` (created in Task 6) provides `spawn_py(code) -> (Popen, pid)` and `kill_tree(popen, pid)` (terminates the interpreter pid, then the launcher).

## Review Focus

1. Stop pressed while a run waits in the dialog or Hello prompt: the run ends as a recorded stop, the dialog child is gone, the proof is a deny (Task 8 test `test_win_stop_during_dialog_kills_child`).
2. A stale `runs/<pid>` whose pid now belongs to another Python process: never terminated or signalled (Task 6 test `test_win_stop_skips_reused_pid`).
3. `GOVAIOS_HOME` spelled to land inside the real home (other case, forward slashes, trailing separator, `..`): refused (Task 9 test `test_win_dev_home_refuses_real_home_variants`).
4. Non-ASCII text (Gmail subjects, Hello reason with a flow id) through report files and stdout: no `UnicodeEncodeError` (Task 9 test `test_win_requires_utf8_mode` plus the R14 refusal).
5. Windows Hello not set up or unavailable: `prove` returns `(False, "failed")`, never raises (Task 8 test `test_win_hello_unavailable_is_failed`).

---

## Stage A: importable, Mac unchanged

### Task 1: Windows dev environment, dependency markers, line endings

**Files:**
- Modify: `pyproject.toml`
- Create: `.gitattributes`

- [ ] **Step 1:** Install Python 3.14 on Windows (`winget install Python.Python.3.14`, or the python.org installer if winget lacks it). Verify: `py -3.14 --version` prints `Python 3.14.x`.
- [ ] **Step 2:** Add `; sys_platform == "darwin"` to the four `pyobjc-framework-*` dependencies in `pyproject.toml`. Nothing else changes in the file.
- [ ] **Step 3:** Create `.gitattributes`:
```
flows/** text eol=lf
pages/** text eol=lf
*.py text eol=lf
*.yaml text eol=lf
*.sh text eol=lf
bin/* text eol=lf
```
- [ ] **Step 4:** `git add --renormalize .` then `git status`. Expected: no file content changes (the repo is already LF); if any file shows as modified, stop and report it.
- [ ] **Step 5:** `py -3.14 -m venv .venv` then `.venv\Scripts\python -m pip install -e ".[dev]"`. Expected: installs without pyobjc.
- [ ] **Step 6:** Commit `build: platform markers for pyobjc, LF line endings`.

### Task 2: `govaios/win/files.py`: locks, no-follow open, user folders

**Files:**
- Create: `govaios/win/__init__.py` (empty docstring: "Windows-only primitives (ctypes). Import only on win32.")
- Create: `govaios/win/files.py`
- Modify: `packaging/gov-aios.spec` (add `excludes=["govaios.win", "govaios.desktop.windows"]` to `Analysis`)
- Test: `tests/test_win_files.py` (`pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")`)

**Interfaces:**
- Produces:
  - `flock_ex(f, blocking: bool = True) -> None`: `LockFileEx` exclusive on bytes 0..1 at offset 0 of `f` (file object or fd), whatever the file position. Blocking waits forever; non-blocking raises `BlockingIOError` when held.
  - `funlock(f) -> None`: `UnlockFileEx` on the same range; no error if not locked.
  - `open_nofollow(path, flags: int, mode: int = 0o600) -> int`: `os.open(path, flags | os.O_BINARY, mode)`, then refuses (closes, raises `OSError(errno.ELOOP, ...)`) if `os.lstat(path)` has `FILE_ATTRIBUTE_REPARSE_POINT` or the opened fd is not a regular file.
  - `user_home() -> Path`: `SHGetKnownFolderPath(FOLDERID_Profile)`.
  - `local_appdata() -> Path`: `SHGetKnownFolderPath(FOLDERID_LocalAppData)`.
  - `display_name() -> str`: `GetUserNameExW(NameDisplay)`, falling back to `GetUserNameW`, then `"Admin"`.

- [ ] **Step 1: Write failing tests**
```python
def test_flock_nonblocking_busy_from_other_process(tmp_path):
    # child holds the lock (subprocess running flock_ex then sleeping 2 s, prints "held")
    ...  # wait for "held"
    with open(tmp_path / "x.lock", "a") as f:
        with pytest.raises(BlockingIOError):
            files.flock_ex(f, blocking=False)

def test_flock_ignores_file_position(tmp_path):
    p = tmp_path / "x.lock"; p.write_text("abc")
    with open(p, "a") as a, open(p, "a") as b:   # "a" positions at EOF
        files.flock_ex(a)
        with pytest.raises(BlockingIOError):
            files.flock_ex(b, blocking=False)
        files.funlock(a)
        files.flock_ex(b, blocking=False)

def test_open_nofollow_refuses_junction(tmp_path):
    target = tmp_path / "real"; target.mkdir()
    link = tmp_path / "link"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    with pytest.raises(OSError):
        files.open_nofollow(link, os.O_RDONLY)

def test_user_folders():
    assert files.user_home().is_dir()
    assert files.local_appdata().is_dir()
    assert files.display_name()
```
- [ ] **Step 2:** `.venv\Scripts\pytest tests/test_win_files.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `govaios/win/files.py` with ctypes (`ctypes.WinDLL("kernel32", use_last_error=True)` inside each function; handle from `msvcrt.get_osfhandle`).
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5:** Commit `feat(win): file locks, no-follow open, user folders`.

### Task 3: every module imports on Windows; Windows data home

**Files:**
- Modify: `govaios/approvals.py`, `govaios/delivery.py`, `govaios/audit/log.py`, `govaios/executor.py`, `govaios/home.py`, `govaios/identity.py`, `govaios/panel/settings.py`, `govaios/runstate.py`, `govaios/auth.py`, `govaios/netguard.py`, `govaios/sandbox.py`, `govaios/cli.py`
- Test: `tests/test_win_imports.py` (Windows only)

**Interfaces:**
- Consumes: Task 2 `flock_ex`, `funlock`, `user_home`, `local_appdata`, `display_name`.
- Produces: on Windows, `home.data_home()` default is `local_appdata() / "GOV-AIOS"`; `GOVAIOS_HOME` still overrides. `audit.log.AuditLog.append` works on Windows without `chflags` and without directory fsync.

Rules for every edit (R3): `import fcntl` / `import pwd` / pyobjc imports move under `if not WIN:` (or `if sys.platform == "darwin":` for pyobjc) with the same module-level names on Mac; a Windows branch replaces the single line that uses them (`fcntl.flock(lock, fcntl.LOCK_EX)` → `if WIN: winfiles.flock_ex(lock) else: fcntl.flock(...)`). Specifically:
- `runstate.py`: the `_libproc` load and `argtypes` lines go under `if not WIN:`; `_exe_path` on Windows returns `None` until Task 6.
- `audit/log.py`: lock as above; the directory-fsync block in `_key` runs only `if not WIN`; the `st_flags`/`chflags` re-arm runs only `if not WIN`.
- `auth.py`: `LocalAuthentication`/`Quartz` imported only on darwin (names `LA`, `Quartz` set to `None` on Windows). Behaviour on Windows comes in Task 8.
- `netguard.py`: on Windows nothing is allowed: `if family != getattr(socket, "AF_UNIX", object()): raise PermissionError(_BLOCKED)` (Mac evaluates exactly as before).
- `sandbox.py`: `apply()` on Windows prints the sandbox notice to stderr once per process and returns.
- `cli.py`: `_write_shim_file` returns at once on Windows (no shim on Windows).

- [ ] **Step 1: Write failing tests**
```python
MODULES = ["govaios.cli", "govaios.engine", "govaios.auth", "govaios.guard", "govaios.hook", "govaios.powers",
           "govaios.runstate", "govaios.delivery", "govaios.audit.log", "govaios.audit.web", "govaios.panel.settings"]

@pytest.mark.parametrize("m", MODULES)
def test_imports_on_windows(m):
    importlib.import_module(m)

def test_default_data_home_is_localappdata(monkeypatch):
    monkeypatch.delenv("GOVAIOS_HOME")
    monkeypatch.setattr(files, "local_appdata", lambda: tmp_path)
    assert home.data_home() == tmp_path / "GOV-AIOS"

def test_audit_append_and_verify_on_windows(tmp_path):
    log = AuditLog(tmp_path)
    log.append("resume", decision="allow")
    log.append("resume", decision="deny")
    assert verify_main([str(log.path), str(log.pub_path)]) == 0

def test_netguard_blocks_everything_on_windows():   # in a subprocess: block_all_network is one-way
    out = subprocess.run([sys.executable, "-c", "from govaios.netguard import block_all_network as b; b();"
                          "import socket\ntry: socket.socket()\nexcept PermissionError: print('blocked')"],
                         capture_output=True, text=True)
    assert out.stdout.strip() == "blocked"

def test_sandbox_apply_is_notice_on_windows(capsys):
    sandbox_real.apply(sandbox_real.RUN_PROFILE)   # conftest patches apply; import the real function first
    assert "DEV: no OS network lockdown on Windows; in-process block only" in capsys.readouterr().err
```
- [ ] **Step 2:** Run. Expected: FAIL (`ModuleNotFoundError: fcntl` / `pwd`).
- [ ] **Step 3:** Make the edits above.
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5:** Commit `feat(win): govaios imports on Windows; Windows data home`.

### Task 4: test suite runs on Windows

**Files:**
- Modify: `tests/conftest.py`
- Modify (skip markers only): Mac-behaviour tests in mixed test files, as found

- [ ] **Step 1:** In `conftest.py`: guard the `os.chflags` loop with `if hasattr(os, "chflags")`; on Windows set `collect_ignore = [...]` for modules that are Mac-only by nature (initially `test_auth.py`, `test_macos.py`, `test_identity.py`, `test_packaging.py`, `test_shim.py`, `test_sandbox.py`, `test_panel_helper.py`, `test_panel_launch.py`, `test_home.py`); add `pytest_report_header` that prints `Windows: Mac-only test modules not collected: <list>`.
- [ ] **Step 2:** `.venv\Scripts\pytest -q`. For each failure decide: Mac-only behaviour (chflags, `UF_APPEND`, `/usr/bin`, fork, `SIGKILL`, pyobjc fakes) → `@pytest.mark.skipif(sys.platform == "win32", reason="macOS: <what>")`; a portable-code bug on Windows → fix in the Windows branch of the module, never in the Mac branch.
- [ ] **Step 3:** Rerun until `.venv\Scripts\pytest -q` passes. Record the pass/skip counts.
- [ ] **Step 4:** R3 gate: `git diff main -- govaios` and check every hunk is an import guard, a Windows branch, or a Windows-only module. List any other hunk in the checkpoint message.
- [ ] **Step 5:** Commit `test: run the suite on Windows; Mac-only tests skipped there`.

### Checkpoint A (admin, Mac)

- [ ] Push `feat/windows-dev` (ask the admin before the first push).
- [ ] Send the admin, verbatim:
```
git fetch && git checkout feat/windows-dev && git pull
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
git diff main --stat -- tests
packaging/build.sh && sudo packaging/install.sh --no-claude
bin/gov-aios doctor
```
Expected on Mac: all of main's tests pass plus the new Windows-only tests skipped; test files changed only by skip markers and conftest; `doctor` output identical to before. Wait for the output; fix on the branch and repeat if anything differs. Continue only after the admin confirms.

---

## Stage B: governance on Windows

### Task 5: Spike: Windows Hello and TaskDialog from a console (throwaway)

**Files:**
- Create: `spikes/windows-hello/probe_hello.py`, `spikes/windows-hello/probe_dialog.py`, `spikes/windows-hello/README.md`

- [ ] **Step 1:** `probe_hello.py`: on 3.14, install a WinRT binding (`winrt-runtime`, `winrt-Windows.Security.Credentials.UI`; record whether 3.14 wheels exist). Check availability, request verification with message `GOV-AIOS spike: run morning_inbox_briefing`, using a completion handler + `threading.Event` (no asyncio), after `block_all_network()`. Record: works?, comes to the front from a console? (try the interop `RequestVerificationForWindowAsync` with the console window handle), what `cancel()` on the operation does to the on-screen prompt, result codes when not set up.
- [ ] **Step 2:** `probe_dialog.py`: TaskDialogIndirect with buttons Deny (default) / Approve, title `GOV-AIOS approval`, auto-Deny after N s via `TDN_TIMER`, run in a child process inside a Job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. comctl32 v6 needs an activation context (manifest via `CreateActCtxW`); record whether it works. If it can't, record tkinter (Deny/Approve, topmost, `after()` timeout) as the fallback.
- [ ] **Step 3:** Ask the admin to run both probes on this PC (Hello PIN set up first) and paste the output. Write findings into `README.md`: chosen Hello library (or "ctypes/COM interop needed" plus an estimate), front-window method, cancel behaviour, chosen dialog method.
- [ ] **Step 4: STOP POINT.** If WinRT needs ctypes-only interop, or Hello can't be shown at all, report to the admin before Task 8. Otherwise commit `spike(win): Hello and dialog findings` and continue.

### Task 6: process identity, run files, guard mutex, Windows emergency stop

**Files:**
- Create: `govaios/win/proc.py`, `tests/winutil.py`
- Modify: `govaios/runstate.py`
- Test: `tests/test_win_runstate.py` (Windows only)

**Interfaces:**
- Produces (`govaios/win/proc.py`):
  - `image_path(pid: int) -> str | None` (`QueryFullProcessImageNameW`), `start_time(pid: int) -> int | None` (`GetProcessTimes` creation FILETIME), `own_image() -> str`.
  - `is_ours(pid: int, start: int) -> bool`: image == `own_image()` (case-insensitive) and creation time == `start`.
  - `terminate_if_ours(pid: int, start: int) -> bool`: one handle opened with `PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION`, verify image + start on it, `TerminateProcess(h, 1)`; True only if terminated.
  - `hold_guard_mutex(home: Path) -> int | None`: `CreateMutexW` named `Local\GOVAIOS-guard-` + first 16 hex of `sha256(normcase(realpath(home)))`; None if it already existed.
  - `guard_mutex_held(home: Path) -> bool`: `OpenMutexW(SYNCHRONIZE)` succeeds.
- Produces (`runstate.py`, Windows branches only): `register_run` writes `str(start_time(os.getpid()))` into `runs/<pid>`; `live_runs` returns pids whose file's start time passes `is_ours`; `guard_alive(home)` = `guard_mutex_held(home)`; new `emergency_stop_win(home, audit, sleep=time.sleep) -> list[tuple[int, str]]`: same order and audit entries as `emergency_stop` (STOPPED first; poll every 0.1 s up to `KILL_AFTER_S` for runs to exit; `terminate_if_ours` the rest → `"killed"`, others `"stopped"`; remove handled entries; never self; the press always audited with `STOP_REASON`).

- [ ] **Step 1: Write failing tests**
```python
def test_is_ours_matches_child_python():
    p, pid = spawn_py("import os, time; print(os.getpid(), flush=True); time.sleep(30)")
    try:
        assert proc.is_ours(pid, proc.start_time(pid))
        assert not proc.is_ours(pid, proc.start_time(pid) + 1)
    finally:
        kill_tree(p, pid)

def test_win_stop_skips_reused_pid(home):     # Review Focus 2
    p, pid = spawn_py("import os, time; print(os.getpid(), flush=True); time.sleep(30)")
    (home / "runs").mkdir(parents=True)
    (home / "runs" / str(pid)).write_text("12345")       # stale start time: not ours
    try:
        out = runstate.emergency_stop_win(home, FakeAudit(), sleep=lambda s: None)
        assert out == [] and proc.start_time(pid) is not None   # still alive, never terminated
    finally:
        kill_tree(p, pid)

def test_win_stop_kills_run_that_ignores_stop(home):
    # child registers itself via runstate.register_run(home) and sleeps without a watcher
    ...
    out = runstate.emergency_stop_win(home, audit)
    assert out == [(child_pid, "killed")]
    assert (home / "STOPPED").exists()
    assert [e["kind"] for e in audit.entries] == ["emergency_stop"]

def test_guard_mutex_single_holder(home):
    h = proc.hold_guard_mutex(home)
    assert h is not None and proc.hold_guard_mutex(home) is None   # second holder refused (other process in real use)
    assert runstate.guard_alive(home)
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `win/proc.py` and the runstate Windows branches. Mac `emergency_stop` and its tests are untouched.
- [ ] **Step 4:** Rerun. Expected: PASS. Run the whole suite. Expected: PASS.
- [ ] **Step 5:** Commit `feat(win): process identity, run files, guard mutex, emergency stop`.

### Task 7: stop watcher and interruptible sleep in run processes (R2, R17)

**Files:**
- Create: `govaios/win/stopwatch.py`
- Modify: `govaios/cli.py` (`_run`, `_dump`, `_deliver`: `if WIN: stopwatch.install(home)` right after `register_run(home)`)
- Create: `tests/win_stop_harness.py` (test helper, not a test module)
- Test: `tests/test_win_stopwatch.py` (Windows only)

**Interfaces:**
- Produces: `install(home: Path, poll_s: float = 0.1) -> None`: replaces `time.sleep` in this process with a sleep that returns early when the stop event is set; starts a daemon thread polling `(home / "STOPPED").exists()` every `poll_s`. On first sight (fires once): set the event; if `signal.getsignal(signal.SIGTERM)` is `signal.SIG_DFL` (or None), `os._exit(1)`; else `_thread.interrupt_main(signal.SIGTERM)`, so the engine's existing SIGTERM handler raises `Stop("emergency stop")`. Idempotent.

- [ ] **Step 1: Write failing tests**
```python
def test_stop_is_recorded_quickly_while_sleeping(tmp_path):      # R2, R17
    # harness: Runner on a one-step approved flow, FakeDesktop whose snapshot sleeps 30 s,
    # engine.auth.prove/approve/screen_locked patched, register_run + stopwatch.install, prints "running"
    p = subprocess.Popen([sys.executable, "-X", "utf8", HARNESS, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    word, pid = p.stdout.readline().split()       # harness prints "running <os.getpid()>"
    assert word == "running"
    t0 = time.monotonic()
    out = runstate.emergency_stop_win(tmp_path, AuditLog(tmp_path))
    assert out == [(int(pid), "stopped")]
    assert time.monotonic() - t0 < 1.5
    kinds = [json.loads(l)["kind"] for l in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert "stop" in kinds and kinds[-1] == "emergency_stop"

def test_no_handler_exits_like_default_sigterm(tmp_path):
    # child: register_run, install(), no SIGTERM handler, sleeps 30 s
    ...
    assert out == [(child_pid, "stopped")] and child.wait(5) == 1   # child_pid printed by the child
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `stopwatch.py` and wire it in `cli.py`.
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5:** Commit `feat(win): stop watcher ends runs as a recorded stop`.

### Task 8: presence proof on Windows: screen lock, dialog, Hello

**Files:**
- Create: `govaios/win/session.py`, `govaios/win/dialog.py`, `govaios/win/taskdialog_child.py`, `govaios/win/hello.py`
- Modify: `govaios/auth.py`, `pyproject.toml` (Windows deps from the Task 5 spike, with `; sys_platform == "win32"`)
- Test: `tests/test_win_auth.py` (Windows only)

**Interfaces:**
- Consumes: Task 2 `flock_ex(blocking=False)`, `open_nofollow`.
- Produces:
  - `session.screen_locked() -> bool`: `WTSQuerySessionInformationW(WTSSessionInfoEx)`, locked unless `SessionFlags == WTS_SESSIONSTATE_UNLOCK (1)`, and the session must be `WTSGetActiveConsoleSessionId()`; any error → True.
  - `dialog.ask(question: str, timeout_s: int, cancelled) -> bool`: runs `taskdialog_child` (method per spike) as a child in a kill-on-close Job; question passed on stdin as JSON; child prints `approve` or `deny`. Polls every `auth.POLL_S`; on cancel / deadline / exception the child is killed. True only for `approve`.
  - `hello.verify(reason: str, deadline: float, cancelled) -> str`: `"device_owner"` on verified, else `"failed"`; unavailable → `"failed"`; cancel/deadline → cancels the operation, returns `"failed"`; no asyncio.
  - `auth.py` Windows dispatch, first line of each function: `screen_locked` → `session.screen_locked()`; `dialog` → `dialog.ask(...)`; `_la_prompt` → `hello.verify(...)` (so `_la_evaluate`'s never-raise wrapper still applies); in `_gate` the lock open uses `open_nofollow` and the try-lock uses `flock_ex(lock, blocking=False)` on Windows. `_gate` prints the R10 relaxation line to stderr once per process before the first prompt.

- [ ] **Step 1: Write failing tests**
```python
def test_screen_locked_fails_closed(monkeypatch):
    monkeypatch.setattr(session, "_query_flags", lambda: (_ for _ in ()).throw(OSError()))
    assert session.screen_locked() is True

def test_win_hello_unavailable_is_failed(monkeypatch, home):      # Review Focus 5
    monkeypatch.setattr(hello, "_available", lambda: False)
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    assert auth.prove("resume gov-aios", home) == (False, "failed")

def test_win_proof_is_device_owner(monkeypatch, home):
    monkeypatch.setattr(hello, "_request", lambda reason, done: done(True))
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    assert auth.prove("run morning_inbox_briefing", home) == (True, "device_owner")

def test_win_busy_when_lock_held(home, monkeypatch):     # second prompt: busy, never raises
    ...  # hold ask.lock with flock_ex in a child process
    assert auth.prove("x", home) == (False, "busy")

def test_win_stop_during_dialog_kills_child(home, monkeypatch):   # Review Focus 1
    monkeypatch.setattr(dialog, "CHILD", [sys.executable, "-c", "import time; time.sleep(60)"])
    monkeypatch.setattr(auth, "screen_locked", lambda: False)
    threading.Timer(0.5, lambda: (home / "STOPPED").touch()).start()
    assert auth.approve("Approve?", "approve flow x", home) == (False, "none")
    assert dialog.last_child.poll() is not None

def test_hello_works_after_netguard():   # R9, subprocess: block_all_network then hello._request with a fake op
    ...
    assert out.stdout.strip() == "device_owner"
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement the four modules and the `auth.py` dispatch; add the spike's Windows deps to `pyproject.toml`.
- [ ] **Step 4:** Rerun, then the whole suite. Expected: PASS.
- [ ] **Step 5:** Manual (admin, this PC): `$env:PYTHONUTF8=1; $env:GOVAIOS_HOME="C:\govaios-dev"; .venv\Scripts\python -c "from govaios import auth; print(auth.approve('Spike: approve?', 'test approve', __import__('pathlib').Path(r'C:\govaios-dev')))"`. Expected: dialog, then Hello; `(True, 'device_owner')` on Approve + PIN, `(False, 'none')` on Deny.
- [ ] **Step 6:** Commit `feat(win): presence proof with dialog and Windows Hello`.

### Task 9: guard hotkey, CLI rules, identity, powers review, doctor

**Files:**
- Create: `govaios/win/hotkey.py`, `govaios/win/devhome.py`
- Modify: `govaios/guard.py`, `govaios/cli.py`, `govaios/identity.py`, `govaios/powers.py`
- Test: `tests/test_win_guard_cli.py` (Windows only)

**Interfaces:**
- Consumes: Task 6 `hold_guard_mutex`, `emergency_stop_win`; Task 2 `local_appdata`.
- Produces:
  - `hotkey.MODS = MOD_CONTROL | MOD_ALT | MOD_WIN | MOD_NOREPEAT` (0x2 | 0x1 | 0x8 | 0x4000), `hotkey.VK = VK_OEM_PERIOD` (0xBE); `register() -> int` (0 or `GetLastError`); `run(on_press, should_quit, tick_s=0.2) -> None` (`MsgWaitForMultipleObjects` with `tick_s` timeout, drain `WM_HOTKEY`, return when `should_quit()`).
  - `guard.main(home)` on Windows → `_win_main(home)`: mutex first (none → print `gov-aios guard: another guard is running` to stderr, return 1), register hotkey (fail → existing message with `ctrl+alt+win+.`, return 1), write `guard.pid`, `SetConsoleCtrlHandler` + SIGINT end the loop, each press runs `emergency_stop_win`, `guard.pid` removed on exit.
  - `devhome.require_dev_home() -> Path`: `GOVAIOS_HOME` set; create it; `normcase(realpath())` of it and of `local_appdata()/"GOV-AIOS"`; refuse if equal or `commonpath` is the real home; message per Global Constraints.
  - `cli.main` on Windows, after parsing and before the sandbox: refuse without UTF-8 mode (`sys.flags.utf8_mode`), then `devhome.require_dev_home()`, both with exit 1 and `_write_exit`.
  - `identity.check()` on Windows: `{"bundle_id": None, "frozen": False, "accessibility": True, "screen_recording": True}`; `_require_dev_home` on Windows calls `devhome.require_dev_home()`.
  - `powers.review` on Windows: opens no panes; statement is the Windows text from Global Constraints.
  - `_doctor` on Windows adds lines `os_network_lockdown: False`, `audit_append_only: False`, `hello_available: <bool>`, and prints the R10 line.

- [ ] **Step 1: Write failing tests**
```python
@pytest.mark.parametrize("spell", [r"{real}\x", r"{REAL}\x", "{real_fwd}/x", r"{real}\sub\..\x", "{real}\\"])
def test_win_dev_home_refuses_real_home_variants(monkeypatch, tmp_path, spell):   # Review Focus 3
    real = tmp_path / "LocalApp" / "GOV-AIOS"; real.mkdir(parents=True)
    monkeypatch.setattr(files, "local_appdata", lambda: tmp_path / "LocalApp")
    monkeypatch.setenv("GOVAIOS_HOME", spell.format(real=real, REAL=str(real).upper(), real_fwd=str(real).replace("\\", "/")))
    with pytest.raises(SystemExit, match="outside the real data home"):
        devhome.require_dev_home()

def test_win_requires_utf8_mode(tmp_path):        # Review Focus 4
    env = {**os.environ, "GOVAIOS_HOME": str(tmp_path), "PYTHONUTF8": "0"}
    r = subprocess.run([sys.executable, "-m", "govaios.cli", "verify-audit"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "refused: on Windows run with PYTHONUTF8=1 (UTF-8 mode)" in r.stderr

def test_win_guard_second_instance_exits_1(tmp_path):
    # start guard A in a subprocess (UTF-8, GOVAIOS_HOME=tmp_path); wait for guard.pid; start guard B
    assert b.returncode == 1 and "another guard is running" in b.stderr

def test_win_guard_ctrl_c_removes_pid(tmp_path):
    # guard in a subprocess with CREATE_NEW_PROCESS_GROUP; send CTRL_BREAK_EVENT; exit within 2 s; guard.pid gone
    ...

def test_win_powers_statement(monkeypatch, home):
    asked = []
    monkeypatch.setattr(powers.auth, "approve", lambda q, r, h: (asked.append(q), (True, "device_owner"))[1])
    assert powers.review(home, [], AuditLog(home))
    assert asked[0].startswith("DEV on Windows: any program running as you can drive this desktop; I accept this for development")
```
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun, then the whole suite. Expected: PASS.
- [ ] **Step 5:** Manual (admin): start `gov-aios-dev guard`. If it fails with the hotkey message while no other guard runs, change `hotkey.MODS` to `MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT` and update the message to `ctrl+alt+shift+.`; rerun tests.
- [ ] **Step 6:** Commit `feat(win): guard hotkey, dev-home and UTF-8 rules, identity, powers review, doctor`.

### Task 10: Windows dev guide and Checkpoint B

**Files:**
- Create: `docs/windows-dev.md` (setup: Python 3.14, venv, `PYTHONUTF8=1`, `GOVAIOS_HOME`, Hello PIN; commands; the R10 relaxations and dev gaps listed verbatim)

- [ ] **Step 1:** Write `docs/windows-dev.md`. Commit `docs: Windows dev setup and governance check`.
- [ ] **Step 2:** Send the admin the Windows check (this PC), verbatim:
```
$env:PYTHONUTF8=1; $env:GOVAIOS_HOME="C:\govaios-dev"
.venv\Scripts\pytest -q
.venv\Scripts\gov-aios-dev guard          # leave running in its own window
.venv\Scripts\gov-aios-dev review-powers  # dialog + Hello, expect "powers review recorded"
.venv\Scripts\gov-aios-dev doctor
# press ctrl+alt+win+.   then:
.venv\Scripts\gov-aios-dev resume         # Hello, expect exit 0
# lock the screen (Win+L), unlock, then:
.venv\Scripts\gov-aios-dev verify-audit
```
Expected: tests pass; the review records; doctor shows the dev lines; the press adds an `emergency_stop` entry and STOPPED; resume clears it; `verify-audit` exits 0.
- [ ] **Step 3:** Run the R3 gate again (`git diff main -- govaios`) and send the Checkpoint A Mac commands plus `bin/gov-aios review-powers`, `bin/gov-aios resume` after a hotkey press on the Mac. Wait for both outputs. Merge only when the admin says so.
- [ ] **Step 4:** Next: write the stage C/D plan (UIA spike, Windows desktop adapter, morning brief with the local flow copy in `GOVAIOS_HOME\apps\`, R1, R12, R13).
