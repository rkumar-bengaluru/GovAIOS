# Teach extension, plan 1 of 2: the matching spike — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove, on the admin's JobLens, that clicks taught with the GOV-AIOS side panel open become steps a run can find again: build step 1 of the spec, with rule 2's pass/fail bar.

**Architecture:** A throwaway script (`spikes/plan6/match_spike.py`) runs GOV-AIOS's existing `Observer` on the admin's Chrome tab, exactly as the engine's teach step does (`govaios/engine.py` ~880-935), with a minimal side-panel extension open. Pass 1 records the admin's four clicks as Observer click events (each carries an `element_spec`). Pass 2, after a fresh load of each page, checks every recorded spec with `engine.find_all` and checks the per-card anchor for **Review**. It prints PASS/FAIL per element. Plan 2 (spec build steps 2–6) is written after this result, because the result decides the mechanism every later task builds on.

**Tech Stack:** Python 3 (`.venv`), pyobjc via `govaios/desktop/macos.py`, Chrome Manifest V3 (plain JSON/HTML, no JS needed).

**Spec:** `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (rule 2 and "Build order" step 1).

## Global Constraints

- The spike only **reads**: no click, key or text is ever posted. It may only pin the window that is already in front (`pin_window`), as the engine does.
- Prints role, name, spec and counts only. Never field values (typed text), and never the value of a secure field.
- Runs only on `http://localhost:8100` (the admin's own app). Any other origin seen on the teach tab ends pass 1, as the engine's teach loop does.
- The admin is present and drives Chrome; the script runs from Terminal, which needs Accessibility and Input Monitoring for the run (pending admin item "turn them off" waits until after this spike).
- Spike code gets no tests and stays under `spikes/plan6/`; nothing in `govaios/` changes.

## Ruling made while planning (to report to the admin)

- **Ruling:** the step's target comes from GOV-AIOS's own accessibility observer (the click under the pointer, `observe_sample` + `Observer`), not from matching an extension DOM report to the accessibility tree. — **Why:** the observer already records clicks as engine-findable specs and was proven on 2026-11-10 (15 clicks seen); it removes the DOM→AX matching problem entirely, and the extension is left with Teach/Pause/Done, the steps view and highlighting. — **Cost if wrong:** if the observer misses clicks with the side panel open, plan 2 adds the extension-report path the spec first described.

## Review Focus

1. **The side panel's own web area is read instead of the page.** Chrome's side panel is a second AXWebArea in the same window; `web_root` takes the first one it finds. Expected: the snapshot is the JobLens page. The spike prints the root's title and URL per page and FAILs if the title is not JobLens's.
2. **The page changes before the snapshot.** Discover, Shortlisted and Review change the page right after the click. Expected: the event is still recorded against the element clicked. The spike FAILs an element that was clicked but has no click event.
3. **Every card has a Review button.** Expected: the recorded spec is unique (it carries `index`), and the per-card anchor finds exactly one Review per card. Checked in pass 2.
4. **A fresh load renders differently** (ids regenerated, order changed). Expected: each spec still finds exactly one element. Checked in pass 2.
5. **JobLens two-line titles hit an AXCell** (2026-11-10). Expected: a click inside a card resolves to its button or link, not a cell. The spike prints the recorded role for each click.

---

### Task 1: The spike script and the minimal side panel

**Files:**
- Create: `spikes/plan6/extension/manifest.json`
- Create: `spikes/plan6/extension/sidepanel.html`
- Create: `spikes/plan6/extension/background.js`
- Create: `spikes/plan6/match_spike.py`

**Interfaces:**
- Consumes: `govaios.desktop.macos.MacDesktop` (`focused_window_id`, `pin_window`, `teach_tab`, `observe_sample`, `web_root`, `current_url`, `same`), `govaios.observer.Observer` (`feed(sample, snap_fn) -> list[event]`, `.pages`, `.ended`), `govaios.engine.find_all(root, spec, page) -> list[Node]`.
- Produces: console output only; the result goes into the spec in Task 2.

- [ ] **Step 1: The extension.** `manifest.json`: `manifest_version: 3`, `name: "GOV-AIOS Teach (spike)"`, `version: "0.0.1"`, `permissions: ["sidePanel"]`, `side_panel: {"default_path": "sidepanel.html"}`, `action: {"default_title": "GOV-AIOS Teach"}`, `background: {"service_worker": "background.js"}`. Create `spikes/plan6/extension/background.js` with the one line `chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });` so clicking the toolbar icon opens the panel. `sidepanel.html`: a heading "GOV-AIOS Teach (spike)", two buttons **Teach** and **Done** that do nothing, and a line "Spike: these buttons do nothing; the Terminal script records."

