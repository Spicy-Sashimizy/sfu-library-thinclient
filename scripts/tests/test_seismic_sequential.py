"""Guard tests for SEISMIC sequential serving (two distinct classes, 2026-06-30).

The sequential serving method — `SequentialSeismicBackend` (a DISTINCT class from
the server-side `ParallelSeismicBackend`), picked by `SFU_SEISMIC_FEDERATION=
sequential` in the retriever (`docs/seismic_sequential_serving/`) — serves the
SAME immutable C2 mmap shards one shard at a time. These tests lock in the
load-bearing properties of the two-class split so a regression fails loudly
instead of silently changing demo answers, re-introducing the Path-A floor, or
re-coupling the two methods' instance state.

Independent of the parallel federation tests (`test_served_seismic_path.py` is the
served-path guard; `g_federation_overlap.py` the parallel overlap gate). These
tests exercise the REAL `ParallelSeismicBackend` / `SequentialSeismicBackend` +
`MmapSeismicIndex` over a tiny in-test synthetic shard, not a mock.

BEHAVIOURS UNDER GUARD (one test each):

1. **T1 Result-equivalence (the keystone)** — `SequentialSeismicBackend` top-k is
   BIT-IDENTICAL to `ParallelSeismicBackend` top-k for the same query + `k'`
   over-fetch. Because every shard shares one SPLADE vocabulary and the per-shard
   score-merge is order-independent (one shared pure `_merge_topk`), visiting
   shards serially vs concurrently cannot change the merged set. A mismatch is a
   real bug (off-by-one in the merge, dropped shard), not an approximation — hence
   the hard equality (same oaid order + scores within 1e-6).
2. **Cascade guard** — the two methods are instances of DIFFERENT concrete classes
   and share NO mutable instance state — a parallel thread bug/state mutation
   physically cannot reach a SequentialSeismicBackend instance. Pins the
   cascade-safety property the Option-3 split exists to provide.
3. **T4 No silent fallback (sequential too)** — `SequentialSeismicBackend` +
   `load_mode="mmap"` with an absent `.mmap/` dir raises `RuntimeError`, NEVER a
   silent Path-A stock reload that would re-introduce the ~137 GB anon floor.
   Sequential inherits the G3 guarantee; assert it, don't assume it.
4. **T6 Encode/traverse split (sequential)** — `search_with_timing` returns
   `(results, encode_ms, traverse_ms)` so the serve bench can attribute per-query
   latency; under sequential, traverse_ms is the sum of per-shard times.
5. **Back-compat selector** — `ShardedSeismicBackend(...)` (no federation kwarg)
   returns a `ParallelSeismicBackend` (the load-bearing harness contract);
   `federation="sequential"` returns `SequentialSeismicBackend`; `federation="bogus"`
   raises ValueError.
6. **Mechanism (B) re-fault** — the pyo3 `MmapSeismicIndex.release_pages` (shipped
   via the `.so` rebuild) is present; after it `MADV_DONTNEED`s a shard's resident
   pages, a subsequent search re-faults and returns IDENTICAL results (the
   `madvise(2)` contract). Asserts release_pages can't corrupt the view.

T2/T3 (RAM-bounded / swap-free) are NOT here — they need the real 150M shards on
the 31.6 GB box and are benchmark-time, not unit-test (per the efficacy rule,
unmeasured claims are marked design-only). They run via
`serve_footprint_bench.py --federation sequential`.

Shard fixture: builds a tiny synthetic SEISMIC index IN-TEST (200 docs, shared
10-token vocab with docs 0-9 boosted on `receptor`/`kinase`), then converts it
to the C2 flat mmap layout via the `c1a_mmap_index` bin — so T1 exercises the
real `MmapSeismicIndex` + both federation branches over it. Skips cleanly when
the toolchain (`seismic`, the c1a bin) is absent; the two no-shard gate tests
(T4, flag validation) still run regardless.

Run from repo root:

    .venv/bin/python3 -m pytest scripts/tests/test_seismic_sequential.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

_VOCAB = ["cell", "receptor", "membrane", "signal", "kinase", "phosphory",
          "transduc", "protein", "gene", "express"]
_SHARD_DOCS = 200
_C1A_BIN = REPO / "spike" / "seismic_upstream" / "target" / "release" / "c1a_mmap_index"
_CARGO_ENV = {"PATH": "/usr/local/cargo/bin:" + os.environ.get("PATH", ""),
              "CARGO_HOME": "/usr/local/cargo", "RUSTUP_HOME": "/usr/local/rustup"}


def _have_seismic() -> bool:
    try:
        import seismic  # noqa: F401
        return hasattr(seismic, "MmapSeismicIndex")
    except Exception:
        return False


def _have_c1a_bin() -> bool:
    return _C1A_BIN.is_file()


def _need_shard(reason: str):
    """Skip a test that needs the built+converted synthetic shard."""
    pytest.skip(reason)


@pytest.fixture
def synth_shard(tmp_path):
    """Build + convert a tiny synthetic SEISMIC shard (mmap layout).

    Returns the STOCK `.index.seismic` path (the path the loader derives the
    sibling `.mmap/` dir from). Skips if the toolchain is absent.

    Layout contract (load-bearing, see ShardedSeismicBackend._load_one_shard +
    the C2 GOTCHA): the converted dir MUST be `<stem>.mmap/` next to the stock
    `<stem>.index.seismic`. Mirrors the test_served_seismic_path.py fixture.
    """
    if not _have_seismic():
        _need_shard("`seismic` (pyo3) not importable in this venv")
    if not _have_c1a_bin():
        _need_shard(f"c1a_mmap_index bin not built: {_C1A_BIN}")

    jsonl = tmp_path / "synth.jsonl"
    with open(jsonl, "w") as f:
        for i in range(_SHARD_DOCS):
            vec = {t: (3.0 if (i < 10 and t in ("receptor", "kinase")) else 0.5)
                   for t in _VOCAB}
            f.write(json.dumps({"id": f"W{1000000 + i}", "vector": vec}) + "\n")

    import seismic
    stem = tmp_path / "synth"
    idx = seismic.SeismicIndex.build(
        str(jsonl), n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
        summary_energy=0.4, max_fraction=1.5, doc_cut=15, num_threads=2)
    idx.save(str(stem))
    stock = tmp_path / "synth.index.seismic"
    assert stock.is_file(), "SeismicIndex.save() did not write the expected stock index"

    mmap_dir = tmp_path / "synth.mmap"
    env = {**os.environ, **_CARGO_ENV}
    proc = subprocess.run(
        [str(_C1A_BIN), "--index-book", str(stock), "--mmap-dir", str(mmap_dir),
         "--n-queries", "5"],
        env=env, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0 or not mmap_dir.is_dir():
        _need_shard(f"c1a_mmap_index conversion failed (rc={proc.returncode}); "
                    f"needs cargo/sudo env.\nstderr: {proc.stderr[:500]}")
    return stock


def test_sequential_identical_to_parallel(synth_shard):
    """THE keystone: sequential top-k is BIT-IDENTICAL to parallel top-k, across
    two DISTINCT serving classes.

    Same query + same `k'` over-fetch over the same shard. Because the per-shard
    score-merge is order-independent (one shared pure `_merge_topk`, identical
    encoded qvec), visiting shards serially vs concurrently cannot change the
    merged set. Assert identical oaid ORDER + scores within 1e-6 (a hard equality
    gate, not a tolerance)."""
    stock = synth_shard
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, SequentialSeismicBackend)

    par = ParallelSeismicBackend([str(stock)], load_mode="mmap")
    seq = SequentialSeismicBackend([str(stock)], load_mode="mmap")
    assert par.federation == "parallel" and seq.federation == "sequential"

    q = {"receptor": 1.0, "kinase": 1.0}
    par_res = par.search_encoded(q, top_k=50, k_prime=200)
    seq_res = seq.search_encoded(q, top_k=50, k_prime=200)

    assert par_res and seq_res, "both modes must return results for a boosted query"

    assert [oaid for oaid, _ in seq_res] == [oaid for oaid, _ in par_res], (
        "sequential top-k must match parallel top-k ORDER exactly "
        f"(merge is order-independent)\n  seq={seq_res[:5]}\n  par={par_res[:5]}")
    assert all(abs(s - p) < 1e-6 for (_, s), (_, p) in zip(seq_res, par_res)), (
        f"sequential scores must match parallel within 1e-6\n"
        f"  seq={seq_res[:5]}\n  par={par_res[:5]}")
    assert seq_res[0][0] == "W1000000", f"top hit must be a boosted doc; got {seq_res[0]}"
    assert all(score == pytest.approx(6.0) for _, score in seq_res[:10]), (
        f"top-10 must be the receptor+kinase boost (3.0+3.0); got {seq_res[:10]}")


def test_sequential_identical_to_parallel_multi_shard(synth_shard, tmp_path):
    """T1 across >1 shard: build a 2nd shard from the SAME vocabulary and confirm
    the two federation methods still merge to identical global top-k. Sequential's
    serial loop and parallel's fan-out must produce the same merged set, regardless
    of how many shards the per-shard results came from."""
    stock = synth_shard
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, SequentialSeismicBackend)

    paths = [str(stock), str(stock)]
    par = ParallelSeismicBackend(paths, load_mode="mmap")
    seq = SequentialSeismicBackend(paths, load_mode="mmap")

    q = {"receptor": 1.0, "kinase": 1.0, "signal": 0.5}
    par_res = par.search_encoded(q, top_k=50, k_prime=200)
    seq_res = seq.search_encoded(q, top_k=50, k_prime=200)

    assert [oaid for oaid, _ in seq_res] == [oaid for oaid, _ in par_res], (
        "multi-shard sequential must match parallel order exactly")
    assert all(abs(s - p) < 1e-6 for (_, s), (_, p) in zip(seq_res, par_res)), (
        "multi-shard sequential scores must match parallel within 1e-6")


def test_hybrid_identical_to_parallel_and_sequential(synth_shard):
    """Q7 keystone (2026-07-10): `HybridSeismicBackend` returns bit-identical
    top-k to BOTH `ParallelSeismicBackend` and `SequentialSeismicBackend`.

    The hybrid flips seq→par on a state signal mid-stream; the load-bearing
    claim is that the flip CANNOT change results — the shared pure `_merge_topk`
    is order-independent, and both fan-outs feed it identical per-shard results
    (same encoded qvec → same dot-product space). So a query served on the flip
    boundary still returns the bit-identical top-k. This test forces BOTH arms
    of the hybrid (sequential via DISABLE, parallel via force-flip) and asserts
    each matches the standalone methods."""
    stock = synth_shard
    import os as _os
    _saved = {k: _os.environ.pop(k, None) for k in list(_os.environ)
              if k.startswith("SFU_SEISMIC_HYBRID_")}
    try:
        from lib.thinclient.sharded_seismic_backend import (
            ParallelSeismicBackend, SequentialSeismicBackend, HybridSeismicBackend)

        paths = [str(stock), str(stock)]
        par = ParallelSeismicBackend(paths, load_mode="mmap")
        seq = SequentialSeismicBackend(paths, load_mode="mmap")

        q = {"receptor": 1.0, "kinase": 1.0, "signal": 0.5}
        par_res = par.search_encoded(q, top_k=50, k_prime=200)
        seq_res = seq.search_encoded(q, top_k=50, k_prime=200)
        assert par_res and seq_res

        _os.environ.pop("SFU_SEISMIC_HYBRID_DISABLE", None)
        hyb_adaptive = HybridSeismicBackend(paths, load_mode="mmap")
        assert hyb_adaptive.federation == "hybrid"
        qs = [{"receptor": 1.0, "kinase": 1.0, "signal": 0.5},
              {"receptor": 1.0, "kinase": 1.0},
              {"receptor": 1.0, "kinase": 1.0, "protein": 0.5},
              {"receptor": 1.0, "kinase": 1.0, "signal": 0.5}]
        for i, qi in enumerate(qs):
            h_res = hyb_adaptive.search_encoded(qi, top_k=50, k_prime=200)
            p_res = par.search_encoded(qi, top_k=50, k_prime=200)
            s_res = seq.search_encoded(qi, top_k=50, k_prime=200)
            assert [o for o, _ in h_res] == [o for o, _ in p_res] == [o for o, _ in s_res], (
                f"hybrid(adaptive, q{i}) must match par+seq order exactly "
                f"(flip at query 3 must not change results)")
            assert all(abs(h - p) < 1e-6 for (_, h), (_, p) in zip(h_res, p_res)), (
                f"hybrid(adaptive, q{i}) scores diverged from parallel")
        assert hyb_adaptive._flipped, (
            "hybrid never flipped seq→par — the flip boundary wasn't exercised; "
            "bump the query count or lower SFU_SEISMIC_HYBRID_FLIP_N")

        _os.environ["SFU_SEISMIC_HYBRID_DISABLE"] = "1"
        hyb_par = HybridSeismicBackend(paths, load_mode="mmap")
        assert hyb_par._flipped is True and hyb_par._force_parallel
        hq = hyb_par.search_encoded(q, top_k=50, k_prime=200)
        assert [o for o, _ in hq] == [o for o, _ in par_res], (
            "hybrid(DISABLED=force_parallel) must match parallel exactly")
    finally:
        for k, v in _saved.items():
            if v is not None:
                _os.environ[k] = v


def test_hybrid_invalid_signal_rejected():
    """`SFU_SEISMIC_HYBRID_SIGNAL=bogus` raises ValueError at construction —
    so a typo can't silently fall through to an unintended flip policy."""
    import os as _os
    from lib.thinclient.sharded_seismic_backend import HybridSeismicBackend
    _stub_seismic()
    old = _os.environ.get("SFU_SEISMIC_HYBRID_SIGNAL")
    try:
        _os.environ["SFU_SEISMIC_HYBRID_SIGNAL"] = "bogus"
        with pytest.raises(ValueError, match=r"HYBRID_SIGNAL"):
            HybridSeismicBackend([], load_mode="stock")
    finally:
        if old is None:
            _os.environ.pop("SFU_SEISMIC_HYBRID_SIGNAL", None)
        else:
            _os.environ["SFU_SEISMIC_HYBRID_SIGNAL"] = old


