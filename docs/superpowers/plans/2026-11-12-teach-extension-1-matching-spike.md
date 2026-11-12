# Teach extension, plan 1 of 2: the matching spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, on the admin's JobLens, that clicks taught with the GOV-AIOS side panel open become steps a run can find again: build step 1 of the spec, with rule 2's pass/fail bar.

**Architecture:** A throwaway script (`spikes/plan6/match_spike.py`) runs GOV-AIOS's existing `Observer` on the admin's Chrome tab, exactly as the engine's teach step does (`govaios/engine.py` ~880-935), with a minimal side-panel extension open. Pass 1 records the admin's clicks on Discover, Shortlisted and Review as Observer click events (each carries an `element_spec`); **Approve & promote is never pressed**: its spec is read from a snapshot of the Review page. Pass 2, after a fresh load of each page, checks every recorded spec with `engine.find_all` and checks the per-card anchor for **Review**. It prints PASS/FAIL per element. Plan 2 (spec build steps 2–6) is written after this result, because the result decides the mechanism every later task builds on.

**Tech Stack:** Python 3 (`.venv`), pyobjc via `govaios/desktop/macos.py`, Chrome Manifest V3 (plain JSON/HTML, no JS needed).

**Spec:** `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (rule 2 and "Build order" step 1).

## Global Constraints

- The spike only **reads**: no click, key or text is ever posted by the script, **and the admin presses nothing that changes data**: pass 1 stops at the Review page, so Shortlisted keeps its 4 profiles for pass 2. It may only pin the window that is already in front (`pin_window`), as the engine does.
- Prints role, name, spec and counts only. Never field values (typed text), and never the value of a secure field.
- Runs only on `http://localhost:8100` (the admin's own app). Any other origin seen on the teach tab ends pass 1, as the engine's teach loop does.
- The admin is present and drives Chrome; the script runs from Terminal, which needs Accessibility and Input Monitoring for the run (pending admin item "turn them off" waits until after this spike).
- Spike code gets no tests and stays under `spikes/plan6/`; nothing in `govaios/` changes. It may reach into private helpers (`macos._attr`, `macos._s`, `studio._walk`, `desk._target`), said so in its docstring.
- Commits go to `feat/teach-extension-build`, never `main`.
- No timeout: each pass ends on Enter in Terminal, Ctrl-C, or the tab leaving `localhost:8100`. Every prompt says "click Terminal, then press Enter". Without a terminal on stdin the script exits at once with a message.

## Ruling made while planning (to report to the admin)

- **Ruling:** the step's target comes from GOV-AIOS's own accessibility observer (the click under the pointer, `observe_sample` + `Observer`), not from matching an extension DOM report to the accessibility tree. — **Why:** the observer already records clicks as engine-findable specs and was proven on 2026-11-10 (15 clicks seen); it removes the DOM→AX matching problem entirely, and the extension is left with Teach/Pause/Done, the steps view and highlighting. — **Cost if wrong:** if the observer misses clicks with the side panel open, plan 2 adds the extension-report path the spec first described.

## Review Focus

1. **The side panel's own web area is read instead of the page.** Chrome's side panel is a second AXWebArea in the same window; `web_root` takes the first one it finds. Expected: the snapshot is the JobLens page. At every check the spike prints every AXWebArea in the window (title, URL). PASS if the one `web_root` picked has origin `http://localhost:8100` and a title containing `JobLens`; a distinct `FAIL side panel read` if it is a `chrome-extension://` page or titled `GOV-AIOS Teach`.
2. **The page changes before the snapshot.** Discover, Shortlisted and Review change the page right after the click. Expected: the event is still recorded against the element clicked. The spike FAILs an element that was clicked but has no click event.
3. **Every card has a Review button.** Expected: the recorded spec is unique (it carries `index`), and the per-card anchor finds exactly one Review per card. Checked in pass 2.
4. **A fresh load renders differently** (ids regenerated, order changed). Expected: each spec still finds exactly one element. Checked in pass 2.
5. **JobLens two-line titles hit an AXCell** (2026-11-10). Expected: a click inside a card resolves to its button or link, not a cell. The spike prints the recorded role for each click.

---

### Task 1: The spike script and the minimal side panel

**Files:**
- Create: `spikes/plan6/extension/manifest.json`, `spikes/plan6/extension/sidepanel.html`, `spikes/plan6/extension/background.js`
- Create: `spikes/plan6/match_spike.py`

