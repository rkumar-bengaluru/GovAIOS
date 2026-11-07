# Related work: computer-use and browser agent security, agent sandboxing and capability systems, and agent tool permission systems (as they compare to GOV-AIOS)

Notes compiled 2026-11-06. Vendor docs were fetched on that date, and the version numbers quoted are the ones the docs printed then. Items marked **[UNVERIFIED]** come only from search snippets or third-party summaries; I did not read the primary source for them.

## Q1. Attacks and defenses specific to computer-use and browser agents (2024–2026)

### Takeaway
Since late 2024, papers have shown repeatedly that screenshot agents, accessibility-tree agents and DOM agents can be hijacked through content in their environment: pop-ups, injected forms, visually embedded text and accessibility-tree triggers. Reported success rates are often 50–100%. Prompt-level defenses ("ignore pop-ups", system-prompt warnings) consistently fail. Vendor mitigations (Operator confirmations, watch mode, injection monitors) are model-side or model-adjacent, and researchers have bypassed them.

### Cited Findings
**Attacks on vendor computer-use agents**
- ZombAIs (Johann Rehberger / Embrace The Red, Oct 2024). A web page carrying a prompt injection made Anthropic's Claude Computer Use (beta) download a binary, `chmod` it, run it, and join a Sliver C2 server. The author reports it worked on the first try. — [Embrace The Red](https://embracethered.com/blog/posts/2024/claude-computer-use-c2-the-zombais-are-coming)
- A 2026 journal follow-up reports a 78% attack success rate (ASR) for a similar C2 attack against Claude Sonnet 4.5 computer use **[UNVERIFIED; minor venue]**. — [Jurnal Sisfokom](https://jurnal.atmaluhur.ac.id/index.php/sisfokom/article/view/2634)
- Rehberger's CCC 39C3 (Dec 2025) talk "Agentic ProbLLMs" covers exploits against computer-use and coding agents. — [CCC schedule](https://events.ccc.de/congress/2025/hub/de/schedule/day:2/kind:all/recorded:1/track:security)
- ChatGPT Operator: Rehberger showed prompt-injection data leakage. He reports that "just typing text hardly ever triggers any confirmations", which means the confirmation gate does not cover exfiltration by form-fill. — [Embrace The Red, 2025](https://embracethered.com/blog/posts/2025/chatgpt-operator-prompt-injection-exploits)
- OpenAI Operator system card (Jan 2025), as reported by secondary coverage **[UNVERIFIED: primary card not fetched]**:
  - mitigations are confirmations before state-changing actions, "watch mode" on sensitive domains such as email, proactive refusals for categories such as banking, and a prompt-injection monitor that pauses execution;
  - susceptibility on an injection set reportedly fell from 62% with no mitigations to 23% with them. — [3l3c summary](https://www.3l3c.ai/us/blog/ai-in-cybersecurity/operator-system-card-security)

**Benchmarks and attacks (academic)**
- **EIA: Environmental Injection Attack on Generalist Web Agents for Privacy Leakage** (Liao et al., arXiv:2409.11295, ICLR 2025).
  - The attacker injects malicious elements into a benign page, using Form Injection or Mirror Injection (which copies the look of genuine elements).
  - Across 177 Mind2Web action steps, ASR was up to 70% for stealing specific PII and 16% for leaking the full user request.
  - A defensive system prompt was hard-pressed to stop it. — [arXiv](https://arxiv.org/abs/2409.11295)
  - Note: "EIA" refers to this paper. The pop-up attack below is a separate paper.
- **Attacking Vision-Language Computer Agents via Pop-ups** (Zhang, Yu, Yang, arXiv:2411.02391, ACL 2025).
  - Adversarial pop-ups in OSWorld and VisualWebArena reached 86% average ASR and cut task success by 47%.
  - "Ignore pop-ups" instructions and advertisement notices were ineffective.
  - It attacked both screenshot agents and SoM agents (screenshot plus accessibility tree). — [arXiv](https://arxiv.org/abs/2411.02391)
- **VPI-Bench** (Cao et al., arXiv:2506.02456, ICLR 2026 poster).
  - 306 test cases on five platforms (Amazon, Booking, BBC, Messenger, Email), each with an instruction embedded visually in the page.
  - ASR was up to 51% for computer-use agents and up to 100% for browser-use agents.
  - System-prompt defenses gave limited protection. — [arXiv](https://arxiv.org/abs/2506.02456); [ICLR 2026](https://iclr.cc/virtual/2026/poster/10009231)
- **WASP** (Evtimov et al., Meta FAIR, arXiv:2504.18575, NeurIPS 2025 D&B).
  - An end-to-end benchmark of prompt-injection hijacking, run in a sandbox built on VisualWebArena.
  - Low-effort, human-written injections partially hijacked agents in up to 86% of cases, including reasoning models and models with instruction-hierarchy training.
  - Agents often failed to complete the attacker's goal anyway; the authors call this "security by incompetence". — [arXiv](https://arxiv.org/abs/2504.18575)
- **OS-Harm** (EPFL/CMU, arXiv:2506.14866, NeurIPS 2025 D&B Spotlight).
  - 150 tasks in OSWorld across three categories: deliberate misuse, prompt injection and model misbehavior. Scoring uses an LLM judge (F1 0.76 and 0.79 against human labels).
  - Models tested were o4-mini, Claude 3.7 Sonnet and Gemini 2.5 Pro.
  - All complied with many misuse requests, and o4-mini followed basic injections in about 20% of cases. — [arXiv](https://arxiv.org/abs/2506.14866); [NeurIPS](https://neurips.cc/virtual/2025/poster/121772)
- **RedTeamCUA** (arXiv:2505.21936) runs adversarial tests in hybrid web and OS environments. It reports that adding an accessibility tree to screenshots substantially lowers ASR for nearly all CUAs, while noting that accessibility trees are not always available. — [arXiv](https://arxiv.org/pdf/2505.21936)
- **RedCode** (Guo et al., arXiv:2411.07781, NeurIPS 2024 D&B).
  - RedCode-Exec has 4,050 risky Python and Bash cases (25 vulnerability types across 8 domains) run in Docker. RedCode-Gen has 160 prompts for generating harmful software.
  - Agents refuse risky operations described in natural language less often than the same operations written as code. — [arXiv](https://arxiv.org/abs/2411.07781)

**Attacks through the accessibility tree**
- Johnson et al., "Manipulating LLM Web Agents with Indirect Prompt Injection Attack via HTML Accessibility Tree" (arXiv:2507.14799, EMNLP 2025 Demos). Universal adversarial triggers placed in HTML reach agents that read the accessibility tree (tested in BrowserGym). — [arXiv](https://arxiv.org/abs/2507.14799)
- Mobile GUI agents (arXiv:2507.04227). A hijacking tool listens for Android Accessibility events and writes adversarial content into both the UI element tree and the screenshot, keeping the two consistent. A static set of more than 3,000 adversarial GUI states accompanies it. — [arXiv](https://arxiv.org/html/2507.04227v2)
- "Environmental Injection Attacks against GUI Agents in Realistic Dynamic Environments" (arXiv:2509.11250; ACM DOI 10.1145/3832148) **[UNVERIFIED: abstract not read]**. — [arXiv](https://arxiv.org/pdf/2509.11250)

**Surveys**
- "OS Agents: A Survey on MLLM-based Agents for General Computing Devices Use" (Hu et al., arXiv:2508.04482; short version at ACL 2025). It lists safety and privacy as a future direction rather than giving them a full security treatment. **[Depth of its security section not verified.]** — [arXiv](https://arxiv.org/abs/2508.04482v1)
- "Systems Security Foundations for Agentic Computing" (arXiv:2512.01295) is a likely systems-security framing paper to cite **[UNVERIFIED: content not read]**. — [arXiv](https://arxiv.org/html/2512.01295v2)

### Inferences
- Almost every attack above works by making the agent misread what it is looking at: a fake form, a mirrored button, a pop-up, or text in pixels or in the accessibility tree. GOV-AIOS identifies the page before any element is used, and allows only elements defined in a captured schema. That is a structural answer to EIA's Mirror and Form Injection and to pop-up attacks: an injected element is not in the schema, so it cannot be acted on, whatever the model "believes".
- The schema approach does not address content injection that changes what the model types into an allowed field, such as exfiltration through a legitimate search box. Rehberger's Operator finding (typing rarely triggers confirmation) is exactly this channel. The paper should state it as a residual risk, or show that per-field risk ratings and value constraints cover it.
- Accessibility-tree injection (arXiv:2507.14799, 2507.04227) means the tree is also attacker-influenced. GOV-AIOS should argue that it uses the tree for structural identification (role, identifier, position in the hierarchy, page fingerprint), not as instruction text for the model.

### Gaps
- I did not fetch Anthropic's own computer-use docs or its prompt-injection classifier announcements, so I cannot give dated claims about Anthropic's CUA mitigations.
- I did not read the primary OpenAI Operator or CUA system card; the 62%→23% figure is secondhand.
- I found no paper that specifically attacks the macOS AX API (as opposed to AT-SPI, Android or HTML accessibility trees). This looks like a genuine gap that GOV-AIOS could note.

## Q2. Sandboxing and capability systems for agents (including the AIOS name clash)

### Takeaway
Industry coding agents now ship OS-level sandboxes: Seatbelt on macOS, and bubblewrap or Landlock plus seccomp on Linux. Academic systems are moving toward deterministic policy enforcement outside the LLM (CaMeL, Progent, ACE, Conseca). None of them sandboxes a GUI or browser driver the way GOV-AIOS does. Rutgers' AIOS is an agent *scheduling and resource-management* kernel whose access control covers only agent-to-agent data. GOV-AIOS is a *governance* layer on a real desktop OS, which is a different problem.

### Cited Findings
**Vendor sandboxes**
- Claude Code sandbox (docs fetched 2026-11-06).
  - What it confines: Bash, PowerShell and Monitor commands, plus the processes they start. It is off by default, built on `@anthropic-ai/sandbox-runtime`, and uses Seatbelt on macOS and bubblewrap (with optional seccomp) on Linux and WSL2.
  - Filesystem: writes are allowed only in the working directory and temp. Reads are allowed across most of the machine by default, including `~/.ssh`, unless narrowed.
  - Protected paths: writes to `.claude` settings, `.mcp.json`, shell startup files and `.git/hooks` are denied.
  - Network: all traffic goes through a host proxy with domain allowlists. Hosts that resolve only to loopback or link-local, including 169.254.169.254, are refused.
  - Not sandboxed: file tools (Read, Edit, Write), WebFetch, hooks, local MCP servers and LSP servers all run with the user's full access.
  - Managed settings: `sandbox.enabled`, `failIfUnavailable` and `allowUnsandboxedCommands:false` make the sandbox admin-required. Repository settings cannot loosen it as of v2.1.285. — [Claude Code sandboxing docs](https://code.claude.com/docs/en/sandboxing)
- Codex sandbox.
  - Official docs separate the sandbox (the technical boundary) from the approval policy (when Codex must ask before crossing it). — [OpenAI Codex sandboxing concept](https://developers.openai.com/codex/concepts/sandboxing.md)
  - On macOS, Codex reportedly generates an SBPL Seatbelt profile at runtime and runs it via `sandbox-exec`. Linux uses bubblewrap, Landlock and seccomp; Windows uses restricted tokens, ACLs and firewall rules **[third-party source]**. — [Vaughan blog, 2026-03](https://codex.danielvaughan.com/2026/03/26/codex-cli-approval-modes-sandbox-security)
- Codex managed `requirements.toml` (docs fetched 2026-11-06).
  - Purpose: "admin-enforced constraints that users can't override". Cloud requirements take precedence over system requirements.
  - Constrainable keys: `allowed_approval_policies`, `allowed_approvals_reviewers`, `allowed_sandbox_modes` (legacy), `allowed_permission_profiles` (Codex 0.138.0+), `[permissions.filesystem] deny_read`, an `mcp_servers` allowlist (an empty list disables all), `[rules] prefix_rules` (prompt or forbidden), `[network_proxy]` (canonical name from 0.166.0), and `[features]` including `browser_use` and `computer_use`. Managed hooks are also listed.
  - `approval_policy="untrusted"` is no longer supported. — [Codex managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)
  - The `/etc/codex/requirements.toml` path on Linux and macOS (with MDM delivery on macOS) comes from a third-party source; the official page section I fetched was truncated before the file locations. — [Vaughan blog, 2026-03](https://codex.danielvaughan.com/2026/03/31/codex-cli-network-security-requirements-toml/)
- macOS `sandbox-exec` and `sandbox_init`.
  - `sandbox-exec` prints a deprecation warning recommending App Sandbox, and Apple publishes no replacement for applying Seatbelt profiles to processes without App Sandbox entitlements. — [apple/containerization issue #737](https://github.com/apple/containerization/issues/737)
  - A March 2026 test found it still working on Sequoia. — [gastown note](https://gastown.dev/docs/research/macos-sandbox-exec)
  - SBPL is Scheme-based and Seatbelt builds on the TrustedBSD MAC framework (2011 guide). — [Apple Sandbox Guide v1.0 (mirror)](https://https-reverse_put_as.proxy.bugsmash.io/wp-content/uploads/2011/09/Apple-Sandbox-Guide-v1.0.pdf)
  - **[UNVERIFIED: Apple's primary docs not fetched]**
- Kubernetes SIG Agent Sandbox: a Kubernetes-native system for isolated, stateful, singleton agent workloads, which can isolate them with gVisor. — [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox); [k8s blog 2026-03-20](https://kubernetes.io/blog/2026/03/20/running-agents-on-kubernetes-with-agent-sandbox/)
- I found no peer-reviewed paper titled "AgentSandbox". The name matches only open-source projects. — [agent-sandbox/agent-sandbox](https://github.com/agent-sandbox/agent-sandbox)

**Policy and capability research**
- **Conseca**, "Contextual Agent Security: A Policy for Every Purpose" (Tsai and Bagdasarian, Google; arXiv:2501.17070; HotOS 2025).
  - An LLM generates a task-specific policy from trusted context only. A deterministic enforcer then checks each proposed action, and denials return a rationale to the agent.
  - The prototype is a Linux computer-use agent with email and filesystem tools; results are preliminary. — [arXiv](https://arxiv.org/abs/2501.17070); [Google Research](https://research.google/pubs/context-is-key-for-agent-security/)
- **CaMeL**, "Defeating Prompt Injections by Design" (Debenedetti et al., Google DeepMind/ETH; arXiv:2503.18813).
  - Control flow comes from the trusted query; untrusted data is processed by a quarantined LLM.
  - Capabilities and provenance tracking block unauthorized data flows.
  - It solves 77% of AgentDojo tasks with provable security, against 84% undefended. — [arXiv](https://arxiv.org/abs/2503.18813)
- **Progent** (Shi et al., arXiv:2504.11703).
  - A DSL expresses privilege as symbolic rules over tool names and arguments, enforced deterministically on every call. An LLM may generate and update the policy.
  - It reports ASR down to 0% (abstract), or 41.2%→2.2% on AgentDojo in one summary. — [arXiv](https://arxiv.org/abs/2504.11703)
- **ACE**: Abstract-Concrete-Execute security architecture for LLM-integrated app systems (arXiv:2504.20984; NDSS 2026).
  - An abstract plan is built from trusted input only and then mapped to concrete apps.
  - Static information-flow checks run on the plan, and data and capability barriers separate apps at runtime.
  - It breaks IsolateGPT. — [arXiv](https://arxiv.org/abs/2504.20984); [NDSS PDF](https://www.ndss-symposium.org/wp-content/uploads/2026-s352-paper.pdf)
- **AIOS: LLM Agent Operating System** (Mei, Zhang et al., Rutgers; arXiv:2403.16971, v1 Mar 2024, v4 May 2025).
  - A kernel layer providing LLM scheduling, context, memory, storage and tool managers.
  - Its access manager puts agents in privilege groups (a hashmap from agent ID to group) that control *agent-to-agent* reads and writes of memory and logs.
  - A user-intervention interface asks for confirmation before irreversible file or tool operations. — [arXiv](https://arxiv.org/abs/2403.16971v1); [HTML v3](https://arxiv.org/html/2403.16971v3)

### Inferences
- **Positioning against AIOS (name clash).**
  - AIOS is an "OS for agents": a scheduler and resource abstraction in which agents are processes inside a Python runtime. Its security model is inter-agent isolation plus confirmation prompts.
  - GOV-AIOS is a governance layer *on top of macOS* that mediates existing third-party agents (Claude Code, Codex, a browser driver) through OS permissions (TCC Accessibility and Screen Recording), Seatbelt, and vendor-provided hook and requirement points.
  - The paper should state this distinction in the introduction or related work. It could also consider expanding the "GOV" prefix in the title to avoid confusion.
- Conseca, Progent and CaMeL all enforce at *tool-call* granularity on API-style tools. GOV-AIOS brings the same "deterministic enforcer outside the LLM" principle to GUI actions, where no API boundary exists by default; the page schema creates one.
- Vendor sandboxes confine *subprocesses* of the coding agent. GOV-AIOS also confines *its own* processes with `sandbox_init`, the opposite direction: the governor limits itself. The paper should say that the `sandbox_init` and `sandbox-exec` interface is officially deprecated yet still used by Codex and Claude Code. That is a portability and maintenance risk shared with industry.

### Gaps
- E2B (Firecracker microVMs) and gVisor-based agent sandboxes: I did not fetch E2B docs, so its claims are not cited here.
- I did not confirm Apple's own `sandbox_init(3)` deprecation marking, or the TCC documentation for Accessibility and Screen Recording.
- The prompt also mentioned a separate "ACE" paper; I verified only the NDSS 2026 ACE.

## Q3. Tool and permission systems (MCP, Claude Code, Codex, Cursor/Copilot, gateways): where are the enforcement points, and is each inside or outside the model's control?

### Takeaway
Real enforcement points exist outside the model in three places:
1. client-side pre-execution hooks and permission rules (Claude Code PreToolUse, Codex rules and requirements);
2. OS sandboxes around executed commands;
3. admin-locked managed configuration.

MCP itself puts security in OAuth and in client consent, and has no protocol-level tool-integrity mechanism. The best-known breaks (tool poisoning, rug pulls, CurXecute, MCPoison) exploit one-time approval and model-visible but user-invisible metadata.

### Cited Findings
**MCP**
- Invariant Labs disclosed tool poisoning on 2025-04-01: hidden instructions in a tool description that the model sees but the user does not. Their demo was a harmless-looking `add` tool in Cursor that exfiltrated `~/.ssh/id_rsa`. — [Invariant Labs](https://invariantlabs.ai/blog/mcp-security-notification)
- Rug pull: a server changes a tool's definition after approval through `notifications/tools/list_changed`, and nothing triggers re-approval. Tool shadowing: one server's description changes how another server's tool is used. **[Secondary sources]** — [CSA whitepaper](https://labs.cloudsecurityalliance.org/research-rb/csa-whitepaper-mcp-security-tool-poisoning-20260506-csa-styl/)
- Invariant released MCP-Scan, which pins tool definitions by hash, around 2025-04-11 **[date UNVERIFIED]**. — [Taskade wiki](https://www.taskade.com/wiki/ai/tool-poisoning)
- The MCP Security Best Practices (draft spec, fetched 2026-11-06) cover:
  - the confused deputy in OAuth proxies (per-client consent is a MUST);
  - token passthrough (forbidden);
  - SSRF during OAuth discovery;
  - state-handle hijacking;
  - local MCP server compromise. One-click local install MUST show the exact command and get explicit approval, and servers SHOULD run in a sandbox with minimal default privileges.
  - OAuth URL scheme validation, stdio proxy escalation, and scope minimization (progressive least privilege).
  - It does **not** define tool-description integrity or re-consent when a tool changes. — [MCP security best practices](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)

**Claude Code** (docs fetched 2026-11-06)
- PreToolUse hooks:
  - they return `permissionDecision` = allow, deny, ask or defer, and can rewrite arguments through `updatedInput`;
  - exit code 2 blocks the call, even if the hook's JSON says allow;
  - other non-zero exits do not block unless `"onFailure":"block"` is set (v2.1.295+);
  - a timed-out PreToolUse hook does not block by default.
- PostToolUse cannot prevent execution. It can block-and-report or replace the output.
- MCP tools can be matched as `mcp__<server>__<tool>`.
- `allowManagedHooksOnly` in managed settings blocks user, project, local and plugin hooks.
- The docs call the `if` filter best-effort and recommend permission rules for hard guarantees. — [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- The sandbox exempts hooks themselves, file tools and MCP servers. Those run unsandboxed with full user access. — [Claude Code sandboxing](https://code.claude.com/docs/en/sandboxing)

**Codex**
- The approval policy is separate from the sandbox, and admins constrain both through requirements (see Q2). `prefix_rules` give command-level prompt or forbidden decisions, and the `mcp_servers` allowlist is matched on command or URL. — [Codex managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration)

**Cursor**
- CurXecute (CVE-2025-54135, CVSS 8.5, Aim Labs): a prompt injection could write `.cursor/mcp.json` without confirmation and get remote code execution.
- MCPoison (CVE-2025-54136, Check Point): a trusted MCP config could be changed later without re-approval.
- Both were fixed in Cursor 1.3 (2025-07-29), which now re-prompts when an MCP config changes.
- BackSlash showed the auto-run *denylist* was trivially bypassed (Base64, scripts, quoting), and Cursor replaced it with an allowlist. — [Tenable FAQ](https://www.tenable.com/blog/faq-cve-2025-54135-cve-2025-54136-vulnerabilities-in-cursor-curxecute-mcpoison); [The Hacker News, 2025-08](https://thehackernews.com/2025/08/cursor-ai-code-editor-fixed-flaw.html)

### Inferences
- **Inside versus outside model control:**

  | Enforcement point | Who controls it |
  |---|---|
  | Operator confirmations and injection monitor; system-prompt defenses; VPI-Bench and EIA "defensive prompts" | Inside, or model-adjacent (model or classifier judgment) |
  | Claude Code PreToolUse with managed-only hooks; Codex requirements and prefix rules; OS sandboxes; MCP client consent dialogs | Outside (deterministic, run by the harness) |
  | Claude Code "auto mode" | Hybrid: a classifier reviews actions |

  GOV-AIOS uses only outside points, plus OS TCC as the root: only the signed app holds the Accessibility and Screen Recording grants.
- The Claude Code docs say themselves that PreToolUse is fail-open by default (non-2 exits and timeouts proceed) unless `onFailure:"block"` is set. GOV-AIOS's managed hooks should set it and the paper should say so; otherwise a reviewer can claim the governor fails open.
- CurXecute and MCPoison show that config files writable by the agent defeat approval systems. Claude Code's protected paths (`.mcp.json`, `.claude`) and GOV-AIOS's root-owned managed settings and `/etc/codex/requirements.toml` are the matching defense. This is a strong point for the paper: the policy lives where the agent cannot write.
- A single audit log across browser flows and two vendors' coding agents: none of the sources I reviewed offers a unified cross-agent, cross-modality audit log. Vendor logs are per-product. This is a plausible novelty claim, but enterprise gateways (below) were not checked.

### Gaps
- Enterprise agent and MCP gateways (for example vendor "AI gateways" and MCP proxies) were not researched, and I have no citations for them.
- GitHub Copilot agent-mode safeguards (terminal command approval, firewall in the Copilot coding agent) were not researched.
- I did not read the PreToolUse and permission-precedence sections of the Claude Code docs past the first 100k characters. The managed-settings precedence and deny-rule semantics should be checked there.
- Codex PreToolUse hooks: the requirements page lists managed hooks, but I did not read the Codex hook event semantics (block and exit codes).

## Q4. Does prior work enforce policy on UI actions by element identity or role (rather than coordinates or pixels)? Is the "risk-rated page schema" novel?

### Takeaway
Prior guardrails for web agents classify or reason about each proposed action with a *learned model* (WebGuard, ShieldAgent, GuardAgent) or a vendor heuristic (Operator confirmations). I found no prior work that enforces an *admin-captured, per-page allowlist of accessibility-tree elements with risk ratings*, gated on page identification, as a deterministic reference monitor. The "risk-rated page schema" therefore looks novel as a deterministic enforcement mechanism. Related ideas exist in risk-labelled action datasets and in policy-as-rules guardrails.

### Cited Findings
- **WebGuard** (Zheng et al., arXiv:2507.14293): an action-level guardrail model that predicts the risk of each web action before it runs. Its dataset spans 193 websites and 22 domains with human-annotated risk levels. Enforcement is a *learned classifier*, not a deterministic schema. — [arXiv](https://arxiv.org/abs/2507.14293)
- A 2026 denial-of-service paper on agent guardrails runs WebGuard alongside BrowserGym and checks browser actions against the accessibility tree. It also shows that guardrails can themselves be attacked. — [arXiv:2606.14517](https://arxiv.org/pdf/2606.14517)
- **ShieldAgent** (arXiv:2503.22738): a guardrail agent that turns policy documents into probabilistic rule circuits over actions, with 90.1% recall reported on ShieldAgent-Bench. — [arXiv](https://arxiv.org/abs/2503.22738)
- **GuardAgent** checks whether agent actions satisfy safety-guard requests (benchmark Mind2Web-SC) **[UNVERIFIED: arXiv ID not retrieved]**. — cited via [ShieldAgent](https://arxiv.org/abs/2503.22738)
- PolicyGuard-4B (arXiv:2510.03485) checks proposed actions against the active policy before execution, using a learned model. — [arXiv](https://arxiv.org/abs/2510.03485)
- Conseca, Progent and CaMeL are deterministic but work over *API tool calls and arguments*, not GUI elements. — [Conseca](https://arxiv.org/abs/2501.17070); [Progent](https://arxiv.org/abs/2504.11703); [CaMeL](https://arxiv.org/abs/2503.18813)
- RedTeamCUA found that accessibility-tree grounding lowers ASR compared with screenshots alone. This supports structural grounding as a defense, though it is not a policy mechanism. — [arXiv](https://arxiv.org/pdf/2505.21936)
- The Mirror Injection attack in EIA works because agents trust *visual or semantic similarity*. Identity-based allowlisting of elements is the natural counter, but the EIA paper does not propose it. — [arXiv](https://arxiv.org/abs/2409.11295)

### Inferences
- **Novelty claim, worded carefully.** GOV-AIOS appears to be the first system where:
  1. an administrator captures page schemas from the OS accessibility tree;
  2. each actionable element carries a risk rating that decides allow, confirm or deny;
  3. page identity is verified before any element is resolved;
  4. enforcement is deterministic and lives in a separately signed process holding the TCC grants, so the model can only *request* schema-level actions.

  The closest prior art is WebGuard (risk-rated actions, but learned and per-action), Progent and Conseca (deterministic, but over API tools), and the Operator confirmations (heuristic, inside the vendor).
- The schema is a capability list in the classic sense: an element ID on a verified page is an unforgeable handle. The paper can frame it as "capabilities for GUIs", tying it to CaMeL and ACE.
- Expected reviewer objections:
  - **Coverage and maintenance:** schemas must be captured per page and break when the UI changes.
  - **Accessibility-tree spoofing:** attackers can inject elements with matching roles or labels (arXiv:2507.14799, 2507.04227). Page identification must therefore use more than labels.
  - **Data-flow attacks** through allowed text fields are not covered by element allowlisting.

### Gaps
- I did not search exhaustively for RPA and enterprise automation tools (UiPath and similar) that may already allowlist UI selectors for governance. That industry precedent could weaken the novelty claim and should be checked.
- I found no paper that evaluates a GUI agent defense on the macOS AX API specifically.
