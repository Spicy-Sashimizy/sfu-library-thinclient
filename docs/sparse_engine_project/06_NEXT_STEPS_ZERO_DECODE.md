# 06 · Next steps — the zero-decode tiebreaker (format-wall vs real-wall)

**Status:** ✅ **RESOLVED — FORMAT-WALL (2026-06-26)** — and the §4 follow-ons it
kicked to are now **measured and killed (2026-06-26, see `07_INTEGRATION_PLAN.md`).**
The experiment ran and **flipped the P2 kill.** Warm p50 dropped from 696 ms (R3-v1
decode-per-query) to **25.63 ms** (R3-v2 zero-decode) on the same 4-shard med_bio
subset — below qdrant's 66 ms bar, G1 byte-identical (50/50 @1M + 40/40 @persona),
anon 1.976 GB, cold/warm 1.49. **The wall was R3-v1's compact format (decode per
query), not the Block-Max algorithm.** The format question is settled (FORMAT-WALL).
**But** the *provisional* re-open required the §4 follow-ons (inverted-side mmap,
pruning sub-linearity, parallel latency) — and **both decisive ones now FAIL at the
150M target**: pruning is **linear in corpus** (worst-query `blocks_scored/num_blocks`
≈0.95 stable across a 2.15× corpus jump), and the forward-only RAM cure projects to
**~50 GB at 150M (~7.6× the Qdrant floor it replaces).** → Gate-zero re-decided **STOP**;
thin client ships on Qdrant, `immsparse` kept as a research result, SEISMIC is the
pivot if 150M-single-collection ever becomes hard. Result files: `p2_zerodecode_*`,
`p3b_pruning_persona.json`, `p3a_inverted_floor.json`. Full record:
`03_GO_NO_GO_GATES.md` decision log + `07_INTEGRATION_PLAN.md` §8. The PROPOSED
scoping below is preserved for provenance.

---

**Original status: PROPOSED (2026-06-26).** The project is KILLED at P2 (`README.md`,
`03_GO_NO_GO_GATES.md`). This doc scopes the **one cheap experiment** that would
either resurrect it or close it for good — and corrects a framing error in the
kill notes.

---

## 0. Why this doc exists (the framing correction)

The P2 kill notes say the warm-latency wall (G3a: 696 ms vs qdrant 66 ms) is
"decode-bound … a fix would need SIMD/batch block decode or a re-layout — too
invasive for the spike." That is **half right and half misleading**:

