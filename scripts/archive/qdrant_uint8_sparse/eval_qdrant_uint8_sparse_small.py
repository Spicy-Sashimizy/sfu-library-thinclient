#!/usr/bin/env python3
# CLOSED SUPERSEDED 2026-09-25 — f32→uint8 Qdrant sparse spike, moot since the SEISMIC promotion 2026-07-06 (docs/archive/qdrant_uint8_sparse/README.md); moved from scripts/experiments/ 2026-10-11
"""Small-scale end-to-end measurement of the f32 -> uint8 SPARSE quantization
fallback for the Qdrant SPLADE leg (docs/archive/qdrant_uint8_sparse/).

WHY THIS EXISTS IN THIS SHAPE (read before trusting a number out of it):

The spike's original plan was to flip `datatype=uint8` on a real Qdrant server's
sparse index and measure RSS/page-cache at 30M docs. That plan is NOT runnable on
this host: there is no qdrant binary, no docker/podman, and no server on :6333.
The only Qdrant available is the python client's *local mode*
(`QdrantClient(path=...)`), whose implementation (qdrant_client/local/) contains
no `datatype` handling at all -- it stores sparse values as plain python floats
and scores them in numpy. So local mode can prove the WRITE + QUERY contract and
the RANKING consequence of 8-bit values, but it cannot measure the engine's RAM.

What this script therefore measures, honestly:

  * QUALITY  -- the ranking consequence of representing SPLADE doc weights in
                8 bits, measured against exact f32 scoring on the same corpus:
                overlap@k, NDCG@k proxy (gain = exact f32 score), score error.
                This is engine-independent: it is a property of the numbers.
  * STORAGE  -- bytes of the sparse *value* representation, f32 vs uint8 +
                per-doc scale, counted on the real encoded arrays.
  * LATENCY  -- local-mode query wall time. This is a PYTHON BRUTE-FORCE scorer,
                NOT the Rust engine. Reported only as a relative sanity signal;
                it is NOT a substitute for G-LATENCY at 30M.

Corpus: real SPLADE vectors. Titles come from the live thin-client metadata
(read-only) and are encoded with the repo's own local SPLADE ONNX export, so the
weight distribution is the real one, not a guess. Abstracts are not available
cheaply, so nnz/doc is title-only (~73) and lower than the production title+
abstract vectors (~120); quantization error is per-value so this mostly affects
the absolute byte totals, which are reported per-nnz as well as per-doc.

Stages (each cached so a rerun is cheap):
  corpus  -- read titles, SPLADE-encode, cache CSR npz in the scratchpad
  eval    -- exact f32 ground truth, quantize, build BOTH qdrant local
             collections (datatype=FLOAT32 / datatype=UINT8), query both,
             rescore, emit JSON

Usage:
  .venv/bin/python3 scripts/archive/qdrant_uint8_sparse/eval_qdrant_uint8_sparse_small.py \
      --docs 50000 --queries 50 --out data/eval_results/qdrant_uint8_sparse_small_20260925.json
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("uint8_sparse")

META_SQLITE = REPO_ROOT / "data" / "thinclient_index" / "meta.sqlite"
SPLADE_ONNX = REPO_ROOT / "models" / "splade_onnx_fused"
TOKENIZER_DIR = REPO_ROOT / "models" / "sfu-academic-embed-v1"
BERT_VOCAB = 30522

UINT8_MAX = 255


# ─────────────────────────────── quantizer ───────────────────────────────────
# The unit under test. Pure numpy, no qdrant import, so scripts/tests can
# exercise it without a collection.

@dataclass(frozen=True)
class QuantizedSparse:
    """A sparse vector whose values are 8-bit codes plus one f32 scale.

    `values ~= codes * scale`. `indices` is u32 in the shared BERT-vocab id
    space (identical to the f32 vector's index space -- quantization never
    touches indices).
    """
    indices: np.ndarray
    codes: np.ndarray
    scale: float

    def __post_init__(self):
        if self.indices.shape != self.codes.shape:
            raise ValueError("indices/codes length mismatch")


class SparseQuantizerError(ValueError):
    """Raised when a vector cannot be quantized under the declared contract."""


def choose_scale(values: np.ndarray, mode: str = "per_vector_max",
                 global_scale: float | None = None) -> float:
    """Pick the f32 scale that maps `values` onto 0..255.

    mode="per_vector_max": scale = max(values)/255, i.e. the largest weight in
        THIS vector lands exactly on code 255 -- no clipping ever, error is
        purely rounding. Costs 4 bytes/doc to store the scale.
    mode="global": a fixed corpus-wide scale, quantizing to round(v/scale) and
        CLIPPING at 255 (this is what src/lib/thinclient/builder.py does for the
        retired BMP leg with QUANT_SCALE=70, i.e. scale = 1/70). Costs nothing
        per doc but clips any weight above 255*scale.

    An empty vector, or one whose values are all zero, gets scale 1.0 (every
    code is 0; dequantizing returns zeros) rather than a division by zero.
    """
    values = np.asarray(values, dtype=np.float32)
    if values.size and float(values.min()) < 0.0:
        raise SparseQuantizerError(
            "negative sparse weight: SPLADE weights are log1p(relu(.)) and must "
            "be >= 0; unsigned 8-bit quantization cannot represent a sign")
    if mode == "global":
        if global_scale is None or not (global_scale > 0):
            raise SparseQuantizerError("mode='global' needs a positive global_scale")
        return float(global_scale)
    if mode != "per_vector_max":
        raise SparseQuantizerError(f"unknown scale mode {mode!r}")
    if values.size == 0:
        return 1.0
    vmax = float(values.max())
    if vmax <= 0.0:
        return 1.0
    return vmax / UINT8_MAX


def quantize_sparse(indices, values, *, mode: str = "per_vector_max",
                    global_scale: float | None = None,
                    drop_zero_codes: bool = True) -> QuantizedSparse:
    """f32 sparse vector -> uint8 codes + one f32 scale.

    drop_zero_codes=True prunes entries whose weight rounds to code 0. Those
    entries contribute exactly 0.0 to every dot product once dequantized, so
    dropping them is lossless with respect to the quantized scoring function and
    strictly cheaper to store; it is the reason uint8 buys more than 4x on the
    value+index pair for long-tailed SPLADE vectors.
    """
    indices = np.asarray(indices, dtype=np.uint32)
    values = np.asarray(values, dtype=np.float32)
    if indices.shape != values.shape:
        raise SparseQuantizerError("indices/values length mismatch")
    scale = choose_scale(values, mode=mode, global_scale=global_scale)
    codes = np.rint(values / np.float32(scale))
    codes = np.clip(codes, 0, UINT8_MAX).astype(np.uint8)
    if drop_zero_codes:
        keep = codes != 0
        indices, codes = indices[keep], codes[keep]
    return QuantizedSparse(indices=indices, codes=codes, scale=float(scale))


def dequantize_sparse(q: QuantizedSparse) -> tuple[np.ndarray, np.ndarray]:
    """uint8 codes + scale -> (indices u32, values f32).

    These are the values a `datatype=uint8` sparse index scores against: the
    engine stores codes and reconstitutes `code * scale` at scoring time, so
    feeding these floats to a float collection reproduces the uint8 ranking
    exactly on any engine.
    """
    return q.indices, (q.codes.astype(np.float32) * np.float32(q.scale))


def f32_sparse_bytes(nnz: int, *, index_bytes: int = 4) -> int:
    """Bytes for one f32 sparse vector: u32 index + f32 value per nnz."""
    return nnz * (index_bytes + 4)


def uint8_sparse_bytes(nnz: int, *, index_bytes: int = 4, scale_bytes: int = 4) -> int:
    """Bytes for one uint8 sparse vector: u32 index + u8 code per nnz + scale."""
    return nnz * (index_bytes + 1) + scale_bytes


# ─────────────────────────────── corpus ──────────────────────────────────────

def _read_titles(n: int) -> list[str]:
    """Read n real academic titles from the live metadata DB (read-only)."""
    if not META_SQLITE.exists():
        raise SystemExit(f"missing {META_SQLITE}")
    uri = f"file:{META_SQLITE}?mode=ro&immutable=1"
    con = sqlite3.connect(uri, uri=True)
    try:
        rows = con.execute(
            "SELECT title FROM docs WHERE title IS NOT NULL LIMIT ?", (n,)
        ).fetchall()
    finally:
        con.close()
    out = [r[0].strip() for r in rows if r[0] and r[0].strip()]
    if len(out) < n:
        logger.warning("only %d titles available (asked %d)", len(out), n)
    return out


def _encode_splade(texts: list[str], *, threads: int, batch: int = 32,
                   max_len: int = 48):
    """SPLADE-encode texts with the repo's local ONNX export. Returns CSR parts."""
    import onnxruntime as ort
    from transformers import AutoTokenizer

    so = ort.SessionOptions()
    so.intra_op_num_threads = threads
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(SPLADE_ONNX / "model.onnx"), so,
                                providers=["CPUExecutionProvider"])
    tok = AutoTokenizer.from_pretrained(str(TOKENIZER_DIR))

    indptr = [0]
    all_idx: list[np.ndarray] = []
    all_val: list[np.ndarray] = []
    t0 = time.perf_counter()
    for start in range(0, len(texts), batch):
        chunk = texts[start:start + batch]
        enc = tok(chunk, max_length=max_len, truncation=True, padding=True,
                  return_tensors="np")
        ids = enc["input_ids"].astype(np.int64)
        mask = enc["attention_mask"].astype(np.int64)
        logits = sess.run(None, {"input_ids": ids, "attention_mask": mask,
                                 "token_type_ids": np.zeros_like(ids)})[0]
        w = np.log1p(np.maximum(logits, 0.0)) * mask.astype(np.float32)[..., None]
        pooled = w.max(axis=1)
        for row in pooled:
            nz = np.nonzero(row)[0]
            all_idx.append(nz.astype(np.uint32))
            all_val.append(row[nz].astype(np.float32))
            indptr.append(indptr[-1] + nz.size)
        if start and start % (batch * 100) == 0:
            el = time.perf_counter() - t0
            logger.info("encoded %d/%d (%.0f docs/s)", start, len(texts),
                        start / max(el, 1e-9))
    el = time.perf_counter() - t0
    logger.info("encoded %d docs in %.0fs (%.0f docs/s)", len(texts), el,
                len(texts) / max(el, 1e-9))
    return (np.asarray(indptr, dtype=np.int64),
            np.concatenate(all_idx) if all_idx else np.zeros(0, np.uint32),
            np.concatenate(all_val) if all_val else np.zeros(0, np.float32))


