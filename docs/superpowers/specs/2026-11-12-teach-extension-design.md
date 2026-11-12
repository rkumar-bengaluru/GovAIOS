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

## Left to the builder

- **How a click seen by the extension becomes an accessibility element the engine can find.** The extension sees the page's DOM; runs see Chrome's accessibility tree. One approach: the extension reports each action with its element's role, accessible name and on-screen box, and GOV-AIOS reads the tab's accessibility tree at that moment (as `govaios/observer.py` does today) and matches the element there. Prove the chosen approach with a short spike on the JobLens Shortlisted page before building on it.
- How the extension gets permission to watch pages (all sites, or asked per site), as long as the anti-goals hold.
- The pairing details (what the 6-digit code is exchanged for, where it is kept, how it is revoked).
- How "repeat until none are left, at most N" is expressed in the flow (today's `select_items` + `for_each_item` pick items up front, which does not fit a list that shrinks as you act on it).
- How the run asks for the first-run grant (a Home card, as other run questions are) and where the grant is stored.
- Lesson file shape for a new app (today's `lessons.save` needs an existing flow id).
- The side panel's look, following the panel's existing style.
- The order of building, as long as the first lesson above works end to end first.
