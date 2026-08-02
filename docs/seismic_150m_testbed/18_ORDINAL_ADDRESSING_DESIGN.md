# 18 — Ordinal addressing: the thin client's storage problem is an ADDRESSING problem

**Status:** DESIGN + MEASURED PRIMITIVES (2026-08-02). **Not implemented, not
adopted.** No production code changed.
**Parent:** `17_BM25_THROUGH_SEISMIC_SPIKE.md` §10–§13 (the consolidation spikes
that led here).
**Code:** `spike/meta_consolidation/` · **Results:** `data/eval_results/c1_*`,
`c3_*`, `c5_*`, `c6_*`

---

## 1. What a W-id is, and why it is the wrong address

Every document in this index is keyed by its **OpenAlex Work ID** — a string
like `W2803642969`. OpenAlex is the upstream bibliographic corpus the whole
150M-doc index is built from, so the W-id is the *natural* key: it is what the
upstream data ships with, what the OpenAlex API accepts for the cold-section
abstract fetch (`retriever._fetch_remote_abstracts`), what the eval fixtures
record as `seed_doi`, and what every judged result set is keyed by. Nothing
about that is wrong — as an **identity**, W-id is exactly right.

The problem is that it also became the **address**.

`builder.encode_meta_id` strips the `W` and stores the rest as an INTEGER
PRIMARY KEY (measured 2026-08-02: at 150M rows, `docs_other` — the TEXT overflow
for ids that do not round-trip — holds **zero** rows, so in practice every id is
an integer). But that integer is **sparse**: 150,413,098 documents spread over a
key range up to 7,143,276,021. Density ≈ 1 in 47.

A sparse key carries no information about *where* its row lives. Resolving one
is therefore inherently a **search**:

| structure | what it does | cost, 1000 ids @150M |
|---|---|---|
| SQLite B-tree (today) | descend a tree, ~1 random page read per id | **400.8 ms** |
| tantivy fst term dictionary | walk a finite-state transducer per id | 897.7 ms (×10 fan-out) |
| Lance BTREE scalar index | columnar B-tree | 255.1 ms |

