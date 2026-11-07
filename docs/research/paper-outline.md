# Paper outline (working title)

**Working title:** *Presence-Bound Capability Boundaries for GUI and Coding Agents*
**Alternative:** *GOV-AIOS: Governing AI Agents on the Desktop with Human-Bound Approvals*

The system name and its distinction from Rutgers' AIOS (arXiv 2403.16971) are an admin decision.

**Target:** USENIX Security '27 cycle 2: 13 body pages, plus references and the Open Science and ethics appendices.
**Authors:** the admin and collaborators, Avanta Labs.
**Acknowledgements:** disclose that the system and paper were designed and built in collaboration with Claude (Anthropic) via Claude Code.

## 1. Introduction (1.25 pp)
- **Motivation (the admin's own, 2026-11-08):** one person on one laptop handing their routine work to agents to get more
  done, e.g. vetting job matches on Himalayas into JobLens, a Gmail briefing, making repo demo videos with Walker,
  the routine parts of JobLens's web UI, and coding with Claude Code and Codex. Productivity is the goal; governance is
  what makes delegating it safe enough to do.
- **Problem:** agents now act through GUIs and shells on personal machines. Model-level defenses fall to adaptive attacks ("The Attacker Moves Second"; CAISI: 57% → 80% with retries).
- **Prior work's gap:** deterministic defenses (CaMeL, Progent, FIDES, Conseca, ACE) govern API tool calls. GUI guardrails (WebGuard, ShieldAgent) are learned. Approval prompts are fatigued (Claude Code users accept 93%) and can be manipulated (Lies-in-the-Loop).
- **The idea:** a governor outside the model that:
  1. lets agents act only on elements of page schemas captured from the real accessibility tree, each risk-rated, with default-deny and an allow-list of sites;
  2. binds each run to a human who is physically present, approving an exact artifact the governor wrote;
  3. governs browser flows and coding agents under one policy and one tamper-evident log;
  4. lets an LLM write new automations safely, by treating its output as untrusted;
  5. keeps the governor itself off the network and keeps models out of the run-time loop: a browser flow is fixed
     steps, so text injected into a page has no model to steer, and data leaves only to approved destinations.
- **Contributions:** N1–N8 from the report plus N9 (network-less governor, no model at run time), worded "to our knowledge".
- **The claim, worded carefully** (admin and Claude, 2026-11-08). Not "prompt injection is solved". Instead:
  - *browser flows:* no model reads untrusted content while a flow runs, and the governor process has no network
    (`sandbox_init`); only the real Chrome talks to the web, on approved origins, and output goes only to approved
    destinations;
  - *coding agents:* their models still read untrusted text (repo files, command output, packages, plugin results).
    GOV-AIOS does not stop that text reaching the model; it confines what an injected agent can **do** (a non-LLM
    check on every command, edit and plugin call; egress allow-listed; the sandbox locked on) and records it.
- **Headline result:** the gap between proposed and executed attacks (S1–S3), with the overhead.

## 2. Background and threat model (1 pp)
- macOS TCC, the accessibility tree, LocalAuthentication and the Secure Enclave.
- Claude Code managed settings and hooks; Codex `requirements.toml` and hooks.
- The threat model from `evaluation-plan.md`, with the residuals stated up front. Network-borne residuals to state:
  injected text can still reach the admin in a report (e.g. the Gmail briefing); Studio's LLM sees masked page captures
  at authoring time; coding agents' models read untrusted content (see the claim in §1).

## 3. Design (3.5 pp)
- **3.1 Architecture:**
  - the signed app;
  - the launch helper forked before the sandbox;
  - the panel (127.0.0.1, no JavaScript);
  - the LaunchAgent.
- **3.1b No network, no model at run time:**
  - the governor and its runner apply `sandbox_init` before anything else: no network except local sockets; the panel
    binds only to 127.0.0.1; delivery reaches only `localhost:8100` (JobLens);
  - the launch helper is the one unsandboxed part and runs only fixed commands it validates itself;
  - flows are fixed steps checked against page schemas: no LLM interprets page text while a flow runs, so
    content injection changes nothing the flow does (compare CaMeL, where the planner never sees data but a model
    still runs at execution time);
  - what this does not cover: Chrome's own network, what the admin reads, coding agents' models.
- **3.2 Presence-bound authorization:**
  - Touch ID with a typed code word (after Phase 0);
  - TOTP 30-minute sessions that end at lock;
  - Secure Enclave–signed approvals over digests (Phase 2);
  - backoff after refusals;
  - why TOTP ranks below Touch ID (NIST 800-63B-4).
- **3.3 Page schemas as capabilities:**
  - identification before use;
  - roles and risk levels;
  - `max_element_risk`;
  - destinations;
  - typing only into search boxes;
  - what this cannot stop: in-schema harm, exfiltration through allowed typing, accessibility spoofing.
- **3.4 One layer for coding agents:**
  - Claude Code: managed-only hooks, `onFailure: block`, a mandatory sandbox, protected config;
  - Codex: the equivalent mechanisms and their gaps.
- **3.5 Audit:**
  - the hash chain;
  - signed and anchored heads (Phase 2);
  - what it does and doesn't detect.
- **3.6 Studio: safe synthesis:**
  - capture;
  - masking by accessibility role;
  - a model with no tools;
  - checks: tree match, a risk floor the LLM can only raise, permission trimming, destinations within captured origins;
  - a draft mode;
  - approval.

## 4. Implementation (0.75 pp)
- Code size and tests (around 650 tests).
- The macOS APIs used.
- `sandbox_init` deprecation as a risk shared with the Claude Code and Codex sandboxes.

## 5. Evaluation (3.5 pp)
- S1–S4 and the conditions C0–C2, per `evaluation-plan.md`.
- Tables:
  - utility / utility under attack / ASR (proposed vs executed);
  - false blocks;
  - approvals per task;
  - overhead.
- Studio acceptance and masking-leak results.
- The optional approval pilot.

## 6. Discussion and limitations (1 pp)
- **Weaknesses W1–W18** (as corrected in `roadmap.md`):
  - in-schema harm;
  - same-user attacker;
  - schema maintenance;
  - spoofing;
  - no fleet layer (registry, central policy, SIEM, remote kill);
  - single admin;
  - unmeasured fatigue at scale.
- **Mapping to governance frameworks:**
  - OWASP LLM06 and the Agentic Top 10 (approval of the raw action);
  - EU AI Act Arts. 12, 14(4)(e) and 26(6), as voluntary alignment;
  - NIST AI RMF MANAGE 2.4;
  - ISO/IEC 42001 A.6.2.8.

## 7. Related work (1.5 pp)
Built from the report's sections:
- prompt-injection defenses (system and model level);
- computer-use and browser agent attacks;
- sandboxes and capability systems;
- MCP and tool permissions;
- human approval and warning fatigue;
- tamper-evident logging;
- LLM workflow synthesis with verification;
- governance frameworks.

## 8. Conclusion (0.25 pp)

## Appendices
- Open Science: artifacts, how to reproduce, what needs vendor accounts.
- Ethics: no real users' data; how the pilot was run, if any; responsible disclosure of any vendor issues found.
- AI-use disclosure (also in the acknowledgements).
