# Job Apply under GOV-AIOS: integration test

Status: **built on branch `feat/job-apply`; live tests A–G not yet run (admin).** Spec and plan:
`docs/superpowers/plans/2026-11-07-job-apply.md`.

## What it does

You paste a Himalayas job link in the control panel (`/job-apply <link>` in Talk, or the **Job Apply** card).
The run:

- opens the job, clicks Apply, and lands on a Greenhouse or Lever form;
- fills the form from your answer bank (`apply/answers.yaml`, edited at `/apply/bank`);
- for a question the bank can't answer, shows an **answer card** in the panel. It waits up to 15 minutes.
  You can tick "save to my bank" to keep the answer;
- attaches your CV after Touch ID (every time, never remembered);
- shows a **result card** (filled of total, "fill in Chrome yourself", "check"), and **stops before Submit**.
  You review and submit. If the run stopped early, the card says so: check the form in Chrome.

Fields it can't fill or read back are left for you ("fill yourself"). Nothing is ever submitted by GOV-AIOS.

The bank format (invented example values):

```yaml
cv_file: ~/Documents/cv-example.pdf   # must be inside your home folder
answers:
  - key: full_name
    labels: ["Full name", "Name"]
    answer: "Alex Example"
  - key: notice
    labels: ["Notice period"]
    answer: "30 days"
```

## Set up (admin)

1. Rebuild and install: `GOVAIOS_SIGN_ID="GOV-AIOS Dev" packaging/build.sh`, then
   `sudo packaging/install.sh --no-claude` (the root step).
2. Panel: approve the **Job Apply** app (`job_apply`) with Touch ID.
3. Open `/apply/bank`, enter your answers and `cv_file`, save.

## Live test

Use Chrome with the Himalayas page signed in as you normally are. Use real job links; below they are
placeholders: `https://himalayas.app/companies/<company>/jobs/<job>`.

**A. Greenhouse job.** Pick a job whose Apply leads to Greenhouse. In Talk: `/job-apply <link>`. Expect: the
form fills from the bank; a question not in the bank shows the answer card (answer it once with "save to my
bank" and once without). Before sending, type an answer and wait 10 s: it must still be there (the page doesn't
reload while the card shows). Touch ID is asked before the CV attaches; the result card shows filled of total,
what to fill yourself and what to check; the run stops with Submit untouched.

**B. Lever job.** The same on a Lever job (`jobs.lever.co/<company>/<id>/apply`).

**C. Workable job.** Expect the run to stop with "unexpected page" and touch nothing.

**D. Emergency stop.** Start a run, wait for the answer card, press **ctrl+option+cmd+.** The run must stop and
its temporary files must be removed. Clear the stop from the panel. Repeat twice more, stopping (1) while the
CV Touch ID prompt is up and (2) right after the file sheet closes. Each time the panel must say the run
stopped (not "finished"), and the result card must say the run stopped and list Resume/CV under "fill in Chrome
yourself" unless it was attached.

**E. Audit.** Panel → Audit log: each fill shows its source (bank or your answer) and no values.

**E2. Logged out.** Log out of Himalayas in that Chrome profile and run `/job-apply <link>`. Expect the run to stop
on the job page and ask you (Touch ID) to log in and resume; nothing is clicked. Log back in after.

**F. New tab or new window.** Note whether Himalayas' Apply opens a tab or a window. A window stops the run
(see Known gaps); report which you saw.

**G. Regression.** From Talk run the Gmail brief and Himalayas → JobLens, then start `/claude` and `/codex`.
All four work as before, with no new approval prompt (their flow digests are pinned by
`test_existing_flow_digests_unchanged`).

## Things to know while testing

- A pasted link with `?utm...`, a `#fragment` or a trailing `/` is trimmed before it is checked.
- A select's placeholder ("Select...") is never offered as an answer.
- A dropdown drawn outside the form goes to "fill yourself".
- `cv_file` must be inside your home folder. At run time any symlinked CV is refused (even one pointing inside
  home, e.g. a synced or aliased folder): point `cv_file` at the real file. A missing file is allowed in the bank,
  but the run then leaves the CV for you.
- The bank page refuses edits over about 60 KB, and shows a message rather than saving part of it.
- An unfocusable combo box stops the run; a combo whose text doesn't match the read-back goes to "fill yourself".
- The CV check follows "No file chosen": any other text in the file field counts as attached.
- Bank answers are read at the start of the run; answers you save mid-run apply from the next run.

## Recovery

Run misbehaving: emergency stop (ctrl+option+cmd+.), then clear it in the panel. Close the form tab; nothing
was submitted.

## Known gaps

- No CAPTCHA detection. An earlier challenge makes a fill fail its read-back, so that field goes to
  "fill yourself".
- Disabled fields and character limits aren't detected; a failed read-back sends the field to "fill yourself".
- The CV is attached as a file only. Greenhouse's paste mode isn't supported.
- A run started from the CLI (no ticket) never asks; pending fields go to "fill yourself".
- If Himalayas' Apply opens a new window, the pinned-window check stops the run (test F shows which happens).
- Lever Apply links seen go straight to the form, so there is no Lever posting page.
- `/job-apply` takes a pasted link, not a JobLens list (the panel sandbox has no outbound network).
- Fragile steps, unverified until tests A and B:
  - the combo (react-select) option click, and where its option list is drawn;
  - Chrome's native select menu;
  - the macOS file sheet (Go to Folder; Escape on refusal);
  - whether the Lever file field's text changes after a real attach.
