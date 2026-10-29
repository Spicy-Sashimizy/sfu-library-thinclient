# Code invariants, constraints & workarounds (migrated from code comments 2026-09-01)

**Status:** ACTIVE

The codebase carries no internal comments (policy 2026-09-01); every
constraint, invariant, magic-number provenance, and external-bug workaround
that used to live in a comment lives here, ordered by module, with a
`file` pointer. Where an entry restates a research doc, the research doc is
authoritative (source-of-truth rules: `.claude/CLAUDE.md`). Env-gate
semantics: `ENV_GATES.md`. External-API client rules:
`EXTERNAL_API_CONTRACT.md`.

Line numbers are as of 2026-09-01 (pre-strip); use the symbol names to
locate after drift.

## source/lib/thinclient/retriever.py

- **BM25F query text is lower-cased before `parse_query`** (`bm25f_query_text`, 2026-09-30, O19; revised 2026-10-01): every non-alphanumeric, Unicode whitespace included, becomes an ASCII space (tantivy's query grammar accepts only ASCII separators: NBSP/U+2005 raised), and each alphanumeric is lower-cased unless that yields several code points (`'İ'` -> `i`+U+0307, which the grammar rejects; the field tokenizer lower-cases `İ` as at index time). Lower-casing is NOT hit-neutral: tantivy's parser collapses a repeated word only by surface form, so before 99e2b663 a word in two case variants ("How ... how") became two identical term clauses after the lower-casing tokenizer (double weight) while a same-case repeat was one; upper-case `AND`/`OR`/`NOT` were boolean operators and `IN` raised. Lower-cased text gives each distinct word one clause regardless of case — the intended, case-insensitive behaviour; it changes the parsed query for 1 of 120 topics (index 117) and 27 of the 350 M3 titles (`scripts/experiments/eval_delta_ingest_o19_case_parse.py`, `data/eval_results/delta_ingest_O19_case_parse_20261001.json`). `_bm25f_leg` skips a section whose `parse_query` raises `ValueError` (for example, every token over tantivy's 40-byte limit: "Only excluding terms given"), so the leg returns no hits instead of raising out of `search_rrf`. Tests: `scripts/tests/test_bm25f_query_text.py`, `scripts/tests/test_bm25f_query_text_unicode.py`.

- **FS-aware federation default** (`_pick_federation`): on passthrough/network
  filesystems (9p/virtiofs/NFS) mmap page cache does not stay resident, so
  `SequentialSeismicBackend` is the better default; on native local disk pages
  stay resident and parallel wins. Federation mode is roughly latency-NEUTRAL
  for a genuinely cold fault (measured 2026-07-18: parallel p50 9134 ms versus
  sequential 8747 ms) — the real cold-latency lever is the filesystem. Environment
  always overrides the heuristic.
- **Staging idempotency marker**: a `.staged_ok` marker records source byte
  size + mtime_ns + fingerprint; avoids re-walking the 42 GB source tree on a
  slow mount every boot (minutes on 9p). An existing correct copy without a
  marker (for example, staged by `scripts/stage_seismic_local.sh`) is adopted.
- **Staging crash-safety**: copies go to `<name>.tmp-<pid>` then
  `os.replace` (atomic — readers see old-or-new, never partial). Leftover tmp
  from a killed copy is garbage: never resumed (a partial SQLite file is not a
  shorter valid one) and never opened. A previous stage's `-wal`/`-shm`
  sidecars must not shadow the new file. Refuses a source with a live
  `-wal`/`-journal` (a byte copy would drop those pages).
- **`META_STAGE_FAST_TAIL = 65536`**: head+tail bytes hashed by the
  `fingerprint` verify mode (size + head/tail 64 KiB sha256).
- **Post-open probe**: `sqlite3.connect` is lazy — force a real read at open
  so an unusable file fails NOW, not on the first served query.
- **meta.sqlite location dominates the filter stage** (doc
  `seismic_150m_testbed/18` §14, measured 2026-08-03): 222.2 ms on 9p versus
  4.0 ms on local disk at 500 candidates — 55× for a file copy, no code
  change. Staging is a dev-container lever, a production no-op (droplets
  serve off local block storage; without FORCE the code refuses to copy from
  a local FS).
- **SPLADE model default** (2026-07-09, D2): the offline bert-FUSED export —
  same fp32 weights, exact GELU, 1.11× encode, merged overlap@10 0.999 versus
  unfused (doc `seismic_150m_testbed/08` §D). Regenerate via
  `scripts/seismic_testbed/d2_ort_fusion_matrix.py`; `models/splade_onnx` is
  the unfused fallback. A bare HF hub id cannot be fetched in the air-gapped
  serving container — defaults must be local paths.
- **Flat-abstract detection**: a consolidated section may have
  `abstracts.sqlite` deleted, served entirely from the flat sidecar (doc 18
  §18) — open on the sidecar's presence, not just the SQLite file's.
- **meta schema versions**: v2 stores W-ids as INTEGER PRIMARY KEY (+
  `docs_other` TEXT overflow); v1 indexes (for example, thinclient_1m) are TEXT.
- **Ordinals fail CLOSED** (`SFU_THINCLIENT_ORDINALS`): raises rather than
  falling back if configured and unusable — quietly serving SQLite after
  being told to serve ordinals would make a misconfiguration look like a
  performance regression. Loads only if the directory's `ordinal_space_id`
  matches the index `manifest.json`. Ids with no ordinal (warm-cache growth)
  fall back to SQLite rather than being dropped; docs with no build-time
  ordinal MUST go through the SQLite path — dropping them would silently
  lose exactly the documents the warm cache exists to surface. Requires
  arrays on local disk (off 9p measured 8× slower than SQLite).
- **Leg-metrics accessors** are O(1) + thread-safe by design: the tools layer
  diffs a window around each search to get per-leg ms without a callback
  plumbed through every leg.
- **Manifest forms**: both dict `{"shards":[{"mmap_dir":…}]}` (e5/e8
  promotion manifests) and bare list of shard-dir strings (testbeds/fixtures)
  are accepted; C2.5 records carry both `index_path` and `mmap_dir` —
  `mmap_dir` is authoritative.
- **Manifest promotion ladder** (E8 dv-v2 → E5 dv-v1 → plain dv): gated on
  the REAL serving root so synthetic/test index_roots never silently pick up
  the 150M corpus. A set `SFU_SEISMIC_SHARD_MANIFEST` always wins (one-env
  rollback to any prior manifest); a missing set path fails loudly.
- **Shard staging** (`SFU_SEISMIC_STAGE_DIR`): serving off 9p/NFS is
  ~160–240× slower per mmap fault and page cache doesn't hold (measured
  2026-07-18). No-op on a droplet; best-effort.
- **Shard staging never deletes what it cannot replace** (fixed 2026-09-29,
  `_stage_shards_local`): a shard whose source resolves to its own staged
  path is skipped — before the fix, a process given `staged_manifest.json`
  with `SFU_SEISMIC_STAGE_DIR` set compared the staged directory (marker included)
  against the marker's size, judged it stale, removed it and then failed to
  copy it from itself (staged shard 0 lost and re-staged 2026-09-29, see
  `archive/inplace_update/07_INPLACE_PAUSE_HANDOVER_2026-09-29.md` §6). A re-copy goes
  to `<name>.tmp-<pid>` and replaces the old copy only after the copy
  completed; a failed copy leaves the old staged shard in place. The repository
  `.env` sets `SFU_SEISMIC_STAGE_DIR`, so removing it from a process
  environment is not enough — set it empty. Pinned by
  `scripts/tests/test_seismic_shard_staging.py`.
- **Two serving classes, no shared mutable state**: parallel and sequential
  federation are distinct classes sharing only pure helpers (cascade
  design — the score-merge cannot drift between methods).
- **SPLADE over-fetch before post-filter** (fixed 2026-07-06): the leg
  previously fetched exactly top_k then filtered, thinning results below
  top_k. Default k′ = max(2×fetch, 100).
- **`info()` is an operational-proof surface**: reports which optional
  payload components are live (a deploy can PROVE it shipped/omitted the
  dense partition) and which copy of `meta.sqlite` the filter stage reads
  (the 55× variable).
- **Encoder degradation**: a missing/corrupt ONNX model must degrade the
  leg, not the query — RRF still fuses BM25F (+dense).

### Hydrate once per request (`hydrate_scope`, lever #0, 2026-09-25)

- **Scope = one request, never longer.** `ThinClientRetriever.hydrate_scope()`
  sets a `contextvars.ContextVar` memo for the duration of a `with` block;
  `_hydrate` then asks `_meta_rows` / `fetch_abstracts` (and so the OpenAlex
  remote fetch) only for ids not yet asked in that scope. The memo is
  discarded on exit: there is no cross-request abstract/meta cache, so no
  stale abstracts. `_rrf_legs` (hence `search_rrf` / `search_rrf_detailed`)
  opens one around its legs. Plain `search()` / `dense_search()` outside a
  scope are unmemoised, exactly as before.
- **Owner-bound, re-entrant.** The memo records its retriever; another
  `ThinClientRetriever` in the same context bypasses it. A nested scope on
  the same retriever reuses the outer memo.
- **Misses are memoised too** (`rows_seen` / `abs_seen`): an id with no meta
  row or no abstract is not re-asked within the scope. Consequence: a
  transient remote failure (swallowed `RequestException`) on leg 1 is not
  retried by leg 2 for shared ids. Fused RRF output is unaffected — for a
  shared id `_rrf_fuse` keeps the first leg's dict — so the fused result is
  byte-identical to the unmemoised path.
- **Exceptions leave the memo untouched.** An exception escaping
  `_meta_rows` / `fetch_abstracts` propagates as before and the ids are not
  marked seen, so a later leg in the same scope re-asks them.
- **Warm-cache `enqueue` is NOT memoised**: `_hydrate` still enqueues each
  leg's full result list once per leg, same batches as before.
- **Thread-safety.** A `threading.Thread` does not inherit the ContextVar,
  so worker threads spawned inside a scope run unmemoised; a memo shared by
  asyncio tasks of one request is guarded by the memo's own lock (held
  across the lookup, which serialises only same-request hydrates).
- **Router path is NOT scoped by the retriever.** `FederatedSearchRouter`
  LOCAL_RRF calls `search()` twice on the retriever with no scope, so the
  serving GUI/MCP path gets the dedupe only once the router (or its caller
  in `tools.py`) wraps both calls in `retriever.hydrate_scope()` (use
  `getattr(..., "hydrate_scope", contextlib.nullcontext)` for the
  OpenSearch retriever). Pinned by `test_hydrate_memo_*` in
  `source/tests/test_thinclient.py`.

### Remote abstract fetch (injected fetcher, 2026-09-25)

- **`_fetch_remote_abstracts` is the single dispatch point** (tests and
  `scripts/experiments/speculation_*.py` monkeypatch it). With
  `remote_abstract_fetcher` set it calls only that (serving: the shared
  `OpenAlexClient.fetch_abstracts_by_ids`, so key/budget/breaker/cache
  apply) and never `requests.get`; any exception from the fetcher is logged
  by type name and degrades to `{}`. With no fetcher it uses
  `_fetch_remote_abstracts_direct` (offline fallback, unbudgeted), which
  sends `api_key` if `openalex_api_key` was given, else `mailto` — the
  no-key call shape is unchanged. Error strings are passed through
  `redact_api_key`, which since 2026-10-10 masks `mailto=` values as well
  as `api_key=` (the contact address is the operator's and stays out of
  logs).
- `remote_abstracts=False` still means no remote call of either kind.
- The `hydrate_scope` memo sits above this dispatch, so the fetcher sees
  each id at most once per request (pinned by
  `test_hydrate_scope_fetches_once_per_id_via_injected_fetcher`).
- Budget/breaker consequences are in `docs/EXTERNAL_API_CONTRACT.md`
  §"Thin-client abstract hydration goes through OpenAlexClient".

