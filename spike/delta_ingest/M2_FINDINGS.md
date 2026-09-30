# M2 findings: delta-shard recall on corpus (a)

**Status:** ACTIVE

Measured 2026-09-30 (UTC) on this host (16 cores, 31 GB, WSL2), sharing it
with the in-place spike's B7 (cores 0-7, latency lock) and S0-2 (up to 27.8 GB
RSS), and the M3/M8 agents. Bars are those of `docs/delta_ingest/03_SPIKE_PLAN.md`
row M2, unchanged. Numbers below are copied from the results file; the file is
authoritative.

- Results: `data/eval_results/delta_ingest_M2_20260930.json`
- Harness: `scripts/experiments/eval_delta_ingest_m2_delta_recall.py`
  (pre-registration commit 885c29e7; deviation note 11a690e4, written before
  any DELTA-arm query of the sample ran; measured code = `git archive
  885c29e7 src spike/delta_ingest`)

## Corpus (a) fixture (shared with M3)

- Root `/home/vscode/work/delta_ingest/corpus_a/root`, `READY.json` next to it
  (published 2026-09-30 18:13Z).
- Population: base docs in `social_sciences__recent`, the only hot section and
  so the only one with a local abstract sidecar (23.4M docs). Corpus (a) is
  therefore ONE section of ten, not a whole-corpus sample.
- Sampling: seeded permutation (`sfu-delta-m2-2026-09-30`) over that
  section's ordinals; 50,203 walked, 203 rejected for an empty title, 0 for a
  missing abstract; 50,000 kept.
- Update: meta title/doi/year/type/is_oa + sidecar abstract + the fixed
  sentence "This record was updated after publication." Ids are bare W-ids.
- Build: CLI `ingest --source jsonl --namespace openalex` (desktop_gpu, GPU
  encode; ONNX TensorRT provider missing, CUDA fallback as in O8) then
  `flush --force`, with the frozen M4 base manifest and
  `SFU_THINCLIENT_ORDINALS` set (the snapshot predates O9's `--ordinal-dir`).
  Ingest classified 50,000 updated / 0 new / 0 unchanged, encoded 50,000.
  g0001: 50,000 docs with vectors, SEISMIC build 16.7 s (dim 25,099, nnz
  4,238,135), c1a 1.2 s, dotvbyte 1.4 s, 631 MB on disk.
- Verify: generations.json = g0001 with 50,000 docs; livedocs `.liv` popcount
  50,000 (superseded_in_base 50,000, deleted 0); shard_manifest = 8 base + 1
  delta shard; buffer 0. Gate-on `search_rrf` smoke: health OK (9 shards,
  origins [None x 8, 1], livedocs per-shard filter attached, cross-encoder
  loaded), 50 results, the target doc at rank 1; no ENOMEM/fallback lines.

## Results

| Bar (plan row M2, verbatim) | Measured | Verdict |
|---|---|---|
| own-recall of the delta copy >= 0.95 of the base's own-recall (k=10, SPLADE leg, title-as-query) | BASE 956/1,352 = 0.7071; DELTA (delta copy only) 1,108/1,352 = 0.8195; ratio **1.159** | **PASS, PARTIAL** (1,352 of the N=2,000 the probe rule set) |
| per-shard overlap@10 vs exact dot product >= 0.99 on each set (E8 params) | 120 topics 0.9975 (min 0.9, 117/120 identical as a set, 96 in order); 100 diverse 1.0 (100/100 set, 81 in order); 1,000 titles 0.9968 (min 0.9, 968 set, 819 in order) | **PASS** |
| mask leak (sampled doc returned by both copies / base copy surviving the filter) must be 0 | 0 of 1,352 (the base copy was in a base shard's top-k' before the filter for 1,043; the filter removed every one) | **PASS** |

Supplementary (no bar):
- k=50: BASE 0.7441, DELTA 0.8728 (ratio 1.173).
- Transitions at k=10: 154 docs hit only as the delta copy, 2 only as the
  base copy.
- Every DELTA hit was attributed to the delta shard (position 8): 1,108/1,108
  at k=10; the delta copy was in the delta shard's post-filter top-k' for
  1,308 of 1,352.
- Served parameters on the delta shard (k=k'=100, heap 0.8,
  query_cut=len(terms), SFU_SEISMIC_PREFLOOR unset): identical overlap
  numbers to the E8 params on all three sets.

Reading the ratio: it is above 1 because the two copies do not compete
against the same corpus. The base copy is ranked inside a 18.8M-doc base shard
(SEISMIC approximate, per-shard k'=100), the delta copy inside a 50k-doc
shard where SEISMIC is near exact (the overlap bar above). A base copy was
absent from every base shard's top-100 for 309 of 1,352 titles, and BASE
recall@50 is only 0.744. So the bar is met, but the number says "an update
does not lose SPLADE-leg recall", not "the delta shard ranks like the base":
the delta copy is favoured, and at larger generation sizes the ratio should
fall toward 1 (*est.*, unmeasured). The appended sentence also changes the
doc vector slightly; its effect is not separated.

## Deviations

- N: the 50-query probe (delta arm, the last 50 ids of the permuted list,
  18:15Z) measured p50 4.6 s/query and the rule gave N=2,000 (the floor).
- The BASE arm then slowed to more than 11 s/query while the S0-2 process
  grew to 27.8 GB RSS (swap 15/16 GB used, MemAvailable 2.3 GB at 19:30Z).
  Before any DELTA-arm query of the sample ran, I committed a deviation
  (11a690e4): stop BASE with SIGINT at 20:50Z, then run DELTA on the same
  order. BASE stopped at 1,352 rows. DELTA ran 20:50Z-22:53Z and was stopped
  by SIGINT after 1,440 rows. The verdict uses the common prefix of 1,352,
  as pre-registered for a deadline stop, and is PARTIAL because
  1,352 < 2,000.
- Both arm logs end with a KeyboardInterrupt traceback from those stops.
  That is the only warning signature in either log; no ENOMEM or fallback
  lines. Health passed before the first query in both arms: BASE 8 shards,
  no delta layer; DELTA 9 shards, generations [1], livedocs popcount 50,000,
  per-shard filter attached, buffer 0.
- The 20:50Z stop script used `pgrep -f`. It matched the base child and also
  a zsh wait loop of another session (pid 635753) whose command line
  contained the pattern. That shell got one SIGINT and kept running.

## Host conditions

Load 7 to 13 throughout. B7 held cores 0-7. S0-2 ran on cores 8-15 at 3 to
27.8 GB RSS. The M3 agent and an rsync were also running. The GPU was idle
except for this fixture's encode. Every wall/latency field is
`timings_valid: false`.

## Issues found (not fixed; not my files)

- `spike/delta_ingest/generation.py` `build_seismic_shard`/`build_generation`:
  `generation.json` `seismic.jsonl` and `seismic.stock` keep absolute paths
  under `gNNNN.building/`, which no longer exist after the rename to
  `gNNNN/`. `mmap_dir` is made relative, so serving is unaffected.
- O8 seen again: the ingest log shows the TensorRT provider failing to load
  (`libnvinfer.so.10` missing), so the encode falls back to CUDA.

## Not measured

- The remaining 648 queries of N=2,000, and the pre-registered 10,000 target.
- Recall for the other nine sections (no local sidecar). Corpus (a) is
  `social_sciences__recent` only.
- The effect of the appended sentence alone (vector drift), and how the
  ratio changes with generation size.
- The full `search_rrf` / fused list (that is M3's question).
