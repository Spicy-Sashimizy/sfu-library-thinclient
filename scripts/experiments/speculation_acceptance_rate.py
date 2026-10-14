#!/usr/bin/env python3
"""Gating measurement (a) + the raw pass for the gap split (step 2) of
docs/SPECULATIVE_RETRIEVAL_UPGRADES.md.

ONE index pass over the 120 natural-language topics of
data/eval_results/dense_ablation_qrels_20260817.json (`topics[*].natural`).
Each topic is run twice back to back: run 1 ("first", colder) and run 2
("repeat", warm). Each run replays the SERVED path exactly as
tools.search_academic_structured does it, with the live objects built by
lib.tools._get_federated_router() (same env, same feature flags):

    router.search(query, {}, top_k=_retrieval_top_k(10), force_source=LOCAL_RRF)
        -> retriever.search(mode="bm25f")  : leg + _hydrate(meta rows + abstracts)
        -> retriever.search(mode="splade") : leg + _hydrate
        -> federated_search._rrf_merge     : the served fusion (DOI-keyed)
    tools._cache_works(fused)
    tools._maybe_rerank(fused, query, 10)
        -> rerank_results (stage 1)  -> reranker._compute_semantic_scores (embedding)
        -> rerank_with_crossencoder  (CE, pool 20)
        -> rerank_with_lambdamart    (only if the flag is on)

Timers are attached by monkeypatching in this process only (instance
attributes on the retriever, module attributes on lib.tools /
lib.reranker / lib.federated_search). retriever.py is not edited. Leg ms are
read from the same `_record_leg` counters the serve query-log diffs, so
`total - (bm25f + splade)` here is the serve log's gap by construction.

Provenance: `ThinClientRetriever._rrf_fuse(legs, 20, with_provenance=True)`
(the static fusion `search_rrf_detailed` uses) is applied to the captured leg
lists - no second retrieval - and its top-20 ids are checked against the
served `_rrf_merge` output.

Why not call search_rrf_detailed directly: it would run the two legs a
second time per query (doubling index traffic on a 31 GB host serving a
118 GB mmap index) and it fuses with the retriever's id-keyed RRF instead of
the router's DOI-keyed one that serving uses. The captured-leg form gives
the identical per-leg rankings plus the served fused list in one pass.

Outputs:
  data/eval_results/speculation_pass_raw_<date>.jsonl        per (topic, run)
  data/eval_results/speculation_acceptance_rate_<date>.json  measurement (a)
Then run speculation_gap_split.py on the raw file for step 2.

Run:
  .venv/bin/python3 scripts/experiments/speculation_acceptance_rate.py
"""
from __future__ import annotations

import argparse
import json
import os
import statistics as st
import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
EVAL = REPO / "data/eval_results"
DATE = date.today().isoformat()
RAW = EVAL / f"speculation_pass_raw_{DATE}.jsonl"
OUT = EVAL / f"speculation_acceptance_rate_{DATE}.json"
LIMIT = 10
PROBE = "effects of social media use on adolescent mental health"


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return xs[i]


def dist(xs, bars=()):
    out = {"n": len(xs), "mean": round(st.fmean(xs), 4), "median": round(st.median(xs), 4),
           "p10": round(pct(xs, 10), 4), "p90": round(pct(xs, 90), 4),
           "min": round(min(xs), 4), "max": round(max(xs), 4)}
    for b in bars:
        out[f"frac_ge_{b}"] = round(sum(1 for x in xs if x >= b) / len(xs), 4)
    return out


