# spike/ — vendored forks + spike code

- `seismic_upstream/` — the LIVE seismic Rust fork (gitignored nested repository;
  tracked as `seismic_upstream_fork.patch`). Build recipes: doc 10 §7.7.
  `main` = 2c4d863 (reset 2026-09-30); the CLOSED in-place spike's v3 commits sit on
  branch `inplace-v3` — never merge it into `main` (owner decision 2026-09-30).
  NEVER build shippable .so with -C target-cpu=native (v3 is the portable
  target, gates recleared 2026-07-17).
- `seismic_testbed_instrumented/`, `toolkit_fork/`, `vectorium_fork/` — live.
- `delta_ingest/` — ACTIVE 2026-09-29: source-agnostic trickle-update ingest
  (records/adapters/ledger/buffer/generation/compaction/CLI). Serving reader
  is product code at `source/lib/thinclient/delta_layer.py` (gate
  `SFU_DELTA_ROOT`). Docs + pre-registration: `docs/delta_ingest/`. Tests:
  `scripts/tests/test_delta_ingest.py`. Work directories under `work/` are gitignored.
- `archive/smallmachine_levers/` — CLOSED DEAD 2026-09-25 (cloud access
  ended; the OCI E5 box its bars were judged on is gone). Evidence only;
  never pending.
- `archive/block_prefetch/` — lever #4 term-prefix WILLNEED prefetch module
  (unit tests deleted 2026-10-11, recoverable from 4e66eb6d), CLOSED MEASURED 2026-09-25 (cold −4.4% versus ≥ 20% bar;
  `docs/SPECULATIVE_RETRIEVAL_UPGRADES.md` §4 row 4). Evidence only; never pending.
- `archive/inplace_update/` — in-place bit-update spike (format-v3 encoder/decoder
  patches under `patches/`, Rust updater crate, Stage-0 harness modules, specification +
  findings), CLOSED MEASURED 2026-09-30 by its GO rule (S0-1 coverage 0.019 versus
  0.80; `docs/archive/inplace_update/`). Fork `seismic_upstream/`: `main` reset to
  2c4d863 on 2026-09-30; the v3 commits a3173d1..328bf51 are on branch `inplace-v3`
  (c7b4b54 on `b1-guard`), never in the installed `.so`. Do not merge `inplace-v3`
  into `main` (owner decision 2026-09-30: +1.3 % B1 per-query cost). Evidence only;
  never pending.
- `archive/mmap_bmp/` — the killed BMP spike (STOPPED 2026-06-26, evidence
  for docs/archive/sparse_engine_project decision record). Do not resurrect or
  delete.
