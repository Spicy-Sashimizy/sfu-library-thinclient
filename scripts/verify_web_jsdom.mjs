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
  window.fetch = (url, opts) => {
    const u = String(url);
    if (!online) return Promise.reject(new Error('offline: network down'));
    if (u.includes('/health')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(HEALTH_LIVE) });
    if (u.includes('/api/search')) {
      const body = opts && opts.body ? JSON.parse(opts.body) : {};
      searchBodies.push(body);
      const data = searchResponder ? searchResponder(body) : SEARCH_LIVE;
      return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(data) });
    }
    if (u.includes('/api/index_status')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ metrics: {} }) });
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

  return { dom, window, errors, evalIn, ioInstances, searchBodies };
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

console.log('\n================ jsdom GUI verification ================');
let pass = 0, fail = 0;
for (const r of results) {
  const tag = r.ok ? 'PASS' : 'FAIL';
  if (r.ok) pass++; else fail++;
  console.log(`  [${tag}] ${r.ctx.padEnd(52)} ${r.detail}`);
}
console.log(`\n${pass} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
