# Ingest-side fixes 2026-10-01 (Agent F, second-wave dispatch): O7, O14, O15, O17

**Status:** ACTIVE

Scope: ingest-side code under `spike/delta_ingest/` only, no index load, no
latency lock. Open-issue numbers refer to `docs/delta_ingest/02_DESIGN.md`
§3.1. Host shared with Agent A's exclusive latency run (04:15Z–06:10Z): all
work here ran `nice -n 19 taskset -c 12-15 OMP_NUM_THREADS=2`, so every wall
time below is INVALID as a throughput number.

## O7 — streaming partition adapter

- **Defect.** `OpenAlexSnapshotAdapter.iter_records` did
  `gzip.decompress(self._get(url))` (compressed body + the whole decompressed
  partition in RAM) and `iter_deletions` did the same for `deleted_ids.csv.gz`.
  M6 measured 6.74 GB ingest peak RSS on both profiles, above the laptop
  profile's `max_rss_gb` 3.0.
- **Test (failing first).** `scripts/tests/test_delta_partition_stream.py`
  (5 tests): partition responses must be read through `iter_content` with
  `stream=True` and never via `.content`; a local path / `file://` manifest
  entry is read in place; Python heap (tracemalloc) while iterating a 6,000-
  work synthetic gzip'd JSONL partition stays below a quarter of its
  decompressed size; deletions are streamed with the old date semantics; a
  failed download is retried and the spool file is removed. All 5 failed on
  105261c8, all pass after the fix.
- **Fix** (`spike/delta_ingest/adapters.py`). New `_open_gz(url)` context
  manager: a local partition is opened with `gzip.open` in place; a remote one
  is downloaded with `session.get(url, stream=True)` in 1 MiB chunks into a
  temp spool file (compressed) under `spool_dir` (CLI `--spool-dir`, default
  system temp), then decompressed line by line; the spool is unlinked
  afterwards; a failed attempt truncates and retries. Sessions without
  `iter_content` (offline fakes such as the M6 harness `LocalSession`) fall
  back to writing `.content` to the spool — still no decompressed copy in
  RAM. `_get` is kept for the (small) manifest only. Resume granularity is
  unchanged (per partition: `synced` is appended only after a whole part).
- **Invariant (spike code, recorded here):** the snapshot adapter never holds a
  whole partition or `deleted_ids` body in memory; memory per partition =
  one chunk + gzip window + one line.
- **Measured** 2026-10-01 ~04:14Z–04:16Z, script
  `scripts/experiments/eval_delta_ingest_o7_streaming.py`, results
  `data/eval_results/delta_ingest_O7_streaming_20261001.json` (HEAD at run
  e59ad355, adapter = working tree with this fix; pre-fix adapter loaded from
  `105261c8:spike/delta_ingest/adapters.py`). Corpus: the REAL OpenAlex
  partition `updated_date=2026-09-15/part_0001` (item B download, 359,271,114 B
  gz, 276,848 lines, 3,242,179,450 B raw); subset = its first 60,000 lines
  re-gzipped (84,118,854 B gz, 724,960,795 B raw) so the pre-fix arm stays
  under the 4 GB address-space cap (`prlimit --as`). Adapter iteration only
  (records counted and dropped), one child process per arm, VmHWM.

  | corpus | arm | records in slice (min_year 2010) | peak RSS GB |
  |---|---|---|---|
  | subset 60k lines | pre-fix (`.content` + gzip.decompress) | 41,735 | **1.527** |
  | subset 60k lines | fixed, streamed + spooled | 41,735 | **0.024** |
  | subset 60k lines | fixed, local path in place | 41,735 | **0.024** |
  | full partition | fixed, streamed + spooled | 205,358 | **0.026** |
  | full partition | fixed, local path in place | 205,358 | **0.025** |

  Record counts are identical across arms (41,735), and the full-partition
  count 205,358 equals the M7-seed in-slice count at min_year 2010. The
  pre-fix arm was NOT run on the full partition (it would exceed the 4 GB
  cap); scaling its subset peak by raw size gives ~6.8 GB *est.*, which agrees
  with M6's 6.74 GB. Time to first record on the subset: 1.89 s pre-fix vs
  0.13 s spooled (timings invalid, shared host).
- **Not measured.** The whole `ingest` pipeline peak (ledger + tantivy +
  encoder) on the laptop profile after the fix: the adapter is no longer the
  peak, but the encoder/model RSS is now the floor and is UNMEASURED here
  (needs a CPU encode run, not allowed under the lock). Real HTTP streaming
  against S3 (the fake session streams from local disk).

