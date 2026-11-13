# Teach extension: teaching GOV-AIOS your pages from a Chrome side panel: design (2026-11-12)

This is project 2 of 2, agreed with the admin on 2026-11-11 and 2026-11-12. Project 1 (Home is the chat, the Apps page, the run queue) is merged (PR #33). The points agreed for this project on 2026-11-11 are at the end of `2026-11-11-panel-apps-and-queue-design.md`; this document carries them forward and replaces that section.

## Why

- Today's teach flow lives on the panel: a run stops on a page it does not know, the admin presses **Teach this page**, does the page in Chrome and closes the tab. The admin's words: "i did not know once i click teach where to start and end".
- The admin wants to teach their own apps first (no terms question), then outside sites, and to cover **about 100 pages in a week, at least 10 pages per app**.
- GOV-AIOS learns from the admin's own actions on their own pages: "let a process learn what i do in a page … i am learning from my own data". Nothing is learned from other people's data.
- The admin chose a GOV-AIOS Chrome extension with a side panel, in their own Chrome profile (Profile 2), over a custom browser: sign-ins would be lost, Google blocks sign-in in embedded browsers, and it would take months.

## The first lesson (the admin's example)

On JobLens (`http://localhost:8100`, the admin's own app):

1. Start on the home page `http://localhost:8100/`.
2. Click the **Discover** tab, then the **Shortlisted** tab. Today it holds 4 profiles in review.
3. For each profile: click **Review**, then **Approve & promote**.

This lesson is the acceptance test. The admin teaches it on **one** profile and accepts the repeat. Then pressing **Run** on the new app approves and promotes every remaining shortlisted profile, with no help. To test again, Shortlisted is refilled through the JobLens API that SyncJobLens already uses to add profiles (the admin, 2026-11-12: "the syncjoblens already uses an api to add profile to shortlisted, that can be reused"); the builder adds a small test-only script or step for that, sending the admin's own test profiles to their own app.

## How things are organised: Site → Pages → Apps

- **Site**: one origin, for example JobLens at `localhost:8100`.
- **Pages**: each page is taught once and saved once as a page file in `pages/` (as `joblens_job.yaml` and `himalayas_matches.yaml` are today). Any app may use any page. Pages are named automatically from site and title ("JobLens · Shortlisted"); the admin can rename them.
- **Apps**: one app is one job the admin would press **Run** for ("Approve shortlisted profiles", "Apply to Ready jobs"). A site has many apps sharing its pages. An app is an ordinary flow file in `flows/`, approved and run exactly as flows are today.
- **One Teach is one app**, start to finish.
- **Studio** in the navigation becomes the extension's home and is grouped by site: each site lists its pages, its apps, its lessons and drafts, and a page count toward the 100. Today's Studio page content and the panel's own teaching card ("Do the page in Chrome. Close the tab when you're done.") are replaced by this.

## Goals

1. **A GOV-AIOS extension in Chrome** (Profile 2) with a side panel. It watches and highlights only; it never clicks or types.
2. **Start and end are the admin's, and visible.** In the side panel: **Teach** (starts recording on the current tab, and records the tab's address as the app's start), **Pause** / **Resume** (for things not to record, such as logging in), **Done**, **Cancel**. While recording, the page shows a red **● Recording** sign.
3. **The side panel shows what was learned as plain steps, page by page**, as they happen ("JobLens · Shortlisted: click Review"), with a **YAML** tab showing the same steps as flow YAML.
4. **Repeats.** The admin does the steps on **one** item of a list, then the side panel offers a repeat, with its limit editable: *"Review → Approve & promote: repeat for every profile on Shortlisted, until none are left, at most [10]"*. The admin accepts it and presses Done, leaving the other items for Run. *My call: the offer appears as soon as the steps started on a list item and came back to the same list (or the list page is shown again); the admin need not do a second item. "Until none are left" because each approval takes a profile off the list; "the first [N]" is offered when the list does not shrink.*
5. **Reuse.** A page a known page file matches plugs in its existing elements instead of a new page.
6. **Typed text.** For each value typed during a lesson, the side panel asks: **always this text**, **asked at Run**, or **from my answer bank** (the existing `answers.yaml`). *My call; `lessons.py` already makes this choice for answer-bank fields.* Secure (password) fields are never recorded.
7. **At Done**: **New app** (named by the admin) or **Add to an app** (for example SyncJobLens gaining a new first step).
8. **Teach this page from a stopped run.** When a run stops on a page it does not know (SmartRecruiters on 2026-11-10), the run's card on Home offers **Teach this page**. It hands over to the extension as "continuing <app>, from here". The admin does that page and presses Done; the steps are added to that app at the step where it stopped. The next run goes through. This is the smooth path for the JobLens apply journey, which leaves for outside sites.
9. **Show me** highlights each step's target on the real pages, without clicking or typing.
10. **Try it**: one real run of the draft, through the normal checks. It goes only to the lesson's sites and needs one Touch ID tied to the exact draft. It never presses a submit-level button: it stops there and says *"Try it stops here: the real run will press Approve & promote."* *My call, to keep the agreed "Try it cannot submit".*
11. **Approve**: one Touch ID for the whole lesson, through today's lesson approval (`approve_lesson` in `govaios/audit/web.py`: checked, then Touch ID, then written).
12. **Terms for outside sites.** The admin's own apps (`localhost`, `127.0.0.1`) need no check. An outside site asks once, in the side panel, before anything on it is recorded, with three choices:
    - **allowed**, with the clause it rests on (as today's `terms.record`);
    - **forbidden** (nothing on that site is recorded);
    - **no terms found: I'll go ahead**: a waiver with the admin's note, saved as "waived by you", valid 90 days, which the admin can withdraw from the site's Studio page.
13. **Pressing buttons that change things on the admin's own apps.** See the next section.

## Pressing "Approve & promote": submit-level buttons on your own apps

**Which presses are submit-level.** *My call:* each click step in the side panel shows its level, guessed from the button: tabs, links, and buttons that only open something (Discover, Shortlisted, Review) are `navigate`; buttons whose name changes something (Approve, Promote, Reject, Delete, Save, Send, Submit, Apply, Confirm…) are `submit`; Pay / Buy / Checkout are `payment`. The admin can change any step's level in the side panel before Done. This replaces today's "every button is submit" guess (`lessons._risk`) for extension lessons.

**Where it is enforced.** *My call:* the rule is checked by the page's address when the press happens, in the policy check (`govaios/policy.py` `decide`), not only by the flow's single `max_element_risk`. An app that mixes the admin's own app and outside sites (JobLens apply) may press submit-level buttons only on its `localhost`/`127.0.0.1` pages; on any other page the run stops before Submit as today.

The admin agreed on 2026-11-12: "yes, let it press Approve & promote on my own apps, when it does for the first time it asks for approval for clicks, the new runs of the same flow preserve the audit logs".

- On the admin's own apps (`localhost`, `127.0.0.1`) an app may press submit-level buttons such as Approve & promote. On outside sites nothing changes: GOV-AIOS stops before Submit and the admin presses it.
- **First run**: the run stops just before the first submit-level press and asks on Home, with Touch ID: *"Let 'Approve shortlisted profiles' press Approve & promote on JobLens?"* The question lists every submit-level button the app may press, by name. *My call: one Touch ID covers all of them for that app, not one per button.*
- **Later runs of the same app** press them without asking.
- **Any edit to the app** asks again: the grant is tied to the app's digest, as approvals are today.
- **Every press is in the audit log** (app, page, button, time), as clicks are today. Earlier runs' entries are never removed.
- Payment-level buttons are never pressed, on any site.

## Non-goals

- The extension driving the page. Runs stay as they are: Chrome, driven through the accessibility tree by GOV-AIOS. The extension only watches and highlights.
- Other browsers or other Chrome profiles.
- Publishing the extension to the Chrome Web Store. It is loaded unpacked, once, by the admin (developer mode in `chrome://extensions`).
- Masking lesson values. Dev mode: "no masking for now". Lessons are files readable only by the admin (0600), as today.
- Teaching from someone else's recordings, or sharing lessons.

## Anti-goals (it would be a failure if…)

- …anything was recorded outside a Teach, outside the tab being taught, or while paused.
- …an outside site was recorded before its terms question was answered, or one marked forbidden was recorded at all.
- …the extension clicked, typed or submitted anything.
- …a taught step could not be found by the run on the same page: the steps the side panel shows must be steps the engine can do (accessibility role and name, as page files hold today), not something only the extension understands.
- …anything other than the GOV-AIOS panel on this Mac could talk to the extension or send it lessons, or a web page could read what was recorded.
- …a submit-level press happened on an outside site, or on the admin's own app without the first-run grant for that exact app version.
- …a lesson changed a flow, page file or the answer bank without the one Touch ID at Approve.

## Constraints

- **The extension talks only to the panel on this Mac** (`http://127.0.0.1:8765`), never to the internet.
- **Teaching stays connected** (agreed 2026-11-12). The extension is connected to GOV-AIOS once, with the panel's 6-digit sign-in code, and stays connected until the admin disconnects it in Studio. It records only while a panel session is signed in. If the session ends mid-lesson (30 minutes, screen lock, sign-out), recording pauses, the lesson so far is kept, and it resumes when the admin signs in to the panel again. The emergency stop pauses it the same way.
- **The extension's code lives in this repo** (`extension/`), Chrome Manifest V3, plain JavaScript and HTML with no framework and no build step, as the panel is plain server-rendered HTML.
- **The panel stays as it is built**: server-rendered HTML in `govaios/audit/web.py`, no JavaScript framework.
- **Lessons become what lessons become today**: page files in `pages/`, flow steps in `flows/`, bank keys in `answers.yaml`, through `govaios/lessons.py` (`propose`, `build`, `apply`), approvals bound to digests (`govaios/approvals.py`), audit entries in the existing audit log.
- **Terms** use `govaios/terms.py`. The waiver is new: a fourth kind of entry beside allowed / forbidden / unclear, with the admin's note, the same 90-day age limit, and a way to withdraw it.
- **Running stays AX-driven**; the risk levels are the existing ones (`read`, `navigate`, `modify`, `submit`, `payment` in `govaios/policy.py`).
- Single admin per laptop; no accounts.

## Rules settled after the design review (2026-11-12)

The admin passed on a review of this design; these rules answer it. Where they differ from a line above, these win. *All are my calls unless marked as the admin's.*

### 1. Repeats

- **An item** is the list entry (row, card or list item in the accessibility tree) that contains the target of the repeat's first step: the profile card holding **Review**.
- **Each round re-finds the list**: go to the list page, take the **first** item that still has the first step's target, do the steps. Never an index kept from the round before: on a shrinking list an index skips items.
- **None left** means the list page is shown (its page check passes) and no item has the target, including an empty-state message ("No profiles"). Only the items on the page as shown count: no paging, filtering or scrolling to find more.
- **N is a cap on successes** (default 10). The cap stops a repeat that never shrinks.
- **A failure on one item stops the run** and reports which item failed, by the item's visible label (the profile's name), with the rounds that succeeded before it. It is not retried or skipped.
- **The audit log** gets one entry per round with the item's label and outcome, as clicks are logged today: the admin's own data, unmasked in dev mode.
- In the flow this is one new repeat step whose rounds re-find the list as above. It is not today's `select_items` + `for_each_item`, which pick items up front.

### 2. Matching what the extension sees to what a run clicks

- **The mechanism:** the extension reports each action with the element's role, accessible name and on-screen box. GOV-AIOS reads the tab's accessibility tree at that moment (as `govaios/observer.py` does) and records the matching accessibility element as the step's target, in the page-file form runs already use.
- **A spike comes first, with this bar to pass. All of it must pass on JobLens before anything else is built:**
  - It matches **Discover**, **Shortlisted**, **Review** and **Approve & promote** (all four, not one of them).
  - Each match is still found by the engine after a fresh load of the same page (the page reloaded between Teach and Run).
  - When two elements share a role and name (every card's **Review**), it records a stronger anchor: the containing item, or the nearest heading. The run then finds the intended one, and the repeat's "first item that has Review" works.
- **Ambiguous at Teach time:** if the stronger anchor still matches more than one element, the side panel asks the admin which one they meant, by highlighting the candidates.
- **No match at Teach time:** the step is **not saved**. The side panel says *"Run could not find this. Do it again, or skip it,"* so a lesson never holds a step a run cannot do.

#### Spike result (2026-11-12, `spikes/plan6/match_spike.py`, run by the admin on JobLens)

**Final verdict: SPIKE PASS** (option A, commits `b45ede9` and `2a97ac5`). Every part of the bar passed:

- **The mechanism that passed:** the extension's content script reports each `pointerdown` (capture phase) with the screen point, tag, role and visible name, never values. GOV-AIOS reads the element under that point (`desk._hit`), then takes a snapshot (`web_root`) and climbs to the nearest clickable role (`link`, `button`, `tab`, `radio`). It reads the element 9–17 ms after the press and takes the snapshot 23–54 ms after it. Every read finished **before the release**, with normal quick clicks. The name GOV-AIOS read equalled the name the page reported on every click.
- **Recorded steps:** `{role: link, name: Discover}`, `{role: tab, name_matches: '^Shortlisted \(\d+\)$'}`, `{role: button, name: Review, index: 0}`, `{role: button, name: "Approve & promote"}` (read, never pressed). All four were found exactly once after Cmd-R.
- **Anchor:** 2 Review buttons for 2 Shortlisted profiles, each in its own `row`; the recorded Review is the first row's.
- **A bug found and fixed on the way:** Chrome lists every table cell twice, under its row and again under its column (`AXColumn`). The snapshot saw 4 Reviews for 2 rows. `MacDesktop._snap` no longer goes into `AXColumn`s (`2a97ac5`), so the cells are read once, under their rows. Indexes counted over a table changed with it.
- A press on empty page space reports no name and is ignored.

Earlier runs, with what each failure taught:

- ✅ **The side panel is not read by mistake.** Chrome shows two web areas (`JobLens` and `chrome-extension://…/sidepanel.html`); `web_root` picked the JobLens page at every check.
- ✅ **Discover** (`{role: link, name: Discover}`) was recorded and found again after Cmd-R.
- ✅ **Approve & promote** (`{role: button, name: "Approve & promote"}`) was read inside the Review pop-up and found again after Cmd-R + Review. Review opens a pop-up (`role=dialog`, `aria-modal`) on the same address, `/discover`. The page behind it stays readable, and each profile is a table `row`.
- ❌ **Review was missed by the observer's polling.** It was recorded once, when the admin held the mouse down for a second (`{role: button, name: Review, index: 0}`), and missed on other clicks. A normal click starts and ends between two looks. By the next look the pop-up covers the point, and the button's own label has changed to "Close". **Decision: the element must be read at the moment the mouse goes down.** The observer-only ruling in plan 1 is withdrawn; how to catch that moment is the admin's choice (below).
- ❌ **Shortlisted** was recorded as `Shortlisted (4)` and found 0 times after the reload. The count is part of the tab's name, and it changes. **Decision:** a name that ends in a count `(n)` is saved as `name_matches: '^Shortlisted \(\d+\)$'` (already supported by `engine.matches`), never as the exact name.
- Also seen: Review and Close were rated `submit` (today's "every button is submit" guess). That is expected; rule "Which presses are submit-level" replaces it.

### 3. Connecting the extension (pairing)

- **The 6-digit code is used once.** It is checked like a panel sign-in code (the same verifier, so replays are refused) and exchanged for a long random token. The code is never kept or reused as the token.
- **The panel keeps only a hash of the token**, beside its other state. The extension keeps the token in its own storage, out of reach of web pages.
- **Only the extension talks to the panel's extension endpoints:** every call carries the token in a header (not a cookie), and the panel also checks that the call comes from the extension ID recorded at pairing (`chrome-extension://<id>`). The extension's ID is fixed by a key in its manifest, so it is the same after a reload.
- **The extension talks only to `http://127.0.0.1:8765`**, a fixed address. Any other address, including other localhost ports, is refused. If the panel is not running, the side panel says so and records nothing.
- **Pages cannot reach it:** recording runs in the extension's content script, which sends events only to the extension's own background worker. It never listens to messages from the page, and the page never sees what was recorded.
- **One connection at a time:** connecting again, from another Chrome profile or after reinstalling, replaces the old connection and invalidates its token.
- **Disconnect** (in Studio) deletes the token hash on the panel and the token in the extension the next time it calls. It also **ends any open lesson, and the lesson's recording is deleted**: a disconnected extension can never resume it.

### 4. The Touch IDs a new app meets: separate, never merged

1. **Try it** (optional): one Touch ID tied to the exact draft. It allows that one Try-it run only.
2. **Approve**: one Touch ID for the whole lesson. It writes the pages, steps and bank changes and approves the app's new version (today's `approve_lesson`).
3. **First-run press grant** (only for an app that presses submit-level buttons on the admin's own apps): one Touch ID on its first run, just before the first press, listing every such button by name. It is stored apart from the approval, tied to the app's digest, and asked once per version.

Approve never implies the press grant, and the press grant is never asked twice for the same version. The Touch ID prompt names which of the three it is.

### 5. Try it

- **It runs on the real pages and real data.** Before it starts, the side panel says what it will open, for example *"Try it will open one real profile on JobLens. It will not approve it."*
- **It stops before any submit-level or payment-level click**, never after it, naming the button: *"Try it stops here: the real run will press Approve & promote."*
- **A second safety net:** Try it also stops before any button whose name looks change-making (the list in "Which presses are submit-level"), even if the step was marked `navigate`. A mis-rated step cannot change data during Try it.

### 6. Where an unfinished lesson lives

- **The panel writes each recorded event to the lesson file on disk as it arrives** (under `lessons/`, 0600, as today). The extension holds only the lesson's id. A panel restart or a Chrome restart loses nothing already recorded.
- **There is one open lesson at a time.** After a pause or a session end, **Resume** in the side panel continues that same lesson, on whatever tab the admin presses it in. Studio also lists the open lesson with **Resume** and **Discard**.

### 7. Pause

- **Pause removes the detour from the lesson; it does not hide it.** Nothing is recorded while paused, no page visited while paused becomes part of the lesson, and no terms question is asked while paused.
- **On Resume**, if the tab is on a different page from where the admin paused, the lesson gains a step that opens that page by its address (without the query part, as lessons store addresses today). If the page is on an outside site, its terms question is asked first.

### 8. Add to an app

- **Teach this page** (from a stopped run) adds the new steps at the step where the run stopped.
- **Add to an app** (at Done) adds them **at the end** by default. The admin can pick an earlier point ("after step: open Shortlisted") from the app's steps, listed in the side panel.

### 9. Typed text

- **The side panel uses `lessons.py`'s answer-bank logic** (its proposal of bank fields); it does not add a second one. The admin's choice for a field is recorded in the step and wins on later runs.
- **"Always this text"** keeps the literal value. Later changes to the bank do not affect it.
- **"From my answer bank"** reads the bank on every run, so changes to the bank are picked up.
- **"Asked at Run"** becomes an input the Run form asks for, as apps with inputs do today.

### 10. Page reuse

- **The match key is the page file's own identification** (its `title_matches` and `anchors`), as runs already use for checking which page they are on.
- **Exactly one known page matches:** it is reused, with no question.
- **More than one matches, or none matches but a known page has the same site and path:** the side panel asks *"This looks like JobLens · Shortlisted. Reuse it?"*, listing the candidates, or **New page**.
- **None matches and no path is shared:** it is a new page.

### 11. The page count toward 100

- **The count** is the number of approved page files, each counted once, however many apps use it.
- **Renaming a page** changes its shown name, not its file id, so it is not counted twice.
- **Drafts and pages waiting for approval** are shown beside the count ("+3 waiting") but are not counted.
- Studio shows the count per site and the total.

## Plan 2 result (2026-11-13, run by the admin on JobLens, PR #35)

**Build steps 2 and 3 work end to end.** The admin paired the extension, taught Home → Discover → Shortlisted → Review → Close → Review → Close, pressed Done, named the app, approved its lesson with one Touch ID, and pressed Run: every taught click ran, through to the end.

Found and fixed while testing:

- **Pairing did not stick:** Chrome sends no `Origin` on the extension's GET, so the token was dropped. `/ext/state` is a POST (`27754f8`).
- **A refused button's note vanished** on the next poll (`b7db7e3`).
- **Teach stopped at once:** the panel's run launch takes the focus from Chrome. Teach brings Chrome to the front before pinning its window (`c209bfa`).
- **The empty Draft was approved instead of its lesson:** signing in from the lesson tab lands on Home, and Approvals offered the bare Draft. A Draft with a waiting lesson now links to the lesson (`2a80b95`).
- **A page visited twice merged its visits:** Discover → Applications → Discover became one Discover list that left the page midway. A page visited again keeps only the clicks of its last visit and moves to the end (`6681a2c`). Studio apps can be deleted from Apps with Touch ID (same commit, the admin's request).
- **A click inside the Review pop-up failed the page check:** the modal hides the page's `Discover` heading from the accessibility tree. Within a taught page's steps, the same URL and title count as the same page (`224f445`).

Seen, not changed: lessons end with an automatic **hand-over** card on the last page, which a click-only lesson does not need (decided in plan 3). Shortlisted showed 2 profiles, not 4: JobLens screens posted listings by score, so not every refill lands there (plan 3's refill script reports where each one went).

## Plan 3 result (2026-11-13, run by the admin on JobLens)

- **Press grant: passed.** MoveDroppedToShortListed (Discover → Dropped → Review → Approve & promote, taught twice) asked one Touch ID, "Let '…' press Approve & promote", then pressed Approve & promote on both profiles itself and ended `done`. JobLens moved them from Dropped to Promoted.
- **Fixed during the run:** End on a hand-over card stopped with "input refused: focused window is not the verified window": the engine brought Chrome forward before stopping. End now stops without doing that (`d73a1eb`). The first runs were on the morning's build, which still turned Approve & promote into a hand-over.
- **Not yet run live:** Repeat (the box wasn't ticked; the two rounds were taught one by one), a second run asking no grant, and Try it.

## Build order

1. **Spike:** matching on JobLens Shortlisted, with the bar in rule 2. If it fails, stop and come back to the admin.
2. **Pairing**, and pausing and resuming when the panel session ends (rules 3 and 6).
3. **The first lesson without the repeat:** Teach, the side panel's steps, the YAML tab, Done, New app, Approve.
4. **Repeat** (rule 1).
5. **The first-run press grant and Try it** (rules 4 and 5), plus the test-only script that refills Shortlisted.
6. **Teach this page, terms and waiver, Studio grouping, page reuse and the page count** (rules 8, 10 and 11).

The first lesson works end to end after step 5.

## Left to the builder

- How the extension gets permission to watch pages (all sites, or asked per site), as long as the anti-goals hold.
- The flow syntax of the new repeat step, and how the run asks for the first-run grant (a Home card, as other run questions are) and where the grant is stored, within rules 1 and 4.
- The lesson file shape for a new app (today's `lessons.save` needs an existing flow id).
- The side panel's look, following the panel's existing style.
