"""Contract tests for the f32 -> uint8 SPARSE quantizer (docs/archive/qdrant_uint8_sparse/).

The quantizer is the whole lever: if its round-trip error is not bounded, the
"uint8 costs ~nothing in quality" claim has no floor under it. One test per
promise the quantizer makes -- error bound, exactness of the scale endpoints,
zero handling, index preservation, sign refusal, clipping under a global scale,
and the storage arithmetic the spike's byte numbers are computed from.

Run: .venv/bin/python3 -m pytest scripts/tests/test_qdrant_uint8_sparse.py -q
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
_SRC = REPO / "scripts" / "experiments" / "eval_qdrant_uint8_sparse_small.py"
_spec = importlib.util.spec_from_file_location("eval_qdrant_uint8_sparse_small", _SRC)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

QuantizedSparse = _mod.QuantizedSparse
SparseQuantizerError = _mod.SparseQuantizerError
choose_scale = _mod.choose_scale
quantize_sparse = _mod.quantize_sparse
dequantize_sparse = _mod.dequantize_sparse
f32_sparse_bytes = _mod.f32_sparse_bytes
uint8_sparse_bytes = _mod.uint8_sparse_bytes
UINT8_MAX = _mod.UINT8_MAX


def _splade_like(n, rng, vmax=3.0):
    """Non-negative, long-tailed weights in the range real SPLADE emits."""
    v = rng.lognormal(mean=-1.0, sigma=0.8, size=n).astype(np.float32)
    return np.minimum(v, vmax).astype(np.float32)


# ── scale selection ───────────────────────────────────────────────────────────

def test_per_vector_scale_puts_max_on_code_255():
    vals = np.array([0.1, 2.5, 1.0], dtype=np.float32)
    q = quantize_sparse([1, 2, 3], vals)
    assert q.codes[np.argmax(vals)] == UINT8_MAX
    assert q.scale == pytest.approx(2.5 / 255, rel=1e-6)


def test_empty_vector_gets_unit_scale_and_no_codes():
    q = quantize_sparse(np.zeros(0, np.uint32), np.zeros(0, np.float32))
    assert q.scale == 1.0
    assert q.codes.size == 0 and q.indices.size == 0


def test_all_zero_vector_does_not_divide_by_zero():
    assert choose_scale(np.zeros(5, np.float32)) == 1.0
    q = quantize_sparse(np.arange(5, dtype=np.uint32), np.zeros(5, np.float32))
    assert q.codes.size == 0


def test_negative_weight_is_refused():
    with pytest.raises(SparseQuantizerError):
        quantize_sparse([1, 2], np.array([0.5, -0.1], dtype=np.float32))


def test_global_mode_requires_a_positive_scale():
    with pytest.raises(SparseQuantizerError):
        quantize_sparse([1], np.array([1.0], np.float32), mode="global")
    with pytest.raises(SparseQuantizerError):
        quantize_sparse([1], np.array([1.0], np.float32), mode="global",
                        global_scale=0.0)


def test_unknown_mode_is_refused():
    with pytest.raises(SparseQuantizerError):
        choose_scale(np.array([1.0], np.float32), mode="magic")


def test_length_mismatch_is_refused():
    with pytest.raises(SparseQuantizerError):
        quantize_sparse([1, 2, 3], np.array([1.0, 2.0], np.float32))


# ── round-trip error bound ────────────────────────────────────────────────────

def test_round_trip_error_never_exceeds_half_a_step():
    """|v - dequant(quant(v))| <= scale/2 = max(v)/510, for every entry."""
    rng = np.random.default_rng(7)
    for _ in range(200):
        n = int(rng.integers(1, 300))
        vals = _splade_like(n, rng)
        idx = rng.choice(30522, n, replace=False).astype(np.uint32)
        q = quantize_sparse(idx, vals, drop_zero_codes=False)
        _, back = dequantize_sparse(q)
        assert np.all(np.abs(vals - back) <= q.scale / 2 + 1e-6)
        assert np.all(np.abs(vals - back) <= vals.max() / 510.0 + 1e-6)


def test_relative_error_on_the_largest_weights_is_sub_percent():
    """The weights that decide ranking (the big ones) survive nearly intact."""
    rng = np.random.default_rng(11)
    worst = 0.0
    for _ in range(100):
        vals = _splade_like(200, rng)
        q = quantize_sparse(np.arange(200, dtype=np.uint32), vals,
                            drop_zero_codes=False)
        _, back = dequantize_sparse(q)
        big = vals >= 0.5 * vals.max()
        worst = max(worst, float(np.max(np.abs(vals[big] - back[big]) / vals[big])))
    assert worst < 0.01


def test_codes_stay_in_uint8_range_and_dtype():
    rng = np.random.default_rng(3)
    q = quantize_sparse(np.arange(500, dtype=np.uint32), _splade_like(500, rng))
    assert q.codes.dtype == np.uint8
    assert q.codes.max() <= UINT8_MAX and q.codes.min() >= 0


def test_indices_are_untouched_by_quantization():
    rng = np.random.default_rng(5)
    idx = np.sort(rng.choice(30522, 64, replace=False)).astype(np.uint32)
    vals = _splade_like(64, rng) + 0.2
    q = quantize_sparse(idx, vals, drop_zero_codes=False)
    assert np.array_equal(q.indices, idx)
    assert q.indices.dtype == np.uint32


# ── zero handling ─────────────────────────────────────────────────────────────

def test_zero_codes_are_dropped_and_dropping_is_score_lossless():
    """A dropped entry contributes exactly 0.0 to any dot product, so pruning
    it cannot change a quantized score."""
    vals = np.array([2.0, 0.001, 0.0005, 1.0], dtype=np.float32)
    idx = np.array([10, 11, 12, 13], dtype=np.uint32)
    kept = quantize_sparse(idx, vals, drop_zero_codes=True)
    full = quantize_sparse(idx, vals, drop_zero_codes=False)
    assert kept.indices.size < full.indices.size
    assert np.all(kept.codes != 0)
    q = np.zeros(30522, np.float32)
    q[idx.astype(np.int64)] = np.array([1.0, 5.0, 5.0, 2.0], np.float32)

    def dot(qs):
        i, v = dequantize_sparse(qs)
        return float(np.dot(v, q[i.astype(np.int64)]))

    assert dot(kept) == pytest.approx(dot(full), rel=1e-6)


def test_explicit_zero_value_quantizes_to_code_zero():
    q = quantize_sparse([1, 2], np.array([0.0, 1.0], np.float32),
                        drop_zero_codes=False)
    assert q.codes[0] == 0


# ── global (BMP-style) scale ──────────────────────────────────────────────────

def test_global_scale_clips_at_255_instead_of_rescaling():
    """QUANT_SCALE=70 -> scale 1/70 -> anything above 255/70 = 3.643 clips."""
    scale = 1.0 / 70.0
    vals = np.array([1.0, 3.0, 9.0], dtype=np.float32)
    q = quantize_sparse([1, 2, 3], vals, mode="global", global_scale=scale)
    assert q.codes.tolist() == [70, 210, UINT8_MAX]
    _, back = dequantize_sparse(q)
    assert back[2] == pytest.approx(255 / 70.0, rel=1e-5)
    assert back[2] < vals[2]


def test_global_scale_is_exact_on_multiples_of_the_step():
    q = quantize_sparse([1, 2], np.array([1.0, 2.0], np.float32),
                        mode="global", global_scale=1.0 / 70.0)
    _, back = dequantize_sparse(q)
    assert back == pytest.approx(np.array([1.0, 2.0], np.float32), rel=1e-5)


# ── storage arithmetic ────────────────────────────────────────────────────────

def test_value_bytes_shrink_exactly_4x_and_totals_include_indices():
    nnz = 120
    assert f32_sparse_bytes(nnz) == nnz * 8
    assert uint8_sparse_bytes(nnz) == nnz * 5 + 4
    assert f32_sparse_bytes(nnz) / uint8_sparse_bytes(nnz) == pytest.approx(
        960 / 604, rel=1e-6)


def test_ranking_is_preserved_on_a_synthetic_corpus():
    """End-to-end sanity without qdrant: top-10 overlap vs exact f32 scoring."""
    rng = np.random.default_rng(23)
    n_docs, dim = 2000, 30522
    X = np.zeros((n_docs, dim), np.float32)
    Xq = np.zeros((n_docs, dim), np.float32)
    for d in range(n_docs):
        nnz = int(rng.integers(40, 140))
        idx = rng.choice(dim, nnz, replace=False).astype(np.uint32)
        vals = _splade_like(nnz, rng)
        X[d, idx.astype(np.int64)] = vals
        i2, v2 = dequantize_sparse(quantize_sparse(idx, vals))
        Xq[d, i2.astype(np.int64)] = v2
    overlaps = []
    for _ in range(20):
        qi = rng.choice(dim, 30, replace=False)
        q = np.zeros(dim, np.float32)
        q[qi] = _splade_like(30, rng) + 0.3
        a = set(np.argsort(-(X @ q))[:10].tolist())
        b = set(np.argsort(-(Xq @ q))[:10].tolist())
        overlaps.append(len(a & b) / 10.0)
    assert float(np.mean(overlaps)) >= 0.95
