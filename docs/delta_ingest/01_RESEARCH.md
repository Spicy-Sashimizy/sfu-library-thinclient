# 01 — Research record (online, 2026-09-29)

**Status:** ACTIVE

Everything below was fetched on 2026-09-29 by two research agents and is
quoted with its source. "Docs state" is what a source says; *inference* is
ours. Pre-2026 write-ups about OpenAlex are stale: OpenAlex was rewritten
("Walden", 2025-11-03) and the snapshot layout, merge handling and API
pricing all changed.

## 1. OpenAlex — how to stay current

### 1.1 Snapshot (the free path)

- Layout (help.openalex.org/access/snapshot, /access/sync, /download/snapshot-format):
  `s3://openalex/data/jsonl/works/updated_date=YYYY-MM-DD/part_NNNN.gz`
  (Parquet tree in parallel since June 2026). "Each partition holds the
  records that last changed on that date, in part files of up to 400,000
  records each." `manifest.json` carries per-file `meta.record_count` /
  `content_length`, so a delta can be **sized before downloading**.
- Incremental rule, verbatim: "To update a copy you made on date X, download
  only partitions with `updated_date` > X and upsert them by `id`." Records
  that change **move out of** their old partition; the bucket is the complete
  current database, exactly once per record.
- Cadence: the free public snapshot is **quarterly** (second Wednesday of
  Jan/Apr/Jul/Oct). Daily full snapshots are Member+/Partner only.
- Size (Sept 2026 release): ~626M records, works JSONL ~615 GB; ~190M of
  those are the "expansion corpus" (`is_xpac`), excluded by default.
- `merged_ids/` **ended with the Walden cutover**. Works deletions now ship as
  `data/jsonl/works/deleted_ids.csv.gz` (`work_id, deleted_date`; "tens of
  millions of rows"; in the public bucket since 2026-09-23). Instruction:
  "delete every ID in deleted_ids.csv.gz from your copy". Merges leave no
  explicit old→new map; `locations[].id` values survive the merge and are the
  trail. *Inference:* merged-away works appear in `deleted_ids`.
- Churn: one indexed changefile page gave **2026-02-19 works changefile =
  3,171,968 records, 10.1 GB**. *Inference:* ~95M touched works/month, that is,
  ~15% of all records, dominated by citation-count bumps. `updated_date` is
  "the last change to anything in the work object — **including citation-
  count increases**". A content-hash diff is therefore load-bearing: without
  it a monthly delta re-encodes ~15–30M docs of our ≥2015 slice for ~1M real
  changes (*estimate*, new:updated ≈ 1:15–1:30).

### 1.2 API

- `from_created_date` / `from_updated_date` exist but are **paid-plan only**
  (Member+ $10k/yr). Unauthenticated probes returned 429 (inconclusive on
  2026-09-29); **confirmed 2026-10-29** with the project key: 429
  `Plan upgrade required` — "part of daily sync, which comes with the Member+
  and Partner plans" — and by OpenAlex support the same day (no free
  increases; premium daily snapshot and changefiles are paid too). The
  spike CLI's default `--filter from_created_date:2026-01-01`
  (`spike/delta_ingest/cli.py`) therefore cannot run on the free key.
- Keys mandatory since **2026-02-13**; "No more polite pool! No more email
  parameter." Free key $1/day; list+filter $0.10/1,000 calls; search
  $1/1,000; hard cap 100 req/s; every response carries `meta.cost_usd`.
  `per_page` max 100 per the 2026-09-29 docs read — **measured 2026-10-29:
  `per_page=200` returns 200 works with a cursor** (support states 200 per
  filter page); cursor paging unbounded but "don't use cursor paging to
  download the entire dataset". Credit model per support 2026-10-29: 10,000
  credits/day, search 10, filter page 1, single-id GET free
  (`docs/EXTERNAL_API_CONTRACT.md` note of that date).
- A merged-away id answers **301** on single-entity GET; `is_retracted`
  arrives as an ordinary update (the record stays).
- ⚠ **`EXTERNAL_API_CONTRACT.md` still describes the mailto polite pool
  (10 req/s) and a 900-call daily budget.** That is the code's current
  behaviour, not OpenAlex's current terms; a dated note was added there in
  this commit. Re-verifying the live client against the key-only regime is
  outside this spike.

### 1.2a Addendum 2026-10-29 — free daily feed by publication date

**Status of this subsection: MEASURED volumes, DESIGN ONLY for ingest;
nothing built, no default changed.** OpenAlex support (2026-10-29) suggests
`filter=from_publication_date:<d>&sort=publication_date` as the free way to
pull new publications: open on the free tier, 1 credit per page of 200.
Corpus-wide counts measured that day with the project key (`/works`, no
`search`, 1 credit each; `to_publication_date:2026-10-29` added because
forward-dated issue records exist — newest seen `2027-10-27`, 3,961 of the
7-day window):

