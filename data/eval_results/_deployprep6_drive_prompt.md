# DRIVE PROMPT — deployprep wave 6: GUI full-interaction testbed (WI-16)

You are the in-container execution half of `deployprep` wave 6 (2026-07-17).
Waves 1–5 are COMPLETE — read `data/eval_results/_deployprep_timing.md` +
git log; do NOT redo their work. Owner directive: implement
`docs/infrastructure/GUI_INTERACTION_TESTBED_PLAN.md` EXACTLY — that plan is
the contract (architecture §1, invariant oracle §2, four generator layers §3
snippets, verdict/regression contract §4, item breakdown §5). Read it, then
`docs/infrastructure/GUI_BAREBONES_PROGRESS_SPEC.md` (§2 toggles ARE the L-B
model) and `docs/THIN_CLIENT_SWAP.md` §Web GUI, before touching anything.

## Binding rules — identical to wave 1 (`_deployprep_drive_prompt.md`
§Binding rules + §OWNER CONSTRAINTS + §STAY-ALIVE apply verbatim)

Highlights: git pull before commits; explicit adds — NEVER `git add .`;
NO serving-path/API changes (this wave is `scripts/gui_testbed/` + docs only;
`web/` may ONLY be touched to FIX a defect the testbed finds, each fix its
own commit citing the failing seed/action); no docker; no /tmp for
deliverables; absolute dates; F6 discipline on any measured claim; NO deploy
/ NO DO spend / NO TrueNAS / NO served-default flips.

## Environment facts (host-verified 2026-07-17 18:07Z — do NOT re-derive)

- **Chromium IS NOW AVAILABLE** (wave-5's "no Chromium" is stale): Playwright
  1.61.1 chromium-headless-shell 149.0.7827.55 launches headless, system deps
  installed. Playwright lives in the npx cache, NOT node_modules:
  `PW=/home/vscode/.npm/_npx/e41f203b7505f1fb/node_modules` — the existing
  `scripts/e2e_sweep.mjs` PW-env pattern (`${PW}/playwright/index.js`)
  resolves `chromium` correctly (host-verified). Use the SAME pattern in
  every testbed script; never `npm install playwright` into the repo.
- jsdom is in repo `node_modules` (wave-5 verify scripts still run).
- Vendoring gremlins.js: fetch a pinned release of `gremlins.min.js` (2.x)
  into `scripts/gui_testbed/vendor/`, record version + sha256 in the doc.
  Network fetch to vendor is allowed; runtime stays CDN-free per the plan.

## Audit additions (2026-07-17 host audit — cross-checked vs current
Playwright/monkey-testing best practice; these are part of the contract)

1. **Failure artifacts**: on every `fail`/`fatal`, capture a screenshot AND a
   Playwright trace (`context.tracing.start({screenshots:true,snapshots:true})`
   … `stop({path})`) to `data/eval_results/gui_testbed_artifacts/2026-07-17/`.
   Screenshots of failures are committed; trace zips stay local (record their
   paths in the verdict JSON, do not commit multi-MB zips).
2. **4th chaos arm — storage corruption**: before page load, seed
   localStorage with garbage in the interface-prefs keys (truncated JSON,
   wrong types, 1 MB string). The suite must boot to defaults, not wedge —
   this is a real returning-user state.
3. **Live sweep requirement**: `scripts/e2e_sweep.mjs` has never been run
   live in this container (wave 5 used jsdom evidence). Run it live FIRST
   (WI-16a precondition) — its PASS/FAIL is the baseline; record honestly.
4. Playwright discipline: role-based locators, web-first waits (no fixed
   sleeps in assertions), headless shell, per-layer wall-clock in the verdict
   JSON, total runtime budget ≤ 20 min per plan §4.

## Time budget — hard stop for new work **2026-07-17 21:40Z**; ledger rows +
doc sync + commit + push + exit by **22:10Z** ABSOLUTE. ~34 min/item
baseline. Depth over breadth: a green L-A + oracle beats four half-done
layers. If a layer cannot pass its bar, record the honest FAIL + failing
seeds — refuted expectations are valid results.

## Work-queue (strict order; each item: read → build → run → document →
commit+push → timing row `WI-16<letter>` → next)

- **WI-16a** `invariants.mjs` + `enum_sweep.mjs` green on current GUI
  (after the live `e2e_sweep.mjs` baseline run).
- **WI-16b** `model_walk.mjs` — model transcribed from
  GUI_BAREBONES_PROGRESS_SPEC §2 (bar: 100% state + event coverage).
- **WI-16c** vendored gremlins + `monkey.mjs` — N=10 seeds × 60 s ×
  {no-chaos + 4 chaos arms (backend-dead, hang, 429-storm, storage-corrupt)};
  failing seeds → `scripts/gui_testbed/regression_seeds.json` (runs first,
  forever), replay-confirmed before being recorded.
- **WI-16d** `resize_sweep.mjs` — 320→1920 w-sweep, zoom, DPR contexts,
  mid-skeleton resize.
- **WI-16e** `run_all.mjs` roll-up → `data/eval_results/gui_testbed_2026-07-17.json`
  + doc section in GUI_INTERACTION_TESTBED_PLAN.md ("MEASURED 2026-07-17"
  status header replacing "NOTHING BUILT") + backlog row in doc 11 +
  THIN_CLIENT_SWAP §Web GUI pointer + README index if new doc.
- **WI-16f (stretch, only if ≥40 min remain)** vendored axe-core a11y scan
  per screen as an oracle extension; record violations honestly, fix nothing
  outside `web/` defect rules above.

## Host-queue

Same file + protocol as wave 1: `data/eval_results/_deployprep_host_queue.md`,
blocks `## REQ-<n>` continuing existing numbering. The host monitor is
active this session. Expected host needs: none (Chromium prep is done) —
anything privileged goes through the queue, never run yourself.

## Session end

Ledger rows final, session-end doc sync per CLAUDE.md, commit, push, exit by
22:10Z even if incomplete (honest partial status in ledger rows).
