# Plan 2 spike: platform facts

Throwaway probes for plan 2 (admin authentication and isolation), decision log
`docs/superpowers/decisions/2026-11-05-admin-auth-isolation.md` rows 4, 6, 8,
10, 13, 14, 18, 22, 23, 27, 29. Results are log rows 38+. Probes that need
Touch ID, the screen, the admin's Chrome or sudo are in [RUNBOOK.md](RUNBOOK.md).

Run from the repo root with `.venv/bin/python` (needs
`pyobjc-framework-LocalAuthentication`, added to the project by Task 3).

| Probe | Row | Command | Expected | Observed (2026-11-05, Claude Code 2.1.318) |
| :- | :- | :- | :- | :- |
| `probe_latency.sh` | 13 | `spikes/plan2/probe_latency.sh` | median < 1 s | median 39 ms (20 runs, min 38, max 77) |
| `probe_sandbox.py` | 22 | `.venv/bin/python spikes/plan2/probe_sandbox.py run --drive` | sandbox_init ok; TCP and DNS fail; Unix sockets work | sandbox_init ok, TCP and child `curl` blocked, socketpair and named Unix socket work, bind blocked. **DNS still resolves** (also uncached names): FAIL |
| `probe_sandbox.py` | 22 | `... run --dnsfix --drive` | as above, DNS fails | all PASS: `DNS_FIX` blocks DNS |
| `probe_sandbox.py` | 22 | `... ui --dnsfix --drive` | serves on 127.0.0.1 | http.server on 127.0.0.1:0 serves an unsandboxed client; sandboxed outbound to localhost blocked; rest as `run` |
| `probe_sandbox.py` | 22 | `... run --exec --dnsfix --drive`, `ui --exec ...` | fallback works | `/usr/bin/sandbox-exec -p` gives the same results |
| `probe_sandbox.py` (app) | 22 | `spikes/plan2/build_probe_app.sh`; `open -W --stdout F --stderr F build/probe/dist/gov-aios-probe.app --args run --dnsfix` | works in a signed, hardened-runtime app | all PASS. TCC checks (`--tcc`): RUNBOOK §4 |
| one-off under `RUN_PROFILE + DNS_FIX` | 22 | see report | no-prompt pyobjc still callable | `AXIsProcessTrusted` returns (False, no grant), `NSWorkspace.runningApplications` works, `LAContext.canEvaluatePolicy` works |
| `probe_auth.py` | 4, 6 | `.venv/bin/python spikes/plan2/probe_auth.py` | both policies evaluable with Touch ID | biometrics True, device_owner True, biometryType 1 (Touch ID), lid open. Prompts: RUNBOOK §1 |
| `probe_lock.py` | 8 | `.venv/bin/python spikes/plan2/probe_lock.py 2` | keys present | `kCGSessionOnConsoleKey` == `"kCGSSessionOnConsoleKey"`, True; `CGSSessionScreenIsLocked` **absent** (not False) while unlocked. Lock/switch: RUNBOOK §2 |
| `probe_hotkey.py` | 10 | `.venv/bin/python spikes/plan2/probe_hotkey.py 0` (Terminal, no grants) | registers | status 0; also 0 under `RUN_PROFILE + DNS_FIX`; a second process gets -9878 (`eventHotKeyExistsErr`, exclusive flag). Firing: RUNBOOK §3 |
| `probe_chrome.py` | 23 | RUNBOOK §5 | one Chrome, page loads | admin |
| `probe_hook.sh` + `probe_mcp.py` | 14, 27 | headless `claude -p` in a scratch dir (below) | matcher `*` covers everything | fires for Bash, Read, ToolSearch, `mcp__probe__echo`, Agent, and the subagent's Bash (payload has `agent_id`, `agent_type`) |
| `probe_hook.sh` | 27, 28 | same | hook outside Claude's sandbox | hook reads a `sandbox.filesystem.denyRead` file; sandboxed `cat` of it gets "Operation not permitted" |
| `probe_hook.sh` | 14 | modes `block`, `crash`, `segv`, `hang` (timeout 5) | all block with `onFailure: "block"` | all four blocked (side-effect file absent); control without `onFailure`: crash lets the call run |
| sandboxed Bash `open` | 29 | `open -W -n <copy of gov-aios.app> --args selftest lines 1 --dev`; `open -g -j -a Calculator` | can or cannot | **cannot**: `kLSUnknownErr` -10810, "Couldn't communicate with a helper application" (docs: needs `sandbox.allowAppleEvents`, default false). Unsandboxed control works |
| managed-settings keys | 14 | docs + `claude -p --settings <json>` | every key exists | all exist; `Write(path)` deny rules are rejected (use `Edit`, which covers Write); see below |
| TCC after move | 18 | RUNBOOK §6 | grant follows | admin |

