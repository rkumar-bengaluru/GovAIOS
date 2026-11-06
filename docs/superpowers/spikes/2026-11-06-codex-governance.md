# Spike: governing OpenAI Codex CLI with GOV-AIOS (2026-11-06)

Research only. Codex here: `/opt/homebrew/bin/codex`, codex-cli 0.162.1 (arm64 binary under `@openai/codex-darwin-arm64`).
Local tests used an isolated `CODEX_HOME` under the session scratchpad (`.../scratchpad/codex-spike/home`). No login, no model call, nothing in `~/.codex`, `/etc` or `/Library` was changed. `~/.codex/auth.json` was not touched.
Docs (the old developers.openai.com URLs 308-redirect here): https://learn.chatgpt.com/docs/hooks , .../docs/enterprise/managed-configuration , .../docs/config-file/config-advanced .

## Short answers

1. Pre-check: **yes, mostly.** Stable `hooks` feature (`codex features list`: `hooks stable true`). `PreToolUse` command hooks get JSON on stdin and can deny.
2. Audit: `PostToolUse` hook (per tool call, with `tool_response`) beats `notify` (turn-level only). OTel `codex.tool_decision` / `codex.tool_result` is a third source.
3. Managed lock: **yes.** `/etc/codex/requirements.toml` (+ macOS MDM `com.openai.codex`), with `allow_managed_hooks_only`.
4. Sandbox/approval: lockable via `allowed_sandbox_modes`, `allowed_approval_policies`, `experimental_network`.
5. MCP: allowlist lockable in requirements; hooks also match `mcp__server__tool` names.

## Claude Code vs Codex

| Point | Claude Code today (repo) | Codex equivalent | Evidence | Confidence |
|---|---|---|---|---|
| Pre-check | Managed `hooks.PreToolUse` matcher `*` runs `gov-aios hook`; stdin has `tool_name`, `tool_input`, `cwd`; stdout `hookSpecificOutput.permissionDecision`; exit 2 + stderr blocks; `onFailure: block` (govaios/hook.py, hook.py `managed_settings`) | `[hooks]` in config.toml / hooks.json, event `PreToolUse`. Stdin: `session_id, transcript_path, cwd, hook_event_name, model, turn_id, tool_name, tool_use_id, tool_input, permission_mode`. Deny = `hookSpecificOutput.permissionDecision:"deny"` + `permissionDecisionReason` (legacy `decision:"block"`), or exit 2 with stderr. `ask` NOT supported (GOV-AIOS never returns ask to Claude anyway; its own dialog resolves it, so this fits). Matches `Bash` (shell), `apply_patch`/`Edit`/`Write`, `mcp__*`, other local function tools. | https://learn.chatgpt.com/docs/hooks ; binary strings list events PreToolUse, PermissionRequest, PostToolUse, ... and "failed to parse hook event input" | High for contract (near-identical to Claude's). Medium for fail-closed behaviour on hook crash/timeout: docs do not say; must be tested with a login. |
| Approval-ish gate | Hook does Touch ID dialog itself for `ask` | Also a `PermissionRequest` event exists; but the PreToolUse path is enough | docs | Medium |
| Audit | Hook appends `request` entry (allow/deny, approver, redacted command) to AuditLog; there is no post-action record for Claude | `PostToolUse` hook (gets `tool_response`; can only replace feedback, not undo). `notify = [prog]`: one JSON argv, only `agent-turn-complete` with `type, thread-id, turn-id, cwd, input-messages, last-assistant-message`. OTel `[otel]` events `codex.tool_decision`, `codex.tool_result` (exporter none/otlp-http/otlp-grpc). | config-advanced doc | High for hooks/notify; Medium for OTel |
| Managed lock | `/Library/Application Support/ClaudeCode/managed-settings.json` (root-owned, `allowManagedHooksOnly`) | `/etc/codex/requirements.toml` (Linux/macOS), macOS MDM domain `com.openai.codex` key `requirements_toml_base64`; `[hooks] managed_dir=...` + `allow_managed_hooks_only = true` ignores user/project/session/plugin hooks. Also `/etc/codex/managed_config.toml` and `/etc/codex/config.toml` layers (binary strings confirm all three paths; `/etc/codex` does not exist on this Mac today). | managed-configuration doc; `strings` on the binary | High on paths and keys. Medium on file-ownership checking: docs give none, so assume Codex does not verify root ownership; the install must make it root:wheel 0644. |
| Precedence | Managed settings beat user/project | Requirements (low to high): system file, cloud bundle, legacy managed_config, MDM. Requirements are constraints users cannot override; conflicting local value falls back to a compatible one with a notice. Defaults (config): MDM `config_toml_base64` > `managed_config.toml` > user `config.toml`; `-c` CLI overrides sit under managed layers. Hooks/rules/filesystem merge field-specifically. | docs | High |
| Sandbox | `sandbox.enabled`, `failIfUnavailable`, no unsandboxed commands, `denyRead` of protected paths | Modes `read-only`, `workspace-write`, `danger-full-access`; `allowed_sandbox_modes` in requirements. Named permission profiles (`allowed_permission_profiles`, `default_permissions`, filesystem+network). Local test: `codex sandbox -- /usr/bin/touch <outside>` gave "Operation not permitted" (Seatbelt works, no login needed). `.git`, `.codex`, `.agents` stay read-only in workspace-write. | docs; local run | High |
| Approval policy | `permissions.disableBypassPermissionsMode` | `approval_policy`: `on-request`, `never`, or granular table; `untrusted` reported no longer supported by docs (check). `allowed_approval_policies`, `allowed_approvals_reviewers` in requirements. | docs | Medium (docs and old example list disagree on `untrusted`) |
| Network | `sandbox.network.allowManagedDomainsOnly`, `allowedDomains` = policy destinations; drift check vs policy | Off by default in workspace-write (local test: `curl https://example.com` inside `codex sandbox` -> "Could not resolve host"). Enforced domain policy via `experimental_network` in requirements (binary has `allowed_domains`, `denied_domains`, `managed_allowed_domains_only`, `allow_unix_sockets`, `allow_local_binding`, a `codex_network_proxy`). Web search: `allowed_web_search_modes`. | strings; local run | Medium: key shape of `experimental_network` is undocumented in what I fetched and marked experimental |
| Extensions | `enableAllProjectMcpServers:false`, `strictPluginOnlyCustomization` | `[mcp_servers]` allowlist in requirements (name AND identity must match); `[features]` table in requirements; plugin marketplace sources restrictable; `rules.prefix_rules` with `prompt`/`forbidden` (never `allow`) | managed-configuration doc | High |

