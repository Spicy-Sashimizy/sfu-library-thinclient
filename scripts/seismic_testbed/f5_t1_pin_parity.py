#!/usr/bin/env python3
"""Phase 5 T1 bit-identity with F3 pin ON — out-of-process (1 backend) to fit
the dev container's ~50 GB VmSize ceiling (3 backends × 2 shards × 3.85 GB
forward mmap + ONNX exceeds it). Runs ONCE: load ONE backend (2 shards,
parallel), search_encoded the 20 diverse queries, dump the oaid-order list.
Invoked twice (pin OFF baseline, then pin ON) and compared by the caller.

T1 is bit-identical BY CONSTRUCTION (the pin tier is residency-only: mlock +
MADV_DONTNEED; `_merge_topk`, scoring, record decode are untouched). This
script asserts it empirically anyway — the no-silent-breakage contract.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def main():
    from lib.thinclient.sharded_seismic_backend import (
        ParallelSeismicBackend, _load_manifest)
    tag = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    paths = _load_manifest(
        "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json",
        load_mode="mmap")[:2]
    b = ParallelSeismicBackend(paths, load_mode="mmap")
    qrecs = json.loads((REPO / "data" / "eval_results" /
                        "diverse_queries.json").read_text())
    queries = [r["paraphrase"] for r in qrecs][:20]
    results = []
    for qt in queries:
        q = b.encode_query(qt)
        r = b.search_encoded(q, top_k=50, k_prime=100) if q else []
        results.append([o for o, _ in r])
    out = {
        "tag": tag, "pin_budget_gb": os.environ.get("SFU_SEISMIC_PIN_BUDGET_GB"),
        "mlock_floor": os.environ.get("SFU_SEISMIC_MLOCK_FLOOR"),
        "hotset_pinned_gb": round(b._hotset_pinned_gb, 3),
        "floor_mlocked": b._floor_mlocked,
        "results_oaid_order": results,
    }
    out_path = REPO / "data" / "eval_results" / f"_t1_pin_{tag}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"T1 {tag}: pinned {b._hotset_pinned_gb:.3f}GB, "
          f"wrote {out_path}, q0 top={results[0][0] if results and results[0] else None}")


if __name__ == "__main__":
    main()
