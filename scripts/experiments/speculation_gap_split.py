#!/usr/bin/env python3
"""Step 2 of docs/SPECULATIVE_RETRIEVAL_UPGRADES.md: split the serve-log gap
(`total - (bm25f leg + splade leg)`) into its stages.

No index access: reads the per-(topic, run) raw records that
speculation_acceptance_rate.py wrote during its single served-path replay
(data/eval_results/speculation_pass_raw_<date>.jsonl). Run 2 (immediate
repeat) is the primary "warm" figure; run 1 is reported as "first".

Stages (all ms, per query):
  hydrate_bm25f / hydrate_splade  ThinClientRetriever._hydrate per leg
      of which meta_rows            meta.sqlite rows
      of which abstracts_local      fetch_abstracts minus the remote part
      of which remote               _fetch_remote_abstracts (OpenAlex)
  leg_residual                    search() wall minus recorded leg ms minus
                                  hydrate (query-log write, bookkeeping)
  rrf_merge                       federated_search._rrf_merge
  cache_works                     tools._cache_works
  stage1_embed                    reranker._compute_semantic_scores
  stage1_rest                     rerank_results minus the embedding
  ce                              rerank_with_crossencoder
  lambdamart                      only when the flag is on
  unattributed                    gap minus everything above (router
                                  bookkeeping, timer overhead)

Duplicate-hydrate: both legs hydrate their own top-k independently; the
number of ids present in both legs' lists is hydrated twice.

Run:
  .venv/bin/python3 scripts/experiments/speculation_gap_split.py [raw.jsonl]
"""
from __future__ import annotations

import json
import statistics as st
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "data/eval_results"
DATE = date.today().isoformat()


def pct(xs, p):
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return xs[i]


def summ(xs):
    return {"p50": round(pct(xs, 50), 1), "p95": round(pct(xs, 95), 1),
            "mean": round(st.fmean(xs), 1)}


def stages(r: dict) -> dict:
    t = r["timers"]
    leg = r["leg_ms"]
    out = {}
    for L in ("bm25f", "splade"):
        remote = t["remote"].get(L, 0.0)
        out[f"hydrate_{L}"] = t["hydrate"].get(L, 0.0)
        out[f"hydrate_{L}_meta_rows"] = t["meta_rows"].get(L, 0.0)
        out[f"hydrate_{L}_abstracts_local"] = t["abstracts"].get(L, 0.0) - remote
        out[f"hydrate_{L}_remote"] = remote
        out[f"leg_residual_{L}"] = (t["search_wall"].get(L, 0.0) - leg.get(L, 0.0)
                                    - t["hydrate"].get(L, 0.0))
    out["rrf_merge"] = t["rrf_merge"]
    out["cache_works"] = t["cache_works"]
    out["stage1_embed"] = t["stage1_embed"]
    out["stage1_rest"] = t["stage1_total"] - t["stage1_embed"]
    out["ce"] = t["ce"]
    out["lambdamart"] = t["lambdamart"]
    return out


TOP = ["hydrate_bm25f", "hydrate_splade", "leg_residual_bm25f", "leg_residual_splade",
       "rrf_merge", "cache_works", "stage1_embed", "stage1_rest", "ce", "lambdamart"]


def analyse(rows: list[dict]) -> dict:
    per = []
    for r in rows:
        legs = r["leg_ms"].get("bm25f", 0.0) + r["leg_ms"].get("splade", 0.0)
        gap = r["total_ms"] - legs
        s = stages(r)
        s["unattributed"] = gap - sum(s[k] for k in TOP)
        s["hydrate_total"] = s["hydrate_bm25f"] + s["hydrate_splade"]
        s["hydrate_remote_total"] = s["hydrate_bm25f_remote"] + s["hydrate_splade_remote"]
        s["gap"] = gap
        s["legs"] = legs
        s["total"] = r["total_ms"]
        s["leg_bm25f"] = r["leg_ms"].get("bm25f", 0.0)
        s["leg_splade"] = r["leg_ms"].get("splade", 0.0)
        s["n_hydrated"] = r["n_hydrated"]
        s["n_dup_hydrated"] = r["n_dup_hydrated"]
        s["remote_ids"] = sum(r["timers"]["remote_ids"].values())
        s["remote_hits"] = sum(r["timers"]["remote_hits"].values())
        per.append(s)
    keys = [k for k in per[0] if k not in ("n_hydrated", "n_dup_hydrated", "remote_ids",
                                             "remote_hits")]
    dist = {k: summ([p[k] for p in per]) for k in keys}
    gap_sum = sum(p["gap"] for p in per)
    share = {k: round(sum(p[k] for p in per) / gap_sum, 4)
             for k in TOP + ["unattributed", "hydrate_total", "hydrate_remote_total"]}
    share_p50 = {k: round(st.median([p[k] / p["gap"] for p in per if p["gap"] > 0]), 4)
                 for k in TOP + ["unattributed", "hydrate_total"]}
    n_h = sum(p["n_hydrated"] for p in per)
    n_d = sum(p["n_dup_hydrated"] for p in per)
    return {
        "n": len(per),
        "stage_ms": dist,
        "share_of_gap_aggregate": share,
        "share_of_gap_median_per_query": share_p50,
        "duplicate_hydrate": {
            "hydrated_ids_total": n_h, "hydrated_twice_total": n_d,
            "dup_share_of_hydrated": round(n_d / n_h, 4) if n_h else None,
            "dup_per_query": summ([p["n_dup_hydrated"] for p in per]),
            "queries_with_any_dup": sum(1 for p in per if p["n_dup_hydrated"] > 0),
        },
        "remote_abstracts": {
            "ids_requested_total": sum(p["remote_ids"] for p in per),
            "ids_returned_total": sum(p["remote_hits"] for p in per),
            "ids_requested_per_query": summ([p["remote_ids"] for p in per]),
        },
    }


def main() -> int:
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else EVAL / f"speculation_pass_raw_{DATE}.jsonl"
    rows = [json.loads(l) for l in raw.open() if l.strip()]
    out = {
        "what": "Step 2 of docs/SPECULATIVE_RETRIEVAL_UPGRADES.md: the serve-log gap "
                "(total - bm25f leg - splade leg) split into stages on the served path "
                "replayed offline, 120 natural-language topics, 2 back-to-back runs each.",
        "date": DATE,
        "script": "scripts/experiments/speculation_gap_split.py",
        "raw": str(raw.relative_to(REPO)) if raw.is_relative_to(REPO) else str(raw),
        "producer": "scripts/experiments/speculation_acceptance_rate.py",
        "warm_run2_primary": analyse([r for r in rows if r["run"] == 2]),
        "first_run1": analyse([r for r in rows if r["run"] == 1]),
    }
    dst = EVAL / f"speculation_gap_split_{DATE}.json"
    dst.write_text(json.dumps(out, indent=1))
    w = out["warm_run2_primary"]
    print(json.dumps({"stage_ms": w["stage_ms"], "share": w["share_of_gap_aggregate"],
                      "dup": w["duplicate_hydrate"], "remote": w["remote_abstracts"]}, indent=1))
    print("wrote", dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
