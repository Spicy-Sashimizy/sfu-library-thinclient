# 03 · Min-RAM design map — the effective combo

**Created 2026-07-13. Status: DESIGN + Phase 0/5 building (2026-07-14) — every
projected number is *est.* unless it cites a result file.** This doc assembles
the *most effective version of each proposed function* from docs 01/02 into one
coherent design, optimized for the search engine's actual goals: serve the full
150M-doc SEISMIC leg with **bit-identical results** on the **least RAM**,
degrading gracefully from a 6 GB localized deploy up to a RAM-rich server.

Build gates (unchanged from doc 02 — this doc does not override them):
**(G-a)** production-shaped query-log re-run of Q12, **(G-b)** E8 Stage-2 lands
(reconversion invalidates hot-set sidecars). Nothing here is built before both.
**Both PASSED 2026-07-14**: G-b = E8 dv-v2 8-shard reconversion landed + served
(commits fcfcfb2/0d3497f/5ebae0f; Q7 federated 2-rep PASS + 6-rep A/B
confirmation); G-a = Q12b production-shaped probe **GO** (hot-set-80 3.07 GB ≤
4 GB, repeat 0.987 ≥ 0.25; `q12b_access_skew_production_20260714.json`). F1–F5
are unblocked and building in build-order (§5).

---

## §1 The tier picture (what lives where)

The design is three residency tiers over the existing mmap substrate —
"rung 2" of the control ladder (mmap + measured pinning), deliberately NOT
the pread rewrite (rung 4):

```
RAM ┌────────────────────────────────────────────────────────────┐
    │ TIER P — PINNED (mlock'd, kernel can never evict)          │
    │  P1 structural floor: posting lists + doc map + fwd        │
    │     offsets            ~1.5 GB   (measured, Fix#4/Q9)      │
    │  P2 hot forward extents (from usage sidecar)               │
    │     budget dial: 0 / 1.6 / 4.2 GB ≈ 0 / 50% / 80% of       │
    │     touches            (measured coverage curve, Q12)      │
    ├────────────────────────────────────────────────────────────┤
    │ TIER C — CACHED (plain page cache, kernel-reclaimable)     │
    │  whatever RAM remains; the kernel's global LRU is fine     │
    │  for this residual — we stopped fighting it (E7 verdict)   │
    ├────────────────────────────────────────────────────────────┤
DISK│ TIER S — STREAMED (mmap, faulted on demand)                │
    │  the cold ~73% of forward_data that 120 diverse queries    │
    │  never touched (measured, Q12) + everything under memory   │
    │  pressure                                                  │
    └────────────────────────────────────────────────────────────┘
```

Why this shape wins on RAM: **only Tier P is a hard commitment.** Tier C
costs nothing under pressure (clean file pages, droppable instantly), and
Tier S costs nothing at rest. Total *guaranteed* footprint = floor + pin
dial + anon serving floor (~1.1 GB Path-C, measured) + encoder — everything
else is elastic.

## §2 The most effective version of each proposed function

