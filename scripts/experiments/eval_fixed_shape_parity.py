#!/usr/bin/env python3
"""Fixed-shape scoring + per-candidate speculative reuse: 120-topic ranking parity.

Owner decision 2026-09-25 (docs/SPECULATIVE_RETRIEVAL_UPGRADES.md §7 item 1):
the stage-1 embedder and the cross-encoder score in fixed (batch, seq_len)
tensors on both paths so lever #1 can reuse drafted per-candidate scores.
This harness is the index pass that checks the consequences.

Per topic (the 120 ``topics[*].natural`` queries of
data/eval_results/dense_ablation_qrels_20260817.json), with the live objects
from ``lib.tools._get_federated_router()`` (same env and flags as serving;
the container sets SFU_FEATURE_RRF_ENABLED=true), replaying the sequence of
``tools.search_academic_structured`` without its query-log side effects:

    router.search(q, {}, top_k=_retrieval_top_k(10), force_source=LOCAL_RRF)
    tools._cache_works(fused); tools._maybe_rerank(fused, q, 10)

Passes, in order:
  warm  gate OFF, new scoring (page-cache / model warm-up; also a determinism
        check against pass OFF)
  OFF   gate OFF, new fixed-shape scoring              -> arm (ii)
  ON    gate ON (SFU_SEARCH_SPECULATIVE_RERANK=1)      -> arm (iii)
Then, with no index access, on the fused list captured in pass OFF:
  OLD   the pre-change scoring (arm (i)): ``lib.embedding.compute_similarity``
        replaced by the version at git BASE (``git show BASE:source/lib/embedding.py``, or ``BASE:src/lib/embedding.py`` for a base before 2026-10-13,
        executed as a separate module) and ``lib.reranker._ce_score_pairs``
        replaced by BASE's one-line call ``ce.predict(pairs).tolist()`` —
        the only two scoring lines that changed in lib/reranker.py.
  NEW   the new scoring on the same captured list (must reproduce pass OFF).

Remote abstracts (keyed OpenAlexClient since 6dab7e6f) are memoised per id
list inside this process: the warm pass pays the calls, OFF/ON reuse them.

Bars: (ii) vs (iii) byte-identical on all topics (hard); (i) vs (ii) zero
top-10 order changes (reported with max score delta; a reorder is a finding).
Also records ``speculative_rerank.counters()`` over pass ON and total-ms
p50/p95 for passes OFF and ON (every pass is a result-cache miss: this path
never reads the result cache), and stage-1 / CE ms for OLD vs NEW scoring on
identical inputs.

Run:  .venv/bin/python3 scripts/experiments/eval_fixed_shape_parity.py [--base 7fe22228]
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
import statistics as st
import subprocess
import sys
import threading
import time
import types
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
DATE = date.today().isoformat()
OUT = REPO / f"data/eval_results/fixed_shape_parity_{DATE}.json"
LIMIT = 10


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))]


def summ(xs):
    return {"n": len(xs), "p50": round(pct(xs, 50), 1), "p95": round(pct(xs, 95), 1),
            "mean": round(st.fmean(xs), 1)}


def dump(docs):
    return json.dumps(docs, sort_keys=True, default=str)


def ids(docs):
    return [d.get("openalex_id") or d.get("doi") or d.get("title") for d in docs]


def load_base_embedding(base: str):
    rel = "source/lib/embedding.py"
    if subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{base}:{rel}"], capture_output=True).returncode != 0:
        rel = "src/lib/embedding.py"
    src = subprocess.check_output(["git", "-C", str(REPO), "show", f"{base}:{rel}"], text=True)
    mod = types.ModuleType("base_embedding")
    mod.__file__ = str(REPO / "source/lib/embedding.py")
    exec(compile(src, f"{base}:{rel}", "exec"), mod.__dict__)
    return mod


class Probe:
    """Main-thread capture of stage-1 scores, CE pairs/scores and stage ms.

    Draft-thread calls (gate ON) are ignored, so ms and scores are those of
    the request's own critical path.
    """

    def __init__(self):
        import lib.reranker as rr
        import lib.tools as tools
        self.reset()
        self.ce_impl = rr._ce_score_pairs
        orig_sem = rr._compute_semantic_scores
        orig_stage1 = tools.rerank_results
        orig_ce_stage = tools.rerank_with_crossencoder
        probe = self

        def on_main():
            return threading.current_thread() is threading.main_thread()

        def ce_scores(ce, pairs):
            out = probe.ce_impl(ce, pairs)
            if on_main():
                probe.ce_pairs.extend(pairs)
                probe.ce_out.extend(out)
            return out

        def sem(query, docs, model_path=None):
            out = orig_sem(query, docs, model_path)
            if on_main():
                probe.emb_out = list(out or [])
            return out

        def stage1(*a, **kw):
            t0 = time.perf_counter()
            out = orig_stage1(*a, **kw)
            if on_main():
                probe.emb_ms += (time.perf_counter() - t0) * 1000
            return out

        def ce_stage(docs, query, limit):
            t0 = time.perf_counter()
            out = orig_ce_stage(docs, query, limit)
            if on_main():
                probe.ce_ms += (time.perf_counter() - t0) * 1000
            return out

        rr._ce_score_pairs = ce_scores
        rr._compute_semantic_scores = sem
        tools.rerank_results = stage1
        tools.rerank_with_crossencoder = ce_stage

    def reset(self):
        self.ce_ms = 0.0
        self.emb_ms = 0.0
        self.ce_pairs = []
        self.ce_out = []
        self.emb_out = []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="7fe22228", help="commit whose embedding.py / CE call is arm (i)")
    ap.add_argument("--limit-topics", type=int, default=0)
    ap.add_argument("--pairs-out", default="", help="JSONL of the real CE (query, text) pairs (pass OFF)")
    ap.add_argument("--remote-cache", default="",
                    help="JSON file persisting the remote-abstract memo across runs (loaded if present, saved at end)")
    args = ap.parse_args()

    os.environ.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)
    import lib.tools as tools
    import lib.embedding as emb
    import lib.reranker as rr_mod
    from lib import speculative_rerank
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
    probe = Probe()

    remote_memo: dict = {}
    if args.remote_cache and Path(args.remote_cache).exists():
        for k, v in json.loads(Path(args.remote_cache).read_text()):
            remote_memo[tuple(k)] = v
    remote_stats = {"calls": 0, "memo_hits": 0, "preloaded_keys": len(remote_memo)}
    orig_remote = retriever._fetch_remote_abstracts

    def remote(ids):
        key = tuple(ids)
        if key in remote_memo:
            remote_stats["memo_hits"] += 1
            return dict(remote_memo[key])
        remote_stats["calls"] += 1
        out = orig_remote(ids)
        remote_memo[key] = dict(out)
        return out

    retriever._fetch_remote_abstracts = remote
    new_ce_impl = probe.ce_impl

    def old_ce_impl(ce, pairs):
        return ce.predict(pairs, show_progress_bar=False).tolist()

    base_emb = load_base_embedding(args.base)
    new_compute_similarity = emb.compute_similarity

    def serve(q):
        probe.reset()
        t0 = time.monotonic()
        fused = router.search(q, {}, top_k=fetch_k, force_source=SearchSource.LOCAL_RRF)
        captured = copy.deepcopy(fused)
        final = []
        if fused:
            tools._cache_works(fused)
            final = tools._maybe_rerank(fused, q, LIMIT)
        total = (time.monotonic() - t0) * 1000
        return {"fused": captured, "final": final, "total_ms": total, "ce_ms": probe.ce_ms,
                "emb_ms": probe.emb_ms, "ce_pairs": list(probe.ce_pairs), "ce_out": list(probe.ce_out),
                "emb_out": list(probe.emb_out)}

    def rerank_only(q, fused, old: bool):
        probe.reset()
        probe.ce_impl = old_ce_impl if old else new_ce_impl
        emb.compute_similarity = base_emb.compute_similarity if old else new_compute_similarity
        try:
            docs = copy.deepcopy(fused)
            t0 = time.perf_counter()
            final = tools._maybe_rerank(docs, q, LIMIT) if docs else []
            ms = (time.perf_counter() - t0) * 1000
        finally:
            probe.ce_impl = new_ce_impl
            emb.compute_similarity = new_compute_similarity
        return {"final": final, "ms": ms, "ce_ms": probe.ce_ms, "emb_ms": probe.emb_ms,
                "ce_pairs": list(probe.ce_pairs), "ce_out": list(probe.ce_out),
                "emb_out": list(probe.emb_out)}

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

    serve("effects of social media use on adolescent mental health")

    res = {"warm": [], "off": [], "on": []}
    for pass_name in ("warm", "off", "on"):
        if pass_name == "on":
            os.environ["SFU_SEARCH_SPECULATIVE_RERANK"] = "1"
            speculative_rerank.reset_for_test()
        else:
            os.environ.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)
        for i, q in enumerate(items):
            r = serve(q)
            if pass_name == "on":
                for _ in range(200):
                    if not speculative_rerank._job_busy:
                        break
                    time.sleep(0.01)
            res[pass_name].append(r)
            print(f"[{pass_name} {i+1}/{len(items)}] total={r['total_ms']:.0f} ms", flush=True)
    counters_on = speculative_rerank.counters()
    if args.remote_cache:
        Path(args.remote_cache).write_text(json.dumps([[list(k), v] for k, v in remote_memo.items()]))
    os.environ.pop("SFU_SEARCH_SPECULATIVE_RERANK", None)

    if args.pairs_out:
        with open(args.pairs_out, "w") as fh:
            for q, r in zip(items, res["off"]):
                for pq, pt in r["ce_pairs"]:
                    fh.write(json.dumps({"q": pq, "t": pt}) + "\n")

    per_topic = []
    old_runs, new_runs = [], []
    for q, off in zip(items, res["off"]):
        new_runs.append(rerank_only(q, off["fused"], old=False))
        old_runs.append(rerank_only(q, off["fused"], old=True))

    for i, q in enumerate(items):
        off, on, warm = res["off"][i], res["on"][i], res["warm"][i]
        new, old = new_runs[i], old_runs[i]
        fused_same = dump(off["fused"]) == dump(on["fused"])
        oid, nid = ids(old["final"]), ids(new["final"])
        ce = rr_mod._get_cross_encoder()
        pairs = new["ce_pairs"]
        ce_old_same = old_ce_impl(ce, pairs) if pairs else []
        ce_delta = max((abs(a - b) for a, b in zip(ce_old_same, new["ce_out"])), default=0.0)
        emb_delta = max((abs(a - b) for a, b in zip(old["emb_out"], new["emb_out"])), default=0.0)
        moved = [{"id": x, "old_rank": oid.index(x), "new_rank": nid.index(x) if x in nid else None}
                 for x in oid if x not in nid or nid.index(x) != oid.index(x)]
        stage1_old = [p[1] for p in old["ce_pairs"]]
        stage1_new = [p[1] for p in new["ce_pairs"]]
        per_topic.append({
            "query": q,
            "ii_vs_iii_byte_identical": dump(off["final"]) == dump(on["final"]),
            "fused_identical_off_on": fused_same,
            "warm_vs_off_final_identical": dump(warm["final"]) == dump(off["final"]),
            "new_rerank_reproduces_off": dump(new["final"]) == dump(off["final"]),
            "i_vs_ii_top10_order_identical": oid == nid,
            "i_vs_ii_top10_set_identical": set(oid) == set(nid),
            "i_vs_ii_stage1_top20_order_identical": stage1_old == stage1_new,
            "i_vs_ii_moved": moved,
            "max_abs_delta_ce": ce_delta,
            "max_abs_delta_stage1": emb_delta,
            "n_fused": len(off["fused"]), "n_final": len(off["final"]),
            "total_ms_off": round(off["total_ms"], 1), "total_ms_on": round(on["total_ms"], 1),
        })

    k = lambda name: [p[name] for p in per_topic]
    n = len(per_topic)
    out = {
        "what": "Fixed-shape scoring (stage-1 embedder + CE) and per-candidate speculative reuse "
                "(lever #1): 120-topic ranking parity, docs/SPECULATIVE_RETRIEVAL_UPGRADES.md §7 item 1.",
        "date": DATE,
        "script": "scripts/experiments/eval_fixed_shape_parity.py",
        "base_commit_arm_i": args.base,
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural", "n_topics": n,
        "config": {"features": feats, "fetch_k": fetch_k, "limit": LIMIT, "torch_device": device,
                   "torch_threads": threads, "load_s": round(load_s, 1),
                   "embedding_model_path": os.environ.get("SFU_EMBEDDING_MODEL_PATH"),
                   "fixed_shape": {"ce_seq_len": rr_mod._CE_SEQ_LEN, "ce_batch": rr_mod._CE_BATCH,
                                   "embed_seq_len": emb._FIXED_SEQ_LEN, "embed_batch": emb._EMBED_BATCH},
                   "force_source": "LOCAL_RRF",
                   "remote_abstract_memo": dict(remote_stats, note=(
                       "harness-only memo on retriever._fetch_remote_abstracts: the first pass "
                       "fetches (keyed OpenAlexClient, 900/day tracker), later passes reuse the "
                       "identical response so OFF/ON see the same abstracts and spend stays bounded")), "passes": "warm(off) -> off -> on, then OLD/NEW rerank-only on pass-off fused lists"},
        "bars": {
            "ii_vs_iii_byte_identical": f"{sum(k('ii_vs_iii_byte_identical'))}/{n}",
            "fused_identical_off_on": f"{sum(k('fused_identical_off_on'))}/{n}",
            "i_vs_ii_top10_order_identical": f"{sum(k('i_vs_ii_top10_order_identical'))}/{n}",
            "i_vs_ii_topics_with_any_top10_order_change": n - sum(k("i_vs_ii_top10_order_identical")),
            "i_vs_ii_top10_set_identical": f"{sum(k('i_vs_ii_top10_set_identical'))}/{n}",
            "i_vs_ii_stage1_top20_order_identical": f"{sum(k('i_vs_ii_stage1_top20_order_identical'))}/{n}",
            "max_abs_delta_ce": max(k("max_abs_delta_ce")),
            "max_abs_delta_stage1": max(k("max_abs_delta_stage1")),
        },
        "checks": {
            "warm_vs_off_final_identical": f"{sum(k('warm_vs_off_final_identical'))}/{n}",
            "new_rerank_on_captured_fused_reproduces_off": f"{sum(k('new_rerank_reproduces_off'))}/{n}",
        },
        "speculative_rerank_counters_pass_on": counters_on,
        "latency_ms": {
            "total_cache_miss_gate_off": summ([r["total_ms"] for r in res["off"]]),
            "total_cache_miss_gate_on": summ([r["total_ms"] for r in res["on"]]),
            "ce_stage_ms_gate_off": summ([r["ce_ms"] for r in res["off"]]),
            "ce_stage_ms_gate_on": summ([r["ce_ms"] for r in res["on"]]),
            "stage1_stage_ms_gate_off": summ([r["emb_ms"] for r in res["off"]]),
            "stage1_stage_ms_gate_on": summ([r["emb_ms"] for r in res["on"]]),
            "rerank_only_same_input": {
                "old_scoring": {"maybe_rerank": summ([r["ms"] for r in old_runs]),
                                "ce_stage": summ([r["ce_ms"] for r in old_runs]),
                                "stage1_stage": summ([r["emb_ms"] for r in old_runs])},
                "new_fixed_shape": {"maybe_rerank": summ([r["ms"] for r in new_runs]),
                                    "ce_stage": summ([r["ce_ms"] for r in new_runs]),
                                    "stage1_stage": summ([r["emb_ms"] for r in new_runs])},
            },
            "note": "one warm pass each; host idle except this run (2026-09-25 evening), not isolated",
        },
        "per_topic": per_topic,
    }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({x: out[x] for x in ("bars", "checks", "speculative_rerank_counters_pass_on", "latency_ms")},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
