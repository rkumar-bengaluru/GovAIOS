# GOV-AIOS: delivery and the first app (JobLens) — Design

Date: 2026-11-06. Status: draft for admin approval.
Builds on: governance-layer spec (`2026-11-05-governance-layer-design.md`), plan 2
(`2026-11-05-admin-auth-isolation-design.md` and its decision log). Spike:
`spikes/plan4/RESULTS.md`. JobLens contract: `JobLens/docs/external_agent_integration.md`
(in the JobLens repo, read 2026-11-06).

## 1. Intent

The first GOV-AIOS automation that saves the admin time: one command takes today's Himalayas
matches and puts them, scored, into JobLens's **Shortlisted** tab (or **Dropped** with a
reason). Today the flow stops at writing JSON files in `jd_selected/`; the admin then has to
move them by hand.

It also introduces two lasting ideas:

- **Delivery** (admin): `deliver:` is where a flow's output goes after the run. Each flow names
  a *target*; the target knows how to send. JobLens is HTTP; a later morning-brief target could
  be speech (TTS). Only `joblens` is built now.
- **App** (admin's name): a GOV-AIOS app is a flow + the page schemas it uses + its delivery
  target, approved as one unit. The first app is **JobLens** (flow `himalayas_job_vetting`).
  Apps are **data only** (YAML GOV-AIOS reads), never code GOV-AIOS runs: an app cannot do
  anything the governance layer does not allow. Targets, and the code that sends, live inside
  GOV-AIOS.

## 2. Goals, non-goals, anti-goals

**Goals**
1. `bin/gov-aios run flows/himalayas_job_vetting.yaml`: one command, one Touch ID; collect, then
   deliver to JobLens.
2. Each saved job reaches JobLens once; retries after a busy answer (409, 429) happen on a later
   delivery, never in a loop.
3. Every delivery is audited without content.

**Non-goals (this design)**
- The `speak` target, or any target besides `joblens`.
- Packaging, installing or listing apps; "app" is the name and the concept, no new file format.
- Extracting `location` / `posted_on` (optional in JobLens).
- Polling JobLens for scores or showing them.
- Flow improvements from the backlog (back-and-retry, closing the window).

**Anti-goals (a failure even if it works)**
- Any network in the run sandbox (spec §9.2.5). The spike showed a run-sandboxed child cannot
  live under a network-allowing parent, so the run and the delivery are **separate processes**.
- A flow file choosing where data goes (an address, a port, a URL).
- Job text in the audit log.
- Breaking what exists: flows without `deliver:` (the morning brief) run exactly as today, with
  unchanged approvals; the 364 tests keep passing.

## 3. Constraints

- Network for delivery: outbound TCP to `127.0.0.1:8100` only, by a new `DELIVER_PROFILE`
  (spike-verified string): `_BASE + ' (allow network-outbound (remote ip "localhost:8100"))' + " " + _DNS_FIX`.
  No inbound, no DNS, no other port. `sandbox.apply` stays the first call in `main()` (ruling 19).
- JobLens endpoint (prod): `POST http://127.0.0.1:8100/api/discover/listings`, JSON; unknown
  fields are a 400.
- Standard library only (`urllib.request`); no new dependency.
- Plan 2 rules hold: Touch ID on every run start; STOPPED and screen lock refuse; revoke works.

## 4. How it works

### 4.1 Flow file (no breaking change)

`steps:` is untouched. Two additions inside `workflow:` of the Himalayas flow only:

```yaml
  permissions:
    allow: [..., deliver]          # Rule 9: unlisted = denied
  deliver: { to: joblens, from: jd_selected, source: Himalayas }
```

- `to`: a target name GOV-AIOS knows; unknown → the flow is refused at load.
- `from`: must equal a `write_json` directory of this flow (under the data home).
- `source`: the JobLens `source` label (1–50 chars, no control characters).

The file changes, so its approval hash changes: the Himalayas flow is approved once more. The
flow approval dialog adds "delivers to: joblens (local)". The morning brief file does not change.

### 4.2 One command, two launches

`bin/gov-aios run <flow>`:

1. Launches the app with `run <flow>` exactly as today (run sandbox, no network).
2. If the run process wrote `deliver` to a new shim file `GOVAIOS_NEXT_FILE` (it does so only
   when the flow has a `deliver:` block **and** the run ended with `flow_end`), the shim launches
   the app again with `deliver <flow>` and streams its output the same way.

The run process (trusted, signed) makes the decision; the shim only reads the file. Otherwise
the shim behaves as today; its exit code is the run's, or the delivery's if the run succeeded.

### 4.3 `gov-aios deliver <flow>`

New subcommand, sandboxed with `DELIVER_PROFILE` (`PROFILES["deliver"]`). It never uses
Accessibility, input, the screen or Chrome. It can also be typed on its own (e.g. after a 409),
so it checks everything itself and trusts nothing from the shim:

1. Preflight: registered as a run (so the emergency stop ends it); refuse if STOPPED, screen
   locked, guard not running, or not the signed app (`--dev` gets no exemptions, row 28).
2. The flow is approved for its current hash (`flow_ok`), has a `deliver:` block, and `deliver`
   is in its `allow` list; else refuse.
3. The **latest** run of this flow in the audit log ended with `flow_end`; else refuse
   ("last run did not finish").
4. First contact: if `destination_ok(flow_id, "joblens")` is false, ask (dialog, then Touch ID):
   "Flow '<id>' wants to deliver its saved jobs to JobLens (local, 127.0.0.1:8100) for the first
   time. Approve?" Remembered like a site; shown and revocable on the audit page as site
   `joblens`. Otherwise no prompt: the run's start proof covers its delivery. A standalone
   `deliver` can only send files from admin-proven runs to the fixed target, so it needs no
   new proof.
5. Send every file in `from` whose `flow` field is this flow id and that is not yet done (4.4),
   oldest first, one request at a time.

### 4.4 Tracking (once only)

`deliveries.json` in the data home, keyed by the SHA-256 of the file's bytes, atomic writes
under a lock (same pattern as `approvals.json`). Outcomes:

| JobLens answer | Outcome | Sent again? |
|---|---|---|
| 202 | `delivered` (+ listing id) | no |
| 200 duplicate | `duplicate` (+ listing id) | no |
| 400 | `failed` (+ the field name from the message) | no, unless the file changes |
| 409 (budget / no master CV), 429 (daily cap) | `retry`; **stop the batch**, rest stay pending | yes, next delivery |
| connection refused, timeout, 5xx | `retry`; stop the batch | yes |
| description < 300 chars | `skipped_too_short`, not sent | no |

Files of a run that stopped part-way stay pending and go with the next good run (admin, earlier).

### 4.5 Payload

Exactly: `title` ← `job_title` (whitespace runs collapsed to one space; control characters
removed), `company`, `jd_text` ← `description`, `url` (http/https only, else dropped),
`source` ← the flow's `deliver.source`. Empty optional fields are left out. A field over its
JobLens limit (`title`/`company` 500, `url` 2000, `jd_text` 50,000) makes the file `failed`
locally, not truncated.

### 4.6 Audit and output

One entry per file: kind `delivery`, `flow`, `target: joblens`, `file_hash`, `response_code`
(or `null` if not sent), `listing_id`, `outcome`. Never title, company, text or URL.
Printed summary: `deliver joblens: delivered 4, duplicate 1, retry 0, failed 0, skipped 0`.
Exit 0 when nothing is `retry` or `failed`, else 1.

### 4.7 Details settled after the builder check (my calls)

- **Unique job files.** `write_json` names files `YYYYMMDD-<title slug>.json`, so two jobs with
  the same title on one day overwrite each other. New name:
  `YYYYMMDD-<title slug>-<first 8 hex of SHA-256 of the job URL>.json`. Only the Himalayas flow
  uses `write_json`; no flow hash changes.
- **Approval hash.** `read_bound` already hashes the whole flow file plus its pages, so adding
  `deliver:` changes the Himalayas digest with no hashing code change. No test pins a digest.
- **Shim file.** The run process writes `GOVAIOS_NEXT_FILE` only after `flow_end`; the shim
  creates it empty with `mktemp` and deletes it on exit, like its other files. A forged or stale
  file can at most start `deliver`, which re-checks everything (4.3).
- **"Latest run"** is per flow id: the last `flow_start` for that flow in the audit log must be
  followed by its `flow_end`. `deliver` refuses while any other GOV-AIOS run is live
  (`live_runs`), so it never overlaps a run.
- **Order** is oldest `captured_at` first. The admin deleted the pre-delivery files on
  2026-11-06, so the first batch is only new runs; a 429 stops the batch as in 4.4.
- **First-contact prompt cancelled or failed:** exit 1, nothing sent, all files pending.
- **Exit code:** `skipped_too_short` alone still exits 0.
- **Payload checks** run after trimming: a title that is empty or has no letter or digit, or a
  description under 300 characters after trimming, is `failed` / `skipped_too_short` locally.

## 5. Tests the builder must add (beyond unit tests of each part)

- A flow without `deliver:` writes no `GOVAIOS_NEXT_FILE` and the shim launches once.
- Morning brief and Himalayas digests: morning unchanged; Himalayas changes only by the new keys.
- `deliver` refuses when: STOPPED, locked, flow revoked, last run not `flow_end`, unknown target.
- A tampered flow cannot change the address (there is no field for it); `to: other` is refused.
- 409 mid-batch stops the batch, later files stay pending, a second run sends them.
- Same file twice → one request; changed file → new hash → sent.
- Audit entries contain no payload text (fixture with a distinctive marker string).
- `DELIVER_PROFILE` in a child process: :8100 allowed, :8000, 1.1.1.1:443 and DNS denied
  (the spike's checks, as tests in the style of the existing sandbox child tests).

## 6. Review focus (likely to bite, not covered by the cases above)

1. JobLens not running (Docker down): connection refused → `retry`, a clear message, exit 1;
   the run itself still counts as done.
2. The admin presses the emergency stop during delivery: the request in flight may complete;
   no further request is sent; tracking stays consistent.
3. JobLens on the dev port (8000) by mistake: denied by the sandbox; the message says so.
4. A job file edited or corrupt JSON: `failed` with reason, the batch continues.
5. Very long descriptions near 50,000 characters: sent intact, not cut.

## 7. Calls I made (admin to check)

- The run process, not the shim, decides whether delivery follows (`GOVAIOS_NEXT_FILE`).
- No Touch ID for delivery after the first-contact approval; standalone `deliver` needs none.
- `source` lives in the flow's `deliver:` block (a label, not an address).
- 400 and over-limit files are not retried; 409/429/connection errors stop the batch.
- The browser key `application:` keeps its name (renaming it would change both flows' hashes);
  "app" names the bundle in docs and UI only.

## 8. Left to the builder

Module layout (suggested `govaios/delivery.py` with `TARGETS` and the JobLens sender), the
exact refusal messages, how the shim reads `GOVAIOS_NEXT_FILE`, test fixtures for a fake
JobLens server (a local `http.server` on a free port in unsandboxed tests).
