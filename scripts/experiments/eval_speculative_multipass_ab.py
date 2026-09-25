#!/usr/bin/env python3
"""Lever #1 (SFU_SEARCH_SPECULATIVE_RERANK) multi-pass A/B on the 120 topics.

docs/SPECULATIVE_RETRIEVAL_UPGRADES.md §6 step 4. Same replay as
scripts/experiments/eval_fixed_shape_parity.py (live objects from
``lib.tools._get_federated_router()``, serving env/flags, CUDA):

    router.search(q, {}, top_k=_retrieval_top_k(10), force_source=LOCAL_RRF)
    tools._cache_works(fused); tools._maybe_rerank(fused, q, 10)

Pass order: one warm-up pass (gate OFF, discarded), then OFF, ON, OFF, ON,
OFF, ON (interleaved so host drift hits both arms alike). Every pass is a
result-cache miss (this path never reads the result cache).

Pre-registered bars (§6 step 4, fixed before this run):
  * byte-parity: every ON pass's final list == the OFF final list, 120/120
  * cache-miss total p50 drop >= 0.8 x (acceptance 0.55 x step-2 overlappable
    ms) ~= 128 ms (§3b ceiling 0.16 s)
  * total p95 not worse than +5%
  * cache_hit / speculative counters untouched (asserted in unit tests; the
    WI-18 and result-cache counters are also snapshotted here)

Also reported per ON pass: speculative_rerank.counters() deltas (ce_hits,
embed_hits, candidates_drafted, drafts that never ran a CE batch =
drafts_started - draft_ce_batches, real_ce_waited), and the attributable
critical-path ms: main-thread stage-1 stage and CE stage p50, and the
``_maybe_rerank`` wall ms, per pass.

OpenAlex budget: remote abstracts go through a harness memo keyed on the id
list (``--remote-cache`` JSON from a previous run). By default a memo miss
makes NO remote call and returns {} (memoised, so both arms see the same
empty result); ``--allow-remote-calls`` lets misses spend the daily budget.

Run:  .venv/bin/python3 scripts/experiments/eval_speculative_multipass_ab.py \
          --remote-cache <memo.json> [--passes 3] [--limit-topics N]
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

_spec = importlib.util.spec_from_file_location(
    "eval_fixed_shape_parity", REPO / "scripts/experiments/eval_fixed_shape_parity.py")
fsp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fsp)

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
DATE = "2026-09-25"
OUT = REPO / f"data/eval_results/speculative_multipass_ab_{DATE}.json"
LIMIT = 10
BAR_P50_DROP_MS = 128.0
BAR_P95_WORSE_FRAC = 0.05


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--limit-topics", type=int, default=0)
    ap.add_argument("--remote-cache", required=True)
    ap.add_argument("--allow-remote-calls", action="store_true")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    os.environ.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)
    import lib.tools as tools
    from lib import speculative_rerank, speculation, result_cache
    from lib.federated_search import SearchSource

    feats = dict(tools._get_features())
    router = tools._get_federated_router()
    retriever = tools._get_thinclient_retriever()
    if retriever is None:
        print("search backend is not thinclient; abort", file=sys.stderr)
        return 2
    fetch_k = tools._retrieval_top_k(LIMIT)
    t0 = time.perf_counter()
    retriever._load()
    load_s = time.perf_counter() - t0
    probe = fsp.Probe()

    memo: dict = {}
    cache_path = Path(args.remote_cache)
    if cache_path.exists():
        for k, v in json.loads(cache_path.read_text()):
            memo[tuple(k)] = v
    rstats = {"preloaded_keys": len(memo), "memo_hits": 0, "misses": 0, "remote_calls": 0,
              "allow_remote_calls": args.allow_remote_calls}
    orig_remote = retriever._fetch_remote_abstracts

    def remote(id_list):
        key = tuple(id_list)
        if key in memo:
            rstats["memo_hits"] += 1
            return dict(memo[key])
        rstats["misses"] += 1
        if not args.allow_remote_calls:
            memo[key] = {}
            return {}
        rstats["remote_calls"] += 1
        out = orig_remote(id_list)
        memo[key] = dict(out)
        return out

    retriever._fetch_remote_abstracts = remote

    orig_mr = tools._maybe_rerank
    rr_ms = {"v": 0.0}

    def timed_mr(docs, q, limit):
        t = time.perf_counter()
        try:
            return orig_mr(docs, q, limit)
        finally:
            rr_ms["v"] = (time.perf_counter() - t) * 1000

    def serve(q):
        probe.reset()
        t0 = time.monotonic()
        fused = router.search(q, {}, top_k=fetch_k, force_source=SearchSource.LOCAL_RRF)
        t1 = time.monotonic()
        captured = fsp.dump(fused)
        final = []
        rr_ms["v"] = 0.0
        if fused:
            tools._cache_works(fused)
            final = timed_mr(fused, q, LIMIT)
        total = (time.monotonic() - t0) * 1000
        return {"fused": captured, "final": fsp.dump(final), "total_ms": total,
                "retrieval_ms": (t1 - t0) * 1000, "rerank_ms": rr_ms["v"],
                "ce_ms": probe.ce_ms, "emb_ms": probe.emb_ms}

    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        threads = torch.get_num_threads()
    except Exception:
        device, threads = "unknown", None

    topics = json.loads(TOPICS.read_text())["topics"]
    items = [t["natural"] for t in topics.values()]
    if args.limit_topics:
        items = items[:args.limit_topics]

    wi18_before = speculation.counters()
    cache_before = result_cache.counters()

    serve("effects of social media use on adolescent mental health")
    order = ["warmup"] + [arm for _ in range(args.passes) for arm in ("off", "on")]
    passes = []
    for pi, arm in enumerate(order):
        if arm == "on":
            os.environ["SFU_SEARCH_SPECULATIVE_RERANK"] = "1"
        else:
            os.environ.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)
        speculative_rerank.reset_for_test()
        rows = []
        for i, q in enumerate(items):
            r = serve(q)
            if arm == "on":
                for _ in range(500):
                    if not speculative_rerank._job_busy:
                        break
                    time.sleep(0.01)
            rows.append(r)
            print(f"[{pi}:{arm} {i+1}/{len(items)}] total={r['total_ms']:.0f} "
                  f"rerank={r['rerank_ms']:.0f} ms", flush=True)
        counters = speculative_rerank.counters()
        passes.append({"arm": arm, "rows": rows, "counters": counters})
    os.environ.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)
    cache_path.write_text(json.dumps([[list(k), v] for k, v in memo.items()]))

    wi18_after = speculation.counters()
    cache_after = result_cache.counters()
    ref = next(p for p in passes if p["arm"] == "off")["rows"]
    n = len(items)

    def pass_summary(p):
        rows = p["rows"]
        s = {"arm": p["arm"],
             "total_ms": fsp.summ([r["total_ms"] for r in rows]),
             "retrieval_ms": fsp.summ([r["retrieval_ms"] for r in rows]),
             "maybe_rerank_ms": fsp.summ([r["rerank_ms"] for r in rows]),
             "stage1_stage_ms": fsp.summ([r["emb_ms"] for r in rows]),
             "ce_stage_ms": fsp.summ([r["ce_ms"] for r in rows]),
             "final_identical_to_first_off": f"{sum(r['final'] == f['final'] for r, f in zip(rows, ref))}/{n}",
             "fused_identical_to_first_off": f"{sum(r['fused'] == f['fused'] for r, f in zip(rows, ref))}/{n}"}
        if p["arm"] == "on":
            c = p["counters"]
            drafted = c["candidates_drafted"] or 1
            s["counters"] = c
            s["reuse"] = {
                "ce_hits_over_candidates_drafted": round(c["ce_hits"] / drafted, 3),
                "stage1_hits_over_candidates_drafted": round(c["embed_hits"] / drafted, 3),
                "ce_hits": c["ce_hits"], "embed_hits": c["embed_hits"],
                "candidates_drafted": c["candidates_drafted"],
                "candidates_accepted": c["candidates_accepted"],
                "drafts_started": c["drafts_started"],
                "drafts_without_ce_batch": c["drafts_started"] - c["draft_ce_batches"],
                "draft_ce_early": c["draft_ce_early"],
                "draft_ce_covered": c["draft_ce_covered"],
                "abandoned": c["abandoned"],
                "real_ce_waited": c["real_ce_waited"],
            }
        return s

    summaries = [pass_summary(p) for p in passes]
    offs = [s for s in summaries if s["arm"] == "off"]
    ons = [s for s in summaries if s["arm"] == "on"]
    pooled = {}
    for arm in ("off", "on"):
        rows = [r for p in passes if p["arm"] == arm for r in p["rows"]]
        pooled[arm] = {k: fsp.summ([r[f] for r in rows]) for k, f in
                       (("total_ms", "total_ms"), ("retrieval_ms", "retrieval_ms"),
                        ("maybe_rerank_ms", "rerank_ms"), ("stage1_stage_ms", "emb_ms"),
                        ("ce_stage_ms", "ce_ms"))}
    per_topic_median = {}
    for arm in ("off", "on"):
        arm_passes = [p["rows"] for p in passes if p["arm"] == arm]
        med = lambda f: [sorted(rows[i][f] for rows in arm_passes)[len(arm_passes) // 2] for i in range(n)]
        per_topic_median[arm] = {"total_ms": fsp.summ(med("total_ms")),
                                 "maybe_rerank_ms": fsp.summ(med("rerank_ms"))}

    parity_all = all(s["final_identical_to_first_off"] == f"{n}/{n}" for s in summaries[1:])
    d = lambda k, stat: round(pooled["off"][k][stat] - pooled["on"][k][stat], 1)
    p50_drop = d("total_ms", "p50")
    p95_ratio = pooled["on"]["total_ms"]["p95"] / pooled["off"]["total_ms"]["p95"]
    out = {
        "what": "Lever #1 speculative rerank (early draft CE + per-candidate reuse over fixed-shape "
                "scoring): multi-pass A/B gate OFF vs ON, docs/SPECULATIVE_RETRIEVAL_UPGRADES.md §6 step 4.",
        "date": DATE,
        "script": "scripts/experiments/eval_speculative_multipass_ab.py",
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural", "n_topics": n,
        "pass_order": order,
        "config": {"features": feats, "fetch_k": fetch_k, "limit": LIMIT, "torch_device": device,
                   "torch_threads": threads, "load_s": round(load_s, 1),
                   "embedding_model_path": os.environ.get("SFU_EMBEDDING_MODEL_PATH"),
                   "force_source": "LOCAL_RRF", "remote_abstract_memo": rstats},
        "bars": {
            "byte_parity_every_pass_vs_first_off": parity_all,
            "cache_miss_p50_drop_ms_pooled": p50_drop,
            "cache_miss_p50_drop_bar_ms": BAR_P50_DROP_MS,
            "p50_bar_met": p50_drop >= BAR_P50_DROP_MS,
            "p95_on_over_off_pooled": round(p95_ratio, 4),
            "p95_bar_met": p95_ratio <= 1 + BAR_P95_WORSE_FRAC,
            "wi18_counters_unchanged": wi18_before == wi18_after,
            "result_cache_counters_unchanged": cache_before == cache_after,
        },
        "attributable_ms_pooled_p50_drop": {
            "stage1_stage": d("stage1_stage_ms", "p50"),
            "ce_stage": d("ce_stage_ms", "p50"),
            "maybe_rerank": d("maybe_rerank_ms", "p50"),
            "retrieval": d("retrieval_ms", "p50"),
        },
        "pooled": pooled,
        "per_topic_median_over_passes": per_topic_median,
        "passes": summaries,
        "note": "host: local WSL2 (31 GB, 16 cores), RTX 4070 Ti SUPER; only this run on "
                "data/thinclient_index, other agents idle-ish (not isolated)",
    }
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: out[k] for k in ("bars", "attributable_ms_pooled_p50_drop", "pooled")}, indent=1))
    for s in summaries:
        print(s["arm"], s["total_ms"]["p50"], s["maybe_rerank_ms"]["p50"], s.get("reuse"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