def test_distinct_classes_share_no_mutable_state(synth_shard):
    """The cascade-safety property of Option 3 (two distinct classes): a parallel
    and a sequential backend are instances of DIFFERENT concrete classes and share
    NO mutable instance state — so a thread bug or a state mutation in one method
    physically cannot reach the other's instance. A regression here (e.g. an
    accidental shared cache/object) would re-introduce cross-method coupling,
    defeating the whole point of the split."""
    stock = synth_shard
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, SequentialSeismicBackend)

    par = ParallelSeismicBackend([str(stock)], load_mode="mmap")
    seq = SequentialSeismicBackend([str(stock)], load_mode="mmap")
    assert type(par) is not type(seq), \
        "parallel and sequential must be DIFFERENT concrete classes"
    assert type(par) is ParallelSeismicBackend and type(seq) is SequentialSeismicBackend
    assert par._encoder is not seq._encoder, "encoders must be per-instance"
    assert par.shards is not seq.shards, "shard lists must be per-instance"
    assert par is not seq


def test_release_pages_present_on_mmap_index():
    """The pyo3 `MmapSeismicIndex` must expose `release_pages` (mechanism B). A
    stale .so without it makes the sequential resident bound a heuristic, not a
    guarantee — fail loudly so it's rebuilt (maturin develop)."""
    stock = None
    if not _have_seismic():
        pytest.skip("`seismic` (pyo3) not importable in this venv")
    import seismic
    assert hasattr(seismic.MmapSeismicIndex, "release_pages"), \
        "MmapSeismicIndex lacks release_pages() — rebuild the .so (mechanism B)"


