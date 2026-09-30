# 05 — Brief: in-place bit updater + custom encoder/decoder over the immutable base

> **CLOSED MEASURED 2026-09-30** — the pre-registered GO rule of `06_INPLACE_SPIKE_PLAN.md` read NO-GO: bar S0-1 measured a long-list dead-slot coverage of **0.019** (95 % CI 0.018–0.020) against 0.80. In one quarter 27 % of shard 0's docs are updated and 15 % more are new while deletions free 6 %, and a list cannot grow, so dead-slot reuse cannot absorb the churn (`inplace_s0_20260930.json`). Nothing in-place replaces it: updates stay with delta generations (`docs/delta_ingest/`). The v3 encoder/decoder is exact (B1 460/460, +1.3 % per query) and the +tail variant was built, but they remove the wrong obstacle. Full record: `docs/archive/inplace_update/06_INPLACE_SPIKE_PLAN.md` results table and §"NO-GO 2026-09-30". Not current; do not resume.

**Status:** CLOSED MEASURED 2026-09-30

**Written 2026-09-29** in cloud session `session_01DDVDP4QNv6y5xe28YGtt9z`
(conversation with the owner) as the dispatch brief for the local session
`session_01W21GKQhsdhoE9jbxQScFr5`. Nothing in this document is measured.
Every number is *est.* or a snippet-level literature fact unless it cites a
results file. Sources were read as search snippets only (arXiv, Springer,
MDPI and the OpenAlex docs are egress-blocked from the cloud container);
each is marked `[snippet]` and must be re-read before being quoted as fact.

**State: DESIGN ONLY, EFFICACY UNMEASURED. Zero code exists for this track.**

> **Reconciliation note 2026-09-29 (local session, at merge).** The brief was
> written from a branch forked at `3cc64680`; the local tree had moved on.
> Where the text below disagrees with this note, this note is current.
> 1. `04_IMMUTABILITY_RESEARCH.md` EXISTS (commit `7fca4721`). §1.7 and §8.5
>    calling it missing are stale; the task is to extend it with §3's sources
>    re-read and re-marked, not to create it.
> 2. The twin-shard rebuild is not "UNVERIFIED" but a **FAILED BAR**:
>    overlap@10 0.9858 / 0.9870 vs 0.99
>    (`data/eval_results/delta_ingest_twin_rebuild_20260929.json`, M9 in
>    `03_SPIKE_PLAN.md`). Arm A3, the §2.8 compactor, and bars S0-2 / B6 use a
>    rebuild as reference; every such bar is scored against the served base
>    A0 as well, and the rebuild's own 0.986 is recorded as the known ceiling
>    of that path.
> 3. M7 churn filter is a **FAILED BAR** (≈1.15:1 and ≈2.61:1 *est.* vs
>    < 3:1, `data/eval_results/delta_ingest_M7_20260929.json`): nearly every
>    touched record must be re-encoded, so Stage 0's "one quarter of churn"
>    demand is the touched volume, not a filtered fraction of it.
> 4. M1 PASS on the clean run, M6 recorded, livedocs G1/G2 PASS partial
>    101/120 — see `03_SPIKE_PLAN.md` addendum. M2–M5, M8, M10 remain NOT RUN.
> 5. Host limits for the dispatch (open issue O12 in `02_DESIGN.md`, 9p
>    `.venv` import ENOMEM): latency runs serialize on
>    `/tmp/sfu_latency_measure.lock`; eval scripts assert all models loaded
>    before measuring.
>
> **Correction note 2026-09-29 (after the source re-read).** Every `[snippet]`
> source of §3 was re-read where it could be opened; the verification table
> and findings are in `04_IMMUTABILITY_RESEARCH.md` §"Addendum 2026-09-29".
> The finalised bars are in `06_INPLACE_SPIKE_PLAN.md`. Claims below that the
> re-read does NOT support, left in place as the record of what was dispatched:
> 1. §2.5 "a crash mid-batch leaves epoch e serving" — refuted for evictions
>    and same-batch slot reuse (the overwritten content is gone); holds only
>    for slots already dead at the published epoch.
> 2. §2.4 "recall cannot drop" — SEISMIC block summaries are approximations,
>    not upper bounds, and a component absent from a summary cannot be
>    covered by an inflation byte. DESIGN ONLY.
> 3. §3 both "appears novel" rows — partially anticipated (top-k view
>    maintenance, Yi et al. ICDE 2003; updatable looser block bounds,
>    Macdonald & Tonellotto ICTIR 2017; list-level bound raising, Rule &
>    Mackenzie 2026).
> 4. §3 attributions: the in-place scalar updates in arXiv 2605.01260 are
>    Vespa Proton's, not Uber Sia's; Moffat & Mackenzie use linked blocks and
>    their ~2 B/posting is for frequency postings; hawdb issue 292 supports
>    the delta design; "~65 % query time, no precision loss" has no source.
> 5. §1.1 "11–57 % fabricated" has no source; the 45 % figure is one study
>    (GPT-4o only). OpenAlex: a key is optional for small use ($0.10/day
>    without, $1/day with a free key), per the docs read 2026-09-29.
> 6. §7 "mmap coherence holds on both platforms" — local files only.

