# GOV-AIOS paper draft (v1, full length, for team review)

Version 1 · 11 Nov 2026 · exported from the team review doc, rev 49

## Abstract

AI agents now act on personal computers through browsers, desktop apps and shells, and defenses that live inside the model fall to adaptive prompt injection. We present GOV-AIOS, a governor for one person's laptop that enforces a capability boundary outside the model. Browser and desktop flows may act only on elements of page schemas captured from the operating system's accessibility tree, each one risk-rated and default-deny. Every run and every risky action is approved by a human who is physically present, through the platform's own biometric or PIN prompt (Touch ID on macOS, Windows Hello on Windows) combined with a typed code word, and the approval covers an artifact the governor wrote, not text the agent wrote. An authenticator-app session gives a short, screen-lock-bounded alternative. The same policy and the same hash-chained audit log govern two vendors' coding agents, Claude Code and OpenAI Codex, through administrator-owned managed configuration that the agent cannot edit. The governor has no network access and no model in its run-time loop. Our prototype runs on macOS, and a Windows port is in progress behind the same OS-neutral interfaces. We report live use on real sites: job vetting on Himalayas under its Personal Agent clause, an inbox briefing on Gmail, and form filling on Greenhouse and Lever that stops before Submit, plus live tests of both coding agents under governance. GOV-AIOS does not detect prompt injection; it limits what an injected agent can do and records what it tried.

## 1. Introduction

One person on one laptop can now hand routine work to agents. The work that motivated this paper is the first author's own: a morning brief that reads the newest emails aloud and, later, the day's calendar; vetting new job matches on a job board and sending the good ones to a local tracker; filling in each employer's application form; and writing code with Claude Code or Codex. The owner wants to say "give me my inbox brief" and hear it, or "run job vetting" and be told when it is done. Productivity is the goal. Governance is what makes the delegation safe enough to do.

Each of these tasks touches something the owner cares about: a mailbox, a logged-in account on a third-party site, personal details typed into a form, a source tree with credentials nearby. Each also reads text the owner did not write. An email, a job post or a README can carry instructions aimed at whatever agent reads it.

The agents doing this work read untrusted text: web pages, emails, repository files, command output. Defenses inside the model do not hold against an adaptive attacker. In the CAISI evaluation, attack success rose from 57% to 80% once attackers were allowed retries. Human approval prompts are the usual fallback, but Anthropic reports that Claude Code users accept 93% of manual permission prompts. Lies-in-the-Loop showed that an injected agent can misdescribe the very action it asks the user to approve.

Deterministic defenses do exist. CaMeL, Progent, FIDES, Conseca and ACE enforce policy in ordinary code, outside the model. To our knowledge they all work at the API tool-call layer. The guardrails that do act at the GUI layer, such as WebGuard and ShieldAgent, are learned classifiers. No system we found applies deterministic mediation to GUI actions on a real desktop and to coding agents under one policy.

GOV-AIOS is a governor that sits between every executor and the operating system. It makes four contributions, each worded as "to our knowledge" pending a final novelty check:

1. **A deterministic reference monitor over accessibility-tree actions.** Flows act only on elements of admin-approved page schemas, gated on page identity and on per-element risk, and only on sites whose terms allow a personal agent.
2. **Presence-bound approval of a governor-written artifact.** The admin approves a digest of the exact flow and pages through the platform's own biometric or PIN prompt (Touch ID, Windows Hello) and a typed code word, so an agent can neither approve itself nor act while the owner is away.
3. **One governance layer for GUI flows and two vendors' coding agents.** Claude Code and OpenAI Codex are governed through root-owned managed configuration, with one audit log across all executors.
4. **A network-less governor with no model at run time.** Flows are fixed steps, so text injected into a page has no model to steer, and output goes only to approved destinations.

The claim is deliberately narrow. GOV-AIOS does not stop untrusted text from reaching a coding agent's model. It confines what an injected agent can **do** and records what it tried. The intended headline result is the gap between attacks an agent proposes and attacks that actually execute.

We have used GOV-AIOS on live pages, not only test sites: on Himalayas, whose terms exempt a "Personal Agent" (clause 30A); on Gmail for the inbox brief; and on Greenhouse and Lever application forms, where it fills the form from the owner's prepared answers and stops before Submit. Both coding agents ran governed on the same laptop.

Section 2 gives background, and Section 3 the threat model. Section 4 presents the design and Section 5 what the owner sees: the panel, the prompts and the voice channel. Section 6 covers the implementation and the Windows port, Section 7 live use, and Section 8 the evaluation plan. Sections 9 to 11 cover related work, limitations and the conclusion.

## 2. Background

### 2.1 Accessibility trees and OS permissions

Desktop operating systems expose every window as an accessibility tree for screen readers: a hierarchy of elements, each with a role (button, link, text field, combo box), a name and a value. On macOS this is the AX API; on Windows it is UI Automation. A program that reads the tree can see a web page in Chrome the way a screen reader does, without screenshots, and can locate an element before it acts on it.

