# GOV-AIOS: roadmap to the paper (from 2026-11-07)

Inputs:
- the cited report, `docs/research/reports/GOV AIOS agent governance related work.md` (called "the report" below; W-numbers and N-numbers refer to it);
- the Studio spec, `docs/superpowers/specs/2026-11-06-studio-capture-handover-design.md`;
- `docs/backlog.md`.

**Target:** USENIX Security '27, cycle 2. Register by **19 Jan 2027**, paper due **26 Jan 2027**, artifacts due 29 Jan 2027, notification 6 May 2027. Body limit is 13 pages, and the Open Science appendix and artifacts are mandatory. Preprints are allowed.
**Fallbacks:** CCS 2027 (dates estimated) or NDSS 2028 (about May 2027, estimated).
**Preprint:** arXiv cs.CR, cross-listed to cs.AI and cs.HC, posted once the submission is in.

The paper's claim, as the research sharpened it:
- GOV-AIOS does **not** detect prompt injection. It is a **capability boundary for GUI and coding agents**, enforced outside the model.
- The human approves an **exact artifact the governor wrote** (a digest of the flow and its pages), and that approval is bound to their **physical presence** (Touch ID, or a session that ends at screen lock).
- The main result is the gap between attacks the agent **proposes** and attacks that are **executed**, measured from the hash-chained log.

## Corrections to the report from the codebase (checked 2026-11-06)
- **W1, hooks failing open:** does not apply to Claude Code. `govaios/hook.py` writes `"onFailure": "block"` with a 300 s timeout, `allowManagedHooksOnly: true`, a mandatory sandbox (`failIfUnavailable: true`) and a managed-domains-only network. **Still open for Codex:** how Codex treats a hook that crashes or times out, which needs one live test.
- **Agent config protection:** Claude Code config is protected:
  - `.claude` at any depth and `.mcp.json` are denied for Edit;
  - `~/.claude.json` is denied for Edit;
  - project MCP servers are disabled.

  **Not yet protected:** `~/.codex`, `AGENTS.md` and `requirements.toml` integrity. These are part of Phase 2.

## Phase 0: hardening quick wins (7–8 Nov, about 2 days)
Small fixes the research exposed. Each is cheap, and each removes a reviewer objection.
- **W2, typed code instead of compared code.** The 4-letter word appears **only** in the Touch ID prompt; the admin types it into the page to finish signing in (NIST SP 800-63B-4: comparing two codes "is not sufficient"). Tests: a wrong word fails, and the word never appears on the page.
- **Backoff must not reset on a new request:** check the v2 F2 counter against a fresh `pre` token.
- **The audit records what the approver saw:** add the digest of the rendered approval text to `approve` and `ui_login` entries (open question in the report).
- **Name clash with Rutgers' AIOS:** pick the paper's system name early (for example keep "GOV-AIOS" and add one line distinguishing it from AIOS, arXiv 2403.16971). **Admin decision.**

## Phase 1: Studio phase 1 (9–29 Nov, 3 weeks)
Build the spec: capture, masking, handover, checks, typing into search boxes only, run-time inputs, draft mode, approval.
- **Day 1 decisions (spec §8):** the Claude channel (API key in Keychain, or Claude Code in no-tools mode), and whether other LLMs write flows in the first build.
- **Paper evidence it produces:**
  - N-claims on safe synthesis: tree match, a risk floor the LLM can only raise, permissions trimmed to what's used, masking by accessibility role;
  - suite S3 below.
- **Known weakness to disclose (W, Studio):** control names stay unmasked, so a hostile label can still address the LLM. The checks must hold even then.

## Phase 2: Codex governance and stronger proofs (30 Nov – 13 Dec, 2 weeks)
- **Codex governance:**
  - `/etc/codex/requirements.toml` written by the installer (root-owned), with managed hooks only, locked sandbox and approval modes, and an MCP allowlist;
  - a `PreToolUse` hook calling `gov-aios hook`;
  - one live test that a hook crash or timeout **fails closed** (W1 for Codex);
  - protect `~/.codex` and `AGENTS.md` like `.claude`.
- **W3, signed approvals:** a Secure Enclave key, usable only with Touch ID, signs `(flow digest, pages digest, nonce, time)`. The engine checks the signature, not a bare yes/no from LocalAuthentication. This is also the start of the deferred "same-user ticket minting" fix (v1 ruling 5) and of v2 F3.
- **W4, anchored audit:** sign each audit head with the same key, and export the head hash outside the machine (a git remote or a file you keep elsewhere). `verify-audit` checks against the anchor. The paper still states the limits: truncation before the first anchor, and local timestamps.
- **Out of scope, disclosed as future work (W5):** an agent registry, central policy, SIEM export, remote kill, and multiple users or roles.

## Phase 3: evaluation (7 Dec – 3 Jan, overlaps Phase 2; see `evaluation-plan.md`)
- Build **GOV-AIOS-Bench**, four suites, because no benchmark exists for macOS accessibility-tree agents.
- Run three conditions:
  - the agent alone;
  - the agent plus GOV-AIOS policy;
  - policy plus a simulated approver.
- Report:
  - utility, utility under attack, and attack success, the last split into proposed vs executed;
  - false blocks;
  - approvals per task;
  - p50/p95 overhead.
- **Optional, admin decision:** a small approval-fatigue pilot (n ≈ 10–20) instead of the full user study, which would need ethics review and wouldn't fit before 26 Jan.

## Phase 4: writing, citations, artifact (14 Dec – 19 Jan)
- **Writing:** draft section by section from `paper-outline.md`. Related work comes from the report.
- **Citation pass:** check **every** citation against the actual paper. USENIX treats hallucinated references as misconduct. Every [U] or [S] item in the report gets a [V], or is dropped.
- **Novelty pass:** read the 2026 IFC and guardrail papers the report lists (GIF, SPA, APPA, Provably Secure Agent Guardrail, AgentSys), RPA selector allowlisting (UiPath, Power Automate), and enterprise MCP gateways. Reword any N-claim they weaken.
- **Clean public repo** (backlog), anonymised for review (e.g. an anonymous mirror):
  - demo flows against local test pages;
  - no Himalayas, Gmail or personal data;
  - Apache-2.0 licence;
  - a secrets and personal-data scan.
- **Ethics and Open Science appendix:** threat model, artifacts, and the AI-use disclosure in the acknowledgements.
- **Admin:**
  - line up the arXiv cs.CR endorser (personal endorsement is required since 21 Jan 2026);
  - register on HotCRP by 19 Jan.

## Phase 5: submit (19–26 Jan)
- 19 Jan: register the abstract. 26 Jan: submit. 29 Jan: artifacts.
- After submission, post to arXiv. Check the venue's anonymity rule first: USENIX allows preprints, but the submission itself stays anonymous.

## Calendar risks
- Late December holidays: Phase 3 runs over them, so start the bench harness in Phase 1 week 3.
- Studio slipping past 29 Nov: cut Studio from the paper's contributions to "design and early results", and keep N1–N3 (presence, GUI capability boundary, one layer for every agent) as the core.
- IEEE S&P cycle 2 (17 Nov 2026) is not viable.

## Not ours to decide (admin)
1. The Claude channel for Studio; other LLMs as writers. Decide on day 1 of Phase 1.
2. The system name and the Rutgers AIOS distinction.
3. The user-study scope (pilot or none).
4. The endorser, the authors list and affiliations (Avanta Labs).
