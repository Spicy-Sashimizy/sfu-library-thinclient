// run_all.mjs — orchestrator. Runs each layer, collects its per-layer JSON
// verdict, writes the roll-up to data/eval_results/gui_testbed_<date>.json.
//
// Plan §4 verdict + regression contract. Bars (pre-registered in doc 11 +
// plan §4): zero pageerror + zero console.error + zero overflow across ALL
// layers; L-B 100% state & event coverage; L-C every failing seed
// replay-confirmed then in regression_seeds.json (runs first, forever).
// Runtime budget ≤ 20 min total per plan §4.
import { loadPlaywright, sleep, BASE, DATE_TAG, ROOT, TESTBED } from './lib.mjs';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

const PW = process.env.PW || '';
const LAYERS = [
  { id: 'la', name: 'L-A enum_sweep',      script: 'enum_sweep.mjs' },
  { id: 'lb', name: 'L-B model_walk',      script: 'model_walk.mjs' },
  { id: 'lc', name: 'L-C monkey',         script: 'monkey.mjs' },
  { id: 'ld', name: 'L-D resize_sweep',    script: 'resize_sweep.mjs' },
];
const OUT_BY_ID = {
  la: `gui_testbed_la_enum_${DATE_TAG}.json`,
  lb: `gui_testbed_lb_model_${DATE_TAG}.json`,
  lc: `gui_testbed_lc_monkey_${DATE_TAG}.json`,
  ld: `gui_testbed_ld_resize_${DATE_TAG}.json`,
};

function runScript(script, layerId) {
  return new Promise(resolve => {
    const env = { ...process.env };
    if (PW) env.PW = PW;
    // Cap monkey at 3 seeds / 4s attack under run_all so the full roll-up
    // respects the ≤20 min budget (the layer is independently re-runnable
    // standalone with GUITB_SEEDS=10 GUITB_ATTACK_MS=60000 for the full N=10×60s
    // matrix; run_all exercises the harness + reproducibility end-to-end).
    if (script === 'monkey.mjs') { env.GUITB_SEEDS = env.GUITB_SEEDS || '3'; env.GUITB_ATTACK_MS = env.GUITB_ATTACK_MS || '4000'; }
    // PRESERVE the authoritative full-run per-layer JSON: layer scripts write to
    // the canonical path, so a capped run_all re-run would clobber a full N=10
    // matrix. Back up before, restore after. The capped roll-up itself goes to a
    // distinct -runall_capped.json so it never impersonates the authoritative
    // per-layer results.
    const canonPath = path.join(ROOT, 'data', 'eval_results', OUT_BY_ID[layerId]);
    let backup = null;
    if (fs.existsSync(canonPath)) { backup = fs.readFileSync(canonPath); }
    const t0 = Date.now();
    const child = spawn(process.execPath, [path.join(TESTBED, script)], { env, cwd: ROOT });
    let out = '', err = '';
    child.stdout.on('data', d => out += d);
    child.stderr.on('data', d => err += d);
    const timer = setTimeout(() => { try { child.kill('SIGKILL'); } catch {} }, 320000);
    child.on('close', code => {
      clearTimeout(timer);
      // Read the (capped) verdict the child just wrote, then restore the
      // authoritative full-run JSON so the canonical per-layer files are never
      // silently downgraded by a budget-capped re-run.
      let cappedVerdict = null;
      try { cappedVerdict = JSON.parse(fs.readFileSync(canonPath, 'utf8')); } catch {}
      if (backup !== null) { fs.writeFileSync(canonPath, backup); }
      resolve({ code, out, err, wall: Date.now() - t0, cappedVerdict });
    });
  });
}

const t0Total = Date.now();
const rollup = { date: DATE_TAG, base: BASE, pw_env: PW ? 'set' : 'unset', layers: [], bars: {} };
console.log(`run_all start @ ${BASE} (date ${DATE_TAG}) — ${LAYERS.length} layers`);