- [ ] **Step 2: `match_spike.py`, pass 1 (record).** Module docstring states how to run it (as `spikes/plan5/observe_spike.py` does). Flow:
  1. Refuse unless `AXIsProcessTrusted()`; print whether Input Monitoring is granted (`Quartz.CGPreflightListenEventAccess()`).
  2. `desk = MacDesktop(); desk._target = "chrome"` (spike only). Print "Bring Chrome to the front on http://localhost:8100/ with the side panel open, then press Enter." Wait for Enter, then `desk.pin_window(desk.focused_window_id("chrome"))` and `tab = desk.teach_tab("chrome")`.
  3. Loop every 0.03 s for up to 180 s, as the engine's `tick()` does: `sample = desk.observe_sample("chrome")`; if the sample is on the teach tab and its URL's origin is not `http://localhost:8100`, end pass 1; `evs = obs.feed(sample, snap)` where `snap()` returns `desk.web_root("chrome")` and refuses (ends pass 1) if `current_url` left the origin. Stop on Ctrl-C or when the admin presses Enter (read stdin non-blocking with `select`).
  4. For each click event print: page title + path, `role`, `label`, the spec, and `submit`. For each page in `obs.pages` print its URL, its title and whether the title matches `^JobLens$`.

- [ ] **Step 3: Pass 2 (find again).** Print "Now reload each page and walk it again: Home → Discover → Shortlisted → Review (do NOT press Approve & promote). Press Enter after each page has loaded; type q and Enter when done." On each Enter: `root = desk.web_root("chrome")`, `path = urlsplit(desk.current_url("chrome")).path`; for every click event recorded on a page with the same path, `hits = find_all(root, ev["spec"], {"elements": {}})`; print `PASS` if `len(hits) == 1 and hits[0].name == ev["label"]`, else `FAIL` with `len(hits)`.

- [ ] **Step 4: The per-card anchor for Review.** On the Shortlisted page in pass 2, also check: for the recorded Review event's spec without `index` (`{k: v for k, v in spec.items() if k != "index"}`), `reviews = find_all(...)`. Each Review's container is its nearest ancestor with role in `("row", "article", "group", "region")`, using a parent map as in `observer._Snap.up`. Print `PASS anchor` if every Review has a container, the containers are distinct, and the first container's own subtree holds exactly one Review; print the container role and `len(reviews)`. The admin's Shortlisted holds 3–4 profiles here.

- [ ] **Step 5: The verdict line.** Last line: `SPIKE PASS` only if pass 1 recorded a click event for each of `Discover`, `Shortlisted`, `Review`, `Approve & promote` (by label, case-sensitive), every page title matched JobLens, every pass-2 check printed PASS, and the anchor check passed. Otherwise `SPIKE FAIL: <the failed checks, comma-separated>`.

- [ ] **Step 6: Check it starts.** Run: `.venv/bin/python -c "import ast,sys; ast.parse(open('spikes/plan6/match_spike.py').read())"` and `.venv/bin/python spikes/plan6/match_spike.py </dev/null` (no Chrome in front needed). Expected: the permission lines print, then it waits or exits cleanly on EOF without a traceback.

- [ ] **Step 7: Commit**

```bash
git add spikes/plan6
git commit -m "spike(teach): side-panel matching spike on JobLens"
```

### Task 2: The admin's run and the verdict

**Files:**
- Modify: `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (append "Spike result (date)" under rule 2)

- [ ] **Step 1: The admin runs it** (present at the Mac). Load `spikes/plan6/extension` unpacked in Chrome Profile 2 (`chrome://extensions` → Developer mode → Load unpacked), open its side panel, open `http://localhost:8100/`, then in Terminal: `.venv/bin/python spikes/plan6/match_spike.py`. Pass 1: Discover → Shortlisted → Review (first profile) → Approve & promote. Pass 2 as the script says. The admin pastes the output.
- [ ] **Step 2: Record the result** in the spec: the verdict line, which checks failed, the recorded roles and specs (no values), and the decision: PASS → write plan 2 on the observer mechanism; FAIL → stop and bring the failure to the admin with the options.
- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-11-12-teach-extension-design.md
git commit -m "docs(spec): teach extension matching spike result"
```
