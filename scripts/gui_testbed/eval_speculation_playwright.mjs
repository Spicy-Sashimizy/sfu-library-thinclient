import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadPlaywright, openApp, mockApi } from './lib.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

const results = [];
function record(ctx, ok, detail) { results.push({ ctx, ok, detail }); }

const QUERIES = [
  'machine learning for drug discovery',
  'climate change adaptation policy',
  'crispr gene editing salmon',
  'quantum computing error correction',
  'reinforcement learning robotics',
];

try {
  const { chromium } = await loadPlaywright();
  const specCalls = [];
  const searchCalls = [];
  for (let i = 0; i < QUERIES.length; i++) {
    const q = QUERIES[i];
    const { page, context } = await openApp({
      chromium, app: 'search.html',
      viewport: { width: 1440, height: 900 }, waitMount: true,
    });
    await page.route('**/health', (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', tools: 27, warm: true, warmup: 'warm' }),
    }));
    await page.route('**/api/speculate', (route) => {
      const req = route.request();
      let body = {};
      try { body = JSON.parse(req.postData() || '{}'); } catch {}
      specCalls.push({ query: body.query, t: Date.now() });
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ status: 'fired', mode: 'predicted',
          predicted: body.query }) });
    });
    await page.route('**/api/search', (route) => {
      searchCalls.push({ t: Date.now() });
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ results: [
          { id: 'R1', title: 'Result for ' + q, authors: ['A'], year: 2024,
            source: 'Nature', doi: '10.0/x', cited_by: 3, type: 'article',
            abstract: 'a', tldr: 't' }],
          notes: [], meta: { count: 1 } }) });
    });

    const input = await page.locator('input').first();
    await input.click();
    const interKey = 120;
    for (const ch of q) {
      await input.press(ch);
      await page.waitForTimeout(interKey + Math.floor(Math.random() * 40));
    }
    await page.waitForTimeout(500);
    const specCallsBeforeEnter = specCalls.length;
    await input.press('Enter');
    await page.waitForTimeout(300);

    const cards = await page.locator('h3').count();
    record(`trial ${i + 1}: speculate fired during typing`,
      specCalls.length > 0, `specCalls=${specCalls.length} (last="${specCalls[specCalls.length - 1]?.query || ''}")`);
    record(`trial ${i + 1}: results rendered after Enter`, cards > 0, `h3 count=${cards}`);
    record(`trial ${i + 1}: no speculate fired AFTER Enter (cancel-on-submit)`,
      specCalls.length === specCallsBeforeEnter,
      `before=${specCallsBeforeEnter} after=${specCalls.length}`);
    await context.close();
  }
  const allFired = results.filter(r => r.ctx.includes('speculate fired') && r.ok).length;
  const allRendered = results.filter(r => r.ctx.includes('results rendered') && r.ok).length;
  record('SUMMARY: speculate fired in ≥1 trial', allFired >= 1, `${allFired}/${QUERIES.length} fired`);
  record('SUMMARY: results rendered in all trials', allRendered === QUERIES.length, `${allRendered}/${QUERIES.length}`);
} catch (e) {
  record('Playwright speculation proof — threw', false, String(e).slice(0, 300));
  console.error(e);
}

console.log('\n======== speculation Playwright wiring proof ========');
let pass = 0, fail = 0;
for (const r of results) {
  const tag = r.ok ? 'PASS' : 'FAIL';
  if (r.ok) pass++; else fail++;
  console.log(`  [${tag}] ${r.ctx.padEnd(54)} ${r.detail}`);
}
console.log(`\n${pass} pass / ${fail} fail`);
process.exit(fail ? 1 : 0);
