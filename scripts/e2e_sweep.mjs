const PWPATH = process.env.PW ? `${process.env.PW}/playwright/index.js` : 'playwright';
const _pw = await import(PWPATH);
const chromium = _pw.chromium || (_pw.default && _pw.default.chromium);

const BASE = process.env.BASE || 'http://127.0.0.1:8080';
const VIEWPORTS = [
  { name: 'laptop-1280', width: 1280, height: 720 },
  { name: 'hd-1366',     width: 1366, height: 768 },
  { name: 'mid-1536',    width: 1536, height: 864 },
  { name: 'fhd-1920',    width: 1920, height: 1080 },
];

const sleep = ms => new Promise(r => setTimeout(r, ms));
let problems = [];
let actions = [];
let CUR = '';
const act = (s) => actions.push(`${CUR.padEnd(28)} ${s}`);

function wire(page, ctx) {
  page.on('console', m => { if (m.type() === 'error') problems.push(`[console.error] ${ctx()} :: ${m.text().slice(0,200)}`); });
  page.on('pageerror', e => problems.push(`[PAGEERROR] ${ctx()} :: ${String(e).slice(0,200)}`));
}

async function overflow(page) {
  return page.evaluate(() => {
    const de = document.documentElement;
    const xs = [de.scrollWidth - de.clientWidth];
    document.querySelectorAll('main,aside,[data-screen-label]').forEach(el => {
      if (el.scrollWidth - el.clientWidth > 2) xs.push(el.scrollWidth - el.clientWidth);
    });
    return Math.max(0, ...xs);
  });
}

async function clickByText(page, text, timeout = 2500) {
  try { await page.getByText(text, { exact: false }).first().click({ timeout }); act(`click "${text}" -> ok`); return true; }
  catch { act(`click "${text}" -> MISS`); return false; }
}

async function exerciseSearch(page, deep) {
  for (const s of ['Saved', 'History', 'Databases', 'Settings', 'Admin', 'Search']) {
    await clickByText(page, s); await sleep(150);
    if (s === 'Settings') {
      for (const t of ['LLM Backend', 'Zotero', 'Dictionary', 'Privacy', 'LLM Backend', 'Privacy']) { await clickByText(page, t); await sleep(120); }
      for (const t of ['synonyms', 'stop expansions', 'abbreviations']) { await clickByText(page, 'Dictionary'); await clickByText(page, t); await sleep(80); }
    }
    if (s === 'Admin') { for (const t of ['Models', 'Curate', 'Logs', 'Overview']) { await clickByText(page, t); await sleep(120); } }
    if (s === 'Databases') { const inp = page.locator('input').first(); try { await inp.fill('science'); await sleep(150); } catch {} }
  }
  if (deep) {
    await clickByText(page, 'Search'); await sleep(200);
    const inp = page.locator('input').first();
    try { await inp.fill('machine learning drug discovery'); await inp.press('Enter'); } catch {}
    await sleep(28000);
    try { await page.locator('h3').first().click({ timeout: 2000 }); await sleep(400);
      for (const t of ['Citations', 'Export', 'Abstract']) { await clickByText(page, t); await sleep(150); } } catch {}
  }
}
async function exerciseAnalytics(page) {
  await clickByText(page, 'Operator'); await sleep(300);
  await clickByText(page, 'Operator'); await sleep(150);
}
async function exerciseIndex(page, deep) {
  for (const t of ['Warm Cache', 'Storage Budget', 'Personas']) { await clickByText(page, t); await sleep(250); }
  if (deep) { await clickByText(page, 'biomedical'); await sleep(200); await clickByText(page, 'Unpack'); await sleep(400); }
}

const APPS = {
  'search.html':       exerciseSearch,
  'analytics.html':    exerciseAnalytics,
  'index_manager.html':exerciseIndex,
};

const browser = await chromium.launch();
const results = [];

