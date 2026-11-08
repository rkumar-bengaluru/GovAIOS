# Studio drafts from the Web Sandbox — design (2026-11-08, night 2)

Branch `feat/studio-drafts`. The admin's vision: analyse web pages one by one in the sandbox, get a draft flow per page,
then later build a bigger flow (an app) by linking those draft pages.

## How it works now

1. **Capture**: in the Web Sandbox the admin presses *Capture this page*. The engine saves the capture as before. If the flow allows `write_draft` (gated and audited like any action), it also writes two files into the apps folder:
   - **a draft page** `apps/pages/<site>_<title>.yaml`, built by `govaios/studio.py` from the capture:
     - identification: the exact document title, plus up to two headings as anchors;
     - elements: headings, form fields, buttons and up to 40 links.
     - Fields use a stable DOM id when there is one, and their name otherwise. Ids made up per page load (React, react-select, Radix, Headless UI, UUIDs) are never used.
     - An element whose spec matches more than once gets an `index`, so it resolves to exactly one node.
     - Risks are conservative: fields are modify, links are navigate, and every button is **submit** until it's reviewed. Page values are never written, only names and ids.
   - **a Check app** `apps/flows/check_<page>.yaml`: read only (launch, navigate, read_page). It opens the captured page (path only, never the query) and identifies it with the draft page. It appears in the panel's **Drafts**; nothing runs until the admin approves it.
2. **Verify**: approve the Check app and run it. If it reaches the page and identifies it, the draft page matches the live site.
3. **Link into a bigger flow**: a flow uses a page by its id (`classify_page` `on_match`, `target: <page>.<element>`). Approving that flow binds the page's exact bytes (`approvals.read_bound`), so editing a linked draft page later needs the flow approved again. This is tested in `tests/test_studio.py::test_a_bigger_flow_links_draft_pages_by_id`.

Checked on the admin's four real captures (Greenhouse ×3, Google): each draft identified its own capture, and every element resolved to exactly one node.

## Composing a bigger app (built 2026-11-09, branch `feat/studio-compose`)

The panel has a **Studio** page (rail link). It lists the draft pages that have a Check app, each with its start URL and whether its Check app is approved. Below the list, **Compose an app** takes a name and up to 10 steps, each picked from a list:
- **Open `<page>`**: step 1 opens the page's URL; a later Open waits for the page a click led to;
- **Click `<element>` on `<page>`**: only links and buttons rated read, navigate or modify are offered. A submit-rated click is never offered, and the core refuses it too;
- **Fill the form on `<page>`**: from the answer bank, with fix cards for failed fields. A draft page has no `form_region`, so the whole page is the form;
- **Hand over**: you check and submit in Chrome, then press Next.

**Save as a Draft app** writes `apps/flows/studio_<name>.yaml` (exclusive, never replacing an app) and audits a `setting` / `studio_compose` entry. The flow's permissions are only what its steps need; its destinations are Google plus each opened page's site; its element ceiling is the highest-rated click. It runs only after you approve it, and that approval binds every draft page it uses.

The core, `studio.catalogue()` + `studio.compose()` + `studio.write_composed()`, is UI-free, so a CLI or an LLM writer can use it later and get the same checks.

## Not built yet (next steps)

- **Repeated items** (lists, rows, cards: "for each job") in composed apps.
- **A preview** of the composed YAML before saving, and editing a composed app in Studio.
- **Lowering button risks** where it's safe: a reviewed Next or Continue becomes navigate.
- **Masking captures** (spec §5.3, with the form amendment) before Studio leaves dev mode.
- Page `fields:` for repeated items (job cards, rows) are not drafted. Claude adds them when a list page is linked.
