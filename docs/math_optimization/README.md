# docs/math_optimization/ — SEISMIC dot-kernel math & ISA-portability

**Status:** DEFERRED 2026-09-25 (M2 measured but NOT promoted - it failed its pre-registered bar; M6-M10 pre-registered and unfrozen)

> **Status (2026-07-03):** research/pre-gate track. The native rebuild
> (E7 Arm E1) already closed the math gate (gate b). The work in this section
> investigates **deeper math restructuring** for the SEISMIC per-candidate
> scoring kernel, gated on cheap Python pre-gates before any Rust edit.
> **Not on the served path.** Source-of-truth for current state:
> `docs/THIN_CLIENT_SWAP.md` (architecture) and `docs/seismic_150m_testbed/`
> (the E6/E7 compressed-forward + mmap-serving track this builds on).

This section documents the **mmap/SEISMIC matrix-math optimization arc**: what
the per-candidate dot-product actually is, the measured corpus quirks that
justify restructuring it, the interaction map of what a math change touches,
the **x86→ARM (aarch64 / Apple Silicon / iPhone) ISA-portability discipline**,
and the staged, pre-registered testing protocol.

## Documents

| Doc | What it is |
|---|---|
| `00_CONTEXT_AND_CORRECTIONS.md` | What this arc is, the corrections to earlier framing (math gate is GREEN, the failure is memory), and the source-of-truth hierarchy |
| `01_KERNEL_AND_MATH_MAP.md` | The grounded kernel map: `DotVbyteFixedu8::dot_product` line-by-line, the three "thirds" (decode/gather/arith), the data types, the layout asymmetry, the objdump evidence (vpgatherdd=0), the build config |
| `02_DB_QUIRKS_JUSTIFYING_MATH_CHANGES.md` | The measured corpus properties (doc values ≤3.25 & non-negative, nnz mean 87.6, FixedU8Q fidelity 0.995, query cap 64, BMP u8×u8 precedent) that make integer-dot and query-shrink viable |
| `03_INTERACTION_MAP.md` | What each math change (M1–M5) touches in files, whether it forces a shard rebuild, the ISA risk, the footguns (saturation, M5's 88× duplication blocker) |
| `04_ISA_PORTABILITY_RULES.md` | *The iPhone/ARM discipline.* Full x86-intrinsic inventory, the x86→aarch64 instruction mapping (vpmaddubsw↔UDOT), the build-config rules, the cross-compile CI gate |
| `05_TESTING_PROTOCOL.md` | The staged protocol (Stage 0 Python pre-gate → Stage 1 T1 bit-identical → Stage 2 E7 gates → Stage 3 150M serve → Stage 4 aarch64 parity), each with pre-registered bars and result-file conventions |
| `06_PREGATE_RESULTS.md` | **MEASURED** pre-gate results: the `query_int` integer-dot pre-gate (M2 GO, overlap@10 0.99) + the aarch64 cross-compile status + the zero-gather inventory (76.7%). The borderline 0.99 was later refuted at n=100 — see 07 |
| `07_M2_IMPLEMENTATION_RESULTS.md` | **MEASURED (2026-07-03)** M2 implementation verdict: kernel correct + portable + ~6% faster warm, but **gate a FAILS at n=100** (0.984 vs 0.99 bar; f32 control 0.991) → env-gated OFF, NOT promoted. Includes the M2b (i32-widen, 7-bit) revival path |
| `08_FURTHER_MATH_CANDIDATES.md` | **PRE-REGISTERED 2026-07-05; M7 MEASURED-KILLED 2026-07-08** — the researched M6–M10 candidate map beyond 03's M1–M5: M6 VNNI/UDOT hardware integer dot (`vpdpbusd`↔`UDOT`, i32 accumulate kills the saturation that killed M2 — 7-bit query), M7 query-membership bitmap + intersection dot (**KILLED by the Stage-0 sim: all-miss-pack rate 0.194 <0.3 — hits anti-cluster**), M8 batched multi-candidate scoring (register blocking, quality-free), M9 shuffle-LUT (Quicker ADC lineage — poor-fit analysis recorded), M10 native-f16 (premise unverified). Includes the dotvbyte-index-DB impact table (only M9 would force re-conversion), leverage map, and external sources. **Order after 2026-07-08 Stage-0 results: E8 Stage-1 → M8 instrument → M2b → M6** (see TL;DR) |

## TL;DR (updated 2026-07-08)

- **Stage-0 results (2026-07-08, shards 1–2, n=100):** **M7 KILLED** —
  all-miss-pack rate 0.194 (<0.3 bar); query hits anti-cluster, the pack
  skip never fires (08 §M7, `data/eval_results/m7_pack_membership_sim_20260708.json`).
  **E8 Stage-0 GO** — per-doc u8 scale 0.997/0.993 vs FixedU8Q 0.985/0.984
  (`data/eval_results/e8_stage0_perdoc_scale_20260708.json`). **Executing
  order is now E8 Stage-1 → M8 → M2b → M6** (08 §Recommended-order).

- **Execution entry point for everything below:**
  `../archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` (2026-07-05) — ordered
  queue, recipes, pre-registered bars.
- **G8d (2026-07-05) reshapes the M-track.** Full-corpus dv-vs-f16 parity:
  corpus mean 0.9906, shards 1–2 = 0.985 (accepted as marginal, doc 10 §7.6).
  Consequences, all recorded in 05/08: (a) **worst-case-shard rule** — quality
  gates run on shards 1–2, never shard0-only (shard0 measured best-case);
  (b) **quality-free candidates first** — order amended to M7 → M8 → M2b → M6;
  (c) the highest-value quality item is now **E8 (dv-v2 per-doc scale)**, a
  *recovery* lever, pre-registered in `seismic_150m_testbed/11`.

- **Gate b (math/latency) is PASS** — `warm_p50_ratio = 0.957` (bar ≤1.07) via
  the native rebuild (`target-cpu=native`, env-only, no code). This corrects the
  earlier "failed 22% is pure matrix-math cost" framing: the math is no longer
  the failing gate.
- **Gate c (memory/page-faults) is FAIL** — `majflt_cold_ratio = 0.591`
  pre-registered / **0.560 fully calibrated** (bar ≤0.55; E7 Fix #4+#5B floor
  prefault, `10_FORWARD_COMPRESSION_DESIGN.md` §7.3–§7.4, 2026-07-03), a
  structural cold-major-fault property, **not** a per-candidate math property.
  No dot-kernel change can touch it — both advice levers (MADV_RANDOM,
  MADV_WILLNEED) AND page-aligned record placement (Fix #5A) refuted
  2026-07-03; the decisive open experiment is E7b
  (`scripts/seismic_testbed/HOST_PROMPT_E7B_RAMCAP.md`).
- **M2 (integer dot, query quantized to 6-bit) — IMPLEMENTED 2026-07-03,
  NOT PROMOTED.** The Rust kernel (`dot_product_int6`, `SFU_SEISMIC_M2_INT6`
  env gate, default OFF) is correct (bit-matches the Python pre-gate model),
  aarch64-clean, and ~6% faster warm (E7 gate b 0.930 vs 0.993 f32 control,
  n=100). But **gate a (parity) FAILS at n=100: overlap@10 0.984 < 0.99 bar**
  (f32 control 0.991 on the same queries — int6 costs −0.007). The n=40
  pre-gate 0.99 was a small-n artifact, as 06's borderline caveat warned.
  Full story + the M2b (i32-widen, 7-bit query) revival path:
  `07_M2_IMPLEMENTATION_RESULTS.md`.
- **Zero-gather inventory = 76.7%** — measured: 77% of kernel gather lanes
  fetch zero (doc term not in query), the wasted-FMA tail M1 (vptest skip)
  would elide. (This grounds a previously-unmeasured estimate.)
- **The codebase is cross-ISA at source level today** — the kernel is
  `std::simd` (portable), the only x86 intrinsics are in `swizzle.rs` and are
  dual-cfg-guarded to compile out on aarch64. The portability discipline
  (`04_…md`) exists to **keep** it that way through any math change.
