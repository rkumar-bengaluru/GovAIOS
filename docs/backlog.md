# GOV-AIOS backlog

Work not in an active plan. Ask "show me all backlog" to see this file. Newest areas first.
Updated 2026-11-06 after control panel v2 (PR #10).

## Apps platform (branch `feat/apps-platform`)

- **Studio: new apps from a sentence.** Capture the real page, mask it, hand it to an LLM, check
  the draft, test-run it, approve it. Spec: `docs/superpowers/specs/2026-11-06-studio-capture-handover-design.md`.
  Decided: typing into search boxes only, with run-time inputs. Open until build: the Claude channel
  (API key in Keychain or Claude Code no-tools mode); other LLMs as writers.
- **My apps and Marketplace** panel areas. Each app drives its own setup; upgrades carry apps over.
  Mockup: `docs/superpowers/mockups/2026-11-06-apps-journey.html`.
- **Claude Code refusals made by its own managed deny rules are not in the audit log** (seen live
  2026-11-07: reading the data home and writing /tmp were refused before the hook ran). Only calls that
  reach the hook are logged.
- **Chat in Talk:** plain messages (not commands) answered by Claude in the panel (admin, 2026-11-07).
  Needs the Studio decision on how the panel reaches Claude. Apps with run-time inputs show them on
  their `/app` card.
- **Change Claude Code folders from the panel:** setup keeps an existing policy's folders.
- ~~Govern OpenAI Codex like Claude Code~~ built 2026-11-07 (branch `feat/codex-template`) and live-tested
  (A–E passed) per `docs/codex-integration-test.md`. Still open: Codex network allow-list (`experimental_network`),
  Codex built-in tools beyond Bash/apply_patch/MCP.
- **JobLens integration** (admin, 2026-11-07): next after Codex is verified.
- **Inbox brief short app name** (`app:` in `flows/morning_inbox_briefing.yaml`) so the panel
  accepts "run inbox brief".
- **Later: service-account / API connectors** (e.g. Drive API): new action kind, Keychain
  credentials, scopes, network rules. Admin: "leave service account for later".

## Publication and open source (admin, 2026-11-06)

Order: Studio phase 1 → attack-suite evaluation → paper and public repo released together.
Dated plan: `docs/research/roadmap.md` (target USENIX Security '27 cycle 2, paper due 26 Jan 2027).

- **Hardening the research exposed** (roadmap Phases 0 and 2; W-numbers are from `docs/research/reports/`):
  - ~~typed code word in place of compared code (NIST 800-63B-4)~~ done in Phase 0 (branch `feat/phase0-hardening`);
  - ~~the audit records a digest of what the approver saw~~ done in Phase 0 for panel sign-in and flow/step approvals;
    still to do: the Claude Code hook, JobLens delivery, executor policy, powers review and authenticator approvals;
  - Secure Enclave–signed approvals over digests;
  - signed and anchored audit heads;
  - Codex hooks fail closed, and `~/.codex` and `AGENTS.md` are protected.

- **Attack-suite evaluation.** Turn the existing tests into a measured attack suite. Cover:
  - injected page text steering a flow;
  - forged or replayed panel requests and stale tokens;
  - an agent (Claude Code, Codex) acting outside its rules;
  - writes or destinations a flow doesn't allow;
  - an LLM-written draft that tries to widen its permissions.

  Report blocked vs total for each, and the time added per action.
- **Paper outline and related-work survey.** Target an arXiv preprint in cs.CR (the admin has endorsers), and optionally an agent-security workshop or demo track. The paper needs:
  - contributions (presence-bound approval, risk-rated page schemas, one governance layer for browser and coding agents, safe LLM-written apps);
  - a threat model with the known residuals stated;
  - the evaluation;
  - an acknowledgement of Claude (Anthropic) via Claude Code. AI can't be listed as an author on arXiv or with ACM/IEEE.
- **Clean public repo.** A new repo with fresh history, not this one made public, because this repo's history holds personal data (Google account, Chrome profile, Himalayas/JobLens). It needs:
  - the chosen code: engine, policy, audit, panel, sandbox, Claude Code and Codex governance, Studio checks;
  - a demo flow against a public test page;
  - no Himalayas, Gmail or delivery targets;
  - a secrets and personal-data scan before release;
  - an Apache-2.0 licence.

## Control panel residuals (v2 rulings doc)

- Keychain / Secure Enclave work: fixes same-user ticket minting (v1 ruling 5) and the
  cookies-not-port-scoped risk (v2 F3).
- An app deleted from the apps folder comes back on the next install unless revoked (v2 M2).
- A startup crash writes a traceback to `panel.log` on each 30 s restart (v2 M4).
- Not yet seen live: the launch helper surviving a panel crash under launchd and stopping its run.
- One full-suite run once failed 13 tests (likely two pytest runs sharing temp dirs); watch for it.
- Voice and hands-free: speak commands and the authenticator code to the panel (admin, 2026-11-07).

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