---

## 0. What the local session is asked to do

Reconciled 2026-09-29.

1. Open a spike for this track inside the thin client (NOT a separate dev
   container — §7 gives the reasons). Proposed paths: code
   `spike/archive/inplace_update/`, docs stay in `docs/delta_ingest/` (this track is
   the compaction-avoidance layer of that design), results
   `data/eval_results/inplace_*`.
2. Deploy Opus agents (owner's instruction), split as in §8.
3. Focus: the **bit updater** (in-place slot/record/summary writes into the
   served dotvbyte-v2 shard files) and the **custom encoder/decoder** that
   makes those writes legal and atomic.
4. **Fully benchmark against what we ingest with today**: the delta layer
   (`02_DESIGN.md`, generations + newest-wins masks, gate `SFU_DELTA_ROOT`)
   and the full per-shard rebuild from f16 twins (`04_HANDOFF` item 4). The
   arms and bars are pre-registered in §6; write them into `03_SPIKE_PLAN.md`
   (or a sibling plan) BEFORE any number is produced.
5. Obey `.claude/CLAUDE.md` (pull → edit → add specific files → commit →
   push; same-commit doc rule; `**Status:**` lines; absolute dates; no
   inline code comments in product code; `data/seismic_150m/` is READ-ONLY —
   all in-place writes go to a COPY of one shard under a gitignored work dir).

---

## 1. Conclusions of the 2026-09-29 conversation (context the agents need)

1. **"LLM approximates the record, online DB fixes the bits" — rejected.**
   The index stores deterministic functions of a tiny record (title,
   abstract, year, type, DOI). Given the record the encoder is exact; without
   it an LLM fabricates. 2025–26 studies: 11–57 % of LLM citations fabricated,
   45 % of the real ones carry field errors, DOI worst `[snippet]`. OpenAlex
   single-entity lookups are free (keys mandatory, $1/day free budget,
   list/filter $0.10/1k, search $1/1k, 100 req/s) — verification IS the
   cheap step and yields the exact record, so the draft is dead weight.
   Legitimate LLM roles: candidate generator whose output survives only as a
   lookup key; doc2query-style expansion for abstract-less records (gains on
   SPLADE smaller than on BM25, needs filtering, must be measured).
   **Repo drift found:** `src/lib/openalex.py` still enforces the retired
   10 req/s polite pool + 900-call/day cap; `01_RESEARCH.md` §1.2 already
   flags it. Separate small task.
2. **"Immutable" here is three things.** (a) The *encoding* — packed
   postings and Elias-Fano summary offsets are dense, so an insert shifts
   everything after it in that list (theorem about the code, not the
   medium). (b) *Concurrent readers* — a query walking a list while it is
   rewritten reads garbage; the cheapest primitive is an aligned 8-byte
   write, atomic on x86-64. (c) *Policy* — `CODE_INVARIANTS.md` forbids
   mutating the served base because parity gates compare against a fixed
   reference; a version stamp satisfies it.
3. **No fourth way in general.** Redirection costs reads, gaps cost space,
   rebuild costs writes (RUM conjecture, already cited in `04_HANDOFF`).
   Every published in-place system is redirection + a little slack with
   better bookkeeping. The question is the minimum of each.
4. **Page-level overlays** (CoW filesystem snapshot, `MAP_PRIVATE` patches,
   userfaultfd, patch map in the reader) fit only fixed-size edits; one
   updated doc touches ~100 pages (≈400 KiB) vs ~1 KB in the delta layer →
   dominated for OpenAlex churn. Operational win only: snapshot before a
   shard rebuild = free rollback + block-level distribution delta.
5. **Direct bit editing that IS real today** (`04_HANDOFF` item 5a is the
   design-only lever): fixed-width fields — a doc's f16 values with
   unchanged nnz, a block summary max, a forward offset, the 48-bit pointer
   inside a packed posting. Plus **spare bits**: each posting stores a 48-bit
   offset into a ~3 GB shard (needs ~32 bits) and a 16-bit nnz (typ. ~88) →
   ~20 spare bits/posting; each per-doc `forward_offsets.bin` entry is 8 B
   for a ~33-bit value → ~30 spare bits/doc. Tombstone/epoch/version tags
   can live there at zero size cost.
6. **Already on the table in `04_HANDOFF`, not new:** SPFresh-style
   append-and-repoint (DESIGN-ONLY, gated on M4), slack-space format
   (CLOSED), twin-shard per-shard rebuild (item 4, UNVERIFIED; ~17–19 min
   build + minutes convert, peak ~10 GB, serial), era/time partitioning
   (DEFERRED), livedocs bitset (item 3/C, built).
7. **Genuinely untried angles named in the conversation** (recorded for the
   backlog, NOT this spike): backward-compatible query-encoder upgrades over
   frozen doc vectors; chunk-level distribution deltas (`zstd --patch-from`
   long-range / Prolly-tree structural sharing) between shard builds;
   query-time federation with the live OpenAlex API for the newest slice;
   `04_IMMUTABILITY_RESEARCH.md` (dispatched item H) does not exist yet.

---

## 2. The design (this spike's object)

Key insight: SEISMIC is already lossy on purpose — posting lists are
truncated to top-λ postings per term and block summaries approximate block
maxima. A lossy structure can absorb churn by **replacement** and by
**loosening its approximations**, without growing.

### 2.1 Dead space inventory (per dv-v2 shard, `09_CROSS_SHARD_MMAP_AUDIT.md` §file table)

| Dead space | Where | Reusable for | Reached via |
|---|---|---|---|
| deleted doc's forward record (~175 B) | `forward_components.bin` / `forward_values.bin` | any record with nnz ≤ hole | pointers only → free list works |
| deleted doc's posting slot (u64) | `posting_lists.bin` packed postings (323 MB) | a new posting for the same term | slot overwrite, list length unchanged |
| ~20 spare high bits/posting, ~30/doc offset | inside existing u64 fields | tombstone, epoch, flags | masked write, nothing moves |
| bytes freed by shrinking a list on delete | tail of that list | future inserts into that list | organic slack, paid by churn |

### 2.2 Mechanism A — forward heap with size-class free list

Forward records are never scanned, only dereferenced. Maintain a free list of
holes bucketed by byte size (jemalloc-style classes). New/re-encoded record
→ smallest fitting hole → write → repoint the doc's `forward_offsets.bin`
entry (8 B, atomic) and each of its packed postings' 48-bit offsets. Record
that fits no hole → append at tail (the existing append-and-repoint path).

### 2.3 Mechanism B — bounded posting lists with slot reuse + eviction

List capacity = its build-time truncated length (never grows). Insert of a
new doc containing term t: (1) take a dead slot if one exists; else (2) if
the new weight > the list's current minimum-weight posting, overwrite that
slot (eviction — the evicted doc stays in the forward index and reachable
through its other terms, exactly the loss profile truncation already
imposes); else (3) drop the posting from this list. Eviction needs the
per-list minimum: keep a small side array (u16 quantized min + slot index
per list) — fixed width, in place.

### 2.4 Mechanism C — monotone bound loosening instead of re-clustering

A block summary approximates the block's per-component maxima (u8 values +
f32 min/quant). An inserted doc whose weights sit under the summary costs
nothing. One that exceeds it: raise the u8 component (fixed width) and, if it
overflows the quant range, bump the block's f32 scale. Cheaper variant: **one
per-block inflation byte** (≈3.3 M blocks/shard from `block_offsets` 26 MB /
8 B → ~3.3 MB/shard) the scorer multiplies into the bound. Raising a bound
only makes the block visited more → recall cannot drop; latency degrades
slowly; compaction resets it.