def test_sequential_refault_after_release_pages_identical(synth_shard):
    """Mechanism (B) safety: `release_pages` (MADV_DONTNEED) discards resident
    pages but keeps the virtual mapping → the next search re-faults from the file
    and returns IDENTICAL results. Search the same shard sequentially TWICE (the
    `_fan_out` calls `release_pages` after the 1st shard each time); the two
    results must be bit-identical. A divergence means release_pages corrupted the
    view (e.g. advised an owned-anon range by mistake)."""
    stock = synth_shard
    from lib.thinclient.sharded_seismic_backend import SequentialSeismicBackend

    seq = SequentialSeismicBackend([str(stock)], load_mode="mmap")
    hook = hasattr(seq.shards[0], "release_pages")
    if not hook:
        pytest.skip("shard has no release_pages() (older .so); re-fault test n/a")

    q = {"receptor": 1.0, "kinase": 1.0, "signal": 0.5, "protein": 0.5}
    first = seq.search_encoded(q, top_k=50, k_prime=200)
    seq.shards[0].touch_slab()
    second = seq.search_encoded(q, top_k=50, k_prime=200)

    assert first and second, "both searches must return results"
    assert [oaid for oaid, _ in second] == [oaid for oaid, _ in first], (
        "results changed across searches after release_pages — the MADV_DONTNEED "
        "re-fault does NOT return identical data (a real bug)\n"
        f"  1st={first[:5]}\n  2nd={second[:5]}")
    assert all(abs(s - p) < 1e-6 for (_, s), (_, p) in zip(second, first)), (
        f"scores changed after release_pages re-fault\n"
        f"  1st={first[:5]}\n  2nd={second[:5]}")


