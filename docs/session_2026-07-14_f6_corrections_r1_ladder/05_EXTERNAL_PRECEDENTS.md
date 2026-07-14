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
