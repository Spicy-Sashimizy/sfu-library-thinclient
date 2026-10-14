import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const TESTBED = path.join(ROOT, 'scripts', 'gui_testbed');
export const PWPATH = process.env.PW ? `${process.env.PW}/playwright/index.js` : 'playwright';

export const BASE = process.env.GUITB_BASE || 'http://127.0.0.1:8080';
export const DATE_TAG = '2026-07-17';
export const ARTIFACT_DIR = path.join(ROOT, 'data', 'eval_results', 'gui_testbed_artifacts', DATE_TAG);

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export async function loadPlaywright() {
  const _pw = await import(PWPATH);
  const chromium = _pw.chromium || (_pw.default && _pw.default.chromium);
  if (!chromium) throw new Error(`chromium not resolved from PW=${PWPATH}`);
  return { chromium };
}

export const sleep = ms => new Promise(r => setTimeout(r, ms));

export function makeLog(layer) {
  const failures = [];
  const warnings = [];
  const actions = [];
  const fail  = (kind, detail) => failures.push({ kind, detail, t: Date.now() });
  const fatal = (kind, detail) => failures.push({ kind: 'fatal:' + kind, detail, t: Date.now() });
  const warn = (kind, detail) => warnings.push({ kind, detail, t: Date.now() });
  const act  = (s) => actions.push(`${new Date().toISOString().slice(11, 23)} ${s}`);
  return { layer, failures, warnings, actions, fail, fatal, warn, act };
}

export function arm(page, log, ctxFn) {
  page.on('pageerror', e => log.fatal('pageerror', `${ctxFn()} :: ${String(e && e.message || e).slice(0, 240)}`));
  page.on('console', m => {
    if (m.type() === 'error') log.fail('console.error', `${ctxFn()} :: ${m.text().slice(0, 240)}`);
  });
}

export async function overflow(page) {
  return page.evaluate(() => {
    const de = document.documentElement;
    const xs = [de.scrollWidth - de.clientWidth];
    document.querySelectorAll('main,aside,[data-screen-label],[role="main"]').forEach(el => {
      if (el.scrollWidth - el.clientWidth > 2) xs.push(el.scrollWidth - el.clientWidth);
    });
    return Math.max(0, ...xs);
  });
}

export async function isMockShown(page) {
  return page.evaluate(() => !!document.getElementById('sfu-demo-pill'));
}

export async function startTrace(context, name) {
  try { await context.tracing.start({ screenshots: true, snapshots: true, sources: true }); } catch {}
  return name;
}

export async function captureArtifacts(page, context, log, label) {
  const crash = log.failures.some(f =>
    f.kind.startsWith('fatal:') || f.kind === 'pageerror' || f.kind.includes('wedged') || f.kind.includes('threw'));
  if (!crash) {
    try { await context.tracing.stop(); } catch {}
    return null;
  }
  if (!fs.existsSync(ARTIFACT_DIR)) fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
  const stamp = label.replace(/[^a-z0-9_-]+/gi, '_').slice(0, 80);
  const png = path.join(ARTIFACT_DIR, `${stamp}.png`);
  const zip = path.join(ARTIFACT_DIR, `${stamp}.trace.zip`);
  try { await page.screenshot({ path: png, fullPage: true }); } catch {}
  try { await context.tracing.stop({ path: zip }); } catch {}
  return { screenshot: path.relative(ROOT, png), trace: path.relative(ROOT, zip), failures: log.failures.length };
}

export async function check(page, log, ctx) {
  const over = await overflow(page);
  if (over > 4) log.fail('overflow', `${over}px at ${ctx}`);
  await page.evaluate(() => 1, { timeout: 2000 }).catch(() => log.fatal('wedged', ctx));
  const mock = await isMockShown(page);
  if (mock) {
    const visible = await page.locator('#sfu-demo-pill').isVisible().catch(() => false);
    if (!visible) log.fail('honesty', `mock data shown but demo pill hidden at ${ctx}`);
  }
  return over;
}

export async function openApp({ chromium, app = 'search.html', viewport = { width: 1440, height: 900 }, deviceScaleFactor = 1, log, ctxLabel, setup, waitMount = true }) {
  const context = await chromium.newContext({ viewport, deviceScaleFactor });
  await startTrace(context, ctxLabel);
  const page = await context.newPage();
  arm(page, log, () => ctxLabel);
  try {
    if (setup) await setup(page, context);
    await page.goto(`${BASE}/app/${app}`, { waitUntil: 'load', timeout: 30000 });
    if (waitMount) {
      await page.waitForFunction(() => document.getElementById('root') && document.getElementById('root').childNodes.length > 0, { timeout: 15000 }).catch(() => {});
    }
    await sleep(300);
  } catch (e) {
    log.fatal('goto', `${ctxLabel} :: ${String(e).slice(0, 180)}`);
  }
  return { context, page };
}

export async function mockApi(page, mode = 'live', opts = {}) {
  const delay = opts.searchDelayMs || 0;
  if (mode === 'backend-dead') {
    await page.route('**/health', r => r.abort());
    await page.route('**/api/**', r => r.abort());
    await page.route('**/analytics', r => r.abort());
    return;
  }
  await page.route('**/health', r => r.fulfill({ json: { status: 'ok', tools: 12, warm: true } }));
  await page.route('**/api/unpack', r => r.fulfill({ json: { ok: true, message: 'queued (mock)' } }));
  await page.route('**/analytics', r => r.fulfill({ json: { panels: {} } }));
  await page.route('**/api/search', async r => {
    if (mode === 'hang') { await sleep(opts.hangMs || 15000); }
    if (mode === '429') return r.fulfill({ status: 429, headers: { 'Retry-After': '3' }, json: {} });
    if (delay) await sleep(delay);
    return r.fulfill({ json: { results: [{ id: 'R1', title: 'Result one', authors: ['A. One'], year: 2024, source: 'Nature', volume: '1', issue: '1', doi: '10.0/x', cited_by: 5, type: 'article', abstract: 'abs', tldr: 'tldr' }], notes: [], meta: { count: 1 } } });
  });
}

export function storageCorruptScript() {
  return `
    (function () {
      try {
        var k = 'sfu-interface-prefs';
        // 1. truncated JSON (unclosed)
        localStorage.setItem(k, '{"advancedFiltersOpen":tru');
        // 2. wrong types (number where bool expected, object for string)
        localStorage.setItem('sfu-interface-prefs-wrongtypes', '{"savedHistoryNav":42,"density":[]}');
        // 3. 1 MB string blob in the prefs key (extreme)
        localStorage.setItem(k + '-blob', '{"density":"' + 'x'.repeat(1048576) + '"}');
        // 4. the actual prefs key with 1MB value (the danger case)
        localStorage.setItem(k, '{"density":"' + 'y'.repeat(500000) + '"');
      } catch (e) {}
    })();
  `;
}