for (const vp of VIEWPORTS) {
  for (const app of Object.keys(APPS)) {
    const ctxName = `${app}@${vp.name}`;
    CUR = ctxName;
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await context.newPage();
    wire(page, () => ctxName);
    const before = problems.length;
    try {
      await page.goto(`${BASE}/app/${app}`, { waitUntil: 'load', timeout: 30000 });
      act(`goto ${app} (${vp.width}x${vp.height}) -> loaded`);
      await sleep(600);
      await APPS[app](page, false);
      await sleep(200);
      const ov = await overflow(page);
      results.push({ ctxName, overflow: ov, errors: problems.length - before });
    } catch (e) { problems.push(`[NAV/THREW] ${ctxName} :: ${String(e).slice(0,160)}`); results.push({ ctxName, overflow: -1, errors: problems.length - before }); }
    await context.close();
  }
}

const deepVp = { width: 1440, height: 900 };
for (const app of Object.keys(APPS)) {
  const ctxName = `${app}@deep-1440`;
  CUR = ctxName;
  const context = await browser.newContext({ viewport: deepVp });
  const page = await context.newPage();
  wire(page, () => ctxName);
  const before = problems.length;
  try {
    await page.goto(`${BASE}/app/${app}`, { waitUntil: 'load', timeout: 30000 });
    act(`goto ${app} (deep 1440) -> loaded`);
    await sleep(600);
    await APPS[app](page, true);
    results.push({ ctxName, overflow: await overflow(page), errors: problems.length - before });
  } catch (e) { problems.push(`[THREW] ${ctxName} :: ${String(e).slice(0,160)}`); }
  await context.close();
}

{
  CUR = 'design-consistency';
  const CANON = ['--bg','--text','--text-secondary','--text-muted','--border','--border-light','--radius','--radius-sm','--sidebar-width'];
  const snap = {}, timing = {};
  for (const app of ['search.html','analytics.html','index_manager.html']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage(); wire(page, () => 'consistency:' + app);
    const t0 = Date.now();
    try {
      await page.goto(`${BASE}/app/${app}`, { waitUntil: 'load', timeout: 30000 });
      await page.waitForFunction(() => { const r = document.getElementById('root'); return r && r.childNodes.length > 0; }, { timeout: 15000 }).catch(() => {});
      timing[app] = Date.now() - t0;
      snap[app] = await page.evaluate((names) => {
        const cs = getComputedStyle(document.documentElement); const o = {};
        names.forEach(n => o[n] = cs.getPropertyValue(n).trim());
        o.accent = (cs.getPropertyValue('--accent-red') || cs.getPropertyValue('--c-red')).trim();
        return o;
      }, CANON);
      act(`measured ${app}: ${timing[app]}ms to mount`);
    } catch (e) { problems.push(`[THREW] consistency:${app} :: ${String(e).slice(0,120)}`); }
    await ctx.close();
  }
  const keys = [...CANON, 'accent'];
  const mism = [];
  for (const k of keys) {
    const vals = [...new Set(Object.values(snap).map(s => s && s[k]).filter(Boolean))];
    if (vals.length > 1) mism.push(`${k}: ` + Object.entries(snap).map(([a, s]) => a.replace('.html','') + '=' + (s && s[k])).join(' | '));
  }
  results.push({ ctxName: 'design tokens unified (9+accent)', overflow: 0, errors: mism.length, note: mism.length ? `${mism.length} MISMATCH` : 'all match' });
  mism.forEach(m => problems.push('[DESIGN-MISMATCH] ' + m));
  Object.entries(timing).forEach(([a, ms]) => results.push({ ctxName: 'load ' + a, overflow: 0, errors: 0, note: ms + 'ms to mount' }));

  CUR = 'banner-shift';
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage(); wire(page, () => 'banner-shift');
  try {
    await page.goto(`${BASE}/app/search.html`, { waitUntil: 'load', timeout: 30000 });
    await page.waitForFunction(() => document.querySelector('aside'), { timeout: 10000 }).catch(() => {});
    const top = () => page.evaluate(() => { const a = document.querySelector('aside'); return a ? a.getBoundingClientRect().top : null; });
    const before = await top();
    await page.evaluate(() => window.SFUUI && window.SFUUI.setMockBanner(true, 'test')); await sleep(300);
    const after = await top();
    const shift = (before != null && after != null) ? Math.abs(after - before) : -1;
    act(`banner toggled: sidebar top ${before}->${after} (${shift}px)`);
    results.push({ ctxName: 'demo banner layout shift', overflow: 0, errors: shift > 1 ? 1 : 0, note: shift + 'px' });
    if (shift > 1) problems.push(`[BANNER-SHIFT] sidebar moved ${shift}px when demo banner shown`);
  } catch (e) { problems.push(`[THREW] banner-shift :: ${String(e).slice(0,120)}`); }
  await ctx.close();
}

