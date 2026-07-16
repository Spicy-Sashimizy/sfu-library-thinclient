#!/usr/bin/env python3
"""WI-2 (deployprep 2026-07-16) — replay + summary of the serve query-log JSONL.

Proves the format the production query-log (`lib.serve_query_log`) emits feeds
the disk_streaming-research Q12-style skew analysis (the gate the LRU/pin tier
+ PILOT prefetch are blocked on). Reads one or more
`serve_query_log.jsonl` files and reports:

  - n_queries, n_distinct_query_hashes, n_distinct_result_fps
  - repeat-traffic: query_hash frequency distribution + the share of queries
    that are repeats of a prior query (the "real users repeat subjects" signal
    Q12's production-shape probe synthesized because no log existed)
  - result-fingerprint concentration: the hot-set-80/hot-set-50 — how many
    distinct result-sets cover 50%/80% of all answers (a small number ⟹ a
    small hot set covers most traffic ⟹ the LRU/pin win; the colibrì premise)
  - per-leg latency stats (p50/p95/mean for bm25f/splade/dense/total) — the
    encode-vs-traverse attribution that locates the next latency lever + the
    leg whose result-set dominates the hot pages
  - federation-mode mix (parallel/sequential/hybrid) — proves the field is
    captured for the sequential-vs-parallel A/B context

Usage:
    .venv/bin/python3 scripts/seismic_testbed/wi2_query_log_replay.py \\
        data/eval_results/serve_query_log.jsonl [--out summary.json]

The output JSON is the machine-readable summary; stdout is the human report.
"""
import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def percentile(data, p):
    if not data:
        return None
    s = sorted(data)
    return s[min(int(len(s) * p / 100), len(s) - 1)]


def load_entries(paths: list[str]) -> list[dict]:
    out = []
    for p in paths:
        with open(p) as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    out.append(json.loads(ln))
    return out


def hot_set_coverage(counter: Counter, frac: float) -> int:
    """Distinct keys needed to cover `frac` of total touches (smallest hot set)."""
    total = sum(counter.values())
    if total == 0:
        return 0
    target = frac * total
    acc = 0
    n = 0
    for _key, cnt in counter.most_common():
        acc += cnt
        n += 1
        if acc >= target:
            return n
    return n


def summarize(entries: list[dict]) -> dict:
    n = len(entries)
    qhashes = Counter(e.get("query_hash", "") for e in entries)
    rfps = Counter(e.get("result_fp", "") for e in entries)
    modes = Counter(e.get("mode", "") for e in entries)
    feds = Counter(e.get("federation", "") for e in entries)
    backends = Counter(e.get("backend", "") for e in entries)

    # repeat-traffic: a query_hash appearing >1 is a repeat subject
    repeat_hashes = sum(c - 1 for c in qhashes.values() if c > 1)
    repeat_frac = (repeat_hashes / n) if n else 0.0

    # per-leg latency
    leg_stats = {}
    for leg in ("bm25f", "splade", "dense", "rrf", "total"):
        vals = [e["leg_ms"][leg] for e in entries
                if e.get("leg_ms") and leg in e["leg_ms"]]
        if vals:
            leg_stats[leg] = {
                "p50_ms": round(percentile(vals, 50), 2),
                "p95_ms": round(percentile(vals, 95), 2),
                "mean_ms": round(statistics.mean(vals), 2),
                "n": len(vals),
            }

    return {
        "n_queries": n,
        "n_distinct_query_hashes": len(qhashes),
        "n_distinct_result_fps": len(rfps),
        "repeat_traffic": {
            "repeat_queries": repeat_hashes,
            "repeat_frac": round(repeat_frac, 4),
            "top5_query_hashes": [{"hash": h, "count": c}
                                  for h, c in qhashes.most_common(5)],
        },
        "result_fingerprint_concentration": {
            "hot_set_50_keys": hot_set_coverage(rfps, 0.50),
            "hot_set_80_keys": hot_set_coverage(rfps, 0.80),
            "hot_set_90_keys": hot_set_coverage(rfps, 0.90),
            "n_distinct": len(rfps),
            "top5_result_fps": [{"fp": f, "count": c}
                                 for f, c in rfps.most_common(5)
                                 if f],  # skip empty-fp (no results) rows
        },
        "mode_mix": dict(modes),
        "federation_mix": dict(feds),
        "backend_mix": dict(backends),
        "leg_latency_ms": leg_stats,
    }


def report(s: dict) -> str:
    lines = ["=== serve query-log summary ==="]
    lines.append(f"queries: {s['n_queries']}  "
                 f"distinct query_hashes: {s['n_distinct_query_hashes']}  "
                 f"distinct result_fps: {s['n_distinct_result_fps']}")
    rt = s["repeat_traffic"]
    lines.append(f"repeat-traffic: {rt['repeat_queries']} repeat queries "
                 f"({rt['repeat_frac']:.1%})  top hash appears "
                 f"{(rt['top5_query_hashes'][0]['count'] if rt['top5_query_hashes'] else 0)}×")
    rc = s["result_fingerprint_concentration"]
    lines.append(f"result-set concentration: hot-set-80 = {rc['hot_set_80_keys']} "
                 f"distinct answer sets cover 80% of traffic "
                 f"(of {rc['n_distinct']} distinct); hot-set-50 = "
                 f"{rc['hot_set_50_keys']}")
    lines.append(f"mode mix: {s['mode_mix']}  federation: {s['federation_mix']}  "
                 f"backend: {s['backend_mix']}")
    lines.append("per-leg latency (p50/p95/mean ms):")
    for leg, st in s["leg_latency_ms"].items():
        lines.append(f"  {leg:7s} {st['p50_ms']:.1f} / {st['p95_ms']:.1f} / "
                     f"{st['mean_ms']:.1f}  (n={st['n']})")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="serve_query_log.jsonl file(s)")
    ap.add_argument("--out", default=None, help="write summary JSON here")
    args = ap.parse_args()
    entries = load_entries(args.inputs)
    s = summarize(entries)
    print(report(s))
    if args.out:
        Path(args.out).write_text(json.dumps(s, indent=2))
        print(f"\nsummary written to {args.out}")
    # The skew gate (mirrors Q12/Q12b): a small hot-set-80 + nonzero repeat
    # ⟹ the colibrì premise transfers ⟹ LRU/pin viable; flag either way.
    rc = s["result_fingerprint_concentration"]
    rt = s["repeat_traffic"]
    if s["n_queries"] == 0:
        print("\n(empty log — nothing to analyze)")
        return 0
    verdict = ("SKEW PRESENT" if (rt["repeat_frac"] > 0 or rc["n_distinct"] < s["n_queries"])
               else "UNIFORM")
    print(f"\nskew verdict: {verdict} (repeat {rt['repeat_frac']:.1%}, "
          f"hot-set-80 {rc['hot_set_80_keys']} of {rc['n_distinct']} distinct)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