The same power is dangerous, so both systems gate it. macOS keeps per-app grants in TCC (Transparency, Consent and Control) for Accessibility, Input Monitoring and Screen Recording, and charges a process started from a terminal to the terminal app. Windows gates input injection into higher-integrity windows through UIAccess and integrity levels. GOV-AIOS relies on these grants: it is meant to be the only process that holds them, so an agent cannot drive the screen directly.

In our first capture of a logged-in job-matches page in real Chrome, the tree held 1,047 nodes, and each of the 20 job cards appeared as a consistent article element. This regularity is what makes a page schema possible.

### 2.2 Platform presence checks

Both platforms offer a local prompt that proves a person is at the device. macOS has LocalAuthentication, which shows Touch ID or the device password, with keys that can live in the Secure Enclave. Windows has Windows Hello, which accepts a fingerprint, face or PIN, with keys in the TPM. Both return to the caller only after the person acts, and both refuse while the session is locked. NIST SP 800-63B-4 ranks such device-bound authenticators above one-time codes from an authenticator app, because TOTP can be phished.

### 2.3 Managed configuration for coding agents

Coding agents read their settings from several layers, and the highest layer is meant for administrators. Claude Code reads a managed settings file that overrides user and project settings and can define hooks, permission rules, a sandbox and network limits. Its `PreToolUse` hook receives each tool call as JSON before it runs and can deny it. Codex reads a system `requirements.toml` whose values users cannot override, and has a similar `PreToolUse` hook. Both sandbox their shells with the OS: Seatbelt on macOS. Placing these files where only an administrator can write them is what turns them from preferences into policy.

### 2.4 Site terms and personal agents

Most sites forbid robots and scraping. A few now separate a personal agent from a bot. Himalayas, a remote-jobs board, bans robots and scraping in clauses 30 and 93 but exempts a **Personal Agent** in clause 30A: software acting for one person who has authorised it, using their own account, giving only truthful information, not bypassing security features or use limits, and not collecting or republishing data in bulk. By contrast, Upwork's Terms of Use (section 3.5) forbid any "robot, spider, scraper, or similar mechanisms" without written permission, and make no exception. We found no shopping or travel site with an exemption like 30A. GOV-AIOS treats such a clause as a precondition: a flow that acts on a third-party site needs a recorded terms verdict, and sites like Upwork are simply not automated.

## 3. Threat model and goals

We protect one admin's accounts, files and outgoing actions on one laptop (macOS today, Windows in progress). There is exactly one admin per laptop, by design.

|  |  |
| --- | --- |
| **Attacker controls** | Any page or file an agent reads (indirect prompt injection), including accessibility labels; the output of any LLM; requests to the local panel from other web origins |
| **Trusted** | The signed GOV-AIOS app; the OS and its presence check (macOS TCC, LocalAuthentication and Secure Enclave; Windows Hello and TPM); the admin at approval time, reading the governor-written summary |
| **Out of scope (stated as residuals)** | A malicious process running as the same user; physical coercion; kernel compromise; harm inside an allowed schema that the admin approves (measured, not prevented) |

The design goals follow from this:

- **No bypassing.** No executor, including an AI agent, acts on the OS before GOV-AIOS decides. GOV-AIOS is the only process that holds the OS powers to read the screen and inject input.
- **No unattended use.** A stolen or unattended laptop cannot run flows or approve actions; runs refuse while the screen is locked.
- **Stop instead of guess.** Anything not matched is denied.
- **Tamper-evident record.** Every request, decision, approver and outcome is logged, with identities and outcomes but never content (no page text, email bodies, typed text or secrets).

An explicit anti-goal: GOV-AIOS does not disguise automation to evade a site's bot detection. Sites whose terms forbid personal agents are not automated at all.

## 4. Design

The governor is a pure decision function, `allow | deny | ask`, over one request format. Every request names its executor, flow, flow digest, step and the page it was perceived on. Rules layer as ground rules, then flow policy, then approved lists, and anything unmatched is denied. The policy engine never sees screen or OS state directly, so it can be unit-tested in isolation.

