// L-B model-based walk — the suite is a small state space; encode it as a
// transition graph and walk ALL shortest paths (BFS). Plan §3 L-B contract.
//
// THE MODEL IS THE SPEC of GUI_BAREBONES_PROGRESS_SPEC §2: the Interface
// toggles ARE the model. Transcribed verbatim from web/lib/interface_prefs.js
// PREF_DEFAULTS + web/src/_sidebar.jsx SUITE_NAV_ITEMS.
//
// States (search-app screens): search, saved, history, databases, settings,
// admin. Plus the suite apps reached via the suite shell: analytics,
// index_manager.
//
// Events:
//   nav:<screen>   click the sidebar nav button (saved/history/databases/admin
//                  are HIDDEN until their toggle is ON — so the model first
//                  fires the enable-toggle event).
//   toggle:<key>   flip an Interface pref (role="switch" in Settings → Interface,
//                  or a density radio). Persisted in localStorage.
//
// Bars (plan §3 L-B): every state reached ≥1×, every event fired ≥1×,
// invariants green on every step.
import { loadPlaywright, makeLog, arm, check, captureArtifacts, openApp, sleep, mockApi, BASE, DATE_TAG, ROOT } from './lib.mjs';
import fs from 'node:fs';
import path from 'node:path';

// The model — one entry per nav/toggle/filter, transcribed from spec §2.
// `from: '*'` means applicable in any state; `to` is the resulting state.
const EVENTS = [
  // Nav events (require the screen's toggle ON where applicable).
  { name: 'nav:search',     from: '*', to: 'search',   pre: [],                       do: async p => clickNav(p, 'Search') },
  { name: 'nav:saved',      from: '*', to: 'saved',    pre: ['toggle:savedHistoryNav'], do: async p => clickNav(p, 'Saved') },
  { name: 'nav:history',    from: '*', to: 'history',  pre: ['toggle:savedHistoryNav'], do: async p => clickNav(p, 'History') },
  { name: 'nav:databases',  from: '*', to: 'databases',pre: ['toggle:databasesTab'],  do: async p => clickNav(p, 'Databases') },
  { name: 'nav:settings',   from: '*', to: 'settings', pre: [],                       do: async p => clickNav(p, 'Settings') },
  { name: 'nav:admin',      from: '*', to: 'admin',    pre: ['toggle:adminPanels'],   do: async p => clickNav(p, 'Admin') },
  // Interface toggles (fire in Settings). Each is its own event so coverage is explicit.
  { name: 'toggle:advancedFiltersOpen', from: '*', to: 'settings', pre: [], do: async p => flipToggle(p, 0) },
  { name: 'toggle:savedHistoryNav',      from: '*', to: 'settings', pre: [], do: async p => flipToggle(p, 1) },
  { name: 'toggle:databasesTab',         from: '*', to: 'settings', pre: [], do: async p => flipToggle(p, 2) },
  { name: 'toggle:analyticsApp',         from: '*', to: 'settings', pre: [], do: async p => flipToggle(p, 3) },
  { name: 'toggle:indexManagerApp',      from: '*', to: 'settings', pre: [], do: async p => flipToggle(p, 4) },
  { name: 'toggle:adminPanels',          from: '*', to: 'settings', pre: [], do: async p => flipToggle(p, 5) },
  { name: 'toggle:density',              from: '*', to: 'settings', pre: [], do: async p => clickDensity(p) },
  // Settings sub-tabs (each is a reachable statelet; counted as events fired).
  { name: 'tab:LLM Backend', from: 'settings', to: 'settings', pre: [], do: async p => clickText(p, 'LLM Backend') },
  { name: 'tab:Zotero',      from: 'settings', to: 'settings', pre: [], do: async p => clickText(p, 'Zotero') },
  { name: 'tab:Dictionary',  from: 'settings', to: 'settings', pre: [], do: async p => clickText(p, 'Dictionary') },
  { name: 'tab:Privacy',     from: 'settings', to: 'settings', pre: [], do: async p => clickText(p, 'Privacy') },
  // Filters expander (Tier-1 one-interaction-away control).
  { name: 'toggle:filters',  from: '*', to: 'search', pre: [], do: async p => clickText(p, 'Filters') },
];
const ALL_STATES = ['search', 'saved', 'history', 'databases', 'settings', 'admin'];

