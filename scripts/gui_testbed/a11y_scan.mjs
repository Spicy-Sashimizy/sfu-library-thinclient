// L-F (stretch, WI-16f) — vendored axe-core a11y scan per screen, as an
// invariant-oracle EXTENSION (not a gate layer; the plan §2 oracle is the
// gate; this records a11y violations honestly for future remediation).
//
// axe-core 4.10.1 vendored (sha256
// 3815dfdf753d9fea828f4988f4c2e4895c82d670b369b0e79a8a63caebf5819e), same
// no-CDN rule as gremlins + React. Run per screen (search/analytics/
// index_manager, + the search sub-screens saved/history/databases/settings/
// admin where reachable); record every violation: id, impact, count, node
// selectors + a snippet. Fix NOTHING outside web/ defect rules — this is
// measurement only (the drive-prompt WI-16f rule).
import { loadPlaywright, makeLog, arm, check, mockApi, openApp, sleep, BASE, DATE_TAG, ROOT, TESTBED } from './lib.mjs';
import fs from 'node:fs';
import path from 'node:path';

const AXE = path.join(TESTBED, 'vendor', 'axe.min.js');
const APPS = ['search.html', 'analytics.html', 'index_manager.html'];

// Sub-screens to walk on the search app (the ones reachable by default or via
// a single toggle). Each is a distinct a11y context.
const SEARCH_SCREENS = [
  { name: 'landing',    go: async p => {} }, // default
  { name: 'settings',   go: async p => { await p.locator('aside button', { hasText: 'Settings' }).first().click({ timeout: 3000 }).catch(() => {}); await sleep(200); } },
  { name: 'interface',  go: async p => { await p.locator('aside button', { hasText: 'Settings' }).first().click({ timeout: 3000 }).catch(() => {}); await sleep(150); await p.getByText('Interface', { exact: false }).first().click({ timeout: 3000 }).catch(() => {}); await sleep(200); } },
];

async function scanPage(page, context, label) {
  await page.addScriptTag({ path: AXE }).catch(() => {});
  const res = await page.evaluate(() => {
    if (!window.axe || !window.axe.run) return { error: 'axe not loaded' };
    return window.axe.run({ runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] } });
  }).catch(e => ({ error: String(e).slice(0, 120) }));
  if (res.error) return { label, error: res.error };
  return {
    label,
    passes: res.passes ? res.passes.length : 0,
    incomplete: res.incomplete ? res.incomplete.length : 0,
    inapplicable: res.inapplicable ? res.inapplicable.length : 0,
    violations: (res.violations || []).map(v => ({
      id: v.id, impact: v.impact, count: (v.nodes || []).length,
      help: (v.help || '').slice(0, 80),
      tags: (v.tags || []).filter(t => /^wcag/.test(t)),
      nodes: (v.nodes || []).slice(0, 5).map(n => ({
        target: Array.isArray(n.target) ? n.target[0] : n.target,
        html: (n.html || '').slice(0, 120),
        failureSummary: (n.failureSummary || '').slice(0, 100),
      })),
    })),
  };
}

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const t0 = Date.now();
const log = makeLog('L-F a11y_scan');
log.act(`a11y_scan start @ ${BASE} (date ${DATE_TAG}) — axe-core 4.10.1`);

const perScreen = [];

for (const app of APPS) {
  const { page, context } = await openApp({
    chromium: browser, app, log, ctxLabel: `a11y:${app}`,
    setup: async (p) => { await mockApi(p, 'live'); },
  });
  // 1. landing scan
  perScreen.push(await scanPage(page, context, `${app}:landing`));
  log.act(`${app} landing: ${perScreen[perScreen.length-1].violations?.length ?? 0} violations`);
  // 2. search sub-screens (only for search.html — analytics/index_manager are single-screen-ish)
  if (app === 'search.html') {
    for (const s of SEARCH_SCREENS.slice(1)) {
      await s.go(page);
      await check(page, log, `a11y ${app} ${s.name}`);
      const r = await scanPage(page, context, `${app}:${s.name}`);
      perScreen.push(r);
      log.act(`${app} ${s.name}: ${r.violations?.length ?? 0} violations`);
    }
  }
  await context.close();
}

await browser.close();
const wall = Date.now() - t0;

// Roll up violations across screens.
const allVios = [];
for (const s of perScreen) if (s.violations) for (const v of s.violations) allVios.push({ screen: s.label, ...v });
const byImpact = { critical: 0, serious: 0, moderate: 0, minor: 0 };
allVios.forEach(v => { if (byImpact[v.impact] !== undefined) byImpact[v.impact] += v.count; });
const byRule = {};
allVios.forEach(v => { byRule[v.id] = (byRule[v.id] || 0) + v.count; });

const verdict = {
  layer: 'L-F a11y_scan (stretch)', date: DATE_TAG, wall_ms: wall,
  tool: 'axe-core 4.10.1 (vendored, sha256 3815dfdf753d9fea828f4988f4c2e4895c82d670b369b0e79a8a63caebf5819e)',
  summary: {
    screens_scanned: perScreen.length,
    total_violations: allVios.reduce((a, v) => a + v.count, 0),
    distinct_rules: Object.keys(byRule).length,
    by_impact: byImpact,
  },
  violations_by_rule: byRule,
  per_screen: perScreen,
  note: 'measurement only — NOT a gate layer; the plan §2 invariant oracle is the gate. Fix nothing outside web/ defect rules (drive-prompt WI-16f). Violations recorded for future remediation.',
};
const OUT = path.join(ROOT, 'data', 'eval_results', `gui_testbed_lf_a11y_${DATE_TAG}.json`);
fs.writeFileSync(OUT, JSON.stringify(verdict, null, 2));
console.log(JSON.stringify({ layer: verdict.layer, ...verdict.summary, violations_by_rule: byRule, out: path.relative(process.cwd(), OUT) }, null, 2));
