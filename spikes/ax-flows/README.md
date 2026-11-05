# Spike: governed flows on Gmail and Himalayas

A minimal GOV-AIOS runner: flow YAML → governance decision → OS adapter →
verify. Both flows use the same Chrome profile. Himalayas writes each job
description to `jd_selected/*.json` (in place of the vetting service in
README Part III); Gmail prints the five newest messages (no TTS).

```
roles.yaml        neutral roles, OS operations, and keys, mapped to macOS AX and Windows UIA
desktop/          OS adapters; macos.py implemented, Windows uses the same interface
governance.py     pure policy: allow / deny / ask, approved flows + destinations (Rule 11)
engine.py         page identification, element location, step execution (OS-agnostic)
pages/            page schemas in neutral roles
flows/            himalayas_job_vetting.yaml, morning_inbox_briefing.yaml
dump.py           print a page's neutral-role tree, for capturing schemas
```

## Run

```sh
python3 -m venv .venv && .venv/bin/pip install pyobjc-framework-ApplicationServices pyobjc-framework-Quartz pyobjc-framework-Cocoa pyyaml
.venv/bin/python test_governance.py
.venv/bin/python run.py flows/himalayas_job_vetting.yaml
.venv/bin/python run.py flows/morning_inbox_briefing.yaml
```

The terminal needs macOS Accessibility permission. The runner moves the
real mouse and types into Chrome, so leave the keyboard and mouse alone
while it runs. Approvals are native dialogs; no answer within the timeout
means deny. The first run of each flow asks to approve the flow, then each
destination on first contact; both are remembered in `approvals.json`.
Editing a flow or any page schema asks again.

## OS neutrality

Schemas and flows never name a platform role, key, or API. Pages use
neutral roles (`link`, `heading`, `article`, `grid`, …), flows use logical
keys (`focus_address_bar`, `browser_back`), and pages are identified by
the web document title, not the window title (whose format differs per OS).
`roles.yaml` holds the only per-OS mapping. A Windows adapter implements
the operations listed there with UI Automation and `SendInput`.

## Findings (2026-11-05)

- Logged out, `himalayas.app/jobs/matches` returns the same URL and title
  with sign-up content. The auth guard needs content anchors (`absent:
  [login_link]`), not URL or title.
- A public job page also shows "Log in", so logged-out detection must be
  scoped to the matches title; otherwise identification is ambiguous and
  the engine stops (Rule 2), as it did in testing.
- "Google" in the window title matched every Chrome window
  ("… - Google Chrome"); identification moved to the document title.
- Job detail: title = first `heading` in `main`, description = first
  `article` in `main`; Save / Apply now / Job expired? are `submit`.
- The engine re-finds the selected item by its fields after every
  navigation (handles are invalid after the tree rebuilds) and stops if
  the item is gone.
- **Profile display names repeat** ("Rupak" for two accounts), so the
  window title cannot identify a profile. Flows launch Chrome with
  `--profile-directory` and verify the signed-in account on google.com
  before touching any site.
- Logged in, Himalayas renders Save / Apply now as **buttons**; logged
  out they are **links**. Anchors use the "Apply now" heading (same in
  both states) and every variant is listed as `submit`.
- **Modifier leak:** after the ⌘[ (back) shortcut, a synthetic click
  inherited ⌘ and Chrome opened the job in a background tab. Mouse
  events now carry no modifier flags. The Windows adapter needs the same
  care (Ctrl+click also opens a background tab).
- Clicks wait for the target's bounds to settle, and a click that
  leaves the page unchanged is retried once; a click that lands on an
  unexpected page is never retried.
- Approval (Rule 11) hashes the flow and page schemas, not the engine
  or adapter code: changing those does not ask again. To be decided for
  the real runtime.
- Result: 5/5 job descriptions saved to `jd_selected/` in ~20 s; second
  run needed no approval prompts.
- Gmail (captured live): the message list is a `table` of `row`s; the
  subject is a link (its name includes the preview snippet). Row checkbox
  and star are `modify`. The message body has no label or stable id and is
  found by web class `a3s` (`dom_class`, UIA `ClassName` on Windows).
  Primary/Promotions tabs are ARIA tabs, which Chrome exposes as
  `AXTabGroup`/`AXRadioButton`.
- Row identity uses sender + subject only: Gmail's relative dates
  ("x minutes ago") change between snapshots.
- The sender heading can carry extra words ("Verified sender",
  "Unsubscribe"); needs cleanup before TTS.
- Result: 5/5 distinct messages opened, read, and returned to Inbox in
  ~30 s. Opening a message marks it read (accepted in README Part II).
- Scrolling uses the `AXScrollToVisible` accessibility action rather
  than wheel input; clicks and keys are real OS events.
