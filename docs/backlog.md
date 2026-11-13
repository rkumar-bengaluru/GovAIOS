# GOV-AIOS backlog

Work not in an active plan. Ask "show me all backlog" to see this file. Newest areas first.
Updated 2026-11-08 with JobLens tasks and Web Sandbox (branch `feat/joblens-tasks`); 2026-11-07 Job Apply; before that 2026-11-08 Claude Code and Codex governance (PRs #16, #17).

## JobLens apply (app JobLens, flow `job_apply`; branch `feat/joblens-tasks`, 2026-11-08)

- ~~List JobLens applications in `/job-apply`~~ built 2026-11-08: the run reads JobLens in Chrome, one panel task per Ready
  job (design `docs/superpowers/specs/2026-11-08-joblens-tasks-design.md`, test plan `docs/joblens-integration-test.md`).
- **Tailored CV**: attach the CV JobLens Apply downloads to ~/Downloads instead of the bank's `cv_file`.
- **Mark submitted in JobLens** after Next job (a submit-rated click: needs its own approval).
- ~~Jobs that link straight to an employer form~~ done 2026-11-08 (`classify_page` `{skip_to: on_form}`).
- **JobLens page files are from source code**: confirm against the first live capture.
- **Greenhouse paste-CV mode.** The CV is attached as a file only today.
- **Workable**, after a terms check. It stops with "unexpected page" for now.
- **CAPTCHA detection.** Today an earlier challenge only shows up as a failed read-back.
- **Batch runs** of several links.
- Live test plan and known gaps: `docs/job-apply-integration-test.md`.

## Apps platform (branch `feat/apps-platform`)

- **Studio: new apps from a sentence.** Capture the real page, mask it, hand it to an LLM, check
  the draft, test-run it, approve it. Spec: `docs/superpowers/specs/2026-11-06-studio-capture-handover-design.md`.
  Decided: typing into search boxes only, with run-time inputs. Open until build: the Claude channel
  (API key in Keychain or Claude Code no-tools mode); other LLMs as writers.
- **`gov-aios capture <page>`: Studio capture as a CLI step first** (admin, 2026-11-07). It replaces running
  `gov-aios dump` by hand, which prints names and values unmasked to the terminal. Touch ID as dump does,
  masks per spec §5.3, writes `studio/<draft>/capture/<page>.json` (0600), never stdout. The panel's
  "Capture this page" comes later on top of it. Then decide roles and intent (§5.4).
  Evidence (2026-11-07, Greenhouse + 2 Lever captures): 101/101 form fields keep a label if values are
  masked and only the text node just before each field is kept (6 Lever fields have their question only
  in that text). **Spec §5.3 needs amending for forms:** its 60-character cap and controls-only kept list
  would mask long Greenhouse question labels and those Lever questions; combo_box, popup_button and radio
  are not in its kept roles. Not yet checked against Gmail/JobLens/Himalayas captures.
- **Web Sandbox** built 2026-11-08 (`flows/web_sandbox.yaml`): open any https site (Touch ID on first contact), capture
  the pages the admin chooses, read only. Since night 2 (branch `feat/studio-drafts`) each capture also writes a draft
  page + a read-only Check app as Drafts (`docs/superpowers/specs/2026-11-08-studio-drafts-design.md`). Still open:
  repeated items and a YAML preview in Studio compose (compose itself built 2026-11-09, panel /studio), lowering reviewed button risks,
  masking before non-dev use, the terms gate (Plan 3).
- **Capture on stop** — dev version built 2026-11-08 (branch `feat/capture-on-stop`): unmasked, in the run,
  `captures/` keeps the last 10. Still open: masking before non-dev/Studio use, the panel showing the reason,
  non-web flows (screen capture). Original note (admin, 2026-11-08: pick right after `gov-aios capture`): When a run stops on a refused
  input or "left the page", save a masked capture (same masking as capture) plus the failed target, the element
  under the click point and the step, to `captures/<run>.json` (0600), never stdout. Why: the
  Greenhouse Country combo took several rebuild-and-run rounds of guessing because nothing showed the live tree.
- **My apps and Marketplace** panel areas. Each app drives its own setup; upgrades carry apps over.
  Mockup: `docs/superpowers/mockups/2026-11-06-apps-journey.html`.
- **Claude Code refusals made by its own managed deny rules are not in the audit log** (seen live
  2026-11-07: reading the data home and writing /tmp were refused before the hook ran). Only calls that
  reach the hook are logged.
- **Panel UI design pass** (admin, 2026-11-07): the Talk cards, coding-agent pages and Marketplace need a
  proper design before more UI is added.
- **Independent security review** of the coding-agent work before the attack-suite evaluation: the root
  step (`ROOT_SCRIPT` under the macOS administrator dialog), the Terminal launch file, `codex-hook`
  (patch parsing, plugin remembering). Not reviewed yet.
- **Chat in Talk:** plain messages (not commands) answered by Claude in the panel (admin, 2026-11-07).
  Needs the Studio decision on how the panel reaches Claude. Apps with run-time inputs show them on
  their `/app` card.
- **Change Claude Code folders from the panel:** setup keeps an existing policy's folders.
- ~~Govern OpenAI Codex like Claude Code~~ built 2026-11-07 (branch `feat/codex-template`) and live-tested
  (A–E passed) per `docs/codex-integration-test.md`. Still open: Codex network allow-list (`experimental_network`),
  Codex built-in tools beyond Bash/apply_patch/MCP.
- **JobLens integration** (admin, 2026-11-07): next after Codex is verified.
- ~~Inbox brief short app name~~ done 2026-11-08 (`app: Inbox Brief`; approve it once again).
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

## Studio observer: deferred from the first slice

- Pause for terms + Touch ID when a lesson moves to a new origin (today the lesson just ends).
- Consent checkboxes can't be filled from the bank yet.
- Type then Enter misses the last value.
- Reading a site's terms for the admin (Plan 3, second slice).

## Panel: Apps page and run queue, follow-ups (2026-11-11)

- "Last started" on an app card shows the raw ISO time; show it like "today 12:49".
- Empty states: an empty Apps grid and an empty "Waiting for approval" list render nothing.
- When a queued app auto-starts, the previous JobLens run's job list and result drop off Home (they are keyed on the run); the finished/stopped line stays.
- Signing out of one browser clears the queue even if another browser is still signed in (as the spec says; revisit if two browsers are used).
- A failed queued start writes three audit lines (started, error, dropped); a failed "dropped" audit loses the entry without a message.
- An app queued while it is running shows only "Running…" on its card (no ✕); "unqueue <app>" removes it.
- If an audit write fails as a session ends, the queue is cleared but the session_end line can be missing.
- /apps re-reads the whole audit log on each load; App.title has no unit test; Home order tests anchor on strings.
- tests/test_web_sandbox.py::test_full_lesson_returns_to_the_sandbox_card flaked once in a full run.

## Teach extension, plan 2 leftovers (2026-11-12, branch `feat/teach-extension-build`)

- **Resume on another page** adds a step that opens that page (rule 7); today Resume there is refused.
- **Edit a step's level** in the side panel (plan 3, with the press grant).
- **Recording starts only through the side panel's poll**: if the panel is closed before the run goes live, nothing is recorded.
- **Disconnect mid-press**: a press being handled as the run stops can leave an orphan lesson file (no TEACH_OPEN).
- **Recorder**: a malformed port in the page address raises; a pause on an outside site stores that site; page key keeps `user:pass@`; an empty-space press doesn't clear a stale note.
- **Teach run input**: TEACH_IN read unbounded per pass; `run_id` None would accept lines without `run`; idle end untested.
- **Pairing**: `pair()` can't say "locked out"; pair audit written after the file; no bad-code or wrong-Host tests.
- **Panel**: `/ext/state` runs `propose` on every poll (watch latency); malformed lesson JSON gives 500 in `/ext/done`; the new-app audit scan trusts unsigned lines (Touch ID still required).
- **Extension**: a page can hide the ● Recording sign; "did not start" note stays until the next Teach.
- **Flaky test**: `test_teach_records_lesson_and_stops_task` (observer path) fails about 1 in 3 runs.
