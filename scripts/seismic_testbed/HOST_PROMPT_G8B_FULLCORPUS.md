# HOST PROMPT — G8b: full-corpus f16-vs-dotvbyte serve bench @ 58 GB (paste-ready)

Paste everything below the `---` into a Claude Code instance running **directly
on the host** (NOT inside the dev container). This is the full-corpus successor
to E7b (`docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §7.5):
E7b confirmed per-shard that dotvbyte survives a cap where f16 cliffs; G8b
answers the two remaining questions **at full 150M corpus scale**:

1. **The clean G8 f16 baseline** (owed since 2026-06-29: every prior G8
   latency number was swap-confounded) — uncapped at 58 GB, where the 41.4 GiB
   f16 working set (8 × 5.18 GiB measured, E7b) finally fits.
2. **The deploy verdict for the 32 GB box**: capped cells emulating the
   container host, where f16 can never fit and dotvbyte's ~24.8 GiB
   (8 × 3.10 GiB *est.* from shard0) should.

The operator has EXPLICITLY approved the `wsl --shutdown` / 58 GB reconfig for
this run (it kills every container, including sfu-library-mcp).

---

## ⚠️ RULE ZERO — THE SHARDS ARE IRREPLACEABLE-EXPENSIVE. DO NOT TOUCH /tmp.

On 2026-06-30 a host reboot wiped `/tmp/seismic_testbed/` and destroyed all
8 served shards + sources (66 GB, a full day to rebuild). Everything now lives
at the persistent path and this experiment uses it **READ-ONLY**:

```
data/seismic_150m/index/plan01/global_shard{0..7}of8.mmap            (f16, ~8.3 GB each)
data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.mmap   (dv,  ~5.5 GB each)
```

- **Never** copy, move, "stage", or symlink shards into /tmp or any
  tmpfs/overlay path. Run against the persistent paths directly.
- **Never** delete, rebuild, or re-convert a shard dir. If one is missing or a
  manifest fails to load: **STOP and report** — do not "fix" it.
- Before starting AND after finishing, record the full inventory and confirm
  byte-identical:
  ```bash
  du -sb data/seismic_150m/index/plan01/global_shard*of8.mmap \
         data/seismic_150m/index/plan01/global_shard*of8.dotvbyte.mmap \
    | tee /tmp/g8b_inventory_$(date +%s).txt
  ```
- All result files go under `data/eval_results/` (tracked, persistent).

## ⚠️ RULE ONE — DO NOT TOUCH THE SHARED `.venv` (this broke the container once)

On 2026-07-03 the E7b host session repointed `.venv/pyvenv.cfg` + the
`python3.11` symlink at a host-only uv path (`/home/<user>/.local/share/uv/...`).
The `.venv` lives on the shared mount, so that **broke the dev container's
MCP server and bench tooling** until it was restored on 2026-07-04. The
container-correct config is back in place (`home = /usr/bin`, symlink →
`/usr/bin/python3.11`); the host uv variant is preserved at
`.venv/pyvenv.cfg.host-uv` for reference. **Do not edit anything under
`.venv/` on the host — ever.** Instead, run the host's own 3.11 interpreter
against the venv's site-packages via PYTHONPATH:

```bash
# the uv-managed 3.11 installed for E7b on 2026-07-03:
HOSTPY=/home/<user>/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11
export PYTHONPATH=/path/to/repo/.venv/lib/python3.11/site-packages
$HOSTPY -c "import seismic; print('seismic ok')"   # must print ok — else STOP
```

(The native `.so` is built for linux-x86_64 cpython 3.11; both interpreters
load it. If `$HOSTPY` is missing: `uv python install 3.11` — do NOT touch
`.venv`.)

## ⚠️ RULE TWO — the 58 GB reconfig and what it kills

The `wsl --shutdown` step kills **every WSL distro and every container**
(sfu-library-mcp, qdrant, the dev container). The operator approved this for
G8b. Sequence, from **PowerShell on Windows**:

1. Confirm no container-side work is running first (ask the operator; also
   `pgrep -f convert_f16` and `pgrep -f serve_footprint` inside the distro
   must be empty).
2. Edit `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   memory=58GB      # the practical host max (clean 2026-06-30 G8 RAM verdict)
   ```
3. `wsl --shutdown`, restart the Ubuntu distro, `free -g` must show ~58 total.
4. **After the whole run**: revert `.wslconfig` to the previous value (or
   remove the line) and `wsl --shutdown` again, then restart the containers /
   Docker Desktop so sfu-library-mcp comes back.

## Prereq checks (assert, don't assume)

1. `cd` to the repo checkout, branch `spike/mmap-bmp`, `git pull` FIRST
   (brings the dotvbyte manifest + this runbook). Explicit `git add <files>`
   only — NEVER `git add .`.
2. Shard inventory (Rule Zero): **16 dirs** — 8 f16 + 8 dotvbyte. If any
   `global_shard{1..7}of8.dotvbyte.mmap` is missing, the container-side
   conversion didn't finish — STOP and report.
3. Manifests, both committed under `data/eval_results/`:
   - f16: `seismic_c25_shards_150m_mmap.json`
   - dv:  `seismic_c25_shards_150m_mmap_dotvbyte.json`
4. `free -g` shows ~58 GB (Rule Two done).
5. Cap mechanism: `sudo systemd-run --scope -p MemoryMax=28G -p MemorySwapMax=0 -- true`
   must succeed.
6. `$HOSTPY` + PYTHONPATH import check (Rule One). Also
   `ls models/splade_onnx_fp16` — the bench encodes queries in-process.

## The cells (run in this order; drop_caches before EVERY cell)

`BENCH=scripts/seismic_testbed/serve_footprint_bench.py`, common flags:
`--queries 40 --passes 3 --federation parallel`. Result files:
`data/eval_results/g8b_fullcorpus_{f16,dv}_{uncapped58,cap32G,cap28G,cap24G}.json`.

```bash
HOSTPY=/home/<user>/.local/share/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11
export PYTHONPATH=$PWD/.venv/lib/python3.11/site-packages
BENCH=scripts/seismic_testbed/serve_footprint_bench.py
MAN_F16=data/eval_results/seismic_c25_shards_150m_mmap.json
MAN_DV=data/eval_results/seismic_c25_shards_150m_mmap_dotvbyte.json

# ── Cell A: clean G8 f16 baseline (THE owed number) — uncapped, swap off ──
sudo swapoff -a || echo "swapoff denied — check vmswap in the JSON instead"
sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'
$HOSTPY $BENCH --shard-manifest $MAN_F16 --queries 40 --passes 3 \
  --federation parallel \
  --result-file data/eval_results/g8b_fullcorpus_f16_uncapped58.json

# ── G8c warm matrix, f16 arm — RUN NOW while the f16 cache is hot ──
# (doc 11 Tier 1: k′/query_cut/heap_factor cells, ~2 min each; skipping this
# wastes the cold fill you just paid for)
HOSTPY=$HOSTPY ./scripts/seismic_testbed/g8c_warm_matrix.sh f16

# ── Cell B: dv uncapped control (expect ≈ warm parity with A) ──
sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'
$HOSTPY $BENCH --shard-manifest $MAN_DV --queries 40 --passes 3 \
  --federation parallel \
  --result-file data/eval_results/g8b_fullcorpus_dv_uncapped58.json

# ── G8c warm matrix, dv arm — same deal, dv cache is hot ──
HOSTPY=$HOSTPY ./scripts/seismic_testbed/g8c_warm_matrix.sh dv

# ── Cells C/D/E/F: the capped 32 GB-box emulation ──
# 28G first (decisive), then 32G (generous), then 24G dv only (dv's own cliff).
for CAP in 28G 32G; do
  for ARM in f16 dv; do
    MAN=$([ $ARM = f16 ] && echo $MAN_F16 || echo $MAN_DV)
    sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'
    sudo systemd-run --scope --same-dir --uid $(id -u) --gid $(id -g) \
      -p MemoryMax=$CAP -p MemorySwapMax=0 \
      env PYTHONPATH=$PYTHONPATH \
      $HOSTPY $BENCH --shard-manifest $MAN --queries 40 --passes 3 \
        --federation parallel \
        --result-file data/eval_results/g8b_fullcorpus_${ARM}_cap${CAP}.json
  done
done
sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'
sudo systemd-run --scope --same-dir --uid $(id -u) --gid $(id -g) \
  -p MemoryMax=24G -p MemorySwapMax=0 \
  env PYTHONPATH=$PYTHONPATH \
  $HOSTPY $BENCH --shard-manifest $MAN_DV --queries 40 --passes 3 \
    --federation parallel \
    --result-file data/eval_results/g8b_fullcorpus_dv_cap24G.json

# ── G8c Tier-2: sequential-federation cells, run LAST (they destroy cache
#    state anyway). Includes H5, the localized-deploy cell: full corpus,
#    sequential, dotvbyte, inside a 6 GB cap. See doc 11.
HOSTPY=$HOSTPY ./scripts/seismic_testbed/g8c_warm_matrix.sh seq
```

Notes:
- The SPLADE ONNX encoder runs **inside** the capped process in every capped
  cell — symmetric between arms, so the comparison stands; its ~1–2 GB anon is
  why the deploy-emulation cap is 28G rather than 27G. If a capped f16 cell is
  OOM-killed by the cgroup instead of thrashing, that IS the result — record
  "OOM at cap" and move on; do not raise the cap to "help" it.
- The f16 cells at 28G/32G are expected to thrash (working set 41.4 GiB).
  40 queries × 3 passes may take tens of minutes per cell. If a single pass
  exceeds ~90 min, kill THAT cell, record "timeout, thrash-bound", and
  continue — the cliff is already demonstrated by the partial pass data.

## Pre-registered predictions + decision rules (write BEFORE looking at results)

| cell | prediction (from E7b shard0 ×8 *est.*) |
|---|---|
| A f16 @58 uncapped | fits (41.4 GiB < 58); warm p50 = THE clean G8 number |
| B dv @58 uncapped | fits; warm p50 ≈ A (E7 gate b 0.957× native) |
| C f16 @28G | CLIFF or OOM (41.4 GiB ≫ 28) |
| D dv @28G | fits (~25 GiB file + ~2 anon); warm, majflt→0 — **decisive** |
| — f16/dv @32G | f16 still cliffs; dv comfortable |
| — dv @24G | dv's own cliff (locates the floor) |

- **Clean-G8 rule:** cell A is a verdict iff `vmswap ≈ 0` AND warm p50 < cold
  p50 (the wrapper-script criteria from `run_g8_latency_noswap.sh`). Record
  the encode/traverse split.
- **Deploy rule (the §7.5 rule at corpus scale):** dotvbyte is confirmed for
  the 32 GB box iff at 28G dv's warm passes are clean (majflt/pass → ~0, p50
  within ~2× of its uncapped warm) while f16 has cliffed/OOMed. If dv ALSO
  cliffs at 28G, the aggregate estimate was optimistic → record honestly; the
  fallback deploy is sequential federation (one shard resident), which E7b
  already covers.
- **Discard any cell with `vmswap > 0`** in the result JSON (swap-confounded,
  the G8 §A1 lesson) — capped cells have `MemorySwapMax=0` so this should
  only ever threaten cells A/B if `swapoff` was denied.

## Handoff

1. Re-verify the Rule Zero inventory (must be byte-identical).
2. Commit ONLY the new result JSONs:
   `git add data/eval_results/g8b_fullcorpus_*.json data/eval_results/g8c_*.json && git commit && git push`.
   If push auth is missing on the host, commit locally and say so.
3. Do not edit docs — the container session writes the doc-10 / 08 / 06
   verdicts from your JSONs.
4. Revert `.wslconfig` (Rule Two step 4) and restart the containers.