| # | Function (doc 01/02 name) | Most effective form | Why this form (evidence) |
|---|---|---|---|
| F1 | **Usage telemetry** (colibrì `eusage`) | Offline/periodic, NOT per-query-in-serving: rerun `q12_access_skew_probe.py`-style collection over the real query log on a schedule (or sample 1-in-N served queries via `search_visited`), aggregate to **extents** | Per-query telemetry in the hot path costs a Vec copy per query for data that changes slowly; the hot set is a *distribution*, sampled is enough. Zero serving-path risk |
| F2 | **Hot-set persistence** (colibrì `.coli_usage`) | JSON sidecar per shard: `<shard>.mmap/hotset.json` = sorted list of `(page_start, page_len)` **extents** + the manifest's `forward_format_version` + `forward_reordered` + a generation date; refuse (and log) on key mismatch | E5's `block_walk_canonical` made hot pages contiguous → extents are few and large; version-keying makes E8 Stage-2 reconversion fail-loud instead of pinning garbage |
| F3 | **Pin tier** (colibrì `pin`) | `mlock_ranges(extents)` pyo3 hook on `MmapSeismicIndex` + budget check: pin ≤ min(dial, `MemAvailable` − floor − headroom) at load, largest-coverage extents first (greedy by touch count — the Q12 counter is the ranking) | mlock-on-mmap keeps zero-copy and needs ~10% of the pread rewrite's code; budget-from-`MemAvailable` is colibrì's own discipline and the no-OOM guarantee |
| F4 | **Floor prefault → floor pin** (Q9 upgrade) | extend `prefault_floor` with an optional mlock flag (same slabs) | the floor faults identically every cold start (measured constant, Fix#4); on capped hosts it's the first thing kswapd steals back — locking it makes Q9's win durable |
| F5 | **Eviction between shards** (mechanism B) | `release_pages_except(pinned_extents)` — range-split `MADV_DONTNEED` around pinned extents | plain DONTNEED **EINVALs on mlocked ranges** (doc 02 §4); the split keeps the sequential ~1-shard residency guarantee for the *unpinned* remainder |
| F6 | **Serving method** | keep Q7 `HybridSeismicBackend` unchanged (sequential-cold → parallel-warm, adaptive flip) | flip threshold is self-derived from observed cold, so a pin tier that lowers cold traverse auto-tightens it — zero new code |
| F7 | **Software LRU proper** (colibrì `ESlot`/`eclock`) | **omitted** from the combo | with F1–F5, the kernel LRU only manages Tier C, where its blindness is acceptable; a userspace LRU adds policy code for the low-value residual (rung 3 — only if F3 measurably plateaus) |
| F8 | **PILOT prefetch** | **omitted** (parked, doc 02 §3.3) | cold path is channel-contended (sequential cold < parallel cold, measured 2026-07-09); 3 adjacent negative results |
| F9 | **pread + buffer pool** | **omitted** (deferred, doc 02 §3.4) | owned buffers are *unreclaimable* anon RAM — strictly worse for the min-RAM goal unless F3 hits the kernel-policy ceiling with evidence |

The one genuinely new moving part is small: **F3+F5 are ~2 pyo3 hooks and a
range-splitter**; F1/F2 are scripts + a sidecar format; F4 is a flag; F6 is
nothing.

## §3 The combo per deployment shape (RAM budgets)

> **MEASURED VERDICT 2026-07-14 (R1 ladder + pin arm — supersedes the *est.*
> cells below):** the F3 pin hypothesis is **REFUTED in the self-thrash
> regime** — at 6 GB, pin@1.6 made steady p50 ~35% WORSE (4.9 → 6.6 s; fault
> count +7%, per-fault cost +26% from lost fault-run contiguity), at 8 GB
> neutral (`r1_cap{8,6}g_pin16_20260714.json`, backlog §R1). The 6 GB row's
> "~2× better p50" prediction is dead: this workload's working set is
> **~15.5 GB**, and below it no residency policy helps (capacity math).
> Honest deploy floor: **16 GB minimum / 24 GB comfortable**. The 6 GB shape
> requires working-set reduction (compression, k′ tightening), not pinning.
> Still-open pin regimes: external cache competitors; rescoped ~20 MB F4
> floor. F6 prefault remains the proven lever (2.8× cold p95, all shapes).
> Recommended config: `THIN_CLIENT_SWAP.md` env register.

Fixed costs (measured): anon serving floor ~1.1 GB (Path-C), structural floor
~1.5 GB, SPLADE ORT encoder ~0.7 GB (*est.* — measure before quoting). dv
forward total 30.5 GB across 8 shards (Q12 JSON).

**2026-07-14 CORRECTION (from F4 build, §5 step 2):** the "~1.5 GB structural
floor" is **PER SHARD** (posting_lists.bin 1.16 GB + doc-mapping 0.35 GB), NOT
the 8-shard total. `mlock_floor` as built locks the FULL posting_lists slab × 8
= **~13.4 GB total floor pin** — which **defeats the min-RAM goal** and would
blow the 6 GB localized combo below. The combos below are corrected
accordingly: **F4 (floor-mlock) is NOT in the combo until rescoped** to the
~20 MB true constant floor (Q9's "~5,000 pages"). F3 hotset pin (1.6 / 4.2 GB
total, correctly scoped) is the real min-RAM lever. Until F4 is rescoped, the
combos drop the F4 term.

| Deploy shape | Combo (dial settings) | Guaranteed RSS (*est.*) | Expected behavior (*est.*) |
|---|---|---|---|
| **Localized min-RAM (6 GB cap)** — the H5 cell | sequential-only + F4 floor-pin + F3 pin @ **1.6 GB** (hot-50) + F5 release-except | ~1.1 + 1.5 + 1.6 + 0.7 ≈ **4.9 GB** locked; ~1 shard transient on top → fits 6 GB | ~50% of candidate touches never fault (Q12 curve); per-query cost ≈ Σ shards over the *other* 50% → vs today's H5 prediction (tens of s/query) plausibly **~2× better p50**; floor never re-faults |
| **32 GB host (the G8 regime)** | hybrid (F6) + F4 + F3 @ **4.2 GB** (hot-80) + F5 on the cold arm | ~7.5 GB locked, rest of RAM = Tier C | the 15.8 s warm≈cold sequential floor attacked from two sides: 80% of touches pinned + Tier C holds much of the residual → **~1.5–3× p50** (doc 02 §6 revised est.); paraphrase-like traffic (62% warm-hit, measured) benefits most |
| **RAM-rich server (≥ 40 GB free)** | parallel, F3 @ **0** (pin dial off), F4 optional | ~2.6 GB + page cache grows to working set | pinning adds nothing when nothing is evicted (doc 02 §3.2) — the dial exists precisely so this shape pays zero |
| **Cold-start-sensitive (any shape)** | + prefault (not mlock) the F2 sidecar extents at load, Q9-style | no locked delta | first queries hit a pre-warmed hot set: cold p50 → warm-ish for the hot fraction (*est.* 1.3–2× cold, doc 02 §6) |

**The single most effective min-RAM combo, named:** dv shards (E8 v2 once
served) + E5 reorder (already served) + sequential/hybrid federation +
floor-pin + hot-50 pin @ 1.6 GB + release-except + prefault-hotset-at-load.
Guaranteed footprint ~5 GB, everything above it elastic, results
bit-identical by construction (residency-only levers; T1 untouched).

## §4 Why this is the RAM-optimal point (the reasoning, briefly)

- **Every GB in Tier P buys a measured, known return** (the Q12 coverage
  curve: 1.6 GB→50%, 4.2 GB→80%, 5.95 GB→90%, then steeply diminishing).
  No other lever on the table has a measured GB→latency exchange rate.
- **Every GB *not* pinned remains someone else's** — the kernel reclaims
  Tier C freely, so the design never competes with co-resident services
  (the thin-client constraint) and cannot OOM by construction (F3 budget
  check).
- **The codec + layout levers are already banked**: dv is the smallest
  forward (E7b), E5 reorder already delivered 0.53× cold majflt and makes
  the hot set contiguous (cheap to pin). This design *composes with* rather
  than replaces them.
- The omitted functions (F7–F9) all spend either RAM (F9's buffers) or
  complexity (F7/F8) on the elastic tiers, where the return is unmeasured
  or measured-negative.

## §5 Build order (post-gates), smallest-risk first

1. F2 sidecar format + F1 offline generator (script-only; can ship before
   the gates since it changes nothing served). **DONE 2026-07-14**: schema
   `seismic.hotset.v1` (sorted `(page_start, page_len)` extents + version_keys
   `forward_format`/`forward_format_version`/`forward_reordered`/
   `forward_data_words` + generation date); loader refuses-and-logs on key
   mismatch (E8 reconversion fails loud, not pins garbage). Generator
   `scripts/seismic_testbed/f1_hotset_generator.py` emits per-shard sidecars at
   the Phase-3 dials (hot50_1.6gb / hot80_4.2gb / full_touched) over the Q12b
   production query log; sidecars + inventory under `data/eval_results/`. EFFICACY: F1
   sidecars PENDING EMIT (Phase 0b GO → emit step next).
2. F4 floor-mlock flag (one-arg change to an existing hook). **BUILT 2026-07-14;
   EFFICACY UNMEASURED + OVER-SCOPED**: `mlock_floor(include_forward_offsets)`
   pyo3 hook on `MmapSeismicIndex` (both codecs) +
   `sharded_seismic_backend.mlock_floor`; gate `SFU_SEISMIC_MLOCK_FLOOR=1`.
   Hook works (1.67 GB locked on shard 0) BUT it locks the FULL posting_lists
   slab (1.16 GB/shard × 8 = **~13.4 GB total**) — NOT the doc-03 "~1.5 GB".
   The "~1.5 GB structural floor" is PER SHARD; the true small constant floor
   is ~5,000 pages = 20 MB (Q9). **Default-off (kill-switch) is correct** until
   `mlock_floor` is rescoped to the ~20 MB true floor; 13 GB of floor pin
   defeats the min-RAM goal. Degrades to no-op if mlock denied.
3. F3 `mlock_ranges` + budget check; A/B on the 32 GB host vs pin-off. **BUILT
   2026-07-14; MECHANISM VERIFIED; latency A/B HOST-GATED**: `mlock_ranges(extents)`
   pyo3 hook (greedy by touch count in Python, budget-capped at
   min(`SFU_SEISMIC_PIN_BUDGET_GB`, MemAvailable − 1.5 GB floor − 1.0 GB
   headroom)); `sharded_seismic_backend.load_hotset_and_pin` loads the F2
   sidecar at construction + applies the cap (the no-OOM guarantee). Manual 8-shard
   pin: 0.782 GB pinned cleanly (the no-op fallback kicks in past the memlock
   ceiling, no crash). LATECNY A/B **HOST-GATED**: the 15.8 s warm≈cold regime is
   a 32 GB HOST phenomenon; this dev container (54 GB MemAvailable) is already
   RAM-speed at warm → no latency uplift measurable here. Requires the
   operator's constrained-host run (G8 regime).
4. F5 `release_pages_except` (needed only for the sequential/hybrid-cold arm;
   parallel path never releases). **BUILT 2026-07-14; EFFICACY UNMEASURED
   (host-gated)**: `release_pages_except(pinned_extents)` pyo3 hook; range-splits
   `MADV_DONTNEED` around mlocked extents (plain DONTNEED EINVALs on mlocked
   ranges, §4). Not exercised (relevant only under memory pressure on the
   sequential cold arm — the constrained-host run).
5. Re-run T1 bit-identity + the G6 overlap harness with pinning ON. **DONE
   2026-07-14 — 20/20 BIT-IDENTICAL**: `ParallelSeismicBackend` (2 shards, E8 v2,
   F3 pin 1.6 GB dial = 0.4 GB pinned) produces bit-identical top-50 oaid-order
   on 20/20 diverse queries vs pin-OFF (`_t1_pin_{off,on}.json`). Residency-only
   levers → T1 by construction; asserted empirically. Run out-of-process (3
   backends × 2 shards exceeds the dev container's ~50 GB VmSize ceiling).
6. Cold-start prefault-hotset-at-load (the cold-p95 lever). **DONE 2026-07-14 —
   MEASURED (corrected)**: `prefault_ranges(extents)` pyo3 hook + `prefault_hotset`
   backend method; gate `SFU_SEISMIC_PREFLOOR_HOTSET=1`.

   > **CORRECTION 2026-07-14**: the first recorded result ("cold p95 30 ms,
   > ~150×", commit 0b4e9c3) was **INVALID** — every one of the 300 bench
   > queries had silently failed (encoder ImportError under the gate +
   > VMA-table saturation killing the parallel arm) and was scored as a ~0 ms
   > no-op by the harness. Five defects fixed in commit 2203d9b (eager-load
   > gate, all-failed bench guard, checksum-as-GB log, MADV_SEQUENTIAL
   > VMA-split extent coalescing, poisoned-cell aggregation).

   Corrected paired A/B (same day, same natively-rebuilt .so, full q7
   fadvise-DONTNEED protocol, 100 q × 3 passes × 2 reps, 0 failed queries):
   gate OFF cold p50 666-676 ms / p95 **4656-4686 ms**; gate ON cold p50
   373-490 ms / p95 **1464-1884 ms (median 1674)** → **~2.8× cold-p95, ~1.5×
   cold-p50, warm unchanged** (52-55 ms both arms)
   (`f6_prefault_hotset_20260714.json` vs `f6_gateoff_baseline_20260714.json`).
   Result parity gate-ON vs gate-OFF: **10/10 queries identical** (top-10 ids +
   scores, 2026-07-14; harness promoted to
   `scripts/seismic_testbed/seismic_result_parity.py` — run it for every
   residency-lever enable, incl. the F3 constrained-host A/B).
   Attribution note (corrected 2026-07-14 audit): warm improving 117→54 ms vs
   the 2026-07-13 baseline is an **operating-conditions confound (CPU
   contention), not a module win** — evidence: encode (pure ONNX, no Rust)
   also halved 30.4→16.7 ms; the 01:00 rebench on the OLD .so under co-load
   still showed warm 115-126 ms; the rebuild used no target-cpu flags. Treat
   ~54 ms as the quiet-host warm figure and ~120 ms as the co-loaded figure.
   Not prefault either way (warm identical in both arms). Cold p95 is
   disk-bound and immune to this confound (gate-OFF p95 matches the
   2026-07-13 baseline across days).
   Caveat (unchanged): the win is PROCESS-COLD WARMUP (first queries of a
   fresh process after prefault, no intervening eviction); under sustained
   memory pressure the prefaulted pages are evicted and need F3 mlock to stay
   resident. Prefault = the cold-start lever; mlock = the durability lever.

Kill-switch discipline: everything behind env gates (`SFU_SEISMIC_PIN_BUDGET_GB=0`
= today's behavior exactly). F4 behind `SFU_SEISMIC_MLOCK_FLOOR=0`. F6 behind
`SFU_SEISMIC_PREFLOOR_HOTSET=0`. All default-off → byte-identical to the
pre-program path.
