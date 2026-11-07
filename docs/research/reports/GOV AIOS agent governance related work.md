# GOV-AIOS brings deterministic mediation to GUI agents

Position GOV-AIOS as the first system we know of that applies the "enforce policy outside the model" principle (CaMeL, Progent, FIDES, Conseca, ACE) to **GUI and accessibility-tree actions on a real desktop**, and that binds the human approval to physical presence and to a digest of the exact code that will run. Every deterministic prompt-injection defense the notes verified works at the API tool-call layer, in AgentDojo-style environments. The GUI-layer guardrails that do exist (WebGuard, ShieldAgent, GuardAgent, PolicyGuard) are learned classifiers, and the vendor confirmations (Operator, Claude Code prompts) depend on the model or a classifier. This gap holds up across six research threads, but it is an absence-of-evidence claim, so word it as "to our knowledge". Several 2026 papers, the RPA industry (UiPath selector governance), and enterprise MCP and agent gateways have not been checked. The evaluation should report the AgentDojo triad (benign utility, utility under attack, targeted ASR). Following WASP, it should split ASR into *proposed* versus *executed* malicious actions, because GOV-AIOS's main result is the gap between those two numbers. It should add over-blocking, approval burden, p50/p95 latency overhead and multi-attempt (CAISI-style) results. The research also found real design weaknesses that reviewers will raise: Claude Code hooks fail open by default, the 4-letter code is compared rather than typed, Touch ID returns an unsigned boolean, the audit chain can be rewritten by the same UID, and the system has no fleet layer. Fix or disclose these before submitting. The realistic target is **USENIX Security '27 cycle 2 (paper due 26 Jan 2027 AoE)**, with an arXiv cs.CR preprint. That route needs a personal endorser under arXiv's 21 Jan 2026 rule, a systems-paper framing (not a position paper), and an AI-use disclosure in the acknowledgments.

**Verification tags are kept from the source notes.** Their meanings differ by note, so they are kept as written. **[V]** or [fetched]: checked against the primary page (arXiv abstract or HTML, vendor doc, GitHub API, standard text) on 2026-11-06. **[S]**: from a search-engine or secondary summary; check the number in the PDF. **[U]**, [M], [memory, unverified] or [UNVERIFIED]: from prior knowledge or a snippet only; do not cite without checking. [aggregator]: from a deadline tracker. ESTIMATE: a date inferred from past cycles. [Inference] and [Gap] are the researchers' own judgments. Where two notes gave different tags for the same item, this report uses the stronger one and says so.

---

## Every deterministic injection defense stops at the API tool call

### System-level defenses form a three-tier taxonomy

The related-work section should group prompt-injection defenses by **where the guarantee comes from**. Only a small group of designs claims guarantees that do not depend on model behavior. They get them by taking control flow and/or data flow away from the LLM and enforcing policy in ordinary code.

**Tier (a): deterministic and model-independent.** GOV-AIOS belongs here.

