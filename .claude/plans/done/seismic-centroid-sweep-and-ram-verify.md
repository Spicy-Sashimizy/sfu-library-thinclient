# Plan — SEISMIC centroid_fraction sweep (G2) + fully-confirmed 150M RAM requirement (G7)

Branch: `spike/mmap-bmp` (continue; all SEISMIC work lives here).
User ask: "run the centroid_fraction sweep AND fully confirm that the 150M db needs 160 GB RAM."

## Why these two, and what each decides

`02_GO_NO_GO_GATES.md` G2 has two escapes still OPEN as of 2026-06-27:
`centroid_fraction` (the one untested quality lever) and G6 RRF (measured
INCONCLUSIVE / persona-unmeasurable 2026-06-27). G7 (150M build) is ⬜ open. The
user wants both quality escapes exhausted AND the 150M build-RAM cost pinned to
a verified number, so the KILL/KEEP decision can rest on closed gates.

This plan closes the `centroid_fraction` lever (G2 sweep #3) and produces a
**measured, defensible** 150M build-RAM figure for G7 — not a two-point linear
extrapolation. Critically, the RAM verification is done WITHOUT attempting a
150M build (which is RAM-impossible here); it measures the RSS-vs-corpus
scaling curve at the largest scales this host fits, then projects with a fit +
confidence interval.

## What I verified scoping this (so the plan is grounded, not assumed)

- **Full corpus = 150,413,098 docs** (`data/thinclient_index/manifest.json`,
  sum over all 9 sections; 5 sections x ~8 slices each, 123 GB compressed spool).
- **Build RSS data points (owned `SeismicIndex.build`):**
  929k docs → 1.91 GB RSS / 1.16 GB disk;
  2.0M docs → 2.81 GB RSS / 1.69 GB disk;
  2.0M unpruned (P3: max_frac×6.7, doc_cut→1, summary_energy→0.9) → 7.92 GB RSS / 5.28 GB disk.
- **Linear projection 2M→150M from the two default points = ~128 GB peak RSS.**
  Host = 31 GB physical, ~8 GB available, 16 GB swap, 755 GB free disk on /tmp.
  → literal 150M build is RAM-impossible here (gate-zero RAM-no-go, same as
  BMP rows 4+6). mmap cures SERVING RAM, not BUILD RSS; pyseismic 0.4.0 has
  no on-disk/streaming build path (only `SeismicIndex.build(jsonl)`, holds the
  whole forward index + k-means clustering in RAM — confirmed in memory).
- **Build-RAM ceiling on this host** (leave OS headroom): a ~16-22 GB RSS build =
  ~18-25M docs. So the largest single measured point this host can hit is ~25M docs
  (~22 GB RSS) — enough to add two new data points (8M, 25M) to the 929k/2M pair
  and pin the scaling coefficient, NOT just extrapolate.
- **The full-corpus baseline record (`parity_record_tc_qdrant_20260625_0001.json`)
  is non-degenerate at full scale** (scanned this session): SPLADE top-50 recovers
  mean 10.78 judged docs/query vs the persona slice's 1-6; 37/40 queries recover
  >=3 judged docs; UNION(BM25F,SPLADE) covers >=3 on 40/40. → IF a 150M SEISMIC
  treatment leg existed, G6 WOULD be measurable (the degeneracy that made it
  unmeasurable was slice-scoping, not the harness). This is recorded as the
  finding that makes the G7 host-block averted from G6's framing, not G6 itself.

## Workstream A — centroid_fraction sweep (G2 sweep #3, ~20 min wall)

### A1. Add a `centroid_fraction` lever axis to `g2_param_sweep.py`

The script already has a `--lever` switch ({max_fraction, n_postings}) and a
`GRIDS` map. Add a third grid + branch. The lever semantics: `centroid_fraction`
controls clustering density (fraction of docs used as k-means centroids); it is
NOT a posting-retention lever — the existing verdict-logic docstring notes it
"unlikely to move top-10" because it changes which docs cluster together, not
which postings survive pruning. So unlike n_postings (where bit-identical is the
"structural ceiling" signal), centroid_fraction changes block membership → a
real run is *expected* to perturb per-query top-10; the question is whether that
moves overlap@10 toward 0.95.

Grid (cheapest informative; min-cluster-size held at default 2):
- `P0_cf0.1` — anchor, reproduce 0.479 (DEFAULTS, centroid_fraction=0.1).
- `C1_cf0.05` — halve clustering density (fewer/coarser blocks → bigger blocks,
  more per-block approx; tests the "coarse clustering loses recall" direction).
- `C2_cf0.2` — double clustering density (more/finer blocks → smaller blocks,
  tighter summaries; tests the "fine clustering improves recall" direction).
- `C3_cf0.4` — aggressive 4x denser clustering (RSS rises; bounds the reachable
  ceiling on this axis). 0.4 keeps it under the host's ~8 GB available budget
  (clustering overhead scales with centroid count; persona 2M at cf0.4 ~ proj
  ~4-5 GB RSS, safe; will assert-avail before each build).

Verdict logic (new branch): existing _verdict builds n_postings + max_fraction
branches; add `centroid_fraction` branch:
- P0 must reproduce 0.479 (±0.03) else HARNESS DRIFT.
- If any C-config >= 0.95 → G2 RECOVERABLE via centroid_fraction (bisect).
- If overlap rises monotonically P0→C2→C3 but stays <0.95 → G2 TUNABLE-NOT-
  REACHED (extrapolate cf further; note RSS cost).
- If overlap frozen/falls across C1=C2=C3 with bit-identical-to-P0 per-query
  → CENTROID_FRACTION INERT (the final index-quality lever exhausts; 0.479 is
  the query-time approximation floor, KILL-candidate on the quality axis).

### A2. Run it

```
.venv/bin/python3 scripts/seismic_testbed/g2_param_sweep.py --lever centroid_fraction \
  --jsonl /tmp/seismic_testbed/jsonl/med_bio_2000000.jsonl \
  --baseline data/eval_results/seismic_parity_persona_2m.json \
  --result-file data/eval_results/seismic_g2_centroid_fraction_sweep.json
```
Runs offline (Qdrant cached) — no live Qdrant, no API key, no OS. ~4 min/build
× 4 configs ≈ 16-20 min. Writes result JSON + prints verdict.

### A3. Doc + memory (same-commit per CLAUDE.md)

- `02_GO_NO_GO_GATES.md` G2 row: append sweep #3 result (date, the 4 overlap
  numbers, verdict — INERT vs TUNABLE vs RECOVERABLE, result-file path).