## source/lib/thinclient/sharded_seismic_backend.py

- **posting_lists.bin layout table** (`_PL_LAYOUT`; the doc said `_POSTING_LAYOUT` until 2026-10-10 — code name wins): (manifest key,
  element size, alignment, role); `read_pod` pads the cursor to element
  alignment, `read_bytes` (values, align 1) does not. NAV versus DATA roles feed
  the F4 floor pin. Verified exact: walking the table over a shard manifest
  reproduces `posting_lists.bin`'s byte length to the byte (shard0:
  1,159,211,728 B, 2026-08-17). Mirrors Rust
  `mmap_io.rs::read_posting_lists`.
- **Manifest paths are repo-root-relative**; the serving process cwd is not
  guaranteed to be the repository root (MCP launch), so unresolvable relative
  paths are anchored to the repository root.
- **Partial conversion fails loudly** (guard 2026-07-06): a
  partially-converted manifest must never serve a partial corpus.
- **WI-10 shard isolation**: all gates default OFF → load loop + `_fan_out`
  byte-identical to pre-WI-10; a shard that fails to load is marked FAILED
  with a None placeholder — one bad shard file never stops the other seven.
  Both `_fan_out`s iterate `self.shards` in order, so the i-th call pairs
  with the i-th failure tracker (positional coupling).
