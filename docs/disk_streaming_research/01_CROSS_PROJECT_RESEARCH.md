# 01 · Cross-project disk-streaming research — colibrì, sluice, KTransformers, VibeBlade

**Status:** DEFERRED 2026-09-25 (F1-F6 hooks built and env-gated OFF; no promotion decision taken)

**Created 2026-07-13. Status: RESEARCH / LITERATURE — not on served path.** This
doc records findings from studying external projects that stream
parameters/experts from disk, mapped onto our own mmap-based SEISMIC sparse-index
streaming code. It answers: *what techniques from those projects could transfer
to our disk-streaming serving path, and which have we already tried-and-refuted
so we don't burn a re-run?*

This is **literature + code-mapping research**, not a measurement. Per the
new-module efficacy rule, every lever below is labeled **IMPLEMENTED / REFUTED /
UNMEASURED**; the testable ones are framed as candidate hypotheses at the end.

> **VERIFIED + CORRECTED 2026-07-13** — every external claim below was checked
> against the upstream READMEs and colibrì's `c/glm.c` source; see
> `02_METHOD_VERIFICATION_AND_INTEGRATION.md` §1 for the claim-by-claim table.
> Two corrections recorded there (§2): candidate #2's "hottest **shards**"
> granularity is structurally wrong (every federated query touches all 8
> shards — skew can only exist at posting-block/forward-page level), and
> candidate #1 needs **no Rust** (pyo3 `search_visited` already returns the
> visited set — the telemetry ran same-day as probe **Q12**, pre-registered in
> `seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md` §Q12).

**The framing.** colibrì (*JustVugg/colibri*) streams 744B-param MoE expert
weights from disk to run GLM-5.2 in ~25 GB RAM. Our repository streams a SEISMIC
sparse index from disk to serve 150M docs on a 32 GB host. The structure is the
same shape — *a small resident "dense" tier + a bulk "streamed" tier selected
on demand by a per-query routing step (the router, resp. the query_cut posting
lists)*. The analogy is genuine, *not* forced; whether each colibrì lever
transfers depends entirely on whether our query traffic has the access locality
colibrì's expert routing has — and that is an open, measurable question, not an
assumption.

## Projects surveyed

