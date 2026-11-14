# Outcome checks and proof packets: design (2026-11-14)

Agreed with the admin on 2026-11-14, after comparing GOV-AIOS with WebArena, BrowserGym, Playwright and the
record-and-replay tools (backlog entry "Outcome check per step", `ae66117`). Revised the same day after a builder check,
the admin's review (`112ba98`) and an architect review against the code (this version). *My call* marks decisions the
admin has not made; everything else is theirs.

## Why

- Today a run proves a click happened, not that it worked. The engine checks the page before a step
  (`wait_for_page`) and the point under the mouse, but nothing after: a press that changed nothing still counts as
  done (automationexercise "Add to cart", 2026-11-13). WebArena's evaluators check the result (URL match, text on the
  page, page state); Playwright tests end in `expect(...)`. GOV-AIOS has no equivalent.
- The admin wants evidence a third party can trust: who approved the press, and where the item went. Their words:
  "what could be a proof that who clicked and evidence of where the profile went, kind of signed packet of proof would
  be good".
- **Strategy (the admin, 2026-11-14):** quick prototypes of in-house use cases, each taught live in a teaching session,
  as proof of concept for enterprises: "the same concept can be sold to an enterprise, the solution itself which they
  can use to automate". The proof packet is what the demo shows at the end. It is also a small section of the paper, as
  an enterprise requirement.

## The two use cases

