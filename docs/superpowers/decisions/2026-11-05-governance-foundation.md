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
| 7 | 2026-11-05 | 8 | The plan says `run`, `dump` and `doctor` require the app unless `--dev`. Must `doctor`? | Confirmed: only `run` and `dump` call `require_app`. `doctor` is read-only, runs anywhere, still accepts (and ignores) `--dev` so Task 8's test and Task 9 Step 2 work, and exits 1 when `bundle_id` is not `com.govaios.cli`, so running outside the app is reported, never hidden | architect | Plan Task 1b (`main(["doctor"])` test), Task 8, Task 9 Step 2; transparency |
| 8 | 2026-11-05 | 3 | `UF_APPEND` makes pytest tmp dirs undeletable. Where does cleanup go? | Confirmed: the autouse `tests/conftest.py` fixture clears flags (`os.chflags(p, 0)`) on teardown, walking only that test's tmp `GOVAIOS_HOME`, never any other path. Production code still sets `UF_APPEND` | architect | Plan Global Constraints (autouse home), Task 3 Step 4 |
| 9 | 2026-11-05 | 5 | Task 5 runs the Himalayas flow "with `count: 1`", but the flow hardcodes 5 and checks the google.com account first | Confirmed, amended: tests copy `flows/` and `pages/` into tmp and set `count: 1` in the copy. Privacy amendment: the copy also replaces `browser.account` with `test@example.invalid`, and the fake `google_home` tree's account button uses that, so the admin's real email never enters fixtures or test audit logs. Shipped flow files stay unchanged | architect | Plan Task 5; spec principles table ("Privacy first") |
| 10 | 2026-11-05 | 1b | Hardened runtime + ad-hoc signing fails to load the bundled Python.framework ("different Team IDs"). Add `disable-library-validation`? | Option (a), tightened. Keep `--options runtime` always. `build.sh` adds `packaging/entitlements.plist` only when `GOVAIOS_SIGN_ID` is not a `Developer ID Application:` identity, because ad-hoc and self-signed dev certs both lack a Team ID; with Developer ID it signs without entitlements and keeps library validation on. Asserts in `build.sh` after signing: the plist holds exactly one key, `com.apple.security.cs.disable-library-validation` (never `allow-dyld-environment-variables`, `get-task-allow` or `allow-unsigned-executable-memory`); a Developer ID build's `codesign -d --entitlements -` output has no `disable-library-validation`, or the build fails; a dev build prints `WARNING: library validation off (dev signing)` to stderr. Rejected (b): with no hardened runtime, DYLD injection and debugger attach are open, which is weaker than (a). Rejected (c): it also weakens release builds | architect | Spec 5.1 ("no bypassing"), spec 9.1 (ad-hoc day 1), plan Global Constraints (`GOVAIOS_SIGN_ID`); safer-option rule |