- **CaMeL** (Debenedetti, Shumailov, Fan, Hayes, Carlini, Fabian, Kern, Shi, Terzis, Tramèr; arXiv:2503.18813, v1 24 Mar 2025, v2 24 Jun 2025) [V]. It extracts control and data flow from the trusted query, so untrusted data "can never impact the program flow". It attaches capabilities to values and enforces policies when tools are called. On AgentDojo it solves **77% of tasks with provable security, against 84% undefended** (v2 numbers) ([arXiv:2503.18813](https://arxiv.org/abs/2503.18813)) [V].
  - One note records the v1 abstract figure of 67% as "conflicting across versions" ([HF/abstract](https://huggingface.co/papers/2503.18813)). Cite v2 explicitly.
  - The privileged-LLM, quarantined-LLM and interpreter architecture is [U, from paper body, not re-read]. So are the stated limits: hand-written policies, acknowledged side channels, no coverage of a user who approves a bad action.
  - No peer-reviewed venue is listed [V]. Code: github.com/google-research/camel-prompt-injection, Apache-2.0 [V].
- **Design Patterns for Securing LLM Agents against Prompt Injections** (Beurer-Kellner et al.; arXiv:2506.08837, v3 27 Jun 2025) [V]. Six patterns: Action-Selector, Plan-Then-Execute, LLM Map-Reduce, Dual LLM, Code-Then-Execute, Context-Minimization. Its principle is that once untrusted input is ingested it must be "*impossible* for that input to trigger any consequential actions" ([arXiv:2506.08837v3](https://arxiv.org/html/2506.08837v3)) [V].
  - It concedes that general-purpose agents with guarantees "remain out of reach".
  - It warns that human verifiers can be "tired or overloaded", yet still uses user confirmation in its own email case study [V].
  - The part of the HTML that was read does not address computer-use agents [V, partial read].
- **IsolateGPT** (formerly SecGPT; Wu, Roesner, Kohno, Zhang, Iqbal; NDSS 2025; arXiv:2403.04960) [S]. Hub-and-spoke isolation of third-party apps. Overhead is **under 30% for three-quarters of tested queries** ([arXiv:2403.04960](https://arxiv.org/abs/2403.04960v2); [NDSS PDF](https://www.ndss-symposium.org/wp-content/uploads/6A-f1131-Wu.pdf)) [S]. The venues note marks the same overhead claim [fetched] ([arXiv 2403.04960](https://arxiv.org/abs/2403.04960)). Code license NOASSERTION [V].
- **f-secure** (Wu, Cecchetti, Xiao; arXiv:2409.19091) [S]. An IFC security monitor filters untrusted input out of planning ([arXiv:2409.19091](https://arxiv.org/abs/2409.19091v1)) [S]. The venues note marks the abstract claim of security "while preserving functionality and efficiency" [fetched] ([arXiv 2409.19091](https://arxiv.org/abs/2409.19091)). No venue was found [Gap].
- **FIDES** (Costa, Köpf, Kolluri, Paverd, Russinovich et al., Microsoft; arXiv:2505.23643, v2 3 Sep 2025) [S]. A lattice-labelled planner with a stated integrity noninterference guarantee ([arXiv:2505.23643](https://arxiv.org/pdf/2505.23643)) [S]. Exact ASR and utility numbers were not retrieved [Gap]. MIT license [V].
- **ACE** (Abstract-Concrete-Execute; arXiv:2504.20984; NDSS 2026). It plans abstractly from trusted input, runs static IFC checks on the plan, and puts barriers between apps at run time. It breaks IsolateGPT ([arXiv](https://arxiv.org/abs/2504.20984); [NDSS PDF](https://www.ndss-symposium.org/wp-content/uploads/2026-s352-paper.pdf)).
- **Progent** with **hand-written** policies (see tier b).

**Tier (b): deterministic enforcement of an LLM-authored policy.**

- **Progent** (Shi et al.; arXiv:2504.11703) [S]. A DSL for tool-call privilege policies.
  - v2 (Aug 2025) reports **0% ASR with hand-written policies** on AgentDojo, ASB and AgentPoison.
  - With LLM-generated policies on AgentDojo, ASR falls **39.9% → 1.0%** and utility moves 79.4% → 76.3% ([arXiv:2504.11703v2](https://arxiv.org/html/2504.11703v2)) [S].
  - v1 reported 41.2% → 2.2% ([v1](https://arxiv.org/html/2504.11703v1)) [S]. Cite the version you quote.
  - MIT license, active Oct 2026 [V]. It is the closest analogue to GOV-AIOS: both use default-deny privilege policies enforced in code. The difference is that GOV-AIOS policies are human-curated schemas captured from the real accessibility tree, not LLM-generated, and they gate GUI elements.
- **DRIFT** (Li, Liu et al.; arXiv:2506.12104; NeurIPS 2025) [S]. A secure planner, a dynamic validator and an injection isolator ([arXiv](https://arxiv.org/abs/2506.12104); [slides](https://neurips.cc/media/neurips-2025/Slides/116028_p9LqCjy.pdf)). Numbers were not retrieved [Gap].
- **Conseca** (Tsai & Bagdasarian, Google; arXiv:2501.17070; HotOS 2025) [V]. An LLM generates a just-in-time policy from **trusted context only**, and a deterministic enforcer applies it. The prototype is a Linux computer-use agent with preliminary results ([arXiv](https://arxiv.org/abs/2501.17070); [Google Research](https://research.google/pubs/context-is-key-for-agent-security/)).

**Tier (c): probabilistic, judged by an LLM.**

- **MELON** (Zhu et al.; ICML 2025; arXiv:2502.05174) [S]. It re-runs the agent with the user task masked. It claims to block more than 99% of attacks ([ICML](https://icml.cc/virtual/2025/poster/44447)) [S]. It was broken by conditional injections in "The Attacker Moves Second" ([arXiv:2510.09023](https://arxiv.org/abs/2510.09023)) [S]. No license file [V].
- **Task Shield** (Jia, Wu et al.; arXiv:2412.16682) [S]. **2.07% ASR at 69.79% utility** on AgentDojo with GPT-4o ([arXiv](https://arxiv.org/abs/2412.16682)) [S].

**Background.** The Dual LLM pattern (Willison, 25 Apr 2023) is [U, URL not re-fetched] ([simonwillison.net](https://simonwillison.net/2023/Apr/25/dual-llm-pattern/)). The patterns paper says its quarantined LLM "can still be manipulated" [V].

**2026 IFC successors not yet opened, all [U]:**

- GIF ([arXiv:2606.23277](https://arxiv.org/pdf/2606.23277))
- SPA ([arXiv:2608.27234](https://arxiv.org/pdf/2608.27234))
- APPA ([NeurIPS 2026](https://neurips.cc/virtual/2026/168263))
- "Provably Secure Agent Guardrail" ([arXiv:2605.29251](https://arxiv.org/pdf/2605.29251))
- AgentSys ([arXiv:2602.07398](https://arxiv.org/pdf/2602.07398))

**These must be read before the novelty claim goes out**, because any of them could already mediate GUI actions.

### Model-level defenses collapse under adaptive attack

Model-level defenses cut static-attack ASR to near zero, but the protection depends on the attack distribution.

- **Spotlighting** (Hines et al., arXiv:2403.14720): reports >50% to <2% ASR [U] ([arXiv](https://arxiv.org/abs/2403.14720)).
- **StruQ** (Chen, Piet, Sitawarin, Wagner; arXiv:2402.06363; USENIX Security 2025) [U for ID and venue]: stops optimization-free attacks but not optimization-based ones ([BAIR blog](https://bair.berkeley.edu/blog/2025/04/11/prompt-injection-defense)) [S].
- **SecAlign** (arXiv:2410.05451, CCS 2025) [S]: about 8% ASR for the strongest attack on Llama3-8B ([arXiv](https://arxiv.org/html/2410.05451v3)) [S].
- **Meta SecAlign** (arXiv:2507.02735, v3 Feb 2026) [S]: **1.9% AgentDojo ASR for the 70B model, against about 14.7% for the base model, and 0% on WASP** ([arXiv v3](https://arxiv.org/html/2507.02735v3); [HF card](https://huggingface.co/facebook/Meta-SecAlign-70B/blob/main/README.md)) [S]. Figures change across versions.
- **Instruction Hierarchy** (Wallace et al., OpenAI; arXiv:2404.13208) [V for ID and authors; results S]: over-refusal is a known drawback ([arXiv](https://arxiv.org/abs/2404.13208v1)).
- **DataSentinel** (Liu, Jia, Jia, Song, Gong; IEEE S&P 2025; arXiv:2504.11358) [S]: FPR near 0 and FNR near 0 up to 0.07 ([arXiv](https://export.arxiv.org/abs/2504.11358); [PSU](https://pure.psu.edu/en/publications/datasentinel-a-game-theoretic-detection-of-prompt-injection-attac/)). MIT code [V].
- **Llama Prompt Guard 2**: PromptGuard 1 was reported bypassable by character spacing [U, not fetched] ([HF](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M)).

Three adaptive-attack papers carry the paper's central argument.

- **"The Attacker Moves Second"** (Nasr, Carlini, Sitawarin, Schulhoff et al.; arXiv:2510.09023) [S]. Of 12 published defenses, **most exceeded 90% ASR under adaptive attack**, despite near-zero original numbers. Human red-teaming succeeded in every scenario.
- **"A Critical Evaluation of Defenses against Prompt Injection Attacks"** (arXiv:2505.18333) [S]. GCG reaches **>0.80 ASR against StruQ and 0.72 against SecAlign** ([arXiv](https://arxiv.org/pdf/2505.18333)).
- **"Adaptive Attacks Break Defenses Against Indirect Prompt Injection Attacks on LLM Agents"** (arXiv:2503.00061) [S, title only] and **PISmith** (arXiv:2603.13026) [U, title only] support the same point ([2503.00061](https://arxiv.org/pdf/2503.00061); [2603.13026](https://arxiv.org/pdf/2603.13026)).

NIST CAISI's agent-hijacking evaluation gives the government-grade version of the argument ([NIST CAISI blog](https://www.nist.gov/node/1872381)) [V]:

- Red teaming raised ASR **from 11% to 81%** on held-out AgentDojo Workspace tasks.
- The average across five injection tasks was **57%, rising to 80% with 25 attempts per task**.
- A follow-on public competition drew more than 250,000 attacks and found at least one successful attack against all 13 frontier models [V, search snippet] ([CAISI](https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition)).

The framing for the paper follows from this. A model-level defense reduces *the probability that the model is fooled*. A deterministic gate turns that into *the probability that a non-schema action executes*, which is zero by construction. GOV-AIOS is orthogonal to these defenses and can be stacked with them: a Meta-SecAlign-class backbone reduces how often a denial or prompt fires, which helps usability, not security.

### Surveys call for OS-style mediation but name no GUI solution

Two papers give the paper a ready-made agenda to instantiate.

- **"Systems Security Foundations for Agentic Computing"** (Christodorescu, Fernandes, Hooda, Jha, Rehberger, Chaudhuri et al.; arXiv:2512.01295, v2 19 Feb 2026). It argues that prior work "lacks system-security perspective and guarantees" ([arXiv](https://arxiv.org/abs/2512.01295)) [V, abstract only]. The computer-use note marks it [UNVERIFIED: content not read] ([HTML v2](https://arxiv.org/html/2512.01295v2)).
- **"Toward Securing AI Agents Like Operating Systems"** (Pirch, Horlboge, Großmann, Asif, Kireev, Holz, Rieck; arXiv:2605.14932). It finds that "several protection mechanisms fail in practice" in four OpenClaw-like agents, and that OS techniques mitigate many of the issues ([arXiv](https://arxiv.org/abs/2605.14932)) [V]. Its abstract does not cover human approval or GUI agents.

Other surveys to cite:

- The CUA threat survey "JARVIS or Ultron?" ([arXiv:2505.10924](https://arxiv.org/pdf/2505.10924)) [S, title only]
- The ACM Computing Surveys agent-security survey ([DOI 10.1145/3773080](https://dl.acm.org/doi/full/10.1145/3773080)) [S, title only]
- "A Framework for Formalizing LLM Agent Security" ([arXiv:2603.19469](https://arxiv.org/pdf/2603.19469)) [U]
- "Security of OpenClaw Agents" ([arXiv:2605.25435](https://arxiv.org/pdf/2605.25435)) [U]
- "OS Agents" (Hu et al., arXiv:2508.04482), which treats safety only as a future direction [depth not verified] ([arXiv](https://arxiv.org/abs/2508.04482v1))

**Neither survey's open-problem list was confirmed to mention presence-bound approval or accessibility-tree mediation.** Their silence supports the novelty claim but does not prove it.

---

## Computer-use agents fail at perception, and the page schema answers that structurally

### Attacks on GUI agents succeed 50–100% of the time

The attack literature for screenshot, accessibility-tree and DOM agents is consistent: the agent misreads what it sees, and prompt-level defenses fail.

**Vendor-agent exploits**

- **ZombAIs** (Rehberger, Oct 2024). An injected web page made Claude Computer Use download a binary, `chmod` it and join a Sliver C2 server on the first try ([Embrace The Red](https://embracethered.com/blog/posts/2024/claude-computer-use-c2-the-zombais-are-coming)).
- A 2026 follow-up reports **78% ASR against Claude Sonnet 4.5** [UNVERIFIED; minor venue] ([Jurnal Sisfokom](https://jurnal.atmaluhur.ac.id/index.php/sisfokom/article/view/2634)).
- Rehberger's Operator exploits found that "just typing text hardly ever triggers any confirmations" ([Embrace The Red 2025](https://embracethered.com/blog/posts/2025/chatgpt-operator-prompt-injection-exploits)). His 39C3 talk covers coding agents as well ([CCC](https://events.ccc.de/congress/2025/hub/de/schedule/day:2/kind:all/recorded:1/track:security)).
- Secondary coverage of the Operator system card reports injection susceptibility falling **from 62% to 23%** with mitigations [UNVERIFIED: primary card not fetched; it returned 403] ([3l3c summary](https://www.3l3c.ai/us/blog/ai-in-cybersecurity/operator-system-card-security)).

**Academic attacks and benchmarks**

| Work | Setting | Headline result | Tag/venue |
|---|---|---|---|
| EIA (Liao et al., arXiv:2409.11295) | Form/Mirror Injection on Mind2Web, 177 steps | ≤70% ASR for specific PII; 16% for full request; defensive prompt fails | ICLR 2025 ([arXiv](https://arxiv.org/abs/2409.11295)); [M] in synthesis note |
| Pop-ups (Zhang, Yu, Yang, arXiv:2411.02391) | OSWorld + VisualWebArena | **86% avg ASR, −47% task success**; "ignore pop-ups" ineffective; hits SoM (screenshot+a11y) agents | ACL 2025 ([arXiv](https://arxiv.org/abs/2411.02391)) |
| VPI-Bench (Cao et al., arXiv:2506.02456) | 306 visual-injection cases, 5 platforms | ≤51% CUA, ≤100% browser-use ASR | ICLR 2026 poster ([arXiv](https://arxiv.org/abs/2506.02456); [ICLR](https://iclr.cc/virtual/2026/poster/10009231)) |
| WASP (Evtimov et al., arXiv:2504.18575) | VisualWebArena sandbox | Partial hijack in 16–86% of cases; full attacker goal 0–17% ("security by incompetence") | NeurIPS 2025 [S]/[V] ([arXiv](https://arxiv.org/abs/2504.18575v3)) |
| OS-Harm (arXiv:2506.14866) | 150 OSWorld tasks | o4-mini follows basic injections ~20%; LLM judge F1 0.76/0.79 | NeurIPS 2025 D&B Spotlight ([arXiv](https://arxiv.org/abs/2506.14866); [NeurIPS](https://neurips.cc/virtual/2025/poster/121772)) |
| RedTeamCUA (arXiv:2505.21936) | Hybrid web+OS | Adding the a11y tree **lowers ASR** for nearly all CUAs | ([arXiv](https://arxiv.org/pdf/2505.21936)) |
| RedCode (Guo et al., arXiv:2411.07781) | 4,050 risky Python/Bash cases in Docker | Agents refuse risky natural-language requests less often than the same operations as code | NeurIPS 2024 D&B ([arXiv](https://arxiv.org/abs/2411.07781)) |
| Johnson et al. (arXiv:2507.14799) | Universal triggers in the HTML accessibility tree | Hijacks a11y-reading agents in BrowserGym | EMNLP 2025 Demos ([arXiv](https://arxiv.org/abs/2507.14799)) |
| Mobile GUI hijack (arXiv:2507.04227) | Android Accessibility events | Consistent tree+screenshot poisoning; >3,000 adversarial states | ([arXiv](https://arxiv.org/html/2507.04227v2)) |
| Env. injection in dynamic GUIs (arXiv:2509.11250) | GUI agents | — | [UNVERIFIED: abstract not read] ([arXiv](https://arxiv.org/pdf/2509.11250)) |

Further attack and benchmark citations from the synthesis note:

- BrowseSafe ([arXiv:2511.20597](https://arxiv.org/html/2511.20597v1)) [S]
- Greshake et al., the foundational indirect-injection paper ([arXiv:2302.12173](https://arxiv.org/abs/2302.12173)) [M]
- Unverified 2026 titles: AgentDyn ([arXiv:2602.03117](https://arxiv.org/html/2602.03117v1)) [S], INFUSE ([arXiv:2610.20776](https://arxiv.org/html/2610.20776v1)) [U], "Indirect Prompt Injection in the Wild" ([arXiv:2604.27202](https://arxiv.org/pdf/2604.27202)) [U], "Agent Data Injection Attacks are Realistic Threats" ([arXiv:2607.05120](https://arxiv.org/pdf/2607.05120)) [U], "The Blind Spot of Agent Safety" ([arXiv:2604.10577](https://arxiv.org/pdf/2604.10577)) [U]

**What this means for GOV-AIOS.** EIA's Mirror and Form Injection and the pop-up attacks all add elements that are not in the admin-captured schema. Those elements cannot be acted on, whatever the model believes. That is the structural argument.

The accessibility-tree attacks (2507.14799, 2507.04227) cut the other way. They show the tree itself is attacker-influenced. The paper must therefore argue that GOV-AIOS uses the tree for **structural identification** (role, identifier, hierarchy position, page fingerprint), not as instruction text, and that page identification uses more than labels.

**No paper attacking the macOS AX API specifically was found.** The paper can note this as a gap, and its own suite can fill it.

### Learned guardrails are the only prior UI-element policy

No prior work was found that enforces an admin-captured, per-page allowlist of accessibility elements with risk ratings, gated on page identity, as a deterministic reference monitor. The closest work is all learned.

- **WebGuard** (arXiv:2507.14293): a classifier trained on 193 sites with human-annotated risk levels ([arXiv](https://arxiv.org/abs/2507.14293)). A 2026 DoS paper runs it against BrowserGym's accessibility tree and shows guardrails can themselves be attacked ([arXiv:2606.14517](https://arxiv.org/pdf/2606.14517)).
- **ShieldAgent** (arXiv:2503.22738): probabilistic rule circuits, 90.1% recall ([arXiv](https://arxiv.org/abs/2503.22738)).
- **GuardAgent** (Xiang et al.; arXiv:2406.09187; ICML 2025) [V metadata, S numbers]: about 98% on EICU-AC and about 83% on Mind2Web-SC ([arXiv](https://arxiv.org/abs/2406.09187); [PMLR](https://proceedings.mlr.press/v267/xiang25a.html)). The computer-use note lists it [UNVERIFIED: arXiv ID not retrieved]. The synthesis note supplies and verifies the ID.
- **PolicyGuard-4B** (arXiv:2510.03485) ([arXiv](https://arxiv.org/abs/2510.03485)).

Framing for the paper:

- The schema is **"capabilities for GUIs"**: an element ID on a verified page is an unforgeable handle. This ties the design to CaMeL and ACE.
- The page schema creates an API boundary where a GUI has none by default.

**Unchecked prior art that could weaken the claim:** RPA and enterprise automation tools (UiPath and others) that allowlist UI selectors for governance.

### Vendor sandboxes confine subprocesses, and the hooks are the enforcement point

**Claude Code sandbox** (docs fetched 2026-11-06; [sandboxing docs](https://code.claude.com/docs/en/sandboxing)):

- Built on Seatbelt on macOS and bubblewrap on Linux. It is off by default.
- It confines Bash, PowerShell and Monitor commands.
- Reads are allowed across most of the disk by default, including `~/.ssh`.
- It denies writes to `.claude`, `.mcp.json`, shell rc files and `.git/hooks`.
- **It does not sandbox file tools, WebFetch, hooks, local MCP servers or LSP servers.**
- It can be made admin-required with `sandbox.enabled`, `failIfUnavailable` and `allowUnsandboxedCommands:false`. Repository settings cannot loosen it as of v2.1.285.

**Codex.** The docs separate the sandbox from the approval policy ([Codex sandboxing](https://developers.openai.com/codex/concepts/sandboxing.md)).

- Managed `requirements.toml` provides "admin-enforced constraints that users can't override" ([Codex managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)). It covers approval policies, permission profiles (0.138.0+), `deny_read`, an `mcp_servers` allowlist, `prefix_rules`, `[network_proxy]` (0.166.0), `browser_use`/`computer_use` feature flags, and managed hooks.
- `approval_policy="untrusted"` is no longer supported.
- **The `/etc/codex/requirements.toml` path** and the runtime SBPL generation come only from a **third-party source** ([Vaughan, requirements](https://codex.danielvaughan.com/2026/03/31/codex-cli-network-security-requirements-toml/); [Vaughan, sandbox](https://codex.danielvaughan.com/2026/03/26/codex-cli-approval-modes-sandbox-security)). The official page section that was fetched was truncated before the file locations.

**macOS `sandbox-exec` is deprecated**, with no Apple replacement for non-App-Sandbox processes ([apple/containerization #737](https://github.com/apple/containerization/issues/737)). It still worked on Sequoia in March 2026 ([gastown](https://gastown.dev/docs/research/macos-sandbox-exec)). For SBPL background, the 2011 guide ([mirror](https://https-reverse_put_as.proxy.bugsmash.io/wp-content/uploads/2011/09/Apple-Sandbox-Guide-v1.0.pdf)) is [UNVERIFIED: Apple's primary docs not fetched].

**Kubernetes SIG Agent Sandbox** isolates server-side agents with gVisor ([repo](https://github.com/kubernetes-sigs/agent-sandbox); [blog](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/)). No peer-reviewed "AgentSandbox" paper exists ([agent-sandbox](https://github.com/agent-sandbox/agent-sandbox)).

**Two framing points.**

1. Vendor sandboxes confine the *agent's subprocesses*. GOV-AIOS confines *itself* with `sandbox_init`. That is the opposite direction, and the deprecated interface is a maintenance risk GOV-AIOS shares with industry.
2. **AIOS** (Mei, Zhang et al., Rutgers; arXiv:2403.16971) is a different system that happens to share the name. It is an agent scheduling and resource kernel, its access manager covers only agent-to-agent memory and logs, and it confirms irreversible operations ([arXiv](https://arxiv.org/abs/2403.16971v1); [HTML v3](https://arxiv.org/html/2403.16971v3)). GOV-AIOS is a governance layer on macOS that mediates existing third-party agents through TCC, Seatbelt and vendor hook points. **State this in the introduction**, and consider spelling out "GOV" in the title.

### MCP has no tool-integrity mechanism, and agent-writable config defeats approval

**MCP attacks.** Invariant Labs disclosed **tool poisoning** on 1 Apr 2025: a harmless-looking `add` tool exfiltrated `~/.ssh/id_rsa` from Cursor ([Invariant Labs](https://invariantlabs.ai/blog/mcp-security-notification)). Rug pulls (definitions changed through `tools/list_changed`, with no re-approval) and tool shadowing come from [secondary sources] ([CSA](https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-tool-poisoning-20260506-csa-styl/)). MCP-Scan's hash pinning is dated about 11 Apr 2025 [date UNVERIFIED] ([Taskade](https://www.taskade.com/wiki/ai/tool-poisoning)).

**MCP Security Best Practices** (draft, fetched 2026-11-06; [MCP spec](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)). It covers the OAuth confused deputy, token passthrough, SSRF, and local-server installation. It requires showing the exact command and getting explicit approval before a one-click local install, and it recommends running servers in a sandbox. **It defines neither tool-description integrity nor re-consent when a tool changes.**

**Cursor.** **CurXecute (CVE-2025-54135, CVSS 8.5)** let a prompt injection write `.cursor/mcp.json` and get RCE. **MCPoison (CVE-2025-54136)** let an approved config be changed later without re-approval. Both were fixed in Cursor 1.3 on 29 Jul 2025. BackSlash's denylist bypass pushed Cursor to an allowlist ([Tenable](https://www.tenable.com/blog/faq-cve-2025-54135-cve-2025-54136-vulnerabilities-in-cursor-curxecute-mcpoison); [The Hacker News](https://thehackernews.com/2025/08/cursor-ai-code-editor-fixed-flaw.html)).

**Claude Code hooks** ([hooks docs](https://code.claude.com/docs/en/hooks)):

- PreToolUse returns allow, deny, ask or defer, and can rewrite input.
- **Exit code 2 blocks the call. Other non-zero exits do not block unless `"onFailure":"block"` is set (v2.1.295+), and a PreToolUse hook that times out does not block by default.**
- PostToolUse cannot prevent execution.
- `allowManagedHooksOnly` blocks user, project and plugin hooks.
- The docs call the `if` filter best-effort.

**Who controls each enforcement point:**

| Enforcement point | Inside or outside model control |
|---|---|
| Operator confirmations and injection monitor; system-prompt defenses | Inside / model-adjacent |
| Claude Code managed PreToolUse; Codex requirements and prefix rules; OS sandboxes; MCP client consent | Outside (deterministic, harness-run) |
| Claude Code auto mode | Hybrid (a classifier reviews actions) |

GOV-AIOS uses only outside points, with TCC as the root of trust: only the signed app holds the Accessibility and Screen Recording grants.

**The strongest point here is that policy lives where the agent cannot write**: root-owned managed settings and requirements files. That is exactly the defense CurXecute and MCPoison show is needed.

**Not researched:** enterprise AI/MCP gateways, Copilot agent-mode safeguards, and Codex hook exit-code semantics. The unified cross-vendor, cross-modality audit claim is plausible but unchecked against gateways.

---

## Presence binding fixes self-approval, not approval fatigue

### Users approve 93% of prompts, and fatigue is an exploitable attack surface

**Vendor telemetry is the best current evidence.**

- Anthropic reports that Claude Code users **accept 93% of manual permission prompts** ([Anthropic auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode)) [V].
- Auto mode escalates after "3 consecutive denials or 20 total". Its classifier has a 17% false-negative rate on real overeager actions (n=52), 5.7% on synthetic exfiltration (n=1,000), and a 0.4% false-positive rate end to end. Anthropic says it "is not a drop-in replacement for careful human review on high-stakes infrastructure" [V].
- Sandboxing "safely reduces permission prompts by 84%" ([Anthropic sandboxing](https://www.anthropic.com/engineering/claude-code-sandboxing)) [V].
- Third-party figures disagree (93% vs 97%) ([tessl](https://tessl.io/blog/claude-code-gets-auto-mode-to-cut-approval-fatigue/); [techwyse](https://www.techwyse.com/news/platform-updates/anthropic-claude-code-auto-mode-default)) [V, secondary]. **Cite only the primary 93%.**

**Academic and attack work.**

- Wang, Li and Tian (arXiv:2605.24309) found runtime approval in **15 of 21 production agent systems**, with users "caught between approval fatigue and uncontrolled agent autonomy" ([arXiv](https://arxiv.org/abs/2605.24309)) [V].
- **Lies-in-the-Loop** (Checkmarx Zero, Sept 2025): indirect injection makes the agent misrepresent its own approval dialog, demonstrated as RCE on Claude Code from a GitHub issue ([Checkmarx](https://checkmarx.com/zero-post/bypassing-ai-agent-defenses-with-lies-in-the-loop/); [OWASP](https://owasp.org/www-community/attacks/Lies_in_the_Loop); [Dark Reading](https://www.darkreading.com/application-security/-lies-in-the-loop-attack-ai-coding-agents)) [V].
- User-mediated attacks (arXiv:2601.10758) [V, abstract only] ([arXiv](https://arxiv.org/html/2601.10758)).

**Usable-security background.**

- **Alice in Warningland** (Akhawe & Felt, USENIX Security 2013): more than 25M warning impressions. Users clicked through 70.2% of Chrome SSL warnings and about 33% of Firefox SSL warnings ([USENIX](https://www.usenix.org/conference/usenixsecurity13/technical-sessions/presentation/akhawe)) [V].
- **Android permissions** (Felt et al., SOUPS 2012): only 17% of participants attended to permissions at install time ([DOI 10.1145/2335356.2335360](https://unpaywall.org/10.1145%2F2335356.2335360); [TR](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2012/EECS-2012-26.html)) [V].
- **fMRI habituation** (Anderson et al., CHI 2015): habituation is automatic, and polymorphic warnings resist it ([DBLP](https://dblp.uni-trier.de/rec/conf/chi/AndersonKJEHV15.html); [BYU](https://scholarsarchive.byu.edu/facpub/9306)) [V]. DOI 10.1145/2702123.2702322 [U].
- **Vance et al., MISQ 2018**: longitudinal results ([PDF](https://misq.umn.edu/pub/skin/frontend/default/misq/pdf/V42I2/14124_RA_VanceJenkins.pdf)) [V, partial]. DOI 10.25300/MISQ/2018/14124 [U].
- **"Fog of Warnings"** (SOUPS 2019): habituation to benign notifications carries over to security warnings ([USENIX](https://www.usenix.org/conference/soups2019/presentation/vance)) [V].
- **Bravo-Lillo et al.**: inhibitive attractors (SOUPS 2013, [PDF](https://microsoft.com/en-us/research/wp-content/uploads/2016/02/a6_Bravo-Lillo.pdf); SOUPS 2014, [USENIX](https://www.usenix.org/conference/soups2014/proceedings/presentation/bravo-lillo)) [V]. The 2013 DOI is [U].
- **Böhme & Köpsell** (CHI 2010) [U] and **Utz et al.** (CCS 2019) [U] on consent dialogs.

**MFA push fatigue is the closest real-world analogue.**

- In the 2022 Uber breach, the contractor received repeated pushes until "Eventually, however, the contractor accepted one" ([Uber](https://www.uber.com/newsroom/security-update/)) [V].
- **NIST SP 800-63B-4** (July 2025) says approve-only push "is no longer considered acceptable". It requires push rate limits (§3.1.3.2) and limits on failed attempts (§3.2.2), and says a newly generated secret "SHALL NOT reset the failed authentication count" ([NIST](https://pages.nist.gov/800-63-4/sp800-63b.html); [CSRC](https://csrc.nist.gov/pubs/sp/800/63/b/4/final)) [V].
- Jubur, Shrestha, Saxena and Prakash (AsiaCCS 2021) [V, title/venue only]. The original prompt attributed this paper to "Shirvanian", which is wrong ([researchr](https://researchr.org/publication/JuburSSP21); [PDF](https://nsaxena.engr.tamu.edu/wp-content/uploads/sites/238/2023/10/3433210.3453084.pdf)).

**The honest claim for the paper.** Presence binding defends against **an autonomous agent approving its own actions and against approvals happening while the user is away**. It does not solve approval fatigue.

GOV-AIOS reduces fatigue in four ways:

- It approves per artifact (a digest-pinned flow) instead of per tool call.
- It reserves prompts for high-risk elements.
- It applies exponential backoff after refusals, the agent-side analogue of NIST's push rate limit and Claude Code's denial cap.
- It varies the prompt text per request (flow name plus code), a weak form of polymorphism.

Because the governance layer, not the model, writes the prompt from the flow digest, GOV-AIOS is a direct countermeasure to Lies-in-the-Loop. Claim this explicitly.

**No controlled 2023–2026 user study was found that measures how often people approve harmful agent actions.** That is either a contribution the paper can make or a limitation it must declare.

### Standards separate presence from intent, and GOV-AIOS's code is the weaker "compare" form

**WebAuthn.** Level 3 became a W3C Recommendation on 25 Aug 2026. It has no transaction-authorization extension ([W3C](https://www.w3.org/TR/webauthn-3/)) [V]. The UP/UV flag bits and the dropped L1 `txAuthSimple` extension are [U] ([L2](https://www.w3.org/TR/webauthn-2/); [L1](https://www.w3.org/TR/2019/REC-webauthn-1-20190304/)).

**What-you-see-is-what-you-sign patterns**, all [U]:

- W3C Secure Payment Confirmation ([SPC](https://www.w3.org/TR/secure-payment-confirmation/))
- FIDO UAF Transaction Confirmation Display ([FIDO](https://fidoalliance.org/specs/fido-uaf-v1.2-ps-20201020/fido-uaf-authnr-cmds-v1.2-ps-20201020.html))
- Landrock & Pedersen's WYSIWYS (1998)
- PSD2 RTS Art. 5 dynamic linking ([EUR-Lex 2018/389](https://eur-lex.europa.eu/eli/reg_del/2018/389/oj))

**NIST SP 800-63B-4 §3.1.3** ([NIST](https://pages.nist.gov/800-63-4/sp800-63b.html)) [V]:

- It requires "transfer of the secret" between channels, and says "Presenting the claimant with a list of secrets to compare is not sufficient."
- A biometric "SHALL only be used as part of multi-factor authentication with a physical authenticator."
- Manually entered outputs such as TOTP "SHALL NOT be considered phishing-resistant."

**Number matching.** Microsoft Entra makes users *enter* the number, but allows Approve/Deny on the same device ([Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity/authentication/how-to-mfa-number-match)) [V]. Enforcement began 8 May 2023 [V, secondary] ([BleepingComputer](https://www.bleepingcomputer.com/news/microsoft/microsoft-enforces-number-matching-to-fight-mfa-fatigue-attacks/amp/); [Sikich](https://www.sikich.com/insight/microsoft-mfa-update-in-may-2023-number-matching/)). CISA calls number matching an interim mitigation ([CISA](https://www.cisa.gov/sites/default/files/publications/fact-sheet-implement-number-matching-in-mfa-applications-508c.pdf)) [V].

**Apple.** `LAContext.evaluatePolicy` returns a boolean to the caller, and the `localizedReason` text is supplied by the caller. `SecAccessControl` `.biometryCurrentSet` instead gates a Secure Enclave key [U] ([LAContext](https://developer.apple.com/documentation/localauthentication/lacontext); [Platform Security](https://support.apple.com/guide/security/welcome/web)).

**Mapped onto GOV-AIOS:**

- Touch ID is UV, not just UP.
- The 4-letter code is number matching in its **compare** form. GOV-AIOS can defend it on two grounds: both displays are on the same machine, and the code sits inside the OS-rendered sheet, much like Microsoft's same-device exception. The paper must still concede that the human may skip the comparison.
- Digest-bound approval is **WYSIWYS / dynamic linking applied to agent actions**.
- The 30-minute TOTP session is NIST-style reauthentication. It ends on screen lock, but it is not phishing-resistant, so rank it below Touch ID.

### Delegation research assumes the local presence problem is already solved

**Vendor guidance converges on confirmation plus isolation.**

- Anthropic's computer-use docs recommend a VM, no credentials, a domain allowlist, and human confirmation for consequential actions "before each block runs" ([Claude docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool)) [V].
- OpenAI says Operator should "ask for approval" before significant actions ([OpenAI](https://openai.com/index/introducing-operator/)) [V].
- Google (Díaz, Kern, Olive) sets out three principles: defined human controllers, limited powers, observable actions ([Google Research](https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/); [Willison](https://feeds.simonwillison.net/2025/Jun/15/ai-agent-security/)) [V].

**Network delegation schemes.**

- South et al., "Authenticated Delegation and Authorized AI Agents" (arXiv:2501.09674): OAuth/OIDC credentials ([arXiv](https://arxiv.org/abs/2501.09674)) [V].
- IETF draft-oauth-ai-agents-on-behalf-of-user (-02, Aug 2025; not adopted by a working group) ([datatracker](https://datatracker.ietf.org/doc/html/draft-oauth-ai-agents-on-behalf-of-user-02)) [V].
- Chan et al., "Visibility into AI Agents" (FAccT 2024; arXiv:2401.13138) ([arXiv](https://arxiv.org/abs/2401.13138v6)) [V]. Its siblings "IDs for AI Systems" (arXiv:2406.12137) and "Infrastructure for AI Agents" (arXiv:2501.10114) are [U].

**Position GOV-AIOS as complementary.** These schemes take for granted the local presence and intent problem that GOV-AIOS solves. GOV-AIOS's "credential" is the local approval record, with no issuer and no relying party.

### A same-UID hash chain detects edits but not rewrites

**Classic secure-logging schemes.**

- **Schneier & Kelsey** (TISSEC 1999). Volume and issue are cited inconsistently. Their scheme makes pre-compromise entries "impossible to undetectably modify or destroy" ([Schneier](https://www.schneier.com/academic/archives/1999/05/secure_audit_logs_to.html); [1998 PDF](https://www.cs.unc.edu/~fabian/courses/CS600.624/paper-secure-logs.pdf)) [V]. DOI 10.1145/317087.317089 is [U].
- **Crosby & Wallach** (USENIX Security 2009) history trees: tampering is detectable only relative to a commitment held outside the logger [U, PDF unreadable] ([USENIX](https://www.usenix.org/legacy/event/sec09/tech/full_papers/crosby.pdf)).
- **Forward-secure schemes**, all [U]: Bellare & Yee (1997); Ma & Tsudik, FssAgg (TOS 2009, DOI 10.1145/1502777.1502779), which addresses truncation; and Marson & Poettering (ESORICS 2013, DOI 10.1007/978-3-642-40203-6_7), the basis of journald's Forward Secure Sealing.
- **Certificate Transparency**, [U]: RFC 6962 and RFC 9162 ([6962](https://www.rfc-editor.org/rfc/rfc6962); [9162](https://www.rfc-editor.org/rfc/rfc9162)), with witnesses ([Trillian](https://github.com/google/trillian); [Sigsum](https://www.sigsum.org/)).
- **Haber & Stornetta** (1991, DOI 10.1007/BF00196791) [U].

**Agent observability defines what to log, not how to protect it.**

- OpenTelemetry GenAI conventions have moved to their own repository and include no integrity provisions ([OTel](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/); [repo](https://github.com/open-telemetry/semantic-conventions-genai)) [V]. The span names are [U].
- AgentOps (arXiv:2411.05285) [U].
- Chan et al. and South et al. call for audit trails without specifying tamper evidence [V].

**No 2023–2026 tamper-evident log built for LLM agents was found.**

GOV-AIOS's `verify-audit` detects mid-log edits made without re-hashing, and it detects accidental corruption. If someone holds a copy of the head hash outside the machine, every prefix up to that head can be verified. It does **not** protect against any of these:

- full rewrite by the same UID;
- truncation or whole-file deletion;
- compromise of a persistent key (no forward security);
- forks or split views;
- a compromised daemon omitting events;
- unauthenticated timestamps.

---

## Studio is the first synthesis loop to verify security rather than function

### Synthesis prior art validates task success, not safety

There are three lineages:

1. **Instruction-to-workflow generation.** ProAgent (arXiv:2311.10751) [V] embeds LLM judgment inside the running workflow. WorkflowLLM (arXiv:2411.05451) [V] fine-tunes on 106,763 Shortcuts-style workflows and scores with CodeBLEU and an LLM judge ([arXiv](https://arxiv.org/abs/2411.05451v1); [HF](https://huggingface.co/papers/2411.05451)). UiPath Autopilot [V for doc wording] ([docs](https://docs.uipath.com/autopilot/other/latest/user-guide/about-autopilot); [KMWorld](https://www.kmworld.com/Articles/News/News/UiPaths-Autopilot-blends-AI-and-automation-for-enhanced-workflow-productivity--161101.aspx); [CX Today](https://www.cxtoday.com/data-analytics/uipaths-new-autopilot-turns-paper-documents-into-automation-apps/)) and Power Automate Copilot [V] ([MS Learn](https://learn.microsoft.com/en-us/power-automate/desktop-flows/copilot-in-power-automate-for-desktop); [release plan](https://learn.microsoft.com/en-us/power-platform/release-plan/2024wave1/power-automate/create-desktop-flows-using-natural-language-copilot-power-automate-desktop)) rely on a human reviewing the result in a designer.
2. **Learning from demonstrations.** ECLAIR (arXiv:2405.03710; PVLDB 17, DOI 10.14778/3681954.3681964) [V metadata, S details] validates task completion and sends unmasked screenshots to GPT-4V ([arXiv](https://arxiv.org/abs/2405.03710); [Crossref](https://api.crossref.org/works/10.14778%2F3681954.3681964)).
3. **Induction from agent trajectories**:
   - **AWM** (arXiv:2409.07429) [V] gets +12.0 points on WebArena with soft-prompt workflows ([arXiv](https://arxiv.org/abs/2409.07429)).
   - **ASI** (arXiv:2504.06821; COLM 2025) [V] **re-executes each induced skill on test trajectories before accepting it**, and beats AWM by 11.3% ([arXiv](https://arxiv.org/abs/2504.06821)).
   - **SkillWeaver** (arXiv:2504.07079) [V] reports +31.8% on WebArena and +39.8% on real sites, using unsandboxed Python/Playwright skills ([arXiv](https://arxiv.org/abs/2504.07079v1)). Some summaries give 25–38% [S, conflicting]. Cite the abstract.

**Studio is the next step on the AWM → ASI → SkillWeaver line**, from functionally verified to security-verified and human-signed. Its DSL is closed and not Turing-complete, which keeps the static checks decidable.

**Page representations** support the accessibility-tree choice:

- **WebArena** uses the accessibility tree by default (arXiv:2307.13854) [M] ([arXiv](https://arxiv.org/abs/2307.13854)). The roughly 14% GPT-4 vs 78% human figure is [M, from memory].
- **OSWorld**: a11y agents scored about 2.4–12.2% against 5.3% for screenshot-only (arXiv:2404.07972) [V]; the numbers are [S] ([PDF](https://arxiv.org/pdf/2404.07972)).
- **OS-Harm**: a11y 21.1% vs screenshot 5.3% on Gemini 2.5 Pro [S].
- **OSWorld-Human**: the accessibility tree "drastically increases per-task latency" [S] ([OS-Harm](https://arxiv.org/pdf/2506.14866); [OSWorld-Human](https://arxiv.org/pdf/2506.16042)).
- **SeeAct** [M] ([arXiv](https://arxiv.org/abs/2401.01614)); **Aria-UI** 15.15% [S] ([PDF](https://arxiv.org/pdf/2412.16256)); **Mind2Web** [M] ([arXiv](https://arxiv.org/abs/2306.06070)).
- **WorkArena** (ICML 2024) [V] for enterprise evaluation ([arXiv](https://arxiv.org/html/2403.07718v5); [PMLR](https://proceedings.mlr.press/v235/drouin24a.html); [blog](https://www.servicenow.com/blogs/2024/introducing-workarena-benchmark)). WorkArena++ (arXiv:2407.05291) is [M].

Studio reads the tree **once, at authoring time**, so it pays the latency cost once and needs no screenshots at run time.

### "LLM proposes, verifier disposes", applied to authoring

**Grammar-constrained decoding guarantees syntax only.**

- SynCode (arXiv:2403.01632) [V] ([arXiv](https://arxiv.org/abs/2403.01632v4)); XGrammar (arXiv:2411.15100) [V] ([arXiv](https://arxiv.org/html/2411.15100v3)).
- Outlines [M] ([arXiv](https://arxiv.org/abs/2307.09702)); Geng et al. [M] ([arXiv](https://arxiv.org/abs/2305.13971)).
- "When Grammar Guides the Attack" (arXiv:2503.24191) [S, title and ID only] warns that grammars can open jailbreak vectors ([arXiv](https://arxiv.org/pdf/2503.24191)).

**LLM-generates, checker-checks.**

- **Clover** (arXiv:2310.17807; SAIV 2024) [V]: accepts up to 87% of correct instances with **zero false positives** ([arXiv](https://arxiv.org/abs/2310.17807)).
- **Self-Debugging** [M] is the precedent for retrying with verifier feedback ([arXiv](https://arxiv.org/abs/2304.05128)).

**Policy generators**, each with a difference from Studio:

- **Conseca** sees only trusted context. Studio *must* see untrusted page structure, so it masks row and cell text, floors risk and trims permissions independently of what the LLM claims.
- **Progent** lets an LLM write policies. Studio *derives* permissions from the actions the generated program actually uses ([arXiv](https://arxiv.org/abs/2504.11703v2)) [V].
- **CaMeL** generates a program per query at run time. Studio generates once, verifies statically against a captured tree, and has a human sign the result.
- **GuardAgent** generates guardrail code.
- **AgentSpec** (arXiv:2503.18666) is [M], ID unconfirmed.

**Least-privilege inference.**

- CELLMATE (arXiv:2512.12594) [S] is deny-by-default per web app ([PDF](https://arxiv.org/pdf/2512.12594)).
- AuthBench (arXiv:2605.14859) [S, **unverified**: seen only on aggregator pages] reports that LLMs both over- and under-grant permissions ([aggregator](https://awesomepapers.io/papers/2605.14859)). If verified, it motivates deterministic permission trimming directly.

**The "risk can only go up" rule.** The verifier takes the maximum of the LLM's label and a floor computed from role and name. This is a monotone lattice constraint, and no prior paper was found that frames LLM-assigned risk this way. It is a candidate novelty claim.

### Masking by role beats PII detection, and authoring time avoids round-trips

A 2026 cluster of papers puts a trusted local layer between the screen and a cloud agent:

- "Available but Invisible" (arXiv:2602.10139) [S], which cites PrivWeb (not located) ([arXiv](https://arxiv.org/html/2602.10139v1))
- **PrivacyGuard** (arXiv:2610.16778) [V]: existing placeholder defenses "mask detected spans and reuse exact strings". Its fix gives 34–83% less leakage, and cross-form continuity rises from 0.04 to 0.81 ([arXiv](https://arxiv.org/abs/2610.16778))
- CAPED ([arXiv:2606.12666](https://arxiv.org/pdf/2606.12666)) [S]
- PlanTwin, which shows regex/NER detectors miss domain identifiers ([arXiv:2603.18377](https://arxiv.org/pdf/2603.18377)) [S]
- LLM-Redactor, where no technique dominates ([arXiv:2604.12064](https://arxiv.org/html/2604.12064v1)) [S]
- PII Shield ([arXiv:2603.24895](https://arxiv.org/html/2603.24895v1)) [S]

Apple Private Cloud Compute ([Apple](https://security.apple.com/blog/private-cloud-compute/)) [V] protects data *in* the cloud. Its 2026 extension to Google Cloud hardware is [S] ([Help Net Security](https://www.helpnetsecurity.com/2026/06/10/apple-private-cloud-compute-google-cloud-expansion/)). Studio is complementary: it minimizes what leaves the device.

**Two structural advantages to claim:**

1. Studio masks by accessibility role (all row and cell text), not by PII detection, so it avoids the detector-recall failures PlanTwin criticizes.
2. It masks once, at authoring time, so placeholders never round-trip through an LLM at run time. That round-trip is exactly where PrivacyGuard finds leaks.

**Residual risk:** unmasked control names can carry personal data, such as a user's name on an account button, and can carry injection text.

**Persistence makes static verification matter more.** WASP's "security by incompetence" does not apply to synthesized flows: once a deterministic executor runs an injected step, it runs it competently every time. Induced skills in AWM, ASI and SkillWeaver also persist ([AWM](https://arxiv.org/abs/2409.07429)) [V]. **No published study of injection into workflow or program synthesis from page captures was found.** That is both a novelty claim and an evaluation opportunity.

---

## Frameworks prescribe GOV-AIOS's point-of-action controls but assume a fleet it lacks

At the point of action, every framework surveyed asks for what GOV-AIOS does: oversight by a present human, least privilege, approving the raw action, logs, and a stop button. Every framework also assumes an organizational and fleet layer that GOV-AIOS does not have.

### NIST

- AI RMF 1.0 was released 26 Jan 2023 and "is being revised as part of the White House AI Action Plan". AI 600-1 was released 26 Jul 2024 ([NIST](https://www.nist.gov/itl/ai-risk-management-framework); [AI 600-1 PDF](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)) [V].
- There is no agent profile. A critical-infrastructure concept note followed on 7 Apr 2026 [V].
- Subcategory wording is [U] ([AI 100-1](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf)): GOVERN 3.2, MAP 3.5, MEASURE 2.7, MANAGE 2.4 ("supersede, disengage, or deactivate"), MANAGE 4.1, GOVERN 6.
- AI 600-1 GV-3 "Human-AI Configuration and Oversight", MG-2.4-001/-002/-004 and GV-1.7-001 are [V, secondary] ([myctrl GV-3](https://myctrl.tools/frameworks/nist-ai-600-1/family/govern-3); [MG-2.4-004](https://myctrl.tools/frameworks/nist-ai-600-1/mg-2-4-4); [Anaconda](https://www.anaconda.com/blog/nist-ai-600-1-generative-ai-profile-guide)). The 12 risk names are [U].
- The CAISI RFI (Federal Register 8 Jan 2026, docket NIST-2025-0035; [NIST](https://www.nist.gov/news-events/news/2026/01/caisi-issues-request-information-about-securing-ai-agent-systems); [FR](https://www.govinfo.gov/content/pkg/FR-2026-01-08/html/2026-00206.htm)) [V] asks how to "constrain and monitor the extent of agent access". That is nearly word for word GOV-AIOS's M2 and M5.
- The RFI analysis appeared 18 May 2026 [V, snippet] ([NIST](https://www.nist.gov/publications/summary-analysis-responses-request-information-regarding-security-considerations-ai)).
- The Agent Standards Initiative launched 17 Feb 2026 [V, secondary] ([CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-nist-caisi-ai-agent-security-agenda-2026-2/); [Pillsbury](https://www.pillsburylaw.com/en/news-and-insights/nist-ai-agent-standards.html)).
- The COSAIS agent overlays exist as use cases [V] ([CSRC](https://csrc.nist.gov/Projects/cosais/use-cases)) and were still in development in April 2026 [V, secondary] ([CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-nist-ai-agent-standards-20260416-csa-style/)). A CSF AI profile is [U] ([Redmond](https://redmondmag.com/articles/2025/08/26/nist-outlines-cybersecurity-framework-for-ai-system.aspx)).

### EU AI Act

Article sources: [Art. 3](https://artificialintelligenceact.eu/article/3/), [Art. 12](https://artificialintelligenceact.eu/article/12/), [Art. 14](https://artificialintelligenceact.eu/article/14/), [Art. 26](https://artificialintelligenceact.eu/article/26/) [V].

- **Art. 3(4)** defines a deployer.
- **Art. 12** requires automatic logs.
- **Art. 14(4)(b), (d) and (e)** cover automation bias, override, and a "stop" button that brings the system to "a safe state".
- **Art. 26(2)** requires competent overseers. **Art. 26(6)** requires logs to be kept at least six months.
- Art. 19 [U] ([src](https://artificialintelligenceact.eu/article/19/)) and Art. 50 [U] ([src](https://artificialintelligenceact.eu/article/50/)).

**Digital Omnibus timeline** [V, secondary] ([Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)):

- Annex III high-risk obligations now apply from **2 Dec 2027**, and Annex I from 2 Aug 2028.
- Art. 50 still applies from 2 Aug 2026.
- Art. 4 AI literacy is softened.

**Omnibus legislative status.**

- Provisional agreement on 6–7 May 2026 [V] ([Sidley](https://datamatters.sidley.com/2026/06/22/eu-lawmakers-reach-provisional-agreement-to-delay-key-eu-ai-act-obligations/)).
- Parliament adopted it on 16 Jun and the Council on 29 Jun [V, secondary] ([FPF](https://fpf.org/blog/the-ai-act-implementation-timeline-what-changes-under-the-ai-omnibus)).
- Its publication as Regulation (EU) 2026/1744 is [U, secondary only; check ELI on EUR-Lex] ([nicfab](https://www.nicfab.eu/en/posts/digital-omnibus-ai-official-journal/)).
- New prohibitions are [U, single secondary] ([Pillitteri](https://pasqualepillitteri.it/en/news/5190/digital-omnibus-ai-act-eu-parliament)). GPAI duties fall upstream on model providers [U] ([AI Act Explorer](https://artificialintelligenceact.eu/the-act/)).

**Framing.** Coding and browser agents are not Annex III systems. GOV-AIOS is therefore **voluntary alignment** with the Art. 12/14 design pattern, and becomes compliance evidence only if an agent is used for an Annex III purpose after 2 Dec 2027. GOV-AIOS is deterministic code, so it is probably not itself an "AI system".

### ISO/IEC 42001 and 23894

- ISO/IEC 42001 Annex A has **38 controls across 9 objectives** [V, secondary] ([blckalpaca](https://blckalpaca.at/en/knowledge-base/ai-agents/iso-42001-ai-management-system/annex-a-controls-iso-42001); [ISO](https://www.iso.org/standard/81230.html)).
- **A.6.2.8** event logs [V, secondary] ([ISMS.online](https://www.isms.online/iso-42001/annex-a-controls/a-6-ai-system-life-cycle/a-6-2-8-ai-system-recording-of-event-logs/); [agenticrail](https://agenticrail-web.pages.dev/blog/iso-42001-a628-event-log/)). M5 exceeds what it requires.
- Other control and clause titles are [U].
- ISO/IEC 23894 is non-certifiable guidance [V, secondary] ([AI Standards Hub](https://aistandardshub.org/a-new-standard-for-ai-risk-management); [Strac](https://www.strac.io/blog/iso-23894); [ISO](https://www.iso.org/standard/77304.html)). ISO/IEC 42005 is [U].

### OWASP

- **LLM06:2025 Excessive Agency** [V, primary URL; content via secondary summary] ([OWASP](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)). It says "Require a human to approve high-impact actions before they are taken." LLM01 is [U] ([OWASP](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)).
- **Top 10 for Agentic Applications 2026** (published 9 Dec 2025) [V] ([OWASP](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026)). Categories ASI01–ASI10, with mitigations: least agency, confirming the *raw action rather than the agent's summary*, immutable logs that record what was displayed, and a kill switch "that actually works" [V, secondary] ([Cycode](https://cycode.com/blog/owasp-top-10-agentic-applications/); [Kaspersky](https://www.kaspersky.com/blog/top-agentic-ai-risks-2026/55184/)).
- The Feb 2025 T1–T15 guide, including T10 "Overwhelming HITL", is [U] ([OWASP](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)).

### MITRE ATLAS

- AML.T0080, T0081, T0082 and T0086 [V, secondary] ([CSA gap analysis](https://labs.cloudsecurityalliance.org/research/csa-research-note-atlas-agentic-gap-analysis-20260327/)). The proposed T0090–T0095 are candidates, not official.
- T0110, CS0054 and T0051/T0053/T0054 are [U] ([nhimg](https://nhimg.org/articles/ai-agent-attack-techniques-expand-mitre-atlas-beyond-llm-threats/); [ATLAS](https://atlas.mitre.org/techniques/AML.T0051)). Technique counts are unreliable [U] ([Speakeasy](https://www.speakeasy.com/blog/mitre-atlas-explained)).

### Industry

- **Google's** three principles [V] ([Google Research](https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/)). SAIF is [U] ([saif.google](https://saif.google/)).
- **Microsoft CAF** (ms.date 2026-04-09) [V] ([Learn](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization)). It is the most explicit about fleet needs: "You can't govern agents you don't know exist", a distinct agent identity, consistent policy across platforms, SOC routing, and "Decide in advance how to quickly disable an agent".
- **Agent 365 / Entra Agent ID** [V] ([governance](https://learn.microsoft.com/en-us/entra/id-governance/agent-id-governance-overview); [registry](https://learn.microsoft.com/entra/agent-id/agent-registry-convergence)). The planned 1 May 2026 retirement of the registry pages is [U, third-party] ([topedia](https://blog-en.topedia.com/?p=65633)).
- **CSA AICM** v1.0: 243 objectives in 18 domains. v1.1: 247 objectives [V] ([AICM](https://cloudsecurityalliance.org/artifacts/ai-controls-matrix/); [v1.1](https://cloudsecurityalliance.org/blog/2026/07/14/ai-controls-matrix-v1-1-strengthening-the-foundation-for-trustworthy-ai)). Control IDs were not mapped.
- **Anthropic RSP v3.0** (24 Feb 2026) [V] ([Anthropic](https://www.anthropic.com/news/responsible-scaling-policy-v3)) governs model development, not deployer controls. Point releases 3.1–3.4 are [V, search snippet] ([RSP](https://www.anthropic.com/responsible-scaling-policy)).

### Control mapping

Abbreviated from the notes. Tags follow each clause's source.

| Clause | GOV-AIOS mechanism | Gap to declare |
|---|---|---|
| EU AI Act Art. 14(1), (4)(d) [V] | M1 presence approval; denial = override | High-risk only, from 2 Dec 2027; no overseer-competence record |
| Art. 14(4)(e) [V] | M6 e-stop + stop on lock | "Safe state" and rollback for half-done actions undefined |
| Art. 14(4)(b) [V] | M3 risk tiers, M4 digest-bound approval | No measured fatigue or rubber-stamp data |
| Art. 12, 26(5)–(6) [V] | M5 hash chain | On-device only; no retention, export or aggregation |
| Art. 26(2) [V] | M8 single admin | No org-assigned, trained overseers; no multi-user setup |
| NIST MANAGE 2.4 / MG-2.4-004 [U]/[V, secondary] | M6 (lock as a pre-set criterion) | No anomaly-triggered stop; no stakeholder notice |
| CAISI RFI topic 5 [V] | M2 + M5 | None at host scope |
| CAISI hijacking eval [V] | Attack suite | Must report multi-attempt results |
| ISO 42001 A.6.2.8 [V, secondary] | M5 always on | No AIMS documentation |
| OWASP LLM06 [V] | M1, M2, M3 | Agent runs as the OS user; no per-user OAuth scoping |
| OWASP ASI01/ASI09 [V, secondary] | M4 + M5 | Check the log stores the *displayed* artifact, not only the digest |
| OWASP ASI05 [V, secondary] | M4 for approved scripts | Coding agents' arbitrary shell needs separate policy |
| ATLAS AML.T0081 [V, secondary] | M4, M5 | Integrity of agent config files (settings, MCP, AGENTS.md) unclear |
| ATLAS AML.T0086 [V, secondary] | M2 destination allowlist | Covert channels inside allowed hosts |
| Microsoft CAF 2.1.2–2.1.4, 2.3.8, 2.3.10 [V] | M7 on one host; M5; M6 | No registry, agent identity, central policy, SIEM export or remote kill |

The paper's strongest framework claim is that **no framework surveyed requires cryptographic binding between what was approved and what executes**. M4 goes beyond all of them.

---

## Novelty claims, worded so they survive review

| # | Claim (use "to our knowledge") | Closest prior art | Caveat / must check before submission |
|---|---|---|---|
| N1 | First deterministic reference monitor over **GUI/accessibility-tree actions**, using admin-captured, risk-rated page schemas gated on page identity | WebGuard, ShieldAgent, GuardAgent, PolicyGuard (learned); Progent, Conseca, CaMeL, ACE (deterministic but API-level) | Read the 2026 IFC papers (GIF, SPA, APPA, Provably Secure Agent Guardrail, AgentSys) [U]; check RPA selector governance (UiPath); check the full texts of 2512.01295 and the CUA survey |
| N2 | Approval bound to **human presence** (Touch ID, or TOTP that ends on lock) and to a **digest of the exact code**, written by the governor rather than the model | CaMeL confirmations [U]; Operator confirmations; NIST number matching; SPC/WYSIWYS [U] | Claim self-approval and away-from-keyboard defense, **not** a fix for fatigue; currently compare-style and unsigned (see weaknesses) |
| N3 | One governance layer and one audit log across browser/desktop flows **and** two vendors' coding agents | Per-product vendor logs; Microsoft Agent 365 (cloud fleet) | Enterprise AI/MCP gateways not researched; Copilot not researched |
| N4 | Policy placed where the agent cannot write (root-owned managed settings, requirements.toml) | Claude Code protected paths; Cursor fixes after CurXecute and MCPoison | Verify the official requirements.toml path (currently from a third-party source) |
| N5 | Synthesis that treats LLM output as **untrusted** and verifies it against security invariants plus a captured environment snapshot | ASI, SkillWeaver (functional checks); Clover; Conseca, Progent | UIST/CHI programming-by-demonstration and ICSE Selenium/Appium script generation not surveyed |
| N6 | A monotone **risk floor** on LLM-assigned risk labels | None found | Search not exhaustive |
| N7 | Masking **by accessibility role** before the LLM call, once, at authoring time | PrivacyGuard, CAPED, PlanTwin (run-time, detector-based) | PrivWeb not located; leakage through control names |
| N8 | First evaluation on the **macOS AX API**, and first injection study targeting **workflow synthesis** | Android, HTML and AT-SPI tree attacks | Absence of evidence only |

**Numbers that still need checking against the PDFs before they go into the related-work table:**

- FIDES, DRIFT and f-secure ASR/utility (not retrieved)
- Progent's per-version figures
- CaMeL 67% vs 77%: cite v2
- Meta SecAlign per version
- Task Shield, MELON and SecAlign [S]
- The OSWorld, OS-Harm, ECLAIR, Mind2Web and WebArena baselines [S]/[M]
- The WASP venue (one note says NeurIPS 2025 D&B, another a NeurIPS 2025 poster)
- The b3 attack count: the paper says 194,331 attacks across 34 models, press coverage says 19,433 and 31; prefer the paper ([arXiv:2510.22620v2](https://arxiv.org/html/2510.22620v2)) [S]

**IDs and venues still marked [U]/[M]:** InjecAgent, ASB, AgentHarm, StruQ, Spotlighting, EIA, Greshake, Mind2Web, WebArena, SeeAct, AgentSpec, WorkArena++.

**AgentDojo's 97 tasks and 629 cases are [fetched]** in the venues note, which supersedes the [U] tag in the prompt-injection note.

---

## Design weaknesses the research exposed

These come straight from the notes' inferences. Reviewers who know the cited work will find them, so each one needs either a fix or a sentence in the limitations section.

| # | Weakness | Evidence | Fix or disclosure |
|---|---|---|---|
| W1 | **Claude Code hooks fail open.** Non-2 exits and timeouts let the call proceed unless `"onFailure":"block"` is set (v2.1.295+). Codex PreToolUse exit semantics were not read | [Claude Code hooks](https://code.claude.com/docs/en/hooks) | Set `onFailure:"block"` and `allowManagedHooksOnly` in managed settings; check the Codex hook semantics; say so in the paper |
| W2 | **Compare, not enter, code matching.** The 4-letter code is compared visually, and NIST says "a list of secrets to compare is not sufficient" | [NIST 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html); [Microsoft number matching](https://learn.microsoft.com/en-us/entra/identity/authentication/how-to-mfa-number-match) | Make the user type the code; or defend the same-device, OS-rendered-sheet exception and concede that users may skip the comparison |
| W3 | **Unsigned Touch ID approvals.** `LAContext` returns a boolean [U], so same-user code that can call or patch the daemon could spoof it | [Apple LAContext](https://developer.apple.com/documentation/localauthentication/lacontext) [U] | Sign (flow digest ‖ page-file digest ‖ nonce) with a Secure Enclave key under `.biometryCurrentSet`, the analogue of WebAuthn's signed challenge; state which variant is implemented |
| W4 | **Same-UID hash chain.** Full rewrite, truncation and deletion go undetected; no forward security, no protection against forks, unauthenticated timestamps, and a compromised daemon can omit events | Schneier–Kelsey; Crosby–Wallach; Ma–Tsudik (see logging section) | Add an HMAC or signature with a Secure Enclave key; anchor the head hash externally (git remote, Sigsum, Rekor); forward-secure keys as future work |
| W5 | **Enterprise fleet gaps.** No registry, agent identity, central policy push, retention or export, SIEM, remote kill, multi-user roles or overseer competence records | [Microsoft CAF](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization); EU Art. 26(2), 26(6); ISO 42001 cl. 9 | Frame GOV-AIOS as an endpoint enforcement point that a control plane consumes; single admin per laptop is a deliberate scope choice |
| W6 | **TOTP is not phishing-resistant** under 800-63B-4 | [NIST](https://pages.nist.gov/800-63-4/sp800-63b.html) | Rank TOTP sessions below Touch ID |
| W7 | **Data flows through allowed fields.** Element allowlisting does not stop exfiltration typed into a legitimate field, which is Rehberger's "typing rarely triggers confirmation" channel. GOV-AIOS gates actions, not reads | [Embrace The Red](https://embracethered.com/blog/posts/2025/chatgpt-operator-prompt-injection-exploits) | Per-field risk and value constraints; destination allowlists; declare covert channels inside allowed hosts |
| W8 | **Accessibility-tree spoofing.** Injected elements with matching roles or labels | [arXiv:2507.14799](https://arxiv.org/abs/2507.14799); [arXiv:2507.04227](https://arxiv.org/html/2507.04227v2) | Identify pages by structure (fingerprint, hierarchy, identifiers), not labels; evaluate it |
| W9 | **Schema coverage and maintenance.** Schemas break when the UI changes | Inference (computer-use note) | Measure the schema breakage rate; Studio re-capture as mitigation |
| W10 | **In-schema misuse.** The injected agent picks a legitimate but harmful element and the user approves | Patterns paper "tired verifier" [V] | Keep approvals for high-risk elements; run the user study |
| W11 | **Approval fatigue is unmeasured.** A constant-looking biometric sheet habituates | Anderson et al.; Vance et al. | Vary the prompt per request; make sure backoff is **not reset** by fresh requests (NIST §3.2.2) |
| W12 | **Unmasked control names** leak personal data and remain an injection channel into Studio | PlanTwin critique [S] | Evaluate with WASP/EIA payloads in labels |
| W13 | **Agent config integrity unclear** (settings, MCP config, AGENTS.md; ATLAS T0081). Does the log store the *displayed* artifact or only the digest? | OWASP ASI09; CSA ATLAS note | Check the codebase; state the answer |
| W14 | **Coding-agent shell coverage.** Digest approval covers approved scripts, not arbitrary shell (ASI05); Claude Code's sandbox exempts hooks, file tools and MCP servers | [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing) | Define the shell-policy scope explicitly |
| W15 | **Deprecated `sandbox_init`/`sandbox-exec`** | [apple/containerization #737](https://github.com/apple/containerization/issues/737) | Note it as a portability risk shared with Codex and Claude Code |
| W16 | **Undefined e-stop "safe state"** and no rollback | EU Art. 14(4)(e) | Define the halt semantics |
| W17 | **No multi-agent mediation** (ASI07/ASI08); no anomaly detection (ASI10) | OWASP Agentic Top 10 | Declare out of scope |
| W18 | **Name clash with Rutgers AIOS** | [arXiv:2403.16971](https://arxiv.org/abs/2403.16971v1) | Distinguish the two in the introduction; consider retitling |

---

## Evaluation plan: report the proposed-versus-executed gap

### Metrics and conditions

**Core metrics.** Use the AgentDojo triad as the backbone: benign utility, utility under attack, and targeted ASR. CaMeL, Progent and FIDES all report these against an undefended baseline [fetched] ([AgentDojo](https://arxiv.org/abs/2406.13352); [CaMeL](https://arxiv.org/abs/2503.18813); [Progent](https://arxiv.org/abs/2504.11703); [FIDES](https://arxiv.org/abs/2505.23643)). The triad itself is [memory, unverified; the abstract does not state it]. AgentDojo is MIT-licensed and actively maintained [V].

**Split ASR in two, following WASP** ([arXiv](https://arxiv.org/abs/2504.18575)):

- **Intermediate ASR**: the malicious action was *proposed*.
- **End-to-end ASR**: the action was *executed* despite governance.

GOV-AIOS's thesis lives in the gap between these two numbers, and the hash-chained audit log gives ground truth for what was proposed, approved and executed.

**Additional metrics:**

- **Over-blocking rate**: benign actions denied or escalated.
- **Approval burden**: prompts per task and per hour.
- **Latency overhead**: p50/p95 per governed action, in IsolateGPT's style (under 30% for 75% of queries).
- **Token overhead** for Studio.
- **Multi-attempt ASR**: CAISI found 57% rising to 80% with 25 tries, so report results under repeated attempts.

**Utility cost.** Report a figure comparable to CaMeL's 7-point drop.

**Three conditions:**

1. Agent alone.
2. Agent plus GOV-AIOS policy.
3. Agent plus policy plus presence approval. Use a simulated approver that always approves for the upper bound and a rule-following approver for the lower bound.

### Benchmarks to reuse

| Benchmark | Fit | License / code |
|---|---|---|
| AgentDojo (97 tasks, 629 security cases [fetched]) | Port the task/attack DSL and evaluators; map tools onto schema actions | MIT, ethz-spylab/agentdojo [V]; NIST variant usnistgov/agentdojo-inspect [V] |
| WASP | Highest fit for browser UI | NOASSERTION, likely CC-BY-NC: check before redistributing [V] |
| ASB (arXiv:2410.02644) | Additional tool-agent attacks; ~27.55% average indirect-PI ASR | MIT, agiresearch/ASB [V]; ID [S], venue [U] |
| InjecAgent (arXiv:2403.02691) | Low fit (single-turn, simulated) | MIT, inactive [V]; ID [U] |
| AgentHarm (arXiv:2410.09024) | Malicious-user threat model only | inspect_evals MIT [V]; dataset terms [U] |
| OS-Harm, VPI-Bench, Pop-ups, EIA, RedTeamCUA | Payload sources for desktop and visual injection | See the computer-use section |
| b3 (arXiv:2510.22620) | Low fit (tests the backbone model, not the system) | Repo not found [Gap] |

**No benchmark targets a macOS accessibility-tree desktop agent, and no published method evaluates a governance layer around a GUI agent.** The paper has to define this methodology, which is itself a contribution.

### Suites to build

Build four suites:

1. **UI injection.** Port AgentDojo and ASB tasks into mocked macOS and Chrome apps, with payloads in AX/DOM text, files and emails.
2. **Coding agents.** Injected instructions in a README, issue text or a post-install script, targeting destructive shell or git actions.
3. **Studio synthesis.** Measure the rate of out-of-schema or under-rated actions with and without the validator, with payloads seeded into control names.
4. **Human approval.** A within-subjects longitudinal design in the style of Vance et al., with a known fraction of malicious requests. Measure approval-error rate, time to decision and drift, and compare static prompts with polymorphic or risk-differentiated ones. Anderson's fMRI study used n=25 and his behavioral study n=80 ([JMIS](https://jmis-web.org/articles/1304); [summary](https://academicnewsletter.sufe.edu.cn/info/408012)), which suggests roughly 50–100 participants. **That figure is the researcher's inference, not a verified SOUPS norm.**

### Threat model

Use the Greshake framing ([arXiv 2302.12173](https://arxiv.org/abs/2302.12173)) [memory, unverified], with Dolev–Yao as the classic template ([IEEE](https://ieeexplore.ieee.org/document/1056650)) [memory, unverified URL]:

> "The attacker controls the content of any web page, document, email or repository file the agent reads, and may choose it adaptively; the attacker does not control the user, the GOV-AIOS daemon, the macOS kernel, or the signed approval app, and cannot forge the user's presence signal."

List the non-goals: a compromised OS, a malicious user, side channels.

**Watch the W3 interaction.** "Cannot forge presence" holds only if Touch ID approvals are signed.

### Artifact

- Aim for the USENIX "Available" and "Functional" badges. USENIX '26 made availability mandatory, and Functional and Reproducible are optional ([Call for Artifacts](https://www.usenix.org/node/315295); [secartifacts](https://secartifacts.github.io/usenixsec2026/instructions)).
- Ship replay scripts that also verify the audit chain.
- Provide recorded traces, because the real-Chrome AX dependency makes "Reproducible" hard.
- ACM badges are [memory, unverified; page 403] ([ACM](https://www.acm.org/publications/policies/artifact-review-and-badging-current)).

---

## Publishing: arXiv now needs an endorser, and USENIX '27 cycle 2 is the fit

### arXiv norms

**Endorsement.** Since **21 Jan 2026**, automatic endorsement requires *both* an institutional email *and* a prior accepted arXiv paper in the same endorsement domain. Everyone else needs a personal endorser, and arXiv staff cannot endorse ([arXiv blog](https://blog.arxiv.org/2026/01/21/attention-authors-updated-endorsement-policy/)) [fetched].

- Endorsers must have qualifying papers from 3–5 years back. Do not mass-email potential endorsers. Each abstract page lists who can endorse ([endorsement help](https://info.arxiv.org/help/endorsement.html)) [fetched].
- Practical route: start the submission early and forward the 6-character code to a co-author or advisor with recent cs.CR papers.

**Moderation.** Moderators can decline or reclassify papers. They expect archival interest. They throttle prolific submitters (2 new submissions per month, 3 active), give no feedback, and allow one final appeal ([moderation](https://info.arxiv.org/help/moderation/index.html)) [fetched]. No cs.CR-specific criteria were found.

**Review and position papers.** Since **31 Oct 2025**, CS review and position papers need completed peer review first ([arXiv blog](https://blog.arxiv.org/?p=1740); [Decrypt](https://decrypt.co/347196?amp=1); [heise](https://heise.de/-11050464)). So **frame GOV-AIOS as a systems paper with an implementation and an evaluation.** Use primary category cs.CR, cross-listed to cs.AI and cs.HC.

### AI-authorship rules

- **arXiv**: "Generative AI language tools should not be listed as an author." Significant use must be reported, and authors are responsible for any AI-introduced errors and references ([moderation](https://info.arxiv.org/help/moderation/index.html) [fetched]; [Jan 2023 blog](https://blog.arxiv.org/2023/01/31/arxiv-announces-new-policy-on-chatgpt-and-similar-tools)).
- **ACM**: disclose in the acknowledgments [aggregator; ACM page 403] ([Monperrus](https://www.monperrus.net/martin/ai-policy-summary); [ACM](https://www.acm.org/publications/policies/new-acm-policy-on-authorship); [SIGCHI](https://sigchi.org/news/blog/acm-publications-policy-guidance-for-sigchi-venues/)).
- **IEEE**: disclose in the acknowledgments, naming the system and the sections it affected [fetched] ([IEEE Open](https://open.ieee.org/author-guidelines-for-artificial-intelligence-ai-generated-text/)).
- **Springer Nature**: "Human accountability cannot be transferred to AI systems" [fetched] ([Springer](https://www.springernature.com/gp/policies/editorial-policies)). Nature Portfolio wants disclosure in Methods [aggregator] ([Nature](https://www.nature.com/nature-portfolio/editorial-policies/ai)).
- **USENIX Security '27**: does not require disclosure, but treats hallucinated references as misconduct and encourages authors to run the PC's hallucination-detection tool [fetched] ([CFP](https://www.usenix.org/conference/usenixsecurity27/call-for-papers)).

**One acknowledgments paragraph** can satisfy all of these. It should name the tools, the sections and code they touched, and state that humans verified everything. Because GOV-AIOS *governs* coding agents, it should also disclose agent-written artifact code as a provenance matter.

### Candidate venues as of 6 Nov 2026

| Venue | Deadline (AoE) | Notes | Source tag |
|---|---|---|---|
| IEEE S&P 2027 cycle 2 | **17 Nov 2026** (abstract ~1 week earlier) | 11 days away; not viable without a finished evaluation. Page limits for 2027 [memory, unverified] | [sec-deadlines](https://sec-deadlines.github.io/); [S&P](https://cycle1.sp2027.ieee-security.org/deadlines); [Alfred Scholar](https://www.alfredscholar.com/conferences/ieee-sp-2027/) |
| IEEE Euro S&P 2027 | 2 Dec 2026 | Abstract 1 week earlier | [sec-deadlines](https://sec-deadlines.github.io/) |
| PETS 2027 | 30 Nov 2026; 28 Feb 2027 | Rolling; fits the privacy-masking angle | [sec-deadlines](https://sec-deadlines.github.io/) |
| ACM AsiaCCS 2027 round 2 | 11 Dec 2026 | | [CFP](https://asiaccs2027.cityu.edu.mo/call-for-papers/) |
| **USENIX Security '27 cycle 2** | **Register 19 Jan, paper 26 Jan, artifacts 29 Jan 2027**; notification 6 May | 13 pages; **mandatory Open Science appendix**; anonymous artifacts (anonymous.4open.science, "SEC27"); preprints allowed; cycle-1 rejects cannot resubmit; Denver, 11–13 Aug 2027 | [fetched] [CFP](https://www.usenix.org/conference/usenixsecurity27/call-for-papers); [conf](https://www.usenix.org/conference/usenixsecurity27) |
| ACM CCS 2027 | ESTIMATE ~mid-Jan and ~late Apr 2027 | Atlanta, 11–15 Oct 2027 [aggregator] | [sec-deadlines](https://sec-deadlines.github.io/); [BERI](https://www.beri.net/events/acm-ccs-2027) |
| NDSS 2028 | ESTIMATE ~6 May 2027 | arXiv "discouraged but not prohibited"; 13 pages; NDSS 2027 location conflicts (Seoul vs San Diego) | [NDSS 2027 CFP](https://www.ndss-symposium.org/ndss2027/submissions/call-for-papers/); [home](https://www.ndss-symposium.org/ndss2027/); [trybibby](https://trybibby.com/conference-deadlines/ndss-2027) |
| ACSAC 2027 | ESTIMATE ~late May 2027 | | [sec-deadlines](https://sec-deadlines.github.io/) |
| AISec 2027 (at CCS) | ESTIMATE ~late Jul 2027 | Long or short papers [memory, unverified] | [sec-deadlines](https://sec-deadlines.github.io/) |
| IEEE SaTML 2028 | ESTIMATE ~late Sep 2027 | Archival conference; the 2027 deadline (29 Sep 2026) has passed | [mldeadlines](https://mldeadlines.com/conference/satml/); [BERI](https://www.beri.net/events/satml-2027) |
| NDSS posters / co-located workshops | No 2027 poster call yet | 2026 format: abstract of at most 2 pages plus a draft poster; non-archival | [NDSS 2026 posters](https://www.ndss-symposium.org/ndss2026/submissions/call-for-posters/); [workshops](https://www.ndss-symposium.org/ndss2027/submissions/call-for-co-located-workshops/); [2027 submissions](https://www.ndss-symposium.org/ndss2027/submissions/) |

**Unverified venues:** DLSP, LAMPS, the CHI LBW and UIST demo dates, EuroSys, and whether ATC still exists are all [memory, unverified].

**Recommended sequence:**

1. Finish the attack suite.
2. Post to arXiv cs.CR.
3. Submit to USENIX Security '27 cycle 2.
4. If rejected, fall back to CCS 2027 cycle 2 or NDSS 2028, with SaTML 2028 as the ML-security alternative.
5. In parallel, run a non-archival poster or demo of the approval panel.

**Anonymity.** The product name and GitHub repo de-anonymize the paper. Use a code name and an anonymous artifact mirror, and for NDSS keep the preprint's timing and title apart from the submission.

---

## Conclusion

The research changes what the paper should claim. "Prompt-injection defense" is the wrong headline: GOV-AIOS detects no injections, and model-level defenses lose to adaptive attackers whatever the paper says. The defensible headline is that GOV-AIOS **creates a capability boundary where GUIs have none**, and **moves the human decision to a deterministic artifact the model did not write**. That reframing absorbs the strongest critiques in the literature: the "tired verifier", Lies-in-the-Loop, and CAISI's retry curve. It also explains why Studio's static verification matters more than run-time checks do, since a poisoned synthesized flow runs competently every time.

The same research shows that the current implementation falls short of its own threat model in exactly the places a security PC will probe. A presence signal that is an unsigned boolean, a code that is compared rather than typed, hooks that fail open, and a log the agent's own UID can rewrite each turn "cannot forge presence" or "tamper-evident" into an overclaim. Fixing W1–W4 is cheaper than defending them in rebuttal: they need a Secure Enclave signature, a typed code, `onFailure:"block"`, and an external head anchor. Fixing them also turns the proposed-versus-executed ASR gap from an architectural argument into a measured result. Against the 26 Jan 2027 deadline, the critical path is the evaluation suite plus those four fixes. The related-work section is already largely written by this synthesis.
