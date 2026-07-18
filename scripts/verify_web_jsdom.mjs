// Verify the SFU Library Suite GUI mounts with zero runtime errors (offline +
// online), mirroring the 2026-06-19 verification method recorded in
// docs/THIN_CLIENT_SWAP.md §Web GUI. Plain jsdom (no browser): load vendor
// React + the shared lib + each compiled app into a DOM and capture any
// console.error / thrown exception during mount + a simulated search.
//
// Run:  node scripts/verify_web_jsdom.mjs
import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(ROOT, 'web');
const read = (p) => readFileSync(path.join(WEB, p), 'utf8');

const results = [];
function record(ctx, ok, detail) { results.push({ ctx, ok, detail }); }

// Build a fresh DOM that mirrors the HTML head (tokens + base.css + vendor +
// lib scripts) and returns a harness. `online` swaps the fetch mock: online
// returns {status:"ok",tools:N} for /health and a non-empty /api/search so the
// demo banner stays absent; offline rejects so mock fallback + banner fire.
function makeDom({ online }) {
  const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="root"></div></body></html>`, {
    url: 'http://localhost/app/search.html',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  // jsdom lacks requestAnimationFrame (React 18 createRoot uses it for flush).
  window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  window.cancelAnimationFrame = (id) => clearTimeout(id);
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));

  // fetch mock: online vs offline.
  const HEALTH_LIVE = { status: 'ok', tools: 12 };
  const SEARCH_LIVE = { results: [{ id: 'L1', title: 'Live result one', authors: ['A. One'], year: 2024, source: 'Nature', volume: '1', issue: '1', doi: '10.0/x', cited_by: 5, type: 'article', abstract: 'abs', tldr: 'tldr' }], notes: [], meta: { count: 1 } };
  window.fetch = (url, opts) => {
    const u = String(url);
    if (!online) return Promise.reject(new Error('offline: network down'));
    if (u.includes('/health')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(HEALTH_LIVE) });
    if (u.includes('/api/search')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(SEARCH_LIVE) });
    if (u.includes('/api/index_status')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ metrics: {} }) });
    if (u.includes('/analytics')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ panels: {} }) });
    return Promise.resolve({ ok: false, status: 404, headers: { get: () => null }, json: () => Promise.resolve({}) });
  };

  window.resizeTo = () => {};

  const errors = [];
  const origErr = window.console.error.bind(window.console);
  window.console.error = (...a) => { errors.push(a.map(String).join(' ')); origErr(...a); };
  window.addEventListener('error', (e) => { errors.push('windowerror: ' + (e.error ? e.error.stack : e.message)); });

  // Inject the search.html <style> tokens + base.css (static text; no eval).
  const styleEl = window.document.createElement('style');
  styleEl.textContent = read('search.html').match(/<style>([\s\S]*?)<\/style>/)[1]
    + '\n' + read('lib/base.css');
  window.document.head.appendChild(styleEl);

  // Evaluate vendor + lib + app scripts in the window context (the HTML loads
  // them as plain <script src=...>; jsdom outside-only needs manual eval).
  const evalIn = (src, label) => {
    try { window.eval(src); }
    catch (e) { errors.push(`EVAL ${label}: ${e.message}`); throw e; }
  };
  evalIn(read('vendor/react.production.min.js'), 'react');
  evalIn(read('vendor/react-dom.production.min.js'), 'react-dom');
  evalIn(read('lib/mock.js'), 'mock.js');
  evalIn(read('lib/api.js'), 'api.js');
  evalIn(read('lib/ui.js'), 'ui.js');
  evalIn(read('lib/interface_prefs.js'), 'interface_prefs.js');

  return { dom, window, errors, evalIn };
}

async function mountApp(html, { online }) {
  const { window, errors, evalIn } = makeDom({ online });
  evalIn(read('search.js'), 'search.js');
  // Let React mount + the mount-time /health probe settle.
  await new Promise((r) => setTimeout(r, 50));
  return { window, errors };
}

function assertNoErrors(ctx, errs) {
  const clean = errs.filter((e) => !/Failed to load resource|Could not load|favicon/i.test(e));
  record(ctx, clean.length === 0, clean.length ? clean.slice(0, 3).join(' || ') : '0 runtime errors');
  return clean;
}

// 1) Offline mount (backend down → mock fallback + demo banner).
try {
  const { window, errors } = await mountApp('search.html', { online: false });
  await new Promise((r) => setTimeout(r, 60));
  const banner = window.document.getElementById('sfu-demo-pill');
  record('search mount OFFLINE — banner present', !!banner, banner ? 'demo pill rendered' : 'NO banner (unexpected offline)');
  assertNoErrors('search mount OFFLINE — console errors', errors);
} catch (e) { record('search mount OFFLINE — threw', false, String(e)); }

// 2) Online mount (backend up → no banner).
try {
  const { window, errors } = await mountApp('search.html', { online: true });
  await new Promise((r) => setTimeout(r, 60));
  const banner = window.document.getElementById('sfu-demo-pill');
  record('search mount ONLINE — banner absent', !banner, banner ? 'banner unexpectedly present' : 'no demo pill online ✓');
  assertNoErrors('search mount ONLINE — console errors', errors);

  // 3) Simulated search online: type a query + Enter → results render.
  const inp = window.document.querySelector('input');
  if (inp) {
    // React controlled inputs ignore `inp.value = ...` because it sets the
    // property past React's tracker; use the native setter so React's onChange
    // fires with the new value, then dispatch Enter to submit.
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(inp, 'machine learning drug discovery');
    inp.dispatchEvent(new window.Event('input', { bubbles: true }));
    inp.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await new Promise((r) => setTimeout(r, 90));
    const cards = window.document.querySelectorAll('h3');
    record('search ONLINE — simulated search → result cards', cards.length > 0, `${cards.length} h3 titles rendered`);
    assertNoErrors('search ONLINE — simulated search errors', errors);
  } else {
    record('search ONLINE — simulated search → result cards', false, 'no input found to type into');
  }
} catch (e) { record('search mount ONLINE — threw', false, String(e)); }

// 4) §1 skeleton-gate: 429 Retry-After countdown + degraded flag plumbing via
//    the api.js layer directly (no DOM needed — proves the real-signal wiring).
try {
  const { window, errors } = makeDom({ online: true });
  window.eval(read('lib/mock.js')); void 0;
  window.eval(read('lib/api.js'));
  // Override fetch to return a 429 with Retry-After: 3.
  window.fetch = () => Promise.resolve({ ok: false, status: 429, headers: { get: (h) => h === 'Retry-After' ? '3' : null }, json: () => Promise.resolve({}) });
  const res = await window.SFUApi.search('q', {});
  record('api 429 → {source:"retry",retryAfter:3}', res.source === 'retry' && res.retryAfter === 3, JSON.stringify({ source: res.source, retryAfter: res.retryAfter }));

  // 5) degraded flag passes through from a live response.
  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ results: [], notes: [], degraded: true, degraded_shards: 2 }) });
  const res2 = await window.SFUApi.search('q', {});
  record('api degraded flag passes through', res2.degraded === true && res2.degradedShards === 2, JSON.stringify({ degraded: res2.degraded, degradedShards: res2.degradedShards }));

  // 6) health warm flag: present → honored; absent → defaults true (forward-only).
  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'ok', tools: 12, warm: false }) });
  const h1 = await window.SFUApi.health();
  record('health warm=false honored', h1.warm === false, 'warm=' + h1.warm);
  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'ok', tools: 12 }) });
  const h2 = await window.SFUApi.health();
  record('health absent-warm defaults true (forward-only)', h2.warm === true, 'warm=' + h2.warm);
  assertNoErrors('api-layer checks — console errors', errors);
} catch (e) { record('api-layer checks — threw', false, String(e)); }

// 7) §2 interface prefs persistence: write then read across a fresh DOM
//    (simulated reload — shares the localStorage store between two windows).
try {
  const { window: w1, errors } = makeDom({ online: true });
  const P1 = w1.SFUUI;
  P1.writeInterfacePrefs({ advancedFiltersOpen: true, savedHistoryNav: true, databasesTab: false, analyticsApp: false, indexManagerApp: true, adminPanels: false, density: 'compact' });

  // Fresh DOM = a "reload". Share the first window's localStorage store with it
  // (localStorage is a getter-only prop on Window, so shadow it on the instance).
  const dom2 = new JSDOM('<!DOCTYPE html><html><body></body></html>', { url: 'http://localhost/app/search.html', runScripts: 'outside-only', pretendToBeVisual: true });
  dom2.window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  Object.defineProperty(dom2.window, 'localStorage', { value: w1.localStorage, configurable: true });
  dom2.window.eval(read('lib/mock.js'));
  dom2.window.eval(read('lib/api.js'));
  dom2.window.eval(read('lib/ui.js'));
  dom2.window.eval(read('lib/interface_prefs.js'));
  const reread = dom2.window.SFUUI.readInterfacePrefs();
  record('interface prefs persist across reload', reread.advancedFiltersOpen === true && reread.savedHistoryNav === true && reread.indexManagerApp === true && reread.density === 'compact' && reread.databasesTab === false, JSON.stringify(reread));
  // Integrity floor: PREF_DEFAULTS has NO banner/degraded/pill keys (the
  // reliability signals are deliberately un-toggleable).
  const keys = Object.keys(P1.INTERFACE_PREF_DEFAULTS);
  const floorClean = !keys.includes('demoBanner') && !keys.includes('degradedNotice') && !keys.includes('backendPill');
  record('integrity floor: banner/degraded/pill NOT toggleable', floorClean, 'toggle keys=' + keys.join(','));
  assertNoErrors('interface prefs — console errors', errors);
} catch (e) { record('interface prefs — threw', false, String(e).slice(0, 200)); }

// 8) WI-18 searchbar speculation controller (term 6): debounced, min-length
//    gated, cancel-on-submit. Tested headlessly with an injected fake clock +
//    fake timers so the debounce is deterministic (no wall-clock waiting).
try {
  const { window, errors } = makeDom({ online: true });
  // The controller talks to SFUApi.speculate; stub it to record calls instead
  // of hitting fetch.
  const fired = [];
  window.SFUApi.speculate = (q, f) => { fired.push(q); return Promise.resolve({ data: { status: 'fired' } }); };
  // A fake timer + clock so the debounce (400 ms default) is testable without
  // waiting wall-clock time.
  const queue = [];
  let clock = 1000;
  const fakeSetTimeout = (fn, ms) => { const id = { fn, at: clock + (ms || 0) }; queue.push(id); return id; };
  const fakeClearTimeout = (id) => { const i = queue.indexOf(id); if (i >= 0) queue.splice(i, 1); };
  const advance = (ms) => { clock += ms; for (const id of queue.filter(x => x.at <= clock)) { const i = queue.indexOf(id); if (i >= 0) queue.splice(i, 1); id.fn(); } };
  const ctrl = window.SFUApi.createSpeculationController(window.SFUApi.speculate, {}, { setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout, now: () => clock });

  // short input → no schedule
  ctrl.onType('cris');
  record('spec ctrl: short input (< minLen=8) not scheduled', !ctrl._pending && fired.length === 0, 'pending=' + ctrl._pending);
  // long input → schedules, NOT fires immediately (debounce)
  ctrl.onType('machine learning for drug discovery');
  record('spec ctrl: long input schedules (debounced), no immediate fire', ctrl._pending && fired.length === 0, 'pending=' + ctrl._pending + ' fired=' + fired.length);
  // advance < debounce → still pending, not fired
  advance(399);
  record('spec ctrl: < debounceMs idle → NOT fired', ctrl._pending && fired.length === 0, 'fired=' + fired.length);
  // advance to debounce → fires exactly once
  advance(1);
  record('spec ctrl: ≥ debounceMs idle → fires speculate once', fired.length === 1, 'fired=' + fired.length + ' q=' + fired[0]);
  // new keystroke cancels the OLD pending timer (and schedules a fresh one):
  // capture the old timer id, type again, assert the old id was cleared.
  ctrl.onType('machine learning for drug discovery overview');
  const oldTimer = queue[queue.length - 1];
  ctrl.onType('machine learning for drug discovery overview part two');
  // The old timer must no longer be in the queue (cancelled by the new keystroke);
  // a fresh one is now pending (debounce restarted).
  const oldStillPending = queue.includes(oldTimer);
  record('spec ctrl: new keystroke cancels OLD pending timer', !oldStillPending && ctrl._pending, 'oldStillPending=' + oldStillPending + ' pending=' + ctrl._pending);
  // submit cancels pending
  ctrl.cancel();
  record('spec ctrl: cancel() clears pending timer', !ctrl._pending, 'pending=' + ctrl._pending);
  assertNoErrors('speculation controller — console errors', errors);
} catch (e) { record('speculation controller — threw', false, String(e).slice(0, 300)); }

// 9) WI-18 speculate endpoint wiring: SFUApi.speculate POSTs /api/speculate
//    with the search args shape (same as /api/search), default-OFF server is a
//    harmless no-op (returns suppressed).
try {
  const { window, errors } = makeDom({ online: true });
  let captured = null;
  window.fetch = (url, opts) => {
    captured = { url: String(url), method: opts && opts.method, body: opts && JSON.parse(opts.body) };
    return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'suppressed', reason: 'cache-off' }) });
  };
  const r = await window.SFUApi.speculate('machine learning for drug', {});
  record('speculate() POSTs /api/speculate with search-args body',
    captured && captured.url.includes('/api/speculate') && captured.method === 'POST' && captured.body.query === 'machine learning for drug' && captured.body.limit === 50,
    captured ? JSON.stringify(captured) : 'no fetch');
  record('speculate() returns the server status (default-OFF → suppressed)', r.source === 'live' && r.data.status === 'suppressed', JSON.stringify(r.data));
  assertNoErrors('speculate endpoint wiring — console errors', errors);
} catch (e) { record('speculate endpoint wiring — threw', false, String(e).slice(0, 300)); }

// Report
console.log('\n================ jsdom GUI verification ================');
let pass = 0, fail = 0;
for (const r of results) {
  const tag = r.ok ? 'PASS' : 'FAIL';
  if (r.ok) pass++; else fail++;
  console.log(`  [${tag}] ${r.ctx.padEnd(52)} ${r.detail}`);
}
console.log(`\n${pass} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
