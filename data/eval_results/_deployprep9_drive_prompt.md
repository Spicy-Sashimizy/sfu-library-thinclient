# DRIVE PROMPT — deployprep wave 9: FINISH wave 8 — speculation three-arm benchmark completion (2026-07-28)

You are the in-container execution half of `deployprep` wave 9. This wave has
NO new feature scope: it exists solely to FINISH wave 8, which was
interrupted on 2026-07-18 mid-WI-18b. Waves 1–7 and WI-18a are COMPLETE — do
NOT redo their work.

## Orient first (read before writing anything — in this order)

1. `data/eval_results/_deployprep8_drive_prompt.md` — the wave-8 contract.
   Its §Binding rules, §Contract terms 1–8, and cell definitions A–G apply to
   this wave VERBATIM. Do not re-derive them; this prompt only adds the
   resume-state facts and the W8-3 fix requirement.
2. `data/eval_results/_deployprep_host_queue.md` — the full HOST-NOTE-W8-1 /
   W8-2 / W8-3 blocks. W8-3 is REJECTED-BLOCKING and is the first thing you
   must fix (below).
3. `data/eval_results/_deployprep_timing.md` — wave-8 rows (WI-18a DONE,
   WI-18b IN PROGRESS at interruption).
4. `scripts/eval_speculation_ab.py` — the benchmark harness as left at commit
   71991cf (arm A worked; arm-C protocol is the defective part).
5. `docs/infrastructure/DEMO_DEPENDABILITY.md` §Wave 8 — the WI-18c doc
   scaffold with TBD cells you will fill.
6. `docs/seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §WI-18 — the
   pre-registered bars (a)–(e). They were registered 2026-07-18 BEFORE any
   measured run and STAND UNCHANGED. Do not renegotiate them.

## Resume-state facts (2026-07-28, verified by the host before launch)

- The container was REBUILT since wave 8: verify your tools before relying
  on them (`.venv/bin/python3 -m pytest src/tests/ -q` should be green from
  WI-18a; check whether Playwright/Chromium is present before promising the
  GUI wiring proof — if absent, record that honestly and rely on the jsdom +
  HTTP evidence, do NOT install a browser).
- The staging serve on :8080 was relaunched by the host at 2026-07-28
  ~03:05Z with default env (cache ON, preseed ON, speculation OFF) and is
  WARMING (native-FS staging copy in progress). Wait for `/health` →
  `warm:true, cache_preseed:"primed"` before any warm cell. The
  wave-8 staging-serve exception applies: the serve is yours to
  stop/start/restart per benchmark arm, and at wind-down it MUST be left
  RUNNING, warm AND primed, speculation OFF.
- `data/eval_results/speculation_ab_2026-07-18.json` contains ONLY arm A
  (cold floor, n=20, p50 2335.88 ms). It is now HISTORICAL: the container
  rebuild + serve restart make cross-session mixing unpromotable. Leave that
  file untouched.

## WI-19a — fix the arm-C protocol (HOST-NOTE-W8-3) — BLOCKING, do first

Implement fix option (a) from the host note — REAL-TIME simulation:
`eval_speculation_ab.py` must sleep the already-computed inter-key
intervals, fire each speculation at its spec point in wall-clock time, and
press Enter at `enter_t` REGARDLESS of speculative-store state.
`resident_by_enter` becomes a fact observed at the real Enter instant, not a
probe-deadline artifact. The 3 s stores-complete probe before Enter is
DELETED (it may survive only as post-trial bookkeeping to record each
fire's store-complete wall latency for the lead-time distribution).
Bar for this item: a code-level self-review in the commit message stating
where the sleep happens, where Enter fires, and why no code path can wait
on the store before Enter — plus one smoke trial per profile showing
plausible wall-clock trial durations (a medium-profile trial must take
roughly its typing duration, not milliseconds). Submit a host-queue block
(`## REQ-<next>`) pointing at the committed fix for host review BEFORE
running the full arm-C cells; continue with non-arm-C cells while waiting
— never idle-wait on the host.

## WI-19b — run the full benchmark (arms A–G, one clean same-session run)

All cells go into a NEW results file
`data/eval_results/speculation_ab_2026-07-28.json` (raw per-trial samples +
event timelines included, wave-8 term 8). Re-run arm A fresh (it is ~1 min
of wall time) so every bar compares within-session numbers. Cell
definitions, n requirements, interleaving rule, trial-hygiene term 7, and
query pools are exactly the wave-8 prompt's WI-18b spec. If the time budget
forces n below a pre-registered minimum, that is a recorded deviation in
the JSON + docs, not a silent change (W8-3 note, last paragraph).
Arm-C headline framing follows HOST-NOTE-W8-1: predictor mode = the
known/in-pool-query scenario, literal mode = the novel-query scenario; no
sentence implies real-world prediction coverage.
When all cells are banked, submit the JSON path in a host-queue block for
F6 review BEFORE writing WI-19c docs.

## WI-19c — F6 docs + verdict (same-commit rule)

Fill the TBD cells in `docs/infrastructure/DEMO_DEPENDABILITY.md` §Wave 8
(retitle the section "Wave 8–9" with both absolute dates), update
`docs/THIN_CLIENT_SWAP.md` if any serving-path/env-gate description moved,
flip the backlog §WI-18 rows to MEASURED with PASS/FAIL per pre-registered
bar, and write the explicit **owner recommendation** (speculation ON or OFF
for the live review) justified ONLY from the measured hit-rate, waste, and
interference numbers (arms C/D/E/F). Every headline number recomputed from
the raw JSON before it enters a doc. README index row if any new doc.

## WI-19d (stretch, only if ≥25 min remain) — the wave-8 WI-18d item
unchanged (Interface toggle + Index Manager speculation counters).

## Time budget + timing ledger (owner requirement — HARD)

Budget: 3 h from launch (~2026-07-28 03:30Z). Hard stop for NEW work:
**2026-07-28 06:30Z**. Wind-down: finish the current step ONLY if <10 min
from its commit, else revert uncommitted work-in-progress cleanly. Then:
ledger rows final (honest statuses), session-end doc sync per CLAUDE.md,
restore the staging serve (cache ON, preseed ON, speculation OFF; `/health`
warm+primed verified), commit, push, exit by **2026-07-28 07:00Z
ABSOLUTE** — even if incomplete. If actual launch differs from 03:30Z by
more than 10 min, shift all times by the same delta and write the actuals
into your first ledger row.

Maintain `data/eval_results/_deployprep_timing.md`: add a "Wave 9 launched
2026-07-28 ..." section header, then a start row when you begin each item
(WI-19a/b/c/d) and a finish row when its final commit lands. Commit the
ledger with each update. Wave 8's WI-18b row stays as committed (historical).

## Host-queue

Same file + protocol: `data/eval_results/_deployprep_host_queue.md`, blocks
`## REQ-<n>` continuing existing numbering; host notes arrive as
`## HOST-NOTE-W9-<n>`. The host monitor is active this session (polling on
a minutes cadence). Expected host needs: the WI-19a protocol-fix review, the
WI-19b F6 review before WI-19c lands, anything privileged, anything
surprising about the serve. When in doubt, write a queue block and continue
with the next non-blocked step — never idle-wait on the host.
