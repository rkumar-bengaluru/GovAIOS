# GOV-AIOS: Governed AI Operating System
### Deterministic workflows. Local control. Policy-safe automation.

> **Your Laptop, Your Rules.** Not a cloud vision agent that guesses. A local OS layer that does exactly what you do every day — only when you told it to, and stops if anything looks off.

[Architecture](./AI_Operating_System_Architecture.png)

> **Core Thesis:** If a user manually checks Gmail daily, automating that same action locally should not be treated as a bot. API scraping and cloud vision agents violate ToS and hallucinate. Governed local execution does not.

---

### The Problem

1.  **API Automation is a policy violation:** No website owner (Amazon, Gmail, ServiceNow) wants third-party bots scraping via APIs. Result: Bot checks, CAPTCHAs, blocks.
2.  **Vision Agents are guesswork:** OpenAI Operator, Anthropic Computer Use, Microsoft CUA see the screen and guess where to click. 70% failure rate in real tasks.
3.  **You still do the same thing every day:** Open browser → Open Gmail → Check if anything needs attention → Open Docs → Update CRM. 60 mins of boring, repeatable work.

### The Solution: GOV-AIOS

GOV-AIOS (pronounced gov-ai-os) is not an AI agent in the cloud. It's a **Governance Layer on your OS**.

**TOP LAYER: Governed Workflow Definition**
You define the workflow deterministically, not with a prompt.

```yaml
# workflows/gmail-attention-check.yml
name: Gmail Attention Check
governance:
  abort_if_not_logged_in: true
  no_credential_bypass: true
  local_only: true

steps:
  - id: 1
    action: open_browser
  - id: 2
    action: check_precondition
    check: gmail.isLoggedIn
    on_fail: STOP_AND_REPORT
  - id: 3
    action: read_by_email
    filter: requires_attention == true
  - id: 4
    action: report
```

**MIDDLE LAYER: Governance & Policy Engine**
1.  **Validate Preconditions:** Is logged in? Is allowed?
2.  **Enforce Policy:** Do not proceed if not logged in. No credential breach. Local-only.
3.  **Deterministic Executor:** Step-by-step, predictable, no assumptions.

**EXECUTION LAYER: Local Desktop Control**
- Uses OS Accessibility APIs (like Vercel agent-desktop) — not pixel screenshots
- Runs 100% locally on Windows / macOS
- Read-only unless explicitly authorized

**BOTTOM FLOW:** Define → Govern → Check → Execute Locally → Report
> Golden Rule: If precondition fails, stop and report — do not try to login or bypass.

---

### Why This is Different

| | API Automation | Cloud Vision Agents | GOV-AIOS |
| :--- | :--- | :--- | :--- |
| **How it works** | Hits unofficial APIs | Sees screen, guesses click | Uses your own logged-in session locally |
| **Policy** | Violates ToS, blocked | Risky, can bypass logins | Compliant, aborts if not logged in |
| **Determinism** | Deterministic but blocked | Non-deterministic | 100% deterministic |
| **Data** | Leaves machine | Screenshots to cloud | Stays on laptop |

### Quick Start (PoC)

```bash
git clone https://github.com/your-org/gov-aios
cd gov-aios
npm install
npx agent-desktop --init
npm run gov:run -- workflows/gmail-attention-check.yml --mode governed
```

If Gmail NOT logged in → `ABORT: Precondition failed (gmail.isLoggedIn=false). No bypass attempted.`

### Naming

- **govos.net / govos.com** — Existing GovTech SaaS (Government OS). Collision.
- **GOV-AIOS** — **Gov**erned **AI** **OS**. New category. Clear, searchable, no collision.
  Suggested domains: `gov-aios.org`, `govaios.dev`, `gov-aios.ai`, `gov-aios.com`

### Roadmap

- [ ] v0.1 - Gmail Attention Checker PoC
- [ ] v0.2 - GWDL YAML parser + Policy Engine
- [ ] v0.3 - Amazon Order Check vs API blocking
- [ ] v1.0 - Paper: Beyond Vision-Based Agents: GOV-AIOS

### License

MIT — Your Laptop, Your Rules.
