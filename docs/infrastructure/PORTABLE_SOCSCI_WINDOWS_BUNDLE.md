# Portable social-sciences Windows bundle — design + size budget

**Status:** ACTIVE

**Created 2026-08-04. Last status update 2026-08-08. STATUS: SHIPPED
(owner-attested)** — data layer + installer + search-queue on the USB
(sha256-verified on-drive 2026-08-06); Windows-native compile (`seismic.pyd`
+ `python\`) OWNER-ATTESTED COMPLETE (Gordon, 2026-08-08; the drive has left
his possession, so the attestation is the standing record). On-Windows QA
(wizard/modes/AVX2/MOVE-BACK/search smoke) remains **UNMEASURED**. Specification for
an auto-launching, run-from-thumb-drive Windows build cut to one discipline
so it fits a consumer USB drive; the plan of record for `PORTABLE_SOCSCI_*`.

**Build progress (2026-08-04, staged at `/var/tmp/portable_socsci_bundle`):**
- Phase 1 (`meta.sqlite` social filter) — ✅ **DONE**: 4.07 GiB, 24,176,093 docs
  (0 `docs_other`), ~27 min. Report `_meta_filter_report.json`.
- Phase 2 (data layer: tantivy + abstracts + encoder + manifest) — ✅ **DONE**:
  recent 18.64 + archive 0.66 + encoder 0.5 = **23.87 GiB**. `_assemble_report.json`.
- Phase 3 (seismic) — ✅ **DONE (v1 full-seismic, owner-chosen 2026-08-04)**: the
  8 whole-corpus `*.e5.v2.mmap` shards copied bit-exact (**41.36 GiB**, 372 s) +
  bundle-local manifest with absolute `mmap_dir` paths
  (`scripts/portable_socsci/03_seismic_full.py`). See §5.
- Phase 4 (Linux serve verify) — ✅ **PASS 2026-08-04**
  (`04_verify_serve.py`; results `data/eval_results/portable_socsci_verify.json`).
  2 sections load in 319 ms; 4 social_sciences queries each return 10 hydrated
  hits with **abstracts from local sidecars only** (`remote_abstracts=False`);
  first query 112 s cold (mmap faults over 42 GiB on the overlay fs), warm p50
  ~1.2 s. Proves the OS-neutral data layer + serving contract end-to-end.
- **v1 bundle total: measured 66 GiB** on-disk (23.87 data + 41.36 seismic +
  encoder) — fits the 114 GB / ~114 GiB-usable drive with ~48 GiB headroom.
- Windows runtime — launcher layer authored (`scripts/portable_socsci/windows/`:
  `START.bat`, `regen_seismic_manifest.py`); skeleton + offline build kit staged
  here (§7, §10 step 5); native compile owner-attested 2026-08-08; **serving on
  Windows UNMEASURED** (reconciled 2026-09-29).

**Installer + search-queue + USB sync (2026-08-05 / 2026-08-06):**
- Setup wizard + Space Assistant + START.bat configuration wiring — ✅ **AUTHORED
  2026-08-05** (commit `c1d0bd9`; `windows/{install_wizard.ps1, space_assistant.ps1,
  SETUP.bat, MOVE-BACK.bat}`). Windows-side efficacy UNMEASURED — see §8.
- Search queue (sequential mode) web UI + `SFU_SEQUENTIAL_MODE` gate — ✅ **BUILT
  2026-08-05** (commit `49b44f7`; `web/source/search.jsx`, `/health` `sequential`,
  Settings→Interface toggle; jsdom 24/24). Documented in `../THIN_CLIENT_SWAP.md`.
- Installer + search-queue staged into the bundle — ✅ **DONE 2026-08-05**
  (commit `c2bce3f`; `07_windows_installer.py`, 10 files with CRLF into
  `/var/tmp/portable_socsci_bundle`).
- **USB incremental sync — ✅ CONFIRMED COMPLETE 2026-08-06** (session
  `5224bc56`): the 66 GiB base bundle plus all 10 installer/search-queue files
  were tar-streamed to the drive and byte-verified — **all ten `sha256sum -c`
  lines read `OK`**, USB copies bit-identical to the container-staged source.
  This is the "updated" milestone: the drive carries every non-native ingredient.
- **Windows-native compile (`seismic.pyd` + relocatable `python\`) —
  ✅ OWNER-ATTESTED COMPILED (Gordon, 2026-08-08).** The Aug-6 session handed off
  a paste-ready QA/build prompt for a *Windows-side* Claude Code session to run
  `build_windows_runtime.ps1` on the drive. **Gordon confirms the USB was
  compiled** (the `.ps1` ran → `seismic.pyd` + `python\` on the drive). This is an
  **owner attestation, not a container-verified fact**: both artifacts are built
  on the Windows host, written to the USB, and are not git-tracked, so neither
  this repository's git history nor this container's transcripts record them. **The
  drive has left Gordon's possession (2026-08-08), so the on-drive ground-truth
  check (`Test-Path <drive>\python\python.exe` / `find … -name 'seismic*.pyd'`) is
  no longer runnable** — the attestation is the standing record.
- **On-Windows QA (wizard render, 3 modes, AVX2 gate, verified MOVE-BACK
  round-trip, serial-queue search smoke) — ❌ UNMEASURED** (see §8).

Parent docs (read for context): `PORTABLE_STACK_MANIFEST.md` (what a bundle
contains + the installer delta list), `../THIN_CLIENT_SWAP.md` (serving path),
`../STORAGE_BUDGET_150M.md` (whole-DB budget), `../seismic_150m_testbed/13_E5_FORWARD_REORDER_DESIGN.md`
(the `reorder_mmap_dir` machinery the seismic subset is built on).

## 0. The ask, and the locked decisions

An operator wants the current stack — **minus the unfinished dense ANN leg** —
on a **~114 GB thumb drive**, auto-deploying with a browser UI that launches on
its own, targeting **Windows**, for an **anthropology / political-science /
history** user. Decisions locked with the owner 2026-08-04:

| # | Decision | Value |
|---|---|---|
| D1 | Dense leg | **STRIPPED** (unfinished; usearch index + v5 encoder both dropped) |
| D2 | Kept corpus | **`social_sciences` section only**, both eras (recent + archive) |
| D3 | Abstracts | **fully offline** for the kept corpus (no query-time API dependency) |
| D4 | Seismic | **subset-rebuilt** to the kept docs (not shipped whole-corpus) |
| D5 | Target OS | **native Windows x86-64** (not Linux, not WSL2) |
| D6 | Delivery | **installer** offering install-to-disk OR run-from-thumb-drive (portable) |
| D7 | Launch | **double-click launcher** + browser auto-open (true USB autorun is dead on modern Windows — see §7) |

## 1. Why `social_sciences` is the right cut

The section classifier (`source/lib/thinclient/sections.py`) is priority-ordered
disjoint vocabulary. The `social_sciences` vocabulary **explicitly contains**
(sections.py:18-20):

> political politics policy sociology economic economics social society …
> **anthropology history philosophy geography** business management finance

So anthropology, history, philosophy, political science, geography, sociology,
and economics **all land in `social_sciences`** — this one section *is* the
target user's corpus. Broader humanities (literature, arts, religion, languages)
fall through to the `other` catch-all; the wargame in §4 prices adding them.

Measured section doc counts (from tantivy `meta.json`, 2026-08-04):

| Section | recent | archive | total | share |
|---|--:|--:|--:|--:|
| **social_sciences** | 23,398,073 | 778,020 | **24,176,093** | **16.1%** |
| other | 54,912,186 | 2,907,826 | 57,820,012 | 38.4% |
| med_bio | 23,279,830 | 149,551 | 23,429,381 | 15.6% |
| phys_eng | 22,061,449 | 164,376 | 22,225,825 | 14.8% |
| cs_math | 22,279,259 | 482,528 | 22,761,787 | 15.1% |
| **total** | | | **150,413,098** | |

## 2. Measured size budget (dense stripped)

All sizes measured on-disk 2026-08-04 (`du`, GiB = 1024³). "Whole corpus" =
150M; "social subset" = the D2 cut. Subset sizes are **`*est.*`** (linear-in-docs
projection at 16.1%) until the subset run produces the real number.

| Component | Whole-corpus (measured) | social subset | Section-sliceable in-container? |
|---|--:|--:|---|
| SEISMIC SPLADE shards (served `e5.v2`, 8×5.2) | 42.0 | **~6.8** `*est.*` | No — needs the §5 subset rebuild (hash-sharded whole corpus) |
| tantivy BM25F | 29.0 | **~6.2** | Yes — copy the two social section directories |
| `meta.sqlite` (v2, int-PK + overflow) | 23.0 | **~3.7** `*est.*` | Yes — `SELECT … WHERE section LIKE 'social_sciences%'` |
| offline abstracts | (hot 13 + packed 42) | **~13.5** | Yes — recent hot sidecar exists; unpack archive |
| SPLADE ONNX encoder | 0.5 | 0.5 | n/a (shared) |
| CPU runtime (python + wheels) | — | ~3 | n/a |
| dense leg + v5 encoder | 3.5 | **0 (stripped)** | D1 |
| **bundle total** | ~150 (all-offline) | **~34** `*est.*` | fits 114 GB with ~72 GiB headroom |

**The headline the owner needed:** stripping dense saves only ~3.5 GiB — nowhere
near enough (full-corpus all-offline is ~150 GiB). What makes it fit is **D2 +
D4**: cut to one section and subset-rebuild seismic. At ~34 GiB it clears a
128 GB / ~114 GiB-usable drive by a wide margin, and would even fit a 64 GB drive.

## 3. Section decision — where each artifact's size comes from

Two artifacts are **whole-corpus and not section-sliceable at the file level**:
`meta.sqlite` (one row per doc, but carries a `section` column → *rebuildable*
by filter, in-container) and the SEISMIC shards (hash-sharded; each shard mixes
all sections → needs the §5 rebuild). Everything else (tantivy, abstracts) is
already per-section on disk and is a copy/unpack.

## 4. WARGAME — what "lit / arts / humanities cold" would cost

Three ways to treat the `other` catch-all (where literature/arts/religion live),
all with the D4 seismic subset, dense stripped, GiB, `*est.*` on subset cells:

| Option | seismic | tantivy | meta | abstracts | +runtime | **total** | Fits 114 GB? |
|---|--:|--:|--:|--:|--:|--:|:--:|
| **A. social only** (D2, chosen) | ~6.8 | 6.2 | 3.7 | 13.5 (social hot) | 3.5 | **~34** | ✅ huge margin |
| **B. social + `other` COLD** | ~22.9 | 16.1 | 12.5 | 13.5 (social hot; `other`→API) | 3.5 | **~69** | ✅ ~45 GiB margin |
| **C. social + `other` OFFLINE** | ~22.9 | 16.1 | 12.5 | ~32.7 (social hot + `other` packed) | 3.5 | **~88** | ✅ tight-ish |

**Reading option B (the wargame answer).** "Cold" means `other` stays **fully
searchable** — its docs are in the seismic subset and tantivy, its titles/DOIs/
filters are in `meta` — but its **abstracts are NOT shipped**; they're fetched
from the OpenAlex API at rerank time (the existing cold-section policy).
Consequences:

- **The search-layer cost is the same as option C, not option A.** To *search*
  `other` you must include its 57.8M docs in the seismic subset (→ ~23 GiB, not
  ~7), its tantivy (→ +10 GiB), and its meta rows (→ +9 GiB). Cold only saves the
  **abstract-shipping** cost (~19 GiB packed), landing ~69 GiB. So "cold" buys
  you the humanities *findability* for +~35 GiB over social-only, and *offline
  reranking* for them costs a further ~19 GiB on top of that.
- **Offline, `other` results degrade.** With no local abstract and no internet,
  the cross-encoder would have to rerank `other` hits on title alone — which the
  architecture explicitly forbids ("Never title-only rerank"). So option B is
  **"social science works fully offline; humanities beyond social science need
  internet to rank well."** On a plane, `other` hits still *appear* (BM25F+SPLADE
  rank them) but their rerank/abstract panel is empty until online.
- **The 57.8M `other` bucket is noisy.** It's the catch-all — not just
  humanities, but everything unmatched. Adding it raises recall for lit/arts at
  the cost of retrieval precision and +35 GiB.

**Recommendation:** ship **option A** now (it covers anthropology/history/
philosophy/poli-sci directly and is tiny). Option B is a clean, self-contained
add-on later — same subset tool, just a larger kept-id set (social ∪ other) and
`other` left cold — if the user finds humanities gaps. Nothing about A blocks B.

## 5. SEISMIC — compression vs subset

**Compression is a bad lever (measured 2026-08-04).** The shards are already
dotvbyte-quantized (u8 + varint). Residual zstd on shard0 samples:

| file | share of shard | zstd -9 ratio |
|---|--:|--:|
| `forward_data.bin` | ~71% | **1.24×** |
| `posting_lists.bin` | ~21% | 1.29× |
| `document_mapping_strings.bin` | ~4% | 2.28× |
| `document_mapping_offsets.bin` | ~3% | 7.2× |

Whole-shard ≈ **1.3×** (42 → ~32 GiB). And the engine **mmaps these files for
random-offset reads**, so a whole-file-zstd blob can't be served — you'd ship
compressed and expand-on-first-boot, needing the full 42 GiB of scratch on the
target anyway. Not worth it.

**Subset is the lever (6× on this corpus) — but it is a REBUILD, not a filter
(corrected 2026-08-04 after reading `mmap_io.rs:2225`).** `reorder_mmap_dir`
rewrites a shard under a *bijection*: it preserves every posting list's block
structure (the same docs stay in the same blocks) and only remaps forward
offsets + permutes the doc-mapping slab. A **subset drops docs**, which changes
*which* docs are in each posting list — so the per-posting **Elias-Fano doc-id
lists** (`ef_high/low_bits`) and the **block-max pruning summaries**
(`summaries/minimums/quants`) must be **re-derived**. Those are build-time
artifacts (clustering + block-max), so a subset **cannot** be a word-filter over
the reorder path; it must **rebuild the inverted structure** over the kept docs'
forward vectors.

**Deliverable (revised):** a Rust bin that (1) mmaps the full shard, (2) decodes
the kept docs' dotvbyte forward records back to sparse vectors, (3) builds a
fresh `SeismicIndex` over just those (reusing `build_inverted_index` /
`write_mmap_index`), (4) dotvbyte-converts (+ optional E5 reorder) to the served
layout. Because SEISMIC re-clusters at build time, the subset is **NOT
bit-identical** to the full index's results for those docs — the **gate is
quality-parity (overlap@10 ≥ the G8d 0.985–0.991 bar) against the full-shard
top-k on kept docs**, not bit-exact. Per-shard clustering over ~3M docs is the
real cost, ×8 shards.

**v1 — full-seismic (bit-exact, no new engine work) — CHOSEN 2026-08-04 (owner).**
Ship the whole 42 GiB seismic and post-filter to kept sections via the trimmed
`meta.sqlite` (candidates outside social_sciences self-drop at hydration). This
is bit-exact "the stack as it is currently," ships without the rebuild bin, and
**already fits the 114 GB drive with ~45 GiB to spare** — at the cost of ~35 GiB
of inert non-social vectors and some SPLADE-leg over-fetch tuning (fewer kept
candidates per k). Implemented in `scripts/portable_socsci/03_seismic_full.py`:
copies the 8 `*.e5.v2.mmap` shards verbatim into `$BUNDLE/seismic/` and emits
`shards.e5.v2.json` with absolute `mmap_dir` paths (repointed at the drive's
mount by `windows/regen_seismic_manifest.py` / `--manifest-only --seismic-root`
on the target host). **v1 bundle total ≈ 66 GiB** (23.87 data + ~42 seismic).
The subset rebuild above (v2) stays the size/cleanliness optimization on top —
nothing in v1 blocks it (same kept-id set).

## 6. Data layer (OS-neutral — build + verify here)

These bytes are identical on Windows and Linux, so they're built and **runtime-
verified in this Linux container** (the only place the stack can execute):

1. **`meta.sqlite` filter** → `docs`/`docs_other` rows `WHERE section LIKE
   'social_sciences%'` into a new db + `VACUUM`. Long (full-scan on 9p, no
   section index). Background job.
2. **tantivy** → copy `sections/social_sciences__{recent,archive}/tantivy`.
3. **abstracts** → copy `social_sciences__recent/abstracts.sqlite` (hot, 13 GiB);
   unpack `packed/social_sciences__archive.tar.zst` into a hot archive sidecar so
   both eras serve offline. Optionally apply the doc-18 SQLite-free/flat-locator
   levers later (−~1.9 GiB; not required to fit).
4. **seismic subset** (§5) → 8 social-only shards + per-shard parity PASS.
5. **manifest + strip dense** → OS-neutral bundle layout, no `dense/`, no v5 model.
6. **verify** → point `ThinClientRetriever` at the bundle, prove a real
   `social_sciences` query serves end-to-end (BM25F + SPLADE + RRF + rerank on
   local abstracts).

## 7. Windows native runtime (build here, PROVE on Windows)

**Portability is better than the manifest's conservative note implied.** The
engine maps via **`memmap2::Mmap`** (`src/mmap_io.rs:27`), which is cross-platform
(`MapViewOfFile` on Windows). The only POSIX-specific code is the `libc`
`madvise`/`posix_fadvise`/`mlock` **perf hooks** (in `mmap_io.rs`,
`pylib/mmap_index.rs`, `bin/c1a_*`, `bin/c2_*`) — correctness-neutral, so they
`#[cfg(unix)]`-gate to Windows no-ops (accept slower cold faults; the F6 prefault
optimization simply won't apply).

Plan:
1. **cfg-gate** the POSIX hooks; keep `MmapSeismicIndex::new` + `search` intact.
2. **cross-build** `seismic.pyd` for `x86_64-pc-windows-msvc` via **cargo-xwin**
   (portable target `x86-64-v3`, never `target-cpu=native` — spike/CLAUDE.md rule).
3. **CPU-only Windows wheels** — `torch` CPU (not cu124), `onnxruntime` (CPU, not
   `-gpu`), `tantivy`, `transformers`, `tokenizers`, `sentence-transformers` is
   NOT needed (dense stripped), `zstandard`, `numpy`, `scipy` — fetched via
   `pip download --platform win_amd64 --only-binary=:all:`.
4. **relocatable Python** — python-build-standalone Windows x86-64, with
   `seismic.pyd` placed on its import path (reproduce the deterministic import-
   path dance the manifest §delta #4 flags).
   *(Plan steps 2–3 as written were superseded on 2026-08-04: the kit builds
   `seismic.pyd` natively on Windows via `maturin` over vendored deps — no
   cross-build — and the serve set `serving_requirements_win.txt` carries no
   torch; see the phase 5b status below and `windows/README.md`.)*
5. **`START.bat`** — sets the bundle environment (`SFU_SEARCH_BACKEND=thinclient`,
   `SFU_SPLADE_BACKEND=seismic`, `SFU_SEISMIC_STAGE_DIR` off / data already local,
   `SFU_DENSE_*` disabled), launches `serve_http.sh`'s Windows twin
   (`serve_http.bat`), waits for `/health` `warm`, then `start http://127.0.0.1:8080/app`.

**Phase 5a status (2026-08-04): cfg-gate DONE, applied to the fork working tree**
(`spike/seismic_upstream/src/mmap_io.rs`; captured as the focused patch
`spike/seismic_upstream_5a_win_cfg_gate.patch`). All five `libc` call sites
(`madvise` WILLNEED/SEQUENTIAL/DONTNEED/RANDOM, `mlock`) now funnel through
`os_madvise`/`os_mlock` shims — real syscalls under `#[cfg(unix)]`, no-ops on
Windows. Linux serving is byte-identical (the shim expands to the prior calls).
NOTE (2026-08-04): the umbrella `spike/seismic_upstream_fork.patch` was **stale**
versus the fork's committed F3–F6 history + unrelated in-tree WIP, so 5a was tracked
as its own incremental patch rather than by regenerating the drifted umbrella.
**CORRECTED 2026-08-31:** the umbrella was regenerated (`git diff 7782a13 HEAD`
from the fork root, fork HEAD `2c4d863`) and now carries the full fork delta
including the 5a cfg-gate, F3–F6, E8 v2, M8 and the F5 scope fix; it applies
cleanly to upstream `7782a13` (verified with `git apply --check` in a detached
worktree). The focused patches stay alongside it for reviewability.
One 5a-relevant change: `os_madvise` now **returns** the syscall status (`i32`)
instead of `()`; the `#[cfg(not(unix))]` arm returns `-1` so a Windows build
accounts 0 bytes released rather than reporting a false "released" number. The
shim shape and the Linux behaviour are otherwise unchanged.

**Phase 5b status (2026-08-04): Linux build UNBLOCKED + 5a VALIDATED; native
Windows build kit prepped.** The earlier blocker was a stale local `Cargo.lock`
pinning `fixed @ fast_to_f32_hack` at a force-pushed-away rev (`02d24b0`);
`Cargo.lock` is gitignored, so `cargo update -p fixed` re-resolves the branch to
its live HEAD (`e7d7248`). With that, **`cargo check --lib` PASSES on Linux
(exit 0, 51 s, 0 errors)** — proving the 5a cfg-gate compiles cleanly *and* the
dep bump is API-compatible with the vectorium/toolkit forks. Only the
Windows-native step remains (produce `seismic.pyd` + the relocatable Python),
which cross-compilation can't runtime-validate on Linux anyway. **The kit builds
it natively on Windows**: `06_windows_buildkit.py` vendors the Rust deps
(offline/reproducible) and ships the fork source into `$BUNDLE/build/`, and
`build_windows_runtime.ps1` on the target runs `maturin build` (Rust + CPython)
+ installs the CPU serving wheels into the drive's Python — self-validating there
(`python -c "import seismic"`).

**Testability boundary (honest):** this Linux container can (in principle)
produce a Windows build that **compiles and links**; it **cannot run or verify**
it, and right now cannot even build it (5b walls above). End-to-end proof (does
`seismic.pyd` load, mmap, and serve bit-exact on Windows?) happens on a real
Windows host. Until then the Windows runtime is "IMPLEMENTED, EFFICACY
UNMEASURED" per the repository's rule.

## 8. Installer + run-from-thumb-drive (D6/D7)

Modern Windows **disables USB AutoRun/AutoPlay for removable drives** (post-
Conficker, ~2011) - an `autorun.inf` will not silently execute. So setup is
**one double-click**, and the installer is a **self-contained PowerShell + WPF
wizard** (no Inno/NSIS toolchain; builds and ships fully offline). Built
2026-08-05 under `scripts/portable_socsci/windows/`.

**Double-click entry points (bundle root):**
- `START.bat` - launch. Double-clicked directly on the USB it runs in portable
  mode (everything on the drive, sequential search queue ON). If the wizard has
  written `sfu_runtime.cfg` next to it, that configuration selects the mode/paths.
- `SETUP.bat` -> `install_wizard.ps1` - the setup wizard.
- `MOVE-BACK.bat` - restore files the wizard offloaded to the USB.

**Wizard steps (`install_wizard.ps1`):**
1. Welcome + USB-vs-SSD speed explainer (measured cold ~112 s off USB).
2. **CPU preflight** - `IsProcessorFeaturePresent(40)` = PF_AVX2. `seismic.pyd`
   is built `x86-64-v3`, so a no-AVX2 CPU is warned + pointed at the lower-ISA
   rebuild (`build_windows_runtime.ps1`, `target-cpu=x86-64-v2`); setup can
   still continue.
3. **Mode** (radio): **Install-to-PC** (copies the whole ~66 GiB engine to the
   SSD; fastest), **Hybrid** (copies the ~24 GiB latency-sensitive parts -
   `thinclient_index`+`models`+`python`+`source`+`web` - to the SSD and streams the
   ~41 GiB `seismic/` from the USB), **Run-from-USB** (nothing installed;
   sequential search queue). Live per-mode free-space math.
4. **Free up space** (only when the chosen mode needs more room than is free) -
   the Space Assistant.
5. **Copy** - determinate progress, run in a background runspace so the WPF
   window stays responsive; the engine copy is byte-accounted.
6. **Finish** - writes `sfu_runtime.cfg`, optional Desktop shortcut, launches.

**Space Assistant (`space_assistant.ps1`) - verified, reversible offload.**
To make room on a small SSD the user hand-picks large personal files (scanned
from Downloads/Videos/Documents/Desktop, >200 MB). Each move is **sha256
original -> copy to `<USB>\_offloaded\<drive>\<path>` -> re-sha256 and require a
match -> only THEN delete the original -> append `moved_manifest.json`**. Delete
is always last, so an interruption never loses data (worst case = a verified
duplicate on the USB). `MOVE-BACK.bat` / `Restore-MovedFiles` reverses every
move (copy back -> verify -> remove the USB copy). This is the safe realization
of the "install in chunks" idea: free enough room first, then copy - same end
state (movies on USB, engine on SSD) without a fragile mid-copy interleave. USB
headroom after the 66 GiB bundle is ~48 GiB - the cap on what can be offloaded.

**`sfu_runtime.cfg` (KEY=VALUE, wizard-written, START.bat-consumed):**
`MODE=pc|hybrid|usb`, `SEQUENTIAL=0|1`, `INDEX_ROOT`, `MODEL_ROOT`,
`SEISMIC_BUNDLE_ROOT` (the root containing `seismic\`; the USB in Hybrid).
START.bat sits with the runtime it launches, so `%ROOT%` finds python + index;
only seismic's location varies by mode. No configuration = portable defaults (all
drive-relative, `SEQUENTIAL=1`). START.bat exports **`SFU_SEQUENTIAL_MODE`** for
the server/UI to key the search queue off.

**Efficacy: IMPLEMENTED 2026-08-05, UNMEASURED on Windows.** The wizard, Space
Assistant, and the START.bat configuration path are authored on Linux and cannot be run
here (WPF + P/Invoke + runspaces need a real Windows host). Windows smoke test
required: wizard renders + all three modes; AVX2 gate; a verified move +
MOVE-BACK round-trip; launch in each mode. **The server `/health` sequential
flag and the web search-queue UI (download-manager pattern, research-backed)
LANDED 2026-08-05** (commit `49b44f7`, touching `web/` + `source/sfu_library_mcp_http.py`;
jsdom 24/24), documented in `docs/THIN_CLIENT_SWAP.md`.

## 9. Mounting the finished drive into THIS dev container

This container runs under **Docker Desktop + WSL2** (`.devcontainer/
docker-compose.yml`; host paths bind-mount with Windows syntax, for example,
`${USERPROFILE}/Downloads:/mnt/host-downloads`). Two facts drive the recipe:
mounting needs a **new bind entry** in that compose (you can't add a mount to a
running container), and recreating the container **ends the running session** —
so mount at the *end*, once the bundle is staged and ready to copy.

**Format first: exFAT (or NTFS), never FAT32.** The bundle holds files over
FAT32's 4 GiB cap (`meta.sqlite` 4.07 GiB; each `forward_data.bin` ~3.85 GiB),
and a 114 GB volume can't practically be FAT32 anyway. WSL2's kernel has exfat +
ntfs3 built in, so no extra packages are needed to mount it.

**usbipd path (owner's choice) — attach the raw device to WSL2, then bind it in:**

1. **Windows (admin PowerShell)** — install once (`winget install usbipd`), then:
   ```powershell
   usbipd list                       # find the drive's BUSID, e.g. 2-4
   usbipd bind   --busid 2-4          # one-time share (admin)
   usbipd attach --wsl --busid 2-4    # attach to WSL2 (re-run after each replug;
                                      # add --auto-attach to keep it attached)
   ```
   While attached, Windows itself loses the drive (exclusive to WSL) — fine for
   writing the bundle.
2. **Default WSL2 distro** (a plain `wsl` shell, NOT this container):
   ```bash
   lsblk                              # find the node, e.g. sdd with part sdd1
   sudo mkdir -p /mnt/wsl/usb
   sudo mount /dev/sdd1 /mnt/wsl/usb  # exfat/ntfs3 auto-detected; add -t exfat if not
   ```
   Mount under **`/mnt/wsl/`** specifically — that tmpfs is shared across the
   WSL↔Docker-Desktop boundary, so a container bind-mount of it resolves
   reliably (a plain `/mnt/<letter>` drvfs path does not propagate the same way).
3. **Add the bind to your container's compose file** (the owner's `.devcontainer/docker-compose.yml`, outside the repository) under `services: app:
   volumes:` and recreate:
   ```yaml
       - /mnt/wsl/usb:/mnt/usb
   ```
   `docker compose -f .devcontainer/docker-compose.yml up -d --force-recreate app`
   (or VS Code → *Development Containers: Rebuild Container*). **This restarts the
   container and ends the current session — reconnect after.**
4. **Verify in the container:** `ls -la /mnt/usb` shows the drive;
   `touch /mnt/usb/.wtest && rm /mnt/usb/.wtest` confirms it's writable.

Alternative (**no usbipd**): if Docker Desktop already shares the drive letter,
just bind `- E:/:/mnt/usb` in the same compose and recreate — simpler, but the
removable drive may not propagate, which is exactly what usbipd fixes.

**Copy the staged bundle onto the drive:**
```bash
rsync -a --info=progress2 /var/tmp/portable_socsci_bundle/ /mnt/usb/
```
Then repoint the seismic manifest at the drive's own path so it serves from
there (Windows `START.bat` does this automatically on the target host):
```bash
BUNDLE=/mnt/usb .venv/bin/python3 scripts/portable_socsci/03_seismic_full.py \
    --manifest-only --seismic-root /mnt/usb/seismic
```

**Drive image instead of a device:** a produced `.img` loop-mounts read-only —
`sudo mount -o loop,ro bundle.img /mnt/usb` — exFAT images need `exfatprogs`/
`exfat-fuse` in the container.

## 10. Execution order (mirrors the task list)

1. This doc (design of record). ← committed 2026-08-04
2. ✅ `meta.sqlite` social filter (phase 1) ‖ tantivy+abstracts+encoder assembly
   (phase 2). Both DONE 2026-08-04 (23.87 GiB data layer).
3. ✅ **v1 seismic (phase 3)**: full-seismic copy over 8 shards + bundle manifest
   (`03_seismic_full.py`). Chosen over the subset-rebuild — see §5. (v2 subset +
   per-shard parity PASS remains the tracked size optimization.)
4. Bundle assembled (dense stripped); **verify it serves on Linux**
   (`04_verify_serve.py`, phase 4).
5. Windows (reconciled 2026-09-29 against code + git history): ✅ 5a cfg-gate
   (`2f270370`, 2026-08-04); ✅ 5b-prep offline build kit `06_windows_buildkit.py`
   (`f77435c7`) staging `build_windows_runtime.ps1` + `serving_requirements_win.txt`;
   ✅ 5d skeleton `05_windows_stage.py` (`a9c4f02b`: `source/` + `web/` + `START.bat`
   CRLF + `regen_seismic_manifest.py`, reports `python/` and `seismic.pyd` as
   still-needed); ✅ 07 installer layer (`c2bce3f1`, 2026-08-05); native
   `seismic.pyd` + relocatable `python\` **compiled on-drive, owner-attested
   2026-08-08** (not container-verifiable). The cargo-xwin cross-build in §7's
   original plan was superseded by the native kit and never built. **Remaining,
   genuinely UNMEASURED: does `seismic.pyd` load, mmap and serve bit-exact on a
   real Windows host** (§7 testability boundary; `PORTABLE_STACK_MANIFEST.md`
   §(d) row 1).
6. Installer (portable + install modes) with the thumb-drive option.
7. Mount instructions validated (§9 — usbipd path is the owner's choice);
   session-end doc sync (`THIN_CLIENT_SWAP.md`, `README.md`).

Numbers marked `*est.*` here are replaced with measured values as each phase
lands; unmeasured Windows-runtime behavior stays flagged until proven on Windows.
