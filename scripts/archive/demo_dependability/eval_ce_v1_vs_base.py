#!/usr/bin/env python3
# CLOSED DEAD 2026-09-25 — demo-dependability WI harness for the OCI deployment that was gone on 2026-09-25 (docs/deprecated/oci_demo/DEMO_DEPENDABILITY.md); evidence kept, bars live in source at pinned commits
"""Judged eval: sfu-cross-encoder-v1 vs base ms-marco CE on the SERVE path (2026-08-19).

Decides the open operator question from data/eval_results/
ce_v1_inversion_check_20260819_1920.json: v1 wins in-pool fine-grained
relevance (old 120-query eval, +0.064 nDCG@10) but promotes off-topic docs
5-6x more than base. Which CE should the OCI demo serve?

Method — mirrors serving exactly, on the FRESH 2026-08-18 judged set
(120 topics x 2 query forms, 25,919 judged pairs, judge claude-haiku-4-5):
  1. Pre-CE candidates: the SERVED 2-leg RRF (bm25f + splade, k=60, 1-based
     ranks — retriever._rrf_fuse convention) reconstructed from the pooling
     run's recorded per-leg top-50s (the recorded fused ranking is NOT used:
     it had the since-ablated dense leg ON).
  2. CE re-scores the top-_CE_CANDIDATE_POOL (20) over "title abstract" —
     the rerank_with_crossencoder text construction — and re-sorts.
  3. nDCG@10 per query form (gain 2^grade - 1, IDCG over the same 20
     candidates); unjudged candidates (should be ~none: pool = union of
     per-leg top-50s over both forms) get gain 0 and are counted.
  4. Arms: none (RRF order) / base ms-marco / v1. Paired deltas with a
     10k topic-level bootstrap (resample 120 topics; a topic contributes
     the mean of its 2 forms). Strata: keyword vs natural-language forms.

Torch backends only: the int8 ONNX export is order-faithful to v1 (measured),
so its quality is v1's.

Usage: .venv/bin/python3 scripts/archive/demo_dependability/eval_ce_v1_vs_base.py
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / "data" / "eval_results"
QRELS = EVAL / "dense_ablation_qrels_20260817.json"
POOL = EVAL / "dense_ablation_pool_20260817.json"
DOCS = EVAL / "dense_ablation_pool_docs_20260817.json"
RRF_K = 60
CE_POOL = 20
NDCG_K = 10
BOOT = 10_000


def rrf2(bm25f: list[str], splade: list[str]) -> list[str]:
    """The served 2-leg fuse: retriever._rrf_fuse with legs bm25f -> splade."""
    scores: dict[str, float] = {}
    for leg in (bm25f, splade):
        for rank, did in enumerate(leg, start=1):
            scores[did] = scores.get(did, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda d: scores[d], reverse=True)


def ndcg_at_k(gains_in_order: list[float], k: int) -> float:
    import math
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains_in_order[:k]))
    ideal = sorted(gains_in_order, reverse=True)
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal[:k]))
    return dcg / idcg if idcg > 0 else 0.0


def main() -> None:
    sys.path.insert(0, str(REPO / "src"))
    from sentence_transformers import CrossEncoder

    qrels = json.loads(QRELS.read_text())["topics"]
    pool = json.loads(POOL.read_text())["queries"]
    doc_text = json.loads(DOCS.read_text())

    gains = {jk: {d["openalex_id"]: d["gain"] for d in t["docs"]}
             for jk, t in qrels.items()}

    models = {
        "v1": CrossEncoder(str(REPO / "models" / "sfu-cross-encoder-v1")),
        "base": CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2"),
    }

    per_form: list[dict] = []
    unjudged_total = cand_total = 0
    t0 = time.perf_counter()
    for q in pool:
        jk = q["judge_key"]
        if jk not in gains:
            continue
        cands = rrf2(q["bm25f"], q["splade"])[:CE_POOL]
        texts = []
        for did in cands:
            d = doc_text.get(did, {})
            texts.append(f"{d.get('title') or ''} {d.get('abstract') or ''}".strip())
        g = gains[jk]
        unjudged_total += sum(1 for did in cands if did not in g)
        cand_total += len(cands)
        cand_gains = [g.get(did, 0) for did in cands]

        row = {"judge_key": jk, "query_type": q["query_type"],
               "none": ndcg_at_k(cand_gains, NDCG_K)}
        pairs = [(q["query"], t) for t in texts]
        for name, ce in models.items():
            scores = ce.predict(pairs, show_progress_bar=False).tolist()
            order = sorted(range(len(cands)), key=lambda i: scores[i], reverse=True)
            row[name] = ndcg_at_k([cand_gains[i] for i in order], NDCG_K)
        per_form.append(row)
    elapsed = time.perf_counter() - t0

    topics: dict[str, dict[str, list[float]]] = {}
    for row in per_form:
        t = topics.setdefault(row["judge_key"], {"none": [], "base": [], "v1": []})
        for arm in ("none", "base", "v1"):
            t[arm].append(row[arm])
    topic_means = {jk: {arm: statistics.mean(v[arm]) for arm in v}
                   for jk, v in topics.items()}
    tlist = list(topic_means.values())

    def boot_delta(arm_a: str, arm_b: str) -> dict:
        """arm_a - arm_b, topic-level paired bootstrap."""
        deltas = [t[arm_a] - t[arm_b] for t in tlist]
        rng = random.Random(0)
        n = len(deltas)
        means = []
        for _ in range(BOOT):
            means.append(statistics.mean(deltas[rng.randrange(n)] for _ in range(n)))
        means.sort()
        return {"mean": round(statistics.mean(deltas), 4),
                "ci95": [round(means[int(BOOT * 0.025)], 4),
                         round(means[int(BOOT * 0.975)], 4)],
                "topics": n}

    def stratum_means(qt: str) -> dict:
        rows = [r for r in per_form if r["query_type"] == qt]
        return {arm: round(statistics.mean(r[arm] for r in rows), 4)
                for arm in ("none", "base", "v1")} | {"n_forms": len(rows)}

    result = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "what": "serve-path CE rerank eval: 2-leg RRF(k=60) top-20 -> CE -> nDCG@10 "
                "(gain 2^grade-1, IDCG over the 20 candidates)",
        "judged_set": QRELS.name,
        "arms": {"none": "RRF order, no CE", "base": "cross-encoder/ms-marco-MiniLM-L-6-v2",
                 "v1": "models/sfu-cross-encoder-v1 (torch; int8 ONNX is order-faithful)"},
        "forms_evaluated": len(per_form),
        "topics": len(topic_means),
        "unjudged_candidates": {"count": unjudged_total, "of": cand_total,
                                "frac": round(unjudged_total / max(cand_total, 1), 4)},
        "ndcg10_mean": {arm: round(statistics.mean(r[arm] for r in per_form), 4)
                        for arm in ("none", "base", "v1")},
        "by_query_type": {"keyword": stratum_means("keyword"),
                          "natural": stratum_means("natural")},
        "paired_bootstrap_10k_topic_level": {
            "v1_minus_base": boot_delta("v1", "base"),
            "v1_minus_none": boot_delta("v1", "none"),
            "base_minus_none": boot_delta("base", "none"),
        },
        "elapsed_s": round(elapsed, 1),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out = EVAL / f"ce_v1_vs_base_judged_{stamp}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"\n>> {out}")


if __name__ == "__main__":
    main()
