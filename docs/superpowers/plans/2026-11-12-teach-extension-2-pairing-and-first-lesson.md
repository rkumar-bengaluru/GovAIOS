# Teach extension, plan 2: pairing and the first lesson — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The admin connects the GOV-AIOS extension once, then teaches "Approve shortlisted profiles" on JobLens from the side panel (Teach, Pause/Resume, Done, Cancel; steps and YAML live), names it as a **new app**, and approves it with one Touch ID. This is spec build steps 2 and 3, on the mechanism the spike passed (option A).

**Architecture:** The extension never touches the accessibility tree. Its content script, injected only into the tab being taught, reports each `pointerdown` (screen point, role, visible name, page origin and path; never values). The background worker POSTs it to the panel (`127.0.0.1:8765`, token header). The panel is sandboxed and has no PyObjC, so it does not read the click. It appends the event to `teach_in.jsonl`. A **Teach run** (the shipped `flows/teach.yaml`, approved once, launched by the panel like any app) polls that file every 10 ms and reads the element under the point at once (`desk.element_at`, then `web_root`, then the nearest clickable). It saves that element as an engine spec, writes the lesson to disk after every event, and writes the steps view to `teach_out.json`. The panel serves that file back to the side panel. At Done the panel makes a Draft app (`studio.new_automation`), binds the lesson to it, and the admin approves it on the existing lesson page (`approve_lesson`), which approves the new app too.

**Tech Stack:** Python 3 (`.venv`, pytest), pyobjc via `govaios/desktop/macos.py`, Chrome Manifest V3 (plain JS/HTML, no build step).

**Spec:** `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (rules 2, 3, 6, 7, the spike result, build order steps 2–3). Plan 1 (`…-1-matching-spike.md`) and `spikes/plan6/match_spike.py` hold the proven read-at-press code (`on_down`, `spec_of`, `COUNT`).

**Not in this plan (plans 3 and 4):** the repeat (rule 1), the first-run press grant and Try it (rules 4 and 5), Add to an app and Teach this page (rule 8), typed text (rule 9; this plan records clicks only), outside sites with terms and the waiver, page reuse questions (rule 10), Studio grouping and the page count, Show me, and editing a step's level. Until plan 3, **Approve & promote is taught as a hand-over**: the new app's run stops before it and the admin presses it, as runs do today.

## Global Constraints

- The extension watches and highlights only. It never clicks, types or submits. `content.js` never reads `.value`, `innerHTML` or form data, only `aria-label`, `innerText` (first 200 chars, trimmed), `tagName` and `role`.
- The extension talks only to `http://127.0.0.1:8765`. `host_permissions` is exactly `["http://127.0.0.1:8765/*", "http://localhost/*", "http://127.0.0.1/*"]`. The last two let it inject into the admin's own apps; outside sites come in plan 4.
- Pairing (rule 3): the 6-digit code goes through `totp.Verifier(home / "totp.state").verify`, so replays are refused. It is exchanged for `secrets.token_urlsafe(32)`, and only `sha256(token)` and the calling `Origin` are kept, in `<home>/extension.json` (0600, `O_NOFOLLOW`). Every `/ext/*` call except `/ext/pair` needs header `X-GovAIOS-Token` and `Origin` equal to the stored one. One connection: pairing again replaces the file. The Origin must match `^chrome-extension://[a-p]{32}$`.
- The extension's ID is fixed by a `key` (public key, base64 DER) in `extension/manifest.json`. The private key is never committed.
- Recording happens only while `panel.session.active()`. Ending the session stops the Teach run, as it stops any run; the lesson on disk is kept and **Resume** continues it.
- Plan 2 records only on `http://localhost:*` and `http://127.0.0.1:*` pages. Any other origin on the teach tab pauses recording with the side panel line *"Outside sites come later: recording paused."*
- Lesson files stay as today: `<home>/lessons/`, 0600, the `_NAME` pattern, no query in addresses, no masking (dev mode).
- Step lines name role and label only, never values: "JobLens · Discover: click Shortlisted".
- Commits go to `feat/teach-extension-build`. The admin merges.

## Rulings made while planning (to report to the admin)

