import { loadPlaywright, makeLog, arm, check, captureArtifacts, openApp, sleep, mockApi, BASE, DATE_TAG, ROOT } from './lib.mjs';
import fs from 'node:fs';
import path from 'node:path';

const APPS = ['search.html', 'analytics.html', 'index_manager.html'];
const MAX_DEPTH = 4;
const CLICK_TIMEOUT = 3500;

const INTERACTIVE = 'button, a[href], input, select, textarea, [role="button"], [role="switch"], [role="tab"], [role="checkbox"], [tabindex]:not([tabindex="-1"])';

function describe(el) {
  return (el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText ||
          el.getAttribute('placeholder') || el.tagName + (el.id ? '#' + el.id : '') || '').trim().slice(0, 48);
}

async function snapInteractives(page) {
  return page.locator(INTERACTIVE).count();
}

async function enumApp({ browser, app, log }) {
  let actions = 0, states = 0, skipped = 0;
  const { page, context } = await openApp({
    chromium: browser, app, log, ctxLabel: `enum:${app}`,
    setup: async (page) => { await mockApi(page, 'live'); },
  });
  try {
    let beforeN = await snapInteractives(page);
    const visited = new Set();
    let worklist = [{ depth: 0 }];
    let guard = 0;
    while (worklist.length && guard++ < 220) {
      const { depth } = worklist.shift();
      const els = page.locator(INTERACTIVE);
      const n = await els.count();
      for (let i = 0; i < n; i++) {
        const el = els.nth(i);
        let visible = false;
        try { visible = await el.isVisible(); } catch { visible = false; }
        if (!visible) { skipped++; continue; }
        const desc = await el.evaluate(describe).catch(() => '<desc-fail>');
        const key = `${depth}:${i}:${desc}`;
        if (visited.has(key)) continue;
        visited.add(key);
        const href = await el.getAttribute('href').catch(() => null);
        if (href && /\.html/.test(href)) continue;
        const ctx = `${app} d${depth} #${i} "${desc}"`;
        try {
          await el.scrollIntoViewIfNeeded({ timeout: 1500 }).catch(() => {});
          await el.click({ trial: false, timeout: CLICK_TIMEOUT });
          log.act(`click OK  ${ctx}`);
        } catch (e) {
          log.warn('unclickable', `${ctx} :: ${String(e).slice(0, 80)}`);
          skipped++;
        }
        actions++;
        await sleep(60);
        await check(page, log, ctx);
        const afterN = await snapInteractives(page);
        states++;
        if (afterN > beforeN + 1 && depth < MAX_DEPTH) worklist.push({ depth: depth + 1 });
        beforeN = afterN;
      }
    }

    log.act(`keyboard pass start (${app})`);
    for (let t = 0; t < 40; t++) {
      await page.keyboard.press('Tab');
      const ctx = `${app} tab#${t}`;
      await check(page, log, ctx);
      if (t % 7 === 0) { await page.keyboard.press('Enter'); await check(page, log, ctx + ' Enter'); }
    }

    const inputs = page.locator('input:not([type="checkbox"]):not([type="radio"]):not([type="file"]), textarea');
    const inN = await inputs.count();
    const GARBAGE = [
      { label: 'unicode', val: '搜索 αβγ 中文 日本語 ΔΛΨ' },
      { label: 'xss-probe', val: '<script>alert(1)</script>' },
      { label: 'rtl', val: 'مرحبا بالعالم هذا اختبار' },
      { label: 'long-10kb', val: 'x'.repeat(10240) },
      { label: 'sql-probe', val: "'; DROP TABLE; --" },
    ];
    for (let i = 0; i < Math.min(inN, 8); i++) {
      const g = GARBAGE[i % GARBAGE.length];
      const el = inputs.nth(i);
      try { if (!await el.isVisible()) continue; await el.fill(g.val, { timeout: 2000 }); }
      catch (e) { log.warn('fill-fail', `${app} input#${i} ${g.label}`); continue; }
      log.act(`fill    ${app} input#${i} ${g.label} (${g.val.length}ch)`);
      actions++;
      await check(page, log, `${app} input#${i} ${g.label}`);
      await el.press('Escape').catch(() => {});
    }
  } finally {
    const art = await captureArtifacts(page, context, log, `enum_${app}`);
    await context.close();
    return { actions, states, skipped, artifacts: art };
  }
}

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const t0 = Date.now();
const log = makeLog('L-A enum_sweep');
log.act(`enum_sweep start @ ${BASE} (date ${DATE_TAG})`);

const perApp = {};
for (const app of APPS) {
  log.act(`=== enum ${app} ===`);
  perApp[app] = await enumApp({ browser, app, log });
}
await browser.close();
const wall = Date.now() - t0;

const verdict = {
  layer: 'L-A enum_sweep', date: DATE_TAG, wall_ms: wall,
  apps: APPS,
  summary: {
    actions: Object.values(perApp).reduce((a, r) => a + r.actions, 0),
    states: Object.values(perApp).reduce((a, r) => a + r.states, 0),
    skipped: Object.values(perApp).reduce((a, r) => a + r.skipped, 0),
    failures: log.failures.length,
    warnings: log.warnings.length,
  },
  per_app: perApp,
  failures: log.failures,
  warnings: log.warnings,
  bars: {
    zero_pageerror: !log.failures.some(f => f.kind.startsWith('fatal:pageerror')),
    zero_console_error: !log.failures.some(f => f.kind === 'console.error'),
    zero_overflow: !log.failures.some(f => f.kind === 'overflow'),
  },
};

const OUT = path.join(ROOT, 'data', 'eval_results', `gui_testbed_la_enum_${DATE_TAG}.json`);
fs.writeFileSync(OUT, JSON.stringify(verdict, null, 2));
console.log(JSON.stringify({ layer: verdict.layer, ...verdict.summary, bars: verdict.bars, out: path.relative(process.cwd(), OUT) }, null, 2));
