# SEISMIC open items + G8 compression lever — single tracking doc

**Created 2026-07-01.** Canonical tracker for the post-G6/G7/G8-clean state:
what's closed, what's open, what blocks what, and the compression idea
reframed as the G8 RAM-residency lever (now wired so it's testable on the
Windows run). Supersedes the scattered open-gate notes in conversation — this
is the on-disk single source of truth.

Source-of-truth hierarchy (CLAUDE.md): the **code** is right; for gate
verdicts the canonical detail lives in `docs/seismic_150m_testbed/`
(`02_GO_NO_GO_GATES.md`, `06_FINDINGS.md`, `08_LATENCY_RESEARCH.md`). This doc
summarizes state + the dependency spine; numbers are dated and point at the
result files / docs that hold them.

---

## ✅ Closed (no action — reference only)

- **G1 build**, **G4 pruning sub-linearity** (the decisive gate), **G7 150M
  build** (serial K=8 sharding, no-OOM on 32 GB), **G8 RAM-half** (anon floor
  0.14 GB vs Qdrant 6.71 GB).
- **G2 quality leg — FAIL at 0.479 overlap**, proven non-recoverable on all
  three index-time lever axes (per-list-cap, global-budget, centroid-density);
  accepted as a structural leg-level floor, **superseded by the system-level G6
  verdict**.
- **G6 RRF parity — PASS** (re-scoped to paired-delta 2026-06-30): SEISMIC
  0.9262 vs Qdrant 0.9065, paired Δ=+0.0197, n=120, CI clears zero. Retires the
  old "INCONCLUSIVE at persona" state. Quality is NO LONGER the open risk.