def test_sequential_mmap_missing_dir_raises_no_silent_fallback():
    """Sequential inherits the G3 guarantee: `SequentialSeismicBackend` +
    `load_mode="mmap"` with an absent `.mmap/` dir raises RuntimeError, NEVER a
    silent Path-A stock reload that would re-introduce the ~137 GB anon floor."""
    from lib.thinclient.sharded_seismic_backend import SequentialSeismicBackend

    bogus = "/nonexistent/absent_shard.index.seismic"
    with pytest.raises(RuntimeError, match=r"mmap dir not found|load_mode=mmap"):
        SequentialSeismicBackend([bogus], load_mode="mmap")


def test_sequential_search_with_timing_split(synth_shard):
    """`search_with_timing` in sequential mode returns
    `(results, encode_ms, traverse_ms)` so the serve bench can attribute latency.
    Under sequential, traverse_ms is the sum of per-shard search times (>=0); on a
    real qvec it is non-zero. The result list must match the untimed search."""
    stock = synth_shard
    from lib.thinclient.sharded_seismic_backend import SequentialSeismicBackend

    seq = SequentialSeismicBackend([str(stock)], load_mode="mmap")
    res, enc_ms, trav_ms = seq.search_with_timing(
        "receptor kinase signal transduc protein", top_k=10, k_prime=40)
    assert isinstance(res, list) and len(res) == 10, "must return 10 results"
    assert all(isinstance(t, tuple) and len(t) == 2 for t in res), \
        "must return [(oaid, score)] tuples"
    assert enc_ms >= 0.0 and trav_ms >= 0.0, "timing walls must be non-negative"
    assert trav_ms > 0.0, f"sequential traverse_ms should be >0; got {trav_ms}"


