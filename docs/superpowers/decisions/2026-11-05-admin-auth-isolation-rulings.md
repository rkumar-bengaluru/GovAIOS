# Plan 2 (admin auth and isolation): controller rulings and live-test results

Rulings the controller made on the admin's behalf while executing the plan (subagent-driven).
The decision log (`2026-11-05-admin-auth-isolation.md`) stays the binding record; these fill the
gaps it left. Each: what was decided — why — cost if wrong.

## Rulings

1. **R1** Spike Task 1 split: automatic probes run by the implementer, admin-only ones in `spikes/plan2/RUNBOOK.md` — Touch ID, lock screen, keys and sudo are the admin's — none.
2. **R2** `approve`/`prove` keep `(ok, auth)`; a busy prompt lock returns `(False, "busy")` — keeps every caller's signature — one extra `auth` value.
3. **R3** `runstate.live_runs(home)` is the shared helper for stop, run GC and the hook — both tasks described it — none.
4. **R4** An autouse test fixture replaces `sandbox.apply`; only child-process tests apply a real sandbox — `sandbox_init` must never run in the pytest process — none.
5. **R5** Where the spike README's managed-settings JSON differs from amended row 14, row 14 wins — the log is the record — none.
6. **R6** Task 7 (pure policy) ran before Tasks 3-6 while runbook results were pending — no dependency — none.
7. **R7** Hook `build_request`: a missing Glob/Grep `path` is the payload cwd; any relative or `~` path is denied — denying beats guessing — an occasional false deny.
8. **R8** Default Claude tool categories follow row 33 — the log over the brief — a tool list tweak.
9. **R9** Policy-only request entries record `auth=null` (never asked); `"none"` means a prompt that proved nothing — distinguishes the two — vocabulary only.
10. Chrome launch follows amended row 23 (run the Chrome binary while Chrome runs; 10 s wait, then kill and Stop; not running → Stop) — the spike disproved `open -n` — rework of the profile handoff.
11. No `sandbox-exec` fallback — `sandbox_init` accepted both profiles — add later if an OS update refuses them.
12. Hook calls that exit 2 (fail-closed) are not audited — the spec audits decided calls only — forensics gap; add a "blocked" entry later.
13. `claude-settings` also refuses a root inside a protected path — never a useful root — admin picks another root.
14. A Bash ask whose command contains secret-like values is denied without a prompt, audited redacted — the admin must see exactly what they approve — the admin reruns without the secret.
15. `register_run` before preflight, `unregister_run` in `finally` — a stop in the gap would miss the run — none.
16. `--dev` gets **no** exemptions (reversed an earlier ruling; row 28) — the log says "No exemptions" — none.
17. Non-dev run preflight includes doctor's identity checks; managed settings are not a run precondition — row 24; row 34 installs them last — none.
18. `dump` proof reason is row 29's "print the open Chrome page".
19. `sandbox.apply` is the first statement after argument parsing — a resolver connection opened earlier survives the sandbox — a network hole if moved.
20. Task 11 split: final whole-branch review and its fixes ran before the admin's attended steps, so the admin tested final code once — none.
21. Data-home hand-back chown done by file descriptor with no-follow opens — admin's plan-review request without path races — install fails closed on odd entries.
22. Accepted: admin-writable `/Applications` races and the checkout-under-sudo trust boundary; TCC designated requirement + doctor pin identity — a signed pkg is future work.
23. Final review: C-1, I-1..I-3, M-1..M-19 fixed in one dispatch; **M-4** (proof channel per call site) deferred to the remote-trigger plan (row 35) — ~9 call sites to refactor later.
24. Residual round (I-N1, m-2, m-3) verified by tests and diff read instead of another full review — matcher widening with tests — one more review later.

## Admin decisions (2026-11-06)

- **Touch ID on every run start stays**, no time window. Remote triggering (row 35) adds proof
  channels later (OTP, verified paired app); every run still carries proof from the admin.
- **Claude Code integration live test deferred** until GOV-AIOS is stable:
  `docs/claude-code-integration-test.md`.
- `strictPluginOnlyCustomization: ["mcp"]` kept (no user MCP servers configured).
- **Flow improvements later:** browser back-and-retry after a wrong page, close the flow's window
  at the end, the morning inbox flow.

## Live test (Task 11 Steps 4-5, 2026-11-06): passed

Install, TCC carried over across reinstalls (designated requirement), powers review, doctor,
normal run (one Touch ID), emergency-stop hotkey, refusal while STOPPED, resume, screen lock,
audit UI login (single-use link), revoke site → site asked again, revoke flow → flow approval
asked again, `verify-audit` OK (603 entries).

Bugs found live and fixed:

- `5ccf31c` Audit UI revoke never applied: `Referrer-Policy: no-referrer` makes Chrome send
  `Origin: null` on same-origin form POSTs → 403. Now `same-origin`.
- `e920712` A click hit an ad that had moved over the job link (same Chrome window), and Chrome
  left the approved destinations. Now the element under the click point must be the target or
  inside it.
- `3358c3f` Buttons say "Revoke flow" / "Revoke site" (the admin twice revoked the site row);
  click refusals print fixed text (`STOPPED: input refused: ...`) instead of `ERROR: RuntimeError`.
- `78e6189` Refusal messages printed twice.

Open, not fixed:

- A click that navigates to an unapproved origin is caught only by the post-click page check;
  there is no origin check after clicks.
- `install.sh` prints a harmless `Bootstrap failed: 5` when its first bootstrap try races the
  old guard's exit.
- Not run live: Touch ID cases B/C (lid closed, lockout), fast user switching, the hotkey under
  secure input, a stop cancelling a waiting prompt.
- Build: `packaging/build.sh` signs ad hoc unless `GOVAIOS_SIGN_ID="GOV-AIOS Dev"` is set; an
  ad-hoc build loses the TCC grants (install's signer check refuses it).
