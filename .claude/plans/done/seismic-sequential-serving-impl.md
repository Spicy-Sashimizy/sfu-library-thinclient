# Plan: Implement SEISMIC Sequential Serving (mechanism A only)

**Scope decided with user (2026-06-30):** Python serial mode only — mechanism (A)
from `docs/seismic_sequential_serving/01_ARCHITECTURE.md`. Mechanisms (B)
`MADV_DONTNEED` and (C) `mlock`/`MADV_RANDOM` stay as documented future hooks
(they need a `.so` rebuild; deferred). The serial branch bounds resident RAM by
searching shards one at a time and relying on the kernel to reclaim idle shards'
file-backed mmap pages under pressure (pure A, no Rust change).

**Non-disruption guarantee (the user's hard constraint):** the parallel
`ThreadPoolExecutor` path is untouched; the serial branch is selected by one
env flag chosen once at backend load; the two modes are never co-active. All
shared inputs (shards + `.mmap/` dirs) are read-only. No new persisted state.

---

## Changes

### 1. `src/lib/thinclient/sharded_seismic_backend.py` — the serial branch

**Constructor** (`__init__`, line 76): add `federation: str = "parallel"` param.
Validate it's in `("parallel", "sequential")` (raise `ValueError` otherwise —
mirrors the existing `load_mode` validation). Store as `self.federation`.
`from_manifest` (line 96) gets a matching `federation` kwarg, plumbed to `cls(...)`.

**`search_encoded` (line 165) — the only behavioral fork.** Today lines 184–193
fan out via `cf.ThreadPoolExecutor`. Replace with a dispatch on `self.federation`:

- `parallel` (default, byte-for-byte identical to today): keep the
  `ThreadPoolExecutor` + `ex.map(_search_one, self.shards)` block exactly as-is.
- `sequential` (new): a plain `for idx in self.shards:` loop calling
  `_search_one(idx)` and appending each result to `merged`. No thread pool.
  GIL is irrelevant (no parallelism attempted). One region faulted in at a time →
  under memory pressure the kernel evicts the previous shard's file pages.

The merge downstream (lines 194–208: sort by `-score`, de-dup by `doc_id`, take
`top_k`) is **shared by both modes** and unchanged — this is what makes
sequential top-k bit-identical to parallel (the load-bearing T1 property).

**`search_with_timing` (line 210):** no change needed. It already delegates to
`search_encoded`, which now dispatches on `self.federation`. The docstring note
"traverse = Σ per-shard" (03_TESTING T6) is automatically true for sequential
because the traversal is now a serial sum. I'll add a one-line docstring note so
the attribution is explicit, matching the doc.

**Docstrings:** extend the module/class docstrings with the "one system, two
serving methods" framing + the result-equivalence note, citing the design doc
(per the same-commit doc rule; the design doc already exists and will be
updated to point at the now-shipped code).

### 2. `src/lib/thinclient/retriever.py` — read the flag at load

**`_seismic_backend` (line 565):** read `SFU_SEISMIC_FEDERATION` (default
`"parallel"`) alongside the existing `SFU_SEISMIC_LOAD_MODE` read (line 588).
Pass `federation=...` to `from_manifest`. Extend the docstring's env-var list
to mention the new flag (default `parallel` = unchanged behaviour).

### 3. `scripts/tests/test_seismic_sequential.py` — NEW independent test file

Mirrors `test_served_seismic_path.py`'s conventions (in-test synthetic shard via
`seismic.SeismicIndex.build` + `c1a_mmap_index` conversion; `_have_seismic()` /
`_have_c1a_bin()` skip-guards; `_env_patch` helper). Reuses the same fixture
builder logic. Tests, per `03_TESTING.md`:

- **T1 Result-equivalence (the keystone):** build ONE synthetic shard, load it
  twice — once `federation="parallel"`, once `federation="sequential"` —
  `search_encoded` both on the same hand-built qvec (`receptor`/`kinase`),
  assert the returned `[(oaid, score)]` lists are bit-identical (same oaid order +
  `abs(s-p) < 1e-6`). This is the hard equality gate the design rests on.
