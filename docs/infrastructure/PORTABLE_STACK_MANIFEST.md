# Portable-stack dependency manifest — what a Qdrant-free, docker-free handout bundles

**Status:** ACTIVE

**Created 2026-07-17 (deployprep wave 2, WI-8). STAGING / authoring only — not
an installer.** The portable handout (`docs/LOCALIZED_DEPLOYMENT_PLAN.md` §2
"Subset" tier) must bundle *exactly* what the serve path needs — today that's
implicit. This doc is the authoritative manifest of a **Qdrant-free, docker-free**
portable bundle: (a) the runtime imports the staging serve path actually loads,
(b) the per-leg artifact inventory with measured file sizes, (c) a staging probe
proving the serve runs env-selected seismic + the v3 portable .so + no Qdrant
reachable, and (d) the delta list of what's still missing for a real installer.

**Parent: `docs/infrastructure/README`-indexed; grandparents
`LOCALIZED_DEPLOYMENT_PLAN.md` (the handout tiers), `16_SUBSET_CORPUS_PILOT.md`
(WI-5 subset blockers) and `10_FORWARD_COMPRESSION_DESIGN.md` §7.7 (WI-4's v3 .so).** The
machine-readable twin of this doc is
`data/eval_results/portable_stack_manifest.json` (regenerate via
`scripts/archive/demo_dependability/wi8_portable_manifest.py`).

**F6-honesty note (2026-07-17):** the 150M figures here are **measured off the
real files on this container** (the served index as-is). The subset-tier
projection is a **formula marked `*est.*`** — WI-5 (`16_SUBSET_CORPUS_PILOT.md`)
measured the full-corpus year-axis cut is 9p-blocked in-container, so the
subset size is *not* a measured full-corpus number here. The v3 .so sizes +
versions are measured off the built artifacts. **No served-default flip:** the
bundle path is env-selected (`SFU_SPLADE_BACKEND=seismic`), the served default
is unchanged; everything here is staging measurement, not a deployed config.

## (a) Runtime imports the staging serve path loads

Audited by **actually loading** the serve path in a venv subprocess (load
`ThinClientRetriever`, fire one `search_rrf` to lazy-load the seismic backend +
ONNX encoder) and dumping `sys.modules` — what loads, not what's grepped.
Conditional imports that don't fire on the seismic path (a Qdrant leg, the BMP
`pisa` leg) are **excluded** — they are not manifest deps for a Qdrant-free
bundle. The corrected probe (`wi8_portable_manifest.py`, 2026-07-17) reports
**210 modules loaded, 24 with resolved dist versions**, and confirms
`qdrant_client` is **NOT in the loaded list + NOT imported on the seismic path**
(`qdrant_client_imported_on_seismic_path: False`; it IS installed, dist
`qdrant-client` 1.18.0, for the env-gated fallback — but unused on this path; that
fallback leg was removed from `retriever.py` 2026-10-12, so no product code imports it now).
(The full per-package list + versions is in the JSON twin; the table below is
the load-bearing subset, versions from `pip list` + `importlib.metadata` on this
venv 2026-07-17.)

| Package | Version (venv) | Why the serve path needs it |
|---|---|---|
| `tantivy` | 0.26.0 | the BM25F leg (8 sections, `lib.thinclient.retriever`) |
| `seismic` (pyo3 .so) | built | the SPLADE/SEISMIC leg — WI-4's v3 portable .so ships here |
| `usearch` | 2.25.3 | the dense leg (int8 rescore index) |
| `numpy` | 2.4.3 | dense vectors + SPLADE encode tensor feeds |
| `onnxruntime` | 1.26.0 (dist `onnxruntime-gpu`) | the SPLADE query encoder (`ort.InferenceSession`, CPUExecutionProvider); the dist name is `onnxruntime-gpu`, the import name is `onnxruntime` — a bundler pins the dist |
| `transformers` | 4.57.6 | the SPLADE tokenizer (`AutoTokenizer`, bert-base-uncased vocab 30522) |
| `tokenizers` | 0.22.2 | transformers' fast tokenizer backend |
| `sentence-transformers` | 5.4.1 | the dense query encoder (sfu-academic-embed-v5) |
| `torch` | 2.6.0+cu124 | embed-rerank bi-encoder + torch cross-encoder runtime (and the optional dense leg). **Corrected 2026-09-27:** on this host both serve-path models run on CUDA when it is visible (automatic device selection, no hard-coded device); with CUDA absent they run on CPU with byte-identical final rankings, and `torch 2.6.0+cpu` serves the same path — §(d) row 6 |
| `zstandard` | 0.25.0 | packed abstract decompression (the `packed/` zst spool) |
| `regex` | 2026.4.4 | tokenizer regex backend |
| `scipy` / `scikit-learn` | 1.17.1 / 1.8.0 | query-encoding / dense-rescore helpers (transitive-ish; pinned in the manifest) |
| stdlib only (the staging serve) | — | `sqlite3`, `http.server`, `urllib`, `json`, `threading`, `ctypes` (meta.sqlite + the staging HTTP server need no third-party) |

