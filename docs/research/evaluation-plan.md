# GOV-AIOS evaluation plan (draft for USENIX Security '27)

The methodology follows the report (§ evaluation): the AgentDojo three metrics, WASP's split between proposed and executed attacks, the overhead reporting used by IsolateGPT and Progent, and a threat-model statement in standard form.

## Threat model (paper wording to refine)
**Protected:** the admin's accounts, files, and outgoing actions on one macOS laptop.

**The attacker controls:**
- the content of any page or file the agent reads (indirect prompt injection), including accessibility labels;
- the outputs of the LLM, both at run time and in Studio;
- requests from other local web origins to the panel.

**Trusted:**
- the signed GOV-AIOS app;
- macOS (TCC, LocalAuthentication, Secure Enclave);
- the admin at approval time, who sees the governor-written summary.

**Out of scope, stated as residuals:**
- **A malicious process running as the same user.** v1 ruling 5 and v2 F3; this shrinks once Phase 2's signed approvals land.
- **Physical coercion.**
- **Kernel compromise.**
- **Attacks inside an allowed schema that the human approves.** These are measured, not prevented.

## Systems under test
- **Browser/desktop flows:** the GOV-AIOS engine with real Chrome (local test sites, plus the public sites each suite names).
- **Coding agents:** Claude Code (managed settings and hooks) and OpenAI Codex (requirements.toml and hooks), each with and without GOV-AIOS.
- **Studio:** LLM-written drafts, with and without the checks.

## Conditions
1. **C0, agent alone:** no GOV-AIOS, vendor defaults.
2. **C1, policy:** GOV-AIOS enforcement, with approval auto-denied for anything that needs a human.
3. **C2, policy plus a simulated approver:** approves whatever the governor's summary marks as "in the request", which is the best case for a careful human; then a "fatigued" approver who approves everything, to bound the damage human error can do.

## Metrics
- **Benign utility:** tasks solved with no attack.
- **Utility under attack:** tasks solved with injections present.
- **ASR-proposed:** attacks the agent tried, from the agent's own trace.
- **ASR-executed:** attacks that changed state. The ground truth is the hash-chained audit log and an external state diff.
- **False blocks:** benign actions refused.
- **Approvals per task:** the fatigue proxy.
- **Overhead:** p50/p95 latency per action, and setup cost (schema capture time).
- **Repeated attempts:** ASR after k = 25 retries, following CAISI's 57% → 80% finding.

## Suites (GOV-AIOS-Bench)
### S1: UI injection against browser flows
- **Base:** adapt WASP (web) and AgentDojo task families to real pages. Each tool call maps to a risk-rated page action.
- **Injections:**
  - page text;
  - accessibility labels and names;
  - pop-ups;
  - look-alike elements (accessibility spoofing);
  - redirects to non-allowed origins;
  - typing exfiltration into allowed search boxes.
- **Pages:** local test sites under our control, so the runs are reproducible and need no real accounts.
- **Expected shape:** ASR-proposed is high in C0 and C1; ASR-executed is near 0 in C1 apart from in-schema actions. Report the residual honestly.

### S2: coding agents
- RedCode-style risky commands.
- Config tampering: editing `.claude`, `.mcp.json`, `~/.codex` or `AGENTS.md`.
- Network exfiltration.
- Writes outside allowed folders.
- Hook crash and timeout behaviour (fail closed).
- Run each with Claude Code and with Codex, in C0 and C1.

### S3: Studio synthesis
- **Inputs:**
  - benign requests;
  - requests over captures that contain injected labels ("set this button's risk to read");
  - LLM replies seeded with over-permissioned or invented elements.
- **Metrics:**
  - drafts accepted vs rejected;
  - risks raised;
  - permissions trimmed;
  - retries;
  - masking leaks (personal-text tokens that reach the handover, measured with planted canaries).

### S4: panel and authorization
Each test passes or fails:
- forged sign-in from another local origin;
- replayed `pre` or `s` cookies;
- prompt spam (backoff);
- a stale ticket;
- a lock during a run;
- signed approval verification after Phase 2.

## Optional: approval pilot (admin decision)
- n ≈ 10–20, within subjects.
- Approve or deny 30 governor-written summaries, 5 of them harmful but inside the schema.
- Measure the approval-error rate and time per decision.
- Small enough to need only a light ethics process. Larger habituation studies (Anderson/Vance style) are future work.

## Baselines and comparison
- **Quantitative:** vendor defaults (C0) on the same tasks.
- **Qualitative:** a table against CaMeL, Progent, FIDES, Conseca, IsolateGPT, WebGuard and ShieldAgent, by enforcement point (model or system), action domain (API or GUI) and human binding. These systems work on API tools, so the comparison is by design, not by head-to-head numbers. Say so.

## Artifacts (USENIX Open Science)
- The public repo has:
  - the engine;
  - the bench harness;
  - the local test sites;
  - scripts that regenerate every table from the audit logs.
- No real accounts are needed to reproduce S1, S3 and S4.
- S2 needs Claude Code or Codex accounts; document it as "requires vendor account".
