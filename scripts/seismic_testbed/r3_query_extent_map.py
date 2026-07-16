#!/usr/bin/env python3
"""R3 instrument 5 (2026-07-16; doc 15 §2): per-query touched-EXTENT map for
the same 40 pre-encoded queries the driver runs, via the `search_visited`
pyo3 surface (`mmap_index.rs:330` — the F1 hot-set generator's surface, NO
Rust changes). Output data/eval_results/_r3_query_extent_map.json.

This is the query half of the (ledger × query-map) join: which 2 MiB extents
each of the 40 queries touches, per shard. Joined to the ledger's ADD/DEL
stream on (ino, pgoff→extent) and sliced by the driver's pass-boundary ns →
R3's deliverable (b): pass-3 residual-fault attribution per query, and the
§R3 expectation-1 verdict (12 GB's residual faults concentrated in extents
touched only by its slow-tail queries vs 16 GB's spread across the median).

Coord mapping (matches the F1 sidecar / Q12 provenance):
  search_visited returns u64 WORD offsets into forward_data.bin (dv) →
  byte = word*8 → page = byte//4096 → extent = page//(2MiB/4KiB)=page//512.
  f16 visited is component-index (not word-offset); see mmap_index.rs:1079's
  note — the served E8 v2 manifest is dv, so word-offset is correct here. The
  manifest's forward_format_version is recorded so the join catches a codec
  flip that would invalidate the mapping.

Read-only: uses the same `_load_manifest`/`_load_one_shard`/`_prepare_query`
helpers as the driver + Q12b; identical served shape (top_k=50, k'=100,
heap_factor=0.8, all-terms query_cut). Pre-encoded queries (e7b_encoded_*)
so no ORT/encoder is in the hot path — same cold-purity discipline as R2.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

MANIFEST = "data/eval_results/seismic_c25_shards_150m_mmap_e5_v2.json"
ENCODEED = "data/eval_results/e7b_encoded_queries.json"
OUT = "data/eval_results/_r3_query_extent_map.json"

PAGE = 4096
WORD = 8               # dv visited starts are u64 word offsets into forward_data.bin
EXTENT = 2 * 1024 * 1024   # 2 MiB — same as r3_cachestat_map for (pgoff→extent) join
PAGES_PER_EXTENT = EXTENT // PAGE   # 512


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--encoded", default=ENCODEED)
    ap.add_argument("--queries", type=int, default=40)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    from lib.thinclient.sharded_seismic_backend import (
        _load_manifest, _load_one_shard, _prepare_query)
    import seismic

    paths = _load_manifest(str(REPO / args.manifest), load_mode="mmap")
    shards = [_load_one_shard(seismic, p, "mmap") for p in paths]
    string_dtype = seismic.get_seismic_string()
    log(f"loaded {len(shards)} shards (mmap, E8 v2)")

    terms = json.loads((REPO / args.encoded).read_text())["terms"][:args.queries]
    log(f"{len(terms)} pre-encoded queries, top_k={args.top_k}")

    # per-shard manifest forward_data_words (to bound extents + cross-check)
    fwd_words = []
    for p in paths:
        man = json.loads((Path(p) if Path(p).is_absolute() else REPO / p)
                         .joinpath("manifest.json").read_text())
        fwd_words.append(man.get("forward_data_words", 0))

    # per-query, per-shard: set of touched extents (2 MiB buckets)
    per_query = []   # [{shard, n_extents, extents:[...]}] per query
    per_shard_extent_touches = [{} for _ in shards]   # extents touched >=1 query
    t0 = time.time()
    for qi, q in enumerate(terms):
        qcomp, qvals, qc, kp = _prepare_query(q, args.top_k, string_dtype,
                                                None, None)
        q_extents = []
        for si, idx in enumerate(shards):
            _res, visited = idx.search_visited(
                "q", qcomp, qvals, k=kp, query_cut=qc, heap_factor=0.8)
            v = np.asarray(visited, dtype=np.uint64)
            if v.size:
                pages = v * WORD // PAGE
                exts = np.unique(pages // PAGES_PER_EXTENT)
                q_extents.append({"shard": si,
                                  "n_extents": int(len(exts)),
                                  "extents": [int(x) for x in exts.tolist()]})
                for e in exts.tolist():
                    per_shard_extent_touches[si][e] = \
                        per_shard_extent_touches[si].get(e, 0) + 1
            else:
                q_extents.append({"shard": si, "n_extents": 0, "extents": []})
        per_query.append({"query": qi, "shards": q_extents,
                          "n_total_extents": sum(s["n_extents"]
                                                 for s in q_extents)})
        if qi % 10 == 0 or qi == len(terms) - 1:
            log(f"  q{qi:2d}/{len(terms)}: "
                f"{per_query[-1]['n_total_extents']} extents "
                f"({time.time()-t0:.1f}s)")

    # extent id (shard, extent) → list of queries touching it (the join key)
    extent_to_queries = {}
    for q in per_query:
        for s in q["shards"]:
            si = s["shard"]
            for e in s["extents"]:
                extent_to_queries.setdefault((si, e), []).append(q["query"])

    out = {
        "probe": "r3_query_extent_map", "date": time.strftime("%Y-%m-%d"),
        "manifest": args.manifest,
        "coord_system": "word_offsets(into forward_data.bin)*8//4096//(2MiB/4KiB)",
        "extent_bytes": EXTENT, "pages_per_extent": PAGES_PER_EXTENT,
        "served_shape": {"top_k": args.top_k, "k_prime": 100,
                         "heap_factor": 0.8, "query_cut": "all-terms"},
        "n_shards": len(shards),
        "forward_data_words_per_shard": fwd_words,
        "n_queries": len(per_query),
        "extents_per_query_mean": round(
            float(np.mean([q["n_total_extents"] for q in per_query])), 2),
        "extents_per_query_p50": float(
            np.median([q["n_total_extents"] for q in per_query])),
        "distinct_extents_touched": len(extent_to_queries),
        # extent → query list (the join's query half; DEL/ADD events map here)
        "extent_to_queries": {f"s{si}e{e}": ql
                              for (si, e), ql in sorted(extent_to_queries.items())},
        "per_query": per_query,
        "elapsed_s": round(time.time() - t0, 1),
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    log(f"wrote {args.out}: {len(extent_to_queries)} distinct extents across "
        f"{len(per_query)} queries; mean {out['extents_per_query_mean']} "
        f"extents/query ({out['elapsed_s']}s)")
    log(f"  extent touched by max {max(len(v) for v in extent_to_queries.values())} "
        f"queries, min 1; this is the join's concentration signal.")


if __name__ == "__main__":
    main()
