#!/usr/bin/env python3
"""E5 gates — reordered shard vs its unreordered twin, same layout, same
queries. Pre-registered in `13_E5_FORWARD_REORDER_DESIGN.md` §2.3:

  parity  — score sequences bit-equal per rank; doc-id SETS equal within
            every interior score-tie group (ScoredRange tie-breaks on
            range.start, which the permutation changes — tie groups may
            reorder internally; a group straddling the k' boundary may swap
            members, quality-neutral). hard_mismatches MUST be 0;
            tie_swaps are reported, not gated.
  pages   — reordered cold-pass majflt ≤ 0.60× baseline (sim said
            0.376-0.400; the bar leaves room for floor noise).
            KILL if > 0.85 (doc 09 E5 kill: <15% reduction).
  latency — reordered warm p50 ≤ 1.05× baseline.

Method mirrors `e7_dotvbyte_gates.py` exactly (release_pages mechanism-B
cold pass, majflt delta, SFU_SEISMIC_PREFLOOR footing, ≤100 queries, both
dirs in ONE process, reps alternate arm order — deterministic majflt is the
E7 precedent). Run AFTER `reorder_mmap_shard` produced the dst dir:

    SFU_SEISMIC_PREFLOOR=2 .venv/bin/python3 scripts/seismic_testbed/e5_shard_gates.py \
        --base-dir data/seismic_150m/index/plan01/global_shard1of8.dotvbyte.mmap \
        --e5-dir   data/seismic_150m/index/plan01/global_shard1of8.dotvbyte.e5.mmap \
        --queries 100
"""
import argparse
import json
import os
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "source"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import load_queries, read_rss  # noqa: E402
from e7_dotvbyte_gates import run_pass  # noqa: E402 (E7 conventions)


def fadvise_dontneed_dir(d: Path) -> int:
    """Evict a shard dir's CLEAN pages from the kernel page cache
    (`posix_fadvise(POSIX_FADV_DONTNEED)` per file). Must run AFTER
    `release_pages()` — mapped-resident pages are not evictable — and is
    required on top of it whenever the shard fits free RAM: madvise only
    drops mapping residency, so re-faults stay MINOR (page cache hits) and
    majflt reads 0 (measured 2026-07-09 on shard1 right after conversion
    streamed both twins through the cache). Returns bytes advised."""
    total = 0
    for f in sorted(os.listdir(d)):
        p = d / f
        fd = os.open(p, os.O_RDONLY)
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            total += os.path.getsize(p)
        finally:
            os.close(fd)
    return total


def run_cold_pass(idx, shard_dir, string_dtype, per_q_terms, label,
                  warm_repeats, k_prime, prefloor):
    """`e7_dotvbyte_gates.run_pass` with true page-cache eviction between
    release and prefault (release -> fadvise DONTNEED -> prefloor -> cold)."""
    released = idx.release_pages()
    assert released > 0, f"{label}: release_pages covered no ranges"
    evicted = fadvise_dontneed_dir(Path(shard_dir))
    assert evicted > 0, f"{label}: fadvise covered no bytes"
    # Delegate the rest (prefloor -> cold pass -> warm reps) to the E7 body;
    # its own release_pages() re-run is a cheap no-op on the now-cold mapping.
    cell, tops = run_pass(idx, string_dtype, per_q_terms, label,
                          warm_repeats, k_prime, prefloor)
    cell["fadvise_bytes"] = evicted
    return cell, tops

TOP_K_PRIME = 200
HEAP_FACTOR = 0.8
SPLADE_QUERY_TERMS = 64
REPS = 3