1. **JobLens (the admin's own app, `localhost:8100`).** Shortlisted → Review → **Approve & promote**, as a Repeat over
   the Shortlisted list. The press moves the profile from Shortlisted to Promoted. Proof: **this round's profile left
   Shortlisted**, and **Promoted's count went up by one** ("Promoted (8)").
2. **HR interview scheduling (a prototype, not built yet).** HR fills candidate, interviewer, date and time, then
   presses **Schedule**, then clicks the **Scheduled** tab (taught). Proof: **Scheduled's count went up by one**.
   - *My call, first build:* matching the new row to *this* candidate needs typed text "asked at Run" (teach-extension
     spec rule 9), which is not built: the recorder records clicks only (`recorder.py:141`, `value: ""`) and learned
     form steps fill from the answer bank (`engine.py:1251-1273`). So the first build proves the HR case by **count
     only**, and its packet says so: **"count changed; item not matched"**. Item matching for HR comes with the
     typed-text plan. The JobLens case gets the full proof now.

## Goals

1. **Studio proposes, the admin confirms each one, at lesson review.** On the lesson page (`lessons.propose`), Studio
   compares the trees before and after each press and proposes outcomes in plain words ("Promoted 7 → 8, +1";
   "this round's profile left Shortlisted"). Proposals are made at review, not live in the side panel, because the
   Repeat item is only chosen there (`lessons.repeatable`).
   - Each proposed outcome has **its own checkbox, unchecked by default**; there is no "confirm all".
   - Each shows the values Studio used: the label, before → after, the change, and for item outcomes which list. These
     are shown to the admin only and never reach the audit.
   - Each says which step it is **checked after** (Settled 6).
2. **Presses that need a press grant need an outcome.** A click at `submit` level on the admin's own apps
   (`localhost`/`127.0.0.1`), the presses that today ask for a one-time press grant, cannot be approved without at
   least one confirmed outcome. Navigation clicks may have one and don't need one. Outside sites are unchanged: GOV-AIOS
   stops before Submit and the admin presses it. `payment` stays never-pressed. (The admin: "things that changes data
   in the target system requires an outcome".)
3. **The proof may come after later taught steps.** An outcome belongs to its press but can be checked after a later
   taught step, up to the step before the next press or the flow's end (HR: Schedule, then the Scheduled click). The
   admin: "a taught click after the press is fine". The proof is never gathered by a click that wasn't taught.
4. **Two outcome kinds in the first build** (*my call*: the others are cut, see Non-goals):
   - **Count moved**: a number in a taught label changed by the taught amount ("Promoted (N)", +1). The lesson stores
     the label pattern and the change, never the number seen while teaching. A run expects **"before" + the change**.
   - **Item left a list**: the Repeat round's own item left the list. "Left" means the number of items with that
     identity on the list dropped by one, so two profiles with the same name don't confuse it.
5. **Each run checks, by polling.** After the step an outcome is checked after, the run reads the page about every 1 s
   for up to **15 s** (*my call*), with `current_page` and a deadline, never `page_root`, whose own "not on X" stop
   would mask the result (`engine.py:416-428`). An outcome **holds** when it holds on **two consecutive reads**.
   - **Holds:** a signed audit entry of kind `outcome` with `outcome: confirmed`, the counts before and after, and the
     item's fingerprint where there is an item.
   - **Never holds in the window:** the run stops with a card **"<button> pressed, result not seen"** and only **End**.
     No Continue or retry: pressing a data-changing button twice could promote or schedule twice. The entry is
     `outcome: not_seen` and records what was last seen, as numbers and label ids only ("Promoted stayed 7, expected
     8"; "item still on Shortlisted").
   - **Never reached** (the run stopped earlier): `outcome: not_checked`. `not_seen` means "looked, and it wasn't
     there".
6. **Fingerprints: a commitment, not a hiding place.** The audit and the packet carry a fingerprint of the item, never
   its text (the admin: "fingerprint only, the name stays in JobLens"). It is SHA-256 over the run id, the round number
   and the item's normalised identity (*my call*).
   - **What it proves:** the item that moved is one the admin can name later, and anyone can check that name against
     the packet.
   - **What it does not do: hide the name.** Names are easy to guess. Anyone with the packet (it carries the run id) and
     a short list of likely names can find which one matches. A keyed fingerprint would hide it, but then the packet
     could not be checked without the key. We choose a checkable commitment and say so on the packet, in the docs and in
     the paper. Share a packet only with someone who may know which item it was.
7. **Proof packet.** One file per panel run (CLI runs have no run id, `engine.py:279-282`: no packet), exported from
   that run's audit view. It holds:
   - **the run's own entries**, linked by `run_prev` (Settled 1);
   - **context entries**: the signed approval entries for this app's digest (`flow_approval` and the lesson approve,
     `engine.py:375`, `web.py:1786`) and its `press_grant` (`engine.py:851`). They are written outside the run (and
     the press grant only on the first run of a digest), so without them a packet from run 2 onward would show no
     approver. They are checked by hash and signature only, outside the run's chain;
   - the signed `packet_export` entry itself (Settled 8), which carries the full chain's entry count and head hash at
     export;
   - the audit public key.

   Nothing in the packet is unsigned except the public key. The standalone verifier (`govaios/audit/verify.py`,
   stdlib + `cryptography` only) checks a packet on its own (Settled 7).
8. **Apps approved before this change keep running** until re-taught (the admin: "keep running until I re-teach
   them"). See Settled 5 for how "old" is decided. Their presses log `outcome: unchecked`, and their packets say
   **"no outcome check"**, so a packet never looks stronger than it is.
9. **The paper**, in a separate commit: a short subsection in §4 of `docs/paper/gov-aios-paper-v1.md`, "Outcome-checked
   steps and proof packets", framed as an enterprise requirement (proof of results, not only of actions). Plus the
   Limitations rows below in §10, and one line in §9 contrasting WebArena's end-of-task evaluators and Playwright's
   `expect` with per-step, signed checks.

## Non-goals (first build)

- No model anywhere in the check. Outcomes are fixed at teaching time and compared literally.
- No proof gathered by untaught clicks, or by reading other apps or APIs.
- **Cut, later plan:** "value changed on the item" (status Pending → Scheduled) and "new address" outcomes; item
  matching from run inputs (needs typed text asked at Run); live proposals in the side panel; a full-log membership
  check in the verifier.
- No change to how existing audit entries are written, beyond the new fields on run entries (Settled 1) and removing
  item text from run entries (Settled 3).
- No Secure Enclave signing. The packet uses the existing on-disk audit key (Limitations).
- Building the HR prototype app. Tests use fixture trees for both use cases.

## Anti-goals (it would be a failure if…)

- A packet showed "confirmed" for an item that wasn't the run's own.
- A name, email or other field value reached the audit, the packet or the panel's audit view.
- A run, **or the next run in the queue**, pressed a data-changing button again after "result not seen".
- An old app's packet, or an HR count-only packet, looked as strong as a fully checked one.
- Teaching got slower or wordier for navigation clicks that need no outcome.

## Constraints

- The audit's no-content rule (`govaios/audit/log.py` `FIELDS`: metadata only) holds. Counts are numbers and are
  allowed; labels are logged by element id. New fields and kinds are added to `FIELDS` and `KINDS` explicitly, and
  `packet_export` to the panel's kinds (`web.py:171`).
- Grants and approvals stay tied to the app's digest. Adding or changing an outcome changes the digest, so the app asks
  for approval again, as any edit does.
- The verifier stays standalone: stdlib + `cryptography`, copyable out of the install.
- The recorder's read at mouse-down stays as fast as today: no extra snapshots between presses.

## Settled (builder check, admin review and architect review, 2026-11-14)

1. **A run's own entries, linked two ways.** Every audit entry a run writes from now on carries `run` (the run id),
   `run_seq` (1, 2, 3…) and `run_prev` (the hash of the run's previous entry, 64 zeros on `flow_start`), all inside the
   signed hash. `Runner._audit` (`engine.py:316`) tracks `run_prev` from what `append` returns. The global `prev` is
   unchanged. **Packet mode does not check the global `prev`**, because it points outside the packet by design.
   *Known edge:* `append` can raise after its line is written (the `chflags` step, `log.py:136`). The run then stops on
   the audit error as today, and its packet shows the last written entry. A packet is marked **incomplete** whenever it
   has no `flow_end` or `stop`.
2. **Teach-time trees.** Each recorded press keeps its own blanked tree (`_blank`) as the event's "before", and the
   lesson keeps one more tree at **Done**. Today only a page's first tree is stored (`recorder.py:134-135`,
   `lessons.py:224`), which cannot be diffed for a second press. A press's "after" is the next press's tree (on any
   page) or the Done tree. *Cost:* one blanked tree per press in the lesson file, about the size of one page tree each.
   No snapshot is taken between presses (Constraints).
3. **No item text in run entries.** Today `do_repeat` logs `target=label`, the row's first cell, usually the profile
   name (`engine.py:117-122`, `:883`, `:885`), and the stop reason "repeat stopped on {label}…" (`:888`) reaches the
   `stop` entry (`:502`). Run entries carry the round number and the fingerprint instead. The **card** shown to the
   admin may still name the item, since it is the admin's own screen. A test asserts that a packet built from a JobLens
   fixture run holds no item text.
4. **"Before" at run time.** "Before" is the last snapshot in the run that was identified as a page and showed the
   outcome's labels. In a Repeat that is the round's start read (`do_repeat`'s count `c`, `engine.py:871`). The press
   itself happens on the Review pop-up, where Shortlisted may not show. When a round has an item-left outcome, the
   outcome poll **replaces** `do_repeat`'s own 10 s "still on the list" wait (`:877-881`). Otherwise that wait stays.
5. **Where the rule is enforced: one check, at every approval.** `outcomes_ok(flow, pages)` is called in
   `Runner.approve_flow` (`engine.py:369`, used by the panel at `web.py:1252` and by the CLI) and in `approve_lesson`
   (`web.py:1781`). Try is exempt: a Try never presses (`engine.py:928`). The check covers only presses that need a
   press grant (own app, `submit`), so hand-written flows for outside sites are unaffected. **"Old" needs no date:** a
   digest already approved keeps running, and any digest not yet approved, including an old app after any edit, must
   pass the check. The approval page says why before Touch ID ("This app now needs an outcome on Approve & promote:
   re-teach that step").
6. **Which step an outcome is checked after: automatic, and shown.** Studio picks the first taught step, from the press
   up to the step before the next press, whose "after" tree shows the outcome. For JobLens that is the press itself
   (the next round's tree, or the Done tree, shows Shortlisted and Promoted). For HR it is the Scheduled click (Done
   tree). The lesson page shows it on each outcome ("checked after: click Scheduled"). The admin can't move it in this
   build; if the wrong step shows the result, they re-teach. The same rule runs at build and at run time.
7. **Verifier, packet mode only.** `verify.py --packet <file>` checks, using only the packet:
   - every entry's hash and signature against the packet's public key;
   - the run's entries: `run_prev` links from 64 zeros, `run_seq` 1…n with no gaps, one `run` value, and `flow_start`
     present;
   - each context entry's hash and signature, and that its `flow_hash` equals the run's `flow_start` digest.

   It reports "complete" or "incomplete (no end entry)", plus "no outcome check" or "count changed; item not matched"
   where those apply.
8. **Packet export.** It needs the signed-in panel session, as every panel page does, and **no Touch ID**: the packet
   holds metadata, counts and fingerprints only, and exporting changes nothing. Each export writes a signed
   `packet_export` entry, with the run id in `target` and the chain's entry count and head hash. It carries no
   `run`/`run_seq`, so it never joins a run's chain. The packet builder selects run entries by `run` **and** `run_seq`.
   The download is served only to the panel's own session.
9. **"Result not seen" ends the run and clears the queue.** Its prefix is added to `RUN_STOPS` (`engine.py:42`), so
   inside JobLens tasks it ends the whole run instead of offering **Next job** (`engine.py:719-724`), and `do_repeat`
   re-raises it unchanged (`_ends_run`, `:887`). The panel calls the existing `clear_queue(...)` (`web.py:437`) when a
   run ends `not_seen`, so no queued run of the same app can press again. Holding the queue while the card waits is not
   enough: the card times out after `ASK_TIMEOUT_S` (`engine.py:36`), and after End the queue would start the next
   run.

## Paper: rows to add to §10 Limitations

| Weakness | Status |
| --- | --- |
| A fingerprint is a commitment, not a hiding mechanism: anyone with the packet and a list of likely names can confirm a suspected one | Accepted and stated on the packet: it proves which item moved to someone who can name it. A keyed fingerprint would hide it, but then the packet cannot be checked without the key |
| The packet is signed with the on-disk audit key, so a same-user process could forge one | Planned: the Secure Enclave key already planned for approvals |
| An outcome is checked on what the page shows, not in the target system's database | By design: GOV-AIOS reads screens, not back ends; an app's own audit or API is the stronger proof where one exists |
| The first build matches the HR item by count only | Planned with typed text asked at Run |

## Left to the builder

- Wording of proposals on the lesson page, and where each checkbox sits.
- How the diff picks counts out of labels (`COUNT`-style patterns exist in `spikes/plan6/match_spike.py`).
- The packet's file format (one JSON file is fine) and name, and how the audit view offers the export.
- The normalisation of an item's identity before fingerprinting (trim, case, whitespace), documented in the verifier.
- Names of the new audit fields beyond `run`, `run_seq`, `run_prev` and the kinds `outcome` and `packet_export`.
