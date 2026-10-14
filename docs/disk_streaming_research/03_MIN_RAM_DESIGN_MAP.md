# 03 · Min-RAM design map — the effective combo

**Status:** DEFERRED 2026-09-25 (F1-F6 hooks built and env-gated OFF; no promotion decision taken)

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
| F4 | **Floor prefault → floor pin** (Q9 upgrade) | ~~extend `prefault_floor` with an optional mlock flag (same slabs)~~ → **RESCOPED 2026-08-17**: lock only the posting-list *navigation* runs (block_offsets + EF offsets + inventories) inside `posting_lists.bin`, budget-capped (`SFU_SEISMIC_MLOCK_FLOOR_MB`, default 160 MB total) under the F3 no-OOM guard — §5 step 2 | the same-slabs form pins 1.67 GB/shard = 13.4 GB (min-RAM goal defeated); the navigation runs are the small always-traversed structural subset (153.1 MB/shard, 13.2% of the slab, measured 2026-08-17) and 20 MB/shard of them locks in 1.6 s, parity 5/5. **A/B RUN 2026-08-17: warm p50 1.019× (bar ≤1.05× PASS), parity 10/10 PASS, pressure-refault bar NOT MEASURED — default stays 0** — §5 step 2 |
| F5 | **Eviction between shards** (mechanism B) | `release_pages_except(pinned_extents, keep_structural=False)` — range-split `MADV_DONTNEED` around pinned extents, over **every mapped slab** | plain DONTNEED **EINVALs on mlocked ranges** (doc 02 §4); the split keeps the sequential ~1-shard residency guarantee for the *unpinned* remainder. **SCOPE FIX 2026-08-31**: as built the hook covered only the forward codec slab, which made the 2026-07-14 16 GB cell a null (the residue is structural). Fixed in code + synthetically verified (dv 4.43× / f16 9.85× more bytes covered); real-stack efficacy still UNMEASURED — `11_EXPERIMENT_BACKLOG.md` R1 F5 entry |
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
> Still-open pin regimes: external cache competitors; the F4 navigation-floor
> pin (RESCOPED 2026-08-17 to ~20 MB/shard — built, residency-measured, and
> latency-A/B'd 2026-08-17: **free per query (warm p50 1.019×) and
> bit-identical, but the residency benefit is still unproven — no
> memory-pressure pass exists in this container; default stays 0**;
> §5 step 2).
> F6 prefault remains the proven lever (2.8× cold p95, all shapes).
> Recommended configuration: `THIN_CLIENT_SWAP.md` environment register.

Fixed costs (measured): anon serving floor ~1.1 GB (Path-C), structural floor
~1.5 GB, SPLADE ORT encoder ~0.7 GB (*est.* — measure before quoting). dv
forward total 30.5 GB across 8 shards (Q12 JSON).

**2026-07-14 CORRECTION (from F4 build, §5 step 2):** the "~1.5 GB structural
floor" is **PER SHARD** (posting_lists.bin 1.16 GB + doc-mapping 0.35 GB), NOT
the 8-shard total. `mlock_floor` as built locks the FULL posting_lists slab × 8
= **~13.4 GB total floor pin** — which **defeats the min-RAM goal** and would
blow the 6 GB localized combo below. The combos below are corrected
accordingly: **F4 (floor-mlock) is NOT in the combo until rescoped**. F3 hotset
pin (1.6 / 4.2 GB total, correctly scoped) is the real min-RAM lever.

> **2026-08-17 UPDATE — F4 RESCOPED (and the "~20 MB true floor" target was a
> unit error).** `SFU_SEISMIC_MLOCK_FLOOR=1` now locks only the posting-list
> **navigation** runs inside `posting_lists.bin` (block_offsets + Elias-Fano
> offsets + DArray inventories), budget-capped by `SFU_SEISMIC_MLOCK_FLOOR_MB`
> (default 160 MB TOTAL = ~20 MB/shard) under the F3 no-OOM guard — MEASURED
> **19,980,288 B in 929 ranges on shard0**, parity 5/5 bit-identical
> (`f4_floor_mlock_rescope_20260817.json`). The old whole-slab pin needs
> `=full`. The "~20 MB true constant floor (Q9's ~5,000 pages)" this doc
> previously called the target **does not exist**: doc 10 §7.3's 5,093 was a
> major-*fault* count carrying ~1.27 GB of readahead pages, not 5,093 resident
> pages. The measured always-traversable structural subset is the 153.1 MB/shard
> navigation floor (13.2% of the slab); ~20 MB/shard is a *budget*, not the
> floor's size. F4's term in the combos below is therefore ~0.16 GB (register
> default). **Latency A/B RUN 2026-08-17** (`f4_floor_ab_verdict_20260817.json`):
> warm p50 62.17 → 63.35 ms (**1.019×**, bar ≤1.05× PASS), parity **10/10**
> identical, load cost **2.8 → 91.4 s** on a cold page cache; the
> pressure-refault bar is **NOT MEASURED** (no RAM cap here), so the gate stays
> **default 0** — §5 step 2.

