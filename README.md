# DesktopPilot --- Morning Inbox Briefing

A schema-driven desktop automation workflow that opens a real Chrome
window, navigates to Gmail using an existing personal Chrome profile,
reads the five newest emails in the Inbox one at a time, and speaks each
email through a local text-to-speech (TTS) engine.

> **Workflow name:** Morning Inbox Briefing\
> **Workflow ID:** `morning_inbox_briefing`\
> **Project:** DesktopPilot\
> **Initial mode:** Local, attended desktop automation\
> **Interaction model:** Visible Chrome + operating-system mouse and
> keyboard events\
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

A browser accessibility tree or DOM inspection may be added as an
optional perception aid, but it must not be used to bypass the desktop
interaction requirement. The runtime should clearly record which
interaction method was used.

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
workflow may resume from a fresh screenshot and re-verify the Gmail
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

DesktopPilot should remain a generic desktop execution framework.
Morning Inbox Briefing is a workflow definition that runs on top of it.

``` text
desktop-pilot/
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
│   └── piper_engine.py
│
├── safety/
│   ├── permissions.py
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
should validate it against a versioned schema before execution.

``` yaml
workflow:
  id: morning_inbox_briefing
  name: Morning Inbox Briefing
  version: 1

  execution:
    mode: native_desktop
    sequential: true
    stop_on_unexpected_state: true
    require_postcondition_before_next_step: true

  browser:
    application: chrome
    profile_id: personal
    reuse_existing_window: true
    headless: false

  steps:
    - id: launch_chrome
      action: launch_application
      target: chrome
      verify:
        page: chrome_profile_chooser_or_new_tab

    - id: select_profile
      action: click
      target: chrome_profile.personal
      verify:
        page: google_home_or_new_tab

    - id: open_google
      action: navigate
      value: "https://www.google.com"
      verify:
        page: google_home

    - id: open_gmail
      action: click
      target: google_home.gmail_link
      verify:
        one_of:
          - gmail_inbox
          - gmail_authentication

    - id: authentication_guard
      action: classify_page
      on_match:
        gmail_inbox: continue
        gmail_authentication: stop_and_request_user
        captcha: stop_and_request_user
        security_challenge: stop_and_request_user
        unknown: stop_and_report

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
          verify:
            playback_completed: true

        - id: return_to_inbox
          action: click
          target: gmail_message.back_to_inbox
          verify:
            page: gmail_inbox

    - id: finish
      action: announce_completion
      value: "Morning Inbox Briefing complete."
```

------------------------------------------------------------------------

## 7. Page schemas

Page schemas describe semantic UI elements, not fixed coordinates.
Coordinates must be resolved from the current screen at runtime.

Example:

``` yaml
page:
  id: gmail_inbox
  title: Gmail Inbox

  identification:
    visual_anchors:
      - inbox_navigation
      - message_list
      - gmail_header

  elements:
    gmail_header:
      type: region
      label: Gmail

    inbox_navigation:
      type: navigation_item
      label: Inbox

    message_rows:
      type: repeated_region
      item_type: email_row
      ordering: newest_first
      fields:
        sender:
          type: text
        subject:
          type: text
        timestamp:
          type: text

    search:
      type: textbox
      label: Search mail
```

The message page should have a separate schema describing sender,
subject, timestamp, message body, and the back-to-Inbox control.

Page schemas must tolerate normal UI variation. If the expected anchors
are absent or ambiguous, the agent should stop rather than use guessed
coordinates.

------------------------------------------------------------------------

## 8. TTS requirements

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
-   Initial platform target should be selected explicitly (Windows or
    macOS); OS-specific desktop controls should be isolated behind one
    interface.
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
-   [ ] It supports pause, resume, skip, and stop.
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
-   Capture screenshots.
-   Perform real OS mouse and keyboard events.
-   Load and validate a simple YAML workflow.
-   Execute ordered steps with verification and bounded retries.

**Deliverable:** A small workflow that opens Google and clicks Gmail.

### Milestone 2 --- Gmail visual workflow

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

-   Improve visual anchors and page identification.
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
  Operating system            To be selected
  Chrome application path     Auto-detect or configure
  Chrome profile identifier   User-configured
  Google URL                  `https://www.google.com`
  Gmail destination           Open via visible Gmail link
  Mail folder                 Inbox
  Message count               5
  Ordering                    Newest first
  TTS engine                  Local Piper ONNX
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

The core DesktopPilot runtime should remain application-agnostic.
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
