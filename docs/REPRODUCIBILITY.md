# Reproducibility — rebuilding the index from the public OpenAlex snapshot, and re-scoring the headline numbers

**Status:** ACTIVE

**Created 2026-10-10. The rebuild path is MEASURED (one 50,000-work run on
this host, both serve checks PASS). The query-encoder export recipe and the
rerank-model fallbacks are documented from code, UNMEASURED this session.**

This doc answers the question an outside reader asks first: *what in this
repository can I actually reproduce?* Short version: every number's inputs
and evidence are in git; the served 150-million-document index is not, but
you can rebuild a servable index of any size from the public OpenAlex
snapshot with one command, and the headline quality numbers can be
re-scored against frozen judgments without re-judging.

## 1. What is in git and what is not

| In git | Not in git (local artifacts) |
|---|---|
| all serving and build code (`src/`, `spike/delta_ingest/`), the GUI, the MCP server | the served 150M index (`data/thinclient_index/`, `data/seismic_150m/`, ~180 GB) |
| every measurement file under `data/eval_results/` (1,500+; index: `data/eval_results/INDEX.md`) | encoder and reranker weights under `models/` (SPLADE ONNX export, in-house cross-encoder and embed fine-tunes) |
| the eval queries, relevance judgments and both LLM-judge caches (`dense_ablation_topics_20260817.json`, `dense_ablation_qrels_20260817.json`, `dense_ablation_judge_cache_20260817.json`, `seismic_kimi_judge_cache.json`) | the built Rust tools (`spike/seismic_upstream/target/release/`) — the fork itself is tracked as a patch, §3 |
| the SEISMIC fork as `spike/seismic_upstream_fork.patch` against upstream `v0.4.0` | the OpenAlex snapshot parts |
| every design decision, pre-registration and FAIL alongside every PASS (`docs/`) | |

## 2. The rebuild path (one command)

```bash
.venv/bin/python3 scripts/reproduce/rebuild_from_openalex.py \
    --work /var/tmp/duck_rebuild --download 1 --limit 50000
```

`--download N` picks N part files from the live snapshot manifest
(`https://openalex.s3.amazonaws.com/data/jsonl/works/manifest.json`, 2,040
parts, 476 M works, 659 GB on 2026-09-23); `--part <file.gz>` uses parts you
already have. The driver then runs the delta-ingest chain against an EMPTY
base index so the whole corpus lands in one published generation, and
serves that generation directory directly as the index root:

| Step | Code reused | Output |
|---|---|---|
| read + normalise each work, rebuild the abstract from `abstract_inverted_index` | `spike/delta_ingest/adapters.py` `JsonlAdapter(openalex_shape=True)`, `records.py` `normalize_openalex_work` / `reconstruct_abstract` | `DocRecord` stream (works without a usable abstract, under 50 chars or paratext, are dropped here) |
| subject × era section | `src/lib/thinclient/sections.py` `classify_doc` | `<base>__<recent|archive>` |
| SPLADE document encode (GPU if present, CPU otherwise) | `src/lib/thinclient/doc_encoder.py` (pulls `prithivida/Splade_PP_en_v1` from the Hugging Face hub on first use) | top-256 sparse vectors |
| tantivy BM25F per section + `meta.sqlite` v2 + abstract sidecars | `src/lib/thinclient/builder.py` `SectionBuilder` | `g0001/sections/*/tantivy`, `g0001/meta.sqlite`, `abstracts.sqlite` |
| SEISMIC stock build → f16 mmap → dotvbyte v2 (the served format) | `spike/delta_ingest/generation.py` `build_seismic_shard` → `c1a_mmap_index`, `convert_f16_to_dotvbyte` (Rust) | `g0001/seismic/*.dotvbyte.v2.mmap` |
| shard manifest + `serve.env` | `generation.py` `publish`; the driver | `delta/shard_manifests/*.json`, `<work>/serve.env` |
| serve check | `scripts/reproduce/verify_rebuild.py` → `ThinClientRetriever.search_rrf(with_provenance=True)` | `<work>/verify.json` |

