# Outcome checks and proof packets: design (2026-11-14)

Agreed with the admin on 2026-11-14, after comparing GOV-AIOS with WebArena, BrowserGym, Playwright and the
record-and-replay tools (backlog entry "Outcome check per step", `ae66117`).

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
  can use to automate". The proof packet is what the demo shows at the end. It is also a section of the paper, as an
  enterprise requirement.

## The two use cases this must cover

1. **JobLens (the admin's own app, `localhost:8100`).** Shortlisted → Review → **Approve & promote**. The press moves
   the profile out of Shortlisted into Promoted. Proof: the profile left Shortlisted, and the Promoted tab's count went
   up by one ("Promoted (8)"), both visible right after the press.
2. **HR interview scheduling (a prototype to be built).** HR fills candidate, interviewer, date and time, then presses
   **Schedule**. Proof: a new row in the **Scheduled** tab with this candidate at this time. The proof may only be
   visible after a click to the Scheduled tab, which the admin teaches after the press.

## Goals

1. **Studio proposes, the admin confirms.** During Teach, after a press, Studio compares the page before and after and
   proposes the outcome in plain words ("Shortlisted 5 → 4, Promoted 7 → 8, this profile left Shortlisted"). The admin
   confirms it or drops it. The admin never has to point at the proof.
2. **Presses that change data need an outcome.** A step at `submit` level (`lessons.level`) cannot be part of an
   approvable app without a confirmed outcome. `navigate` steps may have one, and don't need one. (The admin:
   "things that changes data in the target system requires an outcome".) `payment` stays never-pressed.
3. **The proof may come later, on a taught page.** An outcome belongs to its press but can be checked after later
   taught steps, up to the next press (HR: Schedule, then the taught Scheduled tab click). The admin: "a taught click
   after the press is fine". The proof is never gathered with a click that wasn't taught.
4. **Outcome kinds.**
   - **Count moved**: a number in a label changed by a fixed amount ("Promoted (7)" → "(8)").
   - **Item left or joined a list**: the item is the run's own one, matched by the Repeat round's item or by the
     run's inputs (HR's candidate and time). It is never just "some row appeared".
   - **New address**: the page's origin and path changed to a taught one.
   - **Value changed on the item** (*my guess, for approval and status cases*): for example Status Pending → Scheduled
     on the same row.
