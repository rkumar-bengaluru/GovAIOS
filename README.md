# GOV-AIOS: Governed AI Operating System

### Write it once. It runs exactly as you would. It stops instead of guessing.

> **Your Laptop, Your Rules.** GOV-AIOS (pronounced gov-ai-os) is a
> governance layer on top of your operating system. Anything you do on
> your laptop today can be written once as a **governed flow**. GOV-AIOS
> then performs it the way you would at the keyboard, using the tools
> the OS already provides, and stops and asks you whenever the
> situation is uncertain.

------------------------------------------------------------------------

# Part I --- GOV-AIOS

## The idea

You repeat the same computer work every day: open the browser, check
Gmail, open a document, update a tracker, look for jobs, book travel.
Each of those can be written once as a flow and then run on request.

GOV-AIOS is **not** an API integration platform and **not** a free-roaming
AI agent:

-   **No website APIs.** GOV-AIOS opens the real app and uses your own
    logged-in session, as if you were sitting at the laptop. It does not
    call Gmail, Drive, booking.com, or Upwork APIs.
-   **No improvisation.** GOV-AIOS runs only flows you have already set
    up. The AI may help understand a request and fill in a flow's
    parameters, but it never invents steps.
-   **Local by default.** Execution, perception, and TTS run on your
    machine. Content stays on the laptop unless a flow explicitly sends
    a result to you.

## How it works

``` text
Define flow  →  Govern (policy + preconditions)  →  Execute via OS tools  →  Verify each step  →  Report
```

**Flow layer.** A versioned YAML definition: steps, parameters,
preconditions, permissions, and stop conditions.

**Governance layer.** Validates preconditions, enforces permissions,
pauses for approvals, and stops on anything unexpected.

**Execution layer.** Uses whatever the OS provides, chosen per step for
reliability:

-   Application launch and window control.
-   OS accessibility APIs (the structured, labeled description of the
    screen that apps expose for screen readers).
-   Real OS mouse and keyboard input.
-   OS scripting (AppleScript / Shortcuts on macOS), the file system, and
    the shell.
-   Screenshot vision, only under the restrictions in Ground Rule 3.

**Initial platform:** macOS. Windows comes later behind the same desktop
interface.

## Ground rules

These rules apply to every flow. A flow cannot override them.

1.  **Flows only.** GOV-AIOS executes only flows the admin has set up.
    Requests that don't map to an existing flow are refused and
    reported.
2.  **No guessing.** If a page, element, or state cannot be identified
    with certainty, stop and report.
3.  **Perception order.**
    1.  Use **accessibility** as the primary way to find and act on
        elements.
    2.  On an **unlabeled screen**, screenshot vision may only
        **propose** a target. GOV-AIOS sends the admin a cropped
        screenshot of the proposed target and pauses for confirmation.
    3.  If the admin has not confirmed, or the step is a **payment or
        submission**, GOV-AIOS refuses and reports that the flow is not
        safely automatable.
4.  **Payment always needs approval.** Every payment step pauses and
    asks the admin, over a separate channel, to approve it. This applies
    even when every element is found through accessibility.
