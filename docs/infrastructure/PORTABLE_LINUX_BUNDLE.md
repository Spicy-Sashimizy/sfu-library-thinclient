# Portable Linux runtime bundle — relocatable CPython + CPU wheels + seismic .so

**Status:** ACTIVE

**Created 2026-09-27. MEASURED 2026-09-27** (build, determinism, relocation,
import surface, one-query smoke). Closes the mechanism half of
`PORTABLE_STACK_MANIFEST.md` §(d) row 4 ("python runtime bundling") for a
generic Linux x86-64 handout. Parent: `PORTABLE_STACK_MANIFEST.md` (what a
bundle must contain); sibling: `PORTABLE_SOCSCI_WINDOWS_BUNDLE.md` (the same
pattern for Windows, unmeasured there).

Scripts: `scripts/portable_linux/` — `build_linux_runtime.sh` (entry point),
`pins.conf` (every pin), `serving_requirements_linux.in` (top-level wheel
pins) → `serving_requirements_linux.lock.txt` (63 wheels, each pinned by
version **and** sha256), `bundle_tool.py` (lock / snapshot / fix-scripts /
manifest), `bundle_check.py` (shipped in the bundle as `bin/bundle_check.py`:
`imports` and `smoke` self-checks). Results:
`data/eval_results/portable_linux_bundle_2026-09-27.json`.

## 1. What the bundle is

```
<out>/
  python/        python-build-standalone CPython 3.11.16 (tag 20260924,
                 install_only_stripped, sha256-pinned) + the CPU wheel set
  python/lib/python3.11/site-packages/sfu_bundle.pth
                 two RELATIVE lines: ../../../../ext  and  ../../../../app/src
  ext/seismic/   WI-4's portable x86-64-v3 seismic .so (sha256-pinned) + __init__.py
  app/src/       src/lib/** (*.py only, incl. lib/thinclient/) + sfu_library_mcp_http.py
                 + sfu_library_mcp_server.py
  bin/sfu-python isolated launcher: unsets PYTHONPATH/PYTHONHOME, PYTHONNOUSERSITE=1
  bin/bundle_check.py
  BUNDLE_MANIFEST.json   every file: path, sha256, bytes, category; + bundle_sha256
  BUILD_REPORT.json      wall-clock of this build (outside the manifest)
```

