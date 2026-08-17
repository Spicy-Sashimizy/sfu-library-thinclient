#!/usr/bin/env python3
"""How much of the standard eval set's ground truth is INSIDE the served dense pool?

The dense leg's recorded wins (`data/eval_results/dense_poc_eval.json`,
`pipeline_dense_comparison.json`) were measured with a 600k dense index built as
"judged docs (guaranteed) + random distractors"
(`scripts/experiments/dense_indexer_poc.py` §"Build the doc pool"), and the
SERVED index is built from that same pool
(`scripts/build_thinclient_index.py` DENSE_VECS = data/dense_compression/vectors_600k.npy).

So the served dense leg searches a haystack that was constructed to contain the
eval's answers, while BM25F/SPLADE search all 150M. This script measures the
size of that advantage, which is what decides whether the recorded deltas can be
read as production benefit (they cannot) and whether the standard query set can
host a keep/drop ablation at all (it cannot — see the held-out stratum count).

Cheap and safe to run: reads `dense/ids.json` (8.6 MB) + the judge cache
(0.4 MB). It does NOT open the usearch index, the rescore memmap, `meta.sqlite`,
or any SEISMIC shard, so it can run alongside a parity eval.

Run:
  .venv/bin/python3 scripts/experiments/dense_pool_contamination.py
Writes: data/eval_results/dense_pool_contamination_<YYYYMMDD>.json
"""
from __future__ import annotations

import collections
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "data/eval_results"

# Corpus size the lexical legs actually search (THIN_CLIENT_SWAP.md / the
# dense_compression_eval "full_scale_docs" field).
FULL_CORPUS_DOCS = 150_413_098
RELEVANT_GRADE = 2          # the threshold both dense evals used


def main() -> None:
    ids = set(json.loads((REPO / "data/thinclient_index/dense/ids.json").read_text()))
    cache = json.loads((EVAL / "llm_judge_cache.json").read_text())
    queries = json.loads((EVAL / "diverse_queries.json").read_text())

    relevant: dict[str, set[str]] = collections.defaultdict(set)
    judged: dict[str, set[str]] = collections.defaultdict(set)
    for key, grade in cache.items():
        q, _, doc = key.partition("||")
        judged[q].add(doc)
        if grade >= RELEVANT_GRADE:
            relevant[q].add(doc)

    # The 360 records are 120 judged topics + paraphrases that REUSE the topic's
    # judgments (`judge_key`), so dedup before counting ground truth.
    topics = sorted({q["judge_key"] for q in queries})

    n_rel = sum(len(relevant[t]) for t in topics)
    n_rel_in = sum(len(relevant[t] & ids) for t in topics)
    n_judged = sum(len(judged[t]) for t in topics)
    n_judged_in = sum(len(judged[t] & ids) for t in topics)

    # Stratification an honest ablation would need: topics whose relevant docs
    # are NOT in the pool are the only ones that measure production behavior.
    full_cov = [t for t in topics if relevant[t] and relevant[t] <= ids]
    partial = [t for t in topics
               if relevant[t] and (relevant[t] & ids) and not relevant[t] <= ids]
    held_out = [t for t in topics if relevant[t] and not (relevant[t] & ids)]
    unjudged = [t for t in topics if not relevant[t]]

    random_rate = len(ids) / FULL_CORPUS_DOCS
    observed_rate = n_rel_in / n_rel if n_rel else 0.0

    out = {
        "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "what": "ground-truth coverage of the SERVED dense pool (data/thinclient_index/dense/ids.json)",
        "inputs": {
            "dense_ids": "data/thinclient_index/dense/ids.json",
            "judge_cache": "data/eval_results/llm_judge_cache.json",
            "query_set": "data/eval_results/diverse_queries.json",
            "relevant_grade_threshold": RELEVANT_GRADE,
            "full_corpus_docs": FULL_CORPUS_DOCS,
        },
        "pool": {
            "dense_vectors": len(ids),
            "corpus_fraction": round(random_rate, 6),
        },
        "query_set": {
            "records": len(queries),
            "unique_judged_topics": len(topics),
        },
        "coverage": {
            "relevant_judged_docs": n_rel,
            "relevant_in_pool": n_rel_in,
            "relevant_in_pool_frac": round(observed_rate, 4),
            "all_judged_docs": n_judged,
            "all_judged_in_pool": n_judged_in,
            "all_judged_in_pool_frac": round(n_judged_in / n_judged, 4) if n_judged else 0.0,
        },
        "enrichment_vs_random_subset": round(observed_rate / random_rate, 1),
        "strata": {
            "fully_covered_topics": len(full_cov),
            "partially_covered_topics": len(partial),
            "held_out_topics_zero_relevant_in_pool": len(held_out),
            "topics_with_no_relevant_judged": len(unjudged),
        },
        "interpretation": [
            f"{observed_rate:.1%} of the eval set's relevant docs sit in the served dense "
            f"pool, vs {random_rate:.4%} for a random subset of the same size — "
            f"{observed_rate / random_rate:.0f}x enrichment, by construction.",
            "Therefore the recorded dense deltas (dense_poc_eval.json +0.2924 retrieval "
            "nDCG@10, pipeline_dense_comparison.json +0.119 post-rerank) are an UPPER "
            "bound on production benefit, not a lower bound. eval_pipeline.py's caveat "
            "('OPTIMISTIC / an upper bound') is the correct reading; eval_dense_poc.py's "
            "('a LOWER BOUND') is wrong for the deployed configuration.",
            f"{len(held_out)} topics have zero relevant docs in the pool, so the standard "
            "query set CANNOT provide a held-out stratum: a keep/drop ablation run on it "
            "would re-measure the oracle, not the leg. A fresh judged query set is "
            "required. See docs/DENSE_PARTITION_AND_ABLATION.md.",
        ],
    }

    dest = EVAL / f"dense_pool_contamination_{time.strftime('%Y%m%d')}.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
