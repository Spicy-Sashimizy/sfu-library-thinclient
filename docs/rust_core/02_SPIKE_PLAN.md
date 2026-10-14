# 02 — Spike plan: pre-registered steps, bars, fixtures, recovery, audits

**Status:** ACTIVE (pre-registered 2026-10-11; no step has run)

Reconciled 2026-10-11: Step 0–3 all UNBUILT. The only artifacts of this track so
far are the three docs in this folder, the restore tag, and the change gates
(`infrastructure/SCRIPT_HYGIENE_POLICY.md`). Each step lands as its own commit
through the preflight gate; each step's efficacy is recorded here with numbers,
script path, results path and date before the next step starts.

## 0. Golden fixtures — freeze the Python path first (UNBUILT)

Nothing is ported until the current path's outputs are frozen. One harness,
`scripts/experiments/eval_rust_core_golden.py` (`Lifecycle: harness`, `Doc:
docs/rust_core/02_SPIKE_PLAN.md`, to be written), records per stage for the
120 `natural` topics of `data/eval_results/dense_ablation_qrels_20260817.json`
and the 100 diverse queries used by O10:

| Stage | Frozen output |
|---|---|
| encode | SPLADE term ids + weights (fp32), BM25F query text |
| legs | BM25F top-50 `(id, score)`, SEISMIC per-shard top-k and merged top-50 |
| fuse | RRF top-50 `(id, score)` with tie order |
| filter + hydrate | post-filter survivors; hydrated `(id, title, year, type, doi, abstract_sha1)` |
| final | top-10 after rerank (reuses `eval_cpu_only_serve_path.py`'s `fused_dump` / `final_dump` method) |

Results: `data/eval_results/rust_core_golden_<YYYY-MM-DD>.json` (sha256 recorded
here when written). Edge cases added on purpose: empty query, one-token query,
query with every filter set, query whose BM25F text needs escaping, a deleted
doc in the livedocs set, a query with < 10 survivors. Golden fixtures are
regenerated only when the Python path changes on purpose, and the regeneration
commit says why.

## 1. Torch-free Python serve path (UNBUILT)

Export `models/sfu-academic-embed-v5` (serving-essential 128 MiB) and
`models/sfu-cross-encoder-v1` to **fp32** ONNX; serve both through onnxruntime
behind `SFU_RERANK_ORT=1` (default unset ⇒ torch path, byte-identical to today).

| Bar | Pass | Measured by |
|---|---|---|
| B1 parity | final top-10 byte-identical to the torch path on 120/120 natural + 100/100 diverse | the Step-0 harness, `--arm ort` versus golden |
| B2 latency | `_maybe_rerank` p50 on CPU ≤ 1.1× the torch-CPU arm (1,059 ms, 2026-09-27) | same harness, quiet host, 2 rotated rounds |
| B3 footprint | bundle without torch: wheels ≤ 0.5 GiB (versus 1.10 GiB with torch 2.6.0+cpu, `PORTABLE_LINUX_BUNDLE.md`) | `portable_linux/build_linux_runtime.sh` with the new pins |

If B1 fails for the CE at fp32 the way int8 did (0.968), the CE stays torch and
the handout ships without CE rerank, stated as such. Effort `*est.*`: 2–3 sessions.

## 2. The one function in Rust, two faces (UNBUILT)

`core_search(encoded_query, filters, k) -> Vec<Candidate>` inside the fork crate
(`spike/seismic_upstream/`, new module `source/core/`), covering Tier A of
`01_MODULE_TRIAGE.md`: SEISMIC fan-out + merge, tantivy BM25F leg, RRF k=60,
`meta.sqlite` post-filter, flat-sidecar hydrate, livedocs skip. Faces:

- **pyo3**: `seismic.core_search(...)` called from
  `ThinClientRetriever.search_rrf` when `SFU_RUST_CORE=1` (default unset ⇒
  today's Python path). Built on a fork branch into a side path; the installed
  `.so` is not touched (O10 pattern).
- **CLI**: `seismic-core search --index-root … --manifest … --query … [--year …]`
  printing the same candidate JSON. Same binary crate, `#[cfg(feature = "cli")]`.

| Bar | Pass | Measured by |
|---|---|---|
| C1 parity | fused top-50 AND hydrated survivors byte-identical to golden on 120/120 + 100/100 (ids, order, scores to 1e-6) | Step-0 harness, `--arm rust_core` |
| C2 latency | `search_rrf` p50 ≤ 1.0× the Python path, cold and warm, quiet host (the port must not be slower; it is allowed to be no faster) | same harness; cold = fresh process after `echo 3 > drop_caches` equivalent used in G8 |
| C3 memory | anonymous RSS after 120 queries ≤ the Python path's (1.42 GB CPU arm, 2026-09-27) | `/proc/self/status` VmRSS − RssFile, as in the CPU-only harness |
| C4 no regression | `symbol_inventory.py diff` shows 0 protected removals; `source/tests` 669/669; the gate OFF arm byte-identical to golden | preflight + harness |

Kill rule: if C1 is not 100 % after two fix iterations, or C2 > 1.2×, the
branch is kept as a record and the track CLOSES (KILLED) with the numbers.
Effort `*est.*`: 2–4 weeks part-time.

## 3. Cross-build and the handout proof (UNBUILT; needs hosts)

| Target | Toolchain | Proof |
|---|---|---|
| Windows x86-64 | `cargo-xwin` (or native MSVC on the owner's Windows host) | CLI serves a `rebuild_from_openalex.py` 50 k-work corpus with output byte-identical to the Linux CLI on the Step-0 fixture subset; cold/warm p50 recorded. Closes manifest §(d) row 1 for the CLI path |
| Android aarch64 | `cargo-ndk`, API ≥ 29, run under Termux or `adb shell` | same corpus, same fixture subset; byte-identical modulo float formatting (record any difference); p50 and RSS recorded. Needs a device |
| Linux x86-64-v3 | existing | reference |

The three models are exported once (Step 1) and loaded through `ort` on every
target; the x86 SIMD in the vectorium dotvbyte decoder has aarch64 branches
already (`spike/vectorium_fork/src/encoders/dotvbyte_fixedu8/swizzle.rs`) and
gets its own parity check on the device. Effort `*est.*`: 2–3 weeks plus
hardware.

## Decision after Step 2 (Reconciled 2026-10-11)

Tier B is opened only if C1–C4 pass. If the owner's goal is the compiled
handout and C1–C4 pass, Step 3 runs next and Python is kept for the server and
research. If C1–C4 fail, the handout path falls back to the Python bundles
(`PORTABLE_LINUX_BUNDLE.md`, `PORTABLE_SOCSCI_WINDOWS_BUNDLE.md`) and Android is
recorded as not feasible with this stack.

## Recovery and audit per step

- Before each step's commit: `preflight.py run --slug rust-core-step<N>`
  (restore tag `pre-rust-core-step<N>-<date>`, fast tests, inventory).
- Each step adds its environment gate to `ENV_GATES.md` and its measured row to this
  doc and to `THIN_CLIENT_SWAP.md` §"What runs here now" in the same commit.
- Audits run on Fable (owner instruction 2026-10-11): harness results are
  re-read from the results file, not from the agent's summary; the OFF arm is
  re-run after every ON-arm change.
- Rollback: unset the gate (instant), `git revert` the step commit, or
  `git checkout pre-rust-core-step<N>-<date>`.
