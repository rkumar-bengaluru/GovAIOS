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

1. **Studio proposes, the admin confirms each one.** During Teach, after a press, Studio compares the page before and
   after and proposes outcomes in plain words ("Shortlisted 5 → 4, Promoted 7 → 8, this profile left Shortlisted").
   The admin never has to point at the proof. Unrelated changes between snapshots (a toast, another count, a re-sort)
   produce spurious proposals, so:
   - each proposed outcome has **its own checkbox, unchecked by default**; there is no "confirm all";
   - each one shows the **values Studio used**: the label, before → after, the change ("+1"), and which item it thinks
     left or joined which list. The panel shows these to the admin only and they never reach the audit;
   - each one says which step it will be **checked after** (see Settled 10).
   A submit step needs at least one checked outcome (Goal 2).
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
     on the same row. Only taught labels count: at teach time the admin confirms the before and after **labels**
     (`Pending`, `Scheduled`), which are page structure like `Promoted (N)`. The audit logs the change by taught label
     id (`status_pending → status_scheduled`), never the raw cell text. A cell whose text is not one of the taught
     labels never confirms.
5. **Each run checks, by polling.** After the step an outcome is checked on, the run reads the page about every 1 s for
   up to **15 s** (*my call*). The outcome **holds** when it holds on **two consecutive reads**, so a one-frame
   flicker neither confirms nor denies. Expected values are computed at run time as **"before" + the taught change**,
   never the number Studio saw while teaching: a lesson taught at Promoted 7 still works when a run starts at 12.
   Then:
   - **Holds:** a signed audit entry `outcome` with `outcome: confirmed`, the counts before and after, and the item's
     fingerprint.
   - **Never holds in the window:** the run stops with a card **"<button> pressed, result not seen"** and only **End**.
     There is no Continue or retry, because pressing a data-changing button twice could promote or schedule twice. The
     audit entry is `outcome: not_seen`, and it records what was last seen, as numbers and label ids only ("Promoted
     stayed 7, expected 8"; "item still in Shortlisted"). The admin can then tell "never happened" from "the app was
     slow" by looking in the app.
   - **Never checked** (the run stopped on an earlier step before reaching the check): `outcome: not_checked`, never
     `not_seen`. `not_seen` means "looked, and it wasn't there".
6. **Fingerprints: a commitment, not a hiding place.** The audit and the packet carry a fingerprint of the item
   (profile name; HR's candidate, date and time), never the text itself (the admin: "fingerprint only, the name stays
   in JobLens"). *My call:* SHA-256 over the run id, the round number and the item's normalised fields.
   **What it proves:** the item that moved is one the admin can later name and anyone can check against the packet.
   **What it does not do: hide the name.** Names, dates and times are easy to guess. Anyone with the packet (which
   carries the run id) and a short list of likely names can find which one matches. The per-run salt only stops
   precomputed tables. A keyed fingerprint would hide it, but the packet could then not be checked without the key,
   which defeats a standalone packet. We choose a checkable commitment, and say so on the packet, in the docs and in
   the paper. Share a packet only with someone who may know which item it was.
7. **Proof packet.** One file per run, exported from that run's audit view in the panel. It holds:
   - **only the run's own signed audit entries**, from `flow_start` to `flow_end` or `stop`: who approved (press grant,
     Touch ID), app id, version and digest, each step, each outcome with its fingerprint. The run's entries are not
     contiguous in the global chain (Claude Code hook entries, panel actions and other runs interleave), so the packet
     is not a slice of it; see Settled 1 for how it is linked;
   - the audit public key;
   - the full chain's entry count and head hash at export;
   - the verifier's result at export time.

   The standalone verifier (`govaios/audit/verify.py`, stdlib + cryptography only) checks a packet on its own (Settled 7).
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
  The recorder also takes an "after" snapshot **about 1.5 s after each submit-level press** (*my call*), and again
  at any later taught step up to the next press, so the proof page of the HR case is seen. Either way the extension
  never clicks.
- Grants and approvals stay tied to the app's digest. Adding or changing an outcome changes the digest, so the app
  asks for approval again, as any edit does.
- The verifier stays standalone: stdlib + `cryptography`, copyable out of the install.

## Paper: rows to add to §10 Limitations

| Weakness | Status |
| --- | --- |
| A fingerprint is a commitment, not a hiding mechanism: anyone with the packet and a list of likely names can confirm a suspected one | Accepted and stated on the packet: the packet proves which item moved to someone who can name it. A keyed fingerprint would hide it, but then the packet cannot be checked without the key |
| The packet is signed with the on-disk audit key, so a same-user process could forge one | Planned: the Secure Enclave key already planned for approvals |
| An outcome is checked on what the page shows, not in the target system's database | By design: GOV-AIOS reads screens, not back ends; an app's own audit or API is the stronger proof where one exists |

## Settled after the design review (2026-11-14, all *my calls*)

1. **A run's own entries, linked two ways.** Every audit entry a run writes from now on carries three new fields:
   - `run`: the run id;
   - `run_seq`: 1, 2, 3… within the run;
   - `run_prev`: the hash of the run's previous entry, 64 zeros on its `flow_start`.

   The global `prev` stays exactly as today, pointing to the previous entry in the full log, whatever it was. All
   three fields are inside the signed hash. Entries already written are untouched.

   The packet holds **only the run's own entries**, never interleaved ones: a Claude Code hook entry carries a redacted
   command, and must not travel with an HR proof. The run's chain (`run_prev`) is checked inside the packet. **The
   global `prev` is not checked in packet mode**, because it points outside the packet by design. It is checked only by
   a full-log verification, which can also confirm the packet's entries and head hash belong to the log. A run with no
   end entry (process killed) gives a packet marked **incomplete**, never a silent rejection.
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
   `not_checked`. In a Repeat, each round has its own outcome check and fingerprint (salt: run id plus round number).
   The 1.5 s post-press snapshot (Constraints) is mandatory.
5. **Old apps.** Approval is where the rule is enforced: the panel refuses to approve an app with a `submit` step
   that has no outcome. "Old" means the app's current digest was approved before this change and is unchanged. An old
   app keeps running, and each of its presses logs `outcome: unchecked`.
   **Any approval after this change**, including re-approving an old app after an unrelated edit, needs outcomes on
   every `submit` step. The approval page says so before Touch ID ("This app now needs an outcome on Approve &
   promote: re-teach that step"), so it is no surprise.
6. **Names.** The new audit kind is `outcome`. The existing `outcome` field keeps its meaning and carries
   `confirmed`, `not_seen`, `not_checked` or `unchecked`. `run`, `run_seq` and `run_prev` are as in Settled 1. The
   other new field names are the builder's, added to `FIELDS`.
7. **Verifier, packet mode.** `verify.py --packet <file>` checks, using only the packet:
   - every entry's hash and signature, against the packet's public key;
   - every `run_prev` link inside the packet, starting from 64 zeros on `flow_start`;
   - `run_seq` 1…n with no gaps, all entries with the same `run`;
   - the presence of `flow_start`.

   It reports "complete", or "incomplete (no end entry)" when there is no `flow_end` or `stop`. It does **not** check
   the global `prev` (Settled 1). The full-log mode, as today, gains one check: given the log and a packet, every
   packet entry is in the log and the packet's head hash and count match an entry of the log.
8. **A queue pauses on `not_seen`.** "Result not seen" shows its card on Home like any stop. The run queue does
   **not** start the next queued run until the admin presses End on that card. Otherwise a next run of the same app
   could press again for an item whose first press did happen, and the no-double-press guarantee would cover one run
   but not the queue. Other stops keep today's queue behaviour.
9. **The HR prototype** is not needed for this work. Tests use fixture trees for both use cases.
10. **Which step an outcome is checked after: automatic, and shown.** Studio checks each confirmed outcome after the
    first taught step, from the press up to the step before the next press, whose "after" snapshot shows it. For
    JobLens that is the press itself. For HR it is the taught Scheduled tab click. The lesson page shows it on each
    outcome ("checked after: click Scheduled"). The admin can't move it in this change; if the wrong step shows the
    result, they re-teach. The same rule runs at build time and at run time, so two builds can't differ.
11. **Packet export.** Export needs the signed-in panel session, as every panel page does, and **no Touch ID**: the
    packet holds metadata, counts and fingerprints only, and the action is reversible (nothing changes). Every export is
    audited (`packet_export`, with the run id). The download is served only to the panel's own session, never to an
    unauthenticated local request.

## Left to the builder

- How Studio words a proposed outcome on the lesson page and in the side panel, and where the confirm/drop control sits.
- How the diff picks counts out of labels (`COUNT`-style patterns already exist in `spikes/plan6/match_spike.py`) and
  which list an item belongs to.
- The packet's file format (one JSON file is fine) and its name.
- How the panel's audit view offers the export.
- The exact normalisation of fields before fingerprinting (trim, case, whitespace), as long as the verifier
  documents it.
