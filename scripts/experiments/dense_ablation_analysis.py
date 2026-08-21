#!/usr/bin/env python3
"""Dense-leg ablation analysis — doc DENSE_PARTITION_AND_ABLATION.md §7.

Scores arm A (SFU_DENSE_LEG=0) vs arm B (dense on) under the AMENDED
(2026-08-18, Option 2) decision rule:

  KEEP iff  (1) Δ_all = mean_topic(B−A) post-rerank nDCG@10 over ALL 120
                topics ≥ +0.02 with the paired-bootstrap 95% CI excluding 0
       AND  (2) dose-response: Δ on the low-coverage topics (dense_pool_coverage
                ≤ 0.10) has a positive point estimate.

Per-topic score = mean over the topic's two query forms (keyword + natural),
which share one gradebook (judge_key). Gains are 2^grade − 1 as recorded in the
qrels; the ideal ranking for nDCG comes from the topic's full judged pool.

Usage:
  .venv/bin/python3 scripts/experiments/dense_ablation_analysis.py \
      --arm-a data/eval_results/dense_ablation_A_nodense_20260818.json \
      --arm-b data/eval_results/dense_ablation_B_dense_20260818.json \
      --qrels data/eval_results/dense_ablation_qrels_20260817.json \
      --out   data/eval_results/dense_ablation_analysis_20260818.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

BANDS = [
    ("c == 0", lambda c: c == 0),
    ("0 < c <= 0.05", lambda c: 0 < c <= 0.05),
    ("0.05 < c <= 0.10", lambda c: 0.05 < c <= 0.10),
    ("0.10 < c <= 0.25", lambda c: 0.10 < c <= 0.25),
    ("0.25 < c <= 0.50", lambda c: 0.25 < c <= 0.50),
]
N_BOOT = 10_000
SEED = 20260818


def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at(ranking, gain_by_id, ideal_gains, k=10):
    got = dcg([gain_by_id.get(d, 0) for d in ranking[:k]])
    ideal = dcg(ideal_gains[:k])
    return got / ideal if ideal > 0 else 0.0


def recall_at(ranking, relevant_ids, k=50):
    if not relevant_ids:
        return 0.0
    return len(set(ranking[:k]) & relevant_ids) / len(relevant_ids)


def load_arm(path):
    d = json.load(open(path))
    by_topic = defaultdict(dict)
    for q in d["queries"]:
        by_topic[q["judge_key"]][q["query_type"]] = q
    return d, by_topic


def score_arm(by_topic, topics):
    """per-topic dict: final/retrieval nDCG@10, recall@50, unjudged@10 count."""
    out = {}
    for key, t in topics.items():
        gain = {doc["openalex_id"]: doc["gain"] for doc in t["docs"]}
        judged = set(gain)
        relevant = {d["openalex_id"] for d in t["docs"] if d["relevant"]}
        ideal = sorted(gain.values(), reverse=True)
        forms = by_topic[key]
        per_form = []
        for qt in ("keyword", "natural"):
            q = forms[qt]
            per_form.append({
                "final_ndcg10": ndcg_at(q["final"], gain, ideal, 10),
                "retrieval_ndcg10": ndcg_at(q["rrf"], gain, ideal, 10),
                "recall50": recall_at(q["rrf"], relevant, 50),
                "unjudged_at10": sum(1 for d in q["final"][:10] if d not in judged),
            })
        out[key] = {m: (per_form[0][m] + per_form[1][m]) / 2
                    for m in per_form[0]}
    return out


def paired_bootstrap(deltas, n_boot=N_BOOT, seed=SEED):
    rng = random.Random(seed)
    n = len(deltas)
    point = sum(deltas) / n
    means = []
    for _ in range(n_boot):
        s = sum(deltas[rng.randrange(n)] for _ in range(n))
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[min(int(0.975 * n_boot), n_boot - 1)]
    return {"n_topics": n, "delta": point, "ci95": [lo, hi],
            "ci_excludes_zero": lo > 0 or hi < 0}


def dense_vote_share(arm_by_topic, topics):
    """fraction of final top-10 whose only contributing RRF leg was dense."""
    only_dense = total = 0
    for key in topics:
        for q in arm_by_topic[key].values():
            legs_by_doc = dict(zip(q["rrf"], q["rrf_legs"]))
            for d in q["final"][:10]:
                total += 1
                legs = legs_by_doc.get(d)
                if legs is not None and set(legs) == {"dense"}:
                    only_dense += 1
    return only_dense / total if total else 0.0


def mean_overlap(arm_by_topic, topics, leg_a, leg_b, k=50):
    vals = []
    for key in topics:
        for q in arm_by_topic[key].values():
            la, lb = q.get(leg_a), q.get(leg_b)
            if la and lb:
                vals.append(len(set(la[:k]) & set(lb[:k])))
    return sum(vals) / len(vals) if vals else None


def pctl(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    return s[min(int(p / 100 * len(s)), len(s) - 1)]


def latency_summary(arm_raw):
    out = {}
    keys = set()
    for q in arm_raw["queries"]:
        keys.update(k for k in q if k.startswith("lat_"))
    for k in sorted(keys):
        vals = [q[k] for q in arm_raw["queries"] if k in q and q[k] is not None]
        out[k] = {"p50_ms": pctl(vals, 50), "p95_ms": pctl(vals, 95), "n": len(vals)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm-a", required=True)
    ap.add_argument("--arm-b", required=True)
    ap.add_argument("--qrels", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    qrels = json.load(open(args.qrels))
    topics = qrels["topics"]
    raw_a, by_a = load_arm(args.arm_a)
    raw_b, by_b = load_arm(args.arm_b)
    for key in topics:
        for src, name in ((by_a, "A"), (by_b, "B")):
            missing = {"keyword", "natural"} - set(src.get(key, {}))
            if missing:
                raise SystemExit(f"arm {name} missing forms {missing} for topic {key!r}")

    scores_a = score_arm(by_a, topics)
    scores_b = score_arm(by_b, topics)
    cov = {k: topics[k]["dense_pool_coverage"] for k in topics}
    keys = sorted(topics)

    def deltas(metric, subset):
        return [scores_b[k][metric] - scores_a[k][metric] for k in subset]

    primary = paired_bootstrap(deltas("final_ndcg10", keys))
    lowcov_keys = [k for k in keys if cov[k] <= 0.10]
    lowcov = paired_bootstrap(deltas("final_ndcg10", lowcov_keys))
    strict4_keys = [k for k in keys if cov[k] == 0]
    strict4 = paired_bootstrap(deltas("final_ndcg10", strict4_keys))

    bands = {}
    for label, pred in BANDS:
        sub = [k for k in keys if pred(cov[k])]
        if sub:
            bands[label] = paired_bootstrap(deltas("final_ndcg10", sub))

    secondary = {
        m: paired_bootstrap(deltas(m, keys))
        for m in ("retrieval_ndcg10", "recall50")
    }

    keep = (primary["delta"] >= 0.02 and primary["ci_excludes_zero"]
            and primary["delta"] > 0 and lowcov["delta"] > 0)
    if primary["delta"] >= 0.02 and not primary["ci_excludes_zero"]:
        verdict = "UNDERPOWERED — extend the query set; do not round up to keep"
    elif keep:
        verdict = "KEEP"
    else:
        verdict = "DROP from the payload"

    result = {
        "what": "dense-leg ablation analysis under the 2026-08-18 amended rule (Option 2, dose-response)",
        "date": "2026-08-18",
        "inputs": {"arm_a": args.arm_a, "arm_b": args.arm_b, "qrels": args.qrels},
        "bootstrap": {"resamples": N_BOOT, "seed": SEED, "paired": "over topics; per-topic = mean of the 2 forms"},
        "arm_means": {
            arm: {m: sum(s[k][m] for k in keys) / len(keys)
                  for m in ("final_ndcg10", "retrieval_ndcg10", "recall50", "unjudged_at10")}
            for arm, s in (("A_nodense", scores_a), ("B_dense", scores_b))
        },
        "primary_all_topics_final_ndcg10": primary,
        "dose_response_check_lowcov_c_le_0.10": lowcov,
        "strict4_heldout_as_originally_preregistered": strict4,
        "delta_by_coverage_band": bands,
        "secondary": secondary,
        "dense_vote_share_at10_armB": dense_vote_share(by_b, topics),
        "overlap_at50_armB": {
            "dense∩bm25f": mean_overlap(by_b, topics, "dense", "bm25f"),
            "dense∩splade": mean_overlap(by_b, topics, "dense", "splade"),
            "bm25f∩splade": mean_overlap(by_b, topics, "bm25f", "splade"),
        },
        "latency": {"A_nodense": latency_summary(raw_a), "B_dense": latency_summary(raw_b)},
        "decision_rule": "KEEP iff Δ_all ≥ +0.02 with 95% CI excluding 0 AND low-coverage (c≤0.10) point estimate > 0",
        "verdict": verdict,
        "per_topic": {
            k: {"coverage": cov[k],
                "A_final_ndcg10": scores_a[k]["final_ndcg10"],
                "B_final_ndcg10": scores_b[k]["final_ndcg10"]}
            for k in keys
        },
    }
    Path(args.out).write_text(json.dumps(result, indent=1, ensure_ascii=False))

    p = primary
    print(f"Δ_all final nDCG@10 (B−A, {p['n_topics']} topics): {p['delta']:+.4f}  "
          f"95% CI [{p['ci95'][0]:+.4f}, {p['ci95'][1]:+.4f}]  excludes 0: {p['ci_excludes_zero']}")
    print(f"low-coverage c≤0.10 ({lowcov['n_topics']} topics): Δ {lowcov['delta']:+.4f}  "
          f"CI [{lowcov['ci95'][0]:+.4f}, {lowcov['ci95'][1]:+.4f}]")
    print(f"strict-4 held-out: Δ {strict4['delta']:+.4f}  CI [{strict4['ci95'][0]:+.4f}, {strict4['ci95'][1]:+.4f}]")
    for label, b in bands.items():
        print(f"  band {label:18s} n={b['n_topics']:3d}  Δ {b['delta']:+.4f}  CI [{b['ci95'][0]:+.4f}, {b['ci95'][1]:+.4f}]")
    print(f"dense_vote_share@10 (arm B): {result['dense_vote_share_at10_armB']:.4f}")
    print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