- **The Teach run reads the click, not the panel.** — Why: the panel is sandboxed with no PyObjC; only a run process has Accessibility. — Cost if wrong: none for correctness; ~10 ms of file polling is added to the 9–17 ms the spike measured, well before a normal click's release.
- **Events reach the run through `teach_in.jsonl`, polled every 10 ms, not a socket.** — Why: runs allow only Unix sockets and the panel's profile binds only TCP; files are how the panel and runs already talk (`applyfiles`). — Cost if wrong: if late reads show up in the acceptance run (Task 7, step 3), switch to a Unix socket the run listens on.
- **Teach is a shipped app (`flows/teach.yaml`) the admin copies and approves once**, like Web Sandbox. It has no launch or navigate step: it pins the front Chrome window, the one whose side panel pressed Teach, so the page being taught is never navigated away. — Why: every run needs an approved flow and a ticket. — Cost: one setup step for the admin.
- **A new app is `studio.new_automation`'s Draft app.** The lesson binds to its `on_start` step, so `lessons.build` adds one `on_match` case per taught page (`then: again`, the last `then: end`), as it does today. Approving the lesson also approves the Draft, but only when the lesson says `new_app: true`, the app has never been approved, and its digest still equals the lesson's. — Why: Goal 11, one Touch ID. — Cost if wrong: a looser check would let a lesson approve an edited Draft. The digest check prevents that.
- **Step levels are guessed from role and name now** (spec, "Which presses are submit-level"). Tab, link and radio are `navigate`. A button whose name has a change word (Approve, Promote, Reject, Delete, Save, Send, Submit, Apply, Confirm) is `submit`; one with Pay, Buy or Checkout is `payment`. A button whose first word is Review, Open, View, Show, Close, Back, Details, More or Expand is `navigate`. Any other button is `submit`. `submit` and `payment` steps become hand-overs. — Why: today's `_risk` rates every tab `submit`, so the run would stop at Shortlisted. — Cost: an unknown button stops the run for the admin, which is safe. Editing levels comes in plan 3.
- **The spec is checked against the snapshot it was read from**, and that result (`sure`) is stored in the event. `lessons.propose` uses it instead of re-checking against the page's first tree. — Why: Review's row button reads "Close" once the pop-up opens, so the first tree is wrong for later steps. — Cost: none.
- **Resume on a different page is refused for now** (rule 7 wants a navigate step, and learned cases cannot hold one yet). The side panel says *"Go back to <page> to resume."* — Cost: one manual step for the admin; plan 3 adds the navigate step.
- **A press whose read name differs from the name the page reported is not saved.** The side panel says *"Run could not find this. Do it again, or skip it."* (rule 2). This also covers page zoom and multiple-display offsets.

## Review Focus

1. **Two JobLens pages share the title "JobLens".** A run must tell `/` from `/discover`. Expected: the home page is the known `joblens_applications` (heading Applications), and the Discover page is new with its heading `Discover` as anchor. Test in Task 4: `test_joblens_lesson_builds_two_cases`.
2. **The row's Review becomes "Close" when the pop-up opens.** Expected: Review saved as `{role: button, name: Review, index: 0}` and `sure: true` from its own snapshot. Test in Task 3: `test_spec_checked_against_its_own_snapshot`.
3. **A click on another tab, another window or the side panel.** Expected: nothing is recorded. The extension drops events from tabs other than the teach tab, and the run drops a down whose origin and path differ from `desk.current_url`. Tests in Tasks 3 and 6.
4. **The panel restarts or the session ends mid-lesson.** Expected: every step recorded so far is in the lesson file, and Resume continues the same lesson. Test in Task 3: `test_resume_appends_to_open_lesson`.
5. **A stale or replayed pairing code, or a web page calling `/ext/*`.** Expected: 403 with nothing changed. A page's `Origin` is `http(s)://…`, not `chrome-extension://`. Tests in Task 2.

---

### Task 1: Pairing store

**Files:**
- Create: `govaios/panel/extlink.py`
- Test: `tests/test_extlink.py`