def build_corpus(cache: Path, n_docs: int, n_queries: int, threads: int):
    """Encode (or load from cache) the doc corpus + held-out query set."""
    if cache.exists():
        z = np.load(cache)
        if int(z["n_docs"]) >= n_docs and int(z["n_queries"]) >= n_queries:
            logger.info("corpus cache hit: %s", cache)
            return z
        logger.info("corpus cache too small (%s docs) -- re-encoding", z["n_docs"])
    titles = _read_titles(n_docs + n_queries)
    doc_titles, query_titles = titles[:n_docs], titles[n_docs:n_docs + n_queries]
    logger.info("encoding %d docs + %d queries", len(doc_titles), len(query_titles))
    d_ptr, d_idx, d_val = _encode_splade(doc_titles, threads=threads)
    q_ptr, q_idx, q_val = _encode_splade(query_titles, threads=threads)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, n_docs=len(doc_titles), n_queries=len(query_titles),
             d_ptr=d_ptr, d_idx=d_idx, d_val=d_val,
             q_ptr=q_ptr, q_idx=q_idx, q_val=q_val)
    logger.info("corpus cached -> %s", cache)
    return np.load(cache)


def _csr(ptr, idx, val, n_rows, n_cols=BERT_VOCAB):
    from scipy.sparse import csr_matrix
    return csr_matrix((val.astype(np.float32), idx.astype(np.int32),
                       ptr.astype(np.int64)), shape=(n_rows, n_cols))