{
  CUR = 'sidebar-consistency';
  const feat = {};
  for (const app of ['search.html','analytics.html','index_manager.html']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage(); wire(page, () => 'sidebar:' + app);
    try {
      await page.goto(`${BASE}/app/${app}`, { waitUntil: 'load', timeout: 30000 });
      await page.waitForFunction(() => document.querySelector('aside'), { timeout: 15000 }).catch(() => {});
      await sleep(400);
      feat[app] = await page.evaluate(() => ({
        sidebar: !!document.querySelector('aside'),
        sessionReplay: /Recent Searches/i.test(document.body.innerText),
        aiStatus: /AI (Online|Offline)/i.test(document.body.innerText),
      }));
    } catch (e) { problems.push(`[THREW] sidebar:${app} :: ${String(e).slice(0,100)}`); }
    await ctx.close();
  }
  const allHave = k => Object.values(feat).length === 3 && Object.values(feat).every(f => f && f[k]);
  const sb = allHave('sidebar'), sr = allHave('sessionReplay'), ai = allHave('aiStatus');
  results.push({ ctxName: 'sidebar consistent on all apps', overflow: 0, errors: (sb && sr && ai) ? 0 : 1, note: `sidebar=${sb} sessionReplay=${sr} aiStatus=${ai}` });
  if (!(sb && sr && ai)) problems.push('[SIDEBAR-INCONSISTENT] ' + JSON.stringify(feat));

  CUR = 'pill-consistency';
  const pills = {};
  for (const app of ['search.html','analytics.html','index_manager.html']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    await page.route('**/health', r => r.abort());
    await page.route('**/api/**', r => r.abort());
    await page.route('**/analytics', r => r.abort());
    try {
      await page.goto(`${BASE}/app/${app}`, { waitUntil: 'load', timeout: 30000 });
      await page.waitForFunction(() => document.querySelector('aside'), { timeout: 15000 }).catch(() => {});
      await sleep(1200);
      pills[app] = await page.evaluate(() => !!document.getElementById('sfu-demo-pill'));
    } catch (e) { pills[app] = false; }
    await ctx.close();
  }
  const allPill = Object.values(pills).length === 3 && Object.values(pills).every(Boolean);
  results.push({ ctxName: 'demo pill on ALL apps (offline)', overflow: 0, errors: allPill ? 0 : 1, note: JSON.stringify(pills) });
  if (!allPill) problems.push('[PILL-INCONSISTENT] offline pill: ' + JSON.stringify(pills));
}

{
  CUR = 'suite-shell';
  const context = await browser.newContext({ viewport: deepVp });
  const page = await context.newPage();
  wire(page, () => 'suite-shell');
  const visibleFrame = async () => {
    for (const fr of page.frames()) {
      if (fr === page.mainFrame()) continue;
      try { const el = await fr.frameElement(); if (await el.isVisible()) return fr; } catch {}
    }
    return null;
  };
  const innerText = async () => {
    const fr = await visibleFrame();
    if (!fr) return '';
    try { return (await fr.evaluate(() => document.body.innerText)).replace(/\s+/g, ' '); } catch { return ''; }
  };
  const whichApp = t =>
    /What the search reads from|Five things the collection/i.test(t) ? 'analytics' :
    /Storage Budget|Warm Cache|Personas & Sections|backend:/i.test(t) ? 'index-manager' :
    /Research begins here|Saved Papers|results for/i.test(t) ? 'search' : 'unknown';
  const clickInFrame = async (txt) => {
    const fr = await visibleFrame();
    if (!fr) return false;
    try { await fr.getByText(txt, { exact: false }).first().click({ timeout: 4000 }); act(`shell: click "${txt}" in app`); return true; }
    catch { act(`shell: click "${txt}" -> MISS`); return false; }
  };
  const waitApp = async (want) => { for (let i = 0; i < 20; i++) { if (whichApp(await innerText()) === want) return true; await sleep(500); } return false; };
  try {
    await page.goto(`${BASE}/app/suite.html`, { waitUntil: 'load', timeout: 30000 });
    act('goto suite.html -> loaded'); await sleep(2500);
    const steps = [
      { txt: 'About index', want: 'analytics' },
      { txt: 'Index',       want: 'index-manager' },
      { txt: 'Search',      want: 'search' },
    ];
    let okCount = 0;
    for (const s of steps) { await clickInFrame(s.txt); const ok = await waitApp(s.want); act(`shell: swapped to ${s.want} -> ${ok ? 'OK' : 'FAIL'}`); if (ok) okCount++; }
    results.push({ ctxName: 'suite-shell app-swap (3 nav)', overflow: 0, errors: 0, note: `${okCount}/3 swaps OK` });
  } catch (e) { problems.push(`[THREW] suite-shell :: ${String(e).slice(0,160)}`); }
  await context.close();
}

