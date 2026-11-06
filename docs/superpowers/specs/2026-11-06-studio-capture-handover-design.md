# Studio: new apps from a sentence — capture and handover design

Date: 2026-11-06. Status: **approved to write, not to build.** Build starts when the admin says so. Builds on control panel v2 (`2026-11-06-panel-v2-design.md`, merged as PR #10).

## 1. Intent

The admin wants to make new apps (flows) by describing them, for example "please create a flow for finding a file in Google Drive". An LLM (Claude, or later others) is given the AIOS schema and writes the flow. GOV-AIOS stays the only thing that touches the screen, and nothing an LLM writes runs until the admin approves it.

The panel grows into three areas: **My apps** (what runs on this Mac), **Marketplace** (templates to install), and **Studio** (making new templates). This spec covers Studio's core: how a page is captured, what is handed to the LLM, what comes back, and how it is checked. My apps and Marketplace are only sketched here (§9). The mockup is at `docs/superpowers/mockups/2026-11-06-apps-journey.html`.

## 2. Goals, non-goals, anti-goals

Goals
- From a one-sentence request, Studio produces a **draft** app: one flow file plus the page files it needs.
- Page files are built from the **real page**, captured by GOV-AIOS in the admin's Chrome profile. They are never guessed by the LLM.
- Every draft is checked by GOV-AIOS before the admin sees it, test-run safely, and approved with Touch ID like any flow today.
- Every stage is in the audit log.

Non-goals (this cycle)
- **Service-account / API connectors** (e.g. Drive API). Later: a separate project needing a new action kind, Keychain credentials, scopes and network rules (admin: "let's leave service account for later").
- Editing steps by hand in a visual editor. Studio shows the draft; changing it means asking again or editing the YAML.
- A shared or online marketplace. Templates live on this Mac.
- More than one admin (one admin per laptop, see v2 spec).

Anti-goals (a failure even if it works)
- The LLM ever controlling the screen, browser, files or commands directly.
- Personal content (file names, email subjects, message bodies) leaving the laptop without the admin seeing it first.
- A draft that runs, or gets wider permissions, without the admin's Touch ID.
- An LLM-proposed risk level or permission that is looser than the rules GOV-AIOS already applies.

## 3. Admin decisions (as said)

- "since you/other llm's i will pass the aios schema it is supposed to generate the flow files accordingly, example 'please create a flow for finding a file in a google drive'."
- The Google account comes from a Chrome profile the admin picks, as JobLens does ("yes the chrome profile, like joblens does").
- Service account: later.
- Each app drives its own setup. The panel does not have per-app setup screens (feedback on mockup steps 4 and 6).

## 4. Constraints carried over

- Flow format and engine as today: a closed action set; `permissions.allow` (anything unlisted is denied); `destinations` (Rule 11); `max_element_risk`; page identification before any element is used.
- Page files (`pages/*.yaml`) as today: `identification` (title, anchors, absent) and `elements` (role, name, within, index, risk), with roles from `govaios/roles.yaml`.
- Approvals are keyed by flow id plus a digest of the flow and the pages it uses. The panel runs only approved apps from `<data home>/apps/flows`.
- The signed app holds Accessibility and Screen Recording. Nothing else gets them.
- Panel security rules from v1/v2: 127.0.0.1 only, no JavaScript, CSRF, Touch ID for approvals.

## 5. Design

### 5.1 The journey in Studio
1. **Ask.** The admin types the request and picks a Chrome profile.
2. **Plan.** The LLM returns a *plan*: the steps in plain words and the pages it needs (e.g. `drive_home`, `drive_search_results`), each with a starting address. No YAML yet.
3. **Capture.** For each page, GOV-AIOS opens it in the chosen profile and reads it (§5.2). If a page is reached by a step (e.g. results after a search), the admin gets there by hand in that window and presses **Capture this page**. GOV-AIOS never types or clicks during capture.
4. **Preview and hand over.** The admin sees exactly what will be sent (§5.3) and presses **Hand over**.
5. **Draft.** The LLM returns the flow and page files. GOV-AIOS checks them (§5.5), retrying with the errors up to 3 times.
6. **Review.** A plain summary: steps, what it may do, which sites, what it may never do, and anything the checks tightened.
7. **Test run** (§5.6), then **Approve** with Touch ID. The app appears in My apps.

### 5.2 Capture (on the laptop, read-only)
- Done by the signed app with the existing desktop/AX code (as in the Himalayas spike), in the admin's chosen Chrome profile, after the same account check flows use (`verify_account`).
- Output per page: `<data home>/studio/<draft-id>/capture/<page>.json` (0600) containing:
  - the address without its query string and fragment;
  - the window title;
  - the accessibility tree: role, name, nesting, sibling index, `dom_id` where present, and the neutral role mapping from `roles.yaml`.
- Capture actions are limited to: activate the window, read the tree, read the title. It never clicks, types or navigates. (Navigation to the starting address happens before capture, as a governed `navigate`.)
- Audit: `studio_capture` with draft id, page id, origin, node count and digest. No names or text.

### 5.3 Masking (before anything leaves the laptop)
- **Kept:** names of controls and chrome. That means elements whose role is button, link, menuitem, tab, textbox/searchbox label, checkbox or heading level 1–2, *and* which sit in banner, navigation, toolbar, menu, dialog title or form-label regions. Titles that match the page title pattern are kept too.
- **Masked:** every other name and text. In particular, list rows, table cells, grid cells, articles, documents, listitems and their descendants are masked, along with any text longer than 60 characters. A masked name becomes `‹text n›`, where n is its length. Structure, roles and counts stay.
- **Always masked:** anything that looks like an email address, phone number, URL path beyond the origin, or a number of 6 or more digits, wherever it is.
- The admin sees the masked bundle rendered as an indented tree before handover and can mask more by hand (click a node → mask). They cannot unmask, except by editing the request.
- Masking is deterministic and has its own tests (fixtures from the Himalayas and Gmail captures).

### 5.4 Handover: what goes to the LLM and what comes back
- **Sent, as text only:**
  - the request;
  - the masked capture of each page;
  - the AIOS schema pack: the flow format, the page format, the action list with what each needs, `roles.yaml`, and the risk rules;
  - two worked examples: JobLens and Inbox brief, each a flow plus its pages.
- **The LLM has no tools.** It receives text and returns text. It cannot browse, read the disk, run commands or reach GOV-AIOS.
- **The reply** must be one flow YAML and its page YAMLs, in a fixed envelope, e.g. fenced blocks with file names. Anything outside the envelope is ignored.
- GOV-AIOS writes the reply only into `<data home>/apps/drafts/<draft-id>/` (0700). Never into `apps/flows` or `apps/pages`.
- Audit: `studio_handover` (digest of what was sent, model id, channel) and `studio_reply` (digest, size, parse result). Neither entry records content.
- **Channel: OPEN (admin to decide before build).** Either:
  - **(a)** a direct model API call from the signed app, with the API key in Keychain and network allowed only to the API host; or
  - **(b)** the installed Claude Code CLI run in a no-tools, print-only mode under GOV-AIOS hooks.

  (a) is simpler to make tool-free. (b) reuses the admin's Claude subscription. The rest of this spec does not depend on the choice.

### 5.5 Checks on the draft (the LLM's output is untrusted)
1. **Parse:** the files load with the engine's own loaders. Unknown keys and unknown actions are rejected.
2. **Tree match:** every element in each page file resolves in that page's capture, by role and name, or by role and index within its `within` parent, to exactly one node, or to the expected list for list elements such as `job_cards`.
3. **Page identity:** each page's `identification` matches its own capture and does *not* match any other captured page.
4. **Risk floor:** an element's risk is at least what its role implies (from `roles.yaml` and the existing risk rules). Names that look like submits (send, save, delete, apply, buy, share, move, upload…) are `submit`, whatever the LLM said. The checker only raises a risk, never lowers it.
5. **Permissions:** `permissions.allow` is set to exactly the actions the steps use. `max_element_risk` cannot be higher than the request needs. If the request reads ("find", "list", "read"), it is `navigate`. Anything higher is shown to the admin as a warning.
6. **Sites:** `destinations` must be a subset of the captured origins plus the account check site.
7. **Retries:** a failure is sent back to the LLM as a plain error list. After 3 failed tries, Studio stops and shows the errors to the admin.
- Every change the checker makes (raised risks, trimmed permissions) is listed on the Review screen.

### 5.6 Test run
- The real engine, in a **draft mode**:
  - read-only actions run for real: navigate within destinations, classify, extract, read, report;
  - any element of `submit` risk or above, any `deliver`, and any write outside the draft folder is **stopped and shown**, not done;
  - a test run never needs a code session, but it needs a panel sign-in and is audited as `test_run`.
- Results are shown as the run's steps, with extracted values visible only on the admin's screen. They are never sent to the LLM.

### 5.7 Publish and install
- After approval, the draft is moved to `apps/flows` and `apps/pages` as an approved app. Optionally it is also saved as a template in `<data home>/templates/` so it appears in Marketplace and can be installed again with a different Chrome profile.
- Installing a template copies it and asks the template's own setup questions (e.g. which Chrome profile). The result is a new draft that needs approval. Each app drives its own setup.

## 6. Tests the builder adds
- Masking:
  - fixture trees (Himalayas, Gmail) are masked to the expected output;
  - an email, a long number or a URL path is never kept;
  - control names are kept.
- Envelope parse: extra prose is ignored, a missing file is rejected, unknown keys are rejected.
- Tree match: an invented element fails, an ambiguous element fails, list elements resolve.
- Risk floor: an LLM `read` on a "Send" button becomes `submit`, and the change is reported.
- Permissions are trimmed to the actions used; a destination outside the captures is rejected.
- Retries stop after 3.
- Test run: a submit-risk click is stopped and shown; `deliver` is stopped.
- Audit entries contain digests only (grep the log for fixture names → none).

## 7. Review focus
1. Personal text slipping through masking (names in buttons, e.g. "Open Rupak's file"; accessible descriptions; titles).
2. An LLM reply that passes the checks but does something other than the request (the review summary must make this visible).
3. A page file that identifies the wrong page (two Drive views with the same title).
4. Prompt injection from a captured page (text on the page telling the LLM what to write). Masking removes most of it; the checks must hold even if it gets through.
5. The test run doing something real that should have been stopped.

## 8. Open questions for the admin (before build)
1. Channel: direct API call with key in Keychain, or Claude Code in no-tools mode (§5.4)?
2. Other LLMs (Codex/OpenAI) as Studio writers: in scope for the first build, or Claude only?
3. ~~Typing and inputs~~ **Decided 2026-11-06 (admin): "add typing with search boxes only".** See §11.1. Questions 1 and 2 stay open until the build (admin: "we will decide when we get there").

## 11. Calls made after the builder check (my calls, for the admin to check)
1. **Typing and run-time inputs.** Decided by the admin: typing into search boxes only. So:
   - a new `type_text` action, allowed only into elements whose role is searchbox (or a textbox inside a search landmark), at `navigate` risk; any other text field is refused;
   - flow `inputs:` with names and short descriptions, which the panel asks for when the app is run (e.g. "run drive finder: invoice 2026");
   - each input value audited as a digest, never as text.
2. **Several captures per page.** A page may have more than one capture, e.g. logged-in and logged-out, or empty and populated. Studio asks for the extra states the plan names. Identification must tell apart every captured state that the flow treats differently, as `himalayas_logged_out` does today.
3. **Masking and page files.** `dom_id` and `dom_class` are kept unmasked, because they are structure, not content. In masked regions the LLM addresses elements only by role, `within`, `index`, `dom_id` or `dom_class`. Name-based matching is allowed only on kept names. The tree check is strict: exactly one node, or the expected list. A draft that resolves but fails its test run is normal; Studio sends the failure back as a retry.
4. **Draft mode.** A test run needs a panel sign-in and an open code session, but no approval. Whatever the draft says, it runs with:
   - a ceiling of `navigate` risk, plus `type_text` into its declared inputs;
   - no `deliver`, and writes only into its draft folder.

   The stop-and-show gate is applied in `gate()` as an extra ceiling, so the policy code isn't bypassed. Approval comes after a passing test run, and covers the draft's final bytes.
5. **Draft layout and names.** Drafts live at `apps/drafts/<id>/flows/` and `apps/drafts/<id>/pages/` (siblings, as the engine expects). The LLM must prefix page ids with the app id (e.g. `drive_finder__search_results`). On install, a page id that already exists with different bytes is refused, never overwritten.
6. **Account check.** The first build supports sites where the Google account check applies (as today: verify on google.com first). Other sites have no account check; the flow must classify a logged-out page and stop.
7. **Fixtures.** The masking tests use the Himalayas spike captures (`spikes/ax-himalayas` data). A Gmail capture is made in the first build task. That task also checks that the AX capture carries heading levels and landmarks; if it doesn't, the masking rules fall back to role only.

## 9. Sketch: My apps and Marketplace (context, not this build)
- **My apps:** approved apps with the account and Chrome profile each uses, last run, Run and Settings. Tools found on the Mac (Claude Code, Codex) are listed as "Not governed" with **Set up**. Upgrades carry existing apps over unchanged, with no re-approval.
- **Marketplace:** templates from GOV-AIOS and from Studio. Each says what it needs (account, Chrome, a tool on disk) and what it may do. Each app's template carries its own setup.
- **Coding tools:** Claude Code is governed today through managed settings and hooks. The Codex spike (`docs/superpowers/spikes/2026-11-06-codex-governance.md`) shows Codex 0.162 has a matching `PreToolUse` hook, and a managed `/etc/codex/requirements.toml` that can force managed hooks only and lock the sandbox and approval modes. So Codex can be governed the same way, pending one live test of fail-closed behaviour.

## 10. Left to the builder
- Capture file layout details and the masked-tree rendering.
- The envelope format, as long as it is strict.
- How the schema pack is assembled (generated from the loaders is better than hand-written).
