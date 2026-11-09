# Studio observer: teach a page by doing it — design (2026-11-09)

Branch `feat/studio-observer`. This is the heart of Studio: GOV-AIOS learns the admin's own daily tasks by watching the admin do them, page by page.

## Why

- Today a new page costs a sandbox run, a capture, a Check app to approve, and Claude writing YAML by hand. The admin expects to meet tens of new pages (Oracle careers, Workable, company sites). One app per page "is donkey years".
- The admin's position, in their words: *a process learns what I do on a page, as a learning exercise. I don't need others' data; I learn from my own.* Recording their own actions on their own Mac is the point, not a risk to design away. So the observer records everything the admin does in the lesson, values included, and does not filter the admin's own actions.
- What stays fixed: nothing changes a flow or the bank without the admin seeing it and approving it with Touch ID, and nothing is captured on a site whose terms do not allow a personal agent.

## Goals

1. When a flow meets a page it doesn't know, the admin is told at once and can **teach that page** right there.
2. The admin teaches by doing the page in Chrome as they normally would. The observer records what they did. Closing the tab ends the lesson.
3. Right after the lesson, the panel shows **what was learned**. The admin edits it, then approves with one Touch ID. The flow knows the page from the next run on.
4. A lesson from a flow goes **into that flow**, as one more page it can meet. A lesson from the sandbox goes into a standalone draft page.
5. Studio **New automation**: a name and a starting link make an empty automation, and the same teach loop grows it page by page.
6. Typed values are learned into the **answer bank**. A new value proposes a new key, a different value proposes a change, and each is shown and approved like the steps.
7. Before anything is captured on a new site, a **terms check**.

## Non-goals

- No keyboard recording. Field values come from the page itself (accessibility values), which are also more accurate after autocomplete.
- No recording outside the teach tab: other tabs, windows and apps are never read.
- No AI writing steps the admin didn't do. The observer turns observed actions into steps; nothing is guessed.
- Not now: editing a learned page later (re-teach it instead), branching logic ("if the field is there"), and masking for non-dev use (the dev mode stays unmasked, as today).

## Anti-goals (it would be a failure if…)

- …a flow, a page file or the bank changed without the admin seeing the exact change and approving it.
- …a lesson on one job broke the other jobs' tabs, or the run.
- …the observer missed what the admin clicked and silently produced a step that does something else. If it isn't sure, it asks.
- …teaching ten pages took ten separate apps or ten restarts of the setup.

## The user journey

### A. Teach from a flow (the main path)

