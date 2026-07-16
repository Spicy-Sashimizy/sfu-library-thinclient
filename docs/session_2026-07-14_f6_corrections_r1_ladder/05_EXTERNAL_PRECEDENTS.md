# 05 · External precedents — documented versions of tonight's phenomena

Web research 2026-07-14, on the operator's question: *"search online to see
if there any documented version of this interaction that we are seeing
tonight."* Verdict: every phenomenon has precedent; two are near-verbatim.

## The VMA-split bug class (defects #4 and #6) — a 2017 kernel patch

- **"mm, madvise: fail with ENOMEM when splitting vma will hit
  max_map_count"** — LKML discussion:
  https://lore.kernel.org/lkml/alpine.DEB.2.10.1701241431530.42507@chino.kir.corp.google.com/T/
  merged as def5efe0:
  https://gitlab.freedesktop.org/panfrost/linux/commit/def5efe0376501ef7bd6b53ed061512c142e59aa
  Exactly our failure: sub-range madvise splits VMAs; at max_map_count the
  call returns ENOMEM, indistinguishable to naive callers from memory
  exhaustion — hence our `MemoryError` on a 21 MB read with 55 GB free.
  Thread-spawn failure at saturation ("can't start new thread") follows the
  same path (thread stacks need mmap → mmap needs a VMA slot).
- **The 262,144 is search-engine lore:** Elasticsearch/OpenSearch require
  raising vm.max_map_count from 65,530 to exactly 262,144 — the value found
  in this container (inherited from the project's OpenSearch era):
  https://opensearch.org/blog/error-logs/error-log-max-virtual-memory-areas-vm-max_map_count-is-too-low/
  https://github.com/elastic/elasticsearch/issues/92618
  Irony recorded: headroom pre-tuned for one search engine's map hunger was
  saturated by our own hot-set machinery.

## Profile-guided prefault (F6) — established practice + fresh research

- **Neo4j "warm the cache"** (long-standing operational practice):
  https://neo4j.com/developer/kb/warm-the-cache-to-improve-performance-from-cold-start/
- **LKML on madvise/fadvise(WILLNEED) at application startup** (same
  trade-off reasoning we used):
  https://linux-kernel.vger.kernel.narkive.com/Yb8pG2kz/downsides-to-madvise-fadvise-willneed-for-application-startup
- **Aquifer (2026, MicroVM snapshot restore)** — the closest analogue:
  pre-installs "the entire hot set recorded during offline profiling,"
  deliberately skipping cold pages: https://arxiv.org/pdf/2606.24079
  Near-verbatim our sidecar+prefault design, different domain.

## Manual reclaim without pressure (F5) — deployed at hyperscale

- **Meta TMO / senpai (ASPLOS 2022)** — added the cgroup-v2 `memory.reclaim`
  file so a userspace agent can have the kernel reclaim a computed amount
  "without applying any limit"/pressure:
  https://www.cs.cmu.edu/~dskarlat/publications/tmo_asplos22.pdf
  https://engineering.fb.com/2022/06/20/data-infrastructure/transparent-memory-offloading-more-memory-at-a-fraction-of-the-cost-and-power/
- **DAMON_RECLAIM** — in-kernel proactive reclamation of regions unaccessed
  for N time: https://docs.kernel.org/admin-guide/mm/damon/reclaim.html
- Distinction recorded: TMO/senpai/DAMON let the kernel pick victims by
  observed coldness; our F5 hands it the victim list from the hot-set map
  (map-guided variant of a documented pattern).

## The convergence artifact — components documented, composite apparently not

See `04_CONVERGENCE_ARTIFACT.md` §4 for the full anchoring:
Belady/stack-property (https://en.wikipedia.org/wiki/B%C3%A9l%C3%A1dy%27s_anomaly),
LRU startup/convergence-time theory (WiOpt 2022,
https://ieeexplore.ieee.org/document/9930556/), caching-analysis survey with
mixing times (https://arxiv.org/pdf/2308.02875), kernel reclaim internals
(https://kernel-internals.org/mm/reclaim/), MGLRU rationale
(https://lwn.net/Articles/851184/), sequential flooding
(https://tinkeringwithdata.wordpress.com/2019/04/14/understanding-sequential-flooding/,
https://cs186berkeley.net/notes/note5/).

## R3 addendum — post-measurement prior-art sweep (2026-07-16)

Web cross-reference done after the R3 kernel-ledger results landed, to
pressure-test the "composite apparently not documented" claim above. Verdict:
the claim SURVIVES but must be narrowed in one place.

**Newly found — and it WEAKENS one novelty claim.** *When is the Cache Warm?
Manufacturing a Rule of Thumb* (Zhang, Yang, Blasiak, McCall, Vigfusson,
HotCloud '20, https://www.usenix.org/conference/hotcloud20/presentation/zhang-lei)
defines warmup-time(s, ε) explicitly as a function of cache size s, fits
rule-of-thumb formulas on CDN/memcached traces, and shows caches warm up
faster than they fill. Size-scaled warmup is therefore EMPIRICALLY mapped,
not just theory (it joins the WiOpt-2022/Che-Fagin line above). Our
fixed-window inversion is a direct COROLLARY of their curves (larger s ⇒
longer warmup ⇒ at fixed t a smaller cache can be ahead) — but they do not
state, measure, or name the inversion; their metric is hit ratio in
distributed key-value/CDN caches, not OS page-cache query latency. Related:
Bonfire (FAST '13,
https://www.usenix.org/system/files/conference/fast13/fast13-final118_0.pdf)
documents that larger storage caches take proportionally long to warm.

**Confirmed still-unmapped after searching (the R3-specific pieces):**

1. **The inversion as an observed, quantified phenomenon** — no source found
   reporting a smaller RAM cap beating a larger one on the same workload at
   a fixed wall-clock/pass window in latency terms (our 12 GB 20 ms vs
   16 GB 129 ms at pass 3, thrice-replicated).
2. **The per-page × per-query attribution join** — eBPF request tracing
   exists for DBMSs (Domaschka et al., ICPE '23 companion,
   https://dl.acm.org/doi/10.1145/3578245.3584313), per-request I/O layer
   slicing exists (ReLayTracer, https://arxiv.org/pdf/1906.07124), page-fault
   tracing per process is a practitioner staple
   (https://taras.glek.net/posts/ebpf-mmap-page-fault-tracing/), and
   filemap-tracepoint/cachestat observability is well documented
   (https://biriukov.dev/docs/page-cache/9-advanced-page-cache-observability-and-troubleshooting-tools/,
   LWN on cachestat(2): https://lwn.net/Articles/917096/). But no found work
   JOINS a kernel eviction/refault ledger to per-query page/extent touch
   sets to attribute a warmup transient — the thing R3 built, and the join
   that refuted our own expectation #1.
3. **Per-event field observation of the activation decision** — refault
   distance/activation is thoroughly documented as kernel DESIGN
   (https://lwn.net/Articles/495423/, mm/workingset.c), and eBPF page-cache
   *policy* work exists (cache_ext,
   https://www.asafcidon.com/uploads/5/9/7/0/59701649/cache_ext.pdf), but no
   found study instruments workingset_refault per-event in the field and
   validates against the cgroup counters (our ×512 check, 1.003–1.018).

Consequence for the writeup: cite HotCloud '20 + Bonfire wherever the
04-doc/§7 text implies size-scaled warmup itself is novel — it is not; the
novelty is the latency-visible inversion at the OS page cache, its per-page
attribution, and the refutation of per-query fault concentration.