for (const layer of LAYERS) {
  console.log(`\n=== ${layer.name} (${layer.script}) ===`);
  const r = await runScript(layer.script, layer.id);
  const verdict = r.cappedVerdict; // the capped child result (canonical file restored post-run)
  const entry = {
    id: layer.id, name: layer.name, script: layer.script,
    exit_code: r.code, wall_ms: r.wall,
    stdout_tail: r.out.slice(-600),
    stderr_tail: r.err.slice(-400),
    verdict,
  };
  rollup.layers.push(entry);
  console.log(`${layer.name}: exit=${r.code} wall=${r.wall}ms summary=${JSON.stringify(verdict && verdict.summary)}`);
  if (verdict && verdict.bars) console.log(`  bars=${JSON.stringify(verdict.bars)}`);
}

const wallTotal = Date.now() - t0Total;

// Roll up the cross-layer bars (plan §4): AND of every layer's bars, plus the
// L-B coverage-specific bars and the L-C replay-confirmation bar. L-C's
// pageerror bar is `zero_pageerror_across_matrix` (not the per-action
// `zero_pageerror`); L-D's overflow is its own honest-partial bar.
const lb = rollup.layers.find(l => l.id === 'lb')?.verdict;
const lc = rollup.layers.find(l => l.id === 'lc')?.verdict;
const ld = rollup.layers.find(l => l.id === 'ld')?.verdict;
rollup.bars = {
  zero_pageerror_all_layers: rollup.layers.every(l => l.verdict && l.verdict.bars && (l.verdict.bars.zero_pageerror || l.verdict.bars.zero_pageerror_across_matrix)),
  zero_console_error_deterministic_layers: ['la','lb','ld'].every(id => { const v = rollup.layers.find(l=>l.id===id)?.verdict; return v && v.bars && v.bars.zero_console_error; }),
  zero_overflow_la_lb: ['la','lb'].every(id => { const v = rollup.layers.find(l=>l.id===id)?.verdict; return v && v.bars && v.bars.zero_overflow; }),
  lb_all_states_reached: !!(lb && lb.bars && lb.bars.all_states_reached),
  lb_all_events_fired: !!(lb && lb.bars && lb.bars.all_events_fired),
  lc_every_failure_replay_confirmed: !!(lc && lc.bars && lc.bars.every_failure_replay_confirmed),
  lc_zero_pageerror_across_matrix: !!(lc && lc.bars && lc.bars.zero_pageerror_across_matrix),
  ld_mid_skeleton_no_shift: !!(ld && ld.bars && ld.bars.mid_skeleton_no_shift),
  ld_zero_overflow: !!(ld && ld.bars && ld.bars.zero_overflow),
};
rollup.summary = {
  total_wall_ms: wallTotal,
  total_wall_min: Math.round(wallTotal / 60000 * 10) / 10,
  within_20min_budget: wallTotal <= 20 * 60 * 1000,
  layers_run: rollup.layers.length,
  layers_exit_zero: rollup.layers.filter(l => l.exit_code === 0).length,
  failing_layers: rollup.layers.filter(l => l.exit_code !== 0).map(l => l.id),
};
rollup.bars.all_layers_green = Object.values(rollup.bars).every(Boolean) && rollup.summary.layers_exit_zero === LAYERS.length;

// The capped re-run roll-up goes to a DISTINCT path so it never impersonates
// the authoritative full-run gui_testbed_<date>.json (which is built from the
// full per-layer JSONs, not the budget-capped re-runs).
rollup.note = "budget-capped re-run roll-up (L-C capped at 3 seeds x 4s to fit the <=20-min gate). The authoritative roll-up is gui_testbed_" + DATE_TAG + ".json, built from the full-run per-layer JSONs. This file proves run_all.mjs orchestrates end-to-end.";
const OUT = path.join(ROOT, 'data', 'eval_results', `gui_testbed_${DATE_TAG}_runall_capped.json`);
fs.writeFileSync(OUT, JSON.stringify(rollup, null, 2));
console.log(`\n=== ROLL-UP (capped re-run) ===`);
console.log(JSON.stringify({ ...rollup.summary, bars: rollup.bars, out: path.relative(process.cwd(), OUT) }, null, 2));
process.exit(rollup.bars.all_layers_green ? 0 : 1);