### 2.5 Mechanism D — epoch bits + one atomic header flip

Every in-place write tags its slot's spare bits with epoch e+1. Readers
ignore slots tagged above the epoch in the shard header (or a dual meta
record, LMDB-style: two headers, txn id written last, readers take the
newer valid one). A batch of thousands of writes becomes visible with ONE
aligned 8-byte header write; a crash mid-batch leaves epoch e serving.
Replaces the generation directory as the consistency primitive.

### 2.6 The custom encoder/decoder (format v3, proposed)

Rule: **dense coding where data is frozen, fixed-width where it is mutable.**
Keep dotvbyte for forward values and Elias-Fano for the immutable parts of
summaries. Change three things:
- per-block free-slot bitmap + epoch in the spare bits of existing u64
  postings (no new bytes);
- forward-heap header with size-class free lists in a small side file,
  written by the encoder at build, maintained by the updater;
- per-block inflation byte, read by the block-scoring loop as a multiplier.
Decoder = current reader (`spike/vectorium_fork`, `seismic_upstream` patch
chain) + three masks + one multiply in the scoring loop. Encoder = current
converter (`convert_f16_to_dotvbyte --value-scale perdoc`) + emit empty
bitmaps/free lists. **Format version bump; parity gate must pass
bit-identical with zero patches applied.**

