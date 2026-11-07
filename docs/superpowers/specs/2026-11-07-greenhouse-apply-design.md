# Apply to a JobLens application on Greenhouse, from Talk: design

Status: draft for admin review (2026-11-07). Nothing built.

## Why

The admin's goal is to hand routine work to agents safely. In the job pipeline, Himalayas vetting and JobLens
delivery are already governed. The step left by hand is the most tedious one: filling in each company's
application form. A JobLens application's Apply link goes to its Himalayas page, whose Apply goes to the
company's application system (Greenhouse in the admin's example), where the form is filled in and submitted.

## Goals

- From Talk, one application at a time: pick a JobLens application, and GOV-AIOS opens its form and fills
  it from answers the admin wrote in advance.
- Questions it can't answer come back to the admin as a Talk card. The admin may save an answer for next time.
- It stops before Submit. The admin reviews the form and presses Submit themselves.
- Everything is audited: the application, which fields were filled from the bank, which the admin answered.
  Answer values are never logged.

## Non-goals (v1)

- Batch runs over several applications (admin: later).
- Application systems other than Greenhouse (Lever, Ashby, Workday: later).
- AI-drafted answers, auto-submit, marking the application submitted in JobLens.

## Anti-goals (a failure even if it works)

- Any form value that doesn't come from the admin: from the bank, or typed into the card.
- Any AI model choosing what goes in a field. Label-to-answer matching is a fixed rule (see below), so text on
  a page can't steer it. This keeps the research claim of no model in the run-time loop.
- Submit, or anything rated `submit` or `payment`, pressed by GOV-AIOS.
- Data sent to a site that isn't on the flow's destination list.

## Decided (admin)

- Answers come from a bank the admin prepares. Most questions are standard; the few that differ come back to
  the admin.
- One at a time from Talk first; batch later.

## How it works (designer's calls unless marked)

**Answer bank.** A file in the GOV-AIOS data home, `apply/answers.yaml`, mode 0600, which agents can't read
(managed deny on Claude Code and Codex). Each entry has a key, the answer, and the labels it matches. For
example: key `notice_period`, labels "Notice period" and "When can you start?". The panel shows and edits it,
always as text the admin typed. Values never go into the audit log, a flow file or a run report.

**Matching.** Normalise a field label (lower case, collapse spaces, drop punctuation and a trailing `*`), then
look for an exact match against the bank's labels. Nothing fuzzy and no model. If a label matches more than
one entry, the field goes to the admin. Field type must agree: a yes/no answer goes only into a checkbox,
radio group or yes/no select.

**Voluntary demographic questions** (gender, race, veteran, disability) are never filled from the bank. They
always go to the admin.

**Talk.** `/apply` shows a card listing JobLens applications that have a `jd_url` on himalayas.app, filled
from the JobLens API on 127.0.0.1:8100 the same way delivery reaches it (`govaios/delivery.py`). The admin
picks one and presses Start. During the run, a card lists the fields it couldn't fill: the field's label,
an answer box, and a "save to my bank" tick. The run waits for those answers. At the end a card says "Filled
N of M fields. Review the form in Chrome and press Submit yourself."

**Flow** `flows/greenhouse_apply.yaml`. App JobLens; the same Chrome profile and account check as the
Himalayas flow. Destinations are `https://himalayas.app` and `https://job-boards.greenhouse.io`. The
Himalayas Apply button is rated `navigate`, and following it must land on the Greenhouse host or the run
stops. `max_element_risk: modify`, so Submit (`submit`) can't be pressed.

Steps:
1. Open the job's Himalayas page.
2. Classify the page, then follow Apply.
3. Classify the page as `greenhouse_application`, matching the page shell captured once.
4. Read the form's fields.
5. Fill the fields that matched.
6. Ask the admin about the rest.
7. Attach the CV.
8. Report, then leave the window open for the admin.

**New engine pieces.** Today the engine can click, navigate, read and extract, nothing else.
- `read_form`: collects editable fields, each with role, label and options, from the Accessibility tree
  inside the page's form region. It reads only; field values are not recorded.
- `fill_field` (risk `modify`): focus the field and type or choose the value. It works only on fields that
  `read_form` returned in the same run.
