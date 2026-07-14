# 02 · Method verification, integration map, and worth-it analysis

**Created 2026-07-13. Status: RESEARCH + one measured probe (Q12) — not on the
served path.** This doc does three things doc 01 explicitly did not:

1. **Verifies doc 01's external claims online** (READMEs + colibrì's C source
   fetched 2026-07-13) — every claim labeled CONFIRMED / PARTIAL / UNVERIFIED.
2. **Double-checks each "useful to us" feature against our own code and
   measured record** — including two corrections to doc 01.
3. **Maps each candidate onto the current modules** with estimated uplift and
   a worth-developing verdict — plus the first *measured* validity probe
   (Q12 access-skew telemetry, pre-registered in
   `seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §Q12 before the run).

Per the efficacy rule: all uplift numbers here are ***est.*** unless they cite
a result file under `data/eval_results/`.

---

## §1 Online verification of doc 01's external claims (2026-07-13)

### colibrì ([github.com/JustVugg/colibri](https://github.com/JustVugg/colibri))

README + `c/glm.c` source both fetched. Doc 01's portrait is **accurate**; the
identifier-level claims doc 01 made are real code, not paraphrase:

| Claim (doc 01) | Verdict | Evidence |
|---|---|---|
| 744B MoE (GLM) served in ~25 GB RAM; dense tier ~9.9 GB resident (int4), 21,504 routed experts ~370 GB on disk, streamed on demand | **CONFIRMED** | README: "the 21,504 routed experts (75 MoE layers × 256 experts … ~19 MB each at int4) live on disk (~370 GB) and are streamed on demand" |
| Per-layer LRU of expert slots (`ESlot[]`, monotonic `eclock`, linear-scan eviction) | **CONFIRMED (source)** | `c/glm.c`: `typedef struct { int eid; … } ESlot;`, `uint64_t eclock, hits, miss, ereq;`; eviction = linear scan for min timestamp |
| Usage counters `eusage`/`eheat` + pinned hot store, persisted (`.coli_usage`) | **CONFIRMED** | source: `uint32_t **eusage; uint32_t **eheat; ESlot **pin; int *npin;` + `usage_save()`; README: "`.coli_usage` next to the model, updated every turn" |
| PILOT lookahead: next-layer router on residual, **71.6%** top-8 recall, dedicated I/O thread, lock-free 1P/1C ring `pilot_q[4096]` | **CONFIRMED** | README quotes 71.6% exactly; source: `static struct { int l,e; } pilot_q[4096];` with `volatile pilot_w, pilot_r` |
| `pread` (not mmap) + optional O_DIRECT for the streamed tier | **CONFIRMED** | source: `pread(dfd, s->slab, len, base)`; `st_direct_fd` 4K-aligned path |
| DONTNEED default OFF; OS page cache as free L2 | **CONFIRMED** | source: `static int g_drop=0;` → `posix_fadvise(…, POSIX_FADV_DONTNEED)` only when enabled. Note it is **fadvise, not madvise** — consistent with the fd/`pread` architecture (doc 01 said "madvise"; minor correction) |
| Batch-union dedup; cache auto-sized from `MemAvailable` | **CONFIRMED** (README) | "each unique expert of the batch is read once"; "auto-sized from `MemAvailable` at startup" |
| ~0.05–0.1 tok/s cold, ~11 GB disk reads/token | **CONFIRMED** | README, verbatim |
| "inline fadvise blocked ~0.5 ms × 169k calls = +92 s/48 tok" | **UNVERIFIED** | not in the fetched README or the source excerpt; plausibly from a commit message/issue. Treat as anecdote; the surviving lesson (decouple I/O hints onto a worker) stands on sluice's evidence anyway |

### sluice ([github.com/Etelis/sluice](https://github.com/Etelis/sluice))

All of doc 01's claims **CONFIRMED**: vLLM v0.23 plugin (no fork,
`vllm.general_plugins`); experts in host RAM streamed into per-layer GPU slot
buffers; ROUTER-SPLIT keeps CUDA graphs with one eager gap
(`vllm::sluice_stream_gap` — pointer/content split, captured pieces point at
slot buffers whose *contents* the gap rewrites). Numbers: DeepSeek-V2-Lite
27 → **135.7 tok/s (5.4×)** vs classic eager gap; Qwen3-30B-A3B batch=8
offloaded **864.5 tok/s vs 742.3 resident (+16%)**. Negative results verbatim:
`SLUICE_RS_STAGED` **−6–8%**, `SLUICE_LAZY_STEP` **−12–17%**, GEMM-graph
parked on five documented capture hazards. Correctness: md5-equal tokens over
8,000 gap calls; bit-identical under 11,497 forced misses.

### KTransformers ([github.com/kvcache-ai/ktransformers](https://github.com/kvcache-ai/ktransformers))

**CONFIRMED**: "Heterogeneous expert placement (hot experts on GPU, cold
experts on CPU)"; "3-layer (GPU-CPU-Disk) prefix cache reuse" (2025-06-30);
SOSP 2025 paper "KTransformers: Unleashing the Full Potential of CPU/GPU
Hybrid Inference for MoE Models". (Its disk tier is for *prefix cache*, not
expert weights — the expert hot/cold split is GPU/CPU. Doc 01's phrasing
"cold-on-CPU-or-disk" mildly overstated the disk half; the lineage claim
stands.)

### VibeBlade ([github.com/kevin046/VibeBlade](https://github.com/kevin046/VibeBlade))

**CONFIRMED**: "MoE tiered memory … 3-tier VRAM/RAM/SSD with adaptive
eviction", "near-native latency" claimed; toolkit-style stack (speculative
decoding 1.3–3×, activation sparsity 1.3–2.5×, KV quant ~8×). Marketing-grade
numbers — corroborates the *pattern*, contributes no transferable mechanism
detail beyond colibrì/KTransformers.

### The `pread`-vs-mmap method itself (literature)

colibrì's "no mmap for the streamed tier" is not idiosyncratic — it is the
standard DBMS finding. Crotty et al., **CIDR 2022**, "Are You Sure You Want to
Use MMAP in Your Database Management System?"
([pdf](https://db.cs.cmu.edu/papers/2022/cidr2022-p13-crotty.pdf)): when the
working set exceeds RAM, mmap suffers (1) page-table contention, (2)
**single-threaded kernel page eviction** (kswapd CPU-bound), (3) **TLB
shootdowns** on eviction (thousands of cycles each); throughput degrades
2–20× right at the memory-full point, and the page cache cannot saturate
modern NVMe. **This is precisely our measured 150M@32GB regime** — the
62 GB index > 32 GB host where sequential serving went warm≈cold 15.8 s
(2026-07-01). The paper *strengthens* doc 01's framing of `pread`+own-cache
as the foundational (if expensive) lever — see §3.4 for why it still isn't
first in line.

---

## §2 Doc 01 corrections (same-session doc-freshness rule)

1. **Candidate #2's granularity was wrong.** Doc 01 proposed an LRU/pin of
   "the hottest **shards**". A federated query fans out to **all 8 shards
   every query** by construction (`_fan_out` in both serving classes; docs are
   partitioned across shards, every shard holds candidates for every query).
   **There is no shard-level skew to exploit** — zero, structurally, not
   empirically. The only granularities where skew can exist are posting-list /
   posting-block / forward-page level *within* every shard. Doc 01 hedged
   "(or, finer, hottest posting-list blocks)" — the hedge is the whole lever.
   Corrected in doc 01 (dated note, this session).
2. **Candidate #1 needs no Rust at all.** Doc 01 proposed "a small env-gated
   counter in the Rust `search_raw_visited` path". The pyo3 surface **already
   returns the visited set to Python** — `search_visited` shipped with Q6/E5
   (`spike/seismic_upstream/src/pylib/mmap_index.rs:251`, returns
   `(results, visited_starts)`). Page-touch telemetry is a pure-Python script
   over the existing instrument. Proven by running it: §5 (Q12).

---

## §3 Feature-by-feature: actually useful here? (the double-check)

Setting: the streamed tier = the dv forward index (~25 GB over 8 shards,
`forward_data.bin` per shard); the resident tier = the structural floor
(~1.5 GB posting lists + doc mapping + forward offsets, already prefaultable —
Q9 `SFU_SEISMIC_PREFLOOR_AT_LOAD`). Cold/warm envelope measured 2026-07-09
in-container (`e5_fullcorpus_cold_container_*`): parallel cold p50 ~2.6 s,
sequential cold ~2.2 s, warm parallel 80–101 ms. The RAM-capped 32 GB host
regime: sequential warm≈cold **15.8 s** (2026-07-01) because 62 GB (f16) >
RAM → every pass re-faults.

### 3.1 Usage telemetry + persisted hot set (colibrì `eusage`/`.coli_usage`) — **USEFUL, and nearly free**

The premise everything else hangs on: *does a hot set exist in SPLADE
traffic?* Two mechanisms argue yes, a priori: query terms are Zipf-distributed
(hot posting lists), and high-impact docs recur across related queries (hot
forward pages — exactly the co-access structure E5 measured and exploited).
But E5 also already *harvested* part of this: `block_walk_canonical` packed
co-accessed docs onto shared pages (cold majflt 0.53–0.54×), which both
(a) shrinks the marginal win left for a pin tier and (b) makes any remaining
hot set *cheaper to pin* (contiguous extents, not scattered pages).
**Verdict: run the telemetry first — it is a Python script over an existing
instrument (§2.2), and its result decides everything downstream. Done as Q12,
results §5.**

### 3.2 Software LRU + hot-pin above the page cache (colibrì `ESlot`/`pin`) — **CONDITIONALLY useful, corrected granularity**

Where it can win: the **RAM-capped host** (the G8/sequential open risk).
There, the kernel's eviction policy is the enemy: it evicts by global LRU
approximation with no knowledge that (say) 3 GB of forward pages serve 60% of
candidate touches. `mlock`ing a measured hot set + letting the rest stream
converts that fraction of per-pass re-faults into RAM hits. On hosts with
RAM ≥ working set (the served container today) it adds nothing — the page
cache already keeps everything (warm 80–101 ms is already RAM-speed).

Honest bound: a pin tier **cannot** beat capacity math. If Q12 shows the
hot-set-80 is ~4 GB it's a real lever on a 32 GB host; if hot-set-80 is
~20 GB, pinning is just a worse page cache. **Verdict: useful iff Q12 GO;
per-page/per-extent granularity, never per-shard (§2.1).**

### 3.3 Router-lookahead prefetch (colibrì PILOT) — **WEAKLY useful at best; hardest precondition set**

The honest mapping is unflattering in three ways doc 01 under-weighted:

1. **colibrì's predictor is cheap and early; ours is neither.** Its router
   look-ahead gets 71.6% of next-layer experts from data already in registers,
   *layers* ahead of use. Our candidate set materializes only as posting-block
   summaries are evaluated — the natural analog is a *two-phase traversal*
   (evaluate summaries → batch-prefetch surviving ranges → score), a real
   restructuring of `posting_list.rs::search`, not a hint bolt-on.
2. **The cold path has no spare I/O channel.** Our own measurement: cold
   *sequential* beats cold *parallel* (2159 vs 2687 ms) because 8-way
   concurrent faulting **contends on the 9p/disk channel**. Prefetch is more
   concurrency on that same channel. colibrì overlaps disk with *compute*
   (GEMMs); our cold queries are I/O-dominated with little compute to hide
   behind.
3. **Every adjacent negative result points the same way**: our per-query
   WILLNEED — zero effect + syscall overhead (E7 Fix #3, REFUTED 2026-07-03);
   sluice's staged prefetch −6–8% and lazy-step −12–17%.

**Verdict: park.** Only revisit if Q12 shows strong locality AND a
channel-headroom measurement shows cold faulting is latency-bound (queue
empty) rather than bandwidth-bound. Doc 01 already made #3 conditional on #1;
this doc adds the second precondition.

### 3.4 `pread` + explicit buffer cache (colibrì's foundation) — **well-founded (CIDR 2022) but still last**

§1 shows the literature is squarely on colibrì's side *for the >RAM regime*,
and our 32 GB-host symptom (warm≈cold, kswapd-driven re-fault churn) is the
textbook presentation. But: (a) it fixes *eviction policy and readahead
control*, not capacity — the 15.8 s floor is mostly capacity misses that no
reader rewrite removes; (b) it is the biggest lift (a second forward read
path in `mmap_io.rs`/vectorium, duplicating the zero-copy view machinery);
(c) a Python/pyo3-level pin tier (§3.2) extracts most of the same control at
~10% of the cost. **Verdict: unchanged from doc 01 — escalation path only,
now with a proper citation.**

### 3.5 Already-shipped mirrors (no action)

Confirmed as already-held ground, no new work: OS-page-cache-as-L2 (default
regime), DONTNEED-between-units (`release_pages`, mechanism B), batch dedup
(`visited` set), floor prefault ≈ dense-resident tier (Q9), adaptive
cold→warm flip (Q7 hybrid), negative-result ledger (this testbed).

---

## §4 Integration map — how each candidate lands in the current modules

Invariant shared by all: **none touch `_merge_topk`, scoring, or record
decode → T1 bit-identical parity is preserved by construction** (page
residency and I/O scheduling only). All env-gated OFF by default.

| Candidate | Touches | Interactions & gotchas |
|---|---|---|
| **#1 telemetry (Q12)** | `scripts/seismic_testbed/q12_access_skew_probe.py` (new, done); reads pyo3 `search_visited` | Zero serving change. Word-offset→page mapping is layout-aware (dv: ×8; f16: ×2). If promoted to always-on serving telemetry later: a `Counter` + periodic JSON dump in `_SeismicBackendBase.search_encoded`, ~30 lines, off the hot path (visited return adds a Vec copy per query — measure before enabling per-query in prod) |
| **#2 LRU/pin tier** | `mmap_io.rs`: new pyo3 hooks `prefault_ranges(pages)` / `mlock_ranges(pages)` / `release_pages_except(pages)` (extend the existing `prefault_floor`/`release_pages` lineage); `sharded_seismic_backend.py`: load hot-set sidecar (the `.coli_usage` analog, e.g. `<shard>.mmap/hotset.json`) at construction, prefault/mlock it Q9-style | (a) **`MADV_DONTNEED` fails with EINVAL on mlocked ranges** — `release_pages` must become range-splitting around pinned extents, or mechanism B flips to `MADV_PAGEOUT` for unpinned ranges; (b) pin budget must come off `MemAvailable` (colibrì discipline) minus the Q9 floor; (c) composes with Q7 hybrid — a warm pin tier lowers cold traverse, so the adaptive flip threshold self-adjusts (no change needed, it's derived from observed cold); (d) E5 reorder makes hot extents contiguous → store the hot set as extents, not pages; (e) sidecar is per-`forward_reordered` layout — a re-reorder or dv-v2 (E8 Stage-2) reconversion **invalidates the hot set** → key it on the manifest's `forward_format_version` + `forward_reordered` |
| **#3 PILOT analog** | `spike/seismic_upstream/src/posting_list.rs` (two-phase or block-skip predictor), new I/O worker + SPSC ring in Rust, hooks in `inverted_index.rs` traversal | Parity-safe only if strictly hint-issuing (no reordered scoring). Preconditions: Q12 locality GO **and** cold-channel headroom measurement (new micro-bench: fault throughput 1-thread vs 2 vs 4 on `forward_data.bin`). Interacts destructively with sequential serving (mechanism B evicts what prefetch loaded) — parallel/hybrid-warm arm only |
| **#4 pread reader** | `mmap_io.rs` forward read path + vectorium `MmapPackedSparseDataset` (second storage impl), buffer-pool module | Escalation only after #2 measurably hits the kernel-policy ceiling. Keeps posting lists mmap'd (they're the prefaulted floor); forward only. O_DIRECT variant interacts with 9p (untested on drvfs/9p — likely unsupported or slow; host-tier ext4 only) |

Cross-cutting: everything keys off the served E5 dv manifest
(`seismic_c25_shards_150m_mmap_e5.json`); E8 Stage-2 (dv-v2 8-shard
reconversion, IN PROGRESS) will re-emit shards — hot-set sidecars and any
pin-tier gating must re-derive after that lands, so **do not build #2 mid-E8**.

---

## §5 Q12 probe — the measured validity test (2026-07-13)

Pre-registered (prediction + decision rule written and committed before the
run): `11_EXPERIMENT_BACKLOG.md` §Q12. Script:
`scripts/seismic_testbed/q12_access_skew_probe.py`. n=120 topic-independent
diverse queries × 8 E5-dv shards, served shape (k′=100, hf=0.8), page-level
histogram of `search_visited` forward touches; secondary 20-topic×3-paraphrase
repeat-traffic stat.

**MEASURED 2026-07-13** (n=120 primary + 60 paraphrase queries, 400 s
in-container, `data/eval_results/q12_access_skew_probe_20260713.json`):

| Metric | Predicted (*est.*) | Measured |
|---|---|---|
| top-10% touched pages' share of touches | ≥50% | **34.2%** — prediction MISSED (skew real but moderate; Gini 0.442 over touched pages) |
| cross-topic repeat-touch fraction | ≥25% | **85.2%** — far exceeded (58% of touched pages hit by ≥2 of 120 queries) |
| hot-set-80 | ≤ ~4 GB | **4.20 GB** — 5% over the bar |
| hot-set-50 / hot-set-90 | — | **1.59 GB / 5.95 GB** |
| distinct pages touched | — | 2.03 M = **27.2%** of the 30.5 GB dv forward (72.8% never touched by 120 diverse queries) |
| per-query touch footprint | — | ~48 k pages ≈ **~197 MB/query** pooled over 8 shards |
| within-topic (paraphrase) warm-hit | — | **62.1%** of a paraphrase's pages already touched by its sibling; pairwise Jaccard 0.44 |

**Verdict under the pre-registered rule: GRAY ZONE (live-leaning).** The
live condition (`hot-set-80 ≤ 4 GB AND repeat ≥ 25%`) is missed by 0.2 GB on
one leg; the close condition (`> 8 GB OR repeat < 10%`) is nowhere near. Per
the rule as written: **candidates #2/#3 are neither closed nor green-lit — the
next gate is a re-run on a production-shaped query log** (the pre-recorded
caveat cuts favorably: real library traffic repeats subjects far more than a
diversity-maximized eval set, so production skew should be ≥ this).

What the numbers say beyond the bar arithmetic (recorded, not a verdict):

- **The colibrì premise does transfer directionally** — traffic is far from
  uniform: 85% of touches are repeat-page touches, a **1.6 GB pin absorbs
  half of all touches** (5% of RAM on the 32 GB host), and 73% of the forward
  index is dead weight for this query mix. A software pin tier has a real
  target to aim at.
- **But it is not colibrì-grade skew** — no small hot set dominates (top-10%
  of pages ≠ 50% of touches), so a pin tier caps out around the coverage
  curve: ~50% of touches at 1.6 GB, ~80% at 4.2 GB, diminishing after.
- **The paraphrase stat (62% warm-hit) is the strongest single argument** for
  a usage-persisted hot set on the RAM-capped host: consecutive related
  queries re-touch most of each other's pages — precisely what mechanism-B
  sequential serving currently *evicts* between shards.

---

## §6 Estimated uplift & worth-developing verdicts (all *est.* unless cited)

Envelope anchors (measured): container cold p50 ~2.2–2.7 s vs warm 80–101 ms
(≈25× cold/warm gap = the absolute ceiling for *any* caching lever);
RAM-capped host sequential warm≈cold 15.8 s (the regime the levers target).

| Candidate | Regime it helps | Uplift (*est.*) | Dev cost | Verdict |
|---|---|---|---|---|
| **#1 telemetry** | none (decision value only) | 0× serving; decides #2/#3 | ~0.5 day — **spent, done as Q12** | ✅ **DO (done)** |
| **#2 LRU/pin** | RAM-capped host (32 GB, 15.8 s floor); also faster process-cold warmup via hot-set prefault | if Q12 GO (hot-set-80 ≤ 4 GB): **~2–4× p50** on the capped host (pin absorbs ~50–80% of per-pass re-faults; capacity misses keep the rest); if Q12 uniform: **~1.0× (nothing)**. Served container today: ~1.0× warm (already RAM-speed), moderate cold-start win from prefaulting the hot set (bounded by the 25× envelope, realistically **1.3–2× cold p50**) | ~2–4 days (pyo3 range hooks + sidecar + backend wiring + EINVAL-splitting) | ⚖️ **CONDITIONAL — Q12 measured GRAY (live-leaning: hot-set-80 4.20 GB vs the 4 GB bar, repeat 85%; §5). Next gate = production-shaped query log; do not build before that AND E8 Stage-2 lands.** Revised uplift with the measured curve: a 1.6 GB pin covers 50% of touches / 4.2 GB covers 80% → on the capped host, **~1.5–3× p50** (*est.*, down from 2–4× — skew is moderate, not colibrì-grade) |
| **#3 PILOT analog** | cold queries on hosts with idle I/O channel | **≤1.3× cold, 1.0× warm** — and plausibly <1.0× (channel contention; three adjacent negative results) | ~1–2 weeks (Rust traversal restructure + worker + ring) | ❌ **PARK** — two preconditions (Q12 GO + channel headroom), poor risk/reward vs #2 |
| **#4 pread+LRU reader** | same as #2, past the kernel ceiling | uplift over #2 unknown; bounded by whatever #2 leaves (eviction-policy losses: TLB shootdowns, kswapd — CIDR 2022 says 2–20× exists *in general*, our residual after #2 is the open question) | ~2–3 weeks | ❌ **DEFER** — escalation only, after #2 ships and measurably plateaus |
| **skew→uniform outcome** | — | if Q12 shows uniform access: **close the whole streaming-tier track**, remediation stays Tier-2 #5 (no-swap host / mlock-floor) — colibrì's own concession ("RAM cap, not disk speed, is the binding constraint on small machines") applies verbatim | 0 | the honest exit |

Bottom line: **one cheap measured probe (Q12) gates the entire investment**;
#2 is the only candidate with a credible payoff, and only for the RAM-capped
deployment shape; #3/#4 are parked/deferred with explicit revival conditions.

---

## Sources (fetched/verified 2026-07-13)

- colibrì README + `c/glm.c`: <https://github.com/JustVugg/colibri>
- sluice README: <https://github.com/Etelis/sluice>
- KTransformers README: <https://github.com/kvcache-ai/ktransformers>
- VibeBlade README: <https://github.com/kevin046/VibeBlade>
- Crotty, Leis, Pavlo — "Are You Sure You Want to Use MMAP in Your Database
  Management System?", CIDR 2022:
  <https://db.cs.cmu.edu/papers/2022/cidr2022-p13-crotty.pdf>
- Internal anchors: `seismic_150m_testbed/06_FINDINGS.md` (sequential-serving
  tie, G8), `10_FORWARD_COMPRESSION_DESIGN.md` (WILLNEED/MADV_RANDOM
  refutations), `13_E5_FORWARD_REORDER_DESIGN.md` (co-access locality),
  `11_EXPERIMENT_BACKLOG.md` §Q12 (this probe's pre-registration).
