#!/usr/bin/env python3
"""Quality gate re-run: FixedU8Q (global 1/64 fixed-point) vs SFR1 per-doc u8.

Same method as E6 phase C: real engine top-200 per query on shard0 mmap,
re-scored in Python under each value quantizer, overlap@10 of re-ranked lists.
Decides DotVByte-reuse vs SFR1-custom for the reader fork.
"""
import json
import statistics
import struct
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path("/workspaces/sfu-library-thinclient")
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts" / "seismic_testbed"))

from e6_forward_codec_proto import (load_token_to_id, load_queries,
                                    SPLADE_QUERY_TERMS, K_PRIME, HEAP_FACTOR,
                                    OVERLAP_K, TOP_K)

MMAP_DIR = REPO / "data/seismic_150m/index/plan01/global_shard0of8.mmap"

from lib.opensearch_retriever import encode_splade  # torch first (ENOMEM lesson)

import seismic
idx = seismic.MmapSeismicIndex(str(MMAP_DIR))
sd = seismic.get_seismic_string()

offs = np.memmap(MMAP_DIR / "forward_offsets.bin", dtype=np.uint64, mode="r")
comps = np.memmap(MMAP_DIR / "forward_components.bin", dtype=np.uint16, mode="r")
vals = np.memmap(MMAP_DIR / "forward_values.bin", dtype=np.float16, mode="r")

tok2id = load_token_to_id(MMAP_DIR)
queries = load_queries(40, REPO / "data/eval_results/diverse_queries.json")
q64s = [dict(sorted(encode_splade(q, "models/splade_onnx_fp16").items(),
                    key=lambda x: -x[1])[:SPLADE_QUERY_TERMS]) for q in queries]

per_q = []
for q64 in q64s:
    known = {t: w for t, w in q64.items() if t in tok2id}
    qcomp = np.array(list(known.keys()), dtype=sd)
    qvals = np.array([float(v) for v in known.values()], dtype=np.float32)
    res = idx.search(query_id="q", query_components=qcomp, query_values=qvals,
                     k=K_PRIME, query_cut=len(known), heap_factor=HEAP_FACTOR)
    per_q.append({"qids": np.array(sorted(tok2id[t] for t in known), dtype=np.int64),
                  "qw": {tok2id[t]: float(w) for t, w in known.items()},
                  "docs": [d for (_q, _s, d) in res]})

targets = {d for pq in per_q for d in pq["docs"]}
moffs = np.memmap(MMAP_DIR / "document_mapping_offsets.bin", dtype=np.uint64, mode="r")
blob = (MMAP_DIR / "document_mapping_strings.bin").read_bytes()
mo = moffs.astype(np.int64)
row_of = {}
for i in range(len(mo) - 1):
    s = blob[mo[i]:mo[i + 1]].decode()
    if s in targets:
        row_of[s] = i
assert len(row_of) == len(targets)
del blob


def dot(row, qids, qw, mode):
    s, e = int(offs[row]), int(offs[row + 1])
    c = np.asarray(comps[s:e], dtype=np.int64)
    v = np.asarray(vals[s:e], dtype=np.float32)
    if mode == "sfr1":
        vmax = np.float32(np.float16(v.max()))
        v = np.clip(np.round(v / vmax * 255.0), 0, 255).astype(np.float32) / 255.0 * vmax
    elif mode == "fixedu8":
        # FixedU8<U6>: round to nearest 1/64, saturate at 255/64 (=3.984)
        v = np.clip(np.round(v * 64.0), 0, 255).astype(np.float32) / 64.0
    m = np.searchsorted(c, qids)
    ok = (m < len(c)) & (c[np.minimum(m, len(c) - 1)] == qids)
    return float(sum(qw[int(q)] * v[mm] for q, mm in zip(qids[ok], m[ok])))


out = {}
for mode in ["sfr1", "fixedu8"]:
    ov10, ov50 = [], []
    for pq in per_q:
        rows = [row_of[d] for d in pq["docs"]]
        exact = [dot(r, pq["qids"], pq["qw"], "exact") for r in rows]
        quant = [dot(r, pq["qids"], pq["qw"], mode) for r in rows]
        br = [pq["docs"][i] for i in np.argsort(-np.array(exact), kind="stable")]
        qr = [pq["docs"][i] for i in np.argsort(-np.array(quant), kind="stable")]
        ov10.append(len(set(br[:OVERLAP_K]) & set(qr[:OVERLAP_K])) / OVERLAP_K)
        ov50.append(len(set(br[:TOP_K]) & set(qr[:TOP_K])) / TOP_K)
    out[mode] = {"overlap@10_mean": round(statistics.mean(ov10), 4),
                 "overlap@10_min": round(min(ov10), 4),
                 "overlap@50_mean": round(statistics.mean(ov50), 4),
                 "gate_pass_0.99": statistics.mean(ov10) >= 0.99}
    print(mode, out[mode])

print(json.dumps(out))