### 2.7 Hybrid rule (from the literature, §3)

In-place for LONG lists (steady dead-slot supply, high-weight common terms);
the delta L0 buffer for SHORT lists (rare terms, no slack). Pure in-place
loses at high update rates in every published comparison. Trickle updates
stay in the buffer; in-place applies them in **term-sorted batches** so all
new postings for one term land in one list and page touches coalesce.

### 2.8 Compactor

When dead fraction or mean inflation crosses a threshold: per-shard rebuild
from the f16 twin (`04_HANDOFF` item 4 path, ~17–19 min + convert), which
re-tightens summaries and defragments. Threshold set by bar S0-3.

---

## 3. Prior art (searched 2026-09-29; all `[snippet]`)

| Design piece | Prior art | Status |
|---|---|---|
| in-place updates on a static inverted index | Lester, Zobel, Williams 2004/2006; Büttcher & Clarke 2006/2008 | done; verdict: in-place wins only at LOW update rate; hybrid (in-place long lists, merge short) beats both |
| in-place revived on SSDs | MFIS 2014 (non-contiguous lists, flash parallelism) | done; the HDD random-write objection is weaker on NVMe |
| immediate-access dynamic index for learned sparse | Moffat & Mackenzie IPM 2023 (extensible arrays, ~2 B/posting); Rule & Mackenzie ECIR 2026 | done — closest work; they chose a GROWABLE format, template for a custom encoder |
| production in-place partial updates | Write-Read Decoupling survey (arXiv 2605.01260, May 2026): Uber Sia, Alibaba Havenask route scalar fields to O(1) in-place | done |
| provisioning empty posting positions | US patent 10474650 | = the CLOSED slack track; know it exists |
| free-list reuse of dead heap records | every storage engine; LMDB freelist | done |
| epoch/version tags, atomic publish by one write | LMDB dual meta pages (txn id last); MERIT 2026 versioned-edge invalidation for graph ANN (3–19× faster deletes, recall stable) | done in other structures |
| truncated top-k lists as the index | static index pruning: Carmel et al. 2001 (ε-guarantee on top-k), Suel; truncation to bounded top set → ~65 % query time, no precision loss | done, STATIC only |
| insert-by-eviction into a bounded list under churn | nothing found | **appears novel → bar S0-2** |
| monotone loosening of block-max bounds vs re-clustering | nothing beyond "bounds must stay upper bounds" (hawdb issue 292 hints at overlay adjustments) | **appears novel → bar S0-3** |
| in-place vector-index updates | SPFresh/LIRE (SOSP 2023), FreshDiskANN, IP-DiskANN 2025, DGAI 2025 | done; SPFresh is the clustered-index analogue of Mechanism B |

