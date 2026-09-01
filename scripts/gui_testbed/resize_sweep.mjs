import { loadPlaywright, makeLog, arm, check, captureArtifacts, openApp, sleep, mockApi, overflow, BASE, DATE_TAG, ROOT } from './lib.mjs';
import fs from 'node:fs';
import path from 'node:path';

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const t0 = Date.now();
const log = makeLog('L-D resize_sweep');
log.act(`resize_sweep start @ ${BASE} (date ${DATE_TAG})`);

let actions = 0, widths = 0, zooms = 0, dprs = 0;
let midSkeletonNoShift = false;

{
  const { page, context } = await openApp({
    chromium: browser, app: 'search.html', log, ctxLabel: 'resize:width-sweep',
    setup: async (p) => { await mockApi(p, 'live'); },
    viewport: { width: 1280, height: 900 },
  });
  try {
    for (let w = 320; w <= 1920; w += 16) {
      await page.setViewportSize({ width: w, height: 900 });
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
      await check(page, log, `width=${w}`);
      actions++; widths++;
    }
    log.act(`width sweep 320→1920 done (${widths} steps)`);
  } finally {
    await captureArtifacts(page, context, log, 'resize_width_sweep');
    await context.close();
  }
}

{
  const { page, context } = await openApp({
    chromium: browser, app: 'search.html', log, ctxLabel: 'resize:zoom-sweep',
    setup: async (p) => { await mockApi(p, 'live'); },
  });
  try {
    for (const z of [0.5, 0.75, 1, 1.5, 2]) {
      await page.evaluate(zv => { document.documentElement.style.fontSize = `${16 * zv}px`; }, z);
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
      await sleep(60);
      await check(page, log, `zoom=${z}`);
      actions++; zooms++;
    }
    log.act(`zoom sweep 0.5→2 done (${zooms} steps)`);
  } finally {
    await captureArtifacts(page, context, log, 'resize_zoom_sweep');
    await context.close();
  }
}

for (const dpr of [1, 2, 3]) {
  const { page, context } = await openApp({
    chromium: browser, app: 'search.html', log, ctxLabel: `resize:dpr=${dpr}`,
    setup: async (p) => { await mockApi(p, 'live'); },
    deviceScaleFactor: dpr,
  });
  try {
    for (const s of ['Settings', 'Saved', 'History', 'Databases', 'Admin', 'Search']) {
      await page.getByText(s, { exact: true }).first().click({ timeout: 3000 }).catch(() => {});
      await sleep(80);
      await check(page, log, `dpr=${dpr} screen=${s}`);
      actions++;
    }
    dprs++;
  } finally {
    await captureArtifacts(page, context, log, `resize_dpr${dpr}`);
    await context.close();
  }
}

{
  const { page, context } = await openApp({
    chromium: browser, app: 'search.html', log, ctxLabel: 'resize:mid-skeleton',
    setup: async (p) => { await mockApi(p, 'live', { searchDelayMs: 700 }); },
    viewport: { width: 1280, height: 900 },
  });
  let noShift = true;
  try {
    const inp = page.locator('input').first();
    await inp.fill('graph neural networks');
    await inp.press('Enter');
    await sleep(330);
    const skel = await page.locator('[data-skeleton-card]').count();
    log.act(`mid-skeleton: ${skel} skeleton cards showing during resize`);
    const w1 = await page.evaluate(() => { const m = document.querySelector('main'); return m ? m.getBoundingClientRect().width : -1; });
    for (const w of [900, 1100, 1400, 760, 1280]) {
      await page.setViewportSize({ width: w, height: 900 });
      await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
      await check(page, log, `mid-skeleton resize w=${w}`);
      actions++;
    }
    await sleep(500);
    const w2 = await page.evaluate(() => { const m = document.querySelector('main'); return m ? m.getBoundingClientRect().width : -1; });
    const ov = await overflow(page);
    const frozen = await page.locator('[data-skeleton-card]').count();
    if (ov > 4 || frozen > 0) { noShift = false; log.fail('mid-skeleton-shift', `ov=${ov}px frozen_skel=${frozen} w1=${w1} w2=${w2}`); }
    log.act(`mid-skeleton result: ov=${ov}px frozen_skel=${frozen} w1=${w1}→w2=${w2}`);
  } catch (e) {
    log.fatal('mid-skeleton-threw', String(e).slice(0, 180));
    noShift = false;
  } finally {
    await captureArtifacts(page, context, log, 'resize_mid_skeleton');
    await context.close();
  }
  midSkeletonNoShift = noShift;
}

await browser.close();
const wall = Date.now() - t0;

const verdict = {
  layer: 'L-D resize_sweep', date: DATE_TAG, wall_ms: wall,
  summary: { actions, widths, zooms, dprs, failures: log.failures.length, warnings: log.warnings.length },
  mid_skeleton_no_shift: midSkeletonNoShift,
  failures: log.failures,
  warnings: log.warnings,
  bars: {
    zero_pageerror: !log.failures.some(f => f.kind.startsWith('fatal:pageerror')),
    zero_console_error: !log.failures.some(f => f.kind === 'console.error'),
    zero_overflow: !log.failures.some(f => f.kind === 'overflow'),
    mid_skeleton_no_shift: midSkeletonNoShift,
  },
};
const OUT = path.join(ROOT, 'data', 'eval_results', `gui_testbed_ld_resize_${DATE_TAG}.json`);
fs.writeFileSync(OUT, JSON.stringify(verdict, null, 2));
console.log(JSON.stringify({ layer: verdict.layer, ...verdict.summary, bars: verdict.bars, out: path.relative(process.cwd(), OUT) }, null, 2));