| Project | What it does | Relevance | Source |
|---|---|---|---|
| **colibrì** | Pure-C engine; runs 744B MoE (GLM-5.2) on ~25 GB RAM by keeping dense weights resident + streaming router-selected experts from disk on demand | **Primary** — nearest analogue; the multi-cache-tier software design is the template | [github.com/JustVugg/colibri](https://github.com/JustVugg/colibri) |
| **sluice** | vLLM plugin (no fork); keeps MoE experts in host RAM, streams router-selected experts into a small per-layer GPU slot cache | Confirms the *reactive* streaming baseline + pointer/content-split for graph capture; its negative-result discipline (staged prefetch slower, lazy-step slower) corroborates ours | [github.com/Etelis/sluice](https://github.com/Etelis/sluice) |
| **KTransformers** | CPU/GPU heterogeneous MoE inference; hot-on-GPU / cold-on-CPU-or-disk expert placement + 3-tier prefix cache reuse | The "hot/cold tiered expert placement" lineage (SOSP 2025) | [github.com/kvcache-ai/ktransformers](https://github.com/kvcache-ai/ktransformers) |
| **VibeBlade** | LLM inference stack; 3-tier VRAM/RAM/SSD adaptive eviction for MoE experts | Confirms VRAM/RAM/SSD adaptive eviction as a known pattern | [github.com/kevin046/VibeBlade](https://github.com/kevin046/VibeBlade) |
| llama.cpp | Supports MoE models (Mixtral, DeepSeek, PhiMoE, Arctic, OLMoE); README silent on disk expert streaming | Negative data point — even the canonical CPU inference project doesn't ship per-expert disk streaming as a first-class feature | [github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp) |

## colibrì's transferable mechanisms

colibrì partitions GLM-5.2 weights into a **resident dense tier** (~9.9 GB:
attention, shared experts, embeddings) and a **streamed expert tier** (~370 GB
on disk at int4), loading an expert only when the router selects it (top-8 of
256 per layer). Mechanisms, in decreasing transfer-relevance to us:

| Mechanism | colibrì implementation | Why it might transfer / not |
|---|---|---|
| **Per-layer LRU of the streamed tier** | `ESlot[]` per layer + monotonic `eclock`; linear-scan LRU eviction; auto-sized from `MemAvailable` | Our only eviction policy today is the kernel page cache, which we cannot steer. A software LRU above it is the biggest *untried* lever. |
| **`pread` (not mmap) for the streamed tier** | coalesced `pread` of contiguous expert weights; optional O_DIRECT 4K-aligned path | mmap gives us the kernel's eviction+readahead, which (per our MADV\_ findings below) we cannot tune to win. A `pread` + explicit-LRU reader would give the control the LRU/pin levers need. Biggest architectural lift; foundational. |
| **Usage-tracked hot pinning** | `eusage` (lifetime) + `eheat` (recent) counters → `pin[]` store (`usage_save` → `.coli_usage`); "the cache that learns," "literally gets faster the more you use it" | We have **no** shard/posting-list hotness telemetry. A counter + persisted hot-set would let startup prefault target the *actually-hot* set, not the constant structural floor. |
| **Router-lookahead prefetch (PILOT)** | `pilot_prefetch` runs next-layer router on the residual (71.6% recall); lock-free 1-prod/1-cons ring `pilot_q[4096]`, drops on full; dedicated I/O thread because inline fadvise blocked (~0.5ms×169k calls = +92s/48 tok) | Our `query_cut` posting lists resolve before forward-index candidate faults — a predictor could fire WILLNEED on likely-scored candidate ranges. **But see refutation below.** |
| Async load pipeline (PIPE) | `g_pipe` I/O worker pthreads; generation-tagged cursor prevents ABA | Overlap disk reads with compute. colibrì's decoupled-I/O-thread lesson survived our refutation of inline WILLNEED. |
| OS page cache as free L2 | `DONTNEED` default OFF — rely on kernel page cache | We already rely on the kernel page cache; this is the default regime. |
| Batch-union dedup | each unique expert read once per batch | Sparse analog: dedup candidate ranges across query terms (our `visited` set already does this). |

## The honest map: where our code mirrors colibrì (and what's missing)

Our repository *is* a disk-streaming system in the same shape. The mapping, with file
anchors (absolute paths for cross-dir reference):

| colibrì concept | Our equivalent | File | Status |
|---|---|---|---|
| Streamed expert weights | mmap forward index (`forward_data.bin` / `forward_components`+`values`) | `spike/seismic_upstream/src/mmap_io.rs` | IMPLEMENTED (Path C) |
| Resident dense tier | posting-list index + doc-mapping floor (~1.5 GB structural floor) | `spike/seismic_upstream/src/mmap_io.rs` (`prefault_floor`) | IMPLEMENTED (E7 Fix #4) |
| Per-layer LRU of the streamed tier | *none — kernel page cache is the sole L2* | — | **MISSING (this is the gap)** |
| `pread` for the streamed tier | *none — mmap everywhere* | — | MISSING (foundational lever) |
| `MADV_WILLNEED` readahead (startup floor) | `touch_bytes` (WILLNEED\|SEQUENTIAL + page-stride read) | `spike/seismic_upstream/src/mmap_io.rs` (`touch_bytes`) | IMPLEMENTED (Fix #4/q9, works for the floor) |
| `MADV_WILLNEED` per-query prefetch | per-range WILLNEED tested | `spike/seismic_upstream/src/mmap_io.rs` | **REFUTED** (see below) |
| `MADV_RANDOM` | `leak_mmap_advise(.., false)` everywhere; tested on f16 forward | `spike/seismic_upstream/src/mmap_io.rs` (`leak_mmap_advise`) | **REFUTED** (see below) |
| `MADV_DONTNEED` release between shards | `release_pages` (sequential mechanism B) | `spike/seismic_upstream/src/mmap_io.rs` (`release_pages`) | IMPLEMENTED |
| Router-lookahead prefetch (PILOT) | *none* | — | MISSING (research step, not a configuration flip) |
| Usage-tracking / hot pin | *none* (the hybrid flip is adaptive on latency, not usage) | `source/lib/thinclient/sharded_seismic_backend.py` (`HybridSeismicBackend`) | MISSING (telemetry half is cheap to add) |
| Per-shard sequential streaming | `SequentialSeismicBackend` (one shard resident → DONTNEED → next) | `source/lib/thinclient/sharded_seismic_backend.py` | IMPLEMENTED, **LATENCY REFUTED at 150M** (see below) |
| Host RAM ≥ resident set | `ParallelSeismicBackend` (ThreadPoolExecutor, all shards resident) | `source/lib/thinclient/sharded_seismic_backend.py` | IMPLEMENTED |
| Cold→warm adaptive flip | `HybridSeismicBackend` (state signal, seq→par flip) | `source/lib/thinclient/sharded_seismic_backend.py` (`_maybe_flip`) | IMPLEMENTED (Q7) |

**The one genuinely missing idea class:** colibrì has **four** cache tiers in
software (LRU → pin → page cache → disk) and **software-driven prediction**
(PILOT). We have **two** tiers (RAM-resident versus page-cache-as-L2) and **zero
prediction** — every cold access is a reactive fault. sluice confirms the same
for GPU expert offloading (strictly reactive there too). That gap is the single
biggest thing to learn from these projects, and it lines up exactly with the
recorded open G8/sequential-latency risk.

## What we already tried-and-refuted (do NOT re-litigate)

Several colibrì-style levers have **already been measured and refuted here**.
Recording these so this reading doesn't re-spend the work:

| Lever | colibrì analog | Our verdict | Date / anchor |
|---|---|---|---|
| Per-query `MADV_WILLNEED` prefetch | `expert_prefetch` (WILLNEED readahead) | **REFUTED** — Fix #3 query-time WILLNEED had **zero effect + syscall overhead**; only the once-at-load *floor* prefault ships and works. The PILOT idea's survive-our-refutation lesson is the *I/O-thread decoupling* (colibrì moved inline fadvise to a worker because it blocked). | 2026-07-03, E7 reclear; `seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` |
| `MADV_RANDOM` to suppress readahead overshoot | colibrì relies on default advice | **REFUTED** — Arm C/D: MADV_RANDOM **quadruples f16's absolute faults** (117k→437k); the gate-c ratio "win" was an artifact of RANDOM hurting f16 *worse* than dv. Disabled everywhere (`random=false`). | 2026-07-03, Arm C/D; `mmap_io.rs` `leak_mmap_advise` doc |
| `MADV_DONTNEED` release between shards (mechanism B) | (colibrì's `g_drop`) | **SHIPPED** — hard 1-shard resident guarantee on the sequential path. Works. | 2026-06-30, sequential serving; `mmap_io.rs:release_pages` |
| Sequential per-shard streaming (the core colibrì pattern) | resident/streamed split + per-unit LRU | **SHIPPED, LATENCY REFUTED at 150M** — warm≈cold 15.8 s p50 because the 62 GB mmap index > page cache on the 32 GB host → re-fault every pass. The "sequential adds a small traversal term" thesis died at 150M here. Remediation = Tier-2 #5 (no-swap host / pre-fault+mlock), NOT more federation tricks. | 2026-07-01, sequential serving |
| Gate-c cold-majflt ratio | the fault-count advantage colibrì's readahead targets | **OPEN** — 0.572 > 0.55 bar; structural floor, "no kernel change fixes c." | 2026-07-03, E7 reclear |

**Net:** the colibrì mirrors left on the table are precisely the ones we have
**not** tried — the **software LRU/pin tier** and the **router-lookahead
prefetch** (and the `pread`-not-mmap foundation that makes the LRU fully
expressive). sluice's negative results (staged prefetch −6–8%, lazy-step
−12–17%, both bit-identical-but-slower) corroborate that naive prefetch under-
performs; the surviving lesson everywhere is *decouple the I/O hint off the hot
path*.

## Candidate experiments (ranked, grounded, parity-safe)

All would be spike-harness experiments in `scripts/seismic_testbed/`, behind environment
gates, parity-guarded by the T1 bit-identical invariant (none touch the shared
`_merge_topk`, so all are results-preserving). These are **candidates only** —
not yet pre-registered into `seismic_150m_testbed/11_EXPERIMENT_BACKLOG.md`. If
adopted, register them there with bars before running.

1. **Usage-tracking + hot-set-skew measurement (telemetry only).** The cheapest,
   highest-value next step: a small env-gated counter in the Rust
   `search_raw_visited` path that writes a shard/posting-list heat map to
   `data/eval_results/`, mirroring colibrì's `eusage`/`.coli_usage`. *No serving
   change.* If access is skewed, levers #2/#3 are worth building. If uniform,
   colibrì's whole premise (sparse activation → a small hot set exists) does
   **not** transfer to this workload → stop investing in streaming-tier tricks,
   stay on Tier-2 #5. **colibrì itself concedes this**: on small-RAM machines
   "the RAM cap (not disk speed) is the binding constraint" — the same wall we
   hit.

2. **In-software per-shard LRU + hot-pin (colibrì `ecache`/`pin` analog).** Keep a
   small resident cache of the hottest shards (or, finer, hottest posting-list
   blocks) in RAM and `mlock` them; stream the rest sequentially. Hypothesis: on
   a 32 GB host with skewed shard traffic, pinned-hot + sequential-rest beats
   both all-resident (OOMs) and all-sequential (re-faults every pass). Attacks
   the G8/sequential-latency open item from a *new* angle (software tiering),
   orthogonal to the refuted kernel-advice levers.

3. **Async router-lookahead prefetch (colibrì PILOT analog) — only if #1 shows
   locality.** A query's `query_cut` posting lists resolve *before* the
   forward-index candidate faults begin. A predictor could fire `MADV_WILLNEED`
   on the forward ranges of the most-likely-scored candidates before the
   traversal touches them, on a *dedicated I/O thread + lock-free ring*
   (colibrì's PILOT discipline), batched, drop-on-full. **Hard precondition:**
   #1 must show locality first, and the prefetch MUST be (a) off the hot path
   on a worker, (b) batched, (c) drop-on-full — to survive our refutation of
   the inline per-range WILLNEED (which the kernel ignored + added syscall
   overhead). The predictor needs candidate starts *predicted* (for example, from
   posting-list block-skips before evaluation); `search_raw_visited` currently
   returns `visited` only *after* the fact. Real research step, not a configuration
   flip.

4. **`pread`-backed forward reader with explicit LRU (lower priority,
   foundational).** colibrì deliberately avoids mmap for the streamed tier and
   uses `pread` + a per-layer LRU it controls. mmap gives us the kernel's
   eviction/readahead, which (per the MADV\_ refutations) we can't tune to win.
   A `pread`-backed forward reader with an ESlot-style LRU would make levers
   #2/#3 fully expressive. Biggest architectural lift (lives in `mmap_io.rs`);
   do #1/#2 on the existing mmap + a Python-level LRU first, escalate to `pread`
   only if the LRU levers show promise but hit the kernel-policy ceiling.

5. **Keep the negative-result discipline (no transfer needed — we already do
   this).** Both colibrì and sluice record what they tried and refuted. Our
   memory file + the `seismic_150m_testbed/` findings docs already form that
   ledger. The practice to keep: record the *reason* a lever failed at this
   scale/architecture, because colibrì's PILOT works *only because* its traffic
   has 71.6%-predictable router locality — the open question for us is whether
   our query traffic has the same locality, measurable before any code.

## What this doc is NOT

- **Not a measurement.** Every external number (colibrì 71.6% PILOT recall,
  0.05 tok/s, ~11 GB/token; sluice 5.4×; etc.) is from the upstream projects'
  own docs, labeled literature, not our runs. Candidate experiments stay
  **UNMEASURED** until run.
- **Not on the served path.** This is research relevant to the G8-latency open
  risk; the served SEISMIC leg is unchanged. Standing constraint
  (`seismic_150m_testbed/README.md`): persona scale is GREEN on Qdrant; the
  150M-single-collection problem is what this research informs.
- **Not a commitment.** Candidates 2–4 are conditional on #1's locality finding.
  If #1 shows uniform access, stop here and keep remediation on the recorded
  Tier-2 #5 path (no-swap host / mlock), per the sequential-serving refutation.
