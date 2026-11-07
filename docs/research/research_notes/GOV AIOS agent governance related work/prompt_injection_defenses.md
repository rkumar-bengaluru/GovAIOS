# Prompt-Injection Defenses and Benchmarks for LLM Agents (related work for GOV-AIOS)

Research date: 2026-11-06. Verification legend: **[V]** means checked against the arXiv abstract or HTML page, or the GitHub API, in this session. **[S]** means taken from a search-engine summary of the primary page, so check the number in the PDF before quoting it. **[U]** means from prior knowledge and not re-verified this session, so do not cite it without checking. Repo licenses come from the GitHub REST API (`/repos/{owner}/{repo}` `.license.spdx_id`) as of 2026-11-06. NOASSERTION means GitHub could not classify the license (often CC-BY-NC or a custom license), so read the LICENSE file.

## System/architectural defenses: mechanism, threat model, guarantees, results, limits, GOV-AIOS relation; which are provable or deterministic?

### Takeaway
Only a small family of designs claims guarantees that do not depend on model behaviour: CaMeL, FIDES, the f-secure IFC system, IsolateGPT, and the patterns paper's Action-Selector, Plan-Then-Execute and Code-Then-Execute. Each does it by taking control flow and/or data flow away from the LLM and enforcing policy in ordinary code. Progent and DRIFT also enforce deterministically, but their policies are often LLM-generated, so the guarantee is only as good as the policy. MELON and Task Shield are detection or LLM-judgment defenses with no deterministic guarantee, and MELON has been bypassed by adaptive attacks. All of these work at the tool-call/API layer. None of the verified defenses governs GUI/accessibility-tree actions or binds approval to human presence, which is the gap GOV-AIOS fills.

### Cited Findings

