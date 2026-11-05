# Decision log: governance foundation

Decisions made while building
`docs/superpowers/plans/2026-11-05-governance-foundation.md`.

**Source** says who decided:
- **admin**: the admin decided it directly;
- **architect**: an architect agent decided it on the admin's behalf,
  from the design, the plan, and the earlier admin decisions.

The admin can overturn any architect decision.

| # | Date | Task | Question | Decision | Source | Basis |
| :- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | 2026-11-05 | all | Where does the work go? | A separate branch, `feat/governance-foundation`; `main` untouched | admin | "use a seprate branch" |
| 2 | 2026-11-05 | 1b, 9 | PyInstaller and pyobjc are brittle. How to package? | `--onedir` inside the `.app`, never `--onefile`; hidden imports for objc, AppKit, Foundation, ApplicationServices, Quartz; packaging tested early (Task 1b) | admin | Review suggestion 1 |
| 3 | 2026-11-05 | 1b | How should the shim's stdout and stderr work outside a TTY, and with races? | Per-invocation `mktemp` files for stdout, stderr, and the exit code, passed with `open --env`; streamed with `tail -f`; no shared `last_exit` | admin | Review suggestion 2 |
| 4 | 2026-11-05 | 6 | Is the in-process network guard enough? | No: it's marked a shortcut that a C extension can bypass. Tests use a credential-free `GOVAIOS_HOME`, and the OS-level sandbox block comes in plan 2 | admin | Review suggestion 3 |
| 5 | 2026-11-05 | 7 | The token in the URL ends up in browser history | OK for localhost on day 1. Add `Cache-Control: no-store` (and `Referrer-Policy: no-referrer`); marked to be replaced by Touch ID in plan 2 | admin | Review suggestion 4 |
| 6 | 2026-11-05 | all | Who answers implementer doubts? | An architect agent represents the admin and logs each answer here. macOS permission grants and approval dialogs stay with the admin | admin | "have an architect agent represent me for doubts and log my decisions" |
