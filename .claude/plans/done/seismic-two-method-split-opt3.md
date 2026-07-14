# Plan: Split into two distinct serving classes (Option 3 — shared module helpers)

**Decided with user (2026-06-30):** refactor the single-class-with-branch design
(shipped last turn) into **two distinct serving classes** — `ParallelSeismicBackend`
(server-side) and `SequentialSeismicBackend` (localized, RAM-efficient) — that share
**pure module-level helpers** (`_merge_topk`, `_load_one_shard`, `_load_manifest`,
`_EncoderShim`), with **no inheritance and no shared mutable instance state**.

**Why Option 3 (cascade reasoning):** for this system whose entire correctness story
is "both methods return bit-identical top-k," *silent divergence* is the most
dangerous cascade — Option 2 (duplicate the merge) is the only shape that allows it.
Option 1 (base class) adds fragile-base + shared-mutable-state + common-mode
cascade vectors. Option 3 keeps the one shared copy of the merge (no drift) and the
only residual cascade vector — common-mode failure of a shared helper — lives in
**pure functions** covered by one merge unit-test + the existing T1 equivalence test.
A parallel thread bug physically cannot reach the sequential class's instance.

**Non-disruption (hard constraint):** keep the back-compat name `ShardedSeismicBackend`
as a thin selector that still accepts `federation=` and defaults to parallel, so the
three load-bearing parity harnesses that construct `ShardedSeismicBackend(index_paths,
load_mode="mmap")` with NO `federation` kwarg (`g6_rrf_parity_fullcorpus.py`,
`reconcile_legoverlap.py`, `serve_footprint_bench.py`) keep working unchanged, and
their bit-identical G6/overlap results don't cascade-break.

---

## File: `src/lib/thinclient/sharded_seismic_backend.py`

### Layout after refactor (one file, three classes + module helpers)

```
module docstring (updated: "two distinct serving methods", cite the cascade rationale)
-module-level: import cf, json, logging, Path, numpy; `log`

# ── shared pure helpers (no instance state crosses the method boundary) ──
class _EncoderShim:                      # unchanged (encode_splade borrow)
def _load_manifest(manifest_path):       # unchanged
def _load_one_shard(seismic_module, p, load_mode, log):  # WAS a method; now module fn
def _merge_topk(per_shard_results, top_k):               # NEW — the ONE shared merge
def _prepare_query(q, string_dtype):    # NEW — tokens/values/qcomp/qvals/qc/kp prep
                                          #   (pure; both classes call it identically)

# ── the two distinct serving classes ──
class ParallelSeismicBackend:
    __init__(self, index_paths, splade_model_path=..., load_mode="stock")
        # validates load_mode; loads shards via _load_one_shard; owns self.shards,
        # self._seismic, self._string_dtype, self._encoder, self.load_mode.
        # NO federation attr — it IS the parallel method.
    from_manifest(...) classmethod        # parallel
    encode_query(query)                   # shared impl, copied (thin: delegates to _EncoderShim)
    search(query, top_k, ...)              # encode then search_encoded
    search_encoded(q, top_k, ...)          # _prepare_query; _fan_out = ThreadPoolExecutor;
                                           #   _merge_topk
    _fan_out(self, _search_one)            # the parallel fan-out (max-of-shards)
    search_with_timing(query, top_k, ...)  # shared impl, copied (thin timing wrapper)
    federation = "parallel"                 # class attr, for back-compat reads (tests assert it)

class SequentialSeismicBackend:
    (mirror of Parallel, but)
    _fan_out(self, _search_one)            # the serial loop (sum-of-shards)
    federation = "sequential"              # class attr
    # OWN docstring: localized/RAM-efficient deployment; bounded resident set;
    #   mechanism (A) of docs/seismic_sequential_serving/

# ── back-compat selector (keeps every existing call site green) ──
class ShardedSeismicBackend:
    """Back-compat selector. Delegates to Parallel (default) or Sequential via
    `federation=`. Prefer the specific class in new code. Kept so the G6/overlap
    parity harnesses (`from seismic_federated import ShardedSeismicBackend`) and
    `ShardedSeismicBackend(index_paths, load_mode="mmap")` ctor calls keep working
    unchanged — their bit-identical results are load-bearing."""
    def __init__(self, index_paths, splade_model_path=..., load_mode="stock",
                 federation="parallel"):
        # validate federation; pick the class; set self.__class__ via delegation
        # (or subclass both — see "shape decision" below)
```

### Shape decision for the selector

`ShardedSeismicBackend` will be a **thin factory function masquerading as a class
via `__new__`** that returns a `ParallelSeismicBackend` or `SequentialSeismicBackend`
instance. Rationale: must return a real instance of one of the two classes (so
`isinstance` + `backend.federation` + the existing `backend.shards`/`.load_mode`
attribute reads all work), AND keep `from_manifest` as a classmethod returning the
right type. `__new__` returning a subclass instance is the standard Python pattern
for this and avoids code duplication. `federation` validation stays in the selector.

### What's shared (pure module helpers) vs what's per-class

**Shared (pure functions, one copy each → no drift):**
- `_load_one_shard` (was a method; takes `seismic_module` + `load_mode` args)
- `_load_manifest` (unchanged)
- `_merge_topk(per_shard_results, top_k)` — the score-sort + de-dup + truncate.
  Extracted verbatim from the current `search_encoded` lines 252-265.
- `_prepare_query(q, string_dtype)` — the tokens/values/qcomp/qvals/qc/kp prep
  (current lines 219-226), pure.
