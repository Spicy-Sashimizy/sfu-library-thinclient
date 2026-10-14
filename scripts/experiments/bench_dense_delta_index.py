#!/usr/bin/env python3
"""Microbenchmark: RAM Hamming brute force vs a mutable usearch b1 index as the
dense warm-cache delta search engine.

Why: docs/DENSE_WARMCACHE_RESEARCH.md v1 chose brute force ("sub-ms below ~200k
docs") and deferred the usearch delta index to v2 without measuring where the
crossover actually is. This script measures it at 10k / 100k / 500k synthetic
delta rows (500k = DEFAULT_MAX_DOCS, the hard doc cap).

Both paths run through the real serving code: `DenseWarmCache.search` with the
arrays pre-filled (the SQLite/encoder path is bypassed — it is not what is
being measured). The usearch path is enabled the way serving enables it,
through SFU_DENSE_DELTA_USEARCH_MIN.

Synthetic data only: random unit vectors with planted neighbourhoods, so this
never touches data/thinclient_index.

Usage:
  .venv/bin/python3 scripts/experiments/bench_dense_delta_index.py \
      [--sizes 10000 100000 500000] [--queries 50] [--fetch 200]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESULTS_DIR = REPO / "data/eval_results"
DIM = 384


def _corpus(n: int, n_q: int, seed: int = 17):
    """n random unit vectors; each query owns a planted 20-doc neighbourhood."""
    import numpy as np

    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, DIM)).astype(np.float32)
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    Q = rng.standard_normal((n_q, DIM)).astype(np.float32)
    Q /= np.linalg.norm(Q, axis=1, keepdims=True)
    for qi in range(n_q):
        rows = rng.choice(n, size=20, replace=False)
        for r, row in enumerate(rows):
            w = 0.95 - 0.02 * r
            v = w * Q[qi] + np.sqrt(1 - w * w) * X[row]
            X[row] = v / np.linalg.norm(v)
    return X, Q


def _fill(cache, X, headroom: int = 1000):
    """Pre-fill the RAM arrays (with headroom, so the incremental-add timing
    never pays for an array doubling) and bypass SQLite/the encoder."""
    import numpy as np

    n = X.shape[0]
    int8 = np.clip(np.round(X * 127.0), -127, 127).astype(np.int8)
    cache._int8 = np.zeros((n + headroom, DIM), dtype=np.int8)
    cache._int8[:n] = int8
    cache._codes = np.zeros((n + headroom, DIM // 8), dtype=np.uint8)
    cache._codes[:n] = np.packbits(int8 > 0, axis=1)
    cache._ids = [f"D{i}" for i in range(n)]
    cache._n = n
    return int8


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+",
                    default=[10_000, 100_000, 500_000])
    ap.add_argument("--queries", type=int, default=50)
    ap.add_argument("--fetch", type=int, default=200)
    ap.add_argument("--topk", type=int, default=10)
    ap.add_argument("--warmup", type=int, default=3)
    args = ap.parse_args()

    import sys

    sys.path.insert(0, str(REPO / "source"))
    import numpy as np

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in args.sizes:
        print(f">> n={n:,} building synthetic corpus ...")
        X, Q = _corpus(n, args.queries)

        os.environ.pop("SFU_DENSE_DELTA_USEARCH_MIN", None)
        import lib.thinclient.dense_cache as dc
        tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"dense_bench_{n}"
        brute = dc.DenseWarmCache(tmp / "brute", seed_ids=[], model_path="",
                                  encoder=lambda t: np.zeros((len(t), DIM),
                                                             dtype=np.float32))
        _fill(brute, X)

        os.environ["SFU_DENSE_DELTA_USEARCH_MIN"] = "1"
        ann = dc.DenseWarmCache(tmp / "ann", seed_ids=[], model_path="",
                                encoder=lambda t: np.zeros((len(t), DIM),
                                                           dtype=np.float32))
        _fill(ann, X)
        t0 = time.perf_counter()
        ann._ann_sync_locked()
        build_s = time.perf_counter() - t0
        assert ann.info()["delta_engine"] == "usearch"
        print(f"   usearch bulk add: {build_s:.2f} s")

        t0 = time.perf_counter()
        extra = np.clip(np.round(X[:1000] * 127.0), -127, 127).astype(np.int8)
        for i in range(1000):
            ann._append_row(f"X{i}", extra[i])
        incr_us = (time.perf_counter() - t0) / 1000 * 1e6

        def bench(cache):
            lat = []
            out = []
            for i in range(args.warmup):
                cache.search(np.packbits(Q[i % len(Q)] > 0), Q[i % len(Q)],
                             args.fetch)
            for qi in range(len(Q)):
                qb = np.packbits(Q[qi] > 0)
                t = time.perf_counter()
                hits = cache.search(qb, Q[qi], args.fetch)
                lat.append((time.perf_counter() - t) * 1000.0)
                out.append([h[0] for h in hits[:args.topk]])
            lat.sort()
            return {"p50_ms": round(statistics.median(lat), 3),
                    "p95_ms": round(lat[int(len(lat) * 0.95)], 3),
                    "mean_ms": round(statistics.mean(lat), 3)}, out

        b_stats, b_hits = bench(brute)
        a_stats, a_hits = bench(ann)
        agree = statistics.mean(
            len(set(a) & set(b)) / max(1, len(b))
            for a, b in zip(a_hits, b_hits))
        exact_hits = []
        i8 = brute._int8[:n].astype(np.float32) / 127.0
        for qi in range(len(Q)):
            s = i8 @ Q[qi]
            exact_hits.append([f"D{j}" for j in np.argsort(-s)[:args.topk]])
        rec_b = statistics.mean(len(set(b) & set(e)) / args.topk
                                for b, e in zip(b_hits, exact_hits))
        rec_a = statistics.mean(len(set(a) & set(e)) / args.topk
                                for a, e in zip(a_hits, exact_hits))

        row = {"n": n, "fetch": args.fetch, "top_k": args.topk,
               "queries": len(Q),
               "brute_force": b_stats, "usearch": a_stats,
               "speedup_p50": round(b_stats["p50_ms"] / a_stats["p50_ms"], 2),
               "usearch_build_s": round(build_s, 3),
               "usearch_incremental_add_us_per_row": round(incr_us, 1),
               "topk_agreement_usearch_vs_brute": round(agree, 4),
               "recall_at_k_vs_exact": {"brute_force": round(rec_b, 4),
                                        "usearch": round(rec_a, 4)}}
        print("   " + json.dumps(row))
        rows.append(row)
        brute.close()
        ann.close()
        del brute, ann, X, Q, i8

    result = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "what": "dense warm-cache delta search: RAM Hamming brute force vs "
                "mutable usearch b1 index, synthetic vectors",
        "host": {"cpu_count": os.cpu_count()},
        "dim": DIM,
        "code": "source/lib/thinclient/dense_cache.py (DenseWarmCache.search)",
        "gate": "SFU_DENSE_DELTA_USEARCH_MIN (default 0 = brute force)",
        "sizes": rows,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    path = RESULTS_DIR / f"dense_delta_index_bench_{stamp}.json"
    path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"\n>> results -> {path}")


if __name__ == "__main__":
    main()
