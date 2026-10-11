# Plan — E8 Stage 2: host-tier dv-v2 full-corpus rollout + serve flip (Q1 finale)

**Created 2026-07-10**, after Stage 1 GO (all 4 bars PASS on shards 1–2 +
post-GO deep validation; `.claude/plans/done/q1-e8-dvv2-perdoc-scale.md`,
doc 12 §3 Q1). This is the **serve unlock**: the only queued item that RAISES
quality — corpus parity 0.9906 → ≥0.995 (*est.*) at zero serve-time cost.

**Environment: the 58 GB host session** (HOSTPY pattern; E7c-scale, ~a day of
conversion). Paste-ready runbook:
`scripts/seismic_testbed/HOST_PROMPT_E8_STAGE2_DVV2.md`.

## Pre-registered bars (written BEFORE the run — never retrofitted)

| # | Gate | Bar |
|---|---|---|
| a | overlap@10 per shard, v2.e5 vs f16 twin, n=100/shard (G8d convention) | **every shard ≥0.99 AND corpus mean ≥0.995** |
| b | on-disk size per shard vs served dv-v1.e5 | within ±2% |
| c | federated warm p50, v2 manifest vs served v1.e5 manifest (same-process interleaved A/B) | ≤1.05× |
| d | federated cold p50 ratio (fadvise-DONTNEED protocol) | ≤1.10× — the E5 cold win must survive (+0.9% pages expected from the 2 B/record head; Stage-1 measured cold 1.02×/0.92×) |
| e | T1 sequential≡parallel on the v2 manifest | 100/100 bit-identical |
| f | reorder/convert parity per shard | converter byte-verify + tie-aware sample check green, all 8 |

ALL bars pass → flip the served manifest. ANY bar fails → record, do NOT
flip, v1.e5 keeps serving (it is untouched throughout — Rule Zero).

## The one-rewrite pipeline (doc 13 §3: perm + re-encode ride the same pass)

Per shard k ∈ {0..7}, all inputs read-only, all outputs NEW dirs:

1. **Convert** (skip for shards 1–2 — Stage-1 dirs
   `global_shard{1,2}of8.dotvbyte.v2.mmap` already exist, build-order):
   `convert_f16_to_dotvbyte --value-scale perdoc`
   `global_shard{k}of8.mmap` (f16 twin) → `global_shard{k}of8.dotvbyte.v2.mmap`.
2. **Reorder**: `reorder_mmap_shard --perm-file
   data/seismic_150m/index/plan01/e5_perms/global_shard{k}of8.block_walk_canonical.perm.bin`
   → `global_shard{k}of8.dotvbyte.e5.v2.mmap`. The existing perms remain
   valid: E8 re-encodes forward VALUES only; the posting-pack walk order that
   derived them is untouched (the reorder bin's sample check re-verifies).
3. **Gate a** for shard k (`e8_dvv2_gates.py` convention vs the f16 twin),
   then delete the intermediate build-order `.v2.mmap` dir (reclaim ~4 GB;
   the Stage-1 shard-1/2 dirs may be deleted after their reorder too — they
   are gate artifacts, reproducible from f16).

Disk transient: ≤2 extra dirs/shard (~8 GB) at any time; 550 GB free
measured 2026-07-09. Sequential per-shard loop, checkpointable — a partial
run resumes at the next unconverted shard.

## After the per-shard loop (federated gates c/d/e)

Build the v2 manifest (`e5_validate_and_manifest.py` lineage →
`manifest json alongside the C2.5/dv/e5 ones`), then
`serve_footprint_bench.py` A/B: served v1.e5 manifest vs v2.e5 manifest,
alternating cells × 2 reps, fadvise-DONTNEED cold protocol, VmSwap≈0 +
warm<cold validity checks. T1 on the v2 manifest.

## Serve flip (only on all-bars PASS)

- Retriever default → the v2.e5 manifest; rollback stays one env var
  (`SFU_SEISMIC_SHARD_MANIFEST` → v1.e5 manifest path), same pattern as the
  qdrant→seismic and plain-dv→e5 promotions.
- **Same-commit docs:** `docs/THIN_CLIENT_SWAP.md` (served format + parity
  headline), doc 10 §7.6 (G8d successor row: new corpus-mean parity),
  doc 12 §3 Q1 verdict line + §4 ledger row + §1 state snapshot, doc 06 row,
  `docs/STORAGE_BUDGET_150M.md` if the size delta moves the budget table.
- Result JSONs: `data/eval_results/e8_stage2_shard{0..7}_2026MMDD.json` +
  `e8_stage2_federated_2026MMDD.json`.

## Rule Zero inventory (before AND after)

`du -sb` over: served `*.dotvbyte.e5.mmap` (v1, all 8), dv build-order
`*.dotvbyte.mmap`, f16 twins `*.mmap`, `e5_perms/` — byte-identical or STOP.

## Non-goals / follow-ons

- Absolute nDCG for the v2 leg (`rejudge_seismic_leg_n120.py` lineage) —
  optional host-tier follow-on AFTER the flip settles the format.
- H5 sequential dv @6G cap — separate host-tier item, may batch into the
  same session AFTER E8 Stage 2 completes (doc 12 §3 host-tier table).
- No int6/M2 revival — v2 keeps the int6 path composable but M2 stays
  env-gated OFF (killed at Q4/M2b, 2026-07-10).

## Risk

- **Conversion-scale defect** class was pre-cleared by the Stage-1 post-GO
  audit (vmax saturation NaN guard + stress suite 5/5, wheel rebuilt).
- **Host reboot mid-run** — the 2026-06-30 shard wipe precedent; outputs go
  to persistent paths, loop is resumable, served artifacts never staged.
- **Windows-side cache asymmetry** — only paired same-run ratios are
  verdicts (established protocol).
