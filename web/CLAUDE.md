# web/ — Duck Library Suite GUI

Vendored React 18 + in-browser Babel (`vendor/`) — NO CDN, NO npm build
step, strict CSP-friendly. Apps are single-file JSX ported from design
prototypes; shell (`suite.html`) iframes one app at a time (bulkhead).

Contracts (read before changing): `docs/infrastructure/
GUI_BAREBONES_PROGRESS_SPEC.md` (progress states + Interface toggles; the
integrity floor — demo banner/degraded notices/backend pill are NEVER
hideable), `WEBGUI_RELIABILITY_RESEARCH.md` (layer map).

Verify like 2026-06-19/WI-15: `node scripts/build_web.mjs` (Babel compile),
`node scripts/verify_web_jsdom.mjs` (105 checks as of 2026-10-12),
`node scripts/verify_web_progress.mjs` (18 checks), `scripts/e2e_sweep.mjs`
(Playwright, when browsers available). Zero console errors + zero
horizontal overflow + no layout shift are hard bars.

Search result paging (PAGE_SIZE 10, cap 5 pages, cumulative fetch + client
merge — the federated path ignores `page`): the constraint is recorded in
`docs/infrastructure/OCI_DEMO_DEPLOYMENT.md` §GUI result paging. Editing
`web/lib/api.js` or `web/*.js` means rotating the `?v=duckN` token in all
four HTML files.

Engagement (2026-10-12): the search app posts query / impression /
result_click / action events via `SFUApi.engagement` (`web/lib/api.js`). Its
`ENGAGEMENT_ACTION_TYPES` / `ENGAGEMENT_KINDS` literals must equal
`ACTION_TYPES` / `KINDS` in `source/lib/engagement.py` (pinned by
`source/tests/test_engagement_gui.py` and a jsdom check). The analytics app shows
only figures the `/analytics` bundle supplies; never add a hard-coded number.