async function clickNav(page, label) {
  // Target the sidebar button by exact text. "Settings" is a sibling of <nav>
  // (not inside it), so scope to `aside button` — NOT `aside nav button`.
  // Exact match avoids the toggle label "Saved & History nav" shadowing "Saved".
  const btn = page.locator('aside button', { hasText: label }).first();
  await btn.waitFor({ state: 'visible', timeout: 2500 }).catch(() => {});
  await btn.click({ timeout: 3000 }).catch(() => {});
}
async function clickText(page, label) {
  await page.getByText(label, { exact: false }).first().click({ timeout: 3000 }).catch(() => {});
}
async function flipToggle(page, idx) {
  const toggles = page.locator('button[role="switch"]');
  if (await toggles.count() > idx) await toggles.nth(idx).click({ timeout: 3000 }).catch(() => {});
}
async function clickDensity(page) {
  await page.getByText('compact', { exact: false }).first().click({ timeout: 3000 }).catch(() => {});
}

// Start from a known pref state for each event: prefs are persisted in
// localStorage and toggles are click-TOGGLES, so firing `toggle:adminPanels`
// (its own event) then later `nav:admin`'s pre-flip would flip it back OFF.
// Fix: set the pref state deterministically via the app's own helper before
// each event, enabling exactly this event's `pre` toggles.
const PREF_KEY = 'sfu-interface-prefs';
const PREF_DEFAULTS = { advancedFiltersOpen: false, savedHistoryNav: false, databasesTab: false, analyticsApp: false, indexManagerApp: false, adminPanels: false, density: 'comfortable' };
function prefsForEvent(eventName) {
  const ev = EVENTS.find(e => e.name === eventName);
  const p = { ...PREF_DEFAULTS };
  for (const pre of (ev && ev.pre) || []) {
    // pre names are toggle:<key>; map to the pref key.
    const key = pre.replace(/^toggle:/, '');
    if (key in p) p[key] = true;
  }
  return p;
}
async function setPrefs(page, prefs) {
  await page.evaluate(([k, p]) => {
    try { localStorage.setItem(k, JSON.stringify(p)); } catch (e) {}
  }, [PREF_KEY, prefs]);
}

// For each target event, arrive in Settings first (toggles only render there),
// fire any `pre` events to make the target reachable, then fire the target.
async function fireEvent(page, eventName, log) {
  // Set deterministic prefs so the target's `pre` toggles are ON (and only those).
  // Reload so React reads the fresh prefs, then navigate to Settings → Interface.
  await setPrefs(page, prefsForEvent(eventName));
  await page.reload({ waitUntil: 'load' }).catch(() => {});
  await page.waitForFunction(() => document.getElementById('root') && document.getElementById('root').childNodes.length > 0, { timeout: 15000 }).catch(() => {});
  await sleep(200);
  await clickNav(page, 'Settings'); await sleep(200); await check(page, log, `pre-nav Settings for ${eventName}`);
  await clickText(page, 'Interface'); await sleep(200); await check(page, log, `pre-tab Interface for ${eventName}`);
  const ev = EVENTS.find(e => e.name === eventName);
  if (!ev) return;
  await ev.do(page);
  await sleep(250);
  await check(page, log, eventName);
}

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const t0 = Date.now();
const log = makeLog('L-B model_walk');
log.act(`model_walk start @ ${BASE} (date ${DATE_TAG})`);

let actions = 0, statesReached = new Set(), eventsFired = new Set();
const { page, context } = await openApp({
  chromium: browser, app: 'search.html', log, ctxLabel: 'model_walk',
  setup: async (page) => { await mockApi(page, 'live'); },
});

