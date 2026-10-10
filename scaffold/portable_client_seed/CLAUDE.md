# sfu-library-portable — project instructions

**What this project is:** the portable/handout client for the Duck Library
thin-client search stack — Rust orchestration (RRF + leg dispatch +
hydration) over the same immutable artifacts the research container serves,
packaged behind a Tauri shell into per-OS installers. Targets:
`x86-64-v3` (proven ships), `aarch64` (Apple Silicon / iPhone-hypothesis),
Windows decision pending.

**What this project is NOT:** the research testbed. Indexes are built,
measured, and gated in `sfu-library-thinclient` (the artifact factory +
parity oracle). This repo never builds or mutates index artifacts.

## THE PARITY GATE (non-negotiable, the founding rule)

No client release — no merged serving-path PR — without **bit-exact top-k
(ids AND scores) against the current golden fixtures** from the oracle repo
(`fixtures/` here, imported via `scripts/import_fixtures.sh`). This is the
WI-4 methodology inherited from the oracle: fixed query set → expected
top-10 per shard → diff. A parity failure is a STOP, never a tolerance.

## Contract versioning (the cross-repo drift guard)

- `CONTRACT.md` pins: bundle-manifest schema version, fixture-set date,
  artifact checksums source. Bump explicitly; never consume unpinned.
- If the oracle repo re-converts shards (e.g. E8 stages) the fixture set
  date CHANGES and this repo re-imports + re-gates before adopting.
- Absolute dates only (e.g. 2026-07-17), never "current"/"latest".

## Repo hygiene

- NO index artifacts, models, or fixtures-derived binaries in git — this
  repo stays CI-friendly small. `fixtures/` holds JSON goldens only (KBs);
  bundles are downloaded/imported to gitignored paths.
- Standard git flow, but inherit one rule from the oracle repo: stage
  explicitly, never `git add .` (imported bundles land in-tree gitignored;
  don't tempt fate).
- Rust: `cargo fmt` + `clippy -D warnings` from day one; portable CPU
  targets only (`x86-64-v3` default; NEVER `target-cpu=native` in anything
  shippable — the oracle measured the SSE2-baseline warm-gate failure AND
  the v3 fix, doc 10 §7.7).

## Key upstream references (read before designing)

In the oracle repo (`sfu-library-thinclient`):
- `docs/infrastructure/PORTABLE_STACK_MANIFEST.md` — what a bundle contains
  + the installer delta list (Windows/mmap, CPU wheels, licensing, spool).
- `docs/infrastructure/PORTABLE_DATA_SHIPPING_RESEARCH.md` — DECIDED:
  subset-prebuilt + OpenAlex live tail; per-shard chunked download.
- WI-14 updater (`scripts/archive/demo_dependability/portable_bundle_updater.py`) —
  the update contract this client implements natively.
- `docs/seismic_150m_testbed/10_FORWARD_COMPRESSION_DESIGN.md` §7.7 — the
  portable-CPU gate history.
- `docs/infrastructure/GUI_BAREBONES_PROGRESS_SPEC.md` +
  `WEBGUI_RELIABILITY_RESEARCH.md` — the UI contract + redundancy layers
  (L1/L5 are structural here: local shell + local cache).
- Seismic engine: consume the fork as a git dependency (it lives nested at
  `spike/seismic_upstream` in the oracle — do NOT re-nest it here).

## First work items (in order — see BOOTSTRAP_PLAN.md)

1. Parity harness FIRST (fixtures import + Rust top-k differ) — before any
   feature code, so every later commit is gated.
2. aarch64 + x86-64-v3 builds of the seismic crate, gates recleared.
3. Rust RRF/dispatch/hydration parity port.
4. Tauri shell consuming the bare-bones GUI spec.
5. Bundle downloader implementing the WI-14 delta contract.