{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const before = problems.length;
  const pass6 = [];
  const ok = (name, cond, note = '') => { pass6.push({ name, ok: !!cond, note }); act(`pass6 ${name}: ${cond ? 'OK' : 'FAIL'}${note ? ' ('+note+')' : ''}`); };

  let searchDelayMs = 0;
  let searchResponse = null;
  await page.route('**/health', r => r.fulfill({ json: { status: 'ok', tools: 12, warm: true } }));
  await page.route('**/api/search', async r => {
    if (searchDelayMs) await sleep(searchDelayMs);
    if (searchResponse === '429') return r.fulfill({ status: 429, headers: { 'Retry-After': '3' }, json: {} });
    if (searchResponse === 'degraded') return r.fulfill({ json: { results: [{ id:'d1', title:'Degraded result', authors:['X'], year:2024, source:'J', volume:'1', issue:'1', doi:'10.0/d', cited_by:1, type:'article', abstract:'a', tldr:'t' }], notes: [], meta: { count: 1 }, degraded: true, degraded_shards: 2 } });
    return r.fulfill({ json: { results: [{ id:'L1', title:'Live result one', authors:['A. One'], year:2024, source:'Nature', volume:'1', issue:'1', doi:'10.0/x', cited_by:5, type:'article', abstract:'abs', tldr:'tldr' }], notes: [], meta: { count: 1 } } });
  });

  try {
    await page.goto(`${BASE}/app/search.html`, { waitUntil: 'load', timeout: 30000 });
    await page.waitForFunction(() => document.getElementById('root') && document.getElementById('root').childNodes.length > 0, { timeout: 15000 }).catch(() => {});
    await sleep(400);

    const hasInput = await page.locator('input').count();
    const landingCards = await page.locator('h3').count();
    ok('default-bare: search box present on landing', hasInput > 0);
    ok('default-bare: no result cards before search', landingCards === 0, `${landingCards} h3`);

    await page.getByText('Filters', { exact: false }).first().click({ timeout: 3000 }).catch(() => {});
    await sleep(200);
    const filterSelects = await page.locator('select').count();
    ok('filters expander: selects appear after click', filterSelects >= 3, `${filterSelects} selects`);

    searchDelayMs = 120; searchResponse = 'results';
    const inp = page.locator('input').first();
    await inp.fill('machine learning drug discovery'); await inp.press('Enter');
    await sleep(50);
    let skel = await page.locator('[data-skeleton-card]').count();
    ok('skeleton absent <300ms (fast search)', skel === 0, `${skel} skeleton cards <300ms`);
    await sleep(400);
    let h3 = await page.locator('h3').count();
    ok('fast search renders result cards', h3 > 0, `${h3} h3`);

    searchDelayMs = 700; searchResponse = 'results';
    await inp.fill('graph neural networks'); await inp.press('Enter');
    await sleep(350);
    skel = await page.locator('[data-skeleton-card]').count();
    ok('skeleton appears ≥300ms (slow search)', skel >= 3, `${skel} skeleton cards ≥300ms`);

    const colW = await page.evaluate(() => { const m = document.querySelector('main'); return m ? m.getBoundingClientRect().width : -1; });
    await sleep(500);
    const colW2 = await page.evaluate(() => { const m = document.querySelector('main'); return m ? m.getBoundingClientRect().width : -1; });
    ok('no layout shift skeleton→results', Math.abs(colW - colW2) <= 1, `${colW}px→${colW2}px`);

    searchDelayMs = 0; searchResponse = '429';
    await inp.fill('overload query'); await inp.press('Enter');
    await sleep(300);
    const countdown = await page.getByText(/retrying in/i).count().catch(() => 0);
    ok('429 → determinate countdown shown', countdown > 0);

    searchResponse = 'degraded';
    await inp.fill('degraded query'); await inp.press('Enter');
    await sleep(350);
    const notice = await page.getByText(/Degraded/i).count().catch(() => 0);
    ok('degraded → one-line notice shown', notice > 0);

    searchResponse = 'results'; searchDelayMs = 0;

    await clickByText(page, 'Settings'); await sleep(200);
    await clickByText(page, 'Interface'); await sleep(250);
    const savedBefore = await page.getByText('Saved', { exact: true }).count().catch(() => 0);
    const toggles = page.locator('button[role="switch"]');
    if (await toggles.count() > 0) { await toggles.nth(1).click(); await sleep(200); }
    const savedAfter = await page.getByText('Saved', { exact: true }).count().catch(() => 0);
    ok('toggle OFF → Saved nav hides', savedBefore > 0 && savedAfter < savedBefore, `before=${savedBefore} after=${savedAfter}`);
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.getElementById('root') && document.getElementById('root').childNodes.length > 0, { timeout: 15000 }).catch(() => {});
    await sleep(400);
    const savedReload = await page.getByText('Saved', { exact: true }).count().catch(() => 0);
    ok('toggle-OFF persists across reload', savedReload === 0, `${savedReload} Saved after reload`);

    const errs6 = problems.length - before;
    const ov6 = await overflow(page);
    ok('PASS6 zero console errors', errs6 === 0, `${errs6} errors`);
    ok('PASS6 zero horizontal overflow', ov6 <= 4, `${ov6}px`);
  } catch (e) { problems.push(`[THREW] pass6 :: ${String(e).slice(0,180)}`); }

  const fail6 = pass6.filter(p => !p.ok).length;
  for (const p of pass6) {
    results.push({ ctxName: 'pass6: ' + p.name, overflow: 0, errors: p.ok ? 0 : 1, note: p.note });
    if (!p.ok) problems.push(`[PASS6-FAIL] ${p.name} :: ${p.note}`);
  }
  results.push({ ctxName: 'PASS6 bare-bones + progress', overflow: 0, errors: fail6, note: `${pass6.length - fail6}/${pass6.length} assertions` });
  await ctx.close();
}

await browser.close();

try {
  const fs = await import('node:fs');
  fs.writeFileSync(new URL('./sweep_interaction_log.txt', import.meta.url),
    `SFU Library Suite — Playwright interaction log (${actions.length} actions)\n` +
    '='.repeat(64) + '\n' + actions.join('\n') + '\n');
} catch {}

console.log('\n================ RESPONSIVENESS / ERROR MATRIX ================');
for (const r of results) {
  const ov = r.overflow < 0 ? 'NAV-FAIL' : (r.overflow > 4 ? `OVERFLOW ${r.overflow}px` : 'ok');
  console.log(`  ${r.ctxName.padEnd(34)} overflow:${String(ov).padEnd(14)} jsErrors:${r.errors}${r.note ? '  '+r.note : ''}`);
}
console.log('\n================ CAPTURED JS ERRORS / CRASHES ================');
if (!problems.length) console.log('  NONE 🎉');
else problems.forEach(p => console.log('  - ' + p));
console.log(`\nINTERACTIONS LOGGED: ${actions.length} (full log -> scripts/sweep_interaction_log.txt)`);
console.log(`TOTAL PROBLEMS: ${problems.length}`);
process.exit(problems.length ? 1 : 0);
