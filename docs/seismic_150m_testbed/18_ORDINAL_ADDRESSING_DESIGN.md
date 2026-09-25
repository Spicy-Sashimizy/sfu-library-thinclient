# 18 — Ordinal addressing: the thin client's storage problem is an ADDRESSING problem

**Status:** ACTIVE

*(The 2026-08-02 header line immediately below is the creation-time state and is
itself superseded: §22–§23 BUILT and PUBLISHED the flat abstract sidecar for
`social_sciences__recent` on 2026-08-17, so production code did change; the
ordinal `_post_filter` path remains gated off behind `SFU_THINCLIENT_ORDINALS`.)*

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

> **Reconciled 2026-09-25** — 5 items (N1–N5): 4 DONE, 0 CLOSED, 0 SUPERSEDED, 1 STILL OPEN.
> STILL OPEN: **N2** (MPHF viability), deferred on this section's own quantified
> reasoning and listed as open work nowhere — not in `docs/README.md`, not in this
> folder's `README.md`. Read every "DONE" here together with **§14 (2026-08-03)**,
> which re-attributed the headline multiples to the 9p filesystem rather than to
> addressing, and with §20–§21 (2026-08-04), which closed the meta-store route
> ("no store holds the speed gate; meta.sqlite stays").

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

— **DONE 2026-08-02 (answered in place above; PASS by code inspection, folded into N3/§11).**

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

— **STILL OPEN 2026-09-25** — never built or measured; no MPHF/PtrHash/RecSplit
result file exists under `data/eval_results/`. The deferral reasoning still holds
and §14 (2026-08-03) strengthens it — ordinals are a **residency** lever, and
§12's measured sorted-array space (1.96 GB for the full 150M ordinal space, vs
`meta.sqlite`'s 24.91 GB) already works. Listed as open work in no Active table
(`docs/README.md`, `docs/seismic_150m_testbed/README.md`).

**N3 — build-time ordinal assignment (medium).** One pass over all 10 sections
assigning global ordinals; write the ordinal fast field into a rebuilt tantivy
section. Measure build cost on ONE section before committing to ten. *Bar:* does
not materially extend the existing build.

— **DONE 2026-08-02 (§11 + §12)** — ordinal artifacts built at 97,063 docs/s on
the pilot and the full 150M space at 98,867 docs/s (1.96 GB), plus the
stale-ordinal guard (§12) and the `SFU_THINCLIENT_ORDINALS` retriever gate
(default off). Results `data/eval_results/n3_*`, `n4_*`. **§10 restaged the
tantivy rebuild itself as deferred indefinitely** (it buys ~2% and would cost
~127M re-fetched OpenAlex abstracts) — so the fast-field half of this item is
deliberately not done.

**N4 — end-to-end prototype on one section (the real test).** Rewrite
`_post_filter` and `_hydrate` against ordinal arrays for
`social_sciences__recent` only, behind an env gate, and measure whole-query
latency — not primitives. *Bar:* a **record-tc byte-parity gate** against the
current retriever, the same bar `eval_parity_section_waves.py` holds. Parity is
non-negotiable; speed without it is meaningless.

— **DONE 2026-08-02 (§11 + §13; RE-ATTRIBUTED §14, 2026-08-03)** — the
`_post_filter` swap passed a 360-trial parity gate (ids, scores AND rank order)
at 120–211× on the stage and 3.20× whole-query at `top_k=50` (§13, parity PASS
216/216). **§14 then showed that win was the filesystem, not the addressing**:
staging `meta.sqlite` to local disk gets 2.83× with no code change, and against a
production-realistic baseline the whole ordinal win is 4.0 → 1.5 ms ≈ 2.0% of the
query, inside the ±4% noise floor. `_hydrate` was NOT rewritten (rejected on
measurement, then reopened in §15 under a consolidation goal). Nothing is
enabled — `SFU_THINCLIENT_ORDINALS` stays default off.

**N5 — C3 block file (independent, do it regardless).** The flat zstd block file
is worth ~3.4× on abstract hydration and ~2.2 GB *on its own*, and does not
depend on ordinals. It is the highest value-per-unit-risk item in this whole
investigation. Ship it separately.