**Explicitly NOT on the seismic serve path** (so NOT in the bundle): `qdrant_client`
(installed in this venv as 1.18.0 for the Qdrant fallback leg, removed from
`retriever.py` 2026-10-12; the seismic path never imported it — confirmed by the staging probe's
`qdrant_client_imported_on_seismic_path=False`); the `bmp` / `pisa` leg
(`SFU_SKIP_BMP=1`); `openai`/`requests` (the live-API abstracts fallback,
optional and owner-gated, not a serve-path dep).

## (b) Artifact inventory — per leg, measured sizes (150M, as-is)

Measured off the real files 2026-07-17 (the served index as-is on this
container). Total portable bundle at 150M ≈ **~185 GB** as-is — far above a
laptop; the **subset tier** carries the handout's real size (below).

| Leg / artifact | Path | Measured size | Notes |
|---|---|---|---|
| **SEISMIC SPLADE** (8 shards) | `data/seismic_150m/index/plan01/global_shard{0..7}of8.dotvbyte.e5.v2.mmap` | **44.41 GB** (41.36 GiB; `du -sb` over the eight `*.e5.v2.mmap` directories, re-measured 2026-10-19; on-disk = mmap-resident). **Correction 2026-10-19:** this cell read 66.24 GB from 2026-07-17 until today; that figure is the f16 `global_shard*of8.mmap` set (66.24 GB measured the same day), not the served dv-v2 shards. The dotvbyte forward codec is what takes the set 66.24 → 44.41 GB on disk | the promoted E8 dv-v2 layout; per-shard mmap_dir sizes in the JSON twin |
| **BM25F** (tantivy) + meta + packed | `data/thinclient_index/` | **114.80 GB** total | includes `meta.sqlite` 24.91 GB + `packed/` abstracts 44.98 GB + `dense/` 0.36 GB + 8 tantivy sections |
| └ meta.sqlite | `data/thinclient_index/meta.sqlite` | 24.91 GB | the docs/doi/year/section metadata db (citation axis absent — WI-5) |
| └ packed abstracts | `data/thinclient_index/packed/` | 44.98 GB | zstd-compressed abstracts (the hydration leg) |
| **Dense** (usearch) | `data/thinclient_index/dense/` | 0.36 GB (**0.357 GB** exactly, measured 2026-08-17) | int8 rescore index, partial-coverage subset (the dense POC — 600k = **0.4%** of 150M). **OPTIONAL COMPONENT**: `b1.usearch` + `rescore_int8.npy` + `ids.json` are excludable as a unit via the `SFU_DENSE_LEG` gate (**DEFAULT OFF since 2026-08-18** — ablation DROP verdict; only literal `1` enables; serving verified to degrade cleanly without them). `delta.sqlite` inside this directory is warm-cache runtime state — never shipped. Keep/drop evidence: `docs/DENSE_PARTITION_AND_ABLATION.md` |
| **SPLADE encoder** | `models/splade_onnx_fused/` | 0.53 GB | the offline fused ONNX export (the served default since D2) |
| **Dense encoder** | `models/sfu-academic-embed-v5/` | 3.34 GB (**serving-essential 128.3 MiB** — the rest is `checkpoints/` training state the serve path never opens) | sentence-transformers export. ⚠️ **Misnamed: not dense-only.** The SAME model backs the embed-rerank stage (`lib/config.py` `_DEFAULT_EMBED_MODEL_PATH` → `lib/reranker._compute_semantic_scores` → `lib/embedding`, with `lib/tools.py` passing `use_embedding=True` unconditionally), so it is **NOT part of the excludable dense partition** — dropping the dense leg does not drop this model. See `docs/DENSE_PARTITION_AND_ABLATION.md` |
| **portable .so (v3)** | `spike/seismic_upstream/target/portable_so/v3/seismic/seismic.cpython-311-x86_64-linux-gnu.so` | **2.70 MB** | WI-4's x86-64-v3 build — parity bit-identical (overlap@10 1.0), warm 0.96× versus native. **Ships NOT the `target-cpu=native` .so.** |