- **Init ordering under mlock (two external-library bugs, 2026-07-14)**:
  mlocking the floor + hot extents (~2.4 GB) BEFORE the SPLADE ONNX session
  loads triggers an onnxruntime dlopen failure ("failed to map segment from
  shared object"); the HF fast tokenizer's rayon pool initializes lazily on
  first `encode_batch` and mlocking first starves `clone()` of thread-stack
  VM (`ThreadPoolBuildError: WouldBlock`). Therefore when pinning or F6
  prefault is ON, the SPLADE encoder is eager-loaded FIRST. The F6 bench's
  invalid "cold p95 30 ms" cells came from exactly this (every query raised
  ImportError and scored 0.0 ms).
- **Q9 startup floor prefault is ONCE-AT-LOAD, not per-query** — distinct
  from the REFUTED per-range query-time WILLNEED (doc 10 Fix #3: kernel
  ignored it, added syscall overhead).
- **Pin tier is residency-only**: F2/F3/F4 touch no scoring or record decode
  → T1 bit-identical by construction; every gate defaults OFF (=0 →
  byte-identical, the kill-switch discipline); `.so` hooks degrade to no-op
  if mlock is denied (no CAP_IPC_LOCK) — an unprivileged process pins 0,
  never crashes.
- **No-OOM pin budget**: never pin past MemAvailable − floor − headroom;
  `floor_gb = 1.5` (structural floor, measured Fix #4/Q9), `headroom_gb =
  1.0` (anon serving floor + encoder + safety). Gap fill can overshoot —
  trim tail extents until within 10% (locked bytes are a hard commitment).
- **TWO-PASS + COALESCE** (mlock and prefault paths): all sidecar/manifest
  reads happen BEFORE the first mlock/prefault call, and mlock uses ≤2048
  coalesced ranges per shard — per-extent mlock (~33k/shard) split VMAs to
  `vm.max_map_count` saturation (shard4 pinned 0.00; shard5 manifest read
  raised). Under the WILLNEED flood even a 21 MB manifest `read_text()` can
  raise MemoryError on WSL2/drvfs (measured twice, 2026-07-14).
- **F2 version-key check REFUSES on mismatch** — fail loud, never pin
  garbage.
- **`prefault_ranges` returns `touch_bytes`' anti-DCE checksum, not a byte
  count** (`mmap_io.rs`) — report submitted extent bytes instead; the
  original F6 run logged "touched 0.00 GB" from the checksum.
- **Sequential mechanism (B)**: `MADV_DONTNEED` each shard's file-backed
  slabs right after its search, so peak resident ≈ 1 shard hard-guaranteed
  (not kernel-reclaim timing). Guarded: stock shards / older `.so` without
  the pyo3 hook degrade to a no-op + debug log, never a raise.
- **Hybrid flip is safe to observe torn**: mode peeked under the lock; both
  modes return the bit-identical merged top-k. Warm bar = geometric mean of
  cold samples × warm_frac, with a zero-guard so the threshold can't be 0.
- **Zero-shard constructibility**: `max(1, …)` on worker counts — the
  selector contract tests build a zero-shard backend and
  `ThreadPoolExecutor` rejects `max_workers=0`.
- **Encoder borrow**: `encode_query` is borrowed via a thin stand-in rather
  than instantiating the upstream encoder class (its `__init__` loads a
  SEISMIC index); pyo3 index objects don't accept dynamic attrs, so
  per-shard `mmap_dir` is tracked in a parallel list (F3).

### block_prefetch.py (lever #4, term-prefix prefetch, 2026-09-25)

> **CLOSED MEASURED 2026-09-25** — cold traverse −4.4% versus a ≥ 20% bar, warm arm slower
> (`docs/SPECULATIVE_RETRIEVAL_UPGRADES.md` §4 row 4). The module moved to
> `spike/archive/block_prefetch/`; nothing live imports it. Kept as the record of
> the posting-list layout walk below.

- **Reachable granularity = one whole posting list per (term, shard).**
  pyseismic exposes no term → block API. What IS readable from Python: each
  `.mmap/` shard's `token_to_id_map.bin` (bincode fixed-int LE: u64 count,
  then u64 strlen + utf-8 + u64 id; ids differ per shard) and its
  `manifest.json` per-list component lengths. Walking those with the
  backend's `_PL_LAYOUT` gives every list's exact byte range in
  `posting_lists.bin`; the walk must consume the file to the byte or the
  shard is skipped (checked on the real shard0 manifest 2026-09-25:
  1,159,211,728 B, 28,702 lists, 322.9 MB packed postings + 836.3 MB
  summary/navigation). Which blocks survive, and the forward pages they lead
  to (`forward_*.bin`, ~85% of index bytes), depend on the traversal and
  cannot be planned. Do not use `_postings_nav_runs` here: it covers
  navigation only, the summary pass also reads `summaries_ids`/`values`/
  `minimums`/`quants`.
- **Plan order is fixed**: terms by SPLADE weight desc (ties by token), the
  summary+navigation run of every (term, shard) first (the per-term summary
  pass reads it unconditionally), then the packed-postings runs (read only
  for surviving blocks). Ranges are page-aligned, the cap clips the crossing
  range to a page multiple and drops the rest, then ranges are coalesced and
  sorted by (path, offset). Same input → same plan.
- **Only finished words are encoded**: a trailing word with no whitespace
  after it is dropped (`completed_words`); one unfinished word plans nothing.
- **Advice only, never a read**: `madvise(MADV_WILLNEED)` when the file is
  mapped in this process (base from `/proc/self/maps`, cached; unmapped
  paths re-checked at most every 30 s), else `posix_fadvise(WILLNEED)` on a
  cached read-only fd. WILLNEED does not change VMA flags, so it does not
  split VMAs (the `vm.max_map_count` trap of the pin tier). Search output
  cannot change.
- **Single slot, drop not queue**: one non-blocking lock covers
  `issue_prefetch` and the `speculate` worker thread; a call that finds it
  held returns at once (`reason: busy`). `issue_prefetch` re-caps any plan
  it is handed. Every error is swallowed and counted in `stats["errors"]`.
- **Inactive unless all hold**: `SFU_BLOCK_PREFETCH` is literal `1`, the
  load mode is `mmap`, and there is at least one shard dir. Inactive calls
  do no encode and no syscalls.
- **Wiring contract (not done)**: the serve app should call
  `configure(backend=<the live ShardedSeismicBackend>)` once the SEISMIC leg
  loads (so staged shard directories are the ones advised), then
  `block_prefetch.speculate(prefix_text)` from the `/api/speculate` handler.
  Without `configure`, the module derives directories from
  `SFU_SEISMIC_SHARD_MANIFEST` + `SFU_SEISMIC_STAGE_DIR` (`.staged_ok`).
- **Known priors against it**: in-query per-range WILLNEED on forward
  ranges was REFUTED (doc `seismic_150m_testbed/10` §7.2: zero fault
  change, warm regression) — this lever differs by advising hundreds of ms
  ahead from another thread, but that difference is unmeasured. With
  `SFU_SEISMIC_PREFLOOR*` or the mlock floor on, the posting lists are
  already resident and the lever is expected to be a no-op.

## source/lib/thinclient/abstracts.py (flat sidecar + store)

- **Plain-fallback buckets decode under the latin dict (O13, pinned
  2026-10-01).** A non-latin bucket that reaches `TRAIN_TARGET_DOCS` before
  latin and fails its own training is written with the PLAIN compressor,
  while `_build_v3_dctxs` later decodes it with the latin dict. This is
  correct because a frame written without a dict carries dictID 0 and never
  references dictionary content, so it decodes identically under any dict
  (test `test_o13_nonlatin_plain_fallback_decodes_with_latin_dict` in
  `scripts/tests/test_delta_serving_fixes.py`). The reverse (dict frame,
  plain decoder) is a hard `Dictionary mismatch` error: never make a bucket
  fall back to plain on the READ side while its writer used a dict.
- **Readers never write (O15, 2026-10-01).** `AbstractStore` connects with a
  `file:` URI built by `Path.resolve().as_uri()` plus `?mode=ro`, so a stray
  statement on any reader (serving, seed, evals) fails with `readonly`
  instead of modifying a served sidecar; `as_uri()` escapes `?`/`#`/`%` in
  paths. Deliberately not `immutable=1` (that also drops locking and change
  detection, unsafe while a builder may still write). Consequence: a sidecar
  with a hot rollback journal errors on open instead of being rolled back by a
  reader. Test `scripts/tests/test_abstract_store_readonly.py`.
- **Stamp identity**: `FLAT_STAMP` carries the identity minted for
  `blocks.bin`; `LOCATOR_STAMP` copies it, and the reader REFUSES any
  pairing whose ids disagree — a locator over the wrong blocks returns a
  real, WRONG abstract with no error. The stamp is a fresh uuid per build
  (not a content hash): a locator built against a different build of the
  same corpus is still wrong — the addresses moved. Stamped only AFTER
  `blocks.bin` is complete.
- **Crash-safe write ordering (rule used 3×)**: rename last — the reader
  keys off `blocks.bin` (resp. `locator.json`, `dicts.json`) existing, so a
  crashed build leaves a directory that is skipped, never half-served.
- **Full-length column validation**: every locator column must be
  full-length, not just wids — an interrupted copy can leave `wids`
  complete and `off` short, and the tail then addresses whatever the shorter
  array holds (doc 18 §12, hit for real 2026-08-02).
- **Locator ids from source**: (b, off, n) come from `source`'s docs table and
  must index blocks built from the SAME source; copying its id would certify a
  false pairing — refuse instead.
- **dtypes from MEASURED maxima, never assumed**: `n` maxes at 71,073 in
  production, which overflows u16 despite the ~32 KB block target; guessing
  would silently truncate the longest abstracts. Sparse block ids keep
  offset −1 sentinels; the reader raises on them rather than preading a
  wrong range.
- **Store durability**: WAL (not OFF) — the store must survive SIGKILL so
  per-slice build resume can append instead of rebuilding the section;
  TRUNCATE checkpoint after commit resets the file. A resume that restored
  pending buffers AND re-fed the crashed slice can hold a doc twice — keep
  the last copy.
- **v3 detection**: a SQLite store is accepted when it has a `docs` (the
  block locator) OR a `blocks` table — once flat exists an operator may drop
  `blocks`, so never key off `blocks` alone. A store with neither is refused
  with a RuntimeError: the v1/v2 per-doc readers (`abs` table, `zdict`/
  `zdict_ru` dicts) were removed 2026-10-11 (codebase triage; no v1/v2 store
  exists here; `test_thinclient_stack.py::test_abstracts_pre_v3_store_refused`
  pins the refusal). v3 uses positional dict ids (`names`). Never let
  `sqlite3.connect()` silently CREATE an empty db in the reader path.
- **numpy torn-file exception taxonomy** (measured 2026-08-17): `np.load`
  does NOT confine torn `.npy` files to OSError — truncated data raises
  ValueError ("mmap length is greater than file size"), zero-byte raises
  EOFError, header-corrupt raises ValueError (pickled data). Catching only
  OSError meant the documented lossless fallback never ran. Falling back is
  lossless here (unlike the ordinal guard, where falling back would mean
  wrong answers).
- **Non-W ids MUST keep the SQLite path**: a `docs_other`-class id the
  ordinal locator cannot address vanishes silently otherwise (doc 18 §6
  hazard 2).
- **`SFU_ABSTRACTS_PREFAULT` default OFF**: J1 measured a fresh process
  serving flat at 0.919× sqlite (8.8% regression) on first touch after
  eviction — the 421 MB of mmap'd `loc_*.npy` fault one page at a time; the
  same seed warm is 1.091×. Prefault is residency-only (byte-identical) but
  costs load time a short-lived process never earns back.
- Constants: `BLOCK_TARGET = 32*1024` (uncompressed bytes/block, measured
  configuration), `BLOCK_CACHE = 64` (decompressed blocks kept hot in the reader).

## source/lib/thinclient/delta_layer.py (+ retriever hooks, 2026-09-29)

Design + engine-interaction matrix: `docs/delta_ingest/02_DESIGN.md`. Gate
`SFU_DELTA_ROOT` (default OFF); with the gate unset no retriever code path
differs (pinned by `scripts/tests/test_delta_ingest.py` last block + the
unchanged stack suite).

- **Published generation directories are immutable.** `gNNNN/` is staged as
  `gNNNN.building/` and renamed once `generation.json` is written; the reader
  opens each generation's `meta.sqlite` with `mode=ro&immutable=1` — legal
  ONLY because nothing ever rewrites a published directory (compaction builds a NEW
  generation and renames the old ones `*.compacted`).
- **The served base `meta.sqlite` is never written.** Delta meta rows live in
  per-generation DBs + the ledger; `_meta_rows` resolves `superseded` ids
  delta-first and misses delta-last, so `_post_filter_sqlite` and `_hydrate`
  see the newest copy. Filters on delta docs therefore work without ordinals
  (ids with no ordinal already fall back to SQLite).
- **Newest-wins mask** (`keep_hit(id, origin)`): `deleted` hides everywhere;
  `superseded[id] = g` keeps only the copy whose origin is `g` (base `None`,
  buffer `0`, generation `g`). BM25F hits carry their section's
  `delta_origin`; SEISMIC results are already score-deduped across shards so
  only `deleted` and "buffer is newest" are exact there (S5 in the design).
- **`generations.json` is written LAST and atomically** (`os.replace`) and
  names the shard manifest; the reader keys on its `stamp`. `reload()` drops
  the SEISMIC backend iff `(stamp, shard_manifest_path)` changed — a
  republish with the same pair is a no-op for the sparse leg.
- **Buffer read side is poll-based and rebuild-safe:** the layer reads the
  ingest ledger read-only, keys on `(count, max rowid)` of the rows in the
  buffer generations, appends when only new rows arrived and rebuilds
  otherwise (also when the buffer-generation set lost a member). Buffer
  generations (`_buffer_generations`, O2 fixed 2026-10-01) = 0 plus every
  `building` or published-but-not-loaded generation that is buffer-derived:
  its ledger `info.from_gens` are all 0 or themselves unloaded and
  buffer-derived; a published row whose `info` lost `from_gens`
  (`finish_generation` overwrites it) counts iff no LOADED generation is
  `compacted` — only a compaction moves loaded docs into a newer generation.
  So a freeze stays visible to the SPLADE buffer leg, meta and abstracts
  until `reload()` (no re-parse: the rows were already held), and a
  compaction of loaded generations is never parsed into RAM (before this,
  every `building` generation was, compactions included). Residual: after a
  compaction of a loaded generation, an unloaded freeze is not counted until
  `reload()`.
  BM25F side (O2 residual, fixed 2026-10-01, test
  `scripts/tests/test_delta_bm25f_freeze_window.py`): a hit from the tantivy
  buffer section is kept only if its id is in the buffer view
  (`_buffer_rows`; `filter_hits` calls `refresh_buffer()` when a buffer hit
  is present), so the buffer tantivy may hold MORE than the buffer view
  without duplicates or stale copies. The ingest side therefore never deletes
  just-frozen docs from the buffer tantivy: after every freeze (`flush` and
  both `ingest` auto-freezes) `BufferWriter.retain_only(keep)` keeps
  gen 0 + `building` + the just-frozen generation and deletes everything
  else. BM25F then sees a frozen doc until `reload()` unless TWO freezes
  happen without a `reload()` in between (the older one is collected at the
  second freeze — remaining residual). The buffer tantivy is bounded by
  buffer + one generation (before the fix, `ingest` auto-freezes never
  deleted, so frozen docs stayed in it forever and were returned twice after
  `reload()`).
  Every buffer accessor, `buffer_size()` included (the SPLADE buffer-leg gate,
  O1 fixed 2026-09-30), calls `refresh_buffer()`, which skips the SQL poll
  while the `(mtime_ns, size)` of `ledger.sqlite` + `-wal` is unchanged and
  opens the ledger lazily.
  The tantivy buffer section (`delta_buffer`, no era suffix — never
  era-pruned) is `reload()`ed per query. If its directory did not exist when the
  layer loaded, `_bm25f_leg` attaches it lazily the first time
  `DeltaLayer.buffer_section_dir()` finds `tantivy/meta.json`
  (`_delta_attach_buffer_section`, 2026-10-01): one `stat` per BM25F query
  until then, a copy-on-write rebind of `_sections` under the load lock
  (never mutate the dict in place — concurrent legs iterate it), and a
  re-check that `_delta` is still the same object (a concurrent `reload()`
  wins). Gate off: `_delta is None`, the hook is never entered. Single writer per tantivy index
  (flock): only the ingest process may hold `BufferWriter`.
- **One delta-root resolver** (`resolve_delta_root`, O16 2026-10-01):
  explicit value > `SFU_DELTA_ROOT` > `<index_root>/delta`, literal `1` =
  `<index_root>/delta`. `load_if_enabled` returns None before resolving when
  the gate is unset/empty (gate-off unchanged) and resolves exactly as before
  when set. Writers pass `for_write=True`: refused (ValueError) inside
  `data/seismic_150m` (READ-ONLY, any spelling) and when the root is
  implicit and lands under the repository `data/` tree (9p). An explicit root under
  `data/thinclient_index` stays allowed (operator's choice).
- **Environment manifest wins.** A set `SFU_SEISMIC_SHARD_MANIFEST` (the documented
  one-env rollback) is honoured even when the delta layer has composed its
  own manifest; the retriever logs that delta shards are not served.
- **Non-W ids** (`<namespace>:<id>`) go to `docs_other` and have no remote
  abstract fallback: every delta generation writes hot sections.
- **Second query encode** when the buffer is non-empty
  (`_delta_merge_sparse` → `encode_splade`): a known cost (Q1 in the design),
  zero when the buffer is empty.

### M4 follow-up serving levers (09 §2 L3–L5, 2026-10-01)

Pre-registration: `docs/delta_ingest/09_M4_FOLLOWUP_PREREGISTRATION.md`.
Every gate is default OFF, only literal `1` enables, and with the gate unset
the code path is the pre-lever one. Findings: `spike/delta_ingest/M4F_FINDINGS.md`.

- **L3 routed abstract probes (`SFU_DELTA_ABS_ROUTE`, `retriever.fetch_abstracts`
  + `DeltaLayer.abstract_owner`).** Read once per retriever at `_load`
  (`self._delta_abs_route`). ON (and a delta layer loaded): the store loop
  skips every abstract store whose `_sections` entry carries `delta_origin`
  (base stores keep their order and run first, as OFF), then
  `_fetch_delta_abstracts_routed` groups the still-missing ids by owner and
  probes only `delta.section_key(gen, section)`; when that key has no store
  (a layout whose meta `section` column does not name a section directory) it falls
  back to every store of that generation. Ownership = the newest loaded
  generation whose `meta.sqlite` (`docs`/`docs_other`, same id encoding as
  `meta_rows`) holds the id and `superseded.get(id, gen) == gen`; one
  `SELECT id, section` per generation DB per call (no cache). Unowned ids
  (base, buffer, unknown) probe no delta store; buffer abstracts still come
  from `buffer_abstracts` (ledger), unchanged. A generation without
  `meta.sqlite` owns nothing (every published generation writes one).
  Known difference from OFF, by design: an id held by two generations gets
  the NEWEST copy's abstract ON and the OLDEST generation's OFF (store-order
  first hit); ids with one copy are identical (test
  `scripts/tests/test_delta_abs_route.py`). Unchanged both ways (pre-existing,
  recorded 2026-10-01): a superseded BASE id is answered by its base store
  first, that is, the stale base abstract, while `_meta_rows` serves the delta
  title. Store keys come from `DeltaLayer.section_key` (also used by
  `section_dirs`).
- **L5 grouped delta shards (`SFU_SEISMIC_DELTA_GROUP`,
  `sharded_seismic_backend.ParallelSeismicBackend`).** Positions come from
  `_delta_group_positions(manifest, n_shards)`, read once in the
  `ParallelSeismicBackend.from_manifest` override (the base classmethod is
  untouched; direct `__init__` construction never groups). `_fan_out`
  submits the group task FIRST (it is the likeliest slow task), then one task
  per base shard, and writes every result back to its shard's position, so
  `_shard_result_filter` (livedocs, position-indexed origins) and
  `_merge_topk` see the same per-shard list as ungrouped. Executor size is
  unchanged (one worker per shard; the group uses one). Fault boundary ON:
  `_guarded_search_one` wraps each shard search inside the group, so a
  raising/timed-out delta shard returns `[]` and alone is marked down; the
  per-shard timeout applies to each grouped shard in turn, so the group can
  take up to (#delta shards × timeout) in the worst case. Boundary OFF: a
  raise propagates from `fut.result()` exactly as from `executor.map`.
  Pinned by `scripts/tests/test_seismic_delta_group.py` (fake shards).
  Risk recorded in 09: the group becomes the slowest task when Σ delta
  traverse > slowest base shard.
- **L4 parse once (`SFU_BM25F_PARSE_ONCE`, `retriever._bm25f_leg`).** Read
  once per retriever at `_load` (`self._bm25f_parse_once`), so in-process
  arms with different environment variables stay independent. ON: per query, a list of
  `(schema, q_title, q_abstract)` keyed by tantivy `Schema` EQUALITY
  (`Schema` is unhashable in tantivy-py 0.26 — a dict key raises TypeError);
  a section whose schema equals an earlier one reuses its two parsed `Query`
  objects. Legal only because a tantivy `Query` carries field ids + terms,
  not index state (BM25 statistics come from the searcher at search time);
  pinned by `scripts/tests/test_bm25f_parse_once.py` (foreign-parsed query on
  a different-content index = own-parsed hits, ids/order/float scores; gate
  ON = OFF on `_bm25f_leg` with and without a year range). The buffer
  section participates like any other (its index is reloaded per query; the
  parsed query does not depend on the reload). Tokenizers are resolved by
  name at parse time: two indexes with an equal schema but a differently
  registered tokenizer under the same name would break the premise — every
  section here is built by `SectionBuilder` with tantivy defaults.

### livedocs (tombstone bitset, `livedocs.py`, item C 2026-09-29)

- **One bit per base ordinal, set = base copy masked** (deleted, or a newer
  delta/buffer copy exists). Format: 80-byte header (`SFULIV01`, version 1,
  nbits, popcount, crc32 of the payload, `ordinal_space_id`) + LSB-first
  payload. Written by `spike/delta_ingest/livedocs.py` via tmp + fsync +
  `os.replace` BEFORE `generations.json`, which names it with its crc32.
- **Fails closed.** Bad magic/version/length/crc, or an ordinal space id that
  differs from the arrays named in `generations.json["livedocs"]`, raises at
  `DeltaLayer` load: a bitset read against another ordinal space masks the
  wrong documents silently (ordinals.py hazard 1).
- **Delete versus superseded is derived, not stored:** a set bit on an id absent
  from `mask.superseded` means deleted everywhere (delta copies included); a
  set bit on a superseded id masks only the base copy. Ids with no base
  ordinal (non-W, or not in the base) stay in the JSON `mask.deleted` list.
- **Applied per shard BEFORE `_merge_topk`** through
  `_SeismicBackendBase._shard_result_filter` (default None = byte-identical
  path; installed only by `DeltaLayer.attach_seismic` when a bitset is
  loaded). Shard origin comes from the composed manifest order (base records
  first, then `delta_generation` records), keyed on the manifest requested
  before `SFU_SEISMIC_STAGE_DIR` staging; any other manifest is all-base.
  Without the per-shard hook, `filter_ids` applies the bitset post-merge
  (superseded ids kept there — S5 remains on that fallback path only).
- **Post-filter, not gather-time skip:** the filter shrinks a shard's k'
  list; the per-shard over-fetch is NOT raised. Exactness versus a deeper fetch is
  measured in `data/eval_results/delta_ingest_livedocs_20260929.json`.
- **Writer needs the base ordinal arrays** (`publish(..., ordinal_dir=)` or
  `SFU_THINCLIENT_ORDINALS` in the INGEST process, relative to the base index
  root); without them `publish` writes the pre-item-C JSON lists unchanged,
  and roots without a `livedocs` key are served exactly as before.
- **The ordinal arrays named by a bitset must be on local disk.** The
  W-id -> ordinal binary search over `wids.npy` (1.2 GB) measured ~0.7 s per
  100 cold ids on 9p versus ms locally (2026-09-29); the served per-shard filter
  costs p50 6.5 ms / 10.6 ms per query (empty / synthetic bitset, 800
  candidates, max 444 ms cold) —
  `data/eval_results/delta_ingest_livedocs_20260929.json`.

### Fold-in per-leg newest origins (doc 10 §3 G4, 2026-10-01)

Pre-registration: `docs/delta_ingest/10_FOLDIN_TRIGGER_PREREGISTRATION.md`;
writer side `spike/delta_ingest/foldin.py` + `ledger.py`; tests
`scripts/tests/test_foldin_masks.py` (every leg x origin, and a 2,000-case
equality check against the pre-G4 filter with no fold).

- **Origins are typed:** `None` = base shard, `int g` = delta generation g,
  `str "fold:s:k"` = fold k of base shard s. A composed manifest record with
  `fold_origin` (and no `delta_generation`) is a fold position. `delta_generation`
  wins when both are present (never written together).
- **Two newest maps, one per leg family.** `mask.superseded` stays the newest
  generation of the sections / meta / abstract copy; `mask.newest_by_leg.seismic`
  (`DeltaLayer.seismic_newest`) names the SEISMIC copy only where it is a
  published fold. Delta and fold positions resolve
  `seismic_newest.get(id, superseded.get(id, origin)) == origin`; base
  positions are unchanged. BM25F (`keep_hit`/`filter_hits`), `filter_ids`,
  `meta_rows`, `abstract_owner` never read `seismic_newest`.
- **The livedocs bit of a folded base doc stays set:** it masks the base
  tantivy/meta copy; at a fold position a set bit drops a doc only when the
  doc is in neither map (deleted).
- **Writer rule (ledger):** `seismic_origin` is set only by `publish-fold`
  for members whose `last_seen` equals the fold snapshot, and every re-stage
  resets it to NULL, so a doc updated after the fold is served from its newer
  delta copy and the stale copy in s′ is dropped.
- **`attach_seismic` also installs the per-shard filter without a livedocs
  bitset when a fold is served** (a fold position in the manifest or a
  non-empty `seismic_newest`): without it a folded doc would be served from
  s′ AND its delta generation. Without a fold it returns exactly as before
  (it may read the composed manifest once more, read-only).
- **No fold = byte-identical:** no `newest_by_leg` key is written (ledger
  `mask()` emits it only when non-empty) and no record carries `fold_origin`.

## source/lib/thinclient/ordinals.py

- Exists to contain two hazards (doc 18 §6): wrong-document filtering and
  silent document loss.
- **Every array validated full-length** — a short column is not a loud
  failure (`wids` complete, `year` truncated ⇒ queries filter against the
  wrong document's metadata); checking only wids missed exactly this on
  2026-08-02.
- **`encode_meta_id` must mirror `builder.encode_meta_id` EXACTLY**,
  including leading-zero rejection: accepting `"W0123"` would map onto the
  ordinal of the DIFFERENT document `"W123"`, pass the `found` check, and
  filter on the wrong document's metadata.
- **Sentinels**: NULL year stored as 0 and must not pass the `y != 0`
  filter (reproduces production `if not (year and …)`); an unknown type
  code can never equal a stored code, so an unseen filter value correctly
  keeps nothing.

## source/lib/thinclient/oa_overlay.py (O17 option (a), base is_oa bitmap, 2026-10-01)

- **Why it exists.** The base `is_oa` (meta.sqlite column, tantivy fast
  field, ordinal `is_oa.npy`) was never populated: 0 of 150,413,098 rows in
  the ordinal `is_oa.npy` built from the served meta.sqlite (2026-08-02 build,
  counted 2026-10-01). The bitmap overrides it without a reindex. Gate
  `SFU_OA_BITMAP` (`ENV_GATES.md`), default OFF.
- **Three states, never two.** known-OA / known-not-OA / unknown (base doc
  the source pass never saw: merged or deleted works, a partial pass).
  Unknown is `None` in the overridden meta row and in the hydrated `is_oa`
  field; the `open_access_only` filter keeps known-OA only. Never collapse
  unknown into False: that is exactly the never-populated defect again.
- **Addressing = base ordinals, fails closed.** Bits are indexed by the
  ordinal space's `wids.npy` order. The stamp names its ordinal directory; load
  refuses unless that directory's `ordinal_space_id` equals the bitmap's, the index
  manifest's `ordinal_space_id` (if any) equals it, and the served
  `<index_root>/meta.sqlite` has the size and `mtime_ns` recorded at build
  (the ordinal space was built from that file). A stale pairing would flag
  the wrong documents with no error (ordinals.py hazard 1). Missing
  `meta.sqlite` with the gate set also raises.
- **Retriever hooks (minimal).** `_bm25f_leg`: for base sections only
  (`delta_origin is None`) the tantivy `is_oa` term clause is dropped and the
  section is searched at `top_k * OVERFETCH_FILTERED`, then `keep_oa` keeps
  known-OA hits; delta sections keep the tantivy clause (their `is_oa` is
  real). `_meta_rows`: the override is applied to base meta rows only, after
  the delta-superseded rows were taken from the delta layer and before the
  dense-cache / delta fallbacks, so delta copies win (newest-wins).
  `_post_filter`: the ordinal fast path is bypassed for `is_oa` queries when
  the overlay is on (the ordinal `is_oa.npy` is the never-populated column);
  other filters keep it. `_hydrate`: `None` passes through only when the
  overlay is on, so gate-off output is unchanged even if a meta row held NULL.
- **Rerank coupling.** `reranker._score_fulltext` reads the hydrated
  `is_oa`, so gate ON changes the composite rerank score of base docs that
  become known-OA (measured effect: `spike/delta_ingest/OA_BITMAP_FINDINGS.md`).
- **Ingest.** `BaseSeeder` uses the bitmap state where known when seeding base
  hashes, so an is_oa-only difference no longer classifies an in-base work as
  updated; unknown keeps meta's value (pre-bitmap behaviour).
- **Builder** (`spike/delta_ingest/oa_bitmap.py`): one unit file per source
  unit, committed by `os.replace` (presence = done, so the pass resumes);
  finalize replays units in name order, so a later `updated_date` partition
  wins for a work present twice. `bitmap_id` = sha256 over ordinal space id +
  both bit arrays (16 hex), used in the result-cache key.

## source/lib/thinclient/builder.py

- **Mid-slice meta commits + WAL TRUNCATE**: per-slice truncate alone was
  insufficient (measured 2026-06-13: a section's ~2 h slices grew
  uncommitted `-wal` to 5.8G/5.3G, ~11G across 3 workers → page-cache
  eviction → swap-thrash on the 31G host). A plain commit only does a
  PASSIVE checkpoint (leaves `-wal` at high-water); TRUNCATE fully
  checkpoints (no concurrent readers here). Mid-slice commits are safe
  because meta rows are idempotent `INSERT OR REPLACE` and only the meta db
  is touched — tantivy (BMP until 2026-10-11) still commits at the slice boundary, so the
  atomic-slice resume model is unchanged.
- **v2 meta schema**: W-ids as INTEGER PRIMARY KEY (rowid alias, varint) —
  measured 166.8 → 99.4 B/doc versus TEXT (~10 GB at 150M); non-`W<digits>` ids
  go to `docs_other` TEXT table. WAL + `synchronous=OFF` is
  crash-consistent to the last commit, not power-safe (fine: every observed
  failure is a process kill).
- **Resume protocol**: everything up to the last recorded slice is durable
  (the BMP-era `next_shard` key is no longer written and is ignored in older
  progress files, 2026-10-11). A crash between the tantivy
  commit and the progress-file write means the first re-fed slice may
  already be committed — the first `add()` probes for its doc and skips
  tantivy adds if found.
- **int8 rescore matrix**: symmetric scale, vectors L2-normalized (‖x‖≤1) —
  must stay byte-identical to `dense_cache.py` quantization so scores are
  comparable.

## source/lib/thinclient/ — other

- `sections.py`: section list is (name, vocabulary) in priority order —
  keep in sync with the measured eval. Era sub-sections
  (`sections/<base>__<era>/`) are the PRIMARY locality axis; the export
  spool stays keyed by BASE section (era routing happens at build time from
  `publication_year`, so in-flight exports are unaffected). Persona → HOT
  sub-sections (live abstract sidecar); everything else COLD (packed
  zstd-19 archives, no local abstracts).
- `dense_cache.py`: quantization byte-identical to
  `builder.build_dense_leg`; RAM tier rebuilt from SQLite (durable truth)
  at startup; `ENCODE_BATCH = 32` (measured ~87 docs/s CPU).
- `dense_cache.py` v2 levers (2026-09-25), both default-inert: the mutable
  usearch delta index (`SFU_DENSE_DELTA_USEARCH_MIN`) is a *candidate*
  engine only — the returned scores are still the exact int8 rescore, so
  they stay comparable with the seed leg's, and `ANN_OVERFETCH = 4`
  compensates for HNSW's approximate candidate cut (measured recall@10 versus
  exact: 0.914 at 10k, 0.990 at 100k, 0.972 at 500k). It fails OPEN: a
  usearch error disables the lever for the process and brute force (always
  correct) continues. `ANN_EXPANSION_ADD/SEARCH = 128` — usearch's 64/64
  default measured 0.995 recall@10 at n=50k for the same latency.
  `make_onnx_encoder` checks the export path BEFORE importing
  onnxruntime/transformers (an enabled gate with a missing export must not
  pay a 75 s import to decide to fall back).
- `dense_delta_merge.py`: the merge is a BULK REBUILD, never an incremental
  `add()` into the served graph — that is what erases HNSW insert-order
  debt (query-correlated insert order is the documented bad case,
  arXiv 2405.17813). It fails CLOSED (nothing written) on any
  ids.json/rescore/b1/manifest disagreement, holds an `O_EXCL`
  `dense/.merge.lock` so two merges cannot interleave, and writes
  `<name>.tmp-<pid>` + fsync + `os.replace` per artifact. The three renames
  are not one atomic group: the ORDER (rescore → b1 → ids) is the
  invariant, and the delta is truncated only after all three land, so a
  crash costs a re-merge, never a document. Seed bits come from
  `Index.get` (exact), NOT from `rescore > 0` — int8 rounding loses the
  sign of |x| < 1/254, so a rescore-derived rebuild would silently differ
  from the served seed.
- `doc_encoder.py`: SPLADE pooling = `log(1+ReLU(x)) * attention_mask`,
  max-pool over sequence (must match the query encoder). `SPARSE_TOP_K =
  256` per doc. With the TRT EP, keep ORT's CPU pool tiny and non-spinning —
  a busy-spinning full-width pool starves the GPU (measured 3.5k → 960
  docs/s regression); tune via `SFU_ORT_INTRA_THREADS`.
  The class attribute `backend` is the REQUESTED backend and is never
  renamed (results files and M6 comparisons key on it); every instance also
  sets `runtime_backend` from what actually runs — `torch_runtime_label`
  (parameter dtype + device type, for example, `pytorch_fp32_cpu`) or
  `ort_runtime_label` (first active ORT provider, for example,
  `onnxruntime_cuda_iob_fp16` when the TensorRT EP failed to load). Record
  both in results (O8, 2026-10-01; test
  `scripts/tests/test_doc_encoder_runtime_label.py`).
- `seismic_backend.py`: `seismic.save()` APPENDS `.index.seismic` to the
  path given; search returns `[(query_id, distance, doc_id), …]`; query
  shaping matches the serving retriever's constants.

## source/sfu_library_mcp_http.py (serve app)

- **Warmup**: retrieval lazy-loads on first `/api/search` (measured 2m24s
  cold, 2026-07-18); one background thread runs a real structured search at
  startup so every model loads sequentially (no concurrent-load meta-tensor
  race — `lib/hf_load_lock.py`) and `/health` reports `warm`.
  `SFU_HTTP_WARMUP=0` disables (then `warm` reports true immediately,
  matching the pre-warmup contract). Warmup battery is small and
  subject-diverse — each distinct query faults a different forward-index
  region; on native FS those pages stay resident (measured warm p50 ~82 ms).
- **Cache-hit attribution MUST use `contextvars.ContextVar`, NOT
  `threading.local`** (HOST-NOTE-W7-1, 2026-07-18): all asyncio requests
  share one event-loop thread, so a threading.local is process-global —
  request A's `finally: reset` could clear the value between B's set and
  B's `log_serve_query`, mislabeling B's cache_hit. Reset to None after use
  so nothing leaks across requests.
- **Pre-seed primer**: runs STRICTLY AFTER the warmup battery, sequentially
  (concurrency 1 — never a parallel burst on the single-GPU cross-encoder
  the served path uses). Idempotent (primes misses only). Primes with the
  demo's default request shape (limit=50, no filters) so the planted key
  matches a real landing-screen click, routed through
  `result_cache.read_through` — the SAME path `api_search` takes (a bare
  `search_academic_structured` call would bypass the cache wrapper).
- **Cache is aside, never load-bearing**: a cache read failure must never
  fail a search — fall through uncached (and stop using the cache for the
  process); store failure non-fatal. Store only on a clean, non-degraded
  success: WI-9 leg-breaker (`router.last_degraded`) and WI-13 BM25F
  silent-fallback surface as degraded notes; warmup must be complete so a
  half-loaded cold state isn't frozen for the TTL.
- **`/health` semantics**: `warming → false` (GUI shows warming message);
  warm/failed/disabled → true (server answers, possibly cold) — consumed by
  `web/lib/api.js`. Shedding flag: absent ⇒ not shedding (added WI-11).
- **`SFU_SEQUENTIAL_MODE=1`** is set by the Windows START.bat in the
  Run-from-USB bundle; the web UI defaults its one-at-a-time search queue ON
  from this. Absent/0 on normal installs.
- **Static GUI served only if the bundle is present** (keeps the server
  usable headless/index-only).
- `force_literal` request override (WI-19b) exists so the bench can measure
  predictor-vs-literal in ONE serve lifetime (no ~5-min re-warm restart to
  flip `SFU_SPECULATE_LITERAL` between legs on 9p).

### Engagement + analytics (`lib/engagement.py`, `lib/analytics.py`, `web/lib/api.js`, 2026-10-12)

- **ACTION_TYPES / KINDS parity:** `ACTION_TYPES` and `KINDS` in `lib/engagement.py`
  must equal the `ENGAGEMENT_ACTION_TYPES` / `ENGAGEMENT_KINDS` array literals in
  `web/lib/api.js`. The client drops events the server would reject, so a type added on
  one side only is silently lost. Pinned by `source/tests/test_engagement_gui.py::
  test_client_server_vocabulary_parity` (regex on the JS literal: keep it a one-line
  `const NAME = [...];`) and the jsdom check "client ACTION_TYPES/KINDS identical".
- **Server-session exclusion:** `tools._log_query` impressions use session id
  `"server"` (`analytics.SERVER_SESSION`). `analytics.engagement_source()` is the one
  place that decides which writer `position_bias` and `session_replay` count: GUI rows
  win whenever any non-server impression exists; the panels say which in `"source"`
  (`gui` / `server` / `none`). A GUI must never use the session id `"server"`; GUI ids
  start with `g-`. Impression rows never open a `session_replay` session.
- **Keepalive flush:** the GUI posts `{"events": [...]}` batches of ≤ 50 events with
  `fetch(..., {keepalive: true})` (64 KB in-flight budget per page: 50 events × ~250 B
  fits) and `navigator.sendBeacon` on `pagehide`. A beacon body arrives with a
  `text/plain` content type; the `/engagement` handler parses the body regardless of the
  content type (`request.json()`) and must keep doing so. The client never throws, never
  awaits the post, and queues nothing while the backend is in mock mode (`noteSource`
  in `api.js`: the last `/health` or search answer decides).
- **Analytics bundle is read-only and figure-complete:** every number the analytics app
  shows comes from a bundle panel; `index_shape` reads `<index root>/manifest.json`
  (never writes), so a missing manifest yields `{"status": "stub"}`, never an
  exception.


### Draft → final search stream (`/api/search_stream`, lever #2, 2026-09-25)

Gate `SFU_SEARCH_DRAFT_STREAM` (default OFF; forced off under
`SFU_SEQUENTIAL_MODE`). Tests: `source/tests/test_search_draft_stream.py`,
`scripts/verify_web_jsdom.mjs` (draft-swap cases).

- **Final = `/api/search` bytes.** The `final` SSE event's data is the
  `JSONResponse` body of the SAME helpers `api_search` runs
  (`_search_cache_lookup` → `_search_cache_miss`): same cache read-through,
  same hit/miss/store/bypass counters, same cacheability rule, same
  serve-log hit row. Never build a final payload any other way. A failed
  final goes out as `event: error` with the `/api/search` 500 body.
- **The draft is never cached** and never mutates result-cache counters. It
  is the retriever's public `search(mode="bm25f")` run in the default
  executor (NOT under `tools._request_semaphore`, so it cannot delay the
  final), labelled `preliminary: true`.
- **Cache hit ⇒ final only**; a draft that completes after the final is
  dropped; a draft that raises is dropped silently (the final still ships);
  no thin-client retriever / federated path off ⇒ final only.
- **Side effects the draft does have** (design §5 risks 2/4): its BM25F leg
  advances the process-global leg metrics, so a streamed miss's serve-log
  `leg_ms.bm25f` can include the draft leg when the two overlap; its
  `_hydrate` enqueues into the dense warm cache (inert while
  `SFU_DENSE_LEG` is off). Take gap/leg measurements gate-OFF.
- **Client: idle-only swap** (`SFUApi.createDraftSwapController`). Draft
  cards carry a visible "Preliminary" label; the final list replaces them
  only after `idleMs` (1200 ms) with no mousemove/scroll/wheel/key/pointer
  activity and no non-empty text selection. A hovered card is pinned at its
  on-screen index in the swapped list; if the hovered card is absent from
  the final, the swap waits for the hover to leave. After a pinned swap the
  exact server order is applied on the next idle window. Load-more is off
  while a draft is shown. Reshuffle metric = |draft top-10 \ final top-10|
  / |draft top-10|, recorded client-side in `SFUApi.draftStreamStats()`.
  The GUI uses the stream only when `/health` reports
  `search_draft_stream: true` and `sequential: false`, and only for the
  first page with the queue off; any non-200 from the stream falls back to
  `/api/search`.

## source/lib/result_cache.py

- The index is STATIC between updates, so an hours-long TTL is correct — an
  entry only goes stale on an index/model swap, which the versioned key
  handles by construction (new stamp → new key). Typical response ≈ tens of
  KiB × 256 entries ≈ low single-digit MiB; the memory cap is a backstop,
  not the sizing lever.
- **Key field order is FIXED — never reorder without bumping the leading
  version tag** (old-order keys would silently collide with new ones). A
  non-thinclient or not-yet-loaded serve caches under a stable `"unknown"`
  stamp (better than failing the search).
- Never cache an empty error-shaped payload (no results + index-unavailable
  notice) — don't freeze "looks broken" across the TTL.
- **Delta stamp (R1, 2026-09-29).** When `SFU_DELTA_ROOT` loaded a delta
  layer (`tc._delta` not None), the key stamp gains
  `@delta=<generations.json stamp>#<epoch>~<ledger>,<ledger-wal>,<buffer meta.json>`
  (`_delta_stamp`): the in-memory published stamp, a process-local epoch per
  `DeltaLayer` instance (every `retriever.reload()` rotates the key, even for
  two publishes in the same second, whose stamps collide), and
  `mtime_ns.size` `os.stat` signatures of the files the live buffer is read
  from. Cost: 3 `stat` calls, no file read, no directory scan (18 µs/key
  measured 2026-09-29). **With the layer off the key is byte-identical to the
  46ec1182 recipe** (pinned by `source/tests/test_result_cache.py::TestDeltaStampR1`)
  — never add a delta term on the gate-off path. `_delta_stamp` must never
  raise: an exception in `_manifest_stamp` falls back to the shared
  `"unknown"` stamp, which would keep serving pre-publish results. A publish
  is only served (and only rotates the key) after `retriever.reload()`; any
  ledger write, including non-buffer bookkeeping and WAL checkpoints,
  rotates the key while ingest runs (over-invalidation by design).
- **OA bitmap stamp (O17, 2026-10-01).** When `SFU_OA_BITMAP` loaded an
  overlay (`tc._oa` not None), `@oa=<bitmap_id>` is appended after any
  `@delta=` suffix, so a rebuilt bitmap rotates the key. With the gate off
  nothing is appended (key unchanged). Pinned by
  `scripts/tests/test_oa_bitmap.py::test_result_cache_key_rotates_with_bitmap`.

## source/lib/speculation.py (WI-18)

- Candidate pool = landing examples (read from `web/source/search.jsx` SOURCE —
  authoritative over the compiled artifact) + seed/bench query files +
  distinct serve-log queries (only when `SFU_SERVE_QUERY_LOG_RAW=1` was on
  at log time — raw is OFF by default, so usually empty). Deterministic
  string matching, recency/frequency tiebreak, NO ML.
- Bench queries are deliberately NOT pre-seeded by the primer, so a bench
  query is cache-COLD on a freshly primed serve and a speculation that
  primes it is a real win.
- Matching: word-boundary containment (a match must end at a word boundary
  or run to the candidate's end); a match too close to the typed text adds
  little information → treated as ambiguous (`SFU_SPECULATE_MIN_RATIO`, default
  0.35 = predicted ≥ 1.35× typed length).
- **One in-flight speculation**: the slot holds the running asyncio Task; a
  request arriving while busy is DROPPED, never queued (term 4);
  `_slot_lock` guards the swap, re-checked under the lock.
- Log semantics: a speculation that's a cache HIT is `cache_hit=true` AND
  `speculative=true`; a fresh store is `cache_hit=false` +
  `speculative=true`; `speculative` absent for ordinary traffic so analytics
  stays uncontaminated. No-match suppression is recorded under its own
  reason and does NOT bump `suppressed_by_guard` (that counter is for term-3
  guards only).

## source/lib/serve_query_log.py (WI-2)

- Staging-on default: unset environment ⇒ on; an explicit `production` profile is
  the only thing that defaults OFF (defense-in-depth — production operations must opt
  in).
- Log fields: `leg_latency_ms` = wall ms per leg in fusion order;
  `cache_hit` is tri-state (absent when cache off); `speculative` absent for
  ordinary traffic. Append mode so a restart resumes the file; bytes
  tracked for rotation (live + `.1`). A bad log path must never break a
  query; a full queue drops+counts (the daemon thread exits with the
  process).
- Repo-root discovery is by `parents[N]` index — `source/lib/` files use
  `parents[2]`, `source/lib/thinclient/` files use `parents[3]`; breaks on
  file moves.

## source/lib/reranker.py + tools.py (pipeline)

> LambdaMART tier (`rerank_with_lambdamart`, `lambdamart_features.py`, `lambdamart_enabled`,
> `SFU_LAMBDAMART_MODEL_PATH`) removed 2026-10-11: the model file never existed in this container.

- Scoring weights dict must sum to 1.0.
- **Production doc shape**: `tools.py` passes `normalize_work()` output —
  keys differ from raw API (`"date"` not `"publication_year"`, flat author
  strings, `"is_oa"`/`"oa_url"` un-nested). The reranker and query logger
  read different keys (`_normalize_for_rerank` reads `date`, `_log_query`
  reads `publication_year`); `year` retained for back-compat.
- **Two distinct RRF constants**: reranker's upstream-position+embedding RRF k
  is separate from `federated_search._RRF_K=60` (tuned separately via Q1.1
  sweep) — do not "deduplicate".
- CE model: SFU fine-tuned v1 preferred (Q3.2: +9.5% NDCG@10 / +0.069
  MRR@10 over base on the original 120-query judged eval), base MS-MARCO
  fallback so the reranker never silently breaks. **OPEN question**: the
  fresh judged serve-path eval (2026-08-19) measured base ABOVE v1 (0.8069
  versus 0.7904, paired −0.0165, CI excludes 0) — `SFU_CE_MODEL_PATH` flips;
  operator decision pending.
- CE int8 ONNX is OPT-IN (`SFU_CE_ONNX=1`, default OFF): at serve shape
  (batch 20) torch measured 11.8 ms versus int8 ONNX 52 ms on 16 cores
  (2026-08-19); the export's 19× win is per-pair batch=1 and only pays on
  single-stream/low-core deploys. Explicit intra-op threads halve ORT's
  default 104 ms to 52 ms.
- **Fixed-shape scoring (2026-09-25, owner decision §7 item 1 of
  `SPECULATIVE_RETRIEVAL_UPGRADES.md`).** Every stage-1 embedding and every
  CE score on the serve path goes through one fixed tensor shape, so a
  (query, text) score is a pure function of (query, text, model, device) and
  never of what else shares the call:
  - CE: `reranker._ce_score_pairs` is the only way the pipeline calls the CE
    (gate off and gate on alike). Pairs are cut into chunks of
    `_CE_BATCH` = **10**; a short chunk is filled with `_CE_PAD_PAIR`
    (`("", "")`) rows whose scores are discarded (dummy-pad rule: pad rows are
    appended after the real rows and their outputs are sliced off; never
    reorder). Each chunk is tokenized with `padding="max_length"`,
    `truncation="longest_first"`, `max_length` = min(`_CE_SEQ_LEN` = **256**,
    the model's `max_seq_length`) and run through the HF model directly
    (`CrossEncoder.predict` pads to the batch's longest pair, which is what
    made scores batch-dependent). **Per-row head on CPU** (`_ce_logits`): the
    encoder runs batched, but on CPU the BERT pooler + classifier run on one
    `(1, hidden)` row at a time — their GEMMs have M = batch, and a small-M
    CPU GEMM gives a row different bits by position (measured 2026-09-25 at
    batch 10: rows 8–9 differed from row 0 by 9.5e-7). On CUDA the batched
    head measured bit-identical at the fixed shape and the per-row loop cost
    ~5 ms per call, so CUDA runs the plain forward — re-verify with
    `ce_batch_invariance_check.py --mode fixed` on any new GPU/driver.
    Architectures without a `pooler` + `classifier` run the plain forward
    (both serving CEs are BERT). The
    model's activation (`activation_fn`, Identity for v1) is applied as
    `predict` would. The int8 ONNX wrapper pads
    to `max_length` itself and is fed the same chunks. A backend returning a
    different row count raises (the CE stage falls back to the pre-CE order).
  - Stage-1: `embedding.encode_texts` chunks into `_EMBED_BATCH` = **11**
    (query + 20 pooled docs = exactly 2 chunks; a ≤10-doc remainder + query =
    1), fills with `_PAD_TEXT` (`""`), tokenizes with `padding="max_length"` to
    min(`_FIXED_SEQ_LEN` = 256, `max_seq_length`), runs `model.forward` and
    L2-normalizes each row. `compute_similarity` takes each cosine as
    `math.fsum` of the float64 elementwise products (exactly rounded, so it
    cannot depend on BLAS blocking or row count).
  - 256 = both serving models' configured max length (CE v1 and embed v5), so
    fixed shape truncates exactly what the old longest-padding path did
    (tokenization of real serve pairs checked identical, pads stripped).
  - **Thread count is not pinned**: fixed-shape scores measured bit-identical
    at torch intra-op threads 1 / 8 / 16 on CPU
    (`data/eval_results/ce_batch_invariance_fixed_cpu_t{1,8,16}_2026-09-25.json`).
    CPU and CUDA scores differ from each other (~6e-6 CE) — irrelevant because
    draft and verify run in one process on one device; do not compare or
    cache scores across devices/processes.
  - **Measured 2026-09-25**: 120/120 topics identical top-10 order old versus
    fixed-shape scoring (max |Δ| CE 9.2e-6, stage-1 3.9e-7) and gate-on
    byte-identical to gate-off 120/120 (`scripts/experiments/eval_fixed_shape_parity.py`,
    `data/eval_results/fixed_shape_parity_2026-09-25.json`).
  - Changing `_CE_BATCH`, `_EMBED_BATCH`, either seq-len constant, the pad
    row, or reintroducing `predict`/`encode` on the serve path moves gate-off
    floats and breaks per-candidate reuse parity: re-run
    `scripts/experiments/ce_batch_invariance_check.py --mode fixed` and
    `scripts/experiments/eval_fixed_shape_parity.py`.
- **Pipeline width invariant**: Stage-1 must hand later stages a pool wider
  than `limit` (≥ `_CE_CANDIDATE_POOL`=20) so rank-11..20 docs can be
  promoted.
- Engagement impressions are emitted independently of the query
  log: they are the per-rank propensity denominators for the analytics
  position-bias panel. Latency clock starts BEFORE the router call so
  retrieval time is included in logged latency. Q2.3: `subject_hint` was
  previously never passed (dead-wired) — fixed so Q2.1/Q2.2 routing rules
  fire.
- CSV export follows RFC 4180 (quote on comma/quote/CR-LF so embedded
  newlines stay in one field).

### Metrics log ids/session (`tools._persist_metric`, 2026-09-25)

- `ids` travels by side channel only: `handle_tool_call` binds a fresh list
  in the `_metric_ids_var` ContextVar; handlers call `_note_result_ids` /
  `_note_doc_id` / `_note_metric_ids`, which fill it (capped at 10) and never
  touch the returned `TextContent`. Tool text output MUST stay byte-identical
  whether or not the log is on (`test_output_text_unchanged_by_metrics_log`).
  Outside `handle_tool_call` (GUI `search_academic_structured`) the notes are
  no-ops.
- Id choice: `normalize_doi(work["doi"])` when non-empty, else
  `openalex_id` (S2 fallback: `paperId`); doc-level tools log
  `[normalize_doi(arg)]`, noted right after argument validation so a failed
  remote call still records which doc was asked for. `ids` is `null` when
  nothing was noted.
- `ids` is noted where the handler already holds the final ranked list
  (after `_maybe_rerank`); executor-thread code (`_fetch_europe_pmc`) cannot
  see the ContextVar, so it fills an explicit `ids_out` list instead.
- `session`: module-level `_PROCESS_SESSION_ID` (8 hex) unless
  `set_metric_session` bound one; `sfu_library_mcp_http.call_tool` binds the
  `mcp-session-id` header (truncated to 64 chars) and resets it in `finally`.
  Header lookup never raises.

## source/lib/speculative_rerank.py (lever #1, `SFU_SEARCH_SPECULATIVE_RERANK`)

- **Parity strategy = per-candidate reuse over fixed-shape scoring
  (2026-09-25; replaced exact-batch memoisation, commit 829d8062).** The
  draft records each model call as (key, items, future): stage-1 key
  `("embed", query, model_path)` with items = the document texts, CE key
  `("ce", id(ce))` with items = the (query, text) pairs. The real pass looks
  up every item it needs in the recorded calls under the same key, reuses
  those drafted scores (waiting on the call's future if it is in flight,
  30 s cap, a failed/short future is ignored), scores only the de-duplicated
  remainder with one ordinary call (itself fixed-shape), and splices results
  back in request order. Byte-parity with gate-off rests entirely on
  "Fixed-shape scoring" (§reranker above): each item's score is independent
  of its call. If the remainder call returns the wrong length (for example, `[]` on
  embed failure) that value is returned as-is, exactly what gate-off would
  have got from the same failing model. Pinned by
  `source/tests/test_speculative_rerank.py`, whose fakes shift every row by an
  amount keyed on the call's padded shape: under fixed shape parity holds
  (`test_gate_on_output_byte_identical_to_gate_off`,
  `test_fixed_shape_makes_per_candidate_scores_bit_stable`); with
  longest-padding fakes the same sequence diverges
  (`test_per_candidate_reuse_breaks_without_fixed_shape`,
  `test_fakes_are_batch_sensitive_without_fixed_shape`).
- **Counters are per candidate**: `embed_hits`/`ce_hits` = items served from
  the draft, `embed_misses`/`ce_misses` = items scored on the request path,
  `embed_calls_skipped`/`ce_calls_skipped` = real passes that made no model
  call at all.
- **Gate-off unchanged.** `is_enabled()` is literal `"1"` only. Off: the
  router never calls `on_draft`, `_maybe_rerank` calls `_maybe_rerank_impl`
  directly, and `speculative_rerank.current()` is None so the two reranker
  hooks make the plain fixed-shape calls (`compute_similarity`,
  `_ce_score_pairs`) — gate-off is unchanged relative to fixed-shape scoring,
  which itself moved gate-off floats once on 2026-09-25
  (`test_gate_absent_takes_no_speculative_path`).
- **Draft pool** = `_rrf_merge(bm25f_results, [], top_k)`, that is, the list the
  router would return if the SPLADE leg added nothing. The draft runs
  `_maybe_rerank_impl(pool, query, top_k)`; `limit` does not enter any key
  (stage-1 embeds the whole pool, CE scores the stage-1 top-20), so the
  caller's `limit` is not needed.
- **Binding is by list identity**: `bind()` registers `id(fused)` with a
  strong ref to the list (so the id cannot be recycled while registered);
  `consume()` takes the entry only if `entry[0] is docs`. Registry is LRU
  32; an evicted handle is closed. Entering `consume()` closes the handle:
  the draft registers no new call afterwards, so every future the real path
  can wait on is already computing (wait bounded by one call; 30 s safety
  timeout falls back to computing).
- **Early draft CE (2026-09-25).** With the CE enabled the draft job starts
  `rerank_with_crossencoder(pool, query, _CE_CANDIDATE_POOL)` on a second
  thread (`sfu-spec-rerank-ce`) at the same moment as the stage-1 draft, so
  the CE batch no longer waits behind the stage-1 embedding. Sound because
  the CE pair text is `title + abstract` of each doc, independent of the
  stage-1 order, and the draft pool (≤ `top_k` = 20) is the whole CE pool.
  The two drafted calls are independent futures; the real stage-1 and the
  real CE each consume their own as soon as it is recorded. When the draft's
  own pipeline reaches its CE call it first waits for the early batch (30 s
  cap) and, if that batch scored every pair it needs, ends the job
  (`draft_ce_covered`, not `abandoned`); otherwise (early batch dropped on
  the slot, abandoned or failed) it falls back to the old in-pipeline draft
  CE call, so the two draft CE calls never overlap. The job releases the
  single draft slot only after joining the early-CE thread. Counters:
  `draft_ce_batches` = draft CE calls registered (early or fallback),
  `draft_ce_early` = those from the early thread; `drafts_started −
  draft_ce_batches` = drafts that never ran a CE batch;
  `draft_ce_dropped_slot` counts each attempt (early + fallback can both
  count for one draft). Pinned by `test_draft_ce_starts_before_stage1_finishes`,
  `test_real_pass_reuses_early_ce_while_draft_stage1_in_flight`,
  `test_early_ce_skipped_when_crossencoder_disabled`.
- **Single slot** (WI-18 term 4 discipline): one draft job process-wide; a
  draft while busy is dropped (`dropped_busy`), never queued. `CE_SLOT`: a
  draft CE batch starts only if no real CE pass is active (else the draft is
  abandoned, `draft_ce_dropped_slot`); a real pass arriving during a draft
  batch waits for that one batch (`real_ce_waited`). Real passes still
  overlap each other exactly as before. Only gate-on requests take the slot.
- `_Abandon` subclasses `BaseException` so the pipeline's own
  `except Exception` fallbacks do not swallow it and log "Reranker failed"
  from the draft thread. Any other draft error is swallowed
  (`job_errors`); `on_draft`/`bind`/`consume` never raise into a search.
- **Counter honesty**: the draft thread touches neither the result cache,
  the serve query-log nor the WI-18 `speculative` ContextVar, so
  `cache_hit`/`speculative` semantics are unchanged
  (`test_speculation_does_not_touch_wi18_or_cache_counters`). Counters live
  in the module dict `counters()`; `candidates_accepted /
  candidates_drafted` is the doc's acceptance rate, `embed_hits /
  (embed_hits + embed_misses)` (and the CE analogue) the reuse rate.
- **Hydrate scope (lever #0) in the router**: both LOCAL_RRF legs run inside
  `getattr(retriever, "hydrate_scope", contextlib.nullcontext)()`, entered
  once per request and exited before the router returns (non-thinclient
  backends get the null context). The draft thread never hydrates and a
  `threading.Thread` does not inherit the scope's ContextVar, so the draft
  cannot depend on the memo
  (`test_router_enters_hydrate_scope_once_per_local_rrf_request`).

## source/lib/federated_search.py

- **Q2.1 zero-coverage subjects**: 15 subjects with 0.0 local NDCG@10 in
  the 120-query judged benchmark — local index holds nothing useful; always
  route live. **Q2.2 soft-live subjects**: OpenAlex live outscores local
  RRF (for example, Anthropology 0.931 versus 0.898); prefer live, `prefer_local`
  overrides (offline/air-gapped).
- The subject detector is a pragmatic keyword table, NOT a classifier —
  only routing-relevant subjects are listed (any other subject routes LOCAL
  anyway); longer phrases first per subject; word-ish boundary check for
  short tokens (`"law"` must not match `"flaw"`); returns `""` (LOCAL) on
  no match. Do not "complete" it.
- RRF beats either retriever alone (+5.1% NDCG@10 versus BM25; average BM25↔SPLADE
  overlap 7.5% — near-orthogonal result sets; P.11 eval 2026-05-15:
  local_rrf 0.2723 versus BM25 0.259 / SPLADE 0.2586).
- The router coordinates two independent backends and must never crash the
  calling handler (clients narrow their own exceptions; the router's broad
  except is deliberate).
- **Routing is either/or** (2026-10-29): a query is answered by the live
  OpenAlex leg OR the local legs, never a fusion of both. Local hits carry
  `source="thinclient"`; live hits carry the journal display name.
- **Date rules read every date filter** (2026-10-29): `requested_range()`
  reads `publication_year` (`"2024"` / `"2020-2024"`), then
  `from_publication_date` / `to_publication_date`. `tools.py` writes a
  `publication_year` range when BOTH `year_from` and `year_to` are set, so
  a router that read only `from_publication_date` never routed that case
  live (the pre-2026-10-29 defect).
- **Coverage-aware date routing** (2026-10-29): with a retriever exposing
  `coverage_end()` (ThinClientRetriever: manifest `built` day, or the delta
  layer's publish day when later), a requested range that starts after the
  coverage end routes live at any window, and a range that ends on or
  before it never routes live by date. Only then does the
  `SFU_FEDERATED_RECENCY_DAYS` start-date window apply. The rule retires
  itself as coverage freshens (monthly rebuild, delta ingest); the window
  stays the owner's knob for the partially-covered open-ended case
  (`year_from=<this year>` with a June build). Routing effect on ranking
  quality: IMPLEMENTED, EFFICACY UNMEASURED (no date-filtered judged set).
- **Year cues follow the calendar** (2026-10-29): `temporal_cues(today)`
  compiles the fixed cue words plus the current and previous calendar
  years (lru-cached per year); no literal year may be re-added to the
  pattern. The bare words `new` and `current` are known false triggers
  ("New Zealand", "electric current") — recorded, not changed.
- **Live failure falls back to the local route** (2026-10-29): the
  OpenAlex client never raises — `_get` returns None on budget, breaker,
  429 storm, 4xx (a bad key is a 401, swallowed as not-found) and
  transport failure — so `search_works` answers
  `{"results": [], "meta": {"count": 0}, "degraded": True}` in that case.
  The router treats that flag, or an exception, as a live failure:
  re-routes the same query to LOCAL_RRF (or LOCAL_INDEX when RRF is off)
  and sets `last_live_fallback`; `tools.py` prefixes the
  `_LIVE_FALLBACK_NOTE`. A genuine zero-hit live answer (no flag) is NOT
  a fallback. `last_degraded` keeps its meaning (local legs unavailable)
  and is set only if the fallback itself fails. Before 2026-10-29 a live
  failure returned an empty list with no notice (observed 2026-10-29: a
  key with a trailing CR from a CRLF `.env` gave 401 → silent empty).

## source/lib/opensearch_retriever.py (query encoders)

> The `OpenSearchRetriever` class was archived 2026-10-11 to
> `scripts/archive/opensearch_era/opensearch_retriever.py`; this module keeps only the live
> SPLADE/dense query encoders.

- SPLADE ONNX export carries the exact indexer weights; the matching
  bert-base-uncased WordPiece tokenizer (30522 lowercase tokens) lives in
  the model directory or any SFU embed model directory (identical vocab); mirrors
  `scripts/mine_hard_negatives.py::SpladeOnnxEncoder` (verified to
  reproduce indexed `sparse_field` weights). Bare HF hub ids no longer work
  in the serving container.
- **`HF_LOAD_LOCK` must cover the imports too**: `from transformers import
  X` races transformers' lazy-module init when another leg's thread is
  inside a `sentence_transformers` load (observed as spurious ImportError,
  2026-07-18) — parallel federated legs make this a first-query event.
- Archived 2026-10-11 with the class (OpenSearch decommissioned 2026-06-11): the SPLADE
  query was `bool.should` with per-term `rank_feature` + log scaling
  (`scaling_factor=4`, top `max_terms` by weight), and the OpenAlex id was the
  OpenSearch `_id` so RRF fusion / judged-doc grading keyed on it consistently.

## source/ MCP entrypoints & misc

- `sfu_library_mcp_server.py`: logging goes to stderr, NEVER stdout — MCP
  uses stdio JSON-RPC and stdout writes corrupt the transport. Server name
  stays `"sfu-library"` (pinned by client configurations and the
  `.bat`/`.ps1` launchers). The 2026-10-10 Duck Library rebrand left it
  unchanged on purpose; renaming it is an owner decision listed in
  `docs/infrastructure/REBRAND_DUCK_LIBRARY_2026-10-10.md`.
- Rebrand compatibility aliases (2026-10-10, removable only once no client
  or script calls the old names):
  - `tools._dispatch_tool` maps the legacy tool names `browse_sfu_databases`
    and `check_sfu_access` to the same handlers as `browse_library_databases`
    / `check_library_access`. The legacy names are deliberately NOT in
    `TOOL_DEFINITIONS` (not advertised; tool count 18 since the 2026-10-12
    owner-decision trim, 27 before); `test_tools_unit.py` pins both halves.
  - The `formatters.format_sfu_database` / `format_sfu_databases_list`
    aliases were removed 2026-10-11 (codebase triage): the documented
    removal condition held (no caller outside the alias lines).
  - `zotero.RECORD_ID_TAG` (`Duck-Library-RecordID`) is what new Zotero
    items get in `extra`; nothing in the product looks items up by that tag.
- `validators.py`: the maximum number of boolean operators is a defensive cap.
- `logging_setup.py`: persistent file handler deliberately always DEBUG
  (full diagnostics); 5 MB rotation.
- `analytics.py`: propensity normalized to rank 1 == 1.0; minimum-click
  threshold exists for statistical validity, not rate limiting.
- `model_registry.py`: availability reflects on-disk reality — a model file
  that isn't present can't be active.
- `engagement.py`: event taxonomy mirrors the design's `ACTION_STYLE` /
  session-replay kinds.
- `zotero.py`: `search_items` / `get_collection_items` were retired
  2026-10-12 with the Zotero read MCP tools (owner decision);
  `list_collections`, `find_collection_by_name`, `verify_credentials`,
  `_format_item` and `format_item_summary` stay because the save path
  (`find_or_create_collection`, `ensure_authenticated`, `check_duplicate`)
  uses them. `sfu_databases.py`: domain matching tries the parent domain
  (`journals.sagepub.com` → `sagepub.com`).

## source/tests — conventions & pinned invariants

- **Env-wipe-before-import**: staging-default gated modules
  (`result_cache`, `speculation`, `serve_query_log`) must have their environment variables
  wiped/set BEFORE import (fresh module so `is_enabled` reflects the test
  environment).
- **Route-level coverage exists for a reason**: the WI-18a collapse-edit
  regression dropped `api_search`'s final return (every non-hit
  `/api/search` 500'd) while all 45 isolation tests passed —
  `test_speculation.py` runs Starlette TestClient against the real app with
  the search function mocked.
- `test_federated_search.py` pins the RRF formula (`2 * 1/(60+1)`);
  `test_openalex_client.py::TestOpenAlexCircuitBreakerWithRetries` and
  `test_semantic_scholar_client.py::TestS2CircuitBreakerWithRetries` pin
  one-breaker-failure-per-logical-request on the live clients
  (`test_retry.py` covers only the `CircuitBreaker` state machine since the
  unused `retry_with_backoff` decorator was removed 2026-10-11);
  (`test_openalex_push.py` was removed 2026-10-11 with the OpenAlex→OpenSearch push.)
- **A unit test that calls `search_academic` must pin the federated gate**
  (fixture `openalex_direct` in `test_tools_unit.py`, added 2026-09-25):
  `_handle_search_academic` serves from the local thin-client index whenever
  `features["federated_search_enabled"]` is on, and it is on in this
  container's config. Tests that mock `_get_openalex` and assert on its
  payload were instead querying the real 150M index and the live OpenAlex
  API (HTTP 429s; the file took 154 s and 2.7 GB RSS — 4.5 s after the fix).
  Patch `lib.tools._get_features` to `{}` to reach the OpenAlex-direct
  branch; the empty dict also keeps rerank and query logging out of the way.
- `test_thinclient.py` fixture contracts, re-pinned 2026-09-25: meta.sqlite
  completeness is `docs` + `docs_other` (two tables since 9a6d1952 — ids
  that fail `encode_meta_id`, for example, the fixture's leading-zero `W000123`,
  only ever land in `docs_other`); the abstract sidecar's table is `docs`,
  not v1's `abs` (d978ba38). Since 2026-10-11 the fixture carries no
  `sparse_field` and builds no `.bmp` shards (BMP leg removed); an
  `SFU_SPLADE_BACKEND` other than `seismic` raises (since 2026-10-12 that
  includes `qdrant`), pinned by `test_unknown_splade_backend_raises` and
  `test_qdrant_splade_backend_removed`.

## Names that look dead but are live — dead-code audit 2026-10-10

Recorded so no future sweep deletes them. Static tools (vulture, ruff) flag
every one of these on each run.

- `tools.py` `_handle_*` functions have no direct callers: they are reached
  only through the `dispatch` dict in `_dispatch_tool`, keyed by the MCP tool
  name string — never delete one without removing its `TOOL_DEFINITIONS` entry.
  The lazy getters annotate return types with string names of lazily imported
  classes; ruff F821 on them is expected. `handle_tool_call(name, arguments)`
  takes exactly two arguments.
- `sfu_library_mcp_http.py` route handlers are referenced only from the
  `_routes` list (by URL from `web/` for `/health`, `/api/search`, `/api/search_stream`,
  `/api/speculate`, `/analytics`, `/api/unpack`, `/engagement` (GUI caller again since
  2026-10-12, `SFUApi.engagement`), and from `scripts/prime_result_cache.py`;
  since 2026-10-11 `GET /api/index_status` and `GET /api/personas`
  have no GUI caller and stay as served API surface only);
  `list_tools`/`call_tool` are registered by the `@mcp_server` decorators.
  `_wire_cache_hit_log()` monkey-patches `serve_query_log.QueryLogger.log` at
  import time, so `_set_thread_cache_hit` / `_thread_cache_hit` look unused
  but are installed via `result_cache.set_cache_hit_logger` and the patched
  `log` (ContextVar-based despite the "thread" names). `QueryLogger.log`'s
  keyword-only signature must be kept: `speculation.wire_speculative_log`
  patches it too.
- The test-only names
  listed here on 2026-10-10 (`tools.get_metrics`, the `embedding` helpers,
  `engagement.log_engagement`, `retry.retry_with_backoff`) were removed
  2026-10-11 (codebase triage) with their tests.
- `FederatedSearchRouter.last_degraded` and `OpenAlexClient.circuit_open` are
  read only via `getattr(..., False)` (tools.py, sfu_library_mcp_http.py,
  result_cache.py). `OpenAlexClient.fetch_abstracts_by_ids` has no call site:
  it is passed as a bound method (`remote_abstract_fetcher=`) into
  `ThinClientRetriever`. `federated_search._normalize_doi` / `_rrf_merge` are
  private names imported by `speculative_rerank.py`.
- `analytics._PANELS` lambdas take an unused `ev` argument on purpose (uniform
  `fn(events)` dispatch arity). `reranker._OnnxCrossEncoder.predict(pairs,
  show_progress_bar=False)`: the unused kwarg is the CrossEncoder.predict
  duck-type and `_ce_forward` passes it.
- `ServerConfig` fields are read as attributes from many modules (vulture
  reports most at 60 %). Fields that were parsed from the environment but
  changed nothing were removed 2026-10-11 (codebase triage), together with
  the feature keys no code read. Clients use their own retry/timeout
  defaults (see EXTERNAL_API_CONTRACT.md).
- `thinclient/delta_layer.py`: every `DeltaLayer` method has zero callers
  inside the file; all are reached through `ThinClientRetriever._delta`
  (retriever.py) and the delta-ingest eval scripts. `delta_layer.refresh_buffer`
  duplicates the ledger's buffer-view SQL (gen 0 + `building` gens) — both
  must change together.
- `thinclient/doc_encoder.py`: `SpladeDocEncoder.encode_batch` and its TRT
  override are reached only polymorphically through `make_doc_encoder()`
  (spike/delta_ingest/encode.py). The ORT `SessionOptions` attribute
  assignments in `dense_cache.py` and `doc_encoder.py` are configuration
  setters, not dead attributes.
- `thinclient/dense_delta_merge.py:183`: ruff F821 on `rescore` is a known
  false positive (a closure reads it before the outer `del rescore`). Do not
  "fix" it by moving the del or the load.
- `thinclient/builder.py` (`SectionBuilder`, `open_meta_db`, `begin_slice`,
  `slice_checkpoint`, `build_dense_leg`) and `thinclient/abstracts.py`
  (`build_flat_sidecar`, `build_ordinal_locator`) have no callers in `source/`:
  they are driven by `scripts/build_thinclient_index.py` and
  `scripts/build_flat_blocks.py`. `prefault_stats` is read by tests and
  documented (doc 18 §23).
- `thinclient/sharded_seismic_backend.py` `_SeismicBackendBase.__init__`: the
  eager `from lib.thinclient.seismic_backend import SeismicBackend` (stored as
  the write-only `_backend_proto`) is LOAD-BEARING — it loads the real module
  before `scripts/tests/test_seismic_sequential.py::_stub_seismic` can plant a
  fake one that lacks `SPLADE_QUERY_TERMS`. Removing it was tried on
  2026-10-10 and reverted (1 failure). `ShardedSeismicBackend` and its
  `__new__` are reached by name through
  `scripts/seismic_testbed/seismic_federated.py`'s re-export. `_floor_mlocked`
  and `_hotset_pinned_gb` are read by `f5_t1_pin_parity.py` / `r1_ram_ladder.py`
  and must not be renamed; the write-only `_floor_prefaulted` /
  `_floor_mlocked_bytes` and the uncalled `fault_status()` were removed
  2026-10-11 (codebase triage; `fault_status`'s only caller was the CLOSED
  harness `scripts/archive/demo_dependability/wi10_shard_isolation.py`, which
  no longer runs against HEAD; `degraded_shards()` is the live per-shard
  fault surface). `_seismic_federation_mode`, `_leg_snapshot_for_log`,
  `_leg_delta_for_log` are underscore-private but called from `lib/tools.py`.
  `sections.subsection_name` (test-only) was removed 2026-10-11;
  `ordinals.write_stamp` and
  `livedocs.pack_header` are called from the writers under `spike/`.

## Retired 2026-10-12 — Qdrant rollback leg (code kept by the owner)

The Qdrant SPLADE leg (`retriever.py` `_splade_leg_qdrant`, `_qdrant`,
`_bert_vocab_map`, `_encode_splade_top`, `SFU_SPLADE_BACKEND=qdrant`,
`SFU_SPLADE_QDRANT_URL`, `SFU_SPLADE_QDRANT_COLLECTION`) was removed
2026-10-12 by owner decision (no Qdrant binary, service or collection in this
container; restore tag `pre-owner-decisions-2026-10-12`). The encoder-failure
contract (encode error or empty encoding → BM25F leg, RRF still fuses) is NOT
retired: the SEISMIC leg still honours it. Retired with the leg:

- 2026-10-12 retired: query term → id mapping through the `bert-base-uncased`
  vocab, the same bijection the Qdrant ingest used to place doc sparse vectors
  (`scripts/archive/spike_qdrant_sparse.py` `_vocab`); query terms absent from
  the vocab were dropped and an all-dropped query fell back to the BM25F leg.
- 2026-10-12 retired: Qdrant query errors degraded to the BM25F leg (logged
  warning), never raised.

## Retired 2026-10-11 — BMP leg (code kept by the owner)

The BMP SPLADE leg (`retriever.py` shard load + `_splade_leg` fall-through,
`builder.py` shard emission, `SFU_SKIP_BMP`, `SFU_LOAD_MEM_FLOOR_GB`,
`SFU_SPLADE_BACKEND=bmp`) was removed 2026-10-11 (codebase triage; no `.bmp`
artifact exists in this container). The invariants below are kept verbatim as
the record for anyone restoring it from the owner's archive branch
(`archive/bmp-qdrant`).

### Former retriever.py bullets

- **BMP resident ratio** `BMP_RESIDENT_RATIO = 3.07`: measured anon-RAM
  expansion of `bmp.Searcher` (probe 2026-06-17, 569 MB shard → 1747 MB RSS;
  ratio holds 12 MB→569 MB). 150M SPLADE = 68.6 GB on disk → ~211 GB
  resident; the process is OOM-killed inside construction, hence the
  `SFU_LOAD_MEM_FLOOR_GB` gate.
- **BMP alpha/beta**: measured on the 1M build (10 SPLADE queries, 64 terms):
  `alpha=0.8` keeps top-50 overlap 1.000 at −29% latency; `beta<1.0` prunes
  query terms and visibly costs quality (0.5 → overlap 0.80).
- **`QUANT_SCALE = 70`** must match `builder.QUANT_SCALE` (see builder entry).
- **Vocab sidecar degradation**: a corrupt vocab sidecar must not take down
  the whole index — `vocab=None` falls back to querying the shard without
  the zero-overlap guard. (The sidecar exists because BMP panics on queries
  whose terms are ALL absent from a shard.)
- **BMP zero-overlap panic**: BMP panics (Rust unwrap) when NO query term
  exists in the shard — skipped via the vocab sidecar; guard kept for old
  builds without sidecars.

### Former builder.py bullets

- **`QUANT_SCALE = 70`**: BMP stores impacts as u8 and SATURATES above 255
  (measured: scale 1000 collapses recall to 0.28; scale 100 clips weights
  > 2.55). Scale 70 keeps every SPLADE log1p weight ≤ 3.64 saturation-free;
  measured recall@50 versus float-exact 0.968–0.970. Ranking is scale-invariant,
  so a retriever/index scale mismatch only rescales scores. Must match
  `retriever.QUANT_SCALE`.
- **Minimum shard size**: BMP returns empty results below ~500 docs and
  panics on heavy score ties — never leave a tail shard smaller; absorb it
  into the previous shard.
- **`bsize=256` + clustered insertion**: measured −54.2% size and −61%
  latency at EQUAL recall versus the paper's bsize=32
  (`eval_storage_levers.py`, `LEXICAL_STORAGE_RESEARCH.md` §9).
- **Chunk size 250k** (halved from 500k/1GB on 2026-06-12): the era split
  runs TWO builders per section worker; 3 workers × 2 builders OOM-killed
  the 150M build on the 31 GB host. Chunk size only bounds the clustering
  window — the measured win comes from 256-doc-block locality, which 250k
  preserves.

### Former source/tests bullet

- Thin-client fixtures stay above BMP's quirks by construction: 3000 docs,
  1000-doc shards, near-unique weights (BMP: empty below ~500 docs/shard,
  panics on heavy ties); vocab sidecars must exist.

### Former `source/lib/thinclient/CLAUDE.md` block

BMP 0.2.6 hard-won quirks (do not "simplify" these away):
- `QUANT_SCALE = 70` — u8 impacts saturate at 255; scale 100 clips, 1000
  collapses recall to 0.28.
- Panics if NO query term exists in a shard → `*.vocab.zst` sidecars + skip.
- `beta=0.0` panics; indexes < ~500 docs return empty → tail shards < 5k
  absorbed into the previous shard.
- `bsize=256` + chunked top-term clustering: measured −54% size, −61% latency.
