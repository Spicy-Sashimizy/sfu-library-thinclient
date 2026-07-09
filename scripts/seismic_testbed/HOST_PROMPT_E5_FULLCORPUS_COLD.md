# HOST PROMPT — E5: full-federated 150M COLD benchmark, dv vs e5 (paste-ready)

Paste everything below the `---` into a Claude Code instance running **directly
on the host** (NOT inside the 32 GB dev container). This closes the one gap left
by the E5 rollout (`docs/seismic_150m_testbed/13_E5_FORWARD_REORDER_DESIGN.md`):

- **Already measured (container, single-shard):** the E5 forward reorder
  (`block_walk_canonical`) cut cold major-faults to **0.53–0.54×** and cold
  traverse p50 to **0.66–0.68×** (~1.5× faster) on shards 1 and 2 individually
  (`e5_shard_gates_20260709_{0917,2115}.json`). Parity bit-identical; served
  federated top-10 A/B exact-order.
- **2026-07-09 UPDATE — a container run of this protocol already CONFIRMED
  the federated win** (fadvise-DONTNEED eviction instead of drop_caches;
  fresh-process mmaps on 9p re-fault Linux-cold regardless): federated cold
  p50 **dv 4960/4838 ms vs e5 2687/2891 ms → 0.569 median ratio**, all
  cells VmSwap 0, warm ≪ cold — see doc 06 row + doc 13 §5,
  `data/eval_results/e5_fullcorpus_cold_container_*.json`. What that run
  could NOT do is evict the **Windows-side** file cache (symmetric across
  arms, so the ratio stands). This host run is now **optional**: run it
  only if a true-disk-cold **absolute** number is needed.

The question is narrow: **does federated cold p50 improve by ~1.4–1.5× (e5 vs
dv) at full corpus scale, with VmSwap≈0 and warm < cold?** This is NOT a
RAM-cliff sweep (E5 is quality-neutral and same-size — no cap sweep needed);
it is one clean cold A/B, dv arm vs e5 arm.

---

## ⚠️ RULE ZERO — THE SHARDS ARE IRREPLACEABLE-EXPENSIVE. READ-ONLY.

A 2026-06-30 host reboot once wiped the shards (a full day to rebuild). This
experiment touches only the two **dotvbyte** shard sets, **READ-ONLY**:

```
data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.mmap      (dv baseline, ~5.2 GB each)
data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.e5.mmap   (e5 reordered, ~5.2 GB each)
```

- **Never** copy, move, "stage", symlink, delete, or re-convert a shard dir.
  Run against the persistent paths directly. If any dir is missing or a
  manifest fails to load: **STOP and report** — do not "fix" it.
- Record the inventory before AND after; confirm byte-identical:
  ```bash
  du -sb data/seismic_150m/index/plan01/global_shard*of8.dotvbyte.mmap \
         data/seismic_150m/index/plan01/global_shard*of8.dotvbyte.e5.mmap \
    | tee /tmp/e5cold_inventory_$(date +%s).txt
  ```
- All result files go under `data/eval_results/` (tracked, persistent).

## ⚠️ RULE ONE — DO NOT TOUCH THE SHARED `.venv`

The `.venv` lives on the shared mount; editing it on the host broke the dev
container once (2026-07-03). **Do not edit anything under `.venv/` — ever.**
Run the host's own 3.11 interpreter against the venv's site-packages:

```bash
HOSTPY=/home/<user>/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11
export PYTHONPATH=$PWD/.venv/lib/python3.11/site-packages
$HOSTPY -c "import seismic; print('seismic ok')"   # must print ok — else STOP
```

(The native `.so` is linux-x86_64 cpython-3.11; if `$HOSTPY` is missing,
`uv python install 3.11` — do NOT touch `.venv`.)

## ⚠️ RULE TWO — enough RAM that VmSwap stays 0 (no cap needed)

The dv/e5 working set is ~25 GB resident (8 × ~3.1 GB) + ~1 GB SPLADE anon, so
it fits well under the project's standard clean config. Ensure the distro has
**≥ ~32 GB** available so the cold-then-warm passes never touch swap:

- `free -g` before starting. If it shows < ~32 GB total, set
  `%UserProfile%\.wslconfig` `[wsl2] memory=58GB`, `wsl --shutdown` from
  PowerShell, restart the distro (this kills every container — get operator
  approval first, as in the G8b runbook). **Revert `.wslconfig` after.**
- If `free -g` already shows ≥ ~32 GB, no reconfig is needed — proceed.

## Prereq checks (assert, don't assume)

1. `cd` to the repo checkout, branch `spike/mmap-bmp`, **`git pull` FIRST**
   (brings the e5 manifest + this runbook). Explicit `git add <files>` only —
   NEVER `git add .`.
2. Shard inventory (Rule Zero): **16 dv dirs** — 8 `.dotvbyte.mmap` +
   8 `.dotvbyte.e5.mmap`. If any is missing, STOP and report.
