# E7 reclear — implement the DotVByte gate-b/c fixes + hard test protocol

**Branch:** `spike/mmap-bmp` (fork-local commit `c987160` carries the Rust edits).
**Goal:** implement the researched fixes and prove under a *pre-registered, hard
protocol* whether they reclear the two failed E7 bars (b warm p50 ≤1.07×,
c cold majflt ≤0.55×). Honest verdict either way; no promotion unless cleared
**and** parity (gate a ≥0.99) stays green.

Baseline to beat (from `data/eval_results/seismic_e7_dotvbyte_gates_20260703_0032.json`,
40 queries, shard0 twins, k′=200):

| gate | bar | f16 | dotvbyte | ratio | verdict |
|---|---|---|---|---|---|
| a parity overlap@10 | ≥0.99 | — | 0.995 | — | PASS (must stay) |
| b warm p50 | ≤1.07× | 5.823 ms | 7.123 ms | 1.223× | FAIL |
| c cold majflt | ≤0.55× | 116974 | 69148 | 0.591× | FAIL |

---

## The fixes (mapped to real edit sites)

### Fix #1 — `RUSTFLAGS="-C target-cpu=native"` rebuild  →  **gate b (primary), gate c (neutral)**
**No code change.** The decode hot loop is `vectorium_fork/src/encoders/dotvbyte_fixedu8.rs:557–640`:
`Simd::gather_select_unchecked` (l.610) + `Simd<u8,16>` shuffle-decode + `Simd::<f32,8>` `mul_add`
accumulate, all `std::simd` portable SIMD. With `RUSTFLAGS=[]` (confirmed), Rust compiles for
baseline x86-64 = SSE2 only → gather is emulated (no `VPGATHERDD`), `mul_add` has no FMA. Host is
Ryzen 7 5700X3D with `avx2`+`fma` confirmed in `/proc/cpuinfo`. `target-cpu=native` enables them.
The f16 path does far less SIMD work, so this **differentially** closes the dotvbyte warm gap.

- Rebuild: `cd spike/seismic_upstream && sudo -E env RUSTFLAGS="-C target-cpu=native" \
  /workspaces/sfu-library-thinclient/.venv/bin/python3 -m maturin develop --release`
  (editable install lands in the venv .so the gate already imports; `-E` carries RUSTFLAGS).
- **Hard proof, not hope:** `objdump -d` the rebuilt .so and grep for avx2/fma instructions in the
  dotvbyte path → must show `vpgatherdd`/`vfmadd*ps`/`ymm` that were **absent** before. If absent
  after rebuild, the rebuild failed → STOP, do not run the gate (false reclearance).
- Caveat: enabling FMA can change float rounding (fused mul-add). Gate a (overlap@10) is the
  correctness backstop — must re-pass ≥0.99 after the rebuild.

### Fix #2 — `MADV_RANDOM` on the forward files  →  **gate c (primary)**
The audit's E2, previously unrun. Forward candidate reads are ~200 B random bursts; default kernel
readahead speculatively faults extra pages around each → inflates cold majflt. `MADV_RANDOM`
disables readahead for exactly this pattern. `MADV_DONTNEED` (from `release_pages`) evicts
residency but does **not** clear the advice hint, so RANDOM persists across the gate's cold cycles.

- Edit `leak_mmap` (`src/mmap_io.rs:889`) to take a `random: bool` and `madvise(MADV_RANDOM)`
  post-map when set. Default unchanged (no advice) for all other files.
- In **both** `MmapSeismicIndex::from_mmap` (f16, l.448–457) and `MmapSeismicIndexDotVByte::from_mmap`
  (l.996–999), call `leak_mmap(.., true)` for the forward files only (offsets/components/values or
  offsets/data). Posting lists, doc-mapping slabs keep default advice.
- Scope is evidence-backed (E2 targets the forward axis); posting-list block access is more
  sequential and stays on default advice. `.so`-only.

