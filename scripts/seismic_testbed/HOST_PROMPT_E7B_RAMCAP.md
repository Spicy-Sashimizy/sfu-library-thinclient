# HOST PROMPT — E7b: the RAM-capped f16-vs-dotvbyte re-bench (paste-ready)

Paste everything below the `---` into a Claude Code instance running **directly
on the host** (NOT inside the dev container — verified 2026-07-03: the container
has `/sys/fs/cgroup` mounted read-only, no docker daemon, and WSL2 denies
`swapoff`, so a hard memory cap is impossible there). This is the decisive open
experiment for the E7 compressed-forward track
(`docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §7.4).

---

## ⚠️ RULE ZERO — THE SHARDS ARE IRREPLACEABLE-EXPENSIVE. DO NOT TOUCH /tmp.

On 2026-06-30 a host reboot wiped `/tmp/seismic_testbed/` and destroyed all
8 served shards + sources (66 GB, a full day to rebuild — see
`docs/seismic_150m_testbed/REBUILD_TO_PERSISTENT_PATH.md`). They now live at
the **persistent** path and this experiment uses them **READ-ONLY**:

```
data/seismic_150m/index/plan01/global_shard0of8.mmap            (f16, 8.1 GB)
data/seismic_150m/index/plan01/global_shard0of8.dotvbyte.mmap   (dv,  5.4 GB)
```

- **Never** copy, move, "stage", or symlink shards into /tmp or any
  tmpfs/overlay path. Run against the persistent paths directly.
- **Never** delete, rebuild, or re-convert a shard dir. If a shard is missing
  or a manifest fails to load: **STOP and report** — do not "fix" it.
- Before starting AND after finishing, record the inventory and confirm it is
  unchanged:
  `du -sb data/seismic_150m/index/plan01/global_shard0of8{,.dotvbyte}.mmap`
  (measured 2026-07-03: **8,277,845,060** and **5,505,939,180** bytes — must
  match exactly before and after; the bench is read-only).
- All result files go under `data/eval_results/` (tracked, persistent).

## ⚠️ RULE ONE — CONTAINER SAFETY & CONCURRENCY

- Nothing in the E7b sweep kills or restarts the dev containers: the cgroup
  cap wraps ONLY the bench process (if it exceeds the cap, the cgroup OOM
  killer takes the bench python, nothing else), and `drop_caches` merely
  causes a brief system-wide re-fault slowdown.
- **Exception:** `wsl --shutdown` (bottom section, 58 GB reconfig) kills every
  WSL distro and every container. It is NOT part of E7b — do not run it as
  part of this sweep.
- **Concurrency:** the host and the containers share one WSL2 VM (one RAM
  pool, one page cache). `drop_caches` will CORRUPT any benchmark running
  inside a container at that moment, and container benchmarks (~12 GB RSS)
  perturb this sweep. **Confirm no container-side benchmark (E7 gates, math-arc
  Stage 2, G8) is running before starting** — ask the operator if unsure.

## Prereq checks (assert, don't assume)

1. `cd` to the repo (`/workspaces/sfu-library-thinclient` or the host's
   checkout of it), branch `spike/mmap-bmp`, and `git pull` FIRST (project
   workflow: pull → work → explicit `git add <files>` → commit → push; NEVER
   `git add .` — the tree carries multi-GB runtime state).
2. Shard inventory (Rule Zero above). If either dir is absent — STOP.
3. `free -h` — need ≥ ~12 GB free RAM (the largest capped run is 8 GB + slack).
   **The current 32 GB WSL2 config is sufficient — no `.wslconfig` change is
   required for E7b.** (See "WSL2 RAM notes" at the bottom for the only case
   that needs more.)
4. A cap mechanism, in preference order — test which works and say which you used:
   - `systemd-run --scope -p MemoryMax=6G -p MemorySwapMax=0 -- true` (cgroup v2)
   - `docker run --rm --memory=6g --memory-swap=6g alpine true` (daemon present?)
   - If NEITHER works on the host either: STOP and report — do not improvise a
     cap by ballooning memory or editing kernel knobs.
5. The pre-encoded queries are **already committed** —
   `data/eval_results/e7b_encoded_queries.json` (git pull brings them). Do NOT
   re-run `--encode-only` unless that file is missing.
6. The venv python must import the native module:
   `.venv/bin/python3 -c "import seismic; print('ok')"` — if this fails on the
   host, STOP and report (the .so is built for the container's glibc/python;
   the fallback is running the capped sweep from inside WSL2's distro shell
   where the container volume is mounted, not rebuilding anything).

## The sweep (one codec per capped process, same cap, 6G first)

```bash
PY=.venv/bin/python3
BENCH=scripts/seismic_testbed/e7b_ramcap_bench.py
P=data/seismic_150m/index/plan01

for CAP in 6G 8G 4G; do            # 6G is the decisive cell — run it first
  for DIR in global_shard0of8.mmap global_shard0of8.dotvbyte.mmap; do
    sudo sh -c 'echo 1 > /proc/sys/vm/drop_caches'   # no inherited residency
    sudo systemd-run --scope --same-dir --uid $(id -u) --gid $(id -g) \
      -p MemoryMax=$CAP -p MemorySwapMax=0 \
      $PY $BENCH --index-dir $P/$DIR --passes 4 --cap-label $CAP \
        --result-file data/eval_results/e7b_$(basename $DIR .mmap)_cap${CAP}.json
  done
done
```

(If using docker instead: bind-mount the repo read-write for
`data/eval_results/` but treat the shard paths as read-only —
`--memory=$CAP --memory-swap=$CAP` is the equivalent pair of flags.)

Cap-choice rationale:

| cap | f16 (6.74 GB forward) | dotvbyte (3.97 GB forward) |
|---|---|---|
| 8G | barely fits — mild pressure | fits whole — control point |
| **6G** | does NOT fit — the hypothesis regime | fits (5.38 GB dir < 6G) — **decisive** |
| 4G | cliffed | pressured too — locates dv's own cliff |

## What decides it + handoff

- Read `passes[1..]` of each JSON (pass 0 is the cold fill). **Promotion is
  justified** iff at 6G f16 has cliffed (pass≥1 p50 ≫ ~2 ms warm, majflt stays
  high) while dv has not (p50 near warm, majflt/pass → ~0). The pre-registered
  rule is doc 10 §7: "promotion is justified for RAM-constrained deploys
  regardless of gate (b)".
- **Discard any cell with `meta.swap_confounded: true`** (VmSwap>0) — the G8
  §A1 lesson; `MemorySwapMax=0` should prevent it, but check every JSON.
- Re-verify the shard inventory (Rule Zero), then commit ONLY the new result
  JSONs: `git add data/eval_results/e7b_*.json && git commit && git push`.
  Do not edit docs — the container session writes the §7.4 E7b verdict from
  your JSONs.

## WSL2 RAM notes (only if a bigger bench is also wanted)

E7b itself needs **no** `.wslconfig` change at the current 32 GB. The ONLY
bench class that needs more is a **full-corpus** G8-style serve run (all
8 shards, ~62 GB working set): for that, set in Windows
`%UserProfile%\.wslconfig`:

```ini
[wsl2]
memory=58GB      # the practical host max used for the clean 2026-06-30 G8 verdict
```

then `wsl --shutdown` from PowerShell and restart. Revert afterwards if the
host needs the RAM back. Do NOT do this for E7b — the capped cells are the
experiment; extra free RAM changes nothing inside the cgroup.
