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

## Not built yet (next steps)

- **Composing a bigger flow from the panel**: pick draft pages in order, choose a step for each (fill this form, click this button, wait for this page), and preview the flow YAML. Today Claude writes the bigger flow by hand from the draft pages.
- **Lowering button risks** where it's safe: a reviewed Next or Continue becomes navigate.
- **Masking captures** (spec §5.3, with the form amendment) before Studio leaves dev mode.
- Page `fields:` for repeated items (job cards, rows) are not drafted. Claude adds them when a list page is linked.
