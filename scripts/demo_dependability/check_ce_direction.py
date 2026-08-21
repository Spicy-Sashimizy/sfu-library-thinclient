#!/usr/bin/env python3
"""Score-direction audit of the served cross-encoder (2026-08-19).

Why: synthetic probes showed models/sfu-cross-encoder-v1 (and its int8 ONNX
export, which is exported FROM that dir) ranking relevant docs BELOW irrelevant
ones — perfectly inverted — while models/sfu-cross-encoder-baseline and the
base cross-encoder/ms-marco-MiniLM-L-6-v2 rank correctly. This script settles
it at scale on the REAL serving distribution: the cached retrieval pools in
data/openalex_eval_cache.json (query + title/abstract candidates, the same
text construction rerank_with_crossencoder uses).

Method: per pool, Spearman rank-correlate v1's scores against the base CE's
(direction-correct reference, NDCG@10 0.6763 on the 120-query judged eval).
A healthy fine-tune correlates positively; a sign-flipped model correlates
negatively pool after pool.

Writes data/eval_results/ce_v1_inversion_check_<stamp>.json.

Usage: .venv/bin/python3 scripts/demo_dependability/check_ce_direction.py [--pools N]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "openalex_eval_cache.json"
OUT_DIR = REPO / "data" / "eval_results"


def _spearman(a: list[float], b: list[float]) -> float:
    """Spearman rho with average ranks (no scipy dependency)."""
    import numpy as np

    def avg_rank(x):
        x = np.asarray(x, dtype=np.float64)
        order = np.argsort(x)
        ranks = np.empty_like(x)
        ranks[order] = np.arange(len(x), dtype=np.float64)
        # average ties
        for v in np.unique(x):
            m = x == v
            if m.sum() > 1:
                ranks[m] = ranks[m].mean()
        return ranks

    ra, rb = avg_rank(a), avg_rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (ra.std() * rb.std()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pools", type=int, default=60, help="max pools to score")
    ap.add_argument("--docs-per-pool", type=int, default=20)
    args = ap.parse_args()

    import numpy as np  # noqa: F401  (used in _spearman)
    import sys
    sys.path.insert(0, str(REPO / "src"))
    import lib.reranker as reranker
    from sentence_transformers import CrossEncoder

    cache = json.loads(CACHE.read_text())
    pools = []
    seen = set()
    for key, docs in cache.items():
        q = key.split("::", 1)[-1]
        if q in seen or not isinstance(docs, list):
            continue
        cand = []
        for d in docs[: args.docs_per_pool]:
            title = d.get("title") or ""
            abstract = d.get("abstract") or ""
            text = f"{title} {abstract}".strip()
            if text:
                cand.append(text)
        if len(cand) >= 5:
            seen.add(q)
            pools.append((q, cand))
        if len(pools) >= args.pools:
            break

    v1 = reranker._OnnxCrossEncoder(reranker._ONNX_CE_DIR)
    base = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

    rhos = []
    t0 = time.perf_counter()
    for q, cand in pools:
        pairs = [(q, t) for t in cand]
        s_v1 = v1.predict(pairs).tolist()
        s_base = base.predict(pairs, show_progress_bar=False).tolist()
        rhos.append(_spearman(s_v1, s_base))
    elapsed = time.perf_counter() - t0

    # Junk-promotion audit: inject real docs from UNRELATED pools (near-certain
    # irrelevant, in-distribution text) and count how often each backend ranks
    # one into the top-5 of an 8-own + 4-injected pool. This is the failure
    # mode that matters in serving: a brittle CE promotes off-topic docs.
    import random
    rng = random.Random(42)
    inj_pools = [(q, c) for q, c in pools if len(c) >= 8][:40]

    def junk_rate(scorer):
        promoted = total = 0
        for i, (q, own) in enumerate(inj_pools):
            foreign = [rng.choice(inj_pools[j][1]) for j in
                       rng.sample([j for j in range(len(inj_pools)) if j != i], 4)]
            texts = own[:8] + foreign
            s = scorer([(q, t) for t in texts])
            order = sorted(range(len(texts)), key=lambda k: s[k], reverse=True)
            promoted += len(set(order[:5]) & set(range(8, len(texts))))
            total += 4
        return promoted, total

    v1_prom, inj_total = junk_rate(lambda p: v1.predict(p).tolist())
    base_prom, _ = junk_rate(lambda p: base.predict(p, show_progress_bar=False).tolist())

    # Serve-shape latency: one _CE_CANDIDATE_POOL-sized batch (20 pairs), the
    # exact call rerank_with_crossencoder makes per query.
    import statistics
    bench_pairs = [(pools[0][0], t) for t in (pools[0][1] * 4)[:20]]

    def bench(scorer, iters=15):
        scorer(bench_pairs)  # warmup
        lat = []
        for _ in range(iters):
            t1 = time.perf_counter()
            scorer(bench_pairs)
            lat.append((time.perf_counter() - t1) * 1000)
        return round(statistics.median(lat), 1)

    lat_v1 = bench(lambda p: v1.predict(p))
    lat_base = bench(lambda p: base.predict(p, show_progress_bar=False))
    torch_v1 = CrossEncoder(reranker._CROSS_ENCODER_MODEL)
    lat_torch_v1 = bench(lambda p: torch_v1.predict(p, show_progress_bar=False))
    result = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "what": "Spearman(v1 int8 ONNX scores, base ms-marco CE scores) per real retrieval pool",
        "v1_model": "models/sfu-cross-encoder-v1-onnx-int8 (exported from models/sfu-cross-encoder-v1)",
        "reference": "cross-encoder/ms-marco-MiniLM-L-6-v2 (direction-correct; judged NDCG@10 0.6763)",
        "pools_scored": len(rhos),
        "docs_per_pool_max": args.docs_per_pool,
        "spearman": {
            "mean": round(statistics.mean(rhos), 4),
            "median": round(statistics.median(rhos), 4),
            "min": round(min(rhos), 4),
            "max": round(max(rhos), 4),
            "frac_negative": round(sum(r < 0 for r in rhos) / len(rhos), 4),
        },
        "junk_promotion_top5": {
            "what": "injected cross-pool (irrelevant, real) docs ranked into top-5 of 8-own+4-injected pools",
            "v1_int8_onnx": {"promoted": v1_prom, "total": inj_total,
                             "rate": round(v1_prom / inj_total, 4)},
            "base_msmarco": {"promoted": base_prom, "total": inj_total,
                             "rate": round(base_prom / inj_total, 4)},
        },
        "serve_batch20_latency_p50_ms": {
            "v1_int8_onnx": lat_v1,
            "v1_torch": lat_torch_v1,
            "base_msmarco_torch": lat_base,
            "note": "batch of _CE_CANDIDATE_POOL=20 pairs, the exact serve call shape; "
                    "the export bench's 19x was per-pair batch=1 and does not transfer.",
        },
        "elapsed_s": round(elapsed, 1),
        "interpretation": "spearman strongly negative + frac_negative ~1.0 = sign inversion; "
                          "weakly positive = legitimate reordering. junk_promotion_top5 measures "
                          "off-topic robustness (lower is better).",
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out = OUT_DIR / f"ce_v1_inversion_check_{stamp}.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print(f"\n>> {out}")


if __name__ == "__main__":
    main()