## O14 — base-vector reuse for text-unchanged base docs

- **Defect.** `IngestLedger.reusable_sparse` reuses only vectors stored in the
  ledger's `records`, so a seeded base doc whose encoder text is unchanged
  (content-only update: is_oa / type / year / DOI; 5,530 of 9,965 seeded docs
  on the M7 primary hot section) was still sent to the encoder.
- **Tests (failing first for the CLI wiring; store/ledger tests written with
  the module).** `scripts/tests/test_delta_base_vectors.py` (9 tests) on
  synthetic shard twins written in the real c1a f16 layout: locator counts
  (non-W ids excluded); exact vectors for valid rows and one named refusal per
  failure (`multiple_rows`, `components_not_increasing`, `unknown_component`,
  `nnz_out_of_range`, `value_not_exact` for an inf value, `not_in_base_shards`,
  `not_w_id`, `mapping_mismatch` for a corrupted id string); a locator built
  for a different shard is rejected; the reused vector survives
  `DocRecord.seismic_line()` → JSON → float32 → f16 with identical bits;
  R1/R2 eligibility (`has_ledger_row`, `not_seeded`, `encode_text_changed`);
  `ensure_sparse` sends only refused docs to the encoder; flag off → nothing;
  CLI `ingest --base-forward-dir … --base-locator-dir …` stores the exact base
  vector for a content-only update and leaves a retitled doc to the encoder
  (`reused_base` 1, `base_refusals {"encode_text_changed": 1}`). The CLI test
  failed (unrecognised arguments) before the wiring.
- **Fix.** New `spike/delta_ingest/base_vectors.py`: `build_locator` (per-shard
  sorted W-id → row arrays, built in 1M-doc chunks, `.npy` memory-mapped),
  `BaseVectorStore.vectors(ids)` (pread of the f16 c1a twin: offsets,
  components, values, mapping string), `base_reuse_candidates` (R1 no ledger
  `docs` row; R2 seeded encode hash64 equals the record's) and
  `reusable_base_sparse`. Exact-or-refuse rules R1–R5 are in the module
  docstring. `cli.py`: `ingest --base-forward-dir DIR (repeat) --base-locator-dir
  DIR` (flag off = unchanged behaviour), new subcommand `build-base-locators`,
  totals `reused_base` + `base_refusals`. Source of vectors = the f16 twins
  (`data/seismic_150m/index/plan01/global_shard{k}of8.mmap` or a local copy),
  never the served dotvbyte fixed-u8 shards (lossy).
- **Measured on the real shard-0 twin** (local copy
  `/home/vscode/work/inplace_update/twin_local/global_shard0of8.mmap`;
  2026-10-01 04:19Z–04:22Z; script
  `scripts/experiments/eval_delta_ingest_o14_base_reuse.py` `locator` +
  `verify-reader`; results
  `data/eval_results/delta_ingest_O14_base_reuse_20261001.json`):
  - The copy's `token_to_id_map.bin`, `document_mapping_offsets.bin`,
    `document_mapping_strings.bin`, `forward_offsets.bin`, `config.json` match the
    2026-09-29 sha256 listing. The 3.3 GB `forward_components.bin`/`forward_values.bin` were
    NOT re-hashed (IO budget under the latency lock).
  - Locator: 18,799,322 docs, all W-ids, 0 duplicate ids; 6.9 s, peak RSS
    0.79 GB (timings invalid); size 18.8M × 12 B ≈ 226 MB per shard.
  - 20,000 random rows (seed 20261001): 20,000 reused exactly, 0 refused,
    20,000/20,000 bit-equal (token order + f16 bits) to an independent
    `np.fromfile` read at the row offsets; nnz mean 88.31, max 255;
    0.93 ms/doc lookup+checks (Python, timings invalid); peak RSS 0.35 GB.
    A first version mapped the forward files (np.memmap): mmap fault-around
    put peak RSS at 2.65 GB for the same 20k rows, so the reader uses
    `os.pread` only.
- **What R1–R5 prove, and what they do not.** They make the delta copy's
  stored vector bit-identical to the base copy's f16 forward vector (exact,
  verified above). The delta build (jsonl → stock → f16 c1a → dotvbyte v2
  per-doc scale) then re-derives the served u8 codes from the same f16 values
  — that the codes equal the base's served codes is *inferred* (per-doc scale
  depends on the doc's own values only), NOT measured. They do NOT prove that
  the base vector equals what today's encoder would produce for the same text
  — that is the doc 08 §0.3 question (87.6 vs 122.5 nnz/doc), measured
  separately below (GPU check), and it does not affect exactness of reuse:
  reuse keeps the delta copy identical to the base copy that serving already
  ranks.
