# Control panel: Home is the chat, an Apps page, and a run queue: design (2026-11-11)

This is project 1 of 2, agreed with the admin on 2026-11-11. Project 2, the teach extension, comes next. Its agreed points are kept at the end of this document so they are not lost; it gets its own design.

## Why

- The panel will grow: tens of apps as Studio teaches pages, and many runs a day.
- Today the approved apps are listed on the left side, next to the navigation, and the Home (Talk) page is getting clumsy. The admin's words: "the task page is getting way clumsy".
- Only one app can run at a time. Starting a second one is refused ("SyncJobLens is not kicking off" on 2026-11-09, while JobLens was waiting on a card). The admin wants to press Run and not be blocked.

## Goals

1. **Home is the chat.** It stays today's Talk page, with one change: **the newest is at the top**, not the bottom. This covers talk replies, the live run's card (Teach this page · Next job · End …), the JobLens job list and results.
2. **A new navigation item, Apps.** It shows every approved app as a card, 3 per row. Each card has its name, one line about it, when it last ran, and a **Run** button.
3. **The left side lists only the navigation**: Home, Apps, Studio, Marketplace, Audit log, Approvals. The apps list that sits there today goes.
4. **A run queue.** Run, whether from an app card or typed in Talk, never refuses because another app is running. The app waits its turn and starts by itself when the run before it ends. The card shows **Running…** or **Queued #n** with ✕ to take it out of the queue.

## Non-goals

- Running two Chrome apps truly at the same moment. GOV-AIOS drives Chrome with the real pointer and keyboard on one pinned window, so two runs would fight over it and the safety checks would stop both. The queue is the agreed answer.
- Studio's new content. Studio becomes the teach extension's home in project 2; this project leaves today's Studio page as it is.
- Changes to Approvals, Audit log, Marketplace or the task details page, apart from the navigation.

## Anti-goals (it would be a failure if…)

- …a queued app started without the same checks a Run gets today: the flow is still approved with the same digest, and the admin is still signed in to the panel.
- …a queued app started after the admin pressed the emergency stop or the panel's Stop.
- …the live run's question (its card) was pushed down out of sight by newer messages. It is the thing the admin must act on.

## The pages

### Home (chat)

- The Talk box stays on top.
- Right under it is the live run's card if it has one, for example *12:51 JobLens · EVERSANA: a page this flow does not know* with its buttons. It stays pinned there while it waits, whatever arrives after it.
- Then everything else, newest first: talk replies, run started or ended, queue changes ("SyncJobLens queued #1", "SyncJobLens started"), the JobLens job list and results.
- The JobLens job list shows the newest job first.
- The admin approved the sketch, version 2 (`.superpowers/brainstorm/…/panel-v2.html`, left half).

### Apps

- A grid of approved apps, 3 per row (fewer on a narrow window), with no apps list on the left.
- Each card shows:
  - the app's name (as the left side shows it today);
  - its description;
  - when it last started, whatever the outcome (*my call*);
  - one button: **Run**, **Running…** (links to Home), or **Queued #n ✕**.
- Apps that take inputs open the same input form a Run uses today, then queue or start.
- After Run, the panel goes to Home, where the run's messages appear at the top.
- Only approved apps appear here. Apps waiting for approval stay on Approvals; drafts stay in Studio.
- The admin approved this from the sketch, version 2 (right half).

## The queue

- It is kept in the panel's memory, in order, and is not kept across a panel restart. *My call: a restart is rare, and a queue that restarts runs by itself after a reboot would be a surprise. No message is shown after a restart, since there is nothing to report.*
- Run while nothing is running starts the app at once, as today. Run while something is running adds the app to the end of the queue and says *"<app> queued #n"*. The same app can be queued only once.
- When the live run ends, however it ends (done, stopped, or **End** on its card), the next app in the queue starts. *My call: End means "end this run"; Stop means "stop everything".* Before it starts, it goes through today's Run checks: the panel is signed in, the flow is approved and its digest is unchanged. If a check fails, that app is dropped with a message on Home, and the next one is tried.
- The **emergency stop**, the panel's **Stop**, a **sign-out** (the browser's or the screen lock's) and the **end of the 30-minute panel session** empty the queue, and Home says so. A queued start needs a live panel session, as a Run does today: queued apps never start with nobody signed in. *My call.*
- An app queued with inputs keeps the inputs it was given. They are checked when it is queued, as a Run checks them today. *My call.*
- A queued entry holds no ticket. Its ticket is made when it starts, so the digest check is fresh. *My call.*
- Only apps (flows) are queued. Claude Code and Codex sessions started from Talk are not Chrome runs and stay as they are. *My call.*
- ✕ on a queued card, or "unqueue <app>" in Talk, takes it out of the queue.

## Constraints

- Everything stays in today's panel stack: server-rendered HTML in `govaios/audit/web.py`, its CSS, no JavaScript framework, and the existing auto-refresh.
- The run checks, tickets (`tickets.create`), Touch ID rules and audit entries stay as they are. A queued start is audited like a normal start, with "queued" noted.

## Left to the builder

- The card style (it follows the panel's existing `appcard` look) and how "last run" is read from the audit log.
- Where the queue lives in code and how the end of a run triggers the next start.

---

## Project 2, agreed so far: the teach extension (for its own design)

Points the admin agreed on 2026-11-11, so they are not lost:

- **A GOV-AIOS extension in Chrome**, in the admin's own profile (Profile 2). It uses Chrome's side panel. Option 1, a GOV-AIOS browser, was dropped: sign-ins would be lost, Google blocks embedded sign-in, and it would take months.
- **Start and end are the admin's, and visible.** **Teach** in the side panel; a red **● Recording** sign on the page; **Pause** for things not to record (logging in); **Done**; **Cancel**.
- **The side panel shows plain steps page by page, with a YAML tab.** A repeat shows its count to edit ("repeat for the first [10] cards").
- **Pages a flow already knows plug in their steps** (reuse). Pages are named automatically from site and title.
- **At Done**: **New app** (named) or **Add to an app**, for example SyncJobLens with a new first step.
- **Show me**: highlights each step's target on the real pages, without clicking or typing. **Try it**: one real run of the draft through the normal checks; it cannot submit, goes only to the lesson's sites, and needs one Touch ID tied to the exact draft. Then **Approve**: one Touch ID for the whole lesson.
- **Terms**: the admin's own apps (localhost) need no check. An outside site asks once, in the side panel, with three choices: allowed (clause), forbidden, or **no terms found: I'll go ahead** (a waiver with the admin's note, saved as "waived by you", 90 days, can be withdrawn).
- **Runs stay as they are**: Chrome, driven through the accessibility tree. The extension only watches and highlights; it never clicks.
- **Studio in the navigation becomes the extension's home**: lessons, drafts, Show me, Try it, Approve. Today's Studio pages and the panel's Teach card go.
- Target volume: about 100 pages in a week, at least 10 pages per app.
