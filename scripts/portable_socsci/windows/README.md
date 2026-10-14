# Windows runtime layer — portable social-sciences bundle

> **STATUS (reconciled 2026-09-29): AUTHORED HERE, COMPILED ON-DRIVE BY OWNER
> ATTESTATION, SERVING ON WINDOWS UNMEASURED.** This Linux container assembles
> the OS-neutral skeleton and a turnkey offline build kit, but it **cannot run or
> verify** the Windows-native pieces. `build_windows_runtime.ps1` was run on the
> drive by the owner (Gordon, attested 2026-08-08; the drive has since left his
> possession, so nothing here can re-check it). The load-bearing proof — does
> `seismic.pyd` load, mmap the shards, and serve a query bit-exact on a real
> Windows x86-64 host — has **never been measured** (design doc §7 "Testability
> boundary", `PORTABLE_STACK_MANIFEST.md` §(d) row 1). The **data layer**
> (phases 1–4) is fully proven on Linux — see the parent `README.md` and design
> doc §6.

The data bytes are OS-neutral (identical on Windows/Linux); only three things are
Windows-specific: the compiled `seismic.pyd`, the CPU-only Python wheels, and the
relocatable interpreter + launcher. This directory holds the launcher/installer
templates and the on-Windows build recipe; the numbered scripts one level up
stage everything else.

## Files in this dir (repo-tracked templates)

| file | role |
|---|---|
| `START.bat` | the double-click launcher; ships at the bundle root. Repoints the seismic manifest at the drive's current mount, sets the bundle serving environment, launches the server, waits for `/health`, opens `http://127.0.0.1:8080/app`. |
| `regen_seismic_manifest.py` | stdlib-only; rewrites `seismic/shards.e5.v2.json` `mmap_dir` paths to the current bundle root (drive letters differ per host). `START.bat` runs it first. |
| `build_windows_runtime.ps1` | the ONE step that runs on Windows (needs a Rust toolchain + internet): fetches a python-build-standalone `install_only` CPython into `<root>\python\` (default `3.11.9`/`20240814`, override `PY_VER`/`PY_TAG`/`PY_STANDALONE_URL`), installs pip + maturin, `maturin build --release --offline` over the vendored fork with `RUSTFLAGS=-C target-cpu=x86-64-v3`, installs the built `seismic` wheel + `serving_requirements_win.txt`, then `python -c "import seismic, onnxruntime, tantivy, numpy, zstandard, starlette, uvicorn"`. Commit `f77435c7` (2026-08-04). |
| `serving_requirements_win.txt` | the CPU-only Windows serve set: onnxruntime, tantivy, numpy, zstandard, transformers, tokenizers, uvicorn, starlette, requests, mcp. **No torch, no sentence-transformers** (dense stripped, D1). |
| `SETUP.bat` → `install_wizard.ps1`, `space_assistant.ps1`, `MOVE-BACK.bat` | the setup wizard (modes: Install-to-PC / Hybrid / Run-from-USB, AVX2 preflight, Space Assistant offload + verified restore). Authored 2026-08-05 (`c1d0bd92`); Windows-side efficacy UNMEASURED (design §8). |

## What exists vs what is proven (code is the source of truth)

| step | where | state |
|---|---|---|
| 5a cfg-gate the POSIX perf hooks (`madvise`/`posix_fadvise`/`mlock` → `#[cfg(unix)]`; `memmap2::Mmap` is already cross-platform) | `spike/seismic_upstream_5a_win_cfg_gate.patch`, applied to the fork | DONE 2026-08-04 (`2f270370`); `cargo check --lib` PASSES on Linux, Linux parity unchanged |
| 5b-prep offline build kit: fork source + `cargo vendor` of every crates.io/git dep (incl. the force-pushed `fixed`) into `$BUNDLE/build/`, plus the `.ps1` and the wheel list | `../06_windows_buildkit.py` | DONE 2026-08-04 (`f77435c7`), ~225 MiB |
| 5b native build on Windows (`seismic.pyd` + `python\`) | `build_windows_runtime.ps1` | **owner-attested run 2026-08-08**; not git-tracked, not container-verifiable |
| 5d OS-neutral skeleton: copy `source/` (minus tests/caches) + `web/` (minus `node_modules`), drop `START.bat` (CRLF) + `regen_seismic_manifest.py` at the root; writes `_windows_stage_report.json` listing `python/` and `seismic.pyd` as `still_needed_on_windows` | `../05_windows_stage.py` | DONE 2026-08-04 (`a9c4f02b`) |
| installer + search-queue layer staged (10 files, CRLF) | `../07_windows_installer.py` | DONE 2026-08-05 (`c2bce3f1`) |
| USB sync, sha256-verified | session record in the design doc | DONE 2026-08-06 |
| **Windows serve proof** (`seismic.pyd` loads, mmaps, serves bit-exact; wizard/modes/AVX2/MOVE-BACK/search smoke) | needs a real Windows x86-64 host | **UNMEASURED** — the open item behind `PORTABLE_STACK_MANIFEST.md` §(d) row 1 |

Superseded (never built, kept for the record): the original plan's
cargo-xwin **cross**-build from Linux and a torch-bearing wheel set. The kit
builds natively on Windows instead (pyo3 cross-builds cannot be
runtime-validated on Linux anyway), and the serve set carries no torch.

## The serving env `START.bat` sets (all bundle-relative)

```
SFU_SEARCH_BACKEND=thinclient      SFU_SPLADE_BACKEND=seismic
SFU_THINCLIENT_INDEX_ROOT=<root>\thinclient_index
SFU_SEISMIC_SHARD_MANIFEST=<root>\seismic\shards.e5.v2.json
SFU_SPLADE_MODEL_PATH=<root>\models\splade_onnx_fused
SFU_SEISMIC_LOAD_MODE=mmap          SFU_SEISMIC_STAGE_DIR=   (empty; data local)
SFU_DENSE_WARMCACHE=0               MCP_HTTP_HOST=127.0.0.1  MCP_HTTP_PORT=8080
```

These mirror the Linux verify (`04_verify_serve.py`) exactly, so a Linux PASS is
strong evidence the *contract* is right; the compiled `seismic.pyd` load + mmap +
serve behavior on Windows remains UNMEASURED (2026-09-29).