3. Manifests, both committed under `data/eval_results/`:
   - dv baseline: `seismic_c25_shards_150m_mmap_dotvbyte.json`
   - e5:          `seismic_c25_shards_150m_mmap_e5.json`
   Each must have `n_shards: 8` and 8 shard records; the e5 one's shard
   `mmap_dir`s must end in `.dotvbyte.e5.mmap`.
4. `$HOSTPY` + PYTHONPATH import check (Rule One); `ls models/splade_onnx_fp16`
   (the bench encodes queries in-process — the encoder is symmetric across
   both arms, so it doesn't affect the dv-vs-e5 delta).

## The cells (drop_caches before EVERY cell; 2 alternating reps)

`BENCH=scripts/seismic_testbed/serve_footprint_bench.py`. `--passes 3` gives
pass 0 = COLD (the headline) + passes 1–2 = warm. Run dv and e5 alternately,
twice, dropping the page cache before each so every cold pass truly faults
from disk. Result files: `data/eval_results/e5_fullcorpus_cold_{dv,e5}_rep{1,2}.json`.

```bash
HOSTPY=/home/<user>/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11
export PYTHONPATH=$PWD/.venv/lib/python3.11/site-packages
BENCH=scripts/seismic_testbed/serve_footprint_bench.py
MAN_DV=data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json
MAN_E5=data/eval_results/seismic_c25_shards_150m_mmap_e5.json

sudo swapoff -a || echo "swapoff denied — check vmswap_gb in each JSON instead"

for REP in 1 2; do
  for ARM in dv e5; do
    MAN=$([ $ARM = dv ] && echo $MAN_DV || echo $MAN_E5)
    sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'   # evict page cache -> real cold
    $HOSTPY $BENCH --shard-manifest $MAN --queries 40 --passes 3 \
      --federation parallel \
      --result-file data/eval_results/e5_fullcorpus_cold_${ARM}_rep${REP}.json
  done
done

# Optional (only if time allows): sequential federation, e5 arm — the
# localized-deploy path. Same drop_caches discipline.
sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'
$HOSTPY $BENCH --shard-manifest $MAN_E5 --queries 40 --passes 3 \
  --federation sequential \
  --result-file data/eval_results/e5_fullcorpus_cold_e5_sequential.json
```

Notes:
- **Alternate dv/e5** (the loop does) so any host drift hits both arms equally;
  the load-bearing figure is the **paired dv-vs-e5 cold p50 ratio**, not either
  absolute value.
- Do NOT set `SFU_SEISMIC_SHARD_MANIFEST` — pass the manifest explicitly with
  `--shard-manifest` so each cell serves the intended arm.
- Each cell: cold pass faults ~25 GB from disk (drvfs), so pass 0 may take
  minutes; passes 1–2 are warm. That's expected.

## Pre-registered predictions + decision rule (write BEFORE looking at results)

| quantity | prediction |
|---|---|
| dv federated cold p50 @150M | the baseline (first clean full-corpus cold number) |
| e5 federated cold p50 @150M | **~0.65–0.75× of dv** — the per-shard 0.66–0.68× carries because parallel federation ≈ slowest shard + merge, and every shard improves ~equally |
| warm p50 (both) | ≈ equal, tens of ms (E5 is warm-neutral) |
| VmSwap (both) | ≈ 0 (working set fits) |

- **Verdict gate (the bench's own `_latency_caveat`):** a cold number is a
  VERDICT only if `vmswap_gb ≈ 0` AND warm p50 < cold p50 in that JSON. If
  either arm shows VmSwap > 0 or warm ≥ cold, that cell is swap-/cache-
  confounded — record it, don't conclude from it, and note the host needs more
  RAM (Rule Two).
- **The E5 claim is CONFIRMED at federated 150M scale iff** the median e5 cold
  p50 (over reps 1–2) is materially below dv's (target ≤ ~0.80×, matching the
  per-shard win within federation overhead) on clean (unconfounded) cells.
- **If e5 cold p50 ≈ dv (no federated win despite the per-shard win):** that is
  a real finding — it would mean federation overhead (thread fan-out, GIL merge)
  dominates the cold path and masks the per-shard page savings. Record it
  honestly; it points the next lever at the fan-out, not the layout.

## Handoff

1. Re-verify the Rule Zero inventory (must be byte-identical).
2. Commit ONLY the new result JSONs:
   `git add data/eval_results/e5_fullcorpus_cold_*.json && git commit && git push`.
   If push auth is missing on the host, commit locally and say so.
3. Do NOT edit docs — the container session writes the doc-13 / 06 verdict
   from your JSONs (report the dv and e5 cold p50 medians + the ratio +
   each cell's vmswap_gb and warm-vs-cold, so the confound gate can be applied).
4. Revert `.wslconfig` if you changed it (Rule Two) and restart the containers.