> **Figure 1 · GOV-AIOS architecture.** Rendered in the review doc (https://claude.ai/artifact/RB63mqBQ9XCP5BxhgPVTYZ); not included in this Markdown copy.

Flows and both coding agents send every request to the governor; only an allowed request acts on macOS, and only the present admin approves.

### 4.1 Page schemas as capabilities

A flow is a fixed list of steps over page schemas. A schema is captured from the live accessibility tree and lists the page's identifying structure and its elements, each with a role and a risk level (read, navigate, write, submit, payment). Before any step, the governor identifies the page from the tree. An unidentified page stops the run.

A flow declares `max_element_risk`. A click on an element above it is refused, and typing is allowed only into declared search boxes. Output may go only to declared destinations; first contact with a new destination needs approval. Payment always needs a fresh approval.

What schemas cannot stop: harm that stays inside the schema, data exfiltrated by typing into an allowed field, and spoofed accessibility elements that match a schema's roles and labels.

### 4.2 Site terms as a precondition

Before a flow that acts on a third-party site can be approved, the site's terms are read through the real browser and the clauses on automation, agents, scraping and access are quoted to the admin with a proposed verdict: `allowed` (with its limits), `forbidden` or `unclear`. An `unclear` verdict is treated as forbidden until the admin decides. The verdict, the quotes, the date and the document version are stored in the flow's `site_terms` block and in the audit. A change away from `allowed` suspends the flow.

Himalayas shows how a clause turns into flow constraints. Clause 30A allows a Personal Agent acting for one authorised person, on their own account, without bypassing security or use limits and without bulk collection. The job-vetting flow therefore:

- uses the admin's own logged-in session, verified against the expected account before any site is opened;
- stops and hands control to the admin at any sign-in, CAPTCHA or unusual-activity page, and suspends the flow after repeated challenges;
- opens a small fixed number of job cards per run, from the first page only, because `robots.txt` disallows paged URLs;
- sends job data only to a service on the same laptop;
- never saves, applies or messages anyone (its `max_element_risk` is `navigate`).

The same gate excludes sites whose terms forbid agents. Upwork is out of scope for this reason. For employer application systems such as Greenhouse and Lever, which publish no candidate-side terms, the employer's notice governs and the admin presses Submit.

### 4.3 Presence-bound approval

Starting a flow and approving an `ask` both need proof that the admin is at the laptop. GOV-AIOS asks the platform's own presence check: Touch ID on macOS, and Windows Hello with its fingerprint, face or PIN on Windows. The prompt is shown by the OS, not by GOV-AIOS or the agent, so an agent cannot draw a fake one. Each prompt uses a fresh context with no reuse window, and the password fallback is hidden so that a shoulder-surfed password is not enough.

To sign in to the panel, the admin must also type a four-letter code word. The code word appears only inside the OS prompt, never on the page, so a page or a local process that drives the panel cannot read it. Following NIST SP 800-63B-4, the code is entered, not just compared.

For a run of everyday tasks, the admin can open a session with a six-digit code from an authenticator app (TOTP), set up once from a QR code. A session lasts at most 30 minutes, ends at screen lock, and lets the admin start already-approved apps without a new biometric prompt. It never approves a new flow, a payment or a first contact with a new destination; those always go back to Touch ID or Windows Hello. We rank TOTP below the device prompt because a one-time code can be phished. Refused attempts back off, and a fresh request does not reset the backoff.

Silence, a timeout, a locked screen or anything other than an explicit approval counts as a denial.

The admin approves a digest of the exact flow and the page files it uses. Any edit to either returns the flow to draft. A new flow passes a simulation rehearsal, where each step highlights its target and sends no input, before a live rehearsal and final approval.

### 4.4 Flow lifecycle

A flow moves from draft to simulation rehearsal to live rehearsal to approved, and any change sends it back to draft.

1. **Draft.** Written by the admin, or by an LLM through Studio (Section 4.8). A draft cannot run.
2. **Terms check** (third-party sites only), as in Section 4.2.
3. **Simulation rehearsal.** For each step, the target element is located through the accessibility tree and highlighted on screen, and the admin answers Yes, No or Edit. No mouse or keyboard events are sent; every step is logged as `SIMULATE`.
4. **Live rehearsal.** The flow runs for real, step by step, each step approved, with test data where possible.
5. **Approved.** The digest of the flow and its page files goes on the approved list. Later runs need only the run approval, plus any per-action approval the rules demand: payment always, first contact with a new destination, and resuming after a challenge the admin solved.

Upgrading GOV-AIOS itself does not reopen every flow: flow approvals bind to the flow and the page files it uses, and an engine release needs one recorded admin approval.

### 4.5 One layer for coding agents

Coding agents keep their own models, but their policy lives where they cannot write it.

- **Claude Code.** GOV-AIOS writes a managed settings file that only an administrator can change (root-owned on macOS). Every tool call first runs the GOV-AIOS hook (`onFailure: block`, 300 s timeout, managed hooks only). The sandbox is mandatory (`failIfUnavailable`), the network is limited to managed domains, writes are limited to approved folders, and agent configuration (`.claude/` at any depth, `.mcp.json`, `~/.claude.json`) and the GOV-AIOS data home are denied. Project MCP servers are disabled.
- **OpenAI Codex.** GOV-AIOS writes a root-owned `/etc/codex/requirements.toml`. Shell commands, file patches and plugin calls go to the GOV-AIOS hook, other hooks are ignored, the sandbox is locked to read-only or workspace-write, approval prompts stay on, and web search is off. Each file in a patch is checked against the approved folders.

For both, a command on the allow-list runs silently, any other command opens a GOV-AIOS dialog with Touch ID, and silence means deny. An emergency hotkey denies all later calls until the admin resumes.

### 4.6 No network, no model at run time

The governor and its runner drop their own network access before anything else (on macOS with `sandbox_init`), so they can reach only local sockets. The panel binds only to 127.0.0.1. Only the real browser reaches the web, on approved origins. A small launch helper, forked before the sandbox, runs only fixed commands it validates itself. Because a flow is fixed steps checked against schemas, no LLM reads page text while a flow runs. Even form filling uses a fixed rule to match a field's label to the admin's prepared answer, so text on a page cannot steer what is typed. Compare CaMeL, where the planner never sees data but a model still runs at execution time.

LLMs are used only to draft. A cloud model may see the structure of a page (roles, generic control names, step order) with all content masked, and its draft is untrusted until the admin approves it.

### 4.7 Audit

Every request, decision, approval (who, which channel, when), action, verification result, stop and error is appended to a hash chain in an append-only file. Elements are logged by schema id, never by accessibility name, because names can carry content. URLs keep only origin and path. A standalone verifier checks the chain without trusting the install. A same-user attacker can still rewrite the whole chain; signing each head with a Secure Enclave key and anchoring it off the machine are planned (Section 10).

### 4.8 Studio: LLM-written flows as untrusted input

Writing page schemas by hand does not scale, so Studio lets an LLM draft them, and treats every draft as untrusted. The admin opens a page and asks for a capture. Studio records the accessibility tree and masks content by role before anything leaves the laptop: field values, row text and the names of content items become placeholders, while the names of controls (buttons, tabs, form labels) stay so that the model can tell them apart. Across one Greenhouse and two Lever application forms, 101 of 101 form fields kept a usable label after masking.

The model gets the masked capture and no tools. Its reply is checked before the admin sees it:

- every element it names must match the captured tree;
- it may only raise a risk level, never lower the default for that role;
- permissions are trimmed to the actions the steps use;
- destinations must lie within the captured origins.

A draft that passes is saved as a draft, still subject to the lifecycle above. The model never approves, runs or edits an approved flow. Unmasked control names remain a channel through which a hostile label can address the model; the checks are designed to hold even then.

## 5. What the admin sees

The admin meets GOV-AIOS in three places: a local control panel, the OS presence prompt, and a voice channel for the daily briefs. Figures 2 to 4 are drawn from the prototype's own prompt text; we will replace them with screenshots, and add the Windows Hello versions, before submission.

### 5.1 Signing in to the panel

The panel is a local web page served on 127.0.0.1 with no JavaScript. It has a Talk page to start apps by name, an Apps page, a run queue, Approvals, the setup pages for the coding agents, and the audit log. A signed-out browser sees only a Locked page with one button. Pressing it raises the OS prompt, which carries a fresh four-letter code word; the admin then types that word into the page (Figure 2). A wrong word, a refused prompt or a screen lock while the prompt is up signs the browser out, and repeated refusals pause sign-in.

> **Figure 2 · panel sign-in (mock-up from the prototype's prompt text).** Rendered in the review doc (https://claude.ai/artifact/RB63mqBQ9XCP5BxhgPVTYZ); not included in this Markdown copy.

### 5.2 Approving an agent's action

When a coding agent asks for something outside its allow-list, GOV-AIOS, not the agent, writes the question (Figure 3). It names the agent, the tool, the folder and the exact command, and for a network fetch it says that approving also allows later fetches to that origin. The admin presses Approve and then passes the OS prompt. Deny, closing the dialog, or 60 seconds of silence all mean no, and the agent's tool call fails with a GOV-AIOS reason. Commands that contain secret-like values are denied outright and never offered for approval.

> **Figure 3 · a coding agent's request, the presence check, and its audit entry (mock-up).** Rendered in the review doc (https://claude.ai/artifact/RB63mqBQ9XCP5BxhgPVTYZ); not included in this Markdown copy.

### 5.3 Voice for the daily briefs

The end state is speech: the admin says "inbox brief" and hears the newest emails read aloud, or later "calendar brief" for the day ahead (Figure 4). Voice is a channel, not a new authority. A spoken command can start only an app that is already approved, only inside a session opened with the OS prompt or the authenticator code, and only while the screen is unlocked. It can never approve a new flow, a payment or a new destination. Speech recognition runs on the laptop and matches only fixed phrases (start, pause, skip, stop, approve, deny); anything else is "unrecognized", never interpreted freely. Audio and transcripts are not kept; the audit records only which phrase matched. Today, apps are started by typing in Talk and the result is spoken on the laptop; spoken commands and the calendar brief are designed but not yet built.

> **Figure 4 · the voice path for the inbox brief.** Rendered in the review doc (https://claude.ai/artifact/RB63mqBQ9XCP5BxhgPVTYZ); not included in this Markdown copy.

## 6. Implementation

The prototype is about 8,500 lines of Python in the `govaios` package, with about 840 unit tests. The macOS prototype reaches the OS through pyobjc (Accessibility, Quartz events, LocalAuthentication). The policy engine, the flow format, the page schemas and the audit log are OS-neutral; only the desktop adapter, the presence check, the network block and the installer are per-platform.

- **App identity.** GOV-AIOS ships as its own signed bundle (`com.govaios.cli`), launched by the OS through a LaunchAgent, so the TCC grants belong to GOV-AIOS and not to Terminal. macOS charges a process started from Terminal to Terminal, which is why a plain Python script cannot be the governor. Dev builds use a stable self-signed certificate with the hardened runtime on; release builds use Developer ID and notarisation.
- **Panel.** A local web UI on 127.0.0.1 with no JavaScript. It is where the admin signs in, approves, runs apps, sets up the coding agents and reads the audit log.
- **Root step.** Installing an agent's managed configuration needs the macOS administrator dialog. The root script copies the staged file only if its SHA-256 matches what the panel staged after the admin's Touch ID approval.
- **Desktop adapter.** An OS-neutral interface maps native accessibility roles to neutral ones, so a Windows adapter can follow behind the same interface.

Apple has deprecated `sandbox_init`, which GOV-AIOS uses for its network block. Claude Code and Codex rely on the same Seatbelt mechanism, so this is a portability risk we share with them.

### 6.1 The Windows port

A port to Windows is in progress behind the same interfaces. The mapping is direct for most parts:

| Part | macOS (built) | Windows (in progress) |
| --- | --- | --- |
| Reading the page | AX API through pyobjc | UI Automation |
| Presence check | Touch ID through LocalAuthentication, code word in the prompt | Windows Hello (fingerprint, face or PIN), code word in the prompt |
| Hardware key for signed approvals (planned) | Secure Enclave | TPM |
| App identity for OS grants | signed `.app` launched by a LaunchAgent | to be settled in the port |
| Coding-agent policy | root-owned managed settings and `requirements.toml` | administrator-only equivalents, to be confirmed per vendor |
| Governor network block | `sandbox_init` | to be settled in the port |

The neutral role table (`roles.yaml`) already maps native accessibility roles to neutral ones, so page schemas and flows written on one platform carry over to the other. We will report the port's status, and any part of the threat model it changes, in the final version.

## 7. Live use

We ran GOV-AIOS on the first author's own accounts and on live third-party pages, in real Chrome, between 5 and 11 November 2026. These runs are not an attack evaluation (Section 8). They show that the boundary is usable on real sites, and how it fails when a page does not match.

### 7.1 Browser flows on live pages

| Flow | Site and terms basis | What it may do | Outcome |
| --- | --- | --- | --- |
| Job vetting | Himalayas matches page; clause 30A (Personal Agent) | read and navigate only; at most a few cards from page one; deliver to a local tracker | ran end to end: opens each card, extracts title, company and description from the tree, delivers to the local tracker |
| Inbox brief | Gmail, the admin's own mailbox | read and navigate only (Compose, Reply and Forward are rated submit) | ran end to end: reads the 5 newest messages and reports sender and subject |
| Job application | Greenhouse and Lever forms reached from a tracked job; employer's notice governs | type only answers from the admin's prepared bank; Touch ID before the CV is attached; never press Submit | on a live Greenhouse form, 14 of 19 fields filled from the bank; the rest came back to the admin as panel cards; the run attached the CV and stopped before Submit |

Every flow first checks that Chrome is signed in to the expected account, and identifies each page from its tree before acting. A sign-in page, an unknown page or a challenge stops the run and hands control to the admin.

The form-filling runs were the most instructive, because each failure was a refusal, not a wrong action. The first live run stopped with "input refused: click point is not on the target element": the form lay below the fold, and the governor would not click whatever was under the pointer. Later runs surfaced three more mismatches between the tree and the screen:

- element bounds lagged the layout by about 18 pixels just after a page loaded;
- the page scrolled between the pointer move and the press;
- a combo box displayed "+91" where the option read "India +91", so the read-back check failed.

In each case GOV-AIOS stopped, or paused on a "fill this field in Chrome" card, instead of guessing. We then fixed the adapter: scroll into view before acting, wait for bounds to settle, retry before the press. Verify-after-act is what turns a brittle GUI automation into a fail-closed one.

### 7.2 Coding agents under governance

Both agents ran under GOV-AIOS on the admin's own laptop, each started in a new session after the managed configuration was installed. Codex CLI 0.162.1 passed all five live tests on 7 Nov 2026. Claude Code was run governed live on 7 Nov 2026 and again by the admin in November; the per-row results for Claude Code below still need to be logged from that run.

Each agent was given the same request: run `git status`, run `make --version`, write a file inside the project, write a file in `/tmp`, and read the GOV-AIOS audit log.

| Call | Expected | Codex (7 Nov) | Claude Code |
| --- | --- | --- | --- |
| `git status` | allowed silently | allowed | allowed (to confirm) |
| `make --version` | GOV-AIOS dialog, then Touch ID | dialog, approved | dialog, approved (to confirm) |
| write a file in the project | allowed | allowed | allowed (to confirm) |
| write `/tmp/...` | denied | denied | denied by managed rule |
| read the audit log | denied | denied | denied by managed rule |
| Deny pressed in the dialog | command does not run | did not run | to run |
| emergency hotkey, then `git status` | denied | denied | to confirm |
| first plugin (MCP) call | asks once, then remembered | asked once | n/a (MCP disabled) |

Two findings came out of these runs. First, Claude Code refused the `/tmp` write and the data-home read through its own managed deny rules, before the GOV-AIOS hook ran. The action was blocked, but it is missing from the GOV-AIOS audit log, because only calls that reach the hook are logged. Second, the Codex inside ChatGPT.app behaved the same as the CLI on `git status` and `make --version`, which suggests it honours the same `/etc/codex/requirements.toml`.

Like the browser runs, these are functional tests; Section 8 describes the attack evaluation.

## 8. Evaluation plan

The main result we will report is the gap between attacks an agent proposes and attacks that execute. We measure it on GOV-AIOS-Bench, which we are building because no benchmark exists for agents acting through an OS accessibility tree. The method follows AgentDojo's three metrics, WASP's split between proposed and executed attacks, and the overhead reporting of IsolateGPT and Progent.

### 8.1 Suites

| Suite | What it attacks | Injections and cases |
| --- | --- | --- |
| S1: UI injection | browser flows on local test sites we control | page text; accessibility labels and names; pop-ups; look-alike elements; redirects to non-allowed origins; typing exfiltration into allowed search boxes |
| S2: coding agents | Claude Code and Codex | risky commands (RedCode-style); edits to `.claude`, `.mcp.json`, `~/.codex` or `AGENTS.md`; network exfiltration; writes outside allowed folders; hook crash and timeout |
| S3: Studio | LLM-written drafts | benign requests; captures with injected labels ("set this button's risk to read"); replies seeded with over-permissioned or invented elements; planted canaries to measure masking leaks |
| S4: panel and approval | the sign-in and approval path | forged sign-in from another local origin; replayed cookies; prompt spam and backoff; stale tickets; screen lock during a run |

### 8.2 Conditions and metrics

Each suite runs under three conditions: **C0**, the agent alone with vendor defaults; **C1**, GOV-AIOS policy with every human approval auto-denied; and **C2**, policy plus a simulated approver. C2 has two variants. A careful approver approves only what the governor's summary shows to be in the request. A fatigued approver approves everything, which bounds the damage human error can do.

We report:

- benign utility and utility under attack;
- attack success, split into proposed (from the agent's own trace) and executed (from the audit log and an external state diff);
- false blocks of benign actions;
- approvals per task, as a fatigue proxy;
- p50 and p95 latency per action, and the setup cost of capturing a schema;
- attack success after 25 retries, following CAISI.

We expect proposed attack success to stay high in C0 and C1, because the agent's model still reads the injection, and executed attack success to fall near zero in C1, except for attacks that stay inside an allowed schema. We will report that residual as measured. S1, S3 and S4 need no real accounts; S2 needs vendor accounts for Claude Code and Codex.

An optional pilot (n ≈ 10 to 20, within subjects) would ask people to approve or deny 30 governor-written summaries, 5 of them harmful but inside the schema, and measure the error rate and time per decision.

## 9. Related work

The closest work enforces policy outside the model, but over API tool calls rather than GUI actions, and none binds approval to physical presence. These systems run in API environments such as AgentDojo, so we compare them by design, not by head-to-head numbers.

| System | Enforcement | Action domain | Human binding |
| --- | --- | --- | --- |
| [CaMeL](https://arxiv.org/abs/2503.18813) | deterministic (capabilities on values) | API tools | confirmation prompts |
| [Progent](https://arxiv.org/abs/2504.11703) | deterministic (privilege DSL) | API tools | none |
| [FIDES](https://arxiv.org/abs/2505.23643) | deterministic (IFC labels) | API tools | none |
| [Conseca](https://arxiv.org/abs/2501.17070) | deterministic, LLM-written policy | Linux computer use (prototype) | none |
| [ACE](https://arxiv.org/abs/2504.20984) | deterministic (static IFC on plan) | API tools | none |
| [IsolateGPT](https://arxiv.org/abs/2403.04960) | isolation (hub and spoke) | third-party apps | per-app consent |
| WebGuard, ShieldAgent (arXiv:2507.14293, 2503.22738) | learned classifier | web GUI | none |
| Claude Code, Codex defaults | sandbox plus model prompts | shell, files | click to approve |
| **GOV-AIOS** | **deterministic (page schemas, hooks)** | **GUI (AX tree) and coding agents** | **Touch ID plus typed code over a governor-written digest** |

CaMeL and Progent are the nearest analogues. Progent's default-deny privilege policies resemble our schemas; ours are captured from the real accessibility tree and curated by a human rather than generated. The Design Patterns paper ([Beurer-Kellner et al.](https://arxiv.org/abs/2506.08837)) states the principle we follow, that untrusted input must not be able to trigger consequential actions. On approval, Anthropic's 93% acceptance figure and Lies-in-the-Loop motivate approving a governor-written artifact; presence binding fixes self-approval and away-from-keyboard use, not fatigue. Tamper-evident logging follows Schneier–Kelsey and Crosby–Wallach. Robotic process automation runs fixed GUI steps with no model, but without this kind of governance; we have not yet surveyed its selector-governance features.

**Attacks on GUI and computer-use agents.** Attacks on agents that read screenshots, accessibility trees or the DOM succeed often. Pop-ups reach an average 86% attack success on OSWorld and VisualWebArena ([Zhang et al.](https://arxiv.org/abs/2411.02391)). EIA's form and mirror injection extracts specific personal data in up to 70% of cases ([Liao et al.](https://arxiv.org/abs/2409.11295)). VPI-Bench reports up to 100% on browser-use agents ([Cao et al.](https://arxiv.org/abs/2506.02456)). WASP finds partial hijacks in 16 to 86% of cases but full attacker goals in only 0 to 17% ([Evtimov et al.](https://arxiv.org/abs/2504.18575)), which motivates our split between proposed and executed attacks. ZombAIs made a computer-use agent download and run a command-and-control binary from one web page. Most of these attacks add elements that are not in a captured schema, and such elements cannot be acted on whatever the model believes. Universal triggers in the accessibility tree ([Johnson et al.](https://arxiv.org/abs/2507.14799)) and Android accessibility hijacking ([arXiv:2507.04227](https://arxiv.org/abs/2507.04227)) show that the tree itself can be attacker-influenced. We therefore use the tree for structural identification, not as instruction text. We found no attack on the macOS AX API.

**Agent configuration and tool integrity.** Agent-writable configuration defeats approval. CurXecute (CVE-2025-54135) let a prompt injection write Cursor's MCP config and run code, and MCPoison (CVE-2025-54136) let an approved config change later without re-approval. MCP tool poisoning exfiltrated SSH keys through an innocent-looking tool. Claude Code's hooks do not block on a crash or timeout unless `onFailure: block` is set. GOV-AIOS places the policy where the agent cannot write it, sets the hook to block on failure, and denies edits to agent configuration at any depth.

**Human approval.** Users approve most prompts: 93% in Claude Code, and runtime approval appears in 15 of 21 production agent systems ([Wang et al.](https://arxiv.org/abs/2605.24309)). Lies-in-the-Loop shows the agent can misdescribe what it asks to do. Usable-security work on warning habituation predicts that a constant-looking prompt is approved by reflex. GOV-AIOS addresses who answers and what they answer about, by binding the approval to presence and to a governor-written artifact. It does not solve fatigue, and we measure approvals per task rather than claim otherwise.

**Tamper-evident logging.** Schneier and Kelsey make pre-compromise entries impossible to modify undetectably; Crosby and Wallach show tampering is detectable only against a commitment held outside the logger; forward-secure schemes address truncation. Our chain detects edits but not a full rewrite by the same user, which is why signed and anchored heads are next.

**Workflow synthesis.** AWM, ASI and SkillWeaver induce reusable web skills from agent trajectories and check that they succeed; ASI re-executes each skill before accepting it. None checks the skill against security invariants. Studio takes the next step on that line: an LLM draft is accepted only if it matches the captured tree, never lowers a risk level, uses no more permissions than its steps need, and is approved by a present human.

**Governance frameworks.** OWASP's LLM06 (excessive agency) and the Agentic Top 10, the EU AI Act's record-keeping and human-oversight articles (12 and 14), NIST AI RMF MANAGE 2.4 and ISO/IEC 42001 all prescribe point-of-action controls and logs. They assume an organisation with a fleet. GOV-AIOS is an endpoint enforcement point that such a control plane could consume, and we claim voluntary alignment, not compliance.

The name GOV-AIOS must be distinguished from AIOS ([arXiv:2403.16971](https://arxiv.org/abs/2403.16971)), an unrelated LLM agent operating system.

## 10. Limitations and discussion

The biggest open weaknesses are that approvals and the audit chain are not yet signed, so a same-user process is the main residual. Each item below is either planned work or a stated limit.

| Weakness | Status |
| --- | --- |
| Touch ID returns an unsigned yes/no; same-user code could spoof it | Planned: a Secure Enclave key, usable only with Touch ID, signs (flow digest, pages digest, nonce, time) |
| The audit chain can be rewritten by the same user | Planned: sign each head and anchor it off the machine; truncation before the first anchor stays a limit |
| Harm inside an allowed schema that the admin approves | Measured in the evaluation, not prevented |
| Exfiltration by typing into an allowed field | Limited by typing only into search boxes and by destination allow-lists |
| Accessibility-tree spoofing | Pages identified by structure, not labels; to be evaluated |
| Coding agents' models still read untrusted text | By design: GOV-AIOS confines actions, not inputs |
| Claude Code refusals by its own managed rules are not audited | Open (Section 7.2) |
| Codex: tools other than shell, patch and plugins skip the hook; no network allow-list yet | Open; web search is off, sandbox network off by default |
| Approval fatigue is unmeasured | Optional pilot, n ≈ 10–20 |
| Schemas break when sites change | Measure the breakage rate; re-capture through Studio |
| No fleet layer (registry, central policy, SIEM, remote kill), one admin | Deliberate scope: an endpoint enforcement point a control plane could consume |

Three further limits belong with the table. **Voice** does not yet verify whose voice it is; it relies on the session having been opened by the OS prompt or the authenticator code, and it can only start approved apps. Speaker verification is future work. **Platform reach**: the threat model was built on macOS, and the Windows port may change what "only GOV-AIOS holds the input powers" means in practice. We will state the differences once the port is done. **Halt semantics**: the emergency stop denies every later action and ends a flow at its next step, but it does not kill a coding agent's command that is already running, and there is no rollback.

**Is a personal-agent clause enough?** Clause 30A gives a clear basis for one site, but we found no comparable clause on shopping or travel sites. Most live-web agent benchmarks either exclude logged-in tasks or do not address site terms at all. Recording a per-site terms verdict, and refusing to automate sites that forbid agents, narrows what GOV-AIOS can do. We think that is the right default for an agent acting on someone's own accounts.

**Why no model at run time?** Removing the model from the run-time loop costs flexibility: a flow cannot adapt to a page it has never seen. We accept that cost because it removes the channel prompt injection relies on. When a page changes, the flow stops, and the fix is a new capture and a fresh approval.

Next steps toward submission are signed approvals and an anchored audit, then GOV-AIOS-Bench and the evaluation in December, the Windows port, and a full citation and novelty pass. The target is USENIX Security '27 cycle 2 (paper due 26 Jan 2027), with an arXiv cs.CR preprint after submission.

## 11. Conclusion

Agents that act on a person's own laptop should not be trusted to police themselves. GOV-AIOS moves the decision out of the model and into a small governor that the agent cannot write to, that has no network and no model of its own, and that answers to one person who must be physically present. Browser flows act only on captured, risk-rated elements of pages on sites whose terms allow a personal agent. Coding agents keep their models, but every command, edit and plugin call passes a non-LLM check. Everything is recorded in one hash-chained log. Live use on Himalayas, Gmail, Greenhouse and Lever, and with Claude Code and Codex, shows the boundary is usable, and that it fails by refusing rather than guessing. The evaluation will measure how much of what an injected agent proposes it can still do.

## Open questions for the team

This draft is written at full length, roughly 10 to 12 pages in USENIX format, with the rest of the 13 kept for evaluation results; we can trim it for each audience. Please weigh in on these:

- [ ] **Title and name.** Keep "GOV-AIOS" with a line separating it from Rutgers' AIOS, or retitle around "presence-bound capability boundaries for GUI and coding agents"?
- [ ] **Lead contribution.** Should the paper lead with coding agents (working and tested today) or with GUI flows (the stronger novelty claim, less evaluated)?
- [ ] **Studio.** Include LLM-written drafts as a contribution, or cut it to "design and early results" if it is not done by end of November?
- [ ] **Claude Code results.** Log the per-row outcomes of the latest governed run so the Section 5 table can drop "to confirm".
- [ ] **Approval pilot.** Run the small pilot (n ≈ 10–20), or ship with no user study?
- [ ] **Authors and affiliation.** Author list, Avanta Labs affiliation, and the arXiv cs.CR endorser.
- [ ] **AI-use disclosure.** The system and this draft were built with Claude through Claude Code; confirm the acknowledgement wording.
- [ ] **Citations.** Every reference must be checked against the actual paper before submission (USENIX treats invented references as misconduct); WebGuard, ShieldAgent and the CAISI figure still need their sources added.

* [ ] **Screenshots.** Figures 2 to 4 are mock-ups drawn from the prototype's prompt text. Replace them with real captures of the panel's Locked page, a Claude Code approval dialog with its Touch ID prompt, and the Talk page, plus Windows Hello versions once the port has them.
* [ ] **Voice claims.** The draft says spoken commands and the calendar brief are designed, not built. Confirm, or tell us what has been built since.
* [ ] **Windows port.** Fill in the three "to be settled" rows in Section 6.1: app identity for OS grants, the governor's network block, and the administrator-only paths for each agent's policy.
* [ ] **Live-run numbers.** Confirm the Greenhouse result (14 of 19 fields filled from the bank) and add the Lever runs and the number of Himalayas and Gmail runs.
