# GOV-AIOS Plan 2: Admin Authentication and Isolation — Design

Date: 2026-11-05 · Status: for admin approval · Builds on
`docs/superpowers/specs/2026-11-05-governance-layer-design.md` (the
**spec**) and the merged governance foundation (plan 1, PR #4).

Every decision here is logged, with its reasons and rejected options, in
`docs/superpowers/decisions/2026-11-05-admin-auth-isolation.md` (the
**log**; "row N" below). The admin delegated those decisions to an
architect agent (row 1) and can overturn any of them. Items marked
**[spike]** rest on platform behaviour not yet seen on this Mac; the
plan's first task confirms them (row 27).

------------------------------------------------------------------------

## 1. Intent

Plan 1 made GOV-AIOS's own runner governed: a signed app identity, approved
flows bound to their content, a signed audit, and input that refuses to go
anywhere but the verified window. Two gaps remain, and they are exactly
the spec's top two threats (spec §3):

1. **Anyone at the laptop can approve.** Today an approval is a click on a
   dialog. A stolen or unattended unlocked laptop, or a process that can
   click, can run flows and approve actions.
2. **AI agents are not governed.** Claude Code acts on the laptop through
   its own tools with nothing between it and the OS but its own permission
   prompts.

Plan 2 closes both: **every decision that grants power needs proof the
admin is present (Touch ID), and Claude Code can act only through
GOV-AIOS's policy engine, inside a sandbox it cannot loosen.** It also
replaces the two plan-1 shortcuts that were explicitly deferred here:
the in-process network guard (foundation row 4) and the audit UI's URL
token (foundation row 5).

Principles (spec §1) and how plan 2 serves them:

| Principle | In plan 2 |
| :--- | :--- |
| No harm | Deny by default for Claude's tools; OS-level network block during runs; locked screen means stop |
| Privacy first | Claude cannot read the GOV-AIOS data home; audit records commands and paths, never contents; secrets redacted |
| Human in control | Touch ID on every grant; one-key emergency stop that always works; revocation in the UI |
| Transparency | The full question is shown before Touch ID; every approval records how it was proven (`auth`) |

## 2. Goals, non-goals, anti-goals

**Goals**

1. Starting a flow, approving any `ask`, opening the audit UI, `dump`,
   resuming after an emergency stop, the powers review, and approving the
   executor policy each require a fresh Touch ID (or device-owner) proof.
   Nothing is cached (rows 4–6, 29).
2. Nothing runs or is approved while the screen is locked; a lock mid-run
   stops the run (rows 8–9).
3. `ctrl+option+cmd+.` stops every run, cancels pending approval prompts,
   and denies every later Claude tool call, at any time, with no
   permission grant needed. It does not kill Claude commands already
   running; the audit says so (rows 10–12, 30).
4. Every Claude Code tool call is decided by GOV-AIOS's policy engine, and
   the hook, the sandbox and the policy cannot be removed or loosened by
   the agent (rows 13–18).
5. Runs have no network at the OS level; Chrome, launched by
   LaunchServices, still reaches the flow's destinations (rows 22–23).
6. The audit UI needs Touch ID to open and lets the admin revoke approved
   flows and destinations; revocations stick and stop a running flow at
   its next step (rows 19–21).
7. `run` refuses unless the admin has reviewed who else holds
   Accessibility, Input Monitoring and Screen Recording in the last 30
   days (row 24).

**Non-goals (plan 2)** (row 3): phone and voice channels (so no remote
stop and no voice session); Secure Enclave audit key; Developer ID and
notarisation; bootstrap and guided enrolment (plan 4); the drafter's
sandbox (plan 4); a separate macOS user per executor; Windows; executors
other than Claude Code; blocking Claude Code's own API traffic during a
run (needs root; v1 denies all Claude tool calls during a run instead,
row 25).

**Anti-goals: failure even if it technically works**

- An approval the admin could not read in full before proving presence.
- A hook, sandbox or policy the governed agent can edit, disable or route
  around (including by rebuilding the binary the hook runs).
- An emergency stop that can silently fail, or a revocation that a
  running flow silently undoes.
- Claude's permission prompt standing in for GOV-AIOS's decision: GOV-AIOS
  never returns `ask` to Claude Code (row 15).
- File contents, edit strings, fetch prompts or secrets in the audit.

## 3. Architecture

``` text
                     root-owned                                 data home (0700)
  ┌────────────────────────────────────────────┐   ┌───────────────────────────────┐
  │ /Applications/gov-aios.app  (row 18)       │   │ audit.jsonl (+flock)          │
  │   gov-aios run / dump / audit-ui / …  ─────┼──▶│ approvals.json (+flock, r.21) │
  │   gov-aios hook   ◀── Claude Code PreToolUse│──▶│ executors/claude_code.yaml    │
  │   gov-aios guard  ◀── LaunchAgent (hotkey) ─┼──▶│ STOPPED, runs/<pid>, guard.pid│
  │ /Library/Application Support/ClaudeCode/   │   │ powers_review, ask.lock       │
  │   managed-settings.json  (row 14)          │   └───────────────────────────────┘
  └────────────────────────────────────────────┘
```

- **Process model (row 13).** Still one app process per CLI call through
  the shim. The only resident process is the **guard**. The **hook** is
  the installed app binary, executed directly by Claude Code for each tool
  call; it decides in-process and needs no OS powers. Processes share
  state only through files in the data home, under locks. No socket and no
  IPC protocol, unless the hook-latency spike fails (fallback in row 13).
- **Install (rows 18, 26).** `packaging/install.sh`, run by the admin with
  sudo, copies the app to `/Applications` (root:wheel), writes the managed
  settings, and loads the guard LaunchAgent. It changes no TCC setting; it
  prints the System Settings steps the admin performs. `dist/` becomes
  build output only; the shim, hook and guard use the installed copy.
- **New module `govaios/auth.py`** owns presence proof and the lock check;
  `policy.py` gains a pure `decide_tool()`; the engine, CLI, audit log and
  web UI change as below.

## 4. Components

### 4.1 Presence proof — `govaios/auth.py` (rows 4–7)

- `approve(question, reason) -> (bool, auth)`: if the screen is locked,
  deny with no prompt. Otherwise take `ask.lock` (one approval prompt at a
  time across all processes), show the existing native dialog with the
  full question (Deny default, Approve), and only on Approve run a fresh
  `LAContext` with the short `reason`. Policy: biometrics when available
  (fallback button hidden), else device-owner authentication (password or
  Watch), else deny. 60 s overall; anything but success is deny. **[spike]**
  prompt text, timeout, which policy each hardware case reaches.
- `prove(reason) -> (bool, auth)`: Touch ID only, no dialog, for actions
  the admin started themselves (`run` start of an approved flow,
  `audit-ui`, `resume`, `dump`). **[designer's call]** Row 4's dialog exists so
  the admin reads what they approve; here they typed the command
  themselves, so the reason line is enough.
- Proof per subcommand (row 29): `prove()` for `run`, `audit-ui`,
  `resume`, `dump`; `approve()` for anything GOV-AIOS proposes (asks,
  flow approval, `review-powers`, the executor policy); none for `hook`
  (its asks use `approve()`), `guard`, `doctor`, `verify-audit`,
  `selftest`.
- `auth` values recorded in the audit: `biometric`, `device_owner`,
  `failed`, `none` (a policy decision with no prompt).
- Adds `pyobjc-framework-LocalAuthentication` and its hidden import.

### 4.2 Locked screen (rows 8–9)

`screen_locked()` reads `CGSessionCopyCurrentDictionary()`: locked if
`CGSSessionScreenIsLocked` is true, the session is not on console, or the
dictionary is missing **[spike]**. Checked at `run` start, before each
step, inside `_require_focus` before every synthetic input, and before
every prompt. Locked mid-run → `Stop`, audited with reason
`screen_locked`. No pause/resume.

### 4.3 Emergency stop and guard (rows 10–12)

- `gov-aios guard`, run by `~/Library/LaunchAgents/com.govaios.guard.plist`
  (`KeepAlive`, `RunAtLoad`), registers `ctrl+option+cmd+.` with Carbon
  `RegisterEventHotKey` via `ctypes` on an accessory-app run loop, then
  writes `guard.pid`. Registration failure → exit with an error (and so
  nothing can run). **[spike]** works with no Accessibility/Input
  Monitoring grant, and under secure input.
- On the hotkey: write `STOPPED`; SIGTERM every live pid in `runs/` whose
  executable is the gov-aios app, SIGKILL after 3 s; audit
  `emergency_stop` with `outcome` per run. `run` turns SIGTERM into
  `Stop("emergency stop")` so its own `stop` entry is written.
- While `STOPPED` exists, `run` refuses and the hook denies.
  `gov-aios resume` removes it after Touch ID (audited `resume`).
- `run` and the hook both require a live guard (`guard.pid` alive and the
  gov-aios app). Each `run` writes `runs/<pid>` at start, removes it at
  exit.
- A hook waiting on an approval prompt is cancelled as deny. Claude
  commands already running are not killed (they cannot be told apart
  from the admin's own processes); the `emergency_stop` entry says so
  (row 30).
- Revoke-all is **not** part of the stop; it lives in the audit UI.

### 4.4 Claude Code isolation (rows 14–18)

**Managed settings** (root-owned; generated by `gov-aios claude-settings`
from the approved executor policy; installed by the admin): `PreToolUse`
hook, matcher `*`, command
`/Applications/gov-aios.app/Contents/MacOS/gov-aios hook`, timeout 300,
`onFailure: "block"`; managed hooks only; bypass-permissions mode
disabled; sandbox enabled and required, no unsandboxed commands, network
limited to the policy's managed domains, data home unreadable, all
weakening switches off. **[spike]** key names, `onFailure` on crash and
timeout, matcher `*` reaching MCP and subagent calls (installed Claude
Code is 2.1.318; `onFailure` needs 2.1.295+).

**Hook (`gov-aios hook`).** Reads Claude Code's `PreToolUse` JSON on stdin
and returns `allow` or `deny` JSON on stdout (exit 0). An `ask` verdict
is resolved by GOV-AIOS itself (4.1 `approve`) and returned as allow or
deny, never as `ask`. Any exception, bad input, unknown tool, missing
guard, `STOPPED`, a flow run in progress, or drift between the managed
`allowedDomains` and the approved `destinations` (either direction,
row 32; `doctor` reports it too) → exit 2 with a one-line reason. Hook latency **[spike]**: median under 1 s per call.

**Executor policy** `executors/claude_code.yaml` in the data home,
approved by content hash with Touch ID on first use and on any change,
audited as `flow: claude_code`, `executor: claude_code`. Fields:
`project_roots`, `allow_commands` (prefixes), `destinations`, `tools`.
Decision rules, in pure `policy.decide_tool(request, policy, approvals)`:

| Tool | Decision |
| :--- | :--- |
| Any tool on a protected path (after `realpath`) | deny |
| Unlisted tool, including any unlisted MCP tool | deny |
| Read / Glob / Grep | inside roots allow, outside ask |
| Edit / Write / NotebookEdit | inside roots allow, outside deny |
| Bash | listed prefix and no shell metacharacter → allow; else ask (sandboxed either way) |
| WebFetch | undeclared origin deny; first contact ask; then allow |
| WebSearch | deny unless listed |

Tools with no row above (row 33): each listed tool has a category fixed
in code. Internal (TodoWrite, ToolSearch, AskUserQuestion, ExitPlanMode
and similar) and delegate (Agent, Skill) allow; search allows when
listed; external (`mcp__*`) asks on every call and is never remembered.
A tool name the code has no category for is denied. LSP, Monitor,
WebSearch and all MCP tools are off in the default policy.

**First policy (row 31).** `gov-aios claude-settings --root <dir>`
writes a default `executors/claude_code.yaml`, shows it whole for
`approve()`, then prints the managed settings. Defaults: commands
`git status`, `git diff`, `git log`, `git show`, `ls`, `.venv/bin/pytest`;
destinations github.com, pypi.org, files.pythonhosted.org. The admin
edits it before approving.

Protected paths: the data home, `/Library/Application Support/GOV-AIOS`,
`/Library/Application Support/ClaudeCode`, `/Applications/gov-aios.app`,
`~/.claude`, `~/Library/LaunchAgents`.

**Audit for Claude** (row 17): one `request` entry per tool call with
`action` (tool), `target` (resolved path or audit URL), new `command`
(full Bash command, secrets redacted), `decision`, `approver`, `channel`,
`auth`. Redaction patterns are listed in row 17 and unit-tested.

### 4.5 OS-level network block (rows 22–23)

Every subcommand except `doctor` calls `sandbox_init()` (via `ctypes`) at
entry, before any other work, with a profile that allows everything but
network: `(allow default) (deny network*)`, Unix sockets allowed, the
mDNS/DNS service lookup denied. `audit-ui` additionally allows binding
and inbound on localhost. Fallback: the shim re-execs through
`/usr/bin/sandbox-exec -p`. **[spike]** profile accepted; AX, CGEvent,
activation, `osascript` dialogs and `LAContext` still work; DNS and TCP
fail; the audit UI still serves.

Chrome is never our child: `launch_application` uses
`open -n -a "Google Chrome" --args --profile-directory=<dir>`, so
LaunchServices starts it, unsandboxed and not attributed to gov-aios
**[spike]** opens the profile window in an already-running Chrome
without a second browser. `netguard` stays as a second layer; its
shortcut comment points at row 22.

### 4.6 Audit UI login and revocation (rows 19–21)

- `audit-ui` requires `prove("open the audit log")`, then prints
  `http://127.0.0.1:<port>/login?c=<code>` (single use, 60 s). `/login`
  sets an `HttpOnly; SameSite=Strict; Path=/` session cookie and 303s to
  `/`. Every request needs the cookie and `Host == 127.0.0.1:<port>`.
  Session ends after 1 hour or on screen lock, and the server exits.
  Audited `ui_login`.
- Approvals page: Revoke per flow, per destination, and Revoke all, each a
  `POST /revoke` with a per-session CSRF token and an exact `Origin`
  check; else 403. No fresh Touch ID (revoking only removes power).
  Audited `revoke`. Everything else stays read-only GET.
- `Approvals` becomes read-modify-write under `flock` on
  `approvals.lock`, saved by temp file + `os.replace`; reads re-read the
  file. `Runner.gate` re-checks the flow hash at every gate, so a revoked
  flow stops at its next step (reason `revoked`).

### 4.7 Powers review (row 24)

`gov-aios review-powers` opens the Accessibility, Input Monitoring and
Screen Recording panes, asks (dialog + Touch ID) the admin to confirm
that only gov-aios and the apps they keep hold these, and records the
kept app names (audited `powers_review`). `run` refuses if the last review
is missing or older than 30 days, or `doctor` fails. No API lists other
apps' grants without Full Disk Access, so an attested review is the
honest form.

### 4.8 Smaller changes (rows 2, 25)

- Audit `KINDS` add `emergency_stop`, `revoke`, `ui_login`,
  `powers_review`, `resume`; `FIELDS` add `auth`, `command`. The verifier
  is unaffected (it checks chain and signatures, not kinds).
- `doctor` also reports: guard alive, managed settings present and
  root-owned, last powers review, screen locked.
- Frozen data home from `pwd.getpwuid(os.getuid()).pw_dir`, not `$HOME`.
- `test_flow_parsed_from_hashed_bytes` patches `read_bytes`.

## 5. Constraints

- The plan-1 global constraints carry over: macOS first behind
  OS-neutral interfaces; the policy engine pure and unit-tested; tests use
  a credential-free tmp `GOVAIOS_HOME`; nothing in the test suite
  triggers real input, real dialogs, real Touch ID or real installs (all
  pyobjc and `subprocess` calls mocked, as in `tests/test_macos.py`).
- **`--dev` gets no exemption (row 28).** It refuses unless
  `GOVAIOS_HOME` is set and is not the real data home. `_run` checks, in
  order: `sandbox_init`, guard alive, `STOPPED`, screen locked, powers
  review, then proof; `Runner` re-checks each step. Tests inject fakes;
  pytest never calls `sandbox_init`.
- Root installs, TCC grants and approval dialogs are the admin's
  (row 1). The plan stops and asks at each.
- Content never on stdout, stderr or the audit; errors carry types, not
  messages (plan 1).
- The first task is the spike (row 27). No production code depends on a
  **[spike]** fact until it is confirmed; a failed check goes back to the
  architect and the affected row is updated before building on it.

## 6. Build order (for the plan)

1. Spike: every **[spike]** item, results appended to the log.
2. Leftovers and locked `Approvals` (4.8, 4.6 last bullet).
3. `auth.py`: lock check and presence proof; wire into `run` start,
   `gate`/`ask`, `_require_focus`.
4. Guard, emergency stop, `resume`, `runs/` bookkeeping.
5. OS-level network block and Chrome via `open -n`.
6. `policy.decide_tool`, executor policy approval, redaction.
7. `gov-aios hook` and `claude-settings`.
8. Audit UI login and revocation.
9. `review-powers`, `doctor` additions, audit kinds and fields.
10. `install.sh` / `uninstall.sh` and docs, including the recovery steps
    (`launchctl kickstart` the guard, `resume`, `sudo rm` the managed
    settings; uninstall never deletes the data home or audit). Managed
    settings go in last, because from then on the Claude session building
    this is governed too (row 34): the admin performs the attended
    end-to-end check in a new session (installs, grants, runs a flow with
    Touch ID, presses the hotkey mid-run, uses Claude Code under the hook,
    revokes a flow in the UI).

## 7. Left to the builder

Module layout beyond `auth.py`; the guard's run-loop details; exact
dialog and Touch ID wording within the rules above; HTML of the new UI
controls (same no-JavaScript, inline-CSS style as plan 1); test
structure; the redaction regexes' exact form within row 17's list.

## 8. Decisions the admin may most want to revisit

From the architect's own notes, in order (also: row 34, this Claude
session becomes governed once the managed settings are installed):

1. **Root-owned `/Applications` install (row 18):** every dev rebuild
   needs a sudo reinstall and possibly a re-grant.
2. **All Claude tool calls denied while a flow runs (row 15):** strict,
   and Claude's own API traffic still is not blocked (row 25).
3. **No fresh Touch ID per revocation (row 20).**
4. **Touch ID on every run start, no session (row 5):** friction on
   repeat runs.
