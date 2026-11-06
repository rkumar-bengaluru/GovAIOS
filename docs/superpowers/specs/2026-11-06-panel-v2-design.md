# Control panel v2 — always there, audit by app — design

Date: 2026-11-06. Builds on `2026-11-06-control-panel-design.md` (v1, branch `feat/control-panel`).

## 1. Intent

The control panel is the face of GOV-AIOS, the thing the admin sees in the end. Every laptop it is installed on has exactly one admin: the person who owns the laptop. v1 made the admin start the panel from Terminal, copy a one-time link, and start again after every lock or hour. v2 makes the panel **always available once installed**: the install starts it and prints its address, and it stays up across locks. The audit view is reorganised around **apps, then their runs**. Later, apps (flows) will be created from the panel, so where apps live becomes the panel's concern.

## 2. Goals, non-goals, anti-goals

Goals
- The panel starts when the admin logs in to the Mac and keeps running (restarted if it crashes). The install sets this up and prints the address.
- One stable address: `http://127.0.0.1:8765/`.
- Seeing the panel needs a browser sign-in with Touch ID, started from the page (no link to copy). Running apps still needs the 30-minute code session, as in v1.
- Audit: apps → that app's runs → a run's steps.
- The spoken name and greeting come from the laptop owner, not a fixed "Rupak".

Non-goals (this cycle)
- Creating or editing apps from the panel (next cycles, but the apps folder is chosen with that in mind, §5.4).
- Voice, hands-free, the morning brief (unchanged from v1 §9).
- More than one user or any view-only role.

Anti-goals (a failure even if it works)
- The panel staying up must not weaken anything: a lock still ends the session and stops its run; nothing runs without a code session; terminal runs still ask for Touch ID.
- No network beyond 127.0.0.1, no JavaScript, same page security rules.
- The Touch ID sign-in button must not let another local page or process sign a browser in, or spam Touch ID prompts.

## 3. Admin decisions (as said)

- "the control panel should always be available on install of the app, the install step should guide the panel url."
- "at some point we will drive flows/apps creation flow from the control panel."
- Audit "should be run apps and per runs."
- "once it is installed to others laptop that person who owns the laptop becomes the admin."
- The admin heard and accepted the spoken sentence.

## 4. Constraints carried from v1

Everything in v1 §4 and the v1 rulings doc stays: `UI_PROFILE` for the web part, the launch helper split off before the sandbox, TOTP rules, 30-minute hard session, run tickets, audit kinds, exact refusal and spoken texts (the name becomes a setting), CSP with no scripts, governance prompts mid-run.

## 5. Design

### 5.1 Started at login (LaunchAgent)
- `packaging/install.sh` installs a second user LaunchAgent, `com.govaios.panel`, next to the existing `com.govaios.guard`, the same way (same ownership, `launchctl bootout` before the app swap, `bootstrap` after). `RunAtLoad` and `KeepAlive` (restart on crash, not on a clean exit).
- The agent runs `/Applications/gov-aios.app/Contents/MacOS/gov-aios panel --port 8765 --apps <apps folder>` directly (no shim; launchd is the parent). Its stdout and stderr go to `<data home>/panel.log`, which gets steps and errors only, never content and never codes or links.
- At the end of the install: `Control panel: http://127.0.0.1:8765/  (sign in with Touch ID on the page)`.
- `uninstall.sh` removes the agent.
- Port 8765 busy → the panel exits non-zero with one clear line in `panel.log`, and launchd retries every 30 s (`ThrottleInterval` 30). The same error is logged at most once per minute. The install checks the port and says so.
- Install runs under `sudo` like today: it resolves the user from `SUDO_USER` exactly as the guard agent does, and every file it creates under the user's home (the agent plist, the apps folder) is owned by that user.
- Terminal `bin/gov-aios panel flows` stays for development on another port (default random, as today).