- `_EncoderShim` (unchanged).

**Per-class (the ONLY thing that differs):**
- `_fan_out(self, _search_one)` — parallel: `ThreadPoolExecutor.map`; sequential:
  serial `for idx in self.shards:` loop. ~5 lines each.
- `search_encoded` calls `_prepare_query` + `self._fan_out` + `_merge_topk`. Identical
  body in both classes EXCEPT the `_fan_out` dispatch (which is the override).

**`encode_query` / `search` / `search_with_timing`:** thin wrappers, identical across
both classes. Copied (not inherited) — each ~6-8 lines. This is acceptable duplication
(wrappers, not logic) and it's what makes the classes genuinely self-contained.
Alternatively: `$fan_out` + these wrappers could live on a tiny mixin, but that
reintroduces shared-instance-state coupling — the exact cascade vector Option 3 avoids.
So copy the thin wrappers.

### `search_with_timing` docstring
Keep the sequential-specific note ("traverse_ms = Σ per-shard") only on
`SequentialSeismicBackend.search_with_timing`. Parallel's notes "traverse ≈ max shard".

### Back-compat surface that MUST keep working (verified by tests after refactor)
- `ShardedSeismicBackend(index_paths, load_mode="mmap")` (no federation) → parallel.
- `ShardedSeismicBackend.from_manifest(manifest, load_mode=...)` → parallel.
- `backend.federation` attribute exists on all three (selector validates + the two
  classes set it as a class attr).
- `backend.shards`, `backend.load_mode`, `backend.search_encoded`, `.search`,
  `.search_with_timing`, `.encode_query` — all present on the two real classes.

---

## File: `scripts/seismic_testbed/seismic_federated.py` (re-export shim)

Add the two new names to the re-export:
```python
from lib.thinclient.sharded_seismic_backend import (
    ShardedSeismicBackend, ParallelSeismicBackend, SequentialSeismicBackend,
    _EncoderShim, _load_manifest,
)
```
Keep `ShardedSeismicBackend` exported (back-compat). The CLI `--federation` flag
stays (it now selects which concrete class the `ShardedSeismicBackend(... federation=...)`
selector builds — unchanged behavior).

---

## File: `src/lib/thinclient/retriever.py`

`_seismic_backend()`: instead of passing `federation=` to `from_manifest`, pick the
concrete class directly — cleaner and explicit, which is the whole point of distinct
classes:
```python
federation = os.environ.get("SFU_SEISMIC_FEDERATION", "parallel")
cls = (SequentialSeismicBackend if federation == "sequential"
       else ParallelSeismicBackend)
self._seismic = cls.from_manifest(manifest, splade_model_path=...,
                                  load_mode=load_mode)
```
Env var name + default unchanged → no cascade to served-path callers. Keep the
back-compat selector importable too (harnesses may use it). Update the docstring.

---

## File: `scripts/tests/test_seismic_sequential.py` (update + extend)

The existing T1 already compares parallel vs sequential — keep it, but have it
construct the two **concrete classes** directly (the real test of "distinct but
equivalent"):
```python
par = ParallelSeismicBackend([str(stock)], load_mode="mmap")
seq = SequentialSeismicBackend([str(stock)], load_mode="mmap")
assert par.federation == "parallel" and seq.federation == "sequential"
```
Add:
- **Distinct-class cascade guard:** assert the two instances are of distinct concrete
  classes and share NO mutable instance state (e.g. `par._encoder is not seq._encoder`,
  `par.shards is not seq.shards`). This pins the cascade-safety property Option 3 gives.
- **Back-compat selector test:** `ShardedSeismicBackend([...], load_mode="mmap")` (no
  federation) returns a `ParallelSeismicBackend` instance; with `federation="sequential"`
  returns a `SequentialSeismicBackend` instance; `federation="bogus"` → ValueError.
  Pins the three load-bearing harnesses' ctor pattern.

Keep T4 (no-silent-fallback, now via `SequentialSeismicBackend`) + T6 + flag-validation.
The `test_served_seismic_path.py` suite (parallel path) stays unchanged and must still
pass — non-disruption proof.

---

## Docs (same-commit per CLAUDE.md)

- `docs/seismic_sequential_serving/01_ARCHITECTURE.md`: update the "code touch-points /
  IMPLEMENTED" section — the serial branch is now a distinct `SequentialSeismicBackend`
  class; cite the two-class split + the cascade rationale (Option 3) briefly.
- `README.md` wave + `00_VISION`: note the two-distinct-class shape (server vs localized).
- Memory: update `seismic-sequential-serving-shipped.md` to reflect the split (was:
  single-class-with-branch; now: two classes + shared pure helpers, no inheritance).

---

## Verification

1. `.venv/bin/python3 -m pytest scripts/tests/test_seismic_sequential.py -q` (T1
   bit-identical MUST still pass against real MmapSeismicIndex — this is the
   correctness keystone).
2. `.venv/bin/python3 -m pytest scripts/tests/test_served_seismic_path.py -q` (parallel
   path + served-path gates — non-disruption).
3. Import smoke: `ParallelSeismicBackend`, `SequentialSeismicBackend`,
   `ShardedSeismicBackend` all importable; selector dispatches correctly.
4. `serve_footprint_bench.py --help` still parses (it constructs via `federation=`).

## Git workflow (per CLAUDE.md)

Pull → edit each file → stage ONLY that file → commit → push, per logical unit.
Never `git add .` (multi-GB runtime state in the tree). Same-commit doc updates.