### Subset-tier projection (`*est.*` — formula, not a measured full-corpus cut)

The handout's real size is the **subset tier** (`LOCALIZED_DEPLOYMENT_PLAN.md` §2:
~10–15M docs on a 20–40 GB laptop). The projection:

```
subset_bundle_gb ≈ (subset_docs / 150_413_098)
                  × (seismic_on_disk_total_gb + packed_abstracts_gb)
                  + splade_encoder_gb + dense_encoder_gb + v3_so_mb
```

WI-5 (`16_SUBSET_CORPUS_PILOT.md`) measured: the full-corpus year-axis cut is
9p-blocked in-container (meta.sqlite has no `year` index + is a 25 GB file on
9p → ~22 min/full-scan). The plan's §3 figure "2022+ = 83M docs" came from the
**live source index (pre-thinclient)**, not corroborated here. So this is
`*est.*`, design-only: linear-in-docs scaling (the working hypothesis), landing
a ~10M subset at **~7–8 GB index + ~4 GB encoders ≈ ~12 GB** — plausibly inside a
20–40 GB laptop. **A real subset number is a host-tier follow-on** (re-export the
spool with `cited_by_count` + build the subset shard — WI-5's unblock sequence,
owner-gated).

## (c) Staging probe — serve runs Qdrant-free + the v3 .so, no served flip

The probe (`wi8_portable_manifest.py::_staging_probe`, run 2026-07-17) loads the
retriever with `SFU_SPLADE_BACKEND=seismic` + `SFU_SEISMIC_FEDERATION=parallel`,
fires a real `search_rrf` (without ever importing `qdrant_client` itself), then
verifies (1) `qdrant_client` was **not** imported on the path
(`qdrant_client_imported_on_seismic_path: False` ✓; `qdrant_client_installed:
True` — installed for the env-gated fallback but unused on the seismic path),
(2) the v3 .so is loadable by **explicit path** (`v3_so_loadable: True`; loaded
under module name `seismic` to match `PyInit_seismic`, exports
`MmapSeismicIndex` the served Path-C class + `SeismicIndex*` variants), (3) the
seismic backend was what served (`seismic_backend_served: True`), (4) the probe
search completed cleanly (`probe_search_error: None`). rc=0. The full booleans +
export list are in the JSON twin. (Earlier probe run had a self-fulfilling
qdrant check — `import qdrant_client` *then* check `sys.modules`; fixed to
`importlib.util.find_spec` + a clean `sys.modules` inspection after the search.)