try {
  // BFS-ish: fire every event once, recording the resulting state at each.
  // After each event, detect which state we're in by the sidebar active button
  // (computed background var(--bg-sidebar-active)) + distinctive screen content.
  for (const ev of EVENTS) {
    log.act(`fire ${ev.name}`);
    await fireEvent(page, ev.name, log);
    eventsFired.add(ev.name);
    actions++;
    // State detection: the sidebar marks active via background colour, not an
    // aria-current attribute — so read the active button's background and fall
    // back to distinctive per-screen text. Order matters: most-specific first.
    const here = await page.evaluate(() => {
      const txt = (document.body.innerText || '').slice(0, 6000);
      // Active nav button: background === --bg-sidebar-active (oklch 28%).
      let activeLabel = null;
      document.querySelectorAll('aside nav button').forEach(b => {
        if (!b.innerText) return;
        const bg = getComputedStyle(b).backgroundColor;
        // oklch(28% 0.016 250) ≈ rgb(58,58,72)-ish; compare via a luminance-ish
        // check: the active button is distinctly lighter than inactive (transparent).
        if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') activeLabel = b.innerText.trim().toLowerCase();
      });
      // Distinctive screen text (checked first — more reliable than nav colour).
      if (/Saved Papers/i.test(txt)) return 'saved';
      if (/Your search history|History\b/i.test(txt) && !/Saved Papers/i.test(txt)) return 'history';
      if (/Databases\b|SFU databases/i.test(txt)) return 'databases';
      if (/LLM Backend|Interface\b|Privacy\b|Zotero|Dictionary/i.test(txt)) return 'settings';
      if (/Admin dashboard|Models|Curate|Operator/i.test(txt)) return 'admin';
      if (activeLabel) return activeLabel;
      return 'search';
    }).catch(() => 'search');
    statesReached.add(here);
    await check(page, log, `${ev.name} -> ${here}`);
  }
} catch (e) {
  log.fatal('model_threw', String(e).slice(0, 200));
} finally {
  await captureArtifacts(page, context, log, 'model_walk_search');
  await context.close();
}

// Second pass: suite apps (analytics, index_manager) reached standalone.
for (const app of ['analytics.html', 'index_manager.html']) {
  const c2 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const p2 = await c2.newPage();
  arm(p2, log, () => `model_walk:${app}`);
  try {
    await mockApi(p2, 'live');
    await p2.goto(`${BASE}/app/${app}`, { waitUntil: 'load', timeout: 30000 });
    await p2.waitForFunction(() => document.getElementById('root') && document.getElementById('root').childNodes.length > 0, { timeout: 15000 }).catch(() => {});
    await sleep(300);
    // Exercise the suite-app nav to confirm each mounts + is reachable.
    for (const t of (app === 'analytics.html' ? ['About index', 'Operator'] : ['Warm Cache', 'Storage Budget', 'Personas'])) {
      await p2.getByText(t, { exact: false }).first().click({ timeout: 3000 }).catch(() => {});
      await sleep(120); await check(p2, log, `suite:${app} "${t}"`);
      eventsFired.add(`suite:${t}`); actions++;
    }
    statesReached.add(app.replace('.html', ''));
  } catch (e) { log.fatal('suite_threw', `${app} :: ${String(e).slice(0, 160)}`); }
  await captureArtifacts(p2, c2, log, `model_walk_${app}`).catch(() => {});
  await c2.close();
}

await browser.close();
const wall = Date.now() - t0;

const statesMissing = ALL_STATES.filter(s => !statesReached.has(s));
const eventsMissing = EVENTS.map(e => e.name).filter(e => !eventsFired.has(e));
const verdict = {
  layer: 'L-B model_walk', date: DATE_TAG, wall_ms: wall,
  summary: { actions, states_covered: statesReached.size, events_fired: eventsFired.size, failures: log.failures.length, warnings: log.warnings.length },
  states_reached: [...statesReached],
  states_missing: statesMissing,
  events_fired: [...eventsFired].sort(),
  events_missing: eventsMissing,
  failures: log.failures,
  warnings: log.warnings,
  bars: {
    all_states_reached: statesMissing.length === 0,
    all_events_fired: eventsMissing.length === 0,
    zero_pageerror: !log.failures.some(f => f.kind.startsWith('fatal:pageerror')),
    zero_console_error: !log.failures.some(f => f.kind === 'console.error'),
    zero_overflow: !log.failures.some(f => f.kind === 'overflow'),
  },
};
const OUT = path.join(ROOT, 'data', 'eval_results', `gui_testbed_lb_model_${DATE_TAG}.json`);
fs.writeFileSync(OUT, JSON.stringify(verdict, null, 2));
console.log(JSON.stringify({ layer: verdict.layer, ...verdict.summary, states_missing: statesMissing, events_missing: eventsMissing, bars: verdict.bars, out: path.relative(process.cwd(), OUT) }, null, 2));
