# Spike: live AX tree capture (himalayas.app/jobs/matches)

Checks Ground Rule 3 before the governance layer is designed: can a page
schema (README §7) be written from the macOS accessibility tree of a real,
visible, logged-in Chrome? Run on Himalayas instead of Gmail.

Run: open the page in Chrome, then `swift axdump.swift > tree.txt`
(the terminal needs Accessibility permission; run twice, see below).

## Findings (2026-11-05)

- The first run only sets `AXEnhancedUserInterface`/`AXManualAccessibility`;
  the `AXWebArea` appears on the next read. The runtime must enable, wait,
  and verify the tree is populated.
- 1047 nodes, proper landmarks, named controls. All 20 job cards are
  `AXDocumentArticle` with the same shape: title, company, `AXTimeGroup`.
- Tag link count varies per card (5-8 links): never address by `position: last`.
- Company names can carry badge text ("NVIDIA Verified").
- Ad iframes sit inside the results container as nested `AXWebArea`s;
  filter by subrole. Their content is untrusted (Rule 7).
- "Save job" changes account data: `risk: submit`.
- Not covered: tree stability across reloads, page 2, expired session,
  acting on elements, Gmail.

`himalayas_matches.yaml` is the resulting page schema. The raw dump is not
committed because it contains personal job matches.
