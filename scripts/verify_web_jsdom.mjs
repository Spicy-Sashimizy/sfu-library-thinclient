import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(ROOT, 'web');
const read = (p) => readFileSync(path.join(WEB, p), 'utf8');

const results = [];
function record(ctx, ok, detail) { results.push({ ctx, ok, detail }); }

function makeDom({ online, searchResponder, io }) {
  const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="root"></div></body></html>`, {
    url: 'http://localhost/app/search.html',
    runScripts: 'outside-only',
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  window.cancelAnimationFrame = (id) => clearTimeout(id);
  window.matchMedia = window.matchMedia || (() => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }));

  const HEALTH_LIVE = { status: 'ok', tools: 12 };
  const SEARCH_LIVE = { results: [{ id: 'L1', title: 'Live result one', authors: ['A. One'], year: 2024, source: 'Nature', volume: '1', issue: '1', doi: '10.0/x', cited_by: 5, type: 'article', abstract: 'abs', tldr: 'tldr' }], notes: [], meta: { count: 1 } };
  const ioInstances = [];
  if (io) {
    window.IntersectionObserver = function (cb, options) {
      this.cb = cb; this.options = options; this.targets = []; this.disconnected = false;
      this.observe = (t) => { this.targets.push(t); };
      this.unobserve = (t) => { this.targets = this.targets.filter((x) => x !== t); };
      this.disconnect = () => { this.targets = []; this.disconnected = true; };
      this.trigger = () => this.cb(this.targets.map((t) => ({ target: t, isIntersecting: true })), this);
      ioInstances.push(this);
    };
  }

  const searchBodies = [];
  const fetchCalls = [];
  const engagementPosts = [];
  window.fetch = (url, opts) => {
    const u = String(url);
    fetchCalls.push(u);
    if (!online) return Promise.reject(new Error('offline: network down'));
    if (u.endsWith('/engagement')) {
      engagementPosts.push({ url: u, opts, body: JSON.parse(opts.body) });
      return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ recorded: 1 }) });
    }
    if (u.includes('/health')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(HEALTH_LIVE) });
    if (u.includes('/api/search')) {
      const body = opts && opts.body ? JSON.parse(opts.body) : {};
      searchBodies.push(body);
      const data = searchResponder ? searchResponder(body) : SEARCH_LIVE;
      return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(data) });
    }
    if (u.includes('/analytics')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ panels: {} }) });
    return Promise.resolve({ ok: false, status: 404, headers: { get: () => null }, json: () => Promise.resolve({}) });
  };

  window.resizeTo = () => {};

  const errors = [];
  const origErr = window.console.error.bind(window.console);
  window.console.error = (...a) => { errors.push(a.map(String).join(' ')); origErr(...a); };
  window.addEventListener('error', (e) => { errors.push('windowerror: ' + (e.error ? e.error.stack : e.message)); });

  const styleEl = window.document.createElement('style');
  styleEl.textContent = read('search.html').match(/<style>([\s\S]*?)<\/style>/)[1]
    + '\n' + read('lib/base.css');
  window.document.head.appendChild(styleEl);

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

  return { dom, window, errors, evalIn, ioInstances, searchBodies, fetchCalls, engagementPosts };
}

async function mountApp(html, opts) {
  const harness = makeDom(opts);
  harness.evalIn(read('search.js'), 'search.js');
  await new Promise((r) => setTimeout(r, 50));
  return harness;
}

function submitQuery(window, q) {
  const inp = window.document.querySelector('input');
  if (!inp) return false;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, q);
  inp.dispatchEvent(new window.Event('input', { bubbles: true }));
  inp.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  return true;
}

function assertNoErrors(ctx, errs) {
  const clean = errs.filter((e) => !/Failed to load resource|Could not load|favicon/i.test(e));
  record(ctx, clean.length === 0, clean.length ? clean.slice(0, 3).join(' || ') : '0 runtime errors');
  return clean;
}

try {
  const { window, errors } = await mountApp('search.html', { online: false });
  await new Promise((r) => setTimeout(r, 60));
  const banner = window.document.getElementById('sfu-demo-pill');
  record('search mount OFFLINE — banner present', !!banner, banner ? 'demo pill rendered' : 'NO banner (unexpected offline)');
  assertNoErrors('search mount OFFLINE — console errors', errors);
} catch (e) { record('search mount OFFLINE — threw', false, String(e)); }

try {
  const { window, errors } = await mountApp('search.html', { online: true });
  await new Promise((r) => setTimeout(r, 60));
  const banner = window.document.getElementById('sfu-demo-pill');
  record('search mount ONLINE — banner absent', !banner, banner ? 'banner unexpectedly present' : 'no demo pill online ✓');
  assertNoErrors('search mount ONLINE — console errors', errors);

  const inp = window.document.querySelector('input');
  if (inp) {
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

try {
  const { window, errors } = makeDom({ online: true });
  window.eval(read('lib/mock.js')); void 0;
  window.eval(read('lib/api.js'));
  window.fetch = () => Promise.resolve({ ok: false, status: 429, headers: { get: (h) => h === 'Retry-After' ? '3' : null }, json: () => Promise.resolve({}) });
  const res = await window.SFUApi.search('q', {});
  record('api 429 → {source:"retry",retryAfter:3}', res.source === 'retry' && res.retryAfter === 3, JSON.stringify({ source: res.source, retryAfter: res.retryAfter }));

  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ results: [], notes: [], degraded: true, degraded_shards: 2 }) });
  const res2 = await window.SFUApi.search('q', {});
  record('api degraded flag passes through', res2.degraded === true && res2.degradedShards === 2, JSON.stringify({ degraded: res2.degraded, degradedShards: res2.degradedShards }));

  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'ok', tools: 12, warm: false }) });
  const h1 = await window.SFUApi.health();
  record('health warm=false honored', h1.warm === false, 'warm=' + h1.warm);
  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'ok', tools: 12 }) });
  const h2 = await window.SFUApi.health();
  record('health absent-warm defaults true (forward-only)', h2.warm === true, 'warm=' + h2.warm);
  assertNoErrors('api-layer checks — console errors', errors);
} catch (e) { record('api-layer checks — threw', false, String(e)); }

try {
  const { window: w1, errors } = makeDom({ online: true });
  const P1 = w1.SFUUI;
  P1.writeInterfacePrefs({ advancedFiltersOpen: true, savedHistoryNav: true, databasesTab: false, analyticsApp: false, indexManagerApp: true, adminPanels: false, density: 'compact' });

  const dom2 = new JSDOM('<!DOCTYPE html><html><body></body></html>', { url: 'http://localhost/app/search.html', runScripts: 'outside-only', pretendToBeVisual: true });
  dom2.window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  Object.defineProperty(dom2.window, 'localStorage', { value: w1.localStorage, configurable: true });
  dom2.window.eval(read('lib/mock.js'));
  dom2.window.eval(read('lib/api.js'));
  dom2.window.eval(read('lib/ui.js'));
  dom2.window.eval(read('lib/interface_prefs.js'));
  const reread = dom2.window.SFUUI.readInterfacePrefs();
  record('interface prefs persist across reload', reread.advancedFiltersOpen === true && reread.savedHistoryNav === true && reread.indexManagerApp === true && reread.density === 'compact' && reread.databasesTab === false, JSON.stringify(reread));
  const keys = Object.keys(P1.INTERFACE_PREF_DEFAULTS);
  const floorClean = !keys.includes('demoBanner') && !keys.includes('degradedNotice') && !keys.includes('backendPill');
  record('integrity floor: banner/degraded/pill NOT toggleable', floorClean, 'toggle keys=' + keys.join(','));
  assertNoErrors('interface prefs — console errors', errors);
} catch (e) { record('interface prefs — threw', false, String(e).slice(0, 200)); }

try {
  const { window, errors } = makeDom({ online: true });
  const fired = [];
  window.SFUApi.speculate = (q, f) => { fired.push(q); return Promise.resolve({ data: { status: 'fired' } }); };
  const queue = [];
  let clock = 1000;
  const fakeSetTimeout = (fn, ms) => { const id = { fn, at: clock + (ms || 0) }; queue.push(id); return id; };
  const fakeClearTimeout = (id) => { const i = queue.indexOf(id); if (i >= 0) queue.splice(i, 1); };
  const advance = (ms) => { clock += ms; for (const id of queue.filter(x => x.at <= clock)) { const i = queue.indexOf(id); if (i >= 0) queue.splice(i, 1); id.fn(); } };
  const ctrl = window.SFUApi.createSpeculationController(window.SFUApi.speculate, {}, { setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout, now: () => clock });

  ctrl.onType('cris');
  record('spec ctrl: short input (< minLen=8) not scheduled', !ctrl._pending && fired.length === 0, 'pending=' + ctrl._pending);
  ctrl.onType('machine learning for drug discovery');
  record('spec ctrl: long input schedules (debounced), no immediate fire', ctrl._pending && fired.length === 0, 'pending=' + ctrl._pending + ' fired=' + fired.length);
  advance(399);
  record('spec ctrl: < debounceMs idle → NOT fired', ctrl._pending && fired.length === 0, 'fired=' + fired.length);
  advance(1);
  record('spec ctrl: ≥ debounceMs idle → fires speculate once', fired.length === 1, 'fired=' + fired.length + ' q=' + fired[0]);
  ctrl.onType('machine learning for drug discovery overview');
  const oldTimer = queue[queue.length - 1];
  ctrl.onType('machine learning for drug discovery overview part two');
  const oldStillPending = queue.includes(oldTimer);
  record('spec ctrl: new keystroke cancels OLD pending timer', !oldStillPending && ctrl._pending, 'oldStillPending=' + oldStillPending + ' pending=' + ctrl._pending);
  ctrl.cancel();
  record('spec ctrl: cancel() clears pending timer', !ctrl._pending, 'pending=' + ctrl._pending);
  assertNoErrors('speculation controller — console errors', errors);
} catch (e) { record('speculation controller — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors } = makeDom({ online: true });
  let captured = null;
  window.fetch = (url, opts) => {
    captured = { url: String(url), method: opts && opts.method, body: opts && JSON.parse(opts.body) };
    return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'suppressed', reason: 'cache-off' }) });
  };
  const r = await window.SFUApi.speculate('machine learning for drug', {});
  record('speculate() POSTs /api/speculate with search-args body',
    captured && captured.url.includes('/api/speculate') && captured.method === 'POST' && captured.body.query === 'machine learning for drug' && captured.body.limit === window.SFUApi.PAGE_SIZE,
    captured ? JSON.stringify(captured) : 'no fetch');
  record('speculate() returns the server status (default-OFF → suppressed)', r.source === 'live' && r.data.status === 'suppressed', JSON.stringify(r.data));
  assertNoErrors('speculate endpoint wiring — console errors', errors);
} catch (e) { record('speculate endpoint wiring — threw', false, String(e).slice(0, 300)); }

const PAGED_CORPUS = 25;
const pagedResponder = (body) => {
  const n = Math.max(0, Math.min(body.limit || 10, PAGED_CORPUS));
  const results = [];
  for (let i = 1; i <= n; i++) {
    results.push({ id: 'P' + i, title: 'Paged result ' + i, authors: ['A. Author'], year: 2024, source: 'Journal', volume: '1', issue: '1', doi: '10.0/p' + i, cited_by: i, type: 'article', abstract: 'abs ' + i, tldr: 'tldr ' + i });
  }
  return { results, notes: [], meta: { count: PAGED_CORPUS } };
};

try {
  const { window, errors, searchBodies } = makeDom({ online: true, searchResponder: pagedResponder });
  const p1 = await window.SFUApi.search('q', {}, 1);
  record('paging: page 1 requests limit=PAGE_SIZE',
    searchBodies[0].limit === window.SFUApi.PAGE_SIZE && p1.page === 1 && p1.pageSize === window.SFUApi.PAGE_SIZE,
    JSON.stringify({ limit: searchBodies[0].limit, page: p1.page, n: p1.results.length }));
  record('paging: full page → hasMore true', p1.hasMore === true && p1.results.length === 10, 'hasMore=' + p1.hasMore + ' n=' + p1.results.length);

  const p2 = await window.SFUApi.search('q', {}, 2);
  record('paging: page N requests cumulative N×PAGE_SIZE (federated ignores page)',
    searchBodies[1].limit === 2 * window.SFUApi.PAGE_SIZE && searchBodies[1].page === undefined && p2.results.length === 20,
    JSON.stringify(searchBodies[1]));

  const p3 = await window.SFUApi.search('q', {}, 3);
  record('paging: short page (corpus exhausted) → hasMore false',
    p3.results.length === PAGED_CORPUS && p3.hasMore === false, 'n=' + p3.results.length + ' hasMore=' + p3.hasMore);

  const pOver = await window.SFUApi.search('q', {}, 99);
  record('paging: page clamped to MAX_PAGES (limit ≤ server cap 50)',
    pOver.page === window.SFUApi.MAX_PAGES && searchBodies[3].limit === window.SFUApi.MAX_RESULTS && window.SFUApi.MAX_RESULTS === 50 && pOver.hasMore === false,
    JSON.stringify({ page: pOver.page, limit: searchBodies[3].limit, hasMore: pOver.hasMore }));

  const merged = window.SFUApi.mergePages(
    [{ id: 'a' }, { id: 'b' }],
    [{ id: 'a' }, { id: 'c' }, { id: 'b' }, { id: 'd' }]);
  record('paging: mergePages dedupes by id, keeps first-seen order',
    merged.map((r) => r.id).join(',') === 'a,b,c,d', merged.map((r) => r.id).join(','));
  assertNoErrors('paging api-layer — console errors', errors);
} catch (e) { record('paging api-layer — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors, ioInstances, searchBodies } = await mountApp('search.html', { online: true, searchResponder: pagedResponder, io: true });
  submitQuery(window, 'paged query');
  await new Promise((r) => setTimeout(r, 120));
  const cards = () => window.document.querySelectorAll('h3').length;
  record('scroll: first page renders PAGE_SIZE cards', cards() === 10, cards() + ' cards');

  const sentinel = window.document.querySelector('[data-testid="sfu-scroll-sentinel"]');
  const live = ioInstances.filter((o) => !o.disconnected && o.targets.length);
  record('scroll: IntersectionObserver observes the list sentinel',
    !!sentinel && live.length === 1 && live[0].targets[0] === sentinel,
    'sentinel=' + !!sentinel + ' observers=' + live.length);

  const before = searchBodies.length;
  live[live.length - 1].trigger();
  await new Promise((r) => setTimeout(r, 120));
  record('scroll: sentinel intersect → fetches next page (cumulative limit)',
    searchBodies.length === before + 1 && searchBodies[before].limit === 20,
    JSON.stringify(searchBodies[before] || null));
  record('scroll: page 2 appended without duplicates', cards() === 20, cards() + ' cards');

  const live2 = ioInstances.filter((o) => !o.disconnected && o.targets.length);
  live2[live2.length - 1].trigger();
  await new Promise((r) => setTimeout(r, 120));
  record('scroll: page 3 appends the tail of the corpus', cards() === PAGED_CORPUS, cards() + ' cards');

  const after = searchBodies.length;
  const idle = ioInstances.filter((o) => !o.disconnected && o.targets.length);
  record('scroll: exhausted corpus → observer torn down, no further fetch',
    idle.length === 0 && searchBodies.length === after,
    'liveObservers=' + idle.length + ' fetches=' + searchBodies.length);
  const tail = window.document.querySelector('[data-testid="sfu-scroll-sentinel"]');
  record('scroll: end-of-results notice replaces the load-more affordance',
    !!tail && /End of results/.test(tail.textContent) && !window.document.querySelector('[data-testid="sfu-load-more"]'),
    tail ? tail.textContent.slice(0, 60) : 'no sentinel');
  assertNoErrors('infinite scroll — console errors', errors);
} catch (e) { record('infinite scroll — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors, searchBodies } = await mountApp('search.html', { online: true, searchResponder: pagedResponder });
  submitQuery(window, 'paged query');
  await new Promise((r) => setTimeout(r, 120));
  const btn = window.document.querySelector('[data-testid="sfu-load-more"]');
  record('scroll fallback: no IntersectionObserver → Load more button rendered', !!btn, btn ? btn.textContent : 'missing');
  if (btn) {
    const before = searchBodies.length;
    btn.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    await new Promise((r) => setTimeout(r, 120));
    record('scroll fallback: Load more click appends the next page',
      window.document.querySelectorAll('h3').length === 20 && searchBodies.length === before + 1,
      window.document.querySelectorAll('h3').length + ' cards');
  } else {
    record('scroll fallback: Load more click appends the next page', false, 'no button to click');
  }
  assertNoErrors('scroll fallback — console errors', errors);
} catch (e) { record('scroll fallback — threw', false, String(e).slice(0, 300)); }

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const mkRes = (id) => ({ id, openalex_id: id, title: 'T ' + id, authors: ['A'], year: 2024, source: 'J', doi: '10.0/' + id, abstract: 'a', type: 'article' });
const sseBody = (chunks) => {
  let i = 0;
  return { getReader: () => ({
    read: () => new Promise((resolve) => {
      if (i >= chunks.length) return resolve({ done: true, value: undefined });
      const c = chunks[i++];
      setTimeout(() => resolve({ done: false, value: c.text }), c.delay || 0);
    }),
    cancel() {},
  }) };
};
const sseEvent = (ev, obj) => `event: ${ev}\ndata: ${JSON.stringify(obj)}\n\n`;

try {
  const { window, errors } = makeDom({ online: true });
  const queue = [];
  let clock = 10000;
  const fakeSetTimeout = (fn, ms) => { const id = { fn, at: clock + (ms || 0) }; queue.push(id); return id; };
  const fakeClearTimeout = (id) => { const i = queue.indexOf(id); if (i >= 0) queue.splice(i, 1); };
  const advance = (ms) => { const end = clock + ms; for (;;) { const due = queue.filter((x) => x.at <= end).sort((a, b) => a.at - b.at)[0]; if (!due) break; clock = Math.max(clock, due.at); queue.splice(queue.indexOf(due), 1); due.fn(); } clock = end; };
  let selecting = false;
  const applied = [];
  const mk = () => window.SFUApi.createDraftSwapController({ idleMs: 1200, setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout, now: () => clock, isSelecting: () => selecting, apply: (list, info) => applied.push({ ids: list.map((r) => r.id).join(','), state: info.state, pinned: info.pinned }) });
  const L = (ids) => ids.split(',').map((id) => ({ id }));
  const before = window.SFUApi.draftStreamStats();

  let c = mk();
  c.showDraft(L('a,b,c,d'));
  record('draft swap: showDraft paints the draft as preliminary', applied.length === 1 && applied[0].state === 'draft' && applied[0].ids === 'a,b,c,d', JSON.stringify(applied[0]));
  c.noteActivity();
  c.offerFinal(L('b,e,a,f'));
  record('draft swap: final while user active → NOT swapped', applied.length === 1 && c.state === 'draft', 'state=' + c.state);
  advance(600); c.noteActivity(); advance(1100);
  record('draft swap: continued activity keeps deferring the swap', applied.length === 1 && c.state === 'draft', 'state=' + c.state + ' applied=' + applied.length);
  advance(100);
  record('draft swap: ≥ idleMs quiet → swaps to the exact final order', applied.length === 2 && applied[1].state === 'final' && applied[1].ids === 'b,e,a,f', JSON.stringify(applied[1]));
  record('draft swap: reshuffle = |draft top10 \\ final top10| / |draft top10|', c.reshuffle === 0.5, 'reshuffle=' + c.reshuffle);

  applied.length = 0;
  c = mk();
  c.showDraft(L('a,b,c,d'));
  c.setHovered('c');
  c.offerFinal(L('c,a,d,b'));
  advance(1200);
  record('draft swap: hovered card pinned at its on-screen index', applied.length === 2 && applied[1].state === 'pinned' && applied[1].ids === 'a,d,c,b' && applied[1].pinned === 'c', JSON.stringify(applied[1]));
  c.setHovered(null);
  advance(1199);
  record('draft swap: pinned order held until the next quiet window', applied.length === 2, 'applied=' + applied.length);
  advance(1);
  record('draft swap: after hover leaves + idle → exact final order', applied.length === 3 && applied[2].state === 'final' && applied[2].ids === 'c,a,d,b', JSON.stringify(applied[2]));

  applied.length = 0;
  c = mk();
  c.showDraft(L('a,b,x'));
  c.setHovered('x');
  c.offerFinal(L('a,b,c'));
  advance(5000);
  record('draft swap: hovered card absent from final → swap waits (never yanked from under cursor)', applied.length === 1 && c.state === 'draft', 'state=' + c.state);
  c.setHovered(null);
  advance(1200);
  record('draft swap: …then swaps once the hover leaves and the user is idle', applied.length === 2 && applied[1].ids === 'a,b,c', JSON.stringify(applied[1] || null));

  applied.length = 0;
  c = mk();
  c.showDraft(L('a,b'));
  selecting = true;
  c.offerFinal(L('b,a'));
  advance(4000);
  record('draft swap: active text selection blocks the swap', applied.length === 1 && c.state === 'draft', 'state=' + c.state);
  selecting = false;
  advance(1200);
  record('draft swap: selection cleared → swap', applied.length === 2 && applied[1].ids === 'b,a', JSON.stringify(applied[1] || null));

  applied.length = 0;
  c = mk();
  c.offerFinal(L('z,y'));
  record('draft swap: final with no draft (cache hit) paints immediately', applied.length === 1 && applied[0].state === 'final' && applied[0].ids === 'z,y', JSON.stringify(applied[0] || null));

  const after = window.SFUApi.draftStreamStats();
  record('draft swap: client counter records reshuffle + swaps', after.reshuffleN - before.reshuffleN === 4 && after.swaps - before.swaps === 4 && after.pinnedSwaps - before.pinnedSwaps === 1 && after.reshuffleMean != null, JSON.stringify({ n: after.reshuffleN, swaps: after.swaps, pinned: after.pinnedSwaps, mean: after.reshuffleMean }));
  record('reshuffleRate: top-10 only, empty draft → 0', window.SFUApi.reshuffleRate([], L('a')) === 0 && window.SFUApi.reshuffleRate(L('a,b,c,d,e,f,g,h,i,j,k'), L('a,b,c,d,e,f,g,h,i,k')) === 0.1, 'ok');
  const p = window.SFUApi.parseSSE('event: draft\ndata: {"a":1}\n\nevent: final\ndata: {"b"');
  record('parseSSE: complete events parsed, partial tail kept', p.events.length === 1 && p.events[0].event === 'draft' && p.events[0].data === '{"a":1}' && p.rest === 'event: final\ndata: {"b"', JSON.stringify(p));
  assertNoErrors('draft swap controller — console errors', errors);
} catch (e) { record('draft swap controller — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors } = makeDom({ online: true });
  const hits = [];
  const draftData = { results: [mkRes('D1'), mkRes('D2')], notes: [], meta: { count: 2 }, preliminary: true };
  const finalData = { results: [mkRes('F1'), mkRes('D1')], notes: [], meta: { count: 2 } };
  window.fetch = (url, opts) => {
    hits.push(String(url));
    return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, body: sseBody([
      { text: sseEvent('draft', draftData).slice(0, 25) }, { text: sseEvent('draft', draftData).slice(25) },
      { text: sseEvent('final', finalData), delay: 5 }]) });
  };
  const drafts = [];
  const r = await window.SFUApi.searchStream('q', {}, 1, (d) => drafts.push(d));
  record('searchStream: POSTs /api/search_stream, draft (split chunks) then final', hits[0].includes('/api/search_stream') && drafts.length === 1 && drafts[0].preliminary === true && drafts[0].results[0].id === 'D1' && r.results.map((x) => x.id).join(',') === 'F1,D1' && r.hadDraft === true && r.source === 'live', JSON.stringify({ drafts: drafts.length, final: r.results.map((x) => x.id), hadDraft: r.hadDraft }));

  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, body: sseBody([{ text: sseEvent('final', finalData) }]) });
  const before = window.SFUApi.draftStreamStats().finalOnly;
  const drafts2 = [];
  const r2 = await window.SFUApi.searchStream('q', {}, 1, (d) => drafts2.push(d));
  record('searchStream: cache-hit stream (final only) → no draft callback', drafts2.length === 0 && r2.hadDraft === false && window.SFUApi.draftStreamStats().finalOnly === before + 1, 'drafts=' + drafts2.length);

  const urls = [];
  window.fetch = (url) => {
    urls.push(String(url));
    if (String(url).includes('/api/search_stream')) return Promise.resolve({ ok: false, status: 404, headers: { get: () => null }, json: () => Promise.resolve({}) });
    return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(finalData) });
  };
  const r3 = await window.SFUApi.searchStream('q', {}, 1, () => {});
  record('searchStream: gate off (404) → falls back to /api/search', urls.length === 2 && urls[1].endsWith('/api/search') && r3.source === 'live' && r3.results.length === 2, JSON.stringify(urls));

  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, body: sseBody([{ text: sseEvent('draft', draftData) }, { text: 'event: error\ndata: {"error":"boom"}\n\n' }]) });
  const r4 = await window.SFUApi.searchStream('q', {}, 1, () => {});
  record('searchStream: error event → mock fallback (demo pill path)', r4.source === 'mock', 'source=' + r4.source);

  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'ok', tools: 12, search_draft_stream: true, sequential: true }) });
  const h = await window.SFUApi.health();
  window.fetch = () => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'ok', tools: 12, search_draft_stream: true }) });
  const h2 = await window.SFUApi.health();
  record('health: draftStream advertised, forced off when sequential', h.draftStream === false && h2.draftStream === true, JSON.stringify({ seq: h.draftStream, plain: h2.draftStream }));
  assertNoErrors('searchStream api-layer — console errors', errors);
} catch (e) { record('searchStream api-layer — threw', false, String(e).slice(0, 300)); }

async function mountStream({ health, finalDelay }) {
  const harness = makeDom({ online: true });
  const { window } = harness;
  const calls = [];
  const draftData = { results: [mkRes('D1'), mkRes('D2'), mkRes('D3')], notes: [], meta: { count: 3 }, preliminary: true };
  const finalData = { results: [mkRes('F1'), mkRes('D2'), mkRes('F3')], notes: [], meta: { count: 3 } };
  window.fetch = (url, opts) => {
    const u = String(url);
    calls.push(u);
    if (u.includes('/health')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(health) });
    if (u.includes('/api/search_stream')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, body: sseBody([{ text: sseEvent('draft', draftData), delay: 5 }, { text: sseEvent('final', finalData), delay: finalDelay }]) });
    if (u.includes('/api/search')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(finalData) });
    return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({}) });
  };
  harness.evalIn(read('search.js'), 'search.js');
  await sleep(150);
  return { ...harness, calls };
}
const titles = (w) => Array.from(w.document.querySelectorAll('h3')).map((h) => h.textContent.replace('Preliminary', '').trim()).join('|');

try {
  const { window, errors, calls } = await mountStream({ health: { status: 'ok', tools: 12, search_draft_stream: true }, finalDelay: 150 });
  submitQuery(window, 'draft stream query');
  await sleep(80);
  const badges = window.document.querySelectorAll('[data-testid="sfu-preliminary-badge"]').length;
  record('GUI stream: draft cards render labelled Preliminary', calls.some((u) => u.includes('/api/search_stream')) && badges === 3 && titles(window) === 'T D1|T D2|T D3' && !!window.document.querySelector('[data-testid="sfu-preliminary-note"]'), `badges=${badges} titles=${titles(window)}`);
  const iv = setInterval(() => window.document.dispatchEvent(new window.MouseEvent('mousemove', { bubbles: true })), 200);
  await sleep(1700);
  record('GUI stream: final arrived but user moving → draft kept (no shuffle)', titles(window) === 'T D1|T D2|T D3', titles(window));
  clearInterval(iv);
  await sleep(1400);
  const badgesAfter = window.document.querySelectorAll('[data-testid="sfu-preliminary-badge"]').length;
  record('GUI stream: idle → swapped to final, label removed', titles(window) === 'T F1|T D2|T F3' && badgesAfter === 0 && !window.document.querySelector('[data-testid="sfu-preliminary-note"]'), `titles=${titles(window)} badges=${badgesAfter}`);
  record('GUI stream: no /api/search call when the gate is on', !calls.some((u) => /\/api\/search$/.test(u)), calls.filter((u) => u.includes('/api/')).join(','));
  assertNoErrors('GUI stream — console errors', errors);
} catch (e) { record('GUI stream — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors, calls } = await mountStream({ health: { status: 'ok', tools: 12, search_draft_stream: false }, finalDelay: 10 });
  submitQuery(window, 'gate off query');
  await sleep(120);
  record('GUI stream: gate off → /api/search, no draft, no label', calls.some((u) => /\/api\/search$/.test(u)) && !calls.some((u) => u.includes('search_stream')) && titles(window) === 'T F1|T D2|T F3' && !window.document.querySelector('[data-testid="sfu-preliminary-badge"]'), calls.filter((u) => u.includes('/api/')).join(','));
  assertNoErrors('GUI stream gate off — console errors', errors);
} catch (e) { record('GUI stream gate off — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors, calls } = await mountStream({ health: { status: 'ok', tools: 12, search_draft_stream: true, sequential: true }, finalDelay: 10 });
  submitQuery(window, 'sequential query');
  await sleep(200);
  record('GUI stream: sequential mode → stream never used', !calls.some((u) => u.includes('search_stream')), calls.filter((u) => u.includes('/api/')).join(','));
  assertNoErrors('GUI stream sequential — console errors', errors);
} catch (e) { record('GUI stream sequential — threw', false, String(e).slice(0, 300)); }


const ENGAGE_KEYS = new Set(['ts', 'session_id', 'kind', 'query', 'rank', 'doc_id', 'action_type', 'refined_from']);
const PY_KINDS = ['query', 'impression', 'result_click', 'action'];
const PY_ACTIONS = (() => {
  const src = readFileSync(path.join(ROOT, 'source', 'lib', 'engagement.py'), 'utf8');
  const m = src.match(/^ACTION_TYPES = \{([^}]*)\}/m);
  return m ? Array.from(m[1].matchAll(/"([a-z_]+)"/g)).map((x) => x[1]) : [];
})();
const validateLikeServer = (ev) => {
  if (!ev || typeof ev !== 'object') return 'not an object';
  if (!String(ev.session_id || '').trim()) return 'session_id missing';
  if (!PY_KINDS.includes(ev.kind)) return 'bad kind ' + ev.kind;
  if (typeof ev.ts !== 'string' || !ev.ts) return 'ts missing';
  if (ev.rank != null && !Number.isInteger(ev.rank)) return 'rank not int';
  if (ev.kind === 'action' && !PY_ACTIONS.includes(ev.action_type)) return 'bad action_type ' + ev.action_type;
  const extra = Object.keys(ev).filter((k) => !ENGAGE_KEYS.has(k));
  if (extra.length) return 'unknown keys ' + extra.join(',');
  return null;
};
const postedEvents = (posts) => posts.flatMap((p) => (p.body && p.body.events) || []);

try {
  const { window, errors, engagementPosts } = await mountApp('search.html', { online: true, searchResponder: pagedResponder });
  submitQuery(window, 'engagement query one');
  await sleep(150);
  window.SFUApi.engagement.flush();
  let evs = postedEvents(engagementPosts);
  const q1 = evs.filter((e) => e.kind === 'query');
  const imps = evs.filter((e) => e.kind === 'impression');
  const ranks = imps.map((e) => e.rank).join(',');
  const sid = evs.length ? evs[0].session_id : '';
  record('engagement: search posts one query event to /engagement',
    q1.length === 1 && q1[0].query === 'engagement query one' && engagementPosts.every((p) => p.url.endsWith('/engagement')),
    JSON.stringify(q1));
  record('engagement: one impression per displayed result, rank 1..N, doc_id = DOI',
    imps.length === 10 && ranks === '1,2,3,4,5,6,7,8,9,10' && imps[0].doc_id === '10.0/p1' && imps.every((e) => e.query === 'engagement query one'),
    'n=' + imps.length + ' ranks=' + ranks + ' doc0=' + (imps[0] && imps[0].doc_id));
  record('engagement: every event carries the same per-tab session id',
    !!sid && evs.every((e) => e.session_id === sid) && window.sessionStorage.getItem('sfu_engagement_session_v1') === sid,
    'sid=' + sid);

  const card3 = window.document.querySelector('[data-result-id="P3"]');
  card3.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  await sleep(40);
  const card2 = window.document.querySelector('[data-result-id="P2"]');
  card2.querySelector('[data-testid="sfu-card-access"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
  card2.querySelector('[data-testid="sfu-card-save"]').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  await sleep(40);
  const before = engagementPosts.length;
  window.SFUApi.engagement.flush();
  evs = postedEvents(engagementPosts.slice(before));
  const click = evs.find((e) => e.kind === 'result_click');
  const abs = evs.find((e) => e.kind === 'action' && e.action_type === 'abstract');
  record('engagement: card click posts result_click with its rank + doc_id + query',
    !!click && click.rank === 3 && click.doc_id === '10.0/p3' && click.query === 'engagement query one',
    JSON.stringify(click || null));
  record('engagement: opening the detail posts action=abstract for the same rank',
    !!abs && abs.rank === 3 && abs.doc_id === '10.0/p3', JSON.stringify(abs || null));
  const pdf = evs.find((e) => e.kind === 'action' && e.action_type === 'pdf');
  const save = evs.find((e) => e.kind === 'action' && e.action_type === 'save');
  record('engagement: access link → action=pdf, bookmark → action=save (rank 2)',
    !!pdf && pdf.rank === 2 && !!save && save.rank === 2, JSON.stringify({ pdf, save }));

  submitQuery(window, 'engagement query two');
  await sleep(150);
  const before2 = engagementPosts.length;
  window.SFUApi.engagement.flush();
  const q2 = postedEvents(engagementPosts.slice(before2)).find((e) => e.kind === 'query');
  record('engagement: a follow-up search carries refined_from = previous query',
    !!q2 && q2.query === 'engagement query two' && q2.refined_from === 'engagement query one', JSON.stringify(q2 || null));

  const all = postedEvents(engagementPosts);
  const bad = all.map(validateLikeServer).filter(Boolean);
  const shapeOk = engagementPosts.every((p) => p.opts.method === 'POST' && p.opts.keepalive === true
    && /json/.test(p.opts.headers['Content-Type']) && Array.isArray(p.body.events) && Object.keys(p.body).join(',') === 'events'
    && p.body.events.length <= 50);
  record('engagement: batch flush = POST {events:[...]} keepalive, every event passes validate_event rules',
    shapeOk && bad.length === 0 && all.length > 0 && PY_ACTIONS.length > 0,
    'batches=' + engagementPosts.length + ' events=' + all.length + (bad.length ? ' bad=' + bad.slice(0, 3).join('|') : ''));
  record('engagement: client ACTION_TYPES/KINDS identical to lib/engagement.py',
    JSON.stringify(window.SFUApi.engagement.ACTION_TYPES.slice().sort()) === JSON.stringify(PY_ACTIONS.slice().sort())
    && JSON.stringify(window.SFUApi.engagement.KINDS.slice().sort()) === JSON.stringify(PY_KINDS.slice().sort()),
    'client=' + window.SFUApi.engagement.ACTION_TYPES.join(',') + ' server=' + PY_ACTIONS.join(','));
  assertNoErrors('engagement wiring — console errors', errors);
} catch (e) { record('engagement wiring — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors } = makeDom({ online: true });
  const sent = [];
  const queue = [];
  const fakeSetTimeout = (fn, ms) => { const id = { fn, ms }; queue.push(id); return id; };
  const fakeClearTimeout = (id) => { const i = queue.indexOf(id); if (i >= 0) queue.splice(i, 1); };
  const q = window.SFUApi.createEngagementQueue({ maxBatch: 3, delayMs: 2000, setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout, send: (b, why) => sent.push({ b, why }), now: () => '2026-10-12T00:00:00Z' });
  const okPush = q.push({ session_id: 's', kind: 'impression', rank: 1, doc_id: 'd1', query: 'x' });
  const rejected = [
    q.push({ session_id: 's', kind: 'nope' }),
    q.push({ session_id: '', kind: 'query' }),
    q.push({ session_id: 's', kind: 'action', action_type: 'teleport' }),
    q.push({ session_id: 's', kind: 'impression', rank: 'x' }),
  ];
  record('engagement queue: invalid events rejected client-side (same rules as validate_event)',
    okPush && rejected.every((r) => r === false) && q.size === 1, 'size=' + q.size);
  record('engagement queue: first event arms one flush timer, nothing sent yet', q.pending && queue.length === 1 && sent.length === 0, 'timers=' + queue.length);
  q.push({ session_id: 's', kind: 'action', action_type: 'save', doc_id: 'd1' });
  record('engagement queue: further events reuse the armed timer', queue.length === 1 && q.size === 2, 'timers=' + queue.length);
  queue[0].fn();
  record('engagement queue: timer flush sends one {events:[...]} batch and empties the queue',
    sent.length === 1 && sent[0].why === 'timer' && sent[0].b.events.length === 2 && q.size === 0 && sent[0].b.events[0].ts === '2026-10-12T00:00:00Z',
    JSON.stringify(sent[0] && sent[0].b));
  q.push({ session_id: 's', kind: 'query', query: 'a' });
  q.push({ session_id: 's', kind: 'query', query: 'b' });
  q.push({ session_id: 's', kind: 'query', query: 'c' });
  record('engagement queue: reaching maxBatch flushes immediately', sent.length === 2 && sent[1].why === 'full' && sent[1].b.events.length === 3 && !q.pending, 'sent=' + sent.length);
  const throwing = window.SFUApi.createEngagementQueue({ send: () => { throw new Error('boom'); }, setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout });
  throwing.push({ session_id: 's', kind: 'query', query: 'z' });
  let threw = false;
  try { throwing.flush('pagehide'); } catch (e) { threw = true; }
  record('engagement queue: a failing transport never throws into the UI', !threw, 'threw=' + threw);
  assertNoErrors('engagement queue — console errors', errors);
} catch (e) { record('engagement queue — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors, fetchCalls } = await mountApp('search.html', { online: false });
  submitQuery(window, 'offline engagement query');
  await sleep(150);
  const card = window.document.querySelector('[data-result-id]');
  if (card) card.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  await sleep(30);
  window.SFUApi.engagement.flush();
  await sleep(10);
  record('engagement: mock mode (backend offline) posts nothing',
    window.SFUApi.engagement.mode() === 'mock' && !fetchCalls.some((u) => u.endsWith('/engagement')) && window.SFUApi.engagement.pending() === 0 && !!card,
    'mode=' + window.SFUApi.engagement.mode() + ' calls=' + fetchCalls.filter((u) => u.endsWith('/engagement')).length);
  record('engagement: mock mode keeps the demo banner (integrity floor)', !!window.document.getElementById('sfu-demo-pill'), 'pill=' + !!window.document.getElementById('sfu-demo-pill'));
  assertNoErrors('engagement mock mode — console errors', errors);
} catch (e) { record('engagement mock mode — threw', false, String(e).slice(0, 300)); }

const ANALYTICS_FIXTURE = {
  generated_for: 'research_analytics_dashboard',
  panels: {
    kpis: { status: 'ok', ndcg_mean_best: 0.6534, best_method: 'splade', k: 10, eval_queries: 120, judged_pairs: 4034, judge: 'fixture-judge', timestamp: '2026-05-16T20:45:46', source: 'data/eval_results/benchmark_llm_judge_final.json',
      methods: [{ method: 'bm25', label: 'BM25F (local)', mean_ndcg: 0.6249, mean_mrr: 0.6562, mean_p_at_k: 0.5108 }, { method: 'splade', label: 'SPLADE (local)', mean_ndcg: 0.6534, mean_mrr: 0.6625, mean_p_at_k: 0.6033 }] },
    ndcg_by_subject: { status: 'ok', primary_method: 'rrf', subjects: [{ subject: 'Music', ndcg: 0 }, { subject: 'Physics', ndcg: 0.8123 }] },
    reranker_signal: { status: 'ok', source: 'heuristic_weights', axes: [{ signal: 'semantic_similarity', weight: 0.35 }, { signal: 'recency', weight: 0.15 }] },
    position_bias: { status: 'awaiting_click_data', source: 'gui', total_clicks: 3, total_impressions: 40, min_clicks_required: 20, note: 'Propensity feeds IPS debiasing of click labels.',
      curve: [{ rank: 1, impressions: 20, clicks: 2, click: 0.1, propensity: 1.0 }, { rank: 2, impressions: 20, clicks: 1, click: 0.05, propensity: 0.5 }, { rank: 3, impressions: 0, clicks: 0, click: 0, propensity: null }] },
    model_versions: { status: 'ok', updated: '2026-06-05', versions: [{ component: 'embedder', version: 'v5', date: '2026-05-24', ndcg: 0.7717, status: 'active', available: true }] },
    session_replay: { status: 'ok', source: 'gui', sessions: [{ session_id: 'g-fixture-sess', start: '2026-10-12T10:00:00+00:00', n_queries: 2, n_clicks: 1, n_actions: 2,
      queries: [{ query: 'fixture query', ts: '2026-10-12T10:00:00+00:00', results: [] }, { query: 'fixture query refined', refined_from: 'fixture query', results: [{ doc_id: '10.0/fx', rank: 4, actions: ['abstract', 'pdf'] }] }] }] },
    index_shape: { status: 'ok', total_docs: 1234567, n_sections: 10, n_subjects: 5, era_boundary_year: 2010, rrf_k: 60, built: '2026-06-16T03:00:21', source: 'data/thinclient_index/manifest.json',
      subjects: [{ subject: 'other', label: 'Other / unrouted', docs: 600000 }, { subject: 'med_bio', label: 'Medicine & biology', docs: 634567 }], eras: [{ era: 'archive', docs: 234567 }, { era: 'recent', docs: 1000000 }] },
    embedding_drift: { status: 'stub', reason: 'UMAP export not wired' },
    access_funnel: { status: 'stub', reason: 'access-resolver logging not wired' },
    oa_equity: { status: 'stub', reason: 'OA-by-subject export not wired' },
  },
};

async function mountAnalytics(responder) {
  const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="root"></div></body></html>`, { url: 'http://localhost/app/analytics.html', runScripts: 'outside-only', pretendToBeVisual: true });
  const { window } = dom;
  window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
  const calls = [];
  window.fetch = (url) => { calls.push(String(url)); return responder(String(url)); };
  const errors = [];
  window.console.error = (...a) => { errors.push(a.map(String).join(' ')); };
  window.addEventListener('error', (e) => { errors.push('windowerror: ' + (e.error ? e.error.stack : e.message)); });
  const styleEl = window.document.createElement('style');
  styleEl.textContent = read('analytics.html').match(/<style>([\s\S]*?)<\/style>/)[1] + '\n' + read('lib/base.css');
  window.document.head.appendChild(styleEl);
  for (const f of ['vendor/react.production.min.js', 'vendor/react-dom.production.min.js', 'lib/mock.js', 'lib/api.js', 'lib/ui.js', 'analytics.js']) {
    try { window.eval(read(f)); } catch (e) { errors.push('EVAL ' + f + ': ' + e.message); throw e; }
  }
  await sleep(80);
  for (const id of ['sfu-operator-toggle', 'sfu-engagement-toggle']) {
    const b = window.document.querySelector(`[data-testid="${id}"]`);
    if (b) b.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  }
  await sleep(40);
  return { window, errors, calls };
}
const okJson = (data) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(data) });
const panelState = (w, n) => { const el = w.document.querySelector(`[data-panel="${n}"]`); return el ? el.getAttribute('data-state') : null; };
const NINE = ['kpis', 'ndcg_by_subject', 'reranker_signal', 'model_versions', 'position_bias', 'session_replay', 'embedding_drift', 'access_funnel', 'oa_equity'];

