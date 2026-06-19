# SFU Library Suite — web GUI

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
| `suite.html` | shell; keeps one iframe per app **alive** and toggles them (no reload/flash on switch); shows a loader until an app mounts |
| `search.html` / `analytics.html` / `index_manager.html` | thin HTML shells that load the **precompiled** `*.js` |
| `src/*.jsx` | **editable source** for each app (search.jsx bundles tweaks-panel) |
| `search.js` / `analytics.js` / `index_manager.js` | **auto-generated** by the build — do not edit |
| `tweaks-panel.jsx` | design-time tweak panel (bundled into `src/search.jsx`) |
| `lib/api.js` | `window.SFUApi` — live backend calls with mock fallback |
| `lib/mock.js` | `window.SFUMock` — sample/fallback data |
| `lib/ui.js` | `window.SFUUI` — the demo-data corner pill |
| `lib/base.css` | shared UX/accessibility baseline (reduced-motion, focus rings, responsive) |
| `vendor/` | React 18.3.1 + ReactDOM (served) + Babel-standalone (build-time only) |

## Live vs. demo data

Every `SFUApi` method tries the live backend first and falls back to `SFUMock`
on error/timeout, tagging the result `source: "live" | "mock"`. Whenever mock
data is shown — backend down **or** a live call returned nothing — `SFUUI`
renders a **demo-data banner** at the top of the app so it's never mistaken for
live results. The Search app's AI-status pill also reflects backend reachability.

## Backend endpoints used

`POST /api/search`, `GET /api/index_status`, `GET /api/personas`,
`POST /api/unpack`, `GET /analytics`, `POST /engagement`, `GET /health`.
See `docs/THIN_CLIENT_SWAP.md` → "Web GUI" for details.

## Editing & build

The apps are **precompiled** for fast loads (no in-browser Babel). To change an
app, edit its source in `web/src/<app>.jsx`, then rebuild:

```bash
node scripts/build_web.mjs        # compiles src/*.jsx -> web/*.js (uses vendored Babel)
```

`lib/*.js`, `lib/base.css`, and `suite.html` are plain JS/CSS — edit directly, no
build. Keep the design system (OKLCH tokens, DM Sans / Lora fonts, `--radius` 8/5/12,
accent `oklch(52% 0.18 25)`) consistent across apps — `scripts/e2e_sweep.mjs`
asserts cross-app token consistency. Sample data lives only in `lib/mock.js`.

Verify after changes: `PW=/tmp/rt/node_modules node scripts/e2e_sweep.mjs`
(needs Playwright installed; checks every screen at 4 viewports for errors,
overflow, load timing, banner no-shift, and design consistency).
