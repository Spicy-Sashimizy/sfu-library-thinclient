#!/usr/bin/env python3
"""Attribute the served-search latency NOT covered by engine leg timings.

Gating measurement (b) of docs/SPECULATIVE_RETRIEVAL_UPGRADES.md, first cut
from the serve query-log already on disk (no new serving code, no new
instrumentation). For every `mode=federated` row that carries per-leg
timings, gap_ms = leg_ms.total - leg_ms.bm25f - leg_ms.splade (- dense when
present).

What the gap contains, by construction (src/lib/thinclient/retriever.py
`search()` records the leg ms BEFORE `_hydrate`; tools.py
`search_academic_structured` measures `total` around router.search +
`_maybe_rerank`): per-leg hydrate (meta rows + abstract sidecar + OpenAlex
remote fetch for misses), the router's RRF merge, stage-1 embedding scoring of
the pool, the cross-encoder pass, LambdaMART when on, and executor hand-off.

Rows excluded: result-cache hits (no legs run), rows without per-leg timings,
and the warm-up rows whose splade leg alone exceeds 10 s (first-contact
mmap faults, not a serving regime). Speculative rows are reported separately
because WI-18 fires them off the typing timeline.
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "data/eval_results/serve_query_log.jsonl"
OUT = ROOT / f"data/eval_results/speculation_gap_from_serve_log_{date.today().isoformat()}.json"
WARMUP_LEG_MS = 10_000.0


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    i = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return xs[i]


def summarize(xs: list[float]) -> dict:
    return {"n": len(xs), "p50_ms": round(pct(xs, 50), 1), "p95_ms": round(pct(xs, 95), 1),
            "mean_ms": round(st.fmean(xs), 1) if xs else None}


def main() -> int:
    rows = [json.loads(l) for l in LOG.open() if l.strip()]
    buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    excluded = {"cache_hit": 0, "no_leg_timings": 0, "warmup": 0}
    for r in rows:
        lm = r.get("leg_ms") or {}
        if r.get("cache_hit") is True:
            excluded["cache_hit"] += 1
            continue
        if "bm25f" not in lm or "splade" not in lm or "total" not in lm:
            excluded["no_leg_timings"] += 1
            continue
        if lm["splade"] > WARMUP_LEG_MS or lm["bm25f"] > WARMUP_LEG_MS:
            excluded["warmup"] += 1
            continue
        legs = lm["bm25f"] + lm["splade"] + lm.get("dense", 0.0)
        gap = lm["total"] - legs
        key = f"{r['ts'][:10]}|{'speculative' if r.get('speculative') else 'user'}"
        for k in (key, "ALL"):
            b = buckets[k]
            b["total_ms"].append(lm["total"])
            b["legs_ms"].append(legs)
            b["gap_ms"].append(gap)
            b["gap_share"].append(gap / lm["total"] if lm["total"] else 0.0)
    out = {"date": date.today().isoformat(), "source_log": str(LOG.relative_to(ROOT)),
           "rows_total": len(rows), "excluded": excluded,
           "gap_definition": "leg_ms.total - (bm25f + splade [+ dense]); see module docstring",
           "buckets": {}}
    for key in sorted(buckets):
        b = buckets[key]
        out["buckets"][key] = {
            "total": summarize(b["total_ms"]), "legs": summarize(b["legs_ms"]),
            "gap": summarize(b["gap_ms"]),
            "gap_share_p50": round(pct(b["gap_share"], 50), 3),
            "gap_share_mean": round(st.fmean(b["gap_share"]), 3) if b["gap_share"] else None,
        }
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))
    print("wrote", OUT.relative_to(ROOT), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