- **G5 persona latency — SIGNAL-PASS 2026-07-01**: leg p50 58.20 ms ≤ 66 ms Qdrant
  ref (n=34, swap-tainted — the real win is SEISMIC's anon floor surviving the
  swap storm that wrecked Qdrant's 66→13,930 ms). Tail exceeds 66 ms; not
  "sub-ms" (that was a micro-bench conflation, corrected). SIGNAL, not HARD —
  superseded by G8-latency at 150M.
- **K=8 persistent rebuild** — 150,413,098 docs, verified, survives /tmp wipes.
- **Sequential vs parallel footprint** — measured 2026-07-01: RAM ✅ (anon
  floor ~1 GB both), latency IO-bound TIE (~15.8 s p50, warm≈cold) because the
  62 GB mmap index > page cache on the 32 GB host → re-fault each pass. The
  "sequential sums a small traverse term" thesis REFUTED at 150M here;
  remediation is a no-swap host (Tier 2 #5), NOT federation-mode.

---

## 🔲 Open gates

| # | Item | State | Blocks |
|---|------|-------|--------|
| **G8-latency** | 150M served p50 in a usable band | ❌ IO-bound ~15.8 s on 32 GB box (working set 62 GB > RAM). This is the single pivotal remaining verdict. The 58 GB-cap run already proved the engine is fast when provisioned (warm ~0.5–0.7 s) — the open question is whether the **compression lever** (below) lets a smaller host reach that without a bigger box. | The Windows-host bench (it resolves G8-latency one way or the other) |
| **G5** | Persona warm p50 ≤ Qdrant 66 ms | ✅ **SIGNAL-PASS (numerically), swap-tainted — MEASURED 2026-07-01.** Persona leg p50 **58.20 ms** (n=34, 2M med_bio, end-to-end `seismic_lat_ms` from `seismic_parity_persona_2m.json`) vs **66 ms** Qdrant ref → p50 clears the bar. **Caveats:** (1) swap-thrashing host (Qdrant leg p50 13,930 ms same run) → NOT no-swap clean; the real signal is "SEISMIC's ~0.14 GB anon floor survived the storm that wrecked Qdrant's 66→13,930 ms." (2) Tail (p95 131 / max 134 ms) exceeds 66 ms — only p50 clears. **NOT "sub-ms"** — the 0.441 ms is the bare mmap-traversal micro-bench, not the leg; the prior "sub-ms warm at G4" note in this doc was wrong (corrected). Traversal-only G4 p50 was 13.93 ms @0.93M / 14.56 ms @2M. Closed (SIGNAL, not HARD; superseded by G8-latency at 150M). See `02_GO_NO_GO_GATES.md` G5 row. | nothing |
| **G9** | Ownership / build-vs-buy (Path C cost vs no-JVM value) | ⬜ analysis only; gated on the G8-latency numbers. | the final decision |

---

## 🔲 Open build / productionization tasks

| # | Item | State |
|---|------|-------|
| **K=16 build** | Experimental K=16 shard index | ✅ **BUILT 2026-07-02** (G7 verdict PASS): 16/16 shards OK, 150,413,098 docs (exact match to K=8 corpus), peak RSS **6.09 GB/shard** (vs K=8's 9.93 — K=16 cuts per-shard RAM ~39%, ~3× under the 20 GB budget), 75.99 GB on-disk total (vs K=8's 66.26; ~15% larger from fixed overheads amortized over smaller shards), ~620 s/shard × 16 ≈ 2.8 hr. Stage 1 (shard) 2.4 hr, Stage 2 (build) 2.8 hr. Manifest `data/eval_results/k16/seismic_plan01_shards_k16.json` + per-shard `build_global_shard{0..15}.json` + logs `k16_stage{1,2}_*.log`. Source G7 `.index.seismic` on `/tmp` scratch (regenerable). **NOT served/converted to mmap yet** — this is the robustness experiment, not the served path; conversion + a federation-overlap re-gate would follow only if a K=16 serve is wanted. |
| **Tier 2 #5** | Boot-time pre-fault + mlock + encoder warm-up | deferred; **conditional on G8 outcome** (the compression cell may avoid needing this). |
| **Tier 2 #6** | Wire shard build (shard→build→mmap) into the monthly rebuild pipeline | deferred until G8/G9 say "ship". |
| **Tier 3 #7/#8** | Flip the env-var default to SEISMIC + land deploy config (the cutover) | deferred — **the finish line**. |

### Dependency spine

```
G8-latency (Windows bench) ──► G9 decision ──► #6 pipeline ──► #7/#8 cutover = DONE
        ▲
   compression cell (new, wired 2026-07-01)
```

Everything downstream hinges on the **single G8-latency measurement on a host
that can actually run the cells**. The compression lever is the new,
non-blocked way to attack that measurement without buying a bigger box.

---

## 🧪 Compression idea → G8 RAM-residency lever (NEW — wires into the G8 bench)

**Framing correction:** this is a **RAM-residency lever**, NOT a storage
compression lever. Disk isn't the constraint (the index is file-backed mmap
that faults in on demand); the constraint is **how much of the working set
stays resident** on a host whose RAM < the 62 GB index.

### Why file compression is OUT (checked, set aside)
- **Whole-file zstd** breaks mmap (forces full-shard owned-anon load = RAM
  blowup → re-introduces the Path-A floor G3 killed).
- **Transparent FS compression** (chattr +c / NTFS compression) leaves the
  *decompressed resident set* unchanged on a fault — it touches the on-disk
  bytes, not the resident-page count, and adds per-fault CPU. Doesn't address
  the actual constraint.

### The idea worth testing: owned-anon load + memory compression
Load the index as **owned-anonymous** (Path A, `SFU_SEISMIC_LOAD_MODE=stock`)
instead of file-backed mmap, **with a compressed-RAM regime enabled**:
- Linux: **zram** (a compressed-RAM block device used as swap) or **zswap**
  (frontswap compression in front of backing swap).
- Windows: **memory compression** (on by default in modern Windows / WSL2).

Anonymous pages under a compressed-RAM regime get compressed **in RAM** (~2–3×,
decompress at multiple GB/s) instead of being paged out. This could convert a
~15 s disk re-fault (file-backed pages dropped from page cache, re-read from
the vhdx) into a ~µs CPU decompress — potentially making 150M serve usably
**without a bigger host**. The crucial difference from file-backed mmap: an
owned-anon page, once compressed to zram/zswap, stays in RAM (just smaller);
a file-backed page, once evicted, must re-fault from disk.

### The 2×2 to measure (on the Windows host that resolves G8)

|              | mem-compression OFF | mem-compression ON |
|--------------|---------------------|--------------------|
| **file-backed mmap** (Path C, `load_mode=mmap`) | the 15.8 s disk re-fault baseline (already measured) | moot — file pages don't compress; expected ≈ baseline |
| **owned-anon** (Path A, `load_mode=stock`) | OOMs / swaps to disk swap at 150M (the Path-A floor G3 killed) | **the candidate win** — anon compressed in RAM, ~2–3× effective resident |

Windows memory compression being default-on means **one cell may already be
"free"** — the operator just runs the stock cell on Windows and reads whether
VmSwap pages are compressed (verdict) vs disk-re-faulted (confound).

### ✅ Wiring status — SHIPPED 2026-07-01 (commit `219c7e1`)
The bench already supported the **load axis** via
`SFU_SEISMIC_LOAD_MODE` (`mmap`=Path C file-backed, `stock`=Path A owned-anon).
This session added the **compression axis** + its gating, so the 2×2 runs honest:

- **`detect_memcompression()`** in
  `scripts/seismic_testbed/serve_footprint_bench.py` — resolves the host's
  anon-page regime (`zram`/`zswap`/`windows_compression`/`disk_swap`/`off`/
  `unknown`) from `/proc`, honoring an operator **`SFU_MEMCOMPRESSION_REGIME`**
  override for the Windows-host case `/proc` can't see. Recorded in the result
  JSON `meta.g8_matrix_cell`.
- **`_latency_caveat()` verdict gate is now regime-aware** — the load-bearing
  fix: under zram/zswap/windows_compression, `VmSwap>0` is the compressed-in-RAM
  mechanism (a VERDICT, decompress at GB/s), NOT the disk re-fault confound the
  old gate flagged it as. Without this fix the stock+zram cell would be
  mislabeled "not a verdict" and the lever would look dead when it worked.
  The 'mmap index exceeds page cache' (warm>=cold) symptom is gated on
  `load_mode=='mmap'` (owned-anon has no file-backed page cache to exceed).
- **14 unit tests** (`scripts/tests/test_serve_footprint_g8_matrix.py`) pin
  the gate's behavior across all matrix cells.

### How to run the four cells (on the Windows host)
```bash
# cell (mmap, off)        — the disk-re-fault baseline:
SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 scripts/seismic_testbed/serve_footprint_bench.py \
    --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json --queries 40 --passes 2 \
    --result-file data/eval_results/seismic_g8_cell_mmap_off_<date>.json

# cell (stock, windows_compression)  — THE candidate win (assert the regime
#   /proc can't see; Windows compression is default-on so no host change needed):
SFU_SEISMIC_LOAD_MODE=stock SFU_MEMCOMPRESSION_REGIME=windows_compression \
    .venv/bin/python3 scripts/seismic_testbed/serve_footprint_bench.py \
    --shard-manifest data/eval_results/seismic_c25_shards_150m_mmap.json --queries 40 --passes 2 \
    --result-file data/eval_results/seismic_g8_cell_stock_wincomp_<date>.json
```
(on Linux, swap `windows_compression` for `zram` after enabling a zram device,
or `zswap`; the gate reads whichever the host reports).

### Expected interpretation
- If the **stock+zram/wincomp cell** gives warm p50 in the usable band (≈ the
  0.5–0.7 s the 58 GB mmap run achieved, or better) with `VmSwap>0` flagged as
  **compressed-in-RAM verdict** → the G8-latency gate CLEARS **without a bigger
  box**: ship the owned-anon + memory-compression config. G9 then weighs the
  Path-C build cost vs this (cheaper) Path-A-with-compression win.
- If the stock cell still re-faults (warm≈cold, large p50) AND `VmSwap` reads
  as disk (regime not compressed) → memory compression isn't enough; the
  no-swap-host / pre-fault+mlock (Tier 2 #5) or a bigger box remains the only
  resolution, and G9 routes to Path C vs bigger-Qdrant-box as before.

### Bigger-lift alternative (NOTE ONLY → G9 / Path C, not for this spike)
A **succinct / Elias-Fano compressed index format** would genuinely shrink the
resident set and is queryable-while-compressed, but requires forking SEISMIC's
build + traversal — not a config knob. Tracked as a Path-C design option for G9,
not actionable here. (See `docs/seismic_150m_testbed/08_LATENCY_RESEARCH.md`
§B1 DotVByte / §B2 4-bit summary quant — design-only, not in our Rust reader.)

### Orthogonal freebie
`zstd` the shard tarball for the host→Windows transfer (~2× smaller copy of
the 66 GB index), decompress once on arrival back to native mmap layout.
Doesn't affect serving; just makes the transfer cheaper.

---

**Net:** the compression angle is reframed as a G8 **RAM-residency lever**,
its one cheap testable form (owned-anon + memory-compression) is **wired and
regression-tested**, and it slots into the same Windows bench that decides
G8-latency. The next action on this lever is the operator's Windows run.