def tie_aware_compare(base: list[tuple[str, float]], e5: list[tuple[str, float]]):
    """Returns (hard_mismatches, tie_swaps) for one query's scored top-k'.

    Scores compared as exact f32 bit patterns; doc ids as sets within each
    maximal equal-score run. The group containing the last rank (the k'
    boundary) may swap members — counted as tie_swaps, never hard."""
    hard = swaps = 0
    if len(base) != len(e5):
        return max(len(base), len(e5)), 0
    bits = lambda x: struct.pack("<f", x)
    for (_, sa), (_, sb) in zip(base, e5):
        if bits(sa) != bits(sb):
            hard += 1
    if hard:
        return hard, 0
    boundary = bits(base[-1][1]) if base else None
    i = 0
    while i < len(base):
        j = i + 1
        while j < len(base) and bits(base[j][1]) == bits(base[i][1]):
            j += 1
        sa = {d for d, _ in base[i:j]}
        sb = {d for d, _ in e5[i:j]}
        if sa != sb:
            if bits(base[i][1]) == boundary:
                swaps += len(sa ^ sb) // 2
            else:
                hard += len(sa ^ sb) // 2
        elif base[i:j] != e5[i:j]:
            swaps += 1  # same set, different internal order
        i = j
    return hard, swaps


