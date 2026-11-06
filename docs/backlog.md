# GOV-AIOS backlog

Work not in an active plan. Ask "show me all backlog" to see this file. Newest areas first.
Updated 2026-11-06 after control panel v2 (PR #10).

## Apps platform (branch `feat/apps-platform`)

- **Studio: new apps from a sentence.** Capture the real page, mask it, hand it to an LLM, check
  the draft, test-run it, approve it. Spec: `docs/superpowers/specs/2026-11-06-studio-capture-handover-design.md`.
  Open before build: the Claude channel (API key in Keychain or Claude Code no-tools mode); other
  LLMs as writers.
- **My apps and Marketplace** panel areas. Each app drives its own setup; upgrades carry apps over.
  Mockup: `docs/superpowers/mockups/2026-11-06-apps-journey.html`.
- **Govern OpenAI Codex** like Claude Code: Codex 0.162 has `PreToolUse` hooks and a managed `/etc/codex/requirements.toml`. Needs one live test (does a hook crash or timeout fail closed?). Spike: `docs/superpowers/spikes/2026-11-06-codex-governance.md`.
- **Inbox brief short app name** (`app:` in `flows/morning_inbox_briefing.yaml`) so the panel
  accepts "run inbox brief".
- **Later: service-account / API connectors** (e.g. Drive API): new action kind, Keychain
  credentials, scopes, network rules. Admin: "leave service account for later".

## Control panel residuals (v2 rulings doc)

- Keychain / Secure Enclave work: fixes same-user ticket minting (v1 ruling 5) and the
  cookies-not-port-scoped risk (v2 F3).
- An app deleted from the apps folder comes back on the next install unless revoked (v2 M2).
- A startup crash writes a traceback to `panel.log` on each 30 s restart (v2 M4).
- Not yet seen live: the launch helper surviving a panel crash under launchd and stopping its run.
- One full-suite run once failed 13 tests (likely two pytest runs sharing temp dirs); watch for it.
- Voice and hands-free.

## Plan 3: terms gate and challenge handling (governance-layer spec §5.5, §5.6)

- **Terms gate.** Before approving a flow on a third-party site, read the site's terms in the real
  browser, quote the automation / agent / scraping clauses, propose `allowed` / `forbidden` /
  `unclear` (`unclear` = forbidden until the admin decides). Store decision, quotes, date and
  version in the flow and the audit. Re-check every 90 days and before re-approval; a change from
  `allowed` suspends the flow.
- **Challenge handling.** CAPTCHA, "verify you're human", login, MFA, unusual activity: stop, the
  admin solves it, re-verify, continue. 3 challenges in 7 days suspends the flow.

## Flow improvements

- After a click lands on the wrong page: browser Back once, re-verify, retry once, else stop.
- ~~Close the flow's own Chrome window at the end (`close_window`)~~ done: JobLens ends with it.
- Run the morning inbox flow under plan 2's governance.
- Origin check after every click (today an unapproved origin is caught only by the post-click
  page check).

## Plan 2 leftovers

- Claude Code integration live test: `docs/claude-code-integration-test.md`.
- Live cases not run: Touch ID with lid closed and in lockout, fast user switching, the hotkey
  under secure input, a stop cancelling a waiting prompt.
- Audit hook calls that exit 2 (blocked); a Glob over the whole root can list nested `.claude`.
- `install.sh` prints a harmless `Bootstrap failed: 5` on its first bootstrap try.
- Signed installer package instead of a checkout under sudo.

## Later (not designed)

- More proof channels: OTP, verified paired phone app; remote triggering of approved flows
  (decision row 35). Every run still carries a proof from the admin. Open: a remote run needs an
  unlocked GUI session, which conflicts with stop-on-lock.
- Unattended execution.
- Windows adapter.