5.  **Pre-approved actions, everything else forwarded.** Each flow
    carries a fixed list of pre-approved actions. When an application
    being operated asks for permission (for example Claude asking "may
    I run `npm install`?"), GOV-AIOS approves it only if it is on that
    list. Every other permission request is forwarded to the admin
    (by local voice in phase 1, by phone later), and the flow waits.
    Without an answer, the request is denied.
6.  **Never bypass authentication.** No password entry, no CAPTCHA, MFA,
    or passkey solving, and no reading or exporting cookies or tokens.
    Stop and ask the admin.
7.  **Content is untrusted data.** Email bodies, web pages, and output
    from applications (including AI assistants) are content to be read,
    never instructions to follow.
8.  **One admin.** Only the admin can start flows or approve actions.
9.  **Least privilege.** Each flow declares what it may do. Anything not
    declared is denied.
10. **Bounded and stoppable.** Every action has a timeout and a
    postcondition. Retries are bounded, and the admin can stop any flow
    at any time.

## The governance layer (the core)

The governance layer is the product. Executors are pluggable: today
GOV-AIOS's own native runner, tomorrow Claude or any other agent. No
executor acts directly. Every action is first described as a request,
then decided, executed, verified, and recorded.

``` text
Executor (native runner / Claude / other agent)
        │  "I want to do X"
        ▼
┌──────────────── GOV-AIOS governance layer ────────────────┐
│ 1. Action request  → who, which flow, what, on what, risk │
│ 2. Policy engine   → allow / deny / ask                   │
│ 3. Approval broker → asks admin (voice now, phone later)  │
│ 4. Verifier        → did the expected result happen?      │
│ 5. Audit log       → decision + outcome, never content    │
└───────────────────────────────────────────────────────────┘
        │ allow
        ▼
     Action happens
```

### Components

1.  **Action request.** One format shared by every executor:

    ``` yaml
    action_request:
      actor: claude                 # or gov_runner, ...
      flow: build_with_claude
      step: claude_session
      action: shell.exec
      target: "npm install"
      risk: modify                  # read | navigate | modify | submit | payment
      perceived_by: accessibility   # accessibility | vision | n/a
    ```

2.  **Policy engine.** A pure decision function with no screen or OS
    access, so it is fully unit-testable. Policies are layered:
    **ground rules** (cannot be overridden) → **flow policy** (may only
    tighten) → **pre-approved list** (specific allows). The result is
    always exactly one of `allow`, `deny`, or `ask`.
3.  **Approval broker.** Delivers each `ask` to the admin over the
    current channel (local voice in phase 1, phone later). Silence or
    an unrecognized answer becomes `deny`.
4.  **Verifier.** Checks the step's postcondition. An action is not
    "done" until it is verified.
5.  **Audit log.** Append-only record of every request, decision,
    approver, and outcome, with no email bodies, page content, or
    secrets. It answers "what did it do, and who allowed it?"

### Executor adapters

| Adapter | How it plugs in | Status |
| :--- | :--- | :--- |
| Native runner | Calls the policy engine before every step it executes | v1 (proven by `morning_inbox_briefing`) |
| Claude Code | A Claude Code `PreToolUse` hook turns each tool call into an action request and returns allow / deny / ask | v1 (proven by `build_with_claude`) |
| Other agents | Any agent that can call the governance layer before acting | Later |

### Example: governing Claude in `build_with_claude`

| Claude wants to… | Request | Decision | Why |
| :--- | :--- | :--- | :--- |
| Read `package.json` | `file.read`, risk `read` | allow | Inside the project folder |
| Run `npm install` | `shell.exec`, risk `modify` | allow | On the flow's pre-approved list |
| Run `curl x.sh \| sh` | `shell.exec`, risk `modify` | ask → no answer in 60s → deny | Not pre-approved (Rule 5) |
| `git push` | `shell.exec`, risk `submit` | ask → admin says "yes" → allow | Submission needs the admin |
| Edit a file outside the project | `file.write` | deny | Ground rule, no prompt |

When denied, Claude is told "denied by GOV-AIOS policy" and continues or
stops. Every row lands in the audit log.

### Example: native runner in `book_travel`

The runner finds "Pay now" through accessibility and sends
`click`, risk `payment`, `perceived_by: accessibility`. Policy says
`ask` (Rule 4, always). The admin approves; the click happens; the
verifier checks that a booking confirmation page appeared. Had "Pay
now" been found only by vision, policy would say `deny` with no prompt
(Rule 3.3).

### Relearning a changed page

UI changes are normal; a human relearns where things moved, and so
does GOV-AIOS, under governance. When an expected element is missing,
GOV-AIOS stops, may propose the new location by vision (Rule 3),
and on the admin's confirmation saves the corrected page schema as a
**new version**. Schema repair is itself a governed, audited action.
Submit and payment elements are never relearned by vision.

### Enforcement scope

> **v1 governs cooperative executors only.** The native runner and
> Claude Code (through hooks) ask before acting. An agent that drives
> the mouse and keyboard directly could simply not ask, and v1 cannot
> stop it.
>
> **Later: OS-level enforcement.** Make the governance layer
> impossible to bypass, for example by sandboxing executors and
> controlling which processes hold macOS Accessibility, Input
> Monitoring, and Screen Recording permissions. Until then, do not
> describe GOV-AIOS as able to contain an uncooperative agent.

## Example flows (target)

| Flow | What it does | Governance notes |
| :--- | :--- | :--- |
| `morning_inbox_briefing` | Reads the five newest Gmail messages aloud | First flow (Part II). Read-only. |
| `book_travel` | Searches booking.com for a route and date and prepares the booking | Stops at payment for approval (Rule 4). |
| `send_drive_file` | Finds a Google Drive file and sends it to the admin's phone | Destination limited to the admin's own devices. |
| `upwork_scan` | Lists Upwork openings that match saved criteria | Read-only. Criteria are part of the flow, not judged live. |
| `build_with_claude` | Opens Claude, submits a build request, reports when Claude finishes | Rule 5 governs Claude's permission prompts. Claude's output is untrusted (Rule 7). |

### Example: `build_with_claude`

GOV-AIOS stays fully scripted, and the open-ended work is delegated to
Claude, just as you would delegate it yourself:

1.  Open the Claude app, or a terminal running Claude Code (accessibility).
2.  Type the request into the labeled input and submit.
3.  Every Claude tool call passes through the governance layer via the
    Claude Code adapter: allow if pre-approved, otherwise ask the admin
    and wait (Rule 5).
4.  Detect completion: Claude has stopped working and the input is ready
    again.
5.  Report Claude's final summary to the admin.

GOV-AIOS confirms that Claude *finished*. It does not judge whether the
result is good, because that would be guessing.

## Remote control by phone (planned)

The admin's laptop is paired with a phone number. Away from home, the
admin calls it and asks for one or more flows, for example: "run
book_travel from Bangalore to Delhi on Friday, send me the itinerary
from Drive, and run upwork_scan." The admin hangs up and the flows run.
Approvals and results reach the admin's phone.

Design to be finalized separately. Current intent:

-   The call only selects existing flows and fills in their parameters
    (Rule 1).
-   The admin is verified by voice **plus** a PIN or a one-time code sent
    to the phone. Voice alone is not sufficient, because voices can be
    cloned and caller ID can be spoofed.
-   Payment and permission approvals use a channel separate from the
    call.
-   The phone channel needs a telephony and messaging service. The
    "no API calls" principle applies to the **sites and apps being
    operated**, not to the control channel.
-   This requires unattended execution (locked screen, expired sessions,
    nobody present for a CAPTCHA). The first flow below is attended
    only.

## Build order

1.  **Governance core.** Action request format and policy engine (pure
    Python, unit-tested), audit log, approval broker (typed answers for
    tests, then local voice).
2.  **Two executor adapters**, to prove executors are pluggable: the
    native runner with `morning_inbox_briefing`, and the Claude Code
    hook with `build_with_claude`.
3.  **Phone control channel.** Calls, admin verification, flow
    selection, and approvals.
4.  **More flows.** `book_travel`, `send_drive_file`, `upwork_scan`.
5.  **Unattended execution.**
6.  **OS-level enforcement** for uncooperative executors.

## What GOV-AIOS is not

-   Not a cloud agent that looks at screenshots and guesses where to
    click.
-   Not a scraper or an unofficial API client.
-   Not a way around logins, CAPTCHAs, or site security.
-   Not a guarantee of compliance with any site's terms of service.
    GOV-AIOS acts within your own session, as you would. Check each
    site's terms for automated use.

------------------------------------------------------------------------

# Part II --- First flow: Morning Inbox Briefing

The first flow, and the proof of the core runner. It opens a real
Chrome window, navigates to Gmail using an existing personal Chrome
profile, reads the five newest emails in the Inbox one at a time, and
speaks each one through a local text-to-speech (TTS) engine.

> **Workflow name:** Morning Inbox Briefing\
> **Workflow ID:** `morning_inbox_briefing`\
> **Project:** GOV-AIOS\
> **Initial mode:** Local, attended desktop automation\
> **Platform:** macOS\
> **Interaction model:** Visible Chrome, accessibility-first element
> location, OS mouse and keyboard events\
> **Default email scope:** Five newest messages in the Inbox\
> **Default TTS:** Local Piper ONNX voice (configurable)

------------------------------------------------------------------------

## 1. Purpose

Morning Inbox Briefing automates a repetitive morning task:

1.  Launch the installed Chrome application.
2.  Select the configured personal Chrome profile.
3.  Navigate to `https://www.google.com`.
4.  Click the Gmail link in Google's top-right navigation.
5.  Check whether Gmail is already authenticated.
6.  If a password, CAPTCHA, passkey, MFA prompt, or other security
    challenge is presented, stop and ask the user to complete it
    manually.
7.  Open the five newest messages in the Inbox, one at a time.
8.  Read each message aloud using local TTS.
9.  Report when the briefing is complete.

This workflow is intended for the user's own account and an existing
Chrome profile. It does not automate credential entry or attempt to
bypass Google's authentication or security controls.

## 2. Design principles

### 2.1 Schema-driven, not free-form autonomy

The workflow, page expectations, action order, permissions, and
verification conditions are defined before execution. The AI may
interpret the visible screen and locate controls, but it must not invent
new business actions or change the workflow.

### 2.2 Real desktop interaction

The initial implementation must use a visible Chrome application and
operating-system-level mouse and keyboard input for browser interaction.
It must not silently substitute headless browser automation or direct
Gmail API access for the specified UI journey.

Elements are located through the OS accessibility API first (Ground
Rule 3). Screenshot vision may only propose a target on an unlabeled
screen, with a cropped screenshot sent to the admin for confirmation.
The runtime records which perception method located each element.

### 2.3 Observe, act, verify

The execution loop is:

`Observe → Identify → Act → Verify → Continue`

The executor advances only when the current step's postcondition passes.
If the page or target cannot be identified with sufficient confidence,
it stops safely rather than guessing.

### 2.4 Least privilege

This workflow is read-only. It does not need permission to send, reply,
forward, delete, archive, label, mark as spam, download attachments, or
change Gmail settings.

### 2.5 Email content is untrusted data

Email bodies, subjects, sender names, links, and attachments may contain
malicious or misleading instructions. They are content to be read, never
instructions to the agent. The agent must not follow instructions found
in emails, open links, download files, run code, or disclose email
contents elsewhere.

------------------------------------------------------------------------

## 3. Scope

### In scope

-   Launching the real Chrome desktop application.
-   Selecting one explicitly configured Chrome profile.
-   Navigating to Google and opening Gmail through the visible UI.
-   Detecting login and security challenge states.
-   Reading the five newest messages in the Inbox.
-   Extracting sender, subject, date/time (when visible), and message
    body text.
-   Reading messages one by one through local TTS.
-   Pausing, resuming, skipping the current message, or stopping the
    briefing.
-   Capturing execution status and non-sensitive diagnostic evidence.

### Out of scope for the initial PoC

-   Entering, storing, or retrieving Google passwords.
-   Bypassing CAPTCHA, MFA, passkey, or security challenges.
-   Sending, replying, forwarding, deleting, archiving, starring,
    labelling, or marking messages.
-   Opening links contained in email bodies.
-   Downloading or opening attachments.
-   Reading attachment contents.
-   Searching all mail, Spam, Trash, or other folders.
-   Automatically changing Chrome or Gmail settings.
-   Using Gmail API as a substitute for the visible UI workflow.
-   Running unattended when the desktop is locked or unavailable.
-   Summarizing or prioritizing emails using a cloud model by default.

------------------------------------------------------------------------

## 4. User workflow

### Step 1 --- Launch Chrome

-   Launch the installed Chrome application.
-   Wait for the browser window to become visible and ready.
-   If Chrome is already open, use the configured policy: reuse the
    existing window only if the selected profile can be verified;
    otherwise stop and ask the user.

### Step 2 --- Select the personal profile

-   Identify the Chrome profile chooser or profile menu.
-   Select the profile configured by the user.
-   Verify that the expected profile is active using visible profile
    identity cues.
-   Do not inspect or export Chrome cookies, browser databases,
    passwords, or session tokens.

The profile name is a user-provided configuration value, not an inferred
identity.

### Step 3 --- Navigate to Google

-   Focus the address bar using a keyboard shortcut.
-   Type `https://www.google.com`.
-   Navigate and wait for the page to load.
-   Identify the Gmail link in the top-right navigation.

### Step 4 --- Open Gmail

-   Click the visible Gmail link.
-   Wait for the Gmail page to load.
-   Identify whether the user is authenticated.

### Step 5 --- Authentication stop conditions

Stop execution and notify the user if any of the following is detected:

-   Password prompt.
-   CAPTCHA or bot challenge.
-   Passkey prompt.
-   Multi-factor authentication prompt.
-   Account recovery or security verification.
-   Unexpected account chooser that cannot be resolved using the
    configured profile.
-   Any other authentication state requiring user input.

The agent must not attempt to solve, bypass, or repeatedly retry these
challenges. It must leave the browser available for the user to complete
authentication manually. After the user confirms completion, the
workflow may resume from a fresh observation and re-verify the Gmail
page.

### Step 6 --- Identify the five messages

-   Use the Gmail Inbox.
-   Select the five newest messages according to the visible Inbox
    ordering.
-   Do not silently switch to unread-only selection.
-   Do not include messages from Spam or Trash.
-   Record a stable in-session identifier for each selected message
    where possible (for example, its visible subject, sender, timestamp,
    and current list position).
-   If fewer than five messages are available, read the available
    messages and report the actual count.
-   If the Inbox ordering or message identity cannot be established,
    stop and ask the user.

**Default selection rule:** five newest Inbox messages, whether read or
unread. The initial PoC should not change read/unread state
intentionally; note that opening messages may cause Gmail itself to mark
them as read.

### Step 7 --- Read each message

For each of the five selected messages:

1.  Open the message by clicking its row.
2.  Verify that the opened message matches the selected sender and
    subject.
3.  Extract visible sender, subject, date/time, and body text.
4.  Exclude quoted history or signatures only when this can be done
    reliably; otherwise read the visible content without silently
    dropping text.
5.  Do not open links or attachments.
6.  Announce the sender and subject.
7.  Speak the message body using the configured local TTS engine.
8.  Wait for speech completion or user control.
9.  Return to the Inbox and verify the next target before opening it.

If the message is a draft, a suspicious warning, a security challenge,
or cannot be safely identified, stop and report the condition rather
than taking an unplanned action.

### Step 8 --- Complete

After the selected messages have been processed:

-   Announce that the briefing is complete.
-   Report how many messages were read.
-   Report any messages skipped and why.
-   Leave Chrome open in Gmail's Inbox.
-   Do not modify or clean up the mailbox.

------------------------------------------------------------------------

## 5. Architecture

GOV-AIOS should remain a generic desktop execution framework.
Morning Inbox Briefing is a workflow definition that runs on top of it.

``` text
gov-aios/
├── schemas/
│   ├── pages/
│   │   ├── chrome_profile_chooser.yaml
│   │   ├── google_home.yaml
│   │   ├── gmail_inbox.yaml
│   │   └── gmail_message.yaml
│   └── workflows/
│       └── morning_inbox_briefing.yaml
│
├── engine/
│   ├── workflow_loader.py
│   ├── schema_validator.py
│   ├── workflow_executor.py
│   └── state_machine.py
│
├── perception/
│   ├── accessibility.py
│   ├── screenshot.py
│   ├── page_identifier.py
│   ├── element_locator.py
│   └── visual_verifier.py
│
├── desktop/
│   ├── chrome.py
│   ├── mouse.py
│   ├── keyboard.py
│   └── screen.py
│
├── email/
│   ├── gmail_ui_reader.py
│   └── message_extractor.py
│
├── tts/
│   ├── speech_engine.py
│   ├── piper_engine.py
│   └── speech_recognizer.py
│
├── safety/
│   ├── permissions.py
│   ├── approvals.py
│   ├── authentication_guard.py
│   └── untrusted_content.py
│
├── runtime/
│   ├── execution_context.py
│   └── execution_logger.py
│
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/
```

### Component responsibilities

  -----------------------------------------------------------------------
  Component                           Responsibility
  ----------------------------------- -----------------------------------
  Workflow loader                     Loads and validates the workflow
                                      and page schemas.

  Workflow executor                   Executes the predefined steps in
                                      order.

  State machine                       Tracks current state, transitions,
                                      stop conditions, and recovery.

  Page identifier                     Determines which expected page is
                                      currently visible.

  Element locator                     Maps semantic element IDs to
                                      current screen locations.

  Desktop controller                  Performs OS-level mouse, keyboard,
                                      and screenshot operations.

  Gmail UI reader                     Navigates the visible Gmail UI and
                                      reads selected messages.

  Message extractor                   Extracts visible message metadata
                                      and body text.

  TTS engine                          Speaks text locally and exposes
                                      playback controls.

  Safety guard                        Enforces read-only permissions and
                                      authentication stop conditions.

  Execution logger                    Records step outcomes without
                                      persisting email contents or
                                      secrets.
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 6. Workflow schema

The following is an illustrative workflow contract. The implementation
should validate it against a versioned schema before execution. The
`perception`, `approvals`, `permissions`, and `pre_approved` blocks are
how a flow expresses the Ground Rules; a flow may tighten them but never
loosen them.

``` yaml
workflow:
  id: morning_inbox_briefing
  name: Morning Inbox Briefing
  version: 2

  execution:
    mode: native_desktop
    sequential: true
    stop_on_unexpected_state: true
    require_postcondition_before_next_step: true
    default_timeout_seconds: 15        # every step has a timeout (Rule 10)
    default_max_retries: 2             # retries are bounded (Rule 10)

  perception:                          # Ground Rule 3
    primary: accessibility
    vision: propose_only               # show crop on screen, ask by voice
    vision_forbidden_for_risk: [submit, payment]

  approvals:                           # Ground Rules 3-5
    channel: local_voice               # phase 1: laptop speaks and listens
                                       # phase 2: phone (same contract)
    answers:
      approve: ["yes", "confirm"]
      deny: ["no", "cancel"]
    timeout_seconds: 60
    on_timeout: deny
    on_unrecognized_answer: ask_again_once_then_deny

  permissions:                         # Ground Rule 9; unlisted = denied
    allow:
      - launch_application
      - navigate
      - click                          # only up to max_element_risk
      - extract_visible_text
      - text_to_speech
    max_element_risk: navigate         # this flow never clicks submit/payment
    deny:
      - send
      - reply
      - forward
      - delete
      - archive
      - change_labels_or_settings
      - download_attachments
      - open_email_links
      - read_browser_credentials

  pre_approved: []                     # Ground Rule 5; read-only flow
                                       # needs nothing pre-approved

  voice_controls:                      # spoken during or between messages
    pause: ["pause"]
    resume: ["resume", "continue"]
    skip: ["skip", "next"]
    stop: ["stop"]
  emergency_stop_hotkey: "ctrl+option+cmd+."   # always works, even if
                                               # speech recognition fails

  browser:
    application: chrome
    profile_id: personal
    reuse_existing_window: true
    headless: false

  steps:
    - id: launch_chrome
      action: launch_application
      target: chrome
      timeout_seconds: 20
      verify:
        one_of:
          - chrome_profile_chooser
          - chrome_new_tab

    - id: select_profile
      action: click
      target: chrome_profile_chooser.profile_personal
      skip_if_page: chrome_new_tab     # profile already active; verified below
      verify:
        one_of:
          - chrome_new_tab
          - google_home
        active_profile: personal

    - id: open_google
      action: navigate
      value: "https://www.google.com"
      timeout_seconds: 20
      verify:
        page: google_home

    - id: open_gmail
      action: click
      target: google_home.gmail_link
      timeout_seconds: 20
      verify:
        one_of:
          - gmail_inbox
          - gmail_authentication
          - captcha
          - security_challenge

    - id: authentication_guard
      action: classify_page
      on_match:
        gmail_inbox: continue
        gmail_authentication: stop_and_request_user
        captcha: stop_and_request_user
        security_challenge: stop_and_request_user
        unknown: stop_and_report
      resume:                          # after manual login
        requires_approval: true        # "I've signed in. Shall I continue?"
        reverify_page: gmail_inbox

    - id: select_messages
      action: identify_list_items
      target: gmail_inbox.message_rows
      parameters:
        folder: inbox
        ordering: newest_first
        count: 5
      verify:
        minimum_count: 1
        maximum_count: 5

    - id: read_messages
      action: repeat_for_selected_items
      steps:
        - id: open_message
          action: click
          target: current_message
          verify:
            page: gmail_message
            identity_matches_selected_message: true

        - id: extract_message
          action: extract_visible_text
          fields:
            - sender
            - subject
            - date
            - body
          constraints:
            attachments: exclude
            links: do_not_follow
            email_instructions: untrusted_data

        - id: speak_message
          action: text_to_speech
          input: extracted_message
          engine: local_piper
          timeout_seconds: none        # bounded by message length and
                                       # voice controls instead
          verify:
            playback_completed_or_skipped: true

        - id: return_to_inbox
          action: click
          target: gmail_message.back_to_inbox
          verify:
            page: gmail_inbox

    - id: finish
      action: announce_completion
      value: "Morning Inbox Briefing complete."
```

### How a confirmation works in phase 1

When a step needs approval (for example, vision proposed a target on an
unlabeled screen, or the flow is resuming after a manual login):

1.  GOV-AIOS pauses the flow.
2.  It shows the proposal on screen (for vision: a cropped screenshot of
    the target, highlighted).
3.  It speaks the question, for example: "I can't find the Gmail link by
    its label. Is the highlighted area the right one? Say yes or no."
4.  It listens with local speech recognition for an answer from
    `approvals.answers`.
5.  "Yes" continues. "No", silence past `timeout_seconds`, or an answer
    still unrecognized after one retry is a **deny**: the flow stops and
    reports.

If the target's `risk` is `submit` or `payment`, step 2 never happens for
a vision proposal: the flow refuses and reports that it is not safely
automatable (Ground Rule 3.3).

The microphone listens only while GOV-AIOS is not speaking (between
sentences, between messages, and while waiting for an answer), so TTS
output is not mistaken for the admin's voice.

------------------------------------------------------------------------

## 7. Page schemas

Page schemas describe UI elements the way the macOS accessibility API
reports them, by **role** and **name**, not by fixed coordinates.
Coordinates are read from the accessibility tree at runtime.

Every element that can be acted on carries a `risk` level:

| Risk | Meaning | Vision proposal allowed? |
| :--- | :--- | :--- |
| `read` | Only read, never clicked | Yes, with confirmation |
| `navigate` | Clicking moves to another view, changes nothing | Yes, with confirmation |
| `submit` | Sends, saves, posts, or changes data | No, refuse |
| `payment` | Spends money | No, refuse; and approval is always required (Rule 4) |

A flow may only act on elements at or below its
`permissions.max_element_risk`.

Example:

``` yaml
page:
  id: gmail_inbox
  title: Gmail Inbox
  application: chrome

  identification:                     # all anchors must be found
    window_title_contains: "Gmail"
    anchors:
      - inbox_navigation
      - message_list

  elements:
    inbox_navigation:
      role: AXLink
      name_matches: "^Inbox"           # e.g. "Inbox 12 unread"
      risk: navigate

    message_list:
      role: AXTable
      risk: read

    message_rows:
      role: AXRow
      parent: message_list
      repeated: true
      ordering: newest_first
      risk: navigate                   # clicking opens the message
      fields:
        sender:    { role: AXStaticText, position: 1 }
        subject:   { role: AXStaticText, position: 2 }
        timestamp: { role: AXStaticText, position: last }

    compose_button:                    # listed so the guard can block it
      role: AXButton
      name: "Compose"
      risk: submit

    search:
      role: AXTextField
      name: "Search mail"
      risk: read
```

The roles, names, and positions above are illustrative. The real values
must be captured from the live accessibility tree during Milestone 1
and kept in version control.

Required page schemas for this flow:

| Page | Purpose |
| :--- | :--- |
| `chrome_profile_chooser` | Profile picker shown at launch |
| `chrome_new_tab` | Chrome open with the profile active |
| `google_home` | Google home page with the Gmail link |
| `gmail_inbox` | Inbox with the message list |
| `gmail_message` | Open message: sender, subject, timestamp, body, back-to-Inbox control |
| `gmail_authentication` | Any Google sign-in, password, or account chooser page (classify only) |
| `captcha` | Any CAPTCHA or bot challenge (classify only) |
| `security_challenge` | MFA, passkey, or account recovery prompts (classify only) |

Classification-only pages define anchors but no actionable elements.
GOV-AIOS never clicks anything on them.

**Chrome note:** Chrome exposes full web-page accessibility only when it
detects an assistive technology. The runtime must ensure renderer
accessibility is enabled (for example, by setting the
`AXEnhancedUserInterface` attribute on Chrome's application element, or
launching with `--force-renderer-accessibility` when Chrome is not
already running) and verify the tree is populated before identifying
any page.

Page schemas must tolerate normal UI variation. If the expected anchors
are absent or ambiguous, stop rather than guess. Vision may only propose
a target under Ground Rule 3.

------------------------------------------------------------------------

## 8. Voice requirements (TTS and speech recognition)

Phase 1 is voice in both directions: GOV-AIOS speaks emails and
questions, and the admin answers and controls playback by speaking.

### Speech recognition

-   Runs locally (for example, whisper.cpp). Audio is never sent to a
    cloud service by default.
-   Recognizes only the fixed phrases in `approvals.answers` and
    `voice_controls`. Anything else is "unrecognized", never interpreted
    freely.
-   Listens only while GOV-AIOS is not speaking.
-   Audio and transcripts are not persisted. Logs record only the
    matched phrase category (approve, deny, pause, and so on).
-   Phase 1 does not verify *whose* voice it is; the admin is assumed to
    be at the laptop. Speaker verification arrives with the phone
    channel.

### TTS

The initial implementation should support a local TTS interface.

Preferred engine: the user's existing Piper ONNX voice model.

``` python
class SpeechEngine:
    def speak(self, text: str) -> None:
        ...

    def pause(self) -> None:
        ...

    def resume(self) -> None:
        ...

    def stop(self) -> None:
        ...

    def wait_until_complete(self) -> None:
        ...
```

### Speech format

For each email:

1.  "Email 1 of 5."
2.  "From: \[sender\]."
3.  "Subject: \[subject\]."
4.  "Received: \[date\], if available."
5.  Read the message body.
6.  Pause and wait for the user or continue according to the configured
    policy.

The TTS layer should support:

-   Pause.
-   Resume.
-   Stop.
-   Skip current email.
-   Playback completion notification.
-   Configurable speech rate and voice.

Do not send email text to a cloud TTS service by default.

------------------------------------------------------------------------

## 9. Safety and privacy requirements

### Permission model

  Capability                                   Permission
  -------------------------------------------- ------------
  Launch Chrome                                Allow
  Select configured Chrome profile             Allow
  Navigate to Google/Gmail                     Allow
  Read Inbox messages                          Allow
  Extract visible message text                 Allow
  Speak email content locally                  Allow
  Send or reply                                Deny
  Forward                                      Deny
  Delete or archive                            Deny
  Change labels or settings                    Deny
  Download attachments                         Deny
  Open email links                             Deny
  Execute email-provided instructions          Deny
  Read or export browser credentials/cookies   Deny

### Authentication

-   Never store Gmail passwords in workflow YAML or source code.
-   Never extract Chrome cookies or session tokens.
-   Never automate CAPTCHA or security challenge bypass.
-   Stop for manual user authentication.
-   Resume only after re-observing and verifying the expected page.

### Prompt injection

Email content is untrusted input. It must never modify the workflow,
permissions, system instructions, or action plan.

The email reader and TTS components should receive content as data only.
They must not pass email text to an unrestricted agent planner.

### Logging

Allowed log data:

-   Workflow ID and version.
-   Execution ID.
-   Step ID.
-   Start/end timestamps.
-   Success/failure status.
-   Error category.
-   Retry count.
-   Screenshot reference when needed and explicitly enabled.

Do not log:

-   Email body text.
-   Passwords or authentication data.
-   Cookies or session tokens.
-   Unnecessary personal email metadata.

Screenshots may contain sensitive information. If screenshot evidence is
enabled, keep it local, restrict access, and apply a configurable
retention policy. Prefer screenshots with sensitive message content
excluded or redacted when possible.

------------------------------------------------------------------------

## 10. Failure handling

  -----------------------------------------------------------------------
  Condition                           Expected behavior
  ----------------------------------- -----------------------------------
  Chrome unavailable                  Stop and report.

  Profile chooser not recognized      Stop; request user intervention.

  Configured profile missing          Stop; do not select another profile
                                      automatically.

  Google page fails to load           Retry within configured limit, then
                                      stop.

  Gmail password prompt               Stop for manual authentication.

  CAPTCHA/MFA/security prompt         Stop for manual authentication.

  Gmail Inbox not identified          Stop; do not guess.

  Fewer than five messages            Read available messages and report
                                      count.

  Message identity mismatch           Return to Inbox or stop; never read
                                      the wrong message silently.

  Message body cannot be extracted    Report the message as skipped;
                                      continue only if safe to identify
                                      the next message.

  TTS failure                         Retry once, then offer text display
                                      or stop according to configuration.

  Unexpected navigation/dialog        Stop and request intervention.

  User presses Stop                   Stop TTS and desktop actions
                                      immediately.
  -----------------------------------------------------------------------

Retries must be bounded. Actions such as clicking a message should be
verified before retrying to avoid acting on a changed page.

------------------------------------------------------------------------

## 11. Execution state machine

Suggested states:

``` text
IDLE
  |
  v
LAUNCHING_CHROME
  |
  v
SELECTING_PROFILE
  |
  v
NAVIGATING_TO_GOOGLE
  |
  v
OPENING_GMAIL
  |
  v
CHECKING_AUTHENTICATION
  |                  \
  | authenticated     \ challenge
  v                    v
IDENTIFYING_INBOX     WAITING_FOR_USER
  |                    |
  v                    | user confirms
SELECTING_MESSAGES    v
  |                 REVERIFYING_PAGE
  v                    |
READING_MESSAGE <------+
  |
  v
SPEAKING_MESSAGE
  |
  v
RETURNING_TO_INBOX
  |
  +---- more messages ----> READING_MESSAGE
  |
  v
COMPLETED
```

Any unexpected state transitions to `STOPPED` with a clear reason. User
cancellation transitions to `CANCELLED`.

------------------------------------------------------------------------

## 12. Non-functional requirements

-   Runs on a local desktop with a visible Chrome window.
-   Initial platform target is macOS; OS-specific desktop controls are
    isolated behind one interface so Windows can follow.
-   No headless browser execution in the initial PoC.
-   No dependency on Gmail API for the primary UI workflow.
-   All workflow and page schemas are version-controlled.
-   Element locations are resolved dynamically; fixed screen coordinates
    are not the source of truth.
-   Each action has a timeout and a postcondition.
-   All retries are bounded.
-   The workflow can be stopped by the user at any time.
-   Email contents are not persisted by default.
-   TTS processing is local by default.
-   The workflow should be repeatable against a test mailbox before
    being used with the personal mailbox.

------------------------------------------------------------------------

## 13. Testing strategy

### Unit tests

-   Workflow YAML validation.
-   Page schema validation.
-   State transitions.
-   Permission enforcement.
-   Authentication stop-condition classification.
-   Email content treated as untrusted data.
-   TTS interface and playback state.
-   Retry and timeout behavior.
-   Log redaction.

### Integration tests

Use a dedicated test Gmail account or controlled test environment where
possible.

Test:

1.  Chrome launches.
2.  Correct profile is selected.
3.  Google opens.
4.  Gmail link is identified and clicked.
5.  Authenticated Inbox is recognized.
6.  Password prompt causes a safe stop.
7.  CAPTCHA/security challenge causes a safe stop.
8.  Five messages are identified in newest-first order.
9.  Each opened message is checked against the selected list item.
10. Message content reaches the local TTS engine.
11. The workflow returns to the Inbox between messages.
12. The workflow reports completion after the available messages are
    read.
13. Stop/pause controls work.
14. No send, delete, archive, forward, link-opening, or
    attachment-download action is possible through this workflow.

### Acceptance criteria

The PoC is accepted when:

-   [ ] It launches a real, visible Chrome window.
-   [ ] It selects only the configured personal profile.
-   [ ] It navigates to Google and opens Gmail through visible UI
    interaction.
-   [ ] It recognizes an authenticated Inbox.
-   [ ] It stops for password, CAPTCHA, MFA, or security challenges.
-   [ ] It identifies the five newest Inbox messages, or all available
    messages if fewer than five exist.
-   [ ] It opens messages individually and verifies message identity.
-   [ ] It reads sender, subject, and available body text through local
    TTS.
-   [ ] It returns to the Inbox between messages.
-   [ ] It supports pause, resume, skip, and stop by voice, and the
    emergency stop hotkey always works.
-   [ ] It finds elements through accessibility; any vision proposal is
    shown as a crop and spoken, and proceeds only on a spoken "yes".
-   [ ] Silence or an unrecognized answer is treated as deny.
-   [ ] It does not send, forward, delete, archive, download, or follow
    links.
-   [ ] Email content cannot change the workflow or trigger additional
    actions.
-   [ ] Logs do not contain email body text or authentication secrets.
-   [ ] It reports completion and any skipped messages accurately.

------------------------------------------------------------------------

## 14. Suggested implementation milestones

### Milestone 1 --- Desktop execution foundation

-   Launch visible Chrome.
-   Select a configured profile.
-   Read the macOS accessibility tree for Chrome.
-   Perform real OS mouse and keyboard events.
-   Load and validate a simple YAML workflow.
-   Execute ordered steps with verification and bounded retries.

**Deliverable:** A small workflow that opens Google and clicks Gmail.

### Milestone 2 --- Gmail UI workflow

-   Identify Gmail authentication states.
-   Stop safely for user authentication.
-   Identify Inbox message rows.
-   Select the five newest messages.
-   Open and verify individual messages.
-   Extract visible message text.

**Deliverable:** A reliable read-only Gmail UI reader.

### Milestone 3 --- Local TTS integration

-   Integrate Piper ONNX.
-   Speak sender, subject, date, and body.
-   Add pause, resume, skip, and stop.
-   Wait for speech completion before proceeding.

**Deliverable:** End-to-end Morning Inbox Briefing.

### Milestone 4 --- Reliability and hardening

-   Improve accessibility anchors and page identification.
-   Add robust error handling and recovery.
-   Add execution evidence and redacted logging.
-   Test screen scaling, browser zoom, and layout variations.
-   Validate all permission boundaries.

**Deliverable:** A repeatable personal desktop automation workflow.

------------------------------------------------------------------------

## 15. Configuration required before implementation

The following values should be configuration, not hardcoded:

  Setting                     Initial value
  --------------------------- -----------------------------
  Operating system            macOS
  Chrome application path     Auto-detect or configure
  Chrome profile identifier   User-configured
  Google URL                  `https://www.google.com`
  Gmail destination           Open via visible Gmail link
  Mail folder                 Inbox
  Message count               5
  Ordering                    Newest first
  TTS engine                  Local Piper ONNX
  Speech recognition engine   Local (e.g. whisper.cpp)
  Approval channel            Local voice
  Approval timeout            60 seconds, then deny
  Emergency stop hotkey       Configurable
  Piper model path            User-configured
  Voice rate                  Configurable
  Screenshot retention        Disabled by default
  Maximum retries             2, configurable
  Authentication handling     Stop for user
  Attachments                 Excluded

Do not put credentials, tokens, cookies, or private email content in
this configuration.

------------------------------------------------------------------------

## 16. Future extensions

These are deliberately outside the initial workflow:

-   Daily scheduled execution.
-   Calendar morning briefing.
-   Email summarization and categorization.
-   Priority detection.
-   Multiple mailbox support.
-   User-configurable email selection rules.
-   Local semantic search over explicitly approved email data.
-   Additional TTS voices.
-   A desktop control panel for workflow execution.
-   More schema-driven workflows for other websites and applications.

The core GOV-AIOS runtime should remain application-agnostic.
Gmail-specific navigation and extraction belong in the page schemas and
workflow-specific components, not in the generic desktop controller.

------------------------------------------------------------------------

## 17. Definition of done

The first release is complete when a user can start
`morning_inbox_briefing`, watch the real Chrome application navigate to
Gmail using the configured profile, safely handle authentication
interruptions, hear the five newest Inbox messages one by one through
local TTS, and receive a completion report.

**The guiding principle: predefined workflow, real desktop interaction,
verified actions, read-only permissions, and human control whenever the
environment is uncertain.**
