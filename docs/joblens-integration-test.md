# JobLens, SyncJobLens and Web Sandbox — live test plan (for 2026-11-09)

Design: `docs/superpowers/specs/2026-11-08-joblens-tasks-design.md`. Branch `feat/joblens-tasks`.

## 0. Install

1. Merge the PR and pull `main`.
2. Rebuild and install: `GOVAIOS_SIGN_ID="GOV-AIOS Dev" packaging/build.sh && sudo packaging/install.sh --no-claude`.
3. Copy the changed and new flows and pages into the apps folder. Install never overwrites it, and the installed copies match `main` today, so nothing of yours is lost:
   ```
   A=~/Library/Application\ Support/GOV-AIOS/apps
   cp flows/job_apply.yaml flows/himalayas_job_vetting.yaml flows/web_sandbox.yaml flows/morning_inbox_briefing.yaml "$A/flows/"
   cp pages/joblens_applications.yaml pages/joblens_job.yaml "$A/pages/"
   ```
4. In the panel, approve the four Drafts: **JobLens**, **SyncJobLens**, **Web Sandbox** and **Inbox Brief** (the morning brief's new short name). Each file changed, so each needs approving once.

## A. JobLens — one task per Ready job

You need at least one job with Status **Ready** in JobLens (`http://localhost:8100/`). Both of today's jobs are Submitted. Either sync a new one, or set WIN back to Ready:
`curl -X PATCH -H 'Content-Type: application/json' -d '{"status":"ready"}' http://127.0.0.1:8100/api/jobs/86b2b721-a84e-4b41-a218-bf41a17af31b`

1. In the panel, type `/joblens` and run it.
2. Expected:
   - Chrome, then the Google account check;
   - JobLens Applications opens and the panel shows a **JobLens jobs** card listing each Ready job;
   - for job 1, a new tab, the job page, then **Apply**. JobLens downloads the tailored CV to ~/Downloads (the run doesn't use it yet) and opens Himalayas in a new tab;
   - Apply now, then the Greenhouse form fills;
   - the CV prompt (Touch ID);
   - a **Ready for you to submit** card, spoken aloud.
3. Click the job's link in the card, or its row, to open `/apply/task/1`: status, counts and its log.
4. Submit in Chrome yourself (or don't). Then press **Next job**. The next Ready job starts in a new tab, and the earlier tab stays as you left it.
5. **End** on any card ends the run. Jobs not reached show "Not started".

If it stops on the JobLens steps (`on_joblens`, `select_jobs`, `open_job` or `open_apply`), the JobLens page files didn't match the live page. They were written from source code, so this is the most likely first failure. Tell Claude: the newest file in `captures/` has the page.

If a job hits a site the flow doesn't know (Workable, a direct company page), only that job stops. You see the **This job stopped** card: press Next job.

## B. Web Sandbox

1. Type `/web-sandbox`, enter an https link to a site whose terms allow a personal agent, and run it.
2. Touch ID asks once for the new site.
3. A **Web sandbox** card appears. Browse in Chrome to a page, then press **Capture this page**. The card lists it with its counts of fields, buttons and links. Repeat for more pages, then press **Done**.
4. Each capture also makes a **draft page** and a **Check app**. Its line on the card says "draft page …, app Check in Drafts". To confirm the draft against the live site, approve the Check app in the panel's Drafts and run it. Then tell Claude which draft pages to link into a bigger flow. Design: `docs/superpowers/specs/2026-11-08-studio-drafts-design.md`.
5. A page on another site (a login redirect, say) is listed as "another site: not captured".

## C. SyncJobLens

Type `/syncjoblens`: the same Himalayas → JobLens sync as before, under its new name.