- **Not measured.** End-to-end encode seconds saved per partition (needs a
  seeded ledger over the partition's in-base docs AND their shard twins; the
  saving bound is the content-only share, 5,530/9,965 = 55.5 % of seeded
  in-base updates on the M7 primary hot section, *est.*); served dotvbyte code
  equality; locators for shards 1–7 (≈ 7 s each *est.* from shard 0).

## O16 — CLI uses the shared delta-root resolver (coordinator request, from Agent E)

- **Defect.** `cli.py` resolved `--delta-root` itself (`<index-root>/delta`
  when absent, ignoring `SFU_DELTA_ROOT`), so any subcommand without
  `--delta-root` wrote a ledger under `data/thinclient_index/`; nothing stopped
  a root inside `data/seismic_150m`.
- **Test (failing first).** `scripts/tests/test_delta_cli_root_and_gens.py`
  (O16 part, 5 tests): `SFU_DELTA_ROOT=<path>` is honoured; explicit
  `--delta-root` beats the env; an implicit root under `data/` and any root
  inside `data/seismic_150m` exit with an error and create nothing; an
  explicit root under `data/` is still allowed. The refusal tests redirect
  `delta_layer.REPO_DATA_DIR` to a tmp tree so a regression can never write
  into the real `data/`.
- **Incident while writing the test (recorded, reverted).** The first version
  of the two refusal tests pointed at the REAL `data/` paths; run against the
  pre-fix CLI (failing-first step, 2026-10-01 04:24:12Z) it created
  `data/seismic_150m/delta_should_not_exist/ledger.sqlite` (empty 60 KB SQLite)
  and `data/thinclient_index/delta/ledger.sqlite`. Both were created by that
  run (timestamps 04:24:12.75–.89Z, dirs did not exist before) and were removed
  at 04:24:30Z; nothing pre-existing under `data/seismic_150m` was read, changed
  or removed (its directory mtime changed). The tests were rewritten to the
  tmp tree before the fix was applied.
