#!/usr/bin/env python3
"""Capture the filter stage's real candidate lists once, for replay under a cap.

Doc `seismic_150m_testbed/18_ORDINAL_ADDRESSING_DESIGN.md` §14 "not settled" #5
asks what happens to the staged-SQLite filter stage (4.0 ms) as available page
cache shrinks, and whether ordinals' 1.5 ms holds while it degrades. Answering
that needs the filter stage measured ALONE under a memory cap: if the benchmark
process also holds the 42 GB of staged SEISMIC shards and the tantivy sections,
their working set competes for exactly the page cache under test and the cap
stops meaning anything.

So the candidate lists are captured ONCE here, from real `search()` calls
through the real retriever (§14's own method: "candidate lists captured once per
query from real `search()` calls and replayed identically to both arms"), and
the ladder in `eval_ordinals_cliff.py` replays them in a process that opens
nothing but `meta.sqlite` and the ordinal arrays.

`_post_filter` is wrapped, not reimplemented: the wrapper records the exact
`(ranked, filters)` the shipped SPLADE leg hands it and then calls through, so
what is captured is what production filters, including the over-fetch
(`OVERFETCH_FILTERED=10`, i.e. 500 candidates at `top_k=50`).

Writes a JSON that is the ladder's only input. Read-only against the index.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "source"))

DEFAULT_QUERIES = REPO / "data/sfu_eval_queries.json"
FILTERS = {"year_range": (2010, 2025), "type": "article"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=str(DEFAULT_QUERIES))
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--seed", type=int, default=20260925)
    ap.add_argument("--mode", default="splade")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.environ["SFU_DENSE_LEG"] = "0"
    os.environ["SFU_DENSE_WARMCACHE"] = "0"
    os.environ.pop("SFU_THINCLIENT_ORDINALS", None)

    from lib.thinclient.retriever import ThinClientRetriever

    r = ThinClientRetriever(index_root=str(REPO / "data/thinclient_index"),
                            remote_abstracts=False)
    if not r.is_available():
        raise SystemExit("thinclient index unavailable")
    if r._meta is None:
        raise SystemExit("no meta.sqlite loaded — nothing to filter against")

    captured: list[dict] = []
    original = r._post_filter

    def wrapper(ranked, f):
        kept = original(ranked, f)
        captured.append({"candidates": [d for d, _ in ranked],
                         "scores": [s for _, s in ranked],
                         "kept": [d for d, _ in kept]})
        return kept

    r._post_filter = wrapper

    raw = json.loads(Path(args.queries).read_text())
    qs = [q["query"] for q in raw if q.get("query")]
    random.Random(args.seed).shuffle(qs)
    qs = qs[:args.n]

    out = {"what": "filter-stage candidate lists captured from real search() calls",
           "date": "2026-09-25",
           "script": "scripts/experiments/eval_ordinals_cliff_capture.py",
           "index_root": str(REPO / "data/thinclient_index"),
           "mode": args.mode, "top_k": args.top_k, "filters": FILTERS,
           "overfetch_filtered": 10, "seed": args.seed,
           "meta_numeric": r._meta_numeric, "queries": []}

    for i, q in enumerate(qs):
        before = len(captured)
        t0 = time.perf_counter()
        r.search(q, top_k=args.top_k, mode=args.mode, filters=dict(FILTERS))
        ms = (time.perf_counter() - t0) * 1000
        calls = captured[before:]
        if not calls:
            print(f"[{i}] {q!r}: no _post_filter call — skipped", flush=True)
            continue
        merged: list[str] = []
        scores: list[float] = []
        kept: list[str] = []
        seen = set()
        for c in calls:
            for did, sc in zip(c["candidates"], c["scores"]):
                if did not in seen:
                    seen.add(did)
                    merged.append(did)
                    scores.append(sc)
            kept.extend(c["kept"])
        out["queries"].append({"query": q, "candidates": merged,
                               "scores": scores,
                               "kept_reference": kept,
                               "n_candidates": len(merged),
                               "search_ms": round(ms, 2)})
        print(f"[{i+1}/{len(qs)}] cand={len(merged)} kept={len(kept)} "
              f"search={ms:.0f}ms", flush=True)

    tot = sum(x["n_candidates"] for x in out["queries"])
    out["n_queries"] = len(out["queries"])
    out["total_candidates"] = tot
    Path(args.out).write_text(json.dumps(out, indent=1) + "\n")
    print(f"WROTE {args.out}: {out['n_queries']} queries, {tot} candidates",
          flush=True)


if __name__ == "__main__":
    main()