**This is env-selected, NOT a served-default flip** (the served default stays
`seismic`; the v3 .so is loadable-by-explicit-path, the production `.so` stays
`native` until an operator swaps v3 in per WI-4's owner-gated note).

## (d) Delta — what's still missing for a real installer

> **Reconciled 2026-09-27** — 6 items: 2 DONE (row 4, Linux x86-64 recipe MEASURED
> 2026-09-27, `PORTABLE_LINUX_BUNDLE.md`; row 6, CPU-only serve path end-to-end
> MEASURED 2026-09-27, `cpu_only_serve_path_2026-09-27.json`), 0 CLOSED, 0 SUPERSEDED,
> 4 STILL OPEN (rows 1, 2, 3, 5).
> (2026-09-25 reconciliation: 0 DONE, 6 STILL OPEN — text below kept as written then.)
> Every row below is genuinely still open: none has a measured closure. What HAS
> moved since 2026-07-17 is the `portable_socsci` Windows track (build kit
> 2026-08-04 commit `f77435c7`; `seismic.pyd` + relocatable `python\` compiled
> on-drive 2026-08-05/06), which implements the *mechanism* for rows 1, 4 and 6 —
> but its Windows-side serving efficacy is explicitly **UNMEASURED**
> (`PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` §8), so none of those rows closes.
> **None of these six appears as open work in `docs/README.md`'s Active tables or
> in `docs/infrastructure/README.md`** — both describe this doc only as a manifest.

| # | Item | Status | Owning doc | Note |
|---|---|---|---|---|
| 1 | **Windows / mmap portability** | OPEN | this doc §delta | the seismic .so is Linux x86-64-v3; a Windows handout needs a native Windows build (or a WSL2 bundle). The mmap load path (`load_mode="mmap"`) is POSIX. Test on a Windows host before claiming portability there. — **STILL OPEN 2026-09-25** — mechanism built, question unanswered: `scripts/portable_socsci/06_windows_buildkit.py` + `windows/build_windows_runtime.ps1` (2026-08-04, commit `f77435c7`) vendor the Rust fork offline and `maturin build` a portable x86-64-v3 `seismic.pyd`, and it was **compiled on-drive 2026-08-05/06**. The load-bearing question — does `seismic.pyd` load, mmap and serve bit-exact on Windows — is **UNMEASURED** (`PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` §8) and needs a real Windows host. |
| 2 | **spool re-export for a subset bundle** | OPEN (host-tier) | `16_SUBSET_CORPUS_PILOT.md` (WI-5) | a subset-tier bundle needs the pre-encoded sparse spool re-exported WITH `cited_by_count` added to `build_thinclient_index.EXPORT_FIELDS`. A full-150M bundle ships the as-is shards and skips this. — **STILL OPEN 2026-09-25** — unchanged since 2026-07-17; `cited_by_count` was never added to `build_thinclient_index.EXPORT_FIELDS` and no subset spool exists. Still runnable here (a local build job, not a cloud one), so it is NOT closed by the 2026-09-25 loss of cloud access. |
| 3 | ** licensing check** | OPEN | this doc §delta | the SPLADE ONNX model, the dense v5 model, and the corpus's OpenAlex license must be cleared for redistribution before any real public handout. Unmeasured — a legal/metadata gate, not a technical one. — **STILL OPEN 2026-09-25** — unchanged; a legal/metadata gate, nothing measurable, no owner recorded. — **INVENTORY DONE 2026-09-29, ROW STAYS OPEN**: the complete factual inventory a decision-maker needs is `PORTABLE_LICENSING_INVENTORY.md` (one row per redistributable component: every shipped model with its base-checkpoint provenance, the OpenAlex corpus (CC0, with the reconstructed-abstract nuance), every top-level runtime wheel from its dist-info, the seismic/vectorium/toolkit forks, the statically linked crates, python-build-standalone, and the project's own code). Headline: the forks and top-level wheels state permissive licences; `splade_onnx*` and the three `sfu-cross-encoder-*` directories are NOT STATED (Apache-2.0 inherited candidates); **the repository itself has no LICENSE file**; 209/247 Rust crates and ~45 transitive wheels are untallied. The gate is a human sign-off — no owner recorded, no clearance given. |
| 4 | **python runtime bundling** | OPEN | this doc §delta | the manifest lists the packages; an installer still needs a frozen/relocatable python (for example, `python-build-standalone`) + the v3 .so placed on its import path. The `~~ismic`/`~-ismic` tilted-name directories in the venv (seismic .so variant slots) show the import-path dance; an installer must reproduce it deterministically. — **STILL OPEN 2026-09-25** — the socsci Windows bundle implements exactly this pattern (relocatable CPython fetched + CPU serving wheels installed into `python\` by `build_windows_runtime.ps1`, 2026-08-04), but only for that one bundle and only unmeasured; the generic Linux handout still has no frozen/relocatable python and no deterministic `.so` import-path recipe. — **DONE (Linux x86-64) — MEASURED 2026-09-27** (`PORTABLE_LINUX_BUNDLE.md`; `scripts/portable_linux/build_linux_runtime.sh`; `data/eval_results/portable_linux_bundle_2026-09-27.json`): python-build-standalone CPython 3.11.16 (tag 20260924, sha256-pinned) + a 63-wheel sha256 lock (CPU only: torch 2.6.0+cpu, onnxruntime 1.26.0) + the v3 `.so` in `ext/seismic/` put on `sys.path` by ONE relative `.pth` (no tilted-name directories). Bundle **1.18 GiB** (runtime 78 MiB / wheels 1.10 GiB / `.so` 2.6 MiB / source 0.65 MiB), cold build **35.9 s**, warm offline 13.7 s; **builds byte-identical** (one `bundle_sha256` over 25,249 files across output paths and cold/offline caches); **relocation PASS** (moved directory, import check re-run from elsewhere); import check PASS (`torch.cuda.is_available()` False, ORT providers Azure-stub + CPU only, cp311 `.so` loads). Host floor glibc ≥ 2.34 + x86-64-v3, verified only on this glibc 2.36 host. One-query `search_rrf` smoke: **PASS** on the 2nd attempt (10 hits, SEISMIC served from the bundle's `.so`, 18.8 s first-query wall in a fresh process); the 1st attempt FAILED to a silent BM25F-only fallback because `models/splade_onnx_fused` carries no tokenizer and the serve path borrows one from code-relative model directories — a handout must ship the tokenizer inside the SPLADE dir. What row 4 does NOT cover: a second machine, and the full HTTP serve + rerank on CPU (row 6). |
| 5 | **macOS / ARM** | OPEN | this doc §delta | untested — the v3 .so is x86-64-v3 only; Apple Silicon needs an arm64 build (or Rosetta for the .so + native python, which is fragile). No measured number. — **STILL OPEN 2026-09-25, and now untestable without new hardware** — still x86-64-v3 only, no arm64 build attempted, no measured number. The only ARM target ever in scope (OCI's Always-Free A1 shape, already "parked") went away with cloud access on 2026-09-25, and the surviving machine is an x86-64 WSL2 host, so there is no ARM or macOS hardware to test on. |
| 6 | **CPU-only runtime wheels** | DONE 2026-09-27 (MEASURED) | this doc §delta | the serve path here imports `torch 2.6.0+cu124` (CUDA) + dist `onnxruntime-gpu` 1.26.0 — a GPU build machine's venv. An END-USER handout must ship **CPU torch** (or no torch, if the dense encoder can run ORT-CPU) + **onnxruntime (CPU)** instead of cu124/gpu (~GBs smaller, no CUDA dependency). The SPLADE encoder already runs `CPUExecutionProvider` (`opensearch_retriever._get_splade_model`), so ORT-CPU serves it; the `sentence-transformers`+`torch` bi-encoder is the torch dependency — ⚠️ **corrected 2026-08-17: that encoder is NOT dense-only**, the embed-rerank stage loads the same model unconditionally, so **disabling the dense leg (`SFU_DENSE_LEG=0`) does NOT close this item**; only dropping embed rerank as well would. Verify the serve path end-to-end with CUDA absent (both encoders on CPU) **before claiming an end-user bundle** (unmeasured here). NOTE: the container-GPU memory rule ("never plan CPU-only for training/bulk-encode") is about the BUILD tier, NOT end-user serve — an end-user handout is serve-only + CPU-only by design; the rule does not forbid CPU wheels for the bundle. — **STILL OPEN 2026-09-25** — a CPU-only serve-path wheel set exists for the socsci Windows bundle (`scripts/portable_socsci/windows/serving_requirements_win.txt`, onnxruntime-based, no torch, 2026-08-04), but this venv still carries `torch 2.6.0+cu124` + dist `onnxruntime-gpu`, and the row's own binding test — verify the serve path end-to-end with CUDA absent, BOTH encoders on CPU — has never been run. The 2026-08-18 dense-leg DROP does not close it (the embed-rerank stage loads the same sentence-transformers model unconditionally), exactly as the row's 2026-08-17 correction says. — **DONE — MEASURED 2026-09-27: the serve path runs end-to-end with CUDA absent, both encoders on CPU, and returns the GPU arm's final top-10 byte for byte.** Harness `scripts/experiments/eval_cpu_only_serve_path.py`, results `data/eval_results/cpu_only_serve_path_2026-09-27.json`. It replays `tools.search_academic_structured`'s sequence (router LOCAL_RRF → `_cache_works` → `_maybe_rerank`: embed rerank + torch CE v1, serving flags) on the 120 `natural` topics of `dense_ablation_qrels_20260817.json`: one GPU warm-up pass, then 2 rotated rounds of 4 arms, each pass a fresh subprocess, each round under the shared measurement flock. Arms: `gpu` (defaults); `cpu` (`CUDA_VISIBLE_DEVICES=""` in the cu124 venv); `cpu_onnx_ce` (same + `SFU_CE_ONNX=1`); `cpu_wheels` (a throwaway venv outside the repository with `torch 2.6.0+cpu` + `onnxruntime 1.26.0` and no CUDA/TensorRT/RAPIDS packages; 0 CUDA libraries mapped in-process). Every CPU worker asserted and recorded `torch.cuda.is_available()` False, embedder + CE on `cpu`, and every live ORT session (SPLADE encoder; the int8 CE when on) on `["CPUExecutionProvider"]`. **(a) Serves:** all 6 CPU passes rc=0, no import or device error, **no product-code change needed** (both models pick their device automatically; nothing calls `.cuda()`). **(b) Parity versus the GPU arm, both torch-CE CPU arms, both passes:** fused list byte-identical 120/120, final top-10 byte-identical 120/120 (order and set), stage-1 top-20 order 120/120; max |Δ| stage-1 score 5.3e-7, CE score 1.7e-5 (2,400 candidates each); each arm is byte-identical pass-to-pass. **(c) Latency, pooled p50 / p95 ms over 240 requests per arm (GPU → CPU):** total cache-miss 4,966 / 7,170 → 5,789 / 7,923 (**+823 ms p50, +17%**; p95 +10.5%); embed rerank 233 / 286 → 721 / 841; CE 56 / 101 → 337 / 379; `_maybe_rerank` p50 285 → 1,059. CPU in both arms, so unchanged within noise: SPLADE query encode p50 42 → 45, SEISMIC traverse 1,516 → 1,651, BM25F leg 2,807 → 2,833, hydrate 127 → 128. The CPU-wheel venv matches the `cpu` arm (total p50 5,743, `_maybe_rerank` 1,053). **(d) Peak RSS (VmHWM, includes mmap'd index pages):** 12.6 GB GPU versus 12.8–12.9 GB CPU; sampled peak anonymous RSS 1.58 GB versus 1.42 GB (CPU wheels 1.35 GB); the GPU arm also held 271 MB of CUDA allocations. **(e) int8 ONNX CE on CPU:** CE stage p50 337 → 219 ms (total p50 5,730) but it is **not** a parity-preserving swap: top-10 order changes on 108/120 topics, set on 39/120 (mean overlap@10 0.968), max |Δ| CE score 1.63 versus torch v1. Caveats: one host (WSL2, 16 cores, torch 8 intra-op threads, shards staged locally); CUDA was made absent by hiding the GPU and by a CPU-wheel venv, not on a machine without an NVIDIA driver; OpenAlex abstracts replayed from a memo built in the warm-up pass (240 calls), so all arms scored identical inputs; the full HTTP serve app was not started (same call sequence, in-process). |

## (e) Update path — how a shipped bundle gets updated (WI-14, 2026-07-17)

A 20–185 GB bundle can't be re-downloaded per update; **this manifest becomes the
update contract once it carries per-artifact `sha256` + `version` + byte size
(shard-granular for indexes)**. WI-14 built that contract + a delta planner + a
crash-safe apply proof. Scripts under `scripts/archive/demo_dependability/`:

- **`portable_bundle_updater.py manifest`** — emits a VERSIONED bundle manifest
  (`data/eval_results/portable_bundle_versions.json`): every artifact as an
  entry with `sha256` + `version` + `bytes`. Each seismic shard `mmap_dir` is
  its OWN entry (immutable shards ⇒ an index update = replace the CHANGED
  shard's files + flip the bundle manifest; unaffected shards are byte-
  identical → the delta names only the changed shard). The `.so` + model weights
  are full-sha256 (small files). **Real-150M shards use pointer-mode**: the
  versioned thing is the shard's `manifest.json` (the pointer that flips),
  NOT the 66 GB of shard data — the data is the immutable artifact the pointer
  is trusted to name, and re-checksumming GBs of it would contend with the live
  serve on the 9p mount. A `dir_version` (sha256 of the file set) detects a
  rebuild. Fixture bundles use full data sha256 (tiny).
- **`portable_bundle_updater.py check`** (`updater_check.py`) — given a LOCAL
  bundle manifest + a "remote" manifest FILE (simulated locally — NO network),
  emits the delta plan: files to fetch (changed/new), total download bytes,
  files unchanged, and the crash-safe APPLY ORDER:
  1. fetch changed/new artifacts **beside** the old (never in-place),
  2. verify each fetched file's `sha256` versus the remote manifest entry,
  3. **FLIP the bundle manifest LAST** (the atomic pointer swap),
  4. keep old files until post-flip verify succeeds (rollback-safe),
  5. (post-healthy-run) delete superseded old files (GC-eligible).
  Rollback = re-flip the bundle manifest to the pre-update manifest; the old
  artifact files were kept (step 4) so no re-fetch is needed — crash-safe: a
  crash mid-apply leaves the old manifest pointing at old files (the flip is
  the only atomic step, and it's last). Machine-readable delta-plan JSON under
  `data/eval_results/wi14_delta_plan_*.json`.
- **`portable_bundle_updater.py apply`** (`updater_apply.py`) — staging proof
  on a tiny FIXTURE bundle (v1→v2 with exactly 2 changed files: shard1
  `data.bin` + the splade `model.onnx`).

### MEASURED 2026-07-17 (`wi14_apply_proof_20260717.json`) — PASS, all 3 bars

| bar | result |
|---|---|
| (b) delta names EXACTLY the changed artifacts (per-file precision) | **PASS** — fetch = {`seismic_shards/shard1`, `splade_model/models/splade_onnx_fused/model.onnx`} (the 2 changed files, not the whole bundle); 4 unchanged |
| (c) applied + sha256-verified before the flip | **PASS** — 2 files staged beside old (old untouched); sha256 verified versus remote manifest; flip only after verify |
| (d) rollback keeps old files present (crash-safe, no re-fetch) | **PASS** — re-flip to v1 manifest; old shard0 directory + old shard1/data.bin + old splade weight all still present |

### Channel / versioning scheme

The versioned manifest carries a `channel` (`stable` / `staging` / `canary`)
+ a `bundle_version` (bumped on any shipped update). A handout user runs
`updater_check.py --local <installed manifest> --remote <latest channel
manifest>` → the delta plan; `updater_apply.py` applies it. The shipped
`portable_stack_manifest.json` (WI-8 §b) is the size inventory; the versioned
`portable_bundle_versions.json` (WI-14) is the update contract layered on top.

### Delta-size expectations for known pending upgrades — costs vary WILDLY by class

> **Reconciled 2026-09-25** — 5 update classes: 2 DONE, 0 CLOSED, 1 SUPERSEDED, 2 STILL OPEN.
> Two of the classes listed as "pending" in 2026-07-17 have since been exercised
> for real (the manifest flip and the E8 dv-v2 re-conversion), and one will never
> ship (the encoder distill: KILLED 2026-07-28). The byte-cost column stays valid
> as a cost model regardless.

This is the headline insight: an "update" is not one size. Different pending
upgrades touch different components, and the download cost spans four orders
of magnitude:

| update class | what changes | download bytes | per the version contract |
|---|---|---|---|
| **manifest flip only** (E5/E8 one-env rollback) | the manifest pointer | ~7.5 KB | shards already resident → **0 data movement** — **DONE 2026-07-14** — this class was exercised for real by the E8 dv-v2 served-default flip (commit `fcfcfb2`; `THIN_CLIENT_SWAP.md` §SPLADE leg): manifest pointer only, shards already resident, one-env rollback to v1.e5 retained. |
| **.so rebuild** (portable v3 recompile / `RUSTFLAGS` target-cpu bump) | 1 file, the `.so` | ~2.7 MB | the cheapest real class — WI-4's `portable_so/v3/seismic...so` — **STILL OPEN 2026-09-25** — the v3 artifact exists and passed WI-4's gates (parity bit-identical overlap@10 1.0, warm 0.96× versus native, 2.70 MB; doc 10 §7.7), but the production `.so` is still the `native` build and the swap stays owner-gated; the upgrade has never been applied. Not listed as open work in `docs/README.md`. |
| **encoder distill** (query-encoder student; doc 14 §5.1) | models only | ~1 GB | the SPLADE ONNX + dense safetensors WEIGHT files; nothing else on the serve path — **SUPERSEDED 2026-07-28** — this upgrade class will not ship: the Q11-C4 distillation build measured 0.726–0.760 versus the 0.99 bar ⇒ KILL, and the encoder book is CLOSED (`seismic_150m_testbed/14_ENCODER_UPGRADE_PATH.md` §6, `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` Q11). The served fused fp32 encoder stays; only doc 14 §5's re-encode branch (never pre-registered) could revive a model-weight update. |
| **E8 dv-v2 re-conversion** (full re-shard of the forward index) | all 8 shards | ~26 GB | every shard's `mmap_dir` rewrites (the per-shard `manifest.json` pointers all change) — **DONE 2026-07-13/14** — all 8 shards re-converted (corpus mean overlap@10 0.9955) and served from 2026-07-14; the ~26 GB figure is now a measured class, not a projection. |
| incremental DATA (new docs without a re-shard) | appended forward records | TBD | **DESIGN ONLY** — the `semantic_docid_ingest` LSM track (below) — **STILL OPEN 2026-09-25** — unchanged: DESIGN ONLY, no code. `docs/README.md` does carry the track (`semantic_docid_ingest/` — "DESIGN ONLY, no code"), so this is the one row here that is indexed; `docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md` Q10's rule still governs ("build only when ingest becomes real"). |

The delta planner reports the actual bytes per update (the fixture proof's
2-file delta = 5 144 bytes; a real class's bytes come from the versioned
manifest's per-artifact `bytes`). **Windows-installer implication**: the
updater is plain python (no network here — a real installer fetches over the
bundle manifest's `channel` URL); the crash-safe flip is the same on Windows
once the .so portability (§delta #1) is solved. The crash-safe apply order +
keep-old-until-verify is what makes a 185 GB bundle's update SURVIVABLE — a
mid-update crash never leaves the bundle half-applied (the manifest flip is
atomic + last; the old files are still there).

### Incremental-DATA path — design only (not built this wave)

The versioned manifest handles **artifact updates** (a rebuilt .so / retrained
model / re-converted shard set). It does NOT handle **incremental data** — new
documents added to the corpus without a full re-shard. That is the eventual
`semantic_docid_ingest` LSM track (`docs/semantic_docid_ingest/`): a log-
structured merge forward-index append path where new docs land as new
forward records (new mmap sub-shards) merged into the served set, with the
bundle manifest listing the active LSM layer set. An incremental-data update
delta would then be the NEW LSM layer files (tens of MB, not a 26 GB re-shard)
+ a manifest flip — the same update contract, a new update class. This wave
does not build it; it is flagged here so the update path's known gap is
recorded, not papered.

## Caveats (recorded, not papered)

- **9p container mount caveat.** The measurements were taken on the development
  container whose `data/` is a 9p/drvfs mount. File SIZES are exact (a property
  of the files, not the mount); the *latency* of loading them is the 9p-cold
  regime WI-3/Q9/F6 measured — a real host (native ext4) loads faster. A laptop
  installer's first-run warmup is bounded by the *host's* disk, not 9p.
- **v3 .so is Linux x86-64-v3 / Haswell-class.** WI-4 (`doc 10 §7.7`) verified
  parity 1.0 + warm 0.96× on the served shards; v2 (SSE-only, pre-Haswell
  fallback) is warm 2.2× (slow, parity-safe) — the installer picks v3 unless the
  target CPU predates Haswell.
- **No docker, no Qdrant on the bundle path.** This manifest is explicitly the
  Qdrant-free, docker-free bundle (the served stack is SEISMIC since the
  2026-07-06 promotion). The Qdrant `on_disk` sparse path was an env-gated
  fallback, never a handout dep; it was removed 2026-10-12 (code kept by
  the owner).
- **Unmeasured cells are marked as such** — the subset-tier size is `*est.*`;
  the Windows/macOS portability is "no measured number"; the license gate is
  "not a technical measurement." No silent claims.
