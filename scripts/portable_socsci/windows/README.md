# Windows runtime layer — portable social-sciences bundle

> **STATUS: AUTHORED HERE, PROVEN ON WINDOWS.** This Linux container can
> *cross-build and assemble* the Windows runtime, but it **cannot run or verify**
> it. Everything here is "IMPLEMENTED, EFFICACY UNMEASURED" (repo rule) until a
> real Windows x86-64 host loads `seismic.pyd`, mmaps the shards, and serves a
> query. The **data layer** (phases 1–4) is fully proven on Linux — see the
> parent `README.md` and design doc §6.

The data bytes are OS-neutral (identical on Windows/Linux); only three things are
Windows-specific: the compiled `seismic.pyd`, the CPU-only Python wheels, and the
relocatable interpreter + launcher. This dir holds the launcher templates; the
build/assembly steps below produce the rest.

## Files in this dir (repo-tracked templates)

| file | role |
|---|---|
| `START.bat` | the double-click launcher; ships at the bundle root. Repoints the seismic manifest at the drive's current mount, sets the bundle serving env, launches the server, waits for `/health`, opens `http://127.0.0.1:8080/app`. |
| `regen_seismic_manifest.py` | stdlib-only; rewrites `seismic/shards.e5.v2.json` `mmap_dir` paths to the current bundle root (drive letters differ per host). `START.bat` runs it first. |

## Build steps (run on this Linux host; each is a cross-build / download)

1. **cfg-gate the POSIX perf hooks** (design §7). The engine maps via
   `memmap2::Mmap` (cross-platform); only the `libc` `madvise`/`posix_fadvise`/
   `mlock` calls are POSIX. Gate them `#[cfg(unix)]` → Windows no-ops (accept
   slower cold faults; the F6 prefault won't apply). Files:
   `spike/seismic_upstream/src/mmap_io.rs`, `pylib/mmap_index.rs`, `bin/c1a_*`,
   `bin/c2_*`. **Correctness-neutral** — parity must be unchanged on Linux after.

2. **cross-build `seismic.pyd`** for `x86_64-pc-windows-msvc` via **cargo-xwin**
   (`cargo xwin build --release --target x86_64-pc-windows-msvc`). Portable ISA
   only — `RUSTFLAGS="-C target-cpu=x86-64-v3"`, **never** `target-cpu=native`
   (spike/CLAUDE.md rule). Output → `python\Lib\site-packages\seismic.pyd`
   (or wherever it lands on the import path — reproduce the manifest §delta #4
   import-path dance).

3. **CPU-only Windows wheels** — `pip download --platform win_amd64
   --python-version 3.13 --only-binary=:all: --dest wheels/` for: `torch` (CPU,
   **not** cu124), `onnxruntime` (CPU, **not** `-gpu`), `tantivy`, `transformers`,
   `tokenizers`, `zstandard`, `numpy`, `scipy`. `sentence-transformers` is **not**
   needed (dense stripped, D1). Install into the relocatable python.

4. **relocatable Python** — python-build-standalone Windows x86-64, unpacked to
   `<bundle>\python\`, with the wheels + `seismic.pyd` on its import path.

5. **assemble** (phase 5, TODO `05_windows_stage.py`) — copy `src/` and `web/`
   into the bundle, drop `START.bat` + `regen_seismic_manifest.py` at the root,
   place `python\`. Result is a self-contained drive; `START.bat` is the entry.

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
strong evidence the *contract* is right; only the compiled `seismic.pyd` load +
mmap behavior remains Windows-unproven.