- **Right:** the cost is CPU **decode**, not page faults (G3b proved cold≈warm, 1.04×).
- **Misleading:** it implies the wall is intrinsic to *mmap-BMP*. It is not. The
  measured latency chain shows the wall is a **property of R3's compact on-disk
  format**, not of BMP, mmap, or the Block-Max algorithm:

  | Build | Forward index on access | warm p50 | anon |
  |---|---|---|---|
  | Stock BMP (load-into-RAM) | decoded, **resident** | **4.67 ms** (1M) | 1.98 GB ❌ |
  | R3 flat (mmap + `get_block` **decode per query**) | compact, **re-decoded** | ~67 ms (1M, 14×) | 0.535 GB ✅ |
  | R3 flat @ persona | same | 696 ms (~150×) | ~2 GB/4 shards |

  Stock BMP is *fast* (4.7 ms, matching the [BMP paper](https://arxiv.org/abs/2405.01117)).
  R3 traded the resident decoded forward array (= the anon floor it cured) for a
  **per-query decode** (`FlatIndex::get_block` "decodes one block transiently",
  `spike/archive/mmap_bmp/FORK_BMP.md:75`). The 10–150× is that decode — an artifact of
  choosing a *compact* layout that must be decoded, **not tested against a
  zero-decode layout**.

So the honest open question the spike never answered:

> **Is the wall the *format* (compact → must decode per query) or the *algorithm*
> (Block-Max iteration / pruning touches too much work regardless)?**

This experiment answers exactly that, cheaply. The kill stays correct *unless*
this single test flips it.

---

## 1. Gate-zero: is bespoke even worth it? (do this BEFORE any code)

Per `WHY_NO_FOSS.md` (Risk R7), a custom engine is only worth owning if
**no-JVM + embeddable-as-a-library + your exact measured quality recipe** is worth
more than maintaining bespoke code. The fallbacks (per-persona Qdrant locally;
OpenSearch+SEISMIC or Infinity at 150M) are real and mature.

**Decision (record before starting):** **YES — bespoke is strategically worth
it; run §2.** (2026-06-26.) The thin client itself does not need a bespoke
engine — Qdrant at persona scale is already GREEN (66 ms, 30M-fits tier). The
ownership case is strictly the *full-150M-single-collection* floor disease,
where no mature no-JVM engine covers the lexical+sparse+immutable intersection
(`WHY_NO_FOSS.md`, Risk R7). That justifies one ~1–2 day tiebreaker run for a
    *reason*, not curiosity.
- If "fallbacks are fine" → **stop here.** Keep this doc as the closed lesson.
  For the *thin client* specifically, Qdrant at persona scale (66 ms, GREEN 30M
  zone) is already the correct answer — no engine needed. The floor disease is
  strictly a *full-150M-single-collection* problem (`DECISION_TRAIL.md` step 10).
- If "no-JVM + embeddable + exact quality is strategically worth bespoke code"
  → run §2.

This gate exists so the experiment is run for a *reason*, not curiosity.

---

## 2. The experiment — zero-decode forward region

### Hypothesis
The warm regression is `get_block` decoding the compact forward block on every
`block_score` call. If the forward region is stored in a **directly-addressable
(zero-decode) layout** — a block obtained by a pointer-cast over an mmap'd
sub-slice, no decode, no allocation — then warm p50 approaches stock (single- to
low-tens of ms) **while anon stays ~0**, because the bytes are page-cache-resident
and read in place.

### The change (on the existing R3 fork)
Base: `spike/archive/mmap_bmp/R3_fork.patch` (applies clean to a fresh upstream
`pisa-engine/BMP` clone). Build into a throwaway venv, **never** project `.venv`
(`FORK_BMP.md` isolation rules).

1. **Builder (`src/index/flat.rs`, `write_flat`):** serialize each block's forward
   records in their *final* in-memory representation — a `#[repr(C)]` / POD record
   array (e.g. `bytemuck`-castable `(u16 term, u8, u8)` tuples) behind the existing
   per-block offset table. Uncompressed on purpose.
2. **Reader (`FlatIndex::get_block`):** return a `&[Record]` via
   `bytemuck::cast_slice(&mmap[start..end])` — **zero decode, zero alloc.** This is
   the whole point: the search path reads the block straight from page cache.
3. **Search path (`src/flat_search.rs`):** unchanged. `block_score` already
   consumes a block slice → keep it byte-for-byte so **G1 stays identical by
   construction** (this is the R3 invariant; preserve it).
4. **Instrument:** add a per-query counter for **#blocks actually scored** (the
   confound control — see §3).

Cost: disk grows (the forward region is no longer compact). **You have budget** —
G3c measured flat at **0.79× bincode** today, i.e. you are currently *smaller* than
stock; spending that headroom on a directly-readable layout is the trade.

### Run (reuse the P2 harness unchanged)
```bash
BMP_LOAD=flat MMAP_BMP_SITE=<fork-venv>/lib/python3.11/site-packages \
  <fork-venv>/bin/python3 spike/archive/mmap_bmp/measure_p2_cold.py \
    --flat 'spike/archive/mmap_bmp/persona_med_bio/splade_00[0-3].bmflat' \
    --baseline spike/archive/mmap_bmp/out --qdrant-p50 66 \
    --result-file data/eval_results/p2_zerodecode_med_bio_4shard.json
```
Use the **4-shard subset** (≈2.4 GB flat, ≈2 GB anon) — same as the clean P2 run —
to avoid swap contamination on the 31 GB host while live Qdrant is up. Run in a
window where dropping page cache / disturbing Qdrant is acceptable (it recovers;
P2 confirmed "all shards ready" after).

---

## 3. Decision thresholds (what flips the kill, what confirms it)

Re-baseline against the SAME 4-shard subset the P2 RED used
(`data/eval_results/p2_coldp95_med_bio_4shard.json`: warm p50 696 ms).

| Outcome | Criterion (4-shard med_bio) | Verdict |
|---|---|---|
| **FORMAT-WALL** (kill was premature) | warm p50 **≤ ~66 ms** AND G1 byte-identical AND anon ≤ ~2 GB/4 shards | The wall was the compact format. **Reconsider the build** — re-open P3 path, but only after §4 follow-ons. |
| **Partial** | warm p50 drops a lot (e.g. 696 → ~150 ms) but still **> 66 ms** | Decode was *a* cost but not the only one — pruning/iteration or PyO3 also bite. Judgment call; likely still not worth it. Record blocks-scored to attribute. |
| **REAL-WALL** (kill stands, now proven) | warm p50 still **≫ 66 ms** with zero decode | Cost is Block-Max **iteration/pruning** (or PyO3 per-call), not format. The standalone idea is **truly dead** — close the project for good. |

### Result (2026-06-26): **FORMAT-WALL — the kill was premature.**

| Metric | P2 RED baseline (R3-v1 decode/query) | Zero-decode (R3-v2) | Bar |
|---|---|---|---|
| warm p50 | **696 ms** | **25.63 ms** | ≤ 66 ms (qdrant) ✅ |
| warm p95 | 1458 ms | 57.01 ms | — |
| cold/warm p95 | 1.04 | 1.49 | ≤ 3 (G3b) ✅ |
| RssAnon / 4 shards | 1.98 GB | 1.976 GB | ≤ ~2 GB ✅ |
| G1 byte-identical | — | 50/50 (1M) + 40/40 (persona) | HARD ✅ |
| disk `.bmp`→`.bmflat` | 0.79× | 0.79× (2.9 GB→2.4 GB) | G3c ✅ |
| **#blocks-scored/query** | (not instrumented) | p50 **3481**, p95 7370, **max 7424** | confound |

**Verdict:** removing the per-query decode (`get_block` → `get_block_views` via
`bytemuck::cast_slice`; `block_score` → `flat_block_score` over the views) drops
warm p50 **~27× to 25.63 ms — below qdrant**. The wall was R3-v1's *compact
format* (decode per query), **not** the Block-Max algorithm. The P2 kill is
**superseded**; the standalone `immsparse` idea is re-opened *provisionally*.

**⚠️ Confound caveat (does not flip the verdict but bounds it):** the
#blocks-scored counter fires hard — `max 7424 ≈ (1.9M docs / 256 bsize)` = the
entire block count of the largest shard. The descending-upper-bound iteration
prunes almost nothing and scores O(corpus) blocks per query. The win is real
*because* zero-decode made scoring-all-blocks cheap; but per §3's own rule, if
blocks-scored *grows with shard size* (it will — it's ≈ docs/256), pruning is
the long-pole and zero-decode alone can't guarantee the win holds at 150M. This
makes §4's follow-ons non-optional before any re-open commits.

**§4 follow-ons a re-open still needs (unchanged by this result):**
1. **mmap the inverted side** — `documents` + `range_maxes` are still `.to_vec()`'d
   (1.976 GB/4 shards here → 8.26 GB/16 shards, the P2 scale regression). A true
   zero-anon cure must offset-index these too.
2. **Native parallel shard search** — 25.63 ms is a *serial* Python/PyO3
   harness number (per-(shard,query) in a loop); engine-level serving merges shards
   in parallel native threads (~`max(shard)` not `sum`).
3. **Re-enter the gate ladder at P3/G4** (end-to-end RRF NDCG@10 ±0.005) before
   any spin-off — the original kill criteria still apply.

Eval: `spike/archive/mmap_bmp/measure_p2_cold.py` (harness edited to record #blocks-scored;
same `posix_fadvise` weak-cold mode as the 696 ms run, since `sudo drop_caches` is
unavailable in this container — apples-to-apples). Result file:
`data/eval_results/p2_zerodecode_med_bio_4shard.json`. G1 evidence:
`data/eval_results/p2_zerodecode_G1_1m.json` + `spike/archive/mmap_bmp/compare_zerodecode_persona.py`.

**Reproducibility:** the zero-decode build is `upstream pisa-engine/BMP @ c0a17ffc`
+ `spike/archive/mmap_bmp/R3_fork.patch` (R3-v1, the G2 cure) + `spike/archive/mmap_bmp/R3v2_delta.patch`
(the zero-decode forward-region rewrite: `FlatPair`/`TermEntry` POD + `get_block_views`
`cast_slice` reader + `flat_block_score` + `blocks_scored` counter). The delta applies
clean on a fresh R3-v1 clone (verified). Build: `maturin build --release` from `python/`
with `PYO3_PYTHON=<cp311 venv>/bin/python3`; install into a throwaway venv (never project
`.venv`). Fork source lives at `/tmp/bmp-fork-work/BMP` (scratchpad, gitignored).

**Confound control (mandatory):** record **#blocks scored per query**. The G3a note
also blamed "heap-driven descending-upper-bound block iteration." If pruning scores
O(corpus) blocks (grows with shard size), that's the real wall and zero-decode won't
save it — and you'll *see* it in the counter even before the latency number. This is
what makes the experiment a clean tiebreaker rather than another single-number run.

**Budget:** ~1–2 days on the existing fork. If it runs longer than that, the
fail-fast posture says stop — the kill stands.

---

## 4. If FORMAT-WALL: what a PASS does NOT yet prove

A latency PASS on the 4-shard subset is *necessary, not sufficient*. Do not
re-open the build without also retiring these, which P2 surfaced and this
experiment does not touch:

1. **G2-at-scale (the inverted side).** R3 cured only the *forward* index; the
   *inverted* side (`documents: Vec<String>`, `range_maxes`, `kth_scores`) is
   `.to_vec()`'d in `FlatIndex::from_mmap` → **8.26 GB anon on 16 persona shards**
   (`03_GO_NO_GO_GATES.md`, 2026-06-26). A true zero-anon cure must mmap the
   inverted side too (offset-indexed `documents` + `range_maxes`). The experiment
   runs fine without this (4 shards ≈ 2 GB anon is tolerable) but the *engine*
   can't ship without it.
2. **Native parallel shard search.** P2 measured per-(shard, query) latency in a
   serial Python/PyO3 loop (`measure_p2_cold.py:94`). Real serving merges shards in
   parallel native threads (~`max(shard)` not `sum`). Confirm the engine-level
   number, not the harness number.
3. **Re-enter the gate ladder** at P3/G4 (end-to-end RRF NDCG@10 within ±0.005)
   before any spin-off — the original kill criteria still apply.

## 5. Alternative if reviving (worth a paragraph, not a detour)
If the algorithm itself is the wall (REAL-WALL), the research-grade *faster* path is
**SEISMIC**, not BMP: [SIGIR'24](https://dl.acm.org/doi/10.1145/3626772.3657906)
reports **sub-millisecond** single-threaded on MS-MARCO SPLADE (1–2 orders faster
than inverted-index methods), with a [2025 scalability paper](https://arxiv.org/html/2501.11628v1)
and [dynamic superblock pruning](https://arxiv.org/pdf/2504.17045) for massive
corpora. Its summary-vector blocks are also more mmap-amenable. Caveat: still
load-into-RAM by research design, so the *same* decode-vs-resident question would
have to be answered for it too — which is exactly why §2 is the right first test
regardless of engine.
