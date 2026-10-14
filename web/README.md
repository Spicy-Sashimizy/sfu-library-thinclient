# Duck Library Suite — web GUI

The web GUI for the thin-client stack. Implementation of the `claude.ai/design`
handoff bundle. Served as **static files at `/app`** by the HTTP entry point —
no Node/npm build step.

## Run it

```bash
cd src
MCP_HTTP_PORT=8080 ../.venv/bin/python3 -m uvicorn sfu_library_mcp_http:app --host 0.0.0.0 --port 8080
# open http://localhost:8080/app
```

`/app` redirects to `suite.html` (the shell), which mounts one app at a time.

## Layout

| Path | What |
|---|---|
| `suite.html` | shell; keeps one iframe per app **alive** and toggles them (no reload/flash on switch); shows a loader until an app mounts; **refuses to mount iframes for apps toggled off** in Settings → Interface (shows a notice instead) and tears them down when toggled off mid-session |
| `search.html` / `analytics.html` / `index_manager.html` | thin HTML shells that load the **precompiled** `*.js` |
| `source/*.jsx` | **editable source** for each app (`_sidebar.jsx` is prepended into every app by the build) |
| `search.js` / `analytics.js` / `index_manager.js` | **auto-generated** by the build — do not edit |
| `lib/api.js` | `window.SFUApi` — live backend calls (`health`, `search`, `searchStream`, `speculate`, `analytics`, `unpack`, plus the `engagement` event client added 2026-10-12) with mock fallback; surfaces HTTP 429 as `{source:"retry", retryAfter}` and passes through `degraded`/`degraded_shards` |
| `lib/mock.js` | `window.SFUMock` — sample/fallback data |
| `lib/ui.js` | `window.SFUUI` — the demo-data corner pill |
| `lib/interface_prefs.js` | extends `window.SFUUI` (created by `lib/ui.js`) with the bare-bones Interface prefs (§2): localStorage-persisted toggles for which nav items/apps are shown; broadcasts `suiteInterfacePrefs` so the shell unmounts toggled-off apps |
| `lib/base.css` | shared UX/accessibility baseline (reduced-motion, focus rings, responsive) |
| `vendor/` | React 18.3.1 + ReactDOM (served) + Babel-standalone (build-time only) |
| `CLAUDE.md` | agent rules for this directory (contracts, verify commands, `?v=duckN` cache-token rotation, engagement literal pinning) |

## Live vs. demo data

Every `SFUApi` method tries the live backend first and falls back to `SFUMock`
on error/timeout, tagging the result `source: "live" | "mock"`. Whenever mock
data is shown — backend down **or** a live call returned nothing — `SFUUI`
renders a **demo-data banner** at the top of the app so it's never mistaken for
live results. The Search app's AI-status pill also reflects backend reachability.

## Search progress + bare-bones default (WI-15)

Honest, threshold-staged search-progress indication + a progressive-disclosure
default screen, per `docs/infrastructure/GUI_BAREBONES_PROGRESS_SPEC.md`:

- **<300 ms** → nothing (a flashing indicator is worse than none).
- **300 ms–10 s** → skeleton result cards (`SkeletonResultCard`, `data-skeleton-card`)
  matching the live `ResultCard` box geometry exactly (zero layout shift) + an
  elapsed counter. Shimmer is opacity-only and pinned to ~0 ms under
  `prefers-reduced-motion` by `lib/base.css` rule 1.
- **>10 s AND `/health` says `warm=false`** → honest "index warming" message
  (keep skeletons). The `warm` flag is read forward-only (`/health` may omit it).
- **HTTP 429** → determinate "retrying in Ns" countdown from the `Retry-After`
  header, then one auto-retry of the same query.
- **`degraded`/`degraded_shards` on the response** → results render + a one-line
  degraded notice.

The default screen is Tier-0 minimal (search box, results, one status line); the
year/type/access/sort filters are a collapsed "Filters" expander (Tier-1) and the
rest are Settings → **Interface** toggles (Tier-2, localStorage). The demo-data
banner, degraded notices, and backend pill are an **integrity floor** — never
toggleable, never hidden. Verified headless by `scripts/verify_web_jsdom.mjs`
(offline+online mount, 429/degraded/warm plumbing, prefs persistence, integrity
floor) and `scripts/verify_web_progress.mjs` (skeleton ≥300ms / absent <300ms,
no layout shift, 429 countdown, degraded notice, toggle persistence across
reload); the browser-level sweep is `scripts/e2e_sweep.mjs` PASS 6.

## Backend endpoints used

`GET /health`, `POST /api/search`, `POST /api/search_stream` (only when the
server advertises the draft stream, gate `SFU_SEARCH_DRAFT_STREAM`),
`POST /api/speculate` (gate `SFU_SEARCH_SPECULATE`), `GET /analytics`,
`POST /api/unpack`, `POST /engagement`. The `SFUApi.indexStatus`/`personas`
clients were removed 2026-10-11 (no caller); the server still serves
`/api/index_status` and `/api/personas`. Since 2026-10-12 the search app posts
engagement events through `SFUApi.engagement` (per-tab session id in
`sessionStorage`, batched `{events:[...]}` flushes with `fetch(..., {keepalive:
true})` every 2 s or at 50 events, `navigator.sendBeacon` on `pagehide`; never
posts in mock mode), and the analytics app ("About this index") renders every
panel of the `/analytics` bundle, stub panels as "Not wired: <reason>". See
`docs/THIN_CLIENT_SWAP.md` → "Web GUI" for details.

## Editing & build

The apps are **precompiled** for fast loads (no in-browser Babel). To change an
app, edit its source in `web/source/<app>.jsx`, then rebuild:

```bash
node scripts/build_web.mjs        # compiles source/*.jsx -> web/*.js (uses vendored Babel)
```

`lib/*.js`, `lib/base.css`, and `suite.html` are plain JS/CSS — edit directly, no
build. Keep the design system (OKLCH tokens, DM Sans / Lora fonts, `--radius` 8/5/12,
accent `oklch(52% 0.18 25)`) consistent across apps — `scripts/e2e_sweep.mjs`
asserts cross-app token consistency. Sample data lives only in `lib/mock.js`.

Verify after changes: `PW=/tmp/rt/node_modules node scripts/e2e_sweep.mjs`
(needs Playwright installed; checks every screen at 4 viewports for errors,
overflow, load timing, banner no-shift, and design consistency).
