// THE invariant oracle — every layer calls this after every action.
// (GUI_INTERACTION_TESTBED_PLAN.md §2 contract; the bars from e2e_sweep.mjs
// promoted to per-action assertions.)
//
// Hard bars (pre-registered in doc 11 backlog + plan §4):
//   - zero pageerror          (any uncaught throw = fatal)
//   - zero console.error      (any logged error = fail)
//   - zero horizontal overflow (>4px = fail; 2px sub-pixel tolerance)
//   - event loop responds within 2 s (a wedged UI = fatal)
//   - honesty floor: mock/demo data on screen ⇒ demo pill visible, NEVER hidden
//
// These are exported individually (so a layer can run a single check) and as a
// combined `check`. Failure artifacts (screenshot + trace) are captured by
// lib.captureArtifacts at layer-end, not here (per audit addition #1: traces
// stop once, after the run, to keep the zips whole).
export { arm, check, overflow, isMockShown } from './lib.mjs';
export { captureArtifacts } from './lib.mjs';