| Window (publication_date) | Works | Pages of 200 | Credits = pages |
|---|---:|---:|---:|
| 2026-10-22 .. 2026-10-29 (7 d), all domains | 305,297 | 1,527 | 1,527 (15 % of a day) |
| 2026-06-16 (base build) .. 2026-10-29, all domains | 11,142,846 | 55,715 | 5.6 days of budget |
| 7 d, `primary_topic.domain.id:domains/2` (Social Sciences) | 42,760 | 214 | 214 |
| since build, Social Sciences | 1,466,960 | 7,335 | 73 % of a day |
| 7 d, `primary_topic.field.id:fields/33` (Political Science) | 18,461 | 93 | 93 |

The feed page carries full work objects: 172 of 200 (86 %) had an
`abstract_inverted_index`, so abstracts for the delta come with the pull at
no extra credit. `spike/delta_ingest/adapters.py::OpenAlexApiAdapter` takes an
arbitrary `filter_expr`, so `--source openalex-api --filter
'from_publication_date:…,to_publication_date:…'` works today without code.

**What it covers and what it cannot.** A publication-date pull sees works
whose *stated* date is in the window. Each daily run must re-scan a trailing
window to catch late arrivals (works OpenAlex ingests weeks after their
publication date); a 7-day trailing re-scan costs ~1.5 K credits/day
corpus-wide, ~0.2 K for Social Sciences, and anything arriving later than
the window is only caught by the next quarterly snapshot. It never sees
**updates** to existing records (retractions, merges, citation counts,
corrected metadata) — the 1:15–1:30 new:updated ratio of §1.1 — so the
snapshot adapter stays the only free path for those; this feed replaces
nothing, it fills the snapshot's lag for *new* work only.

**Is it meaningful for delta ingest?** For supply, yes: the free tier can
deliver every new publication daily (corpus-wide ~44 K works/day *measured
over 7 days*) at ≤ 15 % of the credit budget, or the hot Social Sciences
slice at ~2 %. **The binding constraint is serving-side, not the API**: doc
10 F0 measured c = 21.35 ms per million live delta docs per query (upper
bound), so the 8 ms sections-tier budget is spent at ≈ 375 K delta docs —
≈ 8–9 days of the corpus-wide feed, ≈ 60 days of the Social Sciences slice
(*est.* from the measured rates) — and fold-in is not promotable as measured
(F0, F3, F8 FAIL; F7 FLAGGED), with `SFU_DELTA_ROOT` default OFF. The feed
therefore makes a *scoped* delta (hot sections only, ~6 K docs/day) the
realistic first use, and leaves the promotion decision exactly where doc 10
and doc 11 left it. Nothing here changes a verdict.

### 1.3 Abstracts

