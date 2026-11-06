# GOV-AIOS control panel (typed) — Design

Date: 2026-11-06. Status: draft for admin approval.
Builds on: governance-layer spec, plan 2 (admin auth and isolation) and its rulings, plan 4
(delivery, JobLens app). Mockup of the agreed journey: `.superpowers/brainstorm/*/content/journey-v2.html`
(local, not committed).

## 1. Intent

The admin wants to talk to GOV-AIOS instead of typing commands: "run the JobLens app now", and hear
"Rupak, the JobLens flow is complete, thank you" when it is done. The end state is voice, including
hands-free (in the shower). This design is the first of three steps: **the control panel, typed**.
It builds everything voice will stand on (apps list, the authenticator code and the 30-minute
session, starting runs from the panel, the spoken result), so the security parts are tested before
speech arrives. Voice (step 2) and hands-free (step 3) are recorded in §9 as decided, not built.

The panel replaces today's audit page (`audit-ui`): one local page for talking, runs, the audit log
and approvals.

## 2. Goals, non-goals, anti-goals

**Goals**
1. `bin/gov-aios panel`: Touch ID, then a local page with Talk, Audit log, Approvals.
2. Apps listed as **Approved** (approved for the flow file's current hash) and **Drafts** (any other
   flow in `flows/`).
3. One-time authenticator setup; afterwards a 6-digit code opens a **30-minute session** in which a
   typed "run joblens" starts the app at once, with no Touch ID.
4. Live progress of the run in the page (step lines only, never page content), the result written
   and spoken on the Mac.
5. The audit page's functions (runs, run detail, full log, verified check, revoke) move into the panel.

**Non-goals (this design)**
- Speech input, wake phrase, hands-free (steps 2 and 3, §9).
- Creating or editing apps in the panel; the morning inbox brief as an app (next project).
- Phone or remote access; anything not on `127.0.0.1`.
- Changing the terminal: `bin/gov-aios run ...` keeps Touch ID on every run (admin, 2026-11-06).

**Anti-goals (a failure even if it works)**
- The page approving anything. Approving an app, a site or a delivery target stays the signed
  app's native dialog + Touch ID.
- A session that outlives a screen lock, the emergency stop, or 30 minutes.
- A terminal run that skips Touch ID because a panel session is open.
- Network beyond what exists: the panel serves `127.0.0.1` only; runs keep `RUN_PROFILE`; delivery
  keeps `DELIVER_PROFILE`. No cloud speech, no cloud anything.
- Job or mail content in the page, the audit log, or stdout.

## 3. Admin decisions (2026-11-06)

- Terminal stays, Touch ID per run as today.
- Panel runs: authenticator code (TOTP) → 30-minute session → approved apps start with no further
  proof. Rationale (admin): bounded exposure, like a token with an expiry; the admin sets the Mac
  to lock after 30 minutes of inactivity.
- Approved apps only; a draft is refused with "get it approved first".
- On-device speech only (no Chrome speech recognition: it sends audio to Google).
- Voice input: click once, stop on silence. Hands-free: armed inside a session (§9).
- The panel replaces the audit page.

## 4. Constraints

- Plan 2 rules hold: STOPPED and screen lock refuse; the emergency stop ends runs; revoke works;
  the audit log is signed and append-only; Touch ID dialogs come from the signed app.
- The panel server keeps `UI_PROFILE` (inbound localhost only) and the existing login model:
  single-use link printed after Touch ID, session cookie, CSRF token, `Origin` check,
  `Referrer-Policy: same-origin`.
- TOTP: RFC 6238, SHA-1, 6 digits, 30-second step, accept the current step ±1; a code already used
  is refused (replay); 5 wrong codes in a row lock code entry for 15 minutes. Codes are compared in
  constant time.
- Standard library, plus at most one small pure-Python QR encoder for the setup screen (§8).

## 5. How it works