**The import-path recipe (replaces the venv's tilted-name dirs).** The dev
venv's `~~ismic` / `~-ismic` / `~yseismic` dirs are pip's half-uninstalled
leftovers from swapping `.so` variants in place. The bundle never installs a
seismic wheel: the `.so` sits in `ext/seismic/` and one `.pth` file in
site-packages appends `ext/` and `app/src/` to `sys.path` with **relative**
paths (CPython's `site` resolves `.pth` lines against the site-packages dir),
so the path is fixed by the layout, not by the build location. Nothing else in
the bundle provides a `seismic` module, so there is no precedence question.

**Wheel set (CPU only).** Mirrors the dev venv (§(a) of the manifest) with the
two GPU dists swapped: `torch 2.6.0+cu124` → **`torch 2.6.0+cpu`** (from
`download.pytorch.org/whl/cpu`), dist `onnxruntime-gpu 1.26.0` →
**`onnxruntime 1.26.0`**. torch stays because the full serve path needs it:
the embed-rerank stage (`lib/embedding.py`) and the torch cross-encoder
(`lib/reranker.py`) both import `sentence_transformers` + `torch`. Also pinned:
tantivy 0.26.0, numpy 2.4.3, zstandard 0.25.0, transformers 4.57.6, tokenizers
0.22.2, sentence-transformers 5.4.1, usearch 2.25.3, scipy 1.17.1,
scikit-learn 1.8.0, regex 2026.4.4, requests 2.32.5, starlette 0.52.1, uvicorn
0.40.0, mcp 1.26.0, pydantic 2.12.5; transitive deps resolved once and locked
(no nvidia-* / CUDA wheel in the lock). **Excluded: `pyzotero`** — its
dependency `bibtexparser<2` ships sdist-only, which the wheel-only policy
rejects; `lib/zotero.py` imports it lazily, so search is unaffected but the
Zotero MCP tools are unavailable in the bundle.

**What is NOT in the bundle, and how the serve path finds it.** No index data,
no model weights. The bundle's `lib/` resolves its repo-root defaults to
`app/`, where nothing lives, so these must be set:

| Env var | Points at | Note |
|---|---|---|
| `SFU_THINCLIENT_INDEX_ROOT` (or `ThinClientRetriever(index_root=…)`) | `data/thinclient_index/` | tantivy sections, `meta.sqlite`, `packed/` |
| `SFU_SEISMIC_SHARD_MANIFEST` | a shard manifest JSON | **required**: the default-manifest auto-pick only fires when the index root equals the repo's own `data/thinclient_index`. The served manifests record repo-root-relative `mmap_dir` paths, which the bundle would re-anchor at `app/`; pass a manifest with absolute paths (`bundle_check.py smoke --anchor <repo>` writes a temp absolute copy) |
| `SFU_SPLADE_MODEL_PATH` | a dir holding `model.onnx` **and** the bert-base-uncased tokenizer files | ⚠ the served `models/splade_onnx_fused/` has only `model.onnx` + `config.json`; in the repo the tokenizer is borrowed from code-relative `models/sfu-academic-embed-v{1,4-bge,4-mini}` (`lib/opensearch_retriever.py` `_TOKENIZER_FALLBACK_DIRS`), which the bundle's code cannot see — see smoke attempt 1 below. A handout must ship the tokenizer inside the SPLADE dir (`bundle_check.py smoke --splade-tokenizer` builds a symlinked composite) |
| `SFU_EMBEDDING_MODEL_PATH` | `models/sfu-academic-embed-v5/` | embed-rerank stage (not dense-only) |
| `SFU_CE_MODEL_PATH` | `models/sfu-cross-encoder-v1/` | else the reranker falls back to the HF-hub id `cross-encoder/ms-marco-MiniLM-L-6-v2` (network) |

## 2. Measured 2026-09-27 (this host: WSL2, glibc 2.36, x86-64 with AVX2)

**Size** (`BUNDLE_MANIFEST.json` content bytes; GiB = 1024³):

| Part | Files | Bytes | |
|---|--:|--:|--:|
| runtime (CPython tree as extracted) | 3,855 | 82,132,145 | 78.3 MiB |
| wheels (everything pip added) | 21,348 | 1,183,212,110 | 1.10 GiB |
| seismic .so (+ `__init__.py`) | 2 | 2,700,400 | 2.6 MiB |
| source (`app/src`) | 41 | 679,861 | 0.65 MiB |
| launcher (`bin/`, `.pth`) | 3 | 10,714 | 10 KiB |
| **total** | **25,249** | **1,268,735,230** | **1.18 GiB** |

On-disk block usage of a fresh, never-run build: **1,346,527,232 B (1.25 GiB)**
(`du -s --block-size=1`). torch alone is ~670 MiB of the wheels; next are scipy
83, transformers 57, onnxruntime 51 MiB. Download cache for one build: CPython
tarball 30.8 MB + wheelhouse 324.4 MB (63 wheels).

**Build wall-clock:** fully cold (empty cache: CPython + all wheels
downloaded) **35.9 s** (fetch+extract python 2.5, download wheels 15.9, install
11.4, assemble 1.5, manifest 4.6); warm cache, offline
(`SFU_BUNDLE_OFFLINE=1`) **13.7 s** and 14.3 s (final recipe).

**Determinism: PASS.** Two offline builds of the final recipe, into
`build_a` and a deeper `other/deeper/build_b`, produced the identical
`bundle_sha256 a3936833b4f9b45d981e0bb86fc5dc6737c3a3c8a46548eef7716e6408a4e820`
over 25,249 files; the previous revision (which differed only in
`bin/bundle_check.py`) was built three times — cold cache, offline, deeper
path — with one identical fingerprint (`a9ccdc73…`). `grep -rF <build path>`
finds the build location in no bundle file. Two sources of nondeterminism were found and fixed on the way (see
`CODE_INVARIANTS_SCRIPTS.md` §scripts/portable_linux): pip writing timestamped
`.pyc` into the bundle while it ran (→ `PYTHONDONTWRITEBYTECODE=1`), and pip
console scripts carrying the absolute build path in their shebang plus the
matching hash in `RECORD` (→ rewritten to the `/bin/sh` trampoline and `RECORD`
rows refreshed).

**Import check (outside the lock): PASS**, 9.6 s wall in place (first run,
bytecode cold), `bin/sfu-python bin/bundle_check.py imports` from cwd `/`:
`lib.thinclient.retriever` and `seismic` both resolve inside the bundle,
`seismic.MmapSeismicIndex` present; `torch 2.6.0+cpu`,
`torch.cuda.is_available()` **False**; `onnxruntime 1.26.0` providers
**`['AzureExecutionProvider', 'CPUExecutionProvider']`** — no CUDA/TensorRT
provider (the Azure EP is the stock CPU wheel's remote-endpoint stub, not a
device); no `sys.path` entry or loaded module outside the bundle (torch's
runtime jit stub in a fresh `mkdtemp()` is reported separately).

**ABI check: PASS.** The v3 `.so` is `cpython-311`; the bundled CPython is
3.11.16 and loads it. The `.so` needs glibc ≥ 2.34 (`GLIBC_2.34` symbols);
the highest wheel tag in the lock is `cryptography … manylinux_2_34` (pulled in
by `mcp` → `pyjwt[crypto]`), so **the bundle's host floor is glibc 2.34 +
x86-64-v3 (AVX2/FMA)**. Only verified on this host's glibc 2.36.

**Relocation: PASS.** The built dir was `mv`ed to
`/tmp/claude-1000/portable_linux/moved/some/other/bundle_relocated` and the
import check re-run from cwd `/var`: PASS, 4.4 s, every resolved path under
the new location. The smoke below also ran from the moved copy.

**Smoke (one `search_rrf`, under `flock /tmp/sfu_latency_measure.lock`):**
run from the relocated bundle, cwd `/var`, against `data/thinclient_index`
(9p) + the served E8 dv-v2 manifest (anchored to absolute paths in a temp
copy), query "social capital and civic participation", `top_k=10`,
`remote_abstracts=False`.

- **Attempt 1 (lock held 04:02:46–04:03:01Z): FAIL, and the check caught
  it.** 10 hits came back, but the log carried `SEISMIC SPLADE leg failed (No
  local bert-base-uncased tokenizer found for SPLADE …)` — the SPLADE leg fell
  back to BM25F only, silently as far as the hit list goes. Cause: the tokenizer
  lookup described in the env table above. This is a real handout-contract gap
  in the served model dir, not a bundle defect.
- **Attempt 2 (lock held 04:19:16–04:19:36Z): PASS** with
  `--splade-tokenizer models/sfu-academic-embed-v1`: 10 hits (8 with a local
  abstract), SEISMIC served from the bundle's own `ext/seismic/…so`, no
  WARNING records, `torch.cuda.is_available()` False, nothing loaded from
  outside the bundle. **First `search_rrf` wall-clock: 18.8 s** in a fresh
  process (lazy load of 8 mmap shards + ONNX encoder + tantivy + `meta.sqlite`
  off 9p included). One number, not a latency benchmark.

## 3. What is still unmeasured

- **A second machine.** Relocation was a move on the same host; no other
  distro, glibc, or CPU has run the bundle. The glibc 2.34 floor is read off
  the ELF symbols and wheel tags, not tested on a 2.34 host.
- **The full HTTP serve** (`app/src/sfu_library_mcp_http.py`) was not
  started from the bundle; only the retriever path was exercised. The web UI
  (`web/`) is not in the bundle.
- **Rerank on CPU inside the bundle** (embed-rerank + torch cross-encoder):
  `search_rrf` does not rerank, so it was not exercised inside the bundle.
  Row 6's binding test (full serve path, CUDA absent, BOTH encoders on CPU)
  was run separately on 2026-09-27 with the same wheel pins (`torch
  2.6.0+cpu`, `onnxruntime 1.26.0`) in a non-relocatable venv: final top-10
  byte-identical to the GPU arm on 120/120 topics, total p50 +823 ms
  (`PORTABLE_STACK_MANIFEST.md` §(d) row 6,
  `data/eval_results/cpu_only_serve_path_2026-09-27.json`). The rerank path
  inside the relocatable bundle itself is still unmeasured.
- **CPU latency** of the bundle is not benchmarked here (one smoke number
  only). The CPU serve-path latency on this host (not from the bundle) is in
  `PORTABLE_STACK_MANIFEST.md` §(d) row 6 (2026-09-27).
- **ONNX cross-encoder** (`SFU_CE_ONNX=1`) looks for
  `models/sfu-cross-encoder-v1-onnx-int8` relative to the code, i.e. inside
  `app/`; there is no env override, so it cannot be enabled in the bundle
  without a code change.
- **Shipping the SPLADE tokenizer in the model dir.** The smoke proves a
  composite dir works; no handout-ready SPLADE dir (ONNX + tokenizer) has
  been built, and the served dir is left as is.
- **Lower-ISA fallback** (the v2 `.so`, doc 10 §7.7) is not wired in; the
  recipe ships v3 only.