- `06_FINDINGS.md`: add a "G2 sweep #3 (centroid_fraction)" bullet; update the
  open-gates line ("all three server-side pruning levers + the one clustering-
  density lever proven inert" if INERT, or reopen quality path if tunable).
- Memory `seismic-testbed-p1-p2-results.md`: append the centroid_fraction outcome
  to the G2 section; update the one-line headline if it flips the quality arc.

## Workstream B — fully-confirmed 150M build-RAM requirement (~40 min wall)

The claim "150M needs ~128 GB" is currently a 2-point linear projection. To
FULLY confirm it, measure the RSS-vs-docs curve at 4 points including 2 new
larger scales this host still fits, fit a model, and project to 150M with a
stated interval — not a single number plausibly cited as "the answer."

### B1. Reuse `build_persona_seismic.py` to build 2 new measured points

The builder already records peak_rss_gb + on_disk_gb + build_seconds + dim per
build. Build two new med_bio sub-shards (the existing jsonl only has smoke/929k/
2M; need larger — generate from `spool_to_seismic_jsonl.py --limit`):
- **8M docs** (`--limit 8000000`, jsonl ~11 GB on disk, RSS ~8 GB — safe): adds a
  4x-larger point vs the 2M pair; spans the regime where clustering overhead
  begins to show.
- **25M docs** (`--limit 25000000`, jsonl ~36 GB on disk, RSS ~22 GB — near the
  host ceiling, leave headroom via `nice -n 19` + watch MemAvailable; ABORT the
  build gracefully if available drops <2 GB to avoid OOM-kill): the largest
  feasible point; this is what makes the 150M projection defensible rather
  than a 2-point line.

Both build with DEFAULTS (parity-matched; no sweep here — this is the RSS
curve, not quality). Result JSONs:
`data/eval_results/seismic_build_scale_8m.json`, `seismic_build_scale_25m.json`.

### B2. Fit + project (new small script `scripts/seismic_testbed/project_150m_ram.py`)

Collect all measured points (929k, 2M, 8M, 25M) → fit two models and report
both (defense in depth — a single linear fit can hide curvature):
- **Linear** `rss = a + b·docs` (what the 2-point proj used) → 150M proj.
- **Power-law** `rss = a · docs^c` (captures sub-linear clustering overhead
  which the 2M-vs-unpruned-2M gap hints at) → 150M proj with the exponent.

If the 25M point forces curvature, the power-law fit is the honest one and the
linear projection was an over/under-estimate — that's the "fully confirmed" part.

Report: the 150M projected peak RSS under each model, a **conservative band**
[min(linear, power), max(linear, power)], the measured RSS/doc at 25M (→ direct
scale to 150M as a cross-check: rss/doc × 150M), and a one-line verdict:
"150M build requires ≈X GB peak RSS (band Y–Z), which is ≫ 31 GB physical on
the current host → confirmed host-impossible; a G7 build needs a host with
≥ (X · 1.3 safety) GB RAM." Result → `data/eval_results/seismic_g7_150m_ram_projection.json`.
This is the number that goes into the G7 row + answers the user's exact question.

### B3. Doc + memory (same-commit)

- `02_GO_NO_GO_GATES.md` G7 row: fill the "Measured/Notes" with the projected
  figure + band + "confirmed RAM-impossible on 31 GB host; needs ≥ X GB host"
  (the build itself stays ⬜ not-run — projection, not a built 150M index; mark
  explicitly "RAM requirement CONFIRMED BY MEASUREMENT + fit, not by a 150M build").
- `06_FINDINGS.md`: short section "G7 150M build-RAM projection (measured-curve)".
- Memory `seismic-testbed-p1-p2-results.md`: add the G7 RAM number + the 4-point
  curve to the build/infra facts; note scipy/fit details if non-obvious.

## Sequencing + cost

1. Workstream A (sweep) first — cheap, offline, ~20 min, answers the open
   G2 quality escape. Commit.
2. Workstream B (RAM verify) second — ~40 min, the larger builds are the
   long pole and watch-RAM; answers the user's literal 160 GB question with
   a measured curve, not a 2-point line. Commit (B1+B2+B3 together).
3. Memory + docs ride in each workstream's same-commit (CLAUDE.md rule).

Both workstreams are background-able; I'll run the builds in background and
poll. Total committed wall ≈ 1 hour.

## Honest caveats (pre-registered)

- The 150M projection is a FIT over ≤25M points, not a measured 150M build. It
  will be LABELED as such in the G7 row + memory — never stated as "we built
  150M and it OOM'd." (The CLAUDE.md efficacy rule forbids unlabelled measured
  claims; a projection is explicitly marked `*proj.*` / "curve fit, not build".)
- If the 25M build OOM-aborts (host RAM pressure from other procs), B2 falls
  back to 3 points (929k/2M/8M) with a wider, more conservative band — still a
  defensible confirmation, just less tight. The script will not silently fudge.
- centroid_fraction is low-expectation (not a posting-retention lever). If INERT,
  that is the expected and decisive result — it exhausts the last G2 escape; it
  does NOT by itself KILL unless combined with the already-INCONCLUSIVE G6.
  The combined read goes in the memory headline as the honest "quality arc"
  status, not a unilateral KILL.
- A tunable centroid_fraction result (overlap rises) would REOPEN the quality
  path — I'd report that as needing a follow-up bisect, not ship a PASS.