class Timers:
    """Per-run accumulator the patched functions write into."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.cur_leg = None
        self.legs_docs = {}
        self.d = {"hydrate": {}, "meta_rows": {}, "abstracts": {}, "remote": {},
                  "remote_ids": {}, "remote_hits": {}, "search_wall": {},
                  "rrf_merge": 0.0, "cache_works": 0.0, "stage1_total": 0.0,
                  "stage1_embed": 0.0, "stage1_embed_calls": 0, "stage1_n_docs": 0,
                  "ce": 0.0, "ce_n_pairs": 0, "lambdamart": 0.0, "maybe_rerank": 0.0}


T = Timers()


def _add(key, ms):
    leg = T.cur_leg or "?"
    T.d[key][leg] = T.d[key].get(leg, 0.0) + ms


def install(retriever):
    import lib.federated_search as fs
    import lib.reranker as rr
    import lib.tools as tools

    orig_search = retriever.search
    orig_hydrate = retriever._hydrate
    orig_meta = retriever._meta_rows
    orig_abs = retriever.fetch_abstracts
    orig_remote = retriever._fetch_remote_abstracts

    def search(query, top_k=50, mode=None, filters=None):
        leg = "splade" if mode == "splade" else "bm25f"
        T.cur_leg = leg
        t0 = time.perf_counter()
        out = orig_search(query, top_k=top_k, mode=mode, filters=filters)
        T.d["search_wall"][leg] = (time.perf_counter() - t0) * 1000
        T.legs_docs[leg] = out
        T.cur_leg = None
        return out

    def hydrate(ranked, source):
        t0 = time.perf_counter()
        out = orig_hydrate(ranked, source)
        _add("hydrate", (time.perf_counter() - t0) * 1000)
        return out

    def meta_rows(ids):
        t0 = time.perf_counter()
        out = orig_meta(ids)
        _add("meta_rows", (time.perf_counter() - t0) * 1000)
        return out

    def fetch_abstracts(ids):
        t0 = time.perf_counter()
        out = orig_abs(ids)
        _add("abstracts", (time.perf_counter() - t0) * 1000)
        return out

    def remote(ids):
        t0 = time.perf_counter()
        out = orig_remote(ids)
        _add("remote", (time.perf_counter() - t0) * 1000)
        leg = T.cur_leg or "?"
        T.d["remote_ids"][leg] = T.d["remote_ids"].get(leg, 0) + len(ids)
        T.d["remote_hits"][leg] = T.d["remote_hits"].get(leg, 0) + len(out)
        return out

    retriever.search = search
    retriever._hydrate = hydrate
    retriever._meta_rows = meta_rows
    retriever.fetch_abstracts = fetch_abstracts
    retriever._fetch_remote_abstracts = remote

    orig_merge = fs._rrf_merge

    def rrf_merge(primary, secondary, top_k):
        t0 = time.perf_counter()
        out = orig_merge(primary, secondary, top_k)
        T.d["rrf_merge"] += (time.perf_counter() - t0) * 1000
        return out

    fs._rrf_merge = rrf_merge

    orig_sem = rr._compute_semantic_scores

    def sem(query, docs, model_path=None):
        t0 = time.perf_counter()
        out = orig_sem(query, docs, model_path)
        T.d["stage1_embed"] += (time.perf_counter() - t0) * 1000
        T.d["stage1_embed_calls"] += 1
        T.d["stage1_n_docs"] += len(docs)
        return out

    rr._compute_semantic_scores = sem

    orig_rr = tools.rerank_results
    orig_ce = tools.rerank_with_crossencoder
    # LambdaMART tier removed 2026-10-11; the wrapper is installed only if a build still has it
    orig_lm = getattr(tools, "rerank_with_lambdamart", None)
    orig_cw = tools._cache_works

    def rerank_results(*a, **k):
        t0 = time.perf_counter()
        out = orig_rr(*a, **k)
        T.d["stage1_total"] += (time.perf_counter() - t0) * 1000
        return out

    def ce(docs, query, limit):
        t0 = time.perf_counter()
        out = orig_ce(docs, query, limit)
        T.d["ce"] += (time.perf_counter() - t0) * 1000
        T.d["ce_n_pairs"] += min(len(docs), rr._CE_CANDIDATE_POOL)
        return out

    def lm(*a, **k):
        t0 = time.perf_counter()
        out = orig_lm(*a, **k)
        T.d["lambdamart"] += (time.perf_counter() - t0) * 1000
        return out

    def cache_works(works):
        t0 = time.perf_counter()
        orig_cw(works)
        T.d["cache_works"] += (time.perf_counter() - t0) * 1000

    tools.rerank_results = rerank_results
    tools.rerank_with_crossencoder = ce
    if orig_lm is not None:
        setattr(tools, "rerank_with_lambdamart", lm)
    tools._cache_works = cache_works


def run_once(router, retriever, query, fetch_k):
    """One served-path replay. Returns (record, fused_docs, final_docs)."""
    import lib.tools as tools
    from lib.federated_search import SearchSource
    from lib.thinclient import retriever as rmod

    T.reset()
    before = rmod.snapshot_leg_metrics()
    t0 = time.monotonic()
    fused = router.search(query, {}, top_k=fetch_k, force_source=SearchSource.LOCAL_RRF)
    t_router = (time.monotonic() - t0) * 1000
    final = []
    if fused:
        tools._cache_works(fused)
        t1 = time.perf_counter()
        final = tools._maybe_rerank(fused, query, LIMIT)
        T.d["maybe_rerank"] = (time.perf_counter() - t1) * 1000
    total = (time.monotonic() - t0) * 1000
    leg_ms = rmod.leg_metrics_delta(before)
    rec = {"leg_ms": {k: round(v, 2) for k, v in leg_ms.items()},
           "total_ms": round(total, 2), "router_ms": round(t_router, 2),
           "timers": json.loads(json.dumps(T.d, default=float))}
    return rec, fused, final


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-topics", type=int, default=0)
    args = ap.parse_args()

    import lib.tools as tools
    from lib.federated_search import detect_subject
    from lib.thinclient.retriever import ThinClientRetriever

    cfg = tools._get_config()
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
    install(retriever)

    from lib.federated_search import SearchSource
    t0 = time.perf_counter()
    probe_rec, _, _ = run_once(router, retriever, PROBE, fetch_k)
    probe_s = time.perf_counter() - t0
    b = [d["openalex_id"] for d in T.legs_docs.get("bm25f", [])]
    s = [d["openalex_id"] for d in T.legs_docs.get("splade", [])]
    probe_overlap = len(set(b) & set(s))
    if not s or probe_overlap >= len(b):
        print(f"SPLADE leg looks degraded (bm25f∩splade={probe_overlap}/{len(b)}); abort",
              file=sys.stderr)
        return 3
    run_once(router, retriever, PROBE, fetch_k)

    env_keys = sorted(k for k in os.environ if k.startswith("SFU_") and not any(
        w in k for w in ("KEY", "TOKEN", "AUTH", "USER_ID", "TUNNEL")))
    env = {k: os.environ[k] for k in env_keys}
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "unknown"

    topics = json.loads(TOPICS.read_text())["topics"]
    items = list(topics.items())
    if args.limit_topics:
        items = items[:args.limit_topics]

    RAW.write_text("")
    per_topic = []
    for i, (kw, t) in enumerate(items):
        q = t["natural"]
        route = router.route(q, {}, subject_hint=detect_subject(q))
        runs = []
        for run in (1, 2):
            rec, fused, final = run_once(router, retriever, q, fetch_k)
            bm = [d["openalex_id"] for d in T.legs_docs.get("bm25f", [])]
            sp = [d["openalex_id"] for d in T.legs_docs.get("splade", [])]
            fused_ids = [d.get("openalex_id") for d in fused]
            final_ids = [d.get("openalex_id") for d in final]
            prov = ThinClientRetriever._rrf_fuse(
                {"bm25f": T.legs_docs.get("bm25f", []), "splade": T.legs_docs.get("splade", [])},
                fetch_k, with_provenance=True)
            rec.update({"topic_key": kw, "query": q, "run": run, "route": route.value,
                        "bm25f_ids": bm, "splade_ids": sp, "fused_ids": fused_ids,
                        "final_ids": final_ids,
                        "fuse_prov": [[d["openalex_id"], d["rrf_legs"]] for d in prov],
                        "n_hydrated": len(bm) + len(sp),
                        "n_dup_hydrated": len(set(bm) & set(sp))})
            with RAW.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
            runs.append(rec)
        r = runs[1]
        bm, fu, fi = r["bm25f_ids"], r["fused_ids"], r["final_ids"]
        prov_ids = [p[0] for p in r["fuse_prov"]]
        legs_of = [tuple(sorted(p[1])) for p in r["fuse_prov"]]
        per_topic.append({
            "topic_key": kw, "query": q, "route_if_served": r["route"],
            "overlap20_bm25f_vs_fused": len(set(bm[:20]) & set(fu[:20])) / 20,
            "overlap10_bm25f_vs_postce": len(set(bm[:10]) & set(fi[:10])) / 10,
            "overlap10_fused_vs_postce": len(set(fu[:10]) & set(fi[:10])) / 10,
            "overlap10_bm25f_vs_fused": len(set(bm[:10]) & set(fu[:10])) / 10,
            "overlap20_bm25f_vs_splade": len(set(bm[:20]) & set(r["splade_ids"][:20])) / 20,
            "postce_top10_in_bm25f_top20": len(set(fi[:10]) & set(bm[:20])) / 10,
            "fused_prov_counts": {"both": legs_of.count(("bm25f", "splade")),
                                  "bm25f_only": legs_of.count(("bm25f",)),
                                  "splade_only": legs_of.count(("splade",))},
            "rrf_fuse_matches_served_merge": prov_ids == fu,
            "rrf_fuse_same_set_as_served_merge": set(prov_ids) == set(fu),
            "run1_vs_run2_fused_identical": runs[0]["fused_ids"] == fu,
            "run1_vs_run2_final_identical": runs[0]["final_ids"] == fi,
            "n_bm25f": len(bm), "n_fused": len(fu), "n_final": len(fi),
        })
        print(f"[{i+1}/{len(items)}] acc20={per_topic[-1]['overlap20_bm25f_vs_fused']:.2f} "
              f"ov10ce={per_topic[-1]['overlap10_bm25f_vs_postce']:.2f} "
              f"total1={runs[0]['total_ms']:.0f} total2={r['total_ms']:.0f}", flush=True)

    k = lambda name: [p[name] for p in per_topic]
    prov_tot = {c: sum(p["fused_prov_counts"][c] for p in per_topic)
                for c in ("both", "bm25f_only", "splade_only")}
    n_slots = sum(prov_tot.values())
    summary = {
        "what": "Gating measurement (a) of docs/SPECULATIVE_RETRIEVAL_UPGRADES.md: "
                "acceptance = |bm25f top-20 ∩ served fused top-20| / 20 (levers #1/#3) and "
                "|bm25f top-10 ∩ post-CE top-10| / 10 (lever #2), served path replayed offline.",
        "date": DATE,
        "script": "scripts/experiments/speculation_acceptance_rate.py",
        "raw": str(RAW.relative_to(REPO)),
        "topics_file": str(TOPICS.relative_to(REPO)),
        "query_field": "natural",
        "n_topics": len(per_topic),
        "primary_run": "run 2 (immediate repeat, warm); overlaps are deterministic - see run1_vs_run2 fields",
        "serving_config": {"features": feats, "env_non_secret": env,
                           "index_root": str(retriever.root),
                           "splade_backend": retriever._splade_backend,
                           "federation": retriever._seismic_federation_mode(),
                           "fetch_k": fetch_k, "limit": LIMIT, "torch_device": device,
                           "embedding_model_path": cfg.embedding_model_path,
                           "load_s": round(load_s, 1), "probe_first_s": round(probe_s, 1),
                           "probe_bm25f_splade_overlap20": probe_overlap},
        "acceptance_at20_bm25f_vs_fused": dist(k("overlap20_bm25f_vs_fused"), (0.5, 0.7)),
        "overlap_at10_bm25f_vs_postce": dist(k("overlap10_bm25f_vs_postce"), (0.5, 0.7)),
        "context": {
            "overlap_at10_bm25f_vs_fused_prece": dist(k("overlap10_bm25f_vs_fused"), (0.5, 0.7)),
            "overlap_at10_fused_vs_postce": dist(k("overlap10_fused_vs_postce"), (0.5, 0.7)),
            "overlap_at20_bm25f_vs_splade": dist(k("overlap20_bm25f_vs_splade"), (0.5,)),
            "postce_top10_covered_by_bm25f_top20": dist(k("postce_top10_in_bm25f_top20"), (0.5, 0.7, 1.0)),
        },
        "fused_top20_provenance": {"slots": n_slots, **prov_tot,
                                   "share": {c: round(v / n_slots, 4) for c, v in prov_tot.items()}},
        "checks": {
            "rrf_fuse_order_equals_served_merge": sum(k("rrf_fuse_matches_served_merge")),
            "rrf_fuse_set_equals_served_merge": sum(k("rrf_fuse_same_set_as_served_merge")),
            "run1_run2_fused_identical": sum(k("run1_vs_run2_fused_identical")),
            "run1_run2_final_identical": sum(k("run1_vs_run2_final_identical")),
            "routes_if_served": {r: k("route_if_served").count(r) for r in set(k("route_if_served"))},
        },
        "per_topic": per_topic,
    }
    OUT.write_text(json.dumps(summary, indent=1))
    print(json.dumps({x: summary[x] for x in ("acceptance_at20_bm25f_vs_fused",
                                             "overlap_at10_bm25f_vs_postce",
                                             "fused_top20_provenance", "checks")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