### Fix #3 — `MADV_WILLNEED` batch per posting block  →  **gate c (secondary, CONDITIONAL)**
Only if #1+#2 leaves gate c >0.55. The current `prefetch_with_range` is a CPU cache-line prefetch —
does nothing for cold page faults. Issuing `madvise(MADV_WILLNEED)` over a block's candidate forward
ranges *before* the scoring pass turns serial blocking faults into overlapped async readahead. More
invasive (touches the search loop in `posting_list.rs`/`mmap_io.rs::search_raw`); staged last so the
cleaner fixes are measured first.

### Fix #4 — k′ 200→100  →  **both gates, SECONDARY / parameter-axis (NOT same-footing)**
E1 measured recall-safe at overlap 0.995. Decode cost scales with candidates scored, so it shrinks
the warm gap AND the fault count. But it is a **different operating point**, not a reclearance of the
pre-registered k′=200 bars. Run at the best config **separately**, labelled "different footing", so it
cannot masquerade as a same-bar reclearance.

---

## Hard testing protocol (pre-registered, deterministic)

Bars are the gate script's (unchanged): **b ≤1.07, c ≤0.55, a ≥0.99**. Fixed across all arms:
same 40 diverse queries (`data/eval_results/diverse_queries.json`, assert n==40), same shard0 twins,
WARM_REPEATS=5, `release_pages()` confirmed >0 before each cold pass, VmRSS recorded pre/post cold
to confirm eviction. Each arm writes its own timestamped json + the gate script's literal
PASS/FAIL verdict.

Additive gate-script changes (minimal, no bar-math change, keeps apples-to-apples vs 00:32):
`--build-label <str>`, `--drop-caches` (optional `sync; echo 3 > /proc/sys/vm/drop_caches` before
each cold pass when root — guarantees truly cold), and a `build` block in the result json:
`{rustflags, simd_verified (objdump bool), forward_madvise, fork_sha, main_sha, build_label}`.

| arm | config | pre-registered prediction | decision |
|---|---|---|---|
| **A control** | current .so, re-run gate | reproduce b≈1.22, c≈0.59 | env-stability anchor |
| **B native** | Fix #1 only; objdump-verify AVX2 first; cargo unit tests (parity) green | b→~1.10 (paper floor), c≈0.59 | gate b focus |
| **C native+random** | +Fix #2 (MADV_RANDOM forward) | b≈B, c→<0.55 | gate c focus |
| **D** (cond.) | +Fix #3 (WILLNEED batch) — **only if C's c>0.55** | c further down | gate c fallback |
| **E k100** | best config, k′=100 | lower b+c | reported as **different footing**, not a reclearance |

Per-arm hardening: A and B each re-run **twice**; warm p50 must be stable within ±5% across the pair
or the arm is flagged noisy (not a PASS). Parity gate a is re-checked on **every** arm — any
a<0.99 blocks promotion regardless of b/c.

Verdict rule (pre-registered): E7 recleared ⟺ some arm with `simd_verified=true` AND `a≥0.99`
hits `b≤1.07` AND `c≤0.55` at k′=200. Arm E cannot trigger reclearance.

---

## Execution order
1. `git pull` (mandatory); confirm on `spike/mmap-bmp`.
2. Implement Fix #2 only (the one code edit; Fix #1 is a rebuild flag, #3/#4 conditional). Commit +
   push in the fork (`spike/seismic_upstream`) per the git workflow.
3. Arm A (control re-run, current .so) → anchors env.
4. Rebuild (#1) → objdump-verify AVX2 → cargo unit tests → Arm B.
5. (Target .so already carries Fix #2 from step 2; Arm B used the post-#1 build.) Arm C =
   rebuild-with-#2 + run.
6. If C gate c>0.55 → implement Fix #3 → Arm D.
7. Arm E (k′=100) at best config, labelled separate.
8. Record all arm jsons under `data/eval_results/seismic_e7_*_<arm>_<ts>.json`. Update
   `docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §5/§7 with the measured per-fix
   deltas + the final same-footing verdict (per the doc-freshness rule). Commit + push.

## Out of scope here
E7b (RAM-capped bench where the f16 corpus no longer fits page cache) remains the downstream
promotion gate, as proposed last turn; this work only reclears (or fails) the two pre-registered b/c
bars on the same footing.