All three *search*. That is why §10 (C1), §11 (C3's locator) and §12 (C5/Lance)
all failed or only marginally won: **they each swapped the searcher while
keeping the address.** The ~400 ms post-filter mask is not a SQLite problem, a
tantivy problem, or a Lance problem. It is a consequence of asking "where is
`W2803642969`?" a thousand times per query.

An **ordinal** — a dense integer `0..N-1` assigned at build time — is not an
identity, it is an address. Looking up an ordinal is an array index, not a
search. That is the whole idea.

## 2. Why this was not considered earlier

Not an oversight so much as a consequence of how the system was assembled, and
worth stating plainly so the same shape of mistake is recognisable next time:

1. **The three engines were adopted independently**, each with its own internal
   numbering (tantivy `DocId`, usearch integer keys, SEISMIC's own ids). The
   *only* identifier all three could agree on was the one they were all built
   from — the W-id. So W-id became the fusion key by default, and then the
   lookup key by inertia. There is no design document choosing it; it was never
   a decision.
2. **Each sidecar was added to solve its own problem.** `meta.sqlite` for
   filtering, `abstracts.sqlite` for rerank text, `dense/ids.json` to map
   usearch keys back to W-ids, `delta.sqlite` for warm-cache growth. Every one
   is locally reasonable. The shared cost — *every one of them is keyed by a
   sparse id and therefore needs a search structure* — is only visible when you
   look at all four together.
3. **The cost was never measured until 2026-08-02.** §10.3 was the first time
   anyone put a number on the post-filter mask (~0.4 ms/id, ~400 ms at 1000
   candidates). Before that it was assumed cheap, because at spike scale it *is*
   cheap — the identical code path measures 4.15 ms at 208k docs and 400 ms at
   150M, a **96× gap**. Small-corpus intuition actively concealed this.
4. **The consolidation framing pointed away from it.** The original goal was
   "4 storage technologies → 3", which invites you to ask *which engine can
   absorb which* — an engine-substitution question. The productive question was
   *what are all these stores actually doing*, and the answer is: the same
   sparse-key search, four times over.

`dense/ids.json` deserves a special note: it is already an ordinal map. usearch
returns dense integer keys and `ids.json` translates them to W-ids. The pattern
was in the codebase; it just was not generalised.

## 3. Prior art — this is standard practice, and we are the outlier

Cross-checked against the wider ecosystem (web survey 2026-08-02):

**Lucene has always done this.** Lucene assigns internal, dense, sequential
`docid`s per segment, reassigned on merge, and is explicit that they
"must always be treated as internal implementation, not exposed as part of an
application, nor stored or referenced outside of Lucene's internal APIs."
Applications that need an external key keep an explicit **docid ↔ UID map**,
precisely so filtering against an external set does not become a per-id search.
Elasticsearch/OpenSearch inherit this. So the split between *identity* (UID) and
*address* (docid) is the mainstream design; our index collapsed the two.

That also validates the durability warning in §6 below: Lucene forbids
persisting docids **because they are reassigned on merge**, which is exactly the
stale-ordinal hazard.

**The key→ordinal map has a better primitive than we used.** §13 used a sorted
`int64` array plus `np.searchsorted`. That works, but it is neither the smallest
nor the fastest option:

| approach | space @150M | lookup | notes |
|---|---|---|---|
| sorted int64 + binary search (§13, measured) | **1.20 GB** | ~956 ns/key | what we measured; simple, no dependency |
| **Elias-Fano** monotone sequence | ~**142 MB** *(est.)* | O(1) access | `2 + log2(u/n)` bits/elem; u=7.14e9, n=150M → ~7.6 bits |
| **MPHF (PtrHash)** | ~**45 MB** *(est.)* | **8–37 ns/key** | 2.4 bits/key default; 8 ns/key streaming on integer keys |
| MPHF (RecSplit / ShockHash-RS) | ~28 MB *(est.)* | slower than PtrHash | 1.44–1.58 bits/key, near the log2(e)=1.443 lower bound |

*(Space figures are arithmetic from the published bits/key, not measured here.)*

**MPHF caveat that matters for us:** a minimal perfect hash is only defined for
keys **in** the constructed set. Query a W-id that is not in the index and it
returns a plausible-looking but wrong ordinal — silently. Mitigation is cheap
and we need the structure anyway: verify by reading `ordinal → W-id` and
comparing. That array must exist regardless, because results are returned to
callers as W-ids.

So the corrected design is **MPHF + verification**, not binary search — ~27×
smaller and ~25–100× faster per key than what §13 measured, with the verification
read being one access into an array we already have to keep.

## 4. What was measured

All at production scale unless stated. Sources: `data/eval_results/`.

### 4.1 The mask and the key lookup (`c6_ordinal_20260802_0704.json`)

150M rows, mmap'd columnar arrays, vs the measured production SQLite baselines
in `c1_production_scale_20260802_0529.json`:

| k | ordinal mask | W-id→ordinal (binary search) | `meta.sqlite` |
|---|---|---|---|
| 100 | 1.012 ms | 1.767 ms | 38.68 ms |
| 500 | 0.695 ms | 0.659 ms | 203.43 ms |
| 1000 | 0.161 ms | 0.956 ms | 400.83 ms |
| 5000 | 0.565 ms | 3.870 ms | — |

Binary search landed on the exact row at every k. **The ratios (22×–2491×) are
noisy and are NOT the claim** — absolute times are sub-millisecond, so small
variance moves the multiple a lot (an independent earlier run measured the k=100
mask at 0.405 ms vs 1.012 ms here). The claim is the *band*: sub-millisecond to
low-milliseconds where SQLite costs 38–400 ms, reproduced across two runs.

### 4.2 Residency is the mechanism (`c6_ordinal_*`)

| artifact | size |
|---|---|
| filter columns (`year` i16, `type` i8, `is_oa` u8, `section` i8) × 150M | 0.75 GB |
| sorted W-id index (int64) — replaceable by ~45 MB MPHF | 1.20 GB |
| **total resident** | **~1.95 GB** (→ ~0.8 GB with MPHF) |

~1.95 GB stays in RAM permanently. **24.9 GB never can.** This is why the result
is structural and not a page-cache accident.

### 4.3 Reading the ordinal out of tantivy (`c6_tantivy_fastfield_20260802_0710.json`)

This was §13's load-bearing unmeasured assumption. Production `builder.py:132`
already declares `year` as `fast=True`, so reading a u64 fast field for a batch
of `DocAddress`es could be measured on the **real** index without a rebuild —
the same mechanism an `ordinal` fast field would use.

Real index (23,398,073 docs), real eval queries, **arms interleaved within each
repetition and their order randomised per rep** (§11's addendum ran all of one
arm then the other, which let the second reuse the first's page faults and made
its absolute numbers unusable):

| k | search | `searcher.doc()["id"]` (today) | `fast_field_values` (ordinal path) | ratio |
|---|---|---|---|---|
| 10 | 281.6 ms | 5.62 ms | 6.54 ms | 0.9× — **within noise, not claimed** |
| 50 | 54.3 ms | 34.87 ms | 16.25 ms | 2.1× |
| 100 | 47.3 ms | 23.72 ms | 4.12 ms | 5.8× |
| 500 | 47.2 ms | 75.11 ms | **6.83 ms** | **11.0×** |

**Gap closed, favourably.** Production *already* pays the stored-id read to turn
hits into W-ids; the ordinal path replaces a 75 ms step with a 6.8 ms one at
k=500, and the advantage grows with k. C6 is cheaper at the tantivy stage too,
not only at the metadata stage. At k=10 the arms are indistinguishable and no
claim is made there.

## 5. The design

Assign every document a **global ordinal** `0..N-1` at build time, unique across
all 10 sections. Then:

| role today | becomes | mechanism |
|---|---|---|
| `meta.sqlite` filter columns | mmap'd columnar arrays, ordinal-indexed | numpy fancy-index |
| `meta.sqlite` title/DOI | flat blob + ordinal-indexed `(off, len)` arrays | one pread on final top-k only |
| `meta.sqlite` id lookup | MPHF (W-id→ordinal) + `ordinal→W-id` array for verification | ~8–37 ns/key |
| `abstracts.sqlite` locator | ordinal-indexed `(block, off, len)` arrays | **solves C3's locator without tantivy or SQLite** |
| `abstracts.sqlite` blocks | flat zstd block file, unchanged codec | **C3's good half** (§11: 3.8× faster) |
| `dense/ids.json` | the ordinal **is** the usearch key | **C4, free** |
| `dense/delta.sqlite` | reserved high ordinal range | |
| tantivy `id` stored field | `ordinal` u64 **fast field** | §4.3: 2.1–11× cheaper than the stored read |

**Direction matters.** C1 failed going `id → DocId` (fst traversal). This goes
`DocId → ordinal → metadata`: columnar throughout, never touching a term
dictionary.

**Result:** SQLite leaves the container entirely — replaced not by another
database but by flat mmap'd arrays and a blob file, which are not a database
system at all. The three *engines* remain; §5/§6 of doc 17 proved they cannot
merge.

    engines           3 (tantivy · SEISMIC · usearch) — permanent
    storage databases 4 → 0

This subsumes C3's block half, all of C4, and delivers what C1 wanted (removing
the post-filter mask) by the one route C1 never tried.

## 6. Risks

Ordered by how much they should worry you.

1. **Stale ordinals fail SILENTLY.** After a rebuild, ordinals renumber. Any
   persisted ordinal — warm caches, query logs, a client that cached results —
   then points at the **wrong document**, with no error raised. This is the
   single most dangerous property of the design and the reason Lucene forbids
   persisting docids. **Mandatory mitigation:** stamp an ordinal-space version
   (uuid + build timestamp) in `manifest.json`, embed it in every derived
   artifact, and hard-refuse to load a mismatched pair. No "best effort".
2. **MPHF false positives.** A W-id not in the index hashes to a valid-looking
   ordinal. Mitigated by the `ordinal → W-id` verification read, which must be
   treated as non-optional, not an assertion that can be compiled out.
3. **Query-driven growth.** `DenseWarmCache` adds docs at query time with no
   build-time ordinal. Reserve a high ordinal range; never renumber live.
4. **Global uniqueness across sections.** Ordinals must be assigned in one pass
   over all 10 sections, not per-section.
5. **Build-time cost** of the assignment pass at 150M — unmeasured.
6. **Flexibility is the thing being traded away.** This works because the
   thin-client index is write-once and shipped static. A mutable index could not
   do it. If the product ever needs incremental in-place updates, this design
   fights that directly.

## 7. Next steps

Staged so each gate can kill the design before the expensive work starts.

**N1 — SEISMIC ordinal-nativeness (BLOCKING, cheap) — ✅ ANSWERED 2026-08-02: PASS.**

SEISMIC's document id is simply whatever string the build writes into the `"id"`
field of its jsonl (`scripts/seismic_testbed/spool_to_seismic_jsonl.py:137`,
`{"id": doc_id, "vector": sparse}`), and `SeismicBackend.search` returns it
verbatim (`seismic_backend.py:99`, `[(doc_id, float(dist)) for (_qid, dist,
doc_id) in res]`). Today `doc_id` is the W-id. Writing the **ordinal** instead
makes SEISMIC return ordinals directly.

- **No fork, no upstream change** — one line in the build script.
- Cost: SEISMIC ids are strings, so ordinals arrive as `"12345"` and need a
  `str→int` parse. That is paid on top-k results only (10–100), not per
  candidate, so it is negligible.
- Minor bonus: `"12345"` is *shorter* than `"W2803642969"`, so SEISMIC's internal
  id map shrinks slightly.

The blocking gate is cleared. Verified by code inspection, not by a build —
an actual ordinal-keyed SEISMIC build is folded into N3.

**N2 — MPHF viability (cheap, but DEFERRED — it is a RAM lever, not a latency
lever).** Build a PtrHash/RecSplit MPHF over the real 150,413,098 W-ids; measure
construction time, on-disk size, and lookup latency including the verification
read. *Bar:* ≤100 MB and ≤100 ns/key end-to-end, else keep the measured 1.2 GB
sorted array (which already works).

**Why this is NOT urgent, quantified.** At k=1000 the binary search costs
0.956 ms against a tantivy leg search of ~47 ms (§4.3). An MPHF that made key
lookup *instantaneous* would save ~1 ms of a ~50 ms query — about **2%**. Its
real benefit is memory: 1.20 GB → ~45 MB, which matters for the residency
argument in §4.2, not for latency. Benchmarking MPHF variants against each other
before N4 would repeat this investigation's recurring error — optimising a stage
that is not on the critical path (cf. §11, where C3's locator turned out to be
1.3% of abstract fetch).

**N3 — build-time ordinal assignment (medium).** One pass over all 10 sections
assigning global ordinals; write the ordinal fast field into a rebuilt tantivy
section. Measure build cost on ONE section before committing to ten. *Bar:* does
not materially extend the existing build.

**N4 — end-to-end prototype on one section (the real test).** Rewrite
`_post_filter` and `_hydrate` against ordinal arrays for
`social_sciences__recent` only, behind an env gate, and measure whole-query
latency — not primitives. *Bar:* a **record-tc byte-parity gate** against the
current retriever, the same bar `eval_parity_section_waves.py` holds. Parity is
non-negotiable; speed without it is meaningless.

**N5 — C3 block file (independent, do it regardless).** The flat zstd block file
is worth ~3.4× on abstract hydration and ~2.2 GB *on its own*, and does not
depend on ordinals. It is the highest value-per-unit-risk item in this whole
investigation. Ship it separately.

**Explicitly NOT next:** migrating to Lance (§12), or any engine substitution.
§12's Lance result (1.15–1.72× on lookup) is *worse* than ordinal addressing on
the same axis, and Lance cannot host the SPLADE leg while lancedb#1930 is open.
Lance stays a documented alternative, not a plan.

## 8. Status

**MEASURED:** filter mask and key lookup at 150M (§4.1), residency (§4.2),
tantivy fast-field read on the real index (§4.3), plus the C1/C3/C5 results that
motivated this in doc 17 §10–§12.

**NOT MEASURED, NOT IMPLEMENTED:** everything in §7. There is no end-to-end
number for this design — only its primitives. The 96× spike-vs-production gap in
doc 17 §10.3 is the standing reason not to trust primitives as a system result.

**Not adopted. No production code changed.**

---

## 9. N5 EXECUTED (2026-08-02): flat block store built, gated, **2.89×**

§7's N5 — C3's block half, the item flagged "do it regardless" because it is
independent of ordinals and the best value-per-risk in the investigation.

- Code: `spike/meta_consolidation/08_n5_flat_block_store.py`
- Results: `data/eval_results/n5_flat_blocks_20260802_0741.json`
- Built from the production `social_sciences__recent/abstracts.sqlite`
  (read-only): **1,062,917 blocks → `blocks.bin` 11.13 GB + 19.7 MB index**,
  878 s. Trained per-script zstd dictionaries and the ~32 KB block layout copied
  **verbatim** — the codec is untouched, which §11 showed matters more than the
  envelope (payload is 83% of the store).
- Locator deliberately left in SQLite: §11 measured moving it to tantivy as a
  27–54× regression on that stage.

**Byte-parity gate: PASS.** 20,000 randomly sampled ids; every abstract returned
byte-identical to `AbstractStore.fetch`. Same id set, zero mismatches.

| k | production `abstracts.sqlite` | N5 flat block file | |
|---|---|---|---|
| 10 | 18.71 ms | 6.64 ms | 2.82× |
| 50 | 80.06 ms | 27.91 ms | 2.87× |
| 100 | 159.36 ms | 55.22 ms | **2.89×** |

> **CORRECTION 2026-08-02 (audit): N5 is a latency lever, NOT a space lever.**
> §7 above described N5 as worth "~3.4× on abstract hydration and ~2.2 GB". The
> 2.2 GB is doc 17 §11's *computed* ceiling (flagged there as "computed, not
> measured") for the **full C3 design**, which also moved the locator into
> tantivy and so removed the entire 2.339 GB SQLite envelope. N5 deliberately
> keeps the locator in SQLite, so that envelope stays. Measured on
> `social_sciences__recent`: sqlite 13.47 GB + sidecar 11.15 GB = **24.62 GB
> with both present**, and ~13.49 GB after `DROP TABLE blocks; VACUUM;` —
> i.e. roughly where it started. Adopt N5 for the 2.89×, not for space.

**Doc 17 §11 projected ~3.4×; the measured end-to-end is 2.89×.** The projection
took the block stage's 3.8× and assumed it carried through; the locator and
decompress stages dilute it. §11 has been superseded in place. The verdict is
unchanged — adopt the block move — but the multiple was optimistic, which is the
third time in this investigation a projection has been worse than its
measurement (cf. the 48× pragma → 1.18×, and the 3.23× Lance size → 1.73×).

## 10. RESTAGED (2026-08-02): the rebuild is an optimisation worth ~2%, not a prerequisite

§5's design stored the ordinal as a **tantivy fast field**, and §7's N3/N4
assumed a section rebuild. Prompted by the question *"what parts do we need from
the original OpenAlex data?"*, that assumption was checked and it is **wrong in
the load-bearing direction**.

**What a rebuild would cost.** tantivy stores neither title nor abstract
(`builder.py:130-131`, both `stored=False`), so a section cannot regenerate
itself. Titles are recoverable from `meta.sqlite` (all 150.4M), but abstracts
only exist locally for the one hot section (23,398,073 docs). The source spool is
gone — `data/thinclient_index/spool/` is empty and the 123 GB `spool_backup` in
`REBUILD_TO_PERSISTENT_PATH.md` is absent (*when and how is not established; do
not infer*). So rebuilding all ten sections needs OpenAlex
`abstract_inverted_index` for **~127,015,025 documents**.

**What a rebuild would buy.** Nothing except removing the `W-id → ordinal` hop:

| stage, 1000 candidates | today | ordinal, NO rebuild |
|---|---|---|
| W-id → row | 400.8 ms | 0.956 ms (binary search) |
| filter mask | *(above)* | 0.161 ms |
| **total** | **400.8 ms** | **~1.1 ms** |

**~360× with zero changes to tantivy, SEISMIC, usearch, or the build.** The legs
keep emitting W-ids exactly as they do today. An ordinal fast field would remove
only the 0.956 ms binary search — **~1 ms of a ~50 ms query, about 2%** — in
exchange for re-fetching 127M abstracts.

**Restaged accordingly:**

- **Phase 1 — no rebuild, no OpenAlex, no engine change.** Ordinal arrays +
  binary search, swapping `_post_filter` only. Captures ~360× of the win. This
  is what N3 builds and N4 gates.
- **Phase 2 — DEFERRED INDEFINITELY.** Ordinal fast fields in tantivy (§4.3
  measured the read as 2.1–11× cheaper than the stored-id read, so the mechanism
  is sound — it is simply not worth 127M abstracts for ~2%). Revisit only if the
  corpus is re-materialised for an unrelated reason.
- **N1 (SEISMIC ordinal-nativeness) is likewise downgraded** from BLOCKING to
  optional. It also only removes a translation hop; its real merit is that
  `"12345"` is shorter than `"W2803642969"`, a small memory win at rebuild time.

This is the same error as the deferred-MPHF case in §7 N2 — staging work because
the design *could* use it, without first pricing what it buys. Caught earlier
this time, but caught by a question rather than by discipline.

---

## 11. N3 + N4 EXECUTED (2026-08-02): parity PASS, **120–211× on the filter stage**

### N3 — ordinal artifacts built from the real `meta.sqlite`

- Code: `spike/meta_consolidation/09_n3_build_ordinals.py`
- Results: `data/eval_results/n3_ordinal_build_20260802_0804.json`

**25,000,000 ordinals in 258 s = 97,063 docs/s**, `monotonic=True` — the
`INTEGER PRIMARY KEY` scan really does emit ascending ids, so `ordinal → W-id`
is sorted for free and the binary search is valid. Artifacts **0.33 GB**
(filter columns 0.13 GB, `wids` 0.20 GB) against `meta.sqlite`'s 24.91 GB.

Extrapolated to the full 150,413,098 docs: **~26 min** and **~2.0 GB**, which
matches §4.2's independently-derived ~1.95 GB. Build throughput is I/O- and
CPU-bound and linear, so this extrapolation is far safer than a latency one —
but it is still an extrapolation, and **the full 150M pass was not run**.

> **Why 25M and not 150M:** the first full attempt burned 14 minutes inside
> `SELECT count(*) FROM docs`, a full scan of the 24.9 GB table, purely to size
> the output arrays — a self-inflicted cost, since the row count was already
> known from §10.3's probe. Restarted with `--limit` (which skips the count) on
> a 25M subset to fit the session. The script should take the row count as a
> parameter; it currently only avoids the scan via `--limit`.

### N4 — `_post_filter` swapped, gated on parity

- Code: `spike/meta_consolidation/10_n4_postfilter_parity.py`
- Results: `data/eval_results/n4_postfilter_20260802_0805.json`
- Arms: production `_meta_rows` + `_post_filter` (reproduced from
  `retriever.py:988-1044`) vs `searchsorted` + vectorised mask. **No rebuild of
  tantivy, SEISMIC or usearch** — per §10, the legs keep emitting W-ids.

**PARITY GATE: PASS — 360 trials across 3 filter shapes, 0 mismatches.** The
comparison is full list equality: surviving **ids, scores AND rank order**. A
filter that reorders the legs' ranking is wrong no matter how fast it is.

| filter | trials | mismatches |
|---|---|---|
| `year_only` | 120 | 0 |
| `year_type` | 120 | 0 |
| `year_type_oa` | 120 | 0 |

| candidates | production (`meta.sqlite`) | ordinal path | |
|---|---|---|---|
| 100 | 21.43 ms | **0.179 ms** | 119.7× |
| 500 | 101.38 ms | **0.603 ms** | 168.1× |
| 1000 | 214.14 ms | **1.013 ms** | **211.4×** |

**Read the ratios carefully.** The production arm here measures 214 ms at
k=1000, against 400.8 ms measured over the full 150M id range (§4.1) — because
candidates are drawn from the ordinal-covered first 25M ids, a narrower and
more cache-friendly slice. The **ordinal arm is scale-independent** (1.013 ms
here vs 0.956 ms at full 150M, §4.1). So 120–211× is the *conservative* figure;
at full corpus coverage the production side rises to ~400 ms while the ordinal
side does not move, putting the true ratio nearer 400×. **The 120–211× band is
what was measured; the ~400× is inference.**

### What this settles, and what it does not

**Settled:** the ordinal filter path is correct (byte-exact, order-preserving,
360 trials) and 2+ orders of magnitude faster, with **no change to any search
engine and no rebuild of anything**.

**Not settled:**
1. **Whole-query latency.** This measures the filter stage in isolation. The
   tantivy leg alone is ~47 ms (§4.3), so a ~213 ms filter saving is large but
   the end-to-end query improvement has NOT been measured.
2. **The full 150M artifact build** — extrapolated, not run.
3. **`_hydrate`** — only `_post_filter` was swapped. Title/DOI hydration still
   goes to `meta.sqlite`.
4. **Integration.** Nothing is wired into `retriever.py`; this is a standalone
   harness reproducing the production code path, not a patched retriever.
5. **The stale-ordinal guard** (§6 risk 1) is designed, not implemented.

**Not adopted. No production code changed by this spike.**

---

## 12. The stale-ordinal guard IMPLEMENTED (2026-08-02)

§11's "not settled #5". §6 risk 1 called stale ordinals *the single most
dangerous property of the design*; it was designed but not built, and nothing
should ship before it exists.

- Code: `src/lib/thinclient/ordinals.py` — `OrdinalSpace`, `write_stamp`,
  `load_if_enabled`. **Read by nothing yet**: no serving path imports it, and
  it is inert unless `SFU_THINCLIENT_ORDINALS` names a directory.
- Tests: `scripts/tests/test_ordinals_guard.py` — **12/12 pass 2026-08-02**.

**Mechanism.** The build mints a uuid4 `ordinal_space_id` into
`ordinal_space.json` beside the arrays; the index `manifest.json` must carry the
same id under `ordinal_space_id` to authorise the pairing. `OrdinalSpace`
raises `OrdinalSpaceMismatch` on any other outcome and **fails closed** — an
unstamped manifest disables ordinals rather than trusting them. There is
deliberately no override flag. The id is a fresh uuid per build, not a hash of
the corpus, because two builds of the same corpus are still *different ordinal
spaces* and a content hash would invite treating "same corpus" as "same
addresses".

Each refusal has its own test: rebuilt arrays vs an old manifest, unstamped
manifest, missing stamp file, truncated arrays (the `--rows` under-estimate
case, which the build now also refuses outright).

**A second silent-wrong-answer hazard was found while wiring this, and is not
in §6.** `_meta_rows` falls back to `DenseWarmCache.metadata_rows` for docs
missing from `meta.sqlite` (`retriever.py:1022-1025`; 9,255 such docs at the
last serve). Those are added at query time and by construction have **no
build-time ordinal** — §6 risk 3, but the consequence was under-stated there.
The N4 harness's mask would drop them silently. So `OrdinalSpace.post_filter`
returns `(kept, unresolved)` and refuses to decide the misses itself; the caller
must resolve them the existing way. This makes ignoring warm-cache docs a
visible choice at the call site instead of an invisible default.

**Efficacy: N/A — this is a correctness guard, not a lever.** It is not on the
measured latency path.

### The full 150M ordinal space BUILT (§11's "not settled #2")

§11 extrapolated the full build from a 25M subset at ~26 min and ~2.0 GB. It
was run for real on 2026-08-02 and the extrapolation holds:

| | §11 (25M, measured) | §11 → 150M (extrapolated) | **150M, measured** |
|---|---|---|---|
| rows | 25,000,000 | 150,413,098 | **150,413,098** |
| throughput | 97,063 docs/s | — | **98,867 docs/s** |
| wall time | 258 s | ~26 min | **25.4 min** (1521 s) |
| artifacts | 0.33 GB | ~2.0 GB | **1.96 GB** |

`monotonic=True` over the whole corpus, so `ordinal → W-id` is sorted for free
and the binary search is valid at full scale. Filter columns 0.75 GB + `wids`
1.20 GB against `meta.sqlite`'s **24.91 GB** — independently reproducing §4.2's
~1.95 GB residency figure, derived there by a different route.

Results: `data/eval_results/n3_ordinal_build_20260802_1946.json`. Verified
against `meta.sqlite` on 300 random ordinals: the binary search landed on the
exact ordinal every time and all 300 `(year, type, is_oa)` triples matched the
source rows exactly.

This is the one extrapolation in this investigation that survived contact with
its measurement — because build throughput is I/O- and CPU-bound and linear,
unlike the latency extrapolations that were wrong by up to 96×.

---

## 13. N6 EXECUTED (2026-08-02): **whole-query 3.20× at production's default top_k**

§11's "not settled #1", the number that decides whether any of this ships.

- Code: `spike/meta_consolidation/11_n6_whole_query_latency.py`
- Results: `data/eval_results/n6_whole_query_20260802_2104.json`
- Real `ThinClientRetriever.search()` against the real index, arms switched by
  the **real serving gate** (`_ordinals`, what `SFU_THINCLIENT_ORDINALS` sets)
  — so the ordinal arm runs the shipped `_post_filter`, fallback included, not
  a harness reimplementation.
- 12 eval queries × 3 reps, arms interleaved per rep with order randomised per
  rep, `SFU_DENSE_WARMCACHE=0`, SEISMIC + ordinal arrays both staged to local
  disk (see "Residency" below).

| case | candidates | production | ordinal | Δ | |
|---|---|---|---|---|---|
| splade k=10 | 100 | 91.6 ms | 81.3 ms | −10.2 ms | 1.13× *(within noise — not claimed)* |
| **splade k=50** | **500** | **344.6 ms** | **107.6 ms** | **−237.0 ms** | **3.20×** |
| splade k=100 | 1000 | 728.8 ms | 269.5 ms | −459.2 ms | **2.70×** |
| bm25f k=10 | 100 | 547.5 ms | 539.0 ms | −8.5 ms | 1.02× *(control)* |
| bm25f k=50 | 500 | 572.1 ms | 522.7 ms | −49.3 ms | 1.09× *(control)* |
| bm25f k=100 | 1000 | 570.5 ms | 567.4 ms | −3.1 ms | 1.00× *(control)* |

**PARITY PASS: 216/216 pairs, 0 mismatches**, full returned result lists (ids,
scores AND order) across all six cases. **Coverage: 0 ids without an ordinal in
57,600** — the full-150M space covers the corpus, and no query fell back to
SQLite.

### What the negative control disqualifies

`_bm25f_leg` pushes filters into tantivy and **never calls `_post_filter`**, so
its three rows must show no difference. They show 1.00×, 1.02× and **1.09×**.
That 9% is spurious by construction, and it is the honest **noise floor** at
n=36 samples per arm.

Therefore **splade k=10's 1.13× is inside the noise band and is NOT claimed.**
Only k=50 (3.20×) and k=100 (2.70×) clear it, and they clear it by 30×. The
band also means the two headline multiples should be read as "≈3×", not as
3.20 and 2.70 precisely.

**p90 tails are not usable and no tail claim is made** — they invert in places
(splade k=10: ordinal p90 858.6 ms vs production 154.1 ms) because tail is
dominated by page faults in a shared page cache at this sample size.

### Where the query actually goes (production arm, splade k=50)

| stage | ms | share |
|---|---|---|
| `_post_filter` | 261.1 | **61.5%** |
| `_hydrate` → `_meta_rows` | 17.5 | 4.1% |
| `_hydrate` → `fetch_abstracts` | 29.4 | 6.9% |
| everything else (SEISMIC leg + SPLADE encode) | 117.0 | 27.5% |
| total | 424.9 | |

The filter stage is **61.5% of the whole query**, which is why replacing it
moves the system number at all — and is the direct answer to §10.3's worry that
a stage-level win would evaporate end-to-end. It did not.

### `_hydrate` extension REJECTED (§11 "not settled #3") — measured, not assumed

`hydrate_meta` is **17.5 ms, 4.1%** of the query. Extending ordinals to
title/DOI needs a flat blob over all 150,413,098 docs, for at most 4.1% even if
it became free. That is the same shape of mistake as §7 N2's MPHF (~2%) and
§11's C3 locator (1.3%) — optimising a stage that is not on the critical path.
**Not built.** It is `_post_filter`, and only `_post_filter`, that was worth
replacing. (`fetch_abstracts` at 6.9% is separately addressed by N5's 2.89×.)

### Residency is a deployment PRECONDITION, not an implementation detail

The first N6 attempt ran the ordinal arrays from the repo path, which is **9p**
in this container, and the ordinal arm measured **2973 ms vs production's
362 ms — 8× SLOWER**, parity still PASS. A `searchsorted` over the 1.20 GB
`wids.npy` is ~27 random accesses per id; at 500 candidates that is ~13,500
random page faults, and on 9p at ~0.5 ms/fault that is ~3 s.

§4.2 said residency was "the mechanism"; this measures what happens without it.
**The arrays must sit on local disk (or be RAM-resident). On a passthrough
mount the design is worse than the SQLite path it replaces.** The same applies
to the SEISMIC shards, which production already stages via
`SFU_SEISMIC_STAGE_DIR`. Both were staged to local overlay for the reported run.

### Status after N6

**Settled:** whole-query latency (this section), the full-150M artifact build
(§12), the stale-ordinal guard (§12), retriever integration (§12), and
`_hydrate` (rejected, above).

**Still not settled:** search *quality* is untouched by all of this — the
parity gate proves the ordinal path returns byte-identical result sets, so
quality is unchanged **by construction**, but no LLM-judged eval was run and
none is needed for that reason. Adoption also still needs an
`ordinal_space_id` stamped into the production `manifest.json`, which is an
operator action and has **not** been done: nothing is enabled today.

---

### N3 build script fixed (§11's noted defect)

`09_n3_build_ordinals.py` now takes `--rows`, sizing the output arrays without
the 14-minute `SELECT count(*)` full scan. An under-estimating `--rows` is
**refused**, not silently truncated: the old `i >= n_rows` break would have
emitted a partial ordinal space, and a missing tail is invisible at query time
(those ids simply fail the `found` check).
