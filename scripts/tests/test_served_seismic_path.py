"""Guard tests for the served SEISMIC SPLADE-leg path (2026-06-30).

The promoted served path — `_seismic_backend()` + `SFU_SEISMIC_SHARD_MANIFEST`
mmap gate + the degrade-to-BM25F contract (commits c74ec5a / 48cba3e) — shipped
with no test coverage while the rest of the thinclient package is tested. These
tests lock in the three load-bearing behaviors of that change so a regression
fails loudly instead of silently re-introducing the ~137 GB Path-A anon floor
G3 killed, or breaking RRF fusion on a leg failure.

BEHAVIORS UNDER GUARD (one test each):

1. **Happy path** — `SFU_SEISMIC_SHARD_MANIFEST` + `load_mode=mmap` → the
   federated backend loads the converted `.mmap/` shard and
   `_splade_leg_seismic` returns `[(oaid, score)]` (the Qdrant/BMP-leg shape
   RRF + record-tc join on).
2. **mmap-no-silent-fallback** — a missing `.mmap/` dir raises `RuntimeError`,
   NEVER a silent Path-A fallback (which would re-introduce the ~137 GB anon
   floor). This is the load-bearing G3 guarantee: assert it, don't assume it.
3. **degrade-to-BM25F** — a backend failure during the SEISMIC leg falls back to
   the BM25F leg so RRF still fuses the other legs (the encoder-failure
   contract `_splade_leg_seismic` inherits from the Qdrant/BMP legs).

Shard fixture: builds a tiny synthetic SEISMIC index IN-TEST (200 docs, shared
10-token vocab with docs 0-9 boosted on `receptor`/`kinase`), then converts it
to the C2 flat mmap layout via the `c1a_mmap_index` bin — so the happy-path
exercises the REAL `MmapSeismicIndex` + `ShardedSeismicBackend` + the retriever
leg, not a mock. Skips cleanly when the toolchain (`seismic`, the c1a bin, or
a writable cargo env) is absent — the two gate tests (#2, #3) still run without
any shard, so they guard on every box regardless.

Run from repo root:

    .venv/bin/python3 -m pytest scripts/tests/test_served_seismic_path.py -q
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# Shared 10-token vocab; docs 0-9 carry boosted `receptor`/`kinase` so a query
# on those two terms must return W1000000..W1000009 on top (score 6.0 = 3.0+3.0).
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
    """Build + convert a tiny synthetic SEISMIC shard.

    Returns the STOCK `.index.seismic` path (the path the loader derives the
    sibling `.mmap/` dir from). Skips if the toolchain is absent.

    Layout contract (load-bearing, see ShardedSeismicBackend._load_one_shard +
    the C2 GOTCHA): the converted dir MUST be `<stem>.mmap/` next to the stock
    `<stem>.index.seismic`. We build the stock index in-process, then run the
    `c1a_mmap_index` bin to produce the mmap dir.
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

    # In-process build (avoids build_persona_seismic.py's tail stat-crash on the
    # result-file size, and is faster/leaner for a 200-doc test fixture).
    import seismic
    stem = tmp_path / "synth"                       # bare stem -> written as synth.index.seismic
    idx = seismic.SeismicIndex.build(
        str(jsonl), n_postings=3500, centroid_fraction=0.1, min_cluster_size=2,
        summary_energy=0.4, max_fraction=1.5, doc_cut=15, num_threads=2)
    idx.save(str(stem))                              # appends .index.seismic
    stock = tmp_path / "synth.index.seismic"
    assert stock.is_file(), "SeismicIndex.save() did not write the expected stock index"

    # Convert stock -> mmap dir via the c1a bin (C2 flat layout: strings+offsets,
    # the only layout MmapSeismicIndex loads with non-None doc_mapping).
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


# ── #1: happy path — federated mmap backend loads + returns [(oaid, score)] ──