Sources (re-read before quoting): researchgate 221574123 (Lester et al.
2004); people.eng.unimelb.edu.au/jzobel/fulltext/ipm06.pdf; Springer
10.1007/s10791-007-9042-8 (Büttcher & Clarke); ScienceDirect
S030643791400180X (MFIS); arXiv 2211.06030 (Moffat & Mackenzie); Springer
10.1007/978-3-032-21324-2_1 (Rule & Mackenzie 2026); arXiv 2605.01260
(Write-Read Decoupling); github.com/alibaba/havenask wiki; US 10474650;
arXiv 2607.29173 (MERIT); alphaxiv 2502.13826 (IP-DiskANN); arXiv 2105.09613
(FreshDiskANN); dl.acm.org/doi/10.1145/3600006.3613166 (SPFresh);
lmdb.tech/doc; researchgate 221301210 (Carmel et al.);
research.engineering.nyu.edu/~suel/papers/prune.pdf; arXiv 2405.01117
(Block-Max Pruning for LSR); github.com/nowledge-co/hawdb/issues/292.

---

## 4. What it buys (all *est.*, vs the delta layer — the real alternative)

| Dimension | Delta generations (`02_DESIGN.md` §3–§4) | In-place + custom decoder |
|---|---|---|
| SEISMIC probes/query | 8 base + 1 per live generation (≤8 before compaction) | 8, always |
| BM25 sections/query | 10 + 1/generation + buffer | 10 + a smaller buffer |
| meta / abstract probes | +1 SQLite probe per generation each | none extra |
| second query encode | while buffer non-empty, *est.* +10–40 ms (Q1) | same, less often |
| storage growth / updated doc | 1.0–1.3 KB until compaction, base copy retained | ≈0 when it fits a hole |
| write pattern | sequential 1 KB/doc, then compaction rewrites all | ~100 scattered 8-B slot writes/doc; MUST batch by term |
| publish | drop + re-mmap backend (cost UNMEASURED, M5), prefault/mlock state lost | one 8-B epoch write, no reload |
| rebuild cadence | compaction >8 gens + eventual fold-in | per-shard re-tighten from twins at threshold |
| quality | exact, newest wins | lossy on rare terms/evicted postings, bounded by existing truncation loss |

Sizing: M4 budgets ≤ +8 ms p50 per live generation (compaction at 8) → up to
~60 ms generation tax on a warm federated p50 of ~65 ms (G8b) — a doubling
at worst case; sequential mode adds ~30 ms/shard (248 ms at 8, G8g).
Parallel mode already doubles slowest-shard time at 8 concurrent shards
from memory-bandwidth contention (G8g: 12.9 vs 6.4 ms) — each generation
adds a competing thread; holding shards at 8 protects that tail. **The buy
is exactly the size of the measured generation tax; if M4 shows 1–2 ms/gen,
this design is a storage/publish nicety, not a latency lever.**

---

## 5. Why a spike inside the thin client, not a dev container