| Deploy shape | Combo (dial settings) | Guaranteed RSS (*est.*) | Expected behavior (*est.*) |
|---|---|---|---|
| **Localized min-RAM (6 GB cap)** — the H5 cell | sequential-only + F4 floor-pin + F3 pin @ **1.6 GB** (hot-50) + F5 release-except | ~1.1 + 1.5 + 1.6 + 0.7 ≈ **4.9 GB** locked; ~1 shard transient on top → fits 6 GB | ~50% of candidate touches never fault (Q12 curve); per-query cost ≈ Σ shards over the *other* 50% → versus today's H5 prediction (tens of s/query) plausibly **~2× better p50**; floor never re-faults |
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
2. F4 floor-mlock flag (one-arg change to an existing hook). **BUILT 2026-07-14
   (OVER-SCOPED) → RESCOPED 2026-08-17; MECHANISM MEASURED, LATENCY EFFICACY
   UNMEASURED.**

   *As built 2026-07-14:* `mlock_floor(include_forward_offsets)` pyo3 hook on
   `MmapSeismicIndex` (both codecs) + `sharded_seismic_backend.mlock_floor`
   locks whole SLABS — posting_lists 1.16 GB + doc-mapping 0.36 GB +
   forward_offsets 0.15 GB = 1.67 GB/shard × 8 = **~13.4 GB total**, which
   defeats the min-RAM goal (the "~1.5 GB structural floor" of §3 is PER
   SHARD).

   *The "~20 MB true floor" target was itself wrong (found 2026-08-17).* It came
   from Q9/E7-Fix#4 via doc 10 §7.3, which measured **5,093 major FAULTS**
   stripped by `prefault_floor` — and states in the same row that those faults
   carry **~1.27 GB** of pages (readahead amortizes ~64 pages per major fault).
   `5,093 × 4 KiB = 20 MB` was a fault-count-as-page-count unit error; no 20 MB
   slab exists to lock.

   *Rescope as shipped 2026-08-17* (`sharded_seismic_backend.mlock_structural_floor`,
   pure Python — `/proc/self/maps` base + `ctypes` `mlock(2)` on sub-slab
   ranges; no .so rebuild, so the served kernel/.so is untouched): gate `=1`
   now locks ONLY the posting-list **navigation** metadata — per list, the
   contiguous `block_offsets + Elias-Fano offsets (high/low bits) + DArray
   inventories` run inside `posting_lists.bin` (`_PL_LAYOUT` NAV rows; the walk
   reproduces the slab's byte length exactly, else the shard is refused). Never
   the data extents (packed postings / summary ids / values / minimums /
   quants), never doc-mapping, never the forward slabs. Dials + guards:
   `SFU_SEISMIC_MLOCK_FLOOR_MB` (TOTAL across shards, default **160** =
   20 MB/shard at 8), the F3 no-OOM guard (`MemAvailable − 1.0 GB`), the
   ≤2048-ranges/shard VMA-split cap, largest-run-first selection (a size proxy
   for term frequency — HEURISTIC). `SFU_SEISMIC_MLOCK_FLOOR=full` reproduces
   the old whole-slab pin; `=0` (default) is byte-identical to the pre-F4 path.

   **MEASURED 2026-08-17** (`data/eval_results/f4_floor_mlock_rescope_20260817.json`,
   `scripts/seismic_testbed/f4_floor_mlock_smoke.py`, shard0 dv-v2, budget
   20 MB): **locked 19,980,288 B in 929 ranges in 1.6 s**, process `VmLck`
   delta equal to the reported byte count (kernel-side confirmation); the
   shard's complete navigation floor is **153.1 MB of the 1,159.2 MB slab
   (13.2%)**, so the budget pinned the top 13% of it. Full-register default
   = 8 × ~20 MB ≈ **160 MB versus the old 13.4 GB (671× less)**. Result parity
   gate-ON versus gate-OFF: **5/5 queries bit-identical** (top-10 ids+scores,
   capture files byte-identical; `seismic_result_parity.py`).

   **LATENCY A/B RUN 2026-08-17 (idle host, NOT RAM-capped): 2 of 3
   pre-registered bars PASS, 1 NOT MEASURED — default stays 0.**
   Results: `data/eval_results/f4_floor_ab_verdict_20260817.json` (summary),
   `f4_floor_ab_off_20260817.json` / `f4_floor_ab_on_20260817.json` (arms),
   `f4_floor_mlock_8shard_20260817.json` (residency smoke),
   `f4_floor_parity_{off,on}_20260817.json` (capture files).

   | bar (pre-registered above) | measured | verdict |
   |---|---|---|
   | warm p50 ON ≤ 1.05× OFF | **1.019×** (62.17 → 63.35 ms) | **PASS** |
   | zero navigation-page re-faults under pressure | — | **NOT MEASURED** |
   | parity 0 mismatches | 0 (10/10 ids+scores identical) | **PASS** |

   Full-register residency smoke, 8 shards: **159,907,840 B locked in 7.65 s**,
   `VmLck` delta equal to the reported bytes; the complete navigation floor
   across the register is **1,225,697,128 B**, so the 160 MB budget pins 13.0%
   of it. Warm p95 **105.6 → 95.0 ms** and warm mean **67.2 → 63.4 ms** are
   nominally BETTER with the gate on, that is, mlock costs nothing per query;
   `anon_floor` moves 1.1359 → 1.1370 GB (+1.1 MB) and `VmRSS` peak 17.61 →
   17.73 GB (+0.12 GB ≈ the locked bytes). **Cost that was not on anyone's
   list:** load time **2.8 s → 91.4 s**, because the mlock walk faults the
   160 MB of navigation runs off 9p with a page cache the previous arm's
   `fadvise(DONTNEED)` had just emptied (the same walk took 7.65 s warm). It is
   a one-time load cost, but it is 88 s of it on a cold container.

   **Why this is not a green light.** The bar that would justify the gate —
   *residency under pressure* — is the one that was not measured:
   `serve_footprint_bench` has no memory-pressure pass and this container has
   no RAM cap, so nothing here forced the navigation pages to compete for
   reclaim. mlock'd pages are unevictable by kernel semantics and `VmLck`
   proves the lock landed, but "the pages survive pressure" was asserted, not
   observed. The cold arm (p50 968.5 versus 1199.1 ms, 0.81×) looks favourable and
   is **not claimable**: n=100 single-pass with p95 6.8/8.8 s, a spread that
   dwarfs the difference. So: the A/B licenses *enabling* the gate on a host
   that wants it (it is free and bit-identical), and does not demonstrate a
   win. **Default stays 0**; the real test remains the R1/R3 RAM-capped host
   ladder.

   The A/B as run (reproduce on a RAM-capped host for the missing bar):

   ```bash
   # ── 1. residency (light, no benchmark): what does the gate actually lock? ──
   SFU_SEISMIC_LOAD_MODE=mmap SFU_SEISMIC_MLOCK_FLOOR_MB=160 .venv/bin/python3 \
     scripts/seismic_testbed/f4_floor_mlock_smoke.py \
     --out data/eval_results/f4_floor_mlock_8shard_<YYYYMMDD>.json

   # ── 2. latency A/B (HEAVY — idle host only): same binary, same manifest ──
   M=data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json
   SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 \
     scripts/seismic_testbed/serve_footprint_bench.py --shard-manifest $M \
     --federation hybrid --queries 100 --passes 3 \
     --result-file data/eval_results/f4_floor_ab_off_<YYYYMMDD>.json
   SFU_SEISMIC_LOAD_MODE=mmap SFU_SEISMIC_MLOCK_FLOOR=1 \
   SFU_SEISMIC_MLOCK_FLOOR_MB=160 .venv/bin/python3 \
     scripts/seismic_testbed/serve_footprint_bench.py --shard-manifest $M \
     --federation hybrid --queries 100 --passes 3 \
     --result-file data/eval_results/f4_floor_ab_on_<YYYYMMDD>.json

   # ── 3. bit-identity (always, both arms) ──
   SFU_SEISMIC_LOAD_MODE=mmap .venv/bin/python3 \
     scripts/seismic_testbed/seismic_result_parity.py capture /tmp/off.json
   SFU_SEISMIC_LOAD_MODE=mmap SFU_SEISMIC_MLOCK_FLOOR=1 .venv/bin/python3 \
     scripts/seismic_testbed/seismic_result_parity.py capture /tmp/on.json
   .venv/bin/python3 scripts/seismic_testbed/seismic_result_parity.py \
     compare /tmp/off.json /tmp/on.json
   ```

   (Step 2 loads all 8 shards and runs 300 queries per arm with
   `fadvise(DONTNEED)` between cells — it evicts the machine's page cache and
   must NOT be run while another eval is measuring on the same host.)

   Bars (pre-registered 2026-08-17): warm p50 ON ≤ 1.05× OFF (mlock adds no
   per-query work), zero navigation-page re-faults under a memory-pressure
   pass, parity 0 mismatches. Anything else = keep default-off.
3. F3 `mlock_ranges` + budget check; A/B on the 32 GB host versus pin-off. **BUILT
   2026-07-14; MECHANISM VERIFIED; latency A/B HOST-GATED**: `mlock_ranges(extents)`
   pyo3 hook (greedy by touch count in Python, budget-capped at
   min(`SFU_SEISMIC_PIN_BUDGET_GB`, MemAvailable − 1.5 GB floor − 1.0 GB
   headroom)); `sharded_seismic_backend.load_hotset_and_pin` loads the F2
   sidecar at construction + applies the cap (the no-OOM guarantee). Manual 8-shard
   pin: 0.782 GB pinned cleanly (the no-op fallback kicks in past the memlock
   ceiling, no crash). LATECNY A/B **HOST-GATED**: the 15.8 s warm≈cold regime is
   a 32 GB HOST phenomenon; this development container (54 GB MemAvailable) is already
   RAM-speed at warm → no latency uplift measurable here. Requires the
   operator's constrained-host run (G8 regime).
4. F5 `release_pages_except` (needed only for the sequential/hybrid-cold arm;
   parallel path never releases). **BUILT 2026-07-14; EFFICACY UNMEASURED
   (host-gated)**: `release_pages_except(pinned_extents)` pyo3 hook; range-splits
   `MADV_DONTNEED` around mlocked extents (plain DONTNEED EINVALs on mlocked
   ranges, §4). Not exercised (relevant only under memory pressure on the
   sequential cold arm — the constrained-host run). **SCOPE FIX 2026-08-31 —
   FIXED IN CODE, EFFICACY UNMEASURED ON THE REAL STACK**: the hook released
   only the forward codec slab, so the one cell that did run it (2026-07-14,
   16 GB) was a null; it now covers every mapped slab, byte accounting only
   credits successful `madvise` calls, and `release_pages_except_by_slab()`
   reports per-slab evidence. Fork commit `2c4d863`; synthetic numbers +
   caveats in `11_EXPERIMENT_BACKLOG.md` (R1 F5 entry).
5. Re-run T1 bit-identity + the G6 overlap harness with pinning ON. **DONE
   2026-07-14 — 20/20 BIT-IDENTICAL**: `ParallelSeismicBackend` (2 shards, E8 v2,
   F3 pin 1.6 GB dial = 0.4 GB pinned) produces bit-identical top-50 oaid-order
   on 20/20 diverse queries versus pin-OFF (`_t1_pin_{off,on}.json`). Residency-only
   levers → T1 by construction; asserted empirically. Run out-of-process (3
   backends × 2 shards exceeds the development container's ~50 GB VmSize ceiling).
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
   (`f6_prefault_hotset_20260714.json` versus `f6_gateoff_baseline_20260714.json`).
   Result parity gate-ON versus gate-OFF: **10/10 queries identical** (top-10 ids +
   scores, 2026-07-14; harness promoted to
   `scripts/seismic_testbed/seismic_result_parity.py` — run it for every
   residency-lever enable, incl. the F3 constrained-host A/B).
   Attribution note (corrected 2026-07-14 audit): warm improving 117→54 ms versus
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

Kill-switch discipline: everything behind environment gates (`SFU_SEISMIC_PIN_BUDGET_GB=0`
= today's behavior exactly). F4 behind `SFU_SEISMIC_MLOCK_FLOOR=0`. F6 behind
`SFU_SEISMIC_PREFLOOR_HOTSET=0`. All default-off → byte-identical to the
pre-program path. **The rescope preserved this (2026-08-17):**
`SFU_SEISMIC_MLOCK_FLOOR` is parsed by `_mlock_floor_mode()` — `0`/unset/
unrecognized → OFF (fail-safe: a typo can never pin gigabytes), `1` → the
rescoped navigation floor, `full` → the 2026-07-14 whole-slab pin. With the
gate off, the load path executes the identical statements it did before the
rescope (the only edit on the OFF path is the environment decode, which yields the same
`False` for unset/`0`); empirically the gate-OFF and gate-ON parity captures are
byte-identical files. A pre-rescope-binary arm was NOT re-run (the machine was
running the WS-A parity eval on 2026-08-17) — OFF-path identity is established
by diff inspection, not by a third capture.
