# Enterprise and Regulatory AI Governance Frameworks for Agentic AI, Mapped to GOV-AIOS

Research date: 2026-11-06. Legend: **[V]** means the claim was checked this session against the cited page (primary or a reputable secondary source). **[U]** means unverified: from background knowledge, or only from a third-party summary. Re-check every [U] item against the primary text before putting it in the paper.

GOV-AIOS mechanisms referred to below:

- **M1:** Human-presence-bound approval (Touch ID; TOTP session that ends on screen lock).
- **M2:** Default-deny permissions and allow-listed destinations per flow.
- **M3:** Risk-rated UI elements, with submit-risk actions blocked unless allowed.
- **M4:** Approval bound to a digest of the exact code that will run.
- **M5:** Tamper-evident, hash-chained audit log.
- **M6:** Kill switches: emergency stop, and stop on screen lock.
- **M7:** One governance layer for browser automations and coding agents (Claude Code, Codex).
- **M8:** One admin per laptop.

## Q1. NIST: AI RMF 1.0, AI 600-1 GenAI Profile, and 2025-2026 agent work (CAISI)

### Takeaway
The NIST AI RMF and AI 600-1 are voluntary and organisation-level. Their outcomes for human-AI oversight roles (GOVERN 3), deactivation (MANAGE 2.4) and monitoring (MANAGE 4) map directly onto M1, M5 and M6. NIST's 2026 agent work is still at the RFI, evaluation and overlay-drafting stage, and has published no binding agent controls. CAISI's hijacking evaluations give a strong empirical reason to put deterministic gates *outside* the model, which is GOV-AIOS's design premise: attacks succeeded 57% of the time on average, rising to 80% with 25 retries.