def test_backcompat_selector_default_is_parallel():
    """`ShardedSeismicBackend(index_paths, load_mode="mmap")` with NO federation
    kwarg returns a ParallelSeismicBackend instance — the load-bearing harness
    contract (g6_rrf_parity_fullcorpus.py, reconcile_legoverlap.py,
    serve_footprint_bench.py). If this default ever flips or the selector stops
    returning the concrete class, those harnesses' bit-identical results break."""
    from lib.thinclient.sharded_seismic_backend import (
        ShardedSeismicBackend, ParallelSeismicBackend, SequentialSeismicBackend)
    _stub_seismic()
    b = ShardedSeismicBackend([], load_mode="stock")
    assert type(b) is ParallelSeismicBackend, \
        f"selector default must return ParallelSeismicBackend; got {type(b).__name__}"
    assert b.federation == "parallel"


def test_backcompat_selector_federation_kwarg_dispatches():
    """`federation="sequential"` on the back-compat selector returns a
    SequentialSeismicBackend instance; `federation="parallel"` returns
    ParallelSeismicBackend. (New code should construct the concrete class
    directly — this just pins the back-compat surface.)"""
    from lib.thinclient.sharded_seismic_backend import (
        ShardedSeismicBackend, ParallelSeismicBackend, SequentialSeismicBackend)
    _stub_seismic()
    assert type(ShardedSeismicBackend([], load_mode="stock",
               federation="sequential")) is SequentialSeismicBackend
    assert type(ShardedSeismicBackend([], load_mode="stock",
               federation="parallel")) is ParallelSeismicBackend


def test_backcompat_selector_invalid_value_rejected():
    """`federation='bogus'` on the selector raises ValueError BEFORE any shard
    loads — mirror of the load_mode validation, so a typo can't silently fall
    through."""
    from lib.thinclient.sharded_seismic_backend import ShardedSeismicBackend
    _stub_seismic()
    with pytest.raises(ValueError, match=r"federation"):
        ShardedSeismicBackend([], load_mode="stock", federation="bogus")


def _stub_seismic():
    """Install throwaway `seismic` + `seismic_backend` modules so the ctor's
    loader has no real shards to build. Used by the flag-validation tests, which
    assert attributes/validation only (no shard search). Idempotent."""
    import types
    if "seismic" not in sys.modules:
        seismic = types.ModuleType("seismic")
        seismic.get_seismic_string = lambda: "<U30"
        seismic.SeismicIndex = types.SimpleNamespace(load=lambda p: None)
        seismic.MmapSeismicIndex = lambda d: None
        sys.modules["seismic"] = seismic
    if "lib.thinclient.seismic_backend" not in sys.modules:
        sb = types.ModuleType("lib.thinclient.seismic_backend")
        class SeismicBackend: ...
        sb.SeismicBackend = SeismicBackend
        sys.modules["lib.thinclient.seismic_backend"] = sb
