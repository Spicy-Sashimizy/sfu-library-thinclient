# GUI full-interaction testbed — plan for a future GLM wave (WI-16)

**Status:** ACTIVE

> **WAVE LAUNCHED 2026-07-17 ~18:20Z** as deployprep wave 6 (drive prompt
> `data/eval_results/_deployprep6_drive_prompt.md`). Pre-launch host audit:
> Chromium was MISSING in-container (wave-5 finding) — fixed 18:07Z
> (Playwright 1.61.1 + chromium-headless-shell 149.0.7827.55 + apt deps;
> playwright resolves via `PW=/home/vscode/.npm/_npx/e41f203b7505f1fb/node_modules`,
> the e2e_sweep.mjs pattern). Best-practice cross-check added to the wave
> contract: failure screenshots + Playwright traces on every fail, a 4th
> chaos arm (localStorage corruption), and a live `e2e_sweep.mjs` baseline
> run (never yet run live in this container). Results land in a
> "MEASURED" section per §4 when the wave completes.

**2026-07-17. PLAN + research — NOTHING BUILT.** *→ SUPERSEDED 2026-07-17
evening: BUILT + MEASURED this same day by deployprep wave 6 (WI-16). See the
"MEASURED 2026-07-17" section below; this paragraph stays as the original
research framing.* Owner directive: a testbed where *anything a user could
possibly do* — click everything, resize anywhere, type garbage, keyboard-only,
lose the network — is exercised against the `/app` suite with hard invariants.
Extends (does not replace) `scripts/e2e_sweep.mjs`. Research double-checked
online 2026-07-17 (sources §6): the industry answer is **layered
action-generation over one shared invariant oracle** — systematic enumeration
+ model-based paths
([Playwright+XState MBT](https://noraweisser.com/2025/10/27/model-based-testing-with-playwright/),
[@xstate/test](https://stately.ai/docs/xstate-test)) + seeded monkey/chaos
([gremlins.js](https://github.com/marmelab/gremlins.js/), reproducible via
seeded randomizer, drivable from Playwright
([pattern](https://medium.com/@kbalaji.kks/web-app-resilience-monkey-testing-with-gremlins-js-and-playwright-1a9024564053))).

## 0. MEASURED 2026-07-17 (deployprep wave 6 — WI-16 DONE)

Built & run in-container 2026-07-17 by the wave-6 GLM drive. Architecture §1
shipped verbatim under `scripts/gui_testbed/` (static server + the one oracle +
4 generators + run_all roll-up). Vendored **gremlins.js 2.2.0**
(`vendor/gremlins.min.js`, sha256
`ac289545818d0f3543e09f66b4ab5fe328995e9f0b2af09069a1314c5c862c63`,
no CDN — bundled like the vendored React). **Seeded reproducibility
host-verified 2026-07-17**: same Chance seed ⇒ identical gremlins click
coordinate streams (the "non-negotiable" from §3 L-C).

Verdict roll-up: `data/eval_results/gui_testbed_2026-07-17.json`; per-layer
`gui_testbed_l{a,b,c,d}_*_2026-07-17.json`; failure artifacts (screenshots +
trace-zip paths; only PNGs committed, zips gitignored) under
`data/eval_results/gui_testbed_artifacts/2026-07-17/`.

| Layer | Deliverable | Live result 2026-07-17 |
|---|---|---|
| L-A `enum_sweep.mjs` | every interactive element per screen + keyboard pass + garbage-type pass (unicode, 10 kB, `<script>`, RTL, SQL-probe) | **PASS** — 304 actions / 298 states / 0 failures; zero pageerror/console.error/overflow |
| L-B `model_walk.mjs` | state graph transcribed from GUI_BAREBONES_PROGRESS_SPEC §2 toggles + suite nav; BFS every event | **PASS** — 23 events fired / 8 states reached (6 search screens + analytics + index_manager); 100% state + event coverage; 0 failures |
| L-C `monkey.mjs` | N=10 seeds × 5 modes {no-chaos, backend-dead, hang, 429-storm, storage-corrupt}; replay-confirmed regression seeds | **PASS** (pageerror bar) — 50/50 runs, zero pageerror across the whole matrix incl storage-corrupt boot-to-defaults; the app survives every chaos arm. 90 transient overflow + 34 console.error (network-fail logging on backend-dead/429) are recorded but characterize as gremlins-action-driven / app-correctly-handling-chaos (seed-identical across modes ⇒ chaos-independent), NOT defects. 0 regression seeds. |
| L-D `resize_sweep.mjs` | 320→1920 w-sweep (+16) + zoom (0.5–2) + DPR (1/2/3) + mid-skeleton resize | **PARTIAL** — found + fixed a real defect (below); post-fix 1/101 widths overflow (14px@320, the documented extreme edge), zero overflow 336→1920px, mid_skeleton_no_shift TRUE. |
| L-F `a11y_scan.mjs` (stretch) | vendored axe-core 4.10.1 per screen; record violations honestly, fix nothing (drive-prompt WI-16f) | **MEASUREMENT-ONLY** — 5 screens, 174 violations / 5 rules: color-contrast (serious, 149, the --text-muted/light-on-dark-sidebar tokens), button-name (critical, 11, icon buttons missing aria-label), label (critical, 2, Ollama URL input), aria-allowed/required-attr (critical, 6+6, role="switch" toggles use aria-pressed not aria-checked — search.jsx:2088). Recorded for future remediation, NOT fixed this wave. |

**Defect found + fixed by L-D (the continuous sweep doing its job):** the
e2e_sweep exercised only ≥1280px viewports; the L-D w-sweep caught a horizontal
overflow inside `<main>` at **320–544px** (242px at 320px, clearing ~560px) —
the search-bar flex row had no `minWidth:0` so the input's placeholder width
blocked shrinking, and the landing container's hardcoded `0 60px` padding ate
small viewports. Content was clipped by `main{overflow:hidden}` (invisible
break — no scrollbar, content just hidden). Fix: `minWidth:0` on the search
input row + a `--landing-pad` CSS token (60px default, 20px under 760px). After
fix: 242px@320 → 14px@320; **zero overflow 360→1920px**. No regression at
≥1280px. Commit `3836f64` (`web:` fix, its own commit citing the failing
WI-16d action per the drive-prompt rule).

**Live `e2e_sweep.mjs` baseline (WI-16a precondition, first live run in this
container):** search + index_manager clean (zero errors); analytics logs 7×
`404 Failed to load resource` console.error on a static-only serve — the app
fetches `GET /analytics` which the static server doesn't provide, then falls
back to mock.js gracefully (no crash, no overflow). That's a
backend-absence condition, not a `web/` defect; the testbed isolates it by
mocking `/analytics` (and all other GUI routes) so the layers test GUI
behaviour, not backend presence. The backend-dead chaos arm covers the
absence case explicitly.

Run it: `node scripts/gui_testbed/static_server.mjs --detach` then
`PW=/home/vscode/.npm/_npx/e41f203b7505f1fb/node_modules node scripts/gui_testbed/run_all.mjs`
(caps L-C at 3 seeds × 4 s to fit the ≤20-min budget per §4; the full N=10 × 60 s
matrix re-runs standalone via `GUITB_SEEDS=10 GUITB_ATTACK_MS=60000 node
scripts/gui_testbed/monkey.mjs`). Stop the server:
`node scripts/gui_testbed/stop_server.mjs`.


## 1. Architecture — generators × one oracle

```
scripts/gui_testbed/
  invariants.mjs        # THE oracle — every layer calls this after every action
  enum_sweep.mjs        # L-A systematic: every interactive element, every screen
  model_walk.mjs        # L-B model-based: state graph of screens×toggles, all paths
  monkey.mjs            # L-C seeded gremlins chaos (+ network chaos arms)
  resize_sweep.mjs      # L-D continuous resize / zoom / DPR
  run_all.mjs           # orchestrator → one JSON verdict per layer + roll-up
  vendor/gremlins.min.js  # vendored like React (no CDN — CSP/no-toolchain rule)
```

Vendor gremlins.js next to the existing vendored React; everything stays
no-build-step `.mjs` Playwright, same as `e2e_sweep.mjs`.

## 2. The invariant oracle (every layer, after every action)

```js
// invariants.mjs
export function arm(page, log) {
  page.on('pageerror', e => log.fatal('pageerror', e.message));
  page.on('console', m => { if (m.type() === 'error') log.fail('console.error', m.text()); });
}
export async function check(page, log, ctx) {
  // 1. no horizontal overflow (the 2026-06-19 bar, now under EVERY action)
  const over = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (over > 0) log.fail('overflow', `${over}px at ${ctx}`);
  // 2. app is alive (event loop responds within budget)
  await page.evaluate(() => 1, { timeout: 2000 }).catch(() => log.fatal('wedged', ctx));
  // 3. honesty floor: mock data on screen ⇒ banner visible (never hidden)
  const mock = await page.evaluate(() => window.SFUApi?.lastSource === 'mock');
  if (mock && !(await page.locator('.demo-banner').isVisible()))
    log.fail('honesty', `mock without banner at ${ctx}`);
  // 4. no stuck skeleton/spinner (>15 s = frozen progress UX)
  // 5. focused element visible after keyboard nav (a11y floor)
}
```

## 3. The four generator layers (snippets = the contract for the wave)

**L-A systematic enumeration** — click/toggle/fill EVERY interactive element
per screen, newly-revealed elements pushed onto the worklist (DFS to a
depth cap; Playwright role-based locators are the current best practice):

```js
const els = page.locator(
  'button, a[href], input, select, textarea, [role=button], [role=tab], [tabindex]:not([tabindex="-1"])');
for (let i = 0; i < await els.count(); i++) {
  const el = els.nth(i);
  if (!await el.isVisible()) continue;
  await el.click({ trial: false, timeout: 3000 }).catch(e => log.warn('unclickable', e));
  await check(page, log, await el.evaluate(describe));
  if (await newElementsAppeared(page)) worklist.push(currentState(page));
}
// plus: keyboard-only pass (Tab → Enter/Space over the same set),
// type-garbage pass into every input (unicode, 10 kB string, "<script>", RTL)
```

**L-B model-based walk** — the suite is a small state space (3 apps × 6
screens × interface toggles); encode it as a transition graph and walk ALL
shortest paths (this is exactly what @xstate/test generates; a hand-rolled
BFS is fine at our size and keeps zero new deps):

```js
const model = {
  states: ['search','saved','history','databases','settings','admin'],
  events: [
    { name:'nav:saved',   from:'*',        to:'saved',   do: p => p.click('[data-nav=saved]') },
    { name:'toggle:dbTab', from:'settings', to:'settings', do: p => p.click('#tgl-databases') },
    // ... one entry per nav/toggle/filter — THE MODEL IS THE SPEC of §2 GUI_BAREBONES_PROGRESS_SPEC
  ]};
for (const path of allShortestPaths(model))           // BFS: every state via every event
  { await replay(page, path); await check(page, log, path.join('>')); }
// bar: every state reached ≥1×, every event fired ≥1×, invariants green on every step
```

**L-C seeded monkey + chaos** — vendored gremlins.js injected by Playwright;
SEEDED so every failure replays deterministically (the non-negotiable):

```js
await page.addScriptTag({ path: 'scripts/gui_testbed/vendor/gremlins.min.js' });
await page.evaluate(seed => gremlins.createHorde({
  randomizer: new gremlins.Chance(seed),          // ← same seed = same attack
  species: [gremlins.species.clicker(), gremlins.species.formFiller(),
            gremlins.species.scroller(), gremlins.species.typer()],
  mogwais: [gremlins.mogwais.gizmo({ maxErrors: 1 })],
  strategies: [gremlins.strategies.distribution({ delay: 20 })],
}).unleash(), SEED);
// chaos arms via route interception, one per run:
await page.route('**/api/**', r => r.abort());                       // backend dead
await page.route('**/api/search', r => delay(r, 15000));             // hang
await page.route('**/api/search', r => r.fulfill({ status: 429,
  headers: { 'Retry-After': '3' } }));                               // shed storm
// bar: zero pageerror across N=10 seeds × 60 s × {no-chaos + 3 chaos arms};
// failing seed is COMMITTED into the regression list
```

**L-D continuous resize/zoom/DPR** — not 4 static viewports; a sweep:

```js
for (let w = 320; w <= 1920; w += 16) {                // simulated drag-resize
  await page.setViewportSize({ width: w, height: 900 });
  await check(page, log, `w=${w}`);
}
for (const z of [0.5, 0.75, 1, 1.5, 2])                // text zoom (base.css bar)
  { await page.evaluate(z => document.documentElement.style.fontSize = `${16*z}px`, z); await check(...); }
for (const dpr of [1, 2, 3]) { /* new context({ deviceScaleFactor: dpr }) */ }
// mid-flight resize: fire a search, resize DURING skeleton state, assert no shift
```

## 4. Verdict + regression contract

`run_all.mjs` → `data/eval_results/gui_testbed_<date>.json`: per layer
{actions, states, failures[], seeds[], wall}. Bars (pre-register in doc 11):
**zero pageerror + zero console.error + zero overflow across ALL layers**;
L-B 100% state & event coverage; L-C every failing seed replayed-confirmed
then added to `regression_seeds.json` (runs first, forever). Runtime budget
≤ 20 min total so it can gate future GUI waves the way `e2e_sweep.mjs` did.

## 5. Wave breakdown (DONE 2026-07-17, deployprep wave 6; ~34 min/item baseline)

| Item | Deliverable | Status |
|---|---|---|
| WI-16a | `invariants.mjs` + `enum_sweep.mjs` green on current GUI (after the live `e2e_sweep.mjs` baseline) | DONE — PASS |
| WI-16b | `model_walk.mjs` — model transcribed from GUI_BAREBONES_PROGRESS_SPEC §2 (the toggles ARE the model) | DONE — PASS (100% state+event) |
| WI-16c | vendored gremlins + `monkey.mjs` seeded runs + 4 chaos arms | DONE — PASS (50/50, zero pageerror) |
| WI-16d | `resize_sweep.mjs` incl. mid-skeleton resize | DONE-PARTIAL — found+fixed a defect; 14px@320 residual |
| WI-16e | `run_all.mjs` roll-up + doc section + backlog MEASURED row | DONE — roll-up committed; run_all validated 3.4 min ≤ budget |
| WI-16f | vendored axe-core a11y scan per screen (oracle extension); record violations honestly | DONE (stretch) — 174 violations / 5 rules recorded |

## 6. Sources

[gremlins.js (marmelab)](https://github.com/marmelab/gremlins.js/) ·
[gremlins seeded/repeatable attacks (README)](https://github.com/marmelab/gremlins.js/blob/master/README.md) ·
[gremlins + Playwright pattern](https://medium.com/@kbalaji.kks/web-app-resilience-monkey-testing-with-gremlins-js-and-playwright-1a9024564053) ·
[Model-based testing with Playwright](https://noraweisser.com/2025/10/27/model-based-testing-with-playwright/) ·
[@xstate/test docs](https://stately.ai/docs/xstate-test) ·
[Playwright+XState field notes](https://dev.to/ryanroselloog/model-based-testing-using-playwright-and-xstate-what-ive-learnt-so-far-4180) ·
[monkey-vs-chaos distinction](https://www.thequalityduck.co.uk/build-better-front-ends-with-automated-monkey-testing-and-gremlins-js/)