- **T4 No silent fallback (sequential too):** point a sequential-mode backend at
  an absent `.mmap/` dir → `RuntimeError`, never a Path-A stock load. (Parallel
  already has this in `test_served_seismic_path.py`; the sequential path must
  inherit it. Cheap, no shard needed.)
- **T6 Encode/traverse split (sequential):** `search_with_timing` in sequential
  mode returns `(results, encode_ms, traverse_ms)` with `traverse_ms ≥ 0`
  (non-zero on a real qvec). Confirms the timed path attributes sequential runs.
- **Flag validation:** `federation="bogus"` → `ValueError`; `federation`
  absent / `"parallel"` → the existing parallel behaviour (one assertion that
  the constructor's default `self.federation == "parallel"`).

T2/T3 (RAM-bounded / swap-free) need the real 150M shards + a 31.6 GB box —
those are benchmark-time, not unit-test, and live in the bench (item 5). Not
asserted here; the file's docstring says so explicitly (per the efficacy rule —
unmeasured claims marked design-only).

### 4. `scripts/seismic_testbed/seismic_federated.py` — CLI parity (small)

Add `--federation {parallel,sequential}` (default `parallel`) to the standalone
probe's argparse (the `from seismic_federated import ShardedSeismicBackend` path
at line ~101), plumbed to the ctor. This is the testbed's own entrypoint, kept
in sync with the served package. No change to the re-export shim itself.

### 5. `scripts/seismic_testbed/serve_footprint_bench.py` — `--federation` flag

Add `--federation {parallel,sequential}` (default `parallel`), pass to
`ShardedSeismicBackend(index_paths, load_mode="mmap", federation=args.federation)`
at line 315/345. Record `federation` in the result JSON's metadata block (next to
`load_mode` at line ~574). The bench already captures VmSwap + cold/warm passes
+ the encode/traverse split — `04_BENCHMARKING.md` says extend it with exactly
this flag, so the methodology is already implemented; this just threads the mode
through. No new measurement logic.

### 6. Docs — update in the same commits (per CLAUDE.md same-commit rule)

- `docs/seismic_sequential_serving/README.md` + `00_VISION_AND_GOALS.md`: flip
  status from "DESIGN / not yet implemented" → "IMPLEMENTED (mechanism A), EFFICACY
  UNMEASURED" (the efficacy rule's exact phrase for shipped-before-eval). Note
  (B)/(C) remain design-only future hooks.
- `01_ARCHITECTURE.md`: point the "code touch-points" section at the real shipped
  lines (serial branch in `search_encoded`, flag in `_seismic_backend`).
- `02_BUILD.md`: the `SFU_SEISMIC_FEDERATION=sequential` knob is now live — mark
  it shipped instead of "the new mode (to be)".
- `docs/README.md`: add the sequential-serving dir to the index if not already
  there (git status shows the docs are untracked — verify they're indexed).

---

## What I will NOT touch (non-disruption)

- The `ThreadPoolExecutor` parallel code path — byte-for-byte identical
  (sequential is a sibling branch, gated by the flag; default keeps parallel).
- Any Rust / `.so` (mechanisms B/C deferred per scope decision).
- The build, shards, `.mmap/` dirs, query encoder — all read-only shared inputs.
- G2/G6 quality (orthogonal; sequential returns the same docs as parallel — T1).
- Existing tests (`test_served_seismic_path.py`, `test_thinclient_stack.py`) —
  the new file is additive.

## Verification

- Run the new test file: `.venv/bin/python3 -m pytest scripts/tests/test_seismic_sequential.py -q`
- Re-run the existing served-path guard tests to prove non-disruption:
  `.venv/bin/python3 -m pytest scripts/tests/test_served_seismic_path.py -q`
- Import smoke test: both federation modes construct + the default is `parallel`.

## Git workflow (per CLAUDE.md)

Pull → edit each file → stage ONLY that file → commit → push, per file/logical
unit. Never `git add .` (working tree has multi-GB runtime state). Same-commit
doc updates land in the commit that ships the code they document.