try {
  const { window, errors, calls } = await mountAnalytics((u) => u.includes('/analytics') ? okJson(ANALYTICS_FIXTURE) : okJson({ status: 'ok', tools: 12 }));
  const states = NINE.map((n) => n + '=' + panelState(window, n));
  const want = NINE.map((n) => n + '=' + ANALYTICS_FIXTURE.panels[n].status);
  record('analytics: all nine panels render with their bundle status', states.join(',') === want.join(',') && calls.some((u) => u.endsWith('/analytics')), states.join(' '));
  const text = window.document.body.textContent;
  const stubs = window.document.querySelectorAll('[data-testid="sfu-panel-stub"]');
  record('analytics: the three stub panels say "Not wired: <reason>", no figures',
    stubs.length === 3 && /Not wired: UMAP export not wired/.test(text) && /Not wired: access-resolver logging not wired/.test(text) && /Not wired: OA-by-subject export not wired/.test(text),
    'stub notices=' + stubs.length);
  const awaiting = window.document.querySelector('[data-testid="sfu-awaiting-clicks"]');
  const pbRows = window.document.querySelectorAll('[data-testid="sfu-position-bias"] tbody tr').length;
  record('analytics: position_bias awaiting state shows click count vs threshold + raw counts',
    !!awaiting && /3 of the 20 clicks/.test(awaiting.textContent) && pbRows === 2 && /gui|search GUI/.test(text),
    (awaiting ? awaiting.textContent.slice(0, 80) : 'no notice') + ' rows=' + pbRows);
  const sess = window.document.querySelector('[data-session="g-fixture-sess"]');
  record('analytics: session replay renders query → clicked result → actions',
    !!sess && /fixture query refined/.test(sess.textContent) && /refined from/.test(sess.textContent) && /#4/.test(sess.textContent) && /abstract/.test(sess.textContent) && /pdf/.test(sess.textContent),
    sess ? sess.textContent.slice(0, 120) : 'no session node');
  const kpiRows = window.document.querySelectorAll('[data-testid="sfu-kpi-methods"] tbody tr').length;
  const modelRows = window.document.querySelectorAll('[data-testid="sfu-model-versions"] tbody tr').length;
  record('analytics: kpis method table, model_versions table, reranker weights, subject NDCG from the bundle',
    kpiRows === 2 && /0\.653/.test(text) && modelRows === 1 && /semantic similarity/.test(text) && /0\.812/.test(text) && /Physics/.test(text),
    'kpiRows=' + kpiRows + ' modelRows=' + modelRows);
  record('analytics: index facts + disclosures sourced from index_shape/reranker_signal',
    /1,234,567/.test(text) && /600,000 documents/.test(text) && /recency weight \(0\.15\)/.test(text) && /k = 60/.test(text) && panelState(window, 'index_shape') === 'ok',
    'facts ok=' + /1,234,567/.test(text));
  const banned = ['0.967', '0.966', '600k', '600k-vector', '150,413,098', '41.2M', '18432', 'top 64'].filter((s) => text.includes(s));
  record('analytics: no prototype placeholder figure survives', banned.length === 0, banned.length ? 'found ' + banned.join(',') : 'none of the prototype figures present');
  assertNoErrors('analytics fixture — console errors', errors);
} catch (e) { record('analytics fixture — threw', false, String(e).slice(0, 300)); }

try {
  const { window, errors } = await mountAnalytics(() => Promise.reject(new Error('offline')));
  const states = NINE.map((n) => panelState(window, n));
  const text = window.document.body.textContent;
  record('analytics: backend offline → every panel an explicit stub, no figures',
    states.every((s) => s === 'stub') && /Not wired: live backend unavailable/.test(text) && !/\d{1,3},\d{3},\d{3}/.test(text),
    states.join(','));
  record('analytics: backend offline → demo banner shown (integrity floor)', !!window.document.getElementById('sfu-demo-pill'), 'pill=' + !!window.document.getElementById('sfu-demo-pill'));
  assertNoErrors('analytics offline — console errors', errors);
} catch (e) { record('analytics offline — threw', false, String(e).slice(0, 300)); }

console.log('\n================ jsdom GUI verification ================');
let pass = 0, fail = 0;
for (const r of results) {
  const tag = r.ok ? 'PASS' : 'FAIL';
  if (r.ok) pass++; else fail++;
  console.log(`  [${tag}] ${r.ctx.padEnd(52)} ${r.detail}`);
}
console.log(`\n${pass} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