- **Fix.** `cli.main` calls `lib.thinclient.delta_layer.resolve_delta_root(index_root,
  args.delta_root, for_write=True)` (E's resolver, 8520e6e2) and exits with
  the resolver's message on `ValueError`. `--delta-root` help text updated.
  Invariant/env docs were already written by E (`docs/ENV_GATES.md`
  `SFU_DELTA_ROOT`, `docs/CODE_INVARIANTS.md` "One delta-root resolver").

## from_gens kept on publish (coordinator request, from Agent E — O2 residual)

- **Defect.** `IngestLedger.finish_generation` overwrote `generations.info`
  with the publish info, dropping the `from_gens` that `open_generation`
  wrote. The serving reader's `_buffer_generations` (c6a9d4de) then has to
  guess for published rows, so after a compaction of a loaded generation a
  later unloaded freeze waited for `reload()`.
- **Test (failing first).** `test_finish_generation_keeps_from_gens` and
  `test_finish_generation_explicit_from_gens_not_overwritten` in
  `scripts/tests/test_delta_cli_root_and_gens.py` (KeyError `from_gens`
  before the fix).
- **Fix.** `finish_generation` merges the stored `from_gens` into the new info
  unless the caller passed its own. Verified with
  `scripts/tests/test_delta_serving_fixes.py` + `test_delta_ingest.py` (green).
  Generations published before this commit still lack `from_gens` (the
  reader's fallback rule applies to them).

## O15 — AbstractStore read-only by construction

- **Defect.** `AbstractStore.__init__` (`src/lib/thinclient/abstracts.py`)
  connected with `sqlite3.connect(str(path))` — read-write; any stray write
  statement on a reader (serving, seed, evals) would modify a served sidecar.
- **Test (failing first).** `scripts/tests/test_abstract_store_readonly.py`
  (3 tests, on a SectionBuilder-built section): `CREATE TABLE` through the
  store's connection must raise `readonly` (DID NOT RAISE before the fix); open
  + fetch of all docs leaves the file bytes and every directory entry's mtime
  unchanged; a path containing `?`, `#`, `%20` and a space still opens (URI
  escaping).
- **Fix.** `sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro",
  uri=True, check_same_thread=False)`. Not `immutable=1`: that also disables
  locking and change detection, which is unsafe if a builder still writes the
  file; `mode=ro` is enough to forbid writes. The store only ever ran SELECT /
  PRAGMA table_info (checked). Invariant added to `docs/CODE_INVARIANTS.md`
  §abstracts.py. Regression suites green: test_abstract_locator,
  test_build_resume, test_flat_block_builder, test_thinclient_stack,
  src/tests/test_thinclient, test_delta_seed, test_delta_serving_fixes,
  test_delta_ingest (131 tests, 2026-10-01).
- **Residual.** A sidecar left with a hot rollback journal can no longer be
  recovered by a reader (read-only cannot roll back); it errors instead of
  silently repairing. None exists in the measured stores (*not checked on every
  section*).

## O17 — base `is_oa` (assessment + sample, no code change)

- **Measured 2026-10-01 04:29Z** (read-only, `data/thinclient_index/meta.sqlite`,
  sequential id-ordered reads): `SUM(is_oa)` = **0 of 300,000** meta rows in six
  50,000-row windows starting at W2000000000, W2400000000, W2900000000,
  W3000000000, W4000000000, W4300000000. The last window spans 8 sections (all 0).
  A wider random-probe sample over 9p was started but killed by its own
  300 s timeout (random 9p reads too slow under the lock), so there is no result for it.
- **Cause (code reading, not executed):** `scripts/build_thinclient_index.py:71`
  exports a top-level `is_oa` field from the OpenSearch source, but neither
  the retired `splade_indexer.py` nor `opensearch_sync.py` (last at
  `dab0dd1f^`) ever wrote `is_oa`. The builder stores `bool(doc.get("is_oa"))`,
  which is `False` when the field is missing. So the base `is_oa` is **never
  populated** rather than "stale or biased". This explains M7's one-way 0 → 1
  flips (25,792, none 1 → 0). Status: strongly supported (0/300k + code path),
  not proven for every row (a full scan reads 25 GB over 9p).
- **Consequences.** (1) Every in-base OA work is a content-only "update" on
  first contact with the snapshot (4,465 of the 5,530 content-only updates on
  the M7 primary hot subset are is_oa alone). With O14 these cost a ledger row
  plus a delta copy, but no encode. (2) **Serving (inferred from code, not
  run):** the thin-client OA filter (`retriever.py` ~1018 tantivy `is_oa`
  fast field, ~1403 meta check, ~1582 `open_access.is_oa`) can match no base
  doc, so `open_access_only=true` searches return only delta docs. This is
  user-visible if that filter is exposed (`tools.py` 1234/1331/1511 set it).
- **Options (design only):** (a) a base-side `is_oa` bitmap built from one
  snapshot pass, served as a fast-field override (no reindex); (b) leave
  is_oa out of `CONTENT_FIELDS` for in-base docs until (a) exists, so an
  is_oa-only flip does not make a delta copy (but then base docs stay
  non-OA in serving); (c) accept as-is: the delta layer slowly repairs is_oa
  at ~1 delta copy per OA base doc touched. Recommend (a). This is a
  coordinator/owner decision.

## Full base-hash seed — launch procedure (NOT started)

**Correction to the seed findings.** `BASE_HASH_SEED_FINDINGS.md` assumes a
full seed needs "each packed section unpacked". That premise is wrong on this
host. `manifest.json` lists `hot_sections: ["social_sciences__recent"]`, and the
builder writes `abstracts.sqlite` for hot sections only
(`builder.py:10`). Two packed archives were streamed and listed
(`med_bio__archive`, `phys_eng__archive`): **0 abstract bytes** in either.
Listing `cs_math__recent.tar.zst` failed with 9p ENOMEM (O12) after its first
members. **The base text of the other ~127.0M docs is not on this host.** Their
encode hash cannot be computed, and neither can a full seed. The seedable set
is the hot section: 23,398,073 docs.

Seeding the other sections needs a text source equal to the base build's
(2026-06-11..16 OpenSearch export): an OpenAlex snapshot from that date, or
the export spool (gone). Using today's snapshot would hash the new text,
which defeats the purpose. Design only.

Hot-section seed (resumable; run when no latency measurement is running):

```bash
# 0. local copies off 9p (O12): ~25 GB meta + ~24 GB sidecar; 660 GB free on /
mkdir -p /home/vscode/work/delta_ingest/seed_full/{meta,sidecars/social_sciences__recent}
rsync -a --inplace data/thinclient_index/meta.sqlite /home/vscode/work/delta_ingest/seed_full/meta/
rsync -a data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite \
         data/thinclient_index/sections/social_sciences__recent/abstracts.sqlite.flat \
         /home/vscode/work/delta_ingest/seed_full/sidecars/social_sciences__recent/
# 1. seed into the ledger the ingest will use (the production delta root; --delta-root is now mandatory
#    for roots under data/, O16). Resumable: re-run the same command, cursor key base_seed:0-9000000000.
SFU_META_STAGE_DIR=/home/vscode/work/delta_ingest/seed_full/meta \
nice -n 10 taskset -c 8-15 /workspaces/sfu-library-thinclient/.venv/bin/python3 -m spike.delta_ingest.cli seed-base \
  --index-root data/thinclient_index --delta-root <DELTA_ROOT on local disk> \
  --sidecar-root /home/vscode/work/delta_ingest/seed_full/sidecars \
  --seed-lo 0 --seed-hi 9000000000 --seed-batch 5000
# 2. check: cli status --delta-root <DELTA_ROOT>  -> ledger.base_seeded ~ 23.4M
```

Expected cost (*est.*, from the 2026-09-30 T2 timers on 9p, id order): meta
scan 14.7 µs/row × 150.4M rows ≈ 37 min, plus abstract fetch 0.55 ms/doc × 23.4M ≈
3.6 h, so **≈ 4.2 h** (local copies: faster, unmeasured). Ledger
`base_hashes` 23.4M × 28.3 B ≈ **0.66 GB**. Copies ≈ 49 GB (copy time
unmeasured). The other 127M rows are skipped and counted under
`skipped_no_local_sidecar`.

## O8 view (asked by the coordinator; no change made)

I agree with E. A per-instance label (`device` + `get_providers()[0]`,
torch dtype) is the honest fix. It must be ADDED next to the existing class
label (a new key such as `runtime_backend`), not replace it. Results files and
M6 comparisons key on the class label strings, so renaming would break
comparisons silently. The M6 desktop_gpu number then reads as "ORT-CUDA fp16"
and laptop as "torch fp32", both of which M6 already states in prose.

## O14 addendum — GPU check: base vector vs re-encode of the same text (doc 08 §0.3)

Run 2026-10-01 06:10:09Z–06:10:31Z, after the latency lock was released.
`flock -s` on the lock, `nice 10`, cores 12–15, local venv mirror. Script
`eval_delta_ingest_o14_base_reuse.py gpu-check`. Results: `gpu_check` block
of `data/eval_results/delta_ingest_O14_base_reuse_20261001.json` (HEAD at run
d7ac191d). Timings are invalid.

Docs: meta rows with id > W4000000000 in id order (60,000 scanned). 7,505 of
them are in shard 0. **1,882** are in `social_sciences__recent` with a sidecar
abstract, and all 1,882 passed R3–R5. Text = `encoder_text()` of the seed's
base record (meta title + sidecar abstract). Encoder: `SpladeDocEncoderTRT`
class. The TRT EP failed to load (libnvinfer missing), so it actually ran on
ORT-CUDA fp16 (O8).

| metric | value |
|---|---|
| nnz/doc, base f16 vector | 83.00 |
| nnz/doc, re-encode | 83.18 (ratio 1.0022) |
| term-set Jaccard, mean / p5 | 0.9935 / 0.9756 |
| cosine, mean / p1 | 0.99998 / 0.99996 |
| docs bit-identical | 0 / 1,882 |
| shared-term values f16-equal | 8,304 / 155,859 (5.3 %) |
| max abs diff on a shared term | 0.075 |

Reading:
- **Doc 08 §0.3's encoder-calibration worry is not confirmed for the
  ingest encoder.** On identical text, today's encoder gives the same nnz as
  the base (83.18 vs 83.00) with cosine 0.99998. The 122.5 nnz/doc of the
  S0-1 re-encodes must come from something else (different or longer text, or
  the archived prep path). That source is UNMEASURED here.
- **Reuse is not "equal to a re-encode".** Re-encoding is numerically noisy
  (fp16 runtime differences, 4-decimal rounding: 0 docs bit-identical, and
  0.65 % of terms differ in membership near the 0.01 threshold). Base-vector
  reuse is the only way to keep a content-only delta copy bit-identical to the
  base copy that serving already ranks. Exact-or-refuse therefore refers to
  the base copy, as designed.