5. **Each run checks.** After the step an outcome is checked on, the run waits for it, about 10 s (*my call*, the same
   as `page_root`'s wait). Then:
   - **Holds:** a signed audit entry `outcome` with `outcome: confirmed`, the counts before and after, and the item's
     fingerprint.
   - **Doesn't hold:** the run stops with a card **"<button> pressed, result not seen"** and only **End**. *My call:*
     no Continue or retry, because pressing a data-changing button twice could promote or schedule twice. The audit
     entry is `outcome: not_seen`.
6. **Fingerprints, never names.** The audit and the packet carry a fingerprint of the item (profile name; HR's
   candidate, date and time), never the text. The name stays in JobLens or the HR app (the admin: "fingerprint only,
   the name stays in JobLens"). Anyone holding the name can recompute the fingerprint and confirm it. *My call:*
   SHA-256 over the run id and the item's normalised fields, so the same name gives different fingerprints in
   different runs. The run id is in the packet.
7. **Proof packet.** One file per run, exported from that run's audit view in the panel. It holds:
   - the run's signed audit entries, flow start to flow end, as a contiguous slice of the chain: who approved (press
     grant, Touch ID), app id, version and digest, each step, each outcome with its fingerprint
   - the audit public key
   - the verifier's result at export time

   The standalone verifier (`govaios/audit/verify.py`, stdlib + cryptography only) checks a packet on its own: each
   signature, and each `prev` link inside the slice. *My call:* the packet also carries the chain head's hash at
   export, so a later full-log check can show the slice belongs to it.
8. **Apps approved before this change keep running** without outcome checks until re-taught (the admin: "keep running
   until I re-teach them"). *My call:* their runs say "no outcome check" in the audit (`outcome: unchecked` on each
   press) and on the packet, so a packet never looks stronger than it is. Re-teaching a press adds its outcome. This
   covers `MoveDroppedToShortListed`, `studio_automationbuy` and `studio_discoverproducts`.
9. **The paper.** A short subsection in §4 Design of `docs/paper/gov-aios-paper-v1.md`, "Outcome-checked steps and
   proof packets", framed as an enterprise requirement: proof of results, not only of actions. Plus rows in §10
   Limitations (below), and one line in §9 Related work contrasting WebArena's end-of-task evaluators and Playwright's
   `expect` with per-step, signed checks. "A very small part for now."

## Non-goals

- No model anywhere in the check. Outcomes are fixed at teaching time and compared literally at run time.
- No proof gathered by extra, untaught clicks or by reading other apps or APIs.
- No outcome checks for outside sites' presses beyond today's rules. Outside sites still stop before Submit, so their
  presses are the admin's own.
- No change to how old audit entries are written. New entry kinds only.
- No Secure Enclave signing in this change. The packet uses the existing audit key (see Limitations).
- Building the HR prototype app itself is not part of this design. It is the next demo, and only its shape is
  assumed here.

## Anti-goals (it would be a failure if…)

- A packet showed "confirmed" when the item that moved wasn't the run's own (someone else's row appearing at the
  same time).
- A name, email or other field value reached the audit, the packet or the panel's audit view.
- A run pressed a data-changing button a second time after "result not seen".
- An old app's packet looked identical to a checked one.
- Teaching got slower or wordier for navigation clicks that need no outcome.

## Constraints

- The audit's no-content rule (`govaios/audit/log.py` `FIELDS`: metadata only) holds. Counts are numbers and are
  allowed; labels are logged by element id, as today. New fields must be added to `FIELDS` explicitly.
- The recorder takes one snapshot per press, at mouse-down, before the page reacts (`recorder._down`). The "after" of
  press N is therefore the snapshot of the next press on that page or the next page, or a snapshot taken at **Done**.
  *My call:* the builder may add one extra snapshot shortly after each submit-level press if the next press is
  too far off. Either way the extension never clicks.
- Grants and approvals stay tied to the app's digest. Adding or changing an outcome changes the digest, so the app
  asks for approval again, as any edit does.
- The verifier stays standalone: stdlib + `cryptography`, copyable out of the install.

## Paper: rows to add to §10 Limitations

| Weakness | Status |
| --- | --- |
| A fingerprint of a short name can be found by trying likely names | Accepted: the per-run salt stops lookup tables, not guessing; a keyed fingerprint would hide it but needs the key to check |
| The packet is signed with the on-disk audit key, so a same-user process could forge one | Planned: the Secure Enclave key already planned for approvals |
| An outcome is checked on what the page shows, not in the target system's database | By design: GOV-AIOS reads screens, not back ends; an app's own audit or API is the stronger proof where one exists |

## Settled after the design review (2026-11-14, all *my calls*)

1. **A run's own entries.** Every audit entry a run writes from now on carries a new field `run` (the run id) and
   `run_seq` (1, 2, 3… within the run). Entries already written are untouched. The packet holds **only the run's own
   entries**, never interleaved ones (a Claude Code hook entry carries a redacted command, and must not travel with an
   HR proof). Each entry's signature proves it is genuine. `run_seq` with no gaps, from `flow_start` to `flow_end` or
   `stop`, proves none was dropped. A run with no end entry (process killed) gives a packet marked **incomplete**,
   never rejected silently. The packet also carries the full chain's entry count and head hash at export, so a later
   full-log check can place it.
2. **The run's own item.**
   - In a Repeat round, the item is the list item the round works on, read from the live page when the round starts.
   - In the HR case it is the run's inputs that Studio marked as the item's fields at teach time (the candidate, date
     and time inputs).
   - The lesson stores which fields form the item, never their values. It may store label patterns such as
     `Promoted (N)`: those are page structure, like the names page files already hold.
   - "Left the list" means the number of items with that identity dropped by one, so two profiles with the same name
     (engine.py notes names can repeat) don't confuse it.
3. **Before and after at run time.** The engine reads the "before" values (counts, the item's presence) from the page
   just before the press, in the run itself, and the "after" after the step the outcome is checked on. A count rule is
   the change taught (for example +1). Where an item is known, both the count and the item must hold. If someone else
   changes the same list at the same moment, the result is a false **stop**, which is the safe side. A false confirm
   needs both checks fooled.
4. **The window.** An outcome is checked after its press or after a later taught step, at the latest the step before
   the next press, or the flow's end. If a step in between fails, the run stops as today, and the outcome is recorded
   `not_seen`. In a Repeat, each round has its own outcome check and fingerprint (salt: run id plus round number). If
   no snapshot follows the last press during teaching, the recorder takes one shortly after it: mandatory, not
   optional.
5. **Old apps.** "Old" means the app's current digest was approved before this change and is unchanged. Approval is
   where the rule is enforced: the panel refuses to approve a new or edited app with a `submit` step that has no
   outcome. An unchanged, already-approved app keeps running, and each of its presses logs `outcome: unchecked`.
6. **Names.** The new audit kind is `outcome`. The existing `outcome` field keeps its meaning and carries
   `confirmed`, `not_seen` or `unchecked`. The other new field names are the builder's, added to `FIELDS`.
7. **Verifier.** `verify.py` gets a packet mode: check every signature, the `run_seq` run with no gaps, the presence
   of `flow_start`, and report "complete" or "incomplete (no end entry)".
8. **Queued runs.** "Result not seen" is a stop like any other: the card shows on Home, and the queue treats it as
   today's stops.
9. **The HR prototype** is not needed for this work. Tests use fixture trees for both use cases.

## Left to the builder

- How Studio words a proposed outcome on the lesson page and in the side panel, and where the confirm/drop control sits.
- How the diff picks counts out of labels (`COUNT`-style patterns already exist in `spikes/plan6/match_spike.py`) and
  which list an item belongs to.
- The packet's file format (one JSON file is fine) and its name.
- How the panel's audit view offers the export.
- The exact normalisation of fields before fingerprinting (trim, case, whitespace), as long as the verifier
  documents it.