1. JobLens is on job 3 and lands on a page it doesn't know (`classify_page` finds no match: today the "unexpected page" stop).
2. **Notification**: a macOS notification, spoken text and a panel card: *"JobLens can't go on: this page is new. Teach it?"* with **Teach this page · Next job · End**.
3. **Teach this page**:
   1. If the page's site is new to the flow, the **terms check** (below). Forbidden or unclear: nothing is captured, and the card falls back to Next job / End.
   2. Touch ID once to let the lesson read this site (it adds the site to this run's destinations in memory, as the sandbox does).
   3. The panel card turns into **Teaching: do the page in Chrome. Close the tab when you're done.** It shows a live list of what the observer has seen ("clicked *Apply Now*", "Email ← rupak.k@…"), so the admin can watch it work. **Cancel lesson** discards everything.
4. The admin does the page, possibly several pages (Oracle: job page → sign-in by email → form page 1 → page 2). They stop where they'd normally hand over (before the final submit), or they press the submit themselves.
5. The admin **closes the tab**. That ends the lesson.
6. **What I learned** screen, one section per page:
   - the page (its title and a draft page id),
   - its steps in order: *click Apply Now*, *fill Email ← bank `email`*, *choose India in Country ← bank `country`*, *tick "I agree"*, …,
   - bank changes: *new key `notice_period` = "30 days" (label "Notice period")*, *add label "E-mail address" to `email`*,
   - per line: edit, delete; per page: delete.
   - **Approve** → Touch ID → the flow file, the new page files and the bank change together.
7. After approval the job is marked **Learned**, and the card offers **Next job · End**. The current run keeps the flow it started with (approval binds the file at start). The next run uses the new version.

### B. New automation in Studio

1. Studio → **New automation**: a name and a starting link (e.g. JobLens at `http://localhost:8100/`).
2. Terms check for that site (localhost and the admin's own apps: no check, see below).
3. It writes an empty automation: Chrome, the Google account check, open the starting link, then **teach**. Approve with Touch ID.
4. Run it: Chrome opens the start page and the teach card appears straight away. Same lesson, same "What I learned", same approval.
5. Run it again: it plays back what it knows. Where a click opens a page it hasn't seen, path A takes over.

### C. Sandbox

The same lesson with no flow: each page becomes a draft page in Studio (as now), with its learned steps, for linking into an automation later. The Check apps go: capture already proves the page is recognised (round trip), so they add nothing.

## The observer

During a lesson it watches **only the teach tab's window** in Chrome, and records **events**:

| Event | How it's seen | Becomes |
|---|---|---|
| page change | URL or title change, then a settled snapshot of the tree | a new page section, a draft page |
| click | a listen-only mouse-down monitor, then the accessibility element under that point | *click <element>* |
| field value | the focused field's value, read when focus leaves it | *fill <field>* ← bank key |
| choice | a combo box / list's selected option on change | *choose <option> in <field>* |
| checkbox / radio | its checked state on change | *tick* / *pick* |
| file chosen | the file input shows a file name | *attach CV* (existing CV step) |

- The listen-only mouse monitor sees positions only, needs no new permission (the app has Accessibility already) and runs only during a lesson. It never blocks or changes input. *My call*: this is the only reliable way to know which link was clicked, since links don't always take focus.
- The keyboard is not tapped. A password field's value is unreadable by design (secure field): the step becomes *you fill this yourself* (hand-fill, like the CV today).
- Each element is turned into a page spec with the existing `studio.draft_page` rules (stable ids, names, `index` for duplicates) and checked to resolve to exactly one element on its snapshot. If it doesn't, the line says *not sure what this was* and the admin fixes or deletes it.
- Clicks on another tab, window or app are ignored. The lesson ends on tab close, on **Cancel lesson**, or after 30 minutes of nothing.
- Raw lessons are kept under `lessons/` (unmasked, dev mode, 0600, last 30), like `captures/`.

## Turning a lesson into a flow change

- **Pages**: each new page becomes `apps/pages/<site>_<title>.yaml` (`studio.draft_page`, then trimmed to the elements the steps use plus the identification).
- **Steps**: per page, the observed actions in order: click (never a submit-rated click: see below), fill from the bank, choose, tick, attach CV. The last page of the lesson ends with the existing **hand over** (review card).
- **Into the flow**: the page is added to the `classify_page` step where the run got stuck, so that matching it runs its steps. The engine needs a new `on_match` form for this, a list of steps for that page. After a page's steps the run classifies again, until it reaches a hand-over page. The exact YAML shape is the builder's.
- **Submit**: a submit click the admin made in a lesson is recorded and shown, but played back as *hand over: you submit*, as today. *My call*; see open questions.
- **Bank**: a typed value equal to a bank answer uses that key (and adds the field's label to it if new). Otherwise a new key, named from the label, is proposed. The same label with a different value proposes a change to that key. A backup of the bank is written before each approved change.
- **Approval**: the flow digest changes, so the one Touch ID approves the new flow plus its pages (bound as today by `approvals.read_bound`) plus the bank change, and the panel audits a `lesson` entry with the page ids and the step and key counts.

## Terms check (first slice of backlog Plan 3)

- Per **site** (origin), stored once, re-asked after 90 days: `allowed`, `forbidden` or `unclear` (= forbidden until decided), with the date, the terms link and the quoted clause.
- First slice: the panel opens the site's terms page in Chrome next to a card asking the admin for the verdict and the clause (paste). Reading the terms for the admin and proposing a verdict with quotes is a later slice.
- `localhost`, `127.0.0.1` and sites already in an approved flow (Himalayas, Greenhouse, Lever, Google) are treated as decided today and need no check.
- Before a lesson, a sandbox capture, or a New automation on a site: `allowed` is required.

## Cleanup

- Drafts and Studio-made automations get **Delete** on the panel (audited, Touch ID not needed: deleting can't widen anything). Shipped apps stay revoke-only, as now.
- No more Check apps; existing ones can be deleted.

## Constraints

- macOS, Chrome, the accessibility tree only (as everything today). No website APIs.
- The engine's safety rules stay: the click-point check, pinned window, emergency stop, locked screen. The observer reads only and never acts.
- One Touch ID per lesson approval.

## Left to the builder

- The flow YAML shape for "on this page, these steps" and the classify-again loop.
- How the observer polls (accessibility notifications or a short poll), within the events table above.
- The "What I learned" page layout, following the panel's style.

## Calls made after the builder check (mine; the admin can overturn any)

1. **Fields replay through the existing `fill_form`, not as fixed per-field steps.** The same site shows different fields per job. A lesson teaches the page's identity, its clicks and choices, and the bank (labels and answers). On replay, `fill_form` matches fields by label, as on Greenhouse, with its passes and fix cards. Clicks, choices outside the form and the hand-over are explicit steps.
2. **Each typed value has a "keep" setting on the What I learned screen:**
   - **Keep in bank**: the default for short values;
   - **This job only**: the step stays a fix card for each job;
   - **Don't keep**: the default for one-time codes and for text over 200 characters (cover letters, "why this company").
3. **Terms are decided per registrable domain.** One verdict covers `oraclecloud.com`. Destinations stay per origin, with Touch ID per new origin as today. If a lesson moves to a new origin partway (a sign-in host), the observer pauses: terms check if the domain is new, then Touch ID, then it carries on. A refusal drops that page and ends the lesson there.
4. **First slice: only `classify_page`'s unknown page offers Teach.** The learned page is added as a case of that step. The other "wrong page" stops (a click's page check, "left the form page", "still not on the expected page") keep Next job / End and come in a later slice, each converted to a classify point.
5. **A lesson writes the flow's copy in the apps folder, which the admin owns** (install never overwrites it). It never writes the repo's shipped file: Claude copies a learned page back into the repo when asked. The **panel** writes the files after the Touch ID approval, never the engine mid-run (it is sandboxed and busy). "Shipped apps stay revoke-only" is about deleting only.

## Open questions for the admin

1. A submit click you made during the lesson: played back as *hand over* (my call), or replayed with its own Touch ID each run?
2. During a lesson, should the other jobs' tabs wait, or can the run carry on with other jobs in the background? (My call: the run waits; one thing at a time.)
