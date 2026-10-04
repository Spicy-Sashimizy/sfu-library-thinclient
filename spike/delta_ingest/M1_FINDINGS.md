# M1 findings: gate-off parity, 2 passes per arm, on current code

**Status:** ACTIVE

Rerun of M1 dispatched 2026-10-01 (Agent C, second-wave dispatch). The bar is
`docs/delta_ingest/03_SPIKE_PLAN.md` row M1, frozen 2026-09-29, unchanged:
"fused + final top-10, 120 topics, `SFU_DELTA_ROOT` unset vs set with an EMPTY
delta root -> byte-identical 120/120"; fixed inputs: 2 passes per arm. The
2026-09-29 result (PASS 120/120, `data/eval_results/delta_ingest_M1_20260929.json`)
ran ONE pass on code `aa0fc405`, which predates the livedocs serving code
(6f5dd471), the shard-staging fix (585f3cab), the O1 buffer-refresh fix
(8a51e48f), the O3 cleanup (37937f6b) and the O19 BM25F lower-casing fix
(99e2b663).

## Pre-run note (written 2026-10-01 ~04:15Z, before any measurement)

**Method.** Unchanged from the 2026-09-29 harness: per topic and pass,
`fused = ThinClientRetriever.search_rrf(q, top_k=50)` and
`final = lib.tools._maybe_rerank(deepcopy(fused), q, 10)`, serialised with
`json.dumps(sort_keys=True)`; identity is string equality of every field incl.
scores. Remote abstracts stubbed to `{}` in every arm. Topics: the 120
`natural` queries of `data/eval_results/dense_ablation_qrels_20260817.json`
(the same file the 2026-09-29 harness read; note for the coordinator: the 03
results row names `data/sfu_eval_queries.json` field `query`, which is not
what that harness read). `compare()` is imported unchanged from
`scripts/experiments/eval_delta_ingest_m1_gate_off_parity.py`.

**Harness.** New file `scripts/experiments/eval_delta_ingest_m1_2pass.py`
(the 2026-09-29 harness is left untouched because the earlier result cites
it). Additions: health gate before the first query (onnxruntime imports,
`encode_splade` returns terms, cross-encoder not None, embedding model loads,
SEISMIC backend loads, arm's delta state as expected, no failure signature in
load warnings — else exit 3, no rows); per-row warning capture with a
`degraded` flag; rows appended as JSONL per topic so a kill leaves a usable
partial; child stops itself at the deadline; O12 early-ENOMEM restart (up to
3); code = `git archive <HEAD> src` snapshot on local disk
(`/home/vscode/work/delta_ingest/m1/code_<commit8>/`) feeding both arms.

**Arms (same commit, same snapshot, separate processes).**
- `gate_off` — reference arm = the pre-delta serving path AT THE SAME COMMIT:
  `SFU_DELTA_ROOT` absent from the child env. Both arms therefore carry the
  O19 lower-casing, so O19 cannot show up as a gate effect.
- `empty_root` — `SFU_DELTA_ROOT=/home/vscode/work/delta_ingest/m1/empty_root_dir`
  (fresh, asserted empty before and after; health asserts 0 generations,
  0 deleted, 0 superseded, empty buffer, no shard manifest, no sections).
- Informational only, NOT the bar: today's `gate_off` pass 1 vs the stored
  2026-09-29 `gate_off` rows (code aa0fc405) — a cross-commit view of what
  the intervening commits changed on the gate-off path.

**Passes.** 2 per arm, sequential within each process (pass 1 completes over
all 120 topics before pass 2 starts). Reported: gate_off vs empty_root per
pass (fused full list, fused top-10, final top-10, id-only views), and
pass 1 vs pass 2 within each arm (noise control).

**Run config.** Interpreter `/home/vscode/work/venv_local/bin/python3`;
`SFU_SPLADE_MODEL_PATH=/home/vscode/work/models_local/splade_onnx_fused`,
`SFU_CE_MODEL_PATH=/home/vscode/work/models_local/sfu-cross-encoder-v1`,
`SFU_EMBEDDING_MODEL_PATH=/home/vscode/work/delta_ingest/m1/models/sfu-academic-embed-v5`
(sha256 verified 2026-10-01 equal to the repo copies: SPLADE model.onnx
1b018e1a…, CE model.safetensors 69367ede…, embed-v5 all 11 files; SPLADE
tokenizer files equal to `models/sfu-academic-embed-v1`); `SFU_SEISMIC_STAGE_DIR=""`,
`SFU_META_STAGE_DIR=""`; `SFU_SEISMIC_SHARD_MANIFEST` and
`SFU_SEARCH_SPECULATIVE_RERANK` removed (serving default manifest). Each child
under `flock -s /tmp/sfu_latency_measure.lock`, `nice -n 10`, gate_off on
cores 0-3, empty_root on cores 4-7, both arms concurrently.

**Deviations from the fixed inputs (stated before the run).**
1. "Host otherwise idle" is NOT met: Agent B builds SEISMIC shards on cores
   8-15 at the same time, and the two arms run concurrently. All latency /
   wall-time fields are INVALID; identity is the deliverable.
2. Stage dir empty: shards are served from `data/seismic_150m` over 9p. The
   2026-09-29 run inherited `SFU_SEISMIC_STAGE_DIR=/var/tmp/seismic_stage`
   from `.env` and served the staged copy. Both of today's arms are equal, so
   this does not touch the bar; it only qualifies the cross-commit view.
