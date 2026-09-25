#!/usr/bin/env python3
"""Shared Stage-0 candidate gathering for the docs/archive/seismic_150m_testbed/12_EXECUTION_ROADMAP.md queue.

Runs the real engine (f16 mmap shard) top-k' search for n queries and resolves
each returned doc string to its forward-index row — the exact e6b lineage
(`e6b_fixedu8_quality.py`), factored out so Q1 (E8 proxy re-score) and Q2
(M7 pack-membership sim) share one candidate set per shard instead of paying
the 18.8M-row doc-mapping scan twice.

Caches the resolved candidate set as JSON per (shard, n) so the second caller
is instant. Cache lives in data/eval_results/_stage0_cache/ (small: qids +
rows + doc strings only).

Worst-case-shard rule (12 §2.1): callers run shards 1 and 2, never shard0-only.
Rule Zero: read-only over the shard dirs.
"""
import gc
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import (load_token_to_id, load_queries,  # noqa: E402
                                    SPLADE_QUERY_TERMS, K_PRIME, HEAP_FACTOR)

CACHE_DIR = REPO / "data/eval_results/_stage0_cache"
QUERY_FILE = REPO / "data/eval_results/diverse_queries.json"
MODEL_PATH = "models/splade_onnx_fp16"


def gather_candidates(mmap_dir: Path, n_queries: int) -> list[dict]:
    """Return per-query candidate sets on an f16 mmap shard.

    Each element: {"qids": sorted list[int] (shard token ids in the query),
                   "qw": {token_id: f32 weight}, "docs": [doc strings],
                   "rows": [forward rows, aligned with docs]}.
    """
    CACHE_DIR.mkdir(exist_ok=True)
    cache = CACHE_DIR / f"cands_{mmap_dir.name}_n{n_queries}_k{K_PRIME}.json"
    if cache.exists():
        per_q = json.loads(cache.read_text())
        for pq in per_q:
            pq["qw"] = {int(k): v for k, v in pq["qw"].items()}
        print(f"[stage0] cache hit: {cache.name} ({len(per_q)} queries)")
        return per_q

    from lib.opensearch_retriever import encode_splade  # torch first (ENOMEM lesson)
    import seismic

    idx = seismic.MmapSeismicIndex(str(mmap_dir))
    sd = seismic.get_seismic_string()
    tok2id = load_token_to_id(mmap_dir)
    queries = load_queries(n_queries, QUERY_FILE)
    assert len(queries) == n_queries, f"query pool exhausted at {len(queries)}"
    q64s = [dict(sorted(encode_splade(q, MODEL_PATH).items(),
                        key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]) for q in queries]

    per_q = []
    for q64 in q64s:
        known = {t: w for t, w in q64.items() if t in tok2id}
        qcomp = np.array(list(known.keys()), dtype=sd)
        qvals = np.array([float(v) for v in known.values()], dtype=np.float32)
        res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                         k=K_PRIME, query_cut=len(known), heap_factor=HEAP_FACTOR)
        per_q.append({"qids": sorted(int(tok2id[t]) for t in known),
                      "qw": {int(tok2id[t]): float(w) for t, w in known.items()},
                      "docs": [d for (_q, _s, d) in res]})
    del idx
    gc.collect()

    # Resolve doc strings -> forward rows (one linear pass over the mapping).
    targets = {d for pq in per_q for d in pq["docs"]}
    moffs = np.memmap(mmap_dir / "document_mapping_offsets.bin",
                      dtype=np.uint64, mode="r")
    blob = (mmap_dir / "document_mapping_strings.bin").read_bytes()
    mo = moffs.astype(np.int64)
    row_of = {}
    for i in range(len(mo) - 1):
        s = blob[mo[i]:mo[i + 1]].decode()
        if s in targets:
            row_of[s] = i
    assert len(row_of) == len(targets), "unresolved candidate doc ids"
    del blob
    gc.collect()

    for pq in per_q:
        pq["rows"] = [row_of[d] for d in pq["docs"]]
    cache.write_text(json.dumps(per_q))
    print(f"[stage0] gathered + cached: {cache.name} "
          f"({len(per_q)} queries, {len(targets)} unique docs)")
    return per_q


def open_forward(mmap_dir: Path):
    """f16 forward memmaps (offsets, components, values) — read-only."""
    offs = np.memmap(mmap_dir / "forward_offsets.bin", dtype=np.uint64, mode="r")
    comps = np.memmap(mmap_dir / "forward_components.bin", dtype=np.uint16, mode="r")
    vals = np.memmap(mmap_dir / "forward_values.bin", dtype=np.float16, mode="r")
    return offs, comps, vals