### 5.1 Opening the panel
`bin/gov-aios panel` (the `audit-ui` command stays as an alias) proves presence with Touch ID,
starts the server and prints the single-use link, exactly as `audit-ui` does today. The browser
session lasts at most 60 minutes (today's `SESSION_TTL`), independent of the run session. The server
never shuts itself down while a run it launched is live (today the browser-session expiry stops the
server); it stops once that run has ended.

### 5.2 Apps
The panel reads `*.yaml` from a flows directory given on the command line (`bin/gov-aios panel flows`;
the shim makes it absolute, as it does for `run`); pages come from its sibling `pages/`, as for runs.
It computes each flow's digest
with `read_bound` and compares it with `approvals.json`:
- **Approved:** `flow_ok(id, digest)` is true.
- **Draft:** anything else (never approved, or changed since approval).

Each app shows a display name. New optional flow key `workflow.app: <name>` (e.g. `JobLens`);
without it the panel shows the flow `name`. Adding the key to the Himalayas flow changes its hash:
one more approval (dialog + Touch ID) on its next run. The morning brief file is not touched here.

A draft has an **Approve…** button. It does not approve: it asks the signed server to show the
same native approval dialog a first run shows today (flow summary, then Touch ID). Only a yes in
that dialog writes `approvals.json`.

### 5.3 Authenticator setup (once)
Setup screen (Approvals → Authenticator): the server makes a 20-byte random secret, shows it as a
QR code and as a base32 key (`otpauth://totp/GOV-AIOS:Admin?secret=...&issuer=GOV-AIOS`). The
admin scans it on the phone and types one code; if it verifies, a native dialog + Touch ID
confirms, and only then the secret is stored. Reset: Approvals → Reset authenticator (Touch ID),
which deletes the secret and ends any session.

Secret storage: the macOS Keychain item owned by the signed app if workable, else
`<data home>/totp.key` mode 0600 (same standing as the audit signing key today). The page never
receives the secret after the setup screen.

### 5.4 The 30-minute session
- Opened by a valid code typed in the Talk box when no session is open. Lasts exactly 30 minutes
  from the code; never extended; a new session needs a new code.
- Ends early on: screen lock (any lock during the session, even if unlocked again), the emergency
  stop, Reset authenticator, the panel server stopping, or a "End session" button.
- Shown as the ring by the admin's name (mockup) with the minutes left.
- Held only by the panel server process, in memory, plus a one-time **run ticket** per run (5.5).
  Nothing on disk says "session open", so nothing outside the panel can borrow it.

### 5.5 Starting a run from the panel
Typed text is matched to an approved app: lowercase, strip "run", "the", "app", "now", "please",
then exact match on the app's display name or flow id. No match or more than one: GOV-AIOS asks
("Which app: …?") and runs nothing. A draft: "<name> is a draft. Get it approved first." Only one
run at a time; a request while a run is live is refused ("JobLens is still running").

With a session open, the panel server:
1. Creates a run ticket: 32 random bytes, valid 60 seconds, one use, bound to the flow id and digest;
   written to `<data home>/tickets/<hex>` (mode 0600, no-follow, exclusive create).
2. Launches the signed app as two launches exactly like the shim (`run <flow>` then, if asked,
   `deliver <flow>`), passing the ticket to the run launch only, and streams both launches' output
   lines to the page.
3. The run process consumes the ticket instead of asking Touch ID: it must exist, be unexpired,
   match the flow id and current digest, and is deleted before the run continues (read-and-unlink
   under a lock). Any check fails → `Stop("run ticket not valid")`, no Touch ID fallback.
4. The run-start audit entry records `approver=admin`, `channel=totp_session`, `auth=ticket`,
   with a session id (random, not the code).

A run started from the terminal has no ticket and asks Touch ID as today. A ticket is useless after
one run, after 60 seconds, and for any other flow or a changed flow file.

### 5.6 Result and spoken reply
When both launches end, the panel writes the outcome into Talk ("JobLens finished: delivered 2,
duplicate 3" from the deliver summary line) and speaks
"Rupak, the <app> flow is complete, thank you." (or "… stopped: <reason>") with the Mac's on-device
speech (`NSSpeechSynthesizer`/`AVSpeechSynthesizer` via PyObjC, or `/usr/bin/say`). The admin's
name comes from a setting, default "Rupak".

### 5.7 Audit log and approvals
Today's pages move under Audit log (runs, run detail, full log, verified banner) and Approvals
(apps, sites, delivery targets, authenticator) with the existing revoke forms. The runs table adds
"Started by": `Terminal, Touch ID` or `Panel, session code`.

New audit kinds: `totp_setup`, `totp_reset`, `session_open` (decision, reason on failure such as
`bad_code` / `replay` / `locked_out`), `session_end` (reason: `expired` / `screen_lock` /
`emergency_stop` / `reset` / `ended` / `server_stop`). Never the code or the secret.

## 6. Tests the builder must add

- TOTP against the RFC 6238 test vectors; ±1 step accepted, ±2 refused; replay refused; lockout
  after 5 failures and its expiry.
- Session: ends at 30:00; ends on a screen lock (fake lock event) even if unlocked again; ends on
  STOPPED; never extended by a code typed mid-session.
- Ticket: consumed once; expired, wrong flow, changed flow file, symlinked or missing ticket all
  stop the run without a prompt; a terminal run without ticket still calls `auth.prove`.
- Command matching: "run the joblens app now" → JobLens; unknown and ambiguous → no run; draft →
  refused text; second request while running → refused.
- Approve… on a draft calls the native approval and writes nothing when it is declined.
- Page and audit entries contain no job content (marker-string fixture, as in plan 4).
- `audit-ui` alias still works; existing audit-page tests pass under the panel.

## 7. Review focus

1. The panel server is a new launcher of runs: a request forged from another local page (CSRF,
   wrong Origin, no session) must never start one.
2. Lock detection: a lock and unlock between two page requests must still end the session.
3. Clock changes: a session or ticket expiry must not be extended by moving the clock back
   (use a monotonic clock where possible).
4. A run started from the panel and then stopped with the hotkey: both launches end, the page shows
   "stopped", the session ends.
5. Two browser tabs on one panel: one session, one run at a time.

## 8. Calls I made (admin to check)

- Command name `panel <flows dir>`; `audit-ui` stays as an alias.
- The panel server waits for a live run to end before it stops on browser-session expiry.
- Run tickets on disk (one use, 60 s) are how a run knows it came from the panel; the session
  itself lives only in the panel server's memory.
- A lock at any moment during the session ends it.
- Apps get an optional `app:` display name; adding it to the Himalayas flow means one re-approval.
- The QR code needs one small pure-Python dependency (e.g. `segno`); if refused, the key is typed
  by hand.
- 5 wrong codes lock code entry for 15 minutes.
- The spoken name is a setting, default "Rupak".

## 9. Decided for later steps (not built here)

- **Voice (step 2):** click once to listen, stops on silence; on-device recognition in the signed
  app (`SFSpeechRecognizer` with on-device only); the page shows the live transcript as
  `Admin -> ...`; recognised text goes through the same matching as typed text.
- **Hands-free (step 3):** inside a session, "Listen hands-free" arms a wake phrase ("GOV-AIOS");
  audio before it is discarded; the request is read back aloud with a 5-second "say cancel" window;
  only apps the admin marked hands-free; ends with the session. The admin sets macOS to lock after
  30 minutes of inactivity; GOV-AIOS does not change that setting.
- **Morning inbox brief** as the second app under governance: the next project, so "my meeting
  plan" has an app to run.

## 10. Left to the builder

Module layout (suggested `govaios/panel/` with `totp.py`, `session.py`, `apps.py`, and the server
growing out of `audit/web.py`), how lock events reach the panel (the guard's run loop already
receives distributed notifications), the page markup (the mockup is the reference, not a spec),
the progress transport (polling or server-sent events), and exact refusal texts beyond those given.
