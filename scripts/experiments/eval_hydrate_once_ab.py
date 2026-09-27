#!/usr/bin/env python3
"""Lever #0 (hydrate once per request) multi-pass A/B on the 120 topics.

docs/SPECULATIVE_RETRIEVAL_UPGRADES.md §4 row 0 / §6 step 3. Same replay as
scripts/experiments/eval_speculative_multipass_ab.py (live objects from
``lib.tools._get_federated_router()``, serving env/flags, CUDA):

    router.search(q, {}, top_k=_retrieval_top_k(10), force_source=LOCAL_RRF)
    tools._cache_works(fused); tools._maybe_rerank(fused, q, 10)

Arms (serving defaults are NOT changed; SFU_SEARCH_SPECULATIVE_RERANK is
unset in both arms, i.e. its default OFF):
  * OFF: the retriever INSTANCE's ``hydrate_scope`` is replaced by
    ``contextlib.nullcontext`` for the pass. The router enters
    ``getattr(retriever, "hydrate_scope", nullcontext)()``, so the instance
    attribute takes effect there; no memo is open, so each leg's ``_hydrate``
    goes the direct ``_meta_rows`` + ``fetch_abstracts`` path (pre-#0 code).
  * ON: current code (the instance attribute is deleted, class method used).

Pass order: one warm-up pass (ON, discarded), then OFF, ON, ON, OFF, OFF, ON
(ABBA-style, so a monotone host drift hits both arms alike), 3 passes/arm.
Every pass is a result-cache miss (this path never reads the result cache).

Instrumentation (instance attributes on the one retriever, harness-only):
  * ``_hydrate``: wall ms per call, summed per request = hydrate stage ms
    (both legs; meta rows + local abstract sidecars + remote stub + dict build).
  * ``_meta_rows`` / ``fetch_abstracts`` / ``_fetch_remote_abstracts``: calls
    and ids per request, counted only while inside ``_hydrate``.
  * duplicate-hydrate share: ids passed to ``fetch_abstracts`` that were
    already passed earlier in the same request / all ids passed.

Remote abstracts: the multi-pass A/B's memo file (keyed on id-list tuples)
is not on disk any more, and a list-keyed memo would give the two arms
different answers anyway (#0 changes WHICH id lists reach the remote call).
So the remote fetch is a per-id stub: ``--remote-cache`` (optional JSON
{openalex_id: abstract}) answers per id; ids not in it get no abstract.
No OpenAlex call is ever made. Both arms therefore see the same abstract for
the same id, and remote ids/calls are reported as counts, not wall time.

Counters: ``speculation.counters()`` (WI-18), ``result_cache.counters()`` and
``speculative_rerank.counters()`` are snapshotted before and after the run.

Run (under the shared latency lock):
  flock /tmp/sfu_latency_measure.lock .venv/bin/python3 \
      scripts/experiments/eval_hydrate_once_ab.py [--passes 3] [--limit-topics N]
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import statistics as st
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

TOPICS = REPO / "data/eval_results/dense_ablation_qrels_20260817.json"
DATE = "2026-09-27"
OUT = REPO / f"data/eval_results/hydrate_once_ab_{DATE}.json"
LIMIT = 10
EST_SAVING_MS = 7.0


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))]


def summ(xs, nd=2):
    return {"n": len(xs), "p50": round(pct(xs, 50), nd), "p95": round(pct(xs, 95), nd),
            "mean": round(st.fmean(xs), nd)}


def dump(docs):
    return json.dumps(docs, sort_keys=True, default=str)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--limit-topics", type=int, default=0)
    ap.add_argument("--remote-cache", default="")
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

    per_id: dict = {}
    if args.remote_cache and Path(args.remote_cache).exists():
        per_id = dict(json.loads(Path(args.remote_cache).read_text()))

    req = threading.local()

    def new_req():
        return {"hydrate_ms": 0.0, "hydrate_calls": 0, "meta_calls": 0, "meta_ids": 0,
                "abs_calls": 0, "abs_ids": 0, "abs_dup_ids": 0, "remote_calls": 0,
                "remote_ids": 0, "seen_abs": set(), "in_hydrate": 0}

    cur = {"r": new_req()}

    orig_hydrate = retriever._hydrate
    orig_meta = retriever._meta_rows
    orig_fetch = retriever.fetch_abstracts

    def hydrate(ranked, source):
        r = cur["r"]
        r["in_hydrate"] += 1
        t = time.perf_counter()
        try:
            return orig_hydrate(ranked, source)
        finally:
            r["hydrate_ms"] += (time.perf_counter() - t) * 1000
            r["hydrate_calls"] += 1
            r["in_hydrate"] -= 1

    def meta_rows(ids):
        r = cur["r"]
        if r["in_hydrate"]:
            r["meta_calls"] += 1
            r["meta_ids"] += len(ids)
        return orig_meta(ids)

    def fetch_abstracts(ids):
        r = cur["r"]
        if r["in_hydrate"]:
            r["abs_calls"] += 1
            r["abs_ids"] += len(ids)
            r["abs_dup_ids"] += sum(1 for i in ids if i in r["seen_abs"])
            r["seen_abs"].update(ids)
        return orig_fetch(ids)

    def remote(ids):
        r = cur["r"]
        r["remote_calls"] += 1
        r["remote_ids"] += len(ids)
        return {i: per_id[i] for i in ids if i in per_id}

    retriever._hydrate = hydrate
    retriever._meta_rows = meta_rows
    retriever.fetch_abstracts = fetch_abstracts
    retriever._fetch_remote_abstracts = remote

    def set_arm(arm):
        if arm == "off":
            retriever.hydrate_scope = contextlib.nullcontext
        else:
            retriever.__dict__.pop("hydrate_scope", None)

    orig_mr = tools._maybe_rerank

    def serve(q):
        cur["r"] = new_req()
        t0 = time.monotonic()
        fused = router.search(q, {}, top_k=fetch_k, force_source=SearchSource.LOCAL_RRF)
        t1 = time.monotonic()
        captured = dump(fused)
        final = []
        rr = 0.0
        if fused:
            tools._cache_works(fused)
            t2 = time.perf_counter()
            final = orig_mr(fused, q, LIMIT)
            rr = (time.perf_counter() - t2) * 1000
        total = (time.monotonic() - t0) * 1000
        r = cur["r"]
        r.pop("seen_abs")
        r.pop("in_hydrate")
        r.update({"fused": captured, "final": dump(final), "total_ms": total,
                  "retrieval_ms": (t1 - t0) * 1000, "rerank_ms": rr})
        return r

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
    n = len(items)

    wi18_before = speculation.counters()
    cache_before = result_cache.counters()
    spec_before = speculative_rerank.counters()

    abba = ["off", "on", "on", "off"]
    order = ["warmup"] + [abba[i % 4] for i in range(2 * args.passes)]
    passes = []
    for pi, arm in enumerate(order):
        set_arm("on" if arm == "warmup" else arm)
        rows = []
        for i, q in enumerate(items):
            r = serve(q)
            rows.append(r)
            print(f"[{pi}:{arm} {i+1}/{n}] total={r['total_ms']:.0f} "
                  f"hydrate={r['hydrate_ms']:.1f} abs_calls={r['abs_calls']} "
                  f"dup={r['abs_dup_ids']}", flush=True)
        passes.append({"arm": arm, "rows": rows})
    set_arm("on")

    wi18_after = speculation.counters()
    cache_after = result_cache.counters()
    spec_after = speculative_rerank.counters()
    measured = [p for p in passes if p["arm"] != "warmup"]
    ref = next(p for p in measured if p["arm"] == "off")["rows"]

    def counts(rows):
        tot = lambda k: sum(r[k] for r in rows)
        return {"requests": len(rows),
                "hydrate_calls_per_request": round(tot("hydrate_calls") / len(rows), 3),
                "meta_rows_calls_per_request": round(tot("meta_calls") / len(rows), 3),
                "fetch_abstracts_calls_per_request": round(tot("abs_calls") / len(rows), 3),
                "remote_calls_per_request": round(tot("remote_calls") / len(rows), 3),
                "meta_rows_ids_total": tot("meta_ids"),
                "fetch_abstracts_ids_total": tot("abs_ids"),
                "remote_ids_total": tot("remote_ids"),
                "duplicate_ids_total": tot("abs_dup_ids"),
                "duplicate_share": round(tot("abs_dup_ids") / max(1, tot("abs_ids")), 4),
                "requests_with_duplicate": sum(1 for r in rows if r["abs_dup_ids"])}

    def pass_summary(p):
        rows = p["rows"]
        return {"arm": p["arm"],
                "hydrate_ms": summ([r["hydrate_ms"] for r in rows]),
                "total_ms": summ([r["total_ms"] for r in rows], 1),
                "retrieval_ms": summ([r["retrieval_ms"] for r in rows], 1),
                "maybe_rerank_ms": summ([r["rerank_ms"] for r in rows], 1),
                "counts": counts(rows),
                "final_identical_to_first_off": f"{sum(r['final'] == f['final'] for r, f in zip(rows, ref))}/{n}",
                "fused_identical_to_first_off": f"{sum(r['fused'] == f['fused'] for r, f in zip(rows, ref))}/{n}"}

    summaries = [pass_summary(p) for p in passes]
    pooled = {}
    for arm in ("off", "on"):
        rows = [r for p in measured if p["arm"] == arm for r in p["rows"]]
        pooled[arm] = {"hydrate_ms": summ([r["hydrate_ms"] for r in rows]),
                       "total_ms": summ([r["total_ms"] for r in rows], 1),
                       "retrieval_ms": summ([r["retrieval_ms"] for r in rows], 1),
                       "maybe_rerank_ms": summ([r["rerank_ms"] for r in rows], 1),
                       "counts": counts(rows)}
    paired = {}
    for k in ("hydrate_ms", "total_ms"):
        med = {}
        for arm in ("off", "on"):
            arm_rows = [p["rows"] for p in measured if p["arm"] == arm]
            med[arm] = [st.median(rows[i][k] for rows in arm_rows) for i in range(n)]
        deltas = [a - b for a, b in zip(med["off"], med["on"])]
        paired[k] = {"per_topic_median_off_minus_on": summ(deltas, 3),
                     "topics_on_faster": sum(1 for d in deltas if d > 0)}

    off_dup = [r["abs_dup_ids"] for p in measured if p["arm"] == "off" for r in p["rows"]]
    parity_final = all(s["final_identical_to_first_off"] == f"{n}/{n}" for s in summaries if s["arm"] != "warmup")
    parity_fused = all(s["fused_identical_to_first_off"] == f"{n}/{n}" for s in summaries if s["arm"] != "warmup")
    d = lambda k, stat: round(pooled["off"][k][stat] - pooled["on"][k][stat], 2)
    out = {
        "what": "Lever #0 hydrate once per request (ThinClientRetriever.hydrate_scope memo, router "
                "LOCAL_RRF scope): multi-pass A/B scope bypassed (OFF) vs current code (ON), "
                "docs/SPECULATIVE_RETRIEVAL_UPGRADES.md §4 row 0 / §6 step 3.",
        "date": DATE,
        "script": "scripts/experiments/eval_hydrate_once_ab.py",
        "topics_file": str(TOPICS.relative_to(REPO)), "query_field": "natural", "n_topics": n,
        "pass_order": order,
        "config": {"features": feats, "fetch_k": fetch_k, "limit": LIMIT, "torch_device": device,
                   "torch_threads": threads, "load_s": round(load_s, 1),
                   "embedding_model_path": os.environ.get("SFU_EMBEDDING_MODEL_PATH"),
                   "speculative_rerank_gate": "unset (default OFF) in both arms",
                   "force_source": "LOCAL_RRF",
                   "remote_abstracts": {"mode": "per-id stub, 0 OpenAlex calls",
                                        "per_id_preloaded": len(per_id)},
                   "dense_cache_present": retriever._dense_cache is not None},
        "results": {
            "byte_parity_final_all_passes_vs_first_off": parity_final,
            "byte_parity_fused_all_passes_vs_first_off": parity_fused,
            "hydrate_ms_pooled_p50_drop": d("hydrate_ms", "p50"),
            "hydrate_ms_pooled_p95_drop": d("hydrate_ms", "p95"),
            "total_ms_pooled_p50_drop": d("total_ms", "p50"),
            "total_ms_pooled_p95_drop": d("total_ms", "p95"),
            "est_saving_ms_from_3b": EST_SAVING_MS,
            "off_duplicate_ids_per_request": summ(off_dup, 2),
            "wi18_counters_unchanged": wi18_before == wi18_after,
            "result_cache_counters_unchanged": cache_before == cache_after,
            "speculative_rerank_counters_unchanged": spec_before == spec_after,
            "counters_before_after": {"wi18": [wi18_before, wi18_after],
                                      "result_cache": [cache_before, cache_after],
                                      "speculative_rerank": [spec_before, spec_after]},
        },
        "paired": paired,
        "pooled": pooled,
        "passes": summaries,
        "note": "host: local WSL2 (31 GB, 16 cores), RTX 4070 Ti SUPER; run held "
                "/tmp/sfu_latency_measure.lock (no other index-loading job during the run); "
                "remote-abstract wall time is NOT in the hydrate figures (per-id stub), "
                "remote savings are the id/call counts",
    }
    Path(args.out).write_text(json.dumps(out, indent=1, default=str) + "\n")
    print(json.dumps({k: out[k] for k in ("results", "paired")}, indent=1, default=str))
    for s in summaries:
        print(s["arm"], s["hydrate_ms"]["p50"], s["total_ms"]["p50"], s["counts"]["duplicate_share"],
              s["final_identical_to_first_off"], s["fused_identical_to_first_off"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