Data gravity (f16 twins, dv-v2 shards, qrels, gate scripts live only in the
owner's ClaudeBox container; `data/seismic_150m/` is irreplaceable); toolchain
gravity (vendored Rust forks, patch chain, portable-target rule
`spike/CLAUDE.md`: never `-C target-cpu=native` for shippable .so);
governance (Status lines, pre-registration, efficacy recording, closed-track
rules — `delta_ingest` is the template); dependency on an unrun bar (M4).
Extract to its own crate/container only after Stage 0 + M4 say GO and the
format proves out on this corpus.

---

## 6. Pre-registered arms and bars (write into the plan BEFORE measuring)

### Stage 0 — Python only, one twin shard, no Rust, zero serving impact

Inputs: one f16 twin `global_shard{i}of8.mmap` (read via
`scripts/seismic_testbed/stage0_candidates.py::open_forward`), the matching
served dv-v2 shard (read-only), one free OpenAlex snapshot partition set
(one quarter of `deleted_ids` + new works — M7's download), the 240-query
replay set / judged qrels already used by the delta plan.

| Bar | Measures | Threshold (proposed; local session finalises before running) |
|---|---|---|
| S0-1 supply vs demand | per term: dead slots from one quarter of deletions/merges vs new postings from one quarter of new works; split by list length decile | ≥ 80 % of new postings for lists ≥ 10 k slots absorbed WITHOUT eviction; report the decile where coverage falls below 50 % (= the hybrid cut-off) |
| S0-2 quality under synthetic churn | simulate insert/delete/replace per §2.3 for 1, 3, 6 quarters on the twin; overlap@10 and NDCG@10 vs a fresh rebuild of the same doc set | overlap@10 ≥ 0.99 at 3 quarters (the existing gate); record the quarter where it first breaks |
| S0-3 latency vs inflation | simulate block visits/query as bounds loosen per §2.4 (count blocks whose inflated bound clears the heap threshold) | ≤ +10 % block visits at the proposed compaction threshold; the threshold is an OUTPUT of this bar |

GO to Stage 1 only if S0-1 ≥ threshold for long lists AND S0-2 passes at
≥ 1 quarter AND M4 of `03_SPIKE_PLAN.md` (run it as part of this spike —
it is the comparison arm) shows a generation tax ≥ 3 ms p50/generation.
Otherwise: record CLOSED MEASURED with the numbers and stop.

### Stage 1 — Rust encoder/decoder on a COPY of one shard, head-to-head

Arms (same doc set = one quarter of real OpenAlex churn, same 240 queries,
same host, quiet-host gated like `warmcache_metric3_isolated_20260925`):
- **A0 base**: served dv-v2 shard, no updates (reference).
- **A1 delta**: base + N delta generations, N ∈ {1, 4, 8}, built by
  `spike/delta_ingest` (this IS current ingest).
- **A2 in-place**: base copy re-encoded to format v3 + the same docs applied
  in term-sorted batches via the bit updater.
- **A3 rebuild**: fresh per-shard rebuild from twin incl. the new docs
  (upper bound on quality, cost baseline).

| Bar | Measures | Threshold |
|---|---|---|
| B1 parity | v3 decoder on v3 shard with ZERO patches vs A0 | bit-identical top-k′ and scores (T1-style 20/20) |
| B2 apply cost | wall time + bytes written to apply one quarter (A2) vs build the equivalent generation(s) (A1) vs A3 | report; GO if A2 ≤ A1 |
| B3 query latency | `search_rrf` p50/p95 A0 / A1(N=1,4,8) / A2 / A3, parallel AND sequential backend | A2 within 5 % of A0; A1 numbers ARE the M4 result |
| B4 storage | shard bytes A1 vs A2 vs A3 after one quarter and after 4 | report |
| B5 publish | epoch flip (A2) vs `reload_index` drop + re-mmap (A1, = M5) | report; prefault/mlock state retained in A2 |
| B6 quality | overlap@10 / NDCG@10 A1 vs A2 vs A3 on judged qrels | A2 ≥ 0.99 overlap vs A3; A2 NDCG within CI of A1 |
| B7 crash safety | kill -9 mid-batch, reopen | serves epoch e, no torn reads (fuzz 100 kills) |

Results → `data/eval_results/inplace_{s0,b}_<YYYYMMDD>.json`; every doc
claim cites the file. Promotion (a served gate) is NOT in scope of this spike.

---

## 7. Known risks / open questions

- Rust changes in the vendored reader: comparable size to the closed slack
  track's "weeks of Rust" estimate minus the format-wide gap plumbing;
  keep the patch chain convention (`seismic_upstream_*.patch`).
- Lists with no dead slot and no evictable posting silently drop the new
  doc from that term — S0-1 quantifies how often; the hybrid rule bounds it.
- Updated docs written into holes lose the E5 reorder's page locality
  (Q6/E5 measured 0.376–0.400× pages/query from ordering) — bounded to the
  changed fraction; B3 catches it.
- Per-list minimum side array for eviction: size ≈ #lists × 4 B; confirm
  from `manifest.json` list count.
- Windows bundle: no userfaultfd needed (we do NOT use it); atomic 8-B
  writes + mmap coherence hold on both platforms.
- The 9p host path: in-place writes must target local disk copies
  (`THIN_CLIENT_SWAP.md` §Filter: 55× stage penalty on 9p).

---

## 8. Suggested agent split (Opus, per owner)

1. **Stage-0 measurement agent** — Python over the twin + OpenAlex partition;
   produces S0-1/S0-2/S0-3 JSON + a one-page findings note. Starts now.
2. **M4 comparison agent** — runs `03_SPIKE_PLAN.md` M4 (and M5) on the real
   stack with `spike/delta_ingest`; this is arm A1 and the GO input.
3. **Encoder/decoder agent** (blocked on GO) — format v3 in
   `spike/vectorium_fork` / `seismic_upstream` patch chain; B1 parity first.
4. **Bit-updater + benchmark-harness agent** (blocked on GO) — free list,
   slot reuse/eviction, inflation byte, epoch flip; harness for A0–A3, B2–B7.
5. **Docs/pre-registration agent** — writes §6 into the plan BEFORE agents
   1–2 report numbers; updates `docs/delta_ingest/README.md`, `docs/README.md`;
   creates the missing `04_IMMUTABILITY_RESEARCH.md` with §3's sources
   re-read and re-marked `[read]`.

Owner's stated priorities: the bit updater, the custom encoder/decoder, and
a FULL benchmark against current ingest (delta layer + rebuild). Stage 0 and
M4 exist to make that benchmark honest, not to defer it.

---

## Addendum 2026-09-29 (cloud session, after reading origin `e708b90`) — two proposals for the local session

Reconciled 2026-09-29. Written after reading `06_INPLACE_SPIKE_PLAN.md`,
`07_INPLACE_PAUSE_HANDOVER_2026-09-29.md` and the `04_IMMUTABILITY_RESEARCH.md`
addendum. Both proposals are DESIGN ONLY. Neither replaces a pre-registered
bar: where a bar is affected, the proposal is to pre-register the alternative
as a *supplementary* definition or arm in a dated addendum BEFORE the run,
beside the frozen one, never instead of it.

### P1. Vector-diff change filter (touches M7, the delta classify step, S0-1 demand)

**Problem.** The ledger holds no hashes for base docs, so every touched
in-base doc is classified `updated` (M7 as coded: 1.00:1), and `06` §"Fixed
inputs" counts every touched in-base doc as re-encoded (delete old postings
+ insert new). The handover estimates ≈11 M updated docs in shard 0 per
quarter (≈60 % of the shard, *est.*, one file). Yet M7's own text proxy on
the one hot section with a sidecar found the **encoder text changed for
25.3 %** of touched in-base docs (1,344 cosmetic / 302 minor / 871
substantive of 9,965). Demand is therefore inflated by roughly 4× (*est.*)
by a bookkeeping gap, not by real churn.

**Proposal.** Use the f16 twin's forward record as the base-side content
witness. For a touched in-base doc: encode the new text (already required to
produce demand), remap token ids, and compare the new sparse vector with the
doc's stored vector read via `stage0_candidates.py::open_forward`. Define
`unchanged` = identical component set AND every value equal after the f16
cast (exact; record a second, tolerant variant `max |Δw| ≤ 1 f16 ulp` as
supplementary). `unchanged` → no re-index, no dead posting, no demand.

Where it applies:
1. **Delta layer classify** (`spike/delta_ingest`): the missing base
   `content_hash`/`encode_hash` is replaced by a twin comparison for in-base
   ids; new ids are unaffected. This is the fix for the M7 FAIL's root cause
   (ledger without base hashes), not a re-cut of the M7 bar.
2. **S0-1** — record a second demand/supply pair `new_vd(L)`, `dead_vd(L)`
   under `supplementary` (only vector-changed docs count), beside the frozen
   definition. The GO rule keeps reading the frozen one unless the owner
   re-pre-registers before the run.
3. **M7** — re-score touched:must-encode with vectors instead of the text
   proxy, on the same two part files; a third number beside the two recorded.

**Costs, honestly.** The comparison itself is one ~175 B forward read per
touched doc. The encode is the real cost and it is unavoidable for the
comparison: at the M6 contended GPU rate (629.7 docs/s) 11 M docs ≈ 4.9 h per
shard-quarter (*est.*; clean rate UNMEASURED). Cheap pre-filter where it
exists: compare title+abstract text against the hot abstract sidecar (M7's
proxy) and encode only text-changed docs; sidecar coverage is hot sections
only, so the vector diff remains the universal detector.

### P2. Block- or list-level copy-on-write re-encode instead of slot patching + inflation byte (format v3)

**Problems it answers** (both from the `04` addendum):
- §B.2: SEISMIC summaries are α-mass-pruned, quantised, sparse
  approximations, not upper bounds. A component absent from a block's
  summary cannot be added in place, a scalar inflation byte cannot represent
  it (`blind_mass`), and recall is not monotone under a moving heap
  threshold. Mechanism C's premise is refuted.
- §D: an epoch flip cannot roll back a slot that was live at the published
  epoch (eviction, same-batch reuse, raised summary bytes). Mechanism D's
  crash claim is refuted as written.

**Proposal.** Never overwrite a byte a published epoch can reach. The write
unit is a whole SEISMIC block (or, see the caveat, a whole list): decode it,
apply inserts/evictions/deletes, **rebuild its summary exactly as the build
does** (α-mass over the component-wise max, u8 quant with per-block
min/quant), encode the new block into free space (tail of the file or a
per-shard block heap with a free list), fsync, then flip the block's
`block_offsets` entry — one aligned 8-byte store, release/acquire — and
fsync again. Old block bytes stay allocated until the next snapshot or
compaction, so epoch-e readers stay valid and B7's rollback holds without an
undo log. Slot-level in-place writes remain only for forward-offset
repoints. Format v3 adds a per-block CRC in the block header (the integrity
whole-file checksums lose under any in-place edit).

**Precedents [snippet-level from the cloud session; local session to
re-read]:** CUBIT, VLDB 2024 (fixed-raw-size bitmap segments, each
independently compressed, re-encoded on update); SPFresh SOSP 2023 (CoW
blocks held until the next snapshot — already [read] in `04` §A #13); LMDB
(never overwrite a reachable page; sync data before meta — [read] in `04`);
Parquet/Puffin per-page/per-file checksums.

**Caveat that decides the write unit.** Per `spike/archive/inplace_update/shard.py`,
summaries are stored per LIST as EF-coded arrays spanning that list's blocks
(summaries_ids bitfield, u8 values, per-block min/quant, EF offsets). If one
block's summary cannot be re-encoded without re-encoding the list's summary
section, the write unit is the LIST: rewrite packed postings + block offsets
+ summaries for that list into free space and flip the list's start offset.
Sizes (*est.* from the mmap audit): ≤ 5,250 postings × 8 B ≈ 42 KB of
postings plus summaries ≈ 100 KB per list; 28,702 lists; a quarter touching
most lists rewrites on the order of `posting_lists.bin` (1.16 GB of the
shard's ~7.7 GB) while the 6.6 GB forward index stays in place. That is
"rebuild the posting side only, keep the clustering and the forward index",
which is (a) far cheaper than A3 and (b) free of the re-clustering drift
that M9's parity FAIL is *inferred* to come from (forward round-trips
exactly; posting side differs).

**Asked of the local session (cheap, no Stage-1 code):**
1. From `ShardView` on shard 0: distribution of bytes per block and per list
   (postings, block offsets, summary section) and whether a block's summary
   entries are separable from the list's EF structure. This picks block vs
   list as the write unit.
2. Pre-register, before any Stage-1 number, a supplementary arm **A2b**
   (CoW block/list re-encode, exact summary rebuild, offset flip) beside A2,
   scored on the same B1–B7 rows; B7's power-loss arm applies to it
   unchanged. A2b has no inflation byte, so S0-3 does not gate it; its
   quality question is B6 on the CoW-rebuilt lists.
3. Record P1's supplementary demand/supply beside S0-1's frozen definition
   and re-score M7 with vectors (P1 item 3).

Nothing above changes a served default, a frozen threshold, or the GO rule.