**Interfaces:**
- Produces: `pair(home: Path, code: str, origin: str) -> str | None` (the token, or None for a bad code or origin); `check(home: Path, token: str | None, origin: str | None) -> bool`; `disconnect(home: Path) -> None`; `connected(home: Path) -> bool`. File `extension.json`: `{"hash": hex, "origin": str, "at": iso}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_pair_then_check(home_with_totp):    # fixture: a saved TOTP secret, clock fixed
    t = extlink.pair(home, code_now, "chrome-extension://" + "a" * 32)
    assert t and extlink.check(home, t, "chrome-extension://" + "a" * 32)
    assert not extlink.check(home, t, "chrome-extension://" + "b" * 32)
    assert not extlink.check(home, "x" + t, "chrome-extension://" + "a" * 32)
    assert t not in (home / "extension.json").read_text()
    assert (home / "extension.json").stat().st_mode & 0o777 == 0o600

def test_code_is_single_use(...): second pair() with the same code -> None, the first token still checks
def test_bad_origin_refused(...): pair(home, code, "https://evil.example") is None, no file written
def test_repair_replaces(...): a new pair() with the next code: the old token fails, the new one checks
def test_disconnect(...): check() False and connected() False after disconnect()
def test_symlink_refused(...): extension.json a symlink -> check() False, pair() None
```

- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_extlink.py -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** with `hmac.compare_digest` on the hex hashes. Write through a temp file + `os.replace` (as `totp._replace` does). Origin pattern `^chrome-extension://[a-p]{32}$`.
- [ ] **Step 4:** Run the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat(panel): extension pairing store (single-use code, hashed token, pinned origin)`.

### Task 2: The panel's `/ext/*` endpoints and Disconnect

**Files:**
- Modify: `govaios/audit/web.py` (`do_GET`, `do_POST`: an `/ext/` branch before the cookie checks; `studio_page`: a Disconnect form; `POSTS["/studio/disconnect"]`)
- Modify: `govaios/applyfiles.py` (constants `TEACH_IN = "apply/teach_in.jsonl"`, `TEACH_OUT = "apply/teach_out.json"`, `TEACH_OPEN = "apply/teach_open.json"`; `append_line(home, name, obj)` with `O_APPEND|O_NOFOLLOW`, 0600)
- Test: `tests/test_panel_web.py` (the `panel` fixture), `tests/test_applyfiles.py`

**Interfaces:**
- Consumes: `extlink.*` (Task 1); `start_run(hit, vals)`, `apps()`, `panel.session`, `panel.run_id`.
- Produces: JSON endpoints (all `Content-Type: application/json`; every response carries the `SEC` headers):
  - `POST /ext/pair {code}` → 200 `{token}` | 403.
  - `GET /ext/state` → `{signed_in: bool, recording: bool, paused: bool, lesson: str|null, lines: [str], yaml: str, note: str}`. Recording state comes from `teach_out.json`, but only when its `run` equals `panel.run_id` and the run is live.
  - `POST /ext/teach {tab_url}` → starts the approved app with id `teach`, with input `lesson` = the open lesson's name from `TEACH_OPEN`, or `new`. 409 `{note}` when signed out, when another run is live, or when Teach is not approved.
  - `POST /ext/event {kind: down|pause|resume|done|cancel, …}` → appends `{run: panel.run_id, …}` to `TEACH_IN`. 409 when no Teach run is live.
  - `POST /ext/done {name}` → Task 4's binding. 200 `{lesson_url: "/lesson/<name>"}`.
  - `POST /ext/discard` → deletes the open lesson file and `TEACH_OPEN`.
- Bodies are JSON, at most 4096 bytes. A field outside the event's known keys is dropped. `name` and `role` are cut to 200 chars; `x` and `y` must be finite numbers.

- [ ] **Step 1: Write the failing tests** (in `tests/test_panel_web.py`):

```python
def test_ext_pair_and_state(panel): POST /ext/pair with the current code and Origin chrome-extension://a…a -> 200 token;
    GET /ext/state with token + origin -> 200 json signed_in False
def test_ext_refuses_web_origin(panel): same call with Origin http://localhost:8100 -> 403
def test_ext_refuses_without_token(panel): /ext/state with no token -> 403
def test_ext_event_needs_live_teach_run(panel): -> 409
def test_ext_teach_starts_the_teach_app(panel): session open, teach.yaml approved -> launcher made with inputs {"lesson": "new"}
def test_ext_event_appended_with_run_id(panel): after teach, POST down -> teach_in.jsonl last line has run == panel.run_id,
    no keys other than run, kind, x, y, name, role, tag, url, t
def test_studio_disconnect_ends_open_lesson(panel): POST /studio/disconnect (csrf) -> extension.json gone, TEACH_OPEN gone,
    the open lesson file gone, audit entry "extension" outcome "disconnected"
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.** The `/ext/` branch runs inside `guarded` (Host and screen-lock checks stay). It skips the cookie, CSRF and `Origin == 127.0.0.1` checks, because the stored Origin plus the token replace them. Audit `extension` entries for pair (allow or deny) and disconnect. Never audit the token or the code.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest tests/test_panel_web.py tests/test_applyfiles.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(panel): extension endpoints, pairing and Disconnect in Studio`.

### Task 3: The recorder (reads each press in the Teach run)

**Files:**
- Create: `govaios/recorder.py`
- Modify: `govaios/desktop/macos.py` (public `element_at(self, x: float, y: float)`, which returns `self._hit((x, y))`)
- Modify: `govaios/lessons.py` (`level(role: str, name: str) -> str`, per the ruling; `new_name(flow_id) -> str` and `write(home, name, doc) -> None`, split out of `save`, which then calls them: same 0600, temp file + replace, same KEEP pruning)
- Test: `tests/test_recorder.py`, `tests/test_lessons.py`

**Interfaces:**
- Consumes: `lessons.write/new_name/load/level`, `studio.element_spec`, `capture.tree`, `engine.find_all`, `applyfiles.write_json`.
- Produces: `class Recorder(desk, app, home, run_id, lesson: str | None)` with:
  - `.handle(ev: dict) -> None` (one `teach_in` line);
  - `.name` (the lesson file name);
  - `.done`, `.cancelled` (bools);
  - `.paused` (bool).

  The lesson doc is `{"flow": "teach_new", "digest": None, "step": None, "at", "new_app": True, "pages": [{url, title, tree, events}]}`.
  - A click event is `{"kind": "click", "spec", "label", "value": "", "secure": False, "submit": level != "navigate", "risk": level, "sure": bool}`.
  - `teach_out.json` is `{run, lesson, paused, note, lines}`.
  - `TEACH_OPEN` is `{"lesson": name}` while open; it is removed on done or cancel.

- [ ] **Step 1: Write the failing tests** with a fake desk (`element_at`, `web_root`, `current_url`, `same`) returning `Node` trees built in the test:

```python
def test_down_records_a_click_step(): home tree with link Discover; ev down at its point, url http://localhost:8100/
    -> lesson file has one page (url http://localhost:8100/) with one event {kind: click, spec: {role: link, name: Discover},
       risk: navigate, sure: True}; teach_out lines == ["JobLens · Applications: click Discover"]
def test_counted_name_saved_without_count(): tab "Shortlisted (2)" -> spec name_matches '^Shortlisted \\(\\d+\\)$', risk navigate
def test_spec_checked_against_its_own_snapshot(): two rows with Review; down on row 1 -> spec index 0, sure True, even though
    a later snapshot renames it Close
def test_name_mismatch_not_saved(): ev name "Review", element read "Skip" -> no event; note == "Run could not find this. Do it again, or skip it."
def test_other_page_down_dropped(): ev url path /discover while desk.current_url is /  -> nothing recorded
def test_outside_origin_pauses(): current_url https://example.com/ -> paused, note "Outside sites come later: recording paused."
def test_new_path_starts_a_page(): downs on / then /discover -> two pages, each with its own first-snapshot tree
def test_pause_drops_downs(): pause, down, resume, down -> one event
def test_resume_elsewhere_refused(): pause on /discover, resume with current_url / -> still paused, note "Go back to JobLens · Discover to resume."
def test_resume_appends_to_open_lesson(): Recorder(lesson=name of an existing file) -> its next click is appended to that file's pages
def test_cancel_deletes_lesson(): cancel -> lesson file and TEACH_OPEN gone
def test_level(): level("tab","Shortlisted (2)")=="navigate"; level("button","Review")=="navigate";
    level("button","Approve & promote")=="submit"; level("button","Pay now")=="payment"; level("button","Frobnicate")=="submit"
```

- [ ] **Step 2:** Run `.venv/bin/python -m pytest tests/test_recorder.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** `on_down` as `spikes/plan6/match_spike.py`'s `on_down` + `spec_of`:
  - read the element at the point, take a snapshot, then climb to `("link", "button", "tab", "radio")`;
  - `sure = find_all(snapshot, spec) == [node]` by identity;
  - the page key is origin + path. The page's stored tree is its first snapshot, and its title comes from the heading: `"<site name> · <first h1>"`, where the site name is the document title, so "JobLens · Discover".

  Write the lesson file after every saved event.
- [ ] **Step 4:** Run the tests. Expected: PASS. Then run `.venv/bin/python -m pytest -q`. Expected: all pass (`lessons.save` keeps its behaviour).
- [ ] **Step 5: Commit** `feat(teach): recorder reads each press at once and writes the lesson as it goes`.

### Task 4: Done → new app → one Touch ID

**Files:**
- Modify: `govaios/lessons.py`:
  - `bind(home, name, flow_id, digest, step) -> None`: rewrites the lesson's flow, digest and step;
  - `propose` uses `ev["sure"]` and `ev["risk"]` when present, and turns `payment` into a hand-over as it does `submit`;
  - `preview(lesson, pages_dir, bank) -> tuple[list[str], str]`: the step lines and the YAML of the `on_match` cases `build` would add.
- Modify: `govaios/audit/web.py`:
  - `/ext/done` makes the app with `studio.new_automation(flows_dir, name, first page url, approved_browser())`, takes its digest from `read_bound`, then `bind(…, "on_start")` and removes `TEACH_OPEN`;
  - `approve_lesson` adds the new-app rule from the rulings, with the Touch ID text `Approve the new app <name> and what GOV-AIOS learned`;
  - `/ext/state` fills `yaml` from `preview`.
- Test: `tests/test_lessons.py`, `tests/test_panel_web.py`

- [ ] **Step 1: Write the failing tests:**

```python
def test_joblens_lesson_builds_two_cases(tmp_path): a lesson with page / (tree: heading Applications, link Discover; event click
    Discover) and page /discover (tree: heading Discover, tab Shortlisted (2), two rows with Review; events Shortlisted, Review,
    Approve & promote risk submit) bound to a new_automation app -> build's flow: on_start.on_match has joblens_applications
    {do: [click …discover], then: again} and a new page id with do [click shortlisted, click review, hand_over], then: end;
    "unknown" stays last; the new page's identification anchors its Discover heading and does not identify the home tree
def test_preview_lines_and_yaml(): preview(...) lines == ["JobLens · Applications: click Discover",
    "JobLens · Discover: click Shortlisted", "JobLens · Discover: click Review", "JobLens · Discover: you press Approve & promote"]
def test_new_app_lesson_approves_the_draft(panel): /ext/done name "Approve shortlisted" -> flows/studio_approve_shortlisted.yaml;
    POST /lesson/approve -> one prove() call with "Approve the new app Approve shortlisted and what GOV-AIOS learned";
    Approvals.flow_ok(app id, new digest) True
def test_new_app_lesson_refused_if_draft_edited(panel): edit the draft after Done -> "changed since this lesson", nothing approved
def test_new_app_rule_needs_never_approved(panel): an app approved once, then revoked, with new_app lesson -> refused
```

- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(teach): Done makes a new app; approving its lesson approves it with one Touch ID`.

### Task 5: The Teach app and its engine action

**Files:**
- Create: `flows/teach.yaml`. It has id `teach`, app `Teach`, a browser block copied from `web_sandbox.yaml`, input `lesson` with pattern `new|[0-9-]{22}-[a-z0-9_]{1,64}\.json`, permissions `allow: [read_page, teach]` with `max_element_risk: read`, `destinations: []`, and steps `[{id: record, action: record_lesson}]`.
- Modify: `govaios/engine.py` (`do_record_lesson`): refuse unless Chrome is in front. It pins `focused_window_id`, gates `teach` (`read`), then loops every 0.01 s. Each pass reads the new lines of `TEACH_IN` whose `run` equals its run id and feeds them to `Recorder.handle`. Every 0.5 s it checks `runstate.stopped` and `auth.screen_locked` (Stop, as `ask` does). It ends on done or cancel, and also after `TEACH_IDLE_S` with no event while not paused; the lesson is kept. It audits `lesson` with outcome `recorded` and the lesson name.
- Test: `tests/test_teach.py`

- [ ] **Step 1: Write the failing tests:** `test_record_lesson_feeds_events_and_ends_on_done`, `test_record_lesson_stops_on_emergency_stop`, and `test_record_lesson_ignores_other_run_lines` (fake desk, lines written to `TEACH_IN` before the call), and `test_teach_flow_loads_and_checks` (the shipped `flows/teach.yaml` passes the engine's flow check).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** Run `.venv/bin/python -m pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat(teach): the Teach app, a run that records from the extension's presses`.

### Task 6: The extension

**Files:**
- Create: `extension/manifest.json` (MV3, name `GOV-AIOS Teach`, version `0.1.0`, `key`, permissions `["sidePanel", "storage", "scripting", "tabs"]`, host_permissions per Global Constraints, `side_panel.default_path: sidepanel.html`, `background.service_worker: background.js`)
- Create: `extension/background.js`, `extension/content.js`, `extension/sidepanel.html`, `extension/sidepanel.js`
- Create: `extension/README.md` (load unpacked, the ID, how to pair)
- Test: `tests/test_extension_files.py`

**Interfaces:**
- Consumes: Task 2's endpoints.
- `background.js` holds the token (`chrome.storage.local`) and the teach `tabId`. It injects `content.js` into the teach tab at Teach and after each load of that tab (`tabs.onUpdated` status `complete`). It forwards a `down` only when the message came from that tab and the lesson is not paused. Its fetches go only to `http://127.0.0.1:8765`.
- `content.js` listens for `pointerdown` in the capture phase and sends `{kind: "down", x: screenX, y: screenY, name, role, tag, url: location.origin + location.pathname, t: Date.now()}`. It draws a fixed red **● Recording** sign in a closed shadow root and removes it when told to stop. It has no listener for page `message` events.
- `sidepanel.html/js`:
  - Not paired: a 6-digit field and **Connect**.
  - Paired: **Teach**, **Pause**/**Resume**, **Done** (asks the app's name), **Cancel**, a **Steps** tab and a **YAML** tab (from `/ext/state`, polled every 500 ms while open), the note line, and **Resume** / **Discard** when a lesson is open.
  - Signed out: *"Sign in to the panel (type your code on Home) to record."*
  - After Done it opens `http://127.0.0.1:8765<lesson_url>` in a new tab.

- [ ] **Step 1: Write the failing tests** (`tests/test_extension_files.py`):
  - `host_permissions` equals the list in Global Constraints.
  - `key` is present and is valid base64.
  - No `content_scripts` entry: content is injected only into the teach tab.
  - `content.js` never contains `.value`, `innerHTML` or `addEventListener("message"`, and `background.js` never fetches any host other than `127.0.0.1:8765`.
  - The ID derived from `key` (sha256 of the DER, first 32 hex digits mapped 0-f → a-p) is printed in `README.md`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Generate the key** (`openssl genrsa 2048 | openssl rsa -pubout -outform DER | base64`), keeping the private key out of the repo. Then write the files.
- [ ] **Step 4:** Run `.venv/bin/python -m pytest tests/test_extension_files.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(extension): GOV-AIOS Teach side panel (connect, teach, pause, done, steps and YAML)`.

### Task 7: The admin's acceptance run on JobLens

**Files:**
- Modify: `docs/superpowers/specs/2026-11-12-teach-extension-design.md` (a "Plan 2 result" line under Build order)
- Modify: `docs/backlog.md` (rule 7's navigate-on-resume, editing levels)

- [ ] **Step 1: Prepare** (admin):
  - rebuild and install;
  - copy `flows/teach.yaml` into the apps folder and approve **Teach**;
  - in `chrome://extensions`, remove the spike extension and load `extension/`;
  - open its side panel, type the panel code, then **Connect**.
- [ ] **Step 2: Teach** (admin):
  - type the code on Home to open a session;
  - on `http://localhost:8100/`, press **Teach**;
  - click Discover, Shortlisted, then Review on the first profile, then press Approve & promote yourself (the lesson records it as your hand-over);
  - press **Done** and name it **Approve shortlisted**, then **Approve** on the lesson page (Touch ID).

  Expected: the Steps tab showed the four lines of `test_preview_lines_and_yaml` as they happened.
- [ ] **Step 3: Run it** (admin): `run approve shortlisted` on Home. Expected: it opens Google, checks the account and opens JobLens. It clicks Discover, Shortlisted and Review on the next profile, then stops before Approve & promote, which the admin presses. Paste the result card.
- [ ] **Step 4: Record** the result in the spec, park the deferred items in `docs/backlog.md`, and commit `docs(spec): teach extension plan 2 result`.