**CaMeL (Debenedetti, Shumailov, Fan, Hayes, Carlini, Fabian, Kern, Shi, Terzis, Tramèr; Google/Google DeepMind/ETH), arXiv:2503.18813, v1 24 Mar 2025, v2 24 Jun 2025 [V]**
- Mechanism: CaMeL is a system layer around the LLM. It "explicitly extracts the control and data flows from the (trusted) query," so untrusted data "can never impact the program flow." It attaches capabilities to values and enforces security policies when tools are called, to stop exfiltration of private data over unauthorized flows — [arXiv:2503.18813](https://arxiv.org/abs/2503.18813) [V]
- Architecture detail: a privileged LLM writes Python-like code, a quarantined LLM parses untrusted data with no tool access, and a custom interpreter tracks provenance and capabilities — [arXiv:2503.18813](https://arxiv.org/abs/2503.18813) [U, from paper body, not re-read]
- Result: "77% of tasks with provable security" on AgentDojo, versus 84% for the undefended system (v2 numbers, newer models) — [arXiv:2503.18813](https://arxiv.org/abs/2503.18813) [V]
- Threat model and limits: the user query is trusted. Policies must be written by hand. Side channels are acknowledged. The design does not cover a user who approves a bad action, or text-to-text manipulation of what the user sees (only tool-call effects) — [arXiv:2503.18813](https://arxiv.org/abs/2503.18813) [U]
- Peer-reviewed venue: none listed on arXiv as of v2 [V]. Code: github.com/google-research/camel-prompt-injection, Apache-2.0 (license from the GitHub API) [V].
- GOV-AIOS relation: same philosophy (enforcement outside the model, deterministic policy). The difference is the layer: GOV-AIOS mediates GUI actions on schema-captured accessibility elements rather than interpreted tool code, and it adds human-presence-bound approval. CaMeL policy checks can ask the user to confirm, but presence is not bound to that confirmation [U].

**Dual LLM pattern (Simon Willison, 25 Apr 2023)**
- Mechanism: a Privileged LLM has tools but never sees untrusted text. A Quarantined LLM reads untrusted content and has no tools. A non-LLM Controller passes the quarantined output around by symbolic reference ($VAR1) only — [simonwillison.net/2023/Apr/25/dual-llm-pattern](https://simonwillison.net/2023/Apr/25/dual-llm-pattern/) [U, URL not re-fetched]
- Limitation (stated in the patterns paper): the quarantined LLM "can still be manipulated" and can leak data it was given, for example through encoded output. CaMeL was motivated by the fact that the Dual LLM pattern does not track data flow through variables — [arXiv:2506.08837](https://arxiv.org/html/2506.08837v3) [V]; [arXiv:2503.18813](https://arxiv.org/abs/2503.18813) [U for the motivation claim]

**Design Patterns for Securing LLM Agents against Prompt Injections (Beurer-Kellner, Buesser, Creţu, Debenedetti, Dobos, Fabian, Fischer, Froelicher, Grosse, Naeff, Ozoani, Paverd, Tramèr, Volhejn), arXiv:2506.08837, v1 10 Jun 2025, v3 27 Jun 2025 [V]**
- Six patterns — [arXiv:2506.08837v3](https://arxiv.org/html/2506.08837v3) [V]:
  1. **Action-Selector:** the LLM maps a request to a predefined action and never sees the action's output.
  2. **Plan-Then-Execute:** the agent fixes its tool-call sequence before it reads untrusted data.
  3. **LLM Map-Reduce:** isolated sub-LLMs each process one untrusted item, followed by a constrained reduce step.
  4. **Dual LLM**, as above.
  5. **Code-Then-Execute:** CaMeL-style generated programs.
  6. **Context-Minimization:** the user prompt is removed from context once it has chosen the action.
- Design principle: once untrusted input is ingested, it must be "*impossible* for that input to trigger any consequential actions." Goal: "provable resistance to prompt injection" — [arXiv:2506.08837](https://arxiv.org/abs/2506.08837) [V]
- Threat model: injected instructions in files, emails, calendar events, web pages, reviews, resumes and DB records. The user may also be malicious. Attacker goals are unauthorized tool calls, exfiltration, output manipulation, reputational harm and DoS — [arXiv:2506.08837v3](https://arxiv.org/html/2506.08837v3) [V]
- Limitations: general-purpose agents with guarantees "remain out of reach with current capabilities." The patterns deliberately restrict agent capability. Plan-then-execute "does not prevent all prompt injections," for example it cannot stop an injection that changes the arguments of a pre-planned call. No single pattern suffices on its own. Detectors "do not provide guarantees" — [arXiv:2506.08837v3](https://arxiv.org/html/2506.08837v3) [V]
- On human-in-the-loop: the paper notes that confirmation can "pose a safety risk themselves with tired or overloaded human verifiers approving unsafe actions," yet it still uses "The user is asked to review and confirm any consequential action" in its email case study — [arXiv:2506.08837v3](https://arxiv.org/html/2506.08837v3) [V]
- Computer-use and GUI agents are not specifically addressed (based on the 0–100k characters of the HTML that were read) [V, partial read].
- GOV-AIOS relation: risk-rated page schemas with a closed action set amount to an Action-Selector at the UI layer. The allow-listed destinations limit where data can flow. GOV-AIOS's human-presence binding directly answers the paper's "tired verifier" concern in part: the approval comes from a physically present human, though fatigue still has to be argued, for example by limiting approvals to high-risk elements.

**IsolateGPT, formerly SecGPT (Wu, Roesner, Kohno, Zhang, Iqbal), NDSS 2025, arXiv:2403.04960 (v1 Mar 2024 as SecGPT, v2 Jan 2025 as IsolateGPT) [S]**
- Mechanism: a hub-and-spoke design. Each third-party app/tool runs in its own isolated spoke, and spokes talk only through a trusted hub that mediates the interactions — [arXiv:2403.04960](https://arxiv.org/abs/2403.04960v2); [NDSS paper PDF](https://www.ndss-symposium.org/wp-content/uploads/6A-f1131-Wu.pdf) [S]
- Threat model: malicious or compromised third-party apps attacking other apps or the user's data through the shared LLM context [S/U].
- Results: overhead is under 30% for three-quarters of the tested queries — [arXiv:2403.04960](https://arxiv.org/abs/2403.04960v2) [S]
- Code: github.com/llm-platform-security/SecGPT, license NOASSERTION per the GitHub API [V].
- GOV-AIOS relation: both are OS-style mediation. IsolateGPT isolates apps from each other. GOV-AIOS mediates agent-to-GUI actions and adds human approval.

**f-secure LLM system (Fangzhou Wu, Ethan Cecchetti, Chaowei Xiao), arXiv:2409.19091, Sep 2024 [S]**
- Mechanism: information-flow control. A security monitor filters untrusted input out of the planning process, and the authors formalize security properties for this — [arXiv:2409.19091](https://arxiv.org/abs/2409.19091v1) [S]
- Code is reported at github.com/fzwark/Secure_LLM_System [S, not checked]. Peer-reviewed venue: not found [Gap].

**FIDES (Costa, Köpf, Kolluri, Paverd, Russinovich, et al.; Microsoft), "Securing AI Agents with Information-Flow Control," arXiv:2505.23643, v2 3 Sep 2025 [S]**
- Mechanism: a planner that tracks confidentiality and integrity labels over a lattice, enforces policies deterministically, and provides primitives to selectively hide and reveal information from the LLM (variables plus constrained decoding). The authors state a noninterference guarantee for integrity — [arXiv:2505.23643](https://arxiv.org/pdf/2505.23643) [S]
- Result: with policy checks disabled, the extra hide/reveal machinery did not reduce task completion compared with a basic planner when using reasoning models (AgentDojo-based evaluation) — [arXiv:2505.23643](https://arxiv.org/pdf/2505.23643) [S]. Exact ASR and utility numbers were not retrieved [Gap].
- Code: github.com/microsoft/fides, MIT (GitHub API) [V].

**Progent (Shi et al., UC Berkeley and others), "Progent: Programmable Privilege Control for LLM Agents," arXiv:2504.11703 [S]**
- Mechanism: a domain-specific language for fine-grained tool-call privilege policies (allow/deny with argument constraints and fallback actions), enforced deterministically at tool-call time. Policies can be written by hand or generated and updated by an LLM — [arXiv:2504.11703v2](https://arxiv.org/html/2504.11703v2) [S]
- Results:
  - v2 (Aug 2025): ASR is 0% across AgentDojo, ASB and AgentPoison with hand-written policies. With LLM-generated policies on AgentDojo, ASR falls from 39.9% to 1.0% while utility goes from 79.4% to 76.3% — [arXiv:2504.11703v2](https://arxiv.org/html/2504.11703v2) [S]
  - v1 (Apr 2025) reported 41.2% to 2.2% — [arXiv:2504.11703v1](https://arxiv.org/html/2504.11703v1) [S]
  - Cite the version you quote.
- Limitation: the guarantee holds only for what the policy expresses, and an LLM-generated policy brings back model trust [Inference].
- Code: github.com/sunblaze-ucb/progent, MIT, active as of Oct 2026 [V].
- GOV-AIOS relation: the closest analogue, since both use default-deny privilege policies enforced in code. GOV-AIOS policies are human-curated schemas captured from the real accessibility tree rather than LLM-generated, and they gate GUI elements rather than API tool calls.

**MELON (Kaijie Zhu, Xianjun Yang, Jindong Wang, Wenbo Guo, William Wang), ICML 2025, arXiv:2502.05174 (title changed in v2 to v4 to "Provable Defense...") [S]**
- Mechanism: the agent is re-run with the user task masked. If the masked run produces tool calls similar to the original run's, the calls are being driven by tool output, meaning an injection, so they are flagged — [arXiv:2502.05174](https://arxiv.org/abs/2502.05174v3); [ICML 2025 poster](https://icml.cc/virtual/2025/poster/44447) [S]
- Claimed result: blocks more than 99% of attacks on AgentDojo while preserving utility (ICML lay summary) — [ICML](https://icml.cc/virtual/2025/poster/44447) [S]
- Broken: "The Attacker Moves Second" built conditional injections that fire only in the unmasked run, which evades MELON's comparison — [arXiv:2510.09023](https://arxiv.org/abs/2510.09023) [S]
- Not deterministic: it depends on the LLM's behaviour in both runs and on a similarity threshold. Code: github.com/kaijiezhu11/MELON (no license file per the GitHub API) [V].

**Task Shield (Feiran Jia, Tong Wu, et al.), arXiv:2412.16682, Dec 2024 [S]**
- Mechanism: a test-time LLM judge checks that every instruction and tool call "contributes to user-specified goals" — [arXiv:2412.16682](https://arxiv.org/abs/2412.16682) [S]
- Result: on AgentDojo with GPT-4o, ASR is 2.07% with 69.79% utility — [arXiv:2412.16682](https://arxiv.org/abs/2412.16682) [S]
- Not deterministic, because the judge is itself an LLM that can be injected [Inference].

**DRIFT (Hao Li, Xiaogeng Liu, et al.), "Dynamic Rule-Based Defense with Injection Isolation," arXiv:2506.12104, NeurIPS 2025 [S]**
- Mechanism:
  - A Secure Planner produces a minimal function trajectory and a JSON-schema parameter checklist.
  - A Dynamic Validator checks deviations from that plan.
  - An Injection Isolator masks injected instructions in memory.
  - The authors argue for moving from static to dynamic policy enforcement — [arXiv:2506.12104](https://arxiv.org/abs/2506.12104); [NeurIPS slides](https://neurips.cc/media/neurips-2025/Slides/116028_p9LqCjy.pdf) [S]
- Evaluated on AgentDojo and others. Exact numbers were not retrieved [Gap]. The repo SaFoLab-WISC/DRIFT has moved (HTTP 301) [V].

**Plan-then-execute / action-selector in general:** formalized in the patterns paper above. CaMeL is effectively plan (code) then execute with IFC. DRIFT and Progent are dynamic or policy variants.

**2026 IFC successors (seen in search results, abstracts not read, all [U]):**
- "GIF: Locally Sound Geometric Information Flow Control for LLMs," [arXiv:2606.23277](https://arxiv.org/pdf/2606.23277)
- "SPA: Securing Persistent LLM Agents Across Queries with Plan-First Information-Flow Control," [arXiv:2608.27234](https://arxiv.org/pdf/2608.27234)
- "APPA: Recoverable Information-Flow Control for Real-World LLM Agents," [NeurIPS 2026](https://neurips.cc/virtual/2026/168263)
- "Provably Secure Agent Guardrail," [arXiv:2605.29251](https://arxiv.org/pdf/2605.29251)
- "AgentSys: ...Explicit Hierarchical Memory Management," [arXiv:2602.07398](https://arxiv.org/pdf/2602.07398)

### Inferences
- A taxonomy for the paper:
  - (a) deterministic, model-independent: CaMeL, FIDES, f-secure, IsolateGPT, Action-Selector and Plan-Then-Execute, Progent with human-written policies;
  - (b) deterministic enforcement of an LLM-authored policy: Progent-LLM, DRIFT;
  - (c) probabilistic, LLM-judged: MELON, Task Shield.
  GOV-AIOS sits in (a).
- Every verified defense assumes structured tool APIs, an environment like AgentDojo's. None mediates raw GUI/accessibility actions or desktop apps. This is the clearest novelty claim for GOV-AIOS, but phrase it as "to our knowledge" and re-check the 2026 papers marked [U].
- Human confirmation is treated as a weak, fatigue-prone fallback (patterns paper). GOV-AIOS should present presence-binding (Touch ID/TOTP ending on screen lock) as defending against an autonomous agent approving its own actions, or headless approval. It should not claim to solve approval fatigue.
- The utility cost of deterministic designs is concrete: CaMeL is 7 points below the undefended system (77% vs 84%). GOV-AIOS should report a comparable utility figure.

### Gaps
- Exact numbers for FIDES, DRIFT and f-secure were not retrieved.
- The CaMeL policy and side-channel limitations are from memory [U].
- The Willison URL was not re-fetched.
- No peer-reviewed venue was confirmed for CaMeL or f-secure.

## Model-level defenses: spotlighting, StruQ, SecAlign, Meta SecAlign, instruction hierarchy, detectors. Why insufficient alone?

### Takeaway
Model-level defenses cut the ASR of static attacks dramatically, to near zero, but they give probabilistic, distribution-dependent protection. Adaptive attacks consistently push them back above 90% ASR. Fine-tuning defenses also cost utility. So model-level defenses complement system-level enforcement and cannot replace it.

### Cited Findings
- **Spotlighting (Hines et al., Microsoft), arXiv:2403.14720, Mar 2024 [U]:**
  - Mechanism: prompt transformations (delimiting, datamarking, encoding such as base64) that mark the provenance of untrusted input.
  - Result: ASR falls from above 50% to below 2% on GPT-family models, with little task impact.
  - The search did not surface this paper this session, so verify the ID and numbers at [arxiv.org/abs/2403.14720](https://arxiv.org/abs/2403.14720) [U].
- **StruQ (Sizhe Chen, Piet, Sitawarin, Wagner), "Structured Queries," arXiv:2402.06363, USENIX Security 2025 [U for ID and venue]:**
  - Mechanism: separates prompt and data channels with reserved delimiter tokens, then fine-tunes the model on simulated injections placed in the data part.
  - It effectively stops optimization-free attacks but is vulnerable to optimization-based ones — [BAIR blog](https://bair.berkeley.edu/blog/2025/04/11/prompt-injection-defense) [S]
  - Code: Sizhe-Chen/StruQ, NOASSERTION [V].
- **SecAlign (Chen, Zharmagambetov, Mahloujifar, Chaudhuri, Wagner, Guo), arXiv:2410.05451, CCS 2025 [S]:**
  - Mechanism: preference optimization (DPO) on pairs of a secure and an insecure response to an injected input.
  - Result: ASR of the strongest tested attack reaches about 8% on Llama3-8B-Instruct without utility loss — [arXiv:2410.05451](https://arxiv.org/html/2410.05451v3) [S]
  - Code: facebookresearch/SecAlign, NOASSERTION [V].
- **Meta SecAlign (Chen, Zharmagambetov, Wagner, Guo), arXiv:2507.02735, v1 3 Jul 2025, v3 Feb 2026 [S]:**
  - The first open-weight model with a built-in injection defense, at 8B and 70B (Llama-3.x based).
  - Meta-SecAlign-70B reaches 1.9% ASR on AgentDojo, and the HF card shows about 14.7% for the undefended base model. ASR on WASP is 0%. v3 claims near-zero agentic ASR, "comparable to GPT-5" with reasoning — [arXiv:2507.02735v3](https://arxiv.org/html/2507.02735v3); [HF model card](https://huggingface.co/facebook/Meta-SecAlign-70B/blob/main/README.md) [S]
  - The figures change across v1 to v3, so cite the version.
  - Code: facebookresearch/Meta_SecAlign, NOASSERTION [V].
- **Instruction Hierarchy (Wallace, Xiao, Leike, Weng, Heidecke, Beutel; OpenAI), arXiv:2404.13208, Apr 2024 [V for ID and authors]:**
  - Mechanism: trains a privilege ordering of system > user > tool output, using synthetic aligned and misaligned instruction data.
  - Result: large robustness gains on GPT-3.5, including on unseen attack types, with minimal capability loss.
  - Known drawback: over-refusal — [arXiv:2404.13208](https://arxiv.org/abs/2404.13208v1) [S]
- **DataSentinel (Yupei Liu, Yuqi Jia, Jinyuan Jia, Dawn Song, Neil Gong), arXiv:2504.11358, IEEE S&P 2025 [S]:**
  - Mechanism: a detector LLM fine-tuned through minimax (game-theoretic) training against adaptive evasion.
  - Result: FPR close to 0, and FNR close to 0 up to 0.07, across 7 target tasks, 9 injected tasks, 6 LLMs and 9 attacks — [arXiv:2504.11358](https://export.arxiv.org/abs/2504.11358); [PSU record](https://pure.psu.edu/en/publications/datasentinel-a-game-theoretic-detection-of-prompt-injection-attac/) [S]
  - Code: liu00222/Open-Prompt-Injection, MIT [V].
- **PromptGuard / Llama Prompt Guard 2 (Meta):** a small classifier (86M and 22M mDeBERTa-class) that flags jailbreak and injection text. Early PromptGuard 1 was reported bypassable by simple character spacing — [Llama Prompt Guard 2 model card](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M) [U, not fetched].
- **Why insufficient alone:**
  - "The Attacker Moves Second" (Nasr, Carlini, Sitawarin, Schulhoff, et al.), arXiv:2510.09023, Oct 2025: of 12 published defenses tested, most were above 90% ASR under adaptive attack, even though their original evaluations reported near-zero. Human red-teaming succeeded in all scenarios. All filtering and secret-knowledge defenses were bypassed — [arXiv:2510.09023](https://arxiv.org/abs/2510.09023) [S]
  - "A Critical Evaluation of Defenses against Prompt Injection Attacks," arXiv:2505.18333: GCG reaches ASR above 0.80 against StruQ on both benchmarks and 0.72 against SecAlign on MMLU-PI. Both defenses lose relative and absolute utility, contrary to their original claims — [arXiv:2505.18333](https://arxiv.org/pdf/2505.18333) [S]
  - "Adaptive Attacks Break Defenses Against Indirect Prompt Injection Attacks on LLM Agents," arXiv:2503.00061 — [arXiv:2503.00061](https://arxiv.org/pdf/2503.00061) [S, title only]
  - The patterns paper says such heuristics "do not provide guarantees" — [arXiv:2506.08837v3](https://arxiv.org/html/2506.08837v3) [V]
  - The PISmith RL-based red-teamer, arXiv:2603.13026 (2026) — [arXiv:2603.13026](https://arxiv.org/pdf/2603.13026) [U, title only]

### Inferences
- The core argument for the paper: a model-level defense's ASR is measured against a fixed attack distribution, and a motivated attacker optimizes against that distribution. A deterministic, out-of-model gate turns "the probability the model is fooled" into "the probability a non-schema action executes," which is zero by construction. What remains is approved in-schema misuse, which is the residual risk to discuss.
- GOV-AIOS is orthogonal to these defenses and can stack with them. A Meta-SecAlign-class backbone would reduce how often the agent proposes something that needs a denial or an approval prompt. That bears on usability and approval fatigue, not on security.

### Gaps
- Spotlighting, StruQ's arXiv ID and venue, and PromptGuard details are [U].
- No independent adaptive evaluation of Meta SecAlign v3 was found.

## Benchmarks: what they measure, metrics, reusability for a desktop/browser governance layer, license, code

### Takeaway
AgentDojo is the de facto standard: it reports utility, utility under attack and targeted ASR, uses an MIT license, and is extensible. It is API-tool based, however, not GUI based. WASP (web, VisualWebArena) is the closest fit for a browser/UI governance layer. No standard desktop/accessibility-tree injection benchmark was found, so GOV-AIOS probably needs to adapt WASP or AgentDojo tasks to real apps, or build its own suite.

### Cited Findings
- **AgentDojo (Debenedetti, Zhang, Balunović, Beurer-Kellner, Fischer, Tramèr), arXiv:2406.13352, NeurIPS 2024 Datasets & Benchmarks [U for ID and venue; widely cited]:**
  - Four suites (workspace, Slack, travel, banking), 74 tools, 97 user tasks and 629 security cases [U for the 97/629 counts].
  - Rule-based evaluators. Metrics: benign utility, utility under attack, targeted ASR — [AgentDyn comparison, arXiv:2602.03117](https://arxiv.org/html/2602.03117v1) [S]
  - Used by CaMeL, Progent, MELON, Task Shield, DRIFT and Meta SecAlign (see above).
  - Code: ethz-spylab/agentdojo, MIT, active (last push Jun 2026) [V].
  - Reusability: the attack/task DSL and the evaluator pattern carry over. The environments do not, because they are Python tool stubs rather than a GUI.
- **InjecAgent (Zhan, Liang, Ying, Kang), arXiv:2403.02691, ACL Findings 2024 [U for ID and venue]:**
  - 1,054 test cases over 17 user tools and 62 attacker tools; categories are direct harm and data stealing; metric is ASR [U for counts].
  - Single-step, simulated tool calls only — [arXiv:2602.03117](https://arxiv.org/html/2602.03117v1) [S]
  - Code: uiuc-kang-lab/InjecAgent, MIT, inactive since Jul 2024 [V].
  - Reusability: low, because it is single-turn and simulated.
- **ASB, Agent Security Bench (Zhang et al.), arXiv:2410.02644, ICLR 2025 [S for ID, U for venue]:**
  - Covers direct and indirect PI, memory poisoning and backdoors; 16 attacks and 11 defenses per a comparison table. Average indirect-PI ASR is about 27.55% — [arXiv:2410.02644](https://arxiv.org/pdf/2410.02644); [arXiv:2602.03117](https://arxiv.org/html/2602.03117v1) [S]
  - Also defines a Net Resilient Performance metric [U].
  - Code: agiresearch/ASB, MIT, active (Sep 2026) [V].
- **AgentHarm (Andriushchenko et al., Gray Swan / UK AISI), arXiv:2410.09024, ICLR 2025 [U]:**
  - Measures compliance with harmful requests (direct misuse and jailbreaks), not injection. Metrics: harm score and refusal rate — [arXiv:2602.03117](https://arxiv.org/html/2602.03117v1) [S]
  - Distributed through UK AISI inspect_evals (MIT [V]). The dataset on HF has its own license terms [U].
  - Relevance to GOV-AIOS: it fits a "malicious user/agent" threat model, not indirect injection.
- **WASP (Evtimov et al., FAIR at Meta), arXiv:2504.18575, v3 May 2025, NeurIPS 2025 [S]:**
  - End-to-end web-agent injection tests in sandboxed VisualWebArena (GitLab and Reddit clones).
  - Separates intermediate hijack from attacker goal completion: attacks partly succeed in up to 86% of cases, but full attacker goals succeed in only 0–17% — [arXiv:2504.18575](https://arxiv.org/abs/2504.18575) [S]
  - Code: facebookresearch/wasp, NOASSERTION (likely CC-BY-NC, so check) [V for NOASSERTION].
  - Reusability: the highest for a browser governance layer. It needs real browser UI and supports screenshot and accessibility-tree observation spaces [U for observation spaces].
- **b3, Backbone Breaker Benchmark (Lakera and UK AISI), "Breaking Agent Backbones," arXiv:2510.22620, ICLR 2026 [S]:**
  - 10 "threat snapshots" that isolate the backbone LLM's vulnerable decision points rather than a full agent. Uses crowdsourced attacks from Gandalf: Agent Breaker.
  - Attack and model counts conflict: the paper says 194,331 attacks and 34 models, while press coverage says 19,433 and 31. Prefer the paper — [arXiv:2510.22620v2](https://arxiv.org/html/2510.22620v2) [S]
  - Repo lakeraai/b3 not found via the GitHub API, so the code location and license are unverified [Gap].
  - Reusability: low for a governance layer, because it measures the model, not the system.
- **2025–2026 successors (titles from search; the content of each is unverified):**
  - AgentDyn, a dynamic open-ended PI benchmark, [arXiv:2602.03117](https://arxiv.org/html/2602.03117v1) [S]
  - INFUSE, a unified surface benchmark for indirect PI, [arXiv:2610.20776](https://arxiv.org/html/2610.20776v1) [U]
  - "Indirect Prompt Injection in the Wild" (prevalence study), [arXiv:2604.27202](https://arxiv.org/pdf/2604.27202) [U]
  - "Agent Data Injection Attacks are Realistic Threats," [arXiv:2607.05120](https://arxiv.org/pdf/2607.05120) [U]
  - "The Blind Spot of Agent Safety" (benign instructions causing harm in computer-use agents), [arXiv:2604.10577](https://arxiv.org/pdf/2604.10577) [U]
  - From prior knowledge, not checked this session: VWA-Adv, EIA (environmental injection on web agents), and OS-Harm / RedCode-style CUA benchmarks [U].

### Inferences
- An evaluation design for GOV-AIOS: report AgentDojo's three metrics (benign utility, utility under attack, ASR) over WASP-style real-UI tasks, and add a GOV-AIOS-specific metric for approval prompts per task (fatigue).
- WASP's split between hijack and goal completion maps well onto GOV-AIOS's claim. The agent may be hijacked, but the consequential action is blocked or needs presence-bound approval.
- License caution: AgentDojo, InjecAgent and ASB are MIT and can be reused freely. Check WASP's license before redistributing derived tasks.

### Gaps
- AgentDojo, InjecAgent, AgentHarm and ASB IDs, venues and counts are from prior knowledge [U]. Verify them on arXiv before submission.
- The b3 code location and license were not found.
- No benchmark targeting a macOS accessibility-tree desktop agent was found.

## What do 2025–2026 surveys conclude about open gaps (human approval, UI agents, enforcement outside the model)?

### Takeaway
Recent systematizations converge on applying classic systems security (isolation, privilege separation, mediation, IFC) outside the model, and they say general-purpose agents with guarantees remain unsolved. Human approval is consistently treated as necessary but fatigue-prone, and computer-use/UI agents are flagged as under-defended. This review could not confirm specific survey text naming presence-bound approval or accessibility-tree mediation as a gap. That absence supports a novelty claim, but it is not proof.

### Cited Findings
- "Systems Security Foundations for Agentic Computing" (Christodorescu, Fernandes, Hooda, Jha, Rehberger, Chaudhuri, et al.), arXiv:2512.01295, v1 1 Dec 2025, v2 19 Feb 2026: argues that prior work "lacks system-security perspective and guarantees." Analyzes agents with classic security principles at the end-to-end system level, with 11 real-world attack case studies, and lists short- and long-term research problems — [arXiv:2512.01295](https://arxiv.org/abs/2512.01295) [V, abstract only]
- "Toward Securing AI Agents Like Operating Systems" (Pirch, Horlboge, Großmann, Asif, Kireev, Holz, Rieck), arXiv:2605.14932, May 2026: agents and OSes share the problems of resource isolation, privilege separation and mediated communication. In four OpenClaw-like agents, "several protection mechanisms fail in practice." Some capabilities are insecure by design, and many vulnerabilities can be mitigated with established OS techniques. Human approval and GUI agents are not covered in the abstract — [arXiv:2605.14932](https://arxiv.org/abs/2605.14932) [V]
- The patterns paper: general-purpose agents with guarantees "remain out of reach"; human verifiers may be "tired or overloaded" — [arXiv:2506.08837v3](https://arxiv.org/html/2506.08837v3) [V]
- "A Survey on the Safety and Security Threats of Computer-Using Agents: JARVIS or Ultron?" arXiv:2505.10924 (2025): a dedicated CUA threat survey — [arXiv:2505.10924](https://arxiv.org/pdf/2505.10924) [S, title only]
- "The Emerged Security and Privacy of LLM Agent: A Survey with Case Studies," ACM Computing Surveys — [DOI 10.1145/3773080](https://dl.acm.org/doi/full/10.1145/3773080) [S, title only]
- "A Framework for Formalizing LLM Agent Security," [arXiv:2603.19469](https://arxiv.org/pdf/2603.19469); "Security of OpenClaw Agents," [arXiv:2605.25435](https://arxiv.org/pdf/2605.25435) [U, titles only]
- "The Attacker Moves Second" recommends evaluating against the strongest adaptive attacker, which favours designs whose security does not rest on the model — [arXiv:2510.09023](https://arxiv.org/abs/2510.09023) [S]

### Inferences
- GOV-AIOS positioning: the paper can claim to instantiate the "OS-style mediation outside the model" agenda (2512.01295, 2605.14932) for GUI agents on a real desktop. It adds two things the verified related work lacks:
  - (1) an action surface derived from the real accessibility tree and risk-rated per element;
  - (2) approval bound to human presence (Touch ID, or TOTP that ends on screen lock), which addresses an agent self-approving and approvals happening while the user is away.
- Expect reviewers to raise: (i) in-schema misuse (an injected agent picks a legitimate but harmful element and the user approves it), which is the patterns paper's fatigue critique; (ii) the cost of schema coverage and maintenance as UIs change; (iii) the confidentiality side, meaning what the model reads, since GOV-AIOS gates actions, not reads, unless the allow-listed destinations cover exfiltration.

### Gaps
- Full texts of 2512.01295 and the CUA survey were not read, so their specific lists of open problems, and whether they mention human approval or UI agents, are unconfirmed.
- The 2026 surveys marked [U] were not opened.
