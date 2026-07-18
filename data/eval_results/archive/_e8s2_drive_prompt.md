You are executing the E8 Stage 2 SHARD-REBUILD LOOP ONLY, in this dev container,
per `.claude/plans/e8-stage2-host-dvv2-serve.md` and doc 12 §3 Q1 (source of
truth). You were launched non-interactively by the host-ops operator to do the
mechanical shard rebuild and NOTHING beyond it. Work shard-by-shard; resumable.

## HARD SCOPE — do only this, then STOP
- Rebuild shards k = 3,4,5,6,7 (convert + reorder + per-shard gate), then
  reorder-only for k = 1,2 (their `.dotvbyte.v2.mmap` intermediates already
  exist from Stage 1). Shard 0 is DONE (result JSON + e5.v2 dir exist) — SKIP it.
- After the last shard: STOP and print a summary. DO NOT run federated gates,
  DO NOT build the v2 manifest, DO NOT run serve_footprint_bench, and above all
  DO NOT flip the serve manifest. The operator does the flip. Halting here is
  the whole point.

## RULE ZERO — inputs are IRREPLACEABLE and READ-ONLY
Never modify, delete, move, symlink, or re-convert any INPUT dir:
  global_shard{k}of8.mmap (f16 twins), global_shard{k}of8.dotvbyte.e5.mmap
  (SERVED v1), global_shard{k}of8.dotvbyte.mmap (dv v1), e5_perms/*.perm.bin.
The ONLY dirs you may delete are the intermediate `global_shard{k}of8.dotvbyte.v2.mmap`
dirs, and ONLY after that shard's gate has PASSED. All outputs go to NEW dirs.
If any input is missing or fails to load: STOP and report — do not "fix" it.

## Environment (verified by operator)
- Interpreter for ALL python: `.venv/bin/python3` (it imports `seismic`; the
  container default `python3` does NOT — never use it).
- Rust bins (post-Stage-1 rebuild, vmax NaN guard):
  `spike/seismic_upstream/target/release/convert_f16_to_dotvbyte`
  `spike/seismic_upstream/target/release/reorder_mmap_shard`
  Discover exact flags with `--help` and/or the `.rs` source; match the Stage-1
  invocation (per-doc value scale for convert; block_walk_canonical perm for
  reorder). Cross-check against the shard-0 logs in data/eval_results/
  (_e8s2_shard0_convert.log, _e8s2_shard0_reorder.log, _e8s2_shard0_gates.log).
- FIRST, verify the toolchain: load a Stage-1 v2 dir
  (global_shard0of8.dotvbyte.e5.v2.mmap) and confirm its forward format is
  `dotvbyte_fixedu8_v2` (use the same API `e8_dvv2_gates.py` uses). If not: STOP.

## The loop (per shard)
1. Convert (k in 3,4,5,6,7 only): f16 twin -> `global_shard{k}of8.dotvbyte.v2.mmap`.
2. Reorder: v2 dir -> `global_shard{k}of8.dotvbyte.e5.v2.mmap` with
   `e5_perms/global_shard{k}of8.block_walk_canonical.perm.bin` (+ sample check).
3. Per-shard gate (`e8_dvv2_gates.py` convention): overlap@10 of v2.e5 vs the
   f16 twin, n=100 — BAR ≥0.99. Also record size of v2.e5 vs the served v1.e5
   dir — BAR ±2%. Write `data/eval_results/e8_stage2_shard{k}_$(date +%Y%m%d).json`.
4. If the gate PASSES: delete the intermediate `.dotvbyte.v2.mmap` dir, then
   `git add` the result JSON (+ a one-line "Stage 2 IN PROGRESS, k/8 done" note
   in doc 12 §3 Q1) and commit + push. If it FAILS: STOP, delete nothing, report.

## Standing rules
- `git pull` FIRST (STOP on conflict). Explicit `git add <files>` only, NEVER
  `git add .`. Commit + push after each shard for clean resume.
- Run serially — one convert loads a whole shard (~10 GB) into RAM; never
  concurrent.
- At the very end: re-run
  `du -sb data/seismic_150m/index/plan01/global_shard*of8*.mmap data/seismic_150m/index/plan01/e5_perms`
  and diff against `data/eval_results/_e8s2_inventory_before_1783973549.txt`.
  It MUST be byte-identical. Report the diff (or "clean") in your final summary.

## Final summary (print this, then STOP)
Per shard: overlap@10, size delta %, PASS/FAIL, result-JSON path. Plus the
Rule Zero inventory verdict. State clearly that the federated gates + serve flip
were NOT done and await operator sign-off.
