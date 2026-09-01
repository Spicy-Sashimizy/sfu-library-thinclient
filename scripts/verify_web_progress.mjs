import { readFileSync } from 'node:fs';
import { JSDOM } from 'jsdom';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const WEB = path.join(ROOT, 'web');
const read = (p) => readFileSync(path.join(WEB, p), 'utf8');

const results = [];
const ok = (name, cond, note = '') => results.push({ name, ok: !!cond, note });

function makeDom({ searchDelayMs = 0, searchResponse = 'results', healthWarm = true }) {
  const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="root"></div></body></html>`, {
    url: 'http://localhost/app/search.html', runScripts: 'outside-only', pretendToBeVisual: true,
  });
  const { window } = dom;
  window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
  window.cancelAnimationFrame = (id) => clearTimeout(id);
  window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });

  window.fetch = (url, opts) => {
    const u = String(url);
    if (u.includes('/health')) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ status: 'ok', tools: 12, warm: healthWarm }) });
    if (u.includes('/api/search')) {
      return new Promise((resolve) => {
        setTimeout(() => {
          if (searchResponse === '429') return resolve({ ok: false, status: 429, headers: { get: (h) => h === 'Retry-After' ? '3' : null }, json: () => Promise.resolve({}) });
          if (searchResponse === 'degraded') return resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ results: [{ id:'d1', title:'Degraded result', authors:['X'], year:2024, source:'J', volume:'1', issue:'1', doi:'10.0/d', cited_by:1, type:'article', abstract:'a', tldr:'t' }], notes: [], meta: { count: 1 }, degraded: true, degraded_shards: 2 }) });
          resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({ results: [{ id:'L1', title:'Live result one', authors:['A. One'], year:2024, source:'Nature', volume:'1', issue:'1', doi:'10.0/x', cited_by:5, type:'article', abstract:'abs', tldr:'tldr' }], notes: [], meta: { count: 1 } }) });
        }, searchDelayMs);
      });
    }
    return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({}) });
  };

  const errors = [];
  window.console.error = (...a) => { errors.push(a.map(String).join(' ')); };
  window.addEventListener('error', (e) => { errors.push('windowerror: ' + (e.error ? e.error.stack : e.message)); });

  const styleEl = window.document.createElement('style');
  styleEl.textContent = read('search.html').match(/<style>([\s\S]*?)<\/style>/)[1] + '\n' + read('lib/base.css');
  window.document.head.appendChild(styleEl);

  const evalIn = (src, label) => { try { window.eval(src); } catch (e) { errors.push(`EVAL ${label}: ${e.message}`); throw e; } };
  evalIn(read('vendor/react.production.min.js'), 'react');
  evalIn(read('vendor/react-dom.production.min.js'), 'react-dom');
  evalIn(read('lib/mock.js'), 'mock.js');
  evalIn(read('lib/api.js'), 'api.js');
  evalIn(read('lib/ui.js'), 'ui.js');
  evalIn(read('lib/interface_prefs.js'), 'interface_prefs.js');
  return { dom, window, errors, evalIn };
}

function reactType(window, inp, text) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(inp, text);
  inp.dispatchEvent(new window.Event('input', { bubbles: true }));
}

async function typeAndSearch(window, text) {
  const inp = window.document.querySelector('input');
  reactType(window, inp, text);
  inp.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

{
  const { window, errors } = makeDom({ searchDelayMs: 0 });
  window.eval(read('search.js'));
  await sleep(60);
  ok('default-bare: search box present on landing', !!window.document.querySelector('input'));
  ok('default-bare: no result cards before search', window.document.querySelectorAll('h3').length === 0, `${window.document.querySelectorAll('h3').length} h3`);
  ok('default-bare: 0 console errors', errors.filter(e => !/favicon/i.test(e)).length === 0, errors.slice(0,2).join('||'));
}

{
  const { window } = makeDom({});
  window.eval(read('search.js'));
  await sleep(60);
  const selectsBefore = window.document.querySelectorAll('select').length;
  const filtersBtn = Array.from(window.document.querySelectorAll('button')).find(b => /Filters/i.test(b.textContent));
  if (filtersBtn) filtersBtn.click();
  await sleep(30);
  const selectsAfter = window.document.querySelectorAll('select').length;
  ok('filters collapsed by default (no selects)', selectsBefore === 0, `${selectsBefore} selects`);
  ok('filters expander opens selects', selectsAfter >= 3, `${selectsAfter} selects after click`);
}

{
  const { window, errors } = makeDom({ searchDelayMs: 120 });
  window.eval(read('search.js'));
  await sleep(60);
  await typeAndSearch(window, 'fast query');
  await sleep(60);
  const skel = window.document.querySelectorAll('[data-skeleton-card]').length;
  ok('skeleton absent <300ms (fast search)', skel === 0, `${skel} skeleton cards`);
  await sleep(200);
  const h3 = window.document.querySelectorAll('h3').length;
  ok('fast search renders result cards', h3 > 0, `${h3} h3`);
  ok('fast-search pass: 0 console errors', errors.filter(e => !/favicon/i.test(e)).length === 0, errors.slice(0,2).join('||'));
}

{
  const { window, errors } = makeDom({ searchDelayMs: 700 });
  window.eval(read('search.js'));
  await sleep(60);
  await typeAndSearch(window, 'slow query');
  await sleep(380);
  const skel = window.document.querySelectorAll('[data-skeleton-card]').length;
  ok('skeleton appears ≥300ms (slow search)', skel >= 3, `${skel} skeleton cards`);
  const wBefore = window.document.querySelector('main')?.getBoundingClientRect().width ?? -1;
  await sleep(500);
  const wAfter = window.document.querySelector('main')?.getBoundingClientRect().width ?? -1;
  ok('no layout shift skeleton→results', Math.abs(wBefore - wAfter) <= 1, `${wBefore}px→${wAfter}px`);
  ok('slow-search pass: 0 console errors', errors.filter(e => !/favicon/i.test(e)).length === 0, errors.slice(0,2).join('||'));
}

{
  const { window, errors } = makeDom({ searchResponse: '429' });
  window.eval(read('search.js'));
  await sleep(60);
  await typeAndSearch(window, 'overload query');
  await sleep(300);
  const countdown = (window.document.body.textContent.match(/retrying in/i) || []).length;
  ok('429 → determinate countdown shown', countdown > 0, `matches=${countdown}`);
  ok('429 pass: 0 console errors', errors.filter(e => !/favicon/i.test(e)).length === 0, errors.slice(0,2).join('||'));
}

{
  const { window, errors } = makeDom({ searchResponse: 'degraded' });
  window.eval(read('search.js'));
  await sleep(60);
  await typeAndSearch(window, 'degraded query');
  await sleep(400);
  const notice = (window.document.body.textContent.match(/Degraded/i) || []).length;
  ok('degraded → one-line notice shown', notice > 0, `matches=${notice}`);
  ok('degraded pass: 0 console errors', errors.filter(e => !/favicon/i.test(e)).length === 0, errors.slice(0,2).join('||'));
}

{
  const blank = new JSDOM('<!DOCTYPE html><html><body></body></html>', { url: 'http://localhost/app/search.html', runScripts: 'outside-only', pretendToBeVisual: true });
  const store = blank.window.localStorage;
  const mk = (searchResponse) => {
    const dom = new JSDOM(`<!DOCTYPE html><html><body><div id="root"></div></body></html>`, { url: 'http://localhost/app/search.html', runScripts: 'outside-only', pretendToBeVisual: true });
    dom.window.requestAnimationFrame = (cb) => setTimeout(() => cb(Date.now()), 0);
    Object.defineProperty(dom.window, 'localStorage', { value: store, configurable: true });
    dom.window.matchMedia = () => ({ matches: false, addListener(){}, removeListener(){}, addEventListener(){}, removeEventListener(){} });
    dom.window.fetch = (url) => {
      const u = String(url);
      if (u.includes('/health')) return Promise.resolve({ ok:true, status:200, headers:{get:()=>null}, json:()=>Promise.resolve({status:'ok',tools:12,warm:true}) });
      if (u.includes('/api/search')) return Promise.resolve({ ok:true, status:200, headers:{get:()=>null}, json:()=>Promise.resolve({ results:[{id:'L1',title:'Live r',authors:['A'],year:2024,source:'N',volume:'1',issue:'1',doi:'10.0/x',cited_by:1,type:'article',abstract:'a',tldr:'t'}], notes:[], meta:{count:1} }) });
      return Promise.resolve({ ok:true, status:200, headers:{get:()=>null}, json:()=>Promise.resolve({}) });
    };
    const errors = [];
    dom.window.console.error = (...a) => errors.push(a.map(String).join(' '));
    dom.window.addEventListener('error', e => errors.push('windowerror: ' + (e.error?e.error.stack:e.message)));
    const evalIn = (src,l) => { try { dom.window.eval(src); } catch(e){ errors.push(`EVAL ${l}: ${e.message}`); throw e; } };
    evalIn(read('vendor/react.production.min.js'),'react');
    evalIn(read('vendor/react-dom.production.min.js'),'react-dom');
    evalIn(read('lib/mock.js'),'mock');
    evalIn(read('lib/api.js'),'api');
    evalIn(read('lib/ui.js'),'ui');
    evalIn(read('lib/interface_prefs.js'),'prefs');
    return { dom, window: dom.window, errors };
  };

  const { window: w1 } = mk();
  w1.eval(read('search.js'));
  await sleep(80);
  const savedNavBtn = (win) => Array.from(win.document.querySelectorAll('aside nav button'))
    .some(b => b.textContent.replace(/\s+/g, ' ').trim() === 'Saved');
  const savedBefore = savedNavBtn(w1);
  ok('default ON: Saved nav present', savedBefore, `Saved nav present=${savedBefore}`);

  w1.SFUUI.writeInterfacePrefs({ advancedFiltersOpen: false, savedHistoryNav: false, databasesTab: false, analyticsApp: false, indexManagerApp: false, adminPanels: false, density: 'comfortable' });
  await sleep(50);

  const { window: w2 } = mk();
  w2.eval(read('search.js'));
  await sleep(90);
  const savedAfter = savedNavBtn(w2);
  ok('toggle OFF persists across reload → Saved nav hidden', !savedAfter, `Saved nav present=${savedAfter}`);

  const keys = Object.keys(w2.SFUUI.INTERFACE_PREF_DEFAULTS);
  ok('integrity floor: no banner/degraded/pill toggle keys', !keys.includes('demoBanner') && !keys.includes('degradedNotice') && !keys.includes('backendPill'), keys.join(','));
}

console.log('\n================ §1/§2 progress sweep (jsdom) ================');
let pass = 0, fail = 0;
for (const r of results) { if (r.ok) pass++; else fail++; console.log(`  [${r.ok?'PASS':'FAIL'}] ${r.name.padEnd(46)} ${r.note}`); }
console.log(`\n${pass} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