## What GOV-AIOS would have to write

All as root via a new `packaging/install.sh` step (admin sudo, same pattern as the ClaudeCode managed-settings swap: temp file, chown root:wheel, 0644, validate, `mv`).

1. `/etc/codex/requirements.toml` (generated by a new `govaios/codex.py` beside hook.py, from the same executor policy; `gov-aios codex-settings` mirrors `claude-settings`):
   - `allowed_sandbox_modes = ["read-only","workspace-write"]` (drop `danger-full-access`)
   - `allowed_approval_policies = ["on-request"]` (never `never`)
   - `[hooks] managed_dir = "/Applications/gov-aios.app/Contents/Resources/codex-hooks"` and `allow_managed_hooks_only = true`; a `PreToolUse` (matcher `*`) command `gov-aios codex-hook` and a `PostToolUse` one for audit
   - `experimental_network` with policy destinations; `allowed_web_search_modes = ["disabled"]` or cached
   - MCP allowlist empty; protect `.codex` writes
   - `[rules] prefix_rules` forbidden entries for GOV-AIOS paths (cheap defence in depth)
2. Code: `gov-aios codex-hook` adapting `hook.py`. Same `_decide` flow; map `Bash` -> command category, `apply_patch` -> write with paths parsed from the patch, `mcp__*` -> deny unless allowlisted. Output is already the same JSON shape; reuse `Block` and exit 2. Reuse AuditLog with `ID = "codex"`, its own flow approval and drift check (requirements.toml vs policy), as done for `claude_code`.
3. Optional: MDM profile for `requirements_toml_base64` (highest precedence) if the Mac is managed; otherwise the /etc file.
4. Doctor check: `/etc/codex/requirements.toml` exists, root-owned, digest matches policy.
5. Tests: unit tests on the adapter with canned stdin payloads; one live test later with a logged-in Codex (not run here).

Note: the user's own `notify` in `~/.codex/config.toml` is already used by Computer Use ("turn-ended"). `notify` is a single slot, so do not use it for audit; hooks do not conflict.

## Gaps (Codex governed less tightly)

- Docs state tool hooks are "a useful guardrail, not a complete enforcement boundary". Hosted tools (`WebSearch`) are not hooked; use `allowed_web_search_modes`.
- No `ask` verdict, so approvals must be GOV-AIOS's own dialog (already the design). `PermissionRequest` semantic not explored.
- `PostToolUse` cannot undo; audit is after the fact. `notify` is turn-level only.
- Hook failure mode (crash, timeout) fail-open vs closed is undocumented; Claude has `onFailure: block`. Needs a live test. Mitigation: `allowed_approval_policies` and sandbox still hold, and the hook command can be a tiny wrapper that exits 2 on any error (as hook.py does).
- `/etc/codex` is outside `/Library`; no evidence Codex verifies root ownership. A local admin account can still edit it; the single-admin-per-laptop model already accepts that. Codex Desktop app / app-server (`codex app-server`, `agents` daemon) should read the same layers but is not verified.
- Non-managed hooks need `/hooks` trust review; only moot with `allow_managed_hooks_only`.
- `experimental_network` and permission profiles are experimental/beta, schema may move between versions; pin and check in doctor.
- Project `.codex/` layers are loadable when trusted; managed-only hooks plus `.codex` write protection cover this.
- Version drift: this is 0.162.1; docs fetched are current, not version-pinned. Not verified against the openai/codex source.

## Recommendation

Proceed. Codex can be pre-checked with the same hook contract. Build a `codex-hook` adapter reusing `hook.py`'s decision path, ship it via a root-owned `/etc/codex/requirements.toml` with `allow_managed_hooks_only` plus sandbox/approval/network locks. Before shipping, run one logged-in live test covering: hook deny actually stops `Bash` and `apply_patch`; hook crash/timeout behaviour; requirements override of `~/.codex/config.toml` and `-c` flags; `experimental_network` key shape. Treat Codex governance as "guardrail plus sandbox" and say so in the panel.