## Hook probe setup (row 14, 27)

Scratch dir (never the repo or the real data home) holding a copy of
`probe_hook.sh` and `probe_mcp.py`, `secret.txt`, `hello.txt`, a `mode` file,
and `.claude/settings.local.json`:

```json
{
  "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "<scratch>/probe_hook.sh", "timeout": 5, "onFailure": "block"}]}]},
  "sandbox": {"enabled": true, "failIfUnavailable": true, "allowUnsandboxedCommands": false,
              "filesystem": {"denyRead": ["<scratch>/secret.txt"]}}
}
```

Runs: `claude -p --model haiku --mcp-config <scratch>/mcp.json --allowedTools ... "<tiny prompt>"`
with `mcp.json` = `{"mcpServers": {"probe": {"command": "python3", "args": ["<scratch>/probe_mcp.py"]}}}`.
Blocking was checked with `touch ran-<mode>`: the file must not exist afterwards.

## Managed settings Task 8 emits (row 14)

Checked against code.claude.com/docs/en/settings-reference, /hooks, /sandboxing,
/permissions for Claude Code 2.1.318, and loaded without a warning by
`claude -p --settings`. Differences from row 14's wording:

- Permission deny rules: `Read(...)` and `Edit(...)` only. Claude Code warns that
  `Write(path)` "is not matched by file permission checks — only Edit(path) rules
  are"; an `Edit` deny blocked the Write tool in the probe.
- Absolute paths in permission rules need `//`; `~/` is home. Rules with spaces work.
- `allowedDomains` takes host names (optional `:port`), not URLs: Task 8 strips
  the scheme from the policy's `destinations`.
- `Read(...)` deny rules are also added to the sandbox `denyRead` by Claude Code;
  the explicit `denyRead` is kept for clarity.
- `enableWeakerNestedSandbox` is Linux-only; `false` is harmless.
- Not in row 14 but relevant: `sandbox.allowAppleEvents` (default `false`, keeps
  `open`/`osascript` out of sandboxed Bash; do not set it).

`allowedDomains` below comes from row 31's default destinations.

```json
{
  "allowManagedHooksOnly": true,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/Applications/gov-aios.app/Contents/MacOS/gov-aios hook",
            "timeout": 300,
            "onFailure": "block"
          }
        ]
      }
    ]
  },
  "permissions": {
    "disableBypassPermissionsMode": "disable",
    "deny": [
      "Read(~/Library/Application Support/GOV-AIOS/**)",
      "Edit(~/Library/Application Support/GOV-AIOS/**)",
      "Read(//Library/Application Support/GOV-AIOS/**)",
      "Edit(//Library/Application Support/GOV-AIOS/**)",
      "Read(//Library/Application Support/ClaudeCode/**)",
      "Edit(//Library/Application Support/ClaudeCode/**)",
      "Read(//Applications/gov-aios.app/**)",
      "Edit(//Applications/gov-aios.app/**)",
      "Read(~/.claude/**)",
      "Edit(~/.claude/**)",
      "Read(~/Library/LaunchAgents/**)",
      "Edit(~/Library/LaunchAgents/**)"
    ]
  },
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "enableWeakerNestedSandbox": false,
    "enableWeakerNetworkIsolation": false,
    "filesystem": {
      "denyRead": ["~/Library/Application Support/GOV-AIOS"]
    },
    "network": {
      "allowManagedDomainsOnly": true,
      "allowedDomains": ["github.com", "pypi.org", "files.pythonhosted.org"],
      "allowAllUnixSockets": false,
      "allowLocalBinding": false
    }
  }
}
```

## Sandbox profiles (row 22, amended by this spike)

`RUN_PROFILE` and `UI_PROFILE` in `probe_sandbox.py` are row 22 verbatim. DNS
goes to mDNSResponder over the Unix socket `/private/var/run/mDNSResponder`,
which `(allow network* (remote unix-socket))` lets through, so the
`com.apple.dnssd.service` mach-lookup deny does not stop it. Appending

```
(deny network-outbound (remote unix-socket (path-literal "/private/var/run/mDNSResponder")))
```

(`DNS_FIX`) blocks it; the architect decides the row-22 amendment.