**Interfaces:**
- Consumes: `govaios.desktop.macos.MacDesktop` (`focused_window_id`, `pin_window`, `teach_tab`, `observe_sample`, `web_root`, `current_url`, `same`), `govaios.observer.Observer` (`feed(sample, snap_fn) -> list[event]`, `.pages`), `govaios.engine.find_all(root, spec, page) -> list[Node]`, `govaios.studio.element_spec(tree, node)`, `govaios.capture.tree(root)`.
- Produces: console output only; the result goes into the spec in Task 2.

- [ ] **Step 1: The extension.** `manifest.json`: MV3, name `GOV-AIOS Teach (spike)`, version `0.0.1`, `permissions: ["sidePanel"]`, `side_panel.default_path: sidepanel.html`, `action.default_title: GOV-AIOS Teach`, `background.service_worker: background.js`. `background.js` is `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });`. `sidepanel.html`: heading "GOV-AIOS Teach (spike)", inert **Teach** and **Done** buttons, and the line "Spike: these buttons do nothing; the Terminal script records."
- [ ] **Step 2: Start.** Refuse unless `AXIsProcessTrusted()`; print Input Monitoring (`CGPreflightListenEventAccess`). If stdin is not a TTY, print "Run this from Terminal: it needs Enter presses." and exit 0. Prompt: open JobLens home (`http://localhost:8100/`) with the side panel open and Shortlisted holding 4 profiles, then click Terminal and press Enter, then click the JobLens page within 60 s; poll `focused_window_id` until Chrome is in front, then `pin_window` and `teach_tab`.
- [ ] **Step 3: Pass 1 (record, nothing approved).** Prompt: "In Chrome click Discover, Shortlisted, then Review on the FIRST profile. Do NOT press Approve & promote. When the Review page has loaded, click Terminal and press Enter." Loop every 0.03 s with `select` on stdin, as the engine's `tick()` does, ending on Enter, Ctrl-C or the tab leaving the origin. Print each event's kind, label, spec and `submit` (never values). On Enter, snapshot the Review page, run the web-area check, and take the spec of the one button named `Approve & promote` via `element_spec` (FAIL if not exactly one). Print the pages seen (URL, title).
- [ ] **Step 4: Pass 2 (find again, by walk order, not by path).** For each check in order (the first click on `Discover`, `Shortlisted`, `Review`, then the `Approve & promote` spec), prompt: "Open the page where you clicked '<label>' (for Approve & promote: the first profile's Review page, the same profile as pass 1), press Cmd-R, wait for it to load, then click Terminal and press Enter." Then: web-area check; `hits = find_all(root, spec, {"elements": {}})`; PASS if `len(hits) == 1 and hits[0].name == label`, else FAIL with `len(hits)`.
- [ ] **Step 5: The per-card anchor (on pass 2's Shortlisted page).** `reviews` = all nodes with the recorded Review's role and name; each one's container is its nearest ancestor with role in `("row", "article", "group", "region")`, from a parent map the spike builds from `root.walk()`. PASS anchor if: every Review has a container, the containers are distinct, the first container holds exactly one Review, and the recorded (indexed) spec's single hit is inside the first container. Print the container role and `len(reviews)` (expected 4).
- [ ] **Step 6: The verdict line.** `SPIKE PASS` only if pass 1 recorded a click for each of `Discover`, `Shortlisted`, `Review` (by label, case-sensitive), the Approve spec was taken, every web-area check, pass-2 check and the anchor check passed. Otherwise `SPIKE FAIL: <failed checks, comma-separated>`.
- [ ] **Step 7: Smoke test.** `.venv/bin/python spikes/plan6/match_spike.py </dev/null`. Expected: the permission lines, then "Run this from Terminal…", exit 0, no traceback.
- [ ] **Step 8: Commit** to `feat/teach-extension-build`: `git add spikes/plan6 && git commit -m "spike(teach): side-panel matching spike on JobLens"`.

### Task 2: The admin's run and the verdict

**Files:**
- Modify: `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (append "Spike result (date)" under rule 2)

- [ ] **Step 1: The admin runs it** (present at the Mac). Load `spikes/plan6/extension` unpacked in Chrome Profile 2 (`chrome://extensions` → Developer mode → Load unpacked), open its side panel from the toolbar icon, make sure Shortlisted has 4 profiles, then in Terminal: `.venv/bin/python spikes/plan6/match_spike.py`, and follow its prompts. Paste the output.
- [ ] **Step 2: Record the result** in the spec: the verdict line, failed checks, recorded roles and specs (no values), and the decision: PASS → write plan 2 on the observer mechanism; FAIL → stop and bring the failure to the admin with the options.
- [ ] **Step 3: Commit** `docs(spec): teach extension matching spike result`.
