# scripts/portable_socsci/ — build the portable social-sciences Windows bundle

Reproducible pipeline for the `social_sciences`-only, dense-stripped, all-offline
thumb-drive bundle. Design of record + size budget + wargame:
`docs/infrastructure/PORTABLE_SOCSCI_WINDOWS_BUNDLE.md`.

The bundle is a **runtime artifact** — it stages OUTSIDE the repo on native disk
(default `/var/tmp/portable_socsci_bundle`, override with `BUNDLE=`), never in git.
These scripts are the repo-tracked recipe that produces it.

Data-layer phases (OS-neutral bytes — built + verifiable in this Linux container):

| step | script | what | ~size / time |
|---|---|---|---|
| 1 | `01_filter_meta.py` | `meta.sqlite` → `social_sciences%` rows only | 4.07 GiB / ~27 min (9p full scan) |
| 2 | `02_assemble_data.py` | copy recent section, unpack archive section, copy SPLADE encoder, write trimmed manifest | ~20 GiB / ~copy-bound |
| 3 | `03_seismic_full.py` | **v1 (chosen 2026-08-04):** copy the 8 full `*.e5.v2.mmap` shards verbatim + emit a bundle-local manifest with absolute `mmap_dir` paths. Bit-exact; social-only filtering is at hydration via the trimmed `meta.sqlite`. | ~42 GiB / copy-bound |
| 4 | `04_verify_serve.py` | point `ThinClientRetriever` at `$BUNDLE/thinclient_index` (with `SFU_SEISMIC_SHARD_MANIFEST=$BUNDLE/seismic/shards.e5.v2.json`) + serve a real `social_sciences` query end-to-end | — |

**Seismic path — v1 vs v2.** v1 (`03_seismic_full.py`) ships the whole 42 GiB
seismic set bit-exact — no new Rust, verifiable here, fits the 114 GB drive with
~45 GiB to spare (design doc §5). The **v2 subset-rebuild** (`03_subset_seismic.*`,
~7 GiB via a Rust `subset_mmap_dir` bin + re-cluster + overlap@10 parity gate) is a
tracked size/cleanliness optimization on top and is NOT required to fit. To repoint
the v1 manifest at the shards' location on the target host (e.g. the mounted drive),
rerun with `--manifest-only --seismic-root <dir>`.

Windows runtime layer (skeleton assembled here; the native binaries build + prove
**only on Windows**):

| step | script | what | status |
|---|---|---|---|
| 5a | `windows/` (`seismic_upstream_5a_win_cfg_gate.patch`) | `#[cfg(unix)]`-gate the seismic engine's `libc` madvise/mlock hooks so it cross-compiles for Windows (no-ops there); Linux serving byte-identical | ✅ DONE — `cargo check --lib` PASSES on Linux |
| 5b-prep | `06_windows_buildkit.py` | copy the Rust fork source into `$BUNDLE/build/` + `cargo vendor` every crates.io & git dep (incl. the force-pushed `fixed`) → **offline** Windows Rust build; stage `build_windows_runtime.ps1` + `serving_requirements_win.txt` | ✅ DONE (~225 MiB) |
| 5b | `build_windows_runtime.ps1` (Windows host) | `maturin build` `seismic.pyd` (offline, vendored) + fetch relocatable CPython + install CPU serving wheels into `python\` | authored; **runs/proves on Windows** (needs Rust) |
| 5d | `05_windows_stage.py` | copy `src/` + `web/` into the bundle, drop `START.bat` (CRLF) + `regen_seismic_manifest.py` at the root | ✅ DONE |

After 5a/5b-prep/5d the bundle is the complete OS-neutral skeleton **+ a turnkey,
offline Windows build kit**. The only remaining step is `build_windows_runtime.ps1`
on a Windows PC with Rust — it produces `python\` (relocatable CPython + CPU
wheels) and `seismic.pyd` (maturin build of the 5a-gated, dep-vendored fork), the
two Windows-native pieces. Then `START.bat` serves offline. See design §7–§8 and
`windows/README.md`.

Env: `BUNDLE` (dest root), `SRC_INDEX` (default `data/thinclient_index`),
`SRC_MODELS` (default `models`). Run via the venv: `.venv/bin/python3 scripts/portable_socsci/0N_*.py`.