3. Local interpreter/model mirrors (byte-identical, above) instead of the 9p
   `.venv`/models, to avoid O12.

**Expected runtime.** 2026-09-29, one pass, staged shards, sequential arms:
gate_off 1,055 s, empty_root (retry) 864 s per pass (both INVALID as
latency). Today *est.* 15–25 min per pass per arm (9p shards, 4 cores each,
concurrent build), i.e. ~35–50 min for 2 passes with the arms concurrent.
The window is lock release (expected ≤ 06:10Z) to the hard stop 06:40Z,
so pass 2 will probably be cut.

**Pre-committed trim order.** (1) Pass 1 must cover all 120 topics in both
arms; it is never trimmed. (2) Pass 2 is cut by the 06:40Z deadline at
whatever topic count it reached (fewer topics on pass 2), reported as
PARTIAL with N. (3) If pass 1 itself does not reach 120 topics by 06:40Z the
result is INCOMPLETE (bar not decided), never a PASS.

**Verdict rule.** Any process failing health, or any row flagged
`degraded`, makes the run INVALID (not FAIL). Otherwise: any compared topic
where fused top-10 or final top-10 differs between the arms in the same
pass → FAIL (first differing topic shown and diagnosed); 120 × 2 passes all
identical → PASS; pass 1 120/120 and pass 2 N < 120 all identical →
PARTIAL (pass 2 N/120). The full 50-doc fused list identity is reported
alongside.

## Results (measured 2026-10-01 05:42:19Z–06:04:02Z)

- Results: `data/eval_results/delta_ingest_M1_2pass_20261001.json`
- Harness: `scripts/experiments/eval_delta_ingest_m1_2pass.py` (pre-run note
  commit 497da6c8, `--no-lock` option f821e370 — not used)
- Measured code: `git archive d985b70d src` (HEAD at launch; contains
  6f5dd471, 585f3cab, 8a51e48f, 37937f6b, 99e2b663); no dirty `src/` files
  at launch.
- Launch: the launcher waited until Agent A's M4 process had exited and the
  latency lock was free, then both children ran under `flock -s` (lock never
  forced, no-lock fallback not used). Agent B's build ran on cores 8-15.
  Timings INVALID.

**Verdict: PASS — 120 topics × 2 passes, byte-identical** (bar of 03 M1,
unchanged).

| Comparison | n | full fused list (50) | fused top-10 | final top-10 |
|---|---|---|---|---|
| gate_off vs empty_root, pass 1 | 120 | 120 | 120 | 120 |
| gate_off vs empty_root, pass 2 | 120 | 120 | 120 | 120 |
| gate_off pass 1 vs pass 2 (noise control) | 120 | 120 | 120 | 120 |
| empty_root pass 1 vs pass 2 (noise control) | 120 | 120 | 120 | 120 |

Health (both processes, asserted before topic 1): onnxruntime 1.26.0;
SPLADE from the local mirror, 43 terms on the warm-up query; CrossEncoder
loaded; SentenceTransformer embedding model loaded; SEISMIC
`SequentialSeismicBackend`, 8 shards, default manifest
`seismic_c25_shards_150m_mmap_e5_v2.json`; empty_root arm's DeltaLayer:
0 generations, 0 deleted, 0 superseded, buffer 0, no shard manifest, no
sections, no livedocs. Empty root listing empty before and after the run
(the O1 buffer refresh created nothing there). 0 degraded rows, 0 failure
signatures in either log, 1 attempt per arm (no O12 restart). Peak RSS
8.2 GB per process (VmSwap 0.9 GB).

Federation note: with `SFU_SEISMIC_STAGE_DIR=""` the FS-aware default
picked `sequential` (shards on 9p); the 2026-09-29 run served the staged
copy with `ParallelSeismicBackend`. Both of today's arms are equal.

### Cross-commit view (informational, NOT the bar)

Today's gate_off pass 1 vs the stored 2026-09-29 gate_off rows (code
aa0fc405): 119/120 identical (fused, fused top-10, final). The one
difference is topic index 117, "How does psychological safety affect
whether people speak up and how teams perform?": rank-1 fused id is the
same, the fused scores and lower ranks differ (rank-1 RRF score 0.02524 →
0.02932). Today's result is stable across both passes and both arms.

Diagnosis (`scripts/experiments/eval_delta_ingest_m1_o19_diag.py`,
2026-10-01 06:04Z, one process on the d985b70d snapshot, same env): with
the current code the topic reproduces today's row; with ONLY
`bm25f_query_text` replaced by the pre-O19 version (no `.lower()`) it
reproduces the 2026-09-29 row byte-for-byte. So the difference is the O19
lower-casing (99e2b663), not the delta gate, the livedocs code, or the
sequential-vs-parallel federation. It contradicts the 99e2b663 commit
message / docstring claim "lower-casing changes no token or hit": for this
query (the only difference is "How" → "how") the BM25F leg's hits change.
Cause inside tantivy's parser NOT investigated (unmeasured).

## Livedocs G1/G2 on the 19 uncovered topics

NOT RUN. The time existed after M1 (06:04Z) but the 2026-09-29 harness
(`scripts/experiments/eval_delta_ingest_livedocs_bitset.py`) has no
topic-offset option, imports `lib` from the shared working tree (which
holds another agent's uncommitted `src/lib/thinclient/delta_layer.py`
edit), and was written against the parallel backend, while the stage-dir-
empty default now selects the sequential one. Changing that harness and
re-validating it was not safe in the remaining window.