— **DONE 2026-08-17 (§9 spike 2026-08-02 → §22 production build → §23 serving
efficacy)** — the flat block store passed a byte-parity gate on 20,000 abstracts
at 2.89× end-to-end (§9, correcting §11's 3.4× projection), then was **BUILT AND
PUBLISHED** for `social_sciences__recent` (§22: gate PASS, 11.57 GB, 19 min 33 s)
— that section serves flat today. Serving efficacy measured against the published
directory (§23): byte-parity PASS, local disk **1.091× warm / 2.546× cold**, 9p
2.876×, −1,897,229,898 B, and **0.919× (slower) on a freshly started process**
until its 421 MB locator is resident. Harness
`scripts/seismic_testbed/j1_flat_sidecar_serving_ab.py`, results
`data/eval_results/j1_flat_*_20260817.json`.

**Explicitly NOT next (still binding as of 2026-09-25 — not counted as an item
above; nothing since has re-opened it, and §20–§21 of 2026-08-04 closed the
meta-store bake-off with "meta.sqlite stays"):** migrating to Lance (§12), or any engine substitution.
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

> **QUALIFIED 2026-08-03 by §16: the 2.89× is a 9p number and does not transfer
> to production.** Both sides of this comparison were on 9p (`work_n5` is on the
> passthrough mount), so it is like-for-like and not the §14 error — but with
> both sides on **local disk**, the identical payload move measures **1.21×**.
> §16 also shows the locator this section deliberately left in SQLite is worth a
> further **4.55×**, i.e. §9 optimised the smaller half.
>
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

> **RE-ATTRIBUTED 2026-08-03 by §14 — the multiple is real, its CAUSE is not
> what this section says.** The 120–211× was measured against a `meta.sqlite`
> sitting on **9p**. §14's control staged that same file to local disk with no
> code change and the filter stage went 222.2 → **4.0 ms** on its own. Ordinals
> then take it 4.0 → 1.5 ms: a further 2.7×, worth **2.5 ms (2.0%)** of the
> query, which is *inside* §14's ±4% noise floor. Read every multiple below as
> "ordinals vs SQLite-on-9p", not "ordinals vs SQLite". The parity results and
> the build numbers are unaffected.

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
- Tests: `scripts/tests/test_ordinals_guard.py` — 12/12 pass 2026-08-02; the
  suite has since grown to **21/21 pass 2026-08-03** (`pytest -q`; the file is
  pytest-style and running it directly is a silent no-op that exits 0).

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

> **RE-ATTRIBUTED 2026-08-03 by §14 — this section's headline is a FILESYSTEM
> result, not an addressing result.** N6 staged the ordinal arrays to overlay
> (correctly — see "Residency" below) but left the production arm's
> `meta.sqlite` on **9p**, so its two arms differed in *two* ways at once and
> the 3.20× could not be attributed. §14's 2×2 control does attribute it:
> staging `meta.sqlite` alone, **with no ordinals and no code change**, gets
> 2.83× — statistically the same as the ordinal arm's 2.72×, and adding
> ordinals on top of staging gets nothing further. The measurements below are
> sound; the causal claim is not. **Do not quote 3.20× as the value of ordinal
> addressing.**

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

---

## 14. N7 EXECUTED (2026-08-03): the 3.20× was the FILESYSTEM, not the addressing

- Code: `spike/meta_consolidation/12_n7_fs_control.py`
- Results: `data/eval_results/n7_fs_control_20260803_0548.json`

### The flaw in N6 that this section exists to correct

§13 established residency as a precondition and staged the ordinal arrays to
`/var/tmp` (overlay). It did **not** stage `meta.sqlite`, which lives at
`data/thinclient_index/meta.sqlite` — **9p** in this container (`df -T`,
2026-08-03). So N6's two arms differed in two ways simultaneously:

| N6 arm | filter addressing | `meta.sqlite` filesystem |
|---|---|---|
| production | SQLite B-tree | **9p** (~0.5 ms/fault, page cache does not hold) |
| ordinal | mmap'd columns | (overlay, for the arrays) |

A two-variable experiment cannot attribute its result to one variable. §13's
own method section demands a negative control for exactly this reason and then
did not apply it to the filesystem. **The 3.20× was an upper bound on the
addressing win, and the split had never been measured.**

### The control: a 2×2 factorial over the two levers

Four arms on the real `ThinClientRetriever.search()`, interleaved within each
rep with order randomised per rep, every arm warmed (N6 warmed only production,
which mildly favours the SQLite arms). `_meta` is swapped by rebinding
`retriever._meta` to a second `sqlite3.connect` on a byte copy of the file,
opened exactly as `retriever.py:414` opens the original; the staged copy's row
count and schema are asserted equal before any timing. 12 queries × 3 reps,
n=36 per arm per case, `SFU_DENSE_WARMCACHE=0`, SEISMIC staged.

**Whole-query p50 (ms), `year_range=(2010,2025) + type=article`:**

| case | `prod_9p` | `sqlite_staged` | `ordinal_9p` | `ordinal_staged` |
|---|---|---|---|---|
| **splade k=50** | **332.3** | **117.3 (2.83×)** | **122.3 (2.72×)** | **125.6 (2.65×)** |
| **splade k=100** | **684.5** | **257.1 (2.66×)** | **248.4 (2.76×)** | **258.6 (2.65×)** |
| bm25f k=50 *(control)* | 524.7 | 528.0 (0.99×) | 546.3 (0.96×) | 525.4 (1.00×) |
| bm25f k=100 *(control)* | 527.4 | 509.2 (1.04×) | 534.1 (0.99×) | 527.5 (1.00×) |

**PARITY PASS: 4/4 cases, 0 mismatches** — all four arms returned identical
`(id, score)` lists, so the arms are comparable and the swap is sound.

**Noise floor ±4%** (bm25f spans 0.96–1.04×), tighter than §13's 1.09× because
every arm is warmed here. The SPLADE effects clear it by ~65×.

### Where the time actually goes — the number that settles it

**Stage profile, splade k=50, mean ms per query:**

| arm | `_post_filter` | `hydrate_meta` | `fetch_abstracts` | other | total |
|---|---|---|---|---|---|
| `prod_9p` | **222.2** | 15.0 | 24.3 | 124.5 | 385.9 |
| `sqlite_staged` | **4.0** | 0.3 | 20.5 | 102.5 | 127.4 |
| `ordinal_9p` | **1.5** | 7.5 | 19.9 | 101.3 | 130.2 |
| `ordinal_staged` | **1.5** | 0.4 | 19.9 | 102.5 | 124.3 |

**Copying a file cut the filter stage 222.2 → 4.0 ms — 55×, no code change.**
Ordinals then take 4.0 → 1.5 ms: a further 2.7× on the stage, but worth
**2.5 ms on a 127.4 ms query = 2.0%**, which is inside the ±4% noise floor and
therefore **not claimable**. Whole-query, `sqlite_staged` (117.3 ms) is
nominally *faster* than `ordinal_staged` (125.6 ms); the marginal effect of
ordinals is not resolvable at this sample size.

### The two levers are redundant, not additive

Each alone gets ~2.7×; both together get nothing more. The mechanism is
consistent: `_post_filter` resolves ~500 candidates against a 24.9 GB B-tree,
which on 9p is thousands of ~0.5 ms faults. Ordinals remove the faults by
shrinking the filter's working set to 1.96 GB of mmap'd arrays; staging removes
them by making the faults cheap. Either clears the bottleneck, so the remaining
~250 ms is the SEISMIC leg + SPLADE encode, which neither lever touches.
`ordinal_9p` staying fast while its `_hydrate` still reads 9p fits the same
mechanism — hydrate touches only `top_k` ids, not the 10× over-fetched
candidate set.

### What this does to the case for ordinal addressing

**Ordinals are a RESIDENCY lever, not a latency lever and not a disk-space
lever.** The first draft of this section called them a space lever; that was
wrong and is corrected here the same day. **Ordinals do not let you delete
`meta.sqlite`** — `_hydrate` still reads title/DOI/section from it
(`retriever.py:1014`) and §13 rejected extending ordinals to hydrate, so the
1.96 GB is **additive to** the 24.9 GB, not a replacement. Nothing about disk
footprint improves; it gets 1.96 GB worse.

What actually shrinks is the **page-cache working set the filter stage
touches** — 1.96 GB of mmap'd columns instead of random descent through a
24.9 GB B-tree. That is §4.2's original "residency is the mechanism" claim and
§12's 1.95 GB figure, and it is the only surviving case for this module:

| | stage/site `meta.sqlite` locally | ordinal addressing |
|---|---|---|
| filter-stage resident set | ~24.9 GB B-tree, randomly descended | **1.96 GB**, additive |
| total disk | 24.9 GB | 24.9 GB **+ 1.96 GB** |
| whole-query k=50 | 117.3 ms | 125.6 ms |
| filter stage | 4.0 ms | 1.5 ms |
| build cost | none | 25.4 min, rebuilt every index build |
| serving code | none | `ordinals.py` + `_post_filter` branch |
| failure mode | none new | stale ordinals return the WRONG doc silently (§6 risk 1) |
| operator ceremony | none | stamp `ordinal_space_id` into `manifest.json` |

So the decision rule is **RAM**, not speed and not disk: on a host with enough
page cache to hold the hot part of the B-tree, ordinals are worth ~2% and
should not ship. On a RAM-constrained host they may hold their 1.5 ms while
staged SQLite degrades toward the 9p numbers. **That degradation has not been
measured** — see "Not settled" #5, which is now the only experiment that could
justify this module.

**By this investigation's own standing bar, ordinals-over-staging does not
clear it.** §7 N2's MPHF (~2%), §11's C3 locator (1.3%) and §13's `_hydrate`
(4.1%) were all rejected as off-critical-path. Ordinals-over-staging is 2.0%,
and unlike those it also ships a silent-wrong-answer failure mode.

### Not settled by this section

1. ~~**The staging plumbing does not exist.**~~ **SETTLED 2026-08-17 — the
   plumbing now exists.** As written (and true when measured): `SFU_SEISMIC_STAGE_DIR` /
   `_stage_shards_local` stages SEISMIC shards only; there
   is no `meta.sqlite` equivalent. N7 measured the lever by swapping the
   connection, which is what such a path would do, but **the production code to
   stage `meta.sqlite` is UNBUILT** — this is a measured lever, not a shipped
   one.
   **Correction 2026-08-17:** `retriever._stage_meta_local` + `_connect_meta`
   ship it — `SFU_META_STAGE_DIR=<dir>` (or `SFU_STAGE_META=1` to reuse
   `SFU_SEISMIC_STAGE_DIR`), `SFU_META_STAGE_FORCE=1`,
   `SFU_META_STAGE_VERIFY=size|fingerprint|sha256`; default OFF, and a no-op
   unless the source FS is 9p/virtiofs/NFS/… so it is a dev-container lever and
   a droplet no-op. Atomic tmp+rename with a verified copy, a `.staged_ok`
   marker keyed on the SOURCE size+mtime_ns+fingerprint, and a refusal to copy
   a database with a live `-wal`. Tested at synthetic size:
   `scripts/tests/test_meta_staging.py` (23 cases). Full command:
   `docs/THIN_CLIENT_SWAP.md` §"The same lever for `meta.sqlite`".

   > **N8 — the automated path MEASURED at full size, 2026-08-17.** The
   > 2026-08-03 numbers above came from a hand `cp` + a hand
   > `sqlite3.connect`; this is the *shipped* path (`_stage_meta_local` +
   > `_connect_meta`'s `mode=ro&immutable=1` open) on the real 24.9 GB file.
   > Code: `spike/meta_consolidation/20_n8_meta_stage_shipped.py`. Results:
   > `data/eval_results/n8_meta_stage_shipped_20260817.json`.
   >
   > | `_post_filter`, 500 candidates | p50 | mean | p90 |
   > |---|---|---|---|
   > | unstaged (`meta.sqlite` on 9p) | **186.7 ms** | 187.9 | 194.6 |
   > | staged (`/var/tmp/meta_stage`, overlay) | **2.97 ms** | 2.97 | 3.14 |
   > | **ratio** | **62.8×** | | |
   >
   > n=36/arm (12 queries × 3 reps), arms interleaved with order randomised per
   > rep, both warmed, candidate lists captured once per query from real
   > `search()` calls and replayed identically to both arms, `_ordinals` off in
   > both (so this is purely the filesystem variable). **Parity 36/36, 0
   > mismatches.** The staging copy itself: **194 s** for 24,908,001,280 B
   > (~128 MB/s off 9p), fingerprint-verified; the second call **skipped in
   > 0.01 s** off the `.staged_ok` marker; `PRAGMA quick_check` = ok,
   > 150,413,098 rows on the copy.
   >
   > **The N7 expectation (222.2 → 4.0 ms, 55×) is reproduced and slightly
   > exceeded** — both arms here are a little faster than 2026-08-03's, and the
   > ratio is of the same order, so the shipped path buys the measured lever
   > with no loss from the immutable read-only open. Aside worth recording: the
   > harness's one-off `SELECT count(*) FROM docs` against the *unstaged* 9p
   > file took **~25.7 min** (01:29:49 → 01:55:29) — a full-table scan of
   > 150.4 M rows over 9p, outside all timed sections, but a vivid measure of
   > what the filter stage is fighting. Item 3 below still applies: on a
   > droplet the source FS is local, `_stage_meta_local` is a no-op by
   > construction, and the staged arm IS the baseline.
2. **Both copies were resident in one process.** Holding a 9p and an overlay
   copy of a 24.9 GB file against 56 GB RAM doubles the meta working set, so
   both arms saw more cache pressure than a single-copy deployment would.
   Interleaving is still correct — the two files are distinct, so cross-arm
   fault reuse on `meta.sqlite` is impossible by construction, while the shared
   SEISMIC/tantivy/ordinal resources still need it.
3. **`prod_9p` HAS NO ANALOGUE IN PRODUCTION, so the realisable win is 2.0%,
   not 2.83×.** `THIN_CLIENT_SWAP.md` (2026-07-18, lines 251-254) already
   settles this for the SEISMIC shards and the same reasoning applies to
   `meta.sqlite`: on a DO droplet the index sits on local block storage, "cold
   faults are already native-fast and page cache holds; the 9p wall is a
   WSL2-dev-container artifact that does not exist off 9p." Production's real
   baseline is therefore the `sqlite_staged` arm — `_post_filter` ≈ 4.0 ms —
   and everything ordinals can still win on the target is **4.0 → 1.5 ms**.
   Building a `meta.sqlite` staging path would be a **no-op on the droplet**,
   exactly as SEISMIC staging already is. (An earlier draft of this section
   hedged this as "may simply not exist there"; the repo had already answered
   it and the hedge is withdrawn.)
4. Concurrency, the dense leg, and the warm-cache `unresolved` merge path are
   all still unmeasured (§13 status list), and all of them inherit this
   section's correction: they must be measured against a **staged** baseline,
   not against `prod_9p`. At 4.0 ms of staged, lock-held filter work the
   concurrency ceiling is far higher than `_meta_lock` made it look.
5. **The residency cliff is unmeasured, and it is the only remaining case for
   this module.** Staged SQLite at 4.0 ms assumes the hot B-tree pages stay
   cached. What happens to that 4.0 ms as available page cache shrinks — and
   whether ordinals' 1.5 ms holds while it degrades — decides whether ordinal
   addressing is worth anything at all. This project already treats RAM as a
   hard serving constraint (`THIN_CLIENT_SWAP.md`: "≤ 8 GB DO NOT SHIP — 2–5
   s/query permanent thrash"), so the question is live rather than academic.

### The methodological lesson, which is the real result (§14)

§13's method section says "every speed claim needs a negative control — an arm
that *cannot* be affected by the change", and N6 built one (`bm25f`) for the
*addressing* variable while leaving the *filesystem* variable uncontrolled.
A negative control only covers the variable you point it at. The prompt-level
rule "check the filesystem before believing any latency number" was applied to
the new code's artifacts and not to the baseline's — and the baseline is where
the entire multiple came from.

---

## 15. C7 (2026-08-03): `meta.sqlite` CAN be deleted — **−10.22 GB, and faster**

- Code: `spike/meta_consolidation/13_c7_meta_flat_sizing.py`
- Results: `data/eval_results/c7_meta_flat_20260803_0635.json`
- **Status: MEASURED at 1M-doc scale. IMPLEMENTED: no. Nothing built or wired.**

### Why §13's rejection was reopened

§13 rejected extending ordinals to title/DOI because `hydrate_meta` is **4.1%**
of query latency — correct against a *latency* objective, and **the wrong
objective** for the consolidation goal doc 17 §13 set ("separate storage
databases 4 → 0"). The question is not "how much faster" but "can a 24.9 GB
SQLite database be deleted, and what does it cost". Reopened on that basis, per
this doc's standing rule that a rejected item needs *the number that changed* —
here the changed number is the objective function itself.

**Operator constraint (2026-08-03): consolidation must leave serving
performance IDENTICAL to mainline.** Not faster — *not slower*. That gate is
what decides between the designs below, and it disqualifies the smallest one.

### What actually has to be replaced

`docs(id INTEGER PRIMARY KEY, title, doi, year, type, is_oa, section)`.
`year/type/is_oa/section` are **already** flat ordinal columns (§12, 0.75 GB),
and `docs_other` is **empty — 0 rows, measured**, so the TEXT-overflow path
costs nothing. Deleting `meta.sqlite` therefore reduces to one question: what
does a flat, ordinal-indexed **title + DOI** store cost?

### Three designs, measured against the shipped SQLite path

50 ids per lookup (production `top_k`), 200 trials, arms interleaved and
order-randomised per trial, titles/DOIs compared byte-for-byte against
`meta.sqlite` on the same ids. Baseline reads the **staged** copy (local disk),
because per §14 measuring against the 9p copy would flatter every design ~50×.

| design | p50 (50 hits) | vs mainline | payload B/doc | replacement total | vs `meta.sqlite` |
|---|---|---|---|---|---|
| `sqlite_mainline` | 0.2324 ms | 1.00× | — | 24.91 GB | — |
| `raw` (u64 offsets, uncompressed mmap) | 0.1424 ms | 0.61× | 142.1 | 24.52 GB | **−0.39 GB** |
| `zstd_blocks` (32 KB, zstd-19, dict) | 2.7684 ms | **11.91× — FAILS** | 36.5 | 7.45 GB | −17.46 GB |
| **`zstd_perdoc` (per-record, shared dict)** | **0.1628 ms** | **0.70× ✓** | **76.7** | **14.69 GB** | **−10.22 GB** |

**PARITY PASS on all three** — every design returned title/DOI identical to
SQLite on every trial. Replacement total = design payload+locator + §12's
already-built filter columns (0.75 GB) and `wids` (1.20 GB).

**Verdict: `zstd_perdoc`.** It is *faster* than mainline (0.70×), so it clears
the no-regression gate outright, and it removes a 24.9 GB SQLite database for
14.69 GB of flat mmap'd artifacts — **−10.22 GB and one database gone**.

### Why the block design fails and the per-doc design does not

`zstd_blocks` is the shipped abstracts-v3 pattern, and it is the *wrong* shape
here. Its blocks hold **230 docs**; `_hydrate`'s 50 ids are scattered, so a
lookup decompresses ~230 records to read one, 50 times over. Abstracts can
afford that because a ~1.5 KB abstract amortises the block; a **142 B** record
cannot. `zstd_perdoc` is the abstracts **v1/v2** shape — one record decompressed
per lookup — and it keeps 62% of the block design's compression (76.7 vs
36.5 B/doc against 142.1 raw) at 17× its speed.

### The sampling bias that nearly got recorded as a result

The first two runs sampled **the first 1M rows by `id`**. `id` *is* the numeric
W-id, so that is the **oldest** OpenAlex works, and it measured **115.1 B/doc**.
Re-sampled as 20 contiguous windows spread across the whole id range, the true
figure is **142.1 B/doc — 23% larger**. Every projection from the head sample
was wrong, and the error was not uniform: it **inverted a verdict**. On the head
sample `raw` looked like a viable −4.44 GB; corrected, it saves **0.39 GB**,
which is nothing. Contiguity was still required (design B's layout depends on
it) — the fix was *many* contiguous windows, not a random scatter.

### NOT SETTLED — the latency numbers are an EXTRAPOLATION

1. **Everything above was measured on a ~1M-doc slice that fits in page
   cache.** At 150.4M the `zstd_perdoc` store is ~12.7 GB and 50 scattered
   lookups become 50 random page faults across it. **This doc's own history
   says that extrapolation is the dangerous one**: the same filter code measured
   4.15 ms at 208k docs and 400 ms at 150M, a **96× gap**, and §14 exists
   because a latency comparison was contaminated by exactly this class of
   effect. The *size* projection is the trustworthy half (§12 found build/size
   extrapolations linear and accurate); **the 0.70× is not yet a result.**
   The gate is: build the store at full 150.4M and re-run against the real
   `_hydrate`, staged, with the §14 arm discipline.
2. **The locator is now the biggest single line item.** `zstd_perdoc`'s u64
   offsets are 8 B/doc = **1.20 GB**, against a 76.7 B/doc payload — and it is
   *additive* to `wids`' identical 1.20 GB. Both are prime targets (delta +
   bit-packing; the offsets are monotonic by construction) before anything
   ships. Untouched here.
3. **`_hydrate` also fetches `section`**, which is already an ordinal column, so
   it is free — but the rewrite that reads title/DOI from the blob and `section`
   from the column has not been written, and byte-parity of the *whole*
   `_hydrate` output is a separate gate from the title/DOI parity measured here.
4. This measures nothing about **build time** for the store at 150.4M.

### What this does to the consolidation scorecard

Doc 17 §13 claimed 4 → 0. With C7 measured, the honest reachable target is:

| storage DB | route | status |
|---|---|---|
| `meta.sqlite` 24.9 GB | ordinal columns (§12, built) + `zstd_perdoc` title/DOI | **route KILLED (§19): −10.64 GB but 87× SLOWER at full 150.4M. §15's 0.70× was a 1M-doc page-cache artifact. Meta's SQLite baseline is a fast uncompressed-text read nothing compressed beats at scale** |
| `abstracts.sqlite` 13.47 GB | N5 flat blocks + ordinal locator + rehomed dicts | **DELETABLE (§18): served SQLite-free with the file gone, parity PASS, 1.19× p50, `_db is None`. −1.92 GB.** Reader + dicts shipped; only the build-time path is left (§18 #1). NOT §16's 5.53× — that was a cold-cache artifact (§17) |
| `dense/ids.json` 41 MB | ordinal *is* the usearch key | unbuilt; needs a dense index rebuild for a 41 MB prize |
| `dense/delta.sqlite` | "reserved high ordinal range" | **likely unreachable**: the warm cache mints addresses at query time, and this design's entire safety argument (§6 risk 1) is that addresses never move |

So **4 → 2 is the defensible target**, not 4 → 0. *(SUPERSEDED 2026-08-04 by
§20: the meta title/DOI store fails the speed gate at full scale, so meta.sqlite
stays and the reachable target is **4 → 3**, abstracts only.)*

---

## 16. C8 EXECUTED (2026-08-03): `abstracts.sqlite` is deletable — and **the locator was the cost, not the payload**

> **CONFIRMED AND EXTENDED 2026-08-17 (§23).** This section's two central
> filesystem/cache claims were re-tested against the **published** sidecar and
> both hold: (a) the payload move is worth ~2.9× on 9p and far less on local
> disk — measured 2.876× vs 1.091× warm, reproducing the 2.89×/1.21× split;
> (b) the cold/warm gap is real — 2.546× cold vs 1.091× warm on local disk. Two
> refinements: this section's cold explanation (SQLite's `docs` pages) is
> **local-disk-only** — on 9p the SQLite arm never warms *at all* while the
> mmap'd locator does, so the cold multiple is *smaller* than the warm one
> there; and the **consolidation arithmetic below is 1,408 B optimistic**
> (the three JSON stamps): the real saving is **1,897,229,898 B**.

- Code: `spike/meta_consolidation/14_c8_abstract_ordinal_locator.py`
- Results: `data/eval_results/c8_abs_locator_20260803_0649.json`
- Artifacts built (under `/var/tmp`, not shipped): flat sidecar 11.13 GB /
  1,062,917 blocks in **115 s**; ordinal locator 421.2 MB in **55 s**.

### What §9 left undone

§9 moved the abstract **payload** into a flat `blocks.bin` (2.89×) and
**deliberately kept the locator in SQLite**, because doc 17 §11 measured a
tantivy locator as a 27–54× regression. That is why §9's own audit note
reclassified N5 as a latency lever and *not* a space lever — and why
`abstracts.sqlite` survives even with the sidecar built: `docs` is still the
only way to find a document's bytes.

The locator is `docs(id TEXT PRIMARY KEY, b, off, n)` over **23,398,073 rows** —
a B-tree over variable-length TEXT W-ids, i.e. exactly the sparse-key search
§1 is about. tantivy lost that job because it is a search engine being asked to
do random access. **Flat arrays were never tried.**

### Result: three arms, byte-parity PASS on 20,000 ids each

50 ids per fetch, 150 trials, arms interleaved with order randomised per trial,
**all three stores on local disk** (`overlay`), so no arm gains a filesystem
advantage — the §14 discipline.

| arm | p50 | mean | p90 | p50 vs mainline |
|---|---|---|---|---|
| `mainline` (sqlite blocks + sqlite locator) | 5.092 ms | 5.362 | 6.488 | 1.00× |
| `flat_only` (flat blocks + sqlite locator) = **N5 as shipped** | 4.194 ms | 3.309 | 5.970 | 1.21× |
| **`flat_ordinal` (flat blocks + ordinal locator)** | **0.921 ms** | 2.561 | 5.450 | **5.53×** |

**`skipped_non_wid: 0`** — every id in the locator is a plain `W<digits>`, so
unlike `meta.sqlite`'s `docs_other` there is no overflow class and nothing falls
back. Locator dtypes were chosen from **measured** maxima: `b` u32
(max 1,517,006), `off` u16 (max 32,767), **`n` u32 — max 71,073, which
OVERFLOWS u16.** Assuming u16 for `n` because blocks target ~32 KB would have
silently truncated the longest abstracts.

### The finding: §9 optimised the wrong half

Moving the payload is worth **1.21×**. Replacing the locator on top of it is
worth a further **4.55×**. The locator — the part §9 deliberately did not
touch — is where the time actually was.

The saving is roughly a **constant ~4 ms** per fetch (the SQLite `docs` query
over 50 TEXT keys), which is why it reads as 5.53× at p50 and only ~1.19× at
p90: at p90 the tail is dominated by block decompression on `BLOCK_CACHE` misses,
which all three arms share and neither change addresses. **On the mean the
consolidated path is 2.09×.** Quote the mean or quote all three; the 5.53× alone
overstates it.

### §9's 2.89× does not transfer to production — a qualification, not an error

§9 built its flat store in `spike/meta_consolidation/work_n5`, which is **9p**,
from a source that is also 9p. That is a valid like-for-like comparison (unlike
§13's, which crossed filesystems — §14). But it is **filesystem-dependent**: on
9p, SQLite's B-tree block read costs several ~0.5 ms faults against the flat
store's single `pread`, so the flat store wins 2.89×. With both sides on local
disk — what the droplet has — the identical change measures **1.21×** here.
**The production-realisable payload win is ~1.21×, not 2.89×.** §9's number
stands as measured; it just does not describe the deployment target. The
`n5_flat_blocks_*.json` results file records no filesystem at all, which is why
this had to be reconstructed from the work directory.

### Consolidation arithmetic

| | |
|---|---|
| `abstracts.sqlite` today | **13.47 GB** |
| flat `blocks.bin` | 11.15 GB |
| ordinal locator (4 arrays, 18.00 B/doc) | 0.42 GB |
| **replacement total** | **11.57 GB** |
| **saved** | **1.90 GB, and one database removed** |

### NOT SETTLED

1. ~~**Nothing is wired.**~~ **DONE 2026-08-03 — §17.** The reader now ships in
   `abstracts.py` (`AbstractLocator` + the fail-closed identity gate,
   `AbstractStore.fetch` routes through it). Measured through the shipped
   `fetch()`: parity PASS, **no regression**. But see §17 — the 5.53× below did
   **not** survive to the shipped path in a warm-cache run.
2. **The `meta` table still has to go somewhere.** It holds the trained zstd
   dictionaries (~KB). Small, but `abstracts.sqlite` cannot actually be deleted
   until they live beside the blocks. Not counted in the arithmetic above.
3. **One section only.** `social_sciences__recent` is the only section with an
   `abstracts.sqlite` today, so this is the whole current abstract store — but a
   build that adds hot sections multiplies both artifacts.
4. **p90 is unimproved** (6.49 → 5.45, 1.19×). If tail latency is what matters,
   this change is close to neutral and the block cache is the target instead.
5. Measured on **local disk**; the shipped path would inherit whatever the host
   provides (§14).

---

## 17. C9 EXECUTED (2026-08-03): the locator reader SHIPS — and the 5.53× does **not** survive the shipped path

> **SUPERSEDED IN PART, 2026-08-17 (§23).** The **1.18× warm** below is a spike
> number — a `/var/tmp` store, fetched on `ORDER BY random()` ids. Measured
> against the **published** sidecar on **real ranked result sets**, local disk,
> fully warm, the same shipped path is **1.091×** (seed-41 confirmation
> 1.086×), and **2.546× cold**. This section's *direction* and its conclusion
> ("the durable win is −1.90 GB and a database removed, not speed") both stand;
> the multiple is smaller than stated here. §23 also records a negative this
> section's methodology hid: every arm here was warmed by a 20,000-id parity
> pass first, so it never saw that a **freshly started** process serving flat
> is **0.919×** sqlite until its 421 MB locator is resident.

- Code: `src/lib/thinclient/abstracts.py` — `AbstractLocator` (the fail-closed
  identity gate), `build_ordinal_locator`, `build_flat_sidecar` now stamps a
  `flat_store_id`, `AbstractStore.fetch` routes through the locator when present
  and verified.
- Tests: `scripts/tests/test_abstract_locator.py` (19, all pass) — parity, every
  fail-closed refusal, the miss contract, the encoder pin.
- Harness: `spike/meta_consolidation/15_c9_shipped_locator_reader.py`.
- Results: `data/eval_results/c9_locator_reader_20260803_2308.json` (+ `_2311`
  confirmation, seed 41).
- **Status: IMPLEMENTED + MEASURED through the shipped `fetch()`. Not built into
  `build_thinclient_index.py`; `abstracts.sqlite` not deletable yet (§2 dicts).**

### What was built

C8 (§16) measured a *harness* `OrdinalLocator` + `fetch_ordinal`. C9 makes it
shipped code: `AbstractStore.fetch()` now consults an `AbstractLocator`
(`searchsorted` over a sorted int64 W-id array + parallel `b/off/n` columns,
written into `<name>.flat/` beside `blocks.bin`) instead of the SQLite `docs`
B-tree, automatically, whenever the locator is present and its identity checks
out. Ids the locator cannot address (non-`W<digits>`) fall back to `docs`
(hazard 2). The reader is not a reimplementation the bench flatters — **every
arm below calls the shipped `fetch()`.**

### The identity gate (the reason this is a class, not four `np.load`s)

A locator addresses *into* `blocks.bin`; paired with a `blocks.bin` from a
different build it returns a real, plausible, **wrong** abstract with no error —
§6 risk 1 in the abstract store. So `build_flat_sidecar` mints a fresh
`flat_store_id` (uuid4, per build, never a content hash — §12's reasoning) into
`flat_store.json` *after* `blocks.bin` is complete; `build_ordinal_locator`
copies it into `locator.json` and refuses to build against a source whose stat
does not match the one those blocks recorded; `AbstractLocator.__init__` refuses
to load unless the two ids match and every column is full-length. It **fails
closed** (missing stamp on either side = refusal, no override flag), and a
mismatch **raises** out of `AbstractStore.__init__` rather than serving — there
is no lossless fallback for a wrong locator the way there is for a half-built
flat sidecar. `test_abstract_locator.py` asserts each refusal.

### Result: parity PASS, no regression — but **1.18×, not 5.53×**

50 ids/fetch, 200 trials, four arms interleaved and order-randomised per trial,
**all on local disk (`overlay`)**, every arm warmed, `mainline_ctrl` a second
identical SQLite store as the noise floor. 20,000-id byte-parity gate.

| arm (all via shipped `AbstractStore.fetch`) | p50 | mean | p90 | vs mainline |
|---|---|---|---|---|
| `mainline` (sqlite blocks + sqlite `docs`) | 3.547 ms | 3.607 | 3.781 | 1.00× |
| `flat_only` (flat blocks + sqlite `docs`) | 3.250 | 3.317 | 3.505 | 1.09× |
| **`flat_ordinal` (flat blocks + ordinal locator)** | **3.012** | **3.067** | **3.283** | **1.18×** |
| `mainline_ctrl` (noise floor) | 3.636 | 3.694 | 3.911 | 0.98× |

Parity **PASS on all four arms**, `skipped_non_wid = 0`. Noise floor **2.51%**
(run 2, seed 41: p50 **1.19×**, noise **0.34%** — the multiple is stable). The
shipped reader is **faster than mainline at p50, mean AND p90, and slower in no
percentile**, so it **clears the operator's no-regression gate outright** while
removing a database.

### Why the 5.53× evaporated — and what is actually invariant

§16's win decomposes, warm, into almost nothing. Payload move: 3.547 → 3.250 =
**0.30 ms**. Locator on top: 3.250 → 3.012 = **0.24 ms**. C8 measured the
locator saving at **~4 ms**; here it is **~0.24 ms**. The difference is the
SQLite `docs` B-tree query over 50 TEXT keys: **~4 ms when its pages are cold**
(C8's number), **~0.24 ms when they are hot** (this run warmed it with a
20,000-id parity pass first). Block *decompression* — which every arm shares and
the locator does not touch — dominates both, so once the `docs` query is warm
the locator's edge is a thin constant.

**So C8's 5.53× is not a shippable headline; it was a cold-cache artifact.**
What survives contact with the shipped path is the thing that actually matters
for consolidation: **byte-parity, no regression in any percentile, and
−1.90 GB with a database removed.** The honest latency claim is "neutral to
~1.18× faster, cache-state-dependent," not "5.53×." A droplet serving from local
disk with a warm working set will see the small number; the win is the removed
database, not the speed. (This is the §16 hedge — "roughly a constant few ms" —
landing on the small end of its own range.)

### Consolidation arithmetic (unchanged from §16, re-confirmed via shipped build)

`abstracts.sqlite` 13.47 GB → `blocks.bin` 11.15 GB + locator 0.421 GB (18.00
B/doc, `b` u32 / `off` u16 / `n` u32 from measured maxima) = **11.57 GB, −1.90
GB**. 23,398,073 rows, `skipped_non_wid = 0`.

### NOT SETTLED

1. ~~**`abstracts.sqlite` is still load-bearing.**~~ **DONE 2026-08-03 — §18.**
   Dicts rehomed (`dump_dict_sidecar`), `skipped_non_wid == 0` confirmed, and
   `AbstractStore` now serves in **SQLite-free mode** with the file deleted.
2. ~~**No build-time path**~~ **CLOSED 2026-08-17 — §22.** An operator build
   path exists (`scripts/build_flat_blocks.py`: staged publish + four-arm
   byte-parity gate + per-stage resume); **the production build was RUN
   2026-08-17, gate PASS, `social_sciences__recent` published**; and
   `build_thinclient_index.py --flat-sidecar` now drives that same
   `build_section` **inline** (after BUILD, before PACK, fail-closed, off by
   default), so a fresh build can emit the sidecar as a build output instead of
   needing an after-the-fact operator step. The inline path is
   **IMPLEMENTED, not exercised at production scale — tested synthetic-only**
   (§22 "still not settled" #2).
3. **One section.** `social_sciences__recent` only; a build that adds hot
   sections multiplies both artifacts.
4. **Shrinking the locator is untouched.** `off`/`n`/`b` and the u64-free `wids`
   are monotonic-ish and compressible (§15 #2); 0.421 GB is small but free.

---

## 18. C10 EXECUTED (2026-08-03): a section served with `abstracts.sqlite` **deleted**

- Code: `src/lib/thinclient/abstracts.py` — `dump_dict_sidecar`,
  `build_flat_sidecar` now rehomes dicts, `AbstractStore` SQLite-free mode
  (`_sqlite_free`, `_db is None`); `retriever.py` opens a store on the flat
  sidecar's presence, not the `.sqlite` file's.
- Tests: `scripts/tests/test_abstract_locator.py` (27, all pass) — SQLite-free
  serves byte-identical, drops unaddressable ids, requires a locator, refuses a
  mismatched dict sidecar, sqlite-vs-sidecar dict parity incl. a trained dict.
- Harness: `spike/meta_consolidation/16_c10_sqlite_free_serving.py`.
- Results: `data/eval_results/c10_sqlite_free_20260803_2329.json`.
- **Status: the store SERVES with `abstracts.sqlite` deleted. Not yet emitted by
  `build_thinclient_index.py` (§17 #2 is now the sole remaining blocker).**

### What was closed

§17 left the file "still load-bearing" for two reasons: the trained zstd dicts
were read from the `meta` table at open, and `AbstractStore.__init__` connected
to the `.sqlite` file unconditionally. C10 closes both. `dump_dict_sidecar`
copies the seven trained dicts (784 KB) into the flat sidecar as
`dicts.json` + raw `zdict_*` files, bound to the same `flat_store_id` as the
blocks (a wrong dict set decodes `blocks.bin` to garbage — zstd usually raises a
dict-id mismatch, but the identity gate refuses it outright). `AbstractStore`
gains a **SQLite-free mode**: when the `.sqlite` file is absent and a
`dicts.json` sidecar is present it holds **no SQLite connection at all** —
blocks from `blocks.bin`, block index from `loc_*.npy`, dicts from the sidecar.
The locator is *mandatory* there (no `docs` table means no other way to resolve
an address) and unaddressable ids have no fallback, which is exactly why
deletion is gated on `skipped_non_wid == 0`.

### Result: byte-parity PASS with the file gone, no regression

`social_sciences__recent`, 50 ids/fetch, 200 trials, four arms interleaved and
order-randomised, all on local disk (`overlay`), warmed, 20,000-id parity gate.
`sqlite_free` is opened on a directory holding **only** the flat sidecar — no
`abstracts.sqlite`.

| arm | p50 | mean | p90 | vs mainline |
|---|---|---|---|---|
| `mainline` (sqlite blocks + sqlite `docs`) | 3.512 ms | 3.644 | 4.119 | 1.00× |
| `flat_ordinal` (flat + locator, sqlite present) | 2.952 | 3.053 | 3.360 | 1.19× |
| **`sqlite_free` (flat + locator + dicts, NO sqlite)** | **2.948** | 3.034 | 3.440 | **1.19×** |
| `mainline_ctrl` (noise floor) | 3.536 | 3.661 | 4.122 | 0.99× |

Parity **PASS on all four**, `_db is None` on the free arm **asserted**, noise
floor **0.69%**. The SQLite-free path is indistinguishable from the
sqlite-present locator path (2.948 vs 2.952) and holds the no-regression gate —
consistent with §17: removing the connection changes nothing about the read
path, which was already flat blocks + ordinal locator.

### The file is now deletable: −1.92 GB, 13.47 → 0

| | size |
|---|---|
| `abstracts.sqlite` today | 13.47 GB |
| `blocks.bin` | 11.13 GB |
| ordinal locator (`loc_*.npy`) | 0.421 GB |
| dicts (`dicts.json` + 7 × `zdict_*`) | 0.0008 GB |
| **replacement total** | **11.55 GB** |
| **saved, and the SQLite database GONE** | **1.92 GB** |

This is the whole `abstracts.sqlite` for the only section that has one, so for
the current index the abstract database drops **4 → 3** on the scorecard (§15).

### NOT SETTLED

1. **Build-time path (the last mile).** Deletion is still an after-the-fact step
   on a built index; `build_thinclient_index.py` must emit the flat sidecar +
   locator + dicts and (optionally) drop the `.sqlite`. Until then this ships as
   an operator/repack action, not a build output.
2. **The dicts sidecar leans on zstd's own dict-id check** for the
   plain-codec buckets (a below-bar store trains none); the identity gate is the
   belt to that suspenders. Both tested, but note the two layers.
3. **One section**, as above. Nothing measured about a multi-hot-section build.

---

## 19. C11 EXECUTED (2026-08-04): the `meta.sqlite` title/DOI route is **−10.64 GB but 87× SLOWER at full scale** — the route is DEAD on the speed gate

- Code: `spike/meta_consolidation/17_c11_meta_store_fullscale.py`
- Results: `data/eval_results/c11_meta_store_20260804_0031.json`
- **Status: the C7 §15 route is KILLED by its own gate. Nothing to ship. This is
  the 96× extrapolation trap §15 warned about, now measured.**

### What was built and measured

§15's NOT-SETTLED #1 demanded the one thing that would settle the route: build
the `zstd_perdoc` title/DOI store at the **full 150.4M** (not a 1M sample) and
re-measure latency, staged, because "the 0.70× is not yet a result." So C11
streamed the whole store — 150,413,098 records, `title\x00doi` per-doc zstd-19
against one trained dict, indexed by the global ordinal (offsets[ordinal]),
verifying `docs.id == wids[ordinal]` row-by-row as it went (2,981 s, 50,453
docs/s). Then it measured `meta_store` vs the **staged** `meta.sqlite` on the
same ids, interleaved, warmed, §14 discipline.

### The result: the size held, the speed collapsed

| arm | p50 | mean | p90 | vs mainline |
|---|---|---|---|---|
| `sqlite_mainline` (staged meta.sqlite) | **0.331 ms** | 0.376 | 0.554 | 1.00× |
| **`meta_store` (perdoc zstd, ordinal-indexed)** | **28.74 ms** | 37.73 | 87.06 | **0.012× — 87× SLOWER** |
| `sqlite_ctrl` (noise floor) | 0.296 | 0.334 | 0.551 | 1.12× |

Parity **PASS** (byte-identical title/DOI, NULL sentinel intact). Size **held
exactly as projected**: 12.32 GB store (73.9 B/doc) + 0.75 filter + 1.20 wids =
14.27 GB, **−10.64 GB** vs 24.91 GB. **Size extrapolates; latency does not** —
§15's 0.70× was a 1M-doc, page-cache-resident artifact, and at 150.4M the store
is a **87× regression**. The operator gate is no-regression; this fails it by
almost two orders of magnitude. **The route is dead as designed.**

### Why abstracts consolidated and meta cannot — the load-bearing asymmetry

This is the important part, because it is not obvious and it is general:

- **The abstract SQLite path is decompression-bound and SLOW** (§18: 3.5 ms
  mainline). A fetch decompresses a 32 KB zstd block per id. A flat ordinal
  store does the *same* decompression, so it matches/beats SQLite — the win was
  never latency, it was removing the database at par.
- **The meta SQLite path is a cheap uncompressed TEXT read and FAST** (0.331 ms
  warm). SQLite reads `title`/`doi` bytes straight from a page-cache-resident
  B-tree, no decompression. **Nothing compressed can beat that at 150M scale:**
  the 12.3 GB perdoc store is *not* resident, so 50 scattered ids become 50 cold
  random page-faults + 50 zstd-dict decompressions ≈ 28 ms, against SQLite's 50
  warm B-tree reads ≈ 0.33 ms.

So the consolidation lever that worked for abstracts (move payload + ordinal
locator) **does not transfer to meta**, because the baseline it must not
regress is ~10× cheaper. The two stores looked like the same problem; they are
not. A fast, uncompressed baseline is the hard one to beat.

### What (if anything) is left for meta

The only C7 design that avoids decompression is **`raw`** (uncompressed mmap +
u64 offsets), and §15 measured it at **−0.39 GB** — i.e. it saves *nothing*
(the 24.9 GB is mostly the title/DOI text, and uncompressed it is ~the same
size). So the meta route faces a **size/speed conflict abstracts never had**:
save space (compress) → lose the speed gate; hold the speed gate (raw) → save
nothing. Whether an off-the-shelf random-access columnar store (Lance
`take(ordinal)`, Vortex) can break that conflict at full scale is the open
question C12 tests — but the burden of proof is now high, and the honest
default is that **`meta.sqlite` may simply not be consolidatable under the
no-regression gate.** The −10.64 GB is real; it is just not free, and the price
is 87×.

### NOT SETTLED

1. ~~**C12 (queued): Lance `take` vs raw vs perdoc vs SQLite.**~~ **DONE — §20.
   Nothing beats warm SQLite; meta consolidation stops here.**
2. **The filter columns still stand.** year/type/is_oa/section as ordinal
   columns (§12) are a real, separate −0.75-GB-for-1.96-GB-resident lever for
   the *filter* stage; C11 says nothing against them. It is only the title/DOI
   *hydration* store that fails.

---

## 20. C12 EXECUTED (2026-08-04): the meta bake-off — **no store holds the speed gate; meta.sqlite stays**

- Code: `spike/meta_consolidation/18_c12_lance_take_bakeoff.py` (run under
  `.venv-lance`)
- Results: `data/eval_results/c12_lance_bakeoff_20260804_0046.json`
- **Status: meta title/DOI consolidation is CLOSED. The reachable target is
  4 → 3 (abstracts only), NOT the 4 → 2 the C7/C8 pairing implied.**

### The bake-off §19 queued, run at full 150.4M

A single streaming pass (442 s) built two new stores from staged `meta.sqlite`
in ordinal order (verifying `docs.id == wids[ordinal]`) — an **uncompressed
`raw`** blob + u64 offsets, and a **Lance dataset** (title/doi columns) — and
reused C11's perdoc store. Five arms, all addressed by ordinal, interleaved,
warmed, all on local disk. The point was Lance's **`take([ordinal])`**: doc 17's
C5 rejected Lance on its BTREE *scalar index* (a searcher, 255 ms) and **never
measured positional take**, which is Lance's real random-access path and is
exactly ordinal addressing. That is the number that changed — so it was measured.

| arm | p50 | mean | p90 | vs mainline | store | saves |
|---|---|---|---|---|---|---|
| `sqlite_mainline` | **0.302 ms** | 1.712 | 4.035 | 1.00× | — | — |
| `raw_mmap` (uncompressed) | 0.695 | 2.831 | 7.454 | **0.43× (2.3× slower)** | 17.68 GB | 5.28 GB |
| `perdoc_zstd` (C11) | 2.178 | 3.033 | 5.686 | 0.14× (7.2× slower) | 12.32 GB | 10.64 GB |
| **`lance_take`** | **6.371** | 6.430 | 7.217 | **0.05× (21× slower)** | **10.80 GB** | 12.16 GB |
| `sqlite_ctrl` (noise) | 0.289 | 1.670 | 3.975 | 1.04× | — | — |

**Quality gate PASS on all arms** (byte-parity of title/doi incl. the NULL
sentinel, 20,000 ids). **Speed gate FAILED by all three** — SQLite wins every
percentile. Noise floor 4.12%.

### What the numbers say

- **Lance `take` is the *slowest* on p50 (21×) despite compressing the *best*.**
  Its columnar string encoding beat zstd-19 per-doc (10.80 vs 12.32 GB, saving
  12.16 GB), but a 50-row scattered `take` pays fixed per-call overhead
  (fragment lookup + columnar decode + Arrow Table materialization) that dwarfs
  the payoff. Lance's "2000× random access vs Parquet" is a throughput/scan
  claim; it does not describe a 50-id point-gather. **The number that changed
  changed the wrong way** — addressed by `take`, Lance is worse than the
  hand-rolled store, not better. C5's rejection stands, now on both axes.
- **`raw` (uncompressed) is closest on p50 (2.3×) and still a regression**, is
  worse than SQLite on mean and p90, and saves only 5.28 GB — the least. It
  confirms §15's point: uncompressed buys speed you still can't match and saves
  almost nothing.
- **The size/speed conflict is total.** Across uncompressed, per-doc-zstd, and
  off-the-shelf columnar, *every* store that saves space regresses latency, and
  the one that comes closest on latency saves least. There is no point on this
  frontier that clears the no-regression gate.

### The verdict, and what it does to the scorecard

**`meta.sqlite`'s title/DOI is not consolidatable under the operator's
no-regression constraint.** The meta SQLite path is a warm, uncompressed-text
B-tree read (~0.3 ms); nothing that compresses (decode cost) or grows
(page-fault cost) beats it at 150M. This is the mirror image of abstracts (§18),
which consolidated *because* its SQLite path was slow. So:

| DB | outcome |
|---|---|
| `abstracts.sqlite` | **removed** (§18, −1.92 GB, SQLite-free) |
| `meta.sqlite` | **stays** — title/DOI hydration cannot beat warm SQLite (C11/§19, C12/§20). Filter columns (§12) remain a separate resident-RAM lever, but do not remove the DB |
| `dense/ids.json`, `dense/delta.sqlite` | unbuilt / likely-unreachable, unchanged |

**Reachable consolidation is 4 → 3, not 4 → 2.** The −10.64 GB was real and the
route was worth chasing to a full-scale number; the gate is what stops it, and
"nothing here clears the bar" is the correct answer. Lance stays a documented
alternative, not a plan — and now on the `take` axis too, not just the scalar
index. *(Vortex is no longer only "documented" — §21 measured it.)*

---

## 21. C13 EXECUTED (2026-08-04): Vortex — **best compression of all, worst latency of all.** Meta stays closed.

- Code: `spike/meta_consolidation/19_c13_vortex_take_bakeoff.py` (run under
  `.venv-lance`, `vortex-data` 0.83.0)
- Results: `data/eval_results/c13_vortex_bakeoff_20260804_0159.json`
- **Status: the second and last credible columnar store, measured. Same verdict
  as Lance — regresses the speed gate. Meta consolidation is comprehensively
  closed.**

### The test

Vortex (spiraldb, LF AI & Data) is the other random-access columnar format, and
it pitches hydration-grade random access — so it got C12's exact bake-off. A
Vortex file of title/doi was built at the full 150.4M in ordinal order
(streaming via a PyArrow `RecordBatchReader`, verifying `id == wids[ordinal]`,
302k docs/s, 550 s), then measured against staged `meta.sqlite`, reusing C12's
raw + Lance stores as arms. **Quirk the reader must handle:**
`VortexFile.scan(indices=)` is a *monotonic selection*, not an ordered gather —
so the reader sorts the 50 ordinals, scans, and reindexes to request order, and
that cost is counted.

| arm | p50 | mean | p90 | vs mainline | store | saves |
|---|---|---|---|---|---|---|
| `sqlite_mainline` | **0.449 ms** | 12.22 | 36.05 | 1.00× | — | — |
| `lance_take` | 6.89 | 7.02 | 8.04 | 0.065× (15×) | 10.80 GB | 12.16 GB |
| `raw_mmap` | 9.10 | 14.28 | 36.04 | 0.049× (20×) | 17.68 GB | 5.28 GB |
| **`vortex_take`** | **12.14** | 13.07 | 18.30 | **0.037× (27×)** | **9.31 GB** | **13.65 GB** |
| `sqlite_ctrl` (noise) | 0.367 | 11.35 | 40.89 | 1.22× | — | — |

Quality gate **PASS** (byte-parity incl. NULL, 20,000 ids).

### The finding, and a measurement caveat

**Vortex compressed the best of everything tested — 9.31 GB, saving 13.65 GB —
and was the *slowest* arm, 27× slower than SQLite on p50.** This is C12's
lesson taken to its limit: across raw (17.68 GB / 20×), perdoc-zstd (12.32 GB /
7×), Lance (10.80 GB / 15×) and now Vortex (9.31 GB / 27×), **better compression
buys a bigger decode cost per gather, and none come within an order of magnitude
of a warm uncompressed B-tree read.** Vortex's FSST/cascade encoding is superb
for size and wrong for a 50-id scattered point-gather.

*Caveat, stated plainly:* this run's noise floor was **18.28%** and the SQLite
baseline's mean/p90 were inflated (12 / 36 ms vs C12's 1.7 / 4.0) — five
multi-GB stores now share the page cache, so the box was under pressure. **The
p50 verdict is robust anyway** — 27× is an order of magnitude past the noise,
and a clean baseline (C11's 0.33 ms) would make the ratio *worse*, not better.
The size figures are unaffected. A more optimised Vortex reader might shave the
per-scan setup, but it cannot close a 27× gap to sub-millisecond.

### Verdict

Both credible off-the-shelf columnar stores are now measured on the right axis
(positional random gather) and both regress. **There is no consolidating store —
hand-rolled or off-the-shelf, compressed or raw — that holds meta's
no-regression gate.** The frontier is exhausted: the more you save, the slower
you get. `meta.sqlite` stays; reachable consolidation is **4 → 3** (abstracts).
Do not reopen without a design that byte-matches AND holds p50 ≤ ~0.3 ms at full
scale — C11–C13 map the whole size/speed frontier and none of it does.

**Synthesis + the one untested design:**
`spike/meta_consolidation/META_CONSOLIDATION_FEASIBILITY.md` aggregates C1–C13,
the five root causes, per-store specs, and the **C14 bespoke proposal** (an FSST
row-store with a *compiled* gather — the only combination the frontier points at
but no test tried). DESIGN ONLY, unmeasured; ~1-in-3 odds on the strict gate.

---

## 22. The production BUILD path (2026-08-17): BUILT AND RUN — the section serves flat

§17's not-settled #2 — "no build-time path" — was the last thing standing
between the shipped flat-store reader and a section that actually serves flat.
Every builder shipped on 2026-08-03; nothing called them, and no `.flat/`
directory existed under `data/thinclient_index/`.

- Code: `scripts/build_flat_blocks.py` (`plan` / `build` / `verify`)
- Tests: `scripts/tests/test_flat_block_builder.py` — **22**, all pass
  2026-08-17 (12 build-path cases + the 6 torn-published-index cases added with
  the `_open_flat` fix in hazard 1 below + 4 for the inline
  `build_thinclient_index.py --flat-sidecar` path, §22 "still not settled" #2)
- Results (SYNTHETIC scale, 2026-08-17):
  `data/eval_results/flat_build_synthetic20k_20260817.json` — a 20,000-doc v3
  store built through the shipped writer, 84 blocks; gate **PASS** on 13,535
  unique sampled ids across all three non-oracle arms and on 84/84 blocks
  byte-for-byte; `sqlite_deletable: false` (the fixture deliberately contains
  two ids the ordinal locator cannot address, so the guard is exercised).
- Docs: `docs/THIN_CLIENT_SWAP.md` §"Building it"

> **SERVING EFFICACY MEASURED 2026-08-17 — §23.** The "separate future run"
> this section calls for below has been done, against this directory, in the
> serving path. Read §23 before quoting any latency figure from §16/§17 for the
> published sidecar: **local disk, fully warm, real ranked result sets →
> 1.091×, not §17's 1.18×**; 9p → 2.876×, which is a filesystem artifact;
> cold → 2.546× on local disk. Byte-parity PASS. Bytes here are 1,408 B high.

**STATUS: PRODUCTION BUILD RUN 2026-08-17 — GATE PASS, PUBLISHED.**
`data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite.flat/`
now exists and the section serves flat (see "The production run" below for the
measured wall time, bytes and gate verdict). What the *tests* measure is still
the build path's behaviour on synthetic 1,200-doc v3 stores built through the
shipped `AbstractStoreWriter`. **SERVING-LATENCY EFFICACY OF THE PUBLISHED
SIDECAR IS MEASURED — §23, 2026-08-17.** It is no longer §16/§17/§18's spike
numbers carried forward: measured against *this* directory, local disk, fully
warm, on real ranked result sets, the shipped path is **1.091×** (not
1.18–1.19×), **2.546× cold**, **2.876× on this container's 9p mount** (a
filesystem artifact), byte-parity PASS, **−1,897,229,898 B**.

### What it does beyond calling the three builders in a row

**1. Staged publish (a real hazard, not defensive decoration).** `AbstractStore`
attaches a sidecar on the *existence* of `abstracts.sqlite.flat/`, and
`_open_flat` used to catch only `OSError` — the case where `blocks.bin` is
missing. A **truncated `block_*.npy` raises `ValueError` out of `np.load`**,
which nothing caught, so a build killed midway through `np.save` would leave a
directory that takes the section down on next open instead of falling back to
v3.

> **FIXED 2026-08-17** (`src/lib/thinclient/abstracts.py`, `_open_flat`). The
> failure modes were measured rather than assumed: truncated data section →
> `ValueError("mmap length is greater than file size")`; zero-byte file →
> `EOFError("No data left in file")`; header-corrupt file → `ValueError`
> (pickled-data path). The except clause is now
> `(OSError, ValueError, EOFError)`, so a torn *published* index degrades to
> the v3 `blocks` table losslessly instead of taking the section down. In
> SQLite-free mode there is nothing to fall back to, so the explicit
> `RuntimeError("… no payloads left …")` still fires. Six regression cases
> (3 tear shapes × {fallback, sqlite-free}) added to
> `scripts/tests/test_flat_block_builder.py`; all 6 fail on the pre-fix code.
> Suite: 45 pass (was 39). Staging below remains the first line of defence —
> the fix covers tears that happen *after* publication, which staging cannot.

The script therefore builds into `abstracts.sqlite.flat.building/` and
`os.rename`s it into place only after the gate passes: the served name never
exists in a half-populated state. (`build_flat_sidecar`'s own
`blocks.bin.partial` rename covers only the payload file, not the arrays.)

**2. A four-arm byte-parity gate, before publishing.** Default 20,000 ids — the
gate size §9/§16/§17 used. All four readers are the *shipped* `AbstractStore`,
constructed over symlink views of the same bytes, so no read path is
re-implemented in the verifier:

| arm | reads | compared against |
|---|---|---|
| `v3` | sqlite `blocks` + sqlite `docs` | — (the oracle) |
| `flat_docs` | `blocks.bin` + sqlite `docs` | `v3`, byte-identical |
| `flat_ordinal` | `blocks.bin` + `loc_*.npy` | `v3`, byte-identical |
| `sqlite_free` | sidecar only, no `.sqlite` at all | `v3` on addressable ids |

Plus a container-level check independent of the codec: random blocks `pread`
out of `blocks.bin` must equal the source `z` BLOB **byte for byte**, with the
same dict id. Both gates are shown by test to *catch* corruption — a single
flipped payload byte and a shifted block offset each fail them.

**3. Sampling discipline.** Ids are drawn as contiguous windows spread across
the whole rowid range and de-duplicated, never a head slice: §16 records a
head-sampled measurement that was 23% wrong *and inverted a verdict*, because
`id` is the numeric W-id and its head is the oldest works.

**4. Per-stage resume.** flat → dicts → locator. A stage counts as done only if
the stamp its builder writes *last* is present, its `flat_store_id` matches the
blocks, **and every array's length matches the stamp** — the §12 failure (one
column short, tail addressing whatever the shorter array holds) is checked for
explicitly, not assumed away. Sub-stage checkpointing was deliberately not
built: each stage is one sequential pass of ~2–15 min per section, so it would
buy minutes and cost a correctness surface.

**5. Additive only.** Source opened read-only; refuses to overwrite a published
sidecar; refuses to reuse a staging directory containing any file it did not
write; verification views are symlinks in a temp dir outside the index tree.
Revert stays `rm -rf <section>/abstracts.sqlite.flat`.

### The production run — RUN 2026-08-17, GATE PASS, PUBLISHED

**MEASURED 2026-08-17** (machine idle, the 150M parity eval having finished).
Command exactly as recorded below; results
`data/eval_results/flat_build_social_sciences__recent_20260817_0118.json` and
`data/eval_results/flat_verify_social_sciences__recent_20260817_0121.json`.

| stage | measured | prior estimate |
|---|---|---|
| flat (`blocks.bin`) | **823.9 s** (13.7 min), 1,062,917 blocks / 1,517,007 slots | ~15 min on 9p ✓ |
| dicts | rehomed inside the flat stage (7 dicts, 0.8 MB); the explicit stage then SKIPped | unmeasured |
| locator | **132.0 s**, 23,398,073 rows, `skipped_non_wid: 0` | unmeasured |
| 4-arm read gate + 500-block byte check | **~3.6 min** (reads 13.0 s, the block check the rest) | 46 s in the N5 spike (much smaller store) |
| **build total (wall)** | **19 min 33 s** | ~15 min + unmeasured stages |
| `verify` re-run (independent) | **2 min 49 s**, PASS | — |

**Bytes (measured, not estimated):** `blocks.bin` 11,131,511,857 B + block
index 19,721,475 B + locator 421,165,826 B + dicts 802,816 B =
**11,573,201,974 B (11.57 GB)** — *below* the 12.12 GB estimate. Against the
13,470,433,280 B sqlite that is **−1,897,231,306 B (−1.90 GB)**, which
reproduces §16/§17's −1.92 GB claim at production scale. Free space on the 9p
index mount before the build: 333.0 GB.

**Gate verdict: PASS on every arm.** `flat_docs`, `flat_ordinal` and
`sqlite_free` each returned all sampled abstracts byte-identical to the v3
SQLite oracle (0 mismatched, 0 missing), and 500 random blocks `pread` out of
`blocks.bin` equalled the source `z` BLOBs. `locator_attached: true`,
`sqlite_free_has_no_db: true`, `sqlite_deletable: true` (0 non-W ids and the
dicts rehomed) — deleting `abstracts.sqlite` is now *legal*, and remains a
separate explicit operator step that has NOT been taken.

**Gate coverage caveat (measured, honest):** `ids_checked` is **14,000**, not
the nominal 20,000. `sample_ids` draws 20 contiguous rowid windows of 1,000;
this table's rowids run to 33,429,674 for 23,398,073 rows, with a ~4.6 M-wide
gap above 23.4 M, so several random starts landing in the gap snap forward to
the *same* run and dedupe away. The gate is therefore 14,000 distinct ids per
arm (deterministic at seed 17 — the `verify` re-run drew the same 14,000). Not
a failure, but the sampler over-reports its own nominal coverage on a table
with rowid gaps.

**Reader hardening shipped in the same session** — see hazard 1 above; a torn
*published* index now degrades to the v3 blocks table instead of raising.

`plan` (stat-only, safe to run any time) reported one section before the build —
it is the only one with an `abstracts.sqlite`:

```
section                              sqlite  sidecar est  flat est (9p)  state
social_sciences__recent              13.47G       12.12G         14.6m  not built
```

```bash
.venv/bin/python3 scripts/build_flat_blocks.py build --section social_sciences__recent
```

Runtime estimate from the two MEASURED rates for this exact source (878 s on the
9p index mount 2026-08-02; 114.9 s on local disk 2026-08-03): **~15 min for the
flat stage on the 9p mount, ~2 min on local disk.** Locator and dict stages at
this scale are *unmeasured* (`bytes_per_doc` 18.0 is measured; wall time is
not); the 20,000-id gate took 46 s in the N5 spike. Disk: **+12.1 GB estimated**
(measured components: blocks.bin 11.13 GB + locator 0.421 GB + dicts 0.8 MB),
**additive** on top of the 13.47 GB sqlite until an operator deletes it — and
deletion is legal only when the report says `sqlite_deletable: true`
(`skipped_non_wid == 0` and the dicts rehomed), which §17 measured true for this
section (23,398,073 rows, 0 skipped).

### Still not settled

1. ~~**The production build has not been run.**~~ ~~**Its serving efficacy is
   unmeasured.**~~ **BOTH SETTLED 2026-08-17.** The build ran, gate PASS,
   published (above); and **§23 measured the published directory in the serving
   path.** Byte-parity PASS (14,000-id windowed gate + every timed trial +
   cross-process digests, 0 mismatches). Latency, real ranked result sets,
   300 interleaved trials per arm: **9p 2.876× warm** (45.679 → 15.886 ms p50,
   p95 3.84×) — which reproduces §9/§16's 9p figure and is *not* production-
   realisable; **local disk 2.546× cold and 1.091× warm**, so §17's 1.18× does
   **not** reproduce against the serving path's own inputs. Bytes re-stat'd:
   −1,897,229,898 B (§22's figure was 1,408 B high — the three JSON stamps).
   New negative, previously unrecorded: **a freshly started process serving
   flat is 0.919× sqlite until its 421 MB locator is resident.** Serving
   default unchanged.
2. ~~**`build_thinclient_index.py` still does not emit the sidecar inline.**~~
   **SETTLED 2026-08-17** — `build_thinclient_index.py --flat-sidecar` adds a
   FLAT phase that runs after BUILD and **before PACK** (packing removes a cold
   section's live directory, and the sidecar is derived from the on-disk
   `abstracts.sqlite`). For every section that has an `abstracts.sqlite` it
   calls this script's own `build_section` — the same staged build, the same
   `flat_store_id` identity checks, the same four-arm byte-parity gate plus
   block `pread` check, the same atomic publish. Nothing is re-implemented.
   **Fail-closed:** a section whose gate does not PASS keeps its staging
   directory, is never published, and the phase raises `RuntimeError` naming
   it, so a build cannot exit 0 having emitted an unverified sidecar. Progress
   is checkpointed in `build_status.json` (`flat_sections`, `flat_info` with
   the per-section report path), and an already-published sidecar is filtered
   out rather than tripping the sub-script's overwrite refusal, so a resumed
   build is safe. Gate size is tunable: `--flat-verify-ids` (default 20,000,
   the doc 18 gate), `--flat-verify-blocks` (default 500).
   **Off by default — without the flag the build's output is unchanged.**
   **IMPLEMENTED, not exercised at production scale — tested synthetic-only**
   (`scripts/tests/test_flat_block_builder.py`, 18 → **22 tests, all pass
   2026-08-17**; the 4 new ones cover the gated-off default, gated-on emission
   + serving through the shipped reader, gate-failure abort, and a rerun
   leaving a published sidecar untouched). No 150M build was re-run for this —
   the published `social_sciences__recent` sidecar remains the one the
   standalone script built (above), and this inline path has never processed a
   production-scale store.
3. **Multi-section behaviour is untested at scale** because only one section
   has abstracts today; `plan` orders smallest-first for when that changes.

---

## 23. J1 EXECUTED (2026-08-17): the PUBLISHED sidecar's SERVING efficacy — **2.88× on 9p, 2.55× cold on local disk, 1.09× warm on local disk**, parity PASS

- Harness: `scripts/seismic_testbed/j1_flat_sidecar_serving_ab.py` +
  `j1_flat_sidecar_serving_ab.sh` (six phases: collect → cold → warm → verdict
  → stage-to-local-disk → the same three again)
- **Pre-registered in commit `2e56b02`, before any arm was run.** Seven bars
  live in an in-source `PREREG` block and are copied verbatim into every
  results file, so the pre-registration's timestamp is git history rather than
  the harness's own say-so.
- Results (`data/eval_results/`): `j1_flat_idsets_20260817.json`;
  `j1_flat_serving_cold_{sqlite,flat}_rep{1,2}_20260817.json` and their
  `_local_` twins; `j1_flat_serving_warm_20260817.json`,
  `..._warm_local_20260817.json`, `..._warm_local_seed41_20260817.json`,
  `..._warm_local_rerun17_20260817.json`; verdicts
  `j1_flat_serving_verdict_20260817.json` (9p),
  `..._verdict_local_20260817.json` (local, first touch),
  `..._verdict_local_warmed_20260817.json` (local, fully warm).

### What §22 left open, and why §17's number could not answer it

§22 published the sidecar and then quoted §16/§17's **1.18–1.19× warm** and
**−1.90 GB** for it. Those are *spike* numbers: stores built under `/var/tmp`,
fetched by a spike harness, on **random** ids (`SELECT id FROM docs ORDER BY
random()`). Production fetches the **ranked top-k of a real query** —
`_hydrate()` hands `[d for d, _ in ranked]` to `fetch_abstracts()` — and ranked
ids are co-topical, so they cluster in the store's script buckets and therefore
in its blocks. A random-id benchmark measures a different locality regime than
the serving path. Nothing had ever been measured against the published
directory.

### The arms — and the finding that `AbstractStore` has no env gate

`AbstractStore` serves flat **iff `<name>.flat/` `is_dir()`**. There is no
env var, no manifest flag, nothing to switch. The arms are therefore built the
way this repo already builds them — **symlink views in a temp directory outside
the index tree**, the same mechanism `build_flat_blocks.py`'s own gate and
§17's harness use — so **no published file was moved, renamed or written**:

| arm | view | wiring asserted before any timing |
|---|---|---|
| `sqlite` | `abstracts.sqlite` → published, **no `.flat` sibling** | `_flat is None`, `_locator is None` |
| `flat` | `abstracts.sqlite` → published, `abstracts.sqlite.flat` → published `.flat/` | `_flat` and `_locator` both attached |
| `sqlite_ctrl` | a second `sqlite` view | the per-run noise floor (§14) |

`journal_mode=delete` (verified), so opening the db read-write — exactly as
`retriever.py:627` does — writes nothing. `find … -newermt` over the section
after the run confirmed no file changed.

**Inputs are real, and federated.** `collect` ran the shipped `_bm25f_leg` over
the 120 `data/sfu_eval_queries.json` queries at `top_k=100`. All **10** sections
are live, so the ranked sets span the whole index and only **46.9%** of ranked
ids resolve in this store — the natural miss mix, not a contrivance. A
`synthetic_miss50` regime (half of each list replaced by well-formed W-ids past
the store's maximum) stresses the miss path further, because the arms are not
symmetric on a miss: a locator miss pays `searchsorted` **and then** the same
`docs` probe as fallback.

### The cold mechanism this container cannot run — and what replaced it

`sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches'`, the f4/serve_footprint_bench
precedent, **cannot run here**: sudo succeeds and the write still fails,
`cannot create /proc/sys/vm/drop_caches: Read-only file system` (WSL2). The
harness uses `posix_fadvise(POSIX_FADV_DONTNEED)` over every file of the
section instead and **records the measured `Cached:` delta**, so a cold claim
is judged on whether eviction happened rather than on the call returning 0. It
evicts *both* arms' files on every run, so arm order cannot leave one warmer.
Measured: **24.44 GB freed** on the first local-disk eviction (the mechanism is
real), and **0 B freed on 9p** — see the 9p page-cache finding below.

### Result 1 — this container (9p), `real_top50`, 300 interleaved trials

| arm | p50 | p95 | p99 | mean | per-doc p50 | vs `sqlite` |
|---|---|---|---|---|---|---|
| `sqlite` | 45.679 ms | 67.729 | 73.934 | 45.401 | 2.038 ms | 1.00× |
| **`flat`** | **15.886** | **17.629** | 19.499 | 15.379 | **0.696** | **2.876×** (p95 **3.84×**) |
| `sqlite_ctrl` | 45.596 | 67.291 | 74.010 | 45.460 | 2.037 | 0.999× |

Noise floor **0.56%**. Reproduced across two independent driver runs (2.857× and
2.876×). Other regimes: `real_top100` **2.965×**, `synthetic_miss50_top50`
**2.856×**, `synthetic_miss50_top100` **2.892×**.

**This reproduces §9/§16's 9p figure (2.82–2.89×) at production scale, on the
published bytes, with real ranked result sets** — and it is exactly the number
§16 warned is *not* production-realisable.

### Result 2 — LOCAL DISK (overlay), the same published bytes

The published section was byte-copied to overlay (`stage`, 19/19 files, 258 s,
identity gate re-checked on the copy) and the identical arms re-run.

| state | `sqlite` p50 | `flat` p50 | multiple |
|---|---|---|---|
| **cold** (fadvise-evicted, fresh process, 2 reps) | 27.645 / 31.744 ms | **11.033 / 12.296** | **2.546×** |
| **warm, first touch after eviction** (seed 17) | 1.907 | 2.075 | **0.919× — a REGRESSION** *(2026-08-18: shown to be a run-ordering cache artifact — symmetric-eviction first touch reads 1.00–1.10×; see §23 "The re-measurement RAN")* |
| **warm, fully warmed** (seed 17 rerun) | 1.726 | 1.581 | 1.091× |
| **warm, fully warmed** (seed 41 confirmation) | 1.827 | 1.683 | 1.086× |

Fully warm at `top_k=100`: **1.105×** / **1.098×**. p95 better in every fully-warm
regime (2.951 → 2.628 at `real_top50`).

### The three things this changes

**1. §17's 1.18× does NOT reproduce on the serving path's own inputs.** On local
disk, fully warm, against real ranked result sets, the shipped flat+ordinal path
measures **1.086–1.105×**, not 1.18×. Same sign, no regression, smaller. §17's
figure came from random ids on a spike-built store; the honest production
claim is now **"~1.09×, i.e. neutral"**. The durable win remains **−1.90 GB and
a database removed**, exactly as §17 concluded — the arithmetic survives, the
multiple shrinks.

**2. A newly started process serving flat is SLOWER than sqlite until its
locator is resident — previously unrecorded.** The `0.919×` row is not noise
(the noise floor in that run was 0.46%) and it is not a seed effect: rerunning
the *same seed 17* once the store was warm gave 1.091×. It is the flat arm
faulting in its **421 MB of mmap'd `loc_*.npy`** — visible as a tail, flat p95
9.597 ms vs sqlite's 3.526 and flat mean 3.238 vs p50 2.075, all of which are
gone by the next run. §17's harness never saw this because it warmed every arm
with a 20,000-id parity pass first. **Operationally: the sidecar has a
warm-up cost a restarting server pays and `abstracts.sqlite` does not.**

**3. §16/§17's cold-vs-warm mechanism is CONFIRMED on local disk and INVERTED on
9p.** Pre-registered bar B5 said the cold multiple must exceed the warm one, and
on local disk it does — **2.546× cold vs 1.091× warm**, which is §16's "the
`docs` B-tree costs ~4 ms cold and ~0.24 ms hot" landing exactly as predicted.
On 9p it **fails**: cold 1.79× vs warm 2.876×, because the caching asymmetry
runs the other way (below).

### The 9p page cache does not hold for `abstracts.sqlite` — but it does for the sidecar

On 9p the `sqlite` arm shows **no warm-up at all**: 46.7 (cold) → 47.0 → 47.5 ms
across three passes of the same process, and 45.7 ms in the interleaved warm run.
`posix_fadvise` freed **0 bytes** there, and host `Cached:` sat at 7.06 GB after
reading a 13.47 GB file. The `flat` arm *does* warm on the same mount
(26.2 → 15.9 ms), because its locator is `mmap`'d rather than read through
SQLite's pager. So on 9p every SQLite measurement is permanently cold, which is
both why the multiple is 2.88× and why B5 inverts. This is §14's "the page cache
does not hold" stated for the abstract store specifically, and measured.

### Byte-parity — the hard gate, PASS everywhere

- **Windowed 20,000-id gate** (`build_flat_blocks.sample_ids`, seed 17 → 14,000
  distinct ids after the rowid-gap dedupe §22 documents): **0 mismatches**, on
  every arm, in all **six** interleaved runs.
- **Every timed trial**, not a sample: the flat arm's returned dict compared to
  the sqlite arm's on all 300 trials × 4 regimes × 6 runs — **0 mismatches**.
- **Cross-process**: the sqlite and flat cold processes' per-query SHA-256
  digests of the fetched `{id: abstract}` are equal.

### Bar-by-bar (pre-registered in `2e56b02`)

| bar | 9p | local disk | note |
|---|---|---|---|
| **B1 parity** (hard gate) | **PASS** | **PASS** | any failure would have voided every number here |
| B2 warm no-regression | PASS | PASS warm / **FAIL first touch** | finding 2 |
| B3 warm p50 ≥ 1.18× | PASS 2.876× — but flagged a 9p artifact by its own rule (>1.5×) | **FAIL, 1.091×** | finding 1 |
| B4 warm p95 no-regression | PASS 3.84× | PASS warm / FAIL first touch | |
| B5 cold multiple > warm | **FAIL** (1.79× vs 2.876×) | **PASS** (2.546× vs 1.091×) | finding 3 |
| B6 bytes | **DIFFERS by 1,408 B** | — | below |
| B7 miss asymmetry (directional) | not observed | not observed | below |

**B6 — a 1,408-byte correction to §22.** On-disk total is **11,573,203,382 B**,
not the 11,573,201,974 B §22 records; the saving is **1,897,229,898 B**, not
1,897,231,306 B. The difference is exactly the three JSON stamps
(`flat_store.json` 367 + `locator.json` 662 + `dicts.json` 379 = 1,408 B), which
§22's build report did not count. **−1.90 GB is unaffected.**

**B7 — the predicted miss asymmetry did not appear**, and the reason is worth
recording: cost tracks **hits, not ids**. On 9p a 50-id fetch returning 22 docs
costs 45.7 ms and one returning 11 costs 24.0 ms — ~2.07 ms per *returned* doc
either way. An absent key is cheap in both arms (the flat arm's extra
`searchsorted` is nanoseconds and its `docs` fallback probe returns nothing
quickly), so a federated deployment's high miss rate does **not** erode the
sidecar's position. Multiples on the miss regimes: 2.856×/2.892× (9p),
1.080×/1.075× (local, warm).

### Filesystem caveat, stated the way §14 requires

`data/thinclient_index` is **9p**; a droplet serves off local block storage.
**The 2.88× is a 9p artifact and must not be quoted as a production number.**
What transfers to the droplet is the local-disk column: **2.55× cold, ~1.09×
warm, a first-touch warm-up penalty, byte-parity, and −1.90 GB.** Both columns
are reported here; neither is quotable alone.

### Verdict on the serving default

**Leave it exactly as it is.** The sidecar is published and serving, it is
byte-identical, it is faster on this container's filesystem and neutral-to-
faster on the target's once warm, and it removes 1.90 GB and a database. The
one genuinely new negative — the first-touch warm-up — is an argument for
touching the locator at load time, not for unpublishing anything. **That
touch is now built and gated OFF (2026-08-18, below); its efficacy is
unmeasured.**

### The mitigation is BUILT — `SFU_ABSTRACTS_PREFAULT=1` (2026-08-18)

- Code: `src/lib/thinclient/abstracts.py` — `AbstractLocator.prefault()` +
  the module-level `_touch_pages()`, called from `AbstractStore._open_locator`
  behind the gate; `PREFAULT_ENV = "SFU_ABSTRACTS_PREFAULT"`.
- Tests: `scripts/tests/test_abstract_locator.py` — **39 tests, all pass
  2026-08-18** (27 before, 12 new).
- **Status: IMPLEMENTED 2026-08-18, EFFICACY MEASURED 2026-08-18 — see
  "The re-measurement RAN" below. Short version: the pre-fault works (421.2 MB
  in 203 ms at open), but the 0.919× regression it targets did not reproduce
  under a symmetric-eviction protocol; default stays OFF.**

**What it does.** At store open, for each of the four `loc_*.npy` columns:
`madvise(MADV_WILLNEED)` on the mapping (advisory readahead, so the kernel
batches the I/O instead of servicing ~103k separate minor faults), then a
strided read of one byte per 4 KiB page whose sum is kept as an anti-DCE
checksum — the F6 `touch_bytes` pattern, because numpy is otherwise free not to
perform the read. 421 MB, sequential, once. That is exactly the "read the
`loc_*.npy` arrays once" this list asked for below.

**Gate and defaults.** `SFU_ABSTRACTS_PREFAULT=1` turns it on; unset — or any
other value — is the shipped behaviour, byte-for-byte unchanged. Only the
literal `"1"` enables, the same shape as `SFU_SEISMIC_PREFLOOR_HOTSET` (F6), so
a typo leaves the default rather than half-enabling it. **Default OFF** because
on it costs load time a short-lived process would never earn back, and because
its benefit is the thing that is still unmeasured.

**Fail-open, deliberately.** Pre-faulting is residency-only: it reads read-only
pages and writes nothing, so it cannot change an answer and no failure of it is
a reason to refuse to serve. Errors are logged and recorded in
`AbstractStore.prefault_stats`; the store carries on with a cold locator, i.e.
gate-off behaviour. This is the opposite of the locator identity gate (§17),
which fails **closed** because *that* one can return wrong bytes.

**What it reports.** `AbstractStore.prefault_stats` =
`{"bytes", "ms", "columns", "checksum", "error"}` (None when the gate is off or
no locator attached), plus a `logger.info` line: `pre-faulted %.1f MB across %d
columns in %.0f ms`.

**The 12 new tests**, all synthetic: gate off by default → `prefault_stats is
None` and fetches unchanged; only `"1"` enables (5 negatives); all four columns
touched with `bytes` equal to the columns' summed `nbytes`; **fetches
byte-identical gate-on vs gate-off** at 3 rows and at 6,000 rows (a locator
spanning many pages, so the strided touch does real work); a raising
`_touch_pages` is non-fatal and leaves serving unaffected; SQLite-free mode
(the deployed shape, §18) pre-faults; no locator ⇒ no stats dict.

**The re-measurement RAN — 2026-08-18, idle machine.** Protocol: the published
section restaged to local disk (`stage`, 19/19 files, identity gate re-checked),
`posix_fadvise(DONTNEED)` over all 19 files with the measured `Cached:` delta
recorded (**23.85 GB freed** first eviction, 1.03 GB before the second run —
i.e. each run started from the same fully-evicted state), then one fresh-process
`interleaved` run per arm-state, seed 17, defaults (300 trials × 4 regimes,
20k-id windowed gate):

| gate state | real_top50 | miss50_top50 | real_top100 | miss50_top100 | parity |
|---|---|---|---|---|---|
| OFF (control) | 1.059× | 1.050× | 1.002× | 1.095× | PASS |
| **ON** (`SFU_ABSTRACTS_PREFAULT=1`) | 1.048× | 1.072× | 1.022× | 1.061× | PASS |

Two findings, one of them a correction:

1. **The pre-fault itself works exactly as designed:** `pre-faulted 421.2 MB
   across 4 columns in 203 ms` at store open from a fully evicted state
   (local disk). The whole locator warm-up is a **~0.2 s one-off load cost**.
2. **The 0.919× first-touch regression did NOT reproduce.** Under a
   *symmetric*-eviction protocol (both arms evicted, fresh process), gate-OFF
   already reads 1.00–1.10× — neutral-to-better at first touch — and gate-ON is
   the same within noise. The 2026-08-17 0.919× row was measured in a page
   cache the preceding cold-bench passes had warmed **asymmetrically** (the
   sqlite arm's B-tree pages hot for the query working set, the flat arm's
   `loc_*.npy` arrays not); it was a **run-ordering cache artifact, not a
   stable serving regression**. The row stays in the table above with this
   note as its context.

**Verdict: default stays OFF.** There is no measured query-time penalty left to
earn back; the gate is a correct, cheap belt-and-suspenders for a long-lived
process that wants deterministic first-query latency (e.g. a demo box warming
at boot), and that is the honest extent of the claim. Results:
`data/eval_results/j1_flat_serving_firsttouch_off_20260818.json`,
`..._firsttouch_prefault_20260818.json`.

### Still not settled (§23)

1. ~~**The warm-up is unmitigated.**~~ **BUILT 2026-08-18 and MEASURED
   2026-08-18 — see "The re-measurement RAN" above.** `SFU_ABSTRACTS_PREFAULT=1`
   pre-faults 421.2 MB in 203 ms at open; the 0.919× row itself turned out to
   be a run-ordering cache artifact (symmetric-eviction first touch is
   1.00–1.10× with the gate off). Default stays OFF. **SETTLED.**
2. **The win is not decomposed here.** J1 measures the shipped composite
   (flat blocks + ordinal locator) against plain sqlite, which is the operator's
   question; §16/§17 hold the payload-vs-locator split, and those are spike
   measurements this run did not redo.
3. **One section, one query set.** 120 bm25f queries against
   `social_sciences__recent`; the SPLADE leg's ranked sets were not collected
   (staging 42 GB of SEISMIC shards would have evicted the very page cache under
   test).
