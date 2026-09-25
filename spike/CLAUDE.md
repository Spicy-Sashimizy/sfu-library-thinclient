# spike/ — vendored forks + spike code

- `seismic_upstream/` — the LIVE seismic Rust fork (gitignored nested repo;
  tracked as `seismic_upstream_fork.patch`). Build recipes: doc 10 §7.7.
  NEVER build shippable .so with -C target-cpu=native (v3 is the portable
  target, gates recleared 2026-07-17).
- `seismic_testbed_instrumented/`, `toolkit_fork/`, `vectorium_fork/` — live.
- `archive/smallmachine_levers/` — CLOSED DEAD 2026-09-25 (cloud access
  ended; the OCI E5 box its bars were judged on is gone). Evidence only;
  never pending.
- `archive/mmap_bmp/` — the killed BMP spike (STOPPED 2026-06-26, evidence
  for docs/archive/sparse_engine_project decision record). Do not resurrect or
  delete.
