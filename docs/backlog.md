# GOV-AIOS backlog

Work not in an active plan. Set by the admin on 2026-11-06: plan 4 goes first; these wait.

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
- Close the flow's own Chrome window at the end (`close_window`, verified window only; built and
  reverted on 2026-11-06, commit 1d6cc6c).
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

## Later (after plan 4, not designed)

- More proof channels: OTP, verified paired phone app; remote triggering of approved flows
  (decision row 35). Every run still carries a proof from the admin. Open: a remote run needs an
  unlocked GUI session, which conflicts with stop-on-lock.
- Unattended execution.
- Windows adapter.
