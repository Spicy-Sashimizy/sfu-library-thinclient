# DRIVE PROMPT — deployprep wave 5: GUI bare-bones + honest search progress

You are the in-container execution half of `deployprep` wave 5 (2026-07-17).
Waves 1–4 are COMPLETE — read `data/eval_results/_deployprep_timing.md` +
git log; do NOT redo their work. Owner directive: implement
`docs/infrastructure/GUI_BAREBONES_PROGRESS_SPEC.md` EXACTLY — that spec is
the contract (progress-indication table §1 + tier/toggle table §2 + the
integrity floor + constraints). Read it, then `docs/THIN_CLIENT_SWAP.md`
§Web GUI, before touching anything.

## Binding rules — identical to wave 1 (`_deployprep_drive_prompt.md`
§Binding rules + §OWNER CONSTRAINTS + §STAY-ALIVE apply verbatim)

Highlights: git pull before commits; explicit adds; NO serving-path/API
changes (this wave is `web/` + e2e harness only — `src/` is out of bounds
except NOTHING); no docker; no /tmp; absolute dates; F6 discipline on any
measured claim; NO deploy / NO DO spend / NO TrueNAS / NO served-default
flips.

## Time budget — SHORT WAVE

Hard stop for new work **2026-07-17 07:20Z**; then ledger row WI-15 finish,
doc sync (THIN_CLIENT_SWAP §Web GUI gets a dated subsection; README index
already points at the spec), commit, push, exit by **07:40Z** ABSOLUTE.
Depth over breadth: if time runs short, §1 progress indication complete-and-
verified beats §1+§2 both half-done. Ledger row: WI-15.

## WI-15 (single item) — implement the spec

1. §1 progress indication in `web/search.html` + `web/lib/` (skeleton cards
   matching result-card shape; 300 ms gate; >10 s warming message off
   /health warm; 429 Retry-After countdown + auto-retry; degraded notices
   from response flags; reduced-motion-safe shimmer).
2. §2 bare-bones default + Settings "Interface" toggles (localStorage
   persistence; suite shell must NOT mount iframes for toggled-off apps;
   integrity floor: banner/degraded/pill never hideable).
3. Verify like the 2026-06-19 GUI work was verified (THIN_CLIENT_SWAP
   records the method): Babel transform-compile of every changed app, jsdom
   mount offline+online zero-runtime-errors, and EXTEND
   `scripts/e2e_sweep.mjs` with: default-bare state, each toggle flips +
   persists across reload, skeleton appears ≥300 ms & absent <300 ms (mock
   latency), 429 countdown state, zero console errors, zero horizontal
   overflow, no layout shift skeleton→results. Run the sweep; record
   pass/fail counts honestly in the doc subsection.

## Session end

Ledger + doc sync + push + exit by 07:40Z even if incomplete (mark honest
partial status in the ledger row).