Then serve it:

```bash
set -a; . /var/tmp/duck_rebuild/serve.env; set +a
scripts/serve_http.sh            # or: PYTHONPATH=src .venv/bin/python3 scripts/reproduce/verify_rebuild.py
```

`serve.env` sets `SFU_THINCLIENT_INDEX_ROOT=<work>/delta/g0001`,
`SFU_SEISMIC_SHARD_MANIFEST=<the composed manifest>`,
`SFU_SPLADE_BACKEND=seismic`, `SFU_SEISMIC_LOAD_MODE=mmap`, `SFU_DENSE_LEG=0`.

### 2.1 Measured record (2026-10-10, this host)

Host: WSL2, 16 cores, 54.9 GB RAM, RTX 4070 Ti SUPER 16 GB, glibc 2.36,
venv Python 3.11. Input: `s3://openalex/data/jsonl/works/updated_date=2026-09-17/part_0005.gz`
(57,643 works, 91.8 MB), first 50,000 lines. Encoder: ONNX Runtime CUDA EP
(TensorRT absent on this host, the documented fallback).

| Metric | Value |
|---|---|
| input lines read | 50,000 |
| works kept (usable abstract) | **21,122** (42.2 %) |
| sections built | 10 (5 subjects × 2 eras) |
| ingest incl. GPU encode, uncontended run | **149 s** |
| flush (tantivy + meta + sidecars + SEISMIC chain) | **31–33 s** (SEISMIC build 4.9 s, f16 mmap 0.8 s, dotvbyte 1.1–1.3 s) |
| **end to end, uncontended** | **182 s** (`/var/tmp/duck_repro/run.log`, manual invocation of the same two CLI commands) |
| **end to end via the driver, quiet host** (`rebuild_from_openalex.py --part … --limit 50000`) | **244.4 s** = ingest 130.3 + flush 31.2 + verify 82.8; the verify step is almost entirely the first SPLADE query-model load in a fresh process, so **build-only ≈ 162 s** |
| same driver run while an 85 GB gitleaks scan hammered the same disk | 450.7 s (kept for honesty: IO contention roughly triples the ingest step) |
| fixed per-process start-up inside the ingest step (encoder import + model load) | ≈ 80 s (the 247-doc download run's ingest took 86.4 s) |
| generation on disk | 364 MB total: SEISMIC mmap 105 MB, sections 20 MB, `meta.sqlite` 3.6 MB, abstracts + stock SEISMIC + jsonl the rest |
| SEISMIC shard | 21,122 docs, dim 23,266, 1.96 M postings, status `served` |
| serve check | **PASS**: 3 queries × 10 hits, BM25F and SPLADE both contributing (7/7, 7/7, 6/5 of 10), every hit with title, year and abstract; warm query wall 40–90 ms; first query 80–87 s (query-encoder cold load, one-time per process) |

Results files: `data/eval_results/reproduce_openalex_50k_2026-10-10.json`
(both runs' reports + the verify output).

**Scaling (documented elsewhere, not re-measured here):** GPU encode
~3.1 k docs/s with TensorRT, ~630 docs/s on ORT-CUDA under contention, ~12
docs/s CPU fp32 (`doc_encoder.py`, `docs/delta_ingest/03_SPIKE_PLAN.md`);
one 18.8 M-doc SEISMIC shard builds in ~17 min at ~10 GB peak
(`docs/seismic_150m_testbed/REBUILD_TO_PERSISTENT_PATH.md`). The driver
raises the flush thresholds so a run lands in ONE generation; the
generation builder holds its records in memory, so keep a single run under
roughly a million works on a 32 GB host (*est.*) and use several work
dirs, or several generations behind `SFU_DELTA_ROOT`, beyond that (§2.3).

### 2.2 Second run — the download path

`--download 1 --min-records 1500 --max-records 6000` on the same host picked
`updated_date=2026-08-26/part_0099.gz` (2,624 works, 2.9 MB): download
1.3 s, ingest 86.4 s, flush 2.9 s, verify 78.8 s (PASS), total 169.4 s —
and only **247 works kept (9.4 %)**, against 42 % for the 2026-09-17 part.
Abstract coverage swings by part, so size a corpus by kept docs. It
exercises manifest fetch, part selection, size-checked download and the
same chain; results file key `download_run`.

### 2.3 Findings and limits

- **Serve the generation directory, not the empty base.** With the empty
  base as index root and `SFU_DELTA_ROOT` pointing at the delta root (the
  multi-generation serve path, measured in `docs/delta_ingest/` M2/M3 on a
  real base), hits came back with ids and abstracts but **blank title and
  year**; the generation-as-root path hydrates fully. Cause not chased
  (UNMEASURED); for single-run rebuilds the driver uses the generation dir.
  Multi-generation standalone serving therefore needs that hydration gap
  closed first.
- **E5 forward reorder is not applied.** The served 150M shards carry the
  E5 co-access reorder (latency-only, quality-identical,
  `docs/seismic_150m_testbed/13_E5_FORWARD_REORDER_DESIGN.md`); the rebuild
  ships plain dotvbyte v2. Rankings are unaffected.
- **The dense leg is off**, as in production (`SFU_DENSE_LEG` default OFF
  since the 2026-08-18 ablation).
- **`cited_by_count` is not carried into `meta.sqlite`** (the long-standing
  WI-5 citation-axis gap); it rides in `DocRecord.extra` only.
- **Abstract coverage decides corpus size.** 42 % of a recent part had a
  usable abstract; older parts differ. Size your `--limit` by kept docs, not
  lines.

## 3. Prerequisites an outside machine needs

1. **Python environment**: the venv wheel set (`requirements.txt`); CPU-only
   serving is measured byte-identical to GPU
   (`infrastructure/PORTABLE_STACK_MANIFEST.md` §(d) row 6). The build step
   is GPU-practical only above a few hundred thousand works.
2. **The SEISMIC fork and the two Rust tools.** The fork is upstream
   `TusKANNy/seismic` tag **`v0.4.0`** (commit `aa5f81a8`) plus ONE tracked
   patch, `spike/seismic_upstream_fork.patch` (6,489 lines; verified
   2026-10-10 to apply cleanly on `v0.4.0`; the four smaller
   `spike/seismic_upstream_*.patch` files are already contained in it):
   ```bash
   git clone https://github.com/TusKANNy/seismic.git spike/seismic_upstream
   git -C spike/seismic_upstream checkout v0.4.0
   git -C spike/seismic_upstream apply ../seismic_upstream_fork.patch
   cd spike/seismic_upstream
   RUSTFLAGS='-C target-cpu=x86-64-v3' maturin build --release -i ../../.venv/bin/python3
   ../../.venv/bin/python3 -m pip install target/wheels/pyseismic_lsr-*.whl
   cargo build --release --bin c1a_mmap_index --bin convert_f16_to_dotvbyte
   ```
   `spike/delta_ingest/generation.py` looks for the two binaries under
   `spike/seismic_upstream/target/release/`. Build with `x86-64-v3`, never
   `native`, if the result is to leave the machine
   (`docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §7.7).
   UNMEASURED this session: the recipe above is read off the fork and the
   docs; the binaries used today were already built.
3. **Models.** Document encoding downloads `prithivida/Splade_PP_en_v1`
   from the Hugging Face hub on first use (network once). Query encoding at
   serve time needs the fused ONNX export at `models/splade_onnx_fused/`
   (`SFU_SPLADE_MODEL_PATH`) **with a bert-base-uncased tokenizer in the
   same dir**; the export is `lib.thinclient.doc_encoder._ensure_onnx_export`
   (FP16 ONNX via `optimum`) followed by
   `scripts/seismic_testbed/d2_ort_fusion_matrix.py` `build_fused`. This
   repo's copy predates the session and the recipe is UNMEASURED here; a
   handout should ship the fused dir plus tokenizer
   (`infrastructure/PORTABLE_LINUX_BUNDLE.md` §1 smoke attempt 1 is what
   happens when the tokenizer is missing: silent BM25F-only fallback).
4. **Rerank models cannot be rebuilt.** `models/sfu-cross-encoder-v1` and
   `models/sfu-academic-embed-v5` are in-house fine-tunes whose trainers
   and training data are gone (`infrastructure/PORTABLE_LICENSING_INVENTORY.md`).
   `search_rrf` (what the rebuild verifies) does not rerank; the MCP/HTTP
   tools do, and without those dirs fall back to the base checkpoints
   (`cross-encoder/ms-marco-MiniLM-L-6-v2`; `lib/embedding.py` default).
   Rankings after rerank then differ from the measured ones. UNMEASURED.

## 4. Re-scoring the headline numbers (what a reader can verify)

The quality claims are LLM-judged nDCG@10 over 120 topics
(`docs/BENCHMARK_METHODOLOGY.md`). Reproducing them means re-scoring the
served shards against the **frozen** judgments, not re-judging: the two
judges disagree with each other at 50 % exact agreement
(`kimi_vs_haiku_rebake_20260629.json`), so a fresh judge yields a different
regime, not a replication.

| Claim | Frozen inputs (in git) | Harness | What it needs | Result it must match |
|---|---|---|---|---|
| served E8 dv-v2 SPLADE leg nDCG@10 0.9426 (Haiku) / 0.9249 (Kimi), n=120, 2026-09-27 | `dense_ablation_topics_20260817.json`, `dense_ablation_qrels_20260817.json`, `dense_ablation_judge_cache_20260817.json`, `seismic_kimi_judge_cache.json` | `scripts/seismic_testbed/seismic_quality_eval.py` | the 150M shards or any rebuild of them; cache-only scoring, no judge calls | `docs/BENCHMARK_METHODOLOGY.md` §"Served E8 dv-v2 SPLADE leg" + its results files |
| dense-leg ablation DROP verdict (Δ nDCG@10 −0.0077) | same topics/qrels/cache | `scripts/experiments/` dense ablation harness named in `docs/DENSE_PARTITION_AND_ABLATION.md` | 150M index + the 600k dense seed | `DENSE_PARTITION_AND_ABLATION.md` §verdict |
| parity numbers (byte-identical top-10 across CPU/GPU, speculative rerank, delta gate) | the 120 `natural` topics | `scripts/experiments/eval_cpu_only_serve_path.py`, `scripts/run_parity_safe.sh` | 150M index | the cited `data/eval_results/*.json` |
| storage levers 300.9 → 188.8 GB | measured sizes recorded per lever | `docs/STORAGE_BUDGET_150M.md`, `docs/LEXICAL_STORAGE_RESEARCH.md` | the full-corpus artifacts | the tables in those docs |

Honest statement for a paper: a reader with this repo can (a) audit every
number against its evidence file and the frozen judgments, (b) rebuild and
serve a corpus of their chosen size from public data with one command,
measured here at 182 s for 21 k works, and (c) reproduce the 150M numbers
only by re-running the full build (~13.5 h GPU encode plus shard builds,
documented estimates) or by obtaining the index. The convergence-artifact
track's discipline (pre-registered bars, one results file per cell,
analysis scripts that read only results files) is the template every table
above follows; see `session_2026-07-14_f6_corrections_r1_ladder/04_CONVERGENCE_ARTIFACT.md`.

## 5. Files

- `scripts/reproduce/rebuild_from_openalex.py` — the driver (download, ingest, flush, serve.env, verify, report)
- `scripts/reproduce/verify_rebuild.py` — the serve check (also usable on any index root)
- `scripts/reproduce/README.md` — family README
- `data/eval_results/reproduce_openalex_50k_2026-10-10.json` — the measured record
