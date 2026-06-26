# Qdrant vs Lucene/OpenSearch — direct RAM comparison (sparse/SPLADE leg)

**Date:** 2026-06-25 · Qdrant = live probe of `splade_150m`; OpenSearch heap =
live probe of the 172.20.0.1:9200 cluster; 150M-corpus OpenSearch RAM behaviour
from the recorded baseline + docs (corpus not currently loaded — see FINDINGS §0).

---

## The one idea that explains everything

Both engines mmap their sparse posting lists (page cache, reclaimable). The
**difference is the non-reclaimable floor**:

- **Lucene/OpenSearch:** a **bounded JVM heap** (fixed `-Xmx2g`) + page cache. The
  heap does **not** grow with corpus size; postings stay on disk and the OS
  reclaims page cache under pressure. **No per-document resident overhead.**
- **Qdrant `on_disk` sparse:** page cache **plus a structural anonymous-RAM floor
  that scales ~linearly with point count** (~43 B/point). That anon RAM is **not
  reclaimable** — the OS can't page it out — so it sets a hard floor that rises
  with corpus size.

At 150M that floor is **6.55 GB** for Qdrant vs a flat **2 GB heap cap** for
Lucene. That single asymmetry is why Qdrant goes RAM-bound at 150M on a small host
and Lucene did not.

---

## Passive RAM (at rest, idle / freshly warmed)

| | Qdrant `on_disk` sparse | Lucene / OpenSearch `rank_features` |
|---|---|---|
| Non-reclaimable floor | **RssAnon 6.55 GB @ 150M** (~43 B/point); **1.44 GB @ 30M** | **JVM heap, bounded `-Xmx2g`** — live: 0.98 GB used / 2.0 GB max. Does NOT scale with corpus |
| mmap page cache (reclaimable) | RssFile ~1.5–1.8 GB at rest | off-heap, reclaimable; sparse postings mmap'd via `MMapDirectory` |
| Total RSS at rest @150M | **~8 GB** (measured live) | ~2 GB heap + reclaimable cache |
| Scaling law | **floor grows with point count** | **floor flat**; only page cache varies |

Sources: `/proc/112/status` 2026-06-25 (Qdrant); `_nodes/stats` 2026-06-25 +
`THIN_CLIENT_SWAP.md` 322–330, `DO_SIZING.md` (OpenSearch).

## Active RAM (under query load)

| | Qdrant `on_disk` sparse @150M | Qdrant @30M | Lucene/OpenSearch |
|---|---|---|---|
| RSS under load | climbs to **~17 GB** (page cache warming the 205 GB index) | ~5.3 GB warm | heap stays ≤ `-Xmx`; page cache uses spare RAM, reclaimable |
| p50 / p95 latency | **545–861 ms / 3.4–4.5 s** (RAM-bound on 24 GB host) | **~66 ms / ~86 ms** (fits) | bounded-heap; no whole-index residency requirement |
| OOM behaviour | kernel OOM-killer SIGKILL when anon + cache + swap exhaust (mitigated by serve-only supervisor `autorestart`) | none | heap-bounded; sparse index size does not force OOM |

Sources: `measure_150m_postfix.log`, `measure_par30_warm.log`,
`THIN_CLIENT_SWAP.md` 472–511.

---

## What this means in practice

1. **At 30M (demo tier) the two are comparable in cost** — Qdrant's 1.44 GB floor
   is trivial and latency is great (~66 ms). No RAM reason to prefer Lucene here,
   and Qdrant avoids the JVM.
2. **At 150M the asymmetry bites.** Qdrant needs its 6.55 GB anon floor *resident*
   **plus** enough page cache to make the 205 GB index non-disk-bound — practically
   a **64–128 GB host** (`DO_SIZING.md`). Lucene serves the same sparse data under
   a 2 GB heap because it never has to hold per-point state resident; its latency
   degrades gracefully with less page cache rather than OOMing.
3. **The fix for Qdrant is host RAM (or fewer points / sharding), not config** —
   the anon floor is structural. The fix that would make Qdrant behave like Lucene
   on this axis (per-point state paged to disk) does not exist in Qdrant today.

