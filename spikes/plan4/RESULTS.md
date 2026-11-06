# Plan 4 spike, part 1: sandbox nesting (2026-11-06)

`probe_sandbox_nesting.py`, run by the controller (plain Python, no TCC).

- DELIVER_PROFILE (`_BASE` + `(allow network-outbound (remote ip "localhost:8100"))` + `_DNS_FIX`)
  works as one sandbox: :8100 allowed; :8000, 1.1.1.1:443 and DNS denied; socketpair works.
- A fresh child inherits it, but `sandbox_init(RUN_PROFILE)` on top is **refused**
  ("sandbox initialization failed: Operation not permitted"). The child keeps :8100 (IPv4 and ::1).
- SIGTERM from parent to child works.

Result: plan A (deliver-sandboxed parent, run-sandboxed child) is impossible on this macOS.
Fallback: two app launches, one sandbox each (`run` under RUN_PROFILE, then `deliver` under
DELIVER_PROFILE); `deliver` sends only files from runs the audit log shows ending in `flow_end`.
Part 2 (TCC from a child) is moot.