- `ask_admin`: stops at a Talk card and waits with a timeout (designer's call: 15 min, then stop and report).
- `attach_file` (risk `submit`-equivalent for approval, see open items): press the CV field's Attach button,
  then in the macOS open panel type the path with cmd+shift+G and press Enter. Only the CV file the admin
  set in the bank is allowed.

Greenhouse forms vary by company, so the page schema covers the shell only: page title area, the form
region, the Submit button rated `submit`. Fields are discovered at run time but have to be inside the form
region, and their values only come from the admin. This is a departure from fully pre-captured page schemas,
and the paper has to say so.

**Approval.** The flow is approved once like other flows (Touch ID). Per run, the first fill on a new company
form needs no extra prompt. Attaching the CV needs Touch ID every time: the file leaves the Mac as soon as
it's attached.

**Audit.** Each fill logs `field label`, `source: bank:<key> | admin`, `decision`. The value is never logged.
Unfilled fields and the end state are logged too ("stopped before Submit").

## Left to the builder

- Where the card wait lives (panel state plus runstate), within the existing run model.
- The exact AX roles for Greenhouse fields, from one capture.
- Tests: label normalisation and the ambiguous-match rule; the type-agreement rule; the demographic rule; no
  value in the audit or the report; `fill_field` refuses a field `read_form` didn't return; Submit can't be
  pressed; a destination outside the list stops the run.

## Settled after the builder check (designer's calls)

- **Attach risk.** The Attach button is rated `modify`, so the `modify` cap and "Submit can't be pressed"
  both still hold. `attach_file` is its own permission, and every use asks for Touch ID (like `deliver`).
  Submit is the only `submit` element.
- **CV path.** The bank holds the path, and it's treated like any answer: never logged or reported. At run
  time it must be a regular file under the user's home, not a symlink. If it's missing, attach is skipped and
  the final card says "attach your CV yourself".
- **Fields never auto-filled**, whatever the bank says: secure text fields; labels that normalise to
  password, SSN or national ID, bank or card; and consent or attestation checkboxes ("I certify…",
  "I agree…"). They always go to the admin.
- **Site terms** (checked 2026-11-07). Greenhouse publishes no candidate or job-board terms of use. Its legal
  index lists customer documents (master subscription agreement, data processing addendum) and privacy
  notices only. Its privacy policy says it "does not apply to the Personal Information collected and used by
  Greenhouse customers … such as when you apply to a job via a Greenhouse-hosted job board". So each
  employer's own notice governs. No clause was found that forbids a candidate filling in their own form with
  help. That is silence, not permission like Himalayas cl. 30A. The flow records it as
  `site_terms: { reviewed: 2026-11-07, basis: "no candidate terms; employer's notice governs; admin submits" }`.
  Greenhouse is reported to use bot protection; the admin pressing Submit keeps that check with a human.
- **Conditional fields.** After the fills, run `read_form` again. New fields go through matching, at most
  3 passes, then whatever's left goes to the admin.
- **Unsupported field types** (multi-select, date, other file fields, anything not text, choice or checkbox):
  not filled, and listed on the final card as "fill in Chrome yourself". Admin cards support text and
  single choice only. A field with a character limit gets a bank answer only if the answer fits; otherwise it
  goes to the admin.
- **Hidden, disabled or off-screen fields** are skipped; only fields inside the form region count. A form
  split over several pages is out of scope for v1: the run fills page one and stops.
- **The wait.** The run keeps its lock and the Chrome window for up to 15 min, then stops and reports. The
  bank is read once at the start. "Save to my bank" entries are written when the run ends, with this form's
  label added. Each save is audited as `bank_updated <key>`, without the value.
- **New tab.** If Apply opens a new tab or window, the engine follows the focused window. A host off the
  list stops the run and reports.
- **CAPTCHA.** If the page shows one, a card asks the admin to solve it in Chrome and press Continue. It
  never gets solved automatically.
- **Form region.** The page schema gains a `form_region` element. `read_form` and `fill_field` only act
  inside it. This adds to classify and policy, so it's planned as its own task.

## Open items

- Whether Greenhouse shows a CAPTCHA, and the real AX roles of its fields: from the first capture.
- CV attach through the macOS open panel is the most fragile step; the fallback is above.
- Some companies host Greenhouse on their own domain (an embedded form). v1 stops on any other host.

## Capture findings (form 1 of 3, 2026-11-07)

Read-only `gov-aios dump` of one Greenhouse form, untouched, Touch ID; summary of roles and labels only.

- 19 of 19 fields have a label and a DOM id: 6 text fields, 13 dropdowns exposed as `combo_box`. Custom
  questions use ids like `#question_<10 digits>`; standard ones `#first_name`, `#email`, `#resume`.
  `fill_field` anchors on id plus label, not label alone.
- CV: `#resume` has Attach, Dropbox, Google Drive and **Enter manually** (paste text). Pasting avoids the macOS
  open panel; the cost is that the employer gets plain text, not the PDF. Designer's call: v1 offers both,
  and the admin picks once in the bank.
- `Submit application` and `Autofill my application` (MyGreenhouse) are named buttons; both are rated
  `submit` and never pressed.
- No CAPTCHA node before submit.
- A dropdown's options aren't in the tree while it's closed, and it closes when focus leaves Chrome, so a
  manual open-then-dump shows nothing. So: fill a dropdown by typing the bank answer into it, pressing Enter,
  and reading the value back. If the value read back isn't exactly the bank answer, clear it and send the
  field to the admin.
- Greenhouse's public job-board API (`boards-api.greenhouse.io/v1/boards/<board>/jobs/<id>?questions=true`)
  returns the same questions, with matching field names and their options. Options are company-specific (CTC
  bands, notice-period ranges, regions), so a bank answer only fills a dropdown when one option matches it
  exactly; otherwise the field goes to the admin. The runtime doesn't call this API: that would add a network
  path outside Chrome. It's used only as an oracle when testing.

## Other systems seen (2026-11-07)

Of the four applications the admin tried, Apply landed on Greenhouse once, Workable once and Lever twice. So
v1 can't be Greenhouse-only in practice.

- **Lever** (`jobs.lever.co`): terms checked. Lever's Terms of Service (last updated 2023-08-25) cover its
  customers only and say nothing about bots or automated access. Its job-seeker page says the employer "uses
  our software to manage their job postings and applications", and its GDPR help says customers give
  candidates their own notice. Same position as Greenhouse: silence, the employer's notice governs, and the
  admin submits. One employer's form says the employer may use AI to screen; nothing about applicants.
  The form (public page, read via fetch, not yet through AX) is one page:
  - Resume/CV is a required file upload with no paste option, so the macOS open panel can't be avoided;
  - free-text salary and skills fields;
  - an availability choice, likely radio buttons, which hit the `tab` role mapping in `roles.yaml`;
  - a location search;
  - a "LinkedIn import" button, never pressed;
  - "Submit application".
- **Workable** (`apply.workable.com`): not checked; it may have its own candidate terms.

## Capture findings, Lever form 1 (2026-11-07)

Read-only AX dump of one `jobs.lever.co/…/apply` form, untouched.

- 10 standard text fields (name, email, phone, location, company, five links) have accessible names. The three
  employer questions (skills, current and expected salary) are **unnamed** text fields: their question text is
  in a static-text node in the same question group, just before the field. `read_form` therefore needs one
  structural rule: a field without a name takes the text of its question group's label node. It's deterministic
  and only applies inside the form region. If the rule finds no text, or more than one candidate, the field
  goes to the admin.
- Single-choice answers ("When will you be available": Immediate, 30, 60 days, serving notice) are radio
  buttons and come through as `tab` (the `roles.yaml` mapping: Chrome maps both to AXRadioButton). The engine
  needs a `radio` role told apart from `tab` by its subrole or parent. That's its own small task.
- Pronoun checkboxes are voluntary personal data: they always go to the admin, like the demographic questions.
- Only 3 of 13 fields have DOM ids (`#resume-upload-input`, `#btn-submit`, and one other). Lever anchors on
  label plus structure, not ids.
- The resume is required and file-only (`#resume-upload-input`), so the macOS open panel is in scope for Lever.
- **hCaptcha is present** (`#h-captcha`, next to Submit). The admin presses Submit, so a challenge there is
  the admin's to solve. If it ever appears before the fill, the CAPTCHA rule applies (card, admin solves it).
- `Apply with LinkedIn` is never pressed; `SUBMIT APPLICATION` (`#btn-submit`) is `submit`.
