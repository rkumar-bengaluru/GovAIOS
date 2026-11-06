# Plan 4 (delivery, first app JobLens): controller rulings and open items

Rulings the controller made while executing the plan subagent-driven (Tasks 1-6). The spec
(`specs/2026-11-06-joblens-delivery-design.md`) and plan stay the binding record. Each: what was
decided — why — cost if wrong.

## Rulings

1. `deliver` parser goes right after `run` (test_cli compares parser order) — none.
2. Shim tests create the flow file (the shim only makes existing paths absolute) — none.
3. Job files open with `O_NONBLOCK` as well as `O_NOFOLLOW` (a FIFO named `x.json` hung the batch) — none.
4. The racy stop-flag test was fixed in the same round — none.
5. The shim clears the pid file after each launch (a stale pid could be signalled after reuse) — none.
6. Small final-review items were folded into the single fix wave (Unicode `Cc` control chars, URL
   without host dropped, `from` must be under the data home, `opid` cleared, "1 file", two refusal
   tests) — a slightly larger fix diff.

Beyond the plan, accepted on review: `deliver_batch` returns an extra `unreachable` count; two
existing fake Runners in `test_cli` gained `deliver = None`; the `run()` helper in
`test_engine_audit` strips the real flow's `deliver:` line from its copy.

## Final review (fixed in 0b909b5)

- An emergency stop while a request is in flight is now audited (`delivery`, outcome `stopped`);
  the file stays pending and a resend gets JobLens's 200 duplicate.
- The sender ignores proxy settings (environment and macOS system proxies) and never follows
  redirects.
- The audit page shows `flow`, `response_code`, `listing_id`, `file_hash`.

## Open, not fixed (judged safe to wait)

- A stop landing after JobLens answered but before the audit write leaves no entry (tiny window).
- Overlap is refused only from the `deliver` side (a `run` started after deliver's check is not
  refused); all files are read before any send.
- A truncated 409/5xx body is recorded with reason `unreachable` (outcome still `retry`).
- `last_run_finished` reads the whole audit log without checking signatures (forging needs the same
  access that could already edit `jd_selected`).
- `GOVAIOS_APP` in `bin/gov-aios` is an unconditional test override (it can only start what the
  caller could start).
- Not tested: Ctrl-C during the second launch; a redirect answer; `Deliveries` under concurrent
  writers; title/company over 500 and url over 2000.
- `check_block` raises `TypeError` (not `ValueError`) on non-string `to`/`from` (still a fail-closed
  error at load); a corrupt `deliveries.json` raises (fails closed).
