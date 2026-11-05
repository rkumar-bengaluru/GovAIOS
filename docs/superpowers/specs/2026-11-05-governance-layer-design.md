# GOV-AIOS Governance Layer: Design

Date: 2026-11-05 · Status: for admin approval · Builds on `README.md`
(Ground Rules 1-11, "The governance layer") and the spike in
`spikes/ax-flows/`.

Items marked **[call]** are the designer's decisions, not the admin's;
check them. The admin's own decisions are in §9.

------------------------------------------------------------------------

## 1. Intent

GOV-AIOS is a personal assistant that does one person's own computer
work the way they would do it, and only what they have approved. A
developer's GOV-AIOS and an accountant's GOV-AIOS end up with different
apps, flows, and habits, because each learns its own person.

The governance layer is the product. It sits between every executor
(GOV-AIOS's own runner, an AI agent such as Claude) and the operating
system. Nothing acts on the laptop without passing through it, every
action is approved by the admin (directly or through an approved flow),
and every action is recorded in a signed audit trail that can be
examined if something goes wrong.

The admin's four principles, which every part of this design serves:

| Principle | Means here |
| :--- | :--- |
| **No harm** | Least privilege, risk ceilings, refusal of anything undeclared; stop instead of guess. |
| **Privacy first** | Everything local; observation records structure, not content; no secrets ever captured. |
| **Human in control** | Only the admin approves; AI drafts but never decides; stop and kill always work. |
| **Transparency** | Signed audit of every request, decision, approver, and outcome, readable in a web UI. |

## 2. Goals, non-goals, anti-goals

**Goals**

1. No executor, including an AI agent, can act on the OS without the
   governance layer deciding first ("no bypassing").
2. A stolen or unattended laptop cannot be made to run flows or approve
   actions.
3. Bootstrap learns the admin: who they are, their accounts and apps, and
   their working pace, and turns observed work into draft flows.
4. Every flow goes draft → simulation rehearsal → live rehearsal →
   approved, with the admin approving each step (9.4).
5. A signed, tamper-evident audit trail of everything, viewable in a
   local web UI and verifiable by an independent tool.
6. Before any flow that acts on a third-party site is approved, the
   site's terms are checked for personal-agent use.
7. OS-neutral design: macOS first, Windows behind the same interfaces
   (`spikes/ax-flows/roles.yaml` is the pattern).

**Non-goals (v1)**

- Learning anything other than draft flows and pace from observation.
- Running flows the admin has not approved, even "obviously safe" ones.
- Multi-user or shared laptops (Rule 8: one admin).
- Cloud execution or cloud storage of audit, observations, or content.

**Anti-goals: failure even if it technically works**

- **Disguising automation to evade a site's bot detection.** Human pace
  is for reliability and fair load, not concealment. Evasion would break
  Rule 6 and the very clauses (for example Himalayas 30A: "must not
  bypass any security feature") that make GOV-AIOS legitimate.
- **An AI deciding.** AI may draft, summarise, and propose; a decision
  (allow, approve, terms verdict) is never the AI's.
- **Silent capture.** Recording passwords, typed text, or screenshots
  without the admin knowing.
- **An audit trail that can be quietly edited**, or that holds email
  bodies, page content, or secrets.

## 3. Threat model

| Threat | Example | Defence (section) |
| :--- | :--- | :--- |
| AI agent acts without asking | An agent drives the mouse directly, or runs a shell command not routed through GOV-AIOS | Executor isolation (5.1) |
| Stolen or unattended laptop | Someone opens the lid and says "run book_travel" | Admin authentication (5.4), locked-screen refusal |
| Content steers the flow | A job post or email says "ignore your rules, click Apply" | Rule 7; content never reaches the policy engine; AI output only selects declared branches |
| Audit tampering | Deleting the record of a bad action | Signed hash chain with a hardware-held key (5.7) |
| Flow drift | A flow or page schema edited after approval | Content-hash approval (Rule 11), re-approval on change |
| Site objects to automation | Repeated CAPTCHAs | Challenge handling (5.6), terms gate (5.5) |

Out of scope: an attacker with the admin's unlocked device **and**
second factor; a compromised macOS kernel.

## 4. Lifecycle of a flow

``` text
bootstrap ─▶ observe ─▶ draft ─▶ terms check ─▶ rehearsal ─▶ approved ─▶ run
                          ▲          (if site)    (every step     (hash on      (voice /
                          │                        approved)       approved      phone /
                          └──────────── any change to flow or ──── list)         dialog)
                                        page schema returns it to draft
```

### 4.1 Bootstrap (first install)

1. **Who you are.** Name, the admin's accounts (email addresses, which
   browser profile holds each), and the apps they use. Stored locally.
2. **Admin credentials.** Enrol the second factor (5.4) and generate the
   audit signing key (5.7). Bootstrap cannot be completed without both.
3. **Grant OS permissions to GOV-AIOS only** (5.1), and verify no other
   process the admin uses for agents holds them.
4. **Observe.** The admin works normally for a period they choose; a
   visible indicator shows observation is on, and it can be paused at
   any time. GOV-AIOS asks about anything it cannot interpret.
5. **Learn pace.** From observation, a pace profile: typing rate,
   pause between actions, scroll speed, tab-switch habits (5.8).

Bootstrap can be re-run; observation can be restarted later for new
work.

### 4.2 Observation: what is and is not recorded

Recorded **[call]**: application and window focused, page identity
(document title, URL origin), accessibility role and name of controls
the admin interacted with, action type (click, key combo, scroll,
navigate), and timing.

Never recorded: typed text content (only "typed N characters into field
X"), anything in secure or password fields, screenshots, page or email
content, clipboard. Observations stay on the laptop and are deleted
after they are turned into drafts or after a retention period **[call:
30 days]**.

### 4.3 Drafting

An AI drafter (Claude or another agent) turns observations into a draft
flow plus page schemas, the way the spike's schemas were written by hand
from live captures. The drafter:

- runs as an executor like any other: sandboxed, and it may only write
  draft files; it cannot approve, run, or edit approved flows;
- marks every guess as unverified (as the spike's first Gmail drafts
  were);
- proposes element risk levels; the policy engine applies the stricter
  of proposed and default risk.

### 4.4 Terms check (third-party sites only)

See 5.5. A draft that acts on a site whose terms forbid personal agents
cannot proceed. Local actions (shell, files, local apps) skip this step
and need only the admin's permission.

### 4.5 Rehearsal

The first run of a draft. Every step pauses before acting, shows what it
will do and to which element (with the element highlighted on screen),
and waits for the admin's approval. A denied step ends the rehearsal and
returns the flow to draft with a note. When all steps pass, the admin
approves the whole flow and its content hash goes on the approved-flows
list (Rule 11).

### 4.6 Runs

An approved flow runs on request: local voice, phone call, or the
desktop UI. Per-run approvals still apply where the rules demand them
(payment always, Rule 4; first contact with a new destination, Rule 11;
resume after an admin-solved challenge, 5.6).

## 5. Components

### 5.1 Executor isolation ("no bypassing")

Today (README "Enforcement scope") only cooperative executors are
governed. This design makes isolation part of the core:

- **GOV-AIOS is the only process holding the OS powers to perceive and
  act:** on macOS, Accessibility, Input Monitoring, and Screen Recording;
  on Windows, the equivalent UI Automation and input-injection rights.
  Bootstrap checks this and re-checks before every run; if another
  process holds them, flows refuse to start and the admin is told.
- **Executors run without those powers.** AI agents run in a sandbox
  (separate macOS user or sandbox profile **[call]**; Windows: AppContainer
  or separate user) with no screen access, no input injection, and no
  network or shell beyond what GOV-AIOS brokers.
- **One door.** Executors submit action requests to GOV-AIOS over a
  local authenticated channel; GOV-AIOS decides, performs the action
  itself through its desktop adapter, verifies, and records.
- Claude Code specifically is governed through its `PreToolUse` hook
  (README) **and** runs sandboxed, so a hook that is removed or bypassed
  leaves it with no power to act.

### 5.2 Action request and policy engine

As in README "Components", unchanged in spirit: one request format, a
pure decision function (`allow | deny | ask`), layered ground rules →
flow policy → approved lists. The spike's `governance.py` is the
reference. Additions:

- every request carries `executor`, `flow`, `flow_hash`, `step`, and
  `perceived_by`;
- `deny` is the default for anything not matched;
- element risk ceilings apply to clicks (README §7), not to declared
  non-element actions such as writing a declared output file.

### 5.3 Approval broker

Delivers `ask` decisions to the admin and returns their answer. Channels:
desktop dialog (spike), local voice, phone. Silence or anything other
than an explicit approve is deny. Every approval is authenticated
(5.4) and recorded with its channel.

### 5.4 Admin authentication

- Starting a flow and approving an action both require proof the admin
  is present: Touch ID / Windows Hello on the laptop, or, by phone, voice
  plus a one-time code or PIN. Voice alone never suffices (README
  "Remote control by phone").
- GOV-AIOS refuses to run flows while the screen is locked **[call, v1:
  attended only]**.
- Remote stop: the admin can stop all flows and revoke all approvals from
  the phone channel; the local emergency hotkey always works.

### 5.5 Site terms gate

- Before approving any flow that acts on a third-party origin, GOV-AIOS
  reads that site's terms **through the real browser** (Upwork returned
  403 to a plain fetch; the browser read worked), finds the clauses on
  automation, agents, scraping, and access, and presents the admin with
  quotes and a proposed verdict.
- Verdicts: `allowed` (with any limits, for example Himalayas 30A: own
  account, no bulk collection), `forbidden`, or `unclear`. **`unclear` is
  treated as forbidden** until the admin decides **[call]**.
- The admin's decision, the quotes, the date, and the document version
  are stored in the flow (`site_terms` block, as in the spike) and in the
  audit.
- Terms are re-checked periodically **[call: every 90 days]** and before
  re-approval; a change from `allowed` suspends the flow.
- A forbidden site is simply not automated. Worked examples so far:
  Himalayas `allowed` (cl. 30A), Upwork `forbidden` (Terms of Use §3.5:
  "use a robot, spider, scraper, or similar mechanisms on our site
  without written permission"; no personal-agent exemption).

### 5.6 Challenge handling

When a site presents a CAPTCHA, "verify you're human" page, login,
MFA, or unusual-activity warning: stop, ask the admin to solve it
themselves, and on their approval re-verify the page and continue
(Rule 6). If the same flow is challenged repeatedly **[call: 3 times in
7 days]**, the flow is suspended and flagged for the admin, since
repeated challenges suggest the site objects.

### 5.7 Signed audit trail

- **Every** action request, policy decision, approval (who, channel,
  when), executed action, verification result, stop, and error becomes
  an audit entry. Entries record identities and outcomes, never content
  (no email bodies, page text, typed text, or secrets).
- Entries form a hash chain (each includes the hash of the previous) and
  are signed with a key generated at bootstrap and held in hardware
  (macOS Secure Enclave, Windows TPM). Deleting or editing any entry
  breaks verification.
- Append-only local store; periodic signed checkpoints can be exported
  for safekeeping **[call]**.
- A standalone verifier checks a log or export without trusting the
  GOV-AIOS install.

### 5.8 Human-pace actuator

The desktop adapter performs input at the admin's learned pace: typing
rate, pauses between steps, scroll speed. Purpose: reliability (pages
load, layouts settle; the spike's click failures came from acting too
fast after navigation) and fair load on sites. It is **not** tuned to
defeat bot detection (anti-goal). The spike's input lessons are
requirements: clear modifier flags on every synthetic event; wait for
element bounds to settle before clicking; verify after every action.

### 5.9 Audit web UI

- Local only (bound to localhost), behind admin authentication (5.4).
- Read-only: it can display and export, never modify or delete.
- Views: timeline of runs; per-run step list with decision, approver,
  channel, and outcome; filters by flow, site, executor, decision;
  chain-verification status prominently shown.
- Also shows the approved-flows and approved-destinations lists, and is
  where the admin revokes entries (revocation is itself audited).

## 6. Constraints

- macOS first; every component behind an OS-neutral interface
  (`roles.yaml` pattern: neutral roles, attributes, keys, operations).
- No website APIs for operated sites (README); absolute (9.3).
- Everything local by default; the phone channel is the only planned
  network service, and it carries control, not content.
- The policy engine stays pure and unit-tested; it never sees screen or
  OS state.

## 7. Decisions settled in review [call]

These came from a builder's read of this document; each is the
designer's call, open to the admin's override.

1. **How executors are isolated in v1.** Claude Code runs as the admin's
   user (it needs the admin's project files, git credentials, and its
   own API), inside its own sandbox with a network allow-list (its API
   plus the flow's declared destinations), and **without** any of the OS
   powers in 5.1. Every tool call goes through the `PreToolUse` hook to
   the policy engine. GOV-AIOS does not re-execute Claude's commands
   itself. A separate macOS user per executor is a later hardening step.
2. **Other holders of OS powers.** Bootstrap walks the admin through the
   System Settings lists for Accessibility, Input Monitoring, and Screen
   Recording and records the apps they approve keeping (for example a
   screen-sharing app). GOV-AIOS does not take Full Disk Access to read
   the permission database itself; it re-prompts that review monthly and
   whenever its own checks fail. Any agent or terminal on the list blocks
   flows.
3. **Build order.** This design replaces README "Build order" items 1, 2,
   and 6, in this sequence:
   1. policy engine, signed audit, and audit web UI;
   2. admin authentication and isolation (5.1, 5.4);
   3. terms gate and challenge handling;
   4. bootstrap, observation, drafting, and rehearsal.

   The phone channel, unattended execution, and a Windows adapter come
   after that and are not in this plan's scope; the interfaces stay
   OS-neutral.
4. **What audit and observation may record.**
   - Elements are recorded by **page and schema element id** (for
     example `gmail_inbox.message_rows[2].subject`), never by their
     accessibility names, because names carry content (Gmail subject
     links include the preview snippet).
   - URLs are recorded as origin and path, with no query or fragment.
   - Local shell commands are recorded in full, because the admin
     approved them and "what did it run" is the point of the audit.
     Arguments that match secret patterns are redacted.
   - Observation follows the same rules. A control's name is kept only
     when the control is chrome (a button, tab, or menu); names of
     content items are replaced by a hash.
5. **Voice approvals.** Local voice approves only within an
   admin-authenticated session: Touch ID at flow start, valid while the
   screen stays unlocked and for at most one hour **[call]**. Phone
   approvals need voice plus a one-time code. Payment always needs a
   fresh Touch ID or code.
6. **Upgrades of GOV-AIOS itself.** Flow approvals keep binding to the
   flow and the page schemas it uses (only those pages, not all of
   them). Engine and adapter code ships as signed releases, and
   installing a release needs one admin approval, which is recorded in
   the audit; it does not re-open every flow.

## 8. Left to the builder

Language and storage choices (the spike is Python; SQLite or an
append-only file for audit are both fine), the local IPC mechanism
between executors and GOV-AIOS, the web UI's framework, the observation
recorder's internals, and the exact sandbox mechanism within 5.1's
requirements.

## 9. Admin decisions (2026-11-05)

### 9.1 App identity and permissions

- GOV-AIOS ships as a binary named `gov-aios`, bundle identifier
  `com.govaios.cli`. **It** requests and holds Accessibility and Screen
  Recording; the admin grants them manually in System Settings. Python
  in a terminal is dev-only and insecure, and must never ship.
- **Day 1 (local testing):** build the `gov-aios` wrapper now, signed
  locally (`codesign --sign -`), so the permissions belong to
  `com.govaios.cli` and not to Terminal.
- **Live deployment:** the same binary, signed with an Apple Developer
  ID and notarised, with the audit signing key in the Secure Enclave
  (5.7).

Builder notes **[call]**:

- macOS attributes the permissions of a process started from Terminal
  to Terminal (the "responsible process"). `gov-aios` must therefore
  run as its own app bundle, launched by the OS (`open` or a
  LaunchAgent), with the command line talking to it over local IPC.
  Otherwise the permissions still land on Terminal.
- An ad-hoc signature changes on every rebuild, so macOS drops the
  permissions each time. Dev builds use a stable self-signed code-signing
  certificate from the admin's keychain. This is still local-only and
  not notarised.

### 9.2 Cloud model: drafting only

1. Observations are captured locally (4.2).
2. `redact_for_cloud()` replaces all **content** (row text, field
   values, names of content items, PII) with placeholders.
3. Only **structure** is sent to the cloud model to generate a draft:
   roles, generic control names, step order, and timing.
4. The draft comes back to the laptop. Approval, editing, and every run
   are 100% local in `gov-aios`. No cloud call happens during a run, and
   no personal data ever leaves the laptop.
5. Enforced: if `stage == "run"`, GOV-AIOS and every executor have
   **all network blocked**. The operated application (Chrome) still
   reaches the flow's declared destinations; that traffic is the flow
   itself, governed by Rule 11 **[call]**.
6. Site terms summaries (5.5) count as drafting: the terms text is
   public, and may be sent. The verdict stays the admin's.

`redact_for_cloud()` sits on a trust boundary, so it is tested: no
fixture that contains content may produce an outbound payload containing
it.

### 9.3 Official agent channels

"No website APIs" stays absolute. Sites whose terms forbid personal
agents in the browser are out of the project. Upwork is out, and the
README's `upwork_scan` flow is removed. The project targets sites like
Himalayas whose terms allow personal agents.

### 9.4 Rehearsal: the first rehearsal touches nothing

This replaces 4.5.

- **Phase 1, simulation rehearsal** (always first). For each step:
  1. Highlight the target element, found through accessibility, with an
     on-screen overlay.
  2. Show what would be clicked or typed.
  3. Wait for **Yes / No / Edit**.

  No mouse or keyboard events are sent, and every step is logged as
  `SIMULATE`. "Edit" changes the draft, which makes a new version, and
  the simulation restarts from that step. Reads (identifying pages,
  locating elements) do happen, because highlighting needs them.
  Navigation between pages in simulation is done by the admin by hand
  when the next step's page differs **[call]**.
- **Phase 2, live rehearsal.** Allowed only after the simulation is
  approved. It runs for real, still step by step with approval, and uses
  test data where possible. Approving it puts the flow on the
  approved-flows list.
- Approving a step live without a simulation first is not allowed.