### 5.2 Sign in from the page
- No single-use link. A signed-out browser sees **Locked** and a **Sign in with Touch ID** button (`POST /signin`).
- `/signin` needs the same Host and Origin checks as every POST. Because the browser has no session yet, CSRF is a pre-login token: `GET /` sets a short-lived (2 min) `pre` cookie (HttpOnly, SameSite=Strict) and puts the same token in the form; `/signin` requires them to match.
- Server side: `auth.prove("sign in to the GOV-AIOS panel, code <WORD>", home)`, where `<WORD>` is 4 random letters also shown on the signed-out page next to the button. The admin approves only when the code in the Touch ID prompt matches the page in front of them. This stops another local page or process from getting its own cookie signed in without the admin noticing (a process can still ask; it cannot make the codes match). Only one prompt at a time across the whole panel (a second press while one is up is refused "busy"); after a refused or cancelled prompt, sign-in is paused for 10 s for everyone. Audit `ui_login` with `channel=touch_id`, as today.
- A browser sign-in lasts until the next screen lock or 8 hours from sign-in, whichever comes first. A lock signs out every browser.
- The 30-minute code session is one per panel (not per browser), opened from the Talk page after sign-in by typing the code, exactly as in v1. A lock ends it and stops its run (v1 ticker, polling the lock every second). Signing one browser out does not end it; a lock, End session, expiry, emergency stop or a panel restart does.
- Sessions and sign-ins are in memory: a panel restart (crash, upgrade, logout) signs everyone out and ends the code session. A run that is live when the panel dies is stopped by the helper, which stops its run when the panel goes away (v1).
- The sandbox and the helper split are done by the app's own `main()`, not the shim, so the launchd-started panel gets both unchanged.
- The server no longer shuts down on lock or on browser-session expiry. It only signs browsers out. (The v1 rule "a lock ends the code session and stops its run" is unchanged.)

### 5.3 Audit by app, then by run
- `/audit`: one row per app (display name, id, approved or draft, number of runs, last run time and outcome, last started by: Panel or Terminal). Apps no longer in the folder but present in the log appear under "Removed apps".
- `/audit/app/<id>`: that app's runs, newest first (time, steps, outcome, started by, delivery summary if any).
- `/audit/run/<seq>`: as today.
- `/audit/log` (full log) stays.
- "Started by" comes from the run's `run_start` entry: `channel=totp_session` → Panel, `touch_id` → Terminal, no `run_start` (older runs) → "—". Outcome comes from `flow_end`; the delivery summary from the run's `delivery` entries (counts by outcome).
- Same columns and escaping rules as v1; no content.

### 5.4 Where apps live
- The panel agent reads apps from `<data home>/apps/` (pages from `<data home>/apps/pages/`). This is the folder future app creation from the panel will write to.
- The install copies the repo's `flows/*.yaml` and `pages/` there when the file is missing; it never overwrites an existing file (an app the admin changed stays changed). Approvals are keyed by app id and file content (digest), not path, so a copy keeps its approval. When a repo app differs from the installed copy, the install lists it ("not updated: <file>") and leaves it; updating it is the admin's choice (copy by hand, then approve again).
- Terminal runs keep taking any path (`bin/gov-aios run flows/x.yaml`); the panel shows only the apps folder.

### 5.5 Owner's name
- The name used in the greeting and spoken sentence defaults to the first word of the Mac account's full name (`pwd` gecos, read by the panel), falling back to "Admin".
- The Approvals page shows it with a **Change** field (POST, CSRF; needs sign-in, not a code session); stored in `<data home>/panel.json` (0600). Audit `setting` with field `name` (the value isn't secret, but it is not logged either).

## 6. Tests the builder adds
- Login: `/signin` with no `pre` cookie, a wrong token, a wrong Origin → 403 and no Touch ID prompt; a second press while a prompt is open → busy; after a refusal, presses within 10 s don't prompt.
- Lock: lock → every browser signed out, server still serving, session ended, run stopped.
- 8-hour sign-in expiry with a fake clock.
- Audit: app rows from a log with two apps and a removed app; app page lists only that app's runs; started-by column.
- Install: the plist is well-formed and names the app binary, port and apps folder; the copy step never overwrites (shell test like `test_shim.py`).
- Name: default from a fake gecos; change is saved 0600 and used in the spoken sentence.

## 7. Review focus
1. Another local page or process making a browser signed-in, or triggering Touch ID prompts in a loop.
2. A lock while signed in from two browsers, with a run live.
3. Port collision at login (another app on 8765).
4. The agent restarting in a loop (`KeepAlive` with a crash at startup), filling `panel.log`.
5. Install over an existing apps folder the admin has changed.

## 8. My calls (for the admin to check)
- Fixed port 8765.
- Sign-in lasts until lock, capped at 8 hours.
- Apps live in `<data home>/apps/`, seeded from the repo, never overwritten.
- The name defaults from the Mac account and can be changed in Approvals.
- `panel.log` in the data home, for steps and errors only.
- 10-second pause after a refused Touch ID sign-in, for everyone.
- A 4-letter code on the page and in the Touch ID prompt, so you only approve the sign-in you started.
- One code session per panel; a panel restart signs out and ends it.
- launchd retry every 30 s on a failed start, with the error logged at most once a minute.
- Repo apps that changed are listed by the install, never copied over yours.
- Unverified until the live test: Touch ID prompts and app launches from a panel started by launchd rather than Terminal.

## 9. Left to the builder
- How the plist is templated (user, paths) in `install.sh`.
- Exact page layout of the app and run tables (follow the v1 styling).
- How `panel.log` is rotated (a size cap is enough).
