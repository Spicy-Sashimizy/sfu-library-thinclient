# HOST PROMPT — E8 Stage 2: dv-v2 full-corpus rollout + serve flip (paste-ready)

Paste everything below the `---` into a Claude Code instance running **directly
on the host** (NOT inside the 32 GB dev container). Plan:
`.claude/plans/e8-stage2-host-dvv2-serve.md`. Doc 12 §3 Q1 is the source of
truth — if this file and doc 12 disagree, doc 12 wins; fix the stale one in the
same commit you notice it.

**What Stage 1 already proved (2026-07-10, container):** dv-v2 per-doc scale
passed all 4 pre-registered bars on the worst-case shards — overlap@10
0.997/0.993 vs f16 (dv-v1 baseline 0.985/0.984), size +0.67%, warm ≤1.04×,
T1 0/0 — plus a post-GO deep audit (v1 back-compat, cross-build identity, NaN
vmax guard + stress suite, wheel rebuilt). `e8_dvv2_stage1_shard{1,2}_20260710.json`.
**Stage 2 = the remaining 6 shards + E5-perm fold + federated gates + the
serve flip.** This is the only queued lever that RAISES quality (corpus parity
0.9906 → ≥0.995 *est.*) at zero serve-time cost.

---

You are executing E8 Stage 2 per `.claude/plans/e8-stage2-host-dvv2-serve.md`.
Work shard-by-shard; the loop is resumable; record every gate before moving on.

## ⚠️ RULE ZERO — THE SHARDS ARE IRREPLACEABLE-EXPENSIVE. READ-ONLY.

A 2026-06-30 host reboot once wiped the shards (a full day to rebuild).
Inputs are READ-ONLY; all outputs go to NEW dirs:

```
READ-ONLY inputs:
  data/seismic_150m/index/plan01/global_shard{0..7}of8.mmap               (f16 twins — conversion source)
  data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.e5.mmap   (SERVED v1 — never touched)
  data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.mmap      (dv v1 build-order)
  data/seismic_150m/index/plan01/e5_perms/*.perm.bin                      (8 perm files, all present)
NEW outputs:
  global_shard{k}of8.dotvbyte.v2.mmap      (intermediate, build-order — delete after its reorder+gate)
  global_shard{k}of8.dotvbyte.e5.v2.mmap   (final, gets served on PASS)
```

- **Never** copy, move, symlink, delete, or re-convert an INPUT dir. If any
  input is missing or fails to load: **STOP and report** — do not "fix" it.
- Shards 1–2 intermediates already exist from Stage 1
  (`global_shard{1,2}of8.dotvbyte.v2.mmap`) — reorder those, don't reconvert.
- `du -sb` inventory over all input dirs BEFORE and AFTER the session; must
  be byte-identical: `du -sb data/seismic_150m/index/plan01/global_shard*of8*.mmap data/seismic_150m/index/plan01/e5_perms | tee /tmp/e8s2_inventory_$(date +%s).txt`

## ⚠️ RULE ONE — DO NOT TOUCH THE SHARED `.venv`

Editing `.venv` on the host broke the dev container once (2026-07-03).
Use the host interpreter against the venv's site-packages:

```bash
HOSTPY=/home/<user>/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11
export PYTHONPATH=$PWD/.venv/lib/python3.11/site-packages
$HOSTPY -c "import seismic; print('seismic ok')"   # must print ok — else STOP
```

The `.so` MUST be the post-Stage-1 rebuild (the one with the vmax NaN guard);
verify: `$HOSTPY -c "import seismic"` then load a Stage-1 v2 dir and check
`get_forward_format() == 'dotvbyte_fixedu8_v2'` — else STOP (stale wheel).

## ⚠️ RULE TWO — RAM + disk

`free -g` ≥ ~32 GB (else `.wslconfig` memory=58GB + `wsl --shutdown` with
operator approval, revert after — G8b runbook). Disk: transient ≤2 extra
dirs/shard (~8 GB); 550 GB free measured 2026-07-09 — re-check `df -h`.

## Standing rules

- Branch `spike/mmap-bmp`; **`git pull` FIRST**; explicit `git add <files>`
  only (NEVER `git add .`); commit+push after each logical unit.
- Bars below are pre-registered (plan + doc 12 §3 Q1) — never moved after
  looking at results. Only paired same-run ratios are verdicts.
- Result JSONs → `data/eval_results/e8_stage2_shard{k}_$(date +%Y%m%d).json`
  + `e8_stage2_federated_$(date +%Y%m%d).json`.

## The loop (per shard k = 0,3,4,5,6,7 then reorder-only 1,2)

1. Convert (skip k∈{1,2}): `convert_f16_to_dotvbyte --value-scale perdoc`
   f16 twin → `global_shard{k}of8.dotvbyte.v2.mmap` (bin:
   `spike/seismic_upstream/src/bin/convert_f16_to_dotvbyte.rs`; Python
   driver `scripts/seismic_testbed/convert_shard_to_mmap.py` has the
   `--value-scale` pass-through).
2. Reorder: `reorder_mmap_shard --src <v2 dir> --dst
   global_shard{k}of8.dotvbyte.e5.v2.mmap --perm-file
   e5_perms/global_shard{k}of8.block_walk_canonical.perm.bin` (+ sample
   check ON). The perms stay valid — E8 changes forward VALUES only, not
   the posting structure the walk order derives from.
3. **Gate a** (per shard): overlap@10 v2.e5 vs the f16 twin, n=100
   (`e8_dvv2_gates.py` convention). Bar: **≥0.99**. Also record size vs the
   served v1.e5 dir — bar **±2%** (gate b).
4. Delete the intermediate `.v2.mmap` dir. Commit the shard's result JSON +
   a one-line progress note in doc 12 §3 Q1 (dated "Stage 2 IN PROGRESS,
   k/8 done") so an interrupted session resumes cleanly.

## Federated gates (after all 8)

- Corpus-mean gate a: **mean ≥0.995, no shard <0.99** (the headline bar).
- Build the v2 manifest (`e5_validate_and_manifest.py` lineage; new JSON
  alongside the existing manifests — do not edit the served one).
- `serve_footprint_bench.py` A/B, served-v1.e5 vs v2.e5 manifests,
  alternating cells × 2 reps, fadvise-DONTNEED cold protocol; every cell
  needs VmSwap≈0 AND warm<cold. Bars: **warm p50 ≤1.05×, cold p50 ≤1.10×**.
- T1 sequential≡parallel on the v2 manifest: **100/100 bit-identical**.

## Serve flip — ONLY on all-bars PASS

Retriever default → v2.e5 manifest; rollback = one env
(`SFU_SEISMIC_SHARD_MANIFEST` → the v1.e5 manifest), same promotion pattern
as plain-dv→e5. **Same commit:** `docs/THIN_CLIENT_SWAP.md`, doc 10 §7.6
(G8d successor parity row), doc 12 §3 Q1 verdict + §4 ledger + §1 snapshot,
doc 06 row, `docs/STORAGE_BUDGET_150M.md` if sizes moved. ANY bar fails:
record the verdict, delete nothing served, v1.e5 keeps serving, STOP.

## Session end

Inventory diff (Rule Zero) must be clean. Re-read doc 12 §3 Q1 against what
was measured; every claim gets numbers + result-file path + absolute date.
Push everything.