> **Caveat — this compares the RAM axis only.** On quality, this stack (tantivy +
> Qdrant) measured **+0.111 NDCG@10 over OpenSearch** at 150M (wins 29/34). So
> Lucene's better sparse-RAM scaling is a real advantage **on that one axis**, paid
> for with lower measured ranking quality and the JVM floor. See `FINDINGS.md` §4.

---

## Qdrant config dead-end — confirmed, not a knob we missed (2026-06-26)

We checked whether **any** Qdrant configuration closes this gap. It does not, and
this is acknowledged by Qdrant's own maintainers — it is structural, not a setting
we overlooked.

**The two things we'd need, and why no config provides them:**

1. **A memory ceiling that degrades gracefully (Lucene's `-Xmx`).** Does not exist.
   - No native config caps Qdrant's RAM ([qdrant-client Discussion #693](https://github.com/qdrant/qdrant-client/discussions/693)).
   - A Docker/K8s `--memory` limit **"won't prevent OOM, it just makes it happen
     earlier"** ([Discussion #168](https://github.com/orgs/qdrant/discussions/168)).
   - **"Qdrant doesn't currently have built-in graceful degradation; it will hit
     OOM when limits are reached."** There is no slow-down-instead-of-die mode.

2. **A way to drop the per-point pinned anon floor.** Does not exist.
   - `on_disk: true`, `memmap_threshold`, `hnsw_config.on_disk`, quantization →
     all reduce **raw vector RAM**, none touch the per-point bookkeeping floor.
   - **"Currently no way to keep vectors ONLY on disk"** — Qdrant always pulls a
     resident working set up ([Issue #4378](https://github.com/qdrant/qdrant/issues/4378)).

**Conclusion:** every Qdrant knob only decides *where data lives* (RAM vs disk),
never *how much RAM it may use* or *whether it survives running out*. The 6.55 GB
floor (§ above) and the OOM-on-overflow behaviour are therefore **uncloseable by
configuration**. This confirms the line above ("the fix is host RAM, not config")
with external sources — it is the structural reason the assessment lands on
mmap-BMP (immutable → ~0 per-point floor) or a bounded-heap Lucene path, not on
further Qdrant tuning.

Sources (2026-06-26): [Discussion #168](https://github.com/orgs/qdrant/discussions/168),
[Discussion #693](https://github.com/qdrant/qdrant-client/discussions/693),
[Issue #4378](https://github.com/qdrant/qdrant/issues/4378),
[memory-consumption](https://qdrant.tech/articles/memory-consumption/),
[capacity-planning](https://qdrant.tech/documentation/guides/capacity-planning/).

---

## Hard requirements for the sparse-vector engine (simplified)

The dead-end above plus the floor analysis reduce to a short, non-negotiable list.
The engine we adopt or build **must** satisfy all of these:

1. **No per-point pinned RAM.** Resident (non-reclaimable) RAM must NOT grow with
   point count — i.e. an *immutable* index with no per-point bookkeeping. This is
   the core cure for the 6.55 GB floor.
2. **Postings served from mmap / page cache.** The bulk of the index must be
   reclaimable page cache, so the OS can reclaim under pressure.
3. **Degrade, don't die.** When RAM is tight it must get *slower* (read from disk),
   never OOM-kill. A flat, bounded resident footprint is what delivers this.
4. **No JVM.** Embeddable/edge/thin-client deployment — the whole point of this
   container. (Rules the OpenSearch/Lucene path back to "RAM-axis reference only".)
5. **Keeps the measured quality recipe.** Must not regress the +0.111 NDCG@10 win
   — learned-sparse (SPLADE) scoring, not plain BM25.
6. **Immutable, distributable static index.** Build once (monthly rebuild), ship a
   read-only artifact; no live-upsert machinery (that machinery IS the floor).
7. **Sliceable per persona.** Load only the persona slice(s) needed, so resident
   cost tracks the loaded slice, not the full 150M.

> Lucene/OpenSearch meets 1–3 and 6–7 but **fails 4 (JVM)** and costs quality (5).
> Qdrant meets 4–5 but **fails 1–3** (the floor + OOM). The empty intersection is
> exactly why mmap-BMP (immutable sparse, no-JVM) is the surgical build — see
> `../sparse_engine_project/WHY_NO_FOSS.md`.
</content>