### Cited Findings
- AI RMF 1.0 (NIST AI 100-1) was released on 26 Jan 2023. NIST says it "is being revised as part of the White House AI Action Plan" and gives no date for the revision. **[V]** [NIST AI RMF page](https://www.nist.gov/itl/ai-risk-management-framework)
- NIST AI 600-1, the Generative AI Profile, was released on 26 Jul 2024. **[V]** [NIST AI RMF page](https://www.nist.gov/itl/ai-risk-management-framework); [PDF](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- On 7 Apr 2026, NIST released a concept note for an "AI RMF Profile on Trustworthy AI in Critical Infrastructure". The AI RMF page lists no agent-specific profile. **[V]** [NIST AI RMF page](https://www.nist.gov/itl/ai-risk-management-framework)
- AI RMF subcategories relevant to GOV-AIOS (wording from background knowledge) **[U]**. [AI 100-1 PDF](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf):
  - **GOVERN 3.2:** policies define roles and responsibilities for "human-AI configurations and oversight".
  - **MAP 3.5:** processes for human oversight are defined, assessed and documented.
  - **MEASURE 2.7:** AI system security and resilience are evaluated.
  - **MANAGE 2.4:** mechanisms exist "to supersede, disengage, or deactivate AI systems" whose behaviour is inconsistent with intended use.
  - **MANAGE 4.1:** post-deployment monitoring plans, including incident response and decommissioning.
  - **GOVERN 6:** third-party and supply-chain risk.
- In AI 600-1, GOVERN 3 is titled "Human-AI Configuration and Oversight". "Human-AI Configuration" is also one of the profile's GAI risk categories (section 2.7). **[V, secondary]** [myctrl.tools GV-3](https://myctrl.tools/frameworks/nist-ai-600-1/family/govern-3)
- AI 600-1 actions on deactivation **[V, secondary]** ([myctrl.tools MG-2.4-004](https://myctrl.tools/frameworks/nist-ai-600-1/mg-2-4-4); [Anaconda guide](https://www.anaconda.com/blog/nist-ai-600-1-generative-ai-profile-guide)):
  - **MG-2.4-001:** communication plans for informing stakeholders during deactivation.
  - **MG-2.4-002:** escalation of GAI incidents to the organisation's risk management function.
  - **MG-2.4-004:** "establish and regularly review specific criteria that warrants the deactivation of GAI systems".
  - **GV-1.7-001:** protocols for deactivation.
- The 12 GAI risks in AI 600-1, from background knowledge **[U]**: CBRN information; confabulation; dangerous, violent or hateful content; data privacy; environmental impacts; harmful bias and homogenization; human-AI configuration; information integrity; information security; intellectual property; obscene, degrading or abusive content; value chain and component integration. [AI 600-1 PDF](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)
- **CAISI agent-hijacking evaluation.** The blog post was published 17 Jan 2025 and updated 19 Dec 2025. **[V]** [NIST CAISI blog](https://www.nist.gov/node/1872381)
  - Method: CAISI used AgentDojo (Workspace, Travel, Slack, Banking) against upgraded Claude 3.5 Sonnet, and added remote-code-execution, database-exfiltration and automated-phishing scenarios. The code is open-sourced at github.com/usnistgov/agentdojo-inspect.
  - Red teaming with the UK AISI raised attack success from 11% (strongest baseline attack) to 81% (strongest new attack) on held-out Workspace tasks.
  - The average success rate across five injection tasks was 57%. Running each task 25 times raised it to 80%.
  - CAISI's conclusion: hijacking "will remain a persistent challenge".
- **CAISI/UK AISI/Gray Swan public red-teaming competition.** It drew more than 250,000 attack attempts from more than 400 participants against 13 frontier models in tool-use, coding and computer-use settings. At least one successful attack was found against every target model. **[V, search snippet; the full page was not read]** [NIST CAISI blog](https://www.nist.gov/blogs/caisi-research-blog/insights-ai-agent-security-large-scale-red-teaming-competition)
- **CAISI RFI on securing AI agent systems.** **[V]** [NIST news](https://www.nist.gov/news-events/news/2026/01/caisi-issues-request-information-about-securing-ai-agent-systems); [Federal Register 2026-00206](https://www.govinfo.gov/content/pkg/FR-2026-01-08/html/2026-00206.htm)
  - Published in the Federal Register on 8 Jan 2026, docket NIST-2025-0035. Comments were due 9 Mar 2026.
  - Topics: threats specific to agents; development and deployment security methods; gaps in existing cybersecurity approaches; measurement; and deployment-environment interventions to "constrain and monitor the extent of agent access".
  - Scope: excludes chatbots and RAG systems that do not act autonomously.
- CAISI published "Analysis of Responses to the RFI Regarding Security Considerations for AI Agents" on 18 May 2026. **[V, search snippet; contents not read]** [NIST publication](https://www.nist.gov/publications/summary-analysis-responses-request-information-regarding-security-considerations-ai)
- NIST launched its AI Agent Standards Initiative on 17 Feb 2026 as an umbrella programme. **[V, secondary]** [CSA research note](https://labs.cloudsecurityalliance.org/research/csa-research-note-nist-caisi-ai-agent-security-agenda-2026-2/); [Pillsbury](https://www.pillsburylaw.com/en/news-and-insights/nist-ai-agent-standards.html)
- NIST COSAIS (Control Overlays for Securing AI Systems), SP 800-53 overlays:
  - Use cases include **single AI agents** and **multi-agent systems**. **[V]** [NIST CSRC COSAIS use cases](https://csrc.nist.gov/Projects/cosais/use-cases)
  - As of Apr 2026 the agent overlays were still in development, with no firm publication date. **[V, secondary]** [CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-nist-ai-agent-standards-20260416-csa-style/)
  - A Cybersecurity Framework Profile for AI was in development in 2025. **[U]** [Redmond](https://redmondmag.com/articles/2025/08/26/nist-outlines-cybersecurity-framework-for-ai-system.aspx)

### Inferences
- MANAGE 2.4 and MG-2.4-004 ask for deactivation mechanisms *with criteria decided in advance*. GOV-AIOS's emergency stop and stop-on-lock (M6) meet the mechanism half. "Screen locked, so the human is absent, so stop" is itself a pre-decided deactivation criterion.
- The 57% to 80% retry result supports placing the control boundary in deterministic code (M2, M3, M4) rather than in model-based detection. A probabilistic defence loses to repeated attempts. A default-deny allow-list does not.
- The RFI's "constrain and monitor the extent of agent access in the deployment environment" topic matches M2 and M5 almost word for word. GOV-AIOS can be positioned as a concrete answer to that topic.

### Gaps
- I could not read the AI 600-1 PDF in this session because PDF tooling was unavailable. Exact action IDs beyond MG-2.4 and GV-1.7, and the official names of the 12 risks, should be checked in the PDF.
- I did not read the contents of the May 2026 RFI response analysis.
- I found no status for any NIST "Cyber AI Profile" or IR number.
- The current publication status of the COSAIS agent overlays is unknown.

## Q2. EU AI Act (Regulation (EU) 2024/1689): Art. 12, 14, 26, 50, GPAI, timelines, and deployer applicability

### Takeaway
Art. 14 (human oversight, including a "stop" button) and Art. 12/26(6) (automatic logs, kept at least six months) are the closest legal analogues to M1, M6 and M5. They bind only *high-risk* systems. Annex III high-risk obligations now apply from 2 Dec 2027 under the Digital Omnibus. A deployer's on-device coding or browser agents are usually *not* high-risk, so the obligations that actually bind them today are Art. 4 AI literacy and, narrowly, Art. 50. GOV-AIOS is therefore best framed as voluntary alignment with the high-risk design pattern, and as useful evidence if an agent is used in an Annex III context.

### Cited Findings
- **Art. 3(4):** a "deployer" is a person or body "using an AI system under its authority except where the AI system is used in the course of a personal non-professional activity". **[V]** [Art. 3, AI Act Explorer](https://artificialintelligenceact.eu/article/3/)
- **Art. 12(1):** "High-risk AI systems shall technically allow for the automatic recording of events (logs) over the lifetime of the system." **[V]** [Art. 12](https://artificialintelligenceact.eu/article/12/)
  - Art. 12(2): logs must support identifying risk situations or substantial modification, post-market monitoring (Art. 72), and deployer monitoring (Art. 26(5)).
  - Art. 12(3): minimum log fields, applicable to biometric (Annex III 1(a)) systems only.
- **Art. 14(1):** high-risk systems must be designed so they "can be effectively overseen by natural persons during the period in which they are in use". **[V]** [Art. 14](https://artificialintelligenceact.eu/article/14/)
  - Art. 14(4)(b): overseers must stay aware of automation bias.
  - Art. 14(4)(d): overseers can decide not to use the system or "disregard, override or reverse" its output.
  - Art. 14(4)(e): overseers can "intervene ... or interrupt the system through a 'stop' button or a similar procedure that allows the system to come to a halt in a safe state".
- **Art. 26 (deployer duties, high-risk only).** **[V]** [Art. 26](https://artificialintelligenceact.eu/article/26/)
  - Art. 26(1): use the system per the instructions for use.
  - Art. 26(2): "assign human oversight to natural persons who have the necessary competence, training and authority".
  - Art. 26(5): monitor operation.
  - Art. 26(6): keep auto-generated logs "for a period appropriate to the intended purpose ... of at least six months".
- **Art. 19:** a parallel provider-side log retention duty of at least six months. **[U]** [Art. 19](https://artificialintelligenceact.eu/article/19/)
- **Art. 50(1):** providers must ensure that systems interacting with natural persons disclose that they are AI. Other Art. 50 duties concern synthetic content, emotion recognition and deepfakes. **[U, not re-fetched]** [Art. 50](https://artificialintelligenceact.eu/article/50/)
- **Timeline as amended by the Digital Omnibus on AI.**
  - Original dates **[U, background]**: entry into force 1 Aug 2024; prohibitions and Art. 4 literacy from 2 Feb 2025; GPAI (Arts. 51-56) from 2 Aug 2025; Art. 50 from 2 Aug 2026.
  - Omnibus changes **[V, secondary]** ([Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)):
    - Annex III (stand-alone) high-risk obligations apply from **2 Dec 2027**.
    - Annex I (product-embedded) high-risk obligations apply from **2 Aug 2028**.
    - Art. 50 "proceed[s] as scheduled from 2 August 2026". Art. 50(2) watermarking has a grace period to 2 Dec 2026 for systems already on the market.
    - GPAI dates: "No change".
    - Art. 4 literacy is softened to "support the development of AI literacy among their staff".
  - Models placed on the market before 2 Aug 2025 have until 2 Aug 2027 (Art. 111(3)). **[U]**
- **Omnibus legislative status.**
  - The provisional agreement was reached on 6-7 May 2026. **[V]** [Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/); [Sidley](https://datamatters.sidley.com/2026/06/22/eu-lawmakers-reach-provisional-agreement-to-delay-key-eu-ai-act-obligations/)
  - Parliament adopted the text on 16 Jun 2026 and the Council on 29 Jun 2026. **[V, secondary]** [FPF](https://fpf.org/blog/the-ai-act-implementation-timeline-what-changes-under-the-ai-omnibus)
  - It was reportedly published in the OJ on 24 Jul 2026 as **Regulation (EU) 2026/1744** and entered into force 27 Jul 2026. **[U, secondary only; check ELI http://data.europa.eu/eli/reg/2026/1744/oj on EUR-Lex]** [nicfab.eu](https://www.nicfab.eu/en/posts/digital-omnibus-ai-official-journal/)
- The Omnibus also adds new prohibitions (nudification apps, CSAM) from 2 Dec 2026. **[U, single secondary]** [Pillitteri](https://pasqualepillitteri.it/en/news/5190/digital-omnibus-ai-act-eu-parliament)
- GPAI obligations (Arts. 53-55) fall on *model providers* such as Anthropic and OpenAI, not on deployers. **[U, background]** [AI Act Explorer](https://artificialintelligenceact.eu/the-act/)

### Inferences
- **Applicability to a deployer's on-device agent tooling.**
  - (a) A company running Claude Code or Codex on employee laptops is a *deployer* (Art. 3(4)). A solo developer using them personally and non-professionally is out of scope.
  - (b) Coding and browser agents are not listed in Annex III, so Arts. 12, 14 and 26 do **not** bind them unless they are used for an Annex III purpose, such as employment decisions (Annex III(4)) or access to essential services.
  - (c) What binds now: Art. 4 literacy (softened), and Art. 50 only where the deployer generates deepfakes or public-interest text.
  - (d) GPAI duties rest upstream with the model vendors.
- **Is GOV-AIOS itself an "AI system"?** Probably not. It is deterministic policy code. It therefore takes on no provider duties, but it can *supply* the Art. 14(4)(e) stop function and the Art. 12/26(6) logs for an agent stack that becomes high-risk.
- The Art. 14(4)(e) "stop button ... halt in a safe state" maps cleanly onto M6, and Art. 14(4)(d) "override or reverse" onto M1 denial. Art. 14(4)(b) automation bias is the risk that M3 and M4 address: the human approves concrete, digest-bound code, not an agent summary.
- **Art. 26(2) competence and authority versus M8.** Single-admin-per-laptop makes the laptop owner the overseer. In an enterprise, the *organisation* must assign and train overseers. Nothing in GOV-AIOS records who is authorised or trained.
- **Art. 26(6) six-month retention.** M5 gives integrity but not a retention policy or export. Art. 12(2) traceability for post-market monitoring implies off-device aggregation, which GOV-AIOS lacks.

### Gaps
- EUR-Lex returned an empty page, so I did not read the consolidated or amended text directly. Article quotes come from artificialintelligenceact.eu, which mirrors the OJ text.
- The OJ number 2026/1744 is reported only by secondary sources.
- I did not check whether the Commission's Art. 96 guidelines or harmonised standards (CEN-CENELEC JTC 21, e.g. prEN on logging and human oversight) have been published.

## Q3. ISO/IEC 42001:2023 and ISO/IEC 23894:2023

### Takeaway
ISO/IEC 42001 is a certifiable management-system standard. Its Annex A controls on operation and monitoring, event logs and responsible use are satisfiable *per laptop* by M5 and M1-M3. Its clauses on roles, competence, internal audit and management review are organisational, and GOV-AIOS cannot satisfy them alone. ISO/IEC 23894 is non-certifiable risk-process guidance (ISO 31000-based) and offers no agent-specific controls.

### Cited Findings
- ISO/IEC 42001 Annex A has 38 reference controls across 9 objectives (A.2-A.10). Clause 6.1.3 says Annex A is not exhaustive. **[V, secondary]** [blckalpaca](https://blckalpaca.at/en/knowledge-base/ai-agents/iso-42001-ai-management-system/annex-a-controls-iso-42001); [ISO page](https://www.iso.org/standard/81230.html)
- **A.6.2.8 "AI system recording of event logs":** the organisation shall determine at which life-cycle phases event logging is enabled. Practitioners recommend tamper-evident storage, which is guidance and not the standard's text. **[V, secondary]** [ISMS.online A.6.2.8](https://www.isms.online/iso-42001/annex-a-controls/a-6-ai-system-life-cycle/a-6-2-8-ai-system-recording-of-event-logs/); [agenticrail](https://agenticrail-web.pages.dev/blog/iso-42001-a628-event-log/)
- Other relevant Annex A controls (titles from background knowledge) **[U]**. [ISO 42001](https://www.iso.org/standard/81230.html):
  - A.3.2 AI roles and responsibilities.
  - A.6.2.6 AI system operation and monitoring.
  - A.6.2.5 AI system deployment.
  - A.8 information for interested parties, including incident communication.
  - A.9.2 processes for responsible use of AI systems.
  - A.9.4 intended use of the AI system.
  - A.10.2/A.10.3 allocating responsibilities with, and managing, suppliers and third parties.
- ISO/IEC 42001 main clauses relevant here **[U]**: 5.3 roles, 7.2 competence, 8.1 operational control, 9.2 internal audit, 9.3 management review, 10.2 nonconformity and corrective action. [ISO 42001](https://www.iso.org/standard/81230.html)
- ISO/IEC 23894:2023 is used alongside ISO 31000:2018 and mirrors its clause structure. Annex C maps risk-management processes across the AI life cycle (per ISO/IEC 22989). It is guidance, not certifiable. **[V, secondary]** [AI Standards Hub](https://aistandardshub.org/a-new-standard-for-ai-risk-management); [Strac](https://www.strac.io/blog/iso-23894); [ISO page](https://www.iso.org/standard/77304.html)

### Inferences
- M5 exceeds the bare A.6.2.8 requirement, which says only "determine when logs are enabled". It also gives the *integrity* that auditors expect evidence to have.
- M2, M3 and M4 together put A.9.4 "intended use" into operation at runtime: each flow can only do what its allow-list and risk ratings permit.
- An ISO/IEC 42001-certified organisation could cite GOV-AIOS as an operational control under 8.1. It would still need the AIMS layer: policy, risk assessment per 6.1, competence, audit and review.

### Gaps
- I did not read the ISO/IEC 42001 text, which is paywalled. Control titles other than A.6.2.8 are [U].
- I did not check whether ISO/IEC 42001 has an amendment, or whether ISO/IEC 42005 or 42006 add agent guidance. ISO/IEC 42005 (impact assessment) was reportedly published in 2025 **[U]**.

## Q4. OWASP: LLM Top 10 2025, Agentic Threats and Mitigations, and the Top 10 for Agentic Applications 2026

### Takeaway
OWASP is the framework that most directly prescribes GOV-AIOS's mechanisms:

- LLM06 Excessive Agency names minimal tools, minimal permissions and human-in-the-loop approval of high-impact actions.
- The 2026 Agentic Top 10 (ASI01-ASI10) adds "least agency", approval of the *raw* action rather than the agent's summary, immutable logs, and a working kill switch.

### Cited Findings
- **LLM06:2025 Excessive Agency.** **[V, primary URL; content via secondary summary]** [OWASP LLM06](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
  - Root causes: excessive functionality, permissions and autonomy.
  - Mitigations:
    - Minimise extensions, e.g. don't offer URL-fetch if it isn't needed.
    - Avoid open-ended extensions, e.g. shell versus a dedicated file-write tool.
    - Minimise permissions and execute in the user's context with minimal OAuth scope.
    - "Require a human to approve high-impact actions before they are taken."
    - Rate limiting.
- **LLM01:2025 Prompt Injection** covers direct and indirect injection. Its mitigations include constraining model behaviour, least privilege, and human approval for high-risk operations. **[U, not fetched this session]** [OWASP LLM01](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- **OWASP Top 10 for Agentic Applications for 2026** was published on 9 Dec 2025. It is peer-reviewed, with more than 100 contributors. **[V]** [OWASP GenAI](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026)
  - Categories **[V, secondary]** ([Cycode](https://cycode.com/blog/owasp-top-10-agentic-applications/)):
    - ASI01 Agent Goal Hijack
    - ASI02 Tool Misuse & Exploitation
    - ASI03 Identity & Privilege Abuse
    - ASI04 Agentic Supply Chain Vulnerabilities
    - ASI05 Unexpected Code Execution (RCE)
    - ASI06 Memory & Context Poisoning
    - ASI07 Insecure Inter-Agent Communication
    - ASI08 Cascading Failures
    - ASI09 Human-Agent Trust Exploitation
    - ASI10 Rogue Agents
- Agentic Top 10 mitigation themes **[V, secondary; check the OWASP PDF]** ([Cycode](https://cycode.com/blog/owasp-top-10-agentic-applications/)):
  - "Least agency": the minimum autonomy, tools and permissions a task requires (ASI02, ASI03).
  - Explicit confirmation of sensitive actions that shows the *raw action rather than the agent's summary* (ASI01, ASI09).
  - Immutable logs of tool calls and memory writes that also record what was displayed at confirmation time (ASI07, ASI09).
  - A kill switch "that actually works when invoked", with behavioural baselines (ASI10).
  - Human-in-the-loop confirmation for file deletion, data modification and external communications (ASI02). **[V, secondary]** [Kaspersky](https://www.kaspersky.com/blog/top-agentic-ai-risks-2026/55184/)
- The OWASP "Agentic AI - Threats and Mitigations" guide (Agentic Security Initiative) appeared in Feb 2025 with a T1-T15 threat taxonomy. From background knowledge, it includes T1 Memory Poisoning, T2 Tool Misuse, T3 Privilege Compromise and T10 Overwhelming Human-in-the-Loop. **[U; searches did not surface the primary document]** [OWASP GenAI resources](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)

### Inferences
- **M4 (digest-bound approval)** is a direct implementation of the ASI01/ASI09 guidance to approve the raw action, not the agent's narrative. The digest guarantees that what was shown is exactly what runs. That closes the "what was displayed versus what ran" gap that OWASP asks logs to capture.
- **M3 (risk-rated UI, submit blocked unless allowed)** implements LLM06's "independently verify and approve high-impact actions" at UI-element granularity for browser agents.
- **T10 "Overwhelming HITL" [U] and ASI09** warn that too many prompts lead to rubber-stamping. M3's risk tiers and per-flow allow-lists reduce prompt volume, but GOV-AIOS has no measured approval-fatigue data. This is a gap worth stating in the paper.
- ASI07 (inter-agent) and ASI08 (cascading) assume multi-agent topologies. GOV-AIOS governs agents individually and does not mediate agent-to-agent messages.

### Gaps
- I did not download the Agentic Top 10 PDF. Per-entry mitigation wording comes from secondary sources.
- I could not retrieve the Feb 2025 Threats and Mitigations guide or confirm its T-numbering.

## Q5. MITRE ATLAS techniques relevant to agents

### Takeaway
ATLAS added agent-specific techniques in Oct 2025, with Zenity Labs. Context poisoning, agent configuration modification, tool-invocation exfiltration and tool poisoning map to threats that M2, M4 and M5 constrain. ATLAS has no lateral-movement or MCP/control-plane coverage.

### Cited Findings
- Agent-focused techniques from the Oct 2025 expansion **[V, secondary]** ([CSA ATLAS gap analysis, 27 Mar 2026, draft](https://labs.cloudsecurityalliance.org/research/csa-research-note-atlas-agentic-gap-analysis-20260327/)):
  - AML.T0080 AI Agent Context Poisoning (.000 Memory; .001 Thread)
  - AML.T0081 Modify AI Agent Configuration
  - AML.T0082 RAG Credential Harvesting
  - AML.T0086 Exfiltration via AI Agent Tool Invocation
- The same CSA note proposes AML.T0090-T0095 (A2A lateral movement, tool-chain poisoning, orchestrator hijacking, credential relay, memory persistence, MCP server compromise). These IDs are **candidates pending MITRE review, not official**. It also notes that ATLAS has no lateral-movement or C2 tactic. **[V]** [CSA ATLAS gap analysis](https://labs.cloudsecurityalliance.org/research/csa-research-note-atlas-agentic-gap-analysis-20260327/)
- AML.T0110 AI Agent Tool Poisoning, and case study AML.CS0054 (data exfiltration via a remote poisoned MCP tool). **[U, vendor blogs]** [nhimg](https://nhimg.org/articles/ai-agent-attack-techniques-expand-mitre-atlas-beyond-llm-threats/); [ATLAS](https://atlas.mitre.org/)
- Long-standing techniques from background knowledge **[U]**: AML.T0051 LLM Prompt Injection (.000 Direct, .001 Indirect), AML.T0053 AI Agent Tool Invocation (formerly "LLM Plugin Compromise"), AML.T0054 LLM Jailbreak. [ATLAS](https://atlas.mitre.org/techniques/AML.T0051)
- Technique counts differ by source and version ("84 techniques / 16 tactics v5.4.0" versus "139 Agentic-tagged entries v2026.09"). These counts are unreliable. **[U]** [Speakeasy](https://www.speakeasy.com/blog/mitre-atlas-explained)

### Inferences
- **T0086 (exfiltration via tool invocation):** M2's allow-listed destinations are the direct mitigation.
- **T0081 (modify agent configuration):** M4 covers code. Whether GOV-AIOS protects agent config files (e.g. `.claude/settings.json`, `AGENTS.md`, MCP config) is a question for the paper to answer explicitly.
- **T0051.001 (indirect injection):** GOV-AIOS does not detect injection. It bounds the blast radius instead (M2, M3), consistent with CAISI's finding that detection loses to retries.

### Gaps
- I did not verify technique IDs on atlas.mitre.org directly. Check them before citing. The latest ATLAS release number is unknown.

## Q6. Industry frameworks: Google SAIF and agent paper, Anthropic RSP, Microsoft CAF and Agent 365, CSA AICM

### Takeaway
Industry guidance converges on the same three ideas: a defined human controller, limited powers, and observable actions. Microsoft's guidance is the most explicit about *enterprise-scale* needs that GOV-AIOS lacks: a central registry, a unique agent identity, cross-platform central policy, SOC integration, and an incident-disable plan. Anthropic's RSP governs model development, not deployer action controls.

### Cited Findings
- **Google, "An Introduction to Google's Approach for Secure AI Agents"** (Díaz and Olive, 2025). **[V]** [Google Research](https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/)
  - Three principles: agents "must have well-defined human controllers, their powers must be carefully limited, and their actions and planning must be observable".
  - Proposes hybrid defence-in-depth: deterministic controls plus reasoning-based defences.
  - The search did not confirm that it is formally part of SAIF.
  - SAIF itself is at [saif.google](https://saif.google/). **[U, not fetched]**
- **Microsoft Cloud Adoption Framework, "Govern and secure AI agents across the organization"** (ms.date 2026-04-09). **[V]** [Microsoft Learn](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization)
  - "Establish a centralized and enforceable governance and security baseline for all AI agents".
  - Maintain an agent registry ("You can't govern agents you don't know exist").
  - "Require each agent to operate under a distinct agent identity" (Entra Agent ID).
  - "Apply policies consistently across first-party agents, custom agents, and third-party agents", including allow or block of MCP servers.
  - Continuous observation, with alerts routed to the SOC through Sentinel.
  - Enforce least privilege, with tools enforcing the user's permissions.
  - Incident response: "Decide in advance how to quickly disable an agent", and preserve logs for forensics.
  - Begin with an audit-based model, then tighten.
- **Microsoft Agent 365** is the unified registry and control plane. Entra Agent ID covers identity, Conditional Access and governance. Licensing is via M365 E7, or Agent 365 plus Entra P1 / M365 E3. **[V]** [Entra Agent ID governance](https://learn.microsoft.com/en-us/entra/id-governance/agent-id-governance-overview); [Agent registry convergence](https://learn.microsoft.com/entra/agent-id/agent-registry-convergence)
  - Entra agent-registry pages will be retired 1 May 2026. **[U, third-party]** [topedia](https://blog-en.topedia.com/?p=65633)
- **CSA AI Controls Matrix (AICM).** **[V]** [CSA AICM](https://cloudsecurityalliance.org/artifacts/ai-controls-matrix/); [CSA v1.1 blog](https://cloudsecurityalliance.org/blog/2026/07/14/ai-controls-matrix-v1-1-strengthening-the-foundation-for-trustworthy-ai)
  - v1.0 was released 9-10 Jul 2025 with 243 control objectives across 18 domains, built on CCM.
  - v1.1 (Jul 2026) has 247 objectives, synchronised to CCM v4.1.
  - The specific AICM control IDs relevant to agent action authorisation were not retrieved.
- **Anthropic Responsible Scaling Policy v3.0** was published 24 Feb 2026. It replaces the ASL-tier focus with Frontier Safety Roadmaps and Risk Reports. **[V]** [Anthropic RSP v3](https://www.anthropic.com/news/responsible-scaling-policy-v3)
  - Point releases 3.1-3.4 followed through 8 Jul 2026. **[V, search snippet]** [Anthropic RSP](https://www.anthropic.com/responsible-scaling-policy)
  - No deployer-side agent action controls were found in the RSP.

### Inferences
- GOV-AIOS meets Google's three principles at laptop scope: controller (M1, M8), limited powers (M2, M3), observable (M5).
- GOV-AIOS meets Microsoft's "decide in advance how to disable" (M6), least privilege (M2) and "consistent policy across agent platforms" (M7, but only on one machine). It misses the registry, unique agent identity, SOC/SIEM export, central policy distribution and cost tracking.
- The RSP is model-provider governance. For the paper, Anthropic's relevant material is product-level: Claude Code permission modes, hooks, sandboxing, and usage-policy rules on agentic use. That material was **not researched here**.

### Gaps
- I did not fetch Anthropic's Usage Policy agentic provisions or the Claude Code security docs (e.g. https://docs.anthropic.com/en/docs/claude-code/security) **[U]**.
- I did not retrieve SAIF's agent-specific risk entries (e.g. "Rogue Actions").
- AICM control IDs (e.g. in the Application and Interface Security or IAM domains) are missing. The AICM spreadsheet is needed.

## Q7. Fit and gap: where frameworks call for what GOV-AIOS does, where it falls short, and the control-mapping table

### Takeaway
Across all the frameworks, GOV-AIOS strongly matches the controls applied *at the point of action*: meaningful human oversight bound to presence, least privilege/agency, an approved-equals-executed guarantee, tamper-evident logs, and a stop button. It falls short on the organisational and fleet layer the same frameworks assume: registry and inventory, per-agent identity, central policy, multi-user role separation, retention and export, SOC reporting, competence records, and measured oversight effectiveness.

### Cited Findings
Control-mapping table. The sources are those already cited above.

| Framework clause | Requirement (short) | GOV-AIOS mechanism | Gap |
|---|---|---|---|
| EU AI Act Art. 14(1), 14(4)(d) [V] ([src](https://artificialintelligenceact.eu/article/14/)) | Effective oversight by natural persons; ability to override or reverse | M1 Touch ID/TOTP approval; denial = override | Binding only for high-risk systems (from 2 Dec 2027). No overseer-competence record. |
| EU AI Act Art. 14(4)(e) [V] ([src](https://artificialintelligenceact.eu/article/14/)) | "Stop" button bringing the system to a safe halt | M6 emergency stop + stop on lock | "Safe state" for half-done browser or code actions (rollback) not defined |
| EU AI Act Art. 14(4)(b) [V] ([src](https://artificialintelligenceact.eu/article/14/)) | Awareness of automation bias | M3 risk tiers, M4 digest-bound exact-code approval | No measured approval-fatigue or rubber-stamp data |
| EU AI Act Art. 12(1)-(2) [V] ([src](https://artificialintelligenceact.eu/article/12/)) | Automatic event logs over the lifetime; traceability | M5 hash-chained log | Log stays on the device; no post-market aggregation |
| EU AI Act Art. 26(2) [V] ([src](https://artificialintelligenceact.eu/article/26/)) | Deployer assigns oversight to competent, authorised persons | M8 single admin = owner | No org-assigned overseer, no training attestation, no multi-user setup |
| EU AI Act Art. 26(5)-(6) [V] ([src](https://artificialintelligenceact.eu/article/26/)) | Monitor operation; keep logs at least 6 months | M5 | No retention policy, export or off-device backup |
| EU AI Act Art. 4 [V, secondary] ([src](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/)) | Support AI literacy of staff | n/a (the approval UI shows risk ratings) | Out of scope |
| NIST AI RMF GOVERN 3.2 / AI 600-1 GV-3 [U]/[V, secondary] ([src](https://myctrl.tools/frameworks/nist-ai-600-1/family/govern-3)) | Define human-AI configuration and oversight roles | M1, M8 | Roles fixed to one admin; no role differentiation |
| NIST AI RMF MANAGE 2.4; AI 600-1 MG-2.4-004, GV-1.7-001 [U]/[V, secondary] ([src](https://myctrl.tools/frameworks/nist-ai-600-1/mg-2-4-4)) | Mechanisms + pre-set criteria to deactivate | M6 (lock = criterion; e-stop) | No automated anomaly-triggered stop; no stakeholder notice (MG-2.4-001) |
| NIST AI RMF MANAGE 4.1 / MG-2.4-002 [U]/[V, secondary] ([src](https://myctrl.tools/frameworks/nist-ai-600-1/family/manage-2)) | Post-deployment monitoring; incident escalation | M5 | No escalation channel or incident reporting |
| NIST CAISI RFI topic 5 [V] ([src](https://www.nist.gov/news-events/news/2026/01/caisi-issues-request-information-about-securing-ai-agent-systems)) | Constrain and monitor agent access in the deployment environment | M2 default-deny + allow-list; M5 | None at host scope |
| NIST CAISI hijacking eval [V] ([src](https://www.nist.gov/node/1872381)) | Adaptive, multi-attempt evaluation | (Paper's attack suite) | GOV-AIOS should report multi-attempt results |
| ISO/IEC 42001 A.6.2.8 [V, secondary] ([src](https://www.isms.online/iso-42001/annex-a-controls/a-6-ai-system-life-cycle/a-6-2-8-ai-system-recording-of-event-logs/)) | Determine life-cycle phases with event logging | M5 (always on, tamper-evident) | No AIMS documentation |
| ISO/IEC 42001 A.6.2.6, A.9.2, A.9.4 [U] ([src](https://www.iso.org/standard/81230.html)) | Operation and monitoring; responsible-use processes; intended use | M2, M3, M7 per-flow policy | Policy authored per laptop, not by the organisation |
| ISO/IEC 42001 cl. 7.2, 9.2, 9.3 [U] ([src](https://www.iso.org/standard/81230.html)) | Competence, internal audit, management review | M5 provides audit evidence | No reporting or dashboards for audit or review |
| OWASP LLM06:2025 [V] ([src](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)) | Minimise functionality, permissions, autonomy; human approval of high-impact actions | M2, M3, M1 | No per-user downstream identity/OAuth scoping (agent runs as the OS user) |
| OWASP LLM01:2025 [U] ([src](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)) | Least privilege + HITL against prompt injection | M2, M3 bound the blast radius | No injection detection (by design) |
| OWASP ASI01/ASI09 2026 [V, secondary] ([src](https://cycode.com/blog/owasp-top-10-agentic-applications/)) | Confirm the raw action, not the agent's summary; log what was displayed | M4 digest binding; M5 | Check that the log stores the displayed artefact, not only the digest |
| OWASP ASI02/ASI03 "least agency" [V, secondary] ([src](https://cycode.com/blog/owasp-top-10-agentic-applications/)) | Minimum autonomy, tools, permissions | M2, M3 | No credential vaulting / per-agent identity (ASI03) |
| OWASP ASI05 RCE [V, secondary] ([src](https://cycode.com/blog/owasp-top-10-agentic-applications/)) | Control unexpected code execution | M4 exact-code digest approval | Covers approved scripts; coding agents' arbitrary shell needs separate policy (verify scope) |
| OWASP ASI10 rogue agents [V, secondary] ([src](https://cycode.com/blog/owasp-top-10-agentic-applications/)) | Working kill switch + behavioural baselines | M6 | No behavioural baselining or alerting |
| OWASP ASI07/ASI08 [V, secondary] ([src](https://cycode.com/blog/owasp-top-10-agentic-applications/)) | Secure inter-agent comms; contain cascades | n/a | Multi-agent orchestration out of scope |
| MITRE ATLAS AML.T0086 [V, secondary] ([src](https://labs.cloudsecurityalliance.org/research/csa-research-note-atlas-agentic-gap-analysis-20260327/)) | Exfiltration via agent tool invocation | M2 destination allow-list | Covert channels inside allow-listed hosts |
| MITRE ATLAS AML.T0081 [V, secondary] ([src](https://labs.cloudsecurityalliance.org/research/csa-research-note-atlas-agentic-gap-analysis-20260327/)) | Modify agent configuration | M4 (code); M5 | Config-file integrity (settings, MCP, AGENTS.md) unclear |
| MITRE ATLAS AML.T0080 [V, secondary] ([src](https://labs.cloudsecurityalliance.org/research/csa-research-note-atlas-agentic-gap-analysis-20260327/)) | Context and memory poisoning | M2, M3 limit impact | No memory hygiene |
| Google secure-agents paper [V] ([src](https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/)) | Defined human controller; limited powers; observable actions | M1+M8; M2+M3; M5 | Observability is local only |
| Microsoft CAF 2.1.2-2.1.4 [V] ([src](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization)) | Registry; distinct agent identity; consistent cross-platform policy | M7 (cross-agent on one host) | No fleet registry, no agent identity, no central policy push |
| Microsoft CAF 2.3.7-2.3.8 [V] ([src](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization)) | Least privilege; SOC/SIEM integration | M2; M5 | No SIEM export or alerting |
| Microsoft CAF 2.3.10 [V] ([src](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/ai-agents/governance-security-across-organization)) | Pre-decided disable; preserve logs for forensics | M6; M5 | No remote/fleet-wide kill |
| CSA AICM v1.1 [V] ([src](https://cloudsecurityalliance.org/artifacts/ai-controls-matrix/)) | 247 control objectives / 18 domains | Partial (IAM, logging, app security) | Specific control IDs not mapped (gap) |

### Inferences
- **Strongest claims for the paper.**
  - (1) M4 digest-bound approval directly implements OWASP's "approve the raw action" guidance and goes beyond what any framework explicitly requires. No framework surveyed demands cryptographic binding between approval and execution.
  - (2) M1 presence binding makes "effective oversight by natural persons ... during the period in which they are in use" (Art. 14(1)) literal: no presence, no agent.
  - (3) M6 stop-on-lock is a pre-declared deactivation criterion in the sense of AI 600-1 MG-2.4-004.
- **Consistent gaps to declare as limitations or future work.**
  - Fleet registry and per-agent identity (Microsoft CAF, ASI03).
  - Central or organisation-authored policy with distribution (CAF 2.1.4, ISO/IEC 42001 A.9).
  - Multi-user and role separation, and overseer competence records (Art. 26(2), GOVERN 3.2).
  - Log retention, export and SIEM integration (Art. 26(6), CAF 2.3.8).
  - Reporting for audit and management review (ISO/IEC 42001 cl. 9).
  - Remote or fleet kill (CAF 2.3.10).
  - Behavioural anomaly detection (ASI10).
  - Rollback and "safe state" semantics (Art. 14(4)(e)).
  - Measured oversight effectiveness and approval fatigue (Art. 14(4)(b), ASI09).
  - Multi-agent mediation (ASI07, ASI08).
- **Enterprise-relevance framing.** GOV-AIOS is an endpoint *enforcement point* that an enterprise control plane (Agent 365-style registry, SIEM, ISO/IEC 42001 AIMS) could consume. The single-admin design is a deliberate scope choice, not a claim of enterprise completeness.
- **Regulatory framing.** For most deployers using coding and browser agents in 2026-2027, no EU high-risk obligation binds them. GOV-AIOS is voluntary alignment with Art. 12 and Art. 14 design patterns, and becomes compliance evidence only if an agent is used in an Annex III context after 2 Dec 2027.

### Gaps
- The table cites some [U] clause wording (AI RMF subcategory text, ISO/IEC 42001 non-A.6.2.8 titles, LLM01, ATLAS T0051/T0053). Verify these against the primary texts before publication.
- No AICM control IDs, SAIF risk IDs or Anthropic usage-policy clauses are mapped.
- Whether GOV-AIOS logs the *displayed* approval artefact, and whether it protects agent config files, depends on the implementation and should be checked in the codebase.