def scored_pass(idx, string_dtype, per_q_terms, k_prime):
    """One warm scoring pass returning per-query [(doc_id, score)] for parity."""
    out = []
    for terms in per_q_terms:
        qcomp = np.array(list(terms.keys()), dtype=string_dtype)
        qvals = np.array([float(v) for v in terms.values()], dtype=np.float32)
        res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                         k=k_prime, query_cut=len(terms), heap_factor=HEAP_FACTOR)
        out.append([(d, float(s)) for (_q, s, d) in res])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-dir", required=True)
    ap.add_argument("--e5-dir", required=True)
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--k-prime", type=int, default=TOP_K_PRIME)
    ap.add_argument("--model-path", default="models/splade_onnx_fp16")
    ap.add_argument("--query-workload",
                    default=str(REPO / "data/eval_results/diverse_queries.json"))
    ap.add_argument("--result-file", default=None)
    args = ap.parse_args()
    assert args.queries <= 100, "audit rule: <=100 queries"
    prefloor = int(os.environ.get("SFU_SEISMIC_PREFLOOR", "0") or 0)

    from lib.opensearch_retriever import encode_splade  # torch first (ENOMEM lesson)
    import seismic

    string_dtype = seismic.get_seismic_string()
    base = seismic.MmapSeismicIndex(args.base_dir)
    e5 = seismic.MmapSeismicIndex(args.e5_dir)
    assert base.forward_format == e5.forward_format, "layout mismatch"
    assert base.len == e5.len and base.nnz == e5.nnz, "cardinality drift"
    man = json.loads((Path(args.e5_dir) / "manifest.json").read_text())
    order_name = man.get("forward_reordered")
    assert order_name, "e5 dir carries no forward_reordered provenance"
    # Size conservation per DATA file (manifest.json legitimately grows by the
    # forward_reordered provenance key, so whole-dir totals differ).
    for f in os.listdir(args.base_dir):
        if f == "manifest.json":
            continue
        a = os.path.getsize(Path(args.base_dir) / f)
        b = os.path.getsize(Path(args.e5_dir) / f)
        assert a == b, f"byte-count drift in {f}: {a} vs {b} — a permutation must conserve size"

    queries = load_queries(args.queries, Path(args.query_workload))
    per_q_terms = []
    for q in queries:
        sparse = encode_splade(q, args.model_path)
        per_q_terms.append(dict(sorted(sparse.items(),
                                       key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]))
    print(f"[e5-gates] {len(queries)} queries encoded; layout "
          f"{base.forward_format}, order {order_name}", flush=True)

    # ---- parity (warm, before the timed cells so cache state is shared) ----
    base_scored = scored_pass(base, string_dtype, per_q_terms, args.k_prime)
    e5_scored = scored_pass(e5, string_dtype, per_q_terms, args.k_prime)
    hard_total = swap_total = 0
    for b, r in zip(base_scored, e5_scored):
        h, s = tie_aware_compare(b, r)
        hard_total += h
        swap_total += s
    print(f"[e5-gates] parity: hard_mismatches={hard_total} "
          f"tie_swaps={swap_total}", flush=True)

    # ---- timed cells: REPS reps, alternating arm order, true page eviction ----
    cells = {"base": [], "e5": []}
    arms = {"base": (base, args.base_dir), "e5": (e5, args.e5_dir)}
    for rep in range(REPS):
        order = ["base", "e5"] if rep % 2 == 0 else ["e5", "base"]
        for label in order:
            idx, shard_dir = arms[label]
            cell, _tops = run_cold_pass(idx, shard_dir, string_dtype, per_q_terms,
                                        f"{label}_rep{rep}", 5, args.k_prime,
                                        prefloor)
            cells[label].append(cell)
            print(f"[e5-gates] {label} rep{rep}: cold p50 "
                  f"{cell['cold_traverse_ms_p50']} ms, warm p50 "
                  f"{cell['warm_traverse_ms_p50']} ms, majflt "
                  f"{cell['majflt_cold_pass']}", flush=True)

    med = lambda arm, k: statistics.median(c[k] for c in cells[arm])
    base_majflt, e5_majflt = med("base", "majflt_cold_pass"), med("e5", "majflt_cold_pass")
    cache_confounded = base_majflt == 0 or e5_majflt == 0
    majflt_ratio = (e5_majflt / base_majflt) if not cache_confounded else None
    warm_ratio = med("e5", "warm_traverse_ms_p50") / med("base", "warm_traverse_ms_p50")
    cold_ratio = med("e5", "cold_traverse_ms_p50") / med("base", "cold_traverse_ms_p50")

    gates = {
        "parity": {"hard_mismatches": hard_total, "tie_swaps": swap_total,
                   "bar": "hard == 0", "pass": hard_total == 0},
        "pages": ({"majflt_cold_ratio": round(majflt_ratio, 4),
                   "majflt_base_p50": base_majflt, "majflt_e5_p50": e5_majflt,
                   "bar": "<= 0.60 (kill > 0.85)", "pass": majflt_ratio <= 0.60,
                   "kill": majflt_ratio > 0.85}
                  if not cache_confounded else
                  {"cache_confounded": True, "majflt_base_p50": base_majflt,
                   "majflt_e5_p50": e5_majflt,
                   "bar": "<= 0.60 — NOT A VERDICT: an arm read majflt 0 "
                          "(pages still cached; doc 08 honesty gate)",
                   "pass": False, "kill": False}),
        "latency": {"warm_p50_ratio": round(warm_ratio, 4), "bar": "<= 1.05",
                    "pass": warm_ratio <= 1.05},
    }
    verdict = ("E5_ALL_GATES_PASS" if all(g["pass"] for g in gates.values())
               else "E5_CACHE_CONFOUNDED" if cache_confounded else
               "E5_KILL" if gates["pages"].get("kill") else
               "E5_GATE_FAIL: " + ",".join(k for k, g in gates.items()
                                           if not g["pass"]))
    out = {
        "meta": {"purpose": "E5 reorder gates — 13_E5_FORWARD_REORDER_DESIGN.md §2.3",
                 "measured_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()),
                 "base_dir": args.base_dir, "e5_dir": args.e5_dir,
                 "order_name": order_name, "n_queries": len(queries),
                 "k_prime": args.k_prime, "heap_factor": HEAP_FACTOR,
                 "prefloor": prefloor, "reps": REPS,
                 "rss": read_rss()},
        "cells": cells,
        "ratios": {"majflt_cold": round(majflt_ratio, 4),
                   "cold_p50": round(cold_ratio, 4),
                   "warm_p50": round(warm_ratio, 4)},
        "gates": gates, "verdict": verdict,
    }
    result = Path(args.result_file) if args.result_file else \
        REPO / f"data/eval_results/e5_shard_gates_{time.strftime('%Y%m%d_%H%M')}.json"
    result.write_text(json.dumps(out, indent=2))
    print(json.dumps({"verdict": verdict, **out["ratios"]}, indent=2))
    print(f"result -> {result}")


if __name__ == "__main__":
    main()
