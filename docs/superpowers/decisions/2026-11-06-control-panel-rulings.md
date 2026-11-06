# Control panel — rulings made during the build

Plan: `docs/superpowers/plans/2026-11-06-control-panel.md`. Each line: what was decided — why — cost if wrong.

1. `make_server` takes `session=` and `tick_s=` (None = no ticker) and exposes `panel.tick()` — test seam the plan named only by its tests — cheap rename.
2. Authenticator state lives at `<home>/totp.state` (0600, no-follow) and is deleted with the secret on reset — plan said "beside the secret" — low.
3. A corrupt, symlinked or unreadable `totp.state` fails closed (code entry locked) — hardening — a corrupt file blocks codes until reset.
4. The run ticket carries the session id; the run's `run_start` audit records it — plan had no carrier — small refactor.
5. **For the admin:** a process running as you that can write `<home>/tickets` can mint a ticket for an *approved* app and start it without Touch ID. Same trust boundary as the 30-minute session; mid-run governance prompts still apply. Fix belongs with the Secure Enclave/Keychain work — if wrong, local malware could start approved flows silently.
6. Panel approvals audit executor `gov_runner` (the packaged app's executor), not the dev default — audit label only.
7. Server shutdown audits `session_end` reason `server_stop` (distinct from End session) — label only.
8. Opening a session while emergency stop is on is refused: "Emergency stop is on. Clear it first." (audited, reason `emergency_stop`) — the next tick would end it anyway.
9. Ending a session deletes the run's unused ticket and SIGTERMs a late-appearing pid — so a slow cold start cannot outlive the session.

Accepted residuals: lock polled every 1 s (a sub-second lock/unlock can be missed); no spoken result when the server itself stops; SIGTERM landing in a few-bytecode window around the handler can skip `server_close`; an app SIGTERMed during cold start exits 70 without `flow_end`; "Approve…" twice opens one dialog (second is "busy"); deferred minors in tickets/TOTP housekeeping.

## After live test 1

10. No sandboxed process can start an app with `open -a` (bisected: even `(allow default)` fails silently). Admin chose: a helper is split off (`fork`) before the sandbox; it has no socket and no web server and accepts only run (a `*.yaml` directly in the flows folder + a 64-hex ticket that exists), stop, and `say -- <text≤300>`. It stops its run and exits when the panel goes away. The web-facing panel stays sandboxed.
11. For the panel, the data folder is resolved (and created if missing) before the sandbox is applied, because the helper needs it — no network involved.
12. `say` itself works under the sandbox; it is routed through the helper anyway (one path, speaker output under the sandbox untested).
13. Restyled to the journey-v2 mockup with CSS only; left out: web fonts, the JS ring, the Emergency stop and Hold to talk buttons (no routes yet), the 6-box code input.
