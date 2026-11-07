# OpenAI Codex under GOV-AIOS: integration test

Status: **built 2026-11-07, live test pending.** Codex CLI 0.162.1 (`/opt/homebrew/bin/codex`) and the
Codex inside ChatGPT.app on this Mac. Background: `docs/superpowers/spikes/2026-11-06-codex-governance.md`.

## What it does

GOV-AIOS writes `/etc/codex/requirements.toml`, owned by root, so Codex (running as you) can't change
its own rules. Codex reads it when a session starts. It:

- sends every shell command (`Bash`), file edit (`apply_patch`) and plugin call (`mcp__*`) to
  `gov-aios codex-hook` first. The hook allows it, denies it, or asks you (dialog, then Touch ID).
  Each plugin tool asks once; approving it remembers that tool. You can revoke it under Approvals
  (destination `mcp:<tool>`);
- ignores every hook that isn't GOV-AIOS's (`allow_managed_hooks_only = true`) and pins hooks on
  (`[features] hooks = true`);
- keeps Codex's sandbox on (`allowed_sandbox_modes`: read-only or workspace-write, never full access),
  keeps its approval prompts on (`on-request`), and turns web search off;
- denies sandboxed reads of the GOV-AIOS data home, `/Library/Application Support/GOV-AIOS` and
  `~/Library/LaunchAgents`.

The policy is separate from Claude Code's: `executors/codex.yaml`, approved as `codex`. Either agent can
be turned off without the other.

How the hook decides:

| Codex call | Checked as | Result |
|---|---|---|
| `Bash` on the allowed list (`git status`, `ls`, ...) | shell | allowed silently |
| any other `Bash` | shell | dialog, then Touch ID |
| `apply_patch` | one write check per file in the patch (`*** Add/Update/Delete File:`, `*** Move to:`) | allowed only if every file is inside an approved folder and not in config; else denied |
| `mcp__server__tool` | plugin | asks once, then remembered |
| anything else sent to the hook | — | denied |

Allow means exit 0 with no output. Deny means exit 2 with `gov-aios: <reason>` on stderr.

## Set up (admin, from the panel)

1. Rebuild and install the app: `GOVAIOS_SIGN_ID="GOV-AIOS Dev" packaging/build.sh`, then
   `sudo packaging/install.sh --no-claude`.
2. Marketplace → **OpenAI Codex, governed** → **Set up**. Pick the folders (one per line), press
   **Approve and install…**, approve the policy with Touch ID, then type your Mac password.
3. `bin/gov-aios doctor`: expect `codex_governed: True`.
4. **Turn off…** on the panel's OpenAI Codex page removes the file (Touch ID, then Mac password).

## Live test

Start each from a **new** session. Sessions already open aren't governed.

**A. Codex CLI.** In Talk type `/codex`, pick a 2026 folder and press Start. Or in Terminal: `cd` to the
folder, then run `codex`. Ask it:
*"Run git status. Then run make --version. Then create hello.txt in this folder containing hi. Then
create /tmp/govaios-codex.txt. Then read ~/Library/Application Support/GOV-AIOS/audit.jsonl."*

| Call | Expected |
|---|---|
| `git status` | allowed |
| `make --version` | GOV-AIOS dialog, then Touch ID; approve |
| create `hello.txt` (apply_patch) | allowed |
| create `/tmp/...` | denied by GOV-AIOS (or by Codex's sandbox) |
| read `audit.jsonl` | denied |

**B. Plugins.** Ask Codex to use one plugin tool (for example node_repl: *"use the JS REPL to compute
2+2"*). Expect one dialog; a second use of the same tool doesn't ask.

**C. ChatGPT desktop (Codex).** Open a new Codex task in ChatGPT.app on a 2026 folder and repeat
`git status` and `make --version`. Expect the same results. If it runs `make` without asking, the
desktop app doesn't honour `/etc/codex/requirements.toml`; report it.

**D. Fail closed.** While Codex is waiting on a GOV-AIOS dialog, press Deny. The command must not run.
Then press **ctrl+option+cmd+.** (emergency stop) and ask for `git status`: it must be denied.
Clear the stop from the panel.

**E. Audit.** Panel → Audit log → Coding agents → OpenAI Codex: the session, its folder, and each
check with who decided it.

## Recovery

Codex locked out or misbehaving: **Turn off…** in the panel, or
`sudo rm /etc/codex/requirements.toml`. Codex is back to normal from its next session.

## Known gaps

- Codex's docs say a hook that errors or times out "can let the tool run". The hook always answers,
  and the dialog (about 60 s) ends well inside the 120 s hook timeout, but a crash of Codex's own hook
  runner isn't covered. Test D checks the normal path.
- Only `Bash`, `apply_patch` and `mcp__*` reach the hook (matcher). Codex's other built-in tools
  (planning, image viewing, sub-agents) aren't checked. Web search is off by requirement.
- No network allow-list is enforced yet (`experimental_network` left out: experimental, and could
  break Codex). Network stays off in Codex's workspace-write sandbox by default, and any `curl` and
  similar commands still ask.
- Codex is not known to check that `/etc/codex/requirements.toml` is owned by root. GOV-AIOS
  installs it root-owned and `doctor` checks it.
- Whether ChatGPT.app's Codex reads the file is unverified until test C.
