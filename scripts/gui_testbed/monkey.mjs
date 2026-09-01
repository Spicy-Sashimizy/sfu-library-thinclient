import { loadPlaywright, makeLog, arm, check, captureArtifacts, openApp, sleep, mockApi, storageCorruptScript, BASE, DATE_TAG, ROOT, TESTBED, mulberry32 } from './lib.mjs';
import fs from 'node:fs';
import path from 'node:path';

const GREMLINS = path.join(TESTBED, 'vendor', 'gremlins.min.js');
const N_SEEDS = parseInt(process.env.GUITB_SEEDS || '10', 10);
const ATTACK_MS = parseInt(process.env.GUITB_ATTACK_MS || '6000', 10);
const MODES = ['no-chaos', 'backend-dead', 'hang', '429-storm', 'storage-corrupt'];
const SEEDS = Array.from({ length: N_SEEDS }, (_, i) => 1000 + i);

const REGRESSION_FILE = path.join(TESTBED, 'regression_seeds.json');

async function runOnce({ browser, seed, mode, log }) {
  const ctxLabel = `monkey seed=${seed} ${mode}`;
  const corrupt = mode === 'storage-corrupt';
  const apiMode = mode === '429-storm' ? '429' : mode === 'backend-dead' ? 'backend-dead' : mode === 'hang' ? 'hang' : 'live';

  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  try { await context.tracing.start({ screenshots: true, snapshots: true, sources: true }); } catch {}
  if (corrupt) {
    await context.addInitScript(storageCorruptScript());
  }
  const page = await context.newPage();
  arm(page, log, () => ctxLabel);
  let stopped = false;
  try {
    if (apiMode !== 'backend-dead') await mockApi(page, apiMode);
    else await mockApi(page, 'backend-dead');
    await page.goto(`${BASE}/app/search.html`, { waitUntil: 'load', timeout: 30000 });
    await page.waitForFunction(() => document.getElementById('root') && document.getElementById('root').childNodes.length > 0, { timeout: 15000 }).catch(() => {});
    await sleep(400);
    await check(page, log, `${ctxLabel} boot`);
    await page.addScriptTag({ path: GREMLINS });
    const unleashed = await page.evaluate(async (seed) => {
      const horde = window.gremlins.createHorde({
        randomizer: new window.gremlins.Chance(seed),
        species: [
          window.gremlins.species.clicker(),
          window.gremlins.species.formFiller(),
          window.gremlins.species.scroller(),
          window.gremlins.species.typer(),
        ],
        mogwais: [window.gremlins.mogwais.gizmo({ maxErrors: 1 })],
        strategies: [window.gremlins.strategies.distribution({ delay: 20 })],
      });
      const stop = horde.unleash();
      return true;
    }, seed);
    const ticks = Math.max(1, Math.floor(ATTACK_MS / 1000));
    for (let i = 0; i < ticks; i++) {
      await sleep(1000);
      await check(page, log, `${ctxLabel} tick#${i}`);
      if (log.failures.some(f => f.kind.includes('pageerror') || f.kind.includes('wedged'))) {
        break;
      }
    }
    stopped = true;
  } catch (e) {
    log.fatal('monkey_threw', `${ctxLabel} :: ${String(e).slice(0, 180)}`);
  }
  const art = await captureArtifacts(page, context, log, `monkey_${mode}_seed${seed}`);
  await context.close();
  const pageerrors = log.failures.filter(f => f.kind.startsWith('fatal:pageerror') || f.kind.startsWith('fatal:wedged') || f.kind.startsWith('fatal:monkey'));
  return { seed, mode, pageerrors: pageerrors.length, console_errors: log.failures.filter(f=>f.kind==='console.error').length, overflow: log.failures.filter(f=>f.kind==='overflow').length, passed: pageerrors.length === 0, artifacts: art };
}

async function replayConfirm(browser, seed, mode) {
  const log2 = makeLog('L-C replay');
  const r = await runOnce({ browser, seed, mode, log: log2 });
  return r;
}

const { chromium } = await loadPlaywright();
const browser = await chromium.launch();
const t0 = Date.now();
const log = makeLog('L-C monkey');
log.act(`monkey start @ ${BASE} (date ${DATE_TAG}) — ${N_SEEDS} seeds × ${MODES.length} modes × ${ATTACK_MS}ms`);

let regression = [];
if (fs.existsSync(REGRESSION_FILE)) {
  try { regression = JSON.parse(fs.readFileSync(REGRESSION_FILE, 'utf8')).seeds || []; } catch {}
}
log.act(`regression seeds on file: ${regression.length}`);

let runs = 0, passedRuns = 0, failedRuns = 0;
const failingSeeds = [];
const perRun = [];

for (const rs of regression) {
  const r = await runOnce({ browser, seed: rs.seed, mode: rs.mode, log });
  r.regression = true;
  perRun.push(r); runs++;
  if (r.passed) { r.note = 'regression seed now PASSES (cleared?)'; passedRuns++; }
  else { failedRuns++; failingSeeds.push({ seed: rs.seed, mode: rs.mode, ...r }); }
  log.act(`regression seed=${rs.seed} ${rs.mode} -> ${r.passed ? 'PASS(cleared)' : 'FAIL(confirmed)'}`);
}

for (const seed of SEEDS) {
  for (const mode of MODES) {
    const r = await runOnce({ browser, seed, mode, log });
    perRun.push(r); runs++;
    if (r.passed) passedRuns++;
    else {
      failedRuns++;
      const confirm = await replayConfirm(browser, seed, mode);
      if (!confirm.passed) {
        failingSeeds.push({ seed, mode, first: r, replay: confirm });
        log.act(`RECORDED failing seed=${seed} ${mode} (replay-confirmed)`);
      } else {
        log.fail('flaky', `seed=${seed} ${mode} failed then passed on replay — NOT recorded`);
      }
    }
    log.act(`seed=${seed} ${mode} -> ${r.passed ? 'PASS' : 'FAIL'} (pe=${r.pageerrors} ce=${r.console_errors} ov=${r.overflow})`);
  }
}

await browser.close();
const wall = Date.now() - t0;

const newRegression = failingSeeds.map(f => ({ seed: f.seed, mode: f.mode }));
const allRegression = [...regression, ...newRegression.filter(nr => !regression.some(r => r.seed===nr.seed && r.mode===nr.mode))];
fs.writeFileSync(REGRESSION_FILE, JSON.stringify({ created: DATE_TAG, note: 'replay-confirmed failing seeds; run first, forever', seeds: allRegression }, null, 2));

const verdict = {
  layer: 'L-C monkey', date: DATE_TAG, wall_ms: wall,
  summary: { runs, passed: passedRuns, failed: failedRuns, regression_seeds: allRegression.length, failures: log.failures.length },
  matrix: { seeds: N_SEEDS, modes: MODES, attack_ms: ATTACK_MS },
  per_run: perRun,
  failing_seeds: newRegression,
  regression_file: path.relative(ROOT, REGRESSION_FILE),
  bars: {
    zero_pageerror_across_matrix: failedRuns === 0,
    every_failure_replay_confirmed: failingSeeds.every(f => f.replay && !f.replay.passed),
  },
  failures: log.failures,
};
const OUT = path.join(ROOT, 'data', 'eval_results', `gui_testbed_lc_monkey_${DATE_TAG}.json`);
fs.writeFileSync(OUT, JSON.stringify(verdict, null, 2));
console.log(JSON.stringify({ layer: verdict.layer, ...verdict.summary, bars: verdict.bars, out: path.relative(process.cwd(), OUT) }, null, 2));
