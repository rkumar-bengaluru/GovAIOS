# JobLens tasks, SyncJobLens rename, Web Sandbox — design (2026-11-08)

Built overnight on branch `feat/joblens-tasks` from the admin's Diwali brief. Not yet run live.

## What the admin asked for

1. The last run guided them when a field failed; they fixed it in Chrome and pressed Continue. Keep that: it is Studio in the making.
2. The Talk window was not the real goal. The real flow:
   - JobLens (their app, `http://localhost:8100/`) opens on Applications, the jobs they approved.
   - A job's page has Apply, which leads to Himalayas, then to the employer's form (Greenhouse today; other sites later, fixed the same way).
   - Each job is its own task in Talk, with its log and a link to the page where they fix things and press Continue: HITL per job.
3. A web sandbox: take any site that allows a personal agent, test it and build flows for its pages.
4. Rename the app that reads Himalayas and pushes the first 10 to JobLens to **SyncJobLens**. The apply app becomes **JobLens**.
5. JobLens is where they approve the jobs to apply to: the morning routine.

## What was built

### Rename
- `flows/himalayas_job_vetting.yaml`: `app: SyncJobLens` (slash `/syncjoblens`). Nothing else changed in that flow.
- `flows/job_apply.yaml`: `app: JobLens` (slash `/joblens`). The flow id stays `job_apply`, so approvals history, audit, captures and the bank keep working.
- Marketplace titles updated; a new Web Sandbox template.
- Both flow files changed, so both need approving again once (digest-bound).

### JobLens app (`job_apply` v2)
Steps: Chrome, then the Google account check, then JobLens Applications. It picks every row whose Status is **Ready**, up to 10, and runs one **task** per job:
1. new tab, JobLens list, click the job's Role link;
2. job page, click **Apply** (JobLens downloads the tailored CV and opens the job link in a new tab);
3. Himalayas, as before: Apply now, the "I'm ready to apply" popup, the Greenhouse or Lever form;
4. fill from the bank, with the "fix it in Chrome" card on any failed field;
5. attach the CV (Touch ID);
6. **review card**: "Ready for you to submit". The admin checks the form in Chrome, submits it there, then presses **Next job** (or **End**).

If a step inside a job stops (unexpected page, a site not in the flow, a field the run can't find), only that task stops:
- the page is captured;
- the task is marked Stopped with the reason;
- a **"This job stopped"** card offers Next job or End.

Safety stops still end the whole run: emergency stop, locked screen, revoked flow, no answer in 15 minutes, a bad reply, a refused input other than a covered click point, and no Chrome window in front.

Each job runs in its own tab, so an earlier job's form stays exactly as the admin left it. Nothing is ever closed or navigated away from under them.

### Panel
- **Talk** shows a "JobLens jobs" card: `1. Client — Role · Done / Working / Needs you / Ready to submit / Stopped / Not started`. Each row links to `/apply/task/<n>`.
- **Task page** `/apply/task/<n>` shows:
  - status, filled X of Y, the "fill yourself" and "check" lists, and the stop reason;
  - the card waiting for this job, if any;
  - the job's own log: audit lines tagged with `item=<n>`.
  It refreshes every 3 seconds while the run is live and no card is waiting.
- One card renderer for all run cards (`applyfiles.CARDS`): fix (Continue/Skip), review (Next job/End), stopped (Next job/End), sandbox (Capture this page/Done). Replies are checked against the card's own choices. Audit kind `apply_card` records the choice and the item. Each card is spoken once.
- The old single-form result card is hidden on runs that have tasks.

### Web Sandbox (`flows/web_sandbox.yaml`)
- It takes a run-time input `site`. The link must be https, without user info, and match the input pattern.
- It opens Chrome, checks the Google account, then opens the site. The site's origin is added to the run's destinations in memory (`destination_inputs`). Like any destination, its first contact asks for Touch ID and is remembered per flow.
- It is **read only**. Allowed actions: launch, navigate, read_page, ask_admin. It never clicks or types on the site.
- It shows a card loop. The admin browses in Chrome, then presses **Capture this page** to save the page (unmasked, dev mode) under `captures/`. The panel lists each page with its counts of fields, buttons and links. **Done** ends it.
- A page on another origin is never read. It is listed as "another site: not captured".
- Claude reads the captures and writes the page and flow YAML. This is the Studio loop done by hand for now.

## Calls I made (the admin was away — check these)

1. **"Approved" means Status = Ready** in JobLens (a finalized CV, so the job page has Apply). Draft and In review rows are skipped, and so are Submitted and later. One line in `pages/joblens_applications.yaml` (`has_text: "Ready"`) changes this.
2. **Up to 10 jobs per run**, in the list's default order (Newest first).
3. **CV**: still the bank's `cv_file`, not the tailored CV that JobLens Apply downloads to ~/Downloads. Using the tailored one is the obvious next step (backlog), but it needs the downloaded file name to be found safely.
4. **JobLens "Mark submitted" is never clicked** (rated submit). The admin marks it in JobLens.
5. **The JobLens pages were written from JobLens source code**, not a live capture. Tomorrow's first run is also their check. A mismatch stops on the JobLens step, with a capture to fix from.
6. The old `/job-apply <link>` mode is gone from the shipped flow. A Himalayas link is now reached only through JobLens. To debug a single site, use the Web Sandbox.
7. Terminal runs (no panel) do every Ready job in its own tab without cards.
8. The sandbox trusts the admin to enter only sites whose terms allow a personal agent. The terms gate (backlog Plan 3) is not built.

## Open questions for the admin

1. Should Draft and In review jobs be included too, or only Ready (my call)?
2. Tailored CV from the JobLens download instead of the bank CV: yes for the next round?
3. After Next job, should the run press JobLens's "Mark submitted" for you (a submit-rated click, so it would need its own Touch ID approval)?
