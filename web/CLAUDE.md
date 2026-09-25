# web/ — SFU Library Suite GUI

Vendored React 18 + in-browser Babel (`vendor/`) — NO CDN, NO npm build
step, strict CSP-friendly. Apps are single-file JSX ported from design
prototypes; shell (`suite.html`) iframes one app at a time (bulkhead).

Contracts (read before changing): `docs/infrastructure/
GUI_BAREBONES_PROGRESS_SPEC.md` (progress states + Interface toggles; the
integrity floor — demo banner/degraded notices/backend pill are NEVER
hideable), `WEBGUI_RELIABILITY_RESEARCH.md` (layer map).

Verify like 2026-06-19/WI-15: `node scripts/build_web.mjs` (Babel compile),
`node scripts/verify_web_jsdom.mjs` (42 checks as of 2026-09-01),
`node scripts/verify_web_progress.mjs` (18 checks), `scripts/e2e_sweep.mjs`
(Playwright, when browsers available). Zero console errors + zero
horizontal overflow + no layout shift are hard bars.

Search result paging (PAGE_SIZE 10, cap 5 pages, cumulative fetch + client
merge — the federated path ignores `page`): the constraint is recorded in
`docs/deprecated/oci_demo/OCI_DEMO_DEPLOYMENT.md` §GUI result paging. Editing
`web/lib/api.js` or `web/*.js` means rotating the `?v=duckN` token in all
four HTML files.