# ─────────────────────────────── metrics ─────────────────────────────────────

def overlap_at_k(a: list[int], b: list[int], k: int) -> float:
    return len(set(a[:k]) & set(b[:k])) / float(k)


def ndcg_at_k(ranked_ids: list[int], gain: dict[int, float], k: int) -> float:
    """NDCG@k where the graded gain of a doc is its EXACT f32 score.

    The ideal ranking is the exact-f32 ranking, so an f32 run scores 1.0 by
    construction and the uint8 number reads directly as "fraction of the exact
    ranking's discounted gain retained".
    """
    dcg = sum(gain.get(d, 0.0) / math.log2(i + 2)
              for i, d in enumerate(ranked_ids[:k]))
    ideal = sorted(gain.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return float(dcg / idcg) if idcg > 0 else 0.0


# ─────────────────────────── qdrant local mode ───────────────────────────────

def _upsert(client, models, name, ptr, idx, val, datatype, batch=2000):
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(
        collection_name=name, vectors_config={},
        sparse_vectors_config={"splade": models.SparseVectorParams(
            index=models.SparseIndexParams(on_disk=True, datatype=datatype))})
    n = len(ptr) - 1
    points, t0 = [], time.perf_counter()
    for i in range(n):
        s, e = int(ptr[i]), int(ptr[i + 1])
        points.append(models.PointStruct(
            id=i, payload={},
            vector={"splade": models.SparseVector(
                indices=idx[s:e].astype(np.int64).tolist(),
                values=val[s:e].astype(np.float32).tolist())}))
        if len(points) >= batch:
            client.upsert(collection_name=name, points=points)
            points = []
    if points:
        client.upsert(collection_name=name, points=points)
    logger.info("upserted %d points into %s (datatype=%s) in %.0fs",
                n, name, datatype, time.perf_counter() - t0)
    return client.get_collection(name)


def _query_all(client, models, name, q_ptr, q_idx, q_val, k):
    ids, lats = [], []
    for i in range(len(q_ptr) - 1):
        s, e = int(q_ptr[i]), int(q_ptr[i + 1])
        qv = models.SparseVector(indices=q_idx[s:e].astype(np.int64).tolist(),
                                 values=q_val[s:e].astype(np.float32).tolist())
        t0 = time.perf_counter()
        res = client.query_points(name, query=qv, using="splade", limit=k)
        lats.append((time.perf_counter() - t0) * 1000.0)
        ids.append([int(p.id) for p in res.points])
    return ids, lats


# ──────────────────────────────── driver ─────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, default=50_000)
    ap.add_argument("--queries", type=int, default=50)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--rescore-depth", type=int, default=100)
    ap.add_argument("--global-scale", type=float, default=1.0 / 70.0,
                    help="BMP-style fixed scale (builder.QUANT_SCALE=70 -> 1/70)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--scratch", default=os.environ.get(
        "UINT8_SPARSE_SCRATCH", "/tmp/qdrant_uint8_sparse"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-qdrant", action="store_true",
                    help="quality/storage only; skip the local-mode collections")
    args = ap.parse_args()

    scratch = Path(args.scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    z = build_corpus(scratch / f"corpus_{args.docs}_{args.queries}.npz",
                     args.docs, args.queries, args.threads)
    d_ptr, d_idx, d_val = z["d_ptr"], z["d_idx"], z["d_val"]
    q_ptr, q_idx, q_val = z["q_ptr"], z["q_idx"], z["q_val"]
    n_docs, n_q = len(d_ptr) - 1, len(q_ptr) - 1
    nnz = int(d_val.size)
    logger.info("corpus: %d docs, %d nnz (%.1f nnz/doc), %d queries",
                n_docs, nnz, nnz / max(n_docs, 1), n_q)

    results: dict = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "date": "2026-09-25",
        "scale": "SMALL-SCALE (real SPLADE vectors, title-only, local mode)",
        "script": "scripts/archive/qdrant_uint8_sparse/eval_qdrant_uint8_sparse_small.py",
        "corpus": {
            "source": "data/thinclient_index/meta.sqlite titles (read-only) "
                      "encoded with models/splade_onnx_fused",
            "n_docs": n_docs, "n_queries": n_q, "nnz_total": nnz,
            "nnz_per_doc_mean": nnz / max(n_docs, 1),
            "nnz_per_doc_median": float(np.median(np.diff(d_ptr))),
            "value_mean": float(d_val.mean()), "value_max": float(d_val.max()),
            "value_p95": float(np.percentile(d_val, 95)),
            "caveat": "title-only SPLADE: ~73 nnz/doc vs ~120 for production "
                      "title+abstract vectors",
        },
        "variants": {},
    }

    # ── quantize every doc, both scale modes ──
    quant = {}
    for mode, gscale in (("per_vector_max", None), ("global", args.global_scale)):
        t0 = time.perf_counter()
        ptr_q = [0]
        idx_q, val_q, codes_q, scales = [], [], [], []
        abs_err_max, sq_err, n_vals, n_clipped = 0.0, 0.0, 0, 0
        for i in range(n_docs):
            s, e = int(d_ptr[i]), int(d_ptr[i + 1])
            raw = quantize_sparse(d_idx[s:e], d_val[s:e], mode=mode,
                                  global_scale=gscale, drop_zero_codes=False)
            _, approx = dequantize_sparse(raw)
            err = np.abs(d_val[s:e] - approx)
            abs_err_max = max(abs_err_max, float(err.max()) if err.size else 0.0)
            sq_err += float((err ** 2).sum())
            n_vals += (e - s)
            if mode == "global":
                n_clipped += int((np.rint(d_val[s:e] / np.float32(gscale)) > UINT8_MAX).sum())
            keep = raw.codes != 0
            di = raw.indices[keep]
            dv = approx[keep]
            codes_q.append(raw.codes[keep])
            scales.append(raw.scale)
            idx_q.append(di)
            val_q.append(dv)
            ptr_q.append(ptr_q[-1] + di.size)
        quant[mode] = {
            "ptr": np.asarray(ptr_q, np.int64),
            "idx": np.concatenate(idx_q) if idx_q else np.zeros(0, np.uint32),
            "val": np.concatenate(val_q) if val_q else np.zeros(0, np.float32),
            "nnz": int(ptr_q[-1]),
            "abs_err_max": abs_err_max,
            "rmse": math.sqrt(sq_err / max(n_vals, 1)),
            "clipped_values": n_clipped,
            "quantize_s": time.perf_counter() - t0,
            "scale_mean": float(np.mean(scales)),
        }
        logger.info("quantized mode=%s nnz %d -> %d, max|err| %.5f, rmse %.5f",
                    mode, nnz, quant[mode]["nnz"], abs_err_max, quant[mode]["rmse"])

    # ── exact f32 ground truth ──
    X = _csr(d_ptr, d_idx, d_val, n_docs)
    depth = args.rescore_depth
    exact_rank, exact_gain = [], []
    t0 = time.perf_counter()
    for i in range(n_q):
        s, e = int(q_ptr[i]), int(q_ptr[i + 1])
        qvec = np.zeros(BERT_VOCAB, np.float32)
        qvec[q_idx[s:e].astype(np.int64)] = q_val[s:e]
        sc = np.asarray(X.dot(qvec)).ravel()
        top = np.argsort(-sc, kind="stable")[:depth]
        exact_rank.append([int(t) for t in top])
        exact_gain.append({int(t): float(sc[t]) for t in top})
    logger.info("exact f32 ground truth for %d queries in %.1fs",
                n_q, time.perf_counter() - t0)

    # ── storage accounting ──
    f32_total = f32_sparse_bytes(nnz)
    for mode in quant:
        qn = quant[mode]["nnz"]
        u8_total = qn * 5 + 4 * n_docs
        results["variants"].setdefault(mode, {})["storage"] = {
            "f32_value_bytes": nnz * 4,
            "uint8_value_bytes": qn * 1,
            "value_shrink_x": (nnz * 4) / max(qn * 1, 1),
            "f32_total_bytes_with_u32_indices": f32_total,
            "uint8_total_bytes_with_u32_indices_and_scale": u8_total,
            "total_shrink_x": f32_total / max(u8_total, 1),
            "f32_bytes_per_doc": f32_total / max(n_docs, 1),
            "uint8_bytes_per_doc": u8_total / max(n_docs, 1),
            "nnz_kept": qn, "nnz_dropped_zero_code": nnz - qn,
        }
        results["variants"][mode]["quantization_error"] = {
            "abs_err_max": quant[mode]["abs_err_max"],
            "rmse": quant[mode]["rmse"],
            "clipped_values": quant[mode]["clipped_values"],
            "quantize_seconds": quant[mode]["quantize_s"],
        }

    # ── numpy-side ranking quality (engine independent) ──
    for mode in quant:
        Xq = _csr(quant[mode]["ptr"], quant[mode]["idx"], quant[mode]["val"], n_docs)
        ov10, ov100, ndcg, ndcg100, resc10, rel_err = [], [], [], [], [], []
        for i in range(n_q):
            s, e = int(q_ptr[i]), int(q_ptr[i + 1])
            qvec = np.zeros(BERT_VOCAB, np.float32)
            qvec[q_idx[s:e].astype(np.int64)] = q_val[s:e]
            sc = np.asarray(Xq.dot(qvec)).ravel()
            top = [int(t) for t in np.argsort(-sc, kind="stable")[:depth]]
            ov10.append(overlap_at_k(top, exact_rank[i], args.k))
            ov100.append(overlap_at_k(top, exact_rank[i], depth))
            ndcg.append(ndcg_at_k(top, exact_gain[i], args.k))
            ndcg100.append(ndcg_at_k(top, exact_gain[i], depth))
            exact_sc = np.asarray(X.dot(qvec)).ravel()
            resc = sorted(top, key=lambda d: -exact_sc[d])
            resc10.append(overlap_at_k(resc, exact_rank[i], args.k))
            den = np.abs(exact_sc[top])
            rel_err.append(float(np.mean(np.abs(sc[top] - exact_sc[top])
                                         / np.maximum(den, 1e-6))))
        results["variants"][mode]["quality_numpy"] = {
            "overlap_at_10": float(np.mean(ov10)),
            "overlap_at_100": float(np.mean(ov100)),
            "ndcg_at_10_proxy_vs_exact_f32": float(np.mean(ndcg)),
            "ndcg_at_100_proxy_vs_exact_f32": float(np.mean(ndcg100)),
            "overlap_at_10_after_exact_rescore_of_top100": float(np.mean(resc10)),
            "mean_relative_score_error": float(np.mean(rel_err)),
        }
        logger.info("mode=%s overlap@10 %.4f ndcg@10 %.4f rescored@10 %.4f",
                    mode, np.mean(ov10), np.mean(ndcg), np.mean(resc10))

    # ── qdrant local-mode end-to-end ──
    if not args.skip_qdrant:
        from qdrant_client import QdrantClient, models
        store = scratch / "qdrant_local"
        shutil.rmtree(store, ignore_errors=True)
        client = QdrantClient(path=str(store))
        info32 = _upsert(client, models, "splade_f32", d_ptr, d_idx, d_val,
                         models.Datatype.FLOAT32)
        qm = quant["per_vector_max"]
        info8 = _upsert(client, models, "splade_u8", qm["ptr"], qm["idx"],
                        qm["val"], models.Datatype.UINT8)
        ids32, lat32 = _query_all(client, models, "splade_f32",
                                  q_ptr, q_idx, q_val, depth)
        ids8, lat8 = _query_all(client, models, "splade_u8",
                                q_ptr, q_idx, q_val, depth)
        ov10 = [overlap_at_k(ids8[i], ids32[i], args.k) for i in range(n_q)]
        ov100 = [overlap_at_k(ids8[i], ids32[i], depth) for i in range(n_q)]
        gt10 = [overlap_at_k(ids32[i], exact_rank[i], args.k) for i in range(n_q)]
        results["qdrant_local_mode"] = {
            "note": "qdrant_client local mode IGNORES datatype (no datatype "
                    "handling exists in qdrant_client/local/); the uint8 "
                    "collection is fed dequantized code*scale values, which "
                    "reproduce a uint8 index's ranking exactly. Latency below "
                    "is a PYTHON brute-force scan, not the Rust engine.",
            "client_version": "1.18.0",
            "datatype_accepted_by_client": True,
            "points_f32": int(info32.points_count),
            "points_uint8": int(info8.points_count),
            "f32_collection_matches_numpy_exact_overlap_at_10": float(np.mean(gt10)),
            "overlap_at_10_uint8_vs_f32_collection": float(np.mean(ov10)),
            "overlap_at_100_uint8_vs_f32_collection": float(np.mean(ov100)),
            "latency_ms": {
                "f32_p50": float(np.percentile(lat32, 50)),
                "f32_p95": float(np.percentile(lat32, 95)),
                "uint8_p50": float(np.percentile(lat8, 50)),
                "uint8_p95": float(np.percentile(lat8, 95)),
            },
        }
        logger.info("qdrant local: overlap@10 u8 vs f32 %.4f | p50 f32 %.1fms "
                    "u8 %.1fms", np.mean(ov10), np.percentile(lat32, 50),
                    np.percentile(lat8, 50))
        client.close()
        shutil.rmtree(store, ignore_errors=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    logger.info("wrote %s", out)


if __name__ == "__main__":
    main()