Still `abstract_inverted_index` in API and snapshot ("OpenAlex does not ship
plaintext abstracts for legal reasons"). Abstracts can **disappear** on
update (publisher takedowns; a 2025-01-29 purge of 350k junk abstracts), so an
update may legitimately drop a work out of the "has abstract" slice — the
ingest treats a vanished abstract as a content change (re-index), not as a
no-op.

### 1.4 Tooling

No official diff feed beyond the partitions. `ourresearch/openalex-documentation-scripts`
(full Postgres load), `openalexPro/openalex-snapshot` (Rust download/verify,
no incremental logic), `seandavi/cu-research-intelligence` (DuckDB, per-
partition watermark — "the free analogue of the paywalled from_updated_date").
Nothing handles `deleted_ids`. Our own retired `scripts/opensearch_sync.py`
(deleted in commit 27621f42, 2026-06-11) already keyed parts on the
`updated_date=…/part` identity — recovered into `adapters.partition_of`.

## 2. Updating immutable indexes — prior art

| System | Inserts | Deletes | Merge | Many-small-segments cost |
|---|---|---|---|---|
| **Lucene** | writer buffers → flush immutable segment | per-segment `.liv` bitset, segment never rewritten; `updateDocument` = delete-by-term + add | TieredMergePolicy: segmentsPerTier 10, maxMergeAtOnce 10, maxMergedSegmentMB 5 GB, floorSegmentMB 2, deletesPctAllowed 20% | one term-dict lookup + posting walk per segment per query |
| **FreshDiskANN** (SIGMOD 2022) | RW-TempIndex in RAM (~30M pts), frozen to RO-TempIndex | DeleteList, graph untouched | StreamingMerge (delete/insert/patch) into the SSD index; recall stable after ~20 cycles at 10% churn | queries fan out to LTI + all temp indexes |
| **Vespa proton** | memory index | Removed sub-DB (id+timestamp tombstones) | flush → new disk index → "fusion" into primary | — |
| **Quickwit** (tantivy splits) | immutable splits | delete tasks rewrite mature splits ("a few per hour or day") | stable_log policy: merge_factor 10, split target 10M docs; "no merge" degrades search | split count degrades search |
| **Milvus** | growing (RAM) → sealed | per-segment DeltaLog + bloom filter → bitset at query | compaction drops rows | no PK de-dup guaranteed |
| **Qdrant** | appendable segment | delete in immutable + insert in appendable | optimizer builds immutable | external-id dedupe at search |

Common pattern: **new docs go to a small mutable tier, deletes are masks
applied to old segments, updates are delete + add, and a background merge
bounds the segment count.** That is exactly what `02_DESIGN.md` builds.

## 3. SEISMIC — no update path exists

- Upstream `TusKANNy/seismic` (tree read 2026-09-29): `build(dataset)` takes a
  whole dataset; persistence is serialize/load; the only `add_document`
  targets the pre-build growable dataset. 17 issues + 2 PRs, **zero** about
  insert/update/delete/merge/incremental. Last commit 2026-09-10 (build-speed
  work; "none of them changes the built index"). Upstream now ships
  `src/pylib/dotvbyte.rs` (ECIR 2026 forward-index compression) — worth
  diffing against `spike/seismic_upstream` later.
- Build cost is near-linear in postings: MS MARCO 8.8M in 5 min (SIGIR 2024);
  MS MARCO v2 138M in 0.5 h without κ-NN (ECIR 2025, 192-core Xeon). Per-list
  pruning/clustering are independent per list, so **a small delta index is
  cheap** — but its pruning threshold and λ are corpus-relative, so a delta
  shard is a validly structured but differently pruned index.
- Closest updatable-LSR prior art: Rule & Mackenzie, "Fast, Compact,
  Immediate-Access Indexing for LSR Systems", ECIR 2026 (research code).

## 4. tantivy-py 0.22–0.26

- Incremental add works: open the existing directory with one writer,
  `add_document`, `commit` → a new segment. `delete_documents_by_term` (raw
  field only — issue #297: deletes on a tokenized field silently miss) and
  `delete_documents_by_query` (0.25.0+, 2025-09-09). Repository pins 0.26.
- **Not exposed:** `merge(segment_ids)`, `set_merge_policy`. LogMergePolicy
  defaults: min_num_segments_in_merge 8, max_docs_before_merge 10M — so
  10M+-doc base segments never re-merge, and small segments merge only when
  ≥8 of similar size accumulate.
- Readers: `config_reader("commit")` / MmapDirectory watch `meta.json`, so a
  reader in another process sees a writer's commit. One writer per index
  (`fs2` flock; "may not be respected on NFS"; stale lockfile after a panic).

## 5. Off-the-shelf learned-sparse engines at 150M / 31 GB — none fit

Qdrant sparse pins its index in RAM (our measurement: ~43 B/point anon,
≈6.5 GB, plus poor latency at 150M — `THIN_CLIENT_SWAP.md`); Elasticsearch/
OpenSearch `rank_features` = JVM heap (removed from this container); Vespa
`wand` runs over a memory-backed attribute; Milvus sparse segments load into
query-node memory; Weaviate has no SPLADE (FR #4019 open); pgvector
`sparsevec` is HNSW-only. **No published 100M+ sparse benchmark with RAM
numbers exists for any of them.**

## 6. Dictionary-compressed block stores

zstd writes the dictID into each frame by default, so blocks can self-identify
their dictionary; there is no numeric drift threshold in any source — practice
is "never rewrite old blocks, tag new ones with their dictionary generation,
retrain when the measured ratio on a new batch degrades" (RocksDB trains one
dict per SST at compaction; Parquet has no trained-dict support).

## 7. Verdict — bespoke vs off-the-shelf

| Leg | Off-the-shelf? | Smallest bespoke piece |
|---|---|---|
| tantivy BM25F | **yes for the mutable buffer** (delete-by-term + add + commit, cross-process reload) | a delta-section layout (Quickwit split model) because base sections are served immutable/packed and tantivy-py cannot force-merge |
| SEISMIC SPLADE | **no** — no insert/delete/merge upstream, nothing planned | one shard per generation through the same build → c1a → dotvbyte chain, plus a newest-wins mask over base hits; fold into base at the next full rebuild |
| meta.sqlite | yes (SQLite) | per-generation meta DB + delta-first resolution of superseded ids (the served base DB is never mutated in place — `CODE_INVARIANTS.md`) |
| abstract sidecar | partial | per-generation v3 store (built); dictionary reuse across generations is the open lever |
| dedupe / RRF | trivial | apply the superseded/deleted sets before fusion (Lucene's delete+add semantic across immutable shards) |
| an off-the-shelf sparse engine instead | **no** (§5) | — |