def test_federated_mmap_backend_returns_results(synth_shard):
    """`SFU_SEISMIC_SHARD_MANIFEST` + mmap → `_splade_leg_seismic` returns
    [(oaid, score)], same shape as the Qdrant/BMP legs RRF fuses on."""
    stock = synth_shard
    manifest = stock.parent / "manifest.json"
    manifest.write_text(json.dumps([str(stock)]))

    env = {**os.environ, "SFU_SPLADE_BACKEND": "seismic",
           "SFU_SEISMIC_SHARD_MANIFEST": str(manifest)}
    from lib.thinclient.retriever import ThinClientRetriever

    with _env_patch(env):
        r = ThinClientRetriever(index_root="", remote_abstracts=False,
                                splade_model_path="")  # no model: search drives the leg directly
        # _seismic_backend() must take the manifest+mmap branch (load_mode defaults
        # to "mmap" — the served 150M path, NOT stock Path-A).
        backend = r._seismic_backend()
        assert backend.load_mode == "mmap", \
            "served path must default to mmap, not stock Path-A"
        assert len(backend.shards) == 1

    # Drive the leg's search step with a hand-built qvec (bypasses the ONNX
    # encoder so the test is hermetic + ~instant, not gated on a 532MB model).
    # `receptor`/`kinase` were boosted on docs 0-9 → they MUST be the top hits.
    res = backend.search_encoded({"receptor": 1.0, "kinase": 1.0}, top_k=5)
    assert isinstance(res, list) and len(res) == 5
    assert all(isinstance(t, tuple) and len(t) == 2 for t in res), \
        "must return [(oaid, score)] tuples — the leg shape RRF joins on"
    top_ids = [oaid for oaid, _ in res]
    assert top_ids == [f"W{1000000 + i}" for i in range(5)], \
        f"boosted docs must lead; got {top_ids}"
    assert all(score == pytest.approx(6.0) for _, score in res), \
        f"scores must be the receptor+kinase dot product (3.0+3.0); got {res}"


# ── #2: mmap-no-silent-fallback — missing .mmap/ raises, never Path-A ─────────

def test_mmap_missing_dir_raises_no_silent_fallback():
    """THE load-bearing G3 guarantee: a missing `.mmap/` dir under
    load_mode=mmap raises RuntimeError — NEVER a silent Path-A fallback that
    would re-introduce the ~137 GB anon floor the savings rest on."""
    from lib.thinclient.sharded_seismic_backend import ShardedSeismicBackend

    bogus = "/nonexistent/absent_shard.index.seismic"
    with pytest.raises(RuntimeError, match=r"mmap dir not found|load_mode=mmap"):
        # from_manifest isn't needed; the ctor's _load_one_shard is the gate.
        ShardedSeismicBackend([bogus], load_mode="mmap")


def test_load_mode_mmap_default_for_served_path(monkeypatch, tmp_path):
    """`_seismic_backend()` defaults `SFU_SEISMIC_LOAD_MODE` to `mmap` for the
    served manifest path — if that default ever flips to `stock`, the served
    150M package would silently re-OOM. Pin it."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([str(tmp_path / "synth-never-built.index.seismic")]))
    monkeypatch.setenv("SFU_SPLADE_BACKEND", "seismic")
    monkeypatch.setenv("SFU_SEISMIC_SHARD_MANIFEST", str(manifest))
    monkeypatch.delenv("SFU_SEISMIC_LOAD_MODE", raising=False)

    from lib.thinclient.retriever import ThinClientRetriever
    r = ThinClientRetriever(index_root="", remote_abstracts=False, splade_model_path="")

    # The gate fires at first load: must be the mmap RuntimeError (missing dir),
    # NOT a Path-A stock deserialize of a nonexistent file (different exception).
    with pytest.raises(RuntimeError, match=r"mmap dir not found|load_mode=mmap"):
        r._seismic_backend()


# ── #3: degrade-to-BM25F — backend failure falls back, RRF still fuses ────────

def test_seismic_backend_failure_degrades_to_bm25f(tmp_path):
    """A backend failure inside `_splade_leg_seismic` degrades to the BM25F
    leg (returns its results, not an exception) so RRF still fuses the other
    legs — the encoder-failure contract inherited from the Qdrant/BMP legs."""
    from lib.thinclient.retriever import ThinClientRetriever

    r = ThinClientRetriever(index_root="", remote_abstracts=False, splade_model_path="")
    # A not-yet-_load()ed thinclient has empty BM25F sections, so the BM25F leg
    # legitimately returns [] for a bogus query — exactly the degrade shape we
    # assert (no raise). Force the SEISMIC backend to blow up on search:
    class _BoomBackend:
        def search(self, query, top_k, **kw):
            raise RuntimeError("simulated seismic backend failure")
    r._seismic = _BoomBackend()

    out = r._splade_leg_seismic("climate adaptation coastal", top_k=10, f=None)
    assert isinstance(out, list), \
        "leg failure must degrade to BM25F results, never raise out of the leg"
    # BM25F leg on an unloaded index: [] is correct (no sections). The point is
    # the exception was swallowed -> RRF fusion proceeds on the other legs.


# ── helpers ───────────────────────────────────────────────────────────────────

class _env_patch:
    """Temporarily overlay env vars (Popen-style os.environmutations are
    process-wide; revert on exit so tests don't leak env into the suite)."""
    def __init__(self, overlay):
        self.overlay = overlay
        self._saved = {}

    def __enter__(self):
        for k, v in self.overlay.items():
            self._saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, old in self._saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
